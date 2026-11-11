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
    land = np.zeros((n, n), bool)
    for k in range(n):                                   # anti-diagonal wall i + j = n + 3, east-south of the centre
        if 0 <= n + 3 - k < n:
            land[k, n + 3 - k] = True
    t = reach._dijkstra(np.zeros((n, n, 2)), land, 1.0, 100.0, 1e9)
    i, j = np.indices((n, n))
    assert not np.isfinite(t[i + j > n + 3]).any()


# ------------------------------------------------------------------ round 15, batch C: M-32 (why), M-34 (budget), M-35 (weather box), M-39 (rules)

class UniformEnv:
    """A uniform current (north, east) with an optional weather box (lat range, lon360 range) like cafe.env.Env's `lat` and `lon`, and optional land cells."""
    def __init__(self, lat0, lon0, c=(0.0, 0.0), box=None, land=None):
        self.fr, self.c, self.land = Frame(lat0, lon0), np.array(c, float), land
        if box:
            self.lat, self.lon = np.array(box[0], float), np.array(box[1], float) % 360.0

    def at(self, lat, lon, t, z):
        n = len(lat)
        cur = np.tile(self.c, (n, 1))
        return dict(current_ne=cur, wind_ne=cur, land=np.zeros(n, bool) if self.land is None else self.land(*self.fr.to_ne(lat, lon)))


def fast_usv(**kw):
    return NS(kind="usv", battery_wh=1e9, hotel_w=1.0, actuators=[], **kw)


def test_r15_m32_a_cell_that_is_only_too_far_is_not_called_blocked(fixed_speed):
    """Still water: 3364 cells read 'currents/winds too strong or blocked' because the search stopped at the time limit and the label tested only for inf."""
    r = run_reach(UniformEnv(5.0, -150.0))
    assert set(np.array(r["why"]).ravel()) == {"", "beyond endurance or time"}
    assert set(np.array(r["why"]).ravel()) == set(np.array(run_reach(UniformEnv(5.0, -150.0), round_trip=True)["why"]).ravel())


def test_r15_m32_a_cell_no_route_reaches_keeps_the_blocked_label_and_land_its_own(fixed_speed):
    n, c0 = 61, 30
    ring = lambda N, E: (np.hypot(N, E) > 6000) & (np.hypot(N, E) < 9000)      # a closed ring of land, 2 cells thick, round the launch point (cells are 1260 m)
    r = reach.reach(fast_usv(), UniformEnv(5.0, -150.0, land=ring), 5.0, -150.0, hours=3, n=n)
    why = np.array(r["why"])
    assert why[c0, c0] == "" and why[c0, c0 + 3] == "" and why[c0, c0 + 6] == "land" and why[c0, c0 + 10] == "currents/winds too strong or blocked"


def test_r15_m32_a_return_that_the_current_forbids_is_labelled_so_not_beyond_endurance(fixed_speed):
    """V = 1 m/s in a 1.5 m/s current toward north: out to the north is fast, back is impossible. The round trip read 'beyond endurance or time' there, and
    the advice for that (a longer horizon, a bigger battery) is wrong: no horizon brings the drone back."""
    env = UniformEnv(5.0, -150.0, c=(1.5, 0.0))
    one = run_reach(env)
    rt = run_reach(env, round_trip=True)
    h1, hr = np.array(one["hours"], float), np.array(rt["hours"], float)
    c0 = 30
    assert np.isfinite(h1).sum() > 50 and np.isfinite(hr).sum() == 1 and np.isfinite(hr[c0, c0])
    went = np.isfinite(h1) & (np.arange(61)[:, None] != c0)
    assert (np.array(rt["why"])[went] == "no way back: currents/winds too strong to return against").all()
    assert (np.array(one["why"])[went] == "").all()
    south = np.array(one["why"])[c0 - 10, c0]
    assert south == "currents/winds too strong or blocked" and np.array(rt["why"])[c0 - 10, c0] == south           # not reachable even one way


def test_r15_m32_the_labels_hold_for_the_pessimistic_map_too(fixed_speed):
    r = run_reach(UniformEnv(5.0, -150.0), adverse=0.5)
    assert set(np.array(r["why"]).ravel()) == {"", "beyond endurance or time"}


@pytest.mark.parametrize("kw", [dict(hours=0.0), dict(hours=-1.0), dict(hours=float("nan")), dict(hours=3, reserve=1.0), dict(hours=3, reserve=1.5),
                                dict(hours=3, reserve=-0.1), dict(hours=3, reserve=float("nan"))])
