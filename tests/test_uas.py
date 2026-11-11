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

from cafe.pm import Tagged
from cafe.pm.env.protocol import AnalyticEnv
from cafe.pm.physics import comms, uas

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
    rf = comms._yaml("radios.yaml")["radios"][P["radio"]["link"]]                       # the radio's numbers are radios.yaml's alone (round 14, M-39)
    assert P["radio"]["link"] == "rfd900x" and rf["center_mhz"] == 915.0 and rf["tx_dbm"] == 30.0 and rf["rx_sens_dbm"] == -121.0   # BRIEF 2.8: 902-928 MHz
    assert P["radio"]["ship_antenna_height_m"] > 0
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


def test_r11_m13_sitl_targets_and_the_track_are_in_the_launch_relative_frame_whatever_the_ship_and_the_launch_time():
    """`_Sim1.p` starts at zero at the launch: the waypoints ride on the ship's displacement since the launch, not on its position
    (a ship not at the origin, or a launch after t = 0, left the arrival test never true and the track shifted by the ship's position)."""
    t_launch, rel = 100.0, np.array([30.0, -20.0, 25.0])
    ship = uas.steaming(pos0=(1000.0, 500.0), speed=5.0, to_deg=90.0)                # 5 m/s east from (1000, 500)
    ship0 = np.asarray(ship(t_launch), float)
    assert np.allclose(ship0, [1500.0, 500.0])
    assert np.allclose(uas._ship_rel(ship, t_launch, ship0, 0.0), 0.0)
    r = uas._ship_rel(ship, t_launch, ship0, 12.0)
    assert r.shape == (3,) and np.allclose(r, [60.0, 0.0, 0.0], atol=1e-9)
    tgt = r + rel                                                                      # what `goto` aims at, and tells the firmware
    p = np.array([90.0, -20.0, 25.0])                                                  # a vehicle holding station on that point of the formation
    assert uas._reached(p, tgt, 2.0, 2.0)
    assert not uas._reached(p + [0.0, 0.0, 3.0], tgt, 2.0, 2.0) and not uas._reached(p + [2.5, 0.0, 0.0], tgt, 2.0, 2.0)
    assert not uas._reached(p, tgt + np.append(ship0, 0.0), 2.0, 2.0)          # the old target (the ship's absolute position added) is far away
    assert np.allclose(p - uas._ship_rel(ship, t_launch, ship0, 12.0), rel)   # the track's formula: p less the ship's displacement


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


AUTOPILOT_THAT_GOES_WHERE_TOLD = FAKE_HEAD + """
import math
from pymavlink.dialects.v20 import common as mavlink2
mav = mavlink2.MAVLink(None, srcSystem=1, srcComponent=1)
beat = mav.heartbeat_encode(2, 3, 129, 4, 4, 3).pack(mav)       # a copter that is armed and in GUIDED
LAT0, LON0, MPD = %r, %r, %r
target = [0.0, 0.0, 0.0]                                         # east, north, up of the last position target, metres from the firmware's home
aimed = open(sys.argv[sys.argv.index("--defaults") + 1].split(",")[-1] + ".aimed", "w")
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)
def serve():
    conn, _ = srv.accept()
    conn.settimeout(0.05)
    rx = mavlink2.MAVLink(None)
    rx.robust_parsing = True
    while True:
        conn.sendall(beat)
        try:
            data = conn.recv(4096)
        except socket.timeout:
            data = b""
        for msg in (rx.parse_buffer(data) or []):
            if msg.get_type() == "SET_POSITION_TARGET_GLOBAL_INT":
                target[:] = [(msg.lon_int / 1e7 - LON0) * MPD * math.cos(math.radians(LAT0)), (msg.lat_int / 1e7 - LAT0) * MPD, msg.alt]
                aimed.write(json.dumps(target + [fc]) + "\\n"); aimed.flush()                 # and the frame it came in on: 2.5 ms of sim time each
            elif msg.get_type() == "COMMAND_LONG" and msg.command == 22:             # take off to param7
                target[2] = msg.param7
threading.Thread(target=serve, daemon=True).start()
fc = 0
while True:                                                      # the target goes back to the bridge in the servo channels, 0.1 m a count
    ask(struct.pack("<HHI16H", 18458, 400, fc, *([int(round(x * 10)) + 20000 for x in target] + [1500] * 13)))
    fc += 1
""" % (uas.SITL_HOME[1], uas.SITL_HOME[0], uas.M_PER_DEG)


class WhereTheServosSay(uas._Sim1):
    """The physics of a vehicle that is exactly where the stand-in autopilot last told it to be: only the frames are tested."""

    def step(self, pwm):
        self.t += uas.DT_PHYS
        self.p = jnp.asarray([[(pwm[i] - 20000) / 10.0] for i in range(3)])


