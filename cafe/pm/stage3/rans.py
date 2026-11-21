"""A glider's hull in a CPU RANS case as a stage-3 part (`body_rans`, work order step 3): its mesh, its child process and its row.

On a CPU the glider's LES window is not run (budget.les_windows), so the vehicle's drag has no stage-3 coefficient. This part puts the window's
shapes (hull ellipsoid and wing plate, windows.vehicle_mesh of each, unioned) through the app's steady RANS (cafe.cfd.external: snappyHexMesh and
simpleFoam, k-omega SST) on two grids at the through-water speed and the body-frame flow direction of the glider's first window. The drag on the
vehicle's reference area is `cd`; its spread is the two-grid GCI and the drag's own wobble. Only the drag is read: no lift, so the row carries none.

Grids and iterations. Measured on orca 2026-11-20 for the demo Seaglider (label x-z5.29, 0.1352 m/s; review/workorder/handbacks/cfdprobe.md):
cfd.external's level offsets -1 and 0 (14 mm and 7 mm cells) gave GCI 0.243 (job rans_g1), over the limit, because the 12 mm wing plate is under one cell on
the coarse one; offsets 0 and 1 (7 mm and 3.5 mm cells) give GCI 0.085 (16 cores, rans_g3) and 0.090 (6 cores, rans_g4) at 600 iterations, refinement
ratio 1.60, 0 failed mesh checks on both grids, the drag's own scatter 0.005 to 0.008, and 867 s on 6 cores (rans_g4); at 1500 iterations the GCI is
0.0904 and the drag settled by iteration 300 to within 0.3 % (rans_g2). The residuals never reach cfd.external's residualControl on the fine grid, so
the iteration count is the stop. cd on the vehicle's reference area is 0.373 against the Hangar model's 0.301 (ratio 1.24). The GCI margin under the 10 %
limit is thin and the drag is not monotone in the cell size (levels 5, 6, 7: 0.2366, 0.2575, 0.2460 N), so the GCI is a sensitivity, not an asymptotic error.

The case runs in a child process (own process group, killed at its deadline) so a hung mesher or solver is a row that says so; cafe/cfd.py is not
edited (its literals key its cache).
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import tempfile
from typing import Any, Callable

import numpy as np
from numpy.typing import NDArray

from .. import vv
from ..jsonio import finite_real, load_json
from . import windows as W
from .freesurface import GCI_MAX, SCATTER_MAX, arm_watchdog

LEVELS = {"coarse": 0, "fine": 1}                                           # cfd.external level_offset of the two grids (level 6 and 7 for the demo glider)
ITERS = 600                                                                 # simpleFoam iterations per grid
LABEL = "RANS (OpenFOAM simpleFoam, k-omega SST), CPU, two-grid GCI"
SIDESLIP_MAX = 1e-6                                                         # |vb_y| / |vb|: glider_case's flow has none, a label has no way to carry it


def _dvec(label: str) -> NDArray[np.float64]:
    """cafe.cfd.dvec (untyped, like the rest of cafe.cfd) as a typed call: the unit vector of a flow-direction label, ValueError for one it does not take."""
    from cafe import cfd
    f: Callable[[str], Any] = cfd.dvec
    return np.asarray(f(label), float)


# ---------------------------------------------------------------------------------------------------- geometry and flow
def write_stl(veh: W.Vehicle, path: str | os.PathLike[str]) -> float:
    """One closed STL of the vehicle's shapes (hull and wing, unioned) in the body frame the flow label is in: no shift, no keel. Returns its length (m)."""
    import trimesh
    m = trimesh.boolean.union([W.vehicle_mesh(veh, i) for i in range(len(veh.shapes))], engine="manifold")
    if not m.is_watertight:
        raise ValueError("the hull and wing do not union into a closed solid")
    m.export(path)
    return float(m.extents.max())


def flow_label(vb: Any) -> tuple[str, float]:
    """(the cafe.cfd direction label, the speed in m/s) of a vehicle moving at body-frame velocity `vb` through still water: "x+z<angle>" or "x-z<angle>"
    (forward motion tilted toward +z or -z, to 0.01 deg). ValueError for a velocity that is not forward motion in the x-z plane within 90 deg: the label
    cannot carry it. cfd.dvec must take the label (checked here, before any mesh)."""
    v = np.asarray(vb, float)
    speed = float(np.linalg.norm(v))
    if not (math.isfinite(speed) and speed > 0.0) or v[0] <= 0.0 or abs(float(v[1])) / speed > SIDESLIP_MAX:
        raise ValueError(f"the body-frame velocity {v.tolist()} is not a forward motion in the x-z plane: the label x[+-]z<angle> cannot carry it")
    label = f"x{'+' if v[2] >= 0 else '-'}z{abs(math.degrees(math.atan2(float(v[2]), float(v[0])))):.2f}"
    _dvec(label)
    return label, speed


