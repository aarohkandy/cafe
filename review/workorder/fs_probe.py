"""Measurement probe for the USV free-surface hull case ('hull_fs', interFoam LTS on the CPU). Not product code.

It builds the vehicle, STL, draft and speed exactly as stage 3 does for the first USV window of a finished demo run (pipeline_windows._fs_submit:
usv_vehicle, freesurface.write_stl, usv_case, vb = R (v - u_env)), then runs ONE grid with cafe.cfd.free_surface (--boxes N refinement boxes, which is
level_offset N - 4 in freesurface.GRIDS' terms, snappy surface level 0) and writes <out>/result.json: cells, failed mesh checks, seconds (mesh, solve),
iterations run, the resistance as block means every 250 iterations over the whole history, the mean and std of the last 20 % (cfd.tail_stats, what
production reports), the drift between the last two 1,000-iteration blocks, the vertical force, Courant numbers and y+ when the logs give them, the
iteration at which the history first satisfies the DTMB study's rule (dtmb5415.settle/unsettled), and the cell-updates per second. The case directory keeps its logs and
postProcessing (cfd._shrink).
cafe/cfd.py and every other product file is untouched: the probe only patches module globals in its own process (cfd.sh, cfd.FS_BOXES for a 5th box).

  --settle   run interFoam through dtmb5415._converge (250-iteration restarts from 1,000 up to --iters until drift <= 0.5 % and scatter <= 2 %) and
             record what it reports; the grid, the boundary conditions and the fluid are production's (no case_recipe: no tank water, no y+ layer sizing).
  --no-keel  the same grid, the STL of the hull ellipsoid only (the keel is the question); the cd of that run is not comparable with cd_hangar.
  --compare A B   no solver: two result.json (A fine, B coarse) -> the refinement ratio, the GCI and the three checks as freesurface.row_fields computes them.

Run on orca (PM_CPUS equal to --cores):
  PM_TAKE=1 PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=6 PM_MEM=24g TM=fs_<name> \
    bin/pmx.sh python review/workorder/fs_probe.py --boxes 4 --iters 8000 --cores 6 --out /data/runs/fs_probe_f4
The run dir (default /data/runs/on1) is only read.
"""
import argparse
import dataclasses
import gc
import json
import math
import os
import pathlib
import re
import sys
import time
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CAFE_OFFLINE", "1")                       # the environment is read from the cache; nothing is fetched
RUNS = pathlib.Path("/data/runs")
BLOCK = 250
# a 5th nested box (x0, x1, |y|, z0, z1 in hull lengths): this probe's own, inside box 4 of cfd.FS_BOXES
EXTRA_BOX = (-0.62, 0.56, 0.13, -0.22, 0.09)


def check_out(out: pathlib.Path) -> None:
    """SystemExit unless `out` is /data/runs/fs_probe*: the case directory is deleted with rmtree and the run dir /data/runs/on1 must never be reachable."""
    if out.parent != RUNS or not out.name.startswith("fs_probe"):
        sys.exit(f"--out {out}: the case is deleted with rmtree, so the directory must be {RUNS}/fs_probe* (never /tmp, never a run)")


