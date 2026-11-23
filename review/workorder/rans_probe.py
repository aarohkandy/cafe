"""Measurement probe for a CPU RANS case of the demo's Seaglider (work order step 3, plan step 0). Not product code, and no test.

It builds the vehicle and case exactly as stage 3 does for the first glider window of a finished demo run, writes the union STL of the
vehicle's shapes, derives the body-frame flow label and speed, then runs cafe.cfd.external twice (--levels, default level_offset -1 and 0;
--iters the cap; the one label) and reports per grid: cells, failed_checks, seconds, iterations, drag, force_std; and refinement ratio, GCI,
cd on the vehicle's ref_area, cd_hangar and cd / cd_hangar. cafe/cfd.py is not touched (its literals key the cache).

Run on orca, alone on the worker, PM_CPUS equal to --cores:
  PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=6 PM_MEM=24g TM=<name> bin/pmx.sh python review/workorder/rans_probe.py --cores 6
  (optional: --levels 0 1 --iters 800 --out /data/runs/rans_probe2)
Scale ladder: --speed-factor F runs the same shape, label and grids at F times the window's speed (Reynolds number F x 2.04e5 on L); --out may then be
/data/runs/rans_ladder_<name>. result.json's summary adds the STL's wetted area, cf by ITTC-57 and Blasius at the run's Reynolds number and the two
form factors on it (and on S_WET_OTHER, another solver's analytic area).
Smoke (no solver):  ... PM_CPUS=2 bin/pmx.sh python review/workorder/rans_probe.py --stop-after-stl --cores 2
Everything is written under --out (default /data/runs/rans_probe); the run dir (default /data/runs/q25) is only read.
"""
import argparse
import json
import math
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CAFE_OFFLINE", "1")                       # the environment is read from the cache; nothing is fetched


# m2, the other solver's analytic wetted area: hull ellipsoid 1.3411 (pipeline_windows.ellipsoid_area)
# plus both faces and four edges of the wing outside the hull
S_WET_OTHER = 1.6427


def form_factors(cd: float, ref_area: float, s_wet: float, re: float) -> dict:
    """Flat-plate friction at the Reynolds number re on the length, by ITTC-57 (0.075 / (log10 re - 2)^2) and by Blasius (1.328 / sqrt(re)), and the
    form factor on each: ff = cd ref_area / (s_wet cf), the drag over the drag of a flat plate of the wetted area s_wet at the same speed."""
    cf_ittc = 0.075 / (math.log10(re) - 2) ** 2
    cf_blasius = 1.328 / math.sqrt(re)
    return dict(re=re, s_wet_m2=s_wet, cf_ittc57=cf_ittc, cf_blasius=cf_blasius,
                ff_ittc57=cd * ref_area / (s_wet * cf_ittc), ff_blasius=cd * ref_area / (s_wet * cf_blasius))


def loglog_slope(re: list, ff: list) -> tuple:
    """Least-squares slope of ln ff on ln re and its standard error (n - 2 degrees of freedom)."""
    x = [math.log(v) for v in re]
    y = [math.log(v) for v in ff]
    n = len(x)
    xm, ym = sum(x) / n, sum(y) / n
    sxx = sum((a - xm) ** 2 for a in x)
    b = sum((a - xm) * (c - ym) for a, c in zip(x, y, strict=True)) / sxx
    rss = sum((c - ym - b * (a - xm)) ** 2 for a, c in zip(x, y, strict=True))
    return b, math.sqrt(rss / (n - 2) / sxx)


def drag_history(case_dir: pathlib.Path, label: str) -> dict:
    """Mean and std of the drag (the force projected on the flow direction) over the last 20 % of iterations, from the case's postProcessing forces
    (what cfd.tail_stats takes: the last 20 %, at least 20 iterations). {} when the case has no force history."""
    from cafe import cfd
    try:
        f = cfd.read_forces(case_dir)["force"]
    except RuntimeError:
        return {}
    drag = -(f["total"] @ cfd.dvec(label))
    mean, std = cfd.tail_stats(drag)
    dv = cfd.dvec(label)
    return dict(drag_tail_mean_n=float(mean), drag_tail_std_n=float(std), drag_tail_std_rel=float(std / mean),
                drag_pressure_tail_mean_n=float(cfd.tail_stats(-(f["pressure"] @ dv))[0]),
                drag_viscous_tail_mean_n=float(cfd.tail_stats(-(f["viscous"] @ dv))[0]),
                tail_iterations=int(max(int(len(drag) * 0.2), 20)), history_iterations=int(len(drag)))


