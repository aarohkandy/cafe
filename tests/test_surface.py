"""cafe.pm.env.surface (the modelled surface layer under the 12 km / 1 h files) against the analytic ci_env fixture: COARE
profile shape, warm layer vs sun and wind, rain-lens sign, diurnal jet direction, Stokes drift vs the fixture spectrum."""
import shutil

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm.config import env_sigmas
from cafe.pm.env import conventions as cv, environment as E, surface as S
from cafe.pm.env.environment import GriddedEnv
from tests.fixtures.ci_env import make as fx

DAY = 7                      # hour index 2023-03-02 01Z = 14:00 local solar time at 165W: the warm layer's afternoon peak
T_RAIN = E.to_seconds("2023-03-02T01:00:00Z")


@pytest.fixture(scope="session")
def sl(ci_full):
    return ci_full.subgrid


@pytest.fixture(scope="session")
def parametric(ci_env, tmp_path_factory):
    """An env over a cache with no restart spectra, whose derived.zarr S.build makes from the fitted spectrum alone."""
    d = tmp_path_factory.mktemp("parametric") / "cache"
    for s in ("wrf.zarr", "umwm.zarr"):
        shutil.copytree(ci_env.cache / "orca" / s, d / "orca" / s)
    messages = []
    fit = S.build(GriddedEnv(d, env_sigmas()), d, log=messages.append)
    return GriddedEnv(d, env_sigmas(), subgrid=S.SurfaceLayer(d)), fit, messages


# ------------------------------------------------------------------------------------------------------------ build

def test_build_checks_the_fitted_stokes_field_against_the_real_spectra(sl, ci_env):
    f = sl.fit
    assert f["n_restart_times"] == 7                                                               # 18Z, 00, 06, 12, 18, 00, 06 over the 36 h window
    assert f["corrected_loo_median_speed_err"] < f["fit_only_median_speed_err"] < 0.1             # the correction helps and the fit alone is already good
    assert f["corrected_loo_median_dir_err_deg"] < 1.0                                             # the fixture waves are aligned downwind everywhere


def test_build_without_restart_spectra_says_so(parametric):
    env, fit, messages = parametric
    assert fit is None and env.subgrid.fit is None and "Stokes fit check None" in messages[0]
    lon, lat, t = np.array([194.4, 196.0]), np.array([-0.7, 0.9]), np.array([fx.T_REF + 9 * 3600.0, fx.T_REF + 20 * 3600.0])
    s = env.waves(lon, lat, t)["stokes0"]
    want = np.stack(fx.stokes_surface(lon, lat, t), -1)
    assert s.kind == "modelled" and "fitted to UMWM" in s.source
    assert np.allclose(s.uncertainty, 0.4 * np.abs(s.value)) and np.all(np.abs(np.hypot(*s.value.T) / np.hypot(*want.T) - 1) < 0.1)   # DHH fit alone: 10 %


# ------------------------------------------------------------------------------------------------------------ COARE

def test_coare_friction_velocity_matches_wrf_and_the_surface_layer_is_unstable(ci_full, sl):
    lon, lat, t = np.full(3, 195.0), np.zeros(3), np.array([fx.T_REF, fx.T_REF + 7 * 3600.0, fx.T_REF + 20 * 3600.0])
    r = sl.coare_at(lon, lat, t)
    assert np.allclose(r["ustar"], ci_full.air(lon, lat, t)["ustar_wrf"].value, rtol=0.05)         # the fixture's WRF UST uses the same drag law at ~neutral
    assert (r["L"] < -5).all() and (r["gf"] > 1.0).all() and (r["z0"] > 1e-5).all() and (r["z0"] < 1e-3).all()   # 28 C sea under 26.5 C air: unstable


def test_wind_profile_ratio_is_monotone_below_the_first_wrf_level(ci_full, sl):
    z = np.array([1.0, 2.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0])
    r, src = sl.profile_ratio(ci_full, 195.0, 0.0, z, fx.T_REF + 7 * 3600.0)
    assert (np.diff(r) > 0).all() and r[4] == pytest.approx(1.0, abs=1e-12) and (r[:4] < 1).all() and (r[5:] > 1).all()
    assert "COARE 3.5" in src
    neutral = np.log(z / 2e-4) / np.log(10.0 / 2e-4)
    assert np.all(np.abs(r / neutral - 1) < 0.1)                                                   # COARE moves the shear by under 10 %, not 2x


