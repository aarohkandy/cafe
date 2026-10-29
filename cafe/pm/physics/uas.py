"""Small-quadrotor UAS for Stage 1: rotor-drag physics, Peukert battery, ArduCopter-style cascade, ship sorties, SITL.

Physics (world ENU, body FLU, z up; every array is components-first, (3, M), so XLA vectorizes over the M members):
    p' = v;  v' = -g z_W + c z_B - R D R^T (v - wind);  R' = R [w]x;  J w' = tau - w x J w       Faessler, Franchi &
    Scaramuzza 2018 (IEEE RA-L 3(2), Eq. 2); the paper has no wind, so the air-relative velocity v - wind is our step
    (rotor drag is a force of the air on the rotors). c = sum(T_i)/m.
Rotors: T_i = kT w_i^2, shaft power kQ w_i^3 (momentum theory with a figure of merit, Leishman 2006 Ch. 2), first-order
    lag 33 ms (NeuroBEM, Bauersfeld et al. 2021). Battery: Peukert (P ~ 1.05) with open-circuit curve and I*R sag.
Multirate: rate/attitude loop + rigid body at DT_PHYS = 2.5 ms; wind lookup, guidance and velocity loop every
    DT_ENV = 50 ms (zero-order hold), as docs/BRIEF.md 2.4 asks. The 50 ms block is one jitted call; the environment
    callbacks run in Python between blocks, so any Environment (WRF, analytic) plugs in.
Controller: cafe/ctrl.py's multirotor structure (position -> velocity PI -> thrust vector -> geometric attitude ->
    rates -> mix) in JAX, with ArduCopter defaults (sqrt controller, PSC_VEL gains, lean-angle limit).
Every constant is in platforms/quad_uas.yaml with a source or an `assumed` reason.
Arithmetic is JAX's default float32 (twice as fast as float64 here, and it leaves the process-wide x64 flag alone): the 480 k-step
sums that matter (energy, charge) are accumulated per 50 ms block and are good to 1e-5; times and positions are kept in float64 on
the host.
"""
import json
import math
import pathlib
import select
import socket
import struct
import subprocess
import threading
import time
from typing import Any, Callable, NamedTuple, Optional, cast

import jax
import jax.numpy as jnp
import numpy as np
import yaml
from jax import lax
from numpy.typing import NDArray

from ..env import conventions as cv

Arr = Any
F = NDArray[np.float64]
XY = tuple[float, float]
Ship = Callable[[float], Arr]
WindFn = Callable[[int, float, Arr], Arr]
LinkFn = Callable[[float, Arr], Arr]

PLATFORM = pathlib.Path(__file__).resolve().parents[3] / "platforms" / "quad_uas.yaml"
DT_PHYS, DT_ENV = 0.0025, 0.05
G0 = 9.80665
FLY, RTL, LAND, DONE, DEAD = 0, 1, 2, 3, 4
FLAGS = ("battery_reserve", "wind_exceeds_airspeed", "attitude_exceedance", "lost_link")
M_PER_DEG = 6371008.8 * math.pi / 180.0
SITL_HOME = (149.1652374, -35.3632621)     # (lon, lat) the firmware is told it is at (ArduPilot's own SITL home): its compass/EKF
#                                            misbehaves at the equator; only metres from home matter to us, the env uses `origin`
SITL_HELP = ("ArduCopter SITL binary not found at {path}. Build it from ArduPilot 4.7.x (./waf configure --board sitl && "
             "./waf copter) and copy build/sitl/bin/arducopter plus Tools/autotest/default_params/copter.parm and "
             "copter-X.parm to that directory; on homebase it lives in ~/work/cafe/data/sitl (/work/sitl under ./pm.sh).")


class SitlUnavailable(RuntimeError):
    """The ArduCopter SITL binary (or the emulator machinery it needs) is missing; Stage 1 reports 0 SITL members."""


# ---------------------------------------------------------------------------------------------- platform file

def check_provenance(node: Any, path: str = "") -> list[str]:
    """Paths of leaves that have neither `source` nor (`assumed: true` and a `why`) - must be empty."""
    if isinstance(node, dict) and "value" in node:
        ok = bool(node.get("source")) or (node.get("assumed") is True and bool(node.get("why")))
        return [] if ok else [path]
    if isinstance(node, dict):
        return [b for k, v in node.items() for b in check_provenance(v, f"{path}.{k}" if path else k)]
    return [path]


def load_platform(path: Optional[str] = None) -> dict[str, Any]:
    """quad_uas.yaml as nested dicts of plain values (provenance stripped after it is checked)."""
    p = pathlib.Path(path or PLATFORM)
    p = p if p.suffix in (".yaml", ".yml") else PLATFORM.parent / f"{p}.yaml"         # a platform name, like the other loaders take
    doc = yaml.safe_load(p.read_text())
    bad = check_provenance(doc)
    if bad:
        raise ValueError(f"platform numbers without a source or an assumed+why: {bad}")

    def strip(n: Any) -> Any:
        return n["value"] if isinstance(n, dict) and "value" in n else {k: strip(v) for k, v in n.items()}
    return cast(dict[str, Any], strip(doc))


# ---------------------------------------------------------------------------------------------- constants -> arrays

def air_density(psfc: Arr, t2: Arr, q2: Arr = 0.0) -> Arr:
    """Moist-air density from surface pressure [Pa], 2 m temperature [K], specific humidity [kg/kg]."""
    return psfc / (287.05 * t2 * (1.0 + 0.608 * q2))


def derive(P: dict[str, Any], M: int, rho: Arr = 1.2, scale: Optional[dict[str, Any]] = None, fault: Optional[str] = None) -> dict[str, Any]:
    """Per-member float64 arrays the jitted code reads. `scale` (each (M,) or scalar): mass, drag, thrust, eff, battery.
    `fault` deliberately breaks one piece of physics so receipts can be shown to fail (see receipts())."""
    af, ro, ae, ba, li, co, so, fa = (P[k] for k in ("airframe", "rotor", "aero", "battery", "limits", "controller", "sortie", "failure"))
    sc = {k: np.broadcast_to(np.asarray((scale or {}).get(k, 1.0), float), (M,)) for k in ("mass", "drag", "thrust", "eff", "battery")}
    rho = np.broadcast_to(np.asarray(rho, float), (M,))
    om_max = ro["omega_max_rpm"] * 2 * math.pi / 60
    area = math.pi * ro["prop_diameter_m"] ** 2 / 4
    kT = ro["thrust_max_n_each"] / om_max ** 2 * rho / ro["rho_ref_kgm3"] * sc["thrust"]
    kQ = kT ** 1.5 / (np.sqrt(2 * rho * area) * ro["figure_of_merit"]) * (1.6 if fault == "fm" else 1.0)
    cap = ba["energy_wh"] / (ba["cells"] * ba["v_nom_cell"]) * sc["battery"]

    def f(x: Arr) -> Arr:
        return np.broadcast_to(np.asarray(x, float), (M,)).copy()

    prm = dict(
        m=af["mass_kg"] * sc["mass"], J=np.array(af["inertia_kgm2"])[:, None] * sc["mass"], arm=f(af["motor_radius_m"] / math.sqrt(2)),
        hotel=f(af["hotel_w"]), kT=kT, kQ=kQ, cq=kQ / kT, om_max=f(om_max), tau_m=f(ro["motor_time_const_s"]), eff=ro["esc_motor_eff"] * sc["eff"],
        ky=f(ro["yaw_torque_ratio_priority"]), drag=np.array([ae["d_x"], ae["d_y"], ae["d_z"]])[:, None] * sc["drag"] * (0.0 if fault == "no_drag" else 1.0),
        wsign=f(-1.0 if fault == "wind_sign" else 1.0), cap=cap, iref=cap / ba["peukert_hours"], pk=f(1.0 if fault == "peukert" else ba["peukert_exponent"]),
        rint=f(ba["r_int_ohm"]), ncell=f(ba["cells"]), vref=f(4.2 * ba["cells"]), vcut=f(ba["cutoff_cell_v"] * ba["cells"]),
        reserve=f(ba["reserve_frac"]), dt_const=f(DT_PHYS if fault == "dt_const" else 0.0),
        tilt_lim=f(math.radians(li["max_tilt_deg"])), tilt_exc=f(math.radians(li["tilt_exceedance_deg"])), v_air=f(li["max_airspeed_ms"]),
        pos_p=f(co["pos_p"]), vel_p=f(co["vel_p"]), vel_i=f(co["vel_i"]), vz_p=f(co["vel_z_p"]), vz_i=f(co["vel_z_i"]), acc_wp=f(co["accel_wp"]),
        acc_z=f(co["accel_z"]), v_up=f(co["speed_up"]), v_dn=f(co["speed_dn"]), att_p=f(co["att_p"]), rate_p=f(co["rate_p"]),
        yaw_slew=f(math.radians(co["yaw_slew_degs"])), i_max=f(co["vel_i_max"]), v_leg=f(min(so["leg_speed_ms"], li["max_airspeed_ms"])),
        rtl_h=f(so["rtl_height_m"]), r_wp=f(so["wp_radius_m"]), v_land=f(so["land_speed_ms"]), t_lim=f(so["duration_s"] * so["time_limit_factor"]),
        yaw_lock=f(0.0), stuck_w=f(fa["stuck_window_s"]), stuck_v=f(fa["stuck_closing_ms"]), stuck_cmd=f(fa["stuck_min_cmd_ms"]),
    )
    prm["ocv_x"] = np.array(ba["ocv_soc"], float)
    prm["ocv_y"] = np.array(ba["ocv_cell_v"], float)
    return {k: jnp.asarray(v) for k, v in prm.items()}


