"""Measurement probe for a CPU double-body RANS case of the demo USV's underwater hull (scale-ladder branch). Not product code.

Question: can a steady, fully submerged RANS case (cafe.cfd.external: snappyHexMesh and simpleFoam, k-omega SST, no free surface) give the demo USV hull's drag
on a CPU, where the free-surface case ('hull_fs', interFoam) never passes its checks? At Fr 0.074 the hull's resistance is almost all viscous and form drag.

The body. The waterline plane z = 0 is a symmetry plane of a double body, so the underwater hull (the half ellipsoid below z = 0 and the keel hanging from it,
stage 3's `usv_vehicle(.., "hull_fs")`) is half of a closed body made of that hull and its mirror image: the FULL ellipsoid of semi-axes (lwl/2, beam/2,
usv.hull_draft_m), the keel below it and the keel's mirror image above it (a plate standing on the top of the ellipsoid). The mirror keel is kept: without
it the body is not symmetric about z = 0 and its drag is not twice the underwater hull's. The keels are overlapped into the ellipsoid by the same
freesurface.KEEL_OVERLAP as the hull_fs STL, so the union is one solid. The stage-3 `hull` part's shape (full ellipsoid, ONE keel below) is not this body: it
has half the keel's drag too few. The flow is along body +x at the window's through-water speed |R (v - u_env)| (hull_fs ignores the leeway the same way).
The hull's drag is HALF the double body's: hull_fs's cd_hangar is the whole underwater hull's resistance (usv.hull_resistance + the keel, usv_case) on the
reference area `veh.ref_area` (usv_vehicle: the full ellipse pi (beam/2) draft plus the keel's frontal area), so cd = (drag / 2) / (rho speed^2 ref_area / 2).

Per grid (cfd.external at --levels A B, --iters N): cells, failed mesh checks, iterations, seconds, drag (double body and the hull's half), pressure and viscous
parts, the drag's tail mean and std, y+ on the body (postProcess yPlus on the finished fields, before the case is shrunk), the layer table of snappyHexMesh. The
summary: refinement ratio, GCI, the four checks of the glider part (stage3.rans.row_fields on the hull's drag), cd on the code's reference, cd_hangar and their
ratio, the Reynolds numbers, cf by ITTC-57, the wetted area, the friction-only estimate and the expected y+ from the first cell the mesh rule gives.

Run on orca, alone on the worker, PM_CPUS equal to --cores:
  PM_TAKE=1 PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=6 PM_MEM=24g TM=<name> bin/pmx.sh python review/workorder/usv_rans_probe.py --cores 6 \
    --levels 0 1 --iters 600 --out /data/runs/usv_rans_a
Smoke (no solver):  ... PM_CPUS=2 bin/pmx.sh python review/workorder/usv_rans_probe.py --stop-after-stl --cores 2 --out /data/runs/usv_rans_smoke
Everything is written under --out (the case directories are deleted and rebuilt); the run dir (default /data/runs/fin1) is only read.
"""
import argparse
import dataclasses
import json
import math
import os
import pathlib
import re
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CAFE_OFFLINE", "1")                       # the environment is read from the cache; nothing is fetched
RUNS = pathlib.Path("/data/runs")
BLOCK = 100


def check_out(out: pathlib.Path) -> None:
    """SystemExit unless `out` is /data/runs/usv_rans_*: the case directories are deleted with rmtree and a finished run must never be reachable."""
    if out.parent != RUNS or not out.name.startswith("usv_rans_"):
        sys.exit(f"--out {out}: the cases are deleted with rmtree, so the directory must be {RUNS}/usv_rans_* (never /tmp, never a run)")


def double_body_shapes(shapes: list[dict[str, Any]], overlap: float) -> list[dict[str, Any]]:
    """[hull, keel(s) below, mirror image(s) above]: `shapes` is the hull_fs vehicle's [hull ellipsoid, keel plate, ...]; each plate has its top pushed
    `overlap` x the hull's vertical semi-axis into the hull (freesurface.write_stl's rule), then is mirrored about z = 0 (centre z -> -z)."""
    hull, *keels = [dict(s) for s in shapes]
    r_z = hull["radii"][2]
    down = []
    for s in keels:
        sx, sy, sz = s["size"]
        cx, cy, cz = s["center"]
        down.append(dict(s, size=(sx, sy, sz + overlap * r_z), center=(cx, cy, cz + overlap * r_z / 2)))
    up = [dict(s, center=(s["center"][0], s["center"][1], -s["center"][2])) for s in down]
    return [hull, *down, *up]


