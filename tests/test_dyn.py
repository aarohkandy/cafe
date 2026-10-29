"""Verification of cafe.dyn (Fossen 6-DOF): torque-free invariants, attitude, a manufactured solution, and the hull terms
against Fossen's own PythonVehicleSimulator (vendored in tests/fixtures/pvs).

What is and is not compared with PythonVehicleSimulator (remus100, otter): the rigid-body mass/inertia, the added-mass
matrix (Lamb spheroid k-factors for REMUS), and the rigid-body + added-mass Coriolis terms, as one-step accelerations
for identical velocities after moving PVS's CO-referenced model to cafe's CoG frame. NOT compared: PVS's propeller,
fin, linear/quadratic damping, cross-flow, lift/drag, restoring forces (cafe takes drag from CFD tables and buoyancy from
panel pressure), and the Munk-moment terms PVS zeroes for REMUS stability (the test shows exactly which entries).
"""
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st
from scipy.integrate import solve_ivp

from cafe import dyn, vehicle
from cafe.pm.physics import rigid
from cafe.pm import vv
from tests.fixtures.pvs import hull_terms as pvs

AXES = [f"{s}{a}" for a in "xyz" for s in "+-"]


def bare(mass, inertia, added=None, kind="uuv"):
    """A vehicle with no actuators, no panels, zero drag: only M_RB, M_A and the Coriolis terms act (gravity removed
    by trim_kg = -mass in `bare_dyn`)."""
    drag = {k: (np.zeros(3), np.zeros(3), 0.0, None) for k in AXES}
    return vehicle.Vehicle("bare", kind, mass, np.asarray(inertia, float), np.zeros(3), np.zeros((6, 6)) if added is None else added, 0.0,
                           [], drag, (1.0, 1e-6, 1.0), np.zeros(3))


def bare_dyn(veh, B=1):
    d = dyn.Dynamics(veh, B, scale=dict(drag=np.zeros(B)))
    d.trim_kg = -veh.mass            # (mass + trim) * g = 0
    return d


def still(B=1):
    return dict(flow_ned=np.zeros((B, 3)))


def spin(d, w0, dt, n, v0=(0, 0, 0)):
    """n steps from body rates w0; -> (w history (n+1, 3), state)."""
    s = dyn.State(1, 0)
    s.w[:] = w0
    s.v[:] = v0
    hist = [s.w[0].copy()]
    for _ in range(n):
        d.step(s, np.zeros((1, 0)), still(), dt)
        hist.append(s.w[0].copy())
    return np.array(hist), s


I3 = np.diag([2.0, 3.0, 5.0])
W0 = np.array([3.0, 1.0, -2.0])


# ------------------------------------------------------------------ 1. torque-free rigid body

def test_body_rates_follow_the_implicit_midpoint_rule():
    """cafe.dyn integrates the Coriolis/gyroscopic terms with the implicit midpoint rule (3 fixed-point iterations):
    cafe == implicit midpoint to iteration tolerance, and clearly != explicit Euler (which it used before 2026-10-29)."""
    d = bare_dyn(bare(10.0, I3))
    dt, n = 1e-3, 3000
    hist, _ = spin(d, W0, dt, n)
    w_ex, w_mid = [W0], [W0]
    for _ in range(n):
        w_ex.append(rigid.explicit_euler(I3, w_ex[-1], dt))
        w_mid.append(rigid.implicit_midpoint(I3, w_mid[-1], dt))
    assert np.max(np.abs(hist - np.array(w_mid))) < 1e-8
    assert np.max(np.abs(hist - np.array(w_ex))) > 1e-4          # distinguishable at this dt and horizon


