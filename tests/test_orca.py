"""cafe.pm.env.orca end to end: a mini orca tree (tests/fixtures/orca/make_fixtures.py) served over HTTP with byte ranges."""
import datetime as dt
import json

import netCDF4
import numpy as np
import pytest
import xarray as xr
from hypothesis import given, strategies as st

from cafe.pm.env import orca
from tests.fixtures.orca import make_fixtures as mk

BOX = (175.0, 185.0, -2.0, 2.0)          # lon 175..185 crosses the dateline, lat -2..2 crosses the equator
WJ, WI = (2, 6), (2, 9)                  # WRF index box this gives (nodes inside, plus one on each side)
UJ, UI = (1, 5), (2, 9)                  # UMWM index box


def t(h):
    return mk.T0 + dt.timedelta(hours=h)


def kept(stride=3):
    """Restart points expected inside the UMWM box on every stride-th box row and column (worked out from the mask)."""
    rc = [(j, i) for j in range(mk.UNY) for i in range(mk.UNX) if mk.SEAMASK[j, i]]
    return np.array([x for x, (j, i) in enumerate(rc) if UJ[0] <= j < UJ[1] and UI[0] <= i < UI[1]
                     and (j - UJ[0]) % stride == 0 and (i - UI[0]) % stride == 0])


def put_wrf(env, h, **kw):
    mk.write_wrf(env.root / f"wrfout_d01_{mk.stamp(h)}", h, **kw)


# ------------------------------------------------------------------ small pure functions

def test_schema_dir_is_overridable(tree, monkeypatch):
    monkeypatch.setenv("CAFE_SCHEMAS", str(tree.schemas))
    assert orca.schema("umwmrst")["variables"]["F"]["shape"] == [len(mk.SEA), mk.NTH, mk.NF]
    monkeypatch.delenv("CAFE_SCHEMAS")
    assert orca.schema("umwmrst")["variables"]["F"]["shape"] == [514120, 32, 37]      # the package's own copy
    monkeypatch.setenv("CAFE_SCHEMAS", "")
    assert orca.schema("wrfout")["global_attrs"]["MAP_PROJ"] == 3


def test_stamp_hours_urls(monkeypatch):
    monkeypatch.setattr(orca, "BASE", "http://h/run")
    assert orca.stamp(dt.datetime(2023, 3, 5, 7, 45)) == "2023-03-05_07:00:00"
    assert orca.urls(t(6)) == {"wrf": "http://h/run/wrfout_d01_2023-03-05_06:00:00",
                               "umwm": "http://h/run/output/umwmout_2023-03-05_06:00:00.nc",
                               "rst": "http://h/run/restart/umwmrst_2023-03-05_06:00:00.nc"}
    assert orca.hours(t(0), t(2)) == [t(0), t(1), t(2)]
    assert orca.hours(t(0), t(0) + dt.timedelta(minutes=119)) == [t(0), t(1), t(2)]      # the hours that cover the window (r7 M-17: it dropped the third file)
    assert orca.hours(t(3), t(0)) == []
    np.testing.assert_array_equal(orca.lon360(np.array([-180.0, -0.5, 0.0, 359.5, 360.0, -350.0])), [180, 359.5, 0, 359.5, 0, 10])


def test_schema_errors_name_the_variable(tree, monkeypatch):
    monkeypatch.setenv("CAFE_SCHEMAS", str(tree.schemas))
    ok = dict(dims=["Time", "south_north", "west_east"], dtype="float32", units="m s-1", shape=[1, mk.NY, mk.NX])
    orca.schema_errors("wrfout", {"U10": ok}, "u")
    bad = dict(ok, dims=["Time", "west_east", "south_north"], dtype="float64", units="knots", shape=[1, 3, 3])
    with pytest.raises(ValueError) as e:
        orca.schema_errors("wrfout", {"U10": bad, "V10": ok, "NOPE": ok}, "http://u")
    msg = str(e.value)
    assert msg.startswith("http://u: does not match") and "NOPE: not in" in msg
    for f in ("dims", "dtype", "units", "shape"):
        assert f"U10.{f} =" in msg
    assert "V10" not in msg


@pytest.mark.parametrize("box,want", [
    (BOX, (2, 6, 2, 9)),
    ((175.0, -175.0, -2.0, 2.0), (2, 6, 2, 9)),                          # the same box with the east edge written as -175
    ((-185.0, -175.0, -2.0, 2.0), (2, 6, 2, 9)),                         # and every longitude negative
    ((170.0, 192.0, -7.0, 7.0), (0, 8, 0, 12)),                          # the whole grid: margins clip at both ends
    ((171.0, 173.0, -7.0, -6.0), (0, 2, 0, 3)),                          # lowest row (clipped on the south)
    ((190.0, 192.0, 6.0, 7.0), (6, 8, 9, 12)),                           # highest row, last columns (clipped on the north)
])
def test_box_index_examples(box, want):
    assert orca.box_index(mk.WLAT, mk.WLON, box) == want


def test_box_index_across_the_prime_meridian():
    lon = (350.0 + 2.0 * np.arange(11)) % 360                           # 350, 352, ..., 358, 0, 2, ..., 10
    assert orca.box_index(np.arange(5.0), lon, (355.0, 5.0, 1.0, 3.0)) == (0, 5, 2, 9)
    assert orca.box_index(np.arange(5.0), np.where(lon > 180, lon - 360, lon), (-5.0, 5.0, 1.0, 3.0)) == (0, 5, 2, 9)