# ---------------------------------------------------------------------------------------------- vector helpers (3, M)

def _dot(a: Arr, b: Arr) -> Arr:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Arr, b: Arr) -> Arr:
    return jnp.stack([a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]])


def _unit(a: Arr, eps: float = 1e-9) -> Arr:
    return a / jnp.maximum(jnp.sqrt(_dot(a, a)), eps)


def _axes(q: Arr) -> tuple[Arr, Arr, Arr]:
    """Body x, y, z axes in the world frame (columns of R) from q = (w, x, y, z), body -> world."""
    w, x, y, z = q
    xb = jnp.stack([1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)])
    yb = jnp.stack([2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)])
    zb = jnp.stack([2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)])
    return xb, yb, zb


def _qmul(a: Arr, b: Arr) -> Arr:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return jnp.stack([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                      aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw])


def _sqrt_ctrl(err: Arr, kp: Arr, a_max: Arr) -> Arr:
    """ArduPilot's sqrt_controller: linear near zero, constant-deceleration (sqrt) beyond."""
    lin = a_max / (kp * kp)
    ae = jnp.abs(err)
    out = jnp.where(ae < lin, kp * ae, jnp.sqrt(jnp.maximum(2 * a_max * (ae - lin / 2), 0.0)))
    return jnp.sign(err) * out


# ---------------------------------------------------------------------------------------------- physics (2.5 ms)

SX = jnp.array([1.0, -1.0, 1.0, -1.0])[:, None]      # ArduPilot QuadX motors 1..4 (FR, RL, FL, RR): x sign
SY = jnp.array([-1.0, 1.0, 1.0, -1.0])[:, None]      #                                                 y sign (left +)
SP = jnp.array([1.0, 1.0, -1.0, -1.0])[:, None]      #                                                 spin: +1 = CCW seen from above


def _dyn(prm: dict[str, Any], p: Arr, v: Arr, q: Arr, w: Arr, om: Arr, om_cmd: Arr, wind: Arr, deck_v: Arr,
         dt: float) -> tuple[Arr, Arr, Arr, Arr, Arr, Arr, Arr, Arr]:
    """One rigid-body step. -> p, v, q, w, om, electrical power [W], specific force (world), z_B up-component."""
    xb, yb, zb = _axes(q)
    T = prm["kT"] * om * om
    vr = v - prm["wsign"] * wind                                        # air-relative velocity (wind enters here)
    dr = prm["drag"]
    drag = dr[0] * _dot(xb, vr) * xb + dr[1] * _dot(yb, vr) * yb + dr[2] * _dot(zb, vr) * zb
    sf = jnp.sum(T, 0) / prm["m"] * zb - drag                           # specific force = what an accelerometer reads
    a = sf - jnp.array([0.0, 0.0, G0])[:, None]
    Qr = prm["kQ"] * om * om
    tau = jnp.stack([prm["arm"] * jnp.sum(SY * T, 0), -prm["arm"] * jnp.sum(SX * T, 0), -jnp.sum(SP * Qr, 0)])
    Jw = prm["J"] * w
    w2 = w + (tau - _cross(w, Jw)) / prm["J"] * dt
    th = jnp.sqrt(_dot(w2, w2)) * dt
    r = jnp.where(th > 1e-12, jnp.sin(th / 2) / jnp.maximum(th, 1e-12), 0.5)
    q2 = _qmul(q, jnp.concatenate([jnp.cos(th / 2)[None], w2 * dt * r]))
    q2 = q2 / jnp.sqrt(jnp.sum(q2 * q2, 0))
    v2 = v + a * dt
    p2 = p + v2 * dt
    om2 = om_cmd + (om - om_cmd) * jnp.exp(-dt / prm["tau_m"])
    pe = jnp.sum(prm["kQ"] * om ** 3, 0) / prm["eff"] + prm["hotel"]
    gr = (p2[2] <= 0.0) & (v2[2] <= 0.0)                                # on the deck: it holds the vehicle level, moving with the ship
    yaw = jnp.arctan2(2 * (q2[0] * q2[3] + q2[1] * q2[2]), 1 - 2 * (q2[2] ** 2 + q2[3] ** 2))
    qlevel = jnp.stack([jnp.cos(yaw / 2), 0 * yaw, 0 * yaw, jnp.sin(yaw / 2)])
    p2 = jnp.where(gr, p2 * jnp.array([1.0, 1.0, 0.0])[:, None], p2)
    v2 = jnp.where(gr, jnp.concatenate([deck_v, jnp.zeros_like(deck_v[:1])]), v2)
    q2 = jnp.where(gr, qlevel, q2)
    w2 = jnp.where(gr, 0.0, w2)
    sf = jnp.where(gr, jnp.array([0.0, 0.0, G0])[:, None], sf)
    return p2, v2, q2, w2, om2, pe, sf, _axes(q2)[2][2]


def _ctrl(prm: dict[str, Any], q: Arr, w: Arr, f_des: Arr, yawd: Arr, vscale: Arr) -> Arr:
    """Geometric attitude + rate loop and mixer (cafe/ctrl.py _multirotor, ArduCopter's order). -> rotor speed commands (4, M)."""
    xb, yb, zb = _axes(q)
    zd = _unit(f_des)
    tt = prm["m"] * jnp.maximum(_dot(f_des, zb), 0.0)                   # thrust along the current body z
    xc = jnp.stack([jnp.cos(yawd), jnp.sin(yawd), 0 * yawd])
    yd = _unit(_cross(zd, xc))
    xd = _cross(yd, zd)
    d, b = (xd, yd, zd), (xb, yb, zb)
    Mx = [[_dot(d[i], b[j]) for j in range(3)] for i in range(3)]       # Rd^T R
    eR = 0.5 * jnp.stack([Mx[2][1] - Mx[1][2], Mx[0][2] - Mx[2][0], Mx[1][0] - Mx[0][1]])
    wd = jnp.clip(-prm["att_p"] * eR, -10.0, 10.0)
    tau = prm["J"] * prm["rate_p"] * (wd - w) + _cross(w, prm["J"] * w)
    base = tt / 4 + (SY * tau[0] - SX * tau[1]) / (4 * prm["arm"])      # roll/pitch/collective
    yaw = -SP * tau[2] / (4 * prm["cq"])
    om_av = prm["om_max"] * jnp.minimum(vscale, 1.0)
    t_av = prm["kT"] * om_av ** 2
    full = base + yaw
    bad = jnp.any((full < 0) | (full > t_av), 0)
    ti = jnp.clip(jnp.where(bad, base + prm["ky"] * yaw, full), 0.0, t_av)
    return jnp.sqrt(ti / prm["kT"])


# ---------------------------------------------------------------------------------------------- battery (per 50 ms)

def _batt(prm: dict[str, Any], soc: Arr, qah: Arr, ewh: Arr, pe: Arr, dt: Arr) -> tuple[Arr, Arr, Arr, Arr, Arr]:
    """Peukert drain with I*R sag: -> soc, charge drawn [Ah], energy [Wh], terminal voltage, current. Closed-form I from P = V I."""
    voc = prm["ncell"] * jnp.interp(soc, prm["ocv_x"], prm["ocv_y"])
    disc = voc * voc - 4 * prm["rint"] * pe
    cur = (voc - jnp.sqrt(jnp.maximum(disc, 0.0))) / (2 * prm["rint"])
    volt = voc - cur * prm["rint"]
    dq = (cur / prm["iref"]) ** (prm["pk"] - 1.0) * cur * dt / 3600.0
    qah = qah + dq
    return 1.0 - qah / prm["cap"], qah, ewh + pe * dt / 3600.0, volt, cur


# ---------------------------------------------------------------------------------------------- state + 50 ms block

class St(NamedTuple):
    p: Any; v: Any; q: Any; w: Any; om: Any            # (3|4, M)
    vint: Any; vd: Any; yawd: Any                       # velocity-loop integrator, slewed velocity demand, yaw target
    soc: Any; qah: Any; ewh: Any; volt: Any; cur: Any  # battery
    phase: Any; wpi: Any; stuck: Any                    # mission logic
    f_tilt: Any; f_batt: Any; f_stuck: Any
    t_tilt: Any; t_batt: Any; t_stuck: Any
    tilt_max: Any; dist_max: Any; t_end: Any; wind_max: Any


def init_state(prm: dict[str, Any], M: int, yaw0: Arr, active: Arr) -> St:
    z3, f, nan = jnp.zeros((3, M)), jnp.zeros(M), jnp.full(M, jnp.nan)
    yaw0 = jnp.broadcast_to(jnp.asarray(yaw0, float), (M,))
    q = jnp.stack([jnp.cos(yaw0 / 2), f, f, jnp.sin(yaw0 / 2)])
    om0 = jnp.zeros((4, M))
    b = jnp.zeros(M, bool)
    return St(z3, z3, q, z3, om0, z3, z3, yaw0, jnp.ones(M), f, f, prm["vref"], f,
              jnp.where(jnp.asarray(active), FLY, DONE).astype(jnp.int32), jnp.zeros(M, jnp.int32), f,
              b, b, b, nan, nan, nan, f, f, nan, f)


