"""cafe.pm.env.hycom: boxes, TEOS-10, layers -> z, the GOFS fetch (local stand-ins for ncss.hycom.org / tds.hycom.org: hang,
error, resume, fallback), the lab readers (netCDF, archv .a/.b) round-tripped against the GOFS values, and the receipts."""
import datetime as dt, http.server, io, json, pathlib, runpy, shutil, sys, threading, urllib.parse

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe import receipts as R
from cafe.pm.env import hycom as h
from tests.fixtures.hycom import make_fixtures as mk

STORE_VARS = ("water_temp", "salinity", "water_u", "water_v", "rho", "c")


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    return mk.make(tmp_path_factory.mktemp("hycom_fx"))


@pytest.fixture(scope="session")
def truth(fx):
    return h.open_store(fx["gofs_zarr"]).load()


class Ncss:
    """Stand-in for ncss.hycom.org and tds.hycom.org: /ncss/<dataset>/<year>?var=..&time_start=..&time_end=.. returns a NetCDF cut
    from the fixture parts. mode: 'ok' | 'hang' (sleeps 60 s) | 'error' (HTTP 500) | 'html' (200, not NetCDF) | 'shift' (data + 1).
    fail: datasets that always answer 500."""

    def __init__(self, parts_dir):
        import xarray as xr
        self.data = {}
        for d in h.DATASETS:
            fs = sorted(pathlib.Path(parts_dir).glob(f"{d}_*.nc"))
            self.data[d] = xr.concat([xr.open_dataset(f).load() for f in fs], dim="time").sortby("time")
        self.mode, self.fail, self.log = "ok", set(), []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):          # the fetch child was killed at its deadline
                    pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                ds = u.path.split("/")[-2]
                outer.log.append((ds, q))
                if outer.mode == "hang":
                    threading.Event().wait(60)
                if outer.mode == "error" or ds in outer.fail:
                    self.send_response(500); self.end_headers()
                    return
                body = b"<html>sorry</html>" if outer.mode == "html" else outer.cut(ds, q)
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/ncss"

    def cut(self, ds, q):
        t = lambda k: np.datetime64(q[k][0].rstrip("Z"))
        a = self.data[ds]
        a = a.sel(time=slice(t("time_start"), t("time_end")), lat=slice(float(q["south"][0]) - 1e-3, float(q["north"][0]) + 1e-3),
                  lon=slice(float(q["west"][0]) - 1e-3, float(q["east"][0]) + 1e-3))
        if "vertCoord" in q:
            a = a.sel(depth=[float(q["vertCoord"][0])], method="nearest")
        a = a[[v for v in q["var"]]]
        if self.mode == "shift":
            a = a + 1.0
        out = io.BytesIO()
        a.to_netcdf(out)
        return out.getvalue()

    def close(self):
        self.httpd.shutdown(); self.httpd.server_close()


@pytest.fixture
def ncss(fx):
    s = Ncss(fx["gofs_parts"])
    yield s
    s.close()


@pytest.fixture
def dods(fx, tmp_path):
    """Local files standing in for tds.hycom.org/thredds/dodsC/.../<dataset>/2023 (netCDF4 opens a path like a URL)."""
    import xarray as xr
    d = tmp_path / "dods"
    for ds in h.DATASETS:
        (d / ds).mkdir(parents=True)
        fs = sorted(pathlib.Path(fx["gofs_parts"]).glob(f"{ds}_*.nc"))
        xr.concat([xr.open_dataset(f, decode_times=False) for f in fs], dim="time").sortby("time").to_netcdf(d / ds / "2023")
    return d


def _fetch(tmp, ncss=None, dods=None, **kw):
    kw = dict(chunk_steps=2, workers=2, deadline_s=120, tries=1) | kw
    return h.fetch_gofs(mk.BOX, mk.STEPS[0], mk.STEPS[-1], tmp, ncss=ncss.base if ncss else "http://127.0.0.1:9/none",
                        dods=str(dods) if dods else "/nonexistent", **kw)


def _same(a, b, vars_=STORE_VARS + ("surf_el",), tol=0.0):
    for v in vars_:
        x, y = a[v].values, b[v].values
        assert np.array_equal(np.isnan(x), np.isnan(y)), v
        assert np.nanmax(np.abs(x - y), initial=0.0) <= tol, v


# ------------------------------------------------------------------ boxes, times, URLs


def test_box_demo():
    assert h.box360(h.TEPEX_C_BOX) == (-5.0, 5.0, 165.0, 195.0)
    assert h.padded(h.TEPEX_C_BOX, 2.0) == (-7.0, 7.0, 163.0, 197.0)
    assert h.box360((-90, 95, 10, 20))[:2] == (-90.0, 95.0) and h.padded((-80, 90, 0, 10), 2.0)[:2] == (-80.0, 90.0)


@given(st.floats(-180, 360), st.floats(1, 100), st.floats(-60, 60), st.floats(0.1, 30))
@settings(max_examples=60, deadline=None)
def test_box_span_and_west_survive_any_lon_convention(w, span, s, ds):
    if (w % 360.0) + span > 360.0 + 1e-9:
        with pytest.raises(ValueError, match="crosses"):
            h.box360((s, s + ds, w, w + span))
        return
    sb, nb, wb, eb = h.box360((s, s + ds, w, w + span))
    assert 0 <= wb < 360 and np.isclose(eb - wb, span) and np.isclose(wb, w % 360.0)