def test_r11_batch_b_fly_sitl_flies_a_formation_on_a_ship_that_is_not_at_the_origin_at_the_launch(tmp_path, monkeypatch):
    """M-13 through `fly_sitl` itself, with a stand-in autopilot (the binary is not on every host): the position target it receives, the
    arrival test and the recorded track must all be in the launch-relative frame. Before, the arrival test aimed at the ship's absolute
    position, was never true, and the run ran to its cap with the track shifted by the ship's position at the launch."""
    from cafe import emulator
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, AUTOPILOT_THAT_GOES_WHERE_TOLD))
    monkeypatch.setattr(uas, "_Sim1", WhereTheServosSay)
    ship = uas.steaming(pos0=(1000.0, 500.0), speed=1.0, to_deg=90.0)                 # 1 m/s east: at (1100, 500) when the sortie starts at 100 s
    wp = np.array([[30.0, -20.0, 25.0], [60.0, 10.0, 30.0]])
    res = uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), ship, 100.0, origin=ORIGIN, plat=P, wp=wp, max_s=60.0, boot_s=0.5, patience_s=5.0, hold_s=10.0,
                       workdir=str(tmp_path / "wd"))
    assert res["t_end"][0] < 40.0                                                   # the waypoints, the hold and the landing were done, not the cap
    aimed = np.array([json.loads(ln) for ln in (tmp_path / "wd" / "uas.parm.aimed").read_text().splitlines()])
    assert np.allclose(aimed[0, :2], [30.0, -20.0], atol=5.0) and aimed[0, 2] == 25.0     # the first waypoint plus the ship's few metres since the launch
    assert np.abs(aimed[:, :2]).max() < 200.0                                       # never the ship's position of 1100 m
    formation = np.array([[0.0, 0.0, 25.0], [30.0, -20.0, 25.0], [60.0, 10.0, 30.0], [0.0, 0.0, 15.0], [0.0, 0.0, 0.0]])
    t_told = aimed[0, 3] * uas.DT_PHYS + 0.5                                        # before the stand-in is first told where to go it stays at the launch point
    pos = res["track"]["pos_rel"][0][res["track"]["t"] > t_told]                    # (the commander thread lags the lockstep by wall time: P-R11M1)
    nearest = np.linalg.norm(pos[:, None, :] - formation[None], axis=2).min(1)
    assert len(pos) >= 10 and nearest.max() < 3.0                                   # every point is a formation point, none shifted by the ship's offset
    assert np.linalg.norm(pos - formation[2], axis=1).min() < 3.0                   # and the hold at the last waypoint is among them


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


# ------------------------------------------------------------------------------------------------------------ review round 2, M-28

def test_the_clamp_diagnostics_carry_the_wind_the_tilt_cannot():
    """M-28: max_tilt_deg is 35.00 in every sortie (the horizontal force is clamped to g tan 35 deg, so the 42 deg exceedance needs 7 deg of
    overshoot), so it says nothing about the wind. The time the demand was beyond the clamp and the largest demand / clamp do."""
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 99.0
    calm, strong = fly(plat=plat, M=1), fly(wind=(13.0, 0.0), plat=plat, M=1)        # 13 m/s: beyond the 12 m/s envelope (within it the leg is slowed: M-10)
    assert calm["sat_s"][0] == 0.0 and calm["demand_ratio_max"][0] == 1.0
    assert strong["sat_s"][0] > 100.0 and strong["demand_ratio_max"][0] > 3.0                  # most of the 300 s sortie, asking for 3x what the clamp gives
    assert strong["max_tilt_deg"][0] < 35.5 and not strong["flags"]["attitude_exceedance"][0]  # the tilt stays at the clamp: no exceedance
    gate = fly(wind=(14.0, 0.0), M=1)
    assert gate["scrubbed"][0]                                                                  # the default launch rule (12 m/s): nothing flown
    assert gate["sat_s"][0] == 0.0 and gate["demand_ratio_max"][0] == 1.0


def test_a_gust_series_that_demands_more_than_the_clamp_shows_in_the_diagnostics():
    plat = fast_plat()
    gust = np.zeros((2, 7200, 3))
    gust[1, :, 0] = 13.0                                             # member 1 flies in a 13 m/s mean error the launch gate never saw (beyond the envelope)
    r = fly(plat=plat, M=2, turb=gust, heading_deg=[270.0, 270.0])   # legs run west, into the 9 m/s that blows toward the east
    assert r["sat_s"][0] < 10.0 and r["demand_ratio_max"][0] < 1.6 and r["sat_s"][1] > 100.0 and r["demand_ratio_max"][1] > 3.0