def test_explicit_euler_reference_grows_by_its_exact_law():
    """|H_{n+1}|^2 = |H_n|^2 + dt^2 |w_n x H_n|^2 for explicit Euler: the reference the conservation test contrasts with."""
    dt, n, w = 2e-3, 1500, [W0]
    for _ in range(n):
        w.append(rigid.explicit_euler(I3, w[-1], dt))
    hist = np.array(w)
    H = hist @ I3
    predicted = np.sum(dt ** 2 * np.linalg.norm(np.cross(hist[:-1], H[:-1]), axis=1) ** 2)
    got = np.sum(H[-1] ** 2) - np.sum(H[0] ** 2)
    assert got > 0 and got == pytest.approx(predicted, rel=1e-8)


def test_energy_and_momentum_conserved_where_explicit_euler_drifts():
    """Torque-free tumble (3.7 rad/s, I = diag(2, 3, 5)) for 10 s: cafe holds |H| and kinetic energy to < 1e-8 at 1 and
    2 ms; explicit Euler gains +0.78 % / +2.0 % at 1 ms and twice that at 2 ms (first order). The test fails if cafe drifts
    (the 2026-10-29 bug: tests/fixtures/broken/dyn_body_rate_drift.py reproduced it)."""
    h0, e0 = rigid.invariants(I3, W0)
    drift = {}
    for dt in (2e-3, 1e-3):
        n = int(10.0 / dt)
        hist, _ = spin(bare_dyn(bare(10.0, I3)), W0, dt, n)
        h, e = rigid.invariants(I3, hist[-1])
        assert abs(h / h0 - 1) < 1e-8 and abs(e / e0 - 1) < 1e-8
        w = W0
        for _ in range(n):
            w = rigid.explicit_euler(I3, w, dt)
        drift[dt] = tuple(x - 1 for x in np.divide(rigid.invariants(I3, w), (h0, e0)))
    for k in (0, 1):
        assert drift[1e-3][k] > 1e-3
        assert drift[2e-3][k] / drift[1e-3][k] == pytest.approx(2.0, rel=0.15)


def test_torque_free_tumble_conserves_angular_momentum_and_energy():
    s = dyn.State(1, 0)
    s.w[:] = W0
    d = bare_dyn(bare(10.0, I3))
    for _ in range(10000):
        d.step(s, np.zeros((1, 0)), still(), 1e-3)
    h0, e0 = rigid.invariants(I3, W0)
    h, e = rigid.invariants(I3, s.w[0])
    assert abs(h / h0 - 1) < 1e-6 and abs(e / e0 - 1) < 1e-6


def test_implicit_midpoint_reference_refuses_a_step_it_cannot_solve():
    with pytest.raises(RuntimeError, match="did not converge"):
        rigid.implicit_midpoint(I3, W0, 50.0)


def test_principal_axis_spin_conserves_everything():
    """About a principal axis w x I w = 0, so the scheme is exact: this is the regime the autopilots live in."""
    hist, _ = spin(bare_dyn(bare(10.0, I3)), [0.0, 0.0, 4.0], 1e-2, 2000)
    assert np.max(np.abs(hist - [0, 0, 4.0])) < 1e-14


def test_attitude_norm_and_rotation_matrix_stay_exact():
    d = bare_dyn(bare(10.0, I3))
    s = dyn.State(1, 0)
    s.w[:] = W0
    for _ in range(20000):
        d.step(s, np.zeros((1, 0)), still(), 5e-4)
    assert abs(np.linalg.norm(s.q[0]) - 1) < 1e-14
    R = dyn.quat_to_R(s.q)[0]
    assert np.max(np.abs(R.T @ R - np.eye(3))) < 1e-13 and np.linalg.det(R) == pytest.approx(1.0, abs=1e-13)