def _block(prm: dict[str, Any], S: St, wp: Arr, ship_p: Arr, ship_v: Arr, wind: Arr, t: Arr, nsub: int, dt: float) -> St:
    """Guidance + velocity loop (once), `nsub` physics steps, battery, flags. `t` = time at the block start since launch."""
    M = S.soc.shape[0]
    z = jnp.zeros(M)
    flying = S.phase < DONE
    W = wp.shape[0]
    # ---- guidance at 50 ms: target relative to the ship, phase transitions
    tgt_fly = jnp.take_along_axis(wp, jnp.minimum(S.wpi, W - 1)[None, None, :], 0)[0]
    tgt = jnp.where(S.phase == FLY, tgt_fly, jnp.where(S.phase == RTL, jnp.stack([z, z, prm["rtl_h"]]), jnp.zeros((3, M))))
    rp = S.p - jnp.concatenate([ship_p, z[None]], 0)
    e = tgt - rp
    eh = jnp.hypot(e[0], e[1])
    reach = (S.phase == FLY) & (eh < prm["r_wp"]) & (jnp.abs(e[2]) < 2.0)
    wpi = S.wpi + reach
    late = (t > prm["t_lim"]) | (S.soc < prm["reserve"])
    phase = jnp.where((S.phase == FLY) & ((wpi >= W) | late), RTL, S.phase)
    phase = jnp.where((phase == RTL) & (eh < 2.0) & (jnp.abs(e[2]) < 2.0), LAND, phase)
    phase = jnp.where((phase == LAND) & (eh > 4.0), RTL, phase)
    cap = jnp.where(phase == LAND, 3.0, prm["v_leg"])
    sh = jnp.minimum(cap, _sqrt_ctrl(eh, prm["pos_p"], prm["acc_wp"]))
    vdes_h = ship_v + e[:2] / jnp.maximum(eh, 1e-6) * sh
    vz_up = jnp.clip(_sqrt_ctrl(e[2], prm["pos_p"], prm["acc_z"]), -prm["v_dn"], prm["v_up"])
    vz = jnp.where(phase == LAND, -prm["v_land"] * jnp.clip(1 - eh / 2.5, 0.0, 1.0), vz_up)
    vraw = jnp.concatenate([vdes_h, vz[None]], 0)
    dh = vraw[:2] - S.vd[:2]                                             # velocity demand slews at the acceleration limit (ArduCopter's shaper)
    dh = dh * jnp.minimum(1.0, prm["acc_wp"] * DT_ENV / jnp.maximum(jnp.hypot(dh[0], dh[1]), 1e-9))
    dz = jnp.clip(vraw[2] - S.vd[2], -prm["acc_z"] * DT_ENV, prm["acc_z"] * DT_ENV)
    vdes = S.vd + jnp.concatenate([dh, dz[None]], 0)
    ev = vdes - S.v
    gain = jnp.stack([prm["vel_p"], prm["vel_p"], prm["vz_p"]])
    igain = jnp.stack([prm["vel_i"], prm["vel_i"], prm["vz_i"]])
    vint = jnp.clip(S.vint + igain * ev * DT_ENV, -prm["i_max"], prm["i_max"])
    acc = gain * ev + vint
    f = acc + jnp.array([0.0, 0.0, G0])[:, None]
    fz = jnp.maximum(f[2], 0.2 * G0)
    fh = jnp.hypot(f[0], f[1])
    k = jnp.minimum(1.0, fz * jnp.tan(prm["tilt_lim"]) / jnp.maximum(fh, 1e-9))
    f_des = jnp.stack([f[0] * k, f[1] * k, fz])
    far = eh > 5.0
    tgt_yaw = jnp.arctan2(e[1], e[0])
    dy = (tgt_yaw - S.yawd + jnp.pi) % (2 * jnp.pi) - jnp.pi
    yawd = jnp.where(far & (prm["yaw_lock"] < 0.5), S.yawd + jnp.clip(dy, -prm["yaw_slew"] * DT_ENV, prm["yaw_slew"] * DT_ENV), S.yawd)
    # ---- 2.5 ms loop
    vscale = S.volt / prm["vref"]
    deck_v = ship_v

    def step(_: Arr, c: Arr) -> Arr:
        p, v, q, w, om, esum, tmax = c
        om_cmd = _ctrl(prm, q, w, f_des, yawd, vscale)
        p, v, q, w, om, pe, _, zbz = _dyn(prm, p, v, q, w, om, om_cmd, wind, deck_v, dt)
        return p, v, q, w, om, esum + pe, jnp.minimum(tmax, zbz)
    go = flying[None]
    c0 = (S.p, S.v, S.q, S.w, S.om, z, jnp.ones(M))
    p, v, q, w, om, esum, zmin = lax.fori_loop(0, nsub, step, c0)
    pmean = esum / nsub
    tb = jnp.where(prm["dt_const"] > 0, nsub * prm["dt_const"], nsub * dt)           # fault: energy booked at a fixed step
    soc, qah, ewh, volt, cur = _batt(prm, S.soc, S.qah, S.ewh, jnp.where(flying, pmean, 0.0), tb)
    # ---- monitors
    tn = t + DT_ENV
    tilt = jnp.arccos(jnp.clip(zmin, -1.0, 1.0))
    rp2 = p - jnp.concatenate([ship_p + ship_v * DT_ENV, z[None]], 0)
    e2 = tgt - rp2
    eh2 = jnp.hypot(e2[0], e2[1])
    ask = jnp.hypot(vdes_h[0] - ship_v[0], vdes_h[1] - ship_v[1])
    closing = (eh - eh2) / DT_ENV
    nohead = flying & (phase <= RTL) & (eh > 5.0) & (ask > prm["stuck_cmd"]) & (closing < prm["stuck_v"])
    stuck = jnp.where(nohead, S.stuck + DT_ENV, 0.0)

    def new(cond: Arr, flag: Arr) -> Arr:
        return cond & ~flag

    n_tilt = new(flying & (tilt > prm["tilt_exc"]), S.f_tilt)
    n_batt = new(flying & (soc < prm["reserve"]), S.f_batt)
    n_stuck = new(stuck >= prm["stuck_w"], S.f_stuck)
    dead = flying & ((soc <= 0.0) | (volt < prm["vcut"]))
    landed = (phase == LAND) & (p[2] <= 0.15) & flying
    phase2 = jnp.where(dead, DEAD, jnp.where(landed, DONE, phase))
    fin = flying & (dead | landed)

    def keep(new_v: Arr, old_v: Arr) -> Arr:
        return jnp.where(go, new_v, old_v)

    wnd = jnp.hypot(wind[0], wind[1])
    return S._replace(
        p=keep(p, S.p), v=keep(v, S.v), q=keep(q, S.q), w=keep(w, S.w), om=keep(om, S.om), vint=keep(vint, S.vint), vd=keep(vdes, S.vd),
        yawd=jnp.where(flying, yawd, S.yawd), soc=jnp.where(flying, soc, S.soc), qah=qah, ewh=ewh, volt=jnp.where(flying, volt, S.volt),
        cur=cur, phase=phase2, wpi=jnp.where(flying, wpi, S.wpi), stuck=stuck,
        f_tilt=S.f_tilt | n_tilt, f_batt=S.f_batt | n_batt | (dead & ~S.f_batt), f_stuck=S.f_stuck | n_stuck,
        t_tilt=jnp.where(n_tilt, tn, S.t_tilt), t_batt=jnp.where(n_batt | (dead & ~S.f_batt), tn, S.t_batt),
        t_stuck=jnp.where(n_stuck, tn - stuck, S.t_stuck),
        tilt_max=jnp.where(flying, jnp.maximum(S.tilt_max, tilt), S.tilt_max),
        dist_max=jnp.where(flying, jnp.maximum(S.dist_max, jnp.hypot(rp2[0], rp2[1])), S.dist_max),
        t_end=jnp.where(fin, tn, S.t_end), wind_max=jnp.where(flying, jnp.maximum(S.wind_max, wnd), S.wind_max))


def _blocks(prm: dict[str, Any], S: St, wp: Arr, ship_p: Arr, ship_v: Arr, wind: Arr, t: Arr, nsub: int, dt: float) -> St:
    """K consecutive 50 ms blocks in one call (lax.scan): ship_p, ship_v (K, 2, M), wind (K, 3, M); t at the first block."""
    def body(S: St, x: Arr) -> tuple[St, None]:
        sp, sv, w, tk = x
        return _block(prm, S, wp, sp, sv, w, tk, nsub, dt), None
    S, _ = lax.scan(body, S, (ship_p, ship_v, wind, t + DT_ENV * jnp.arange(wind.shape[0])))
    return S


_blocks_jit = jax.jit(_blocks, static_argnames=("nsub", "dt"))


# ---------------------------------------------------------------------------------------------- environment glue

def lonlat(origin: XY, east: Arr, north: Arr) -> tuple[Arr, Arr]:
    """Local tangent-plane metres -> lon, lat [deg]; origin = (lon0, lat0). Fine over the ~3 km a sortie covers."""
    lon0, lat0 = origin
    lon = lon0 + np.asarray(east, float) / (M_PER_DEG * math.cos(math.radians(lat0)))
    return (lon + 180.0) % 360.0 - 180.0, lat0 + np.asarray(north, float) / M_PER_DEG


def steaming(pos0: Arr = (0.0, 0.0), speed: Arr = 0.0, to_deg: Arr = 0.0) -> Ship:
    """A ship on a straight course: ship(t) -> (2,) east, north [m] with t seconds on the caller's clock (zero at t = 0)."""
    vel = cv.vec_from_to(speed, to_deg)
    return lambda t: np.asarray(pos0, float) + vel * t


def _ship_at(ship: Ship, t: float, M: int) -> F:
    return np.broadcast_to(np.asarray(ship(t), float), (M, 2)).T.copy()