def layer_recipe(snappy: str) -> dict[str, float]:
    """(nSurfaceLayers, expansionRatio, finalLayerThickness) as written in cfd.EXT_SNAPPY (relativeSizes: the thickness is a fraction of the local cell)."""
    out = {}
    for key, name in (("nSurfaceLayers", "layers"), ("expansionRatio", "expansion"), ("finalLayerThickness", "final")):
        m = re.search(rf"{key}\s+([0-9.eE+-]+)", snappy)
        if not m:
            raise ValueError(f"{key} not found in the snappyHexMesh dictionary")
        out[name] = float(m.group(1))
    return out


def expected_yplus(cell_m: float, speed: float, nu: float, cf: float, layers: float, expansion: float, final: float) -> dict[str, float]:
    """The y+ of the first cell centre if the layers are all added: the final layer is `final` x the surface cell `cell_m`, each layer below it 1 / `expansion`
    of the one above (`layers` of them), the first cell's centre is half the first layer up; u_tau = speed sqrt(cf / 2) with cf the flat-plate friction.
    y_plus_no_layers: the centre of an unlayered surface cell (half the cell)."""
    t_first = final * cell_m / expansion ** (layers - 1)
    u_tau = speed * math.sqrt(cf / 2.0)
    return dict(cell_m=cell_m, first_layer_m=t_first, first_centre_m=t_first / 2.0, u_tau_ms=u_tau, yplus_first_centre=t_first / 2.0 * u_tau / nu,
                yplus_no_layers=cell_m / 2.0 * u_tau / nu)


def parse_yplus(text: str, patch: str = "body") -> dict[str, float] | None:
    """min, max and average y+ of `patch` from an OpenFOAM yPlus log (the 'patch body y+ : min = a, max = b, average = c' and the 'body: min = ..' forms)."""
    m = re.search(rf"{patch}\b[^\n]*?min\s*=\s*([0-9.eE+-]+)\s*,\s*max\s*=\s*([0-9.eE+-]+)\s*,\s*average\s*=\s*([0-9.eE+-]+)", text)
    return None if not m else dict(min=float(m.group(1)), max=float(m.group(2)), average=float(m.group(3)))


def layer_lines(text: str, patch: str = "body") -> list[str]:
    """The lines of snappyHexMesh's layer tables that start with `patch` and carry numbers, raw (ESI v2506 prints two tables: 'faces, layers, avg thickness
    [m] near-wall, overall' and, after the layers are in, 'faces, layers target, mesh, overall thickness [m], [%]'; the header of each says the columns)."""
    return [ln.strip() for ln in text.splitlines() if re.match(rf"\s*{patch}\s+[0-9]", ln)]


def yplus_of(log_text: str) -> dict[str, Any]:
    """`parse_yplus` of a yPlus log, or {error} when OpenFOAM did not calculate it (it then prints 0, 0, 0 after a 'will not be calculated' warning)."""
    if "will not be calculated" in log_text or (y := parse_yplus(log_text)) is None:
        return dict(error="yPlus was not calculated: " + log_text[-300:])
    return y


def final_residuals(text: str) -> dict[str, float]:
    """The last initial residual of each field in a simpleFoam log."""
    out: dict[str, float] = {}
    for name, res in re.findall(r"Solving for (\w+), Initial residual = ([0-9.eE+-]+)", text):
        out[name] = float(res)
    return out


