"""pipeline.s_ingest fetches every input of the mission (orca, TAO, GEBCO, the GOFS 3.1 ocean store), resumable and hash-checked,
skips what is cached, never downloads under CAFE_OFFLINE, and records every input with its sha in the ledger.

The download path runs on the CI fixture against local servers: a Range server holding a GEBCO-format HDF5 file cut from the fixture's
bathymetry, the stand-in THREDDS tree of tests/test_tao.py, and an NCSS stand-in serving the fixture's ocean store.
"""
import http.server
import io
import json
import shutil
import threading
import urllib.parse

import numpy as np
import pytest

from cafe.pm import ledger, pipeline
from cafe.pm.env import bathy, hycom, ocean as ocean_mod, orca, remote, tao
from tests.conftest import Server
from tests import test_pipeline as tp
from tests.test_pipeline import MISSION_PATH, T0, T1, check_of, ctx_for, read_ledger, run_stage
from tests.test_tao import Tree

data, data_copy = tp.data, tp.data_copy                       # the CI tree fixtures of test_pipeline, under the same names
pytestmark = pytest.mark.usefixtures("data")

CMD = f"python -m cafe.pm fetch --mission {MISSION_PATH}"
BOX = (-2.0, 2.0, -167.0, -163.0)                              # (south, north, west, east): the mission box plus its 0.5 degree pad


def never(name):
    def f(*a, **k):
        raise AssertionError(f"{name} must not be called")
    return f


def forbid_downloads(monkeypatch):
    monkeypatch.setattr(orca, "ingest", never("orca.ingest"))
    monkeypatch.setattr(tao, "fetch_tao", never("tao.fetch_tao"))
    monkeypatch.setattr(bathy, "fetch_gebco", never("bathy.fetch_gebco"))
    monkeypatch.setattr(hycom, "fetch_gofs", never("hycom.fetch_gofs"))


# ----------------------------------------------------------------------------------------------------------------- cached and offline

def test_everything_cached_means_nothing_is_fetched_and_every_input_is_recorded_with_its_sha(tmp_path, data, monkeypatch):
    forbid_downloads(monkeypatch)
    monkeypatch.delenv("CAFE_OFFLINE")                                                  # online, yet nothing is asked for
    ctx = ctx_for(tmp_path / "r")
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    for name in ("orca", "tao", "gebco", "ocean_store"):
        assert check_of(d, f"{name}_present")["ok"]
    by = {pathlib_name(i["ref"]): i for i in d["inputs"]}
    store = data.ocean_store
    assert by[store.name]["sha256"] == hycom.open_store(store).attrs["manifest_sha256"] and by[store.name]["kind"].startswith("ocean store")
    gebco = bathy.cache_path(BOX, data.data / "bathy")
    assert by[gebco.name]["sha256"] == remote.sha256(gebco)
    assert by["manifest.json"]["sha256"]                                               # the orca cache manifest, then TAO's below
    assert any(i["ref"].endswith("tao/manifest.json") and i["sha256"] for i in d["inputs"])
    assert all(i["sha256"] or i["ref"].startswith("https://") for i in d["inputs"])    # only the remote orca base has no hash


def pathlib_name(ref):
    return ref.rstrip("/").split("/")[-1]


