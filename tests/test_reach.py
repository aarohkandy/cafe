"""Zermelo checks of cafe.reach against analytic solutions of the time-optimal navigation problem.

Tolerances. made_good is a closed form, so it is held to rounding. The grid search (Dijkstra over 16 neighbours) can only
bend its path through the 16 allowed edge directions; the widest gap between neighbouring directions is atan(1/2) =
26.57 deg, so the worst-case path-length overhead in still water is sec(13.28 deg) - 1 = 2.8 %. A current stretches the
angular gap seen in the fluid frame by up to (1 + c/V) / (1 - c/V) (2.1 at c/V = 0.36), which is why TOL is above the
still-water figure: measured worst overheads are 3.7 % (uniform c/V = 0.36) and 4.9 % (c/V = 0.6), below TOL_UNI = 5.5 %;
TOL = 4.5 % covers the weaker shear and rotation fields (|c|/V <= 0.25). Flow is sampled at edge
mid-points (second order in h). Lattice points reached by one repeated edge are held to rounding instead.
"""
from types import SimpleNamespace as NS

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from scipy.integrate import solve_ivp
from scipy.optimize import brentq, fsolve

from cafe import ctrl, reach
from cafe.mission import Frame

TOL = 0.045
TOL_UNI = 0.055
V = 1.0


def exact_time_uniform(D, c, V):
    """Min time from the origin to displacement D (N, E) in a uniform current c: |D - cT| = VT, smaller non-negative root."""
    a = V * V - c @ c
    b = D @ c
    return (-b + np.sqrt(b * b + a * (D @ D))) / a


def grid(n, h, field):
    """flow[i, j] = (north, east) current at north = (i - c0) h, east = (j - c0) h."""
    c0 = n // 2
    ys = (np.arange(n) - c0) * h
    N, E = np.meshgrid(ys, ys, indexing="ij")
    return np.stack(field(N, E), -1), c0


def times(flow, h, back=False):
    return reach._dijkstra(flow, np.zeros(flow.shape[:2], bool), V, h, 1e9, back=back)


# ------------------------------------------------------------------ made_good (the local Zermelo relation)

def made_good_by_heading(V, c, d):
    """Independent derivation: find the heading whose through-water velocity plus c points along d, by root finding."""
    ang = np.arctan2(d[1], d[0])           # direction angle in the (N, E) plane
    cn, ce = c

    def cross_track(theta):
        vn, ve = V * np.cos(theta) + cn, V * np.sin(theta) + ce
        return -vn * np.sin(ang) + ve * np.cos(ang)          # component perpendicular to d
    lo, hi = ang - np.pi / 2, ang + np.pi / 2
    if cross_track(lo) * cross_track(hi) > 0:
        return 0.0
    th = brentq(cross_track, lo, hi, xtol=1e-14)
    s = (V * np.cos(th) + cn) * np.cos(ang) + (V * np.sin(th) + ce) * np.sin(ang)
    return s if s > 1e-6 else 0.0


@settings(max_examples=200, deadline=None)
@given(st.floats(0.2, 3.0), st.floats(-2, 2), st.floats(-2, 2), st.floats(0, 2 * np.pi))
def test_made_good_matches_root_finding(V_, cn, ce, a):
    d = np.array([np.cos(a), np.sin(a)])
    got = reach.made_good(V_, np.array([cn, ce]), d)
    # when the cross current is just under V the closed form and the root finder lose digits together; skip the knife edge
    if abs(abs(cn * d[1] - ce * d[0]) - V_) > 1e-6:
        assert got == pytest.approx(made_good_by_heading(V_, np.array([cn, ce]), d), abs=1e-7)