def test_box_refusals():
    with pytest.raises(ValueError, match="crosses 0/360"):
        h.box360((-1, 1, 350, 10))
    with pytest.raises(ValueError, match="below north"):
        h.box360((1, 1, 10, 20))


def test_steps_and_epoch():
    s = h.gofs_steps("2023-03-01T12:00:00Z", "2023-03-07T12:00:00Z")
    assert len(s) == 49 and s[0] == mk.T0 and s[-1] - s[0] == 6 * 86400 and set(np.diff(s)) == {10800.0}
    assert len(h.gofs_steps("2023-03-01T13:00:00Z", "2023-03-01T14:00:00Z")) == 0
    assert h.epoch(mk.T0) == h.epoch("2023-03-01T12:00:00Z") == h.epoch(dt.datetime(2023, 3, 1, 12))


def test_ncss_url_uses_0_360_box_and_the_year_file():
    u = h.ncss_url("ts3z", ("water_temp", "salinity"), h.box360((-7, 7, 163, -163)), mk.T0, mk.T0 + 3600)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query)
    assert u.startswith(h.NCSS + "/ts3z/2023?") and q["var"] == ["water_temp", "salinity"]
    assert (q["west"], q["east"], q["south"], q["north"]) == (["163.0000"], ["197.0000"], ["-7.0000"], ["7.0000"])
    assert q["time_start"] == ["2023-03-01T12:00:00Z"] and q["accept"] == ["netcdf4"]


def test_chunks_split_at_the_year_and_never_exceed_n():
    t = dt.datetime(2023, 12, 31, 12, tzinfo=dt.timezone.utc).timestamp() + 10800.0 * np.arange(7)
    c = h._chunks(t, 3)
    assert [len(x) for x in c] == [3, 3, 1] or all(len(x) <= 3 for x in c)
    assert all(len({int(h._iso(v)[:4]) for v in x}) == 1 for x in c) and sum(map(len, c)) == 7 and h._chunks([], 3) == []


# ------------------------------------------------------------------ TEOS-10


def test_kind_is_never_guessed():
    for bad in (None, "", "insitu", "pt"):
        with pytest.raises(ValueError, match="never guessed.*temperature_kind"):
            h.kind_of(bad)
    assert h.kind_of("in_situ") == "in_situ" and h.kind_of("potential") == "potential"
    with pytest.raises(ValueError, match="in_situ"):
        h.teos10(35.0, 10.0, 100.0, 0.0, 180.0, None)


def test_in_situ_vs_potential_at_depth():
    a = h.teos10(35.0, 4.4, 1000.0, 0.0, 180.0, "in_situ")
    b = h.teos10(35.0, 4.4, 1000.0, 0.0, 180.0, "potential")
    assert 0.05 < b["CT"] - a["CT"] < 0.15 and 0.005 < a["rho"] - b["rho"] < 0.05       # warmer water is lighter
    s = h.teos10(35.0, 20.0, 0.0, 0.0, 180.0, "in_situ")
    assert np.isclose(s["CT"], h.teos10(35.0, 20.0, 0.0, 0.0, 180.0, "potential")["CT"], atol=1e-9)    # same at the surface
    assert 1020 < a["rho"] < 1040 and 1400 < a["c"] < 1600 and np.isclose(a["p"], 1005.0, atol=10)


@given(st.floats(33, 37), st.floats(1, 30), st.floats(0, 4000), st.floats(-10, 10))
@settings(max_examples=40, deadline=None)
def test_density_rises_with_salinity_and_falls_with_temperature(sp, t, z, lat):
    r = h.teos10(sp, t, z, lat, 180.0, "in_situ")
    assert h.teos10(sp + 0.5, t, z, lat, 180.0, "in_situ")["rho"] > r["rho"]
    assert h.teos10(sp, t + 0.5, z, lat, 180.0, "in_situ")["rho"] < r["rho"]


# ------------------------------------------------------------------ layers -> z-levels


def test_layers_to_z_basics():
    dp = np.array([[10.0], [20.0], [0.0], [30.0]])                   # mids 5, 20, -, 45; seafloor 60
    v = np.array([[1.0], [2.0], [99.0], [4.0]])
    z = [0, 5, 12.5, 20, 45, 60, 61]
    out = h.layers_to_z(v, dp, z)[:, 0]
    assert np.allclose(out[:6], [1.0, 1.0, 1.5, 2.0, 4.0, 4.0]) and np.isnan(out[6])    # constant above the first mid, vanished layer ignored
    assert np.isnan(h.layers_to_z(v, np.zeros_like(dp), z)).all()                          # a land column
    nan_in_wet = v.copy(); nan_in_wet[1] = np.nan
    assert np.isclose(h.layers_to_z(nan_in_wet, dp, [20.0])[0, 0], 1.0 + (20 - 5) / (45 - 5) * 3.0)      # a NaN layer is skipped, not interpolated through


@given(st.lists(st.tuples(st.floats(0.0, 50), st.floats(-5, 5)), min_size=1, max_size=12), st.lists(st.floats(0, 600), min_size=1, max_size=8))
@settings(max_examples=80, deadline=None)
def test_layers_to_z_stays_within_the_layer_values_and_is_nan_only_below_the_floor(layers, zs):
    dp = np.array([[a] for a, _ in layers])
    v = np.array([[b] for _, b in layers])
    out = h.layers_to_z(v, dp, zs)[:, 0]
    floor = dp.sum()
    wet = dp[:, 0] > 1e-6
    for z, o in zip(zs, out, strict=True):
        if not wet.any() or z > floor + 1e-6:
            assert np.isnan(o)
        else:
            assert v[wet].min() - 1e-9 <= o <= v[wet].max() + 1e-9


