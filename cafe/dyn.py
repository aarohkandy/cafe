"""6-DOF rigid-body dynamics, batched over Monte Carlo samples (leading dim B).

Fossen form about the CoG, NED world, FRD body:
    (M_RB + M_A) nu_dot = tau - C_RB(nu) nu - C_A(nu_r) nu_r
tau = gravity + panel pressure (hydrostatic + waves) + drag(nu_r) + rotational damping
      + added-mass wave-acceleration term + windage + actuators.
Integrated with semi-implicit Euler (velocities first, then pose) — stable at the small steps used.
"""
import numpy as np
from cafe.vehicle import RHO, NU, G, TAU_MOTOR, prop_perf, cross_k

# ------------------------------------------------------------------ quaternion helpers [w,x,y,z], body->NED


def quat_to_R(q):
    w, x, y, z = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)], -1),
        np.stack([2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)], -1),
        np.stack([2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1)], -2)


def quat_mul(a, b):
    aw, ax, ay, az = np.moveaxis(a, -1, 0)
    bw, bx, by, bz = np.moveaxis(b, -1, 0)
    return np.stack([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw], -1)


def euler_to_quat(roll, pitch, yaw):
    cr, sr, cp, sp, cy, sy = (np.cos(roll / 2), np.sin(roll / 2), np.cos(pitch / 2), np.sin(pitch / 2),
                              np.cos(yaw / 2), np.sin(yaw / 2))
    return np.stack([cr * cp * cy + sr * sp * sy, sr * cp * cy - cr * sp * sy,
                     cr * sp * cy + sr * cp * sy, cr * cp * sy - sr * sp * cy], -1)


def quat_to_euler(q):
    w, x, y, z = np.moveaxis(q, -1, 0)
    roll = np.arctan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2 * (w * y - z * x), -1, 1))
    yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return np.stack([roll, pitch, yaw], -1)


def bmv(R, v):      # batched R @ v
    return np.einsum("...ij,...j->...i", R, v)


def bmtv(R, v):     # batched R.T @ v
    return np.einsum("...ji,...j->...i", R, v)


ROTOR_DRAG = 0.03


def ittc(re_):
    return 0.075 / (np.log10(np.maximum(re_, 1e4)) - 2) ** 2


class State:
    def __init__(self, B, nact, p=None, q=None):
        self.p = np.broadcast_to(np.zeros(3) if p is None else p, (B, 3)).astype(float)
        self.q = np.broadcast_to([1.0, 0, 0, 0] if q is None else q, (B, 4)).astype(float)
        self.v = np.zeros((B, 3))       # body linear velocity (earth-relative)
        self.w = np.zeros((B, 3))       # body rates
        self.u = np.zeros((B, nact))    # actuator state (normalized command after motor lag)
        self.energy_wh = np.zeros(B)
        self.t = 0.0
        self.accel_body = np.zeros((B, 3))   # last specific force (what an IMU reads)
        self.alive = np.ones(B, bool)        # battery left & not crashed