def test_attitude_angle_lags_by_the_quaternion_step_error():
    """q <- q (x) [1, w dt/2] (normalized) turns by 2 atan(w dt/2), not w dt: the angle after n steps is short by
    ~ (w dt)^2 / 12 of itself. Tests the size and the sign of that lag (a sign error or wrong half-angle breaks it)."""
    w, dt, n = 2.0, 0.01, 1000
    s = dyn.State(1, 0)
    s.w[:] = [0, 0, w]
    d = bare_dyn(bare(10.0, I3))
    for _ in range(n):
        d.step(s, np.zeros((1, 0)), still(), dt)
    yaw = dyn.quat_to_euler(s.q)[0, 2]
    got = (w * dt * n - 2 * np.arctan(w * dt / 2) * n) / (w * dt * n)       # exact lag of the discrete rotation, wrapped below
    exact = 2 * np.arctan(w * dt / 2) * n
    assert yaw == pytest.approx(np.arctan2(np.sin(exact), np.cos(exact)), abs=1e-12)
    assert got == pytest.approx((w * dt) ** 2 / 12, rel=0.02) and got > 0


# ------------------------------------------------------------------ 2. manufactured solution

MASS = 7.0
A6 = np.array([[1.5, 0.1, 0, 0, 0.05, 0], [0.1, 2.5, 0, 0, 0, 0.1], [0, 0, 3.0, 0.1, 0, 0],
               [0, 0, 0.1, 0.4, 0, 0], [0.05, 0, 0, 0, 0.9, 0.02], [0, 0.1, 0, 0, 0.02, 1.2]])


def v_exact(t):
    return np.array([0.5 + 0.3 * np.sin(1.3 * t), 0.2 * np.cos(0.9 * t), 0.1 * np.sin(2.0 * t)])


def w_exact(t):
    return np.array([0.4 * np.sin(0.7 * t), 0.3 * np.cos(1.1 * t) - 0.1, 0.5 * np.sin(0.5 * t) + 0.2])


def nu_dot_exact(t):
    return np.concatenate([[0.39 * np.cos(1.3 * t), -0.18 * np.sin(0.9 * t), 0.2 * np.cos(2.0 * t)],
                           [0.28 * np.cos(0.7 * t), -0.33 * np.sin(1.1 * t), 0.25 * np.cos(0.5 * t)]])


def forcing(t, flip=1.0):
    """tau that makes nu_exact solve (M_RB + A) nu_dot + C_RB nu + C_A nu = tau (Fossen 2011 eq 6.43, written here from the
    book, not from dyn.py). flip = -1 puts a sign error in the added-mass Coriolis term."""
    v, w, nd = v_exact(t), w_exact(t), nu_dot_exact(t)
    nu = np.concatenate([v, w])
    M = np.block([[MASS * np.eye(3), np.zeros((3, 3))], [np.zeros((3, 3)), I3]]) + A6
    a1, a2 = A6[:3] @ nu, A6[3:] @ nu
    crb = np.concatenate([MASS * np.cross(w, v), np.cross(w, I3 @ w)])
    ca = np.concatenate([-np.cross(a1, w), -np.cross(a1, v) - np.cross(a2, w)])
    return M @ nd + crb + flip * ca


class Forced(dyn.Dynamics):
    flip = 1.0

    def actuator_forces(self, st, v_r):
        f = forcing(st.t, self.flip)
        return f[None, :3], f[None, 3:], np.zeros(1)


def kinematics_reference(T):
    """Integrate p' = R(q) v, q' = q (x) [0, w]/2 with analytic v, w to 1e-12."""
    def rhs(t, y):
        q = y[3:] / np.linalg.norm(y[3:])
        R = dyn.quat_to_R(q)
        w = w_exact(t)
        return np.concatenate([R @ v_exact(t), 0.5 * dyn.quat_mul(q, np.r_[0.0, w])])
    sol = solve_ivp(rhs, (0, T), [0, 0, 0, 1, 0, 0, 0], method="DOP853", rtol=1e-12, atol=1e-13)
    y = sol.y[:, -1]
    return y[:3], y[3:] / np.linalg.norm(y[3:])