def block_means(series: Any, size: int = BLOCK) -> list[float]:
    """Means of consecutive blocks of `size` values (a last short block is dropped when it is under half a block)."""
    import numpy as np
    s = np.asarray(series, float)
    out = [float(s[i:i + size].mean()) for i in range(0, len(s), size) if len(s[i:i + size]) >= size // 2]
    return out


def last_blocks(series: Any, size: int = 1000) -> dict[str, float | None]:
    """The mean of the last `size` values, of the `size` before it, and the drift |a - b| / |a| of the two; None when there are fewer than 2 x size values."""
    import numpy as np
    s = np.asarray(series, float)
    if len(s) < 2 * size:
        return dict(last=None, previous=None, drift=None)
    a, b = float(s[-size:].mean()), float(s[-2 * size:-size].mean())
    return dict(last=a, previous=b, drift=abs(a - b) / abs(a))


def settled_at(total: Any, pressure: Any, viscous: Any, step: int = BLOCK, first: int = 1000) -> int | None:
    """The first iteration count n (a multiple of `step`, at least `first`) at which the history up to n satisfies the DTMB study's rule (dtmb5415.unsettled on
    the last-quarter drift, scatter and the pressure/viscous drift of `_converge`), None when it never does. The three series are the resistance and its
    two parts in the same sign and unit."""
    import numpy as np
    from cafe.pm import dtmb5415 as D
    t, p, v = (np.asarray(x, float) for x in (total, pressure, viscous))
    for n in range(max(first, step), len(t) + 1, step):
        _, _, drift, scatter = D.settle(t[:n])
        parts = max(D.part_drift(p[:n], float(t[:n][-(n // 4):].mean())), D.part_drift(v[:n], float(t[:n][-(n // 4):].mean())))
        if not D.unsettled(n, drift, parts, scatter):
            return n
    return None


def courant(log_text: str) -> dict[str, dict[str, float]]:
    """Courant numbers in an interFoam log: {name: {mean_max, max_max, last_max}} for each 'X Courant Number mean: a max: b' line, and 'flow time scale' min/max
    (LTS) as {min_min, max_max}. {} when the log has none."""
    out: dict[str, dict[str, float]] = {}
    for m in re.finditer(r"^(.*?Courant Number) mean: (\S+) max: (\S+)", log_text, flags=re.M):
        d = out.setdefault(m.group(1).strip(), dict(mean_max=-math.inf, max_max=-math.inf, last_max=math.nan))
        d["mean_max"], d["max_max"], d["last_max"] = max(d["mean_max"], float(m.group(2))), max(d["max_max"], float(m.group(3))), float(m.group(3))
    ts = [(float(a), float(b)) for a, b in re.findall(r"Flow time scale min/max = (\S+), (\S+)", log_text)]
    if ts:
        out["flow time scale [s]"] = dict(min_min=min(a for a, _ in ts), max_max=max(b for _, b in ts), last_min=ts[-1][0], last_max=ts[-1][1])
    return out


def history(case: pathlib.Path) -> dict[str, Any]:
    """The whole force history of a case, one row per iteration (rows of a restarted run's repeated iteration kept once, the last): iteration, the resistance
    (-Fx x 2: the half domain) and its pressure and viscous parts, the vertical force (Fz x 2), all in N."""
    import numpy as np
    from cafe import cfd
    f = cfd.read_forces(case)["force"]
    it, keep = np.unique(f["it"][::-1], return_index=True)
    idx = (len(f["it"]) - 1 - keep)
    k2 = 2.0
    return dict(it=it, total=-k2 * f["total"][idx, 0], pressure=-k2 * f["pressure"][idx, 0], viscous=-k2 * f["viscous"][idx, 0], fz=k2 * f["total"][idx, 2])


def summarize(h: dict[str, Any]) -> dict[str, Any]:
    """The numbers of result.json that come from the history alone (production's last-20 % mean and std, block means, the 1,000-iteration drift, settling)."""
    import numpy as np
    from cafe import cfd
    R = h["total"]
    mean, std = cfd.tail_stats(R)
    n = max(int(len(R) * 0.2), 20)
    return dict(iterations=int(h["it"][-1]), history_rows=int(len(R)), resistance_tail20_mean_n=float(mean), resistance_tail20_std_n=float(std),
                scatter_tail20=float(std / mean), tail20_rows=int(n), block_size=BLOCK, block_means_n=block_means(R), last_two_1000_blocks=last_blocks(R, 1000),
                settled_at_iteration=settled_at(R, h["pressure"], h["viscous"]), vertical_force_tail20_mean_n=float(h["fz"][-n:].mean()),
                vertical_force_block_means_n=block_means(h["fz"]), viscous_tail20_mean_n=float(h["viscous"][-n:].mean()),
                pressure_tail20_mean_n=float(h["pressure"][-n:].mean()), resistance_min_n=float(np.min(R)), resistance_max_n=float(np.max(R)))


def pair(fine: dict[str, Any], coarse: dict[str, Any]) -> dict[str, Any]:
    """The refinement ratio, the GCI and the checks of the pair as stage 3 computes them: freesurface.two_grid (vv.refinement_ratio of the cell counts,
    cfd.gci of the two last-20 % resistances at that ratio) and freesurface.row_fields (cd on the Hangar reference area and density; fs_gci,
    fs_refinement_ratio, fs_iterative_scatter on the fine grid's std / R). `fine` and `coarse` are result.json contents."""
    from cafe import cfd
    from cafe.pm import vv
    from cafe.pm.stage3 import freesurface as FS
    rr = vv.refinement_ratio(fine["grid"]["cells"], coarse["grid"]["cells"])
    Rf, Rc = fine["grid"]["resistance_n"], coarse["grid"]["resistance_n"]
    g = cfd.gci(Rf, Rc, ratio=rr)
    speed = fine["info"]["speed_ms"]
    r = dict(cells=fine["grid"]["cells"], coarse_cells=coarse["grid"]["cells"], refinement_ratio=rr, source="fs_probe",
             speeds={speed: dict(resistance=Rf, std=fine["grid"]["resistance_std_n"], lift=fine["grid"]["vertical_force_n"], gci=g)})
    f = FS.row_fields(r, speed, fine["info"]["rho_hangar"], fine["info"]["ref_area_m2"], fine["info"]["cd_hangar"])
    return dict(refinement_ratio=rr, gci=g, resistance_fine_n=Rf, resistance_coarse_n=Rc, relative_difference=abs(Rc - Rf) / Rf, cd=f["cd"],
                cd_hangar=fine["info"]["cd_hangar"], cd_over_cd_hangar=f["cd"] / fine["info"]["cd_hangar"], added_resistance=f["added_resistance"],
                checks=[dict(name=c["name"], value=c["value"], limit=c["limit"], ok=c["ok"]) for c in f["checks"]], all_ok=all(c["ok"] for c in f["checks"]))


def setup(args: argparse.Namespace, out: pathlib.Path) -> dict[str, Any]:
    """Stage 3's own build of the first USV window's hull_fs case (the run dir read only). Writes <out>/hull.stl; returns the facts (and releases
    the environment)."""
    import numpy as np
    from cafe.pm.pipeline import Context
    from cafe.pm.stage3 import freesurface as FS, pipeline_windows as PW
    ctx = Context(args.mission, None, 0, args.run)
    vid = next(v for v, c in ctx.classes.items() if c == "usv")
    platform = next(v["platform"] for v in ctx.mission["vehicles"] if v["id"] == vid)
    w = json.loads((pathlib.Path(args.run) / "windows" / "windows.json").read_text())[vid][0]
    a = PW.assumptions()
    P = PW.usv.load_platform(platform)
    veh = PW.usv_vehicle(P, a, platform, "hull_fs")
    res = PW._load_res(ctx)
    heading, hsrc = PW.track_heading(res, vid, w["t"]), PW.track_heading_source(res, vid, w["t"])
    out.mkdir(parents=True, exist_ok=True)
    stl = out / "hull.stl"
    geo = FS.write_stl(dataclasses.replace(veh, shapes=veh.shapes[:1]) if args.no_keel else veh, stl)
    full = FS.write_stl(veh, out / "hull_with_keel.stl")                # the production STL's numbers, for the record (also when --no-keel)
    case = PW.usv_case(ctx, w, P, veh, a, heading, "hull_fs", full["wetted_hull_m2"])
    vb = case["R"] @ (case["v"] - case["u_env"])
    speed = float(np.linalg.norm(vb))
    kc = P["keel_area_m2"] / P["keel_span_m"]
    info = dict(vehicle=vid, platform=platform, window_t=w["t"], window_lon=w["lon"], window_lat=w["lat"], heading_deg=case["heading"], heading_source=hsrc,
                speed_ms=speed, velocity_body_ms=[float(x) for x in vb], stl=str(stl), no_keel=bool(args.no_keel), draft_m=geo["draft"], length_m=geo["length"],
                stl_area_m2=geo["area"], wetted_hull_m2=geo["wetted_hull_m2"], production_draft_m=full["draft"], production_stl_area_m2=full["area"],
                froude=speed / math.sqrt(9.81 * geo["length"]), reynolds=speed * geo["length"] / P["nu_water"], ref_area_m2=veh.ref_area,
                cd_hangar=case["cd_h"], cd_hangar_source=case["src"], rho_hangar=case["rho_h"], hull_radii_m=[float(x) for x in veh.shapes[0]["radii"]],
                keel_chord_m=kc, keel_thickness_m=P["keel_t_c"] * kc, keel_span_m=P["keel_span_m"], run_dir=args.run, mission=args.mission,
                iterations_cap=args.iters, boxes=args.boxes, cores=args.cores, settle=bool(args.settle))
    del ctx, res
    gc.collect()                                                        # the environment is about 9 GB: gone before the solver starts
    return info


def run_case(args: argparse.Namespace, out: pathlib.Path, info: dict[str, Any]) -> dict[str, Any]:
    """cafe.cfd.free_surface on <out>/case at level_offset boxes - 4, surf_level 0 and speed `info.speed_ms`; the solver run goes through
    dtmb5415._converge with --settle, else once, with the yPlus function objects added to controlDict either way. -> the grid's record."""
    import numpy as np
    from cafe import cfd
    from cafe.pm import dtmb5415 as D
    case = out / "case"
    seen: dict[str, Any] = {}
    real, old_boxes = cfd.sh, cfd.FS_BOXES
    if args.boxes > len(old_boxes):
        cfd.FS_BOXES = tuple(old_boxes) + (EXTRA_BOX,) * (args.boxes - len(old_boxes))        # only 5 is allowed (argparse); patched in this process only

    def sh(c: Any, cmd: str, log: str) -> None:
        if log.startswith("interFoam"):
            if args.settle:
                seen.update(D._converge(real, pathlib.Path(c), cmd, log, args.iters))
                return
            ctl = pathlib.Path(c) / "system/controlDict"
            ctl.write_text(ctl.read_text().replace("functions\n{", "functions\n{\n" + D.YPLUS_FO, 1))
        real(c, cmd, log)

    cfd.sh = sh
    t0 = time.time()
    try:
        r = cfd.free_surface(str(out / "hull.stl"), info["draft_m"], case, [info["speed_ms"]], args.boxes - 4, iters=args.iters, log=print, surf_level=0)
    finally:
        cfd.sh, cfd.FS_BOXES = real, old_boxes
    wall = time.time() - t0
    U = info["speed_ms"]
    s = r["speeds"][U]
    cells = r["mesh"]["cells"]
    h = history(case)
    sm = summarize(h)
    logs = sorted(case.glob("log.interFoam*"), key=lambda p: (len(p.name), p.name))
    cour = courant("".join(p.read_text(errors="replace") for p in logs))
    cover = None
    try:
        cover = D._layer_cover(case)
    except OSError:
        pass
    wet, rng = D._last_numbers(case, "yPlusWet/*/surfaceFieldValue.dat"), D._last_numbers(case, "yPlus/*/yPlus.dat")
    L = r["L"]
    cell = cfd.FS_H0 * L / 2 ** args.boxes
    keel_cells = info["keel_thickness_m"] / cell
    np.savetxt(out / "history.csv", np.column_stack([h["it"], h["total"], h["pressure"], h["viscous"], h["fz"]]), delimiter=",", fmt="%.8g",
               header="iteration,resistance_N,pressure_N,viscous_N,vertical_N", comments="")
    cfd._shrink(case)
    # settle_report's mean and std are the study's: of the half domain, hence the two full-hull keys
    return dict(cells=cells, failed_checks=r["mesh"]["failed_checks"], half_domain=r["half"], hull_cell_m=cell, keel_thickness_cells=keel_cells,
                seconds_total=r["seconds"], solve_seconds=s["seconds"], mesh_seconds=r["seconds"] - s["seconds"], wall_seconds=wall,
                cell_updates_per_s=cells * sm["iterations"] / s["seconds"], resistance_n=s["resistance"], resistance_std_n=s["resistance_std"],
                vertical_force_n=s["lift"], iterations_cap=args.iters, courant=cour, y_plus_wet_mean=wet[-1] if wet else None,
                y_plus_min=rng[1] if len(rng) > 3 else None, y_plus_max=rng[2] if len(rng) > 3 else None, layer_cover_pct=cover,
                settle_report=dict(seen, mean_n_full=2 * seen["mean"], std_n_full=2 * seen["std"]) if seen else None, case_dir=str(case), **sm)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--boxes", type=int, choices=range(1, 6), default=4, help="refinement boxes (production: coarse 1, fine 4); 5 is a probe-only extra box")
    ap.add_argument("--iters", type=int, default=8000, help="iterations passed to cfd.free_surface (with --settle: the cap; MAX_ITERS of the study is 8000)")
    ap.add_argument("--cores", type=int, default=6, help="MPI ranks of OpenFOAM (CAFE_NPROC); keep it equal to PM_CPUS")
    ap.add_argument("--out", default="/data/runs/fs_probe", help="work directory, must be /data/runs/fs_probe* (the case in it is deleted and rebuilt)")
    ap.add_argument("--run", default="/data/runs/on1", help="finished demo run whose first USV window is built (read only)")
    ap.add_argument("--mission", default=None, help="default: <run>/mission.yaml")
    ap.add_argument("--settle", action="store_true", help="run interFoam through dtmb5415._converge")
    ap.add_argument("--no-keel", action="store_true", help="hull ellipsoid only (the keel is the question)")
    ap.add_argument("--stop-after-stl", action="store_true", help="build the vehicle, STL and speed, write info.json, run nothing")
    ap.add_argument("--compare", nargs=2, metavar=("FINE", "COARSE"),
                    help="two result.json files: the pair's ratio, GCI and checks (no solver); written to --out/pair.json")
    args = ap.parse_args()
    out = pathlib.Path(args.out).resolve()
    check_out(out)
    if args.compare:
        a, b = (json.loads(pathlib.Path(p).read_text()) for p in args.compare)
        res = dict(fine=args.compare[0], coarse=args.compare[1], **pair(a, b))
        out.mkdir(parents=True, exist_ok=True)
        (out / "pair.json").write_text(json.dumps(res, indent=1, default=float))
        print(json.dumps(res, indent=1, default=float))
        return 0
    if args.iters < 1 or args.cores < 1:
        sys.exit("--iters and --cores must be at least 1")
    args.mission = args.mission or str(pathlib.Path(args.run) / "mission.yaml")
    os.environ["CAFE_NPROC"] = str(args.cores)                    # cafe.cfd reads it at import
    info = setup(args, out)
    (out / "info.json").write_text(json.dumps(info, indent=1, default=float))
    if args.stop_after_stl:
        print(json.dumps({k: info[k] for k in ("speed_ms", "draft_m", "length_m", "froude", "reynolds", "cd_hangar", "ref_area_m2", "keel_thickness_m")}))
        return 0
    from cafe.pm.stage3 import freesurface as FS
    result: dict[str, Any] = dict(info=info, estimate_cells=0.98 * FS.refined_cells(min(args.boxes, 4)) if args.boxes <= 4 else None)
    path = out / "result.json"
    path.write_text(json.dumps(result, indent=1, default=float))
    g = result["grid"] = run_case(args, out, info)
    q = 0.5 * info["rho_hangar"] * info["speed_ms"] ** 2 * info["ref_area_m2"]
    g["cd"], g["cd_over_cd_hangar"] = g["resistance_n"] / q, g["resistance_n"] / q / info["cd_hangar"]
    path.write_text(json.dumps(result, indent=1, default=float))
    keys = ("cells", "failed_checks", "iterations", "mesh_seconds", "solve_seconds", "cell_updates_per_s", "resistance_tail20_mean_n", "scatter_tail20",
            "settled_at_iteration", "last_two_1000_blocks")
    print(json.dumps({k: g[k] for k in keys}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
