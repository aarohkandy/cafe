"""cafe.pm.env.ocean (the adapter between GriddedEnv and a hycom Zarr store) against the analytic equatorial ocean of
tests/fixtures/ci_env: westward surface current, eastward undercurrent near 100 m, TEOS-10 density and sound speed, NaN under
the seafloor, and the depth-sign convention (z positive up in the query, positive down in the store)."""
import hashlib
import pathlib
import pickle

import gsw
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm.env import conventions as cv, ocean as O
from tests.fixtures.ci_env import make as fx

T0 = fx.T_REF + 6 * 3600.0                          # 2023-03-02 00Z, an ocean time step


@pytest.fixture(scope="session")
def oc(ci_full):
    return ci_full.ocean


@pytest.fixture
def data(ci_env, monkeypatch):
    monkeypatch.setattr(O, "DATA", ci_env.data)
    return ci_env


def teos(z_down, lat, lon, temp, salt):
    """Density and sound speed from practical salinity and in-situ temperature with the gsw calls, independent of hycom.teos10."""
    p = gsw.p_from_z(-np.asarray(z_down, float), lat)
    sa = gsw.SA_from_SP(salt, p, lon, lat)
    ct = gsw.CT_from_t(sa, temp, p)
    return gsw.rho(sa, ct, p), gsw.sound_speed(sa, ct, p)


# ------------------------------------------------------------------------------------------------------------ opening a store

def test_store_path_follows_the_spec(data):
    assert O.store_path({"source": "gofs31"}, "m") == data.data / "ocean" / "gofs_m.zarr"
    assert O.store_path({}, "m") == data.data / "ocean" / "gofs_m.zarr"                            # gofs31 is the default
    assert O.store_path({"source": "lab_hycom", "path": "/x/lab.zarr"}, "m") == pathlib.Path("/x/lab.zarr")
    assert O.store_path({"source": "gofs31", "path": "/x/other.zarr"}, "m") == pathlib.Path("/x/other.zarr")
    with pytest.raises(ValueError, match="needs a `path`"):
        O.store_path({"source": "lab_hycom"}, "m")


def test_an_ocean_pickles_with_every_field_read(data):
    """cafe.pm.par sends the environment to stage-1 workers; an Ocean that had read nothing yet made every worker read and hold every field again."""
    o = O.Ocean(data.ocean_store)
    w = pickle.loads(pickle.dumps(o))
    assert {"water_u", "water_v", "water_temp"} <= set(w.f) and not o.f.keys() - w.f.keys()
    assert np.array_equal(w.f["water_u"], o.ds["water_u"].values.astype("f4"), equal_nan=True)
    assert np.array_equal(w.current(-165.0, 0.0, 10.0, w.axes[0].x[0]).value, o.current(-165.0, 0.0, 10.0, o.axes[0].x[0]).value)
    assert len(pickle.dumps(o.ds)) < sum(x.nbytes for x in o.f.values()) / 4      # xarray keeps no second copy of a field it read


def test_open_ocean_finds_the_store_and_the_gebco_format_cache(data):
    box = (-2.0, 2.0, -167.0, -163.0)
    o = O.open_ocean({"source": "gofs31"}, data.cache, "ci_fixture", box)
    assert o.path == data.ocean_store and o.bathy.source.startswith("GEBCO_2026") and o.bathy.tried == ()
    assert O.open_ocean({"source": "gofs31"}, data.cache, box=box).path == data.ocean_store           # mission name from the cache directory
    assert O.open_ocean({"source": "lab_hycom", "path": str(data.ocean_store)}, data.cache, box=box).path == data.ocean_store
    assert O.open_ocean({"source": "lab_hycom", "path": str(data.data / "none.zarr")}, data.cache) is None       # no store, no ocean


