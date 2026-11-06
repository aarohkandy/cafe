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
    from the fixture parts. mode: 'ok' | 'hang' (sleeps 60 s) | 'error' (HTTP 500) | 'html' (200, not NetCDF) | 'shift' (data + 1) | 'nan' (every value NaN).
    fail: datasets that always answer 500."""

    def __init__(self, parts_dir):
        import xarray as xr
        self.data = {}
        for d in h.DATASETS:
            fs = sorted(pathlib.Path(parts_dir).glob(f"{d}_*.nc"))
            self.data[d] = xr.concat([xr.open_dataset(f).load() for f in fs], dim="time").sortby("time")
        self.mode, self.fail, self.log, self.empty = "ok", set(), [], set()          # empty: datasets answered with a NetCDF that has no time step
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
        if ds in self.empty:
            a = a.isel(time=slice(0, 0))
        if self.mode == "shift":
            a = a + 1.0
        if self.mode == "nan":
            a = a * np.nan
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
    assert list(h.gofs_steps("2023-03-01T13:00:00Z", "2023-03-01T14:00:00Z")) == [mk.T0, mk.T0 + 10800.0]      # r7 M-24: the steps that cover the window
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


def test_std_takes_lon_into_0_360_unless_the_caller_has_put_it_in_a_box_frame(truth):
    ds = truth.isel(time=slice(0, 1)).assign_coords(lon=truth.lon.values - 360.0)
    np.testing.assert_allclose(h._std(ds).lon.values, truth.lon.values)                                    # the GOFS and fixture callers: 0..360 as before
    np.testing.assert_allclose(h._std(ds, wrap=False).lon.values, truth.lon.values - 360.0)                # a box next to 0 E keeps its neighbour at -0.5


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
    with pytest.raises(ValueError, match="no 3-hourly"):                  # r7 M-24: a window between two steps has both; only an end before the start has none
        h.fetch_gofs(mk.BOX, mk.T0 + 86400, mk.T0, tmp_path)


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


def _store_with_nan_at(h_open, node):
    """h.open_store that returns the store with water_temp masked at `node` (it, iz, ij, ii)."""
    it, iz, ij, ii = node

    def open_store(*a, **k):
        ds = h_open(*a, **k).load()
        ds["water_temp"][dict(time=it, depth=iz, lat=ij, lon=ii)] = np.nan
        return ds
    return open_store


@pytest.mark.parametrize("store_nan, server, want", [(False, "nan", np.inf), (True, "ok", np.inf), (True, "nan", 0.0)],
                         ids=["server-all-NaN", "store-NaN", "both-NaN-agree"])
def test_r10_m20_a_node_masked_on_one_side_only_is_infinitely_far_and_on_both_sides_agrees(fx, ncss, tmp_path, monkeypatch, store_nan, server, want):
    """Round 10 M-20: `max(worst, nan)` keeps worst, so a NaN store value, an all-NaN server answer and the two together all returned 0.0, the
    value of a store that agrees. NaN on both sides (below the sea floor) stays 0.0."""
    nodes = [(0, 3, 2, 4)]
    ncss.mode = server
    if store_nan:
        monkeypatch.setattr(h, "open_store", _store_with_nan_at(h.open_store, nodes[0]))
    assert h.check_node(fx["gofs_zarr"], nodes, ncss.base, 60, tmp_path) == want


def test_r10_m20_a_masked_node_is_not_hidden_behind_an_agreeing_one(fx, ncss, tmp_path, monkeypatch):
    monkeypatch.setattr(h, "open_store", _store_with_nan_at(h.open_store, (0, 3, 2, 4)))
    assert h.check_node(fx["gofs_zarr"], [(2, 6, 4, 7), (0, 3, 2, 4)], ncss.base, 60, tmp_path) == np.inf


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
        h.read_lab_netcdf(min(fx["layered_dir"].glob("*.nc")))
    ds, kind = h.read_lab_netcdf(min(fx["zlevel_dir"].glob("*.nc")))                  # carries the attribute
    assert kind == "in_situ" and np.allclose(ds.depth.values, mk.DEPTH)
    ds, kind = h.read_lab_netcdf(min(fx["layered_dir"].glob("*.nc")), "potential")
    assert kind == "potential" and len(ds.depth) == 40
    import xarray as xr
    f = xr.open_dataset(min(fx["layered_dir"].glob("*.nc"))).load()
    f["temperature"].attrs["temperature_kind"] = "potential"
    f.to_netcdf(tmp_path / "var_attr.nc")
    assert h.read_lab_netcdf(tmp_path / "var_attr.nc")[1] == "potential"
    with pytest.raises(ValueError, match="in_situ"):
        h.ingest_lab_hycom(fx["layered_dir"], fx["box"], tmp_path / "n.zarr")           # kind never guessed at ingest either


def test_lab_netcdf_schema_names_every_problem(fx, tmp_path):
    import xarray as xr
    f = xr.open_dataset(min(fx["layered_dir"].glob("*.nc"))).load()
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
    src = min(fx["zlevel_dir"].glob("*.nc"))
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
    out = h.ingest_lab_hycom(min(fx["zlevel_dir"].glob("*.nc")), fx["box"], tmp_path / "three.zarr")
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


def test_r5_m19_open_store_names_a_corrupt_or_missing_store_and_the_fix(fx, tmp_path):
    from cafe.pm.config import ConfigError
    bad = tmp_path / "gofs.zarr"
    shutil.copytree(fx["gofs_zarr"], bad)
    (bad / "zarr.json").write_text("{not json")
    for cache in (True, False):
        with pytest.raises(ConfigError, match=r"environment cache file .*gofs\.zarr cannot be read .*delete .* and run `python -m cafe.pm fetch"):
            h.open_store(bad, cache=cache)
    with pytest.raises(ConfigError, match="cannot be read"):
        h.open_store(tmp_path / "absent.zarr")


def test_r6_m7_the_remedy_names_the_store_itself_never_its_parent_and_a_lab_store_is_restored(fx, tmp_path):
    from cafe.pm.config import ConfigError
    ocean = tmp_path / "ocean"
    ocean.mkdir()
    bad, other, lab = ocean / "gofs_m.zarr", ocean / "gofs_other.zarr", ocean / "lab_m.zarr"
    for p in (bad, other, lab):
        shutil.copytree(fx["gofs_zarr"], p)
    for p in (bad, lab):
        (p / "zarr.json").write_text("{not json")
    with pytest.raises(ConfigError) as e:
        h.open_store(bad)
    msg = str(e.value)
    assert f"delete {bad} and run `python -m cafe.pm fetch" in msg and str(other) not in msg and f"delete {ocean} " not in msg
    with pytest.raises(ConfigError) as e:
        h.open_store(lab)                                                       # not a gofs* name: the lab's, which cannot be downloaded again
    assert f"restore {lab} from the lab's source" in str(e.value) and "delete" not in str(e.value) and "cannot download it" in str(e.value)
    with pytest.raises(ConfigError, match="restore .*gofs_m.zarr from the lab's source"):
        h.open_store(bad, lab=True)                                             # the mission says so: the name does not matter
    with pytest.raises(ConfigError, match="delete .*lab_m.zarr and run"):
        h.open_store(lab, lab=False)


# ---- review round 7: M-3 (the manifest pins the box), M-30 (an unusable part is removed), M-24 (steps cover the window), M-36 (depth order, all-NaN refusal)

def test_r7_m3_a_changed_box_fetches_every_part_again_and_the_store_has_no_holes_of_the_old_box(fx, truth, ncss, tmp_path, capsys):
    """A first fetch of a smaller box for one step, then the fixture box over three into the same directory: part names are the same and every
    hash matched, so the old step 0 (cut to the small box) was mixed in and the outer join made NaN holes (0.468 against 0.024 NaN share in the demo)."""
    small = (-0.04, 0.04, 179.92, 180.4)
    h.fetch_gofs(small, mk.STEPS[0], mk.STEPS[0], tmp_path, chunk_steps=1, workers=2, deadline_s=120, tries=1, ncss=ncss.base, dods="/nonexistent")
    n = len(ncss.log)
    capsys.readouterr()
    z = h.fetch_gofs(mk.BOX, mk.STEPS[0], mk.STEPS[-1], tmp_path, chunk_steps=1, workers=2, deadline_s=120, tries=1, ncss=ncss.base, dods="/nonexistent")
    said = capsys.readouterr().out
    _same(h.open_store(z), truth)                                                   # step 0 was the small box's: NaN where the truth has water (outer join)
    assert len(ncss.log) - n == 9                                                   # 3 datasets x 3 steps: not one of the 3 old parts was kept
    assert "were cut to [-0.04, 0.04, 179.92, 180.4]" in said and "all 9 parts are fetched again" in said
    assert json.loads((tmp_path / "gofs_tepex_c.parts" / "manifest.json").read_text())["box"] == list(h.box360(mk.BOX))


def test_r7_m3_a_grown_box_asks_the_server_again_and_the_same_box_still_asks_for_nothing(fx, truth, ncss, tmp_path):
    kw = dict(chunk_steps=1, workers=2, deadline_s=120, tries=1, ncss=ncss.base, dods="/nonexistent")
    h.fetch_gofs(mk.BOX, mk.STEPS[0], mk.STEPS[-1], tmp_path, **kw)
    n = len(ncss.log)
    h.fetch_gofs(mk.BOX, mk.STEPS[0], mk.STEPS[-1], tmp_path, **kw)
    assert len(ncss.log) == n                                                        # same box: resumed from the hashes
    grown = (mk.BOX[0] - 0.1, mk.BOX[1] + 0.1, mk.BOX[2] - 0.1, mk.BOX[3] + 0.1)
    h.fetch_gofs(grown, mk.STEPS[0], mk.STEPS[-1], tmp_path, **kw)
    assert len(ncss.log) - n == 9                                                    # 0 before: every part was a "hash match" and the store kept the old extent


def test_r7_m3_parts_cut_to_different_boxes_are_refused_not_joined_into_holes(fx, tmp_path):
    import warnings

    import xarray as xr
    p = tmp_path / "parts"
    shutil.copytree(fx["gofs_parts"], p)
    man = json.loads((p / "manifest.json").read_text())
    victim = sorted(fn for fn, r in man["parts"].items() if r["dataset"] == "ts3z")[0]
    a = xr.open_dataset(p / victim).load()
    a.isel(lat=slice(1, -1), lon=slice(2, -2)).to_netcdf(p / "cut.nc")
    (p / "cut.nc").replace(p / victim)
    man["parts"][victim]["sha256"] = h._sha(p / victim)
    (p / "manifest.json").write_text(json.dumps(man))
    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)                                  # the xarray default join must never decide (it warned, then will raise)
        with pytest.raises(ValueError, match=r"ts3z parts in .*parts were cut to different boxes.*delete .*parts and run fetch again"):
            h.assemble_gofs(p, mk.STEPS, tmp_path / "x.zarr")
        h.assemble_gofs(fx["gofs_parts"], mk.STEPS, tmp_path / "ok.zarr")              # and the ordinary store carries no FutureWarning either


def test_r7_m30_an_unusable_part_is_removed_with_its_entry_and_the_rerun_downloads_it_again(fx, truth, ncss, tmp_path):
    """A server answered one dataset with a NetCDF that holds no time step; the part was recorded by hash, so the rerun made 0 requests and failed alike."""
    ncss.empty = {"uv3z"}
    parts = tmp_path / "gofs_tepex_c.parts"
    with pytest.raises(h.FetchError, match=r"the part uv3z_\S+\.nc was unusable \(OSError: .*Unknown file format.*\); it has been removed: "
                                           "rerun fetch to download it again"):
        _fetch(tmp_path, ncss, chunk_steps=3)
    man = json.loads((parts / "manifest.json").read_text())
    assert not list(parts.glob("uv3z_*")) and {r["dataset"] for r in man["parts"].values()} == {"ts3z", "ssh"}          # the file and its entry are gone
    ncss.empty = set()
    n = len(ncss.log)
    z = _fetch(tmp_path, ncss, chunk_steps=3)
    assert [d for d, _ in ncss.log[n:]] == ["uv3z"]                                      # only the removed part is asked for (0 requests before)
    _same(h.open_store(z), truth)


def test_r7_m30_a_part_with_no_time_step_is_unusable_too(fx, tmp_path):
    import netCDF4
    p = tmp_path / "parts"
    shutil.copytree(fx["gofs_parts"], p)
    man = json.loads((p / "manifest.json").read_text())
    ssh = sorted(fn for fn, r in man["parts"].items() if r["dataset"] == "ssh")
    for victim in ssh:
        with netCDF4.Dataset(p / victim, "w") as nc:                                   # a valid NetCDF whose unlimited time dimension holds nothing
            nc.createDimension("time", None)
            nc.createVariable("time", "f8", ("time",))
        man["parts"][victim]["sha256"] = h._sha(p / victim)
    (p / "manifest.json").write_text(json.dumps(man))
    with pytest.raises(h.FetchError, match=rf"(?s)the part {ssh[0]} was unusable \(ValueError: no time step in it\); the part {ssh[1]} was unusable "
                                           ".*; they have been removed: rerun fetch to download them again"):
        h.assemble_gofs(p, mk.STEPS, tmp_path / "x.zarr")
    assert not any((p / v).exists() for v in ssh) and not set(ssh) & set(json.loads((p / "manifest.json").read_text())["parts"])


def test_r7_m24_the_steps_cover_the_window_and_an_aligned_window_gets_its_own():
    s = h.gofs_steps("2023-03-01T13:00:00Z", "2023-03-02T13:00:00Z")
    assert s[0] == mk.T0 and s[-1] == mk.T0 + 86400 + 10800.0 and s[0] <= h.epoch("2023-03-01T13:00:00Z") and s[-1] >= h.epoch("2023-03-02T13:00:00Z")
    assert np.array_equal(h.gofs_steps("2023-03-01T12:00:00Z", "2023-03-02T12:00:00Z"), mk.T0 + 10800.0 * np.arange(9))


def test_r7_m36_a_z_level_file_listing_depth_deepest_first_reads_like_the_ordered_one(fx, tmp_path):
    import xarray as xr
    src = min(fx["zlevel_dir"].glob("*.nc"))
    good, _ = h.read_lab_netcdf(src)
    xr.open_dataset(src).load().isel(depth=slice(None, None, -1)).to_netcdf(tmp_path / "rev.nc")
    rev, _ = h.read_lab_netcdf(tmp_path / "rev.nc")
    assert np.array_equal(rev.depth.values, good.depth.values) and np.isfinite(rev.water_temp.values).mean() > 0.9 * np.isfinite(good.water_temp.values).mean()
    for v in ("water_temp", "salinity", "water_u", "water_v"):
        assert np.array_equal(rev[v].values, good[v].values, equal_nan=True), v


def test_r7_m36_a_lab_file_whose_field_is_all_nan_is_refused_with_the_file_named(fx, tmp_path):
    import xarray as xr
    from cafe.pm.config import ConfigError
    d = tmp_path / "lab"
    d.mkdir()
    f = xr.open_dataset(min(fx["zlevel_dir"].glob("*.nc"))).load()
    f.assign(temp=f.temp * np.nan).to_netcdf(d / "nan.nc")
    with pytest.raises(ConfigError, match=r"nan\.nc: every value of water_temp is NaN after reading \(.*check the depth axis and the variable names\)"):
        h.ingest_lab_hycom(d, fx["box"], tmp_path / "x.zarr", "in_situ")


# ---- review round 8: M-29 (a coarse lab grid is cut so that the store still brackets the box) and M-30 (snapshots go in by time)


@pytest.mark.parametrize("step", [0.25, 0.5, 1.0])
@pytest.mark.parametrize("wrap", [False, True])
def test_r8_m29_the_cut_of_a_coarse_lab_grid_always_brackets_the_box_to_the_ingest_checks_tolerance(step, wrap):
    import xarray as xr
    box = s, n, w, e = (-0.12, 0.12, 179.84, 180.48)
    bad = []
    for off in np.linspace(0.0, step, 9)[:-1]:
        lat = np.arange(-4.0, 4.0, step) + off
        lon = 170.0 + np.arange(0.0, 20.0, step) + off
        lon = np.where(lon > 180.0, lon - 360.0, lon) if wrap else lon                       # the lab file may write the dateline as -180..180
        ds = xr.Dataset({"x": (("lat", "lon"), np.zeros((len(lat), len(lon))))}, coords=dict(lat=lat, lon=lon))
        out = h._sub(ds, box)
        la, lo = out.lat.values, out.lon.values
        if not (la.min() <= s + 0.1 and la.max() >= n - 0.1 and lo.min() <= w + 0.1 and lo.max() >= e - 0.1):            # what pipeline._ocean_cached asks
            bad.append(round(float(off), 3))
        assert (np.diff(lo) > 0).all() and (np.diff(la) > 0).all() and lo.min() >= 0 and lo.max() < 360
        assert la.min() >= s - 0.1 - step and la.max() <= n + 0.1 + step                      # at most one extra point per edge
        assert lo.min() >= w - 0.1 - step and lo.max() <= e + 0.1 + step
    assert bad == []                                                                         # for 0.5 and 1 deg, most offsets failed before


def test_r8_m29_a_fine_grid_is_cut_as_before(tmp_path):
    """The pad alone brackets a grid finer than 0.2 deg: the extra points are for coarse grids only (the fixture's 0.04 x 0.08 deg store has none)."""
    import xarray as xr
    lat, lon = np.arange(-1.0, 1.0, 0.04), 179.0 + np.arange(0.0, 3.0, 0.08)
    ds = xr.Dataset({"x": (("lat", "lon"), np.zeros((len(lat), len(lon))))}, coords=dict(lat=lat, lon=lon))
    out = h._sub(ds, (-0.12, 0.12, 179.84, 180.48))
    assert out.lat.values.min() >= -0.22 and out.lat.values.max() <= 0.22 and out.lon.values.min() >= 179.74 and out.lon.values.max() <= 180.58
    with pytest.raises(ValueError, match="no lab-HYCOM points"):
        h._sub(ds, (40.0, 41.0, 10.0, 11.0))


SEAM_BOXES = [(-0.12, 0.12, 0.3, 0.8),                       # within a grid step east of 0 E: the western neighbour lies across it (below 0)
              (-0.12, 0.12, 359.2, 359.95)]                  # within a grid step west of 0 E: the eastern neighbour lies across it (above 360)


@pytest.mark.parametrize("box", SEAM_BOXES)
@pytest.mark.parametrize("step", [0.5, 1.0])
@pytest.mark.parametrize("wrap", [False, True])
def test_r8_m29_a_box_next_to_0_e_is_cut_with_the_neighbours_across_it_in_one_continuous_axis(box, step, wrap):
    """`box360` refuses a box across 0 E, not one next to it, whose bracketing neighbour on a coarse grid lies across it. The store's lon axis is
    continuous with the box (359.5 is stored as -0.5, 0.5 as 360.5), so it brackets the box in the frame `pipeline._ocean_cached` compares it in. Stored
    mod 360 (the first version of this fix) the axis had a hole there, and a box 0.3 E failed the check for good."""
    import xarray as xr
    s, n, w, e = box
    bad, across = [], 0
    for off in np.linspace(0.0, step, 9)[:-1]:
        lat = np.arange(-4.0, 4.0, step) + off
        lon = np.arange(-5.0, 5.0, step) + off
        lon = lon if wrap else np.mod(lon, 360.0)                                           # the lab file writes -180..180 or 0..360
        ds = xr.Dataset({"x": (("lat", "lon"), np.zeros((len(lat), len(lon))))}, coords=dict(lat=lat, lon=lon))
        out = h._sub(ds, box)                                                                # ValueError "no lab-HYCOM points" with the plain longitude
        la, lo = out.lat.values, out.lon.values
        if not (la.min() <= s + 0.1 and la.max() >= n - 0.1 and lo.min() <= w + 0.1 and lo.max() >= e - 0.1):            # what pipeline._ocean_cached asks
            bad.append(round(float(off), 3))
        assert (np.diff(lo) > 0).all() and (np.diff(lo) <= step + 1e-9).all()               # increasing, no hole
        assert lo.min() >= w - 0.1 - step and lo.max() <= e + 0.1 + step                      # at most one extra point per edge, none from the far side
        across += int(lo.min() < 0.0 or lo.max() > 360.0)
    assert bad == [] and across > 0                                                          # and the offsets put a neighbour across 0 E


@pytest.mark.parametrize("lon0,step,box,kept", [(-3.5, 1.0, (-0.12, 0.12, 0.3, 0.8), [-0.5, 0.5, 1.5]),               # 1 deg across 0 E: 359.5 and 1.5 beyond
                                                (175.25, 1.5, (-0.12, 0.12, 179.84, 180.48), [179.75, 181.25])])   # 1.5 deg: 181.25 is beyond the 0.5 deg read
def test_r8_m29_a_coarse_archv_grid_is_read_wide_enough_for_the_store_to_bracket_the_box(fx, tmp_path, lon0, step, box, kept):
    """The archv reader cut 0.5 deg around the box before `_sub` asked for the neighbour beyond an edge, so a grid coarser than 0.4 deg left it nothing to
    keep, and the one next to 0 E dropped the neighbour across it. Only the grid files are replaced: the fields are the fixture's 9 x 7."""
    from cafe.pm import pipeline
    d = tmp_path / "archv"
    shutil.copytree(fx["archv_dir"], d)
    plon, plat = np.tile(lon0 + step * np.arange(9.0), (7, 1)), np.tile((-3.0 + np.arange(7.0))[:, None], (1, 9))      # and 1 deg in latitude
    (d / "regional.grid.b").write_text("    9    'idm   ' = x\n    7    'jdm   ' = y\nplon:  min,max =  0 1\nplat:  min,max =  0 1\n")
    (d / "regional.grid.a").write_bytes(mk._rec_a(plon, 9, 7) + mk._rec_a(plat, 9, 7))
    store = h.ingest_lab_hycom(d, box, tmp_path / "coarse.zarr", "in_situ", grid=d / "regional.grid", depth=fx["depth"])
    lon = h.open_store(store).lon.values
    assert pipeline._ocean_cached(store, box, fx["steps"], (fx["steps"][0], fx["steps"][-1]))              # False before: no neighbour beyond the edges
    assert lon.tolist() == kept and h.open_store(store).lat.values.tolist() == [-1.0, 0.0, 1.0]


def _seam_lab(fx, tmp_path, signed):
    """The fixture's z-level snapshots with their longitudes replaced by a 1 deg grid across 0 E (-3.5 ... 4.5), written -180..180 or 0..360."""
    import xarray as xr
    d = tmp_path / ("signed" if signed else "unsigned")
    d.mkdir()
    lon = -3.5 + np.arange(9.0)
    for f in sorted(fx["zlevel_dir"].glob("*.nc")):
        xr.open_dataset(f).load().assign_coords(lon=lon if signed else np.mod(lon, 360.0)).to_netcdf(d / f.name)
    return d


@pytest.mark.parametrize("signed", [True, False])
def test_r8_m29_a_lab_ocean_next_to_0_e_passes_the_ingest_check_and_every_reader_of_its_lon_agrees(fx, tmp_path, signed):
    """End to end for a box at 0.3 to 0.8 E on a 1 deg lab grid (points at -0.5, 0.5, 1.5 ...): the store passes `_ocean_cached` (it did not, and the
    advice to ingest again wrote the same store), and the readers of its lon take a query into the axis's own frame whatever convention it is given in."""
    from cafe.pm import pipeline
    from cafe.pm.env.ocean import Ocean, open_ocean
    box = (-0.12, 0.12, 0.3, 0.8)
    store = h.ingest_lab_hycom(_seam_lab(fx, tmp_path, signed), box, tmp_path / "seam.zarr", "in_situ")
    lon = h.open_store(store).lon.values
    assert lon.tolist() == [-0.5, 0.5, 1.5]
    assert pipeline._ocean_cached(store, box, fx["steps"], (fx["steps"][0], fx["steps"][-1]))
    oc, t = Ocean(store, None, lab=True), float(fx["steps"][0])
    col = oc.ds.water_u.isel(time=0, depth=1, lat=3, lon=[0, 1]).values.astype(float)                       # lat 0.0, depth 10 m: the columns at -0.5 and 0.5
    for q in (0.35, 360.35, -359.65):                                                                        # one place in three spellings
        assert oc.inside(q, 0.0, t) and np.allclose(oc.current(q, 0.0, -10.0, t).value[0], col[0] + (col[1] - col[0]) * 0.85)
    assert oc.inside(359.9, 0.0, t) and not oc.inside(2.0, 0.0, t) and not oc.inside(359.0, 0.0, t)        # -0.1 is in the axis, 2.0 and -1.0 are not
    assert np.isfinite(oc.temperature(359.7, 0.0, -10.0, t).value)
    assert oc.bounds()[:2] == (-0.5, 1.5)
    oc2 = open_ocean(dict(source="lab_hycom", path=str(store)), tmp_path / "c", fetch_bathy=False)     # no box given: the store's extent
    assert oc2.bathymetry(359.7, 0.0).value > 0
    import xarray as xr
    wide = xr.Dataset(coords=dict(lat=[-5.0, 5.0], lon=lon))                                  # the store's lon, with a latitude range that does not bind
    margins = dict(pipeline.ocean_margins(wide, box, [("in", 0.5, 0.0), ("west", 359.9, 0.0)]))
    assert margins["in"] == pytest.approx(1.0) and margins["west"] == pytest.approx(0.4)      # 359.9 is 0.4 inside the western edge, not 358 outside the east


def _copies(fx, tmp_path, names):
    """The fixture's z-level snapshots (12Z, 15Z, 18Z by time) copied to `names` (a list of (source index, new name))."""
    d = tmp_path / "lab"
    d.mkdir(parents=True)
    src = sorted(fx["zlevel_dir"].glob("*.nc"))
    for i, name in names:
        shutil.copy(src[i], d / name)
    return d


def test_r8_m30_snapshots_go_into_the_store_by_time_not_by_file_name(fx, tmp_path):
    d = _copies(fx, tmp_path, [(0, "snap_2.nc"), (1, "snap_1.nc"), (2, "snap_0.nc")])           # names sort the wrong way round
    store = h.open_store(h.ingest_lab_hycom(d, fx["box"], tmp_path / "x.zarr", "in_situ"))
    assert np.array_equal(store.time.values, mk.STEPS)                                          # strictly increasing; reversed before
    ten = tmp_path / "ten"
    ten.mkdir()
    for i, name in ((0, "snap_9.nc"), (1, "snap_10.nc")):                                       # snap_10 sorts before snap_9
        shutil.copy(sorted(fx["zlevel_dir"].glob("*.nc"))[i], ten / name)
    assert np.array_equal(h.open_store(h.ingest_lab_hycom(ten, fx["box"], tmp_path / "y.zarr", "in_situ")).time.values, mk.STEPS[:2])


def test_r8_m30_the_same_snapshot_twice_is_refused_naming_both_files(fx, tmp_path):
    d = _copies(fx, tmp_path, [(0, "a.nc"), (1, "b.nc"), (0, "c.nc")])
    with pytest.raises(ValueError, match=r"a\.nc and c\.nc are the same time \(2023-03-01T12:00:00Z UTC\); remove one"):
        h.ingest_lab_hycom(d, fx["box"], tmp_path / "x.zarr", "in_situ")
    assert not (tmp_path / "x.zarr").exists()                                                   # refused before anything is written
    one = _copies(fx, tmp_path / "one", [(1, "only.nc")])
    assert h.open_store(h.ingest_lab_hycom(one, fx["box"], tmp_path / "z.zarr", "in_situ")).sizes["time"] == 1


def test_r8_m30_a_file_whose_time_cannot_be_read_is_left_to_the_reader_to_name(fx, tmp_path):
    d = tmp_path / "lab"
    d.mkdir()
    (d / "bad.nc").write_text("not a netCDF")
    assert h._snapshot_times(d / "bad.nc") == [] and h._snapshot_times(d / "missing.b") == []
    with pytest.raises(ValueError, match="IO backends"):                                         # the reader's own error, not masked by the time pass
        h.ingest_lab_hycom(d, fx["box"], tmp_path / "x.zarr", "in_situ")
    undecoded = _copies(fx, tmp_path / "u", [(0, "u.nc")])
    import xarray as xr
    f = xr.open_dataset(undecoded / "u.nc").load()
    f.assign_coords(time=np.arange(f.sizes["time"], dtype=float)).to_netcdf(undecoded / "u2.nc")
    assert h._snapshot_times(undecoded / "u2.nc") == []


# ---- review round 9: M-5 (a store path that is, holds or lies inside the lab's source directory deleted the source)

def _lab_dir(fx, tmp_path):
    d = _copies(fx, tmp_path / "work", [(0, "snap_0.nc"), (1, "snap_1.nc"), (2, "snap_2.nc")])
    return d, sorted(p.name for p in d.iterdir())


@pytest.mark.parametrize("where", ["same", "parent", "via_symlink", "tmp_sibling"])
def test_r9_m5_a_store_that_is_holds_or_lies_inside_the_source_is_refused_and_the_source_survives(fx, tmp_path, where):
    from cafe.pm.config import ConfigError
    d, names = _lab_dir(fx, tmp_path)
    link = tmp_path / "link"
    link.symlink_to(d)
    out = dict(same=d, parent=d.parent, via_symlink=link, tmp_sibling=d)[where]
    if where == "tmp_sibling":
        d = d.rename(d.with_name("lab.zarr.tmp"))                       # the store lab.zarr would be built in lab.zarr.tmp, which is the source
        names = sorted(p.name for p in d.iterdir())
        out = d.with_name("lab.zarr")
    with pytest.raises(ConfigError, match="would delete the source"):
        h.ingest_lab_hycom(d, fx["box"], out, "in_situ")
    assert sorted(p.name for p in d.iterdir()) == names                 # every snapshot still there, no store written beside them


def test_l1_a_store_beside_the_lab_files_inside_their_directory_is_written_and_the_source_survives(fx, tmp_path):
    """The refusal also fired when the store merely lay inside the source directory, which deletes nothing (write_store removes the store and its .tmp
    sibling only, and the files are read from the directory itself): a lab that keeps lab.zarr beside its *.nc could not ingest."""
    d, names = _lab_dir(fx, tmp_path)
    for _ in range(2):                                                                  # the second run replaces the store it wrote beside the files
        out = h.ingest_lab_hycom(d, fx["box"], d / "lab.zarr", "in_situ")
        assert h.open_store(out).sizes["time"] == 3
        assert sorted(p.name for p in d.iterdir()) == sorted([*names, "lab.zarr"])


def test_r9_m5_a_single_source_file_is_refused_when_the_store_is_its_directory(fx, tmp_path):
    from cafe.pm.config import ConfigError
    d, names = _lab_dir(fx, tmp_path)
    with pytest.raises(ConfigError, match="would delete the source"):
        h.ingest_lab_hycom(d / "snap_0.nc", fx["box"], d, "in_situ")
    assert sorted(p.name for p in d.iterdir()) == names


def test_r9_m5_gofs_parts_are_protected_the_same_way(fx, tmp_path):
    from cafe.pm.config import ConfigError
    p = tmp_path / "parts"
    shutil.copytree(fx["gofs_parts"], p)
    before = sorted(x.name for x in p.iterdir())
    with pytest.raises(ConfigError, match="would delete the source"):
        h.assemble_gofs(p, mk.STEPS, p)
    assert sorted(x.name for x in p.iterdir()) == before


def test_r9_m5_a_non_empty_directory_that_is_no_zarr_store_is_not_replaced_but_an_old_store_and_an_empty_directory_are(fx, tmp_path):
    from cafe.pm.config import ConfigError
    d, _ = _lab_dir(fx, tmp_path)
    keep = tmp_path / "ocean"
    keep.mkdir()
    (keep / "notes.txt").write_text("not a store")
    with pytest.raises(ConfigError, match="no Zarr metadata or chunks"):
        h.ingest_lab_hycom(d, fx["box"], keep, "in_situ")
    assert (keep / "notes.txt").read_text() == "not a store"
    empty = tmp_path / "empty.zarr"
    empty.mkdir()
    store = tmp_path / "again.zarr"
    for out in (empty, store, store):                                   # an empty directory, then a fresh path, then the store just written
        assert h.open_store(h.ingest_lab_hycom(d, fx["box"], out, "in_situ")).sizes["time"] == 3


@pytest.mark.parametrize("damage", ["top_zarr_json", "all_metadata"])
def test_r9_f_a_lab_store_that_lost_its_metadata_is_repaired_by_the_ingest_that_unreadable_tells_the_user_to_run(fx, tmp_path, damage):
    from cafe.pm.config import ConfigError
    d, _ = _lab_dir(fx, tmp_path)
    store = tmp_path / "lab.zarr"
    h.ingest_lab_hycom(d, fx["box"], store, "in_situ")
    for f in [store / "zarr.json"] if damage == "top_zarr_json" else list(store.rglob("zarr.json")):
        f.unlink()
    with pytest.raises(ConfigError, match="ingest-ocean"):               # the advice: write the store again from the lab's source
        h.open_store(store)
    assert h.open_store(h.ingest_lab_hycom(d, fx["box"], store, "in_situ")).sizes["time"] == 3


@pytest.mark.parametrize("kind", ["netcdf", "archv"])
def test_r9_f_a_source_file_that_is_a_link_into_a_valid_store_is_refused_and_its_target_survives(fx, tmp_path, kind):
    from cafe.pm.config import ConfigError
    store = tmp_path / "lab.zarr"
    h.ingest_lab_hycom(_lab_dir(fx, tmp_path)[0], fx["box"], store, "in_situ")      # a valid store (it has zarr.json)
    src = tmp_path / "src"
    shutil.copytree(fx["archv_dir"] if kind == "archv" else fx["zlevel_dir"], src)
    snap = sorted(src.glob("*.a" if kind == "archv" else "*.nc"))[1:]               # all but one linked: the one real file must not hide the others
    for f in snap:
        shutil.move(f, store / f.name)
        f.symlink_to(store / f.name)
    kw = dict(depth=fx["depth"]) if kind == "archv" else {}
    keep = sorted(p.name for p in store.iterdir())
    with pytest.raises(ConfigError, match="would delete the source"):
        h.ingest_lab_hycom(src, fx["box"], store, "in_situ", **kw)
    assert sorted(p.name for p in store.iterdir()) == keep
