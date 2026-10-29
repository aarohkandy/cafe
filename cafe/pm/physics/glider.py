"""Underwater gliders: steady flight (Seaglider and Slocum) and Stage-1 mission kinematics vectorized over M members.

Seaglider -- UW/APL basestation FlightModel, as coded in basestation3 `HydroModel.hydro_model` (read 2026-10-29) and
described in Eriksen et al. 2001 (IEEE JOE 26(4)), Frajka-Williams et al. 2011 (JTECH 28), Bennett/Stahr/Eriksen 2019.
Units are those of the code: q = rho/2 U^2 in Pa, the angle of attack alpha in DEGREES, hd_a in 1/deg, hd_c in 1/deg^2,
hd_b in Pa^(-s) ("dimensions q^(1/4)") so that b q^s is dimensionless and adds to c alpha^2; l = 1.8 m; B in N.
  Lift L = l^2 a q alpha;  drag D = l^2 q (b q^s + c alpha^2) = l^2 (b q^(1+s) + c q alpha^2).  The BRIEF writes
  D = l^2 q^(1+s) (b + c alpha^2); that does not reproduce BS3's quadratic below and is dimensionally inconsistent with
  hd_b ~ q^(1/4), so the BS3 form is used (the two differ only in how the induced-drag term scales with q).
  Glide angle theta = pitch - alpha (BS3: "pitch = glide + attack angles"); alpha has the sign OPPOSITE to theta, so the
  glide is always steeper than the pitch.  Steady balance along / normal to the path (z up, theta + for climbing):
      D = B sin(theta),    L = -B cos(theta)
  These are the x and z components of B z_hat - D t_hat + L n_hat = 0 with t = (cos th, sin th), n = (-sin th, cos th); the
  BRIEF's one-line "L + B cos th - D sin th = 0" mixes the two components and is not used.  D/L = -tan th gives
  c alpha^2 + a tan(th) alpha + b q^s = 0, i.e. alpha = -(a tan th / 2c)(1 - sqrt(1 - 4 b c q^s / (a^2 tan^2 th))) and, from D,
  q = B sin(th) q^(-s) / (2 l^2 b) (1 + sqrt(...))   (Eriksen 2001 eqs. 7-8 as in BS3, iterated to |dq/q| < 1e-6).
  "Stalled" = no real root (discriminant < 0), B and pitch of opposite sign, no convergence, or U < u_min.
  B = g (rho V - M), V = (V_hull + dV_vbd) exp(-gamma p + alpha_T (T - T_ref)) (BS3 MakeDiveProfiles.py; gamma =
  abs_compress per dbar, alpha_T = therm_expan per degC, T_ref = 15 degC).
Slocum -- Merckelbach et al. 2010/2019 as in `gliderflight` 1.2.1 `SteadyStateGliderModel` (the oracle):
      F_B = g rho (V_g (1 - eps p) + V_bp),  F_g = m_g g,  (Cd0 + Cd1 a^2)/((a_w + a_h) tan(a + pitch)) = a   [a in rad],
      U^2 = 2 (F_B - F_g) sin(pitch + a) / ((Cd0 + Cd1 a^2) rho S).  Here the glide angle is pitch + a_gf (gliderflight's
      a_gf has the sign of the pitch); this module returns alpha = -a_gf so both vehicles share BS3's alpha = pitch - theta.

Mission kinematics (`GliderSim`): sawtooth dives with the Seaglider's own navigation -- heading fixed per dive, chosen
from the depth-averaged current (DAC) of the previous dive so that through-water velocity + DAC points at the target
(BS3 / Eriksen 2001 "dive-averaged current" steering); DAC = (GPS displacement - dead-reckoned water displacement) / dive time.
Horizontal ground velocity = U cos(theta) heading + current(z) while flying; surface drift = surface current + windage *
10 m wind.
Energy: hotel + VBD pump work p dV / eta at each inflection + comms at the surface + attitude motors.
Lon/lat: local metres per degree, WGS84 series of the NGA "length of a degree" table (111132.92 - 559.82 cos 2phi + 1.175 cos 4phi
- 0.0023 cos 6phi; 111412.84 cos phi - 93.5 cos 3phi + 0.118 cos 5phi), tested against the ellipsoid.
Timing: phase changes are evaluated at step ends, so each of the 4 transitions per cycle is late by <= dt (about 1 % of a
3 h cycle at 60 s).
The Environment has no T(z): T = t_deep + (SST - t_deep) exp(-z/h) (assumed, platforms/*.yaml).
"""

from __future__ import annotations

import pathlib
from typing import Any, NamedTuple

import gsw
import numpy as np
import yaml

from ..env import conventions as cv

Arr = Any
PLATFORMS = pathlib.Path(__file__).resolve().parents[3] / "platforms"
DESC, APO, ASC, SURF = 0, 1, 2, 3  # phase codes recorded per member and step
FAILS = ("station_lost", "battery", "seafloor", "overdepth", "no_flight", "waypoint_unreachable")
P_ATM = 101325.0
MODES = ("station", "section", "drift")


class Steady(NamedTuple):
    speed: Arr  # speed through water [m/s]; 0 where not ok
    glide_deg: Arr  # glide angle, + climbing [deg]
    w: Arr  # vertical speed through water, + up [m/s]
    alpha_deg: Arr  # angle of attack, BS3 convention alpha = pitch - glide [deg]
    ok: Arr  # False: no steady solution / stall / pitch opposes buoyancy


