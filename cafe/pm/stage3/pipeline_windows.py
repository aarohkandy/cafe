"""The adapter the pipeline calls for stage 3: `run(ctx, wins, L) -> {vehicle_id: [row, ...]}`.

For every window of `windows/windows.json` (`{vid: [{t, lon, lat, stress, basis}]}`) it builds the vehicle from its platform yaml
(plus the numbers in config/assumptions.yaml under `stage3.*` for every dimension no yaml has), takes the inflow from `ctx.env` at the
window's time and place, runs one wall-modelled LES window (windows.run_window) and, for the glider hull, the FEA of the pressure
hull, and returns one row per window and part. A USV has two parts, `hull` (water) and `wing` (air): the two flows are different
fluids with different Reynolds numbers, so one window cannot carry both.

Frames. The window frame is the body frame. Per class, with R the rotation of ENU into body axes, the window gets
    inflow   = R u_env          (ground-frame environment velocity at the window)
    velocity = R v_vehicle      (vehicle velocity over the ground)
so the flow relative to the body is R (u_env - v_vehicle):
  glider  u_env = current at the glider's working depth; v = current + through-water velocity (speed, glide angle and angle of attack
          from glider.flight at the window's density, pressure and temperature, descending leg); body pitch = -|pitch_deg|;
  usv     hull: u_env = current, v = current + stw along the track (usv.through_water); wing: u_env = wind at the anemometer height,
          v = the same boat velocity, wing at its trim angle of attack to the apparent wind (the wing's lift axis is body z);
  uas     u_env = wind at `uas.window_altitude_m`, v = leg speed along the heading; body tilted by atan(d_x |v_rel| / g) (Faessler et al.
          2018 linear rotor drag), rotors are not modelled (no actuator disk).
Heading is the median stage-1 track heading around the window (`stage1/res.pkl`, nanmedian over members, central difference of the
two neighbouring records); without it, the relative-flow direction: gliders head with the current, the USV downwind, the UAS into the wind.

`cd_hangar`, `cl_hangar`: what the vehicle's own Stage-1 model implies at this window's speed, as coefficients on the same reference
area and density as the window's (cd = F / (rho/2 V^2 A_ref)), so the refit ratio window / hangar means something. Sources are named in
`cd_hangar_source`. Residuary (wave) resistance of the USV hull is left out of the hangar number: the window has no free surface.

Resolution. cells x steps is fitted to plan["les"]["cell_steps_per_window"] (shared between the parts of a USV window) with
lbm.les_resolution: dx is the 10-cells-per-boundary-layer value (BRIEF 2.6) coarsened by the fourth root of the budget shortfall
(cells ~ dx^-3, steps ~ dx^-1), but never so coarse that the smallest body dimension has fewer than `stage3.min_cells_across` cells,
and the run is never shorter than `stage3.min_flow_throughs` box transits. `budget_ok` in the row says whether the budget held. With
plan["les"]["cpu_fallback"] the row is still computed for real and carries the plan's label. A row's `ok` needs every stage-3 self-check
to pass, including the wall-model receipt row (windows.stage3_checks): the refit uses only rows with ok, so no unvalidated coefficient
reaches Stage 1b.
"""
from __future__ import annotations

import math
import pathlib
import pickle
import time
from typing import Any

import numpy as np
import jax.numpy as jnp

from .. import config
from ..physics import glider, uas, usv
from . import lbm, windows as W

G = 9.81


# ---------------------------------------------------------------------------------------------------- assumptions
def assumptions(path=None) -> dict:
    """config/assumptions.yaml keys `stage3.*` -> {short key: value}. A missing key is an error that names it."""
    raw = config.assumptions()
    return {k[len("stage3."):]: v["value"] for k, v in raw.items() if k.startswith("stage3.")}


def need(a: dict, key: str) -> Any:
    if key not in a:
        raise KeyError(f"config/assumptions.yaml has no 'stage3.{key}' (value, unit, why, replace_with)")
    return a[key]