def make_wind(env: Any, origin: XY, deck_h: float, turb: Arr = None, gust: Optional[Ship] = None, hold: int = 20) -> WindFn:
    """wind_fn(k, t, pos(3,M)) -> (3,M): env.wind (east, north) at the vehicle, + turbulence time series row k (M,3) at the
    50 ms step (the last row is held if the sortie outlives it) + gust(t) -> (M,3) (gust front), both supplied by the caller.
    The mean wind is looked up every `hold` blocks (1 s) and held: the vehicle moves < 15 m in that time against a 12 km,
    hourly field, and a gridded lookup per 50 ms was most of a sortie's wall time; the fluctuations stay at 50 ms."""
    mean: dict[str, Arr] = {}

    def fn(k: int, t: float, pos: Arr) -> Arr:
        if k % hold == 0 or "w" not in mean:
            lon, lat = lonlat(origin, pos[0], pos[1])
            mean["w"] = np.asarray(env.wind(lon, lat, deck_h + pos[2], t).value, float)
        w = mean["w"]
        out = np.concatenate([w, np.zeros((w.shape[0], 1))], 1)
        if turb is not None:
            out = out + turb[:, min(k, turb.shape[1] - 1)]
        if gust is not None:
            out = out + np.asarray(gust(t), float)
        return out.T
    return fn


def wind_ref(env: Any, ship: Ship, origin: XY, t: float, height: float, M: int) -> np.ndarray:
    """Mean wind (M, 2) [m/s] at the ship, `height` above the sea, at time t."""
    sp = _ship_at(ship, t, M)
    lon, lat = lonlat(origin, sp[0], sp[1])
    return np.broadcast_to(np.asarray(env.wind(lon, lat, height, t).value, float), (M, 2))


def launch_check(env: Any, ship: Ship, t_launch: float, P: dict[str, Any], M: int, origin: XY = (0.0, 0.0), gust: Optional[Ship] = None) -> dict[str, Any]:
    """Weather gate: scrub if the mean wind at flight height over the sortie exceeds the limit, or a gust front is active at
    the ship within `gust_lookahead_min` of launch. -> dict(ok (M,), wind_ms (M,), front (M,), wind_vec (M,2))."""
    lr, so = P["launch_rule"], P["sortie"]
    h = so["deck_height_m"] + lr["wind_check_height_m"]
    ts = t_launch + np.array([0.0, 0.5, 1.0]) * so["duration_s"]
    wv = np.stack([wind_ref(env, ship, origin, t, h, M) for t in ts])
    mean = np.hypot(wv[..., 0], wv[..., 1]).mean(0)
    front = np.zeros(M, bool)
    if gust is not None:
        for s in np.arange(0.0, lr["gust_lookahead_min"] * 60.0 + 1.0, 30.0):
            g = np.asarray(gust(t_launch + s), float)
            front |= np.hypot(g[..., 0], g[..., 1]) > lr["gust_front_threshold_ms"]
    return dict(ok=(mean <= lr["max_mean_wind_ms"]) & ~front, wind_ms=mean, front=front, wind_vec=wv[0])


# ---------------------------------------------------------------------------------------------- the flux-profile pattern

def _climb(P: dict[str, Any], dh: float, up: bool = True) -> float:
    c, v = P["controller"], (P["controller"]["speed_up"] if up else P["controller"]["speed_dn"])
    return cast(float, dh / v + v / c["accel_z"])


def leg_length_m(P: dict[str, Any]) -> float:
    """Leg length that makes the still-air sortie last sortie.duration_s: climbs, turns at the corners, return, landing."""
    so, c = P["sortie"], P["controller"]
    lv, n, v = so["levels_m"], len(so["levels_m"]), so["leg_speed_ms"]
    nl = n + n % 2
    fixed = _climb(P, lv[0]) + sum(_climb(P, b - a) for a, b in zip(lv, lv[1:], strict=False))
    fixed += _climb(P, abs(lv[-1] - so["rtl_height_m"]), lv[-1] < so["rtl_height_m"])
    fixed += so["rtl_height_m"] / so["land_speed_ms"] + 3.0 + nl * v / c["accel_wp"]
    return cast(float, max((so["duration_s"] - fixed) * v / nl, 100.0))


def flux_pattern(P: dict[str, Any], heading_to_deg: Arr) -> np.ndarray:
    """Stacked legs: out at level 0, climb at the far end, back at level 1, climb at the ship, ... -> (W, 3, M) metres east,
    north, up, relative to the ship. heading_to_deg (M,) is the compass direction of the outbound leg."""
    lv, L = P["sortie"]["levels_m"], leg_length_m(P)
    e = cv.vec_from_to(L, np.atleast_1d(np.asarray(heading_to_deg, float)))      # (M, 2)
    out = []
    for i, h in enumerate(lv):
        a, b = (0.0, 1.0) if i % 2 == 0 else (1.0, 0.0)
        out += [np.column_stack([a * e, np.full(len(e), h)]), np.column_stack([b * e, np.full(len(e), h)])]
    return np.stack(out).transpose(0, 2, 1)


# ---------------------------------------------------------------------------------------------- the simulation driver

def simulate(prm: dict[str, Any], wp: Arr, ship: Ship, wind_fn: WindFn, *, M: int, t0: float, t_max: float, active: Arr = None, yaw0: Arr = 0.0,
             nsub: int = 20, dt: float = DT_PHYS, link: Optional[LinkFn] = None, rec_dt: float = 1.0) -> dict[str, Any]:
    """Fly M members from the ship's deck along waypoints wp (W, 3, M) [ship-relative], return, land. Stops when all are down."""
    assert abs(nsub * dt - DT_ENV) < 1e-12, "physics step must divide the 50 ms environment step"
    active = np.ones(M, bool) if active is None else np.asarray(active, bool)
    wp_j = jnp.asarray(wp)
    sp = _ship_at(ship, t0, M)
    S = init_state(prm, M, yaw0, active)._replace(p=jnp.asarray(np.concatenate([sp, np.zeros((1, M))])))
    f_link, t_link = np.zeros(M, bool), np.full(M, np.nan)
    tr: dict[str, list[Any]] = dict(t=[], pos=[], soc=[], tilt=[], phase=[], ewh=[])
    every = max(int(round(rec_dt / DT_ENV)), 1)
    nblk = int(round(t_max / DT_ENV))
    # one jitted call per record interval (`every` blocks): the mean wind is held over it anyway (make_wind), and a Python
    # round trip + device sync per 50 ms block was most of a sortie's wall time
    for k0 in range(0, nblk, every):
        ks = range(k0, min(k0 + every, nblk))
        sps = [sp] + [_ship_at(ship, t0 + (k + 1) * DT_ENV, M) for k in ks]
        pos = np.asarray(S.p)
        wind = np.stack([np.asarray(wind_fn(k, t0 + k * DT_ENV, pos), float) for k in ks])
        S = _blocks_jit(prm, S, wp_j, jnp.asarray(np.stack(sps[:-1])), jnp.asarray(np.diff(np.stack(sps), axis=0) / DT_ENV), jnp.asarray(wind),
                        k0 * DT_ENV, nsub=nsub, dt=dt)
        sp = sps[-1]
        t = ks[-1] * DT_ENV
        phase = np.asarray(S.phase)
        rel = (np.asarray(S.p) - np.concatenate([sp, np.zeros((1, M))])).T
        if link is not None:
            lost = np.asarray(link(t0 + t + DT_ENV, rel), bool) & (phase < DONE)
            t_link = np.where(lost & ~f_link, t + DT_ENV, t_link)
            f_link |= lost
        tr["t"].append(t + DT_ENV)
        tr["pos"].append(rel)
        tr["soc"].append(np.asarray(S.soc))
        tr["tilt"].append(np.degrees(np.arccos(np.clip(np.asarray(_axes(S.q)[2][2]), -1, 1))))
        tr["phase"].append(phase)
        tr["ewh"].append(np.asarray(S.ewh))
        if (phase >= DONE).all():
            break
    ph = np.asarray(S.phase)
    flags = dict(battery_reserve=np.asarray(S.f_batt), wind_exceeds_airspeed=np.asarray(S.f_stuck),
                 attitude_exceedance=np.asarray(S.f_tilt), lost_link=f_link)
    t_first = dict(battery_reserve=np.asarray(S.t_batt), wind_exceeds_airspeed=np.asarray(S.t_stuck),
                   attitude_exceedance=np.asarray(S.t_tilt), lost_link=t_link)
    return dict(flags=flags, t_first=t_first, landed=(ph == DONE) & active, ditched=ph == DEAD, airborne=(ph < DONE),
                t_end=np.where(np.isnan(np.asarray(S.t_end)), t + DT_ENV, np.asarray(S.t_end)), energy_wh=np.asarray(S.ewh),
                soc_end=np.asarray(S.soc), max_tilt_deg=np.degrees(np.asarray(S.tilt_max)), max_dist_m=np.asarray(S.dist_max),
                max_wind_ms=np.asarray(S.wind_max), final=S, track=dict(t=np.array(tr["t"]), pos_rel=np.stack(tr["pos"], 1),
                                                                         soc=np.stack(tr["soc"], 1), tilt_deg=np.stack(tr["tilt"], 1),
                                                                         phase=np.stack(tr["phase"], 1), ewh=np.stack(tr["ewh"], 1)))


