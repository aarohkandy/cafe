"""Wing-sail USV (Saildrone Explorer class): 4-DOF steady-state VPP, added resistance in waves, Stage-1 kinematics.

What is solved.  Fossen's body-fixed form M nu' + C(nu) nu + D(nu) nu + g(eta) = tau (Fossen 2011, Handbook of Marine Craft
Hydrodynamics and Motion Control) for surge u, sway v, roll phi and yaw psi, as Xiao & Jouffroy (2014, IEEE J. Ocean.
Eng. 39(2), 256-268) apply it to a sailing yacht, at steady state (nu' = 0): the force sum in surge and sway, the heeling /
righting moment in roll and the yaw moment are each zero.  Unknowns per (true wind, heading): through-water speed V, leeway beta,
heel phi, wing depower k, rudder side force Y_r (the autopilot trims the yaw balance with the rudder).  The oracle for the
structure is Jouffroy's Simulink model named in BRIEF 2.4; it was not available here, so the structure is checked by
force-balance residuals and limiting cases (tests/test_usv.py), not against his numbers.

Frames and signs.  Body axes x forward, y to starboard.  Compass angles are degrees clockwise from north (`*_to`, `*_from`);
conversions go through cafe.pm.env.conventions.  The solve runs in a mirrored frame in which the wind (relative to the water)
comes from starboard, and un-mirrors the leeway (the hull is symmetric): the boat slips to leeward, away from the wind.

Current enters through the apparent wind.  The air velocity relative to the boat is
    w_a = w_ground - (c + v_boat_through_water)                       (`_apparent`)
so the current changes the apparent wind speed and angle and therefore the sail force.  It is not added to a still-water
answer afterwards (Sun et al. 2026 as quoted in BRIEF 2.4: current is not superposable; still-water VPPs overpredict SOG by
30-35 %).  Because hull and keel only see the water and the sail only sees the air, the solution depends on the wind relative
to the water, w - c, which is why the Stage-1 simulator reads the current-coupled speed from the still-water (TWS x TWA) table
at the relative wind (`through_water_table`); `through_water` solves it directly and the two agree (tests, receipts).

Textbook citations below are by author, year and title: chapter and equation numbers were not re-checked (formulas marked
'recalled' were written from memory and are covered by the receipts and tests, not by a re-read of the source).

Models (every constant is in platforms/saildrone_explorer.yaml with its source or its assumption):
  Wing   NACA 0015-class polar after Sheldahl & Klimas (1981, SAND80-2114): linear lift to the stall angle with the finite-wing
         slope a = a0 / (1 + a0 / (pi e AR)) (Prandtl lifting line; e.g. Anderson, Fundamentals of Aerodynamics), induced
         drag C_L^2 / (pi e AR) plus C_D0, and the post-stall plate model of Viterna & Corrigan (1982, NASA CP-2230):
         C_L = A1 sin 2a + A2 cos^2 a / sin a, C_D = B1 sin^2 a + B2 cos a, B1 = C_Dmax = 1.11 + 0.018 AR, A1 = B1/2,
         A2 = (C_Ls - C_Dmax sin as cos as) sin as / cos^2 as, B2 = (C_Ds - C_Dmax sin^2 as) / cos as.  The self-trimming
         tail holds the angle of attack at wing_trim_deg; above the heel target the controller depowers it (alpha -> k alpha).
         Heel reduces the projected area by cos(phi) (standard VPP practice, e.g. Kerwin 1978, MIT 78-11).
  Hull   ITTC-1957 correlation line C_F = 0.075 / (log10 Re - 2)^2 times (1 + k), plus a residuary term C_R = cr0 (Fr/Fr_ref)^4
         on wetted area, plus (1 + c phi^2) for heel.  Hull speed 1.34 sqrt(L_ft) kn reproduces the 3.3 m/s cap (receipt); the
         cap is applied as the top of the speed grid.
  Foils  Keel and rudder lift slope from Helmbold's low-aspect-ratio formula a = 2 pi AR / (2 + sqrt(4 + AR^2)) (Helmbold 1942;
         Hoerner & Borst 1975, Fluid-Dynamic Lift), AR doubled for the free-surface image, induced drag C_L^2 / (pi AR),
         profile drag 2 C_F (1 + 2 t/c + 60 (t/c)^4) on planform area (Hoerner 1965, Fluid-Dynamic Drag).
  Windage  Drag on the apparent wind over frontal and lateral areas (Hoerner 1965).
  Roll   Righting moment Delta g GM sin(phi); the heeling moment is the lateral force times the arm from the centre of lateral
         resistance (Larsson & Eliasson, Principles of Yacht Design, for the lever arm).
Waves.  Added resistance by Gerritsma & Beukelman (1972, Int. Shipbuilding Progress 19(217), 285-293), in the form given by
Journee & Massie (2001, Offshore Hydromechanics, TU Delft): R_aw = (k / 2 w_e) integral b'(x) |V_z(x)|^2 dx, V_z the amplitude of
the vertical velocity of the water relative to the section including the forward-speed term, b' the sectional damping
b' = rho g^2 A^2 / w_e^3 with A = 2 sin(k_e b / 2) exp(-k_e d) (Journee & Massie 2001, strip-theory chapter; recalled, equation
number not checked).  Heave and pitch come from the coupled two-DOF strip-theory equations of the relative-motion form with
sectional added mass (rho pi / 8) b^2.  DECISION: closed-form strip theory, not Capytaine -- a 7 m slender hull follows waves
longer than ~30 m (heave RAO -> 1, pitch -> wave slope; receipt), the whole table is built in a few ms, and a 3-D BEM call per
(omega, heading, speed) would dominate the build for no visible change in R_aw.  The (Tp, heading, speed) table is built once
per parameter set and cached (in memory, optionally on disk).  Oblique seas: R_aw is multiplied by max(-cos chi, 0), the
projection of the wave direction on the hull axis (DECISION: no source; zero in following and beam seas).  Spectrum:
Bretschneider (ITTC two-parameter) S = (5/16) Hs^2 wp^4 w^-5 exp(-1.25 (wp/w)^4);
R = 2 integral S R_aw/zeta_a^2 dw = Hs^2 G(Tp, chi, U).
Stage 1 lowers the speed by R_aw / K, K = -dX/dV at the root (first-order).
Capsize proxy: steady heel + sigma_phi sqrt(2 ln N) (Longuet-Higgins 1952), sigma_phi from a 1-DOF roll response to the
Hs/4 wave slope at the peak period with the beam-sea factor |sin chi|.

Stage 1.  `USVSim` follows the interface of cafe.pm.physics.glider.GliderSim (fail / first / run / history).  Each replan the
heading is chosen from 72 candidates to maximise velocity made good toward the active waypoint, ground velocity = through-water
velocity (at the track angle heading - side * leeway) + surface current + Stokes drift; a tack or gybe costs
V * t_tack of distance and is made only if the VMG gain over tack_horizon pays it back; speed is tack_speed_frac of the polar
during the manoeuvre; on a section only headings that reduce the cross-track error are allowed outside the corridor.
Failure flags (first occurrence in `first[name]`, epoch seconds): becalmed = the best through-water speed over all headings is
below the current speed for becalmed_after_h (DECISION: the BRIEF's 'SOG < current' read as speed through water, because a
drifting boat's SOG equals the current); swept_off_track; capsize_proxy; wing_stall = apparent wind below the tail's authority or
inside
the stall cone of the bow for stall_sustain_s; battery.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import pathlib
from typing import Any, NamedTuple, cast

import numpy as np
import yaml

from ..env import conventions as cv

Arr = Any
G = 9.80665
R_E = 6371008.8
DV = 0.05                 # m/s, speed grid of the root search
N_IT = 24                 # fixed-point iterations for (beta, phi, depower, rudder)
NH = 72                   # candidate headings
FAILS = ("becalmed", "swept_off_track", "capsize_proxy", "wing_stall", "battery")
MODES = ("section", "station")
PLATFORMS = pathlib.Path(__file__).resolve().parents[3] / "platforms"
STRINGS = ("radio_900mhz", "radio_2g4", "iridium_link")


# ------------------------------------------------------------------ parameters

def load_platform(name: str = "saildrone_explorer") -> dict[str, Any]:
    """platforms/<name>.yaml (or a path) -> flat dict of values plus 'kind' and 'mission_defaults'.
    Refuses a leaf without value, unit and either a source or assumed: true with a why (same rule as glider.load_platform)."""
    path = pathlib.Path(name)
    if not path.suffix:
        path = PLATFORMS / f"{name}.yaml"
    raw = yaml.safe_load(path.read_text())

    def flat(block: dict[str, Any], where: str) -> dict[str, Any]:
        out = {}
        for k, leaf in block.items():
            if not (isinstance(leaf, dict) and "value" in leaf and "unit" in leaf):
                raise ValueError(f"{path.name}:{where}.{k}: need value and unit")
            if not (leaf.get("source") or (leaf.get("assumed") is True and leaf.get("why"))):
                raise ValueError(f"{path.name}:{where}.{k}: need a source, or assumed: true with a why")
            if isinstance(leaf["value"], str) and k not in STRINGS:
                raise ValueError(f"{path.name}:{where}.{k}: {leaf['value']!r} is a string (floats need a dot and a signed exp.)")
            out[k] = leaf["value"]
        return out

    P = flat(raw["params"], "params")
    P["kind"] = raw["kind"]
    P["mission_defaults"] = flat(raw["mission_defaults"], "mission_defaults")
    return P


def _digest(P: dict[str, Any]) -> str:
    nums = {k: v for k, v in P.items() if isinstance(v, (int, float))}
    return hashlib.sha1(json.dumps(nums, sort_keys=True).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ small numerics

def _lin(tab: Arr, axes: tuple[Arr, ...], pts: tuple[Arr, ...]) -> Arr:
    """n-linear interpolation of `tab` (shape n1..nd[, F]) on uniform axes at broadcast points `pts`; clamped at the ends."""
    pts = np.broadcast_arrays(*[np.asarray(x, float) for x in pts])
    idx, w = [], []
    for ax, x in zip(axes, pts, strict=True):
        t = np.clip((x - ax[0]) / (ax[1] - ax[0]), 0.0, len(ax) - 1.0)
        i = np.minimum(np.floor(t).astype(int), len(ax) - 2)
        idx.append(i)
        w.append(t - i)
    out = 0.0
    for corner in itertools.product((0, 1), repeat=len(axes)):
        wt = np.prod([wi if c else 1.0 - wi for c, wi in zip(corner, w, strict=True)], axis=0)
        g = tab[tuple(i + c for i, c in zip(idx, corner, strict=True))]
        out = out + (wt[..., None] if g.ndim > wt.ndim else wt) * g
    return out


def cf_ittc57(re: Arr) -> Arr:
    """ITTC-1957 model-ship correlation line C_F = 0.075 / (log10 Re - 2)^2."""
    return 0.075 / (np.log10(re) - 2.0) ** 2


def helmbold(ar: Arr) -> Arr:
    """Low-aspect-ratio lift slope per radian, a = 2 pi AR / (2 + sqrt(4 + AR^2)) (Helmbold 1942; Hoerner & Borst 1975)."""
    return 2 * np.pi * ar / (2.0 + np.sqrt(4.0 + ar ** 2))


def wing_slope(P: dict[str, Any]) -> float:
    """Finite-wing lift slope per radian from the section slope by lifting-line theory."""
    ar = P["wing_span_m"] ** 2 / P["wing_area_m2"]
    return cast(float, P["wing_cl_alpha_2d"] / (1.0 + P["wing_cl_alpha_2d"] / (np.pi * P["wing_oswald_e"] * ar)))


def wing_polar(P: dict[str, Any], alpha_deg: Arr) -> tuple[Arr, Arr]:
    """(C_L, C_D) of the wing for |alpha| <= 90 deg (sign of C_L follows alpha): linear + induced drag to the stall angle, Viterna
    & Corrigan (1982) flat-plate model beyond it.  Continuous at the stall angle."""
    ar = P["wing_span_m"] ** 2 / P["wing_area_m2"]
    a3, e, cd0 = wing_slope(P), P["wing_oswald_e"], P["wing_cd0"]
    a = np.radians(np.clip(np.abs(alpha_deg), 0.0, 90.0))
    s = np.radians(P["wing_stall_deg"])
    cls = a3 * s
    cds = cd0 + cls ** 2 / (np.pi * e * ar)
    cdmax = 1.11 + 0.018 * ar
    a2 = (cls - cdmax * np.sin(s) * np.cos(s)) * np.sin(s) / np.cos(s) ** 2
    b2 = (cds - cdmax * np.sin(s) ** 2) / np.cos(s)
    ap = np.maximum(a, s)
    cl_post = 0.5 * cdmax * np.sin(2 * ap) + a2 * np.cos(ap) ** 2 / np.sin(ap)
    cd_post = cdmax * np.sin(ap) ** 2 + b2 * np.cos(ap)
    pre = a <= s
    cl = np.where(pre, a3 * a, cl_post)
    cd = np.where(pre, cd0 + (a3 * a) ** 2 / (np.pi * e * ar), cd_post)
    return np.sign(alpha_deg) * cl, cd


def hull_resistance(P: dict[str, Any], v: Arr, phi: Arr) -> Arr:
    """Hull-body resistance [N] at speed v [m/s] and heel phi [rad]: ITTC-57 friction x (1 + k) + residuary, x (1 + c phi^2)."""
    v = np.maximum(v, 1e-3)
    re = v * P["lwl_m"] / P["nu_water"]
    fr = v / np.sqrt(G * P["lwl_m"])
    q = 0.5 * P["rho_water"] * v ** 2 * P["wetted_area_m2"]
    r = q * (cf_ittc57(re) * (1.0 + P["form_factor_k"]) + P["cr0"] * (fr / P["cr_fr_ref"]) ** 4)
    return r * (1.0 + P["heel_resist_c"] * phi ** 2)


def _apparent(wx: Arr, wy: Arr, vx: Arr, vy: Arr) -> tuple[Arr, Arr]:
    """Air velocity relative to the boat: wind over the ground minus the boat's ground velocity (current included in vx, vy)."""
    return wx - vx, wy - vy