def test_r15_m34_no_budget_is_refused(fixed_speed, kw):
    """reach(veh, env, 10, -95, hours=0.0, n=9) gave radius 0 and all 81 cells reachable in 0 h."""
    with pytest.raises(ValueError, match="no time or energy budget|reserve"):
        reach.reach(fast_usv(), UniformEnv(10.0, -95.0), 10.0, -95.0, n=9, **kw)


def test_r15_m34_a_reserve_of_zero_is_inside_the_documented_range(monkeypatch):
    """[0, 1) includes 0: the whole battery may be spent. Only the upper bound was tested (a guard `0 < reserve` survived)."""
    monkeypatch.setattr(ctrl, "cruise_speed", lambda v: V)
    monkeypatch.setattr(ctrl, "_level_power", lambda veh, v: (10.0, True))
    veh = NS(kind="usv", battery_wh=10.0, hotel_w=1.0, actuators=[])
    r = reach.reach(veh, UniformEnv(10.0, -95.0), 10.0, -95.0, hours=5, n=9, reserve=0.0)
    assert np.isfinite(np.array(r["hours"], float)).sum() > 1
    assert reach.endurance_h(veh, V, 0.0) == pytest.approx(1.0) and reach.endurance_h(veh, V, 0.5) == pytest.approx(0.5)


def test_r15_m35_a_point_exactly_on_the_edge_of_the_weather_box_is_inside():
    """`_inside` is inclusive on all four edges (Env.at holds the edge value there, which is the weather at that point); a hair beyond is outside."""
    env = UniformEnv(50.0, -150.0, box=((49.0, 51.0), (-151.0, -149.0)))
    lat = np.array([49.0, 51.0, 50.0, 50.0, 50.0, 50.0, 48.999, 51.001, 50.0, 50.0])
    lon = np.array([-150.0, -150.0, -151.0, -149.0, -150.0, -150.0, -150.0, -150.0, -151.001, -148.999])
    assert reach._inside(env, lat, lon).tolist() == [True] * 6 + [False] * 4


def test_r15_m34_an_empty_battery_is_refused(monkeypatch):
    monkeypatch.setattr(ctrl, "cruise_speed", lambda v: V)
    monkeypatch.setattr(ctrl, "_level_power", lambda veh, v: (50.0, True))
    with pytest.raises(ValueError, match="no time or energy budget"):
        reach.reach(NS(kind="usv", battery_wh=0.0, hotel_w=1.0, actuators=[]), UniformEnv(10.0, -95.0), 10.0, -95.0, hours=3, n=9)


def test_r15_m35_cells_beyond_the_weather_box_are_blocked_not_read_from_its_edge(monkeypatch):
    """A fast vehicle searched 270 km round a box of +-1 degree (111 km north-south, 72 km east-west at 50 N) and drew cells beyond it reachable."""
    monkeypatch.setattr(ctrl, "cruise_speed", lambda v: 10.0)
    monkeypatch.setattr(reach, "endurance_h", lambda *a, **k: 1e9)
    env = UniformEnv(50.0, -150.0, box=((49.0, 51.0), (-151.0, -149.0)))
    for rt in (False, True):
        r = reach.reach(fast_usv(), env, 50.0, -150.0, hours=6, n=61, round_trip=rt)
        lat, lon = np.array(r["lat"])[:, None], np.array(r["lon"])[None, :] % 360.0
        out = (lat < 49.0) | (lat > 51.0) | (lon < 209.0) | (lon > 211.0)
        hrs, why = np.array(r["hours"], float), np.array(r["why"])
        assert out.sum() > 1000 and r["outside_cells"] == out.sum() and r["weather_box"] == [49.0, 51.0, 209.0, 211.0]
        assert np.isnan(hrs[out]).all() and (why[out] == "outside weather data").all() and not np.array(r["hold"])[out].any()
        if rt:                                                  # out and back inside 6 h: the box's corners (132 km) are too far, the rest is not
            assert set(why[~out]) == {"", "beyond endurance or time"} and np.isfinite(hrs[~out]).sum() > 300
        else:
            assert np.isfinite(hrs[~out]).all() and (why[~out] == "").all()           # inside the box the vehicle gets everywhere in 6 h


def test_r15_m35_a_launch_point_outside_the_box_is_refused_and_a_stub_without_a_box_is_unchanged(fixed_speed):
    with pytest.raises(ValueError, match="outside the loaded weather"):
        reach.reach(fast_usv(), UniformEnv(5.0, -150.0, box=((10.0, 12.0), (-151.0, -149.0))), 5.0, -150.0, hours=3, n=11)
    r = run_reach(UniformEnv(5.0, -150.0))
    assert r["outside_cells"] == 0 and r["weather_box"] is None and "outside weather data" not in set(np.array(r["why"]).ravel())