@pytest.mark.parametrize("box", [(175.0, 185.0, 20.0, 30.0), (100.0, 120.0, -2.0, 2.0), (175.0, 185.0, 7.5, 8.0)])
def test_box_index_outside_the_domain(box):
    with pytest.raises(ValueError, match="outside the model domain"):
        orca.box_index(mk.WLAT, mk.WLON, box)


@st.composite
def grid_and_box(draw):
    """Regular 1-D axes (exact in binary), stored 0..360 or -180..180, and a box inside them at least one cell wide."""
    d, ny_, nx_ = draw(st.sampled_from([1, 2, 4, 8, 16])), draw(st.integers(3, 50)), draw(st.integers(3, 50))
    lon0, lat0 = draw(st.integers(0, 359 * 4)) / 4, draw(st.integers(-90 * 4, 40 * 4)) / 4
    lon_u, lat = lon0 + d / 4 * np.arange(nx_), lat0 + d / 4 * np.arange(ny_)
    lon = np.mod(lon_u, 360)
    if draw(st.booleans()):
        lon = np.where(lon >= 180, lon - 360, lon)
    a_lon = draw(st.integers(0, (nx_ - 1) * 2 * d - 2 * d))
    w_lon = draw(st.integers(2 * d, (nx_ - 1) * 2 * d - a_lon))
    a_lat = draw(st.integers(0, (ny_ - 1) * 2 * d - 2 * d))
    w_lat = draw(st.integers(2 * d, (ny_ - 1) * 2 * d - a_lat))
    pt = (draw(st.integers(a_lon, a_lon + w_lon)), draw(st.integers(a_lat, a_lat + w_lat)))   # a requested point, in eighths
    edge = lambda e: e - 360 if draw(st.booleans()) and e >= 180 else e                        # noqa: E731
    box = (edge((lon0 + a_lon / 8) % 360), edge((lon0 + (a_lon + w_lon) / 8) % 360), lat0 + a_lat / 8, lat0 + (a_lat + w_lat) / 8)
    return lat, lon, box, pt, d / 4, lon0, lat0


@given(grid_and_box())
def test_box_index_brackets_every_requested_point(case):
    lat, lon, box, (pu, pv), dx, lon0, lat0 = case
    j0, j1, i0, i1 = orca.box_index(lat, lon, box)
    assert 0 <= j0 < j1 <= len(lat) and 0 <= i0 < i1 <= len(lon)
    for p, a0, a1 in ((pu / 8 / dx, i0, i1), (pv / 8 / dx, j0, j1)):    # the two nodes either side of the point are inside
        assert a0 <= np.floor(p) and np.ceil(p) < a1


@given(st.lists(st.integers(0, 400), unique=True, max_size=40), st.integers(1, 70))
def test_runs_cover_exactly_and_merge_by_gap(idx, gap):
    idx = np.sort(np.array(idx, dtype=int))
    sp = orca.runs(idx, gap)
    if not len(idx):
        assert sp == []
        return
    assert all(a < b for a, b in sp) and all(sp[k][1] <= sp[k + 1][0] for k in range(len(sp) - 1))
    for v in idx:
        assert sum(a <= v < b for a, b in sp) == 1                       # covered once
    assert all(a in idx and b - 1 in idx for a, b in sp)                 # spans start and end on requested indices
    for k in range(len(sp) - 1):
        assert sp[k + 1][0] - (sp[k][1] - 1) > gap                       # neighbours closer than `gap` were merged
    for a, b in sp:
        inside = idx[(idx >= a) & (idx < b)]
        assert np.all(np.diff(inside) <= gap)
    if gap == 1:
        assert sum(b - a for a, b in sp) == len(idx)                     # exact runs, no extra rows


def test_runs_examples():
    assert orca.runs(np.array([3, 4, 5, 9, 10, 40]), 1) == [(3, 6), (9, 11), (40, 41)]
    assert orca.runs(np.array([3, 4, 5, 9, 10, 40]), 64) == [(3, 41)]
    assert orca.runs(np.array([3, 4, 5, 9, 10, 40]), 5) == [(3, 11), (40, 41)]
    assert orca.runs([], 1) == [] and orca.runs(np.array([7]), 64) == [(7, 8)]


# ------------------------------------------------------------------ WRF