# ------------------------------------------------------------------ the 4-DOF steady-state VPP

def _foil(P: dict[str, Any], pre: str) -> tuple[Arr, Arr, float, Arr, Arr]:
    """(area, aspect ratio with free-surface image, lift slope, t/c, chord) of the keel or rudder."""
    area, span = P[f"{pre}_area_m2"], P[f"{pre}_span_m"]
    ar = 2.0 * span ** 2 / area
    return area, ar, float(helmbold(ar)), P[f"{pre}_t_c"], area / span


def _forces(P: dict[str, Any], V: Arr, beta: Arr, phi: Arr, kd: Arr, Yr: Arr, wx: Arr, wy: Arr, cx: Arr, cy: Arr) -> dict[str, Any]:
    """Surge force X, sway force Y and the pieces the iteration needs, at speed V, leeway beta (rad), heel phi (rad), wing
    depower kd and rudder side force Yr.  Arrays broadcast; mirrored frame (wind from starboard)."""
    rw, ra = P["rho_water"], P["rho_air"]
    ax, ay = _apparent(wx, wy, cx + V * np.cos(beta), cy + V * np.sin(beta))
    aws = np.maximum(np.hypot(ax, ay), 1e-6)
    dx, dy = ax / aws, ay / aws
    s = np.where(dy <= 0.0, 1.0, -1.0)
    nx, ny = -s * dy, s * dx                                   # lift direction: perpendicular to the flow, forward-pointing
    cl, cd = wing_polar(P, P["wing_trim_deg"] * kd)
    qs = 0.5 * ra * aws ** 2 * P["wing_area_m2"] * np.cos(phi)
    fxa, fya = qs * (cl * nx + cd * dx), qs * (cl * ny + cd * dy)
    fxw = 0.5 * ra * P["wind_cd_front"] * P["wind_area_front_m2"] * aws * ax
    fyw = 0.5 * ra * P["wind_cd_side"] * P["wind_area_side_m2"] * aws * ay
    fx, fy = fxa + fxw, fya + fyw
    mh = -(fya * (P["wing_ce_height_m"] + P["clr_depth_m"]) + fyw * (P["wind_height_m"] + P["clr_depth_m"]))
    vs = np.maximum(V, 1e-3)
    qw = 0.5 * rw * vs ** 2
    ak_area, ak_ar, ak, ak_tc, ak_c = _foil(P, "keel")
    bs = np.radians(P["keel_stall_deg"])
    ck = np.clip(-ak * beta, -ak * bs, ak * bs)
    lk = qw * ak_area * ck
    cfk = cf_ittc57(vs * ak_c / P["nu_water"])
    dk = qw * ak_area * (2 * cfk * (1 + 2 * ak_tc + 60 * ak_tc ** 4) + ck ** 2 / (np.pi * ak_ar))
    r_area, r_ar, r_a, r_tc, r_c = _foil(P, "rudder")
    cfr = cf_ittc57(vs * r_c / P["nu_water"])
    yr = np.clip(Yr, -qw * r_area * P["rudder_cl_max"], qw * r_area * P["rudder_cl_max"])
    dr = qw * r_area * 2 * cfr * (1 + 2 * r_tc + 60 * r_tc ** 4) + yr ** 2 / (qw * r_area * np.pi * r_ar)
    d = hull_resistance(P, vs, phi) + dk + dr + qw * P["appendage_cda_m2"]
    return dict(X=fx - d * np.cos(beta) - lk * np.sin(beta), Y=fy - d * np.sin(beta) + lk * np.cos(beta) + yr,
                fy=fy, mh=mh, lk=lk, d=d, qw=qw, ak=ak, ak_area=ak_area, bs=bs, aws=aws, ax=ax, ay=ay,
                yaw=P["wing_ce_x_m"] * fy + P["keel_x_m"] * lk * np.cos(beta), yr=yr)