def test_r15_m10_one_airspeed_envelope_and_one_leg_speed_rule_serve_stage_1_and_stage_3():
    """Round 15 M-10: stage 3 held the airspeed inside the envelope by slowing the leg (DECISIONS 161) and stage 1 commanded 8 m/s of ground speed whatever the
    wind, so upwind in 6 m/s of wind it asked the airframe for 14 m/s of air; `v_air` was stored in `derive` and read nowhere. `leg_speed` is the rule
    (the largest ground speed along a heading that keeps |wind - s h| within the envelope); `airspeed_envelope` the envelope; both are what the sortie
    (`_block`) and the UAS window (`uas_case`) read."""
    from cafe.pm.stage3 import pipeline_windows as pw
    lim, dx = P["limits"], P["aero"]["d_x"]
    env = uas.airspeed_envelope(lim, dx)
    tilt_limited = G * math.tan(math.radians(lim["max_tilt_deg"])) / dx
    assert env == min(lim["max_airspeed_ms"], tilt_limited) == lim["max_airspeed_ms"] == 12.0 and 12.5 < tilt_limited < 12.7
    assert uas.airspeed_envelope(dict(lim, max_airspeed_ms=20.0), dx) == pytest.approx(tilt_limited) and uas.airspeed_envelope(lim, 0.0) == 12.0
    w, west, east, north = np.array([6.0, 0.0]), np.array([-1.0, 0.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0])
    s, ok = uas.leg_speed(w, west, 8.0, 12.0)                                                  # into a wind toward the east: 6 m/s of ground speed is 12 of air
    assert ok and s == pytest.approx(6.0) and np.hypot(*(w - s * west)) == pytest.approx(12.0)
    assert uas.leg_speed(w, east, 8.0, 12.0)[0] == 8.0 and uas.leg_speed(w, north, 8.0, 12.0)[0] == pytest.approx(8.0)    # downwind, across: the leg speed
    s, ok = uas.leg_speed(np.array([14.0, 0.0]), west, 8.0, 12.0)
    assert not ok and not uas.leg_speed(np.array([13.0, 0.0]), north, 8.0, 12.0)[1]                     # the wind alone is beyond the envelope
    assert pw.uas_leg_speed(w, west, 8.0, 12.0) == pytest.approx(6.0) and pw.uas_leg_speed(np.array([14.0, 0.0]), west, 8.0, 12.0) is None
    # the launch rule and the rule agree: at the platform's launch limit an upwind leg has no ground speed left, a hair above it has none at all
    lr = P["launch_rule"]["max_mean_wind_ms"]
    assert lr == uas.airspeed_envelope(lim, dx)
    s, ok = uas.leg_speed(np.array([lr, 0.0]), west, 8.0, uas.airspeed_envelope(lim, dx))
    assert ok and s == pytest.approx(0.0, abs=1e-9) and not uas.leg_speed(np.array([lr + 0.01, 0.0]), west, 8.0, uas.airspeed_envelope(lim, dx))[1]
    prm = uas.derive(P, 3)
    assert "v_air" not in prm and np.allclose(np.asarray(prm["v_env"]), 12.0)


def test_r15_m10_a_leg_into_a_wind_inside_the_envelope_is_flown_at_the_speed_the_airframe_can_hold_not_at_the_commanded_one():
    """Round 15 M-10, on the sortie: into 9 m/s (the launch rule is off) the old sortie commanded 8 m/s of ground speed, 17 m/s of air, and the lean-angle
    clamp was exceeded for most of the 300 s (10 m/s: 100 s and more, the old case of the clamp test); the leg is now slowed to 3 m/s of ground speed,
    the air stays at 12 m/s (tilt 33.7 deg, inside the 35 deg limit) and the clamp is hardly touched."""
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 99.0
    r = fly(wind=(9.0, 0.0), plat=plat, M=1)
    assert r["sat_s"][0] < 30.0 and r["demand_ratio_max"][0] < 3.0 and not r["flags"]["attitude_exceedance"][0]
    assert not r["flags"]["wind_exceeds_airspeed"][0]


# ------------------------------------------------------------------------------------------------ review round 3

def test_first_failure_times_are_float64_so_they_survive_the_sum_with_a_launch_time_in_epoch_seconds():
    """M-6: t_first came back float32 from JAX; added to a 2023 epoch time (1.7e9 s) the sum has 128 s resolution, so the first and the median failure
    of a run printed the same second."""
    t_launch = 1677892992.0 + 37.3                                                               # not a multiple of 128 s
    r = fly(scale=dict(battery=[1.0, 0.2]), t=t_launch)
    for k, v in r["t_first"].items():
        assert v.dtype == np.float64, k
    t1 = r["t_first"]["battery_reserve"][1]
    assert 30.0 < t1 <= r["t_end"][1]
    assert (t1 + t_launch) - t_launch == pytest.approx(t1, abs=1e-6)                             # float32 would be off by up to 64 s
    assert (t1 + t_launch) % 128.0 != 0.0
    m = uas.fly_mission(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), [t_launch], M=2, origin=ORIGIN, plat=fast_plat(),
                        scale=dict(battery=[1.0, 0.2]))["mission"]
    assert m["t_first"]["battery_reserve"][1] == pytest.approx(t_launch + t1, abs=1e-6)


# ------------------------------------------------------------------------------------------------------------ review round 4

def test_the_fast_sortie_reaches_every_waypoint_and_reports_how_many():
    """M-1: fly_sortie returns wp_done (the waypoint index at the end) and n_wp; a sortie that flies the whole pattern is not profile_incomplete."""
    r = fly(M=2)
    assert r["n_wp"] == 4 and r["wp_done"].tolist() == [4, 4] and not r["flags"]["profile_incomplete"].any() and not r["failed"].any()
    assert "profile_incomplete" in uas.FLAGS and set(r["flags"]) == set(uas.FLAGS) == set(r["t_first"])


