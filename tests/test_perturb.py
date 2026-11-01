import numpy as np
import pytest

from cafe.pm.env.perturb import Field, PerturbedEnv, WindNoise, _rot
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats.sampling import load_perturbations

PRI = load_perturbations()


def test_rotation_is_clockwise_compass():
    assert np.allclose(_rot(np.array([[0.0, 1.0]]), np.array([90.0])), [[1.0, 0.0]])     # north -> east
    assert not np.allclose(_rot(np.array([[0.0, 1.0]]), np.array([-90.0])), [[1.0, 0.0]])


def test_field_unit_variance_and_correlation_length():
    ell = 100e3
    f = Field(7, range(400), "s", ell)
    lon = np.zeros((400, 3))
    lat = np.array([0.0, np.degrees(ell / 6.371e6), np.degrees(5 * ell / 6.371e6)])[None, :].repeat(400, 0)
    g = f(lon, lat)
    assert abs(g[:, 0].var() - 1) < 0.2
    r1 = np.corrcoef(g[:, 0], g[:, 1])[0, 1]
    r5 = np.corrcoef(g[:, 0], g[:, 2])[0, 1]
    assert abs(r1 - np.exp(-0.5)) < 0.15 and abs(r5) < 0.2            # Gaussian covariance exp(-d^2 / 2 ell^2)


def test_field_needs_member_axis():
    with pytest.raises(ValueError):
        Field(1, range(4), "s", 1e5)(np.zeros(3), np.zeros(3))


def _pe(X, M=4, cur=(0.5, 0.0)):
    return PerturbedEnv(AnalyticEnv(wind=(0.0, 5.0), current=cur), X, list(range(M)), 11, PRI)


def test_wind_bias_and_direction():
    M = 4
    pe = _pe(dict(wind_speed_bias=np.array([0, 1, -10, 0.0]), wind_direction_bias=np.array([0, 0, 0, 90.0])))
    v = pe.wind(np.zeros(M), np.zeros(M), 10.0, 0.0).value
    assert np.allclose(v[0], [0, 5]) and np.allclose(v[1], [0, 6]) and np.allclose(v[2], [0, 0]) and np.allclose(v[3], [5, 0])


def test_current_crn_same_members_same_field():
    X = dict(current_speed_scale=np.ones(4), current_direction_bias=np.zeros(4))
    a = _pe(X).current(np.zeros(4), np.zeros(4), 0.0, 0.0).value
    b = _pe(X).current(np.zeros(4), np.zeros(4), 0.0, 0.0).value
    assert np.array_equal(a, b)                                       # same members, same draws, any vehicle
    assert not np.allclose(a[0], a[1])                                # but members differ


def test_current_spread_matches_prior():
    M = 2000
    pe = PerturbedEnv(AnalyticEnv(current=(1.0, 0.0)), {}, list(range(M)), 3, PRI)
    v = pe.current(np.zeros(M), np.zeros(M), 0.0, 0.0).value
    s = np.log(np.hypot(v[:, 0], v[:, 1]))
    assert abs(s.std() - PRI["current_speed_scale"]["value"] / np.sqrt(2)) < 0.03   # field half of the variance


def test_waves_scaled():
    pe = _pe(dict(hs_scale=np.array([1, 2, 1, 1.0]), tp_bias=np.array([0, 0, -20, 1.0])))
    w = pe.waves(np.zeros(4), np.zeros(4), 0.0)
    assert np.allclose(w["Hs"].value, [1, 2, 1, 1]) and np.allclose(w["Tp"].value, [8, 8, 1, 9])
    assert pe.depth(0.0, 0.0).value == 4000.0                          # pass-through


def test_no_draws_is_identity_in_mean():
    pe = _pe({})
    assert np.allclose(pe.wind(np.zeros(4), np.zeros(4), 10.0, 0.0).value, [0, 5])
    assert set(pe.waves(np.zeros(4), np.zeros(4), 0.0)) >= {"Hs", "Tp"}


# ------------------------------------------------------------------------------------------------------------ review round 2, M-1 (apply side) and M-21

NOISE_PRI = dict(PRI, wind_speed_noise=dict(dist="normal", value=1.2, tau_h=5.0, unit="m/s", kind="data"),
                 wind_direction_noise=dict(dist="normal", value=20.0, tau_h=0.0, unit="deg", kind="data"))
WIN = (0.0, 6 * 86400.0)


