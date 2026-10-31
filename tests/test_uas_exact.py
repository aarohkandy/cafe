"""cafe.pm.physics.uas: the ArduCopter parameter recipe and the per-member physics that answers its servo packets, pinned to closed forms.
(No firmware is needed: `_Sim1` is driven directly. tests/test_uas.py runs the sortie, the receipts and the SITL wire format.)"""
import math

import jax.numpy as jnp
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from cafe.pm.physics import uas

P = uas.load_platform()
PRM = uas.derive(P, 1)
LEVEL = [[1.0], [0.0], [0.0], [0.0]]
IDLE = np.full(16, 1000.0)                                                       # every motor at 0 thrust (pwm 1000)


def quiet(k, t, pos):
    return np.zeros((3, 1))


def air(q=None, home=(0.0, 0.0), motor_map=(0, 1, 2, 3), wind_fn=quiet, prm=PRM):
    """A member 100 m above the sea, so the ground contact does not hold it."""
    s = uas._Sim1(P, prm, wind_fn, home, motor_map)
    s.p = jnp.asarray([[0.0], [0.0], [100.0]])
    if q is not None:
        s.q = jnp.asarray(q)
    return s


def pwm(*motors):
    return np.array(list(motors) + [1000.0] * (16 - len(motors)))


# ---- sitl_params: what the firmware is told ------------------------------------------------------------------------------
def test_sitl_params_are_the_airframe_in_ardupilot_units():
    p = uas.sitl_params(P)
    assert {k: v for k, v in p.items() if not k.startswith("ATC_RAT")} == dict(
        SIM_RATE_HZ=400, SCHED_LOOP_RATE=200, ARMING_CHECK=0, BATT_MONITOR=4, FRAME_CLASS=1, FRAME_TYPE=1, MOT_PWM_MIN=1000, MOT_PWM_MAX=2000,
        MOT_SPIN_ARM=0.02, MOT_SPIN_MIN=0.03, MOT_SPIN_MAX=1.0, MOT_THST_EXPO=0.98, MOT_THST_HOVER=0.229, MOT_HOVER_LEARN=2,
        MOT_BAT_VOLT_MAX=pytest.approx(25.2), MOT_BAT_VOLT_MIN=pytest.approx(19.8), WPNAV_SPEED=800, WPNAV_ACCEL=250, WPNAV_SPEED_UP=300,
        WPNAV_SPEED_DN=150, WPNAV_RADIUS=300, ANGLE_MAX=3500, FENCE_ENABLE=0, WP_YAW_BEHAVIOR=0, FS_THR_ENABLE=0, FS_GCS_ENABLE=0,
        ATC_ANG_RLL_P=6.0, ATC_ANG_PIT_P=6.0, ATC_ANG_YAW_P=6.0)
    assert p["MOT_THST_HOVER"] == round(0.772 * uas.G0 / 4 / 8.25, 3)                    # hover thrust as a fraction of the maximum thrust
    assert p["SIM_RATE_HZ"] == round(1 / uas.DT_PHYS) and isinstance(p["WPNAV_SPEED"], int) and isinstance(p["ANGLE_MAX"], int)


def test_rate_gains_follow_the_mixer_authority_of_each_axis():
    """P = rate x J / (4 x arm x 0.7071 x thrust_max) for roll and pitch, yaw with the torque arm kQ/kT and a factor 0.5."""
    p = uas.sitl_params(P)
    thrust, om = 8.25, 30000.0 * 2 * math.pi / 60
    arm = 0.13 / math.sqrt(2)
    kt = thrust / om ** 2
    cq = math.sqrt(kt) / (math.sqrt(2 * 1.2 * math.pi * 0.127 ** 2 / 4) * 0.6)
    jx, jy, jz = 0.0025, 0.0021, 0.0043
    want = dict(RLL=20.0 * jx / (4 * arm * 0.7071 * thrust), PIT=20.0 * jy / (4 * arm * 0.7071 * thrust), YAW=0.5 * 20.0 * jz / (4 * cq * thrust))
    assert (round(want["RLL"], 5), round(want["PIT"], 5), round(want["YAW"], 5)) == (0.02331, 0.01958, 0.1491)
    for ax, pk in want.items():
        assert p[f"ATC_RAT_{ax}_P"] == round(pk, 5)
        assert p[f"ATC_RAT_{ax}_I"] == round(pk * (0.1 if ax == "YAW" else 1.0), 5)
        assert p[f"ATC_RAT_{ax}_D"] == (0.0 if ax == "YAW" else round(0.027 * pk, 6))
    assert (p["ATC_RAT_RLL_D"], p["ATC_RAT_PIT_D"], p["ATC_RAT_YAW_I"]) == (0.000629, 0.000529, 0.01491)
    q = uas.sitl_params(P, rate_scale=2.0, FENCE_ENABLE=1, EXTRA=7)
    assert q["ATC_RAT_RLL_P"] == round(2 * want["RLL"], 5) and q["ATC_RAT_YAW_P"] == round(2 * want["YAW"], 5)
    assert q["FENCE_ENABLE"] == 1 and q["EXTRA"] == 7 and q["ATC_RAT_PIT_D"] == round(0.027 * 2 * want["PIT"], 6)