# ---------------------------------------------------------------------------------------------------- frames
def rotation(heading_to_deg: float, pitch_deg: float = 0.0) -> np.ndarray:
    """ENU -> body (x forward, y left, z up). Heading is compass degrees to which x points (horizontal part), pitch is + nose up."""
    h, p = math.radians(heading_to_deg), math.radians(pitch_deg)
    x = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])
    y = np.array([-math.cos(h), math.sin(h), 0.0])
    return np.stack([x, y, np.cross(x, y)])


def compass(e: float, n: float) -> float:
    return math.degrees(math.atan2(e, n)) % 360.0


def track_heading(res: dict | None, vid: str, t: float) -> float | None:
    """Median stage-1 track heading around time t: central difference of the member-median position at the records either side."""
    if not res or vid not in res.get("vehicles", {}):
        return None
    r = res["vehicles"][vid]
    tt = np.asarray(r["t"], float)
    with np.errstate(all="ignore"):
        lon, lat = np.nanmedian(np.asarray(r["lon"], float), 1), np.nanmedian(np.asarray(r["lat"], float), 1)
    i = int(np.argmin(np.abs(tt - t)))
    j0, j1 = max(i - 1, 0), min(i + 1, len(tt) - 1)
    if j0 == j1 or not np.isfinite([lon[j0], lon[j1], lat[j0], lat[j1]]).all():
        return None
    de = ((lon[j1] - lon[j0] + 180.0) % 360.0 - 180.0) * math.cos(math.radians(0.5 * (lat[j0] + lat[j1])))
    dn = lat[j1] - lat[j0]
    return None if math.hypot(de, dn) < 1e-9 else compass(de, dn)


def _val(x) -> np.ndarray:
    return np.asarray(getattr(x, "value", x), float)


# ---------------------------------------------------------------------------------------------------- geometry, per class
def glider_vehicle(P: dict, a: dict, platform: str, depth: float) -> W.Vehicle:
    """Hull (ellipsoid) + wings (flat plate). Seaglider: length from the yaml; Slocum has no length in its yaml (stage3.slocum.*)."""
    if P["kind"] == "seaglider":
        L, D = P["length_m"], need(a, "glider.hull_diameter_m")
        span, chord = need(a, "glider.wing_span_m"), need(a, "glider.wing_chord_m")
    else:
        L, D = need(a, "slocum.length_m"), need(a, "slocum.hull_diameter_m")
        span = math.sqrt(P["S"] * P["AR"])
        chord = P["S"] / span
    wing = dict(type="plate", center=(need(a, "glider.wing_x_frac") * L, 0.0, 0.0), size=(chord, span, need(a, "glider.wing_thickness_m")))
    hull = dict(type="ellipsoid", center=(0.0, 0.0, 0.0), radii=(L / 2, D / 2, D / 2))
    return W.Vehicle(platform, "water", L, [hull, wing], ref_area=math.pi * D * D / 4, material=need(a, "glider.hull_material"),
                     thickness=need(a, "glider.hull_thickness_m"), depth=depth, hull=0, extra=dict(resolve_dim=D, part="body"))


def usv_vehicle(P: dict, a: dict, platform: str, part: str) -> W.Vehicle:
    if part == "hull":
        draft = need(a, "usv.hull_draft_m")
        kc = P["keel_area_m2"] / P["keel_span_m"]
        hull = dict(type="ellipsoid", center=(0.0, 0.0, 0.0), radii=(P["lwl_m"] / 2, P["beam_wl_m"] / 2, draft))
        keel = dict(type="plate", center=(0.0, 0.0, -(draft + P["keel_span_m"] / 2)), size=(kc, P["keel_t_c"] * kc, P["keel_span_m"]))
        frontal = math.pi * (P["beam_wl_m"] / 2) * draft + P["keel_t_c"] * kc * P["keel_span_m"]
        return W.Vehicle(platform, "water", P["lwl_m"], [hull, keel], ref_area=frontal, hull=0,
                         extra=dict(resolve_dim=min(P["beam_wl_m"], 2 * draft), part="hull"))
    c = P["wing_area_m2"] / P["wing_span_m"]
    wing = dict(type="plate", center=(0.0, 0.0, 0.0), size=(c, P["wing_span_m"], need(a, "usv.wing_t_c") * c))     # span along y: lift axis is body z
    return W.Vehicle(platform, "air", max(c, P["wing_span_m"]), [wing], ref_area=P["wing_area_m2"], hull=0,
                     extra=dict(resolve_dim=c, part="wing"))