def load_platform(name: str) -> dict:
    """platforms/<name>.yaml (or a path) -> flat dict of values plus 'kind' and 'mission_defaults'.
    Refuses a leaf without value, unit and either a source or assumed: true with a why."""
    path = pathlib.Path(name)
    if not path.suffix:
        path = PLATFORMS / f"{name}.yaml"
    raw = yaml.safe_load(path.read_text())

    def flat(block: dict, where: str) -> dict:
        out = {}
        for k, leaf in block.items():
            if not (isinstance(leaf, dict) and "value" in leaf and "unit" in leaf):
                raise ValueError(f"{path.name}:{where}.{k}: need value and unit")
            if not (leaf.get("source") or (leaf.get("assumed") is True and leaf.get("why"))):
                raise ValueError(f"{path.name}:{where}.{k}: need a source, or assumed: true with a why")
            v = leaf["value"]
            if isinstance(v, str) and k != "acoustic_modem":
                raise ValueError(f"{path.name}:{where}.{k}: {v!r} is a string (YAML floats need a dot and a signed exponent)")
            out[k] = v
        return out

    P = flat(raw["params"], "params")
    P["kind"] = raw["kind"]
    P["mission_defaults"] = flat(raw["mission_defaults"], "mission_defaults")
    return P


def metres_per_deg(lat: Arr) -> tuple:
    """(metres per degree of longitude, of latitude) at `lat` [deg]."""
    r = np.radians(np.asarray(lat, float))
    return (
        111412.84 * np.cos(r) - 93.5 * np.cos(3 * r) + 0.118 * np.cos(5 * r),
        111132.92 - 559.82 * np.cos(2 * r) + 1.175 * np.cos(4 * r) - 0.0023 * np.cos(6 * r),
    )


def _mass(P: dict) -> float:
    return P["mass_kg"] if P["kind"] == "seaglider" else P["mg"]


def _volume(P: dict, p_dbar: Arr, T: Arr, vbd_cc: Arr) -> Arr:
    """Displaced volume [m^3] at pressure p [dbar], temperature T [degC], VBD setting [cc]."""
    if P["kind"] == "seaglider":
        return (
            (P["volmax_cc"] - P["vbd_range_cc"] + vbd_cc)
            * 1e-6
            * np.exp(-P["abs_compress"] * p_dbar + P["therm_expan"] * (T - P["temp_ref"]))
        )
    return P["Vg"] * (1.0 - P["epsilon"] * p_dbar * 1e4) + vbd_cc * 1e-6


def buoyancy(P: dict, rho: Arr, p_dbar: Arr, T: Arr, vbd_cc: Arr) -> Arr:
    """Net buoyancy B = g (rho V - M) [N], + up."""
    return P["gravity"] * (rho * _volume(P, p_dbar, T, vbd_cc) - _mass(P))


def neutral_vbd_cc(P: dict, rho: Arr, p_dbar: Arr, T: Arr) -> Arr:
    """VBD setting [cc] giving B = 0 at (rho, p, T)."""
    if P["kind"] == "seaglider":
        return _mass(P) / rho / np.exp(-P["abs_compress"] * p_dbar + P["therm_expan"] * (T - P["temp_ref"])) * 1e6 - (
            P["volmax_cc"] - P["vbd_range_cc"]
        )
    return (_mass(P) / rho - P["Vg"] * (1.0 - P["epsilon"] * p_dbar * 1e4)) * 1e6


def seaglider_force_balance(P: dict, speed: Arr, glide_deg: Arr, alpha_deg: Arr, rho: Arr) -> tuple:
    """Hydrodynamic (L, D) [N] at a flight state; lift is BS3's signed one, so a steady state has L = -B cos th, D = B sin th."""
    q = 0.5 * rho * np.asarray(speed) ** 2
    l2 = P["length_m"] ** 2
    return l2 * P["hd_a"] * q * alpha_deg, l2 * q * (P["hd_b"] * q ** P["hd_s"] + P["hd_c"] * np.asarray(alpha_deg) ** 2)


def _sg_core(B: Arr, rho: Arr, pitch_deg: Arr, P: dict, iters: int = 200, tol: float = 1e-6) -> Steady:
    """BS3 hydro_model, vectorized: B [N] (+ up), in-situ rho, pitch [deg] -> Steady."""
    B, rho, pitch = np.broadcast_arrays(*(np.asarray(x, float) for x in (B, rho, pitch_deg)))
    a, b, c, s, l2 = P["hd_a"], P["hd_b"], P["hd_c"], P["hd_s"], P["length_m"] ** 2
    sB, sP = np.where(B >= 0, 1.0, -1.0), np.where(pitch >= 0, 1.0, -1.0)  # BS3: a flat pitch counts as +
    ok = (sB == sP) & (B != 0)
    q = (np.abs(B) / (l2 * b)) ** (1.0 / (1.0 + s))  # vertical flight, alpha = 0
    th = np.where(ok, 0.25 * np.pi * sB, 0.0)
    conv = np.zeros(B.shape, bool)
    with np.errstate(all="ignore"):
        for it in range(iters):
            qp = q
            sd = np.where(qp > 0, qp, np.nan) ** (-s)
            tth = np.tan(th)
            dinv = a * a * tth * tth * sd / (4.0 * b * c)
            ok = ok & (dinv > 1.0)  # real root only for dinv > 1; stays False once lost
            sq = np.sqrt(1.0 - 1.0 / dinv)
            q = np.where(ok, B * np.sin(th) * sd / (2.0 * l2 * b) * (1.0 + sq), 0.0)
            alpha = -a * tth / (2.0 * c) * (1.0 - sq)
            th = np.where(ok, np.radians(pitch - alpha), 0.0)
            conv = ok & (np.abs(q - qp) <= tol * np.abs(q))
            if it >= 2 and not np.any(ok & ~conv):
                break
        ok = ok & conv & (q > 0)
        U = np.where(ok, np.sqrt(2.0 * np.where(ok, q, 0.0) / rho), 0.0)
        ok = ok & (U >= P["u_min_ms"])
    U = np.where(ok, U, 0.0)
    glide = np.where(ok, np.degrees(th), 0.0)
    return Steady(U, glide, U * np.sin(np.radians(glide)), np.where(ok, pitch - glide, 0.0), ok)