def fly_sortie(env: Any, ship: Ship, t_launch: float, *, M: int, origin: XY = (0.0, 0.0), plat: Optional[dict[str, Any]] = None, turb: Arr = None,
               gust: Optional[Ship] = None, link: Optional[LinkFn] = None, scale: Optional[dict[str, Any]] = None, fault: Optional[str] = None,
               dt: float = DT_PHYS, wp: Arr = None, heading_deg: Arr = None) -> dict[str, Any]:
    """One sortie for M ensemble members, vectorized. `ship(t) -> (2,) or (M, 2)` east/north metres (see steaming), `t` on the
    same clock as t_launch and the env. turb (M, n, 3) at 50 ms and gust(t) -> (M, 3) are the caller's perturbations.
    link(t, pos_rel (M,3)) -> bool (M,) lost? is the caller's link model (None: lost_link is never set); scale: see derive.
    -> dict: flags / t_first (s after launch) per FLAGS, scrubbed, failed, landed, ditched, energy_wh, soc_end, max_tilt_deg,
    max_dist_m, track (1 Hz positions relative to the ship: use them for links), launch (the weather gate's numbers)."""
    P = plat or load_platform()
    so = P["sortie"]
    if turb is not None and turb.shape[1] * DT_ENV < so["duration_s"] + 60.0:
        raise ValueError(f"turbulence series covers {turb.shape[1] * DT_ENV:.0f} s, the sortie needs {so['duration_s'] + 60.0:.0f} s")
    gate = launch_check(env, ship, t_launch, P, M, origin, gust)
    sp = _ship_at(ship, t_launch, M)
    lon, lat = lonlat(origin, sp[0], sp[1])
    air = env.air(lon, lat, t_launch)
    rho = air_density(np.asarray(air["psfc"].value, float), np.asarray(air["T2"].value, float), np.asarray(air["q2"].value, float))
    prm = derive(P, M, rho, scale, fault)
    hd = np.asarray(heading_deg if heading_deg is not None else (cv.to_deg(-gate["wind_vec"]) if so["leg_heading"] == "upwind" else so["leg_heading"]), float)
    pat = flux_pattern(P, np.broadcast_to(hd, (M,))) if wp is None else np.asarray(wp, float)
    yaw0 = np.radians(90.0 - np.broadcast_to(hd, (M,)))                                   # compass -> math angle
    out: dict[str, Any] = {}
    if gate["ok"].any():
        out = simulate(prm, pat, ship, make_wind(env, origin, so["deck_height_m"], turb, gust), M=M, t0=t_launch,
                       t_max=so["duration_s"] * so["hard_stop_factor"], active=gate["ok"], yaw0=yaw0, dt=dt, nsub=int(round(DT_ENV / dt)), link=link)
        out["flags"] = {k: v & gate["ok"] for k, v in out["flags"].items()}
        out["t_first"] = {k: np.where(out["flags"][k], v, np.nan) for k, v in out["t_first"].items()}
    else:
        z, zb = np.zeros(M), np.zeros(M, bool)
        out = dict(flags={k: zb.copy() for k in FLAGS}, t_first={k: np.full(M, np.nan) for k in FLAGS}, landed=zb.copy(), ditched=zb.copy(),
                   airborne=zb.copy(), t_end=z, energy_wh=z, soc_end=np.ones(M), max_tilt_deg=z, max_dist_m=z, max_wind_ms=z,
                   track=dict(t=np.zeros(0), pos_rel=np.zeros((M, 0, 3)), **{k: np.zeros((M, 0)) for k in ("soc", "tilt_deg", "phase", "ewh")}))
    out.pop("final", None)
    out.update(t_launch=t_launch, scrubbed=~gate["ok"], launch=gate, failed=np.any([out["flags"][k] for k in FLAGS], 0))
    return out


def fly_mission(env: Any, ship: Ship, launch_times: Arr, *, M: int, **kw: Any) -> dict[str, Any]:
    """N sorties (each on a fresh pack: sortie.battery_swap) -> dict(sorties=[fly_sortie results], mission=per-member roll-up):
    n_scrubbed / n_flown / n_failed / n_landed, flags (any sortie), t_first (earliest absolute time per flag), failed,
    first_failure (time, mode index into FLAGS)."""
    sorties = [fly_sortie(env, ship, float(t), M=M, **kw) for t in launch_times]
    flags = {k: np.any([s["flags"][k] for s in sorties], 0) for k in FLAGS}
    ta = {k: np.where(np.isnan(a := np.stack([s["t_first"][k] + s["t_launch"] for s in sorties])), np.inf, a).min(0) for k in FLAGS}
    tf = {k: np.where(np.isfinite(v), v, np.nan) for k, v in ta.items()}
    allt = np.stack([ta[k] for k in FLAGS])
    first = np.where(np.isfinite(allt.min(0)), allt.min(0), np.nan)
    mission = dict(n_scrubbed=np.sum([s["scrubbed"] for s in sorties], 0), n_flown=np.sum([~s["scrubbed"] for s in sorties], 0),
                   n_failed=np.sum([s["failed"] for s in sorties], 0), n_landed=np.sum([s["landed"] for s in sorties], 0), flags=flags,
                   t_first=tf, failed=np.any([s["failed"] for s in sorties], 0), first_failure_t=first,
                   first_failure_mode=np.where(np.isnan(first), -1, allt.argmin(0)))
    return dict(sorties=sorties, mission=mission)


# ---------------------------------------------------------------------------------------------- ArduCopter SITL (JSON backend)

_dyn_jit = jax.jit(_dyn)
_batt_jit = jax.jit(_batt)
_QC = np.array([0.0, math.sqrt(0.5), math.sqrt(0.5), 0.0])      # ENU -> NED as a rotation (180 deg about (1,1,0)/sqrt2)
_QB = np.array([0.0, 1.0, 0.0, 0.0])                            # FLU -> FRD (180 deg about x)


def _qm(a: Arr, b: Arr) -> Arr:
    return np.asarray(_qmul(jnp.asarray(a)[:, None], jnp.asarray(b)[:, None]))[:, 0]


def sitl_params(P: dict[str, Any], rate_scale: float = 1.0, **extra: Any) -> dict[str, Any]:
    """ArduCopter parameters that tell the firmware what it flies (emulator.py's firmware_params recipe, from this yaml).
    ArduCopter's default rate gains assume a ~1 kg frame; for a 0.77 kg racing frame (J = 0.0025) they put the rate loop
    far above the 33 ms motor pole and it goes unstable, so P is set from the airframe's control authority: ArduPilot's mixer
    moves each motor's thrust by 0.707 x (roll or pitch output) or 1 x (yaw output) of the maximum thrust, times the motor arm.
    MOT_THST_HOVER is a thrust fraction (not a throttle). WP_YAW_BEHAVIOR=0 keeps the nose where it is: with the firmware turning
    toward each leg its EKF flags 'GPS Glitch or Compass error' and the return diverged in 3 of 4 trials, with a fixed heading it did not."""
    ro, co, li, af = P["rotor"], P["controller"], P["limits"], P["airframe"]
    f_h = af["mass_kg"] * G0 / 4 / ro["thrust_max_n_each"]                 # hover thrust as a fraction of max: ArduPilot's MOT_THST_HOVER units
    dtdu = ro["thrust_max_n_each"]                                         # N of thrust per unit of mixer output
    arm = af["motor_radius_m"] / math.sqrt(2)
    om = ro["omega_max_rpm"] * 2 * math.pi / 60
    kt = ro["thrust_max_n_each"] / om ** 2
    cq = kt ** 0.5 / (math.sqrt(2 * 1.2 * math.pi * ro["prop_diameter_m"] ** 2 / 4) * ro["figure_of_merit"])      # kQ / kT [m]
    jx, jy, jz = af["inertia_kgm2"]
    rate = rate_scale * co["rate_p"]
    gain = dict(RLL=rate * jx / (4 * arm * 0.7071 * dtdu), PIT=rate * jy / (4 * arm * 0.7071 * dtdu), YAW=0.5 * rate * jz / (4 * cq * dtdu))
    pid: dict[str, float] = {}
    for ax, pk in gain.items():
        yaw = ax == "YAW"                                   # ArduCopter defaults: I = P (yaw: 0.1 P), D = 0.027 P (yaw: none)
        pid.update({f"ATC_RAT_{ax}_P": round(pk, 5), f"ATC_RAT_{ax}_I": round(pk * (0.1 if yaw else 1.0), 5),
                    f"ATC_RAT_{ax}_D": 0.0 if yaw else round(0.027 * pk, 6)})
    return dict(SIM_RATE_HZ=round(1 / DT_PHYS), SCHED_LOOP_RATE=200, ARMING_CHECK=0, BATT_MONITOR=4, FRAME_CLASS=1, FRAME_TYPE=1,
                MOT_PWM_MIN=1000, MOT_PWM_MAX=2000, MOT_SPIN_ARM=0.02, MOT_SPIN_MIN=0.03, MOT_SPIN_MAX=1.0, MOT_THST_EXPO=0.98,
                MOT_THST_HOVER=round(f_h, 3), MOT_HOVER_LEARN=2, MOT_BAT_VOLT_MAX=4.2 * P["battery"]["cells"],
                MOT_BAT_VOLT_MIN=3.3 * P["battery"]["cells"], WPNAV_SPEED=int(P["sortie"]["leg_speed_ms"] * 100),
                WPNAV_ACCEL=int(co["accel_wp"] * 100), WPNAV_SPEED_UP=int(co["speed_up"] * 100), WPNAV_SPEED_DN=int(co["speed_dn"] * 100),
                WPNAV_RADIUS=int(P["sortie"]["wp_radius_m"] * 100), ANGLE_MAX=int(li["max_tilt_deg"] * 100), FENCE_ENABLE=0,
                WP_YAW_BEHAVIOR=0, FS_THR_ENABLE=0, FS_GCS_ENABLE=0, ATC_ANG_RLL_P=co["att_p"], ATC_ANG_PIT_P=co["att_p"],
                ATC_ANG_YAW_P=co["att_p"], **pid) | extra


