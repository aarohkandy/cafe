"""Built-in autopilots for fast mode, cascaded like ArduPilot's, gains derived from each vehicle's
own mass/inertia so any uploaded design gets a sane controller without hand tuning.

Families:
  multirotor  position -> velocity -> thrust vector -> attitude (geometric, Lee et al. 2010) -> rates -> mix
  steered     boats and finned torpedoes: point along the required water-relative velocity, surge/heading/pitch loops
  holonomic   vectored ROVs: direct 6-DOF force allocation, attitude held level
The controller sees ground velocity (GPS/DVL bottom-track) and speed through the fluid (DVL water-
track / pitot), i.e. it can measure the current but not the future.
"""
import numpy as np
from cafe.dyn import quat_to_R, quat_to_euler, bmtv, bmv
from cafe.vehicle import RHO, G, prop_perf

TILT_MAX = np.radians(35)


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


def family(veh):
    if veh.kind == "uav":
        return "multirotor"
    if any(a.kind == "buoy" for a in veh.actuators):
        return "glider"
    if veh.kind == "uuv" and sum(a.kind == "prop" for a in veh.actuators) >= 5:
        return "holonomic"
    return "steered"


class Autopilot:
    def __init__(self, veh, dyn, B):
        self.veh, self.dyn, self.B = veh, dyn, B
        self.fam = family(veh)
        M = veh.M
        self.m_eff = np.diag(M)[:3]
        self.I_eff = np.diag(M)[3:]
        # bandwidths (rad/s); position < velocity < attitude < rate
        bw = dict(multirotor=(0.8, 2.0, 6.0, 25.0), steered=(0.15, 0.5, 1.0, 3.0), holonomic=(0.3, 0.8, 2.0, 6.0),
                  glider=(0.05, 0.2, 0.4, 1.0))[self.fam]
        self.kp, self.kv, self.katt, self.krate = bw
        self.ki = 0.1 * self.kv
        self.vint = np.zeros((B, 3))
        self.uint = np.zeros(B)
        self.v_cruise = np.full(B, cruise_speed(veh))
        self.v_max = max_speed(veh)
        # a finned sub must never slow below fin-control speed (it would float up); real AUVs don't stop
        self.v_floor = fin_trim_speed(veh) if (veh.kind == "uuv" and family(veh) == "steered") else 0.0

    # -------------------------------------------------------------- guidance

    def velocity_cmd(self, p, target, v_cap, accel=None):
        """ArduPilot-style sqrt controller: approach at v_cap, decelerate to stop on the target."""
        e = target - p
        if self.veh.kind == "usv" or self.fam == "glider":
            e[:, 2] = 0            # boats stay on the surface; gliders run their own depth saw-tooth
        d = np.linalg.norm(e, axis=1)
        a = accel or (0.25 * self.v_max if self.fam != "multirotor" else 2.5)
        eh = np.linalg.norm(e[:, :2], axis=1)
        sh = np.minimum(np.minimum(v_cap, np.sqrt(2 * a * eh)), self.kp * eh * 4)
        v = np.zeros_like(e)
        v[:, :2] = e[:, :2] / np.maximum(eh, 1e-6)[:, None] * sh[:, None]
        # vertical as its own channel (dive/climb to the target level now, not along a glide slope)
        vz_max = 3.0 if self.veh.kind == "uav" else 0.3 * self.v_max
        v[:, 2] = np.clip(self.kp * 2 * e[:, 2], -vz_max, vz_max)
        return v, d

    # -------------------------------------------------------------- control

    def __call__(self, st, v_des_ned, flow_ned, dt, yaw_des=None):
        R = quat_to_R(st.q)
        v_ned = bmv(R, st.v)
        if self.fam == "multirotor":
            return self._multirotor(st, R, v_ned, v_des_ned, flow_ned, dt, yaw_des)
        if self.fam == "holonomic":
            return self._holonomic(st, R, v_ned, v_des_ned, flow_ned, dt)
        if self.fam == "glider":
            return self._glider(st, R, v_ned, v_des_ned, flow_ned, dt)
        return self._steered(st, R, v_ned, v_des_ned, flow_ned, dt)

    def _vel_loop(self, v_ned, v_des, dt):
        err = v_des - v_ned
        self.vint = np.clip(self.vint + err * dt, -10 / self.ki, 10 / self.ki)   # up to 10 m/s2, like PSC_*_IMAX
        return self.kv * err + self.ki * self.vint

    def _multirotor(self, st, R, v_ned, v_des, flow, dt, yaw_des):
        veh = self.veh
        acc = self._vel_loop(v_ned, v_des, dt)
        # feed-forward the body drag at the current airspeed, so wind is fought, not just integrated
        v_rel = st.v - bmtv(R, flow)
        Fd, _ = self.dyn.drag(v_rel)
        from cafe.dyn import ROTOR_DRAG
        Fd[:, :2] -= ROTOR_DRAG * veh.mass * G * v_rel[:, :2]          # rotor drag at ~hover thrust
        f = veh.mass * (acc - [0, 0, G]) - bmv(R, Fd)
        # tilt limit: keep vertical component, shrink horizontal
        fh = np.linalg.norm(f[:, :2], axis=1)
        lim = np.abs(f[:, 2]) * np.tan(TILT_MAX)
        f[:, :2] *= np.minimum(1, lim / np.maximum(fh, 1e-9))[:, None]
        T = np.linalg.norm(f, axis=1)
        zb = -f / T[:, None]                       # desired body z (down) axis in NED
        yaw = quat_to_euler(st.q)[:, 2] if yaw_des is None else yaw_des
        xc = np.stack([np.cos(yaw), np.sin(yaw), np.zeros_like(yaw)], 1)
        yb = np.cross(zb, xc); yb /= np.linalg.norm(yb, axis=1, keepdims=True)
        xb = np.cross(yb, zb)
        Rd = np.stack([xb, yb, zb], 2)
        eR = 0.5 * _vee(np.einsum("bji,bjk->bik", Rd, R) - np.einsum("bji,bjk->bik", R, Rd))
        w_des = -self.katt * eR
        tau = self.I_eff * self.krate * (w_des - st.w) + np.cross(st.w, st.w @ veh.inertia.T)
        T_body = T * np.einsum("bi,bi->b", -R[:, :, 2], -zb)   # thrust along current body -z
        return self._mix_multirotor(np.maximum(T_body, 0), tau)

    def _mix_multirotor(self, T, tau):
        acts = self.veh.actuators
        tm = np.array([a.tmax for a in acts]); qm = np.array([a.qmax for a in acts])
        pos = np.array([a.pos for a in acts]); spin = np.array([a.spin for a in acts], float)
        # per unit s_i = u_i^2. An upward force (0,0,-T) at (x,y,z): M = r x F = (-y T, x T, 0).
        # Reaction torque -spin*Q*dir with dir = (0,0,-1) is +spin*Q about body z (CCW rotor -> yaw right,
        # same as ArduPilot's AP_MOTORS_MATRIX_YAW_FACTOR_CCW = +1).
        Bm = np.vstack([tm, -pos[:, 1] * tm, pos[:, 0] * tm, spin * qm])
        Binv = np.linalg.pinv(Bm)
        want = np.column_stack([T, tau])
        s = want @ Binv.T
        # yaw is lowest priority: if anything saturates, retry without yaw demand
        bad = (s < 0).any(1) | (s > 1).any(1)
        if bad.any():
            w2 = want.copy(); w2[bad, 3] *= 0.2
            s[bad] = w2[bad] @ Binv.T
        s = np.clip(s, 0, 1)
        return self._power_cap(np.sqrt(s))

    def _steered(self, st, R, v_ned, v_des, flow, dt):
        veh = self.veh
        w_des = v_des - flow                            # water-relative velocity we need (NED)
        if veh.kind == "usv":
            w_des[:, 2] = 0
        sp_h = np.linalg.norm(w_des[:, :2], axis=1)
        eul = quat_to_euler(st.q)
        psi_d = np.where(sp_h > 0.05, np.arctan2(w_des[:, 1], w_des[:, 0]), eul[:, 2])
        u_d = np.minimum(np.linalg.norm(w_des, axis=1), self.v_max)
        # don't drive hard while pointing the wrong way (boats turn on the spot first)
        ang = wrap(psi_d - eul[:, 2])
        u_d *= np.clip(np.cos(ang), 0, 1) ** 2
        u_d = np.maximum(u_d, self.v_floor)
        tau = np.zeros((self.B, 6))
        Fd, _ = self.dyn.drag(np.column_stack([u_d, np.zeros((self.B, 2))]))
        v_rel = st.v - bmtv(R, flow)
        self.uint = np.clip(self.uint + (u_d - v_rel[:, 0]) * dt, -3, 3)
        tau[:, 0] = -Fd[:, 0] + self.m_eff[0] * (self.kv * (u_d - v_rel[:, 0]) + 0.2 * self.kv * self.uint)
        r_d = np.clip(self.katt * ang, -0.6, 0.6)
        tau[:, 5] = self.I_eff[2] * self.krate * (r_d - st.w[:, 2])
        if veh.kind == "uuv":
            # A bare torpedo is pitch-unstable (Munk moment outgrows passive fin lift), and fins only work at
            # speed: dive/climb authority ramps in with forward speed, and pitch moves gently, like real
            # AUV autopilots. Diving hard from a standstill saturates the fins and tumbles the vehicle.
            ramp = np.clip((v_rel[:, 0] - 0.5 * self.v_floor) / max(0.5 * self.v_floor, 1e-3), 0, 1) if self.v_floor else 1.0
            th_d = ramp * np.clip(np.arctan2(-w_des[:, 2], np.maximum(sp_h, 0.1)), -0.35, 0.35)
            q_d = np.clip(self.katt * (th_d - eul[:, 1]), -0.15, 0.15)
            tau[:, 4] = self.I_eff[1] * self.krate * (q_d - st.w[:, 1])
            tau[:, 3] = self.I_eff[0] * self.krate * (self.katt * -eul[:, 0] - st.w[:, 0])
        return self._allocate(tau, v_rel, dofs=[0, 3, 4, 5] if veh.kind == "uuv" else [0, 5])

    # glider: saw-tooth between a top and bottom depth, buoyancy sets dive/climb, the moving battery holds the
    # glide pitch, the rudder steers along the water-relative course that makes good the wanted track
    GLIDE = np.radians(26)

    def set_band(self, top, bottom):
        self.band = (float(top), float(bottom))

    def _glider(self, st, R, v_ned, v_des, flow, dt):
        acts = self.veh.actuators
        top, bottom = getattr(self, "band", (5.0, 100.0))
        if not hasattr(self, "diving"):
            self.diving = np.ones(self.B, bool)
        z = st.p[:, 2]
        self.diving = np.where(z >= bottom, False, np.where(z <= top, True, self.diving))
        eul = quat_to_euler(st.q)
        th_d = np.where(self.diving, -self.GLIDE, self.GLIDE)
        e = th_d - eul[:, 1]
        # moving mass forward (u>0) pitches the nose down
        u_mass = np.clip(-(2.0 * e - 1.5 * st.w[:, 1]), -1, 1)
        u_buoy = np.where(self.diving, -1.0, 1.0)
        w_des = v_des - flow
        psi_d = np.arctan2(w_des[:, 1], w_des[:, 0])
        r_d = np.clip(self.katt * wrap(psi_d - eul[:, 2]), -0.1, 0.1)
        tau = np.zeros((self.B, 6))
        tau[:, 5] = self.I_eff[2] * self.krate * (r_d - st.w[:, 2])
        v_rel = st.v - bmtv(R, flow)
        u = self._allocate(tau, v_rel, dofs=[5])
        for i, a in enumerate(acts):
            if a.kind == "buoy":
                u[:, i] = u_buoy
            elif a.kind == "mass":
                u[:, i] = u_mass
        return u

    def _holonomic(self, st, R, v_ned, v_des, flow, dt):
        acc = self._vel_loop(v_ned, v_des, dt)
        v_rel = st.v - bmtv(R, flow)
        Fd, _ = self.dyn.drag(v_rel)
        net_down = (self.veh.mass - RHO["water"] * self.veh.volume) * G    # weight minus buoyancy, NED +z
        F_body = bmtv(R, acc) * self.m_eff - Fd - bmtv(R, np.broadcast_to([0, 0, net_down], acc.shape))
        eul = quat_to_euler(st.q)
        sp_h = np.linalg.norm(v_des[:, :2], axis=1)
        cur = np.linalg.norm(flow[:, :2], axis=1)
        # transiting: nose along the track. Near the target: nose into the current (least drag), and never
        # chase the target's bearing, which flips 180 deg every time the vehicle drifts past it
        into = np.arctan2(-flow[:, 1], -flow[:, 0])
        psi_d = np.where(sp_h > 0.5 * self.v_cruise, np.arctan2(v_des[:, 1], v_des[:, 0]),
                         np.where(cur > 0.05, into, eul[:, 2]))
        att_err = np.column_stack([-eul[:, 0], -eul[:, 1], wrap(psi_d - eul[:, 2])])
        Mt = self.I_eff * self.krate * (self.katt * att_err - st.w)
        return self._allocate(np.column_stack([F_body, Mt]), v_rel, dofs=[0, 1, 2, 3, 4, 5], moments_first=True)

    # -------------------------------------------------------------- allocation

    def _allocate(self, tau, v_rel, dofs, moments_first=False):
        """Bounded pseudo-inverse over the requested DOFs. Props in s=u|u| space, fins in deflection."""
        acts = self.veh.actuators
        n = len(acts)
        Bm = np.zeros((self.B, 6, n))
        rho = RHO[self.veh.fluid]
        lo, hi = np.zeros(n), np.ones(n)
        for i, a in enumerate(acts):
            if a.passive or a.kind in ("buoy", "mass"):
                lo[i] = hi[i] = 0.0            # wings, pump and moving mass aren't allocated here
                continue
            if a.kind == "prop":
                f = a.tmax * a.dir
                Bm[:, :3, i] = f
                Bm[:, 3:, i] = np.cross(a.pos, f) - a.spin * a.qmax * a.dir
                lo[i] = -a.rev
            else:
                q = 0.5 * rho * np.maximum(v_rel[:, 0], 0.05) ** 2
                f = (q * a.area * min(a.cla * a.dmax, 1.2))[:, None] * a.dir
                Bm[:, :3, i] = f
                Bm[:, 3:, i] = np.cross(a.pos, f)
                lo[i] = -1
        Bd = Bm[:, dofs, :]
        # normalize rows so force and moment DOFs are comparable
        scale = np.maximum(np.abs(Bd).max(2, keepdims=True), 1e-9)
        P = np.linalg.pinv(Bd / scale)
        want = tau[:, dofs] / scale[..., 0]
        if moments_first:
            # attitude before translation: solve the moments alone, then add as much of the force demand as
            # still fits the actuator limits (clipping thrusters one by one otherwise loses the moment balance)
            mrow = np.array([d >= 3 for d in dofs])
            sm = np.einsum("bij,bj->bi", P, np.where(mrow, want, 0.0))
            sf = np.einsum("bij,bj->bi", P, np.where(mrow, 0.0, want))
            k = np.ones(self.B)
            for b in range(self.B):
                for a in np.linspace(1, 0, 21):
                    x = sm[b] + a * sf[b]
                    if (x >= lo - 1e-9).all() and (x <= hi + 1e-9).all():
                        k[b] = a; break
                else:
                    k[b] = 0.0
            s = np.clip(sm + k[:, None] * sf, lo, hi)
        else:
            s = np.clip(np.einsum("bij,bj->bi", P, want), lo, hi)
        prop = np.array([a.kind == "prop" for a in acts])
        u = np.where(prop, np.sign(s) * np.sqrt(np.abs(s)), s)
        return self._power_cap(u)

    def _power_cap(self, u):
        acts = self.veh.actuators
        pm = np.array([a.pmax if a.kind == "prop" else 0.0 for a in acts])
        P = (pm * np.abs(u) ** 3).sum(1)
        k = np.minimum(1, (self.veh.power_w / np.maximum(P, 1e-9))) ** (1 / 3)
        prop = np.array([a.kind == "prop" for a in acts])
        return np.where(prop, u * k[:, None], u)