def test_open_ocean_falls_back_to_the_gofs_floor_when_no_gebco_cache_matches(data):
    o = O.open_ocean({"source": "gofs31"}, data.cache, "ci_fixture", fetch_bathy=False)           # box from the store: no matching cache file
    assert o.bathy.source.startswith("HYCOM GOFS 3.1 deepest valid level") and o.bathy.tried[0].startswith("gebco: FileNotFoundError")
    lon, lat = np.array([195.0, 196.75, 197.0]), np.array([0.0, -1.75, -1.75])                     # open sea, the atoll column, the wet-to-100-m column
    t = o.bathymetry(lon, lat)
    assert np.allclose(t.value, [1000.0, 0.0, 110.0], atol=1e-6)               # last level 1000 (lower bound), land, wet to 100 not 120: 100 + 20 / 2
    assert np.allclose(t.uncertainty, [1000.0, 0.0, 20.0 / np.sqrt(12.0)], atol=1e-6)         # the open level's assumed sigma, land, spacing / sqrt(12)


def test_ocean_remembers_where_it_came_from(oc, ci_env):
    assert "gofs_ci_fixture.zarr" in oc.src and hashlib.sha256(b"ci_env").hexdigest()[:12] in oc.src and "synthetic GOFS 3.1" in oc.src
    assert oc.axes[0].x[0] == fx.T_REF and np.allclose(np.diff(oc.axes[0].x), 3 * 3600.0)             # 3-hourly steps as seconds since 1970
    assert np.array_equal(oc.axes[1].x, fx.ODEPTH) and oc.axes[3].x.min() >= 0.0 and oc.axes[3].x.max() < 360.0   # depth positive down, lon 0..360


def test_fields_load_once_as_float32(oc, ci_env):
    a = oc._field("water_u")
    lat, lon = fx._ocean_axes(ci_env.mission)                                                         # the axes the generator wrote the store with
    assert a is oc._field("water_u") and a.dtype == np.float32 and a.shape == (13, len(fx.ODEPTH), len(lat), len(lon))


# ------------------------------------------------------------------------------------------------------------ currents

def _grid_points():
    la, lo, z, t = np.meshgrid([-1.0, 0.0, 1.5], [194.0, 196.0], fx.ODEPTH[[0, 4, 9, 12, 16]], [T0, T0 + 3 * 3600.0], indexing="ij")
    return lo.ravel(), la.ravel(), z.ravel(), t.ravel()


def test_current_equals_the_analytic_ocean_at_the_nodes(oc):
    lon, lat, z, t = _grid_points()
    c = oc.current(lon, lat, -z, t)
    _, _, u, v = fx.ocean(z, lat, lon, t)
    assert c.value.shape == (len(z), 2) and np.allclose(c.value[:, 0], u, atol=1e-6) and np.allclose(c.value[:, 1], v, atol=1e-6)
    assert c.kind == "modelled" and "total current (east, north)" in c.source and c.uncertainty is None


def _undercurrent_checks(o):
    """Westward surface flow, eastward core near 100 m, nothing at 1000 m (the equatorial current system at 165W)."""
    z = -np.arange(0.0, 400.0, 10.0)
    c = o.current(np.full(z.size, 195.0), np.zeros(z.size), z, T0).value
    assert c[0, 0] < -0.4                                                                          # South Equatorial Current at the surface
    assert c[10, 0] > 0.9 and 80.0 <= -z[np.argmax(c[:, 0])] <= 120.0                              # Equatorial Undercurrent core near 100 m
    assert c[10, 0] > 0 > c[0, 0] and abs(o.current(195.0, 0.0, -1000.0, T0).value[0]) < 0.01


def test_the_ocean_current_at_minus_100_m_is_eastward(oc):
    _undercurrent_checks(oc)
    off = oc.current(np.full(2, 195.0), np.array([0.0, 2.0]), np.full(2, -100.0), T0).value[:, 0]
    assert off[1] == pytest.approx(off[0] * np.exp(-((2.0 / 1.5) ** 2)), rel=0.05)                 # the undercurrent is confined to the equator