def test_wind_noise_is_a_stationary_ar1_series_per_member_with_the_fitted_sd_and_time_scale():
    """M-1: the short-lived part of the wind error: sd and e-folding time as fitted, independent between members."""
    z = WindNoise(3, range(1500), "wind_speed_noise", dict(value=1.2, tau_h=5.0), *WIN).x
    assert z.shape == (1500, 145) and abs(z.mean()) < 0.02 and z.std() == pytest.approx(1.2, rel=0.03)
    assert z[:, 0].std() == pytest.approx(1.2, rel=0.06) and z[:, -1].std() == pytest.approx(1.2, rel=0.06)          # stationary from the first hour
    lag1 = np.mean(z[:, :-1] * z[:, 1:]) / z.var()
    assert lag1 == pytest.approx(np.exp(-1.0 / 5.0), abs=0.02) and np.mean(z[:, :-24] * z[:, 24:]) / z.var() == pytest.approx(np.exp(-24.0 / 5.0), abs=0.02)
    white = WindNoise(3, range(1500), "wind_direction_noise", dict(value=20.0, tau_h=0.0), *WIN).x
    assert white.std() == pytest.approx(20.0, rel=0.03) and abs(np.mean(white[:, :-1] * white[:, 1:]) / white.var()) < 0.02
    assert not np.allclose(z[0], z[1])


def test_a_members_wind_noise_is_the_same_in_any_batch_and_any_call_order():
    a = WindNoise(3, [0, 1, 2, 3], "wind_speed_noise", dict(value=1.2, tau_h=5.0), *WIN)
    b = WindNoise(3, [3, 9], "wind_speed_noise", dict(value=1.2, tau_h=5.0), *WIN)
    assert np.array_equal(a.x[3], b.x[0]) and not np.array_equal(a.x[3], b.x[1])
    t = np.array([[0.0, 7200.0, 4 * 3600.0]] * 4)
    assert np.array_equal(a(t, (4, 3)), a(t, (4, 3))) and np.array_equal(a(t, (4, 3))[:, 1], a.x[:, 2])


def test_the_wind_noise_is_held_for_the_hour_it_was_fitted_on_and_at_the_ends_of_the_window():
    w = WindNoise(3, range(2), "wind_speed_noise", dict(value=1.0, tau_h=2.0), *WIN)
    assert w(1799.0, (2,)).tolist() == w.x[:, 0].tolist() and w(1801.0, (2,)).tolist() == w.x[:, 1].tolist()      # nearest hour
    assert w(-1e6, (2,)).tolist() == w.x[:, 0].tolist() and w(1e9, (2,)).tolist() == w.x[:, -1].tolist()


def test_the_fitted_noise_is_added_to_the_members_wind_everywhere_and_to_nothing_else():
    """M-1: speed and direction noise act on top of the persistent biases, at every place and height, as one number per member and hour."""
    M = 3
    X = dict(wind_speed_bias=np.array([0.5, 0.5, 0.5]), wind_direction_bias=np.array([10.0, 0.0, 0.0]))
    pe = PerturbedEnv(AnalyticEnv(wind=(0.0, 5.0)), X, list(range(M)), 11, NOISE_PRI, window=WIN)
    plain = PerturbedEnv(AnalyticEnv(wind=(0.0, 5.0)), X, list(range(M)), 11, PRI)
    t = 7 * 3600.0
    v = pe.wind(np.full(M, 190.0), np.zeros(M), 10.0, t).value
    ds, dd = pe.wn["wind_speed_noise"](t, (M,)), pe.wn["wind_direction_noise"](t, (M,))
    assert np.allclose(np.hypot(*v.T), 5.5 + ds)
    assert np.allclose(np.degrees(np.arctan2(v[:, 0], v[:, 1])), 10.0 * np.array([1, 0, 0]) + dd)       # blowing toward north: rotated clockwise
    again = pe.wind(np.linspace(185.0, 195.0, M), np.linspace(-1.0, 1.0, M), 10.0, t).value                  # another place: the same error
    assert np.allclose(again, v)
    assert not np.allclose(pe.wind(np.full(M, 190.0), np.zeros(M), 10.0, t + 6 * 3600.0).value, v)            # six hours on it has changed
    base = plain.wind(np.full(M, 190.0), np.zeros(M), 10.0, t).value
    assert np.allclose(np.hypot(*base.T), 5.5)
    assert np.allclose(plain.wind(np.full(M, 190.0), np.zeros(M), 10.0, t + 6 * 3600.0).value, base)                   # no fit: no noise
    assert not plain.wn
    assert np.allclose(pe.current(np.full(M, 190.0), np.zeros(M), -1.0, t).value, plain.current(np.full(M, 190.0), np.zeros(M), -1.0, t).value)


def test_the_noise_needs_the_window_it_runs_over_and_takes_it_from_the_sde_when_there_is_one():
    with pytest.raises(ValueError, match="window"):
        PerturbedEnv(AnalyticEnv(), {}, [0, 1], 11, NOISE_PRI)
    pe = PerturbedEnv(AnalyticEnv(), {}, [0, 1], 11, NOISE_PRI, sde=dict(t0=100.0, t1=100.0 + 7200.0, dt=60.0))
    assert pe.wn["wind_speed_noise"].t0 == 100.0 and pe.wn["wind_speed_noise"].n == 3


def test_the_noise_is_vectorised_over_members():
    """M-1: 256 members over a 30-day window are built in well under a second, and a wind query costs one gather."""
    import time
    a = time.perf_counter()
    pe = PerturbedEnv(AnalyticEnv(), {}, list(range(256)), 11, NOISE_PRI, window=(0.0, 30 * 86400.0))
    b = time.perf_counter()
    for _ in range(100):
        pe.wind(np.zeros(256), np.zeros(256), 10.0, 1e6)
    c = time.perf_counter()
    assert b - a < 3.0 and (c - b) / 100 < 0.01