def seaglider_steady(rho: Arr, p: Arr, T: Arr, vbd_cc: Arr, pitch_deg: Arr, params: dict) -> Steady:
    """Steady Seaglider flight at in-situ density rho [kg/m^3], pressure p [dbar], temperature T [degC],
    VBD extension vbd_cc [cc above the retracted volume] and pitch [deg, + nose up]."""
    return _sg_core(buoyancy(params, rho, p, T, vbd_cc), rho, pitch_deg, params)


def _alpha_gf(phi: Arr, P: dict) -> Arr:
    """Root a in (0, pi/2 - phi) of (Cd0 + Cd1 a^2) = (aw + ah) a tan(a + phi): safeguarded Newton, vectorized."""
    k, c0, c1 = P["aw"] + P["ah"], P["Cd0"], P["Cd1"]
    lo, hi = np.zeros_like(phi), 0.5 * np.pi - phi
    al = phi / 50.0
    for _ in range(100):
        t = np.tan(al + phi)
        g = c0 + c1 * al * al - k * al * t
        lo, hi = np.where(g > 0, al, lo), np.where(g > 0, hi, al)
        new = al - g / (2.0 * c1 * al - k * t - k * al * (1.0 + t * t))
        al = np.where((new > lo) & (new < hi), new, 0.5 * (lo + hi))
        if np.max(np.abs(g)) < 1e-13:
            break
    return al


def slocum_steady(rho: Arr, p: Arr, T: Arr, vbd_cc: Arr, pitch_deg: Arr, params: dict) -> Steady:
    """Steady Slocum flight (Merckelbach form, gliderflight oracle).  `T` is accepted for a common signature and unused."""
    del T
    P = params
    rho, p, vbd, pitch = np.broadcast_arrays(*(np.asarray(x, float) for x in (rho, p, vbd_cc, pitch_deg)))
    FB = buoyancy(P, rho, p, 0.0, vbd) + P["mg"] * P["gravity"]  # g rho V
    dF = FB - P["mg"] * P["gravity"]
    pr = np.radians(pitch)
    ok = (np.abs(pitch) >= 0.05) & (np.abs(pitch) <= 60.0) & (dF * pitch > 0)  # gliderflight's tabulated pitch range
    al = np.sign(pr) * _alpha_gf(np.where(ok, np.abs(pr), 0.1), P)
    with np.errstate(all="ignore"):
        U2 = 2.0 * dF * np.sin(pr + al) / ((P["Cd0"] + P["Cd1"] * al * al) * rho * P["S"])
    ok = ok & (U2 > 0)
    U = np.where(ok, np.sqrt(np.where(ok, U2, 0.0)), 0.0)
    ok = ok & (U >= P["u_min_ms"])
    U = np.where(ok, U, 0.0)
    glide = np.where(ok, np.degrees(pr + al), 0.0)
    return Steady(U, glide, U * np.sin(np.radians(glide)), np.where(ok, -np.degrees(al), 0.0), ok)


def flight(P: dict, rho: Arr, p: Arr, T: Arr, vbd_cc: Arr, pitch_deg: Arr) -> Steady:
    """Dispatch on P['kind']."""
    return (seaglider_steady if P["kind"] == "seaglider" else slocum_steady)(rho, p, T, vbd_cc, pitch_deg, P)


def pump_energy_J(dV_cc: Arr, p_dbar: Arr, eta: float) -> Arr:
    """Work to move dV against absolute ambient pressure: p dV / eta."""
    return np.abs(dV_cc) * 1e-6 * (P_ATM + np.asarray(p_dbar) * 1e4) / eta


def _temp_c(P: dict, sst_K: Arr, depth: Arr) -> Arr:
    return P["t_deep_c"] + (sst_K - 273.15 - P["t_deep_c"]) * np.exp(-np.asarray(depth) / P["thermocline_scale_m"])


