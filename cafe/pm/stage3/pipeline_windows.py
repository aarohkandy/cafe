"""The adapter the pipeline calls for stage 3: `run(ctx, wins, L) -> {vehicle_id: [row, ...]}`.

For every window of `windows/windows.json` (`{vid: [{t, lon, lat, stress, basis}]}`) it builds the vehicle from its platform yaml
(plus the numbers in config/assumptions.yaml under `stage3.*` for every dimension no yaml has), takes the inflow from `ctx.env` at the
window's time and place, runs one wall-modelled LES window (windows.run_window) and, for the glider hull, the FEA of the pressure
hull, and returns one row per window and part. A USV has three parts: `hull` (water, native LBM, viscous only), `wing` (air) and
`hull_fs` (the same hull and keel through a free surface, interFoam or FluidX3D in a child process, total resistance: stage3/freesurface.py);
the flows are different fluids or need different solvers, so one window cannot carry them all.

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
`cd_hangar_source`. The `hull` window has no free surface, so its hangar number leaves the residuary (wave) resistance out; the `hull_fs`
window's hangar number is the VPP's whole hull resistance (usv.hull_resistance: friction x (1 + k) + residuary) plus the keel.

Resolution. cells x steps is fitted to plan["stage3"]["cell_steps_per_part"][class] (budget.stage3_plan: the stage's share split over
its LES parts, less the compile guess and the FEA reserve, over `stage3.les_margin`, at the plan's LBM rate) with
lbm.les_resolution: dx is the 10-cells-per-boundary-layer value (BRIEF 2.6) coarsened by the fourth root of the budget shortfall
(cells ~ dx^-3, steps ~ dx^-1), but never so coarse that the smallest body dimension has fewer than `stage3.min_cells_across` cells,
and the run is never shorter than `stage3.min_flow_throughs` box transits. `budget_ok` in the row says whether the budget held. With
plan["les"]["cpu_fallback"] the row is still computed for real and carries the plan's label.

Determinism. Nothing here is sized from elapsed time: dx, steps, the FEA's go/no-go and the free-surface go/no-go are functions of the plan,
the assumptions and the window's kinematics, so two same-seed runs size every window alike. The wall clock is only a safety kill (the LES
run stops after the chunk that spends its slice, the FEA and free-surface children are killed at their deadline); a killed window is a
row that says so (ok False, a reason beginning "killed"). Everything measured (seconds, rates) is in the row's `timing`, which the pipeline
moves into the stage's ledger, so the hashed output carries no timing. A row's `ok` needs every stage-3 self-check
to pass, including the wall-model receipt row (windows.stage3_checks): the refit uses only rows with ok, so no unvalidated coefficient
reaches Stage 1b.
"""
from __future__ import annotations

import dataclasses
import json
import math
import pathlib
import pickle
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import numpy as np
import jax.numpy as jnp
from numpy.typing import NDArray

from .. import budget, config
from ..physics import glider, uas, usv
from . import fluidx3d, freesurface, lbm, windows as W

if TYPE_CHECKING:
    from ..ledger import Ledger
    from ..pipeline import Context

G = 9.81


# ---------------------------------------------------------------------------------------------------- assumptions
def assumptions(path: str | None = None) -> dict[str, Any]:
    """config/assumptions.yaml keys `stage3.*` -> {short key: value}. A missing key is an error that names it (`need`)."""
    return budget.stage3_assumptions()


def need(a: dict[str, Any], key: str) -> Any:
    if key not in a:
        raise KeyError(f"config/assumptions.yaml has no 'stage3.{key}' (value, unit, why, replace_with)")
    return a[key]


# ---------------------------------------------------------------------------------------------------- frames
def rotation(heading_to_deg: float, pitch_deg: float = 0.0) -> NDArray[np.float64]:
    """ENU -> body (x forward, y left, z up). Heading is compass degrees to which x points (horizontal part), pitch is + nose up."""
    h, p = math.radians(heading_to_deg), math.radians(pitch_deg)
    x = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])
    y = np.array([-math.cos(h), math.sin(h), 0.0])
    return np.stack([x, y, np.cross(x, y)])


def compass(e: float, n: float) -> float:
    return math.degrees(math.atan2(e, n)) % 360.0