def _solve(P: dict[str, Any], wx: Arr, wy: Arr, cx: Arr, cy: Arr) -> dict[str, Any]:
    """Steady state in the mirrored frame.  wx, wy: wind over the ground (body axes); cx, cy: surface current (body axes); the
    wind relative to the water (wx - cx, wy - cy) must come from starboard (air velocity y <= 0).  Returns arrays of the broadcast
    shape: V, beta_deg (leeway magnitude), phi_deg, K = -dX/dV at the root [N s/m], aws, awa_deg, kd, resid (|Y|/force scale),
    yaw_resid."""
    cap = P["stw_cap_ms"]
    nv = int(round(cap / DV)) + 1
    Vg = np.linspace(0.0, cap, nv)
    shape = np.broadcast(wx, wy, cx, cy).shape
    wx, wy, cx, cy = (np.asarray(a, float)[..., None] for a in (wx, wy, cx, cy))
    V = np.broadcast_to(Vg, shape + (nv,))
    beta, phi, kd, yr = (np.zeros(shape + (nv,)) for _ in range(4))
    kd = kd + 1.0
    mr = P["mass_kg"] * G * P["gm_m"]
    mallow = mr * np.sin(np.radians(P["heel_target_deg"]))
    for _ in range(N_IT):
        f = _forces(P, V, beta, phi, kd, yr, wx, wy, cx, cy)
        sinp = np.clip(f["mh"] / mr, 0.0, 0.985)
        phi = 0.5 * phi + 0.5 * np.arcsin(sinp)
        kd = 0.5 * kd + 0.5 * np.clip(kd * mallow / np.maximum(f["mh"], 1e-9), 0.05, 1.0)
        need = -(f["fy"] - f["d"] * np.sin(beta) + yr) / np.cos(beta)
        ck = np.clip(need / (f["qw"] * f["ak_area"]), -f["ak"] * f["bs"], f["ak"] * f["bs"])
        beta = 0.5 * beta + 0.5 * (-ck / f["ak"])
        yr = 0.5 * yr - 0.5 * f["yaw"] / P["rudder_x_m"]
    f = _forces(P, V, beta, phi, kd, yr, wx, wy, cx, cy)
    X = f["X"]
    pos = X > 0.0
    cross = pos[..., :-1] & ~pos[..., 1:]
    has = cross.any(-1) & pos[..., 0]
    top = ~has & pos.all(-1)
    i0 = np.where(has, cross.argmax(-1), np.where(top, nv - 2, 0))

    def at(a: Arr, frac: Arr) -> Arr:
        a0 = np.take_along_axis(a, i0[..., None], -1)[..., 0]
        return a0 + frac * (np.take_along_axis(a, i0[..., None] + 1, -1)[..., 0] - a0)

    x0, x1 = at(X, 0.0), at(X, 1.0)
    frac = np.where(has, x0 / np.where(x0 == x1, 1.0, x0 - x1), np.where(top, 1.0, 0.0))
    awa = np.degrees(np.arctan2(np.abs(f["ay"]), -f["ax"]))
    scale = np.abs(f["fy"]) + np.abs(f["lk"]) + 1.0
    nres = np.abs(f["yaw"] + P["rudder_x_m"] * f["yr"]) / (np.abs(f["yaw"]) + np.abs(P["rudder_x_m"] * f["yr"]) + 1.0)
    return dict(V=Vg[i0] + frac * DV, beta_deg=np.degrees(-at(beta, frac)), phi_deg=np.degrees(at(phi, frac)),
                K=np.maximum((x0 - x1) / DV, 1.0), aws=at(f["aws"], frac), awa_deg=at(awa, frac), kd=at(kd, frac),
                resid=at(np.abs(f["Y"]) / scale, frac), yaw_resid=at(nres, frac))


