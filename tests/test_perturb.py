import numpy as np
import pytest

from cafe.pm.env.perturb import Field, PerturbedEnv, _rot
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