# ---- _Sim1: initial state ------------------------------------------------------------------------------------------------
def test_sim1_starts_at_rest_facing_north_on_a_full_battery():
    s = uas._Sim1(P, PRM, quiet, (10, 20), (0, 1, 2, 3))
    for name, shape in (("p", (3, 1)), ("v", (3, 1)), ("w", (3, 1)), ("om", (4, 1)), ("wind", (3, 1)), ("sf", (3, 1)), ("q", (4, 1))):
        assert getattr(s, name).shape == shape, name
    for name in ("p", "v", "w", "om", "wind"):
        assert not np.any(np.asarray(getattr(s, name))), name
    assert np.allclose(np.asarray(s.q)[:, 0], [math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]) and np.allclose(np.asarray(s.sf)[:, 0], [0.0, 0.0, uas.G0])
    assert s.soc.shape == s.qah.shape == s.ewh.shape == s.pe.shape == (1,) and float(s.soc[0]) == 1.0 and not np.any(np.asarray(s.qah))
    assert not np.any(np.asarray(s.ewh)) and not np.any(np.asarray(s.pe)) and np.array_equal(np.asarray(s.volt), np.asarray(PRM["vref"]))
    assert (s.t, s.k, s.tilt, s.pe_acc, s.n_acc, s.tilt_max) == (0.0, 0, 0.0, 0.0, 0, 0.0) and s.rec == [] and s.hist == [] and s.map == [0, 1, 2, 3]
    assert s.pos_en.dtype == np.float64 and list(s.pos_en) == [10.0, 20.0]
    assert np.allclose(s.rpy(), (0.0, 0.0, 0.0), atol=1e-6)                              # facing north is heading 0


# ---- _Sim1.step: pwm -> motors -----------------------------------------------------------------------------------------
def motor_speed_after_one_step(p, **kw):
    s = air(**kw)
    s.step(p)
    return np.asarray(s.om)[:, 0]


def test_pwm_1000_to_2000_is_zero_to_full_speed_through_a_33_ms_lag():
    om_max, lag = float(PRM["om_max"][0]), 1 - math.exp(-uas.DT_PHYS / float(PRM["tau_m"][0]))
    for us in (1100.0, 1250.0, 1500.0, 1750.0, 2000.0):
        assert motor_speed_after_one_step(pwm(us, us, us, us))[0] == pytest.approx((us - 1000.0) / 1000.0 * om_max * lag, rel=1e-5)
    assert np.all(motor_speed_after_one_step(pwm(500.0, 900.0, 1000.0, 1000.0)) == 0.0)                  # below 1000 us is zero, not reverse
    full = motor_speed_after_one_step(pwm(2000.0, 2000.0, 2000.0, 2000.0))
    assert np.allclose(motor_speed_after_one_step(pwm(2600.0, 3000.0, 2001.0, 9999.0)), full, rtol=1e-6)    # above 2000 us is full, not more


def test_the_motor_map_sends_each_servo_channel_to_its_motor():
    assert np.all(np.asarray(motor_speed_after_one_step(pwm(1000.0, 2000.0, 1000.0, 1000.0)))[[0, 2, 3]] == 0.0)
    assert motor_speed_after_one_step(pwm(1000.0, 2000.0, 1000.0, 1000.0))[1] > 200.0
    swapped = motor_speed_after_one_step(pwm(1000.0, 2000.0, 1000.0, 1000.0), motor_map=(1, 0, 2, 3))
    assert swapped[0] > 200.0 and np.all(swapped[1:] == 0.0)
    rolled = motor_speed_after_one_step(pwm(1000.0, 1000.0, 1000.0, 2000.0, 2000.0), motor_map=(3, 0, 1, 2))
    assert rolled[0] > 200.0 and np.all(rolled[1:] == 0.0)                                                  # only channels 0-3 are motors