def test_a_sortie_cut_short_by_the_timer_is_profile_incomplete_and_the_minimum_fraction_sets_the_bar():
    """M-1: the 1200 s return-to-ship timer ended the 20 min pattern at 7 of 8 waypoints in the demo's mean wind and nothing recorded it. Here the same cut
    on the fast sortie: the timer at 60 % of the sortie (time_limit_factor 0.6) returns it after 2 or 3 of 4 waypoints."""
    plat = fast_plat()
    plat["sortie"]["time_limit_factor"] = 0.6
    r = fly(plat=plat, M=2)
    n = int(r["wp_done"][0])
    assert r["n_wp"] == 4 and 1 <= n < 4 and r["wp_done"].tolist() == [n, n] and r["landed"].all()
    assert r["flags"]["profile_incomplete"].all() and r["failed"].all() and not r["flags"]["battery_reserve"].any()          # nothing else failed
    assert np.allclose(r["t_first"]["profile_incomplete"], r["t_end"]) and (r["t_first"]["profile_incomplete"] > 0).all()   # first at the end of the sortie
    ok = copy.deepcopy(plat)
    ok["sortie"]["min_profile_fraction"] = n / 4                                          # exactly the share flown: enough
    assert not fly(plat=ok, M=2)["flags"]["profile_incomplete"].any()
    ok["sortie"]["min_profile_fraction"] = (n + 0.5) / 4
    assert fly(plat=ok, M=2)["flags"]["profile_incomplete"].all()


def test_a_scrubbed_sortie_is_not_profile_incomplete_and_still_reports_its_pattern():
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 1.0
    r = fly(wind=(-5.0, 0.0), plat=plat, M=2)
    assert r["scrubbed"].all() and r["wp_done"].tolist() == [0, 0] and r["n_wp"] == 4
    assert not r["flags"]["profile_incomplete"].any() and np.isnan(r["t_first"]["profile_incomplete"]).all()


def test_the_demo_sortie_in_a_6_m_s_wind_returns_at_7_of_8_waypoints_and_in_still_air_flies_all_8():
    """M-1: real platform, legs upwind, AnalyticEnv's log wind profile (10 m value given). Measured on homebase for 2 .. 9 m/s: 8 of 8 up to 5.0 m/s, 7 of 8 for
    5.5 .. 6.5, 6 at 7.0, 5 from 7.5 to 9 (the reviewer's uniform-wind table has 7 of 8 at 5.3, about 0.3 m/s lower for the same cut)."""
    calm, windy = (uas.fly_sortie(AnalyticEnv(wind=w), uas.steaming(), 0.0, M=1, origin=ORIGIN, plat=P) for w in ((0.0, 0.0), (-6.0, 0.0)))
    assert calm["n_wp"] == windy["n_wp"] == 8 and calm["wp_done"].tolist() == [8] and windy["wp_done"].tolist() == [7]
    assert not calm["flags"]["profile_incomplete"].any() and windy["flags"]["profile_incomplete"].all()
    assert not windy["flags"]["battery_reserve"].any() and windy["landed"].all()                       # before the fix this was a pass


def test_a_one_sample_fade_is_ridden_through_and_a_long_one_sets_lost_link_at_the_start_of_the_run():
    """M-10: lost_link latched on one lost sample of the link model (a smooth-sea two-ray null); it now needs radio.link_loss_hold_s (5 s) of consecutive lost
    samples, and t_first is where that run began."""
    assert P["radio"]["link_loss_hold_s"] == 5.0

    def lost_in(lo, hi):
        return lambda t, pos: np.full(len(pos), lo < t < hi)
    one = fly(link=lost_in(9.5, 10.5), M=2)                                                    # one 1 s sample at t = 10 s
    assert not one["flags"]["lost_link"].any() and np.isnan(one["t_first"]["lost_link"]).all() and not one["failed"].any()
    four = fly(link=lost_in(19.5, 23.5), M=2)                                                  # samples 20 .. 23: 4 s
    assert not four["flags"]["lost_link"].any()
    six = fly(link=lost_in(19.5, 25.5), M=2)                                                   # samples 20 .. 25: 6 s
    assert six["flags"]["lost_link"].all() and six["failed"].all() and np.allclose(six["t_first"]["lost_link"], 20.0)
    two_runs = fly(link=lambda t, pos: np.full(len(pos), (19.5 < t < 22.5) or (24.5 < t < 27.5)), M=2)       # 3 s, a break, 3 s: not 5 s in a row
    assert not two_runs["flags"]["lost_link"].any()
    plat = fast_plat()
    plat["radio"]["link_loss_hold_s"] = 0.0                                                    # hold 0: the first lost sample counts, as before
    assert fly(link=lost_in(9.5, 10.5), plat=plat, M=2)["flags"]["lost_link"].all()
    assert np.allclose(fly(link=lost_in(9.5, 10.5), plat=plat, M=2)["t_first"]["lost_link"], 10.0)


def test_the_hold_counts_each_member_on_its_own_run():
    def link(t, pos):                                                                          # member 0: 6 s lost; member 1: 3 s, a break, 3 s
        return np.array([19.5 < t < 25.5, (19.5 < t < 22.5) or (24.5 < t < 27.5)])
    r = fly(link=link, M=2)
    assert r["flags"]["lost_link"].tolist() == [True, False] and r["t_first"]["lost_link"][0] == pytest.approx(20.0) and np.isnan(r["t_first"]["lost_link"][1])


