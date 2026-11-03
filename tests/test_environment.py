"""cafe.pm.env.environment against the analytic fields of tests/fixtures/ci_env (every expected value is a closed-form function of
lon, lat, t defined in make.py, not read back from the files), plus one deliberately broken variant per convention."""
import datetime as dt
import shutil

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm.config import env_sigmas
from cafe.pm.env import conventions as cv, environment as E, waves
from cafe.pm.env.environment import GriddedEnv, OutsideData
from tests.fixtures.ci_env import make as fx

# linear interpolation in time of A cos(2 pi h / 24) between hourly nodes is off by at most A (2 pi / 24)^2 / 8 (A = 0.4 m/s)
TIME_INTERP = 0.4 * (2 * np.pi / 24) ** 2 / 8 + 1e-4


@pytest.fixture(scope="session")
def grid(ci_env):
    """GriddedEnv without ocean or sub-grid layer: WRF + UMWM + 3-D WRF + restart spectra."""
    return GriddedEnv(ci_env.cache, env_sigmas())


@pytest.fixture(scope="session")
def bare(ci_env, tmp_path_factory):
    """The same cache with only wrf.zarr and umwm.zarr: no 3-D winds, no restart spectra."""
    d = tmp_path_factory.mktemp("bare") / "cache"
    for s in ("wrf.zarr", "umwm.zarr"):
        shutil.copytree(ci_env.cache / "orca" / s, d / "orca" / s)
    return GriddedEnv(d, env_sigmas())


def nodes(env, k=(3, 10, 20), m=(5, 12, 25)):
    return env.low.x[list(k)], env.law.x[list(m)]


# ------------------------------------------------------------------------------------------------------------ time helpers

def test_time_helpers_agree_with_datetime():
    want = dt.datetime(2023, 3, 2, 1, 30, tzinfo=dt.timezone.utc).timestamp()
    assert E.to_seconds("2023-03-02T01:30:00Z") == want
    assert E.to_seconds(dt.datetime(2023, 3, 2, 1, 30)) == want                                  # naive means UTC
    assert E.to_seconds(dt.datetime(2023, 3, 2, 3, 30, tzinfo=dt.timezone(dt.timedelta(hours=2)))) == want
    assert E.seconds(np.datetime64("2023-03-02T01:30:00")) == want
    assert np.array_equal(E.seconds(["1970-01-01T00:00:10", "1970-01-01T00:01:00"]), [10.0, 60.0])


@settings(max_examples=40, deadline=None)
@given(st.integers(min_value=0, max_value=4_000_000_000))
def test_to_seconds_roundtrips_an_iso_string(t):
    iso = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert E.to_seconds(iso) == t


# ------------------------------------------------------------------------------------------------------------ loading

def test_grid_axes_and_bounds_come_from_the_stores(grid, ci_env):
    assert np.allclose(np.diff(grid.low.x), fx.DX) and np.allclose(np.diff(grid.law.x), fx.DX)
    assert np.array_equal(grid.tw.x, ci_env.hours) and len(ci_env.hours) == 37
    assert grid.bounds == (-167.125, -162.875, -2.125, 2.125, ci_env.hours[0], ci_env.hours[-1])
    assert "OUTPUT FROM WRF V4.7.1 MODEL" in grid.wrf_src and "UMWM hourly" in grid.umwm_src
    assert grid.w3 is not None and grid.spec is not None
    assert grid.Wstatic["COSALPHA"].min() == 1.0 and grid.Wstatic["SINALPHA"].max() == 0.0          # Mercator: identity rotation


def test_missing_optional_stores_are_none(bare):
    assert bare.w3 is None and bare.spec is None and bare.ocean is None and bare.subgrid is None
    assert bare.restart_spectrum(195.0, 0.0, bare.tw.x[6]) is None


def test_land_is_nan_in_umwm_and_zero_depth(grid):
    lo, la = np.array([196.75, 196.875]), np.array([-1.75, -1.875])
    j, i = np.searchsorted(grid.lau.x, la), np.searchsorted(grid.lou.x, lo)
    assert np.isnan(grid.U["swh"][:, j[:, None], i[None, :]]).all()
    assert (grid.depth_umwm[j[:, None], i[None, :]] == 0).all() and grid.Wstatic["LANDMASK"][j[:, None], i[None, :]].min() == 1