class _Sim1:
    """One member's physics answering ArduCopter's servo packets (lockstep: one 2.5 ms step per new frame)."""

    def __init__(self, P: dict[str, Any], prm: dict[str, Any], wind_fn: WindFn, home_en: Arr, link_motor_map: Arr) -> None:
        self.P, self.prm, self.wind_fn, self.home, self.map = P, prm, wind_fn, home_en, list(link_motor_map)
        self.p, self.v, self.w = jnp.zeros((3, 1)), jnp.zeros((3, 1)), jnp.zeros((3, 1))
        self.q, self.om = jnp.array([[math.sqrt(0.5)], [0.0], [0.0], [math.sqrt(0.5)]]), jnp.zeros((4, 1))   # facing north
        self.soc, self.qah, self.ewh, self.volt = jnp.ones(1), jnp.zeros(1), jnp.zeros(1), prm["vref"]
        self.t, self.k, self.pe, self.sf, self.tilt, self.wind = 0.0, 0, jnp.zeros(1), jnp.array([[0.0], [0.0], [G0]]), 0.0, jnp.zeros((3, 1))
        self.pe_acc, self.n_acc, self.tilt_max = 0.0, 0, 0.0
        self.rec: list[Any] = []
        self.pos_en = np.array(home_en, float)
        self.hist: list[tuple[float, float, float, float]] = []                          # (t, roll, pitch, yaw) of the attitude we sent, every 50 ms

    def step(self, pwm: Arr) -> None:
        u = jnp.asarray(np.clip((np.asarray(pwm[:4], float)[self.map][:, None] - 1000.0) / 1000.0, 0.0, 1.0))
        cmd = u * self.prm["om_max"] * jnp.minimum(self.volt / self.prm["vref"], 1.0)
        if self.n_acc == 0:                                              # 50 ms: environment lookup, then battery for the last block
            pos = np.asarray(self.p) + np.array([[self.pos_en[0]], [self.pos_en[1]], [0.0]])
            self.wind = jnp.asarray(self.wind_fn(self.k, self.t, pos))
        self.p, self.v, self.q, self.w, self.om, self.pe, self.sf, zbz = _dyn_jit(
            self.prm, self.p, self.v, self.q, self.w, self.om, cmd, self.wind, jnp.zeros((2, 1)), DT_PHYS)
        self.t += DT_PHYS
        self.pe_acc += float(self.pe[0])
        self.n_acc += 1
        self.tilt = math.acos(max(-1.0, min(1.0, float(zbz[0]))))
        self.tilt_max = max(self.tilt_max, self.tilt)
        if self.n_acc == round(DT_ENV / DT_PHYS):
            self.soc, self.qah, self.ewh, self.volt, _ = _batt_jit(self.prm, self.soc, self.qah, self.ewh, jnp.array([self.pe_acc / self.n_acc]), DT_ENV)
            self.pe_acc, self.n_acc, self.k = 0.0, 0, self.k + 1
            self.hist.append((self.t,) + self.rpy())

    def rpy(self) -> tuple[float, float, float]:
        """Roll, pitch, yaw [rad] of the NED/FRD attitude ArduPilot is told (what its ATTITUDE message should echo)."""
        w, x, y, z = _qm(_qm(_QC, np.asarray(self.q, float)[:, 0]), _QB)
        return (math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y)), math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x)))),
                math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))

    def reply(self) -> bytes:
        """JSON state for ArduPilot: NED/FRD, field order as emulator.py found the parser needs it."""
        q = np.asarray(self.q, float)[:, 0]
        qn = _qm(_qm(_QC, q), _QB)
        v, w, sf, p = (np.asarray(x, float)[:, 0] for x in (self.v, self.w, self.sf, self.p))
        volt = float(self.volt[0])
        return (json.dumps(dict(timestamp=self.t, imu=dict(gyro=[w[0], -w[1], -w[2]], accel_body=[sf[0], -sf[1], -sf[2]]),
                                position=[p[1], p[0], -p[2]], quaternion=qn.tolist(), velocity=[v[1], v[0], -v[2]],
                                battery=dict(voltage=volt, current=float(self.pe[0]) / volt))) + "\n").encode()