def test_made_good_closed_cases_and_sign():
    d = np.array([1.0, 0.0])
    assert reach.made_good(1.0, np.array([0.0, 0.0]), d) == 1.0
    assert reach.made_good(1.0, np.array([0.4, 0.0]), d) == pytest.approx(1.4)       # following current
    assert reach.made_good(1.0, np.array([-0.4, 0.0]), d) == pytest.approx(0.6)      # head current
    assert reach.made_good(1.0, np.array([0.0, 0.6]), d) == pytest.approx(0.8)       # cross current: sqrt(1 - 0.36)
    assert reach.made_good(0.3, np.array([-0.5, 0.0]), d) == 0.0
    assert reach.made_good(0.3, np.array([0.0, 0.5]), d) == 0.0
    # swapping which component is north flips the answer: east-pointing d against an east current
    assert reach.made_good(1.0, np.array([0.0, 0.4]), np.array([0.0, 1.0])) == pytest.approx(1.4)


# ------------------------------------------------------------------ uniform current: straight line, constant heading

@pytest.mark.parametrize("c", [(0.3, 0.2), (-0.5, 0.1), (0.0, -0.6)])
def test_uniform_current_times_are_straight_line_times(c):
    n, h = 61, 100.0
    c = np.array(c)
    flow, c0 = grid(n, h, lambda N, E: (np.full_like(N, c[0]), np.full_like(N, c[1])))
    t = times(flow, h)
    for di, dj in reach.STEPS:
        for k in (1, 3, 5):
            D = h * k * np.array([di, dj], float)
            assert t[c0 + k * di, c0 + k * dj] == pytest.approx(exact_time_uniform(D, c, V), rel=1e-9)
    # additivity along one direction is what 'straight line at one heading' means for a time field
    assert t[c0 + 6, c0 + 3] == pytest.approx(3 * t[c0 + 2, c0 + 1], rel=1e-9)
    # arbitrary targets: never faster than the exact optimum, and within the direction-gap overhead
    worst = 0.0
    for i in range(-25, 26, 4):
        for j in range(-25, 26, 3):
            if i == j == 0:
                continue
            ex = exact_time_uniform(h * np.array([i, j], float), c, V)
            assert t[c0 + i, c0 + j] >= ex * (1 - 1e-9)
            worst = max(worst, t[c0 + i, c0 + j] / ex - 1)
    assert worst < TOL_UNI


def test_return_trip_in_uniform_current_uses_the_reverse_current():
    n, h = 41, 100.0
    c = np.array([0.4, -0.1])
    flow, c0 = grid(n, h, lambda N, E: (np.full_like(N, c[0]), np.full_like(N, c[1])))
    tb = times(flow, h, back=True)           # from every cell to the centre
    for di, dj in reach.STEPS:
        D = -h * 4 * np.array([di, dj], float)       # centre minus the start cell
        assert tb[c0 + 4 * di, c0 + 4 * dj] == pytest.approx(exact_time_uniform(D, c, V), rel=1e-9)


# ------------------------------------------------------------------ linear shear: d(tan theta)/dt = V/h

SHEAR_LEN = 40e3          # u_east = -(V / SHEAR_LEN) * y_north


def shear_field(N, E):
    return np.zeros_like(N), -(V / SHEAR_LEN) * N


def shear_path(tan0, T, n=400):
    """Zermelo's optimal heading in this field is tan(theta) = tan(theta0) + (V/L) t (theta from east). Position by quadrature."""
    k = V / SHEAR_LEN

    def rhs(t, y):
        th = np.arctan(tan0 + k * t)
        return [V * np.cos(th) - k * y[1], V * np.sin(th)]
    ts = np.linspace(0, T, n)
    sol = solve_ivp(rhs, (0, T), [0.0, 0.0], t_eval=ts, rtol=1e-11, atol=1e-9)
    return ts, sol.y, k


def shear_optimal_time(target_e, target_n):
    """Shoot for (tan theta0, T) that reach the target."""
    def miss(p):
        _, y, _ = shear_path(p[0], p[1], 3)
        return [y[0, -1] - target_e, y[1, -1] - target_n]
    p = fsolve(miss, [target_n / target_e, np.hypot(target_e, target_n) / V], xtol=1e-12)
    assert np.max(np.abs(miss(p))) < 1e-6
    return p[0], p[1]