def test_rain_rate_nodes_are_the_mean_of_the_two_intervals_they_join(grid):
    """M-16: the rate used to be the backward difference stored at the end of its hour, so an hour of rain read 30 min late and twice as wide."""
    rate = grid.W["rain_mm_h"]
    assert (rate >= 0).all() and rate.max() == pytest.approx(10.0, rel=1e-3)
    j, i = np.unravel_index(np.argmax(fx.rain_footprint(grid.low.x[None, :], grid.law.x[:, None])), rate.shape[1:])
    at = lambda h: float(rate[np.flatnonzero(grid.tw.x == fx.RAIN_T0 + h * 3600.0)[0], j, i])
    assert [at(h) for h in (-1, 0, 1, 2, 3, 4)] == pytest.approx([0.0, 5.0, 10.0, 10.0, 5.0, 0.0], rel=1e-3)             # 10 mm/h from 23Z to 02Z
    assert grid.W["RAINNC"][0, j, i] > 30                                                         # a forgotten difference would read ~46 mm/h
    tt = np.linspace(grid.tw.x[0], grid.tw.x[-1], 20001)
    r = np.interp(tt, grid.tw.x, rate[:, j, i])
    acc = grid.W["RAINNC"][:, j, i] + grid.W["RAINC"][:, j, i]
    assert np.trapezoid(r, tt) / 3600.0 == pytest.approx(acc[-1] - acc[0], rel=1e-4)               # the interpolated rate integrates to the accumulation
    assert np.trapezoid(r * tt, tt) / np.trapezoid(r, tt) == pytest.approx(fx.RAIN_T0 + 1.5 * 3600.0, abs=1.0)  # mid-burst (+2 h before)


def test_rain_rate_nodes_edges_and_unequal_steps():
    acc = np.array([0.0, 4.0, 4.0, 10.0])[:, None, None]
    assert E.rain_rate_nodes(acc, np.array([0.0, 3600.0, 7200.0, 10800.0]))[:, 0, 0].tolist() == [4.0, 2.0, 3.0, 6.0]          # the first node is not 0
    assert E.rain_rate_nodes(acc, np.array([0.0, 1800.0, 5400.0, 7200.0]))[:, 0, 0].tolist() == [8.0, 4.0, 6.0, 12.0]        # intervals of 8, 0 and 12 mm/h
    assert E.rain_rate_nodes(np.array([5.0, 3.0])[:, None, None], np.array([0.0, 3600.0]))[:, 0, 0].tolist() == [0.0, 0.0]  # a reset is 0
    assert E.rain_rate_nodes(np.array([5.0])[:, None, None], np.array([0.0]))[:, 0, 0].tolist() == [0.0]


# ------------------------------------------------------------------------------------------------------------ bounds

def test_inside_is_the_data_box(grid):
    t0, t1 = grid.tw.x[[0, -1]]
    assert grid.inside(195.0, 0.0) and grid.inside(-165.0, 0.0, t0 + 10)
    assert not grid.inside(190.0, 0.0) and not grid.inside(195.0, 3.0) and not grid.inside(195.0, 0.0, t0 - 1) and not grid.inside(195.0, 0.0, t1 + 1)
    assert list(grid.inside(np.array([195.0, 190.0]), np.array([0.0, 0.0]))) == [True, False]


def test_outside_data_names_the_point_and_the_box(grid):
    t = grid.tw.x[5]
    for lon, lat, tt in ((190.0, 0.0, t), (195.0, 5.0, t), (195.0, 0.0, grid.tw.x[0] - 7200.0)):
        with pytest.raises(OutsideData, match=r"outside the ingested data \(box \(-167\.125, -162\.875, -2\.125, 2\.125\), 2023-03-01 18Z\.\.2023-03-03 06Z\)"):
            grid.u10(lon, lat, tt)
    with pytest.raises(OutsideData, match=r"\(190\.000, 0\.000\) at 2023-03-01 23:00Z"):
        grid.u10(np.array([195.0, 190.0]), np.array([0.0, 0.0]), t)                               # reports the first bad element
    with pytest.raises(OutsideData, match="UMWM swh"):
        grid.waves(190.0, 0.0, t)


def test_non_strict_env_clamps_to_the_edge_value(ci_env):
    env = GriddedEnv(ci_env.cache, env_sigmas(), strict=False)
    t = env.tw.x[5]
    assert np.allclose(env.u10(190.0, 0.0, t), env.u10(env.low.x[0], 0.0, t))


# ------------------------------------------------------------------------------------------------------------ 10 m wind