def _vee(S):
    return np.stack([S[:, 2, 1], S[:, 0, 2], S[:, 1, 0]], 1)


# ------------------------------------------------------------------ speeds from the vehicle's own physics

def _level_power(veh, V):
    """Electrical power to hold speed V through the fluid, straight and level; and feasibility."""
    from cafe.dyn import Dynamics, ROTOR_DRAG
    d = Dynamics(veh, 1)
    D = -d.drag(np.array([[V, 0.0, 0.0]]))[0][0, 0]
    props = [a for a in veh.actuators if a.kind == "prop"]
    if veh.kind == "uav":
        W, T = veh.mass * G, veh.mass * G
        for _ in range(20):                       # rotor drag grows with thrust: fixed point
            Dt = D + ROTOR_DRAG * T * V
            T = np.hypot(W, Dt)
        a = props[0]
        per = T / len(props)
        u = np.sqrt(min(per / a.tmax, 1))
        Pe = prop_perf(a.fluid, a.D, a.wmax / (2 * np.pi), a.rev, np.array(u), np.array(0.0))[2] * len(props)
        ok = per <= a.tmax and Dt <= W * np.tan(TILT_MAX)
        return float(Pe) + veh.hotel_w, ok
    # every thruster with a fore-aft component helps: forward-facing ones ahead, aft-facing ones in reverse
    fwd = [a for a in props if abs(a.dir[0]) > 0.3]
    us = np.linspace(0, 1, 2001)
    sgn = lambda a: 1.0 if a.dir[0] > 0 else -1.0
    T = sum(prop_perf(a.fluid, a.D, a.wmax / (2 * np.pi), a.rev, sgn(a) * us, V * a.dir[0])[0] * a.dir[0] for a in fwd)
    ok = T >= D
    if not ok.any():
        return np.inf, False
    u = us[ok][0]
    Pe = sum(prop_perf(a.fluid, a.D, a.wmax / (2 * np.pi), a.rev, np.array(sgn(a) * u), np.array(V * a.dir[0]))[2] for a in fwd)
    return float(Pe) + veh.hotel_w, float(Pe) <= veh.power_w * 1.001