@given(st.floats(-3, 3), st.floats(-1, 1))
@settings(max_examples=30, deadline=None)
def test_layers_to_z_reproduces_a_linear_profile_between_mid_points(a, b):
    dp = np.array([[10.0], [10.0], [20.0], [40.0]])
    mid = np.cumsum(dp[:, 0]) - dp[:, 0] / 2
    out = h.layers_to_z((a + b * mid)[:, None], dp, [5.0, 12.0, 30.0, 60.0])[:, 0]
    assert np.allclose(out, a + b * np.array([5.0, 12.0, 30.0, 60.0]), atol=1e-9)


# ------------------------------------------------------------------ GOFS pipeline on the fixture (no network)


def test_store_layout_and_attributes(truth, fx):
    assert truth.attrs["temperature_kind"] == "in_situ" and truth.attrs["lon_convention"].startswith("0..360")
    assert list(truth.water_temp.dims) == ["time", "depth", "lat", "lon"] and list(truth.surf_el.dims) == ["time", "lat", "lon"]
    assert np.array_equal(truth.time.values, mk.STEPS) and truth.lon.values.min() >= 0 and truth.lon.values.max() < 360
    assert np.allclose(truth.lon.values, mk.LON) and np.allclose(truth.depth.values, mk.DEPTH)
    assert json.loads(truth.attrs["served_by"]) == ["ncss"]
    t = truth.water_temp.values
    assert np.isnan(t[:, :, 0, 0]).all() and np.isnan(t[:, 5:, 3, 4]).all() and np.isfinite(t[:, :5, 3, 4]).all()      # land, seafloor
    r, c = truth.rho.values, truth.c.values
    assert np.nanmin(r) > 1020 and np.nanmax(r) < 1040 and np.nanmin(c) > 1480 and np.nanmax(c) < 1560 and np.array_equal(np.isnan(r), np.isnan(t))
    assert np.all(np.diff(r[0, :, 5, 5]) >= -1e-3)                      # stable: density never decreases with depth in the profile


def test_open_store_refuses_without_temperature_kind(truth, tmp_path):
    bare = tmp_path / "bare.zarr"
    truth.drop_attrs().to_zarr(bare, consolidated=False)
    with pytest.raises(ValueError, match="never guessed"):
        h.open_store(bare)


def test_write_store_refuses_empty_and_unknown_kind(tmp_path):
    with pytest.raises(ValueError, match="no time steps"):
        h.write_store(iter(()), tmp_path / "x.zarr", "in_situ", {})
    with pytest.raises(ValueError, match="never guessed"):
        h.write_store(iter(()), tmp_path / "x.zarr", None, {})


def test_std_fills_a_missing_surface_height_with_nan(truth):
    ds = truth.drop_vars(["surf_el"]).isel(time=slice(0, 1))
    out = h._std(ds)
    assert out.surf_el.shape == (1, 7, 9) and np.isnan(out.surf_el.values).all() and out.water_temp.dtype == np.float32


# ------------------------------------------------------------------ fetch: servers, deadlines, resume


def test_fetch_from_ncss_matches_the_truth_and_writes_a_hashed_manifest(fx, truth, ncss, tmp_path):
    z = _fetch(tmp_path, ncss)
    assert z.name == "gofs_tepex_c.zarr"
    _same(h.open_store(z), truth)
    man = json.loads((tmp_path / "gofs_tepex_c.parts" / "manifest.json").read_text())
    assert len(man["parts"]) == 6 and {r["server"] for r in man["parts"].values()} == {"ncss"}
    for fn, r in man["parts"].items():
        assert h._sha(tmp_path / "gofs_tepex_c.parts" / fn) == r["sha256"] and r["bytes"] > 0 and r["failed_first"] == []
    assert h.open_store(z).attrs["manifest_sha256"] == h._sha(tmp_path / "gofs_tepex_c.parts" / "manifest.json")
    assert len(ncss.log) == 6 and {q["var"][0] for _, q in ncss.log} >= {"water_temp", "water_u", "surf_el"}


def test_fetch_resumes_and_refetches_only_a_damaged_part(fx, truth, ncss, tmp_path):
    _fetch(tmp_path, ncss)
    n = len(ncss.log)
    ncss.mode = "error"
    _fetch(tmp_path, ncss)                                   # everything on disk and hash-checked: no request at all
    assert len(ncss.log) == n
    parts = tmp_path / "gofs_tepex_c.parts"
    victim = sorted(parts.glob("uv3z_*"))[0]
    victim.write_bytes(victim.read_bytes()[:-9] + b"corrupted")          # same size class, wrong hash
    ncss.mode = "ok"
    z = _fetch(tmp_path, ncss, keep_parts=False)
    assert len(ncss.log) == n + 1 and ncss.log[-1][0] == "uv3z"
    _same(h.open_store(z), truth)
    assert not list(parts.glob("*.nc"))                      # keep_parts=False