def _body(wind_en: Arr, current_en: Arr, heading_to: Arr) -> tuple[Arr, Arr, Arr, Arr, Arr]:
    """(wx, wy, cx, cy) in body axes and the mirror sign m (+1: wind relative to the water comes from starboard)."""
    h = cv.vec_from_to(1.0, heading_to)
    s = np.stack([h[..., 1], -h[..., 0]], -1)                      # starboard unit vector
    w, c = np.asarray(wind_en, float), np.asarray(current_en, float)
    wx, wy = np.sum(w * h, -1), np.sum(w * s, -1)
    cx, cy = np.sum(c * h, -1), np.sum(c * s, -1)
    return wx, wy, cx, cy, np.where(wy - cy > 0.0, -1.0, 1.0)


def through_water(P: dict[str, Any], wind_en: Arr, current_en: Arr, heading_to: Arr) -> dict[str, Any]:
    """Current-coupled solve.  wind_en: wind over the ground at the anemometer height (east, north) m/s; current_en: surface
    current; heading_to: compass degrees.  Arrays broadcast (trailing axis 2 for the vectors).  Returns stw [m/s], track_to [deg]
    (direction of motion through the water = heading + signed leeway), leeway_deg (+ = toward starboard), heel_deg, aws, awa_deg,
    K, kd, resid, yaw_resid."""
    wx, wy, cx, cy, m = _body(wind_en, current_en, heading_to)
    s = _solve(P, wx, m * wy, cx, m * cy)
    lee = -m * s["beta_deg"]
    return dict(stw=s["V"], track_to=cv.wrap360(np.asarray(heading_to) + lee), leeway_deg=lee, heel_deg=s["phi_deg"],
                aws=s["aws"], awa_deg=s["awa_deg"], K=s["K"], kd=s["kd"], resid=s["resid"], yaw_resid=s["yaw_resid"])


class Polar(NamedTuple):
    tws: Arr          # (nT,) true wind speed relative to the water at the anemometer height [m/s]
    twa: Arr          # (nA,) true wind angle off the bow [deg], 0 = head to wind, 180 = dead downwind
    f: Arr            # (nT, nA, 7): V, leeway deg, heel deg, K, aws, awa deg, depower


class WaveTab(NamedTuple):
    tp: Arr           # (nP,) peak period [s]
    chi: Arr          # (nC,) wave propagation angle relative to the heading [deg], 0..180 (180 = head seas)
    u: Arr            # (nU,) speed [m/s]
    g: Arr            # (nP, nC, nU): R_aw / Hs^2 [N/m^2]


def _build_polar(P: dict[str, Any]) -> Polar:
    tws, twa = np.arange(0.0, 30.01, 1.0), np.arange(0.0, 180.01, 2.5)
    T, A = np.meshgrid(tws, twa, indexing="ij")
    g = np.radians(A)
    s = _solve(P, -T * np.cos(g), -T * np.sin(g), np.zeros_like(T), np.zeros_like(T))
    return Polar(tws, twa, np.stack([s["V"], s["beta_deg"], s["phi_deg"], s["K"], s["aws"], s["awa_deg"], s["kd"]], -1))


def through_water_table(P: dict[str, Any], pol: Polar, wind_en: Arr, current_en: Arr, heading_to: Arr) -> dict[str, Any]:
    """Same outputs as `through_water` (without resid) from the still-water polar evaluated at the wind relative to the water."""
    wr = np.asarray(wind_en, float) - np.asarray(current_en, float)
    gam = np.mod(cv.from_deg(wr) - np.asarray(heading_to) + 180.0, 360.0) - 180.0
    v, beta, phi, k, aws, awa, kd = np.moveaxis(_lin(pol.f, (pol.tws, pol.twa), (cv.speed(wr), np.abs(gam))), -1, 0)
    side = np.where(gam < 0, -1.0, 1.0)
    lee = -side * beta
    return dict(stw=v, track_to=cv.wrap360(np.asarray(heading_to) + lee), leeway_deg=lee, heel_deg=phi, aws=aws, awa_deg=awa,
                K=k, kd=kd)


# ------------------------------------------------------------------ waves: strip theory + Gerritsma-Beukelman

def _strip(P: dict[str, Any], w: Arr, chi_deg: Arr, u: Arr) -> tuple[Arr, Arr, Arr]:
    """(heave, pitch, R_aw / zeta_a^2) per unit wave amplitude at wave frequency w [rad/s], wave angle chi (180 = head seas) and
    speed u.  Complex heave [m/m] and pitch [rad/m] (pitch positive bow down, referred to the section reference at x = 0)."""
    L, B, M, rho = P["lwl_m"], P["beam_wl_m"], P["mass_kg"], P["rho_water"]
    nx = 21
    dx = L / nx
    x = (np.arange(nx) + 0.5) * dx - L / 2
    b = B * np.sqrt(1.0 - (2 * x / L) ** 2)
    dbar = (M / rho) / (np.sum(b) * dx)
    w, chi, u = (np.asarray(a, float)[..., None] for a in (w, chi_deg, u))
    k, c = w ** 2 / G, np.cos(np.radians(chi))
    we = np.maximum(w - k * u * c, 0.05)
    ke = we ** 2 / G
    bm = rho * G ** 2 * (2 * np.sin(0.5 * ke * b) * np.exp(-ke * dbar)) ** 2 / we ** 3
    kk = -we ** 2 * rho * np.pi / 8 * b ** 2 + 1j * we * bm + rho * G * b
    zeta = np.exp(-1j * k * x * c)
    s0, s1, s2 = (np.sum(kk * x ** n, -1) * dx for n in (0, 1, 2))
    f0, f1 = np.sum(kk * zeta, -1) * dx, -np.sum(kk * x * zeta, -1) * dx
    we0, k0, c0 = we[..., 0], k[..., 0], c[..., 0]
    a11, a22 = s0 - we0 ** 2 * M, s2 - we0 ** 2 * M * (P["kyy_frac"] * L) ** 2
    det = a11 * a22 - s1 * s1
    z, th = (f0 * a22 + s1 * f1) / det, (a11 * f1 + s1 * f0) / det
    r = z[..., None] - x * th[..., None] - zeta
    vz = 1j * we * r + u * (th[..., None] - 1j * k * c * zeta)
    raw = k0 / (2 * we0) * np.sum(bm * np.abs(vz) ** 2, -1) * dx * np.maximum(-c0, 0.0)
    return z, th, raw