def test_made_good_takes_an_array_of_velocities_and_agrees_with_one_at_a_time():
    rng = np.random.default_rng(3)
    c = rng.normal(size=(4, 5, 2))
    d = np.array([0.6, 0.8])
    got = reach.made_good(1.0, c, d)
    assert got.shape == (4, 5) and all(got[i, j] == pytest.approx(reach.made_good(1.0, c[i, j], d), abs=1e-15) for i in range(4) for j in range(5))
    assert isinstance(reach.made_good(1.0, c[0, 0], d), float)


# --- reach.py is outside the mutation gate (row 205): these pin the rules the review's hand-made mutants broke without a test noticing (M-39)

class DepthEnv:
    """A current toward north of 0.05 + 0.002 * depth (m/s), the same at every point: the glider's band mean tells the band apart from the surface."""
    def at(self, lat, lon, t, z):
        z = np.asarray(z, float)
        cur = np.stack([0.05 - 0.002 * z, np.zeros(len(lat))], -1)
        return dict(current_ne=cur, wind_ne=cur, land=np.zeros(len(lat), bool))


def glider(**limits):
    return NS(kind="uuv", battery_wh=1e9, hotel_w=1.0, actuators=[NS(kind="buoy")], limits=dict(glide_speed_sim=0.3, **limits))


@pytest.mark.parametrize("limits, mean_depth", [(dict(glide_band=(10.0, 60.0)), 35.0), (dict(), 52.5)])
def test_r15_m39_a_glider_is_routed_through_the_mean_current_over_its_dive_band(limits, mean_depth):
    """The band is 6 depths from top to bottom (the default 5 to 100 m); the surface current, the top only or the bottom only are different numbers."""
    r = reach.reach(glider(**limits), DepthEnv(), 5.0, -150.0, hours=3, n=11)
    assert r["flow_max"] == pytest.approx(0.05 + 0.002 * mean_depth, rel=1e-12)


def test_r15_m39_endurance_is_the_battery_less_the_reserve_over_the_power(monkeypatch):
    """A USV: P from ctrl._level_power; a glider: hotel power plus 1.0 W (assumed, row 113's pump). The horizon is the lesser of that and the hours asked."""
    monkeypatch.setattr(ctrl, "_level_power", lambda veh, v: (50.0, True))
    monkeypatch.setattr(ctrl, "cruise_speed", lambda v: V)
    usv = NS(kind="usv", battery_wh=1000.0, hotel_w=3.0, actuators=[])
    assert reach.endurance_h(usv, V, 0.2) == pytest.approx(1000 * 0.8 / 50.0) and reach.endurance_h(usv, V) == pytest.approx(1000 * 0.85 / 50.0)
    r = reach.reach(usv, UniformEnv(5.0, -150.0), 5.0, -150.0, hours=100, n=11, reserve=0.2)
    assert r["endurance_h"] == pytest.approx(16.0) and r["horizon_h"] == pytest.approx(16.0)
    g = NS(kind="uuv", battery_wh=100.0, hotel_w=3.0, actuators=[NS(kind="buoy")], limits=dict(glide_speed_sim=0.3))
    assert reach.endurance_h(g, 0.3) == pytest.approx(100 * 0.85 / 4.0)
    assert reach.reach(g, UniformEnv(5.0, -150.0), 5.0, -150.0, hours=100, n=11)["horizon_h"] == pytest.approx(21.25)


@pytest.mark.parametrize("c, can_hold", [(0.7, True), (0.9, False), (0.79, True), (0.81, False)])
def test_r15_m39_a_vehicle_holds_station_in_flow_up_to_80_percent_of_its_speed(fixed_speed, c, can_hold):
    r = run_reach(UniformEnv(5.0, -150.0, c=(c * V, 0.0)))
    assert np.array(r["hold"]).all() == can_hold and np.array(r["hold"]).any() == can_hold


def test_r15_m39_a_diagonal_with_one_land_corner_is_allowed_and_with_two_is_not():
    n, c0, h = 21, 10, 100.0
    flow = np.zeros((n, n, 2))
    land = np.zeros((n, n), bool)
    land[c0 + 1, c0] = True                                               # one corner of the (1, 1) step
    t = reach._dijkstra(flow, land, 1.0, h, 1e9)
    assert t[c0 + 1, c0 + 1] == pytest.approx(h * np.sqrt(2.0), rel=1e-12)
    land[c0, c0 + 1] = True                                               # both corners: a cut through a wall
    assert reach._dijkstra(flow, land, 1.0, h, 1e9)[c0 + 1, c0 + 1] > h * np.sqrt(2.0) * 1.0001