def test_fetch_falls_back_to_opendap_on_http_error(fx, truth, ncss, dods, tmp_path):
    ncss.mode = "error"
    z = _fetch(tmp_path, ncss, dods)
    _same(h.open_store(z), truth, tol=1e-5)
    man = json.loads((tmp_path / "gofs_tepex_c.parts" / "manifest.json").read_text())
    assert {r["server"] for r in man["parts"].values()} == {"opendap"}
    assert all("500" in r["failed_first"][0] for r in man["parts"].values())
    assert sorted(json.loads(h.open_store(z).attrs["served_by"])) == ["opendap"]


def test_a_server_that_never_answers_is_killed_at_the_deadline_and_the_next_server_is_tried(fx, truth, ncss, dods, tmp_path):
    ncss.mode = "hang"
    z = _fetch(tmp_path, ncss, dods, deadline_s=3.0, workers=6)
    man = json.loads((tmp_path / "gofs_tepex_c.parts" / "manifest.json").read_text())
    assert all("no answer within 3 s" in r["failed_first"][0] for r in man["parts"].values())
    _same(h.open_store(z), truth, tol=1e-5)


def test_server_that_sends_html_is_an_error_not_a_netcdf(fx, ncss, tmp_path):
    ncss.mode = "html"
    with pytest.raises(h.FetchError, match="not NetCDF"):
        _fetch(tmp_path, ncss)


def test_one_failed_dataset_does_not_lose_the_others_and_a_rerun_completes(fx, truth, ncss, tmp_path):
    ncss.fail = {"ts3z"}
    with pytest.raises(h.FetchError, match=r"(?s)2 of 6 parts failed.*ts3z"):
        _fetch(tmp_path, ncss)
    man = json.loads((tmp_path / "gofs_tepex_c.parts" / "manifest.json").read_text())
    assert sorted(r["dataset"] for r in man["parts"].values()) == ["ssh", "ssh", "uv3z", "uv3z"]
    ncss.fail = set(); ncss.log.clear()
    _same(h.open_store(_fetch(tmp_path, ncss)), truth)
    assert {d for d, _ in ncss.log} == {"ts3z"}              # only the missing parts were asked for


def test_fetch_refuses_an_empty_window(tmp_path):
    with pytest.raises(ValueError, match="no 3-hourly"):
        h.fetch_gofs(mk.BOX, mk.T0 + 3700, mk.T0 + 3800, tmp_path)


def test_dods_child_says_when_the_box_has_no_data(dods, tmp_path):
    with pytest.raises(ValueError, match="no data"):
        h._child_dods(str(dods / "ts3z" / "2023"), "water_temp", mk.T0, mk.T0, 50.0, 51.0, 10.0, 11.0, str(tmp_path / "o.nc"))


def test_child_wrapper_reports_failure_and_timeout(ncss, tmp_path):
    with pytest.raises(RuntimeError, match="URLError|FileNotFoundError"):
        h._child(["_ncss", "file:///nonexistent/x.nc", tmp_path / "o.nc"], 60)
    ncss.mode = "hang"
    with pytest.raises(TimeoutError, match="no answer within 1 s"):
        h._child(["_ncss", h.ncss_url("ssh", ("surf_el",), h.box360(mk.BOX), mk.STEPS[0], mk.STEPS[0], ncss.base), tmp_path / "o.nc"], 1)


def test_main_entry_points(fx, ncss, dods, tmp_path, monkeypatch):
    url = h.ncss_url("ssh", ("surf_el",), h.box360(mk.BOX), mk.STEPS[0], mk.STEPS[0], ncss.base)
    monkeypatch.setattr(sys, "argv", ["hycom", "_ncss", url, str(tmp_path / "a.nc")])
    runpy.run_module("cafe.pm.env.hycom", run_name="__main__")
    assert (tmp_path / "a.nc").stat().st_size > 0
    args = [str(dods / "ssh" / "2023"), "surf_el", str(mk.STEPS[0]), str(mk.STEPS[1]), *map(str, h.box360(mk.BOX)), str(tmp_path / "b.nc")]
    monkeypatch.setattr(sys, "argv", ["hycom", "_dods", *args])
    runpy.run_module("cafe.pm.env.hycom", run_name="__main__")
    import xarray as xr
    assert xr.open_dataset(tmp_path / "b.nc").sizes["time"] == 2
    ncss.mode = "html"
    monkeypatch.setattr(sys, "argv", ["hycom", "_ncss", url, str(tmp_path / "c.nc")])
    with pytest.raises(ValueError, match="not NetCDF"):
        runpy.run_module("cafe.pm.env.hycom", run_name="__main__")