def _bretschneider(w: Arr, tp: Arr) -> Arr:
    """Bretschneider spectrum for Hs = 1 [m^2 s/rad]: (5/16) wp^4 w^-5 exp(-1.25 (wp/w)^4)."""
    wp = 2 * np.pi / tp
    return 5 / 16 * wp ** 4 * w ** -5 * np.exp(-1.25 * (wp / w) ** 4)


def _build_waves(P: dict[str, Any]) -> WaveTab:
    tp, chi, u = np.linspace(3.0, 21.0, 19), np.linspace(0.0, 180.0, 13), np.linspace(0.0, 3.5, 8)
    w = np.geomspace(0.25, 6.0, 120)
    _, _, raw = _strip(P, w[:, None, None], chi[None, :, None], u[None, None, :])
    s = _bretschneider(w[None, :], tp[:, None])                   # (nP, nW)
    g = 2.0 * np.trapezoid(s[:, :, None, None] * raw[None], w, axis=1)
    return WaveTab(tp, chi, u, g)


_CACHE: dict[str, tuple[Polar, WaveTab]] = {}


def tables(P: dict[str, Any], cache_dir: str | pathlib.Path | None = None) -> tuple[Polar, WaveTab]:
    """(Polar, WaveTab) for the parameter set: in memory, and as .npz under `cache_dir` when given (keyed by a digest of P)."""
    key = _digest(P)
    if key in _CACHE:
        return _CACHE[key]
    f = pathlib.Path(cache_dir) / f"usv_tables_{key}.npz" if cache_dir else None
    if f is not None and f.exists():
        z = np.load(f)
        out = (Polar(z["ptws"], z["ptwa"], z["pf"]), WaveTab(z["wtp"], z["wchi"], z["wu"], z["wg"]))
    else:
        out = (_build_polar(P), _build_waves(P))
        if f is not None:
            f.parent.mkdir(parents=True, exist_ok=True)
            np.savez(f, ptws=out[0].tws, ptwa=out[0].twa, pf=out[0].f, wtp=out[1].tp, wchi=out[1].chi, wu=out[1].u, wg=out[1].g)
    _CACHE[key] = out
    return out


def added_resistance(P: dict[str, Any], wt: WaveTab, hs: Arr, tp: Arr, chi_deg: Arr, speed: Arr) -> Arr:
    """Mean added resistance in irregular waves [N]: Hs^2 G(Tp, |chi|, U), chi = angle between the wave direction and the
    heading (180 = head seas)."""
    return np.asarray(hs, float) ** 2 * _lin(wt.g, (wt.tp, wt.chi, wt.u), (tp, np.abs(chi_deg), speed))


def roll_sigma_deg(P: dict[str, Any], hs: Arr, tp: Arr, chi_deg: Arr) -> Arr:
    """Standard deviation of roll [deg] from a 1-DOF roll response at the peak frequency to the wave slope k Hs/4 |sin chi|."""
    wn = np.sqrt(G * P["gm_m"]) / P["kxx_roll_m"]
    wp = 2 * np.pi / np.maximum(tp, 0.5)
    r = wp / wn
    h = 1.0 / np.sqrt((1.0 - r ** 2) ** 2 + (2 * P["roll_damping"] * r) ** 2)
    return np.degrees(h * wp ** 2 / G * np.asarray(hs) / 4.0 * np.abs(np.sin(np.radians(chi_deg))))


# ------------------------------------------------------------------ Stage 1

def draw_vpp_bias(P: dict[str, Any], members: int, seed: int = 0) -> Arr:
    """Fractional VPP speed change per member ~ N(vpp_bias_mean, vpp_bias_sd), clipped to [-0.9, 0.5] (factor = 1 + bias)."""
    return np.clip(np.random.default_rng(seed).normal(P["vpp_bias_mean"], P["vpp_bias_sd"], members), -0.9, 0.5)


