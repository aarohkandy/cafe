"""cafe.pm.physics.uas: quadrotor physics, sortie model, SITL bridge, receipts (and proof that each receipt can fail)."""
import copy
import functools
import math
import os
import json
import pathlib
import sys
import time

import jax.numpy as jnp
import numpy as np
import pytest
import yaml
from hypothesis import given, settings, strategies as st

from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import uas

P = uas.load_platform()
G = uas.G0
ORIGIN = (-165.0, 0.0)


def fast_plat():
    """Same vehicle, a 5 min two-level sortie so each flight test takes seconds."""
    p = copy.deepcopy(P)
    p["sortie"]["duration_s"], p["sortie"]["levels_m"] = 300.0, [10.0, 25.0]
    return p


def fly(wind=(0.0, 0.0), plat=None, M=2, t=0.0, **kw):
    return uas.fly_sortie(AnalyticEnv(wind=wind), uas.steaming(), t, M=M, origin=ORIGIN, plat=plat or fast_plat(), **kw)


@functools.lru_cache(maxsize=None)
def broken(fault):
    """The receipts with one piece of physics broken on purpose (the real-time SITL run and the 20 min sortie left out)."""
    return uas.receipts(fault=fault, sitl=False, sortie=False)


def sitl_present():
    from cafe import emulator
    return (pathlib.Path(emulator.SITL_DIR) / "arducopter").exists()


# ------------------------------------------------------------------------------------------------ the yaml

def test_every_number_has_a_source_or_an_assumption():
    doc = yaml.safe_load(uas.PLATFORM.read_text())
    assert uas.check_provenance(doc) == []
    broken = copy.deepcopy(doc)
    del broken["rotor"]["motor_time_const_s"]["source"]
    assert uas.check_provenance(broken) == ["rotor.motor_time_const_s"]
    broken = copy.deepcopy(doc)
    broken["aero"]["d_x"] = 0.5                                    # a bare number
    assert "aero.d_x" in uas.check_provenance(broken)
    broken = copy.deepcopy(doc)
    broken["airframe"]["hotel_w"].pop("why")
    assert uas.check_provenance(broken) == ["airframe.hotel_w"]