def test_shear_heading_rate_through_made_good():
    """Along the analytic optimal path, recover the through-water heading from cafe's made-good speed (heading = direction of
    s d - c) and check tan(theta) grows at V/L, and that s equals the path's ground speed."""
    tan0, T = shear_optimal_time(8000.0, 5000.0)
    ts, y, k = shear_path(tan0, T)
    vel = np.array([V * np.cos(np.arctan(tan0 + k * ts)) - k * y[1], V * np.sin(np.arctan(tan0 + k * ts))])      # (E, N)
    tan_th = []
    for i in range(len(ts)):
        c = np.array([0.0, -k * y[1, i]])                        # (N, E)
        d = np.array([vel[1, i], vel[0, i]]) / np.hypot(*vel[:, i])
        s = reach.made_good(V, c, d)
        assert s == pytest.approx(np.hypot(*vel[:, i]), rel=1e-9)
        w = s * d - c                                            # through-water velocity (N, E)
        tan_th.append(w[0] / w[1])
    slope = np.polyfit(ts, tan_th, 1)[0]
    assert slope == pytest.approx(V / SHEAR_LEN, rel=1e-6)
    assert not np.isclose(slope, -V / SHEAR_LEN, rtol=0.5)       # sign matters: the current carries east where y < 0


@pytest.mark.parametrize("target", [(8000.0, 5000.0), (6000.0, -4000.0), (9000.0, 0.0)])
def test_shear_grid_time_matches_zermelo_shooting(target):
    n, h = 81, 250.0
    flow, c0 = grid(n, h, shear_field)
    t = times(flow, h)
    ex = shear_optimal_time(*target)[1]
    got = t[c0 + int(target[1] / h), c0 + int(target[0] / h)]
    assert got >= ex * (1 - 1e-3)
    assert got / ex - 1 < TOL


# ------------------------------------------------------------------ solid-body rotation: theta_dot = omega

OMEGA = 2e-5          # rad/s; at 10 km the current is 0.2 V


def rotation_field(N, E):
    return OMEGA * E, -OMEGA * N          # (north, east) = Omega x r with x east, y north


def test_rotation_heading_rate_through_made_good():
    """The optimal path is straight in the frame turning with the fluid, so x(t) = Rot(Omega t) (V t e0). Heading recovered
    from cafe's made-good speed must advance at Omega."""
    th0 = 0.7
    ts = np.linspace(0, 8000, 200)
    rot = lambda a: np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    heads = []
    for t in ts:
        e0 = np.array([np.cos(th0), np.sin(th0)])                # (E, N)
        x = rot(OMEGA * t) @ (V * t * e0)
        c_en = OMEGA * np.array([-x[1], x[0]])                   # (E, N) fluid velocity at x
        ground = V * rot(OMEGA * t) @ e0 + c_en                  # d/dt of x(t)
        d = np.array([ground[1], ground[0]]) / np.hypot(*ground)  # (N, E)
        c = np.array([c_en[1], c_en[0]])
        s = reach.made_good(V, c, d)
        assert s == pytest.approx(np.hypot(*ground), rel=1e-9)
        w = s * d - c
        heads.append(np.arctan2(w[0], w[1]))                     # heading from east, counter-clockwise
    assert np.polyfit(ts, np.unwrap(heads), 1)[0] == pytest.approx(OMEGA, rel=1e-6)


def test_rotation_grid_time_is_distance_over_speed_in_every_direction():
    """From the centre of a solid-body rotation the fluid frame is the rotating frame: the optimal path is a straight line
    there and the time to a point at radius r is r / V for every bearing and every Omega."""
    n, h = 81, 250.0
    flow, c0 = grid(n, h, rotation_field)
    t = times(flow, h)
    worst = 0.0
    for i in range(-30, 31, 6):
        for j in range(-30, 31, 6):
            if i == j == 0:
                continue
            r = h * np.hypot(i, j)
            worst = max(worst, abs(t[c0 + i, c0 + j] * V / r - 1))
            assert t[c0 + i, c0 + j] * V / r > 1 - 1e-3
    assert worst < TOL
    # the same field with the current reversed (Omega -> -Omega) must give the same times
    flow2, _ = grid(n, h, lambda N, E: (-OMEGA * E, OMEGA * N))
    assert np.allclose(times(flow2, h)[c0 - 30:c0 + 31, c0 - 30:c0 + 31], t[c0 - 30:c0 + 31, c0 - 30:c0 + 31], rtol=0.02)