# ---------------------------------------------------------------------------------------------------- the child
def drag_history(case_dir: str | os.PathLike[str], label: str) -> tuple[float, float] | None:
    """(mean, std) in N of the drag (the force on the body projected on the flow direction `label`) over the last 20 % of the iterations, at least 20,
    from the case's postProcessing forces (cfd.tail_stats). This is the drag's own wobble: the norm of cfd.external's `force_std` is dominated by the lift
    and fails a settled case. None when the case has no readable force history. cfd._shrink keeps postProcessing, so it may be read before or after it."""
    from cafe import cfd
    read: Callable[..., dict[str, Any]] = cfd.read_forces
    tail: Callable[..., tuple[Any, Any]] = cfd.tail_stats
    try:
        f = read(case_dir)["force"]
    except (RuntimeError, ValueError):
        return None
    mean, std = tail(-(f["total"] @ _dvec(label)))
    return float(mean), float(std)


def two_grid(stl: str, label: str, speed: float, workdir: pathlib.Path, log: Callable[[str], None] = print) -> dict[str, Any]:
    """cafe.cfd.external on the two grids of LEVELS (one direction, ITERS iterations each, the coarse grid's case shrunk before the fine one starts) with the
    fine grid's drag, the drag's tail std, the refinement ratio from the two cell counts and the GCI of the drag (Roache, p = 2, Fs = 3, at that ratio)
    against the coarse grid, and both grids' failed mesh checks. Not characterize_external: it drops the coarse grid's mesh checks and fixes its iterations."""
    from cafe import cfd
    solve: Callable[..., dict[str, Any]] = cfd.external                      # cafe.cfd is untyped: called through a typed name, as freesurface does
    gci: Callable[..., float] = cfd.gci
    unit = _dvec(label)
    out: dict[str, dict[str, Any]] = {}
    for name, off in LEVELS.items():
        r = solve(stl, workdir / name, "water", speed, (label,), level_offset=off, iters=ITERS, log=log)
        r["history"] = drag_history(workdir / name, label)
        cfd._shrink(workdir / name)
        r["drag"] = float(-np.dot(r["dirs"][label]["force"], unit))
        if not r["drag"] > 0.0:
            raise ValueError(f"the {name} grid's drag along {label} is not positive ({r['drag']} N)")
        out[name] = r
    fine, coarse = out["fine"], out["coarse"]
    rr = vv.refinement_ratio(fine["mesh"]["cells"], coarse["mesh"]["cells"])
    return dict(rho=fine["rho"], speed=speed, label=label, cells=fine["mesh"]["cells"], coarse_cells=coarse["mesh"]["cells"],
                failed_checks=fine["mesh"]["failed_checks"], coarse_failed_checks=coarse["mesh"]["failed_checks"],
                drag=fine["drag"], drag_coarse=coarse["drag"], drag_std=None if fine["history"] is None else fine["history"][1],
                refinement_ratio=rr, gci=gci(fine["drag"], coarse["drag"], ratio=rr),
                iterations=fine["dirs"][label]["iters"], seconds=fine["seconds"] + coarse["seconds"], levels=dict(LEVELS), iterations_cap=ITERS)


def run_child(job: str, out: str, runner: Callable[..., dict[str, Any]] | None = None) -> int:
    """Child of the stage: job = JSON (stl, label, speed); writes `two_grid`'s result as JSON. The case lives in a temporary directory that goes away
    with it."""
    j = load_json(pathlib.Path(job).read_text())
    with tempfile.TemporaryDirectory(prefix="rans_") as wd:
        r = (runner or two_grid)(j["stl"], j["label"], j["speed"], pathlib.Path(wd))
    pathlib.Path(out).write_text(json.dumps(r, default=float))
    return 0


# ---------------------------------------------------------------------------------------------------- the row
def check(name: str, value: float, limit: float, ok: bool, note: str) -> dict[str, Any]:
    return W.check_row(name, value, limit, ok, note=note)