def _u10_error(env, off_node=False):
    """Largest |env.u10 - analytic| over a set of points: nodes (float32 round-off only) or random off-node points."""
    if off_node:
        r = np.random.default_rng(3)
        lon, lat = r.uniform(193.2, 196.8, 40), r.uniform(-1.8, 1.8, 40)
        t = r.uniform(env.tw.x[0], env.tw.x[-1], 40)
    else:
        lon, lat = nodes(env)
        t = env.tw.x[[0, 7, 20]]
    return np.abs(env.u10(lon, lat, t) - np.stack(fx.wind10(lon, lat, t), -1)).max()


def test_u10_equals_the_analytic_wind(grid):
    assert _u10_error(grid) < 2e-5                                                                # at nodes: float32 storage only
    assert _u10_error(grid, off_node=True) < TIME_INTERP                                          # between nodes: the diurnal cosine in time only
    lon, lat = np.array([195.0]), np.array([0.0])
    assert np.array_equal(grid.u10(lon, lat, grid.tw.x[4]), grid.u10(lon - 360.0, lat, grid.tw.x[4]))   # lon in either convention


def test_trade_wind_blows_from_the_east(grid):
    w = grid.u10(np.full(3, 195.0), np.array([-1.0, 0.0, 1.0]), grid.tw.x[8])
    assert (w[:, 0] < -3).all() and (np.abs(w[:, 1]) < 1.5).all()
    assert (np.abs(cv.from_deg(w) - 90.0) < 20).all() and (np.abs(cv.to_deg(w) - 270.0) < 20).all()


def test_wind_sign_flip_is_caught(grid, monkeypatch):
    monkeypatch.setattr(E.cv, "rotate_grid_to_earth", lambda u, v, c, s: (-(u * c - v * s), -(v * c + u * s)))      # wind read as "from" vs "to"
    with pytest.raises(AssertionError):
        assert _u10_error(grid) < 2e-5


def _rotated_error(env, monkeypatch, alpha_deg=30.0):
    """Store the analytic earth wind as grid-relative components of a grid rotated alpha CCW from east, with the matching
    COSALPHA / SINALPHA; u10 must give the earth wind back."""
    a = np.radians(alpha_deg)
    la, lo = np.meshgrid(env.law.x, env.low.x, indexing="ij")
    ue, ve = np.stack([fx.wind10(lo, la, t) for t in env.tw.x], 1)
    monkeypatch.setitem(env.W, "U10", ue * np.cos(a) + ve * np.sin(a))
    monkeypatch.setitem(env.W, "V10", -ue * np.sin(a) + ve * np.cos(a))
    monkeypatch.setitem(env.Wstatic, "COSALPHA", np.full(la.shape, np.cos(a)))
    monkeypatch.setitem(env.Wstatic, "SINALPHA", np.full(la.shape, np.sin(a)))
    lon, lat = nodes(env)
    t = env.tw.x[[0, 7, 20]]
    return np.abs(env.u10(lon, lat, t) - np.stack(fx.wind10(lon, lat, t), -1)).max()


def test_grid_to_earth_rotation_with_a_rotated_grid(grid, monkeypatch):
    assert _rotated_error(grid, monkeypatch) < 2e-5
    assert _rotated_error(grid, monkeypatch, alpha_deg=-75.0) < 2e-5


def test_rotation_sign_flip_is_caught(grid, monkeypatch):
    monkeypatch.setattr(E.cv, "rotate_grid_to_earth", lambda u, v, c, s: (u * c + v * s, v * c - u * s))            # rotates by -alpha
    with pytest.raises(AssertionError):
        assert _rotated_error(grid, monkeypatch) < 2e-5


@settings(max_examples=30, deadline=None)
@given(lon=st.floats(193.0, 197.0), lat=st.floats(-2.0, 2.0), f=st.floats(0.0, 1.0))
def test_interpolated_u10_stays_within_the_grid_extremes(grid, lon, lat, f):
    w = grid.u10(lon, lat, grid.tw.x[0] + f * (grid.tw.x[-1] - grid.tw.x[0]))
    assert grid.W["U10"].min() - 1e-9 <= w[0] <= grid.W["U10"].max() + 1e-9
    assert grid.W["V10"].min() - 1e-9 <= w[1] <= grid.W["V10"].max() + 1e-9


# ------------------------------------------------------------------------------------------------------------ 3-D wind and the log profile