def test_assemble_refuses_tampered_incomplete_or_empty_parts(fx, tmp_path):
    p = tmp_path / "parts"
    shutil.copytree(fx["gofs_parts"], p)
    assert h.assemble_gofs(p, mk.STEPS, tmp_path / "ok.zarr").exists()
    with pytest.raises(ValueError, match=r"steps are missing"):
        h.assemble_gofs(p, np.r_[mk.STEPS, mk.STEPS[-1] + 10800.0], tmp_path / "x.zarr")
    q = tmp_path / "parts2"
    shutil.copytree(fx["gofs_parts"], q)
    man = json.loads((q / "manifest.json").read_text())
    for fn in [k for k, v in man["parts"].items() if v["dataset"] == "ssh"]:
        del man["parts"][fn]
        (q / fn).unlink()
    (q / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(ValueError, match="no ssh parts"):
        h.assemble_gofs(q, mk.STEPS, tmp_path / "z.zarr")
    victim = sorted(p.glob("ts3z_*"))[0]
    victim.write_bytes(victim.read_bytes() + b"x")
    with pytest.raises(ValueError, match="SHA-256 differs"):
        h.assemble_gofs(p, mk.STEPS, tmp_path / "y.zarr")


def test_check_node_reads_the_server_value_back(fx, ncss, tmp_path):
    nodes = [(0, 3, 2, 4), (2, 6, 4, 7)]
    assert h.check_node(fx["gofs_zarr"], nodes, ncss.base, 60, tmp_path) == 0.0
    ncss.mode = "shift"
    assert abs(h.check_node(fx["gofs_zarr"], nodes, ncss.base, 60, tmp_path) - 1.0) < 1e-4       # a store that disagrees is caught


# ------------------------------------------------------------------ lab readers


def _ingest(fx, key, tmp_path, name="lab.zarr", **kw):
    extra = dict(grid=fx["grid"]) if key == "archv_dir" else {}
    return h.open_store(h.ingest_lab_hycom(fx[key], fx["box"], tmp_path / name, "in_situ", depth=fx["depth"], **(extra | kw)))


@pytest.mark.parametrize("key", ["zlevel_dir", "layered_dir", "archv_dir"])
def test_lab_files_round_trip_to_the_gofs_values(key, fx, truth, tmp_path):
    got = _ingest(fx, key, tmp_path)
    assert np.array_equal(got.time.values, truth.time.values)
    assert np.allclose(got.lon.values, truth.lon.values) and np.allclose(got.lat.values, truth.lat.values)
    for v in STORE_VARS:
        a, b = truth[v].values, got[v].values
        m = np.isfinite(a) & np.isfinite(b)
        assert m.sum() >= 0.7 * np.isfinite(a).sum()
        if key != "archv_dir" or v not in ("water_u", "water_v"):
            assert np.array_equal(np.isnan(a), np.isnan(b)), (key, v)             # same land and seafloor mask
        assert np.abs(a[m] - b[m]).max() <= (5e-5 if v not in ("rho", "c") else 1e-3), (key, v)
    assert got.attrs["temperature_kind"] == "in_situ" and "lab HYCOM" in got.attrs["source"]
    if key == "zlevel_dir":
        assert np.allclose(got.surf_el.values[np.isfinite(got.surf_el.values)], truth.surf_el.values[np.isfinite(got.surf_el.values)], atol=1e-6)
    else:
        assert np.isnan(got.surf_el.values).all() == (key == "layered_dir")      # archv has srfhgt, the layered file has none


def test_archv_destaggering_loses_the_last_column_and_row_and_btrop_is_added(fx, truth, tmp_path):
    got = _ingest(fx, "archv_dir", tmp_path)
    u, v = got.water_u.values, got.water_v.values
    assert np.isnan(u[..., -1]).all() and np.isnan(v[..., -1]).all() and np.isnan(u[..., -1, :]).all() and np.isnan(v[..., -1, :]).all()
    nobt = tmp_path / "nobt"                                  # the same files without the two barotropic records
    nobt.mkdir()
    for b in fx["archv_dir"].glob("archv*.b"):
        stem = fx["archv_dir"] / b.stem
        doc = h.read_b(b)
        recs = [(f["name"], f["k"], f["dens"], h.read_a(str(stem) + ".a", doc, i), f["day"]) for i, f in enumerate(doc["fields"])
                if f["name"] not in ("u_btrop", "v_btrop")]
        mk.write_ab(nobt / b.stem, recs, doc["idm"], doc["jdm"])
    shutil.copy(str(fx["grid"]) + ".a", nobt / "regional.grid.a"); shutil.copy(str(fx["grid"]) + ".b", nobt / "regional.grid.b")
    nb = h.open_store(h.ingest_lab_hycom(nobt, fx["box"], tmp_path / "nb.zarr", "in_situ", depth=fx["depth"]))
    assert np.nanmax(np.abs(nb.water_u.values - u)) > 5e-3 and np.nanmax(np.abs(nb.water_v.values - v)) > 2e-3      # the barotropic part
    assert np.allclose(nb.water_temp.values, got.water_temp.values, equal_nan=True)


def test_potential_reading_changes_density_at_depth_only(fx, truth, tmp_path):
    a = _ingest(fx, "zlevel_dir", tmp_path, "a.zarr")
    b = h.open_store(h.ingest_lab_hycom(fx["zlevel_dir"], fx["box"], tmp_path / "b.zarr", "potential"))
    assert b.attrs["temperature_kind"] == "potential"
    d = (a.rho - b.rho).values
    assert np.nanmax(np.abs(d[:, 0])) < 1e-6 and 0.005 < np.nanmax(d[:, -1]) < 0.05 and np.nanmin(d[:, -1]) >= 0     # in-situ is lighter reading -> positive


def test_lab_netcdf_without_a_kind_refuses_and_attribute_or_argument_supplies_it(fx, tmp_path):
    with pytest.raises(ValueError, match="never guessed"):
        h.read_lab_netcdf(next(fx["layered_dir"].glob("*.nc")))
    ds, kind = h.read_lab_netcdf(next(fx["zlevel_dir"].glob("*.nc")))                  # carries the attribute
    assert kind == "in_situ" and np.allclose(ds.depth.values, mk.DEPTH)
    ds, kind = h.read_lab_netcdf(next(fx["layered_dir"].glob("*.nc")), "potential")
    assert kind == "potential" and len(ds.depth) == 40
    import xarray as xr
    f = xr.open_dataset(next(fx["layered_dir"].glob("*.nc"))).load()
    f["temperature"].attrs["temperature_kind"] = "potential"
    f.to_netcdf(tmp_path / "var_attr.nc")
    assert h.read_lab_netcdf(tmp_path / "var_attr.nc")[1] == "potential"
    with pytest.raises(ValueError, match="in_situ"):
        h.ingest_lab_hycom(fx["layered_dir"], fx["box"], tmp_path / "n.zarr")           # kind never guessed at ingest either


def test_lab_netcdf_schema_names_every_problem(fx, tmp_path):
    import xarray as xr
    f = xr.open_dataset(next(fx["layered_dir"].glob("*.nc"))).load()
    with pytest.raises(ValueError, match=r"hycom_netcdf\.json"):
        h.validate_netcdf(f.drop_vars(["salinity", "u-velocity"]))
    with pytest.raises(ValueError, match="hycom_netcdf"):
        h.validate_netcdf(f.assign(thknss=f.thknss.assign_attrs(units="furlongs")))
    bad = f.copy(); bad.attrs["temperature_kind"] = "warm"
    with pytest.raises(ValueError, match="temperature_kind"):
        h.validate_netcdf(bad)
    h.validate_netcdf(f)
    # the schema lists exactly the names the reader accepts
    sch = json.loads((h.remote.ROOT / "cafe" / "schemas" / "hycom_netcdf.json").read_text())
    text = json.dumps(sch["properties"]["variables"])
    assert all(f'"{n}"' in text for k, names in h.ALIASES.items() if k != "ssh" for n in names) and all(f'"{n}"' in text for n in h.Z_NAMES)


def test_lab_netcdf_structural_refusals_and_level_interpolation(fx, tmp_path):
    import xarray as xr
    src = next(fx["zlevel_dir"].glob("*.nc"))
    f = xr.open_dataset(src).load()
    f.assign_coords(depth=-f.depth).to_netcdf(tmp_path / "neg.nc")
    with pytest.raises(ValueError, match="positive down"):
        h.read_lab_netcdf(tmp_path / "neg.nc")
    f.isel(time=0, drop=True).to_netcdf(tmp_path / "notime.nc")
    with pytest.raises(ValueError, match="needs one each of time"):
        h.read_lab_netcdf(tmp_path / "notime.nc")
    f.assign_coords(time=[1.0]).to_netcdf(tmp_path / "rawtime.nc")
    with pytest.raises(ValueError, match="decodable"):
        h.read_lab_netcdf(tmp_path / "rawtime.nc")
    curv = f.rename({"lat": "y", "lon": "x"}).assign_coords(lat=(("y", "x"), np.zeros((7, 9))), lon=(("y", "x"), np.zeros((7, 9))))
    curv.to_netcdf(tmp_path / "curv.nc")
    with pytest.raises(ValueError, match="curvilinear"):
        h.read_lab_netcdf(tmp_path / "curv.nc")
    ds, _ = h.read_lab_netcdf(src, depth=[0.0, 20.0, 125.0, 5000.0])             # 20 m lies between the 10 and 25 m levels, 5000 m below them
    t = ds.water_temp.values[0]
    assert np.isnan(t[3]).all() and np.array_equal(t[0], f.temp.values[0, 0], equal_nan=True) and np.isfinite(t[1]).any() and np.isfinite(t[2]).any()
    z = f.temp.values[0]
    m1, m2 = np.isfinite(t[1]), np.isfinite(t[2])
    assert m1.sum() > m2.sum() > 0                                          # the shallow column has 20 m but not 125 m
    assert np.allclose(t[1][m1], (z[1] + (20 - 10) / 15 * (z[2] - z[1]))[m1], atol=1e-5)
    assert np.allclose(t[2][m2], (z[4] + 25 / 50 * (z[5] - z[4]))[m2], atol=1e-5)
    assert h._dim(f.temp, "time") == "time"


def test_read_b_parses_the_header_and_validates(fx):
    doc = h.read_b(str(fx["archv_dir"] / "archv.2023_060_12") + ".b")
    assert doc["idm"] == 9 and doc["jdm"] == 7 and doc["header"]["yrflag"] == 3 and doc["header"]["iversn"] == 22
    names = [f["name"] for f in doc["fields"]]
    assert names[:5] == ["montg1", "srfhgt", "surflx", "u_btrop", "v_btrop"] and names.count("thknss") == 19 and doc["fields"][5]["k"] == 1
    assert doc["fields"][3]["min"] <= doc["fields"][3]["max"]
    assert all(f["day"] == doc["fields"][0]["day"] for f in doc["fields"])


def test_read_b_rejects_what_is_not_an_archv_b(tmp_path):
    p = tmp_path / "x.b"
    p.write_text("not a hycom file\n")
    with pytest.raises(ValueError, match="hycom_ab.json"):
        h.read_b(p)
    p.write_text("   9    'idm   ' = x\n   7    'jdm   ' = y\nfield  time step\nu-vel.  =   0   1.0   1  1.0   0.0   1.0\n")
    with pytest.raises(ValueError, match="hycom_ab"):
        h.read_b(p)                                                          # no thknss/temp/salin records


def test_read_a_checks_size_pads_and_marks_land(fx, tmp_path):
    stem = fx["archv_dir"] / "archv.2023_060_12"
    doc = h.read_b(str(stem) + ".b")
    ssh = h.read_a(str(stem) + ".a", doc, 1)
    assert ssh.shape == (7, 9) and np.isnan(ssh[0, 0]) and np.isfinite(ssh[1:, 1:]).all()
    a_file = pathlib.Path(str(stem) + ".a")
    assert a_file.stat().st_size == len(doc["fields"]) * 4096 * 4          # records padded to 4096 words
    short = tmp_path / "short.a"
    short.write_bytes(a_file.read_bytes()[:-4096])
    with pytest.raises(ValueError, match="records of 4096 words"):
        h.read_a(short, doc, 0)


def test_grid_reader_and_refusals(fx, tmp_path):
    g = h.read_grid(fx["grid"])
    assert g["plon"].shape == (7, 9) and np.allclose(g["plat"][:, 0], mk.LAT, atol=1e-6) and np.allclose(np.mod(g["plon"][0], 360), mk.LON, atol=1e-4)
    assert (g["pang"] == 0).all()
    d = tmp_path / "g"
    shutil.copytree(fx["archv_dir"], d)
    b = (d / "regional.grid.b").read_text().replace("pang:", "zzzz:")
    (d / "regional.grid.b").write_text(b)
    assert (h.read_grid(d / "regional.grid")["pang"] == 0).all()                       # no pang record: assume 0
    (d / "regional.grid.b").write_text(b.replace("plat:", "yyyy:"))
    with pytest.raises(ValueError, match="no plon/plat"):
        h.read_grid(d / "regional.grid")
    # curvilinear: plon varying with j
    a = np.tile(mk.LON, (7, 1)) + np.arange(7)[:, None]
    (d / "regional.grid.b").write_text("    9    'idm   ' = x\n    7    'jdm   ' = y\nplon:  min,max =  0 1\nplat:  min,max =  0 1\n")
    (d / "regional.grid.a").write_bytes(mk._rec_a(a, 9, 7) + mk._rec_a(np.tile(mk.LAT[:, None], (1, 9)), 9, 7))
    with pytest.raises(ValueError, match="curvilinear"):
        h.read_grid(d / "regional.grid")


def test_model_day_and_yrflag():
    assert h.model_day_to_epoch(1.0, 3) == dt.datetime(1901, 1, 1, tzinfo=dt.timezone.utc).timestamp()
    assert h.model_day_to_epoch((dt.date(2023, 3, 1) - dt.date(1900, 12, 31)).days + 0.5, 3) == mk.T0
    with pytest.raises(ValueError, match="yrflag 2"):
        h.model_day_to_epoch(1.0, 2)


def test_destagger_and_rotation_convention(fx):
    u = np.arange(12.0).reshape(3, 4)
    ut, vt = h.destagger(u, u)
    assert np.allclose(ut[:, :3], 0.5 * (u[:, :3] + u[:, 1:])) and np.isnan(ut[:, 3]).all()
    assert np.isnan(vt[2]).all() and np.allclose(vt[:2], 0.5 * (u[:2] + u[1:]))


def test_archv_rotation_by_pang_and_time_override_and_errors(fx, tmp_path):
    d = tmp_path / "rot"
    shutil.copytree(fx["archv_dir"], d)
    ga = bytearray((d / "regional.grid.a").read_bytes())
    ga[3 * 16384:4 * 16384] = mk._rec_a(np.full((7, 9), 90.0), 9, 7)                # pang = 90 degrees: grid x is north
    (d / "regional.grid.a").write_bytes(bytes(ga))
    stem = d / "archv.2023_060_12"
    plain, _ = h.read_archv(fx["archv_dir"] / "archv.2023_060_12", fx["grid"], "in_situ", fx["depth"], time=5.0)
    rot, _ = h.read_archv(stem, d / "regional.grid", "in_situ", fx["depth"], time=5.0)
    assert plain.time.values[0] == 5.0
    m = np.isfinite(plain.water_u.values) & np.isfinite(rot.water_u.values) & np.isfinite(plain.water_v.values) & np.isfinite(rot.water_v.values)
    assert np.allclose(rot.water_u.values[m], -plain.water_v.values[m], atol=1e-5) and np.allclose(rot.water_v.values[m], plain.water_u.values[m], atol=1e-5)
    with pytest.raises(ValueError, match="never guessed"):
        h.read_archv(stem, fx["grid"], None)
    with pytest.raises(ValueError, match="no points inside"):
        h.read_archv(stem, fx["grid"], "in_situ", fx["depth"], box=(40, 41, 10, 11))
    other = tmp_path / "wrong"
    shutil.copytree(fx["archv_dir"], other)
    b = (other / "archv.2023_060_12.b").read_text().replace("    9    'idm", "   10    'idm")
    (other / "archv.2023_060_12.b").write_text(b)
    with pytest.raises(ValueError, match="is 10x7 but the grid is 9x7"):
        h.read_archv(other / "archv.2023_060_12", other / "regional.grid", "in_situ")
    nk = tmp_path / "nk"
    shutil.copytree(fx["archv_dir"], nk)
    (nk / "archv.2023_060_12.b").write_text((nk / "archv.2023_060_12.b").read_text().replace("temp    =", "tempX   =", 1))
    with pytest.raises(ValueError, match="no 'temp' record for layer 1"):
        h.read_archv(nk / "archv.2023_060_12", nk / "regional.grid", "in_situ")


def test_ingest_inputs_directory_file_stem_and_conflicts(fx, truth, tmp_path):
    out = h.ingest_lab_hycom(fx["archv_dir"] / "archv.2023_060_12.a", fx["box"], tmp_path / "one.zarr", "in_situ", depth=fx["depth"])
    assert h.open_store(out).sizes["time"] == 1                                       # a .a path, grid found next to it
    out = h.ingest_lab_hycom(fx["archv_dir"] / "archv.2023_060_15.b", fx["box"], tmp_path / "two.zarr", "in_situ", depth=fx["depth"])
    assert h.open_store(out).time.values[0] == mk.STEPS[1]
    out = h.ingest_lab_hycom(next(fx["zlevel_dir"].glob("*.nc")), fx["box"], tmp_path / "three.zarr")
    assert h.open_store(out).sizes["time"] == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="holds no"):
        h.ingest_lab_hycom(empty, fx["box"], tmp_path / "e.zarr", "in_situ")
    with pytest.raises(ValueError, match="no lab-HYCOM points"):
        h.ingest_lab_hycom(fx["zlevel_dir"], (40, 41, 10, 11), tmp_path / "f.zarr", "in_situ")
    mixed = tmp_path / "mixed"
    mixed.mkdir()
    import xarray as xr
    a = xr.open_dataset(sorted(fx["zlevel_dir"].glob("*.nc"))[0]).load()
    b = xr.open_dataset(sorted(fx["zlevel_dir"].glob("*.nc"))[1]).load()
    b.attrs["temperature_kind"] = "potential"
    a.to_netcdf(mixed / "a.nc"); b.to_netcdf(mixed / "b.nc")
    with pytest.raises(ValueError, match="disagree"):
        h.ingest_lab_hycom(mixed, fx["box"], tmp_path / "m.zarr")