def uas_vehicle(P: dict, a: dict, platform: str) -> W.Vehicle:
    bx, by, bz = need(a, "uas.body_radii_m")
    arm_l, arm_w, arm_t = need(a, "uas.arm_length_m"), need(a, "uas.arm_width_m"), need(a, "uas.arm_thickness_m")
    shapes = [dict(type="ellipsoid", center=(0.0, 0.0, 0.0), radii=(bx, by, bz)),
              dict(type="plate", center=(0.0, 0.0, 0.0), size=(arm_l, arm_w, arm_t)),
              dict(type="plate", center=(0.0, 0.0, 0.0), size=(arm_w, arm_l, arm_t))]
    frontal = math.pi * by * bz + (arm_l + arm_w) * arm_t
    return W.Vehicle(platform, "air", arm_l, shapes, ref_area=frontal, hull=0, extra=dict(resolve_dim=2 * bz, part="body"))


# ---------------------------------------------------------------------------------------------------- kinematics + hangar, per class
def _coef(force: float, rho: float, v: float, area: float | None) -> float:
    assert area is not None, "the stage-3 vehicles always carry an analytic reference area"
    return float(force / (0.5 * rho * v * v * area))


def glider_case(ctx, w: dict, P: dict, veh: W.Vehicle, a: dict, heading: float | None) -> dict:
    env, t, lon, lat = ctx.env, w["t"], w["lon"], w["lat"]
    z = -need(a, "glider.window_depth_m")
    cur = _val(env.current(lon, lat, z, t))[:2]
    rho = float(_val(env.density(lon, lat, z, t)))
    sst = float(_val(env.sst(lon, lat, t)))
    p = -z                                                                  # dbar ~ m
    T = float(glider._temp_c(P, sst, -z))
    pitch = -abs(P["pitch_deg"])                                            # descending leg
    vbd = float(glider.neutral_vbd_cc(P, rho, p, T)) - P["vbd_delta_cc"]
    st = glider.flight(P, rho, p, T, vbd, pitch)
    if not bool(np.asarray(st.ok)):
        raise ValueError("the glider has no steady flight at this window's density and pressure (stalled)")
    U, th, al = float(st.speed), float(st.glide_deg), float(st.alpha_deg)
    if heading is None:
        heading = compass(*cur) if np.hypot(*cur) > 1e-6 else 0.0
    hs = np.array([math.sin(math.radians(heading)), math.cos(math.radians(heading))])
    tw = U * np.array([math.cos(math.radians(th)) * hs[0], math.cos(math.radians(th)) * hs[1], math.sin(math.radians(th))])
    u_env, v = np.array([cur[0], cur[1], 0.0]), np.array([cur[0], cur[1], 0.0]) + tw
    A = veh.ref_area
    if P["kind"] == "seaglider":
        Lh, Dh = glider.seaglider_force_balance(P, U, th, al, rho)
        src = "glider.seaglider_force_balance: BS3 hydrodynamic model D = l^2 q (b q^s + c alpha^2), L = l^2 a q alpha at the steady flight state"
    else:
        qS = 0.5 * rho * U * U * P["S"]
        Dh, Lh = qS * (P["Cd0"] + P["Cd1"] * math.radians(al) ** 2), qS * (P["aw"] + P["ah"]) * math.radians(al)
        src = "glider slocum_steady: D = q S (Cd0 + Cd1 alpha^2), L = q S (aw + ah) alpha (Merckelbach form) at the steady flight state"
    return dict(R=rotation(heading, pitch), u_env=u_env, v=v, heading=heading, rho_h=rho, area=A,
                cd_h=_coef(float(Dh), rho, U, A), cl_h=_coef(float(Lh), rho, U, A), src=src + f" (U {U:.3f} m/s, glide {th:.1f} deg, alpha {al:.1f} deg)",
                info=dict(through_water_ms=U, glide_deg=th, alpha_deg=al, pitch_deg=pitch))