class GliderSim:
    """M-member glider ensemble.  mission: dict(mode='station'|'section'|'drift', station=(lon,lat), waypoints=[(lon,lat)..],
    heading_to=deg, dive_depth_m, station_tol_m, lost_hours, wp_radius_m, unreach_hours, vbd_delta_cc); missing keys come from
    the platform's mission_defaults.  perturb: arrays of shape (M,): speed_scale, battery_scale, density_bias [kg/m^3]."""

    def __init__(
        self,
        params: dict,
        members: int,
        env: Any,
        start_lon: Arr,
        start_lat: Arr,
        t0: float,
        mission: dict,
        perturb: dict | None = None,
    ):
        P, M = self.P, self.M = params, int(members)
        self.env, self.t = env, float(t0)
        self._tf = self.t
        md = {**P["mission_defaults"], **mission}
        self.mode = md.get("mode", "station")
        if self.mode not in MODES:
            raise ValueError(f"mode {self.mode!r} not in {MODES}")
        if self.mode == "station":
            self.wps = np.array([md["station"]], float)
        elif self.mode == "section":
            self.wps = np.array(md["waypoints"], float).reshape(-1, 2)
            if len(self.wps) == 0:
                raise ValueError("section mode needs waypoints")
        else:
            self.wps = np.zeros((0, 2))
        self.drift_dir = cv.vec_from_to(1.0, np.full(M, float(md.get("heading_to", 0.0))))
        self.md = md
        self.target_depth = min(md["dive_depth_m"], P["rating_m"])
        pt = perturb or {}
        one = lambda k: np.broadcast_to(np.asarray(pt.get(k, 1.0 if k != "density_bias" else 0.0), float), (M,)).copy()
        self.scale, self.bscale, self.rbias = one("speed_scale"), one("battery_scale"), one("density_bias")
        self.lon = np.broadcast_to(np.asarray(start_lon, float), (M,)).copy()
        self.lat = np.broadcast_to(np.asarray(start_lat, float), (M,)).copy()
        self.depth = np.zeros(M)
        self.phase = np.full(M, SURF)
        self.timer = np.zeros(M)
        self.E = np.zeros(M)
        self.cap = P["battery_J"] * self.bscale
        self.dive_depth = np.zeros(M)
        self.heading = np.zeros((M, 2))
        self.dac = np.zeros((M, 2))
        self.gd, self.dr = np.zeros((M, 2)), np.zeros((M, 2))
        self.t_dive0 = np.full(M, self.t)
        self.w_last = np.zeros(M)
        self.wp_idx = np.zeros(M, int)
        self.done = np.zeros(M, bool)
        self.d_prev = np.full(M, np.nan)
        self.t_prev_dive = np.full(M, np.nan)
        self.stuck_s = np.zeros(M)
        self.out_s = np.zeros(M)
        self.fail = {k: np.zeros(M, bool) for k in FAILS}
        self.first = {k: np.full(M, np.nan) for k in FAILS}
        self._rec: dict = {k: [] for k in ("t", "lon", "lat", "depth", "energy", "phase", "wp")}
        self.surf_s = P["gps_s"] + P["bytes_per_dive"] / P["iridium_Bps"] + P["pump_time_s"]
        self.comm_J = P["comms_W"] * (P["gps_s"] + P["bytes_per_dive"] / P["iridium_Bps"]) + P["attitude_J_per_dive"]
        self._trim()

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _met(self, lon: Arr, lat: Arr, tlon: Arr, tlat: Arr) -> Arr:
        """(M, 2) metres east, north from (lon, lat) to (tlon, tlat), shortest way round the dateline."""
        mx, my = metres_per_deg(lat)
        return np.stack([((tlon - lon + 180.0) % 360.0 - 180.0) * mx, (tlat - lat) * my], -1)

    def _state(self, depth: Arr) -> tuple:
        """(rho, p [dbar], T [degC]) at the members' positions for `depth` (M,) or (M, K); rho without the member bias."""
        z = -np.asarray(depth, float)
        lon, lat = (self.lon, self.lat) if z.ndim == 1 else (self.lon[:, None], self.lat[:, None])
        rho = self.env.density(lon, lat, z, self.t).value
        sst = self.env.sst(lon, lat, self.t).value
        return rho, gsw.p_from_z(z, lat), _temp_c(self.P, sst, -z)

    def _trim(self) -> None:
        """Pilot-style ballast and VBD settings from the nominal environment at the start position, sampled at 11 depths.
        The dive setting is `delta` below the lightest ballast point on the profile and the climb setting `delta` above the
        heaviest, so the glider keeps at least `delta` of net buoyancy in the right direction at every depth (separate dive and
        climb VBD, as the Seaglider target file has), within the pump limits.  If that span does not fit the pump range the pilot
        trims ballast weight: the vehicle mass (in the self.P copy; self.ballast_kg) is shifted to centre the span.
        uh_ref, the steering model's speed, uses the nominal environment at mid-depth."""
        P = self.P
        zs = np.linspace(0.0, self.target_depth, 11)
        rho, p, T = self._state(np.broadcast_to(zs, (self.M, 11)))
        n = neutral_vbd_cc(P, rho, p, T)
        lo, hi = P["vbd_min_cc"], P["vbd_min_cc"] + P["vbd_range_cc"]
        d = self.md.get("vbd_delta_cc", P["vbd_delta_cc"])
        need_lo, need_hi = n.min() - d, n.max() + d
        self.ballast_kg = 0.0
        if need_lo < lo or need_hi > hi:
            self.ballast_kg = float(0.5 * (lo + hi - need_lo - need_hi) * 1e-6 * rho.mean())
            key = "mass_kg" if P["kind"] == "seaglider" else "mg"
            P = self.P = {**P, key: P[key] + self.ballast_kg}
            n = neutral_vbd_cc(P, rho, p, T)
        self.vbd_dive, self.vbd_climb = np.clip(n.min(1) - d, lo, hi), np.clip(n.max(1) + d, lo, hi)
        k = 5
        sd = flight(P, rho[:, k], p[:, k], T[:, k], self.vbd_dive, -P["pitch_deg"])
        sa = flight(P, rho[:, k], p[:, k], T[:, k], self.vbd_climb, P["pitch_deg"])
        self.uh_ref = 0.5 * (sd.speed * np.cos(np.radians(sd.glide_deg)) + sa.speed * np.cos(np.radians(sa.glide_deg)))

    def _flag(self, name: str, mask: Arr) -> None:
        new = mask & ~self.fail[name]
        self.first[name][new] = self._tf
        self.fail[name] |= mask

    def _target_vec(self) -> tuple:
        """Metres to the active waypoint for every member, and the distance."""
        k = np.minimum(self.wp_idx, len(self.wps) - 1)
        v = self._met(self.lon, self.lat, self.wps[k, 0], self.wps[k, 1])
        return v, np.hypot(v[:, 0], v[:, 1])

    def _begin_dive(self, m: Arr) -> None:
        P, md = self.P, self.md
        floor = self.env.depth(self.lon, self.lat).value
        dd = np.minimum(np.minimum(self.target_depth, floor - P["seafloor_margin_m"]), P["rating_m"])
        can = dd >= P["min_dive_m"]
        self._flag("seafloor", m & ~can)
        go = m & can
        if not go.any():
            return
        if self.mode == "drift":
            self.heading = np.where(go[:, None], self.drift_dir, self.heading)
        else:
            v, dist = self._target_vec()
            if self.mode == "section":
                K = len(self.wps)
                for _ in range(K):  # capture radius reached -> next waypoint
                    adv = go & (dist < md["wp_radius_m"]) & (self.wp_idx < K - 1)
                    if not adv.any():
                        break
                    self.wp_idx = self.wp_idx + adv
                    self.d_prev[adv] = np.nan
                    v, dist = self._target_vec()
                self.done |= go & (dist < md["wp_radius_m"]) & (self.wp_idx == K - 1)
                cyc = self.t - self.t_prev_dive
                bad = go & ~self.done & (self.d_prev - dist < 0)  # NaN d_prev compares False
                self.stuck_s = np.where(go, np.where(bad, self.stuck_s + cyc, 0.0), self.stuck_s)
                self._flag("waypoint_unreachable", self.stuck_s > md["unreach_hours"] * 3600.0)
                self.d_prev = np.where(go, dist, self.d_prev)
                self.t_prev_dive = np.where(go, self.t, self.t_prev_dive)
            e = np.where((dist > 1.0)[:, None], v / np.maximum(dist, 1.0)[:, None], np.array([0.0, 1.0]))
            perp = np.stack([-e[:, 1], e[:, 0]], -1)
            r = np.clip(
                np.sum(self.dac * perp, -1) / np.maximum(self.uh_ref, 1e-3), -1.0, 1.0
            )  # swim r upstream of the cross current
            h = np.sqrt(1.0 - r * r)[:, None] * e - r[:, None] * perp
            self.heading = np.where(go[:, None], h, self.heading)
        self.dive_depth = np.where(go, dd, self.dive_depth)
        self.phase = np.where(go, DESC, self.phase)
        self.t_dive0 = np.where(go, self.t, self.t_dive0)
        self.gd[go] = 0.0
        self.dr[go] = 0.0

    # ---- one step ------------------------------------------------------------------------------------------------
    def step(self, dt: float) -> None:
        P, env = self.P, self.env
        self._tf = self.t + dt  # failures are stamped with the end of the step
        self._begin_dive((self.phase == SURF) & (self.timer <= 0.0))
        d0, apo0, a0, s0 = (self.phase == k for k in (DESC, APO, ASC, SURF))
        fly = d0 | a0
        cur = env.current(self.lon, self.lat, -self.depth, self.t).value
        if s0.any():
            cur = np.where(s0[:, None], cur + P["windage"] * env.wind(self.lon, self.lat, 10.0, self.t).value, cur)
        dr_nom = np.zeros((self.M, 2))
        move = cur * dt
        if fly.any():
            rho, p, T = self._state(self.depth)
            vbd = np.where(d0, self.vbd_dive, self.vbd_climb)
            st = flight(P, rho + self.rbias, p, T, vbd, np.where(d0, -P["pitch_deg"], P["pitch_deg"]))
            self._flag("no_flight", fly & ~st.ok)
            th = np.radians(st.glide_deg)
            uh_nom = st.speed * np.cos(th)
            sw = np.where(fly, st.w * self.scale, 0.0)
            dr_nom = (np.where(fly, uh_nom, 0.0)[:, None]) * self.heading * dt
            move = move + dr_nom * self.scale[:, None]
            self.depth = np.where(fly, self.depth - sw * dt, self.depth)
            self.w_last = np.where(d0, np.abs(sw), self.w_last)
        self.depth = np.where(apo0, self.depth + P["apogee_overshoot"] * self.w_last * dt, self.depth)
        diving = ~s0
        self.gd += np.where(diving[:, None], move, 0.0)
        self.dr += dr_nom
        mx, my = metres_per_deg(self.lat)
        self.lon = (self.lon + move[:, 0] / mx + 180.0) % 360.0 - 180.0
        self.lat = np.clip(self.lat + move[:, 1] / my, -90.0, 90.0)
        self.E += P["hotel_W"] * dt
        self.t += dt
        # phase changes
        self.timer = np.where(s0 | apo0, self.timer - dt, self.timer)
        end_apo = apo0 & (self.timer <= 0.0)
        self.phase = np.where(end_apo, ASC, self.phase)
        reach = d0 & (self.depth >= self.dive_depth)
        self.depth = np.where(reach, self.dive_depth, self.depth)
        self.phase = np.where(reach, APO, self.phase)
        self.timer = np.where(reach, P["pump_time_s"], self.timer)
        dV = self.vbd_climb - self.vbd_dive
        self.E += np.where(reach, pump_energy_J(dV, gsw.p_from_z(-self.dive_depth, self.lat), P["pump_eta"]), 0.0)
        up = a0 & (self.depth <= 0.0)
        if up.any():
            self.depth = np.where(up, 0.0, self.depth)
            self.phase = np.where(up, SURF, self.phase)
            self.timer = np.where(up, self.surf_s, self.timer)
            self.dac = np.where(up[:, None], (self.gd - self.dr) / np.maximum(self.t - self.t_dive0, 1.0)[:, None], self.dac)
            self.E += np.where(up, self.comm_J + pump_energy_J(dV, 0.0, P["pump_eta"]), 0.0)
        # failures
        self._flag("battery", self.E > self.cap * (1.0 - P["reserve_frac"]))
        self._flag("overdepth", self.depth > P["rating_m"])
        self._flag("seafloor", self.depth >= env.depth(self.lon, self.lat).value)
        if self.mode == "station":
            _, dist = self._target_vec()
            self.out_s = np.where(dist > self.md["station_tol_m"], self.out_s + dt, 0.0)
            self._flag("station_lost", self.out_s > self.md["lost_hours"] * 3600.0)
        for k, v in (
            ("t", self.t),
            ("lon", self.lon),
            ("lat", self.lat),
            ("depth", self.depth),
            ("energy", self.E),
            ("phase", self.phase),
            ("wp", self.wp_idx),
        ):
            self._rec[k].append(np.copy(v))

    def run(self, seconds: float, dt: float = 60.0) -> dict:
        for _ in range(int(round(seconds / dt))):
            self.step(dt)
        return self.history()

    def history(self) -> dict:
        """Arrays (steps, M) for lon, lat, depth, energy [J used], phase (0 descent, 1 apogee pump, 2 ascent, 3 surface), wp
        (active waypoint index); t (steps,) [s]; fail[name] (M,) bool; first[name] (M,) end of the first step in which it was
        true, NaN if never."""
        h: dict = {k: np.array(v) for k, v in self._rec.items()}
        h["fail"], h["first"] = self.fail, self.first
        return h