# ---- review round 7, M-42: `sortie.battery_swap` was required and read by no code
def test_r7_m42_battery_swap_is_not_a_platform_input_and_an_old_file_that_carries_it_still_loads(tmp_path):
    assert "battery_swap" not in uas.load_platform("quad_uas")["sortie"] and "battery_swap" not in uas.REQUIRED["sortie"]
    raw = yaml.safe_load((uas.PLATFORM.parent / "quad_uas.yaml").read_text())
    raw["sortie"]["battery_swap"] = dict(value=True, unit="-", assumed=True, why="an old file")
    f = tmp_path / "quad_uas.yaml"
    f.write_text(yaml.safe_dump(raw))
    assert uas.load_platform(str(f))["sortie"]["battery_swap"] is True                                  # extra leaves are not refused


def test_r7_m42_every_required_key_of_the_uas_platform_is_named_in_the_code_that_reads_it():
    """A key in `REQUIRED` that no code reads is an input a lab user sets in vain; each key must appear quoted in the package's code."""
    src = "".join(f.read_text() for f in (pathlib.Path(uas.__file__).parents[1]).rglob("*.py"))
    unread = [(g, k) for g, table in uas.REQUIRED.items() for k in table if f'"{k}"' not in src and f"'{k}'" not in src]
    assert unread == [], unread


# ---- review round 8: M-27 (t_end of a scrubbed member, an empty mission), M-38 (the physics socket is loopback only)
def test_r8_m27_a_scrubbed_member_flew_for_zero_seconds_whatever_the_others_do():
    def gust(t):
        g = np.zeros((2, 3))
        g[1, 0] = 6.0 if 300.0 <= t <= 400.0 else 0.0                                          # member 1 is scrubbed by a front
        return g
    r = fly(M=2, gust=gust)
    assert list(r["scrubbed"]) == [False, True] and r["t_end"][1] == 0.0 and r["t_end"][0] > 100.0       # [t, t] before
    assert fly(wind=(14.0, 0.0), M=2)["t_end"].tolist() == [0.0, 0.0]                                   # all scrubbed: as before


def test_r8_m27_a_mission_with_no_launch_time_is_a_named_error():
    with pytest.raises(ValueError, match="fly_mission needs at least one launch time"):
        uas.fly_mission(AnalyticEnv(), uas.steaming(), [], M=3, origin=ORIGIN, plat=fast_plat())


def test_r8_m38_the_sitl_physics_socket_binds_the_loopback_interface_only(tmp_path, monkeypatch):
    import types
    from cafe import emulator
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, "pass\n"))
    bound = []

    class Rec:
        def __init__(self, *a):
            pass

        def bind(self, addr):
            bound.append(addr)
            raise RuntimeError("stop after bind")

        def close(self):
            pass

    monkeypatch.setattr(uas, "socket", types.SimpleNamespace(AF_INET=2, SOCK_DGRAM=2, socket=Rec))
    with pytest.raises(RuntimeError, match="stop after bind"):
        uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / "wd"), instance=3)
    assert bound == [("127.0.0.1", 9002 + 10 * 3)]                                                       # ("0.0.0.0", ...) before


# ------------------------------------------------------------------------------------------------ review round 9, M-3 and M-26
class HoleWind(AnalyticEnv):
    """A masked cell in the wind store: NaN east of `lon_hole` or, with `t_hole`, only at the lookups made in that window of seconds (lo, hi)."""

    def __init__(self, lon_hole=np.inf, t_hole=None, **kw):
        super().__init__(**kw)
        self.lon_hole, self.t_hole = lon_hole, t_hole

    def wind(self, lon, lat, z, t):
        v = np.array(super().wind(lon, lat, z, t).value, float)
        bad = np.broadcast_to(np.asarray(lon, float) > self.lon_hole, v.shape[:-1])
        if self.t_hole is not None:
            bad = bad | (self.t_hole[0] < float(np.max(t)) < self.t_hole[1])
        return Tagged(np.where(bad[..., None], np.nan, v), "hole", 0.0, "assumed")


def test_r9_m3_a_nan_wind_met_in_flight_is_no_current_data_and_the_vehicle_stays_finite():
    """Before: the member met the hole, every flag stayed False but profile_incomplete, and soc_end, max_tilt_deg and the track were NaN. Member 0 flies east
    into the hole (it is NaN from 111 m east of the ship), member 1 west, away from it: only member 0 is flagged, on a zero wind (the env's wind is 0 anyway,
    so its flight is exactly the clean one)."""
    hd = np.array([90.0, 270.0])
    r = uas.fly_sortie(HoleWind(lon_hole=ORIGIN[0] + 0.001, wind=(0.0, 0.0)), uas.steaming(), 0.0, M=2, origin=ORIGIN, plat=fast_plat(), heading_deg=hd)
    clean = fly(M=2, heading_deg=hd)
    assert r["flags"]["no_current_data"].tolist() == [True, False] and r["failed"].tolist() == [True, False]
    assert 0.0 < r["t_first"]["no_current_data"][0] < r["t_end"][0] and np.isnan(r["t_first"]["no_current_data"][1])
    assert np.isfinite(r["soc_end"]).all() and np.isfinite(r["max_tilt_deg"]).all() and np.isfinite(r["track"]["pos_rel"]).all()
    assert not any(r["flags"][k].any() for k in uas.FLAGS if k != "no_current_data")             # profile_incomplete too: the pattern was flown
    assert np.array_equal(r["soc_end"], clean["soc_end"]) and np.array_equal(r["track"]["pos_rel"], clean["track"]["pos_rel"])
    assert uas.FLAGS[-1] == "no_current_data"  # appended: the indices of the others (first_failure_mode) do not move