def test_load_platform_refuses_unsourced_numbers(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("airframe: {mass_kg: {value: 1.0, unit: kg}}\n")
    with pytest.raises(ValueError, match="airframe.mass_kg"):
        uas.load_platform(str(f))


def test_platform_holds_what_the_brief_asks_for():
    assert P["airframe"]["mass_kg"] == 0.772 and P["airframe"]["inertia_kgm2"] == [0.0025, 0.0021, 0.0043]
    assert (P["aero"]["d_x"], P["aero"]["d_y"], P["aero"]["d_z"]) == (0.544, 0.386, 0.0)
    assert P["battery"]["peukert_exponent"] == 1.05
    rf, g24 = P["radio"]["rfd900x"], P["radio"]["link_2g4"]
    assert rf["freq_mhz"] == [902.0, 928.0] and rf["tx_power_dbm"] == 30.0 and rf["rx_sensitivity_dbm"] == -121.0
    assert g24["freq_mhz"][0] > 2000.0 and P["radio"]["ship_antenna_height_m"] > 0
    assert P["sortie"]["duration_s"] == 1200.0


# ------------------------------------------------------------------------------------------------ helpers (properties)

quat = st.tuples(*[st.floats(-1, 1, allow_nan=False)] * 4).filter(lambda q: sum(x * x for x in q) > 1e-3)


@settings(deadline=None, max_examples=40)
@given(quat)
def test_body_axes_are_a_rotation(q):
    q = np.array(q)[:, None]
    q = q / np.linalg.norm(q)
    ax = np.stack([np.asarray(a)[:, 0] for a in uas._axes(jnp.asarray(q))], 1)
    assert np.allclose(ax.T @ ax, np.eye(3), atol=1e-5) and np.isclose(np.linalg.det(ax), 1.0, atol=1e-5)


@settings(deadline=None, max_examples=40)
@given(quat, quat)
def test_quaternion_product_keeps_the_norm(a, b):
    a, b = (np.array(x)[:, None] / np.linalg.norm(x) for x in (a, b))
    assert np.isclose(np.linalg.norm(np.asarray(uas._qmul(jnp.asarray(a), jnp.asarray(b)))), 1.0)


@settings(deadline=None, max_examples=40)
@given(st.floats(-3000, 3000), st.floats(-3000, 3000), st.floats(-179, 179), st.floats(-60, 60))
def test_lonlat_is_the_inverse_of_a_local_tangent_plane(e, n, lon0, lat0):
    lon, lat = uas.lonlat((lon0, lat0), e, n)
    back_n = (lat - lat0) * uas.M_PER_DEG
    back_e = ((lon - lon0 + 180) % 360 - 180) * uas.M_PER_DEG * math.cos(math.radians(lat0))
    assert np.isclose(back_n, n, atol=1e-6) and np.isclose(back_e, e, atol=1e-6)


@settings(deadline=None, max_examples=40)
@given(st.floats(-100, 100), st.floats(0.1, 10), st.floats(0.1, 10))
def test_sqrt_controller_never_asks_for_more_than_the_deceleration_allows(err, kp, a):
    out = float(uas._sqrt_ctrl(jnp.asarray(err), kp, a))
    assert np.sign(out) == np.sign(err) or out == 0.0
    assert abs(out) <= math.sqrt(2 * a * abs(err)) * (1 + 1e-5) + 1e-6


@settings(deadline=None, max_examples=25)
@given(st.floats(20, 400), st.floats(20, 400))
def test_more_power_drains_faster_and_never_charges(p1, p2):
    prm = uas.derive(P, 1)
    out = [uas._batt(prm, jnp.ones(1), jnp.zeros(1), jnp.zeros(1), jnp.array([p]), 1.0) for p in sorted((p1, p2))]
    assert float(out[0][0][0]) >= float(out[1][0][0]) and float(out[1][0][0]) <= 1.0
    assert np.isclose(float(out[0][2][0]), sorted((p1, p2))[0] / 3600.0)


@settings(deadline=None, max_examples=40)
@given(st.floats(95000, 105000), st.floats(285, 305))
def test_air_density_is_ideal_gas(p, t):
    assert np.isclose(uas.air_density(p, t), p / (287.05 * t)) and uas.air_density(p, t, 0.02) < uas.air_density(p, t)


def test_steaming_goes_where_the_course_says():
    ship = uas.steaming((10.0, 0.0), 2.0, 90.0)                      # compass 90 = east
    assert np.allclose(ship(100.0), [210.0, 0.0])
    assert np.allclose(uas.steaming((0, 0), 3.0, 0.0)(10.0), [0.0, 30.0])


# ------------------------------------------------------------------------------------------------ rigid body + rotors

def one_step(prm, om, w=(0.0, 0.0, 0.0), wind=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0), q=(1.0, 0.0, 0.0, 0.0), dt=0.0025):
    a = lambda x: jnp.asarray(x, float)[:, None]
    out = uas._dyn_jit(prm, a([0, 0, 100.0]), a(v), a(q), a(w), a(om), a(om), a(wind), jnp.zeros((2, 1)), dt)
    return [np.asarray(x)[..., 0] if np.ndim(x) > 1 else np.asarray(x) for x in out]


def hover_om(prm):
    return float(np.sqrt(P["airframe"]["mass_kg"] * G / 4 / prm["kT"][0]))


def test_free_fall_and_hover_balance():
    prm = uas.derive(P, 1)
    _, v, *_ = one_step(prm, [0.0] * 4)
    assert np.allclose(v, [0, 0, -G * 0.0025])
    _, v, _, _, _, pe, sf, _ = one_step(prm, [hover_om(prm)] * 4)
    assert np.allclose(v, 0.0, atol=1e-7) and np.isclose(sf[2], G)             # accelerometer reads +g (z up)
    assert 80 < float(pe[0]) < 200                                              # hover electrical power of a 0.77 kg quad


def test_wind_pushes_the_airframe_downwind():
    prm = uas.derive(P, 1)
    _, v, *_ = one_step(prm, [hover_om(prm)] * 4, wind=(5.0, 0.0, 0.0))
    assert np.isclose(v[0] / 0.0025, P["aero"]["d_x"] * 5.0)                    # a = -R D R^T (v - wind), v = 0
    assert abs(v[1]) < 1e-12
    _, v, *_ = one_step(prm, [hover_om(prm)] * 4, wind=(0.0, 5.0, 0.0))
    assert np.isclose(v[1] / 0.0025, P["aero"]["d_y"] * 5.0) and abs(v[0]) < 1e-12
    _, v, *_ = one_step(uas.derive(P, 1, fault="wind_sign"), [hover_om(prm)] * 4, wind=(5.0, 0.0, 0.0))
    assert v[0] < 0                                                             # the wrong sign pushes upwind: what the receipts must catch