def fin_min_speed(veh):
    """Slowest speed at which the elevators can still out-lift the net buoyancy (finned subs)."""
    fins = [a for a in veh.actuators if a.kind == "fin" and abs(a.dir[2]) > 0.5]
    if veh.kind != "uuv" or not fins:
        return 0.0
    dB = abs(RHO["water"] * veh.volume - veh.mass) * G
    cap = sum(a.area for a in fins) * 1.2 * 0.5 * RHO["water"]
    return float(np.sqrt(dB / cap))


def glide_speed(veh, gamma=np.radians(26)):
    """Steady glide speed through the water: net buoyancy along the path balances drag (hull + wings).
    Horizontal component is what moves a glider toward its target."""
    from cafe.dyn import Dynamics
    vb = sum(a.vb for a in veh.actuators if a.kind == "buoy")
    W = RHO["water"] * G * vb
    d = Dynamics(veh, 1)
    for V in np.linspace(0.02, 2.0, 400):
        D = -d.drag(np.array([[V, 0.0, 0.0]]))[0][0, 0]
        wings = sum(0.5 * RHO["water"] * V ** 2 * a.area * (0.01 + 0.0) for a in veh.actuators if a.passive)
        if D + wings >= W * np.sin(gamma):
            return V
    return 2.0


def glide_sim(veh, top=5.0, bottom=100.0, dt=0.06):
    """Fly one full yo (top -> bottom -> top) in still water with the real 6-DOF model and glider autopilot.
    -> (horizontal speed made good m/s, seconds per yo). The steady-glide formula above ignores the turns at
    top and bottom, where the glider slows and pitches over; this doesn't."""
    from cafe.dyn import Dynamics, State
    d = Dynamics(veh, 1)
    ap = Autopilot(veh, d, 1)
    ap.set_band(top, bottom)
    st = State(1, len(veh.actuators), p=[0.0, 0.0, top])
    tgt = np.array([[1e6, 0.0, 0.5 * (top + bottom)]])
    turned, flow = False, np.zeros((1, 3))
    while st.t < 4 * 3600:
        vd, _ = ap.velocity_cmd(st.p, tgt, ap.v_cruise)
        d.step(st, ap(st, vd, flow, dt), dict(flow_ned=flow), dt, None)
        turned |= not ap.diving[0]
        if turned and ap.diving[0]:          # back at the top, about to dive again: one yo done
            break
    return float(st.p[0, 0] / st.t), float(st.t)