def test_r9_m3_the_flag_is_sticky_and_stamped_at_the_end_of_the_first_block_with_a_hole():
    """One lookup (t = 10 s, held for the next second) is NaN and every later one is finite: the 1 s held mean does not clear the flag."""
    r = uas.fly_sortie(HoleWind(t_hole=(9.99, 10.01), wind=(0.0, 0.0)), uas.steaming(), 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    assert r["flags"]["no_current_data"].all() and np.allclose(r["t_first"]["no_current_data"], 10.05) and r["t_end"].min() > 20.0
    assert r["failed"].all() and np.isfinite(r["soc_end"]).all()


def test_r9_m3_a_hole_beyond_the_reach_of_the_sortie_does_not_flag_and_changes_nothing():
    far = uas.fly_sortie(HoleWind(lon_hole=ORIGIN[0] + 0.5, wind=(0.0, 0.0)), uas.steaming(), 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    clean = fly(M=2)
    assert not any(far["flags"][k].any() for k in uas.FLAGS) and not far["failed"].any()
    assert np.array_equal(far["soc_end"], clean["soc_end"]) and np.array_equal(far["track"]["pos_rel"], clean["track"]["pos_rel"])


def test_r9_m3_a_scrubbed_member_is_not_flagged_for_a_hole_it_never_flew_into():
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 1.0
    r = uas.fly_sortie(HoleWind(lon_hole=ORIGIN[0] - 1.0, wind=(-5.0, 0.0)), uas.steaming(), 0.0, M=2, origin=ORIGIN, plat=plat)  # NaN everywhere
    assert r["scrubbed"].all() and not r["flags"]["no_current_data"].any() and not r["failed"].any()


class AirHole(AnalyticEnv):
    """No surface pressure east of 11 km from the origin, with a finite wind: the air state at a ship there is unknown."""

    def air(self, lon, lat, t):
        a = super().air(lon, lat, t)
        bad = np.asarray(lon, float) > ORIGIN[0] + 0.1
        a["psfc"] = Tagged(np.where(bad, np.nan, a["psfc"].value), "hole", 0.0, "assumed")
        return a


def test_r9_m3_no_air_state_at_the_ship_is_a_scrub_like_no_wind_there_not_a_nan_vehicle():
    """Before: a NaN air density at the ship gave NaN soc_end and max_tilt_deg and `profile_incomplete` for a member that was never scrubbed. Member 1's ship is
    50 km east, in the hole; member 0's is not, and flies as it does with no hole."""
    ship = uas.steaming(pos0=np.array([[0.0, 0.0], [50e3, 0.0]]))
    r = uas.fly_sortie(AirHole(wind=(0.0, 0.0)), ship, 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    clean = uas.fly_sortie(AnalyticEnv(wind=(0.0, 0.0)), ship, 0.0, M=2, origin=ORIGIN, plat=fast_plat())
    assert r["scrubbed"].tolist() == [False, True] and r["launch"]["ok"].tolist() == [True, False]
    assert np.isfinite(r["soc_end"]).all() and np.isfinite(r["max_tilt_deg"]).all() and not r["failed"].any()
    assert r["soc_end"][0] == clean["soc_end"][0] and np.array_equal(r["track"]["pos_rel"][0], clean["track"]["pos_rel"][0])


def test_l0_fly_sitl_scrubs_a_ship_with_no_air_state_as_fly_sortie_does_and_never_starts_the_firmware(tmp_path, monkeypatch):
    """Round 9, M-3 sibling: fly_sitl read the air at the ship without fly_sortie's guard, so a hole gave energy_wh and soc_end NaN with every flag False."""
    from cafe import emulator
    marker = tmp_path / "started"
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, f"open({str(marker)!r}, 'w').write('x')\n"))
    ship = uas.steaming(pos0=np.array([[50e3, 0.0]]))                                    # 50 km east of the origin: in AirHole's hole
    res = uas.fly_sitl(AirHole(wind=(0.0, 0.0)), ship, 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / "wd"))
    sortie = uas.fly_sortie(AirHole(wind=(0.0, 0.0)), ship, 0.0, M=1, origin=ORIGIN, plat=fast_plat())
    assert res["scrubbed"].tolist() == [True] == sortie["scrubbed"].tolist() and not marker.exists()
    assert np.isfinite([res["energy_wh"], res["soc_end"], res["max_tilt_deg"], res["t_end"]]).all() and not any(f.any() for f in res["flags"].values())
    assert res["track"]["pos_rel"].shape == (1, 0, 3) and "no finite air state" in res["sitl"]["messages"][0]