def track_heading(res: dict[str, Any] | None, vid: str, t: float) -> float | None:
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


def _val(x: Any) -> NDArray[np.float64]:
    return np.asarray(getattr(x, "value", x), float)


# ---------------------------------------------------------------------------------------------------- geometry, per class
def glider_vehicle(P: dict[str, Any], a: dict[str, Any], platform: str, depth: float) -> W.Vehicle:
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


def usv_vehicle(P: dict[str, Any], a: dict[str, Any], platform: str, part: str) -> W.Vehicle:
    if part in ("hull", "hull_fs"):
        draft = need(a, "usv.hull_draft_m")
        kc = P["keel_area_m2"] / P["keel_span_m"]
        hull = dict(type="ellipsoid", center=(0.0, 0.0, 0.0), radii=(P["lwl_m"] / 2, P["beam_wl_m"] / 2, draft))
        keel = dict(type="plate", center=(0.0, 0.0, -(draft + P["keel_span_m"] / 2)), size=(kc, P["keel_t_c"] * kc, P["keel_span_m"]))
        frontal = math.pi * (P["beam_wl_m"] / 2) * draft + P["keel_t_c"] * kc * P["keel_span_m"]
        return W.Vehicle(platform, "water", P["lwl_m"], [hull, keel], ref_area=frontal, hull=0,
                         extra=dict(resolve_dim=min(P["beam_wl_m"], 2 * draft), part=part))
    c = P["wing_area_m2"] / P["wing_span_m"]
    wing = dict(type="plate", center=(0.0, 0.0, 0.0), size=(c, P["wing_span_m"], need(a, "usv.wing_t_c") * c))     # span along y: lift axis is body z
    return W.Vehicle(platform, "air", max(c, P["wing_span_m"]), [wing], ref_area=P["wing_area_m2"], hull=0,
                     extra=dict(resolve_dim=c, part="wing"))


def uas_vehicle(P: dict[str, Any], a: dict[str, Any], platform: str) -> W.Vehicle:
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


def glider_case(ctx: Context, w: dict[str, Any], P: dict[str, Any], veh: W.Vehicle, a: dict[str, Any], heading: float | None) -> dict[str, Any]:
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


def _keel_drag(P: dict[str, Any], stw: float) -> float:
    """The keel's friction/profile drag at zero leeway: the first term of usv._forces' dk."""
    k_area, _, _, k_tc, k_c = usv._foil(P, "keel")
    return float(0.5 * P["rho_water"] * stw ** 2 * k_area * 2 * usv.cf_ittc57(stw * k_c / P["nu_water"]) * (1 + 2 * k_tc + 60 * k_tc ** 4))


def usv_case(ctx: Context, w: dict[str, Any], P: dict[str, Any], veh: W.Vehicle, a: dict[str, Any], heading: float | None,
             part: str) -> dict[str, Any]:
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
    if part in ("hull", "hull_fs"):
        lee = float(np.asarray(tw["leeway_deg"]))
        rho_w = P["rho_water"]
        r_keel = _keel_drag(P, stw)
        u_env, v = np.array([cur[0], cur[1], 0.0]), np.array([vg[0], vg[1], 0.0])
        kin = dict(R=rotation(heading, 0.0), u_env=u_env, v=v, heading=heading, rho_h=rho_w, area=veh.ref_area, cl_h=None,
                   info=dict(stw_ms=stw, leeway_deg=lee, heel_deg=float(np.asarray(tw["heel_deg"]))))
        if part == "hull_fs":                                               # the VPP's whole hull resistance, upright (the window has no heel)
            r_hull = float(usv.hull_resistance(P, np.float64(stw), 0.0))
            return dict(kin, cd_h=_coef(r_hull + r_keel, rho_w, stw, veh.ref_area),
                        src="usv.hull_resistance (ITTC-57 friction x (1 + form_factor_k) + residuary cr0 (Fr / cr_fr_ref)^4 on the wetted area, upright) "
                            f"+ keel friction/profile drag at zero leeway; rudder and appendage terms excluded; stw {stw:.3f} m/s, leeway {lee:.1f} deg")
        # viscous part of hull_resistance (ITTC-57 friction x (1 + k) on the wetted area; no residuary term: no free surface in the window)
        # plus the keel's friction/profile drag at zero leeway (usv._forces)
        re = stw * P["lwl_m"] / P["nu_water"]
        r_hull = 0.5 * rho_w * stw ** 2 * P["wetted_area_m2"] * usv.cf_ittc57(re) * (1.0 + P["form_factor_k"])
        return dict(kin, cd_h=_coef(float(r_hull + r_keel), rho_w, stw, veh.ref_area),
                    src="usv.cf_ittc57 x (1 + form_factor_k) on the wetted area + keel friction/profile drag at zero leeway; residuary and "
                        f"appendage terms excluded (no free surface / appendages in the window); stw {stw:.3f} m/s, leeway {lee:.1f} deg")
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