@pytest.mark.parametrize("what,name", [("bathy", "gebco"), ("tao", "tao"), ("ocean", "ocean_store")])
def test_offline_missing_data_fails_the_check_with_the_exact_command_and_downloads_nothing(tmp_path, data_copy, monkeypatch, what, name):
    forbid_downloads(monkeypatch)
    shutil.rmtree(data_copy / what)
    with pytest.raises(ledger.StageFailed, match=f"{name}_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    c = check_of(read_ledger(tmp_path / "r", "ingest"), f"{name}_present")
    assert not c["ok"] and "CAFE_OFFLINE" in c["note"] and f"`{CMD}`" in c["note"]


def test_offline_missing_orca_fails_before_anything_else_is_read(tmp_path, data_copy, monkeypatch):
    forbid_downloads(monkeypatch)
    (data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json").unlink()
    with pytest.raises(ledger.StageFailed, match="orca_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    d = read_ledger(tmp_path / "r", "ingest")
    assert not check_of(d, "orca_present")["ok"] and CMD in check_of(d, "orca_present")["note"] and d["inputs"] == []


def test_every_missing_input_is_reported_at_once(tmp_path, data_copy, monkeypatch):
    forbid_downloads(monkeypatch)
    for sub in ("ocean", "tao", "bathy"):
        shutil.rmtree(data_copy / sub)
    with pytest.raises(ledger.StageFailed):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    d = read_ledger(tmp_path / "r", "ingest")
    assert sorted(c["name"] for c in d["checks"] if not c["ok"]) == ["gebco_present", "ocean_store_present", "tao_present"]


def test_the_ocean_context_never_downloads_bathymetry_when_offline_and_does_when_online(tmp_path, data_copy, monkeypatch):
    seen = []
    monkeypatch.setattr(ocean_mod, "open_ocean", lambda *a, **k: seen.append(k["fetch_bathy"]))
    ctx = ctx_for(tmp_path / "r")
    pipeline.ocean(ctx)
    monkeypatch.delenv("CAFE_OFFLINE")
    pipeline.ocean(ctx)
    monkeypatch.setenv("CAFE_OFFLINE", "0")
    pipeline.ocean(ctx)
    assert seen == [False, True, True]


# ----------------------------------------------------------------------------------------------------------------- what counts as cached

def test_an_ocean_store_is_cached_only_if_it_has_every_step_spans_the_box_and_matches_its_parts_manifest(data, tmp_path):
    steps = hycom.gofs_steps(T0, T1)
    store = data.ocean_store
    assert pipeline._ocean_cached(store, BOX, steps)
    assert not pipeline._ocean_cached(tmp_path / "none.zarr", BOX, steps)
    assert not pipeline._ocean_cached(store, BOX, np.append(steps, steps[-1] + 3 * 3600.0))             # one step more than the store has
    assert not pipeline._ocean_cached(store, (-4.0, 2.0, -167.0, -163.0), steps)                        # south of the store
    assert not pipeline._ocean_cached(store, (-2.0, 4.0, -167.0, -163.0), steps)                        # north
    assert not pipeline._ocean_cached(store, (-2.0, 2.0, -169.0, -163.0), steps)                        # west
    assert not pipeline._ocean_cached(store, (-2.0, 2.0, -167.0, -161.0), steps)                        # east
    parts = tmp_path / "w" / "gofs_x.parts"
    parts.mkdir(parents=True)
    copy = tmp_path / "w" / "gofs_x.zarr"
    shutil.copytree(store, copy)
    (parts / "manifest.json").write_text('{"parts": {}}')                                               # the parts the store was not made from
    assert not pipeline._ocean_cached(copy, BOX, steps)
    attrs = hycom.open_store(copy).attrs
    (parts / "manifest.json").write_text("x")                                                           # and one whose hash it does record
    z = json.loads((copy / "zarr.json").read_text())
    z["attributes"]["manifest_sha256"] = remote.sha256(parts / "manifest.json")
    (copy / "zarr.json").write_text(json.dumps(z))
    assert attrs["manifest_sha256"] != hycom.open_store(copy).attrs["manifest_sha256"] and pipeline._ocean_cached(copy, BOX, steps)


def test_a_tao_download_is_cached_only_if_it_covers_the_box_and_window_and_every_file_hashes(data_copy):
    t = data_copy / "tao"
    s, e = T0 + 1, T1 - 1
    assert pipeline._tao_cached(t, BOX, s, e)
    assert not pipeline._tao_cached(t, BOX, T0 - 7200.0, e) and not pipeline._tao_cached(t, BOX, s, T1 + 7200.0)         # window
    for box in ((-3.0, 2.0, -167.0, -163.0), (-2.0, 3.0, -167.0, -163.0), (-2.0, 2.0, -168.0, -163.0), (-2.0, 2.0, -167.0, -162.0)):
        assert not pipeline._tao_cached(t, box, s, e)
    assert not pipeline._tao_cached(data_copy / "nowhere", BOX, s, e)
    victim = next(t.glob("T0N165W/*.nc"))
    victim.write_bytes(victim.read_bytes()[:-1] + b"\0")
    assert not pipeline._tao_cached(t, BOX, s, e)                                                          # a changed file


def test_a_gebco_cut_is_cached_only_if_it_loads_and_still_has_its_raster_hash(data_copy):
    p = bathy.cache_path(BOX, data_copy / "bathy")
    assert pipeline._gebco_cached(p)
    assert not pipeline._gebco_cached(data_copy / "bathy" / "missing.npz")
    z = dict(np.load(p))
    z["elevation"] = z["elevation"] + 1
    np.savez_compressed(p, **z)
    assert not pipeline._gebco_cached(p)                                                                   # hash differs
    p.write_bytes(b"not an npz")
    assert not pipeline._gebco_cached(p)


# ----------------------------------------------------------------------------------------------------------------- a failed download is a failed check

@pytest.mark.parametrize("exc", [hycom.FetchError("3 of 39 parts failed"), ConnectionError("stalled"), ValueError("bad"), LookupError("none")])
def test_a_failed_download_is_a_failed_check_with_the_error_and_the_resume_command(tmp_path, data_copy, monkeypatch, exc):
    monkeypatch.delenv("CAFE_OFFLINE")
    shutil.rmtree(data_copy / "ocean")

    def fail(*a, **k):
        raise exc
    monkeypatch.setattr(hycom, "fetch_gofs", fail)
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    c = check_of(read_ledger(tmp_path / "r", "ingest"), "ocean_store_present")
    assert not c["ok"] and type(exc).__name__ in c["note"] and str(exc) in c["note"] and f"rerun `{CMD}`" in c["note"]


def test_the_labs_hycom_cannot_be_downloaded_and_the_check_names_how_to_make_it(tmp_path, data_copy, monkeypatch):
    mission = tmp_path / "lab.yaml"
    mission.write_text(MISSION_PATH.read_text().replace("ocean: {source: gofs31}", "ocean: {source: lab_hycom, path: /nonexistent/lab.zarr}"))
    for offline in (True, False):
        (monkeypatch.setenv if offline else monkeypatch.delenv)(*(("CAFE_OFFLINE", "1") if offline else ("CAFE_OFFLINE",)))
        with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
            run_stage(pipeline.s_ingest, ctx_for(tmp_path / f"r{offline}", mission=mission), "ingest")
        note = check_of(read_ledger(tmp_path / f"r{offline}", "ingest"), "ocean_store_present")["note"]
        assert "ingest_lab_hycom" in note and ("lab's HYCOM, which this pipeline cannot download" in note or offline)


# ----------------------------------------------------------------------------------------------------------------- the download path, over HTTP

class Ncss:
    """NCSS stand-in over the fixture's ocean store: /ncss/<dataset>/<year>?var=..&time_start=..&time_end=..&north=.. -> NetCDF."""

    def __init__(self, store):
        ds = hycom.open_store(store).load()
        self.ds = ds.assign_coords(time=ds.time.values.astype("datetime64[s]").astype("datetime64[ns]"))
        self.log = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                outer.log.append((u.path.split("/")[-2], q))
                body = outer.cut(q)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/ncss"

    def cut(self, q):
        t = lambda k: np.datetime64(q[k][0].rstrip("Z"))
        f = lambda k: float(q[k][0])
        a = self.ds[list(q["var"])].sel(time=slice(t("time_start"), t("time_end")), lat=slice(f("south") - 1e-3, f("north") + 1e-3),
                                        lon=slice(f("west") - 1e-3, f("east") + 1e-3))
        out = io.BytesIO()
        a.to_netcdf(out)
        return out.getvalue()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def write_gebco_file(path, npz):
    """A GEBCO-format file (HDF5, longitudes -180..180, contiguous int16 elevation) holding the fixture's bathymetry."""
    import h5py
    z = np.load(npz)
    with h5py.File(path, "w") as f:
        f["lon"], f["lat"] = (z["lon"] + 180.0) % 360.0 - 180.0, z["lat"]
        f.create_dataset("elevation", data=z["elevation"])
        f.attrs["title"], f.attrs["id"] = b"GEBCO stand-in cut from the ci_env bathymetry", b"DOI: 10.0/ci"


@pytest.fixture
def network(data, data_copy, tmp_path, monkeypatch):
    """The CI tree with its ocean store, TAO files and GEBCO cut removed, and local servers standing in for GOFS, THREDDS and CEDA."""
    gebco_src = bathy.cache_path(BOX, data.data / "bathy")
    for sub in ("ocean", "tao", "bathy"):
        shutil.rmtree(data_copy / sub)
    www = tmp_path / "www"
    www.mkdir()
    write_gebco_file(www / "gebco.nc", gebco_src)
    server = Server(www)
    tree = Tree(server, tmp_path)
    for var in ("WIND", "SST", "AIRT", "RH"):
        tree.add("T0N165W", "DM200A-20230201", "D", var, 5)
    for var in ("WIND", "SST"):
        tree.add("T2S165W", "DM200A-20230201", "D", var, 5)
    ncss = Ncss(data.ocean_store)
    monkeypatch.delenv("CAFE_OFFLINE")
    monkeypatch.setattr(bathy, "GEBCO_URL", server.url("gebco.nc"))
    monkeypatch.setattr(tao, "BASE", tree.publish())
    monkeypatch.setattr(hycom, "NCSS", ncss.base)
    monkeypatch.setattr(hycom, "DODS", "/nonexistent")
    monkeypatch.setattr(orca, "ingest", never("orca.ingest"))                                  # the orca cache stays (test_orca covers its download)
    yield dict(server=server, ncss=ncss, gebco_src=gebco_src, root=data_copy)
    ncss.close()
    server.close()


def test_a_fresh_ingest_downloads_gofs_tao_and_gebco_then_a_second_one_downloads_nothing(tmp_path, network, data):
    srv, ncss, root = network["server"], network["ncss"], network["root"]
    ctx = ctx_for(tmp_path / "r")
    d = run_stage(pipeline.s_ingest, ctx, "ingest")
    assert all(check_of(d, f"{n}_present")["ok"] for n in ("orca", "tao", "gebco", "ocean_store"))
    # GOFS: one step per request, three datasets, 13 three-hourly steps over the 36 h window; the store matches the fixture where they overlap
    steps = hycom.gofs_steps(T0, T1)
    assert len(ncss.log) == 3 * len(steps) and {q["var"][0] for _, q in ncss.log} >= {"water_temp", "water_u", "surf_el"}
    got, want = hycom.open_store(data.ocean_store).load(), hycom.open_store(root / "ocean" / "gofs_ci_fixture.zarr").load()
    assert np.array_equal(want.time.values, steps) and want.lat.values.min() >= -2.0 - 1e-6 and want.lat.values.max() <= 2.0 + 1e-6
    ref = got.sel(time=want.time, lat=want.lat, lon=want.lon)
    for v in ("water_temp", "salinity", "water_u", "water_v", "rho", "c", "surf_el"):
        assert np.array_equal(np.isnan(want[v].values), np.isnan(ref[v].values)) and np.nanmax(np.abs(want[v].values - ref[v].values)) < 1e-4, v
    parts = root / "ocean" / "gofs_ci_fixture.parts" / "manifest.json"
    assert want.attrs["manifest_sha256"] == remote.sha256(parts)
    store_in = next(i for i in d["inputs"] if i["ref"].endswith("gofs_ci_fixture.zarr"))
    assert store_in["sha256"] == remote.sha256(parts)
    # GEBCO: only the box was read, and the depth at a node is the fixture's
    g = bathy.cache_path(BOX, root / "bathy")
    z = np.load(g)
    assert z["lon"].min() >= 193.0 - 0.01 and z["lon"].max() <= 197.0 + 0.01 and any(r for _, r in srv.log if r)
    assert bathy.from_gebco(g)(195.0, 0.0).value == pytest.approx(bathy.from_gebco(network["gebco_src"])(195.0, 0.0).value)
    assert next(i for i in d["inputs"] if i["ref"] == str(g))["sha256"] == remote.sha256(g)
    # TAO: the files of the two moorings, hashed in the manifest
    man = json.loads((root / "tao" / "manifest.json").read_text())
    assert set(man["selected"]) == {"T0N165W", "T2S165W"} and tao.verify(root / "tao") == len(man["files"]) == 6
    assert any(i["ref"].endswith("tao/manifest.json") and i["sha256"] for i in d["inputs"])
    assert check_of(d, "tao_moorings_compared")["ok"]
    # the second ingest finds everything cached and good: not one more request
    n_ncss, n_srv = len(ncss.log), len(srv.log)
    run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r2"), "ingest")
    assert len(ncss.log) == n_ncss and len(srv.log) == n_srv