def grid_entry(name: str, r: dict, label: str, q: float, L: float, case_dir: pathlib.Path) -> dict:
    """One grid's record of result.json; surface_cell_m is the cell the level gives (base cell L/4 halved `level` times), not the requested size.
    scatter is the norm of force_std over the drag (mostly the lift component); scatter_drag_bound = sum_i |d_i| force_std_i / drag, an upper bound
    of the std of the projected force over the drag; drag_tail_* are the true mean and std of the drag over the last 20 % of the force history."""
    import numpy as np
    from cafe import cfd
    d = r["dirs"][label]
    dv = cfd.dvec(label)
    drag = float(-np.dot(d["force"], dv))
    if not drag > 0:
        raise ValueError(f"grid {name}: the drag {drag} N along {label} is not positive; the case in {case_dir} is kept for its logs")
    return dict(level=r["level"], surface_cell_m=L / 4 / 2 ** r["level"], cells=r["mesh"]["cells"], failed_checks=r["mesh"]["failed_checks"],
                seconds=r["seconds"], solve_seconds=d["seconds"], mesh_seconds=r["seconds"] - d["seconds"], iterations=d["iters"],
                drag_n=drag, force_n=d["force"], force_std_n=d["force_std"], scatter=float(np.linalg.norm(d["force_std"])) / drag,
                scatter_drag_bound=float(np.dot(np.abs(dv), d["force_std"])) / drag,
                cd=drag / q, case_dir=str(case_dir), **drag_history(case_dir, label))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stop-after-stl", action="store_true", help="steps 1 to 3 only: print the label, speed, STL triangle count and watertight flag")
    ap.add_argument("--cores", type=int, default=2, help="MPI ranks of OpenFOAM (CAFE_NPROC); keep it equal to PM_CPUS")
    ap.add_argument("--levels", type=int, nargs=2, default=[-1, 0], metavar=("A", "B"),
                    help="the two level_offsets of cfd.external (0 is level 6 for the demo glider); A is the coarse grid, B the fine one, A < B")
    ap.add_argument("--iters", type=int, default=1500, help="the iteration cap passed to cfd.external (its own default is 1500)")
    ap.add_argument("--speed-factor", type=float, default=1.0, help="the flow speed is the window's speed times this (the scale ladder); all else unchanged")
    ap.add_argument("--out", default="/data/runs/rans_probe", help="work directory (the case directories are deleted and rebuilt)")
    ap.add_argument("--run", default="/data/runs/q25", help="finished demo run: windows.json, stage1/res.pkl and ingest/ the case is built from (read only)")
    ap.add_argument("--mission", default=str(ROOT / "missions" / "tepex_c_demo.yaml"))
    args = ap.parse_args()
    out = pathlib.Path(args.out).resolve()
    if args.levels[0] >= args.levels[1] or args.iters < 1:
        sys.exit(f"--levels {args.levels}: the first must be below the second; --iters {args.iters} must be at least 1")
    if not out.name.startswith(("rans_probe", "rans_ladder_")) or str(out).startswith("/tmp"):
        sys.exit(f"--out {out}: the cases are deleted with rmtree, so the directory must be named rans_probe* or rans_ladder_* and not under /tmp")
    if not 0 < args.speed_factor < 10:
        sys.exit(f"--speed-factor {args.speed_factor}: must be above 0 and below 10")
    os.environ["CAFE_NPROC"] = str(args.cores)                    # cafe.cfd reads it at import
    import numpy as np
    import trimesh
    from cafe import cfd
    from cafe.pm import vv
    from cafe.pm.physics import glider
    from cafe.pm.pipeline import Context
    from cafe.pm.stage3 import pipeline_windows as PW, windows as W

    # 1. the vehicle and the case, as _row builds them for a glider
    ctx = Context(args.mission, None, 0, args.run)
    vid = next(v for v, c in ctx.classes.items() if c == "glider")
    platform = next(v["platform"] for v in ctx.mission["vehicles"] if v["id"] == vid)
    w = json.loads((pathlib.Path(args.run) / "windows" / "windows.json").read_text())[vid][0]
    a = PW.assumptions()
    P = glider.load_platform(platform)
    dive = next(v for v in ctx.mission["vehicles"] if v["id"] == vid).get("task", {}).get("dive_depth_m", P["mission_defaults"]["dive_depth_m"])
    veh = PW.glider_vehicle(P, a, platform, float(dive))
    res = PW._load_res(ctx)
    heading = PW.track_heading(res, vid, w["t"])
    case = PW.glider_case(ctx, w, P, veh, a, heading)

    # 2. the union STL, in the body frame (no shift: the case's flow label is in these axes)
    out.mkdir(parents=True, exist_ok=True)
    stl = out / "glider.stl"
    m = trimesh.boolean.union([W.vehicle_mesh(veh, i) for i in range(len(veh.shapes))], engine="manifold")
    watertight = bool(m.is_watertight)
    if not watertight:
        raise ValueError("the hull and wings do not union into a closed solid")
    m.export(stl)

    # 3. body-frame flow: the vehicle moves at vb through still water (what _row computes), as a label cfd.dvec takes
    vb = case["R"] @ (case["v"] - case["u_env"])
    speed_window = float(np.linalg.norm(vb))
    speed = speed_window * args.speed_factor                                          # the label depends on the direction only
    side = abs(float(vb[1])) / speed_window
    angle = math.degrees(math.atan2(float(vb[2]), float(vb[0])))
    if vb[0] <= 0 or side > 1e-6 or abs(angle) > 90:
        raise ValueError(f"the body-frame velocity {vb.tolist()} is not a forward motion in the x-z plane: the label x[+-]z<angle> cannot carry it")
    label = f"x{'+' if vb[2] >= 0 else '-'}z{abs(angle):.2f}"
    err_deg = math.degrees(math.acos(min(1.0, float(np.dot(cfd.dvec(label), vb / speed_window)))))       # cfd.dvec raises when it does not take the label
    L = float(m.extents.max())
    hs = min(L / 200, float(m.extents.min()) / 16)                                   # cfd.external's own sizes, for the record
    nu = cfd.FLUIDS["water"]["nu"]                                                     # the solver's own viscosity (1.19e-6, windows.NU's value)
    info = dict(speed_factor=args.speed_factor, speed_window_ms=speed_window, nu_solver_m2s=nu, re_length=speed * L / nu,
                vehicle=vid, platform=platform, window_t=w["t"], window_lon=w["lon"], window_lat=w["lat"], dive_depth_m=float(dive),
                label=label, speed_ms=speed, velocity_body_ms=[float(x) for x in vb], label_error_deg=err_deg, heading_deg=case["heading"],
                stl=str(stl), stl_triangles=int(len(m.faces)), stl_watertight=watertight, stl_extents_m=[float(x) for x in m.extents],
                stl_volume_m3=float(m.volume), stl_area_m2=float(m.area), ref_area_m2=veh.ref_area, cd_hangar=case["cd_h"], cl_hangar=case["cl_h"],
                cd_hangar_source=case["src"], rho_hangar=case["rho_h"], solver_rho=cfd.FLUIDS["water"]["rho"], cores=cfd.NPROC,
                levels=args.levels, iterations_cap=args.iters,
                length_m=L, surface_cell_m=hs, base_cell_m=L / 4,
                run_dir=args.run, mission=args.mission)
    (out / "info.json").write_text(json.dumps(info, indent=1, default=float))
    if args.stop_after_stl:
        print(json.dumps(dict(label=label, speed_ms=speed, re_length=info["re_length"], stl_triangles=info["stl_triangles"], stl_watertight=watertight)))
        return 0

    # 4. two grids, one direction; a grid's case is shrunk (mesh and fields deleted, logs kept) before the next
    q = 0.5 * cfd.FLUIDS["water"]["rho"] * speed ** 2 * veh.ref_area                   # the solver's own rho, the one its force carries
    result: dict = dict(info=info, grids={})
    path = out / "result.json"
    runs = {}
    for name, off in zip(("coarse", "fine"), args.levels, strict=True):
        r = cfd.external(str(stl), out / name, "water", speed, (label,), off, iters=args.iters, log=print)
        cfd._shrink(out / name)
        runs[name] = r
        result["grids"][name] = grid_entry(name, r, label, q, L, out / name)
        result["grids"][name].update(level_offset=off, iterations_cap=args.iters)
        path.write_text(json.dumps(result, indent=1, default=float))                # kept after each grid: a failed second grid loses nothing
    fine, coarse = result["grids"]["fine"], result["grids"]["coarse"]
    rr = vv.refinement_ratio(fine["cells"], coarse["cells"])
    g = cfd.gci(fine["drag_n"], coarse["drag_n"], ratio=rr)
    result["summary"] = dict(refinement_ratio=rr, gci=g, cd=fine["cd"], cd_hangar=case["cd_h"], cd_over_cd_hangar=fine["cd"] / case["cd_h"],
                             total_seconds=fine["seconds"] + coarse["seconds"],
                             **form_factors(fine["cd"], veh.ref_area, info["stl_area_m2"], info["re_length"]),
                             **{f"{k}_on_s_wet_other": v for k, v in form_factors(fine["cd"], veh.ref_area, S_WET_OTHER, info["re_length"]).items()
                                if k.startswith("ff_")},
                             note="cd uses the solver's rho (1025) and ref_area; cd_hangar uses the case's own density")
    path.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps(result, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