class Dynamics:
    """One vehicle type, B samples. `scale` holds per-sample Monte Carlo multipliers."""

    def __init__(self, veh, B=1, scale=None):
        self.veh, self.B = veh, B
        s = scale or {}
        self.drag_scale = np.asarray(s.get("drag", np.ones(B)), float) * veh.limits.get("appendage_factor", 1.0)
        self.thrust_scale = np.asarray(s.get("thrust", np.ones(B)), float)
        self.battery_scale = np.asarray(s.get("battery", np.ones(B)), float)
        self.Minv = np.linalg.inv(veh.M)
        self.A = veh.added_mass
        self.rho = RHO[veh.fluid]          # drag, lift, wave pressure; buoyancy uses the local density (step)
        self.trim_kg = 0.0                 # ballast added at launch (mission.World trims gliders to the local water)
        acts = veh.actuators
        self.a_pos = np.array([a.pos for a in acts]).reshape(-1, 3)
        self.a_dir = np.array([a.dir for a in acts]).reshape(-1, 3)
        self.a_prop = np.array([a.kind == "prop" for a in acts], bool)
        self.a_fin = np.array([a.kind == "fin" for a in acts], bool)
        self.a_buoy = np.array([a.kind == "buoy" for a in acts], bool)
        self.a_mass = np.array([a.kind == "mass" for a in acts], bool)
        self.a_passive = np.array([a.passive for a in acts], bool)
        self.a_ar = np.array([a.ar for a in acts])
        self.a_vb = np.array([a.vb for a in acts]); self.a_mm = np.array([a.mmass for a in acts])
        self.a_dx = np.array([a.dx for a in acts])
        self.a_tau = np.array([a.tau if a.tau else TAU_MOTOR[veh.fluid] for a in acts])
        self.a_tmax = np.array([a.tmax for a in acts])
        self.a_rev = np.array([a.rev for a in acts])
        self.a_pmax = np.array([a.pmax for a in acts])
        self.a_qmax = np.array([a.qmax for a in acts])
        self.a_spin = np.array([a.spin for a in acts], float)
        self.a_nmax = np.array([a.wmax / (2 * np.pi) for a in acts])
        self.a_D = np.array([a.D for a in acts])
        self.a_area = np.array([a.area for a in acts])
        self.a_cla = np.array([a.cla for a in acts])
        self.a_dmax = np.array([a.dmax for a in acts])
        self.tau_m = TAU_MOTOR[veh.fluid]
        # drag table as arrays [axis, sign(0:+,1:-)] -> coefficient vectors
        self.Cf = np.zeros((3, 2, 3)); self.Cm = np.zeros((3, 2, 3)); self.vf = np.zeros((3, 2))
        for ax, c in enumerate("xyz"):
            for sg, sgn in enumerate("+-"):
                F, Mc, fv, _ = veh.drag[sgn + c]
                self.Cf[ax, sg], self.Cm[ax, sg], self.vf[ax, sg] = F, Mc, fv
        self.re_ref = veh.drag_re[0] * veh.drag_re[2] / veh.drag_re[1]
        self.half_h = 0.0 if veh.panels is None else float(np.abs(veh.panels[0]).max())

    @staticmethod
    def crest(waves):
        return float(np.max(np.sum(np.abs(waves.a), -1)))

    # -------------------------------------------------------------- forces

    def actuator_forces(self, st, v_r):
        """Thrust/fin forces and moments from the lagged actuator state; electrical power."""
        u = st.u
        F = np.zeros((self.B, len(self.a_tmax), 3))
        power = np.zeros(self.B)
        if self.a_prop.any():
            P = self.a_prop
            va = v_r @ self.a_dir[P].T                                  # forward speed through each disk
            T, Q, Pe = prop_perf(self.veh.fluid, self.a_D[P], self.a_nmax[P], self.a_rev[P], u[:, P], va)
            T = T * self.thrust_scale[:, None]
            F[:, P] = T[..., None] * self.a_dir[P]
            power = Pe.sum(1)
            if self.veh.kind == "uav":
                # rotor drag (blade flapping / induced drag): -k * T * airspeed in the rotor plane.
                # ponytail: k = 0.03 1/s per N of thrust, mid-range of measured small-quad values
                # (Martin & Salaun 2010 and follow-ups); body CFD cannot see this force.
                vperp = v_r[:, None, :] - va[..., None] * self.a_dir[P]
                F[:, P] -= ROTOR_DRAG * np.abs(T)[..., None] * vperp
            # reaction torque: a CCW (spin +1) rotor pushes the body the other way about its thrust axis
            self._q = (self.a_spin[P] * Q * np.sign(u[:, P]))[..., None] * self.a_dir[P]
        if self.a_fin.any():
            # fins and wings: lift from commanded deflection AND from the local angle of attack at the fin
            # (v_r + w x r), which is what makes a finned hull weathervane-stable and damps turning; plus
            # profile + induced drag CD = 0.01 + CL^2/(pi 0.8 AR) (a glider's range IS its lift/drag)
            Fn = self.a_fin
            vloc = v_r[:, None, :] + np.cross(st.w[:, None, :], self.a_pos[Fn])          # (B,nf,3)
            ax = np.maximum(vloc[..., 0], 1e-3)
            alpha = np.arctan2(np.einsum("bfi,fi->bf", vloc, self.a_dir[Fn]), ax)
            cl = np.clip(self.a_cla[Fn] * (u[:, Fn] * self.a_dmax[Fn] - alpha), -1.2, 1.2)
            q = 0.5 * self.rho * np.maximum(vloc[..., 0], 0) ** 2
            F[:, Fn] = (q * self.a_area[Fn] * cl)[..., None] * self.a_dir[Fn]
            cd = 0.01 + cl ** 2 / (np.pi * 0.8 * self.a_ar[Fn])
            sp = np.linalg.norm(vloc, axis=-1, keepdims=True)
            F[:, Fn] -= (q * self.a_area[Fn] * cd)[..., None] * vloc / np.maximum(sp, 1e-6)
        Ft = F.sum(1)
        Mt = np.cross(self.a_pos, F).sum(1)
        if self.a_buoy.any() or self.a_mass.any():
            R = quat_to_R(st.q)
            up = bmtv(R, np.broadcast_to([0.0, 0.0, -1.0], (self.B, 3)))                 # world up, in body axes
            if self.a_buoy.any():
                dV = (u[:, self.a_buoy] * self.a_vb[self.a_buoy]).sum(1)                  # extra displacement, m3
                Fb = (self.rho * G * dV)[:, None] * up
                Ft = Ft + Fb
                Mt = Mt + np.cross(self.a_pos[self.a_buoy][0], Fb)          # pump location (nose on a Slocum)
                # pumping oil out against sea pressure costs energy; letting it back in is a valve (free)
                depth = np.maximum(st.p[:, 2], 0)
                rate = np.maximum(getattr(self, "_dV_rate", np.zeros(self.B)), 0)
                power = power + self.rho * G * depth * rate / 0.5
            if self.a_mass.any():
                x = (u[:, self.a_mass] * self.a_dx[self.a_mass]).sum(1)
                mg = (self.a_mm[self.a_mass].sum() * G) * (-up)                            # weight of the moving mass
                Mt = Mt + np.cross(np.column_stack([x, np.zeros(self.B), np.zeros(self.B)]), mg)
        if self.a_prop.any():
            Mt -= self._q.sum(1)
        return Ft, Mt, power

    def drag(self, v_r):
        """Quadratic drag blended from the six CFD directions; friction part re-scaled with Re."""
        sp = np.linalg.norm(v_r, axis=1)
        d = v_r / np.maximum(sp, 1e-9)[:, None]
        q = 0.5 * self.rho * sp ** 2
        fr = ittc(sp * self.veh.drag_re[2] / self.veh.drag_re[1]) / ittc(self.re_ref)
        F = np.zeros((self.B, 3)); M = np.zeros((self.B, 3))
        for ax in range(3):
            sg = (d[:, ax] < 0).astype(int)
            w = d[:, ax] ** 2 * ((1 - self.vf[ax, sg]) + self.vf[ax, sg] * fr)
            F += w[:, None] * self.Cf[ax, sg]
            M += w[:, None] * self.Cm[ax, sg]
        for ax, entry in (self.veh.cross or {}).items():          # hull lift (vehicle.hull_lift)
            fwd = np.maximum(d[:, 0], 0)
            KF, KM = cross_k(entry, np.degrees(np.arctan2(np.abs(d[:, ax]), np.maximum(fwd, 1e-9))))
            w = (fwd * d[:, ax])[:, None]
            F += w * KF
            M += w * KM
        if self.veh.resistance is not None:      # boat: free-surface resistance curve replaces surge drag
            Vs, R = self.veh.resistance
            Rx = np.where(sp <= Vs[-1], np.interp(sp, Vs, R), R[-1] * (sp / Vs[-1]) ** 2)  # ponytail: V^2 past the last CFD speed
            F[:, 0] = -np.sign(d[:, 0]) * Rx * d[:, 0] ** 2 / np.maximum(q, 1e-9)
        k = (q * self.drag_scale)[:, None]
        return F * k, M * k

    WAVE_EVERY = 0.15   # s between wave-field refreshes (>= ~10 per period of any wave that moves a hull);
                        # hydrostatics are exact every step

    def panel_forces(self, st, R, waves, t, rho_w=None):
        """Integrate instantaneous hydrostatic + wave pressure over the hull panels.
        Pressure: rho g (-z) + p_dyn below the mean surface, rho g (eta - z) between it and the crest
        (simple stretching), 0 above the local surface. The wave field (eta, p_dyn) is refreshed every
        WAVE_EVERY s — waves have periods of seconds — while the stiff hydrostatic part uses the panel
        positions of this step."""
        c, n, a = self.veh.panels
        xw = st.p[:, None, :] + c[None] @ R.transpose(0, 2, 1)                 # (B,N,3) NED
        z = -xw[..., 2]
        cache = getattr(self, "_wave", None)
        if cache is None or t - cache[0] >= self.WAVE_EVERY - 1e-9 or cache[1] is not waves:
            crest = 1.1 * np.max(np.sum(np.abs(waves.a), -1)) + 1e-3
            live = (z < crest).any(0)
            eta = np.full(z.shape, -np.inf); pd = np.zeros(z.shape)
            if live.any():
                eta[:, live], pd[:, live] = waves.fields(xw[:, live, 0], xw[:, live, 1], z[:, live], t, self.rho)
            self._wave = cache = (t, waves, eta, pd)
        eta, pd = cache[2], cache[3]
        rho_w = np.reshape(self.rho if rho_w is None else rho_w, (-1, 1))
        p = np.where(z < 0, -rho_w * G * z + pd, rho_w * G * (eta - z))
        p = np.where(z < eta, p, 0.0)
        f = -(p * a)[..., None] * n                                              # body frame
        return f.sum(1), np.cross(c, f).sum(1), (p > 0).mean(1)

    def step(self, st, cmd, env, dt, waves=None):
        """Advance one step. env: dict with flow_ned (B,3) fluid velocity at the CoG, flow_acc_ned,
        wind_ned (for boats), rho_air."""
        veh, B = self.veh, self.B
        R = quat_to_R(st.q)
        # actuator lag (exact first-order), dead vehicles get nothing
        cmd = np.where(st.alive[:, None], cmd, 0.0)
        cmd = np.where(self.a_passive, 0.0, cmd)
        du = (cmd - st.u) * (1 - np.exp(-dt / self.a_tau))
        if self.a_buoy.any():
            self._dV_rate = (du[:, self.a_buoy] * self.a_vb[self.a_buoy]).sum(1) / dt
        st.u += du
        uf = bmtv(R, env["flow_ned"])
        v_r = st.v - uf
        nu_r = np.concatenate([v_r, st.w], 1)
        tau = np.zeros((B, 6))
        tau[:, :3] += bmtv(R, np.broadcast_to([0, 0, (veh.mass + self.trim_kg) * G], (B, 3)))
        rho_w = np.broadcast_to(np.asarray(env.get("rho_water", self.rho), float), (B,))     # in-situ, per sample
        archimedes = np.column_stack([np.zeros(B), np.zeros(B), -rho_w * G * veh.volume])
        Fa, Ma, power = self.actuator_forces(st, v_r)
        tau[:, :3] += Fa; tau[:, 3:] += Ma
        Fd, Md = self.drag(v_r)
        tau[:, :3] += Fd; tau[:, 3:] += Md
        tau[:, 3:] -= 0.5 * self.rho * veh.rot_damp * st.w * np.abs(st.w)
        if veh.linear_damp is not None:
            tau -= veh.linear_damp * nu_r
        wet = None
        submerged = (veh.panels is not None and waves is not None and veh.kind == "uuv"
                     and (st.p[:, 2] - self.half_h).min() > 1.2 * self.crest(waves))
        if submerged:
            # fully under every trough: hydrostatics integrate exactly to Archimedes, and for waves much
            # longer than the hull the wave force is Froude-Krylov rho*V*a_fluid (added-mass part below)
            Fb = bmtv(R, archimedes)
            tau[:, :3] += Fb; tau[:, 3:] += np.cross(veh.cob, Fb)
            if "flow_acc_ned" in env:
                Ffk = self.rho * veh.volume * bmtv(R, env["flow_acc_ned"])
                tau[:, :3] += Ffk + bmtv(R, env["flow_acc_ned"]) @ self.A[:3, :3].T
        elif veh.panels is not None and waves is None:
            # deep: waves can't reach, panels would just integrate to Archimedes -> do it exactly
            Fb = bmtv(R, archimedes)
            tau[:, :3] += Fb; tau[:, 3:] += np.cross(veh.cob, Fb)
        elif veh.panels is not None:
            Fp, Mp, wet = self.panel_forces(st, R, waves, st.t, rho_w)
            tau[:, :3] += Fp; tau[:, 3:] += Mp
            if "flow_acc_ned" in env:   # diffraction/added-mass part of the wave force on the accelerating fluid
                tau[:, :3] += bmtv(R, env["flow_acc_ned"]) @ self.A[:3, :3].T
        if veh.windage is not None and "wind_ned" in env:
            wr = bmtv(R, env["wind_ned"]) - st.v
            wr[:, 2] = 0
            rho_a = np.reshape(env.get("rho_air", 1.2), (-1, 1))
            tau[:, :3] += 0.5 * rho_a * veh.windage * wr * np.abs(wr)
        # Coriolis: rigid body and added mass (Fossen 2011 eqs 3.57, 6.43)
        v, w = st.v, st.w
        tau[:, :3] -= veh.mass * np.cross(w, v)
        tau[:, 3:] -= np.cross(w, w @ veh.inertia.T)
        a1 = nu_r @ self.A[:3, :].T
        a2 = nu_r @ self.A[3:, :].T
        tau[:, :3] -= -np.cross(a1, w)
        tau[:, 3:] -= -np.cross(a1, v_r) - np.cross(a2, w)
        # M_A acts on the RELATIVE acceleration: nu_r_dot = nu_dot + w x u_c (current seen from a rotating
        # body, Fossen 2011 sec 10.3) -> move the extra term to the right-hand side
        tau -= np.cross(w, uf) @ self.A[:, :3].T
        nudot = tau @ self.Minv.T
        if veh.kind == "uav":                                  # a crashed quad stops: no coasting, no tumbling
            dead = ~st.alive
            nudot[dead] = 0.0
            st.v[dead] = 0.0
            st.w[dead] = 0.0
        st.v += nudot[:, :3] * dt
        st.w += nudot[:, 3:] * dt
        st.p += bmv(R, st.v) * dt
        dq = np.concatenate([np.zeros((B, 1)), st.w * dt / 2], 1)
        dq[:, 0] = 1.0
        st.q = quat_mul(st.q, dq)
        st.q /= np.linalg.norm(st.q, axis=1, keepdims=True)
        # IMU specific force: earth-frame acceleration minus gravity, in body axes
        st.accel_body = nudot[:, :3] + np.cross(w, v) - bmtv(R, np.broadcast_to([0, 0, G], (B, 3)))
        total_w = power + veh.hotel_w
        st.energy_wh += np.where(st.alive, total_w, 0) * dt / 3600
        st.alive &= st.energy_wh < veh.battery_wh * self.battery_scale
        if veh.kind == "uav":
            st.alive &= st.p[:, 2] < 0.0          # touched the sea surface (z down)
        st.t += dt
        return dict(power=total_w, wet=wet)