def test_wind_without_subgrid_is_the_neutral_log_profile(bare):
    t = bare.tw.x[8]
    for z in (2.0, 10.0, 18.0, 50.0):
        w = bare.wind(195.0, 0.5, z, t)
        want = np.stack(fx.wind3d(195.0, 0.5, t, z), -1)
        assert np.allclose(w.value, want, atol=2e-5), z
    assert "neutral log profile" in w.source and w.kind == "data" and w.uncertainty == env_sigmas()["wind_ms"]
    assert np.allclose(bare.wind(195.0, 0.5, 10.0, t).value, bare.u10(195.0, 0.5, t))


def test_wind_above_the_first_level_in_a_sortie_hour_uses_the_3d_fields(grid):
    t = E.to_seconds("2023-03-02T01:30:00Z")
    z = np.array([10.0, 15.0, 30.0, 100.0, 300.0])
    w = grid.wind(np.full(5, 195.1), np.full(5, 0.3), z, t)
    assert np.allclose(w.value[2:], np.stack(fx.wind3d(195.1, 0.3, t, z[2:]), -1), atol=TIME_INTERP * 2)         # log-linear in z is exact for a log profile
    assert np.allclose(w.value[:2], np.stack(fx.wind3d(195.1, 0.3, t, z[:2]), -1), atol=1e-3 + TIME_INTERP * 2)   # below 21 m: the log law at 2e-4 m
    assert "WRF 3-D U/V" in w.source and (np.diff(np.hypot(*w.value.T)) > 0).all()                 # speed increases with height


def test_wind_in_hours_without_3d_fields_ignores_them(grid):
    for iso in ("2023-03-02T02:30:00Z", "2023-03-01T20:00:00Z", "2023-03-03T05:00:00Z"):            # between sorties, before the first, after the last
        w = grid.wind(195.0, 0.0, 100.0, E.to_seconds(iso))
        assert "WRF 3-D" not in w.source and np.allclose(w.value, np.stack(fx.wind3d(195.0, 0.0, E.to_seconds(iso), 100.0), -1), atol=1e-3 + 2 * TIME_INTERP)


def test_wind_above_the_top_stored_level_is_not_held_constant_nor_counted_as_3d(grid, monkeypatch):
    """M-15: above the top level (318 m in the fixture; ~400 m in the real cache) the top level's wind used to be returned and counted as 3-D."""
    t = E.to_seconds("2023-03-02T01:30:00Z")
    lon, lat, z = np.full(3, 195.1), np.full(3, 0.3), np.array([300.0, 318.0, 600.0])
    up = grid._wind3d(lon, lat, z, t)
    assert np.isfinite(up[:2]).all() and np.isnan(up[2]).all()                                      # the top level itself is still inside
    grid.wind_points = grid.wind3d_points = 0
    w = grid.wind(lon, lat, z, t)
    assert (grid.wind_points, grid.wind3d_points) == (3, 2) and np.isfinite(w.value).all()
    monkeypatch.setattr(grid, "use_3d", False)
    assert np.allclose(w.value[2], grid.wind(lon, lat, z, t).value[2])                              # the U10 log profile there, not the top level's wind


def test_wind_below_the_first_level_ignores_the_3d_fields(grid):
    t = E.to_seconds("2023-03-02T01:00:00Z")
    assert np.allclose(grid.wind(195.0, 0.0, 15.0, t).value, np.stack(fx.wind3d(195.0, 0.0, t, 15.0), -1), atol=1e-3)


# ------------------------------------------------------------------------------------------------------------ air

def test_air_reads_each_wrf_variable(grid):
    lon, lat = nodes(grid)
    t = grid.tw.x[[4, 14, 24]]
    a, s = grid.air(lon, lat, t), env_sigmas()
    for i in range(3):
        f = fx.wrf2d(lon[i], lat[i], t[i])
        for key, name in (("T2", "T2"), ("q2", "Q2"), ("psfc", "PSFC"), ("swdown", "SWDOWN"), ("glw", "GLW"), ("ustar_wrf", "UST"), ("pblh", "PBLH")):
            assert a[key].value[i] == pytest.approx(float(f[name]), rel=1e-6, abs=1e-6), key
    assert a["T2"].uncertainty == s["t2_k"] and a["glw"].uncertainty == s["glw_wm2"] and a["rain"].uncertainty is None
    assert 295 < a["T2"].value.min() and a["T2"].value.max() < 303 and 0.012 < a["q2"].value.min() and a["q2"].value.max() < 0.022
    assert set(a) == {"T2", "q2", "psfc", "swdown", "glw", "rain", "ustar_wrf", "pblh"}               # no sub-grid layer: no modelled keys