def test_a_sagging_battery_lowers_motor_speed_in_proportion_and_a_high_one_does_not_raise_it():
    full = motor_speed_after_one_step(pwm(1500.0, 1500.0, 1500.0, 1500.0))
    for scale, want in ((0.5, 0.5), (0.8, 0.8), (1.0, 1.0), (1.5, 1.0), (2.0, 1.0)):
        s = air()
        s.volt = s.volt * scale
        s.step(pwm(1500.0, 1500.0, 1500.0, 1500.0))
        assert np.asarray(s.om)[:, 0] == pytest.approx(full * want, rel=1e-5)


def test_each_motor_gives_the_rate_it_should_roll_pitch_and_yaw_signs():
    """Motor 1 spins up: the quad rolls and pitches positive and yaws negative; motors 2 and 3 flip one sign each (X frame, ArduCopter layout)."""
    got = {}
    for m in range(4):
        s = air()
        for _ in range(40):
            s.step(pwm(*[2000.0 if i == m else 1000.0 for i in range(4)]))
        got[m] = np.sign(np.asarray(s.w)[:, 0])
    assert got[1].tolist() == [1, 1, -1] and got[2].tolist() == [1, -1, 1] and got[3].tolist() == [-1, 1, 1] and got[0].tolist() == [-1, -1, -1]


# ---- _Sim1.step: time, environment lookups, energy ---------------------------------------------------------------------
def test_free_fall_gains_g_times_t_and_the_clocks_run_at_2_5_ms_and_50_ms():
    s = air()
    for _ in range(100):
        s.step(IDLE)
    assert float(s.v[2, 0]) == pytest.approx(-uas.G0 * 0.25, rel=1e-5) and float(s.p[2, 0]) == pytest.approx(100.0 - 0.5 * uas.G0 * 0.25 ** 2, rel=1e-4)
    assert s.t == pytest.approx(100 * 0.0025) and s.k == 5 and s.n_acc == 0 and len(s.hist) == 5 and float(s.v[0, 0]) == 0.0
    assert np.allclose(np.asarray(s.sf)[:, 0], 0.0, atol=1e-5)                                            # a falling body feels no specific force
    assert s.tilt == 0.0 and s.tilt_max == 0.0
    ts = [h[0] for h in s.hist]
    assert ts == pytest.approx([0.05, 0.10, 0.15, 0.20, 0.25]) and all(len(h) == 4 for h in s.hist)


def test_wind_is_read_once_per_block_with_block_index_time_and_world_position():
    calls = []

    def wind(k, t, pos):
        calls.append((k, t, np.asarray(pos).copy()))
        return np.array([[3.0], [0.0], [0.0]])
    s = air(home=(10.0, 20.0), wind_fn=wind)
    for _ in range(45):
        s.step(IDLE)
    assert [c[0] for c in calls] == [0, 1, 2] and [c[1] for c in calls] == pytest.approx([0.0, 0.05, 0.10])
    assert np.allclose(calls[0][2][:, 0], [10.0, 20.0, 100.0]) and calls[0][2].shape == (3, 1) and calls[1][2][0, 0] > 10.0
    assert float(s.wind[0, 0]) == 3.0
    assert float(s.v[0, 0]) > 0.0                                                                         # a wind from the west pushes the airframe east
    moved = air(wind_fn=lambda k, t, pos: np.array([[0.0], [3.0], [0.0]]))
    for _ in range(45):
        moved.step(IDLE)
    assert float(moved.v[1, 0]) > 0.0 and float(moved.v[0, 0]) == pytest.approx(0.0, abs=1e-6)


def test_hotel_load_alone_draws_10_w_and_the_battery_obeys_power_balance():
    s = air()
    for _ in range(20):
        s.step(IDLE)
    assert float(s.pe[0]) == pytest.approx(10.0) and s.k == 1 and s.n_acc == 0 and s.pe_acc == 0.0
    assert float(s.ewh[0]) == pytest.approx(10.0 * 0.05 / 3600.0, rel=1e-5)                               # 10 W for 50 ms
    voc, rint, v = 6 * 4.2, float(PRM["rint"][0]), float(s.volt[0])
    assert v < voc and (voc - v) * v / rint == pytest.approx(10.0, rel=1e-3)                              # P = V I with V = Voc - I R
    assert 0.0 < 1.0 - float(s.soc[0]) < 1e-3 and float(s.qah[0]) > 0.0
    s2 = air()
    for _ in range(19):
        s2.step(IDLE)
    assert s2.n_acc == 19 and s2.k == 0 and float(s2.ewh[0]) == 0.0 and len(s2.hist) == 0                  # the battery waits for the 20th step
    assert s2.pe_acc == pytest.approx(190.0)