def test_wrf_grid(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    assert (g["j"], g["i"]) == (WJ, WI)
    for k in ("XLAT", "XLONG", "LANDMASK", "HGT", "COSALPHA", "SINALPHA"):
        np.testing.assert_array_equal(g[k], mk.wrf_static(k)[WJ[0]:WJ[1], WI[0]:WI[1]])
    np.testing.assert_array_equal(g["XLONG"][0], np.where(mk.WLON360[2:9] >= 180, mk.WLON360[2:9] - 360, mk.WLON360[2:9]))
    assert g["attrs"] == dict(MAP_PROJ=3, CEN_LAT=5.0, CEN_LON=-156.0, STAND_LON=204.0, TRUELAT1=10.0, DX=12000.0, DT=60.0,
                              SST_UPDATE=0, SF_OCEAN_PHYSICS=0, SIMULATION_START_DATE="2023-03-01_00:00:00",
                              TITLE=" OUTPUT FROM WRF V4.7.1 MODEL")


def test_wrf_grid_box_outside(orca_env):
    with pytest.raises(ValueError, match="outside the model domain"):
        orca.wrf_grid(t(0), (10.0, 20.0, -2.0, 2.0))


def test_wrf_grid_wrong_global_attribute(orca_env):
    put_wrf(orca_env, 0, attrs={"MAP_PROJ": 1, "DX": 4000.0})
    with pytest.raises(ValueError, match=r"global attributes differ.*MAP_PROJ.*\(1, 3\).*DX.*\(4000.0, 12000.0\)"):
        orca.wrf_grid(t(0), BOX)


@pytest.mark.parametrize("drift,var,field", [
    (dict(units={"U10": "knots"}), "U10", "units"),
    (dict(units={"PH": "m"}), "PH", "units"),
    (dict(dims={"V10": ("Time", "west_east", "south_north")}), "V10", "dims"),
    (dict(dtypes={"T2": "f8"}), "T2", "dtype"),
])
def test_wrf_grid_schema_drift_names_the_variable(orca_env, drift, var, field):
    put_wrf(orca_env, 0, **drift)
    with pytest.raises(ValueError, match=rf"{var}\.{field} = "):
        orca.wrf_grid(t(0), BOX)


def test_wrf_hour_2d(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    for h in (0, 1, 2):
        d = orca.wrf_hour(t(h), g)
        assert sorted(d) == sorted(orca.WRF2D + ["_bytes"])
        for k in orca.WRF2D:
            np.testing.assert_array_equal(d[k], mk.wrf2d(k, h)[WJ[0]:WJ[1], WI[0]:WI[1]])
            assert d[k].dtype == np.float32
        assert int(d["_bytes"]) == (orca_env.root / f"wrfout_d01_{mk.stamp(h)}").stat().st_size
    assert d["U10"][0, 0] == mk.wrf2d("U10", 2)[2, 2] == 1000 + 200 + 174 * 0.125 + (-3) * 0.0625


def test_wrf_hour_3d_destaggers_and_builds_heights(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    d = orca.wrf_hour(t(1), g, three_d=True)
    nj, ni, nz = WJ[1] - WJ[0], WI[1] - WI[0], orca.NZ3
    for name in ("U3", "V3", "Z3", "TH3"):
        assert d[name].shape == (nz, nj, ni)
    k, j, i = [a.astype(float) for a in np.meshgrid(np.arange(nz), WJ[0] + np.arange(nj), WI[0] + np.arange(ni), indexing="ij")]
    # U = i'^2 + 10k + 100j + h  at faces i' = i, i+1  ->  mass-point mean i^2 + i + 1/2 + 10k + 100j + h
    np.testing.assert_array_equal(d["U3"], i ** 2 + i + 0.5 + 10 * k + 100 * j + 1)
    # V = j'^2 + 10k + 100i + h  at faces j' = j, j+1
    np.testing.assert_array_equal(d["V3"], j ** 2 + j + 0.5 + 10 * k + 100 * i + 1)
    # w-level height 10 k^2 + j/2 + h (PH + PHB = g z); mass level = mean of the two bounding w levels
    np.testing.assert_allclose(d["Z3"], 10 * k ** 2 + 10 * k + 5 + j / 2 + 1, rtol=1e-5)
    np.testing.assert_array_equal(d["TH3"], 300 + k + i / 2 + 1)
    assert d["U3"].dtype == np.float32 and d["TH3"].dtype == np.float32
    assert "U3" not in orca.wrf_hour(t(1), g)


def test_wrf_hour_3d_variables_are_only_checked_when_read(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    put_wrf(orca_env, 1, units={"U": "knots"})
    assert "U10" in orca.wrf_hour(t(1), g)
    with pytest.raises(ValueError, match=r"U\.units = 'knots'"):
        orca.wrf_hour(t(1), g, three_d=True)


def test_wrf_hour_schema_drift(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    put_wrf(orca_env, 1, units={"SST": "C"})
    with pytest.raises(ValueError, match=r"SST\.units = 'C'"):
        orca.wrf_hour(t(1), g)


def test_wrf_hour_times_mismatch(orca_env):
    g = orca.wrf_grid(t(0), BOX)
    put_wrf(orca_env, 1, times=mk.stamp(5))
    with pytest.raises(ValueError, match="Times is 2023-03-05_05:00:00, expected 2023-03-05_01:00:00"):
        orca.wrf_hour(t(1), g)


# ------------------------------------------------------------------ UMWM output

def test_umwm_grid_and_hour(orca_env):
    g = orca.umwm_grid(t(0), BOX)
    assert (g["j"], g["i"]) == (UJ, UI)
    for k in orca.UMWMSTATIC:
        np.testing.assert_array_equal(g[k], mk.umwm_static(k)[UJ[0]:UJ[1], UI[0]:UI[1]])
    n = len(orca_env.requests("output/umwmout_2023-03-05_00:00:00.nc"))
    for h in (0, 2):
        d = orca.umwm_hour(t(h), g)
        assert sorted(d) == sorted(orca.UMWM2D)
        for k in orca.UMWM2D:
            np.testing.assert_array_equal(d[k], mk.umwm2d(k, h)[UJ[0]:UJ[1], UI[0]:UI[1]])
    assert np.isnan(d["swh"]).sum() == (mk.SEAMASK[UJ[0]:UJ[1], UI[0]:UI[1]] == 0).sum() > 0      # land stays NaN
    assert len(orca_env.requests("output/umwmout_2023-03-05_00:00:00.nc")) > n


def test_umwm_grid_reuses_a_header(orca_env):
    u = orca.urls(t(0))["umwm"]
    hdr = orca.remote.cdf1_header(u)
    name = "output/umwmout_2023-03-05_00:00:00.nc"
    before = len(orca_env.requests(name))
    g = orca.umwm_grid(t(0), BOX, hdr)
    assert g["hdr"] is hdr
    assert len(orca_env.requests(name)) - before == 2 + 4               # lat, lon, then rows of lon, lat, seamask, depth: 6 reads


def test_umwm_schema_drift(orca_env):
    mk.write_umwm(orca_env.root / "output" / f"umwmout_{mk.stamp(0)}.nc", 0, units={"swh": "ft"})
    with pytest.raises(ValueError, match=r"swh\.units = 'ft'"):
        orca.umwm_grid(t(0), BOX)
    mk.write_umwm(orca_env.root / "output" / f"umwmout_{mk.stamp(1)}.nc", 1, units={"cd": "1"})
    with pytest.raises(ValueError, match=r"cd\.units = '1'"):
        orca.umwm_hour(t(1), {"j": UJ, "i": UI})


def test_umwm_64bit_offset_file_reads_the_same(orca_env):
    g0 = orca.umwm_grid(t(0), BOX)
    mk.write_umwm(orca_env.root / "output" / f"umwmout_{mk.stamp(0)}.nc", 0, fmt="NETCDF3_64BIT_OFFSET")
    g1 = orca.umwm_grid(t(0), BOX)
    for k in orca.UMWMSTATIC:
        np.testing.assert_array_equal(g0[k], g1[k])


# ------------------------------------------------------------------ restart spectra

def test_spec_points(orca_env):
    ug = orca.umwm_grid(t(0), BOX)
    p = orca.spec_points(t(0), ug)
    want = kept()
    assert len(want) == 5 and mk.SEAMASK[4, 8] == 0                      # one kept node is land, so it is not a sea point
    np.testing.assert_array_equal(p["x"], want)
    lon, lat = mk.rst_points()
    np.testing.assert_array_equal(p["lon"], orca.lon360(lon[want]))      # restart longitudes are stored -180..180
    np.testing.assert_array_equal(p["lat"], lat[want])
    np.testing.assert_array_equal(p["f"], mk.rst_arrays(0)["frequency"])
    np.testing.assert_array_equal(p["th"], mk.rst_arrays(0)["theta"])
    assert p["hdr"][0]["x"] == len(mk.SEA)


@pytest.mark.parametrize("stride", [1, 2, 3, 5])
def test_spec_points_thinning_by_stride(orca_env, stride):
    ug = orca.umwm_grid(t(0), BOX)
    np.testing.assert_array_equal(orca.spec_points(t(0), ug, stride)["x"], kept(stride))


def test_spec_points_none_in_the_box(orca_env):
    ug = orca.umwm_grid(t(0), BOX)
    far = dict(ug, lon=ug["lon"] + 20.0)
    with pytest.raises(ValueError, match="no restart sea points inside the box"):
        orca.spec_points(t(0), far)


def test_spec_points_schema_drift(orca_env):
    ug = orca.umwm_grid(t(0), BOX)
    mk.write_rst(orca_env.root / "restart" / f"umwmrst_{mk.stamp(0)}.nc", 0, units={"F": "m2"})
    with pytest.raises(ValueError, match=r"F\.units = 'm2'"):
        orca.spec_points(t(0), ug)


def test_spec_hour_equals_reading_point_by_point(orca_env):
    ug = orca.umwm_grid(t(0), BOX)
    for stride in (3, 1):
        pts = orca.spec_points(t(0), ug, stride)
        for h in (0, 6):
            d = orca.spec_hour(t(h), pts)
            with netCDF4.Dataset(orca_env.root / "restart" / f"umwmrst_{mk.stamp(h)}.nc") as nc:
                F = np.stack([nc["F"][x] for x in pts["x"]])
                K = np.stack([nc["wavenumber"][x] for x in pts["x"]])
            np.testing.assert_array_equal(d["F"], F)
            np.testing.assert_array_equal(d["k"], K)
            np.testing.assert_array_equal(d["F"], mk.rst_arrays(h)["F"][pts["x"]])
            assert d["F"].shape == (len(pts["x"]), mk.NTH, mk.NF) and d["k"].shape == (len(pts["x"]), mk.NF)


def test_spec_hour_reads_one_range_per_merged_run(orca_env):
    ug = orca.umwm_grid(t(0), BOX)
    pts = orca.spec_points(t(0), ug)
    name = "restart/umwmrst_2023-03-05_06:00:00.nc"
    n = len(orca_env.requests(name))
    orca.spec_hour(t(6), pts)
    assert len(orca_env.requests(name)) - n == 1 + 2 * len(orca.runs(pts["x"], 64))     # header, then F and wavenumber per run


def test_spec_hour_different_sea_point_count(orca_env, monkeypatch):
    ug = orca.umwm_grid(t(0), BOX)
    pts = orca.spec_points(t(0), ug)
    mk.write_rst(orca_env.root / "restart" / f"umwmrst_{mk.stamp(6)}.nc", 6, sea=mk.SEA[:-3])
    with pytest.raises(ValueError, match=r"lon\.shape = \[50\], schema says \[53\]"):    # the schema pins the count first
        orca.spec_hour(t(6), pts)
    monkeypatch.setattr(orca, "schema_errors", lambda *a: None)                        # and the explicit guard behind it
    with pytest.raises(ValueError, match="50 sea points, the first restart had 53"):
        orca.spec_hour(t(6), pts)


# ------------------------------------------------------------------ ingest

def ingest(env, out, t0=0, t1=2, **kw):
    lines = []
    kw.setdefault("threads", 4)
    return orca.ingest(t(t0), t(t1), BOX, out, log=lines.append, **kw), lines


def zarr(out, name):
    return xr.open_zarr(out / name, chunks=None, consolidated=False)


def test_ingest_end_to_end(orca_env, tmp_path):
    out = tmp_path / "out"
    man, lines = ingest(orca_env, out, hours3d=[t(1)])
    assert lines[0] == "ingest: 7 parts, 0 cached, fetching 7 with 4 threads"
    when = np.array([np.datetime64(t(h).replace(tzinfo=None), "s") for h in range(3)])

    w = zarr(out, "wrf.zarr")
    np.testing.assert_array_equal(w.time.values, when)
    np.testing.assert_array_equal(w.lat.values, mk.WLAT[WJ[0]:WJ[1]])
    np.testing.assert_array_equal(w.lon.values, mk.WLON360[WI[0]:WI[1]])          # unwrapped to 0..360 across the dateline
    for k in orca.WRF2D:
        for h in range(3):
            np.testing.assert_array_equal(w[k].isel(time=h).values, mk.wrf2d(k, h)[WJ[0]:WJ[1], WI[0]:WI[1]])
    for k in ("LANDMASK", "HGT", "COSALPHA", "SINALPHA"):
        np.testing.assert_array_equal(w[k].values, mk.wrf_static(k)[WJ[0]:WJ[1], WI[0]:WI[1]])
    assert w.attrs["MAP_PROJ"] == "3" and w.attrs["source"] == orca_env.base

    d3 = zarr(out, "wrf3d.zarr")
    assert d3.U3.shape == (1, orca.NZ3, 4, 7) and np.array_equal(d3.time.values, when[1:2])
    ref = orca.wrf_hour(t(1), orca.wrf_grid(t(0), BOX), three_d=True)
    for k in ("U3", "V3", "Z3", "TH3"):
        np.testing.assert_array_equal(d3[k].values[0], ref[k])

    u = zarr(out, "umwm.zarr")
    np.testing.assert_array_equal(u.lat.values, mk.ULAT[UJ[0]:UJ[1]])
    np.testing.assert_array_equal(u.lon.values, mk.ULON[UI[0]:UI[1]])
    for k in orca.UMWM2D:
        for h in range(3):
            np.testing.assert_array_equal(u[k].isel(time=h).values, mk.umwm2d(k, h)[UJ[0]:UJ[1], UI[0]:UI[1]])
    np.testing.assert_array_equal(u.seamask.values, mk.SEAMASK[UJ[0]:UJ[1], UI[0]:UI[1]])
    np.testing.assert_array_equal(u.depth.values, mk.umwm_static("depth")[UJ[0]:UJ[1], UI[0]:UI[1]])

    sp, x = zarr(out, "umwmspec.zarr"), kept()
    assert np.array_equal(sp.time.values, when[:1]) and sp.attrs["stride"] == 3
    np.testing.assert_array_equal(sp.F.values[0], mk.rst_arrays(0)["F"][x])
    np.testing.assert_array_equal(sp.k.values[0], mk.rst_arrays(0)["wavenumber"][x])
    np.testing.assert_array_equal(sp.plon.values, orca.lon360(mk.rst_points()[0][x]))
    np.testing.assert_array_equal(sp.plat.values, mk.rst_points()[1][x])
    np.testing.assert_array_equal(sp.f.values, mk.rst_arrays(0)["frequency"])

    on_disk = json.loads((out / "manifest.json").read_text())
    assert on_disk["hours"] == 3 and on_disk["hours3d"] == ["2023-03-05_01:00:00"] == man["hours3d"]
    assert on_disk["wrf_index"] == dict(j=list(WJ), i=list(WI)) and on_disk["umwm_index"] == dict(j=list(UJ), i=list(UI))
    assert on_disk["parts"] == {p.name: orca.remote.sha256(p) for p in sorted((out / "hours").glob("*.npz"))}
    assert len(on_disk["parts"]) == 7
    assert on_disk["bytes_fetched"] == sum((orca_env.root / f"wrfout_d01_{mk.stamp(h)}").stat().st_size for h in range(3))


def test_ingest_resumes_from_cached_parts(orca_env, tmp_path):
    out = tmp_path / "out"
    first, _ = ingest(orca_env, out)
    n = len(orca_env.log)
    second, lines = ingest(orca_env, out)
    assert lines[0] == "ingest: 7 parts, 7 cached, fetching 0 with 4 threads"
    assert second["parts"] == first["parts"]
    hour_files = [name for name, _ in orca_env.log[n:] if name.endswith(mk.stamp(1)) or name.endswith(mk.stamp(2) + ".nc")]
    assert hour_files == []                                              # not one request for hour 1 or 2 of any file
    (out / "hours" / f"umwm_{mk.stamp(1)}.npz").unlink()
    third, lines = ingest(orca_env, out)
    assert lines[0] == "ingest: 7 parts, 6 cached, fetching 1 with 4 threads" and lines[-1].startswith("  1/1 parts")
    assert third["parts"] == first["parts"]


def test_r12_m29_the_manifest_lists_the_windows_parts_not_the_directorys(orca_env, tmp_path):
    """Window A, then a disjoint window B into the same cache, then A again: the stores are A's, so the manifest (whose hash keys the derived layer and is a
    ledger input) must be A's, the same bytes as a cold cache of A. It listed A's and B's parts."""
    out, clean = tmp_path / "out", tmp_path / "clean"
    cold, _ = ingest(orca_env, clean, 0, 2)
    ingest(orca_env, out, 0, 2)
    other, _ = ingest(orca_env, out, 4, 6)
    assert sorted(other["parts"]) == sorted([f"{k}_{mk.stamp(h)}.npz" for h in (4, 5, 6) for k in ("wrf", "umwm")] + [f"spec_{mk.stamp(6)}.npz"])
    again, _ = ingest(orca_env, out, 0, 2)
    assert again["parts"] == cold["parts"] and len(again["parts"]) == 7
    assert again == cold and (out / "manifest.json").read_bytes() == (clean / "manifest.json").read_bytes()
    for store in ("wrf.zarr", "umwm.zarr", "umwmspec.zarr"):
        assert orca.remote.tree_sha256(out / store) == orca.remote.tree_sha256(clean / store)
    assert len(list((out / "hours").glob("*.npz"))) == 14               # the other window's parts are still cached, just not this window's


def test_r12_m29_a_store_with_names_that_differ_only_in_case_has_no_consolidated_metadata(orca_env, tmp_path):
    """The spectrum store holds `F` and `f`; zarr sorts its consolidated metadata by case-folded name, so the two tie and come out in directory-listing
    order: two ingests of one window gave stores that differed in zarr.json alone (4 of 12 runs), and `tree_sha256` is a ledger input. Written without it
    the bytes do not depend on the listing. No store may be consolidated while two of its names fold together."""
    out = tmp_path / "out"
    ingest(orca_env, out, 0, 2)
    folded = 0
    for name in ("wrf.zarr", "umwm.zarr", "umwmspec.zarr"):
        names = [str(n) for n in zarr(out, name).variables]
        if len({n.casefold() for n in names}) < len(names):
            folded += 1
            assert json.loads((out / name / "zarr.json").read_text()).get("consolidated_metadata") is None, name
    assert folded == 1                                                  # umwmspec.zarr: the test would pass vacuously if the names stopped colliding


def test_r13_m8_only_hours_divisible_by_six_get_a_spectrum_part_and_no_spectra_means_none_in_the_manifest(orca_env, tmp_path):
    """The two M-29 tests above pass when `hour % 6` is `hour % 3` or when the spec_ names are listed without the spectra (older tests killed those mutants,
    not these): the window 0 to 3 holds hour 0 and hour 3, and a window with spectra=False holds hour 0 and no spec_ part."""
    man, _ = ingest(orca_env, tmp_path / "a", 0, 3)
    assert sorted(n for n in man["parts"] if n.startswith("spec_")) == [f"spec_{mk.stamp(0)}.npz"] and len(man["parts"]) == 9
    off, _ = ingest(orca_env, tmp_path / "b", 0, 2, spectra=False)
    assert not [n for n in off["parts"] if n.startswith("spec_")] and len(off["parts"]) == 6 and not (tmp_path / "b" / "umwmspec.zarr").exists()
    assert not list((tmp_path / "b" / "hours").glob("spec_*"))


def parts_of(out):
    return {p.name: p.stat().st_mtime_ns for p in (out / "hours").glob("*.npz")}


def test_the_manifest_records_the_box_and_a_changed_box_refetches_every_part(orca_env, tmp_path):
    out = tmp_path / "out"
    first, _ = ingest(orca_env, out, hours3d=[t(1)])
    assert first["box"] == list(BOX) == json.loads((out / "manifest.json").read_text())["box"]
    before = parts_of(out)
    marked = out / "hours" / f"umwm_{mk.stamp(0)}.npz"
    np.savez(marked, marker=np.arange(1))                                                       # stands in for a part cut to the old box
    smaller = (176.0, 184.0, -2.0, 2.0)
    lines = []
    second = orca.ingest(t(0), t(2), smaller, out, hours3d=[t(1)], threads=4, log=lines.append)
    assert lines[0] == "ingest: 7 parts, 0 cached, fetching 7 with 4 threads"                  # nothing cut to the old box is reused
    assert second["box"] == list(smaller) and set(parts_of(out)) == set(before)
    assert "marker" not in np.load(marked).files
    again = []
    orca.ingest(t(0), t(2), smaller, out, hours3d=[t(1)], threads=4, log=again.append)
    assert again[0] == "ingest: 7 parts, 7 cached, fetching 0 with 4 threads"                   # the same box resumes from the cached parts


def test_a_cache_with_no_cut_record_cannot_say_which_box_it_was_cut_to_and_is_refetched(orca_env, tmp_path):
    out = tmp_path / "out"
    ingest(orca_env, out)
    (out / "cut.json").unlink()                                                                  # a cache written before the box was recorded
    _, lines = ingest(orca_env, out)
    assert lines[0] == "ingest: 7 parts, 0 cached, fetching 7 with 4 threads"


def test_a_new_3d_hour_refetches_only_that_hours_wrf_part(orca_env, tmp_path):
    out = tmp_path / "out"
    ingest(orca_env, out, hours3d=[t(1)])
    assert zarr(out, "wrf3d.zarr").time.size == 1
    man, lines = ingest(orca_env, out, hours3d=[t(1), t(2)])
    assert lines[0] == "ingest: 7 parts, 6 cached, fetching 1 with 4 threads"
    assert man["hours3d"] == ["2023-03-05_01:00:00", "2023-03-05_02:00:00"] and zarr(out, "wrf3d.zarr").time.size == 2
    man, lines = ingest(orca_env, out, hours3d=[t(1)])                                           # fewer 3-D hours: nothing to fetch
    assert lines[0] == "ingest: 7 parts, 7 cached, fetching 0 with 4 threads" and man["hours3d"] == ["2023-03-05_01:00:00"]


def test_ingest_without_spectra_or_3d(orca_env, tmp_path):
    out = tmp_path / "out"
    man, lines = ingest(orca_env, out, t0=1, t1=2, spectra=False)
    assert lines[0].startswith("ingest: 4 parts") and man["hours3d"] == []
    assert not (out / "umwmspec.zarr").exists() and not (out / "wrf3d.zarr").exists()
    assert zarr(out, "wrf.zarr").time.size == 2


def test_ingest_two_restarts(orca_env, tmp_path):
    out = tmp_path / "out"
    man, _ = ingest(orca_env, out, t0=0, t1=6, threads=2)
    sp = zarr(out, "umwmspec.zarr")
    assert sp.time.size == 2 and man["hours"] == 7
    for n, h in enumerate((0, 6)):
        np.testing.assert_array_equal(sp.F.values[n], mk.rst_arrays(h)["F"][kept()])


def test_ingest_logs_progress_every_twenty_parts(orca_env, tmp_path):
    _, lines = ingest(orca_env, tmp_path / "out", t0=0, t1=6)           # 7 + 7 + 2 = 16 parts: only the last line
    assert lines[0].startswith("ingest: 16 parts") and lines[-1].startswith("  16/16 parts")


def test_ingest_window_without_a_restart_hour(orca_env, tmp_path):
    with pytest.raises(ValueError, match="no restart hour"):
        ingest(orca_env, tmp_path / "out", t0=1, t1=2)


def test_ingest_reversed_window(orca_env, tmp_path):
    with pytest.raises(ValueError, match="before"):
        ingest(orca_env, tmp_path / "out", t0=2, t1=0)


def test_ingest_stops_on_a_drifted_hour(orca_env, tmp_path):
    put_wrf(orca_env, 2, units={"U10": "knots"})
    with pytest.raises(ValueError, match=r"U10\.units = 'knots'"):
        ingest(orca_env, tmp_path / "out")


# ---- review round 6, M-8: the manifests are written atomically and an unreadable record is no record

def test_r6_m8_read_json_treats_an_empty_truncated_or_non_object_file_as_absent(tmp_path):
    f = tmp_path / "m.json"
    assert orca.read_json(f) is None
    for text in ("", "{garbage", '{"a": ', "[1, 2]", "null"):
        f.write_text(text)
        assert orca.read_json(f) is None
    f.write_text('{"a": 1}')
    assert orca.read_json(f) == {"a": 1}


def test_r6_m8_a_write_interrupted_after_the_temporary_leaves_the_old_file(tmp_path, monkeypatch):
    f = tmp_path / "manifest.json"
    orca.write_json(f, {"v": 1})

    def boom(a, b):
        raise OSError("killed")
    monkeypatch.setattr(orca.os, "replace", boom)
    with pytest.raises(OSError, match="killed"):
        orca.write_json(f, {"v": 2})
    assert json.loads(f.read_text()) == {"v": 1}


@pytest.mark.parametrize("text", ["", "{garbage", '{"box": [175.0, 185.0, -2.0, 2.0]}'])
def test_r6_m8_an_unreadable_cut_record_drops_every_part_like_no_record(orca_env, tmp_path, text):
    out = tmp_path / "out"
    ingest(orca_env, out)
    (out / "cut.json").write_text(text)                                         # a truncated record, or a valid one without the 3-D hours
    _, lines = ingest(orca_env, out)
    assert lines[0] == "ingest: 7 parts, 0 cached, fetching 7 with 4 threads"
    assert json.loads((out / "cut.json").read_text())["box"] == list(BOX)


# ---- review round 7: M-17 (a window that does not start on the hour reads the hour's files, labelled with the hour) and M-31 (a failed part stops the rest)

def test_r7_m17_hours_are_the_whole_hours_that_cover_the_window():
    half = dt.timedelta(minutes=30)
    assert orca.hours(t(0) + half, t(4) + half) == [t(h) for h in range(0, 6)]                    # 12:30..16:30 -> 12:00 .. 17:00 on the hour
    assert orca.hours(t(0) + half, t(4)) == [t(h) for h in range(0, 5)]                          # an end on the hour loses no file and gains none
    assert orca.hours(t(0), t(2)) == [t(0), t(1), t(2)]                                           # an aligned window: the list it always gave
    assert orca.hours(t(3), t(0)) == [] and orca.hours(t(1) + half, t(1) + dt.timedelta(minutes=10)) == []


def test_r7_m17_a_half_hour_window_builds_a_time_axis_equal_to_the_file_stamps(orca_env, tmp_path):
    out = tmp_path / "out"
    half = dt.timedelta(minutes=30)
    man, _ = ingest_dt(out, t(0) + half, t(5) + half)                                               # 00:30 .. 05:30 -> files 00 .. 06
    wrf = zarr(out, "wrf.zarr")
    assert man["hours"] == 7
    assert [np.datetime_as_string(x, unit="m") for x in wrf.time.values] == [f"2023-03-05T{h:02d}:00" for h in range(7)]     # the files' own hours
    assert [orca.stamp(x) for x in orca.hours(t(0) + half, t(5) + half)] == [orca.stamp(t(h)) for h in range(7)]


def ingest_dt(out, a, b, **kw):
    lines = []
    kw.setdefault("threads", 4)
    return orca.ingest(a, b, BOX, out, log=lines.append, **kw), lines


def test_r7_m31_a_failed_part_stops_the_rest_and_keeps_the_finished_ones(orca_env, tmp_path, monkeypatch):
    """Ten jobs on two threads, one of them raising: the exception reached the caller after the other nine had run to completion and none was saved."""
    import threading
    import time
    real, lock, ran, bad_hour = orca.wrf_hour, threading.Lock(), [], t(1)

    def wrf(tt, *a, **k):
        if tt == bad_hour:
            raise OSError("server went away")
        time.sleep(0.3)
        with lock:
            ran.append(tt)
        return real(tt, *a, **k)
    monkeypatch.setattr(orca, "wrf_hour", wrf)
    out = tmp_path / "out"
    with pytest.raises(OSError, match="server went away"):
        ingest(orca_env, out, t0=0, t1=6, threads=2, spectra=False)                                   # 7 wrf + 7 umwm jobs
    assert len(ran) <= 3                                                                              # the jobs in flight, not the seven queued (6 before)
    saved = {p.name for p in (out / "hours").glob("*.npz")}
    assert saved and all(f"wrf_{orca.stamp(x)}.npz" in saved for x in ran)                            # what finished was kept


def test_r8_m33_the_manifest_records_the_layout_version_of_the_hour_labelling(orca_env, tmp_path):
    out = tmp_path / "out"
    man, _ = ingest(orca_env, out)
    assert man["layout_version"] == orca.LAYOUT_VERSION == json.loads((out / "manifest.json").read_text())["layout_version"] == 2


# ---- review round 9: M-6 (assemble keeps every hourly part open) and M-38 (the stores are rewritten before the old manifest is dropped)

def test_r9_m6_assemble_closes_each_part_so_a_30_day_window_fits_a_descriptor_limit_of_256(orca_env, tmp_path):
    """1,440 parts (720 hours) under RLIMIT_NOFILE 256: every part open at once raised `OSError: Too many open files` (about 500 hours at 1,024)."""
    import resource
    import shutil
    out, hrs = tmp_path / "out", 720
    wg, ug = orca.wrf_grid(t(0), BOX), orca.umwm_grid(t(0), BOX)
    ts = orca.hours(t(0), t(hrs - 1))
    (out / "hours").mkdir(parents=True)
    orca._save(out / "hours" / f"wrf_{orca.stamp(ts[0])}.npz", orca.wrf_hour(ts[0], wg))
    orca._save(out / "hours" / f"umwm_{orca.stamp(ts[0])}.npz", orca.umwm_hour(ts[0], ug))
    for x in ts[1:]:
        for kind in ("wrf", "umwm"):
            shutil.copy(out / "hours" / f"{kind}_{orca.stamp(ts[0])}.npz", out / "hours" / f"{kind}_{orca.stamp(x)}.npz")
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))
    try:
        man = orca.assemble(out, ts, wg, ug, None, [], BOX)
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert man["hours"] == hrs and man["bytes_fetched"] == hrs * int(orca.wrf_hour(ts[0], wg)["_bytes"])
    assert zarr(out, "wrf.zarr").sizes["time"] == hrs and zarr(out, "umwm.zarr").sizes["time"] == hrs


def test_r9_m38_a_failed_assemble_leaves_no_manifest_so_the_half_rewritten_cache_is_never_trusted(orca_env, tmp_path, monkeypatch):
    out = tmp_path / "out"
    ingest(orca_env, out)
    assert orca.read_json(out / "manifest.json") is not None
    real = xr.Dataset.to_zarr

    def to_zarr(self, store=None, *a, **k):
        if getattr(store, "name", "") == "umwm.zarr":
            raise OSError("disk went away")
        return real(self, store, *a, **k)
    with monkeypatch.context() as m, pytest.raises(OSError, match="disk went away"):
        m.setattr(xr.Dataset, "to_zarr", to_zarr)
        ingest(orca_env, out)                                                      # all parts cached: only assemble runs; wrf.zarr is rewritten first
    assert not (out / "manifest.json").exists() and orca.read_json(out / "manifest.json") is None
    man, lines = ingest(orca_env, out)                                              # the parts were kept: re-assembly only, no fetch
    assert lines[0] == "ingest: 7 parts, 7 cached, fetching 0 with 4 threads" and man["hours"] == 3
    assert orca.read_json(out / "manifest.json")["parts"] == man["parts"]


def test_r13_sweep_the_ingest_manifest_writer_follows_a_symlink_and_leaves_the_link(tmp_path):
    """Round 13, M-14 sibling (batch A's need): `orca.write_json` was a copy of `config.write_json` that replaced a symlinked manifest by a regular file."""
    real, link = tmp_path / "real.json", tmp_path / "manifest.json"
    real.write_text("{}")
    link.symlink_to(real)
    orca.write_json(link, {"v": 1}, indent=1)
    assert link.is_symlink() and json.loads(real.read_text()) == {"v": 1} and not list(tmp_path.glob("*.tmp"))