def test_a_depth_sign_error_in_the_adapter_is_caught(oc, monkeypatch):
    def at_depth_up(self, name, lon, lat, z, t):                                                   # z read as a depth: -100 is 100 m above the surface
        return O.interp(self._field(name), self.axes, [t, np.asarray(z, float), lat, cv.wrap360(lon)])[0]
    monkeypatch.setattr(O.Ocean, "_at", at_depth_up)
    with pytest.raises(AssertionError):
        _undercurrent_checks(oc)


def test_current_is_linear_in_time_between_steps_and_between_levels(oc):
    a = oc.current(195.0, 0.0, -100.0, T0).value
    b = oc.current(195.0, 0.0, -100.0, T0 + 24 * 3600.0).value
    assert b[0] - a[0] == pytest.approx(0.02, abs=1e-5)                                           # +0.02 m/s per day in the fixture
    mid = oc.current(195.0, 0.0, -100.0, T0 + 1.5 * 3600.0).value
    assert mid[0] == pytest.approx(0.5 * (a[0] + oc.current(195.0, 0.0, -100.0, T0 + 3 * 3600.0).value[0]), abs=1e-6)
    z = -110.0                                                                                     # between the 100 and 120 m levels: linear in depth
    assert abs(oc.current(195.0, 0.0, z, T0).value[0] - fx.ocean(-z, 0.0, 195.0, T0)[2]) < 0.07  # h^2 f'' / 8 with h = 20 m, f'' ~ 2 / 40^2
    assert np.array_equal(oc.current(195.0, 0.0, -50.0, T0).value, oc.current(-165.0, 0.0, -50.0, T0).value)   # lon in either convention


# ------------------------------------------------------------------------------------------------------------ T, S, density, sound speed

def test_density_and_sound_speed_are_teos10_of_the_analytic_t_and_s(oc):
    lon, lat, z, t = _grid_points()
    T, S, _, _ = fx.ocean(z, lat, lon, t)
    rho, c = teos(z, lat, lon, T, S)
    assert np.allclose(oc.density(lon, lat, -z, t).value, rho, atol=2e-3) and np.allclose(oc.sound_speed(lon, lat, -z, t).value, c, atol=0.02)
    assert np.allclose(oc.temperature(lon, lat, -z, t).value, T, atol=1e-4)
    assert "TEOS-10" in oc.density(0, 0, 0, T0).source and "in-situ temperature" in oc.temperature(195.0, 0.0, 0.0, T0).source


def test_env_sound_speed_is_the_ocean_sound_speed(ci_full, oc):
    lon, lat, z = np.array([194.0, 196.0]), np.array([-1.0, 1.5]), np.array([-10.0, -300.0])
    assert np.array_equal(ci_full.sound_speed(lon, lat, z, T0).value, oc.sound_speed(lon, lat, z, T0).value)


def test_density_increases_with_depth_and_sound_speed_has_a_minimum(oc):
    z = -np.arange(0.0, 1001.0, 25.0)
    rho = oc.density(np.full(z.size, 195.0), np.zeros(z.size), z, T0).value
    c = oc.sound_speed(np.full(z.size, 195.0), np.zeros(z.size), z, T0).value
    assert (np.diff(rho) > 0).all() and 1020.0 < rho[0] < 1024.0 and 1030.0 < rho[-1] < 1034.0      # stable stratification, tropical surface and 1000 m values
    k = int(np.argmin(c))
    assert 1535.0 < c[0] < 1550.0 and 0 < k < len(z) - 1 and 1470.0 < c[k] < 1485.0 and -z[k] > 200.0   # warm fast surface layer, slow cold thermocline