class USVSim:
    """M-member wing-sail USV ensemble.  `env` is a cafe.pm.env Environment, `start` = (lon, lat) scalars or (M,) arrays,
    `t0` epoch seconds.  mission: dict(mode='section'|'station', waypoints=[(lon, lat), ...] or station=(lon, lat), repeat=False,
    seed=0, plus any mission_defaults key: becalmed_after_h, track_tolerance_km, corridor_km, wp_radius_m, roll_limit_deg,
    stall_sustain_s).  perturb: {'vpp_bias': (M,) fractional speed change} (default draws N(vpp_bias_mean, vpp_bias_sd)).
    The wind is read at the anemometer height, the current at current_z_m; wind/current errors are the caller's environment's."""

    def __init__(self, params: dict[str, Any], members: int, env: Any, start: tuple[Arr, Arr], t0: float, mission: dict[str, Any],
                 perturb: dict[str, Any] | None = None):
        P, M = self.P, self.M = params, int(members)
        self.env, self.t = env, float(t0)
        md = self.md = {**P["mission_defaults"], **mission}
        self.mode = md.get("mode", "section")
        if self.mode not in MODES:
            raise ValueError(f"mode {self.mode!r} not in {MODES}")
        if self.mode == "station":
            self.wps = np.array([md["station"]], float)
        else:
            self.wps = np.array(md["waypoints"], float).reshape(-1, 2)
            if len(self.wps) == 0:
                raise ValueError("section mode needs waypoints")
            if len(self.wps) == 1:
                self.mode = "station"
        self.repeat = bool(md.get("repeat", False))
        pt = perturb or {}
        bias = pt["vpp_bias"] if "vpp_bias" in pt else draw_vpp_bias(P, M, int(md.get("seed", 0)))
        self.fac = 1.0 + np.broadcast_to(np.asarray(bias, float), (M,)).copy()
        self.lon = np.broadcast_to(np.asarray(start[0], float), (M,)).copy()
        self.lat = np.broadcast_to(np.asarray(start[1], float), (M,)).copy()
        self.leg_lon, self.leg_lat = self.lon.copy(), self.lat.copy()
        self.idx = np.zeros(M, int)
        self.hd = np.zeros(M)
        self.side = np.zeros(M)
        self.tack_until = np.full(M, -np.inf)
        self.n_tacks = np.zeros(M, int)
        self.stw, self.sog, self.vmax = np.zeros(M), np.zeros(M), np.zeros(M)
        self.path_m = np.zeros(M)
        self.soc_wh = P["soc0"] * P["battery_wh"] * np.ones(M)
        self.acc = {"becalmed": np.zeros(M), "wing_stall": np.zeros(M)}
        self.fail = {k: np.zeros(M, bool) for k in FAILS}
        self.first = {k: np.full(M, np.nan) for k in FAILS}
        self.arrived = np.full(M, np.nan)
        self.t_plan = -np.inf
        self.t_rec = -np.inf
        self._rec: dict[str, Any] = {k: [] for k in ("t", "lon", "lat", "stw", "sog", "heading", "soc_wh", "wp")}
        self.pol, self.wt = tables(P)
        self.cand = np.arange(NH) * 360.0 / NH

    # ---- helpers -------------------------------------------------------------------------------------------------
    @staticmethod
    def _met(lon: Arr, lat: Arr, tlon: Arr, tlat: Arr) -> Arr:
        """(M, 2) metres east, north from (lon, lat) to (tlon, tlat), the short way round the dateline (equirect.)."""
        dlon = (tlon - lon + 180.0) % 360.0 - 180.0
        return np.stack([np.radians(dlon) * np.cos(np.radians(0.5 * (lat + tlat))) * R_E, np.radians(tlat - lat) * R_E], -1)

    def _geom(self) -> tuple[Arr, Arr, Arr, Arr]:
        """Distance to the active waypoint, unit vector to it, signed cross-track error (+ left of the leg; the distance itself in
        station mode) and the leg's left-normal."""
        k = self.idx % len(self.wps)
        tgt = self._met(self.lon, self.lat, self.wps[k, 0], self.wps[k, 1])
        dist = np.hypot(tgt[:, 0], tgt[:, 1])
        uhat = tgt / np.maximum(dist, 1.0)[:, None]
        if self.mode == "station":
            return dist, uhat, dist, np.zeros_like(uhat)
        leg = self._met(self.leg_lon, self.leg_lat, self.wps[k, 0], self.wps[k, 1])
        ul = leg / np.maximum(np.hypot(leg[:, 0], leg[:, 1]), 1.0)[:, None]
        nl = np.stack([-ul[:, 1], ul[:, 0]], -1)
        me = self._met(self.leg_lon, self.leg_lat, self.lon, self.lat)
        return dist, uhat, np.sum(me * nl, -1), nl

    def _eval(self, hd: Arr, c: dict[str, Any]) -> dict[str, Any]:
        """Speed, track and state for headings hd (M, H) [deg]: polar at the wind relative to the water, minus R_aw / K, times the
        VPP bias, capped at the hull speed."""
        gam = np.mod(c["wfrom"][:, None] - hd + 180.0, 360.0) - 180.0
        f = _lin(self.pol.f, (self.pol.tws, self.pol.twa), (c["tws"][:, None], np.abs(gam)))
        v0, beta, phi, kk, aws, awa, _ = np.moveaxis(f, -1, 0)
        chi = np.abs(np.mod(c["wdir"][:, None] - hd + 180.0, 360.0) - 180.0)
        r = added_resistance(self.P, self.wt, c["hs"][:, None], c["tp"][:, None], chi, v0)
        v = np.minimum(np.maximum(v0 - r / kk, 0.0) * self.fac[:, None], self.P["stw_cap_ms"])
        side = np.where(gam < 0, -1.0, 1.0)
        return dict(v=v, trk=hd - side * beta, side=side, phi=phi, aws=aws, awa=awa, chi=chi)

    def _flag(self, name: str, mask: Arr) -> None:
        new = mask & ~self.fail[name]
        self.first[name][new] = self.t
        self.fail[name] |= mask

    # ---- one step ------------------------------------------------------------------------------------------------
    def step(self, dt: float) -> None:
        P, md, M, t = self.P, self.md, self.M, self.t
        wind = self.env.wind(self.lon, self.lat, P["anemometer_m"], t).value
        cur = self.env.current(self.lon, self.lat, P["current_z_m"], t).value
        wav = self.env.waves(self.lon, self.lat, t)
        stokes = wav["stokes0"].value
        wr = wind - cur
        c = dict(tws=cv.speed(wr), wfrom=cv.from_deg(wr), hs=wav["Hs"].value, tp=wav["Tp"].value, wdir=wav["dir_to"].value)
        if t - self.t_plan >= P["replan_s"]:
            self.t_plan = t
            e = self._eval(np.broadcast_to(self.cand, (M, NH)), c)
            g = cv.vec_from_to(e["v"], e["trk"]) + (cur + stokes)[:, None, :]
            _, uhat, xte, nl = self._geom()
            vmg = np.sum(g * uhat[:, None, :], -1)
            if self.mode == "section":                         # outside the corridor only headings that reduce |xte|
                bad = (np.abs(xte) > md["corridor_km"] * 1e3)[:, None] & (np.sum(g * nl[:, None, :], -1) * xte[:, None] >= 0.0)
                vmg = vmg - 1e6 * bad
            pen = np.where((self.side[:, None] != 0.0) & (e["side"] != self.side[:, None]),
                           (self.stw * P["tack_time_s"] / P["tack_horizon_s"])[:, None], 0.0)
            best = np.argmax(vmg - pen, axis=1)
            free = t >= self.tack_until
            side_new = e["side"][np.arange(M), best]
            tacked = free & (self.side != 0.0) & (side_new != self.side)
            self.hd = np.where(free, self.cand[best], self.hd)
            self.tack_until = np.where(tacked, t + P["tack_time_s"], self.tack_until)
            self.n_tacks += tacked
            self.vmax = e["v"].max(1)
        e1 = {k: a[:, 0] for k, a in self._eval(self.hd[:, None], c).items()}
        self.side = e1["side"]
        self.stw = e1["v"] * np.where(t < self.tack_until, P["tack_speed_frac"], 1.0)
        gv = cv.vec_from_to(self.stw, e1["trk"]) + cur + stokes
        self.sog = cv.speed(gv)
        self.path_m += self.sog * dt
        sde = getattr(self.env, "sde_displacement", None)                                    # unresolved eddies move the position only
        dm = gv * dt if sde is None else gv * dt + sde(self.lon, self.lat, t)
        self.lat = self.lat + np.degrees(dm[:, 1] / R_E)
        self.lon = np.mod(self.lon + np.degrees(dm[:, 0] / (R_E * np.cos(np.radians(self.lat)))) + 180.0, 360.0) - 180.0
        self.t = t + dt
        # waypoints
        dist, _, xte, _ = self._geom()
        if self.mode == "section":
            k = self.idx % len(self.wps)
            reached = dist < md["wp_radius_m"]
            last = self.idx >= len(self.wps) - 1
            adv = reached & (~last | self.repeat)
            self.leg_lon, self.leg_lat = np.where(adv, self.wps[k, 0], self.leg_lon), np.where(adv, self.wps[k, 1], self.leg_lat)
            nxt = (self.idx + 1) % len(self.wps) if self.repeat else np.minimum(self.idx + 1, len(self.wps) - 1)
            self.idx = np.where(adv, nxt, self.idx)
            done = reached & last & (not self.repeat)
        else:
            done = dist < md["wp_radius_m"]
        self.arrived = np.where(done & np.isnan(self.arrived), self.t, self.arrived)
        # failures
        self.acc["becalmed"] = np.where(self.vmax < cv.speed(cur), self.acc["becalmed"] + dt, 0.0)
        self._flag("becalmed", self.acc["becalmed"] >= md["becalmed_after_h"] * 3600.0)
        self._flag("swept_off_track", np.abs(xte) > md["track_tolerance_km"] * 1e3)
        peak = e1["phi"] + np.sqrt(2.0 * np.log(md["cap_cycles"])) * roll_sigma_deg(P, c["hs"], c["tp"], e1["chi"])
        self._flag("capsize_proxy", peak > md["roll_limit_deg"])
        stalled = (e1["aws"] < P["trim_min_aws_ms"]) | (e1["awa"] < P["wing_stall_deg"])
        self.acc["wing_stall"] = np.where(stalled, self.acc["wing_stall"] + dt, 0.0)
        self._flag("wing_stall", self.acc["wing_stall"] >= md["stall_sustain_s"])
        sw = self.env.air(self.lon, self.lat, t)["swdown"].value
        gain = P["solar_eff"] * P["solar_area_m2"] * sw - P["hotel_w"]
        self.soc_wh = np.clip(self.soc_wh + gain * dt / 3600.0, 0.0, P["battery_wh"])
        self._flag("battery", self.soc_wh <= 0.0)

    def run(self, seconds: float, dt: float = 60.0, record_s: float = 3600.0) -> dict[str, Any]:
        """Advance `seconds` in steps of dt, recording every `record_s`; returns `history()`."""
        for _ in range(int(round(seconds / dt))):
            self.step(dt)
            if self.t - self.t_rec >= record_s:
                self.t_rec = self.t
                for k, v in (("t", self.t), ("lon", self.lon), ("lat", self.lat), ("stw", self.stw), ("sog", self.sog),
                             ("heading", self.hd), ("soc_wh", self.soc_wh), ("wp", self.idx)):
                    self._rec[k].append(np.copy(v))
        return self.history()

    def history(self) -> dict[str, Any]:
        """Arrays (records, M) for lon, lat, stw, sog [m/s], heading [deg], soc_wh, wp (active waypoint); t (records,);
        fail[name] (M,) bool; first[name] (M,) epoch seconds of the first occurrence, NaN if never; n_tacks (M,)."""
        h: dict[str, Any] = {k: np.array(v) for k, v in self._rec.items()}
        h["fail"], h["first"], h["n_tacks"] = self.fail, self.first, self.n_tacks
        return h