def usv_case(ctx, w: dict, P: dict, veh: W.Vehicle, a: dict, heading: float | None, part: str) -> dict:
    env, t, lon, lat = ctx.env, w["t"], w["lon"], w["lat"]
    wind = _val(env.wind(lon, lat, P["anemometer_m"], t))[:2]
    cur = _val(env.current(lon, lat, P["current_z_m"], t))[:2]
    if heading is None:                                                     # downwind: the relative-flow direction of a boat with no steering
        heading = (compass(*wind) if np.hypot(*wind) > 1e-6 else 0.0)
    tw = usv.through_water(P, wind, cur, heading)
    stw, track = float(np.asarray(tw["stw"])), float(np.asarray(tw["track_to"]))
    if not stw > 0.0:
        raise ValueError("the USV makes no way through the water at this window's wind (becalmed)")
    vg = cur + stw * np.array([math.sin(math.radians(track)), math.cos(math.radians(track))])
    if part == "hull":
        lee = float(np.asarray(tw["leeway_deg"]))
        rho_w = P["rho_water"]
        # viscous part of hull_resistance (ITTC-57 friction x (1 + k) on the wetted area; no residuary term: no free surface in the window)
        # plus the keel's friction/profile drag at zero leeway (usv._forces)
        re = stw * P["lwl_m"] / P["nu_water"]
        r_hull = 0.5 * rho_w * stw ** 2 * P["wetted_area_m2"] * usv.cf_ittc57(re) * (1.0 + P["form_factor_k"])
        k_area, _, _, k_tc, k_c = usv._foil(P, "keel")
        r_keel = 0.5 * rho_w * stw ** 2 * k_area * 2 * usv.cf_ittc57(stw * k_c / P["nu_water"]) * (1 + 2 * k_tc + 60 * k_tc ** 4)
        u_env, v = np.array([cur[0], cur[1], 0.0]), np.array([vg[0], vg[1], 0.0])
        return dict(R=rotation(heading, 0.0), u_env=u_env, v=v, heading=heading, rho_h=rho_w, area=veh.ref_area,
                    cd_h=_coef(float(r_hull + r_keel), rho_w, stw, veh.ref_area), cl_h=None,
                    src="usv.cf_ittc57 x (1 + form_factor_k) on the wetted area + keel friction/profile drag at zero leeway; residuary and "
                        f"appendage terms excluded (no free surface / appendages in the window); stw {stw:.3f} m/s, leeway {lee:.1f} deg",
                    info=dict(stw_ms=stw, leeway_deg=lee, heel_deg=float(np.asarray(tw["heel_deg"]))))
    aw = wind - vg                                                          # apparent wind (air relative to the boat, over the ground frame)
    aws = float(np.hypot(*aw))
    if aws < P["trim_min_aws_ms"]:
        raise ValueError(f"apparent wind {aws:.2f} m/s is below the wing's trim minimum {P['trim_min_aws_ms']} m/s (wing_stall)")
    alpha = P["wing_trim_deg"]
    cl, cd = (float(np.asarray(x)) for x in usv.wing_polar(P, alpha))
    # body frame of the wing window: x = chord, y = span (horizontal in the window), z = lift axis. The flow relative to the wing is
    # -V (cos a, 0, -sin a) (it arrives from slightly below the chord), so the vehicle velocity is V (cos a, 0, -sin a) in still air.
    ca, sa = math.cos(math.radians(alpha)), math.sin(math.radians(alpha))
    return dict(R=None, u_env=np.zeros(3), v=aws * np.array([ca, 0.0, -sa]), heading=heading, rho_h=P["rho_air"], area=veh.ref_area,
                cd_h=cd, cl_h=cl,
                src=f"usv.wing_polar at the trim angle of attack ({alpha} deg) on the wing area; apparent wind speed {aws:.2f} m/s",
                info=dict(aws_ms=aws, alpha_deg=alpha))


