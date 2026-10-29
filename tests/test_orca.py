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
    assert orca.hours(t(0), t(0) + dt.timedelta(minutes=119)) == [t(0), t(1)]      # whole hours only
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
    return xr.open_zarr(out / name, chunks=None)


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