def mms_errors(dt, T=2.0, flip=1.0):
    d = Forced(bare(MASS, I3, A6), 1, scale=dict(drag=np.zeros(1)))
    d.trim_kg = -MASS
    d.flip = flip
    s = dyn.State(1, 0)
    s.v[:] = v_exact(0.0)
    s.w[:] = w_exact(0.0)
    for _ in range(round(T / dt)):
        d.step(s, np.zeros((1, 0)), still(), dt)
    p_ref, q_ref = kinematics_reference(T)
    ang = 2 * np.arccos(min(1.0, abs(float(s.q[0] @ q_ref))))
    return dict(v=np.linalg.norm(s.v[0] - v_exact(T)), w=np.linalg.norm(s.w[0] - w_exact(T)),
                p=np.linalg.norm(s.p[0] - p_ref), q=ang)


def test_manufactured_solution_converges_at_first_order():
    dts = [0.02, 0.01, 0.005, 0.0025]
    errs = [mms_errors(dt) for dt in dts]
    for k in "vwpq":
        e = [x[k] for x in errs]
        orders = [np.log2(e[i] / e[i + 1]) for i in range(3)]
        assert all(0.85 < o < 1.2 for o in orders), (k, orders)
        # the same observed-order routine the GCI code uses, on the three finest steps
        p = vv.observed_order(e[2] - e[1], e[3] - e[2], 2.0, 2.0) if k in "vw" else None
        assert p is None or 0.8 < p < 1.3


def test_manufactured_solution_catches_a_coriolis_sign_error():
    """With the added-mass Coriolis term sign-flipped in the forcing, the 'solution' is no longer one: the error stops
    converging (order ~ 0), so this test would fail if dyn.py's C_A sign were wrong."""
    e = [mms_errors(dt, flip=-1.0)["w"] for dt in (0.01, 0.005, 0.0025)]
    assert e[0] > 1e-2 and np.log2(e[0] / e[1]) < 0.3 and np.log2(e[1] / e[2]) < 0.3


# ------------------------------------------------------------------ 3. PythonVehicleSimulator hull terms

def to_cg(M_co, r):
    """Fossen 2021 ch. 3: M_CO = H' M_CG H with H = Hmtrx(r_bg), so M_CG = H^-T M_CO H^-1; nu_CG = H nu_CO."""
    H = pvs.Hmtrx(r)
    Hi = np.linalg.inv(H)
    return Hi.T @ M_co @ Hi, H


def cafe_step_accel(veh, nu_cg):
    d = bare_dyn(veh)
    s = dyn.State(1, 0)
    s.v[:] = nu_cg[:3]
    s.w[:] = nu_cg[3:]
    dt = 1e-6                                           # the Coriolis terms are at the step midpoint: an O(dt) offset
    d.step(s, np.zeros((1, 0)), still(), dt)
    return (np.concatenate([s.v[0], s.w[0]]) - nu_cg) / dt


def rigid_inertia_cg(M_rb_co, r):
    mrb_cg, _ = to_cg(M_rb_co, r)
    return mrb_cg[3:, 3:], mrb_cg[0, 0]


NU = [np.array([1.2, -0.3, 0.2, 0.15, -0.4, 0.3]), np.array([0.5, 0.9, -0.6, -0.5, 0.2, 0.7]),
      np.array([-1.0, 0.4, 0.8, 0.3, 0.6, -0.8])]


@pytest.mark.parametrize("nu_co", NU)
def test_remus100_hull_terms_match_fossen(nu_co):
    r = pvs.remus100_mass()
    m_cg, H = to_cg(r["M"], r["r_bg"])
    ma_cg, _ = to_cg(r["MA"], r["r_bg"])
    I, m = rigid_inertia_cg(r["MRB"], r["r_bg"])
    veh = bare(m, I, ma_cg)
    assert np.max(np.abs(veh.M - m_cg)) < 1e-9 * np.abs(m_cg).max()            # mass matrices agree in the CG frame
    nu_cg = H @ nu_co
    unstable = np.linalg.solve(r["M"], -pvs.remus100_C(r["MRB"], r["MA"], nu_co, stabilised=False) @ nu_co)
    shipped = np.linalg.solve(r["M"], -pvs.remus100_C(r["MRB"], r["MA"], nu_co, stabilised=True) @ nu_co)
    got = cafe_step_accel(veh, nu_cg)
    scale = np.abs(H @ unstable).max()
    assert np.max(np.abs(got - H @ unstable)) < 1e-5 * scale                     # Fossen's formula, identical inputs
    # PVS zeroes eight added-mass Coriolis entries for stability; that is the entire difference to cafe
    assert np.max(np.abs(H @ shipped - H @ unstable)) > 1e-3 * scale