def test_air_rain_is_the_derived_rate_and_sun_follows_local_time(grid):
    t = E.to_seconds("2023-03-02T01:00:00Z")                                                       # inside the burst
    lon, lat = np.array([196.5, 193.5]), np.array([1.5, -1.5])
    r = grid.air(lon, lat, np.full(2, t))["rain"].value
    assert r[0] == pytest.approx(float(fx.rain_rate(196.5, 1.5, t)), rel=1e-4) and r[0] > 9 and r[1] < 0.5
    noon, midnight = E.to_seconds("2023-03-01T23:00:00Z"), E.to_seconds("2023-03-02T11:00:00Z")     # local solar noon and midnight at 165W
    sw = grid.air(np.full(2, 193.5), np.full(2, -1.5), np.array([noon, midnight]))["swdown"].value
    assert sw[0] > 800 and sw[1] == 0.0


# ------------------------------------------------------------------------------------------------------------ waves

def test_waves_read_the_umwm_fields(grid):
    lon, lat = nodes(grid, (4, 11, 21), (6, 13, 26))
    t = grid.tw.x[[2, 12, 30]]
    w = grid.waves(lon, lat, t)
    for i in range(3):
        f = fx.umwm2d(lon[i], lat[i], t[i])
        for key, name in (("Hs", "swh"), ("Tp", "dwp"), ("Tm", "mwp"), ("mss", "mss"), ("cp", "dcp"), ("ustar_umwm", "ust")):
            assert w[key].value[i] == pytest.approx(float(f[name]), rel=1e-5), key
    s = env_sigmas()
    assert np.allclose(w["Hs"].uncertainty, s["hs_frac"] * w["Hs"].value) and w["Tp"].uncertainty == s["tp_s"]
    assert (w["Tm"].value < w["Tp"].value).all() and (w["Tp"].value > 5).all() and (w["Hs"].value > 0.5).all()


def test_waves_obey_jonswap_growth_and_deep_water_dispersion(grid):
    lon, lat = np.array([193.5, 196.5]), np.array([0.0, 0.0])
    t = np.full(2, grid.tw.x[10])
    w, u = grid.waves(lon, lat, t), np.hypot(*grid.u10(lon, lat, t).T)
    fetch = 1e3 * (fx.FETCH0_KM + fx.FETCH_SLOPE_KM * (fx.FETCH_LON - lon))
    assert np.allclose(w["Hs"].value, 1.6e-3 * u * np.sqrt(fetch / 9.81), rtol=1e-4)               # Hasselmann et al. 1973: Hs from U and fetch
    assert np.allclose(1 / w["Tp"].value, 3.5 * (9.81 / u) * (9.81 * fetch / u ** 2) ** -0.33, rtol=1e-4)
    assert np.allclose(w["cp"].value, 9.81 * w["Tp"].value / (2 * np.pi), rtol=1e-5)                 # c = g T / 2 pi in deep water
    assert w["Hs"].value[0] > w["Hs"].value[1]                                                      # more fetch to the west, so higher waves there


def _wave_direction_error(env, lon=195.0, lat=0.3, k=9):
    """Degrees between the wave direction toward and the downwind direction (the fixture aligns them)."""
    t = env.tw.x[k]
    d = env.waves(lon, lat, t)["dir_to"].value
    return float(np.abs((d - cv.to_deg(env.u10(lon, lat, t)) + 180.0) % 360.0 - 180.0))


def test_wave_direction_is_toward_the_downwind_side(grid):
    assert _wave_direction_error(grid) < 1.0
    assert abs(grid.waves(195.0, 0.3, grid.tw.x[9])["dir_to"].value - 270.0) < 20                    # trade-wind seas travel toward the west


def test_wave_direction_from_read_as_to_is_caught(grid, monkeypatch):
    monkeypatch.setattr(E.cv, "math_rad_to_compass_to", lambda th: cv.wrap360(270.0 - np.degrees(th)))   # "direction from" instead of "toward"
    with pytest.raises(AssertionError):
        assert _wave_direction_error(grid) < 1.0


