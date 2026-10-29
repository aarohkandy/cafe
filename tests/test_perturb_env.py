"""cafe.pm.env.perturb over the real GriddedEnv of the ci_env fixture: each member's forcing error is applied with the compass
conventions (clockwise rotation, "from" vs "toward") on the analytic wind, current and waves."""
import copy

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from cafe.pm.env import conventions as cv, environment as E, perturb as P, subgrid as SG
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.stats.sampling import load_perturbations

T = E.to_seconds("2023-03-02T03:00:00Z")
PRI = load_perturbations()
QUIET = copy.deepcopy(PRI)                                       # no random current field: only the member-wide draws act
QUIET["current_speed_scale"]["value"] = 0.0
QUIET["current_direction_bias"]["value"] = 0.0


def member_env(env, X, M, priors=QUIET):
    return P.PerturbedEnv(env, X, list(range(M)), 7, priors)


def _rotation_checks(pe, base):
    """Members: unchanged, +1 m/s, floored at zero, rotated 90 degrees clockwise (compass): west -> north."""
    M = 4
    ones = np.ones(M)
    v = pe.wind(195.0 * ones, 0.0 * ones, 10.0, T).value
    assert np.allclose(v[0], base) and np.allclose(np.hypot(*v[1]), np.hypot(*base) + 1.0) and np.allclose(v[2], 0.0)
    assert np.allclose(np.hypot(*v[3]), np.hypot(*base)) and np.isclose((cv.to_deg(v[3]) - cv.to_deg(base) + 180.0) % 360.0 - 180.0, 90.0)


def test_wind_error_changes_speed_and_rotates_the_direction_clockwise(ci_full):
    X = dict(wind_speed_bias=np.array([0.0, 1.0, -100.0, 0.0]), wind_direction_bias=np.array([0.0, 0.0, 0.0, 90.0]))
    pe = member_env(ci_full, X, 4)
    base = ci_full.wind(195.0, 0.0, 10.0, T).value
    assert np.hypot(*base) > 3 and abs(cv.to_deg(base) - 270.0) < 20                               # trade wind blowing toward the west
    _rotation_checks(pe, base)
    assert "member wind error applied" in pe.wind(np.full(4, 195.0), np.zeros(4), 10.0, T).source


def _ccw(v, deg):
    """The broken variant: the same rotation counter-clockwise."""
    r = np.radians(deg)[..., None]
    c, s = np.cos(r), np.sin(r)
    return np.concatenate([v[..., 0:1] * c[..., 0:1] - v[..., 1:2] * s[..., 0:1], v[..., 0:1] * s[..., 0:1] + v[..., 1:2] * c[..., 0:1]], -1)


def test_a_counter_clockwise_wind_rotation_is_caught(ci_full, monkeypatch):
    X = dict(wind_speed_bias=np.array([0.0, 1.0, -100.0, 0.0]), wind_direction_bias=np.array([0.0, 0.0, 0.0, 90.0]))
    monkeypatch.setattr(P, "_rot", _ccw)
    with pytest.raises(AssertionError):
        _rotation_checks(member_env(ci_full, X, 4), ci_full.wind(195.0, 0.0, 10.0, T).value)


@settings(max_examples=40, deadline=None)
@given(st.floats(-20, 20), st.floats(-20, 20), st.floats(-720, 720))
def test_rotation_keeps_the_length_and_turns_by_the_requested_compass_angle(e, n, deg):
    v = np.array([[e, n]])
    w = P._rot(v, np.array([deg]))
    assert np.isclose(np.hypot(*w[0]), np.hypot(e, n), atol=1e-9)
    if np.hypot(e, n) > 1e-3:
        assert np.isclose((cv.to_deg(w[0]) - cv.to_deg(v[0]) - deg + 180.0) % 360.0 - 180.0, 0.0, atol=1e-6)      # compass angles grow clockwise
    assert np.allclose(P._rot(w, np.array([-deg])), v, atol=1e-9)


def _current_checks(pe, ci_full):
    """Draw 4 and 90 deg for member 0, nothing for member 1, on the eastward undercurrent at 100 m."""
    M = 2
    lon, lat, z = np.full(M, 195.0), np.zeros(M), np.full(M, -100.0)
    base = ci_full.current(lon, lat, z, T).value[0]
    v = pe.current(lon, lat, z, T).value
    assert base[0] > 0.9 and abs(base[1]) < 0.05                                                   # the undercurrent flows east
    assert np.allclose(v[1], base)                                                                 # draw 1 and 0 deg: unchanged
    assert np.isclose(np.hypot(*v[0]), np.hypot(*base) * 4.0 ** (1 / np.sqrt(2.0)))                # half of the log-variance is member-wide
    assert np.isclose((cv.to_deg(v[0]) - cv.to_deg(base) + 180.0) % 360.0 - 180.0, 90.0 / np.sqrt(2.0)) and v[0, 1] < 0   # clockwise from east: south
    return pe.current(lon, lat, z, T).source