@settings(max_examples=25, deadline=None)
@given(lon=st.floats(193.2, 196.8), lat=st.floats(-1.8, 1.8), f=st.floats(0.0, 1.0))
def test_profile_ratio_is_monotone_at_any_point(ci_full, lon, lat, f):
    r, _ = ci_full.subgrid.profile_ratio(ci_full, lon, lat, np.array([0.5, 2.0, 6.0, 10.0, 14.0, 20.0]), fx.T_REF + f * 36 * 3600.0)
    assert (np.diff(r) > 0).all() and r[3] == pytest.approx(1.0, abs=1e-12)


def test_wind_below_21_m_uses_the_coare_profile_and_agrees_with_the_log_law(ci_full):
    t = fx.T_REF + 10 * 3600.0
    w2, w10 = ci_full.wind(195.0, 0.0, 2.0, t), ci_full.wind(195.0, 0.0, 10.0, t)
    assert np.allclose(w10.value, ci_full.u10(195.0, 0.0, t)) and "COARE 3.5" in w2.source
    assert 0.8 < np.hypot(*w2.value) / np.hypot(*w10.value) < 0.95 and np.allclose(cv.to_deg(w2.value), cv.to_deg(w10.value))      # slower, same direction


def test_air_gains_the_modelled_surface_layer_keys(ci_full):
    a = ci_full.air(195.0, 0.0, fx.T_REF + 7 * 3600.0)
    assert {"ustar", "L", "dT_warm"} <= set(a) and all(a[k].kind == "modelled" for k in ("ustar", "L", "dT_warm"))
    assert a["L"].value < 0 and 0.1 < a["ustar"].value < 0.3


# ------------------------------------------------------------------------------------------------------------ warm layer and SST

def test_warm_layer_follows_the_sun_and_the_wind(ci_full, sl):
    t = ci_full.tw.x
    dT = sl._g("dT_warm", np.full(37, 195.0), np.zeros(37), t)
    assert dT[0] == 0.0 and 6 <= int(np.argmax(dT[:24])) <= 9 and 0.1 < dT.max() < 1.0              # builds from zero after sunrise, peaks near 14:00 local
    assert (dT[18:25] < 1e-6).all() and (dT >= 0).all()                                            # gone through the night (local 07:00 to 14:00 the next day)
    peak = lambda lon: sl._g("dT_warm", np.full(37, lon), np.zeros(37), t).max()
    assert peak(193.0) < peak(195.0) < peak(197.0)                                                 # u10 falls from -6 to -3.4 m/s eastward: less mixing, warmer


def test_sst_is_the_frozen_wrf_sst_plus_the_warm_layer(ci_full):
    lon, lat = np.array([194.0, 196.0, 195.0]), np.array([-1.0, 1.0, 0.0])
    for k in (0, DAY, 20):
        t = ci_full.tw.x[k]
        s = ci_full.sst(lon, lat, t)
        dT = ci_full.air(lon, lat, t)["dT_warm"].value
        assert np.allclose(s.value, 273.15 + fx.ocean(0.0, lat, lon, fx.T_REF)[0] + dT, atol=2e-4) and s.kind == "modelled" and "warm layer" in s.source
    assert ci_full.sst(lon, lat, ci_full.tw.x[DAY]).value[2] - ci_full.sst(lon, lat, ci_full.tw.x[20]).value[2] > 0.1


# ------------------------------------------------------------------------------------------------------------ diurnal jet

def test_diurnal_jet_points_downwind_and_vanishes_below_the_warm_layer_and_at_night(ci_full, sl):
    lon, lat = np.array([194.0, 196.0]), np.array([-1.0, 1.0])
    t = ci_full.tw.x[DAY]
    jet = ci_full.current(lon, lat, np.zeros(2), t).value - ci_full.ocean.current(lon, lat, np.zeros(2), t).value
    dT0 = ci_full.air(lon, lat, t)["dT_warm"].value
    assert np.allclose(np.hypot(*jet.T), sl.jet_mid * dT0 / sl.jet_ref, rtol=1e-6) and dT0.min() > 0.1      # amplitude: midpoint x dT_warm / dT_ref
    w = ci_full.u10(lon, lat, t)
    cross = jet[:, 0] * w[:, 1] - jet[:, 1] * w[:, 0]
    assert np.allclose(cross / np.hypot(*jet.T) / np.hypot(*w.T), 0.0, atol=1e-9) and (np.sum(jet * w, -1) > 0).all()    # along the wind, not against it
    deep = ci_full.current(lon, lat, np.full(2, -100.0), t).value - ci_full.ocean.current(lon, lat, np.full(2, -100.0), t).value
    night = ci_full.current(lon, lat, np.zeros(2), ci_full.tw.x[20]).value - ci_full.ocean.current(lon, lat, np.zeros(2), ci_full.tw.x[20]).value
    assert np.abs(deep).max() == 0.0 and np.abs(night).max() < 1e-9
    c = ci_full.current(lon, lat, np.zeros(2), t)
    assert c.kind == "modelled" and "diurnal surface jet" in c.source