# ---- receipts --------------------------------------------------------------------------------------------------------
CANON_DELTA_CC = 150.0  # assumed nominal dive/climb buoyancy, +-1.5 N, for the steady-flight receipts only (not the simulator)


def _canon(P: dict) -> tuple:
    """Receipt reference state: rho 1026 kg/m^3, 251 dbar, 12 degC, VBD settings 150 cc either side of its ballast point."""
    rho, p, T = 1026.0, 251.0, 12.0
    n = neutral_vbd_cc(P, rho, p, T)
    return rho, p, T, n - CANON_DELTA_CC, n + CANON_DELTA_CC


def _gliderflight_error(Q: dict, rng: Any) -> tuple:
    """Max relative difference of (U, w, alpha), slocum_steady vs gliderflight SteadyStateGliderModel, on 24 shared states."""
    import gliderflight as gf

    n = 24
    rho, p = rng.uniform(1020.0, 1030.0, n), rng.uniform(0.0, 1000.0, n)
    pitch = rng.choice([-35.0, -26.0, -15.0, 15.0, 26.0, 35.0], n)
    vbd = neutral_vbd_cc(Q, rho, p, 10.0) + np.sign(pitch) * rng.uniform(80.0, 250.0, n)
    gm = gf.SteadyStateGliderModel(rho0=1024)
    gm.define(
        mg=Q["mg"], Vg=Q["Vg"], Cd0=float(Q["Cd0"]), Cd1=float(Q["Cd1"]), aw=Q["aw"], ah=Q["ah"], S=Q["S"], epsilon=Q["epsilon"]
    )
    gm.solve(dict(time=np.arange(n) * 60.0, pressure=p / 10.0, pitch=np.radians(pitch), buoyancy_change=vbd, density=rho))
    r, mine = gm.modelresult, slocum_steady(rho, p, 10.0, vbd, pitch, Q)
    rel = lambda a, b: float(np.max(np.abs(a - b) / np.abs(b)))
    return rel(mine.speed, r.U), rel(mine.w, r.w), rel(mine.alpha_deg, -np.degrees(r.alpha))