# ------------------------------------------------------------------ receipts

def _wind_at_anemometer(P: dict[str, Any], speed: float, from_deg: float) -> Arr:
    """u10 vector for AnalyticEnv whose log-profile wind at the anemometer height has `speed`."""
    from ..env.protocol import AnalyticEnv
    unit = AnalyticEnv(wind=(1.0, 0.0)).wind(0.0, 0.0, P["anemometer_m"], 0.0).value[0]
    return cv.vec_from_from(speed / unit, from_deg)


def mean_sog(P: dict[str, Any], speed: float, hours: float = 12.0, dt: float = 120.0, nb: int = 48, bias: float | None = None) -> float:
    """Mean along-path SOG [m/s] of nb vehicles sailing to one station from 6 degrees away on bearings spread evenly round the
    compass in a uniform wind of `speed` at the anemometer height, no current, VPP bias fixed at `bias` (default: the prior)."""
    from ..env.protocol import AnalyticEnv
    b = np.arange(nb) * 2 * np.pi / nb
    f = P["vpp_bias_mean"] if bias is None else bias
    env = AnalyticEnv(wind=_wind_at_anemometer(P, speed, 0.0), hs=0.0)
    sim = USVSim(P, nb, env, (-165.0 + 6 * np.sin(b), 6 * np.cos(b)), 0.0, dict(mode="station", station=(-165.0, 0.0)),
                 perturb=dict(vpp_bias=np.full(nb, f)))
    sim.run(hours * 3600.0, dt)
    return float(np.mean(sim.path_m) / (hours * 3600.0))


def superposition_ratio(P: dict[str, Any], wind: float, current: float, against: bool = False) -> tuple[float, float]:
    """(speed-through-water ratio, SOG ratio) of 'still-water VPP + current' to the current-coupled solve, averaged over headings
    every 5 deg, for wind blowing toward the west at `wind` m/s and a current of `current` m/s along (or `against`) it."""
    hd = np.arange(0.0, 360.0, 5.0)
    w, c = np.array([-wind, 0.0]), np.array([current if against else -current, 0.0])
    still, cpl = through_water(P, w, np.zeros(2), hd), through_water(P, w, c, hd)

    def sog(r: dict[str, Any]) -> Arr:
        return cv.speed(cv.vec_from_to(r["stw"], r["track_to"]) + c)

    return float(np.mean(still["stw"]) / np.mean(cpl["stw"])), float(np.mean(sog(still)) / np.mean(sog(cpl)))