# ------------------------------------------------------------------------------------------------------------ rain lens

def test_time_since_rain_counts_hours_after_the_last_rainy_hour(sl, ci_full):
    s = sl._g("since_rain_s", np.full(37, 196.5), np.full(37, 1.5), ci_full.tw.x)
    assert (s[:6] >= 1e9).all()                                                                    # nothing rained before 00Z: the lens clock has not started
    assert list(s[6:9]) == [0.0, 0.0, 0.0] and list(s[9:12]) == [3600.0, 7200.0, 10800.0]          # 10 mm/h at 00Z, 01Z, 02Z, then 1 h, 2 h, 3 h later


def test_rain_lens_makes_the_surface_lighter_than_the_water_under_it(ci_full, sl):
    lon, lat = np.array([196.5, 193.5]), np.array([1.5, -1.5])                                     # in the rain, and far from it
    for z, lens_here in ((0.0, True), (-5.0, False)):
        zz = np.full(2, z)
        rho0 = ci_full.ocean.density(lon, lat, zz, T_RAIN).value
        d = ci_full.density(lon, lat, zz, T_RAIN).value - rho0
        warm = -rho0 * sl.alpha * sl._warm(lon, lat, zz, T_RAIN)[0]                               # the warm layer alone, from alpha(T)
        lens = d - warm
        assert abs(lens[1]) < 1e-9                                                                 # no rain, no lens
        if lens_here:
            assert -0.45 < lens[0] < -0.2 and lens[0] == pytest.approx(-rho0[0] * (sl.beta * 0.5 - sl.alpha * 0.2), rel=0.02)   # beta dS beats the cooling
        else:
            assert abs(lens[0]) < 1e-6                                                             # 0.5 m thick: gone at 5 m


def test_warm_layer_makes_the_afternoon_surface_lighter_not_the_water_below(ci_full, sl):
    lon, lat = np.array([193.5, 193.5]), np.array([-1.5, -1.5])
    z = np.array([0.0, -50.0])
    d = ci_full.density(lon, lat, z, T_RAIN).value - ci_full.ocean.density(lon, lat, z, T_RAIN).value
    assert d[0] < -0.05 and d[1] == 0.0
    assert ci_full.density(195.0, 0.0, 0.0, T_RAIN).source.endswith("warm layer and rain lens (TEOS-10 alpha/beta; modelled)")


def test_thermal_expansion_and_saline_contraction_are_the_teos10_values(sl):
    assert 2.5e-4 < sl.alpha < 3.5e-4 and 7.0e-4 < sl.beta < 7.5e-4                                # 1/K and kg/g at 28 C, S = 35 (gsw)


# ------------------------------------------------------------------------------------------------------------ Stokes drift

def test_stokes_surface_drift_at_a_restart_node_equals_the_fixture_spectrum(ci_full):
    lon, lat = float(ci_full.lou.x[12]), float(ci_full.lau.x[9])
    for k in (6, 12, 24):                                                                          # 00Z, 06Z, 18Z: restart times
        t = ci_full.tw.x[k]
        s = ci_full.waves(lon, lat, t)["stokes0"]
        want = np.array(fx.stokes_surface(lon, lat, t))
        assert np.allclose(s.value, want, rtol=1e-3) and 0.03 < np.hypot(*s.value) < 0.25
        loo = ci_full.subgrid.fit["corrected_loo_median_speed_err"]
        assert "leave-one-out" in s.source and s.kind == "modelled" and np.allclose(s.uncertainty, loo * np.abs(s.value))


def test_stokes_drift_is_aligned_with_the_wave_direction(ci_full):
    lon, lat = np.array([194.3, 196.0, 193.6]), np.array([0.4, -0.7, 1.3])
    t = ci_full.tw.x[np.array([9, 20, 31])]
    w = ci_full.waves(lon, lat, t)
    diff = (cv.to_deg(w["stokes0"].value) - w["dir_to"].value + 180.0) % 360.0 - 180.0
    assert np.abs(diff).max() < 3.0                                                                # built on dwd; the correction turns it < 1 deg
    swapped = cv.to_deg(w["stokes0"].value[..., ::-1])                                             # east and north exchanged would not be aligned
    assert np.abs((swapped - w["dir_to"].value + 180.0) % 360.0 - 180.0).min() > 20.0