def uas_case(ctx: Context, w: dict[str, Any], P: dict[str, Any], veh: W.Vehicle, a: dict[str, Any], heading: float | None) -> dict[str, Any]:
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
def fit_window(veh: W.Vehicle, speed: float, budget: float, a: dict[str, Any]) -> dict[str, Any]:
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
def _load_res(ctx: Context) -> dict[str, Any] | None:
    f = pathlib.Path(ctx.run_dir) / "stage1" / "res.pkl"
    # res.pkl is this pipeline's own private checkpoint (the same file s_windows reads, a ledger input whose sha256 `make audit` checks)
    return pickle.loads(f.read_bytes()) if f.exists() else None


_spawn = subprocess.run                                                     # a seam: tests replace it without touching subprocess.run for ccx


def _fea_child(job: str, out: str) -> int:
    """Child process of `_fea`: job = .npz with the vehicle (JSON), wall points, pressure and mesh size; writes the FEA summary as JSON."""
    z = np.load(job, allow_pickle=False)
    veh = W.Vehicle(**json.loads(str(z["vehicle"])))
    with tempfile.TemporaryDirectory() as wd:
        r = W.fea_window(veh, z["points"], z["pressure"], workdir=wd, h=float(z["h"]))
    pathlib.Path(out).write_text(json.dumps(r, default=float))
    return 0


def _fea(veh: W.Vehicle, r: dict[str, Any], a: dict[str, Any], timeout_s: float | None = None) -> dict[str, Any]:
    """The FEA of the pressure hull in a child process that is killed at `timeout_s` (a safety kill): gmsh and ccx cannot be interrupted
    from inside, and the stage's wall-clock share is not negotiable. A killed FEA is `run` False with a reason that says so."""
    if veh.extra.get("fea") is None:
        return dict(run=False, reason=veh.extra["fea_reason"])
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as wd:
        job, out = pathlib.Path(wd) / "job.npz", pathlib.Path(wd) / "out.json"
        np.savez(job, vehicle=json.dumps(dataclasses.asdict(veh), default=float), points=r["wall_points"], pressure=r["wall_pressure"],
                 h=veh.length / need(a, "fea_elements_along"))
        try:
            p = _spawn([sys.executable, "-m", __name__, "--fea", str(job), str(out)], capture_output=True, text=True, timeout=timeout_s,
                               cwd=str(pathlib.Path(__file__).resolve().parents[3]))
        except subprocess.TimeoutExpired:
            return dict(run=False, reason="killed: the FEA did not finish inside the window's remaining wall-clock slice")
        if p.returncode or not out.exists():
            return dict(run=False, reason=f"FEA failed: {(p.stderr.strip().splitlines() or ['no message'])[-1][:200]}")
        return dict(run=True, seconds=time.perf_counter() - t0, **json.loads(out.read_text()))


def _jit_cache(ctx: Context) -> None:
    """Persistent XLA compilation cache under the mission cache: a rerun (or a window of the same shape) skips the compile."""
    import jax
    cache = getattr(ctx, "cache", None)
    if cache is not None:
        jax.config.update("jax_compilation_cache_dir", str(pathlib.Path(cache) / "jax"))  # type: ignore[no-untyped-call]  # jax stub
        jax.config.update("jax_persistent_cache_min_compile_time_secs", 0.0)  # type: ignore[no-untyped-call]  # jax stub


