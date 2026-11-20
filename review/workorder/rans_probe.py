"""Measurement probe for a CPU RANS case of the demo's Seaglider (work order step 3, plan step 0). Not product code, and no test.

It builds the vehicle and case exactly as stage 3 does for the first glider window of a finished demo run, writes the union STL of the
vehicle's shapes, derives the body-frame flow label and speed, then runs cafe.cfd.external twice (level_offset -1 and 0, the one label)
and reports per grid: cells, failed_checks, seconds, iterations, drag, force_std; and refinement ratio, GCI, cd on the vehicle's ref_area,
cd_hangar and cd / cd_hangar. cafe/cfd.py is not touched (its literals key the cache).

Run on orca, alone on the worker, PM_CPUS equal to --cores:
  PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=6 PM_MEM=24g TM=<name> bin/pmx.sh python review/workorder/rans_probe.py --cores 6
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stop-after-stl", action="store_true", help="steps 1 to 3 only: print the label, speed, STL triangle count and watertight flag")
    ap.add_argument("--cores", type=int, default=2, help="MPI ranks of OpenFOAM (CAFE_NPROC); keep it equal to PM_CPUS")
    ap.add_argument("--out", default="/data/runs/rans_probe", help="work directory (the case directories are deleted and rebuilt)")
    ap.add_argument("--run", default="/data/runs/q25", help="finished demo run whose windows.json, stage1/res.pkl and ingest/ the case is built from (read only)")
    ap.add_argument("--mission", default=str(ROOT / "missions" / "tepex_c_demo.yaml"))
    args = ap.parse_args()
    out = pathlib.Path(args.out).resolve()
    if not out.name.startswith("rans_probe") or str(out).startswith("/tmp"):
        sys.exit(f"--out {out}: the cases are deleted with rmtree, so the directory must be named rans_probe* and not under /tmp")
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
    speed = float(np.linalg.norm(vb))
    side = abs(float(vb[1])) / speed
    angle = math.degrees(math.atan2(float(vb[2]), float(vb[0])))
    if vb[0] <= 0 or side > 1e-6 or abs(angle) > 90:
        raise ValueError(f"the body-frame velocity {vb.tolist()} is not a forward motion in the x-z plane: the label x[+-]z<angle> cannot carry it")
    label = f"x{'+' if vb[2] >= 0 else '-'}z{abs(angle):.2f}"
    err_deg = math.degrees(math.acos(min(1.0, float(np.dot(cfd.dvec(label), vb / speed)))))       # cfd.dvec raises when it does not take the label
    L = float(m.extents.max())
    hs = min(L / 200, float(m.extents.min()) / 16)                                   # cfd.external's own sizes, for the record
    info = dict(vehicle=vid, platform=platform, window_t=w["t"], window_lon=w["lon"], window_lat=w["lat"], dive_depth_m=float(dive),
                label=label, speed_ms=speed, velocity_body_ms=[float(x) for x in vb], label_error_deg=err_deg, heading_deg=case["heading"],
                stl=str(stl), stl_triangles=int(len(m.faces)), stl_watertight=watertight, stl_extents_m=[float(x) for x in m.extents],
                stl_volume_m3=float(m.volume), stl_area_m2=float(m.area), ref_area_m2=veh.ref_area, cd_hangar=case["cd_h"], cl_hangar=case["cl_h"],
                cd_hangar_source=case["src"], rho_hangar=case["rho_h"], solver_rho=cfd.FLUIDS["water"]["rho"], cores=cfd.NPROC,
                length_m=L, surface_cell_m=hs, base_cell_m=L / 4,
                run_dir=args.run, mission=args.mission)
    (out / "info.json").write_text(json.dumps(info, indent=1, default=float))
    if args.stop_after_stl:
        print(json.dumps(dict(label=label, speed_ms=speed, stl_triangles=info["stl_triangles"], stl_watertight=watertight)))
        return 0

    # 4. two grids, one direction; a grid's case is shrunk (mesh and fields deleted, logs kept) before the next
    q = 0.5 * cfd.FLUIDS["water"]["rho"] * speed ** 2 * veh.ref_area                   # the solver's own rho, the one its force carries
    result: dict = dict(info=info, grids={})
    path = out / "result.json"
    runs = {}
    for name, off in (("coarse", -1), ("fine", 0)):
        r = cfd.external(str(stl), out / name, "water", speed, (label,), off, log=print)
        cfd._shrink(out / name)
        runs[name] = r
        d = r["dirs"][label]
        drag = float(-np.dot(d["force"], cfd.dvec(label)))
        result["grids"][name] = dict(level=r["level"], surface_cell_m=hs, cells=r["mesh"]["cells"], failed_checks=r["mesh"]["failed_checks"],
                                     seconds=r["seconds"], solve_seconds=d["seconds"], mesh_seconds=r["seconds"] - d["seconds"], iterations=d["iters"],
                                     drag_n=drag, force_n=d["force"], force_std_n=d["force_std"], scatter=float(np.linalg.norm(d["force_std"])) / drag,
                                     cd=drag / q, case_dir=str(out / name))
        path.write_text(json.dumps(result, indent=1, default=float))                # kept after each grid: a failed second grid loses nothing
    fine, coarse = result["grids"]["fine"], result["grids"]["coarse"]
    rr = vv.refinement_ratio(fine["cells"], coarse["cells"])
    g = cfd.gci(fine["drag_n"], coarse["drag_n"], ratio=rr)
    result["summary"] = dict(refinement_ratio=rr, gci=g, cd=fine["cd"], cd_on_ref_area=fine["cd"], cd_hangar=case["cd_h"], cd_over_cd_hangar=fine["cd"] / case["cd_h"],
                             total_seconds=fine["seconds"] + coarse["seconds"], note="cd uses the solver's rho (1025) and ref_area; cd_hangar uses the case's own density")
    path.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps(result, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