# mutation: not mutated. A receipt generator is the audit instrument, not the model: make receipts and the broken-physics tests grade it, and
# its mutants are label, unit and source strings and widened tolerances, each costing a full receipt run.
def receipts(P: dict[str, Any] | None = None) -> None:  # pragma: no mutate block
    """Reproduce what is published about this class of vehicle (see platforms/saildrone_explorer.yaml for the numbers)."""
    from cafe.receipts import bracket, context, receipt
    from ..env.protocol import AnalyticEnv
    P = P or load_platform()
    grp, hours = "usv", 3600.0
    pol, wt = tables(P)
    # ITTC-57 line and the hull-speed cap are closed forms
    receipt(grp, "ITTC-1957 C_F at Re = 1e7", float(cf_ittc57(1e7)), 0.075 / 25.0, 1e-12,
            source="ITTC 1957: 0.075/(log10 Re - 2)^2")
    hull_speed = 1.34 * np.sqrt(P["loa_m"] / 0.3048) * 0.514444
    receipt(grp, "hull speed 1.34 sqrt(LOA ft) kn vs the 3.3 m/s cap", hull_speed, P["stw_cap_ms"], 0.04, "m/s",
            "Mazza et al. 2026 Part 1 (3.3 m/s hull-speed cap) as quoted in BRIEF 2.4")
    # Chiodi et al. 2021: mean SOG band at 5.4 m/s, max at 12 m/s, never above the cap
    u, band = P["chiodi_mean_wind_ms"], P["chiodi_band"]
    receipt(grp, "mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias)", mean_sog(P, u) / u,
            P["chiodi_mean_sog_ms"] / u, band, "-",
            "Chiodi et al. 2021: 0.96 m/s at 5.4 m/s mean wind (0.18 U); band is the yaml's chiodi_band")
    i12 = int(np.argmin(np.abs(pol.tws - P["chiodi_max_wind_ms"])))
    receipt(grp, "best-heading still-water speed at 12 m/s (CALIBRATED: appendage_cda_m2)", float(pol.f[i12, :, 0].max()),
            P["chiodi_max_sog_ms"], 0.10, "m/s", "Chiodi et al. 2021: maximum hourly SOG 2.9 m/s at 12 m/s; a fit")
    bracket(grp, "no (TWS, TWA) in the polar exceeds the hull-speed cap", float(pol.f[..., 0].max()), 0.0, P["stw_cap_ms"] + 1e-9,
            "m/s", "Mazza et al. 2026 Part 1")
    i, j = np.meshgrid([4, 8, 14], [16, 36, 56], indexing="ij")                    # TWS 4, 8, 14 m/s; TWA 40, 90, 140 deg
    v, lee, aws = pol.f[i, j, 0], np.radians(pol.f[i, j, 1]), pol.f[i, j, 4]
    g = np.radians(pol.twa[j])
    tri = np.hypot(-pol.tws[i] * np.cos(g) - v * np.cos(lee), -pol.tws[i] * np.sin(g) + v * np.sin(lee))
    receipt(grp, "apparent wind speed = |true wind - boat velocity| (max relative error over 9 states)",
            float(np.max(np.abs(aws / tri - 1))), 0.0, 0.01, "-",
            "vector triangle of wind and boat velocity (mirrored frame: wind from starboard, leeway to port)", rel=False)
    # Zhang et al. 2019 SPURS-2: 0.2 m/s wind against a 0.9 m/s current sweeps a USV off station and becalms it
    env = AnalyticEnv(wind=(-0.2, 0.0), current=(0.9, 0.0), hs=0.5)
    s = USVSim(P, 16, env, (-125.0, 10.0), 0.0, dict(mode="station", station=(-125.0, 10.0)))
    s.run(24 * hours, 300.0)

    def first_h(k: str) -> float:                                                                   # inf when no member fails
        return float(s.first[k][~np.isnan(s.first[k])].min(initial=np.inf)) / hours

    zhang = "Zhang et al. 2019 (SPURS-2), as quoted in BRIEF 1.4/2.4: swept off track at 0.9 m/s current, 0.2 m/s wind"
    bracket(grp, "SPURS-2: swept_off_track first fires (h)", first_h("swept_off_track"), 1.0, 12.0, "h", zhang)
    bracket(grp, "SPURS-2: becalmed first fires (h)", first_h("becalmed"), s.md["becalmed_after_h"] - 1e-6, 12.0, "h",
            "BRIEF 2.4: becalmed when it cannot stem the current for > N h")
    both = float(np.mean(s.fail["swept_off_track"] & s.fail["becalmed"]))
    receipt(grp, "SPURS-2: fraction of members that fail both ways", both, 1.0, 0.0, "-", zhang, rel=False)
    # Sun et al. 2026: a still-water VPP plus the current overpredicts SOG; the coupled solve does not
    sun = "Sun et al. 2026 (as quoted in BRIEF 2.4)"
    stw_r, sog_r = superposition_ratio(P, 6.0, 0.5)
    bracket(grp, "still-water VPP + current / current-coupled SOG (6 m/s wind, 0.5 m/s current with it)", sog_r, 1.01, 1.8, "-",
            sun + ": superposition overpredicts SOG; this case only fixes the sign and order")
    pub = 0.5 * (P["sun_overpredict_lo"] + P["sun_overpredict_hi"])
    context(grp, "same, speed through water only (published 30-35 % for SOG)", stw_r - 1.0, pub, "-",
            sun + "; trials mix directions")
    context(grp, "4 m/s wind, 0.8 m/s current with the wind, speed through water", superposition_ratio(P, 4.0, 0.8)[0] - 1.0, pub,
            "-", sun + "; a TEPEX-like light-wind, strong-current case")
    context(grp, "SOG ratio with the current against the wind (< 1 is the physics, not a contradiction)",
            superposition_ratio(P, 6.0, 0.5, True)[1], 1.0, "-", "this module: a current against the wind raises the wind")
    # internal consistency: the table is the coupled solve, and the sway force balances
    hh = np.array([20.0, 75.0, 140.0, 200.0, 290.0])
    ww = np.array([[-4.0, 1.0], [3.0, -5.0], [-8.0, -2.0], [0.0, 6.0], [-2.0, -2.0]])
    cc = np.array([[0.2, 0.1], [-0.3, 0.2], [0.4, -0.2], [0.0, -0.5], [0.1, 0.1]])
    err = np.abs(through_water(P, ww, cc, hh)["stw"] - through_water_table(P, pol, ww, cc, hh)["stw"])
    receipt(grp, "Stage-1 table == direct current-coupled solve (max |dV|)", float(err.max()), 0.0, 0.02, "m/s",
            "Galilean invariance (this module)", rel=False)
    res = through_water(P, ww, cc, hh)["resid"]
    receipt(grp, "sway force balance residual at the root (max |Y| / force scale)", float(res.max()), 0.0, 0.05, "-",
            "4-DOF steady state: sum Y = 0", rel=False)
    # long-wave limit of the strip theory: the hull follows the wave (heave -> 1, pitch -> the wave slope)
    z, th, _ = _strip(P, 0.3, 180.0, 0.0)
    receipt(grp, "strip theory, long head waves: heave RAO", float(np.real(z)), 1.0, 0.05, "m/m",
            "Froude-Krylov long-wave limit: a small float follows the surface")
    receipt(grp, "strip theory, long head waves: pitch / (-i k), bow down positive", float(np.real(th / (-1j * 0.3 ** 2 / G))),
            1.0, 0.05, "-", "long-wave limit: pitch = minus the wave slope d(zeta)/dx; a head-sea crest ahead lifts the bow")
    wg = np.geomspace(0.25, 6.0, 4000)
    receipt(grp, "Bretschneider m0 = Hs^2 / 16 (Hs = 1)", float(np.trapezoid(_bretschneider(wg, 9.0), wg)), 1.0 / 16.0, 0.01,
            "m2", "Bretschneider 1959 / ITTC two-parameter spectrum")