def _current_env(ci_full):
    X = dict(current_speed_scale=np.array([4.0, 1.0]), current_direction_bias=np.array([90.0, 0.0]))
    return member_env(ci_full, X, 2)


def test_current_error_scales_by_a_power_of_the_draw_and_rotates_clockwise(ci_full):
    assert "member current error applied" in _current_checks(_current_env(ci_full), ci_full)


def test_current_rotation_sign_flip_is_caught(ci_full, monkeypatch):
    monkeypatch.setattr(P, "_rot", _ccw)
    with pytest.raises(AssertionError):
        _current_checks(_current_env(ci_full), ci_full)


def test_current_random_field_is_smooth_below_the_correlation_length(ci_full):
    M = 64
    pe = P.PerturbedEnv(ci_full, {}, list(range(M)), 3, PRI)
    z = np.full(M, -100.0)
    a = pe.current(np.full(M, 195.0), np.zeros(M), z, T).value
    near = pe.current(np.full(M, 195.0), np.full(M, 0.01), z, T).value                             # 1 km north
    far = pe.current(np.full(M, 195.0), np.full(M, 1.5), z, T).value                               # 170 km north
    base = ci_full.current(np.full(M, 195.0), np.zeros(M), z, T).value
    r = lambda x: np.log(np.hypot(*x.T) / np.hypot(*base.T))
    assert np.abs(r(a) - r(near)).max() < 0.02 and np.std(r(a)) > 0.1                              # nearly equal 1 km apart, members differ
    assert np.abs(np.corrcoef(r(a), r(far))[0, 1]) < 0.45


def test_wave_error_scales_height_and_the_quadratic_stokes_drift_but_not_the_direction(ci_full):
    M = 3
    X = dict(hs_scale=np.array([1.0, 2.0, 1.0]), tp_bias=np.array([0.0, 0.0, -50.0]))
    pe = member_env(ci_full, X, M)
    lon, lat = np.full(M, 195.0), np.zeros(M)
    w, w0 = pe.waves(lon, lat, T), ci_full.waves(lon, lat, T)
    assert np.allclose(w["Hs"].value, [w0["Hs"].value[0], 2 * w0["Hs"].value[1], w0["Hs"].value[2]])
    assert np.allclose(w["stokes0"].value[1], 4.0 * w0["stokes0"].value[1]) and np.allclose(w["stokes0"].value[[0, 2]], w0["stokes0"].value[[0, 2]])
    assert np.allclose(w["Tp"].value[[0, 1]], w0["Tp"].value[[0, 1]]) and w["Tp"].value[2] == 1.0 and w["Tm"].value[2] == 1.0       # floored at 1 s
    assert np.array_equal(w["dir_to"].value, w0["dir_to"].value)
    assert abs(cv.to_deg(w["stokes0"].value[1]) - w["dir_to"].value[1]) < 3.0


def test_everything_else_passes_through_unchanged(ci_full):
    pe = member_env(ci_full, {}, 2)
    lon, lat, z = np.full(2, 194.5), np.full(2, 0.5), np.full(2, -50.0)
    assert np.array_equal(pe.density(lon, lat, z, T).value, ci_full.density(lon, lat, z, T).value)
    assert np.array_equal(pe.sound_speed(lon, lat, z, T).value, ci_full.sound_speed(lon, lat, z, T).value)
    assert np.array_equal(pe.depth(lon, lat).value, ci_full.depth(lon, lat).value) and np.array_equal(pe.sst(lon, lat, T).value, ci_full.sst(lon, lat, T).value)
    assert pe.bounds == ci_full.bounds and list(pe.inside(lon, lat)) == [True, True]
    assert np.array_equal(pe.air(lon, lat, T)["T2"].value, ci_full.air(lon, lat, T)["T2"].value)
    w = pe.wind(lon, lat, 10.0, T).value                                                           # no draws: the member wind is the env wind
    assert np.allclose(w, ci_full.wind(lon, lat, 10.0, T).value)


# ------------------------------------------------------------------------------------------------------------ ocean SDE

M_PER_DEG = 111195.0


