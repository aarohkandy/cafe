"""cafe.pm.env.ocean (the adapter between GriddedEnv and a hycom Zarr store) against the analytic equatorial ocean of
tests/fixtures/ci_env: westward surface current, eastward undercurrent near 100 m, TEOS-10 density and sound speed, NaN under
the seafloor, and the depth-sign convention (z positive up in the query, positive down in the store)."""
import hashlib
import pathlib

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
    assert np.allclose(o.bathymetry(lon, lat).value, [1000.0, 0.0, 100.0], atol=1e-6)                       # deepest valid level: 1000, 0 (land), 100


def test_ocean_remembers_where_it_came_from(oc, ci_env):
    assert "gofs_ci_fixture.zarr" in oc.src and hashlib.sha256(b"ci_env").hexdigest()[:12] in oc.src and "synthetic GOFS 3.1" in oc.src
    assert oc.axes[0].x[0] == fx.T_REF and np.allclose(np.diff(oc.axes[0].x), 3 * 3600.0)             # 3-hourly steps as seconds since 1970
    assert np.array_equal(oc.axes[1].x, fx.ODEPTH) and oc.axes[3].x.min() >= 0.0 and oc.axes[3].x.max() < 360.0   # depth positive down, lon 0..360


def test_fields_load_once_as_float32(oc):
    a = oc._field("water_u")
    assert a is oc._field("water_u") and a.dtype == np.float32 and a.shape == (13, len(fx.ODEPTH), len(fx.OLAT), len(fx.OLON))


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