def row_fields(r: dict[str, Any], area: float, cd_hangar: float) -> dict[str, Any]:
    """The coefficient fields of a `body_rans` row from `two_grid`'s result `r`: cd = the fine grid's drag over q = rho speed^2 area / 2 (the solver's own
    rho, the one its force carries, on the vehicle's reference `area`), cd_spread = the GCI-based (Fs = 3) spread (GCI x cd) with the drag's own wobble
    added in quadrature, used as a standard error by the refit (conservative: the sensitivity to the grid, not a bound), and the four checks that decide
    `ok`."""
    q = 0.5 * float(r["rho"]) * float(r["speed"]) ** 2 * area
    drag = float(r["drag"])
    if not math.isfinite(drag) or drag <= 0.0:
        raise ValueError(f"the RANS run returned a non-physical drag ({drag} N)")
    cd = drag / q
    gci_ok = finite_real(r.get("gci"))                                      # a bool, a text or an integer too large for a float is no index
    gci = float(r["gci"]) if gci_ok else math.nan
    std_ok = finite_real(r.get("drag_std"))
    std = float(r["drag_std"]) if std_ok else math.nan
    scatter = std / drag if std_ok else math.nan
    ratio = vv.refinement_ratio(r["cells"], r["coarse_cells"]) if r.get("cells") and r.get("coarse_cells") else None
    failed = int(r["failed_checks"]) + int(r["coarse_failed_checks"])
    spread = math.hypot(gci * cd if gci_ok else 0.0, std / q if std_ok else 0.0)
    checks = [check("rans_gci", gci, GCI_MAX, gci_ok and gci <= GCI_MAX,
                    "two-grid GCI (Roache, Fs = 3) of the drag: the sensitivity of the drag to the grid, not a bound of the total error (the cd spread has no "
                    "term for model-form or geometry error); fails when it is not "
                    f"finite or is above {GCI_MAX:.0%} (a multiplier that uncertain is not information)"),
              check("rans_refinement_ratio", math.nan if ratio is None else ratio, vv.R_MIN, ratio is not None and ratio >= vv.R_MIN,
                    "r = (N_fine / N_coarse)^(1/3), Celik et al. 2008's effective ratio from the cell counts: at least 1.3 or the GCI is not meaningful"),
              check("rans_iterative_scatter", scatter, SCATTER_MAX, math.isfinite(scatter) and scatter <= SCATTER_MAX,
                    "std / mean of the drag (the force projected on the flow direction) over the last 20 % of the fine grid's iterations: a run still "
                    "wandering has no single answer"),
              check("rans_mesh_checks", failed, 0.0, failed == 0,
                    "checkMesh's failed mesh checks on the fine and the coarse grid together: a drag from a mesh that fails them is not trusted")]
    return dict(cd=cd, cd_spread=max(spread, 1e-12), gci=gci if gci_ok else None, refinement_ratio=ratio, checks=checks, drag_n=drag,
                added_resistance=cd / cd_hangar - 1.0)


def reasons(checks: list[dict[str, Any]], r: dict[str, Any]) -> list[str]:
    """One sentence per failing check."""
    out = []
    for c in checks:
        if c["ok"]:
            continue
        if c["name"] == "rans_iterative_scatter":
            out.append("the solver reported no force history" if not math.isfinite(c["value"]) else
                       f"the drag still wanders by {c['value']:.1%} over the last 20 % of iterations (limit {SCATTER_MAX:.0%}): not converged")
        elif c["name"] == "rans_gci" and math.isfinite(c["value"]):
            out.append(f"grid-convergence index {c['value']:.0%} is above {GCI_MAX:.0%}: the grids disagree too much for the drag to mean anything")
        elif c["name"] == "rans_gci":
            out.append("no grid-convergence index: the two grids' drags give none, so the discretization error is unknown")
        elif c["name"] == "rans_mesh_checks":
            out.append(f"checkMesh failed {int(c['value'])} mesh check(s) (fine grid {r['failed_checks']}, coarse grid {r['coarse_failed_checks']}): "
                       "the drag of a mesh that fails them is not trusted")
        else:
            out.append("refinement ratio unknown (no cell counts)" if not math.isfinite(c["value"]) else
                       f"refinement ratio r = {c['value']:.2f} (cells {r['cells']:,} / {r['coarse_cells']:,}) is below {vv.R_MIN}: the GCI is not meaningful")
    return out


def main(argv: list[str]) -> int:  # pragma: no cover
    arm_watchdog(float(argv[2]))
    return run_child(argv[0], argv[1])


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