def fly_sitl(env: Any, ship: Ship, t_launch: float, *, origin: XY = (0.0, 0.0), plat: Optional[dict[str, Any]] = None, wp: Arr = None, turb: Arr = None,
             gust: Optional[Ship] = None, member: int = 0, scale: Optional[dict[str, Any]] = None, max_s: Optional[float] = None,
             instance: Optional[int] = None, motor_map: tuple[int, ...] = (0, 1, 2, 3), workdir: Optional[str] = None, land: bool = True, hold_s: float = 0.0,
             firmware: Optional[dict[str, Any]] = None, boot_s: float = 20.0, patience_s: float = 60.0) -> dict[str, Any]:
    """Fly ONE member of the sortie with ArduCopter SITL (JSON external physics) at our 2.5 ms step: firmware controllers, our
    physics, wind/turbulence/gust from `env`/`turb`/`gust` (SIM_JSON ignores SIM_WIND_*). Lockstep on our timestamp, no SIM_SPEEDUP,
    so it runs in real time; run members in parallel with distinct `instance`. wp (W,3) ship-relative; default is the flux pattern.
    boot_s / patience_s: sim seconds allowed for the EKF to settle and for each of mode change, arming and take-off. Raises
    SitlUnavailable when the binary is missing. -> same fields as fly_sortie for one member plus sitl=dict(instance, messages)."""
    try:
        from cafe import emulator
    except Exception as e:                                                # pragma: no cover  (the cafe image always has it)
        raise SitlUnavailable(f"cafe.emulator cannot be imported ({e!r}): the SITL socket machinery lives there") from e
    exe = pathlib.Path(emulator.SITL_DIR) / "arducopter"
    if not exe.exists():
        raise SitlUnavailable(SITL_HELP.format(path=exe))
    from pymavlink import mavutil
    P = plat or load_platform()
    so = P["sortie"]
    ship0 = np.asarray(ship(t_launch), float).reshape(-1)[:2]
    lon0, lat0 = lonlat(origin, ship0[0], ship0[1])
    air = env.air(np.atleast_1d(lon0), np.atleast_1d(lat0), t_launch)
    rho = air_density(float(np.ravel(air["psfc"].value)[0]), float(np.ravel(air["T2"].value)[0]), float(np.ravel(air["q2"].value)[0]))
    prm = derive(P, 1, rho, {k: np.asarray(v)[member] if np.ndim(v) else v for k, v in (scale or {}).items()})
    if wp is None:
        w0 = wind_ref(env, ship, origin, t_launch, so["deck_height_m"] + 30.0, 1)
        wp = flux_pattern(P, cv.to_deg(-w0))[:, :, 0]
    wp = np.asarray(wp, float)
    t1 = None if turb is None else turb[member:member + 1]
    g1 = None if gust is None else (lambda t: np.asarray(gust(t), float)[member][None])
    wfn = make_wind(env, origin, so["deck_height_m"], t1, g1)
    inst = emulator.free_instance(set()) if instance is None else instance
    wd = pathlib.Path(workdir or f"/tmp/uas_sitl{inst}")
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "uas.parm").write_text("".join(f"{k} {v}\n" for k, v in sitl_params(P, **(firmware or {})).items()))
    sd = pathlib.Path(emulator.SITL_DIR)
    defaults = ",".join([str(sd / "copter.parm"), str(sd / "copter-X.parm"), str(wd / "uas.parm")])
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 9002 + 10 * inst))
    proc = subprocess.Popen([str(exe), "-w", "--model", "JSON:127.0.0.1", "-I", str(inst), "--sysid", str(inst + 1), "--home",
                             f"{SITL_HOME[1]:.7f},{SITL_HOME[0]:.7f},{so['deck_height_m']:.2f},0", "--defaults", defaults], cwd=wd,
                            stdout=open(wd / "sitl.out", "w"), stderr=subprocess.STDOUT)
    sim = _Sim1(P, prm, wfn, ship0, motor_map)
    cap = max_s if max_s is not None else so["duration_s"] * so["hard_stop_factor"]
    stop = threading.Event()
    notes: list[str] = []
    att: list[tuple[Any, ...]] = []
    tr: dict[str, list[Any]] = dict(t=[], pos=[], soc=[], tilt=[], ewh=[])
    box: dict[str, Any] = dict(armed=False, mode=None, err=None)

    def commander() -> None:
        try:
            m = None
            while m is None:                                              # SITL listens only once it has started; stop looking when told to
                if stop.is_set():
                    return
                try:
                    m = mavutil.mavlink_connection(f"tcp:127.0.0.1:{5760 + 10 * inst}", source_system=250)
                except OSError:
                    time.sleep(0.5)
            hb = None
            while hb is None:
                if stop.is_set():
                    return
                if sim.t > boot_s + patience_s:
                    raise RuntimeError("no MAVLink heartbeat from the autopilot")
                hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
            m.target_system, m.target_component = hb.get_srcSystem(), hb.get_srcComponent()
            mav = mavutil.mavlink
            m.mav.request_data_stream_send(m.target_system, m.target_component, mav.MAV_DATA_STREAM_ALL, 4, 1)

            def drain() -> None:
                while (msg := m.recv_match(blocking=False)) is not None:
                    ty = msg.get_type()
                    if ty == "HEARTBEAT" and msg.get_srcSystem() == m.target_system:
                        box["armed"], box["mode"] = bool(msg.base_mode & 128), msg.custom_mode
                    elif ty == "STATUSTEXT":
                        notes.append(f"{sim.t:.1f}s {msg.text}")
                    elif ty == "ATTITUDE":
                        i = max(int(np.searchsorted([h[0] for h in sim.hist], msg.time_boot_ms / 1000.0)) - 1, 0) if sim.hist else 0
                        att.append((msg.time_boot_ms / 1000.0, msg.roll, msg.pitch, msg.yaw) + (sim.hist[i][1:] if sim.hist else (0.0, 0.0, 0.0)))

            def wait_sim(s: float) -> None:
                t_end = sim.t + s
                while sim.t < t_end and not stop.is_set():
                    time.sleep(0.02)
                    drain()

            def until(cond: Callable[[], Any], s: float, what: str, action: Callable[[], Any]) -> None:
                t_end = sim.t + s
                while not cond():
                    if sim.t > t_end:
                        raise RuntimeError(f"autopilot would not {what} (it said: {'; '.join(notes[-3:]) or 'nothing'})")
                    action()
                    wait_sim(2)

            def goto(rel: Arr, tol_h: float, tol_v: float, limit_s: float) -> None:
                t_end = sim.t + limit_s
                while sim.t < t_end and not stop.is_set():
                    tgt = np.append(np.asarray(ship(t_launch + sim.t), float)[:2], 0.0) + rel
                    lo, la = lonlat(SITL_HOME, tgt[0] - ship0[0], tgt[1] - ship0[1])      # the firmware lives around its own home
                    m.mav.set_position_target_global_int_send(0, m.target_system, m.target_component, 6, 0b0000111111111000,
                                                              int(la * 1e7), int(lo * 1e7), float(tgt[2]), 0, 0, 0, 0, 0, 0, 0, 0)
                    pos = np.asarray(sim.p)[:, 0]
                    if math.hypot(*(pos[:2] - tgt[:2])) < tol_h and abs(pos[2] - tgt[2]) < tol_v:
                        return
                    wait_sim(0.5)

            wait_sim(boot_s)                                             # GPS lock + EKF settle, in sim time
            until(lambda: box["mode"] == 4, patience_s, "switch to GUIDED", lambda: m.mav.command_long_send(
                m.target_system, m.target_component, mav.MAV_CMD_DO_SET_MODE, 0, mav.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, 4, 0, 0, 0, 0, 0))
            until(lambda: box["armed"], patience_s, "arm", lambda: m.mav.command_long_send(
                m.target_system, m.target_component, mav.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, 21196, 0, 0, 0, 0, 0))
            until(lambda: float(sim.p[2, 0]) > 3.0, patience_s, "take off", lambda: m.mav.command_long_send(
                m.target_system, m.target_component, mav.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, float(wp[0, 2])))
            for w_ in wp:
                goto(w_, so["wp_radius_m"], 2.0, 4 * so["duration_s"])
            for _ in range(int(hold_s / 0.5)):                             # hold the last waypoint (still commanding it)
                goto(wp[-1], 0.0, 0.0, 0.5)
            if land:
                goto(np.array([0.0, 0.0, so["rtl_height_m"]]), 2.0, 2.0, 600)
                goto(np.array([0.0, 0.0, 0.0]), 2.0, 0.3, 120)
        except Exception as e:
            box["err"] = f"{type(e).__name__}: {e}"
        finally:
            stop.set()
    th = threading.Thread(target=commander, daemon=True)
    th.start()
    last_fc, last_rec = -1, -1.0
    try:
        while not stop.is_set() and sim.t < cap:
            r, _, _ = select.select([sock], [], [], 0.5)
            if not r:
                if proc.poll() is not None:
                    raise RuntimeError(f"arducopter exited with code {proc.returncode}; see {wd / 'sitl.out'}")
                continue
            data, addr = sock.recvfrom(256)
            if len(data) == 40:
                magic, _, fc, *pwm = struct.unpack("<HHI16H", data)
            elif len(data) == 72:
                magic, _, fc, *pwm = struct.unpack("<HHI32H", data)
            else:
                continue
            if magic not in (18458, 29569):
                continue
            if fc != last_fc:
                sim.step(pwm)
                last_fc = fc
                if sim.t - last_rec >= 1.0:
                    last_rec = sim.t
                    p = np.asarray(sim.p)[:, 0]
                    tr["t"].append(sim.t)
                    tr["pos"].append(p - np.append(np.asarray(ship(t_launch + sim.t), float)[:2], 0.0))
                    tr["soc"].append(float(sim.soc[0]))
                    tr["tilt"].append(math.degrees(sim.tilt))
                    tr["ewh"].append(float(sim.ewh[0]))
            sock.sendto(sim.reply(), addr)
    finally:
        stop.set()
        th.join(timeout=5)
        proc.kill()                                                       # SITL ignores SIGTERM while it waits on a reply
        proc.wait(timeout=10)
        sock.close()
    if box["err"]:
        raise RuntimeError(f"SITL member failed: {box['err']}; autopilot said: {'; '.join(notes[-5:])}")
    soc, tilt = float(sim.soc[0]), math.degrees(sim.tilt_max)
    flags = dict(battery_reserve=np.array([soc < P["battery"]["reserve_frac"]]), wind_exceeds_airspeed=np.zeros(1, bool),
                 attitude_exceedance=np.array([tilt > P["limits"]["tilt_exceedance_deg"]]), lost_link=np.zeros(1, bool))
    return dict(flags=flags, t_end=np.array([sim.t]), energy_wh=np.array([float(sim.ewh[0])]), soc_end=np.array([soc]),
                max_tilt_deg=np.array([tilt]), landed=np.array([float(sim.p[2, 0]) < 0.3 and sim.t > 30.0]), scrubbed=np.zeros(1, bool),
                track=dict(t=np.array(tr["t"]), pos_rel=np.array(tr["pos"])[None], soc=np.array(tr["soc"])[None], tilt_deg=np.array(tr["tilt"])[None],
                           ewh=np.array(tr["ewh"])[None]), sitl=dict(instance=inst, messages=notes, workdir=str(wd), attitude=np.array(att).reshape(-1, 7)))


# ---------------------------------------------------------------------------------------------- receipts