def sde_env(M=1500, steps=720, members=None, seed=3, **kw):
    return P.PerturbedEnv(AnalyticEnv(), {}, list(range(M)) if members is None else members, seed, QUIET,
                          sde=dict(t0=0.0, t1=steps * 60.0, dt=60.0), **kw)


def drift_particles(pe, M, steps, lat0=0.0):
    """Passive particles from (0, lat0), moved each minute by the current the environment returns, as the vehicles do. -> positions [m]."""
    x = np.zeros((M, 2))
    for k in range(steps):
        v = pe.current(x[:, 0] / M_PER_DEG, lat0 + x[:, 1] / M_PER_DEG, 0.0, k * 60.0).value
        x += v * 60.0
    return x


def test_passive_particles_disperse_as_2Kt_in_both_directions_with_no_mean_drift():
    M, steps = 1500, 720
    x = drift_particles(sde_env(M, steps), M, steps)
    K = float(SG.sde_diffusivity(0.0)[0])
    var = 2 * K * steps * 60.0
    assert np.allclose(x.var(0), var, rtol=0.08)                                                    # statistical error of a variance from 1500 draws: 3.7 %
    assert np.all(np.abs(x.mean(0)) < 4 * np.sqrt(var / M))                                         # no drift where K is uniform
    short = drift_particles(sde_env(M, steps), M, 180)                                              # a quarter of the time: a quarter of the variance
    assert np.allclose(short.var(0), var / 4, rtol=0.1)


def test_without_the_sde_the_current_is_exactly_the_perturbed_current():
    pe = sde_env()
    off = P.PerturbedEnv(AnalyticEnv(current=(0.2, 0.1)), {}, list(range(1500)), 3, QUIET)
    on = P.PerturbedEnv(AnalyticEnv(current=(0.2, 0.1)), {}, list(range(1500)), 3, QUIET, sde=dict(t0=0.0, t1=43200.0, dt=60.0))
    a, b = off.current(np.zeros(1500), np.zeros(1500), 0.0, 120.0), on.current(np.zeros(1500), np.zeros(1500), 0.0, 120.0)
    assert pe.sde is not None and off.sde is None and "Lagrangian SDE" in b.source and "Lagrangian SDE" not in a.source
    assert not np.allclose(a.value, b.value) and abs((b.value - a.value).mean()) < 0.05            # noise of zero mean around the same current


def test_the_sde_noise_is_seeded_per_member_and_is_the_same_in_any_batch_and_for_any_repeat_of_a_step():
    a, b = sde_env(members=[0, 1, 2], steps=60), sde_env(members=[2, 3], steps=60)
    lon = lat = np.zeros(3)
    va = a.current(lon, lat, 0.0, 600.0).value
    assert np.array_equal(va, a.current(lon, lat, 0.0, 600.0).value)                               # a step asked twice: one answer
    assert np.array_equal(a.current(lon, lat, 0.0, 600.0 + 20.0).value, va)                         # within the same step too
    assert np.array_equal(b.current(np.zeros(2), np.zeros(2), 0.0, 600.0).value[0], va[2])         # member 2 in another batch
    assert not np.allclose(va[0], va[1]) and not np.allclose(sde_env(members=[0, 1, 2], steps=60, seed=4).current(lon, lat, 0.0, 600.0).value, va)
    assert not np.allclose(a.current(lon, lat, 0.0, 660.0).value, va)                               # the next step is a new increment


def test_the_velocity_is_dK_dx_plus_sqrt_2K_over_dt_times_the_members_increment():
    pe = sde_env(members=[0, 1], steps=60)
    lat = np.array([40.0, 40.0])
    K, g = SG.sde_diffusivity(lat)
    xi = pe.sde.xi[:, 10]
    want = g + np.sqrt(2 * K[:, None] / 60.0) * xi
    assert np.allclose(pe.sde.velocity(np.zeros(2), lat, 600.0), want) and g[0, 1] < 0
    pe.sde.xi[:] = 0.0
    assert np.allclose(pe.sde.velocity(np.zeros(2), lat, 600.0), g)                                # no noise: the drift term alone


def test_the_sde_reads_shapes_with_trailing_axes_and_refuses_times_outside_its_window():
    pe = sde_env(members=[0, 1], steps=10)
    v = pe.sde.velocity(np.zeros((2, 3)), np.zeros((2, 3)), np.array([0.0, 60.0, 120.0]))
    assert v.shape == (2, 3, 2) and not np.allclose(v[:, 0], v[:, 1])
    for t in (-300.0, 10 * 60.0 + 3 * 60.0):
        with pytest.raises(ValueError, match="outside its window"):
            pe.sde.velocity(np.zeros(2), np.zeros(2), t)