def stage_share_s(ctx: Context) -> float | None:
    """The stage's wall-clock share, plan["shares"]["stage3"] * plan["budget_s"] (None when the plan has no wall-clock budget)."""
    plan = ctx.plan
    if "shares" not in plan or "budget_s" not in plan:
        return None
    return float(plan["shares"]["stage3"] * plan["budget_s"])


def why_failed(checks: list[dict[str, Any]], res: dict[str, Any], wlog: dict[str, Any], error: str | None = None) -> list[str]:
    """One plain sentence per reason a window is not ok: resolution below the rule, y+ outside 30-300, wall model unvalidated, no
    convergence, ... Every failing check contributes; nothing fails without a sentence."""
    if error:
        return [error]
    out: list[str] = []
    cpd = res["delta_te"] / res["dx"]
    if cpd < 5.0:
        out.append(f"resolution below the rule: {cpd:.1f} cells per boundary-layer thickness at dx = {res['dx']:.3g} m (BRIEF 2.6: 5-10)")
    cut = f" (run cut: {wlog['cut_reason']})" if wlog.get("cut_reason") else ""
    for c in checks:
        if c["ok"]:
            continue
        n, v, lim = c["name"], c["value"], c["limit"]
        if n == "wall_model_receipt_error":
            out.append("wall model unvalidated: the flat plate (vs ITTC-57) and channel (vs Dean) receipts are not both stored and passing" if math.isnan(v)
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
        elif n == "viscosity_floor":
            out.append(f"viscosity raised to the stability floor (lattice {v:.2g} instead of {lim:.2g}): Reynolds number distorted at this dx")
        elif n == "sponge_clearance_cells":
            out.append(f"the body is {v:.0f} cells from the relaxation layer (need {lim:.0f}): box too small at this dx")
        else:
            out.append(f"check {n} failed: {v} vs {lim}")
    return out


def _base(ctx: Context, w: dict[str, Any], part: str) -> dict[str, Any]:
    """The row of a window that did not run: every field the refit and the report read, empty."""
    les = ctx.plan["les"]
    return dict(t=w["t"], lon=w["lon"], lat=w["lat"], part=part, fluid=None, resolution=None, checks=[], ok=False, reasons=[],
                cd=None, cd_spread=None, cl=None, cl_spread=None, added_resistance=None, cd_hangar=None, cl_hangar=None,
                cd_hangar_source=None, fea=dict(run=False, reason="the window did not run"), label=les["label"] if les["cpu_fallback"] else None)


def _describe(base: dict[str, Any], veh: W.Vehicle, case: dict[str, Any], vb: NDArray[np.float64], heading: float | None) -> None:
    """Kinematics and hangar numbers of the case into the row."""
    base.update(fluid=veh.fluid, heading_deg=case["heading"], env_enu_ms=[float(x) for x in case["u_env"]], velocity_body_ms=[float(x) for x in vb],
                cd_hangar=case["cd_h"], cl_hangar=case["cl_h"], cd_hangar_source=case["src"], kinematics=case["info"],
                heading_source="stage-1 median track" if heading is not None else "relative-flow direction (no stage-1 track)")


def _row(ctx: Context, vid: str, cls: str, w: dict[str, Any], part: str, platform: str, res: dict[str, Any] | None, a: dict[str, Any],
         sizes: dict[str, Any], win_s: float | None) -> dict[str, Any]:
    """One LES window. `sizes` is budget.stage3_plan (what every size comes from); `win_s` is the wall-clock slice left for this window, used
    only as the safety kill of the LES run, of the FEA, and of a window whose turn comes after the share is spent."""
    t0 = time.perf_counter()
    les = ctx.plan["les"]
    base = _base(ctx, w, part)

    def fail(msg: str) -> dict[str, Any]:
        return dict(base, error=msg[:300], reasons=[msg[:300]], timing=dict(wall_s=time.perf_counter() - t0, wall_share_s=win_s))
    if not sizes["runs"]:
        return fail(f"not run: the stage-3 share of this --budget is {sizes['share_s']:.0f} s for {sizes['les_parts']} LES windows, "
                    f"{sizes['slice_s']:.1f} s each (least that can run: {sizes['min_window_s']} s): use a larger --budget")
    if win_s is not None and win_s < need(a, "min_window_s"):
        return fail(f"killed before it started: the stage-3 wall-clock share was spent ({win_s:.1f} s left for this window, least that can run: "
                    f"{need(a, 'min_window_s')} s)")
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
    _describe(base, veh, case, vb, heading)
    plan_cs = sizes["cell_steps_per_part"][cls]
    fea_s = need(a, "fea_reserve_frac") * win_s if (win_s is not None and veh.extra.get("fea")) else 0.0
    run_s = None if win_s is None else win_s - fea_s                      # the LES run's safety kill, not its size
    try:
        fit = fit_window(veh, speed, plan_cs, a)
        chunk = int(need(a, "chunk_steps"))
        steps = -(-fit["steps"] // chunk) * chunk                           # whole chunks: another chunk length is another XLA compile
        spec = W.WindowSpec(velocity=tuple(float(x) for x in vb), dx=fit["dx"], steps=steps, box=fit["box"], cd_ref=case["cd_h"],
                            spinup=need(a, "spinup"), chunk=chunk, wall_s=run_s, nu_floor=need(a, "nu_lat_floor"))
        inflow = lambda x, y, z, t, _u=ub: jnp.stack([jnp.full_like(x, _u[0]), jnp.full_like(x, _u[1]), jnp.full_like(x, _u[2])])    # noqa: E731
        r = W.run_window(veh, spec, inflow)
    except (ValueError, RuntimeError) as e:                                 # memory guard, empty body, no flow ...
        return dict(base, error=str(e)[:300], reasons=[str(e)[:300]], timing=dict(wall_s=time.perf_counter() - t0, wall_share_s=win_s))
    wl = r["wall"]
    left = None if win_s is None else win_s - (time.perf_counter() - t0)
    fea_took = 0.0
    if veh.extra.get("fea") and not sizes["fea"]["runs"]:                    # planned out: the reserve is below stage3.fea_min_s
        fea = dict(run=False, reason=f"not planned: the FEA reserve is {sizes['fea']['reserve_s']:.1f} s of a {sizes['slice_s']:.1f} s slice, below "
                                     f"stage3.fea_min_s ({need(a, 'fea_min_s')} s): use a larger --budget")
    else:
        t_fea = time.perf_counter()
        fea = _fea(veh, r, a, None if left is None else max(left, 0.0))
        fea_took = time.perf_counter() - t_fea
    timing = dict(wall_s=0.0, wall_share_s=win_s, setup_s=wl["setup_s"], compile_s=wl["compile_s"], les_s=wl["les_s"], fea_s=fea_took,
                  fea_seconds=fea.pop("seconds", None), cells_per_s_measured=wl["cells_per_s"])
    resolution = dict(r["resolution"], cells=fit["cells"], cell_steps=fit["cell_steps"], budget_ok=fit["budget_ok"],
                      planned_steps=wl["planned_steps"], run_steps=wl["run_steps"], cut_reason=wl.get("cut_reason"),
                      cells_per_s_planned=les.get("rate"), cell_steps_budget_plan=plan_cs,
                      cells_per_delta=r["resolution"]["delta_te"] / r["resolution"]["dx"])
    checks = list(r["checks"])
    if r["resolution"]["nu_floored"]:                                       # a stability floor changes the Reynolds number: a window that needed it fails
        checks.append(dict(name="viscosity_floor", value=r["resolution"]["nu_lat"], limit=r["resolution"]["nu_lat_physical"], ok=False,
                           note="lattice viscosity raised to the floor; the window is not at the physical Reynolds number"))
    killed = bool(wl.get("killed"))                                         # a run stopped by its safety kill is never ok, whatever its checks say
    checks_ok = bool(r["ok"] and not any(not c["ok"] for c in checks))
    ok = checks_ok and not killed
    reasons = [] if ok else ([wl["cut_reason"]] if killed else []) + ([] if checks_ok else why_failed(checks, r["resolution"], wl))
    timing["wall_s"] = time.perf_counter() - t0
    return dict(base, resolution=resolution, checks=checks, ok=ok, reasons=reasons,
                cd=float(r["cd"]), cd_spread=float(r["cd_spread"]), cl=float(r["cl"]), cl_spread=float(r["cl_spread"]),
                added_resistance=None if r["added_resistance"] is None else float(r["added_resistance"]), fea=fea,
                ref_area=float(r["ref_area"]), source=r["source"], timing=timing)


FS_GRACE_S = 30.0                                                           # how long past its own deadline the parent waits for a child to die
PARTS = budget.STAGE3_PARTS                                                 # the native-LBM parts, one budget slice each
FS_PARTS = budget.FS_PARTS                                                  # the free-surface part: child process, own budget


def _fs_fail(base: dict[str, Any], msg: str, t0: float, **extra: Any) -> dict[str, Any]:
    return dict(base, error=msg[:600], reasons=[msg[:600]], timing=dict(wall_s=time.perf_counter() - t0), **extra)


def _fs_gate(est: dict[str, Any], a: dict[str, Any], plan: dict[str, Any], left_s: float, queued_s: float) -> tuple[bool, str, float]:
    """(fits, reason, seconds the case holds in the queue). The estimate times `fs.margin` must fit the share left after the cases already
    queued (a plan-time rule, the same as budget.stage3_plan's `fs.fit`, not the clock): minutes needed, minutes available and the smallest
    `--budget` profile whose stage-3 share would hold it (and what is already queued) are in the sentence."""
    need_s = est["total_s"] * need(a, "fs.margin")
    if need_s <= left_s:
        return True, "", need_s
    share = plan["shares"]["stage3"]
    return False, (f"free-surface window not run: estimated {est['total_s'] / 60:.0f} min x {need(a, 'fs.margin')} margin = {need_s / 60:.0f} min "
                   f"({sum(est['cells'].values()):,.0f} cells on two grids, {est['iters']} iterations, {est['cores']} cores at {est['rate'] / 1e3:.0f}k "
                   f"cell-updates/s) against {max(left_s, 0) / 60:.1f} min left of the {plan['shares']['stage3'] * plan['budget_s'] / 60:.0f} min "
                   f"stage-3 share; it would fit "
                   f"{freesurface.fitting_budget(queued_s + need_s, share, budget.BUDGET_S)}"), need_s


def _fs_work(base: dict[str, Any], veh: W.Vehicle, case: dict[str, Any], speed: float, geo: dict[str, float], jobdir: str, cfg: dict[str, Any],
             est: dict[str, Any] | None, deadline: float | None, t0: float) -> dict[str, Any]:
    """Runs one free-surface case in a child process (own process group, killed by its own watchdog at the deadline) and builds the row.
    Never raises: a child that fails, is killed or returns nonsense gives a row with `error` and the reason."""
    try:
        job, out = pathlib.Path(jobdir) / "job.json", pathlib.Path(jobdir) / "out.json"
        left = None if deadline is None else deadline - time.perf_counter()
        if left is not None and left <= 0.0:
            return _fs_fail(base, "free-surface window killed before it started: the stage-3 wall-clock share was spent before its turn came", t0)
        job.write_text(json.dumps(dict(stl=str(pathlib.Path(jobdir) / "hull.stl"), draft=geo["draft"], speeds=[speed], config=cfg,
                                       vehicle=dataclasses.asdict(veh) if fluidx3d.available(cfg)[0] else None), default=float))
        try:
            p = _spawn([sys.executable, "-m", "cafe.pm.stage3.freesurface", str(job), str(out), str(1e9 if left is None else left)],
                       capture_output=True, text=True, timeout=None if left is None else left + FS_GRACE_S, start_new_session=True,
                       cwd=str(pathlib.Path(__file__).resolve().parents[3]))
        except subprocess.TimeoutExpired:
            return _fs_fail(base, f"free-surface run killed at its deadline after {time.perf_counter() - t0:.0f} s: it did not finish inside the share", t0)
        if p.returncode or not out.exists():
            how = "killed by its watchdog at the deadline" if p.returncode == -9 else (p.stderr.strip().splitlines() or ["no message"])[-1][:300]
            return _fs_fail(base, f"free-surface run failed ({p.returncode}): {how}", t0)
        r = json.loads(out.read_text())
        r["speeds"] = {float(k): v for k, v in r["speeds"].items()}
        f = freesurface.row_fields(r, speed, case["rho_h"], case["area"], case["cd_h"])
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        return _fs_fail(base, f"free-surface window failed: {e}", t0)
    ok = all(c["ok"] for c in f["checks"])
    ratio = f["refinement_ratio"]
    res = dict(source=r["source"], cells_fine=r["cells"], cells_coarse=r["coarse_cells"], refinement_ratio=ratio, estimate=est,
               speed_ms=speed, hull_wetted_m2_mesh=geo["wetted_hull_m2"], estimated_s=None if est is None else est["total_s"])
    return dict(base, resolution=res, checks=f["checks"], ok=ok, reasons=[] if ok else freesurface.reasons(f["checks"], ratio, (r["cells"], r["coarse_cells"])),
                cd=f["cd"], cd_spread=f["cd_spread"], cl=None, cl_spread=None, added_resistance=f["added_resistance"], gci=f["gci"],
                refinement_ratio=ratio, resistance_n=f["resistance_n"], vertical_force_n=f["vertical_force_n"], ref_area=veh.ref_area, source=r["source"],
                fea=dict(run=False, reason="no structural model: the platform yaml has no hull or wing structure (material, thickness) to build an FEA from"),
                timing=dict(wall_s=time.perf_counter() - t0))


def _fs_submit(pool: ThreadPoolExecutor, ctx: Context, vid: str, w: dict[str, Any], platform: str, res: dict[str, Any] | None, a: dict[str, Any],
               st: dict[str, Any], sizes: dict[str, Any]) -> Future[dict[str, Any]]:
    """Prepares one USV window's free-surface case (kinematics, STL, price), decides whether the share left holds it and either queues
    it behind the earlier ones on `pool` (one at a time: they share the CPUs) or returns the finished not-run row."""
    t0 = time.perf_counter()
    base = _base(ctx, w, "hull_fs")
    done: Future[dict[str, Any]] = Future()
    jobdir = tempfile.mkdtemp(prefix="fs_job_")
    cfg = {"fluidx3d": freesurface.fluidx3d_config().get("fluidx3d")}
    try:
        P = usv.load_platform(platform)
        veh = usv_vehicle(P, a, platform, "hull_fs")
        heading = track_heading(res, vid, w["t"])
        case = usv_case(ctx, w, P, veh, a, heading, "hull_fs")
        vb = case["R"] @ (case["v"] - case["u_env"])
        speed = float(np.linalg.norm(vb))
        _describe(base, veh, case, vb, heading)
        geo = freesurface.write_stl(veh, pathlib.Path(jobdir) / "hull.stl")
        base.update(wetted_area_mesh_m2=geo["wetted_hull_m2"], wetted_area_platform_m2=P["wetted_area_m2"], ref_area=veh.ref_area)
        est = None if sizes["fs"] is None else sizes["fs"]["estimate"]       # priced once, in the plan (None: the FluidX3D plugin runs it)
        left = None if st["share"] is None else st["share"] - st["queued"]
        if est is not None and left is not None:
            fits, why, held = _fs_gate(est, a, ctx.plan, left, st["queued"])
            if not fits:
                shutil.rmtree(jobdir, ignore_errors=True)
                done.set_result(_fs_fail(base, why, t0, resolution=dict(estimate=est, speed_ms=speed, left_s=left)))
                return done
            st["queued"] += held
    except (ValueError, KeyError, RuntimeError, OSError) as e:
        shutil.rmtree(jobdir, ignore_errors=True)
        done.set_result(_fs_fail(base, str(e), t0))
        return done

    def work() -> dict[str, Any]:
        try:
            return _fs_work(base, veh, case, speed, geo, jobdir, cfg, est, st["deadline"], t0)
        finally:
            shutil.rmtree(jobdir, ignore_errors=True)
    return pool.submit(work)


def run(ctx: Context, wins: dict[str, list[dict[str, Any]]], L: Ledger) -> dict[str, list[dict[str, Any]]]:
    """The stage-3 call. Returns {vid: [row, ...]}; every window of every vehicle is attempted (a window that cannot run gives a row
    with `error` and ok False). Per-window self-checks live in the rows; L gets only 'the stage did what it promises'.
    Sizes: every size comes from budget.stage3_plan(ctx.plan, ...) (the same function that fills plan.json), never from elapsed time: each
    LES window is fitted to its class's cell-steps, the FEA runs if its planned reserve reaches `stage3.fea_min_s`, and a free-surface
    case is queued if the estimate times `stage3.fs.margin` fits what is left of the share after the cases queued before it.
    Wall clock: the stage's share (stage_share_s) is split over the LBM windows still to run, so time a window does not use passes to the
    next; it is only a safety kill: the LES run stops after the chunk that spends its slice, the FEA gets what is left of the slice, a window
    whose turn comes with less than `stage3.min_window_s` left is not started; each of these is a row that says "killed".
    A USV window also gets a `hull_fs` row, run in a child process while the LBM windows run (killed at the stage deadline); the rows
    follow the LBM rows of the vehicle. A case that does not fit is a row with ok False and the minutes it needs. Every row carries
    `timing` (seconds, measured rates); pipeline.s_stage3 moves it out of the hashed output into the ledger."""
    a = assumptions()
    res = _load_res(ctx)
    for f in (pathlib.Path(ctx.run_dir) / "stage1" / "res.pkl", config.CONFIG / "assumptions.yaml"):      # what the rows depend on, for the ledger
        if f.exists():
            L.input(f)
    plat = {v["id"]: v["platform"] for v in ctx.mission["vehicles"]}
    sizes = budget.stage3_plan(ctx.plan, ctx.classes, a)
    share = stage_share_s(ctx)
    t_stage = time.perf_counter()
    todo = [(vid, w, part) for vid, ws in wins.items() for w in ws for part in PARTS[ctx.classes[vid]]]
    _jit_cache(ctx)
    rows: dict[str, list[dict[str, Any]]] = {vid: [] for vid in wins}
    st = dict(share=share, t_stage=t_stage, queued=0.0, deadline=None if share is None else t_stage + share)
    with ThreadPoolExecutor(1) as pool:                                     # one free-surface case at a time: they share the CPUs
        fs = [(vid, w, _fs_submit(pool, ctx, vid, w, plat[vid], res, a, st, sizes)) for vid, ws in wins.items() if ctx.classes[vid] in FS_PARTS for w in ws]
        for i, (vid, w, part) in enumerate(todo):
            win_s = None if share is None else (share - (time.perf_counter() - t_stage)) / (len(todo) - i)
            r = _row(ctx, vid, ctx.classes[vid], w, part, plat[vid], res, a, sizes, win_s)
            rows[vid].append(r)
            msg = f"cd={r['cd']:.3g} (hangar {r['cd_hangar']:.3g})" if r.get("cd") is not None else f"error: {r.get('error')}"
            ctx.log(f"stage3 {vid}/{part} t={w['t']:.0f}: ok={r['ok']} {msg} [{r['timing']['wall_s']:.1f} s of {win_s if win_s is None else round(win_s, 1)}]")
        for vid, w, fut in fs:
            r = fut.result()
            rows[vid].append(r)
            msg = f"cd={r['cd']:.3g} (hangar {r['cd_hangar']:.3g})" if r.get("cd") is not None else f"error: {r.get('error')}"
            ctx.log(f"stage3 {vid}/{FS_PARTS[ctx.classes[vid]]} t={w['t']:.0f}: ok={r['ok']} {msg} [{r['timing']['wall_s']:.1f} s]")
    want, got = len(todo) + len(fs), sum(len(r) for r in rows.values())
    L.check("every_window_attempted", got == want, value=got, limit=want)
    bad = [(v, i) for v, rs in rows.items() for i, r in enumerate(rs) if r["ok"] and any(not c["ok"] for c in r["checks"])]
    L.check("no_row_claims_ok_with_a_failing_check", not bad, value=len(bad), limit=0)
    unexplained = [(v, i) for v, rs in rows.items() for i, r in enumerate(rs) if not r["ok"] and not r["reasons"]]
    L.check("every_failed_window_states_a_reason", not unexplained, value=len(unexplained), limit=0)
    spent = time.perf_counter() - t_stage
    if share is not None:
        L.check("stage_held_its_wall_clock_share", spent <= 1.1 * share, value=round(spent, 1), limit=round(1.1 * share, 1),
                note="share = plan shares.stage3 x budget_s; a window cut by the budget is a killed row, not an overrun")
    return rows


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_fea_child(sys.argv[2], sys.argv[3]) if sys.argv[1:2] == ["--fea"] else 2)