def uas_case(ctx, w: dict, P: dict, veh: W.Vehicle, a: dict, heading: float | None) -> dict:
    env, t, lon, lat = ctx.env, w["t"], w["lon"], w["lat"]
    wind = _val(env.wind(lon, lat, need(a, "uas.window_altitude_m"), t))[:2]
    air = env.air(lon, lat, t)
    rho = float(uas.air_density(float(_val(air["psfc"])), float(_val(air["T2"])), float(_val(air["q2"]))))
    if heading is None:                                                     # into the wind: the relative flow is then along the body axis
        heading = (compass(-wind[0], -wind[1]) if np.hypot(*wind) > 1e-6 else 0.0)
    leg = min(P["sortie"]["leg_speed_ms"], P["limits"]["max_airspeed_ms"])
    hv = np.array([math.sin(math.radians(heading)), math.cos(math.radians(heading))])
    v = np.array([leg * hv[0], leg * hv[1], 0.0])
    u_env = np.array([wind[0], wind[1], 0.0])
    vrel = float(np.linalg.norm(u_env - v))
    if vrel < 1e-3:
        raise ValueError("no relative flow: the UAS drifts with the wind")
    dx = P["aero"]["d_x"]
    tilt = math.degrees(math.atan(dx * vrel / G))
    f_drag = P["airframe"]["mass_kg"] * dx * vrel                           # F = m d_x v: Faessler et al. 2018 linear rotor drag
    return dict(R=rotation(heading, -tilt), u_env=u_env, v=v, heading=heading, rho_h=rho, area=veh.ref_area,
                cd_h=_coef(f_drag, rho, vrel, veh.ref_area), cl_h=None,
                src=f"uas aero.d_x = {dx} 1/s linear drag, F = m d_x |v_rel| (Faessler, Franchi, Scaramuzza 2018); includes the rotor "
                    "momentum drag, which the window (no rotors) does not; the ratio therefore reads as 'frame drag / total drag'",
                info=dict(v_rel_ms=vrel, tilt_deg=tilt))


# ---------------------------------------------------------------------------------------------------- resolution
def fit_window(veh: W.Vehicle, speed: float, budget: float, a: dict) -> dict:
    """dx, steps and box so that cells x steps <= budget where the body allows. The shortest acceptable run is `min_flow_throughs`
    box transits; dx is the 10-cells-per-delta value coarsened by the fourth root of (cells x shortest run) / budget (cells ~ dx^-3,
    transit steps ~ dx^-1), then capped so the smallest body dimension keeps `min_cells_across` cells. The run then takes as many
    steps as the budget allows between that shortest run and `window_s` of physical time."""
    box = tuple(need(a, "box_bodies"))
    T, n = need(a, "window_s"), need(a, "cells_per_delta")
    fine = lbm.les_resolution(veh.length, speed, W.NU[veh.fluid], (n,), box, T)["rows"][n]
    transits = need(a, "min_flow_throughs") * fine["shape"][0] / lbm.U_LAT
    short = fine["cells"] * transits / max(budget, 1.0)
    dx = fine["dx"] * max(1.0, short ** 0.25)
    dx = min(dx, veh.extra["resolve_dim"] / need(a, "min_cells_across"))
    shape = tuple(max(8, math.ceil(b * veh.length / dx)) for b in box)
    cells = int(np.prod(shape))
    dt = lbm.U_LAT * dx / speed
    steps_T = math.ceil(T / dt)
    min_steps = math.ceil(need(a, "min_flow_throughs") * shape[0] / lbm.U_LAT)
    steps = int(max(min(steps_T, budget / cells), min_steps))
    return dict(dx=float(dx), steps=steps, box=box, cells=cells, cell_steps=float(cells * steps), budget_ok=bool(cells * steps <= budget),
                min_flow_throughs_steps=min_steps)


# ---------------------------------------------------------------------------------------------------- the stage
def _load_res(ctx) -> dict | None:
    f = pathlib.Path(ctx.run_dir) / "stage1" / "res.pkl"
    # res.pkl is this pipeline's own private checkpoint (the same file s_windows reads, a ledger input whose sha256 `make audit` checks)
    return pickle.loads(f.read_bytes()) if f.exists() else None


def _fea(veh: W.Vehicle, r: dict, a: dict) -> dict:
    if veh.extra.get("fea") is None:
        return dict(run=False, reason=veh.extra["fea_reason"])
    try:
        h = veh.length / need(a, "fea_elements_along")
        return dict(run=True, **W.fea_window(veh, r["wall_points"], r["wall_pressure"], h=h))
    except (ValueError, RuntimeError) as e:
        return dict(run=False, reason=f"FEA failed: {str(e)[:200]}")