def test_rotor_torque_signs_follow_the_ardupilot_quad_x():
    prm = uas.derive(P, 1)
    h = hover_om(prm)
    hi = lambda idx: [h * 1.1 if i in idx else h for i in range(4)]
    _, _, _, w, *_ = one_step(prm, hi([1, 2]))                                  # M2 rear-left, M3 front-left faster: left side up = roll right
    assert w[0] > 0 and abs(w[1]) < 1e-6
    _, _, _, w, *_ = one_step(prm, hi([0, 2]))                                  # M1, M3 front faster: nose up
    assert w[1] < 0 and abs(w[0]) < 1e-6                                        # FLU: a rate about +y (left) is nose DOWN, so nose up is negative
    _, _, _, w, *_ = one_step(prm, hi([0, 1]))                                  # CCW rotors (M1, M2) faster: the body turns clockwise
    assert w[2] < 0 and abs(w[0]) < 1e-6 and abs(w[1]) < 1e-6


def test_torque_free_tumbling_conserves_rotational_energy():
    prm = uas.derive(P, 1, scale=dict(drag=0.0))
    a = lambda x: jnp.asarray(x, float)[:, None]
    p, v, q, w, om = a([0, 0, 1e5]), a([0, 0, 0]), a([1, 0, 0, 0]), a([3.0, 1.0, -2.0]), a([0] * 4)
    J = np.array(P["airframe"]["inertia_kgm2"])
    e0 = 0.5 * np.sum(J * np.asarray(w)[:, 0] ** 2)
    for _ in range(1500):
        p, v, q, w, om, *_ = uas._dyn_jit(prm, p, v, q, w, om, om, a([0, 0, 0]), jnp.zeros((2, 1)), 0.0005)
    assert np.isclose(0.5 * np.sum(J * np.asarray(w)[:, 0] ** 2), e0, rtol=0.01)
    assert np.isclose(np.linalg.norm(np.asarray(q)), 1.0)


def test_the_deck_holds_a_vehicle_that_cannot_lift_and_moves_with_the_ship():
    prm = uas.derive(P, 1)
    a = lambda x: jnp.asarray(x, float)[:, None]
    out = uas._dyn_jit(prm, a([0, 0, 0.0]), a([0, 0, 0]), a([1, 0, 0, 0]), a([0, 0, 0]), a([0] * 4), a([0] * 4), a([0, 0, 0]),
                       jnp.array([[2.0], [1.0]]), 0.0025)
    assert float(out[0][2, 0]) == 0.0 and np.allclose(np.asarray(out[1])[:, 0], [2.0, 1.0, 0.0]) and np.isclose(float(out[6][2, 0]), G)


def test_controller_hovers_and_orders_motors_for_a_tilt():
    prm = uas.derive(P, 1)
    a = lambda x: jnp.asarray(x, float)[:, None]
    q0, w0 = a([1, 0, 0, 0]), a([0, 0, 0])
    om = np.asarray(uas._ctrl(prm, q0, w0, a([0, 0, G]), jnp.zeros(1), jnp.ones(1)))[:, 0]
    assert np.allclose(om, hover_om(prm), rtol=1e-5)
    om = np.asarray(uas._ctrl(prm, q0, w0, a([G * 0.3, 0, G]), jnp.zeros(1), jnp.ones(1)))[:, 0]    # accelerate toward +x, nose = +x
    assert om[1] > om[0] and om[3] > om[2]                                       # rear motors (M2, M4) push the nose down
    om = np.asarray(uas._ctrl(prm, q0, w0, a([0, 0, G]), jnp.zeros(1), jnp.full(1, 0.4)))[:, 0]      # sagged battery: the motors cannot reach hover speed
    assert np.allclose(om, 0.4 * prm["om_max"][0])
    yaw = np.asarray(uas._ctrl(prm, q0, w0, a([0, 0, G]), jnp.full(1, 1.0), jnp.ones(1)))[:, 0]      # turn counter-clockwise by 1 rad: a big demand
    assert np.all(np.isfinite(yaw)) and np.all(yaw >= 0) and yaw[2] > yaw[0] and yaw[0] == yaw[1] and yaw[2] == yaw[3]   # CW rotors (M3, M4) push the body CCW


# ------------------------------------------------------------------------------------------------ sortie

def test_nominal_sortie_in_still_air():
    r = uas.fly_sortie(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, M=3, origin=ORIGIN, plat=P)
    assert r["landed"].all() and not r["failed"].any() and not r["scrubbed"].any() and not r["ditched"].any()
    assert np.all(np.abs(r["t_end"] - 1200.0) < 60.0)                                         # leg length is sized for 20 min
    assert np.all((r["soc_end"] > 0.2) & (r["soc_end"] < 0.5)) and np.all((r["energy_wh"] > 30) & (r["energy_wh"] < 50))
    assert np.all((r["max_dist_m"] > 2000) & (r["max_dist_m"] < 2400))
    tr = r["track"]
    assert tr["pos_rel"].shape[:2] == (3, len(tr["t"])) and np.all(np.diff(tr["t"]) > 0)
    assert tr["pos_rel"][..., 2].max() > 79.0                                                  # reached the top level
    assert np.allclose(tr["pos_rel"][:, -1, :2], 0.0, atol=3.0)
    assert all(np.isnan(v).all() for v in r["t_first"].values())
    assert np.isclose(uas.leg_length_m(P), 2185.0, rtol=0.05)