def test_l0_fly_sitl_points_the_default_pattern_as_in_still_air_when_the_wind_at_the_ship_is_a_hole(tmp_path, monkeypatch):
    from cafe import emulator
    body = FAKE_HEAD + """
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)
for fc in range(0, 400):
    ask(frame(fc, pwm=1100))
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    seen = []
    real = uas.flux_pattern
    monkeypatch.setattr(uas, "flux_pattern", lambda Pl, hd: (seen.append(np.asarray(hd, float)), real(Pl, hd))[1])
    res = uas.fly_sitl(HoleWind(lon_hole=-np.inf, wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / "wd"))
    assert np.isfinite(seen[0]).all() and res["flags"]["no_current_data"].tolist() == [True] and res["scrubbed"].tolist() == [False]


def test_r9_m26_fly_sitl_documents_the_dict_it_returns_not_fly_sortie_s(tmp_path, monkeypatch):
    """The docstring said 'same fields as fly_sortie for one member'; the dict lacks t_first, wp_done, n_wp and more. Every key it returns is named in the
    docstring, and so is every key of fly_sortie's that it lacks, as absent."""
    from cafe import emulator
    body = FAKE_HEAD + """
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)
for fc in range(0, 400):
    ask(frame(fc, pwm=1100))
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    res = uas.fly_sitl(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / "wd"))
    doc = " ".join(uas.fly_sitl.__doc__.split())
    assert "same fields as fly_sortie" not in doc
    head, _, tail = doc.partition("There is no ")
    assert all(k in head for k in (*res, *res["flags"], "sitl")), [k for k in (*res, *res["flags"]) if k not in head]
    lacking = set(fly(M=1)) - set(res)
    assert lacking and all(k in tail for k in lacking), [k for k in lacking if k not in tail]
    assert set(res["flags"]) == {"battery_reserve", "wind_exceeds_airspeed", "attitude_exceedance", "lost_link", "no_current_data"}
    assert "not modelled" in doc and not res["flags"]["wind_exceeds_airspeed"].any() and not res["flags"]["lost_link"].any()


def test_r9_fly_sitl_labels_a_wind_that_is_not_finite_and_gives_the_firmware_a_zero_wind(tmp_path, monkeypatch):
    """Before: the NaN went into the physics and out to the firmware, soc_end and max_tilt_deg were NaN, and no flag said why."""
    from cafe import emulator
    body = FAKE_HEAD + """
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 5760 + 10 * I)); srv.listen(1)
for fc in range(0, 400):
    ask(frame(fc, pwm=1100))