def stage_share_s(ctx) -> float | None:
    """The stage's wall-clock share, plan["shares"]["stage3"] * plan["budget_s"] (None when the plan has no wall-clock budget)."""
    plan = ctx.plan
    if "shares" not in plan or "budget_s" not in plan:
        return None
    return float(plan["shares"]["stage3"] * plan["budget_s"])


def why_failed(checks: list, res: dict, wlog: dict, error: str | None = None) -> list:
    """One plain sentence per reason a window is not ok: resolution below the rule, y+ outside 30-300, wall model unvalidated, no
    convergence, ... Every failing check contributes; nothing fails without a sentence."""
    if error:
        return [error]
    out = []
    cpd = res["delta_te"] / res["dx"]
    if cpd < 5.0:
        out.append(f"resolution below the rule: {cpd:.1f} cells per boundary-layer thickness at dx = {res['dx']:.3g} m (BRIEF 2.6: 5-10)")
    cut = f" (run cut: {wlog['cut_reason']})" if wlog.get("cut_reason") else ""
    for c in checks:
        if c["ok"]:
            continue
        n, v, lim = c["name"], c["value"], c["limit"]
        if n == "wall_model_receipt_error":
            out.append("wall model unvalidated: no stored passing receipt (flat plate vs ITTC-57 or channel vs Dean)" if math.isnan(v)
                       else f"wall model unvalidated: stored receipt error {v:.0%} > {lim:.0%}")
        elif n == "yplus_in_30_300_fraction":
            out.append(f"y+ at the matching point outside 30-300 at {1 - v:.0%} of the wall cells "
                       f"(need {lim:.0%} inside; estimate {res['y_plus_estimate']:.0f})")
        elif n in ("mach_max", "courant_max"):
            out.append(f"{n.split('_')[0]} number {v:.3g} above the limit {lim}: local speeds exceed the reference by too much")
        elif n == "force_running_mean_dev":
            out.append(f"no convergence: the force running mean moves {v:.1%} over the last third (limit {lim:.0%}); "
                       f"{wlog.get('run_steps', '?')} of {wlog.get('planned_steps', '?')} steps run{cut}")
        elif n == "mass_drift_per_step":
            out.append(f"mass changes {v:.2g} per step (limit {lim:g}): open-boundary imbalance")
        elif n == "interpolation_residual":
            out.append(f"coarse-to-fine residual {v:.3g} u_lat above {lim}")
        elif n == "sponge_clearance_cells":
            out.append(f"the body is {v:.0f} cells from the relaxation layer (need {lim:.0f}): box too small at this dx")
        else:
            out.append(f"check {n} failed: {v} vs {lim}")
    return out


