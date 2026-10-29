"""The USV hull in a free surface as a stage-3 window (BRIEF 2.6): its mesh, its price, its child process and its row.

The native LBM windows have no free surface, so they cannot see wave-making resistance. The hull and keel of the `hull` window go
here as an STL of the same shapes (windows.vehicle_mesh of each, unioned) to interFoam on the CPU (cafe.cfd, the iteration count of
the DTMB 5415 validation) or, when the lab enabled the plugin in config/premission.json, to FluidX3D (windows.free_surface_window picks).
Total resistance becomes cd on the window's reference area; the two-grid GCI is its spread. The row is `ok` only if a GCI exists and
r >= vv.R_MIN.

Grids. cafe.cfd.characterize_free_surface pairs refineMesh boxes 3 and 4 (r = 1.13-1.16 < 1.3: its GCI could never pass the ratio check)
and the DTMB pair adds snappy surface levels, but snappy cannot refine refineMesh's directional splits on this hull (hexRef8 "more than
8 points": levels 1 and 2 failed on every grid tried, homebase 2026-10-29). So both grids use surface level 0 and differ by the number
of nested refinement boxes: GRIDS = coarse 1 box, fine 4 boxes (r = 1.45); the cell at the hull is then FS_H0 / 2^4 = 1/80 of the length
(8 cm on the Explorer), not the brief's 1 cm: about 500x the cells, out of reach on 8 CPUs.

Price. Minutes to hours on a CPU, so the stage prices the case before it starts one. Cells: blockMesh + refineMesh counted from the
recipe in cafe.cfd (FS_* constants; nested horizontal-only splits, 4x per box) times a snappy factor (the cells inside the hull are
removed: 0.98 measured). Time: cells x iterations / the cell-updates per second of config/throughput.json (openfoam-pimpleFoam-les,
interpolated between the measured core counts) x a measured interFoam/pimpleFoam cost factor, plus meshing time per cell. The case
runs in a child process (own process group, killed at its deadline) so it overlaps the LBM windows.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import pathlib
import signal
import sys
import tempfile
import threading
from typing import Any, Callable

import numpy as np

from .. import config, vv
from . import windows as W

SOLVER = "openfoam-pimpleFoam-les"                                           # config/throughput.json entry the free-surface case is priced with
CONFIG_FILE = config.CONFIG / "premission.json"
SCATTER_MAX = 0.02                                                           # std / mean of the resistance over the last 20 % of iterations (DTMB 5415's limit)
GCI_MAX = 0.10                                                               # a window whose two-grid GCI is larger says nothing about the drag (DECISIONS)
KEEL_OVERLAP = 0.25                                                          # keel top reaches this fraction of the hull's vertical semi-axis into the hull


def fluidx3d_config() -> dict[str, Any]:
    """config/premission.json (the `fluidx3d` key is read from it; absent = disabled)."""
    return json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.is_file() else {}


# ---------------------------------------------------------------------------------------------------- geometry
def write_stl(veh: W.Vehicle, path: str | os.PathLike[str]) -> dict[str, float]:
    """One closed STL of the vehicle's shapes (hull + keel, the keel's top pushed into the hull so the union is one solid) in the frame
    cafe.cfd.free_surface wants: lowest point at z = 0, so the waterline (the body frame's z = 0) is at z = draft. Returns the draft,
    the length, the total surface area and the wetted area of the hull body alone (what the platform's wetted_area_m2 describes)."""
    import trimesh
    shapes = [dict(s) for s in veh.shapes]
    r_z = shapes[0]["radii"][2]
    for s in shapes[1:]:
        sx, sy, sz = s["size"]
        cx, cy, cz = s["center"]
        s["size"], s["center"] = (sx, sy, sz + KEEL_OVERLAP * r_z), (cx, cy, cz + KEEL_OVERLAP * r_z / 2)
    v = dataclasses.replace(veh, shapes=shapes)
    bodies = [W.vehicle_mesh(v, i) for i in range(len(shapes))]
    m = trimesh.boolean.union(bodies, engine="manifold")
    if not m.is_watertight:
        raise ValueError("the hull and keel do not union into a closed solid")
    draft = float(-m.bounds[0][2])
    wetted = float(bodies[0].area_faces[bodies[0].triangles_center[:, 2] < 0].sum())
    m.apply_translation([0.0, 0.0, draft])
    m.export(path)
    return dict(draft=draft, length=float(m.extents[0]), area=float(m.area), wetted_hull_m2=wetted)


# ---------------------------------------------------------------------------------------------------- price
def zlayers() -> list[tuple[float, float]]:
    """(centre, thickness) in hull lengths of the blockMesh cells in z: each block's n cells grade by expansion ratio g (last/first)."""
    from cafe import cfd
    out: list[tuple[float, float]] = []
    for b, (n, g) in enumerate(zip(cfd.FS_NZ, cfd.FS_GRADE, strict=True)):
        h = cfd.FS_Z[b + 1] - cfd.FS_Z[b]
        r = g ** (1.0 / (n - 1))
        w, z = (h / n if r == 1.0 else h * (1 - r) / (1 - r ** n)), cfd.FS_Z[b]
        for i in range(n):
            out.append((z + w * r ** i / 2, w * r ** i))
            z += w * r ** i
    return out


def refined_cells(n_boxes: int) -> float:
    """Cells of the half domain after blockMesh and `n_boxes` nested refineMesh boxes (each splits its cells in x and y: 4x). A box
    counts the layers whose centre it contains, as topoSet's boxToCell does."""
    from cafe import cfd
    x0, x1, y0, _, _ = cfd.FS_DOMAIN
    nx, ny = int((x1 - x0) / cfd.FS_H0), int(-y0 / cfd.FS_H0)
    dx, dy = (x1 - x0) / nx, -y0 / ny
    total = 0.0
    for z, _ in zlayers():
        c = float(nx * ny)
        for i, (bx0, bx1, by, bz0, bz1) in enumerate(cfd.FS_BOXES[:n_boxes]):
            if bz0 <= z <= bz1:
                c += (4 ** (i + 1) - 4 ** i) * (bx1 - bx0) * (by + 0.01) / (dx * dy)
        total += c
    return total


GRIDS = {"coarse": (-3, 0), "fine": (0, 0)}                                  # (refinement boxes dropped, snappy surface level)


def nproc() -> int:
    """MPI ranks cafe.cfd will use (its CAFE_NPROC, default 6): the child inherits the environment."""
    return int(os.environ.get("CAFE_NPROC", "6"))


def rate(cores: int) -> tuple[float, str]:
    """(cell-updates/s, where from): config/throughput.json[SOLVER], interpolated between the measured core counts (clamped outside)."""
    from cafe import planner
    b = json.loads(planner.BENCH.read_text())[SOLVER]
    xs = sorted(int(k) for k in b["cell_updates_per_s"])
    r = float(np.interp(cores, xs, [b["cell_updates_per_s"][str(k)] for k in xs]))
    return r, f"{SOLVER} measured on {b['host']} {b['measured']} at {xs} cores, interpolated to {cores}"


def estimate(cores: int, snappy_factor: float, cost_factor: float, mesh_s_per_cell: float) -> dict[str, Any]:
    """Wall-clock seconds of the two-grid case at one speed: {grid: cells}, iterations, rate, solve_s, mesh_s, total_s."""
    from cafe.pm import dtmb5415
    cells = {g: snappy_factor * refined_cells(4 + off) for g, (off, _) in GRIDS.items()}
    r, src = rate(cores)
    solve = cost_factor * sum(cells.values()) * dtmb5415.ITERS / r
    mesh = mesh_s_per_cell * sum(cells.values())
    return dict(cells=cells, iters=dtmb5415.ITERS, cores=cores, rate=r, rate_source=src, cost_factor=cost_factor, solve_s=solve, mesh_s=mesh,
                total_s=solve + mesh)


def fitting_budget(need_s: float, share: float, profiles: dict[str, int]) -> str:
    """Which `--budget` profile has a stage-3 share of at least need_s (smallest first), or the plain statement that none does."""
    for name, b in sorted(profiles.items(), key=lambda kv: kv[1]):
        if share * b >= need_s:
            return f"--budget {name} ({share * b / 60:.0f} min of stage 3)"
    return f"no --budget profile (the largest gives {share * max(profiles.values()) / 60:.0f} min of stage 3)"


# ---------------------------------------------------------------------------------------------------- the child
def two_grid(stl: str, draft: float, workdir: pathlib.Path, speeds: list[float], log: Callable[[str], None] = print) -> dict[str, Any]:
    """cafe.cfd.characterize_free_surface with this module's grids (GRIDS) and the validation's iteration count: the fine grid's result
    with the refinement ratio from the two cell counts and each speed's GCI against the coarse grid (Roache, p = 2, Fs = 3, at that r)."""
    from cafe import cfd
    from cafe.pm import dtmb5415
    solve: Callable[..., dict[str, Any]] = cfd.free_surface                      # cafe.cfd is untyped: called through a typed name, as dtmb5415 does
    gci: Callable[..., float] = cfd.gci
    out: dict[str, Any] = {}
    for name, (off, lvl) in GRIDS.items():
        out[name] = solve(stl, draft, workdir / name, speeds, off, iters=dtmb5415.ITERS, log=log, surf_level=lvl)
        cfd._shrink(workdir / name)
    fine: dict[str, Any] = out["fine"]
    rr = vv.refinement_ratio(fine["mesh"]["cells"], out["coarse"]["mesh"]["cells"])
    fine["refinement_ratio"], fine["ratio_below_1_3"] = rr, rr < vv.R_MIN
    for U, r in fine["speeds"].items():
        r["gci"] = gci(r["resistance"], out["coarse"]["speeds"][U]["resistance"], ratio=rr)
    fine["coarse_cells"] = out["coarse"]["mesh"]["cells"]
    return fine


def run_child(job: str, out: str, runner: Callable[..., dict[str, Any]] | None = None) -> int:
    """Child of the stage: job = JSON (stl, draft, speeds, config, vehicle); writes windows.free_surface_window's result as JSON. The case
    lives in a temporary directory that goes away with it."""
    j = json.loads(pathlib.Path(job).read_text())
    veh = W.Vehicle(**j["vehicle"]) if j["vehicle"] else None
    with tempfile.TemporaryDirectory(prefix="fs_") as wd:
        r = W.free_surface_window(j["stl"], j["draft"], j["speeds"], wd, runner=runner or two_grid, config=j["config"], vehicle=veh)
    pathlib.Path(out).write_text(json.dumps(r, default=float))
    return 0


def arm_watchdog(seconds: float) -> threading.Timer:
    """Kill this process's whole group (the child leads its own: OpenFOAM's mpirun and the meshers are in it) after `seconds`: nothing
    inside gmsh/snappy/interFoam can be interrupted, and subprocess.run's timeout would kill only the python process."""
    def kill() -> None:
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpgrp(), signal.SIGKILL)
        else:
            os.kill(os.getpid(), signal.SIGKILL)
    t = threading.Timer(seconds, kill)
    t.daemon = True
    t.start()
    return t


# ---------------------------------------------------------------------------------------------------- the row
def check(name: str, value: float, limit: float, ok: bool, note: str) -> dict[str, Any]:
    return W.check_row(name, value, limit, ok, note=note)


def row_fields(r: dict[str, Any], speed: float, rho: float, area: float, cd_hangar: float) -> dict[str, Any]:
    """The coefficient fields of a free-surface row from windows.free_surface_window's result `r` (speeds keyed by float): cd on `area` and
    `rho` (the reference of cd_hangar), cd_spread = the numerical uncertainty (GCI x cd, with the force's own wobble added in quadrature
    when the solver reported it), the GCI and refinement ratio, and the two checks that decide `ok`."""
    s = r["speeds"][speed]
    q = 0.5 * rho * speed * speed * area
    R = float(s["resistance"])
    if not math.isfinite(R) or R <= 0.0:
        raise ValueError(f"the free-surface run returned a non-physical resistance ({R} N)")
    cd = R / q
    gci = s.get("gci")
    gci_ok = gci is not None and math.isfinite(gci)
    informative = gci_ok and gci <= GCI_MAX
    ratio = vv.refinement_ratio(r["cells"], r["coarse_cells"]) if r.get("cells") and r.get("coarse_cells") else None
    spread = math.hypot(gci * cd if gci_ok else 0.0, (s.get("std") or 0.0) / q)
    checks = [check("fs_gci", math.nan if not gci_ok else float(gci), GCI_MAX, informative,
                    "two-grid GCI (Roache, Fs = 3) of the resistance; fails when the run has no second grid (FluidX3D), it is not finite, "
                    f"or it is above {GCI_MAX:.0%} (a multiplier that uncertain is not information)"),
              check("fs_refinement_ratio", math.nan if ratio is None else ratio, vv.R_MIN, ratio is not None and ratio >= vv.R_MIN,
                    "r = (N_fine / N_coarse)^(1/3), Celik et al. 2008: at least 1.3 or the GCI is not meaningful"),
              check("fs_iterative_scatter", math.nan if s.get("std") is None else float(s["std"]) / R, SCATTER_MAX,
                    s.get("std") is not None and float(s["std"]) / R <= SCATTER_MAX,
                    "std / mean of the resistance over the last 20 % of the pseudo-time iterations: a run still wandering has no single answer")]
    return dict(cd=cd, cd_spread=max(spread, 1e-12), gci=gci if gci_ok else None, refinement_ratio=ratio, checks=checks,
                added_resistance=cd / cd_hangar - 1.0, vertical_force_n=s.get("lift"), resistance_n=R)


def reasons(checks: list[dict[str, Any]], ratio: float | None, cells: tuple[Any, Any]) -> list[str]:
    """One sentence per failing check."""
    out = []
    for c in checks:
        if c["ok"]:
            continue
        if c["name"] == "fs_iterative_scatter":
            out.append("the solver reported no force history" if not math.isfinite(c["value"]) else
                       f"the resistance still wanders by {c['value']:.1%} over the last 20 % of iterations (limit {SCATTER_MAX:.0%}): not converged")
        elif c["name"] == "fs_gci" and math.isfinite(c["value"]):
            out.append(f"grid-convergence index {c['value']:.0%} is above {GCI_MAX:.0%}: the grids disagree too much for the drag to mean anything")
        elif c["name"] == "fs_gci":
            out.append("no grid-convergence index: the free-surface run did not produce a second grid, so its discretization error is unknown")
        else:
            out.append("refinement ratio unknown (no cell counts)" if ratio is None else
                       f"refinement ratio r = {ratio:.2f} (cells {cells[0]:,} / {cells[1]:,}) is below {vv.R_MIN}: the GCI is not meaningful")
    return out


def main(argv: list[str]) -> int:  # pragma: no cover
    arm_watchdog(float(argv[2]))
    return run_child(argv[0], argv[1])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