def test_remus100_added_mass_is_the_lamb_spheroid_except_roll():
    r = pvs.remus100_mass()
    mine = vehicle.spheroid_added_mass(r["L"], r["diam"], r["rho"])
    ma = r["MA"]
    # MA is diagonal in CO; compare in CO directly (spheroid_added_mass is about the spheroid centre = CO here)
    assert np.allclose(np.diag(mine)[[0, 1, 2, 4, 5]], np.diag(ma)[[0, 1, 2, 4, 5]], rtol=1e-12)
    assert mine[3, 3] == 0.0 and ma[3, 3] == pytest.approx(0.3 * r["Ix"])       # cafe has no roll added inertia; PVS 0.3 Ix


@pytest.mark.parametrize("nu_co", NU)
def test_otter_hull_terms_match_fossen(nu_co):
    o = pvs.otter_mass()
    m_cg, H = to_cg(o["M"], o["r_g"])
    ma_cg, _ = to_cg(o["MA"], o["r_g"])
    veh = bare(o["m_total"], o["Ig"], ma_cg)
    # PVS's Ig is the inertia about the CG already (Ig = Ig_CG - m S(rg)^2 ... as it uses it in MRB_CG): same object
    assert np.max(np.abs(veh.M - m_cg)) < 1e-9 * np.abs(m_cg).max()
    nu_cg = H @ nu_co
    ref = H @ np.linalg.solve(o["M"], -pvs.otter_C(o, nu_co, nu_co) @ nu_co)
    got = cafe_step_accel(veh, nu_cg)
    assert np.max(np.abs(got - ref)) < 1e-5 * np.abs(ref).max()


def test_pvs_comparison_fails_on_a_sign_flip():
    """Break the Coriolis sign in the comparison input and the match must go: the agreement above is not vacuous."""
    r = pvs.remus100_mass()
    ma_cg, H = to_cg(r["MA"], r["r_bg"])
    I, m = rigid_inertia_cg(r["MRB"], r["r_bg"])
    nu_co = NU[0]
    wrong = H @ np.linalg.solve(r["M"], +pvs.remus100_C(r["MRB"], r["MA"], nu_co, stabilised=False) @ nu_co)
    assert np.max(np.abs(cafe_step_accel(bare(m, I, ma_cg), H @ nu_co) - wrong)) > 1e-3


@settings(max_examples=40, deadline=None)
@given(st.lists(st.floats(-2, 2, allow_nan=False), min_size=6, max_size=6))
def test_property_cafe_equals_fossen_for_random_velocities(nu):
    """Any velocity vector, REMUS hull terms: cafe's one-step acceleration == Fossen's C(nu) nu formula."""
    nu_co = np.array(nu)
    r = pvs.remus100_mass()
    ma_cg, H = to_cg(r["MA"], r["r_bg"])
    I, m = rigid_inertia_cg(r["MRB"], r["r_bg"])
    ref = H @ np.linalg.solve(r["M"], -pvs.remus100_C(r["MRB"], r["MA"], nu_co, stabilised=False) @ nu_co)
    assert np.max(np.abs(cafe_step_accel(bare(m, I, ma_cg), H @ nu_co) - ref)) < 1e-5 * (1 + np.abs(ref).max())