def test_a_period_change_scales_the_stokes_drift_with_one_over_tp_cubed():
    """M-21: surface Stokes drift of a fixed spectrum shape goes as Hs^2 / Tp^3; a Tp of 8 s instead of 9 s raises it by (9/8)^3."""
    class Waves(AnalyticEnv):
        def waves(self, lon, lat, t):
            w = super().waves(lon, lat, t)
            return dict(w, stokes0=w["stokes0"]._replace(value=np.full(np.shape(w["Hs"].value) + (2,), 0.1)))
    pe = PerturbedEnv(Waves(tp=9.0), dict(tp_bias=np.array([-1.0, 0.0, 1.0, -100.0]), hs_scale=np.array([1.0, 1.0, 1.0, 2.0])), list(range(4)), 3, PRI)
    s = pe.waves(np.zeros(4), np.zeros(4), 0.0)["stokes0"].value
    assert np.allclose(s[:3, 0], 0.1 * np.array([(9 / 8) ** 3, 1.0, (9 / 10) ** 3]))
    assert np.allclose(s[3, 0], 0.1 * 4 * 9.0 ** 3)                                                                     # Hs x 2, Tp floored at 1 s


# Review round 4
def test_m6_the_current_speed_factor_has_median_one_as_documented():
    """M-6: the factor was exp(log a / sqrt 2 + cs f / sqrt 2 - cs^2 / 4): with no field error and a = 1 it cut every current by 2 %."""
    pe = PerturbedEnv(AnalyticEnv(current=(1.0, 0.0)), dict(current_speed_scale=np.ones(3)), [0, 1, 2], 3, PRI)
    pe.fs = lambda lon, lat: np.zeros(np.shape(lon))
    assert np.allclose(np.hypot(*pe.current(np.zeros(3), np.zeros(3), 0.0, 0.0).value.T), 1.0, atol=1e-12)
    M = 4000
    from scipy.stats import norm
    a = np.exp(PRI["current_speed_scale"]["value"] * norm.ppf((np.arange(M) + 0.5) / M))                       # lognormal(median 1, sigma cs), stratified
    pe = PerturbedEnv(AnalyticEnv(current=(1.0, 0.0)), dict(current_speed_scale=a), list(range(M)), 3, PRI)
    v = pe.current(np.zeros(M), np.zeros(M), 0.0, 0.0).value
    assert 0.99 < np.median(np.hypot(v[:, 0], v[:, 1])) < 1.01                                                   # 0.978 before the fix


def test_m9_the_current_error_field_has_no_seam_at_180_degrees():
    lat = np.zeros(4)
    f = Field(20230301, [0, 1, 2, 3], "current_speed_field", 100e3, lon0=180.0)
    assert np.abs(f(np.full(4, 179.99), lat) - f(np.full(4, -179.99), lat)).max() < 0.1                          # 2 km apart: 3.18 sigma before
    plain = Field(20230301, [0, 1, 2, 3], "current_speed_field", 100e3)
    assert np.abs(plain(np.full(4, 179.99), lat) - plain(np.full(4, -179.99), lat)).max() > 1.0                  # the default origin keeps its seam at 180
    here = np.full(4, -170.0)
    la = lat + 1.0
    x, y = np.radians(here) * 6.371e6 * np.cos(np.radians(la)), np.radians(la) * 6.371e6                         # the old formula, away from the seam
    old = np.sqrt(2.0 / 32) * np.cos(x[:, None] * plain.k[:, :, 0] + y[:, None] * plain.k[:, :, 1] + plain.ph).sum(-1)
    zero = Field(20230301, [0, 1, 2, 3], "current_speed_field", 100e3, lon0=0.0)
    assert np.allclose(plain(here, la), old, rtol=0, atol=1e-9) and np.allclose(zero(here, la), old, atol=1e-9)


def test_m9_a_perturbed_env_over_a_box_across_the_date_line_reads_one_field_over_it():
    box = (165.0, -165.0, -5.0, 5.0, -1e12, 1e12)
    M = 8
    pe = PerturbedEnv(AnalyticEnv(current=(1.0, 0.0), bounds=box), {}, list(range(M)), 3, PRI)
    assert pe.fs.lon0 == pytest.approx(180.0) and pe.fd.lon0 == pytest.approx(180.0)
    z = np.zeros(M)
    a, b = (pe.current(np.full(M, lon), z, 0.0, 0.0).value for lon in (179.99, -179.99))
    assert np.abs(np.log(np.hypot(*a.T) / np.hypot(*b.T))).max() < 0.05                                          # several sigma before
    assert PerturbedEnv(AnalyticEnv(), {}, [0], 3, PRI).fs.lon0 == 0.0                                           # a whole-circle box keeps the old origin