def block_means(series: Any, size: int = BLOCK) -> list[float]:
    """Means of consecutive blocks of `size` values (a last block under half a block is dropped)."""
    import numpy as np
    s = np.asarray(series, float)
    return [float(s[i:i + size].mean()) for i in range(0, len(s), size) if len(s[i:i + size]) >= size // 2]


def apparent_order(fine: tuple[float, float], mid: tuple[float, float], coarse: tuple[float, float], fs: float = 1.25) -> dict[str, float]:
    """Celik et al. (2008) three-grid procedure on (value, cells) of the fine, middle and coarse grid, r = (cells ratio)^(1/3): the apparent order p (iterated
    iteration, constant or not), the Richardson-extrapolated value, the fine-middle approximate and extrapolated relative errors and GCI = fs e_a / (r21^p - 1).
    ValueError when the three values are not monotone (the procedure has no p then)."""
    (f1, n1), (f2, n2), (f3, n3) = fine, mid, coarse
    r21, r32 = (n1 / n2) ** (1 / 3), (n2 / n3) ** (1 / 3)
    e21, e32 = f2 - f1, f3 - f2
    if e21 == 0.0 or e32 / e21 <= 0.0:
        raise ValueError(f"the values {f1}, {f2}, {f3} are not monotone: no apparent order")
    s = 1.0
    p = 2.0
    for _ in range(500):
        q = math.log((r21 ** p - s) / (r32 ** p - s))
        p_new = (math.log(abs(e32 / e21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-10:
            p = p_new
            break
        p = 0.5 * (p + p_new)
    else:
        raise ValueError("the apparent order did not converge")
    ext = (r21 ** p * f1 - f2) / (r21 ** p - 1.0)
    e_a = abs((f1 - f2) / f1)
    return dict(p=p, r21=r21, r32=r32, f_extrapolated=ext, e_approx_21=e_a, e_extrapolated_21=abs((ext - f1) / ext), gci_fine_21=fs * e_a / (r21 ** p - 1.0))


def friction_only(cf: float, s_wet: float, ref_area: float) -> float:
    """cf S_wet / A_ref: the drag coefficient of a flat plate of the wetted area at the friction line `cf`, on the reference area."""
    return cf * s_wet / ref_area


def half_result(fine: dict[str, Any], coarse: dict[str, Any], rho: float, speed: float) -> dict[str, Any]:
    """The `two_grid` dict stage3.rans.row_fields reads, for the HULL's drag (half the double body's, std halved too) on the two grid entries of result.json."""
    return dict(rho=rho, speed=speed, cells=fine["cells"], coarse_cells=coarse["cells"], failed_checks=fine["failed_checks"],
                coarse_failed_checks=coarse["failed_checks"], drag=fine["drag_n"] / 2.0, drag_coarse=coarse["drag_n"] / 2.0,
                drag_std=None if fine.get("drag_tail_std_n") is None else fine["drag_tail_std_n"] / 2.0, gci=fine["gci"],
                iterations=fine["iterations"], seconds=fine["seconds"] + coarse["seconds"])


def build(args: argparse.Namespace, out: pathlib.Path) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Stage 3's own build of the first USV window (run dir read only) and the double-body STL <out>/usv_double.stl. -> (info, veh, case)."""
    import numpy as np
    import trimesh
    from cafe import cfd
    from cafe.pm.pipeline import Context
    from cafe.pm.stage3 import freesurface as FS, pipeline_windows as PW, windows as W
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
    geo = FS.write_stl(veh, out / "hull_fs_reference.stl")                         # the production hull_fs STL: its wetted hull area is the Hangar reference's
    case = PW.usv_case(ctx, w, P, veh, a, heading, "hull_fs", geo["wetted_hull_m2"])
    vb = case["R"] @ (case["v"] - case["u_env"])
    speed = float(np.linalg.norm(vb))

    dveh = dataclasses.replace(veh, shapes=veh.shapes[:1] if args.no_keel else double_body_shapes(veh.shapes, FS.KEEL_OVERLAP))
    parts = [W.vehicle_mesh(dveh, i) for i in range(len(dveh.shapes))]
    m = parts[0] if len(parts) == 1 else trimesh.boolean.union(parts, engine="manifold")     # --no-keel: the full ellipsoid alone
    watertight = bool(m.is_watertight)
    if not watertight:
        raise ValueError("the ellipsoid and the two keels do not union into a closed solid")
    stl = out / "usv_double.stl"
    m.export(stl)
    below = float(m.area_faces[m.triangles_center[:, 2] < 0].sum())
    above = float(m.area_faces[m.triangles_center[:, 2] > 0].sum())
    L = float(m.extents.max())                                                         # cfd.external's L: the longest extent (x, the hull)
    lay = layer_recipe(cfd.EXT_SNAPPY)
    nu_s, rho_s = cfd.FLUIDS["water"]["nu"], cfd.FLUIDS["water"]["rho"]
    h0 = L / 4
    hs = min(L / 200, m.extents.min() / 16)                                            # cfd.external's surface cell
    lvl0 = int(math.ceil(math.log2(h0 / hs)))
    info = dict(vehicle=vid, platform=platform, window_t=w["t"], window_lon=w["lon"], window_lat=w["lat"], heading_deg=case["heading"], heading_source=hsrc,
                speed_ms=speed, velocity_body_ms=[float(x) for x in vb], leeway_deg=case["info"]["leeway_deg"], heel_deg=case["info"]["heel_deg"],
                flow_label="+x", stl=str(stl), stl_triangles=int(len(m.faces)), stl_watertight=watertight, stl_extents_m=[float(x) for x in m.extents],
                stl_volume_m3=float(m.volume), stl_area_m2=float(m.area), s_wet_below_m2=below, s_wet_above_m2=above,
                s_wet_hull_body_m2=geo["wetted_hull_m2"], hull_radii_m=[float(x) for x in veh.shapes[0]["radii"]],
                keel_size_m=[float(x) for x in veh.shapes[1]["size"]], keel_overlap=FS.KEEL_OVERLAP, ref_area_m2=veh.ref_area,
                cd_hangar=case["cd_h"], cd_hangar_source=case["src"], rho_hangar=case["rho_h"], nu_hangar=P["nu_water"], solver_rho=rho_s, nu_solver_m2s=nu_s,
                re_solver=speed * L / nu_s, re_hangar=speed * L / P["nu_water"], froude=speed / math.sqrt(9.81 * L), length_m=L, base_cell_m=h0,
                surface_cell_m=hs,
                level_offset0_level=lvl0, layers=lay, levels=args.levels, iterations_cap=args.iters, cores=args.cores, run_dir=args.run, mission=args.mission,
                keel=not args.no_keel, keel_drag_hangar_n=PW._keel_drag(P, case["info"]["stw_ms"]), wetted_area_note=case["wetted_area_note"], hull_fs_stl_area_m2=geo["area"], hull_fs_draft_m=geo["draft"])
    return info, veh, case


def run_grid(name: str, off: int, stl: pathlib.Path, out: pathlib.Path, info: dict[str, Any], q: float) -> dict[str, Any]:
    """cfd.external on one grid (one direction, +x), then y+ and the logs' tables, then the case is shrunk. -> the grid's record."""
    from cafe import cfd
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import rans_probe as RP
    case_dir = out / name
    r = cfd.external(str(stl), case_dir, "water", info["speed_ms"], ("+x",), off, iters=info["iterations_cap"], log=print)
    yplus: dict[str, Any] | None
    try:
        cfd.sh(case_dir, cfd.par("simpleFoam -postProcess -func yPlus -latestTime"), "yPlus")     # the fields are still in processor*/ (_shrink deletes them)
        yplus = yplus_of((case_dir / "log.yPlus").read_text(errors="replace"))
    except (RuntimeError, OSError) as e:
        yplus = dict(error=str(e)[-400:])
    g = RP.grid_entry(name, r, "+x", q, info["length_m"], case_dir)
    f = cfd.read_forces(case_dir)["force"]
    drag = -f["total"][:, 0]
    cd_double = g.pop("cd")
    snappy = (case_dir / "log.snappyHexMesh").read_text(errors="replace")
    solver = (case_dir / "log.simpleFoam.+x").read_text(errors="replace")
    cf = 0.075 / (math.log10(info["re_solver"]) - 2) ** 2
    cfd._shrink(case_dir)
    lay = info["layers"]
    g.update(level_offset=off, iterations_cap=info["iterations_cap"], cd_double_body_on_ref_area=cd_double, cd=cd_double / 2.0,
             hull_drag_n=g["drag_n"] / 2.0, hull_pressure_n=g["drag_pressure_tail_mean_n"] / 2.0, hull_viscous_n=g["drag_viscous_tail_mean_n"] / 2.0,
             drag_block_means_n=block_means(drag, BLOCK), yplus_body=yplus, layer_table_lines=layer_lines(snappy),
             residuals_final=final_residuals(solver), solution_converged="solution converged" in solver.lower(),
             yplus_expected=expected_yplus(g["surface_cell_m"], info["speed_ms"], info["nu_solver_m2s"], cf, lay["layers"], lay["expansion"], lay["final"]))
    return g


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stop-after-stl", action="store_true", help="build the vehicle and the double-body STL only: print speed, Re, areas, watertight flag")
    ap.add_argument("--cores", type=int, default=2, help="MPI ranks of OpenFOAM (CAFE_NPROC); keep it equal to PM_CPUS")
    ap.add_argument("--levels", type=int, nargs=2, default=[0, 1], metavar=("A", "B"), help="the two level_offsets of cfd.external, A < B (coarse, fine)")
    ap.add_argument("--iters", type=int, default=600, help="the iteration cap passed to cfd.external")
    ap.add_argument("--no-keel", action="store_true", help="the full ellipsoid alone (half its drag is the bare hull's); compare with hangar_hull_only_n")
    ap.add_argument("--out", default="/data/runs/usv_rans_probe", help="work directory under /data/runs/usv_rans_*")
    ap.add_argument("--run", default="/data/runs/fin1", help="finished demo run: windows.json, stage1/res.pkl and ingest/ the case is built from (read only)")
    ap.add_argument("--mission", default=str(ROOT / "missions" / "tepex_c_demo.yaml"))
    ap.add_argument("--three", type=float, nargs=6, metavar=("DRAG_F", "CELLS_F", "DRAG_M", "CELLS_M", "DRAG_C", "CELLS_C"),
                    help="no solver: the three-grid apparent order and GCI (Celik 2008) of three finished grids' drags and cell counts, fine, middle, coarse")
    args = ap.parse_args()
    if args.three:
        a = args.three
        print(json.dumps(apparent_order((a[0], a[1]), (a[2], a[3]), (a[4], a[5])), indent=1))
        return 0
    out = pathlib.Path(args.out).resolve()
    check_out(out)
    if args.levels[0] >= args.levels[1] or args.iters < 1:
        sys.exit(f"--levels {args.levels}: the first must be below the second; --iters {args.iters} must be at least 1")
    os.environ["CAFE_NPROC"] = str(args.cores)                    # cafe.cfd reads it at import
    from cafe import cfd
    from cafe.pm import vv
    from cafe.pm.stage3 import rans
    info, veh, case = build(args, out)
    (out / "info.json").write_text(json.dumps(info, indent=1, default=float))
    if args.stop_after_stl:
        print(json.dumps({k: info[k] for k in ("speed_ms", "leeway_deg", "re_solver", "re_hangar", "froude", "stl_triangles", "stl_watertight", "stl_extents_m",
                                               "stl_area_m2", "s_wet_below_m2", "s_wet_above_m2", "s_wet_hull_body_m2", "ref_area_m2", "cd_hangar",
                                               "surface_cell_m", "level_offset0_level", "layers")}, indent=1, default=float))
        return 0
    q = 0.5 * cfd.FLUIDS["water"]["rho"] * info["speed_ms"] ** 2 * veh.ref_area           # the solver's own rho, the one its force carries
    result: dict[str, Any] = dict(info=info, grids={})
    path = out / "result.json"
    for name, off in zip(("coarse", "fine"), args.levels, strict=True):
        result["grids"][name] = run_grid(name, off, pathlib.Path(info["stl"]), out, info, q)
        path.write_text(json.dumps(result, indent=1, default=float))                # kept after each grid: a failed second grid loses nothing
    fine, coarse = result["grids"]["fine"], result["grids"]["coarse"]
    rr = vv.refinement_ratio(fine["cells"], coarse["cells"])
    fine["gci"] = cfd.gci(fine["drag_n"], coarse["drag_n"], ratio=rr)
    rows = rans.row_fields(half_result(fine, coarse, cfd.FLUIDS["water"]["rho"], info["speed_ms"]), veh.ref_area, case["cd_h"])
    cf_s = 0.075 / (math.log10(info["re_solver"]) - 2) ** 2
    cf_h = 0.075 / (math.log10(info["re_hangar"]) - 2) ** 2
    s_wet = info["s_wet_below_m2"]
    q_h = 0.5 * info["rho_hangar"] * info["speed_ms"] ** 2 * veh.ref_area
    result["summary"] = dict(
        refinement_ratio=rr, gci=fine["gci"], cd=rows["cd"], cd_double_body_on_ref_area=fine["cd_double_body_on_ref_area"], cd_hangar=case["cd_h"],
        cd_over_cd_hangar=rows["cd"] / case["cd_h"], hull_drag_n=fine["hull_drag_n"], hangar_drag_n=case["cd_h"] * q_h,
        checks=[dict(name=c["name"], value=c["value"], limit=c["limit"], ok=c["ok"]) for c in rows["checks"]], all_ok=all(c["ok"] for c in rows["checks"]),
        cd_spread=rows["cd_spread"], total_seconds=fine["seconds"] + coarse["seconds"], re_solver=info["re_solver"], re_hangar=info["re_hangar"],
        cf_ittc57_re_solver=cf_s, cf_ittc57_re_hangar=cf_h, s_wet_below_m2=s_wet, s_wet_hull_body_m2=info["s_wet_hull_body_m2"],
        cd_friction_only_re_solver=friction_only(cf_s, s_wet, veh.ref_area), cd_friction_only_re_hangar=friction_only(cf_h, s_wet, veh.ref_area),
        form_factor_ittc57_re_solver=rows["cd"] * veh.ref_area / (s_wet * cf_s),
        keel=info["keel"], hangar_hull_only_n=case["cd_h"] * q_h - info["keel_drag_hangar_n"],
        hull_over_hangar_hull_only=None if info["keel"] else fine["hull_drag_n"] / (case["cd_h"] * q_h - info["keel_drag_hangar_n"]),
        note="cd = (double-body drag / 2) / (0.5 rho_solver speed^2 ref_area); cd_hangar uses the case's own density; rho ratio solver/hangar "
             f"{cfd.FLUIDS['water']['rho'] / info['rho_hangar']:.4f}")
    path.write_text(json.dumps(result, indent=1, default=float))
    print(json.dumps(result["summary"], indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