def _row(ctx, vid: str, cls: str, w: dict, part: str, platform: str, res: dict | None, a: dict, n_parts: int, win_s: float | None,
         meter: dict) -> dict:
    t0 = time.perf_counter()
    les = ctx.plan["les"]
    base = dict(t=w["t"], lon=w["lon"], lat=w["lat"], part=part, fluid=None, resolution=None, checks=[], ok=False, reasons=[],
                cd=None, cd_spread=None, cl=None, cl_spread=None, added_resistance=None, cd_hangar=None, cl_hangar=None,
                cd_hangar_source=None, fea=dict(run=False, reason="the window did not run"), label=les["label"] if les["cpu_fallback"] else None,
                wall_share_s=win_s)

    def fail(msg: str) -> dict:
        return dict(base, error=msg[:300], reasons=[msg[:300]], wall_s=time.perf_counter() - t0)
    if win_s is not None and win_s < need(a, "min_window_s"):
        return fail(f"the stage-3 wall-clock budget is spent: {win_s:.1f} s left for this window (least that can run: {need(a, 'min_window_s')} s)")
    heading = track_heading(res, vid, w["t"])
    try:
        if cls == "glider":
            P = glider.load_platform(platform)
            dive = [v for v in ctx.mission["vehicles"] if v["id"] == vid][0].get("task", {}).get("dive_depth_m", P["mission_defaults"]["dive_depth_m"])
            veh = glider_vehicle(P, a, platform, float(dive))
            veh.extra.update(fea=True)
            case = glider_case(ctx, w, P, veh, a, heading)
        elif cls == "usv":
            P = usv.load_platform(platform)
            veh = usv_vehicle(P, a, platform, part)
            veh.extra["fea_reason"] = "no structural model: the platform yaml has no hull or wing structure (material, thickness) to build an FEA from"
            case = usv_case(ctx, w, P, veh, a, heading, part)
        else:
            P = uas.load_platform()
            veh = uas_vehicle(P, a, platform)
            veh.extra["fea_reason"] = "no structural model: airframe loads are rotor thrust, which the window (no actuator disks) does not carry"
            case = uas_case(ctx, w, P, veh, a, heading)
    except (ValueError, KeyError, RuntimeError) as e:
        return fail(str(e))
    R = case["R"]
    # Galilean: the window runs in the frame where the fluid is at rest and the body moves at the relative velocity (the vehicle
    # frame nest only sees u_env - v); windows.WindowSpec.velocity is then the relative speed the time step is scaled with.
    vb = case["v"] - case["u_env"] if R is None else R @ (case["v"] - case["u_env"])
    ub = np.zeros(3)
    speed = float(np.linalg.norm(vb))
    base.update(fluid=veh.fluid, heading_deg=case["heading"], env_enu_ms=[float(x) for x in case["u_env"]], velocity_body_ms=[float(x) for x in vb],
                cd_hangar=case["cd_h"], cl_hangar=case["cl_h"], cd_hangar_source=case["src"], kinematics=case["info"],
                heading_source="stage-1 median track" if heading is not None else "relative-flow direction (no stage-1 track)")
    plan_cs = les["cell_steps_per_window"] / n_parts
    fea_s = need(a, "fea_reserve_frac") * win_s if (win_s is not None and veh.extra.get("fea")) else 0.0
    run_s = None if win_s is None else win_s - fea_s
    time_cs = None if run_s is None else meter["rate"] * max(run_s - meter["compile_s"], 0.0)
    budget_cs = plan_cs if time_cs is None else min(plan_cs, time_cs)
    try:
        fit = fit_window(veh, speed, budget_cs, a)
        chunk = int(need(a, "chunk_steps"))
        steps = -(-fit["steps"] // chunk) * chunk                           # whole chunks: another chunk length is another XLA compile
        spec = W.WindowSpec(velocity=tuple(float(x) for x in vb), dx=fit["dx"], steps=steps, box=fit["box"], cd_ref=case["cd_h"],
                            spinup=need(a, "spinup"), chunk=chunk, wall_s=run_s)
        inflow = lambda x, y, z, t, _u=ub: jnp.stack([jnp.full_like(x, _u[0]), jnp.full_like(x, _u[1]), jnp.full_like(x, _u[2])])    # noqa: E731
        r = W.run_window(veh, spec, inflow)
    except (ValueError, RuntimeError) as e:                                 # memory guard, empty body, no flow ...
        return dict(base, error=str(e)[:300], reasons=[str(e)[:300]], wall_s=time.perf_counter() - t0)
    wl = r["wall"]
    if wl.get("cells_per_s"):                                               # later windows plan with what this box really delivers now
        meter["rate"] = wl["cells_per_s"]
        meter["compile_s"] = wl["compile_s"] if meter["n"] == 0 else 0.5 * (meter["compile_s"] + wl["compile_s"])
        meter["n"] += 1
    cuts = [wl["cut_reason"]] if wl.get("cut_reason") else []
    if time_cs is not None and run_s is not None and time_cs < plan_cs:
        cuts.insert(0, f"coarsened: {time_cs:.3g} cell-steps afforded by {run_s:.0f} s at {meter['rate']:.3g} cells/s, plan {plan_cs:.3g}")
    left = None if win_s is None else win_s - (time.perf_counter() - t0)
    if veh.extra.get("fea") and left is not None and left < need(a, "fea_min_s"):
        fea = dict(run=False, reason=f"skipped: {max(left, 0):.1f} s of the stage-3 wall-clock budget left for this window "
                                     f"(FEA needs {need(a, 'fea_min_s')} s)")
    else:
        fea = _fea(veh, r, a)
    resolution = dict(r["resolution"], cells=fit["cells"], cell_steps=fit["cell_steps"], budget_ok=fit["budget_ok"],
                      planned_steps=wl["planned_steps"], run_steps=wl["run_steps"], cut_reason="; ".join(cuts) or None,
                      cells_per_s_measured=wl["cells_per_s"], cells_per_s_planned=les.get("rate"), compile_s=wl["compile_s"],
                      cell_steps_budget_plan=plan_cs, cell_steps_budget_time=time_cs, setup_s=wl["setup_s"],
                      cells_per_delta=r["resolution"]["delta_te"] / r["resolution"]["dx"])
    ok = bool(r["ok"] and not any(not c["ok"] for c in r["checks"]))
    return dict(base, resolution=resolution, checks=r["checks"], ok=ok, reasons=[] if ok else why_failed(r["checks"], r["resolution"], wl),
                cd=float(r["cd"]), cd_spread=float(r["cd_spread"]), cl=float(r["cl"]), cl_spread=float(r["cl_spread"]),
                added_resistance=None if r["added_resistance"] is None else float(r["added_resistance"]), fea=fea,
                ref_area=float(r["ref_area"]), source=r["source"], wall_s=time.perf_counter() - t0)


PARTS = {"glider": ("body",), "usv": ("hull", "wing"), "uas": ("body",)}


def run(ctx, wins: dict, L) -> dict:
    """The stage-3 call. Returns {vid: [row, ...]}; every window of every vehicle is attempted (a window that cannot run gives a row
    with `error` and ok False). Per-window self-checks live in the rows; L gets only 'the stage did what it promises'.
    Wall clock: the stage's share (stage_share_s) is split over the windows still to run, so time a window does not use passes to
    the next; each window's LES is cut to its slice (compile included), later windows are planned with the rate measured so far,
    and the FEA runs only if the slice has time left. A window whose slice is below `stage3.min_window_s` is reported as not run."""
    a = assumptions()
    res = _load_res(ctx)
    for f in (pathlib.Path(ctx.run_dir) / "stage1" / "res.pkl", config.CONFIG / "assumptions.yaml"):      # what the rows depend on, for the ledger
        if f.exists():
            L.input(f)
    plat = {v["id"]: v["platform"] for v in ctx.mission["vehicles"]}
    share = stage_share_s(ctx)
    t_stage = time.perf_counter()
    todo = [(vid, w, part) for vid, ws in wins.items() for w in ws for part in PARTS[ctx.classes[vid]]]
    meter = dict(rate=float(ctx.plan["les"].get("rate") or 1e6), compile_s=float(a.get("compile_s_guess", 0.0)), n=0)
    rows: dict[str, list] = {vid: [] for vid in wins}
    for i, (vid, w, part) in enumerate(todo):
        win_s = None if share is None else (share - (time.perf_counter() - t_stage)) / (len(todo) - i)
        r = _row(ctx, vid, ctx.classes[vid], w, part, plat[vid], res, a, len(PARTS[ctx.classes[vid]]), win_s, meter)
        rows[vid].append(r)
        msg = f"cd={r['cd']:.3g} (hangar {r['cd_hangar']:.3g})" if r.get("cd") is not None else f"error: {r.get('error')}"
        ctx.log(f"stage3 {vid}/{part} t={w['t']:.0f}: ok={r['ok']} {msg} [{r['wall_s']:.1f} s of {win_s if win_s is None else round(win_s, 1)}]")
    want, got = len(todo), sum(len(r) for r in rows.values())
    L.check("every_window_attempted", got == want, value=got, limit=want)
    bad = [(v, i) for v, rs in rows.items() for i, r in enumerate(rs) if r["ok"] and any(not c["ok"] for c in r["checks"])]
    L.check("no_row_claims_ok_with_a_failing_check", not bad, value=len(bad), limit=0)
    unexplained = [(v, i) for v, rs in rows.items() for i, r in enumerate(rs) if not r["ok"] and not r["reasons"]]
    L.check("every_failed_window_states_a_reason", not unexplained, value=len(unexplained), limit=0)
    spent = time.perf_counter() - t_stage
    if share is not None:
        L.check("stage_held_its_wall_clock_share", spent <= 1.1 * share, value=round(spent, 1), limit=round(1.1 * share, 1),
                note="share = plan shares.stage3 x budget_s; a window cut by the budget is a coarser row, not an overrun")
    return rows