@settings(max_examples=25, deadline=None)
@given(lon=st.floats(193.0, 197.0), lat=st.floats(-2.0, 2.0), f=st.floats(0.0, 1.0))
def test_density_is_monotone_in_depth_everywhere_the_ocean_is_wet(oc, lon, lat, f):
    z = -np.array([0.0, 10.0, 30.0, 60.0, 100.0, 200.0, 400.0, 800.0, 1000.0])
    n = z.size
    if np.hypot(lon - fx.ATOLL[0], lat - fx.ATOLL[1]) < 0.6:                                      # atoll column and its neighbour are not full-depth
        return
    rho = oc.density(np.full(n, lon), np.full(n, lat), z, T0 + f * 30 * 3600.0).value
    assert (np.diff(rho) > 0).all()


# ------------------------------------------------------------------------------------------------------------ the seafloor

def test_levels_below_the_floor_are_nan_and_dropped_from_the_average(oc):
    land, shallow = (196.75, -1.75), (197.0, -1.75)
    z = np.array([0.0, -50.0, -150.0, -1000.0])
    assert np.isnan(oc.current(np.full(4, land[0]), np.full(4, land[1]), z, T0).value).all()       # an all-land column
    c = oc.current(np.full(4, shallow[0]), np.full(4, shallow[1]), z, T0).value
    assert np.isfinite(c[:2]).all() and np.isnan(c[2:]).all()                                      # wet down to 100 m
    mid = oc.current(196.875, -1.75, -50.0, T0).value                                              # half way to the land column: the wet neighbour alone
    assert np.allclose(mid, oc.current(197.0, -1.75, -50.0, T0).value)
    assert np.isnan(oc.density(shallow[0], shallow[1], -500.0, T0).value) and np.isfinite(oc.density(shallow[0], shallow[1], -50.0, T0).value)


def test_bathymetry_is_the_gebco_format_cache(oc):
    lon, lat = np.array([193.5, 195.0, 196.5]), np.array([-1.5, 0.0, 1.5])
    b = oc.bathymetry(lon, lat)
    assert np.allclose(b.value, fx.seafloor(lon, lat), atol=1.0)                                   # integer metres in the file
    assert b.source.startswith("GEBCO_2026") and "synthetic" in b.source
    assert oc.bathymetry(fx.ATOLL[0], fx.ATOLL[1]).value == 0.0                                    # the atoll is land
    assert (np.asarray(b.uncertainty) > 0).all() and b.source.startswith(oc.bathy.source)


@settings(max_examples=20, deadline=None)
@given(lon=st.floats(193.0, 197.0), lat=st.floats(-2.0, 2.0), z=st.floats(0.0, 1000.0), f=st.floats(0.0, 1.0))
def test_interpolated_current_stays_within_the_store_extremes(oc, lon, lat, z, f):
    c = oc.current(lon, lat, -z, T0 + f * 30 * 3600.0).value
    for k, name in enumerate(("water_u", "water_v")):
        a = oc._field(name)
        if np.isfinite(c[k]):
            assert np.nanmin(a) - 1e-6 <= c[k] <= np.nanmax(a) + 1e-6


# ---- review round 6, M-7: a damaged chunk is the same ConfigError as a damaged store

def _damaged(ci_env, tmp_path, name):
    import shutil
    from cafe.pm.env import hycom
    bad = tmp_path / name
    shutil.copytree(ci_env.ocean_store, bad)
    chunk = next(p for p in sorted((bad / "water_u").rglob("*")) if p.is_file() and p.name != "zarr.json")
    chunk.write_bytes(b"x")                                                     # one byte: what a truncated download leaves
    return bad, hycom