def test_wave_direction_interpolates_across_the_pi_branch_cut(grid):
    t = E.to_seconds("2023-03-02T09:00:00Z")                                                       # d(t) = 0: v changes sign at lat 0 along 195E
    j = int(np.searchsorted(grid.law.x, 0.0))
    i = int(np.searchsorted(grid.lou.x, 195.0))
    th = np.arctan2(grid.U["dwd_n"][15, [j - 1, j + 1], i], grid.U["dwd_e"][15, [j - 1, j + 1], i])
    assert th[0] > 3.0 and th[1] < -3.0                                                            # the stored angles sit on both sides of +-pi
    assert abs(np.mean(th)) < 0.2                                                                  # so averaging the angles themselves would point east
    assert _wave_direction_error(grid, 195.0, 0.0625, 15) < 1.0 and grid.tw.x[15] == t
    w = grid.waves(195.0, 0.0625, t)
    assert abs(w["mdir_to"].value - w["dir_to"].value + 5.73) < 0.5                                # mwd = dwd + 0.1 rad: 5.73 degrees less in compass terms


def test_waves_are_nan_only_inside_the_land_patch(grid):
    t = grid.tw.x[5]
    h = grid.waves(np.array([196.8125, 196.75, 196.0]), np.array([-1.8125, -1.75, 0.0]), t)["Hs"].value
    assert np.isnan(h[0]) and np.isnan(h[1]) and np.isfinite(h[2])
    edge = grid.waves(196.65, -1.7, t)["Hs"].value                                                  # between land and sea nodes: sea nodes only
    assert np.isfinite(edge) and abs(edge - fx.umwm2d(196.65, -1.7, grid.tw.x[5])["swh"]) < 0.1


def test_stokes_without_subgrid_is_off(grid):
    s = grid.waves(195.0, 0.0, grid.tw.x[3])["stokes0"]
    assert np.array_equal(s.value, [0.0, 0.0]) and s.kind == "assumed" and "off" in s.source


# ------------------------------------------------------------------------------------------------------------ restart spectra

def test_restart_spectrum_reproduces_swh(grid):
    it = int(np.flatnonzero(np.isin(grid.tw.x, grid.spec["t"]))[3])
    t = grid.tw.x[it]
    lon, lat = float(grid.spec["lon"][20]), float(grid.spec["lat"][20])
    r = grid.restart_spectrum(lon, lat, t)
    assert r["t"] == t and r["lon"] == lon and r["lat"] == lat and r["F"].shape == (32, 37) and "restart spectrum" in r["source"]
    assert waves.hs_from_restart(r["F"], r["k"], r["f"], r["th"]) == pytest.approx(float(fx.sea_state(lon, lat, t)["hs"]), rel=1e-4)
    assert np.allclose(r["k"], (2 * np.pi * r["f"]) ** 2 / 9.81, rtol=1e-5)                          # deep-water dispersion
    assert r["th"].min() > -np.pi and r["th"].max() < np.pi


def test_restart_spectrum_peak_is_downwind_at_the_jonswap_frequency(grid):
    t = float(grid.spec["t"][2])
    lon, lat = float(grid.spec["lon"][30]), float(grid.spec["lat"][30])
    r = grid.restart_spectrum(lon, lat, t)
    E2 = waves.spectrum_from_restart(r["F"], r["k"], r["f"], r["th"])
    th = waves.theta_compass(r["th"])
    jf, jt = np.unravel_index(np.argmax(E2), E2.shape)
    assert abs(r["f"][jf] - fx.sea_state(lon, lat, t)["fp"]) < 0.1 * r["f"][jf] and abs(th[jt] - 270.0) < 20


def test_restart_spectrum_gives_up_when_too_far_in_space_or_time(grid):
    t = float(grid.spec["t"][2])
    lon, lat = float(grid.spec["lon"][30]), float(grid.spec["lat"][30])
    assert grid.restart_spectrum(lon + 0.1, lat + 0.1, t + 3000.0) is not None                       # 15 km and 50 min off still counts
    assert grid.restart_spectrum(lon, lat, t, max_h=0.5) is not None and grid.restart_spectrum(lon, lat, t + 3600.0, max_h=0.5) is None
    assert grid.restart_spectrum(lon, lat, t + 20 * 86400.0) is None
    assert grid.restart_spectrum(lon + 0.2, lat, t, max_km=5.0) is None and grid.restart_spectrum(lon + 0.2, lat, t, max_km=40.0) is not None
    assert grid.restart_spectrum(lon - 360.0, lat, t) is not None                                    # lon in either convention


# ------------------------------------------------------------------------------------------------------------ depth without an ocean