def test_thrust_costs_more_power_and_lifts():
    s = air()
    for _ in range(40):
        s.step(pwm(1800.0, 1800.0, 1800.0, 1800.0))
    assert float(s.pe[0]) > 100.0 and float(s.v[2, 0]) > 0.0 and float(s.ewh[0]) > 0.0
    assert float(s.soc[0]) < 1.0 and float(s.volt[0]) < 25.2 and s.t == pytest.approx(0.1)


def test_tilt_is_the_angle_between_body_z_and_vertical_and_tilt_max_keeps_the_peak():
    a = math.radians(30) / 2
    s = air(q=[[math.cos(a)], [math.sin(a)], [0.0], [0.0]])
    s.step(IDLE)
    assert s.tilt == pytest.approx(math.radians(30), abs=1e-5) and s.tilt_max == s.tilt
    s.q = jnp.asarray(LEVEL)
    s.step(IDLE)
    assert s.tilt == pytest.approx(0.0, abs=1e-6) and s.tilt_max == pytest.approx(math.radians(30), abs=1e-5)
    b = math.radians(60) / 2
    t = air(q=[[math.cos(b)], [0.0], [math.sin(b)], [0.0]])
    t.step(IDLE)
    assert t.tilt == pytest.approx(math.radians(60), abs=1e-5)


# ---- _Sim1.rpy and reply -----------------------------------------------------------------------------------------------
def ned_frd_quaternion(roll, pitch, yaw):
    """The ENU/FLU quaternion (w, x, y, z) whose attitude in NED/FRD is the aerospace roll-pitch-yaw (3-2-1): R_enu_flu = C R_ned_frd B."""
    r_ned_frd = Rotation.from_euler("ZYX", [yaw, pitch, roll]).as_matrix()
    c, b = np.array([[0.0, 1, 0], [1, 0, 0], [0, 0, -1]]), np.diag([1.0, -1, -1])
    x, y, z, w = Rotation.from_matrix(c @ r_ned_frd @ b).as_quat()
    return np.array([w, x, y, z])


@pytest.mark.parametrize("rpy", [(0.0, 0.0, 0.0), (0.3, -0.2, 1.1), (-0.5, 0.4, -2.0), (1.0, 0.1, 3.0), (-0.2, -0.6, 0.5), (0.1, 0.7, -1.4)])
def test_rpy_returns_the_ned_frd_euler_angles_it_was_built_from(rpy):
    s = air(q=ned_frd_quaternion(*rpy)[:, None])
    got = s.rpy()
    wrap = lambda a: (a + math.pi) % (2 * math.pi) - math.pi
    assert wrap(got[0] - rpy[0]) == pytest.approx(0.0, abs=1e-5)
    assert got[1] == pytest.approx(rpy[1], abs=1e-5)
    assert wrap(got[2] - rpy[2]) == pytest.approx(0.0, abs=1e-5)
    assert all(isinstance(g, float) for g in got)


@pytest.mark.parametrize("pitch", [math.pi / 2, -math.pi / 2])
def test_rpy_clamps_a_pitch_that_float_error_pushes_past_vertical(pitch):
    q = ned_frd_quaternion(0.2, pitch, 0.3) * 1.001                                    # |q| slightly above 1: sin(pitch) = 1.002
    assert air(q=q[:, None]).rpy()[1] == pytest.approx(pitch, abs=1e-6)


def test_reply_is_the_state_in_ned_frd_with_the_clock_and_the_battery():
    s = air()
    s.t = 1.25
    s.p, s.v, s.w, s.sf = (jnp.asarray(x)[:, None] for x in ([3.0, 4.0, 5.0], [1.0, 2.0, 3.0], [0.1, 0.2, 0.3], [0.5, 0.6, uas.G0]))
    s.volt, s.pe = jnp.array([20.0]), jnp.array([100.0])
    j = __import__("json").loads(s.reply())
    assert j["timestamp"] == 1.25 and j["battery"] == {"voltage": 20.0, "current": 5.0}
    assert j["position"] == [4.0, 3.0, -5.0] and j["velocity"] == [2.0, 1.0, -3.0]
    assert np.allclose(j["imu"]["gyro"], [0.1, -0.2, -0.3]) and np.allclose(j["imu"]["accel_body"], [0.5, -0.6, -uas.G0], atol=1e-5)
    assert np.allclose(j["quaternion"], np.array([0.0, 0.0, 0.0, 0.0]) + uas._qm(uas._qm(uas._QC, np.asarray(s.q, float)[:, 0]), uas._QB))
    assert s.reply().endswith(b"\n")