"""
    monkeypatch.setattr(emulator, "SITL_DIR", fake_sitl(tmp_path, body))
    res = {}
    for name, env in (("hole", HoleWind(lon_hole=-np.inf, wind=(0.0, 0.0))), ("clean", AnalyticEnv(wind=(0.0, 0.0)))):
        res[name] = uas.fly_sitl(env, uas.steaming(), 0.0, origin=ORIGIN, plat=P, max_s=0.5, workdir=str(tmp_path / name))
    assert res["hole"]["flags"]["no_current_data"].tolist() == [True] and res["clean"]["flags"]["no_current_data"].tolist() == [False]
    assert np.isfinite([res["hole"]["soc_end"], res["hole"]["max_tilt_deg"], res["hole"]["energy_wh"]]).all()
    assert np.array_equal(res["hole"]["soc_end"], res["clean"]["soc_end"])                       # the env's wind is 0, so the zero wind is the clean flight


# ---- review round 11, M-26: near-threshold tests of the thresholds the closed-loop tests passed by a wide margin ----------------------------------
def test_r11_m26_the_battery_flag_fires_when_the_charge_crosses_the_reserve_not_half_of_it_and_the_return_starts_then_too():
    """`soc < 0.5 * reserve` passed: the only battery tests used a pack so small that the charge fell far below either. The flag's first time is the
    block in which the charge crossed `reserve_frac`: the 1 s record before it is at or above it, the one after below, and the vehicle turns for home."""
    res = P["battery"]["reserve_frac"]
    r = fly(scale=dict(battery=[0.2]), M=1)
    t1 = float(r["t_first"]["battery_reserve"][0])
    t, soc, ph = r["track"]["t"], r["track"]["soc"][0], r["track"]["phase"][0]
    before, after = int(np.searchsorted(t, t1, side="right")) - 1, int(np.searchsorted(t, t1, side="left"))
    assert t[before] <= t1 <= t[after] and soc[before] >= res > soc[after]
    assert ph[before] == uas.FLY and ph[after + 1] == uas.RTL                       # the failsafe return starts with the flag, not at half the reserve


class HeadwindPulse(AnalyticEnv):
    """No wind except a `speed` m/s headwind (from the east, for legs flown east) from t = `ta` for `length` seconds."""

    def __init__(self, ta, length, speed, **kw):
        super().__init__(**kw)
        self.ta, self.length, self.speed = ta, length, speed

    def wind(self, lon, lat, z, t):
        on = self.ta <= float(t) < self.ta + self.length
        return Tagged(np.broadcast_to(np.array([-self.speed if on else 0.0, 0.0]), np.broadcast(lon, lat).shape + (2,)).copy(), "analytic", 0.0, "assumed")


def test_r11_m26_the_no_headway_flag_waits_one_stuck_window_not_two_and_not_half_of_one():
    """`stuck >= 2 * stuck_w` passed (the wind test only needed it to fire before 200 s). A 14 m/s headwind (above g tan(max tilt)/d_x) that lasts
    1.8 windows sets the flag (the run of no headway starts about 3 s after the onset, so it has lasted 1.5 windows by the end); one of 0.9 does not."""
    plat = fast_plat()
    plat["launch_rule"]["max_mean_wind_ms"] = 99.0
    w = plat["failure"]["stuck_window_s"]

    def flag(length):
        return bool(uas.fly_sortie(HeadwindPulse(60.0, length, 14.0), uas.steaming(), 0.0, M=1, origin=ORIGIN, plat=plat, heading_deg=90.0)
                    ["flags"]["wind_exceeds_airspeed"][0])
    assert flag(1.8 * w) and not flag(0.9 * w)


def calm_leg_flag(**failure):
    """`wind_exceeds_airspeed` of a calm 300 s sortie flown with the given `failure` values: the steady closing speed on the long outbound leg is the
    leg speed and the speed asked is the same (probed on orca: 8.0 and 8.0; the climb at the ship and the first seconds of the leg are below both)."""
    plat = fast_plat()
    plat["failure"].update(failure)
    r = uas.fly_sortie(AnalyticEnv(wind=(0.0, 0.0)), uas.steaming(), 0.0, M=1, origin=ORIGIN, plat=plat, heading_deg=90.0)
    return bool(r["flags"]["wind_exceeds_airspeed"][0])


def test_r11_batch_b_the_no_headway_closing_speed_limit_is_read_as_it_is_not_doubled_or_halved():
    """Review round 11, M-26 neighbour (`closing < stuck_v`). The steady closing speed of a calm leg is the leg speed v. A limit of 1.25 v is
    never reached, so the flag fires; one of 0.6 v is passed in the first seconds of the leg, so it does not. Doubling the limit (1.2 v) turns the
    second case into a flag, halving it (0.625 v) the first into none."""
    v = fast_plat()["sortie"]["leg_speed_ms"]
    assert not calm_leg_flag()                                                        # the shipped limit: a calm sortie has headway
    assert calm_leg_flag(stuck_closing_ms=1.25 * v) and not calm_leg_flag(stuck_closing_ms=0.6 * v)


def test_r11_batch_b_the_no_headway_speed_asked_limit_is_read_as_it_is_not_doubled_or_halved():
    """Review round 11, M-26 neighbour (`ask > stuck_cmd`). With the closing limit out of reach (every closing speed is below 100 v) the flag is
    set by the speed the controller asks for alone, which on the long leg is the leg speed v: a limit of 0.6 v is exceeded, so it fires; 1.25 v
    never is. Doubling the limit (1.2 v) takes the first away, halving it (0.625 v) gives the second a flag."""
    v = fast_plat()["sortie"]["leg_speed_ms"]
    assert calm_leg_flag(stuck_closing_ms=100.0 * v, stuck_min_cmd_ms=0.6 * v) and not calm_leg_flag(stuck_closing_ms=100.0 * v, stuck_min_cmd_ms=1.25 * v)


class WindAt(AnalyticEnv):
    """A wind that blows at `speed` m/s only within 2 % of the sortie length of the times in `at`, and none otherwise."""

    def __init__(self, at, speed, span, **kw):
        super().__init__(**kw)
        self.at, self.speed, self.span = at, speed, span

    def wind(self, lon, lat, z, t):
        on = any(abs(float(t) - a) < 0.02 * self.span for a in self.at)
        return Tagged(np.broadcast_to(np.array([self.speed if on else 0.0, 0.0]), np.broadcast(lon, lat).shape + (2,)).copy(), "analytic", 0.0, "assumed")


@pytest.mark.parametrize("frac", [0.0, 0.5, 1.0])
def test_r11_m26_the_launch_gate_averages_the_wind_at_the_start_the_middle_and_the_end_of_the_sortie(frac):
    """`[0, 0.5, 0.5]` for the three sample times passed: a gale only at the end of the sortie was never read. A gale at any one of the three scrubs; a
    gale between them (at a quarter) does not."""
    t0, dur, lim = 5000.0, P["sortie"]["duration_s"], P["launch_rule"]["max_mean_wind_ms"]
    gale = 10.0 * lim                                                                 # a third of it is still over the limit at any height of the check
    env = WindAt([t0 + frac * dur], gale, dur)
    assert not uas.launch_check(env, uas.steaming(), t0, P, 1, ORIGIN)["ok"][0]
    assert uas.launch_check(WindAt([t0 + 0.25 * dur], gale, dur), uas.steaming(), t0, P, 1, ORIGIN)["ok"][0]


def test_r11_m26_a_link_lost_for_exactly_the_hold_latches_and_one_sample_less_does_not():
    """`run_s > link_hold_s` passed: the hold tests used 4 s and 6 s against a 5 s hold, never the 5 s itself."""
    plat = fast_plat()
    hold = int(plat["radio"]["link_loss_hold_s"])

    def lost_for(n):
        return lambda t, pos: np.full(len(pos), 19.5 < t < 19.5 + n)                    # n samples from t = 20 s
    on = fly(link=lost_for(hold), plat=plat, M=1)
    assert on["flags"]["lost_link"].all() and np.allclose(on["t_first"]["lost_link"], 20.0)
    assert not fly(link=lost_for(hold - 1), plat=plat, M=1)["flags"]["lost_link"].any()