def test_depth_falls_back_to_the_umwm_floor_without_an_ocean(grid):
    d = grid.depth(np.array([194.0, 196.0]), np.array([-1.0, 1.0]))
    assert np.allclose(d.value, fx.seafloor(np.array([194.0, 196.0]), np.array([-1.0, 1.0])), atol=0.05) and d.source == "UMWM depth (12 km)"


def test_depth_prefers_the_ocean_bathymetry_when_it_has_one(grid):
    class Bathy:
        def bathymetry(self, lon, lat):
            return "from the ocean"
    env = GriddedEnv.__new__(GriddedEnv)
    env.__dict__.update(grid.__dict__)
    env.ocean = Bathy()
    assert env.depth(195.0, 0.0) == "from the ocean"
    env.ocean = object()                                                                           # an ocean without bathymetry
    assert env.depth(195.0, 0.0).source == "UMWM depth (12 km)"


def test_sst_is_the_frozen_wrf_field(grid):
    lon, lat = nodes(grid)
    a, b = grid.sst(lon, lat, grid.tw.x[0]), grid.sst(lon, lat, grid.tw.x[-1])
    assert np.allclose(a.value, 273.15 + fx.ocean(0.0, lat, lon, fx.T_REF)[0], atol=2e-4) and np.array_equal(a.value, b.value)    # SST_UPDATE = 0
    assert a.uncertainty == env_sigmas()["sst_k"] and "frozen" in a.source


def test_ocean_calls_without_an_ocean_say_so(grid):
    with pytest.raises(OutsideData, match="no ocean source loaded"):
        grid.current(195.0, 0.0, -10.0, grid.tw.x[0])


def test_3d_winds_go_through_the_grid_to_earth_rotation_like_u10(grid, monkeypatch):
    """U3/V3 are grid-relative like U10. Store the analytic earth wind as the components of a grid rotated alpha CCW from east: the
    wind above the first mass level must come back earth-relative; without the rotation it would be turned by alpha."""
    t = E.to_seconds("2023-03-02T01:30:00Z")
    z = np.array([60.0, 100.0, 300.0])
    lon, lat = np.full(3, 195.1), np.full(3, 0.3)
    want = grid.wind(lon, lat, z, t).value
    a = np.radians(30.0)
    ue, ve = grid.w3["U"].copy(), grid.w3["V"].copy()
    monkeypatch.setitem(grid.w3, "U", ue * np.cos(a) + ve * np.sin(a))
    monkeypatch.setitem(grid.w3, "V", -ue * np.sin(a) + ve * np.cos(a))
    for name, v in (("COSALPHA", np.cos(a)), ("SINALPHA", np.sin(a))):
        monkeypatch.setitem(grid.Wstatic, name, np.full(grid.Wstatic[name].shape, v))
    got = grid.wind(lon, lat, z, t)
    assert "WRF 3-D U/V" in got.source and np.allclose(got.value, want, atol=1e-9)
    monkeypatch.setattr(E.cv, "rotate_grid_to_earth", lambda u, v, c, s: (u, v))                                          # the old behaviour
    assert not np.allclose(grid.wind(lon, lat, z, t).value, want, atol=1e-3)


# ------------------------------------------------------------------------------------------------------------ use_3d, lenient (review round 2, M-6 and M-11)

def test_use_3d_off_gives_the_u10_profile_in_a_sortie_hour_and_the_source_says_so(grid, monkeypatch):
    monkeypatch.setitem(grid.w3, "U", grid.w3["U"] * 1.5)                                              # a 3-D field that is not the log profile
    t = E.to_seconds("2023-03-02T01:30:00Z")
    z = np.array([30.0, 100.0, 300.0])
    lon, lat = np.full(3, 195.1), np.full(3, 0.3)
    on = grid.wind(lon, lat, z, t)
    assert "WRF 3-D U/V" in on.source and grid.use_3d
    monkeypatch.setattr(grid, "use_3d", False)
    off = grid.wind(lon, lat, z, t)
    assert "WRF 3-D U/V" not in off.source and "3-D WRF U/V not used (use_3d is off)" in off.source
    assert not np.allclose(off.value, on.value, atol=0.1)                                              # the two wind models differ above the first level
    u10 = grid.u10(lon, lat, t)
    ratio = np.log(z / 2e-4) / np.log(10.0 / 2e-4)
    assert np.allclose(off.value, u10 * ratio[:, None], rtol=1e-6)                                     # the neutral profile scaled from U10