def test_fixture_script_is_deterministic_and_matches_the_committed_files(fx, tmp_path):
    import xarray as xr
    again = mk.make(tmp_path / "again")
    a, b = xr.open_zarr(fx["gofs_zarr"], consolidated=False), xr.open_zarr(again["gofs_zarr"], consolidated=False)
    assert np.array_equal(a.water_u.values, b.water_u.values, equal_nan=True)
    assert (fx["archv_dir"] / "archv.2023_060_12.a").read_bytes() == (again["archv_dir"] / "archv.2023_060_12.a").read_bytes()
    committed = pathlib.Path(mk.__file__).parent / "data"
    assert committed.is_dir() and (committed / "archv_dir" / "archv.2023_060_12.a").read_bytes() == (again["archv_dir"] / "archv.2023_060_12.a").read_bytes()
    assert mk.make.__doc__


def test_fixture_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["make_fixtures", str(tmp_path / "cli")])
    runpy.run_module("tests.fixtures.hycom.make_fixtures", run_name="__main__")
    assert (tmp_path / "cli" / "gofs.zarr").exists() and "archv_dir" in capsys.readouterr().out


# ------------------------------------------------------------------ receipts


def test_receipts_pass_and_cover_both_readers():
    R.OUT.clear()
    assert h.receipts()
    mine = [r for r in R.OUT if r["group"] == "Ocean (HYCOM / TEOS-10)"]
    assert len(mine) == 16 and all(r["ok"] for r in mine)
    claims = " ".join(r["claim"] for r in mine)
    assert "GSW check values" in claims and "archv" in claims and "hybrid layers" in claims and "too warm" in claims
    dens = next(r for r in mine if r["claim"].startswith("in-situ density"))
    assert dens["error"] < 2e-7