def max_speed(veh):
    if family(veh) == "glider":
        return float(glide_speed(veh))
    best = 0.1
    for V in np.linspace(0.05, 40 if veh.kind == "uav" else 8, 400):
        P, ok = _level_power(veh, V)
        if ok:
            best = V
        elif best > 0.1:
            break
    return best


def fin_trim_speed(veh, budget=0.4):
    """Slowest speed at which holding the sub's net buoyancy takes at most `budget` of the fins' lift,
    leaving the rest to fight the pitch instability (a bare torpedo's Munk moment outgrows passive fin lift).
    For REMUS this lands at ~1.4 m/s; the real vehicle cruises at 1.5."""
    return fin_min_speed(veh) / np.sqrt(budget)


def cruise_speed(veh):
    """Best-range speed (minimum energy per metre through the fluid), but never below what the fins
    need for control, and below max speed. Gliders glide at the speed their buoyancy and drag set."""
    if family(veh) == "glider":
        # measured in the 6-DOF model when the design was characterized; the steady formula until then
        return float(veh.limits.get("glide_speed_sim") or glide_speed(veh) * np.cos(np.radians(26)))
    vmax = max_speed(veh)
    Vs = np.linspace(0.1 * vmax, 0.95 * vmax, 60)
    e = [(_level_power(veh, V)[0] / V) for V in Vs]
    floor = fin_trim_speed(veh) if (veh.kind == "uuv" and family(veh) == "steered") else 0.0
    return float(min(max(Vs[int(np.argmin(e))], floor), 0.95 * vmax))