def _station_flags(P: dict, current: float, horizontal: float) -> float:
    """Fraction of 4 members that lose station in 7 days against a uniform eastward `current` [m/s] when the glider's
    horizontal through-water speed is scaled to `horizontal` [m/s]."""
    from ..env.protocol import AnalyticEnv

    env = AnalyticEnv(
        wind=(0.0, 0.0), current=(current, 0.0), current_profile=lambda z: np.ones_like(np.asarray(z, float)), rho=1025.0
    )
    mission = dict(mode="station", station=(180.0, 0.0))
    probe = GliderSim(P, 4, env, 180.0, 0.0, 0.0, mission)
    sim = GliderSim(P, 4, env, 180.0, 0.0, 0.0, mission, perturb=dict(speed_scale=horizontal / probe.uh_ref))
    return float(sim.run(7 * 86400.0, 60.0)["fail"]["station_lost"].mean())


def receipts(params: dict | None = None) -> list:
    """Run every glider receipt; returns the entries added to cafe.receipts.OUT.  `params` replaces the Seaglider defaults
    (tests use it to break units).  Degenerate (broken) physics gives failed receipts, not floating-point warnings."""
    with np.errstate(all="ignore"):
        return _receipts(params)


def _receipts(params: dict | None) -> list:
    from cafe import receipts as rc

    n0 = len(rc.OUT)
    P = params or load_platform("seaglider")
    Q = load_platform("slocum")
    G = "glider"
    rho, p, T, vd, vc = _canon(P)
    sd, sc = seaglider_steady(rho, p, T, vd, -P["pitch_deg"], P), seaglider_steady(rho, p, T, vc, P["pitch_deg"], P)

    # 1. published Seaglider relations
    src = "Eriksen et al. 2001 (typical Seaglider: 0.25 m/s horizontal at glide ratio 1:3); Kongsberg spec 25 cm/s; BRIEF 2.4"
    uh = 0.5 * (sd.speed * np.cos(np.radians(sd.glide_deg)) + sc.speed * np.cos(np.radians(sc.glide_deg)))
    ratio = 0.5 * (1.0 / np.tan(np.radians(-sd.glide_deg)) + 1.0 / np.tan(np.radians(sc.glide_deg)))
    rc.receipt(G, "Seaglider default flight: horizontal speed", float(uh), 0.25, 0.15, "m/s", src)
    rc.receipt(G, "Seaglider default flight: glide ratio (horizontal : vertical)", float(ratio), 3.0, 0.15, "", src)
    for nm, s in (("dive", sd), ("climb", sc)):
        rc.bracket(
            G, f"Seaglider {nm}: speed through water", float(s.speed), 0.2, 0.5, "m/s", "BRIEF 2.4: ~0.2-0.5 m/s path speed"
        )
        rc.bracket(
            G,
            f"Seaglider {nm}: glide ratio",
            float(1.0 / np.tan(np.radians(abs(s.glide_deg)))),
            1.0,
            5.0,
            "",
            "BRIEF 2.4: glide slope 1:1 - 1:5",
        )
        rc.bracket(
            G,
            f"Seaglider {nm}: |alpha| (hd_a is per degree)",
            float(abs(s.alpha_deg)),
            1.0,
            8.0,
            "deg",
            "BS3 HydroModel.py: alpha in degrees; a few degrees at 1:3 (this model: ~4)",
        )

    # 2. the steady balance holds as vectors (x, z components of B z - D t + L n = 0) and a different solver finds the same state
    from scipy.optimize import fsolve

    worst = 0.0
    for s, v in ((sd, vd), (sc, vc)):
        B = float(buoyancy(P, rho, p, T, v))
        L, D = seaglider_force_balance(P, s.speed, s.glide_deg, s.alpha_deg, rho)
        th = np.radians(s.glide_deg)
        fx = -D * np.cos(th) - L * np.sin(th)
        fz = B - D * np.sin(th) + L * np.cos(th)
        worst = max(worst, float(np.hypot(fx, fz) / abs(B)))
    rc.bracket(G, "Seaglider steady state: |sum of forces| / |B|", worst, 0.0, 1e-6, "", "force balance, x and z components")
    B = float(buoyancy(P, rho, p, T, vc))
    eq = lambda x: [
        seaglider_force_balance(P, np.sqrt(2 * x[0] / rho), x[1], x[2], rho)[1] - B * np.sin(np.radians(x[1])),
        seaglider_force_balance(P, np.sqrt(2 * x[0] / rho), x[1], x[2], rho)[0] + B * np.cos(np.radians(x[1])),
        x[1] + x[2] - P["pitch_deg"],
    ]
    q_f, th_f, _ = fsolve(eq, [30.0, 20.0, -3.0], xtol=1e-12)
    rc.receipt(
        G,
        "Seaglider speed: fixed-point iteration vs fsolve on the balance",
        float(sc.speed),
        float(np.sqrt(2 * q_f / rho)),
        1e-5,
        "m/s",
        "Eriksen 2001 eqs. 7-8 (as BS3) vs direct root-find of D = B sin th, L = -B cos th",
    )

    # 3. hull compressibility: the hull compresses less than seawater (BS3), so a glider gets MORE buoyant with depth
    SA, CT = 35.0, 15.0
    r0, r1 = (float(gsw.rho(SA, CT, pp)) for pp in (0.0, 1000.0))
    v0 = neutral_vbd_cc(P, r0, 0.0, 15.0)
    dB = float(buoyancy(P, r1, 1000.0, 15.0, v0) - buoyancy(P, r0, 0.0, 15.0, v0))
    kappa = np.log(r1 / r0) / 1000.0
    rc.bracket(
        G,
        "Seaglider: seawater compressibility minus hull abs_compress",
        float(kappa - P["abs_compress"]),
        0.0,
        1e-6,
        "1/dbar",
        "BS3 FlightModel.py: abs_compress 4.1e-6 is 'slightly less than the compressibility of SW'",
    )
    rc.receipt(
        G,
        "Seaglider: buoyancy gain 0 -> 1000 dbar at 15 degC (sign + : deeper = more buoyant)",
        dB,
        P["gravity"]
        * r0
        * (P["volmax_cc"] - P["vbd_range_cc"] + v0)
        * 1e-6
        * (np.exp((kappa - P["abs_compress"]) * 1000.0) - 1.0),
        0.02,
        "N",
        "g rho V (exp((kappa - gamma) p) - 1), kappa from TEOS-10",
    )

    # 4. Slocum against the gliderflight oracle
    try:
        eu, ew, ea = _gliderflight_error(Q, np.random.default_rng(7))
        for nm, e in (("speed", eu), ("vertical speed", ew), ("angle of attack", ea)):
            rc.receipt(
                G,
                f"Slocum vs gliderflight 1.2.1 steady model, 24 shared states: max relative error in {nm}",
                e,
                0.0,
                2e-3,
                "",
                "gliderflight SteadyStateGliderModel (Merckelbach 2010/2019); tolerance = its 100-point alpha(pitch) table",
                rel=False,
            )
    except ImportError:
        rc.context(
            G, "Slocum vs gliderflight: oracle not installed, comparison NOT run", 0.0, 0.0, "", "pip install gliderflight==1.2.1"
        )

    # 5. kinematics: first descent time = integral dz / |w(z)|
    from ..env.protocol import AnalyticEnv

    env = AnalyticEnv(wind=(0.0, 0.0), rho=1025.0)
    sim = GliderSim(P, 1, env, 180.0, 0.0, 0.0, dict(mode="drift", heading_to=90.0))
    h = sim.run(86400.0, 60.0)
    t_sim = float(h["t"][np.argmax(h["phase"][:, 0] == APO)])
    z = np.linspace(0.0, sim.target_depth, 2001)
    rz, pz, Tz = sim._state(z[None, :])
    wz = flight(P, rz[0], pz[0], Tz[0], sim.vbd_dive[0], -P["pitch_deg"]).w
    f = 1.0 / np.abs(wz)
    rc.receipt(
        G,
        "first descent time to the dive depth vs integral of dz/|w| (60 s steps)",
        t_sim,
        float(np.sum(0.5 * (f[1:] + f[:-1]) * np.diff(z))),
        0.02,
        "s",
        "kinematics: dt = dz / w",
    )

    # 6. station keeping: 0.3 m/s cannot hold against 0.5 m/s, can against 0.1 m/s (BRIEF 1.4)
    rc.bracket(
        G,
        "glider at 0.3 m/s vs uniform 0.5 m/s current: fraction of members losing station",
        _station_flags(P, 0.5, 0.3),
        1.0,
        1.0,
        "",
        "BRIEF 1.4: gliders at 0.25-0.4 m/s cannot hold station against a jet; swimming 0.3 < current 0.5 m/s",
    )
    rc.bracket(
        G,
        "glider at 0.3 m/s vs uniform 0.1 m/s current: fraction of members losing station",
        _station_flags(P, 0.1, 0.3),
        0.0,
        0.0,
        "",
        "swimming 0.3 > current 0.1 m/s with dive-averaged-current steering",
    )

    # 7. energy
    e_full = float(pump_energy_J(P["vbd_range_cc"] * 0.35, 1005.0, P["pump_eta"]))
    rc.bracket(
        G,
        "VBD pump energy, 300 cc against 1000 m",
        e_full,
        1172.0,
        7800.0,
        "J",
        "NOC glider page: 65 W x ~2 min = 7.8 kJ (upper); Copernicus os-2019-36: 1172 J at apogee for a +-21 cc dive (lower)",
    )
    rc.context(
        G,
        "VBD pump energy at apogee, +-21 cc dive to 1000 m",
        float(pump_energy_J(42.0, 1005.0, P["pump_eta"])),
        1172.0,
        "J",
        "Copernicus os-2019-36 dive 227 (different dive; shown for scale)",
    )

    # 8. local metres per degree against the WGS84 ellipsoid
    a, e2 = 6378137.0, 0.00669437999014
    for lat in (0.0, 30.0, 60.0):
        s2 = np.sin(np.radians(lat)) ** 2
        mx, my = metres_per_deg(lat)
        rc.receipt(
            G,
            f"metres per degree of longitude at {lat:.0f} N",
            float(mx),
            a * np.cos(np.radians(lat)) / np.sqrt(1 - e2 * s2) * np.pi / 180.0,
            1e-5,
            "m",
            "WGS84 ellipsoid: N cos(phi) pi/180",
        )
        rc.receipt(
            G,
            f"metres per degree of latitude at {lat:.0f} N",
            float(my),
            a * (1 - e2) / (1 - e2 * s2) ** 1.5 * np.pi / 180.0,
            1e-5,
            "m",
            "WGS84 ellipsoid: M pi/180",
        )
    return rc.OUT[n0:]