def test_the_source_names_why_the_3d_fields_were_not_used(grid, bare):
    assert "no 3-D fields" in bare.wind(195.0, 0.0, 100.0, bare.tw.x[8]).source
    assert "no ingested 3-D hour here" in grid.wind(195.0, 0.0, 100.0, E.to_seconds("2023-03-02T02:30:00Z")).source


def test_the_env_counts_wind_points_and_those_answered_from_the_3d_fields(grid):
    grid.wind_points = grid.wind3d_points = 0
    z = np.array([30.0, 100.0])
    grid.wind(np.full(2, 195.1), np.full(2, 0.3), z, E.to_seconds("2023-03-02T01:30:00Z"))        # sortie hour: both from the 3-D fields
    grid.wind(np.full(2, 195.1), np.full(2, 0.3), z, E.to_seconds("2023-03-02T03:30:00Z"))        # no 3-D hour: U10 profile
    grid.wind(np.full(2, 195.1), np.full(2, 0.3), np.array([10.0, 15.0]), E.to_seconds("2023-03-02T01:30:00Z"))   # below the first level: U10 profile
    assert (grid.wind_points, grid.wind3d_points) == (6, 2)


def test_lenient_returns_edge_values_inside_the_block_and_restores_strictness(grid):
    t = grid.tw.x[5]
    with grid.lenient() as env:
        assert env is grid and not grid.strict
        assert np.allclose(grid.u10(190.0, 0.0, t), grid.u10(grid.low.x[0], 0.0, t))                 # edge-held, no OutsideData
        assert not grid.inside(190.0, 0.0, t)                                                        # and `inside` still says it is outside
    assert grid.strict
    with pytest.raises(OutsideData):
        grid.u10(190.0, 0.0, t)
    with pytest.raises(RuntimeError):
        with grid.lenient():
            raise RuntimeError("x")
    assert grid.strict                                                                                # restored even when the block raises


def test_lenient_holds_the_edge_depth_off_the_bathymetry_grid_and_inside_says_so(grid):
    # q3 at afe0218: a glider past lat 7.002 hit GEBCO's own bounds check and the whole run crashed instead of failing as left_data
    import types
    from cafe.pm.env.bathy import Bathymetry
    b = Bathymetry(np.array([194.0, 196.0]), np.array([-0.5, 0.5]), np.array([[100.0, 200.0], [300.0, 400.0]]), "toy", 1000.0, 1.0)
    env = GriddedEnv.__new__(GriddedEnv)
    env.__dict__.update(grid.__dict__)
    env.ocean = types.SimpleNamespace(bathy=b, bathymetry=b)
    t = grid.tw.x[5]
    assert grid.inside(195.0, 0.9, t) and not env.inside(195.0, 0.9, t)                              # inside WRF, outside the bathymetry grid
    with pytest.raises(ValueError, match="outside the toy grid"):
        env.depth(195.0, 0.9)                                                                         # strict: still raises
    with env.lenient():
        assert np.allclose(env.depth(195.0, 0.9).value, env.depth(195.0, 0.5).value)                 # lenient: the edge depth
        assert np.allclose(env.depth(-165.0, 0.0).value, b(195.0, 0.0).value)                        # a -180..180 longitude is wrapped first


def _copy_cache(ci_env, tmp_path):
    d = tmp_path / "cache"
    shutil.copytree(ci_env.cache, d)
    return d


def test_r5_m19_a_truncated_chunk_is_a_config_error_naming_the_file_and_the_fix(ci_env, tmp_path):
    from cafe.pm.config import ConfigError
    d = _copy_cache(ci_env, tmp_path)
    chunk = next(p for p in sorted((d / "orca" / "wrf.zarr" / "U10").rglob("*")) if p.is_file() and p.name != "zarr.json")
    chunk.write_bytes(b"")
    with pytest.raises(ConfigError, match=r"environment cache file .*wrf\.zarr cannot be read .*delete .*orca and run `python -m cafe.pm fetch"):
        GriddedEnv(d, env_sigmas())


def test_r5_m19_a_corrupt_zarr_json_is_a_config_error_for_every_store(ci_env, tmp_path):
    from cafe.pm.config import ConfigError
    for store in ("umwm.zarr", "wrf3d.zarr", "umwmspec.zarr"):
        d = _copy_cache(ci_env, tmp_path / store)
        (d / "orca" / store / "zarr.json").write_text("{not json")
        with pytest.raises(ConfigError, match=rf"environment cache file .*{store} cannot be read"):
            GriddedEnv(d, env_sigmas())