# ------------------------------------------------------------------ reach() end to end on a stub environment

class RotEnv:
    """Solid-body rotation about the launch point, as an Env-like object over lat/lon."""
    def __init__(self, lat0, lon0, omega):
        self.fr, self.om = Frame(lat0, lon0), omega

    def at(self, lat, lon, t, z):
        n, e = self.fr.to_ne(lat, lon)
        cur = np.stack([self.om * e, -self.om * n], -1)
        return dict(current_ne=cur, wind_ne=cur, land=np.zeros(len(lat), bool))


def run_reach(env, **kw):
    veh = NS(kind="usv", battery_wh=1e9, hotel_w=1.0, actuators=[])
    return reach.reach(veh, env, 5.0, -150.0, hours=3, n=61, **kw)


@pytest.fixture()
def fixed_speed(monkeypatch):
    monkeypatch.setattr(ctrl, "cruise_speed", lambda v: V)
    monkeypatch.setattr(reach, "endurance_h", lambda *a, **k: 1e9)


def test_reach_end_to_end_rotation_and_headwind_adverse(fixed_speed):
    r = run_reach(RotEnv(5.0, -150.0, OMEGA))
    hrs = np.array(r["hours"], float)
    lat, lon = np.array(r["lat"]), np.array(r["lon"])
    fr = Frame(5.0, -150.0)
    n, e = fr.to_ne(lat[:, None] + 0 * lon[None], lon[None] + 0 * lat[:, None])
    rr = np.hypot(n, e)
    ok = np.isfinite(hrs) & (rr > 2000)
    assert ok.sum() > 100
    assert np.max(np.abs(hrs[ok] * 3600 * V / rr[ok] - 1)) < TOL + 0.02          # +0.02: hours are rounded to 0.01 h
    assert r["flow_kind"] == "current" and r["speed_through_fluid"] == V
    slow = run_reach(RotEnv(5.0, -150.0, 0.0), adverse=0.5)
    assert slow["speed_through_fluid"] == pytest.approx(0.5)
    h2 = np.array(slow["hours"], float)
    # still water, half speed: time = r / 0.5
    n2, e2 = fr.to_ne(np.array(slow["lat"])[:, None] + 0 * np.array(slow["lon"])[None],
                      np.array(slow["lon"])[None] + 0 * np.array(slow["lat"])[:, None])
    rr2 = np.hypot(n2, e2)
    ok2 = np.isfinite(h2) & (rr2 > 2000)
    assert ok2.sum() > 30
    assert np.max(np.abs(h2[ok2] * 3600 * 0.5 / rr2[ok2] - 1)) < TOL + 0.02
    assert np.array(slow["hold"]).all()            # no current: it can hold station everywhere


def test_one_cell_wall_of_land_blocks_the_search():
    """Regression (2026-10-29): knight steps hopped a one-cell land wall; all 615 cells beyond it came out reachable."""
    n, h = 41, 100.0
    c0 = n // 2
    land = np.zeros((n, n), bool)
    land[:, c0 + 5] = True
    t = reach._dijkstra(np.zeros((n, n, 2)), land, 1.0, h, 1e9)
    assert not np.isfinite(t[:, c0 + 6:]).any()
    assert np.isfinite(t[:, :c0 + 5]).all()


def test_one_cell_diagonal_wall_blocks_corner_cuts():
    n = 41
    c0 = n // 2
    land = np.zeros((n, n), bool)
    for k in range(n):                                   # anti-diagonal wall i + j = n + 3, east-south of the centre
        if 0 <= n + 3 - k < n:
            land[k, n + 3 - k] = True
    t = reach._dijkstra(np.zeros((n, n, 2)), land, 1.0, 100.0, 1e9)
    i, j = np.indices((n, n))
    assert not np.isfinite(t[i + j > n + 3]).any()