def test_mean_wind_is_looked_up_every_second_and_turbulence_every_50_ms():
    class Spy(AnalyticEnv):
        n = 0

        def wind(self, lon, lat, z, t):
            Spy.n += 1
            return super().wind(lon, lat, z, t)
    r = uas.fly_sortie(Spy(wind=(0.0, 0.0)), uas.steaming(), 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    assert abs(Spy.n - (float(r["t_end"].max()) / 1.0 + 3)) <= 2                               # +3 for the launch gate
    seen = []
    fn = uas.make_wind(AnalyticEnv(wind=(1.0, 0.0)), ORIGIN, 8.0, turb=np.arange(2 * 40 * 3, dtype=float).reshape(2, 40, 3))
    for k in range(40):
        seen.append(fn(k, 0.05 * k, np.zeros((3, 2)))[:, 0])
    seen = np.array(seen)
    assert np.allclose(np.diff(seen[:, 0]), 3.0)                                                # a new turbulence row every block
    assert np.allclose(seen[:, 0] - np.arange(40) * 3.0, seen[0, 0]) and 0.9 < seen[0, 0] < 1.0       # on the held mean wind (profiled to 8 m)


def test_launch_is_scrubbed_in_a_strong_mean_wind():
    r = fly(wind=(13.0, 0.0))
    assert r["scrubbed"].all() and not r["failed"].any() and not r["landed"].any()
    assert r["track"]["pos_rel"].shape == (2, 0, 3) and np.allclose(r["energy_wh"], 0)
    assert r["launch"]["wind_ms"].min() > P["launch_rule"]["max_mean_wind_ms"]


def test_launch_is_scrubbed_when_a_gust_front_is_close():
    def gust(t):
        g = np.zeros((3, 3))
        g[1, 0] = 6.0 if 300.0 <= t <= 400.0 else 0.0                                          # member 1: a front 5-6.7 min after launch
        g[2, 0] = 6.0 if t > 3600.0 else 0.0                                                   # member 2: a front, but an hour away
        return g
    r = fly(M=3, gust=gust)
    assert list(r["scrubbed"]) == [False, True, False] and list(r["launch"]["front"]) == [False, True, False]
    assert list(r["landed"]) == [True, False, True] and not r["failed"][1]
    assert r["energy_wh"][1] == 0 and r["energy_wh"][0] > 5


def test_gust_front_in_flight_pushes_the_vehicle_around():
    def gust(t):
        return np.where(t > 40.0, 1.0, 0.0) * np.array([[0.0, 8.0, 0.0], [0.0, 0.0, 0.0]])     # member 0: +8 m/s north from 40 s in
    plat = fast_plat()
    plat["launch_rule"]["gust_front_threshold_ms"] = 99.0                                      # the gate would see this front coming: switch it off
    r = fly(M=2, gust=gust, heading_deg=90.0, plat=plat)
    assert r["max_wind_ms"][0] > 7.9 and r["max_wind_ms"][1] < 0.5
    k = int(np.argmin(np.abs(r["track"]["t"] - 100.0)))                                        # mid-leg: crosswind + headwind of the leg lean it further
    assert r["track"]["tilt_deg"][0, k] > r["track"]["tilt_deg"][1, k] + 2.0


def test_battery_reserve_flag_with_first_time():
    r = fly(scale=dict(battery=[1.0, 0.2]))                                                    # a fifth of the pack cannot finish 5 min above the reserve
    assert list(r["flags"]["battery_reserve"]) == [False, True] and r["failed"][1] and not r["failed"][0]
    t1 = r["t_first"]["battery_reserve"][1]
    assert 30.0 < t1 <= r["t_end"][1] and np.isnan(r["t_first"]["battery_reserve"][0])


def test_failsafe_returns_home_when_the_reserve_is_reached_and_a_dead_pack_ditches():
    r = fly(scale=dict(battery=[1.0, 0.1]), plat=fast_plat())
    assert r["ditched"][1] and not r["landed"][1] and r["landed"][0]                           # a tenth of the pack cannot even fly the pattern
    assert r["soc_end"][1] < 0.1 and r["flags"]["battery_reserve"][1]                       # the cutoff voltage sags out before the last charge


def test_wind_exceeding_what_the_airframe_can_make_headway_against():
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 99.0
    r = fly(wind=(14.0, 0.0), plat=plat, M=1)                                                  # legs run upwind: 14 m/s > g tan(35 deg)/d_x
    assert r["flags"]["wind_exceeds_airspeed"][0] and r["failed"][0]
    assert 0.0 < r["t_first"]["wind_exceeds_airspeed"][0] < 200.0
    assert r["max_tilt_deg"][0] > 34.0                                                         # it leaned as hard as it was allowed to
    calm = fly(wind=(3.0, 0.0), plat=plat, M=1)
    assert not calm["flags"]["wind_exceeds_airspeed"][0] and calm["landed"][0]


def test_attitude_exceedance_flag_uses_the_limit_in_the_yaml():
    plat = fast_plat()
    plat["limits"]["tilt_exceedance_deg"] = 20.0
    r = fly(plat=plat, M=1)
    assert r["flags"]["attitude_exceedance"][0] and 0.0 < r["t_first"]["attitude_exceedance"][0] < 60.0
    assert not fly(M=1)["flags"]["attitude_exceedance"][0]


def test_lost_link_hook_records_first_time_from_the_callers_link_model():
    calls = []

    def link(t, pos_rel):
        calls.append((t, pos_rel.shape))
        return np.hypot(pos_rel[:, 0], pos_rel[:, 1]) > 400.0                                  # the caller's two-ray / horizon result
    r = fly(link=link, M=2, heading_deg=[90.0, 90.0])
    assert r["flags"]["lost_link"].all() and r["failed"].all()
    assert np.all((r["t_first"]["lost_link"] > 40.0) & (r["t_first"]["lost_link"] < 120.0))
    assert calls[0][1] == (2, 3) and np.isclose(calls[1][0] - calls[0][0], 1.0)
    assert not fly(M=1)["flags"]["lost_link"].any()


def test_turbulence_series_and_gust_front_arrays_enter_the_air_relative_velocity():
    plat = fast_plat()
    short = np.zeros((2, 100, 3))
    with pytest.raises(ValueError, match="turbulence series covers"):
        fly(turb=short, plat=plat)
    n = int((300 + 60) / 0.05) + 1
    turb = np.zeros((2, n, 3))
    turb[1, :, 1] = 8.0                                                                        # member 1: steady 8 m/s from the south
    r = fly(turb=turb, plat=plat, heading_deg=90.0)
    k = int(np.argmin(np.abs(r["track"]["t"] - 100.0)))
    assert r["max_wind_ms"][1] > 7.9 and r["max_wind_ms"][0] < 0.1 and r["track"]["tilt_deg"][1, k] > r["track"]["tilt_deg"][0, k] + 2.0
    assert fly(turb=np.zeros((2, 8000, 3)), plat=plat)["landed"].all()                         # a series long enough is accepted as is


def test_ship_underway_vehicle_lands_on_the_moving_deck():
    ship = uas.steaming((0.0, 0.0), 2.5, 45.0)
    r = uas.fly_sortie(AnalyticEnv(wind=(3.0, 0.0)), ship, 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    assert r["landed"].all() and not r["failed"].any()
    assert np.allclose(r["track"]["pos_rel"][:, -1], 0.0, atol=4.0)


def test_mission_rolls_up_several_sorties():
    def gust(t):
        g = np.zeros((2, 3))
        g[0, 0] = 5.0 if 5000 < t < 6000 else 0.0                                              # member 0: front at the second launch
        return g
    m = uas.fly_mission(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), [0.0, 5000.0, 20000.0], M=2, origin=ORIGIN, plat=fast_plat(), gust=gust,
                        scale=dict(battery=[1.0, 0.2]))
    mi = m["mission"]
    assert len(m["sorties"]) == 3 and list(mi["n_scrubbed"]) == [1, 0] and list(mi["n_flown"]) == [2, 3] and mi["n_landed"][0] == 2
    assert list(mi["failed"]) == [False, True] and mi["n_failed"][1] == 3
    assert 30.0 < mi["t_first"]["battery_reserve"][1] < 400.0 and np.isnan(mi["t_first"]["battery_reserve"][0])
    assert mi["first_failure_mode"][1] == uas.FLAGS.index("battery_reserve") and mi["first_failure_mode"][0] == -1
    assert 0.0 < mi["first_failure_t"][1] < 400.0 and np.isnan(mi["first_failure_t"][0])


def test_flux_pattern_stacks_legs_in_the_requested_direction():
    wp = uas.flux_pattern(P, [90.0, 0.0])                                                      # member 0 east, member 1 north
    L = uas.leg_length_m(P)
    assert wp.shape == (8, 3, 2) and np.allclose(wp[1, :, 0], [L, 0, 10.0], atol=1e-6) and np.allclose(wp[1, :, 1], [0, L, 10.0], atol=1e-6)
    assert np.allclose(wp[2, :, 0], [L, 0, 25.0], atol=1e-6) and np.allclose(wp[3, :, 0], [0, 0, 25.0], atol=1e-6)
    assert list(wp[::2, 2, 0]) == P["sortie"]["levels_m"] and list(wp[1::2, 2, 0]) == P["sortie"]["levels_m"]


def test_simulate_rejects_a_step_that_does_not_divide_the_environment_step():
    with pytest.raises(AssertionError):
        uas.simulate(uas.derive(P, 1), uas.flux_pattern(P, [0.0]), uas.steaming(), lambda k, t, p: np.zeros((3, 1)), M=1, t0=0.0, t_max=1.0, nsub=19)


def test_twenty_minute_sortie_for_256_members_runs_in_under_a_minute():
    M = 256
    rng = np.random.default_rng(1)
    scale = dict(mass=1 + 0.03 * rng.standard_normal(M), drag=1 + 0.1 * rng.standard_normal(M), battery=1 + 0.05 * rng.standard_normal(M))
    env = AnalyticEnv(wind=(5.0, 2.0))
    uas.fly_sortie(env, uas.steaming(), 0.0, M=M, origin=ORIGIN, plat=fast_plat(), scale=scale)          # compile
    t0 = time.time()
    r = uas.fly_sortie(env, uas.steaming(), 0.0, M=M, origin=ORIGIN, plat=P, scale=scale)
    wall = time.time() - t0
    print(f"256 members x {r['t_end'].max():.0f} s sortie: {wall:.1f} s wall, {os.cpu_count()} visible cpus")
    assert wall < 60.0 and r["landed"].mean() > 0.9 and r["t_end"].max() > 1000.0


# ------------------------------------------------------------------------------------------------ receipts and their failures

def test_receipts_pass_and_include_arducopter_when_it_is_installed():
    out = uas.receipts()
    assert len(out) >= 14 and all(r["ok"] in (True, None) for r in out), [r for r in out if r["ok"] is False]
    claims = " | ".join(r["claim"] for r in out)
    for key in ("hover figure of merit", "steady tilt forward at 8 m/s", "discharge time ratio", "2.5 ms vs 1.25 ms", "still-air sortie"):
        assert key in claims
    sit = [r for r in out if r["group"].startswith("UAS SITL")]
    if sitl_present():
        assert len(sit) >= 5 and all(r["ok"] is True for r in sit if r.get("kind") != "context"), sit
    else:
        assert len(sit) == 1 and sit[0]["kind"] == "context"


@pytest.mark.parametrize("fault,group", [("wind_sign", "UAS rotor drag"), ("no_drag", "UAS rotor drag"), ("fm", "UAS propulsion"),
                                         ("peukert", "UAS battery"), ("dt_const", "UAS time step")])
def test_each_receipt_fails_when_its_physics_is_broken(fault, group):
    bad = [r for r in broken(fault) if r["ok"] is False]
    assert bad and any(r["group"] == group for r in bad), (fault, [r["claim"] for r in bad])


def test_a_wrong_wind_sign_is_caught_by_the_lean_direction_and_not_by_the_magnitude():
    bad = {r["claim"]: r["ok"] for r in broken("wind_sign")}
    assert bad["hover in a wind blowing east leans west (into the wind): z_B east component"] is False
    assert bad["steady tilt forward at 8 m/s: atan(d v / g)"] is True


def test_scrambled_motor_order_fails_the_sitl_receipts():
    if not sitl_present():
        pytest.fail("this test needs the ArduCopter binary (homebase: /work/sitl); the missing-binary path is test_missing_binary_*")
    bad = [r for r in uas.receipts(fault="sitl_motor_order") if r["group"].startswith("UAS SITL")]
    assert any(r["ok"] is False for r in bad)


# ------------------------------------------------------------------------------------------------ SITL machinery without the real binary

def fake_sitl(tmp_path, body):
    d = tmp_path / "sitl"
    d.mkdir()
    exe = d / "arducopter"
    exe.write_text(f"#!{sys.executable}\n" + body)
    exe.chmod(0o755)
    return d


def test_missing_binary_is_a_clear_error_naming_the_path(tmp_path, monkeypatch):
    from cafe import emulator
    monkeypatch.setattr(emulator, "SITL_DIR", tmp_path / "nowhere")
    with pytest.raises(uas.SitlUnavailable) as e:
        uas.fly_sitl(AnalyticEnv(), uas.steaming(), 0.0, plat=P)
    assert str(tmp_path / "nowhere" / "arducopter") in str(e.value) and "waf" in str(e.value) and "~/work/cafe/data/sitl" in str(e.value)
    from cafe import receipts as R
    n0 = len(R.OUT)
    uas._sitl_receipts(P, None, R)
    new = R.OUT[n0:]
    assert len(new) == 1 and new[0]["kind"] == "context" and new[0]["value"] == 0.0 and "binary absent" in new[0]["claim"]


def test_missing_emulator_machinery_is_the_same_error(monkeypatch):
    import cafe
    monkeypatch.delattr(cafe, "emulator", raising=False)                  # `from cafe import emulator` finds the attribute first
    monkeypatch.setitem(sys.modules, "cafe.emulator", None)
    with pytest.raises(uas.SitlUnavailable, match="cafe.emulator cannot be imported"):
        uas.fly_sitl(AnalyticEnv(), uas.steaming(), 0.0, plat=P)


FAKE_HEAD = """
import json, socket, struct, sys, time, threading
I = int(sys.argv[sys.argv.index("-I") + 1])
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(30.0)
dst = ("127.0.0.1", 9002 + 10 * I)
def frame(fc, magic=18458, n=16, pwm=1500):
    return struct.pack("<HHI%dH" % n, magic, 400, fc, *([pwm] * n))
def ask(b):
    s.sendto(b, dst)
    return json.loads(s.recvfrom(4096)[0])
"""


def test_lockstep_machinery_answers_every_frame_once(tmp_path, monkeypatch):
    """A stand-in firmware speaks the JSON-backend wire format: junk, bad magic, 16- and 32-channel frames, a repeated frame."""
    from cafe import emulator
    body = FAKE_HEAD + """
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)           # accepts the MAVLink link, never says anything
time.sleep(0.8)                                                  # slower than the 0.5 s poll: the bridge must keep waiting
s.sendto(b"xx", dst)                                             # too short: ignored
s.sendto(frame(0, magic=1), dst)                                 # wrong magic: ignored
a = ask(frame(0))
b = ask(frame(0))                                                # repeated frame: same answer, no new step
c = ask(frame(1, magic=29569, n=32, pwm=1000))
out = {"a": a["timestamp"], "b": b["timestamp"], "c": c["timestamp"], "keys": list(a)}
open(sys.argv[sys.argv.index("--defaults") + 1].split(",")[-1] + ".out", "w").write(json.dumps(out))
for fc in range(2, 400):
    ask(frame(fc, pwm=1100))
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    res = uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / "wd"))
    seen = json.loads((tmp_path / "wd" / "uas.parm.out").read_text())
    assert seen["a"] == seen["b"] == 0.0025 and np.isclose(seen["c"], 0.005)                  # frame 0 stepped once; frame 1 stepped once
    assert seen["keys"] == ["timestamp", "imu", "position", "quaternion", "velocity", "battery"]
    assert 0.5 <= res["t_end"][0] < 0.51 and res["sitl"]["instance"] >= 0 and res["energy_wh"][0] > 0
    assert (tmp_path / "wd" / "uas.parm").read_text().count("\n") > 30
    assert not res["landed"][0] and res["track"]["t"].size >= 1


def test_an_autopilot_that_never_arms_is_reported_and_fails_the_sitl_receipts(tmp_path, monkeypatch):
    from cafe import emulator
    from cafe import receipts as R
    body = FAKE_HEAD + """
from pymavlink.dialects.v20 import common as mavlink2
mav = mavlink2.MAVLink(None, srcSystem=1, srcComponent=1)
beat = mav.heartbeat_encode(2, 3, 0, 0, 4, 3).pack(mav)         # a copter that is alive, in mode 0, disarmed, and says nothing else
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)
def serve():
    conn, _ = srv.accept()
    while True:
        conn.sendall(beat)
        time.sleep(0.1)
