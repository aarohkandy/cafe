"""pipeline.s_ingest fetches every input of the mission (orca, TAO, GEBCO, the GOFS 3.1 ocean store), resumable and hash-checked,
skips what is cached, never downloads under CAFE_OFFLINE, and records every input with its sha in the ledger.

The download path runs on the CI fixture against local servers: a Range server holding a GEBCO-format HDF5 file cut from the fixture's
bathymetry, the stand-in THREDDS tree of tests/test_tao.py, and an NCSS stand-in serving the fixture's ocean store.
"""
import http.server
import io
import json
import pathlib
import shutil
import threading
import urllib.parse

import numpy as np
import pytest

from cafe.pm import audit, ledger, pipeline
from cafe.pm.env import bathy, hycom, ocean as ocean_mod, orca, remote, surface, tao
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
    assert by["orca_manifest.json"]["sha256"] and by["orca_manifest.json"]["shared"] == str(data.data / "cache" / "ci_fixture" / "orca" / "manifest.json")
    assert any(i["shared"].endswith(f"tao/s{tao.SELECTION}/manifest.json") and i["sha256"] for i in d["inputs"] if i.get("shared"))      # TAO's copy
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


def test_l0_offline_with_only_a_cache_of_an_older_selection_rule_fails_the_check_and_says_which_cache_stays(tmp_path, data_copy, monkeypatch):
    """A cache of rounds 1-9 (`tao/manifest.json`, no `selection`) cannot be used offline: the new rule picks files from the catalog. The check says so and
    names the cache that stays, instead of the bare 'not cached'."""
    forbid_downloads(monkeypatch)
    shutil.rmtree(tao.cache_dir(data_copy))
    legacy = data_copy / "tao" / "manifest.json"
    legacy.parent.mkdir(exist_ok=True)
    legacy.write_text(json.dumps(dict(box=[-2.0, 2.0, 193.0, 197.0], t0=0.0, t1=1.0, files={}, selected={})))
    with pytest.raises(ledger.StageFailed, match="tao_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    note = check_of(read_ledger(tmp_path / "r", "ingest"), "tao_present")["note"]
    assert "CAFE_OFFLINE" in note and f"`{CMD}`" in note and f"{data_copy / 'tao'} was selected by an older rule" in note
    assert legacy.is_file()


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


@pytest.mark.parametrize("name, window, advice", [("mystore.zarr", False, "delete .*mystore.zarr.* fetch --mission"),
                                                  ("gofs_lab.zarr", True, "restore .*gofs_lab.zarr.* the pipeline cannot download it")])
def test_l0_a_damaged_ocean_store_gets_the_advice_of_the_missions_source_not_of_its_file_name(data, tmp_path, name, window, advice):
    """Round 9, M-33 sibling: `_ocean_cached` opened the store without the mission's source, so a gofs31 store at a custom .zarr path was called the lab's
    ('the pipeline cannot download it') and a lab store that happened to start with 'gofs' was called fetchable."""
    store = tmp_path / name
    shutil.copytree(data.ocean_store, store)
    (store / "zarr.json").write_text("{trunc")
    steps = hycom.gofs_steps(T0, T1)
    with pytest.raises(pipeline.ConfigError, match=advice):
        pipeline._ocean_cached(store, BOX, steps, (steps[0], steps[-1]) if window else None)
    assert ocean_mod.is_lab(dict(source="lab_hycom")) is True and ocean_mod.is_lab(dict(source="gofs31")) is False and ocean_mod.is_lab({}) is False


def test_a_tao_download_is_cached_only_if_it_covers_the_box_and_window_and_every_file_hashes(data_copy):
    t = tao.cache_dir(data_copy)
    s, e = T0 + 1, T1 - 1
    assert pipeline._tao_cached(t, BOX, s, e)
    assert not pipeline._tao_cached(t, BOX, T0 - 7200.0, e) and not pipeline._tao_cached(t, BOX, s, T1 + 7200.0)         # window
    for box in ((-3.0, 2.0, -167.0, -163.0), (-2.0, 3.0, -167.0, -163.0), (-2.0, 2.0, -168.0, -163.0), (-2.0, 2.0, -167.0, -162.0)):
        assert not pipeline._tao_cached(t, box, s, e)
    assert not pipeline._tao_cached(data_copy / "nowhere", BOX, s, e)
    victim = min(t.glob("T0N165W/*.nc"))                                           # not next(): the first of the listing is the file system's choice
    was = victim.read_bytes()
    victim.write_bytes(was[:-1] + bytes([was[-1] ^ 0xFF]))                         # flipped: the file always changes (a constant may be the byte it has)
    assert victim.read_bytes() != was
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
        assert "cafe.pm ingest-ocean" in note and ("lab's HYCOM, which this pipeline cannot download" in note or offline)


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


def test_l0_fetching_under_a_new_tao_selection_rule_leaves_the_manifest_an_earlier_run_hashed_as_it_was(tmp_path, network):
    """Review round 10: the cache directory was shared by every selection rule, so the first run of a new rule rewrote the `tao/manifest.json` that earlier
    runs' ledgers hash, and their audit failed ('input ... changed since the stage ran'). The rule has its own directory (`tao.cache_dir`)."""
    root = network["root"]
    legacy = root / "tao" / "manifest.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps(dict(source="rounds 1-9", box=[-2.0, 2.0, 193.0, 197.0], t0=0.0, t1=1.0, files={}, selected={})))
    was = legacy.read_bytes()
    d = run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r"), "ingest")
    assert check_of(d, "tao_present")["ok"] and legacy.read_bytes() == was
    new = tao.cache_dir(root) / "manifest.json"
    assert json.loads(new.read_text())["selection"] == tao.SELECTION and new.parent == root / "tao" / f"s{tao.SELECTION}"
    assert any(i.get("shared") == str(new) for i in d["inputs"]) and not any(str(legacy) in (i["ref"], i.get("shared")) for i in d["inputs"])


def ingest_problems(run):
    """What the audit says about the ingest stage of a run directory that holds only that stage (the others have no ledger)."""
    return [x for x in audit.ledger_problems(run) if "stage ingest:" in x]


def test_p32_a_grown_orca_cache_leaves_the_audit_of_an_earlier_run_clean_and_a_changed_part_does_not(tmp_path, data_copy, monkeypatch):
    """P-32: the ledger hashed the one shared `orca/manifest.json`, which `orca.assemble` rewrites whenever a later run needs more hours; the audit of every
    earlier run then said 'input ... changed'. The run keeps the copy it used (ingest/orca_manifest.json); the audit asks the cache for the parts it names."""
    forbid_downloads(monkeypatch)
    cache = data_copy / "cache" / "ci_fixture" / "orca"
    man = cache / "manifest.json"
    run = tmp_path / "r"
    d = run_stage(pipeline.s_ingest, ctx_for(run), "ingest")
    snap = run / "ingest" / "orca_manifest.json"
    assert snap.read_bytes() == man.read_bytes() and not list((run / "ingest").glob("*.part"))
    ins = [i for i in d["inputs"] if i.get("shared") == str(man)]
    assert [i["ref"] for i in ins] == [str(snap)] and ins[0]["sha256"] == remote.sha256(snap) and str(man) not in [i["ref"] for i in d["inputs"]]
    outs = [o["path"] for o in d["outputs"]]
    assert str(snap) in outs and str(man) not in outs
    assert ingest_problems(run) == []
    used = json.loads(snap.read_text())
    name = min(used["parts"])
    # a later run needs one hour more: the shared manifest names another window and one more part
    grown = dict(used, t1="2023-03-04 00:00:00", hours=used["hours"] + 18, parts={**used["parts"], "wrf_2023030400.npz": "0" * 64})
    man.write_text(json.dumps(grown))
    assert ingest_problems(run) == []                                                        # was: input .../orca/manifest.json changed since the stage ran
    man.write_text(json.dumps(dict(grown, parts={})))                                        # a window elsewhere replaced the list
    assert ingest_problems(run) == []
    part = cache / "hours" / name                                                            # the fixture's parts are gone (the stores were assembled)
    part.parent.mkdir()
    part.write_bytes(b"not the part this run read")
    probs = ingest_problems(run)
    assert len(probs) == 1 and f"input {part} changed since the stage ran" in probs[0] and used["parts"][name][:12] in probs[0]
    part.unlink()
    assert ingest_problems(run) == []                                                        # an absent part is no problem, as before
    snap.write_text(snap.read_text() + " ")                                                 # the copy itself is hashed
    assert any(f"input {snap} changed since the stage ran" in x for x in ingest_problems(run))


def test_r11_m9_the_ingest_takes_what_it_reads_of_the_orca_and_tao_manifests_from_the_copy_it_recorded(tmp_path, data_copy, monkeypatch):
    """The stage read the shared orca manifest, then copied it, then read it again for the key of the derived layer; the TAO stage copied it and then
    loaded from the shared file. A fetch of another run between the reads makes the recorded copy differ from what the stage used."""
    forbid_downloads(monkeypatch)
    man_o = data_copy / "cache" / "ci_fixture" / "orca" / "manifest.json"
    man_t = tao.cache_dir(data_copy) / "manifest.json"
    hours = json.loads(man_o.read_text())["hours"]
    real = ledger.copy_manifest

    def swapped(src, dest):
        if pathlib.Path(src) == man_o:                                                  # another run grows the cache just before the copy ...
            man_o.write_text(json.dumps(dict(json.loads(man_o.read_text()), hours=hours + 7)))
        got = real(src, dest)
        if pathlib.Path(src) == man_t:                                                  # ... and rewrites the TAO manifest just after it
            man_t.write_text(json.dumps(dict(json.loads(man_t.read_text()), selected={})))
        return got
    monkeypatch.setattr(ledger, "copy_manifest", swapped)
    run = tmp_path / "r"
    d = run_stage(pipeline.s_ingest, ctx_for(run), "ingest")
    copy = json.loads((run / "ingest" / "orca_manifest.json").read_text())
    assert copy["hours"] == hours + 7 and check_of(d, "orca_hours_cover_window")["value"] == copy["hours"]
    kept = json.loads((run / "ingest" / "tao_manifest.json").read_text())
    assert kept["selected"] and check_of(d, "tao_moorings_compared")["ok"]


def test_lb0_a_derived_layer_rebuilt_on_other_code_leaves_the_audit_of_an_earlier_run_clean_and_a_damaged_one_does_not(tmp_path, data_copy, monkeypatch):
    """P-34 (derived layer), the case that reached the report: the layer's key holds the code digest, so the first run after any code change rebuilt the one
    shared `cache/<mission>/derived.zarr` in place and every earlier run in the data directory read 'input .../derived.zarr changed since the stage ran ...
    run `fetch` again' (and its report opened with 'the numbers may not be what the stages produced'), an advice that rebuilds with the new key and cannot
    clear it."""
    forbid_downloads(monkeypatch)
    first, second = ctx_for(tmp_path / "a"), ctx_for(tmp_path / "b")
    run_stage(pipeline.s_ingest, first, "ingest")
    key_a = json.loads((first.cache / surface.DIGEST).read_text())["built_from"]
    second.code_digest = "another code digest"                                              # what any edit to cafe/ does to ctx.code_digest
    run_stage(pipeline.s_ingest, second, "ingest")
    key_b = json.loads((first.cache / surface.DIGEST).read_text())["built_from"]
    assert key_a != key_b and json.loads((tmp_path / "a" / "ingest" / surface.DIGEST).read_text())["built_from"] == key_a
    assert ingest_problems(tmp_path / "a") == []                                           # was: input .../derived.zarr changed since the stage ran
    assert ingest_problems(tmp_path / "b") == []
    chunk = next(f for f in sorted((first.cache / "derived.zarr" / "ustar").rglob("*")) if f.is_file() and f.name != "zarr.json")
    chunk.write_bytes(chunk.read_bytes()[:-1] + bytes([chunk.read_bytes()[-1] ^ 0xFF]))      # damage under the key run b recorded
    probs = ingest_problems(tmp_path / "b")
    assert len(probs) == 1 and "derived.zarr changed since the stage ran" in probs[0]


def test_p34_orca_stores_assembled_again_by_a_later_run_leave_an_earlier_audit_clean_and_a_damaged_one_does_not(tmp_path, data_copy, monkeypatch, capsys):
    """P-34 (orca stores): `orca.assemble` rewrites wrf.zarr, wrf3d.zarr, umwm.zarr and umwmspec.zarr whole, then the manifest. The audit of an earlier run
    said 'input .../wrf.zarr changed since the stage ran ... delete it and run `fetch` again', which would delete a good store. The run's own copy of the
    manifest (ingest/orca_manifest.json) tells the rewrite (the shared manifest is another one now) from damage (it is the one the run kept)."""
    forbid_downloads(monkeypatch)
    cache = data_copy / "cache" / "ci_fixture" / "orca"
    man, wrf = cache / "manifest.json", cache / "wrf.zarr"
    run = tmp_path / "r"
    run_stage(pipeline.s_ingest, ctx_for(run), "ingest")
    chunk = next(f for f in sorted(wrf.rglob("*")) if f.is_file() and f.name != "zarr.json")
    chunk.write_bytes(chunk.read_bytes() + b"\0")                                           # damage: the manifest is still the one the run kept
    probs = ingest_problems(run)
    assert len(probs) == 1 and f"input {wrf} changed since the stage ran (tree " in probs[0] and "delete it and run `fetch` again" in probs[0]
    used = json.loads(man.read_text())
    man.write_text(json.dumps(dict(used, hours=used["hours"] + 1)))                          # a later assemble: its stores, then its manifest
    capsys.readouterr()
    assert ingest_problems(run) == []
    err = capsys.readouterr().err
    assert f"note: r: stage ingest: input {wrf}: the bytes this run read were replaced by a later fetch" in err
    assert "delete" not in err


def test_p32_a_grown_tao_cache_leaves_the_audit_of_an_earlier_run_clean_and_a_changed_or_lost_file_does_not(tmp_path, network):
    """P-32, TAO: a wider box or window rewrites `tao/s2/manifest.json` (`fetch_tao` is called when `_tao_cached` says the cache does not cover it)."""
    root = network["root"]
    run = tmp_path / "r"
    d = run_stage(pipeline.s_ingest, ctx_for(run), "ingest")
    tdir = tao.cache_dir(root)
    snap = run / "ingest" / "tao_manifest.json"
    assert snap.read_bytes() == (tdir / "manifest.json").read_bytes()
    assert [i["ref"] for i in d["inputs"] if i.get("shared") == str(tdir / "manifest.json")] == [str(snap)]
    assert ingest_problems(run) == []
    before = json.loads(snap.read_text())
    tao.fetch_tao(BOX, T0 - 86400.0, T1 + 86400.0, tdir, base=tao.BASE)                      # what `_need` runs for a wider window
    after = json.loads((tdir / "manifest.json").read_text())
    assert after["t0"] < before["t0"] and after["t1"] > before["t1"]
    assert ingest_problems(run) == []                                                        # was: input .../tao/s2/manifest.json changed since the stage ran
    victim = min(tdir.glob("T0N165W/*.nc"))
    was = victim.read_bytes()
    victim.write_bytes(was[:-1] + bytes([was[-1] ^ 0xFF]))
    probs = ingest_problems(run)
    assert len(probs) == 1 and f"input {victim} changed since the stage ran" in probs[0]
    victim.unlink()
    probs = ingest_problems(run)
    assert len(probs) == 1 and f"input {victim} is missing (the stage read it, tao_manifest.json lists it)" in probs[0]
    victim.write_bytes(was)
    assert ingest_problems(run) == []


def test_p32_a_run_copied_to_a_machine_without_the_cache_is_audited_by_its_own_copy_of_the_manifests(tmp_path, network):
    root = network["root"]
    made = tmp_path / "r"
    run_stage(pipeline.s_ingest, ctx_for(made), "ingest")
    copy = tmp_path / "elsewhere" / "r"
    shutil.copytree(made, copy)
    shutil.rmtree(root / "tao")                                                             # no cache on the other machine
    here = [x for x in ingest_problems(copy) if "tao" in x]
    assert here == []                                                                       # the manifest copy is in the run; nothing to compare with
    (copy / "ingest" / "tao_manifest.json").write_text("{}")
    assert any("tao_manifest.json changed since the stage ran" in x for x in ingest_problems(copy))


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
    man = json.loads((tao.cache_dir(root) / "manifest.json").read_text())
    assert set(man["selected"]) == {"T0N165W", "T2S165W"} and tao.verify(tao.cache_dir(root)) == len(man["files"]) == 6
    assert any(i.get("shared", "").endswith(f"tao/s{tao.SELECTION}/manifest.json") and i["sha256"] for i in d["inputs"])
    assert check_of(d, "tao_moorings_compared")["ok"]
    # the second ingest finds everything cached and good: not one more request
    n_ncss, n_srv = len(ncss.log), len(srv.log)
    run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r2"), "ingest")
    assert len(ncss.log) == n_ncss and len(srv.log) == n_srv