def _scenario(P: dict[str, Any], M: int, wp: Arr, wind: Arr, *, fault: Optional[str] = None, scale: Optional[dict[str, Any]] = None,
              v_leg: Arr = None, lock: Arr = None, yaw0: Arr = 0.0, t_max: float = 60.0, nsub: int = 20,
              dt: float = DT_PHYS) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fly M members on a fixed (3, M) wind and a fixed ship; -> (simulate() result, prm). For receipts."""
    prm = derive(P, M, 1.2, scale, fault)
    if v_leg is not None:
        prm["v_leg"] = jnp.asarray(np.broadcast_to(np.asarray(v_leg, float), (M,)).copy())
    if lock is not None:
        prm["yaw_lock"] = jnp.asarray(np.broadcast_to(np.asarray(lock, float), (M,)).copy())
    w = np.broadcast_to(np.asarray(wind, float).reshape(3, -1), (3, M)).copy()
    r = simulate(prm, wp, lambda t: np.zeros(2), lambda k, t, pos: w, M=M, t0=0.0, t_max=t_max, yaw0=yaw0, nsub=nsub, dt=dt)
    return r, prm


def _hold(h: float, M: int, x: float = 0.0) -> np.ndarray:
    """A hover point repeated so the sortie never reaches 'last waypoint' during a receipt."""
    return np.broadcast_to(np.array([x, 0.0, h])[None, :, None], (4000, 3, M)).copy()


def receipts(plat: Optional[dict[str, Any]] = None, fault: Optional[str] = None, sitl: bool = True,
             sortie: bool = True) -> list[dict[str, Any]]:
    """Reproduce what the literature says about this model and say so through cafe.receipts (each one can fail).
    `fault` breaks one piece of the physics on purpose (wind_sign, no_drag, fm, peukert, dt_const, sitl_motor_order) so the
    tests can show the matching receipt then fails. sitl / sortie switch off the real-time ArduCopter run and the 20 min sortie
    (the two slow ones). -> the receipt dicts added by this call."""
    from cafe import receipts as R
    n0 = len(R.OUT)
    P = plat or load_platform()
    af, ro, ae, ba, so = P["airframe"], P["rotor"], P["aero"], P["battery"], P["sortie"]
    m, area = af["mass_kg"], math.pi * ro["prop_diameter_m"] ** 2 / 4

    # 1. hover power: momentum theory with a figure of merit (Leishman 2006 Ch. 2); a 25 % heavier member checks the T^1.5 law
    r, prm = _scenario(P, 2, _hold(10.0, 2), np.zeros(3), scale=dict(mass=[1.0, 1.25]), fault=fault, t_max=40.0)
    ewh = r["track"]["ewh"]
    p_el = (ewh[:, -1] - ewh[:, -11]) * 3600.0 / 10.0
    thrust = np.asarray(prm["kT"]) * np.sum(np.asarray(r["final"].om) ** 2, 0)
    p_mech = (p_el - np.asarray(prm["hotel"])) * np.asarray(prm["eff"])
    fm = thrust ** 1.5 / np.sqrt(2 * 1.2 * 4 * area) / p_mech
    src = "Leishman, Principles of Helicopter Aerodynamics 2e (2006) Ch. 2: P_ideal = T^1.5 / sqrt(2 rho A), FM = P_ideal / P"
    receipt, bracket, context = R.receipt, R.bracket, R.context
    receipt("UAS propulsion", "hover thrust equals weight", thrust[0], m * G0, 0.01, "N", "Newton; hover after 40 s of the position loop")
    receipt("UAS propulsion", "hover figure of merit from simulated thrust and power vs the identified FM", fm[0], ro["figure_of_merit"], 0.02, "-", src)
    bracket("UAS propulsion", "hover figure of merit inside the small-rotor band", fm[0], 0.40, 0.70, "-",
            "Leishman 2006 Ch. 2; Bohorquez et al., J. AHS 48(2), 2003")
    receipt("UAS propulsion", "mechanical hover power ratio of a 25 % heavier member", p_mech[1] / p_mech[0], 1.25 ** 1.5, 0.02, "-",
            "momentum theory: P ~ T^1.5")

    # 2. rotor drag: steady tilt tan(theta) = d v / g (Faessler et al. 2018, Eq. 2 with a = 0: x_B . (g z_W + d_x v) = 0), and wind = airspeed
    wind = np.zeros((3, 4))
    wind[0, 3] = 8.0
    wp = np.concatenate([np.broadcast_to(np.array([5000.0, 0.0, 10.0])[None, :, None], (3000, 3, 3)), _hold(10.0, 1)[:3000]], 2)
    r, prm = _scenario(P, 4, wp, wind, fault=fault, v_leg=[8.0, 4.0, 4.0, 8.0], lock=[0, 0, 1, 0], yaw0=np.array([0, 0, np.pi / 2, 0.0]), t_max=60.0)
    S = r["final"]
    zb = np.asarray(_axes(S.q)[2])
    tilt = np.degrees(np.arccos(zb[2]))
    v = np.asarray(S.v)
    f18 = "Faessler, Franchi, Scaramuzza, IEEE RA-L 3(2) 2018, Eq. (2)/(7); d_x, d_y from Sec. VII-C"
    for i, (nm, d) in enumerate([("forward at 8 m/s", ae["d_x"]), ("forward at 4 m/s", ae["d_x"]), ("sideways at 4 m/s", ae["d_y"])]):
        sp = float(np.hypot(v[0, i], v[1, i]))
        receipt("UAS rotor drag", f"steady tilt {nm}: atan(d v / g)", tilt[i], math.degrees(math.atan(d * sp / G0)), 0.03, "deg", f18)
    receipt("UAS rotor drag", "hover in an 8 m/s wind leans as far as flying 8 m/s in still air", tilt[3], tilt[0], 0.04, "deg",
            "v_rel = v - wind: the rotors only feel the air-relative velocity")
    bracket("UAS rotor drag", "hover in a wind blowing east leans west (into the wind): z_B east component", zb[0, 3], -1.0, -0.2, "-",
            "the drag force on the airframe points downwind, so the thrust must point upwind")

    # 3. Peukert: discharge time at constant current scales as I^-P (Peukert 1897; t = H (C / (I H))^P)
    cap, k = ba["energy_wh"] / (ba["cells"] * ba["v_nom_cell"]), ba["peukert_exponent"]
    pk = derive(P, 2, 1.2, None, fault)
    cur = jnp.array([2.0, 6.0])
    soc, qah, ew = jnp.ones(2), jnp.zeros(2), jnp.zeros(2)
    t_dead, t = np.zeros(2), 0.0
    while t < 4 * 3600.0 and (t_dead == 0).any():
        voc = pk["ncell"] * jnp.interp(soc, pk["ocv_x"], pk["ocv_y"])
        soc, qah, ew, _, _ = _batt_jit(pk, soc, qah, ew, (voc - cur * pk["rint"]) * cur, 2.0)
        t += 2.0
        t_dead = np.where((t_dead == 0) & (np.asarray(soc) <= 0), t, t_dead)

    def ref(i: float) -> float:
        return cast(float, ba["peukert_hours"] * 3600.0 * (cap / (i * ba["peukert_hours"])) ** k)

    receipt("UAS battery", "discharge time at 2 A vs Peukert t = H (C/(I H))^P", t_dead[0], ref(2.0), 0.01, "s",
            "Peukert 1897; P = 1.05 from docs/BRIEF.md 2.4")
    receipt("UAS battery", "discharge time ratio 2 A : 6 A vs (6/2)^P", t_dead[0] / t_dead[1], 3.0 ** k, 0.01, "-",
            "Peukert 1897; Doerffel & Sharkh, J. Power Sources 155, 2006")

    # 4. time-step convergence 2.5 ms vs 1.25 ms
    wp2 = np.stack([np.array([[0.0], [0.0], [10.0]]), np.array([[300.0], [0.0], [10.0]])])
    e: list[tuple[float, Arr]] = []
    for nsub, dt in ((20, 0.0025), (40, 0.00125)):
        rr, _ = _scenario(P, 1, wp2, np.zeros(3), fault=fault, t_max=40.0, nsub=nsub, dt=dt)
        e.append((float(rr["energy_wh"][0]), np.asarray(rr["final"].p)[:, 0]))
    receipt("UAS time step", "energy of a 40 s climb + leg at 2.5 ms vs 1.25 ms", e[0][0], e[1][0], 0.005, "Wh", "step-halving; docs/BRIEF.md 3 asks 0.5 %")
    context("UAS time step", "position difference between the two steps after 40 s [m]", float(np.linalg.norm(e[0][1] - e[1][1])), 0.0, "m", "step-halving")

    # 5. the whole nominal sortie in still air
    if sortie:
        from ..env.protocol import AnalyticEnv
        rs = fly_sortie(AnalyticEnv(wind=(0.0, 0.0)), steaming(), 0.0, M=1, plat=P, fault=fault)
        bracket("UAS sortie", "still-air sortie, launch to touchdown", float(rs["t_end"][0]), 0.95 * so["duration_s"], 1.05 * so["duration_s"], "s",
                "sortie.duration_s (docs/BRIEF.md 6: 20 min)")
        bracket("UAS sortie", "state of charge at touchdown is above the reserve and the pack was used", float(rs["soc_end"][0]), ba["reserve_frac"], 0.6,
                "-", "battery.reserve_frac")

    # 6. ArduCopter SITL flying the same physics
    if sitl:
        _sitl_receipts(P, fault, R)
    return R.OUT[n0:]


def _sitl_receipts(P: dict[str, Any], fault: Optional[str], R: Any) -> None:
    """ArduCopter SITL vs our controller on the same hover + 60 m leg + return + landing, no wind."""
    from ..env.protocol import AnalyticEnv
    env = AnalyticEnv(wind=(0.0, 0.0))
    wp = np.array([[0.0, 0.0, 10.0], [60.0, 0.0, 10.0]])
    grp = "UAS SITL vs our controller"
    try:
        s = fly_sitl(env, steaming(), 0.0, origin=(-165.0, 0.0), plat=P, wp=wp, hold_s=15.0, max_s=240.0,
                     motor_map=(3, 2, 1, 0) if fault == "sitl_motor_order" else (0, 1, 2, 3))
    except SitlUnavailable as e:
        R.context(grp, "SITL members run (0: binary absent, " + str(e)[:80] + ")", 0.0, 0.0, "members", "cafe/emulator.py SITL_DIR")
        return
    except RuntimeError as e:
        R.bracket(grp, "ArduCopter flew the sortie (inf: it did not: " + str(e)[:80] + ")", float("inf"), 0.0, 0.0, "m", "SITL JSON backend")
        return
    stay = np.concatenate([wp[:1], np.repeat(wp[1:], 3000, 0)])[:, :, None]                 # climb, fly the leg, stay at its end
    ours, _ = _scenario(P, 1, stay, np.zeros(3), t_max=60.0, lock=1.0, yaw0=math.pi / 2)             # nose fixed to the north, as flown by the firmware
    tr = s["track"]
    pos, t, ew = tr["pos_rel"][0], tr["t"], tr["ewh"][0]
    near = (np.hypot(pos[:, 0] - 60.0, pos[:, 1]) < 6.0) & (np.abs(pos[:, 2] - 10.0) < 3.0)             # samples at the leg end
    err = float(np.median(np.linalg.norm(pos[near] - wp[1], axis=1))) if near.sum() > 5 else float("inf")
    R.bracket(grp, "SITL holds the leg end (median distance from it while there)", err, 0.0, 4.0, "m",
              "position band: WPNAV_RADIUS 3 m + GPS-fed control error")
    p_ours = np.asarray(ours["final"].p)[:, 0]
    R.bracket(grp, "our controller holds the same leg end", float(np.linalg.norm(p_ours - wp[1])), 0.0, 3.0, "m", "position band")
    eo = ours["track"]["ewh"][0]
    p_o = float(np.polyfit(ours["track"]["t"][-20:], eo[-20:], 1)[0] * 3600.0)
    p_s = float(np.polyfit(t[near], ew[near], 1)[0] * 3600.0) if near.sum() > 5 else float("inf")
    R.receipt(grp, "mean electrical power while holding the leg end, SITL vs our controller", p_s, p_o, 0.15, "W", "same rotors and battery, two controllers")
    att = s["sitl"]["attitude"]
    a = att[att[:, 0] > 50.0]
    dtilt = np.degrees(np.abs(np.hypot(a[:, 1], a[:, 2]) - np.hypot(a[:, 4], a[:, 5]))) if len(a) else np.array([np.inf])
    R.context(grp, "ArduPilot's tilt estimate vs the attitude we sent, mean absolute difference [deg]", float(dtilt.mean()), 0.0, "deg",
              "its EKF flags a GPS/compass glitch at the first acceleration; see the module notes")
    R.context(grp, "SITL touchdown, horizontal distance from the ship [m] (the firmware's EKF drifts on the return, 4 m to 160 m in 4 trials)",
              float(np.hypot(pos[-1, 0], pos[-1, 1])), 0.0, "m", "GUIDED descent onto the ship; see the module notes")
    R.bracket(grp, "SITL completes the descent (touchdown height above the deck)", float(pos[-1, 2]), -0.5, 0.5, "m", "GUIDED descent")