threading.Thread(target=serve, daemon=True).start()
fc = 0
while True:
    ask(frame(fc))
    fc += 1
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    with pytest.raises(RuntimeError, match="would not switch to GUIDED"):
        uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, wp=np.array([[0.0, 0.0, 5.0]]),
                     workdir=str(tmp_path / "wd3"), boot_s=0.5, patience_s=1.5)
    monkeypatch.setattr(uas, "fly_sitl", functools.partial(uas.fly_sitl, boot_s=0.5, patience_s=1.5))
    n0 = len(R.OUT)
    uas._sitl_receipts(P, None, R)
    new = R.OUT[n0:]
    assert len(new) == 1 and new[0]["ok"] is False and "did not" in new[0]["claim"]


def test_an_autopilot_that_never_speaks_mavlink_is_reported(tmp_path, monkeypatch):
    from cafe import emulator
    body = FAKE_HEAD + """
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)           # accepts the link, never sends a heartbeat
fc = 0
while True:
    ask(frame(fc))
    fc += 1
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    with pytest.raises(RuntimeError, match="no MAVLink heartbeat"):
        uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, wp=np.array([[0.0, 0.0, 5.0]]),
                     workdir=str(tmp_path / "wd4"), boot_s=0.2, patience_s=1.0)


def test_a_firmware_that_dies_is_reported(tmp_path, monkeypatch):
    from cafe import emulator
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, "import sys\nsys.exit(3)\n"))
    with pytest.raises(RuntimeError, match="exited with code 3"):
        uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, wp=np.array([[0.0, 0.0, 5.0]]), max_s=5.0,
                     workdir=str(tmp_path / "wd2"))


def test_sitl_params_match_the_airframe():
    p = uas.sitl_params(P)
    assert p["SIM_RATE_HZ"] == 400 and p["MOT_THST_HOVER"] == pytest.approx(0.772 * G / 4 / 8.25, abs=1e-3)
    assert p["ATC_RAT_RLL_P"] < 0.05 and p["ATC_RAT_YAW_D"] == 0.0 and p["ANGLE_MAX"] == 3500
    assert uas.sitl_params(P, rate_scale=2.0)["ATC_RAT_PIT_P"] == pytest.approx(2 * p["ATC_RAT_PIT_P"], rel=1e-3)
    assert uas.sitl_params(P, FENCE_ENABLE=1)["FENCE_ENABLE"] == 1


# ------------------------------------------------------------------------------------------------ ENU/FLU -> NED/FRD (what ArduPilot is told)

def sim_with(q=(1.0, 0.0, 0.0, 0.0), p=(0.0, 0.0, 0.0), v=(0.0, 0.0, 0.0), w=(0.0, 0.0, 0.0), sf=(0.0, 0.0, G)):
    s = uas._Sim1(P, uas.derive(P, 1), lambda k, t, pos: np.zeros((3, 1)), (0.0, 0.0), (0, 1, 2, 3))
    col = lambda x: jnp.asarray(x, float)[:, None]
    s.q, s.p, s.v, s.w, s.sf = col(q), col(p), col(v), col(w), col(sf)
    return s


def axis_angle(axis, deg):
    a = np.radians(deg) / 2
    return (math.cos(a), *(math.sin(a) * np.asarray(axis, float)))


def test_attitude_conversion_to_ned_frd():
    assert np.allclose(np.degrees(sim_with().rpy()), [0.0, 0.0, 90.0])                           # facing east = heading 90
    assert np.allclose(np.degrees(sim_with(axis_angle([0, 0, 1], 90)).rpy()), [0.0, 0.0, 0.0])    # turned CCW to face north = heading 0
    assert np.allclose(np.degrees(sim_with(axis_angle([1, 0, 0], 10)).rpy()), [10.0, 0.0, 90.0])  # right wing down = positive roll
    assert np.allclose(np.degrees(sim_with(axis_angle([0, 1, 0], 10)).rpy()), [0.0, -10.0, 90.0])  # nose down = negative pitch


@given(st.floats(-179, 179))
def test_heading_is_ninety_minus_the_math_yaw(psi):
    h = np.degrees(sim_with(axis_angle([0, 0, 1], psi)).rpy()[2])
    assert abs((h - (90.0 - psi) + 180) % 360 - 180) < 1e-3


def test_reply_is_ned_frd_with_the_field_order_the_parser_needs():
    s = sim_with(p=(3.0, 4.0, 5.0), v=(1.0, 2.0, 3.0), w=(0.1, 0.2, 0.3), sf=(0.5, 0.6, G))
    s.volt, s.pe = jnp.array([20.0]), jnp.array([100.0])
    j = json.loads(s.reply())
    assert list(j) == ["timestamp", "imu", "position", "quaternion", "velocity", "battery"]
    assert j["position"] == [4.0, 3.0, -5.0] and j["velocity"] == [2.0, 1.0, -3.0]                # north, east, down
    assert np.allclose(j["imu"]["gyro"], [0.1, -0.2, -0.3]) and np.allclose(j["imu"]["accel_body"], [0.5, -0.6, -G])
    assert j["battery"] == {"voltage": 20.0, "current": 5.0} and np.isclose(np.linalg.norm(j["quaternion"]), 1.0)