def _failing(monkeypatch_fn):
    R.OUT.clear()
    monkeypatch_fn()
    h.receipts()
    return [r["claim"] for r in R.OUT if r["ok"] is False]


def test_reading_in_situ_as_potential_fails_the_density_receipts(monkeypatch):
    import gsw
    bad = _failing(lambda: monkeypatch.setattr(gsw, "CT_from_t", lambda sa, t, p: gsw.CT_from_pt(sa, t)))
    assert any(c.startswith("in-situ density") for c in bad) and any(c.startswith("sound speed") for c in bad)
    assert not any("lab HYCOM" in c for c in bad)           # the lab round trip and its truth share the chain: only the check cast sees it


def test_a_pressure_unit_error_fails_the_layered_and_archv_receipts(monkeypatch):
    bad = _failing(lambda: monkeypatch.setattr(h, "ONEM", 9806.0 * 10))
    assert any("archv" in c for c in bad) and any("hybrid layers" in c for c in bad)
    assert not any(c.startswith("in-situ density") for c in bad)


def test_metres_used_as_dbar_fails_the_check_cast(monkeypatch):
    import gsw
    bad = _failing(lambda: monkeypatch.setattr(gsw, "p_from_z", lambda z, lat: -z))          # metres used as dbar: ~1 % off at depth
    assert any(c.startswith("in-situ density") for c in bad)


def test_default_main_runs_the_receipts(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["hycom"])
    R.OUT.clear()
    runpy.run_module("cafe.pm.env.hycom", run_name="__main__")
    assert "PASS" in capsys.readouterr().out