def test_r6_m7_a_damaged_chunk_is_a_config_error_naming_the_store(ci_env, tmp_path):
    from cafe.pm.config import ConfigError
    bad, _ = _damaged(ci_env, tmp_path, "gofs_x.zarr")
    o = O.Ocean(bad)                                                            # the metadata opens; the chunk is read lazily
    with pytest.raises(ConfigError, match=rf"environment cache file {bad} cannot be read .*delete {bad} and run `python -m cafe.pm fetch"):
        o.current(195.0, 0.0, -10.0, T0)
    lab, _ = _damaged(ci_env, tmp_path, "lab_x.zarr")
    with pytest.raises(ConfigError, match=rf"restore {lab} from the lab's source"):
        O.Ocean(lab, lab=True).current(195.0, 0.0, -10.0, T0)
    with pytest.raises(ConfigError, match="cannot be read"):                    # the pickle for the stage-1 workers reads every field first
        pickle.dumps(O.Ocean(bad))


def test_r6_m7_open_ocean_tells_a_lab_store_from_a_downloaded_one(ci_env, tmp_path, data):
    from cafe.pm.config import ConfigError
    lab = tmp_path / "gofs_but_the_labs.zarr"
    import shutil
    shutil.copytree(ci_env.ocean_store, lab)
    (lab / "zarr.json").write_text("{not json")
    with pytest.raises(ConfigError, match="restore .* from the lab's source"):
        O.open_ocean({"source": "lab_hycom", "path": str(lab)}, ci_env.cache, "ci_fixture", fetch_bathy=False)
    with pytest.raises(ConfigError, match="delete .* and run"):
        O.open_ocean({"source": "gofs31", "path": str(lab)}, ci_env.cache, "ci_fixture", fetch_bathy=False)


# ---- review round 7, M-24: the store knows when a query is outside it

def test_r7_m24_ocean_inside_tests_the_stores_lat_lon_and_time_axes_and_bounds_names_them(oc):
    t = oc.axes[0].x
    assert oc.inside(195.0, 0.0, t[3]) and oc.inside(-165.0, 0.0, t[3]) and oc.inside(195.0, 0.0)                    # -165 is 195 east
    assert not oc.inside(195.0, 3.0, t[3]) and not oc.inside(190.0, 0.0, t[3])
    assert not oc.inside(195.0, 0.0, t[-1] + 1.0) and not oc.inside(195.0, 0.0, t[0] - 1.0)
    assert list(oc.inside(np.array([195.0, 190.0]), np.array([0.0, 0.0]), t[3])) == [True, False]
    assert oc.bounds() == (-167.5, -162.5, -2.5, 2.5, float(t[0]), float(t[-1]))


# ------------------------------------------------------------------------------------------------------------ round 13 M-37: a store across 0 E

@pytest.mark.parametrize("axis,queries", [([-1.0, 0.0, 1.0], [-0.5, 359.5, 0.5, 360.5]), ([359.0, 360.0, 361.0], [-0.5, 359.5, 0.5, 360.5])])
def test_r13_m37_a_store_that_crosses_0_e_is_queried_in_its_own_frame(axis, queries):
    """`Ocean._lon` put a query in 0..360, which cut a store across 0 E in two: -0.5 and 359.5 are one place, and a mutant that wrapped to 0..360 held
    the edge value for it. u is the longitude of the store's own axis here, so the answer is the place."""
    o = object.__new__(O.Ocean)
    x = np.asarray(axis)
    o.axes = [O.Axis([0.0, 3600.0], "time"), O.Axis([0.0, 10.0], "depth"), O.Axis([-1.0, 1.0], "lat"), O.Axis(x, "lon")]
    u = np.broadcast_to(x - 360.0 * (x > 180.0), (2, 2, 2, 3)).copy()                  # the longitude in -180..180
    o.f = {"water_u": u, "water_v": np.zeros_like(u)}
    o.src = "test store"
    lon = np.array(queries)
    got = o.current(lon, np.zeros(4), np.full(4, -5.0), 0.0).value[:, 0]
    want = np.array([-0.5, -0.5, 0.5, 0.5])
    assert np.allclose(got, want) and o.inside(lon, 0.0, 0.0).all()
    assert not o.inside(np.array([1.5, 358.5]), 0.0, 0.0).any()
