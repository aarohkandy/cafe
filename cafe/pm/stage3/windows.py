"""One high-resolution window: wall-modelled LES nest + FEA (and interFoam for free-surface boats).

`run_window(vehicle, spec, inflow)` builds a vehicle-following nest from the vehicle's shape primitives (ellipsoid / cylinder
hull, flat-plate wing) or a voxelised STL, runs it, and returns the force time series, drag/lift coefficients with their
spread, the added-resistance proxy, the BRIEF 5.5 `stage3` self-checks, and the mean wall pressure for FEA.
Frame: the window axes are the body axes (x forward, y left, z up, origin at the body centre); `inflow(x, y, z, t)` is the
ground-frame environment velocity (m/s, body axes) at nest coordinates measured from the body centre at t = 0, and
`spec.velocity` is the vehicle velocity in the same frame (the caller rotates WRF/HYCOM into body axes).
`fea_window` maps the wall pressure onto a CalculiX shell model (cafe.fea) and returns the utilization;
`run_windows` overlaps the FEA of window k with the LES of window k+1 in a worker thread.
`free_surface_window` is the interFoam path (cafe.cfd, two-grid GCI), minutes to hours: tests run it at toy size only.
"""
from __future__ import annotations

import math
import os
import pathlib
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import jax.numpy as jnp
from numpy.typing import ArrayLike, NDArray

from cafe.pm.stage3 import lbm, nest, wallmodel as wm

RHO = {"water": 1025.0, "air": 1.20}
NU = {"water": 1.19e-6, "air": 1.5e-5}


@dataclass
class WindowSpec:
    """What one window is. velocity: vehicle velocity in the ground frame (m/s, body axes); duration: physical seconds;
    box: nest size in body lengths; cells_per_delta: 5-10 (BRIEF 2.6); u_lat: lattice speed of the reference U;
    steps overrides duration (tests); spinup: share of the run discarded as start-up.
    nu_floor: lattice viscosity floor (stability on coarse grids); the result says when it was applied and what the physical value was.
    wall_s: wall-clock safety kill of the LES run (XLA compile included): a run still going when it is spent is stopped and says so (`wall_hook`).
    frame: "vehicle" (default) holds the grid on the vehicle and feeds the inflow relative to it (u_env - velocity): Galilean
    exact for constant velocity, no shifts. "ground" keeps the populations in the ground frame and shifts the nest by whole
    cells to follow the vehicle (nest.py): the wake stays where it was left, but each shift displaces the fluid by one cell
    without pushing it, which measured as a spurious force of about -2x the drag at one shift per 25 steps (see report), so forces
    from this mode are not used for coefficients unless the caller accepts that."""
    velocity: tuple[float, ...]
    duration: float = 10.0
    box: tuple[float, ...] = (2.0, 0.6, 0.6)
    cells_per_delta: float = 10
    u_lat: float = lbm.U_LAT
    steps: int | None = None
    spinup: float = 0.3
    dx: float | None = None
    cd_ref: float | None = None
    chunk: int = 200
    storage: str = "fp32"
    frame: str = "vehicle"
    wall_s: float | None = None
    nu_floor: float = 0.0


@dataclass
class Vehicle:
    """shapes: dicts in body axes. {"type": "ellipsoid", "center", "radii"}, {"type": "cylinder", "center", "radius", "length"}
    (axis x), {"type": "plate", "center", "size"} (a box: a wing is a flat plate), {"type": "stl", "path"} (body frame, metres).
    ref_area: for the coefficients (default: frontal area of the voxels). structure: material, wall thickness for FEA."""
    name: str
    fluid: str
    length: float
    shapes: list[dict[str, Any]]
    ref_area: float | None = None
    material: str = "al6061"
    thickness: float = 0.004
    depth: float = 0.0
    hull: int = 0                                                            # index of the shape that carries FEA
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------------------------------- geometry
def _inside(shape: dict[str, Any], x: NDArray[np.float64], y: NDArray[np.float64], z: NDArray[np.float64]) -> NDArray[np.bool_]:
    c = np.asarray(shape.get("center", (0, 0, 0)), float)
    X, Y, Z = x - c[0], y - c[1], z - c[2]
    t = shape["type"]
    if t == "ellipsoid":
        a, b, d = shape["radii"]
        return np.asarray((X / a) ** 2 + (Y / b) ** 2 + (Z / d) ** 2 <= 1, bool)
    if t == "cylinder":
        return np.asarray((np.abs(X) <= shape["length"] / 2) & (Y ** 2 + Z ** 2 <= shape["radius"] ** 2), bool)
    if t == "plate":
        sx, sy, sz = shape["size"]
        return np.asarray((np.abs(X) <= sx / 2) & (np.abs(Y) <= sy / 2) & (np.abs(Z) <= sz / 2), bool)
    raise ValueError(f"unknown shape type {t!r}")


def vehicle_mesh(vehicle: Vehicle, i: int | None = None) -> Any:
    """Closed surface mesh (trimesh, body frame) of shape i (default: the FEA hull)."""
    import trimesh
    s = vehicle.shapes[vehicle.hull if i is None else i]
    c = np.asarray(s.get("center", (0, 0, 0)), float)
    if s["type"] == "stl":
        return trimesh.load(s["path"], force="mesh")
    if s["type"] == "ellipsoid":
        m = trimesh.creation.icosphere(subdivisions=3)
        m.apply_scale(s["radii"])
    elif s["type"] == "cylinder":
        m = trimesh.creation.cylinder(radius=s["radius"], height=s["length"], sections=48)
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))  # type: ignore[no-untyped-call]  # trimesh.transformations is unannotated
    elif s["type"] == "plate":
        m = trimesh.creation.box(extents=s["size"])
    else:
        raise ValueError(f"unknown shape type {s['type']!r}")
    m.apply_translation(c)
    return m


def voxelize(vehicle: Vehicle, dx: float, shape: tuple[int, ...], anchor: tuple[int, ...]) -> NDArray[np.bool_]:
    """Boolean solid mask on the nest grid whose cell `anchor` has its centre at the body origin."""
    g = [(np.arange(n) - a) * dx for n, a in zip(shape, anchor, strict=True)]
    x, y, z = np.meshgrid(*g, indexing="ij")
    solid = np.zeros(shape, bool)
    for s in vehicle.shapes:
        if s["type"] == "stl":
            import trimesh
            m: Any = trimesh.load(s["path"], force="mesh")
            lo, hi = m.bounds
            box = (x >= lo[0]) & (x <= hi[0]) & (y >= lo[1]) & (y <= hi[1]) & (z >= lo[2]) & (z <= hi[2])
            vox = m.voxelized(dx).fill()                                      # surface voxels, holes filled (needs no ray tracer)
            solid[box] |= vox.is_filled(np.stack([x[box], y[box], z[box]], 1))
        else:
            solid |= _inside(s, x, y, z)
    return solid


def frontal_area(solid: NDArray[np.bool_], dx: float, axis: int = 0) -> float:
    return float(solid.any(axis).sum() * dx * dx)


def window_resolution(vehicle: Vehicle, spec: WindowSpec) -> dict[str, Any]:
    """dx, grid shape, time step and step count of a window from the BRIEF 2.6 rule (lbm.les_resolution)."""
    u_rel = float(np.linalg.norm(spec.velocity))
    r = lbm.les_resolution(vehicle.length, u_rel, NU[vehicle.fluid], (spec.cells_per_delta,), spec.box, spec.duration,
                           spec.u_lat, spec.storage)
    row = r["rows"][spec.cells_per_delta]
    dx = spec.dx or row["dx"]
    shape = tuple(max(8, math.ceil(b * vehicle.length / dx)) for b in spec.box)
    steps = spec.steps or math.ceil(spec.duration / (spec.u_lat * dx / u_rel))
    return dict(dx=dx, shape=shape, steps=steps, dt=spec.u_lat * dx / u_rel, delta_te=r["delta_te"], u_rel=u_rel,
                cells=int(np.prod(shape)), y_plus_estimate=2.5 * dx * r["u_tau"] / NU[vehicle.fluid])


# ---------------------------------------------------------------------------------------------------- LES window
def _unit(v: NDArray[np.float64]) -> NDArray[np.float64]:
    return v / max(np.linalg.norm(v), 1e-30)


def blocks(x: ArrayLike, n: int = 5) -> tuple[float, float]:
    """Mean and batch-means spread (std of n block means) of a series."""
    x = np.asarray(x, float)
    parts = np.array_split(x, n)
    bm = np.array([p.mean() for p in parts])
    return float(x.mean()), float(bm.std(ddof=1)) if n > 1 else 0.0


def coefficients(force: NDArray[np.float64], rel_velocity: ArrayLike, rho: float, area: float, spinup: float = 0.3,
                 cd_ref: float | None = None) -> dict[str, Any]:
    """Drag/lift coefficients from a force series (N, body axes) of a body in a fluid moving at `rel_velocity` relative to it.
    Drag is along the relative flow, lift perpendicular to it in the plane of the flow and body z. Cd, Cl are means over the
    run after `spinup` with the batch-means standard error as spread. added_resistance: mean drag over what the hangar
    coefficient `cd_ref` predicts for the same speed, minus 1 (None without cd_ref)."""
    rel = np.asarray(rel_velocity, float)
    e_d = _unit(rel)
    zb = np.array([0.0, 0.0, 1.0])
    e_l = _unit(zb - (zb @ e_d) * e_d)
    q = 0.5 * rho * area * float(np.linalg.norm(rel)) ** 2
    cut = int(len(force) * spinup)
    D, L = force @ e_d, force @ e_l
    nb = 5
    cd_m, cd_s = blocks(D[cut:] / q, nb)
    cl_m, cl_s = blocks(L[cut:] / q, nb)
    added = None if not cd_ref else float(D[cut:].mean() / (cd_ref * q) - 1)
    return dict(drag=D, lift=L, q=q, cd=cd_m, cd_spread=cd_s / math.sqrt(nb), cl=cl_m, cl_spread=cl_s / math.sqrt(nb),
                added_resistance=added, flow_dir=e_d)


def check_row(name: str, value: float, limit: float, ok: bool, **kw: Any) -> dict[str, Any]:
    return dict(name=name, value=float(value), limit=limit, ok=bool(ok), **kw)


def stage3_checks(series: dict[str, NDArray[Any]], spec: nest.NestSpec, force_series: NDArray[Any], buffer: int,
                  plate_error: float | None = None) -> list[dict[str, Any]]:
    """The BRIEF 5.5 `stage3` list. Each can fail; `ok` is the verdict, value/limit are the numbers."""
    ma = float(series["umax"].max() * math.sqrt(3))
    cfl = float(series["umax"].max())
    yf = float(series["yfrac"][len(series["yfrac"]) // 3:].mean()) if spec.wall_model else 1.0
    conv_ok, conv = nest.running_mean_ok(force_series)
    md = nest.mass_drift(series)
    res = float(np.mean(series["res"]) / spec.u_lat)
    shifts = int(np.abs(series["shift"]).sum())
    return [check_row("mach_max", ma, lbm.MACH_MAX, ma <= lbm.MACH_MAX),
            check_row("courant_max", cfl, 0.3, cfl <= 0.3, note="max lattice speed per step (1 cell/step is the stability limit)"),
            check_row("yplus_in_30_300_fraction", yf, 0.9, yf >= 0.9),
            check_row("force_running_mean_dev", conv, 0.02, conv_ok),
            check_row("mass_drift_per_step", md, 1e-3, md <= 1e-3),
            check_row("nest_shift_count", shifts, math.inf, True, note="whole-cell shifts"),
            check_row("interpolation_residual", res, 0.05, res <= 0.05, note="rms(u_fine - u_coarse) at the first sponge layer / u_lat"),
            check_row("sponge_clearance_cells", buffer, spec.sponge + 2, buffer >= spec.sponge + 2,
                      note="distance from the body to the nearest relaxation layer"),
            check_row("wall_model_receipt_error", math.nan if plate_error is None else plate_error, wm.PLATE_TOL,
                      plate_error is not None and plate_error <= wm.PLATE_TOL,
                      note="worse of the stored wall-model receipts (flat plate vs ITTC-57, channel vs Dean); "
                           "fails unless both are stored and within tolerance")]


def wall_hook(steps: int, chunk: int, wall_s: float | None, cells: int, log: dict[str, Any]) -> Callable[[int, float], int]:
    """nest.simulate steps_hook that holds a wall-clock safety kill. It never shortens a run that is on time: the number of steps is the
    caller's (the plan's), whatever the measured speed. After every chunk, if the elapsed time (compile included) has reached `wall_s`
    before the planned steps are done, the run is killed there and `log` says so (killed, cut_reason, run_steps). From chunk 2 on the
    steady cost per step is measured and reported (cells_per_s, compile_s: diagnostics, not inputs to anything)."""
    prev: list[float] = [0, 0.0]                                                          # (steps done, elapsed) after the previous chunk
    first: list[float] = []
    log.update(planned_steps=steps, run_steps=steps, cut_reason=None, killed=False, cells_per_s=None, compile_s=None, les_s=0.0)

    def hook(done: int, elapsed: float) -> int:
        if not first:
            first.append(elapsed)
        if done > chunk:
            per = max((elapsed - prev[1]) / (done - prev[0]), 1e-9)
            log.update(cells_per_s=cells / per, compile_s=max(first[0] - per * chunk, 0.0))
        prev[:] = [done, elapsed]
        log["les_s"] = elapsed
        if wall_s is not None and elapsed >= wall_s and done < steps:
            log.update(run_steps=done, killed=True,
                       cut_reason=f"killed after {done} of {steps} steps: its wall-clock slice of {wall_s:.0f} s was spent (first chunk, with the XLA compile, "
                                  f"took {first[0]:.0f} s)")
            return done
        return steps
    return hook


def run_window(vehicle: Vehicle, spec: WindowSpec, inflow: nest.UEnv, backend: str | None = None) -> dict[str, Any]:
    """Run one LES window. Returns forces (N, body axes), coefficients with spread, checks and the wall pressure map."""
    if backend not in (None, "native"):
        raise ValueError("windows run on the native kernel (wall-modelled nest); see lbm.py for why")
    t_enter = time.perf_counter()
    res = window_resolution(vehicle, spec)
    dx, shape, steps = res["dx"], res["shape"], res["steps"]
    ns = nest.NestSpec(shape, dx, res["u_rel"], NU[vehicle.fluid], u_lat=spec.u_lat, storage=spec.storage, nu_floor=spec.nu_floor)
    res.update(nu_lat=ns.nu_lat, nu_lat_physical=NU[vehicle.fluid] * res["dt"] / dx ** 2, nu_floored=ns.nu_lat > NU[vehicle.fluid] * res["dt"] / dx ** 2)
    lbm.check_memory(res["cells"], None, spec.storage, "native")
    anchor = np.array(shape) // 2
    solid = voxelize(vehicle, dx, shape, tuple(anchor))
    if not solid.any():
        raise ValueError("the vehicle has no cells at this resolution")
    idx = np.argwhere(solid)
    clearance = int(min((idx.min(0)).min(), (np.array(shape) - 1 - idx.max(0)).min()))
    geom = nest.make_geom(solid, anchor)
    if spec.frame not in ("vehicle", "ground"):
        raise ValueError(f"frame must be 'vehicle' or 'ground', not {spec.frame!r}")
    v = np.asarray(spec.velocity, float)
    p0 = (anchor + 0.5) * dx                                                  # body origin = centre of the anchor cell
    vn = v if spec.frame == "ground" else np.zeros(3)                         # velocity of the nest in the inflow's frame
    env = lambda x, y, z, t: inflow(x - p0[0], y - p0[1], z - p0[2], t) - jnp.asarray(v - vn, jnp.float32).reshape(3, *([1] * x.ndim))   # noqa: E731
    params = (jnp.asarray(p0, jnp.float32), jnp.asarray(vn, jnp.float32))
    pwall = np.zeros(geom.ws.cell.shape[1])
    acc: list[NDArray[Any]] = []

    def on_chunk(state: nest.State, done: int) -> None:                       # wall density of the last three chunks: the mean pressure
        rho = np.asarray(state.f.sum(0))
        c = np.asarray(geom.ws.cell)
        acc.append(rho[c[0], c[1], c[2]])
        del acc[:-3]

    wlog: dict[str, Any] = {}
    pre = time.perf_counter() - t_enter                                        # voxelising, wall set, memory guard: part of the budget
    wall = None if spec.wall_s is None else max(spec.wall_s - pre, 0.0)
    state, ser = nest.simulate(ns, env, geom, p0, params, steps, chunk=spec.chunk, v0=tuple(vn), on_chunk=on_chunk,
                               steps_hook=wall_hook(steps, spec.chunk, wall, res["cells"], wlog))
    wlog["setup_s"] = pre
    n = len(ser["F"])
    rho_f = RHO[vehicle.fluid]
    fsi = ser["F"] * rho_f * ns.force_scale                                    # N, body axes
    t = (np.arange(n) + 1) * ns.dt
    z0 = jnp.zeros(1)
    rel = np.asarray(inflow(z0, z0, z0, 0.0))[:, 0] - v                        # fluid relative to the body
    area = vehicle.ref_area or frontal_area(solid, dx)
    co = coefficients(fsi, rel, rho_f, area, spec.spinup, spec.cd_ref)
    cut = int(n * spec.spinup)
    # wall pressure (gauge, Pa) at the wall cells, mean over the last chunks: p = cs^2 (rho - 1) rho_f (dx/dt)^2
    if acc:
        pwall = (np.mean(acc, 0) - 1.0) / 3.0 * rho_f * (dx / ns.dt) ** 2
    cell = np.asarray(geom.ws.cell)
    pts = (cell.T - anchor) * dx
    checks = stage3_checks(ser, ns, co["drag"][cut:], clearance, wm.stored_wall_error() if ns.wall_model else 0.0)
    return dict(vehicle=vehicle.name, resolution=res, t=t, force=fsi, ref_area=area, **co, checks=checks,
                ok=all(c["ok"] for c in checks), wall_points=pts, wall_pressure=pwall, source="native-nest",
                shifts=int(np.abs(ser["shift"]).sum()), series={k: ser[k] for k in ("umax", "res", "yfrac")}, wall=wlog, steps_run=n)


# ---------------------------------------------------------------------------------------------------- FEA
def tri_quality(nodes: NDArray[Any], faces: NDArray[Any]) -> float:
    """Minimum of 4 sqrt(3) A / (l1^2 + l2^2 + l3^2) over triangles (1 = equilateral)."""
    a, b, c = (nodes[faces[:, i]] for i in range(3))
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
    ll = ((b - a) ** 2).sum(1) + ((c - b) ** 2).sum(1) + ((a - c) ** 2).sum(1)
    return float((4 * math.sqrt(3) * area / np.maximum(ll, 1e-30)).min())


def fea_window(vehicle: Vehicle, points: NDArray[Any], pressure: NDArray[Any], workdir: str | os.PathLike[str] | None = None, h: float | None = None,
               buckle: bool = False) -> dict[str, Any]:
    """Shell model of the vehicle's hull under the window's wall pressure plus hydrostatic pressure at `vehicle.depth`.
    Pressure at a shell element = value at the nearest LBM wall cell. Utilization = von Mises (99th percentile, as
    cafe.fea reports it) / yield, or the reciprocal of the buckling factor when `buckle`, whichever is larger."""
    from scipy.spatial import cKDTree
    from cafe import fea
    m = vehicle_mesh(vehicle)
    tree = cKDTree(points)
    hydro = RHO[vehicle.fluid] * 9.81 * vehicle.depth
    pr = lambda cen, nrm: pressure[tree.query(cen)[1]] + hydro            # noqa: E731  (positive pushes inward)
    steps = ("static", "buckle") if buckle else ("static",)
    r = fea.solve(m, "shell", vehicle.material, thickness=vehicle.thickness, pressure=pr, steps=steps, h=h, workdir=workdir)
    util = r["vm_p99"] / fea.MATERIALS[vehicle.material]["yield_"]
    if buckle and r.get("buckling_factor"):
        util = max(util, 1.0 / r["buckling_factor"])
    f = r.pop("field")
    return dict(utilization=float(util), vm_p99=r["vm_p99"], vm_max=r["vm_max"], safety_factor=r["safety_factor"],
                buckling_factor=r.get("buckling_factor"), elements=r["elements"], nodes=r["nodes"],
                min_element_quality=tri_quality(f["nodes"], f["faces"]), hydrostatic_pa=hydro)


def run_windows(jobs: list[tuple[Vehicle, WindowSpec]], inflow: nest.UEnv, omp_threads: int | None = None,
                fea_kw: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """jobs: [(Vehicle, WindowSpec)]. LES of window k+1 runs on this thread while the FEA of window k runs in a worker
    (CalculiX is pinned to one thread by cafe.fea; OMP_NUM_THREADS from the argument or the environment is set for the rest)."""
    if omp_threads:
        os.environ["OMP_NUM_THREADS"] = str(omp_threads)
    out: list[dict[str, Any]] = []
    pending: tuple[dict[str, Any], Future[dict[str, Any]]] | None = None
    with ThreadPoolExecutor(1) as pool:
        for veh, sp in jobs:
            r = run_window(veh, sp, inflow)
            if pending:
                pending[0]["fea"] = pending[1].result()
            pending = (r, pool.submit(fea_window, veh, r["wall_points"], r["wall_pressure"], **(fea_kw or {})))
            out.append(r)
        if pending:
            pending[0]["fea"] = pending[1].result()
    return out


# ---------------------------------------------------------------------------------------------------- free surface
def fluidx3d_window(vehicle: Vehicle, spec: WindowSpec, config: dict[str, Any] | None, workdir: str | os.PathLike[str], stl: str | None = None,
                    free_surface: bool = False, draft: float = 0.0) -> dict[str, Any]:
    """The same window through the FluidX3D plugin (raises FluidX3DUnavailable unless the config enables it and the binary exists)."""
    from cafe.pm.stage3 import fluidx3d
    res = window_resolution(vehicle, spec)
    rho = RHO[vehicle.fluid]
    case = fluidx3d.case_dict(vehicle.name, res["shape"], res["dx"], res["dt"], NU[vehicle.fluid], rho, spec.velocity, res["steps"],
                              stl, free_surface, draft)
    r = fluidx3d.run_case(config, case, workdir)
    v = np.asarray(spec.velocity, float)
    area = vehicle.ref_area or math.pi * (vehicle.length / 8) ** 2
    co = coefficients(r["force"], -v, rho, area, spec.spinup, spec.cd_ref)
    return dict(vehicle=vehicle.name, resolution=res, t=r["t"], force=r["force"], ref_area=area, **co, source="fluidx3d",
                binary_sha256=r["binary_sha256"], checks=[], ok=True)


def free_surface_window(stl: str | os.PathLike[str], draft: float, speeds: list[float], workdir: str | os.PathLike[str],
                        runner: Callable[..., dict[str, Any]] | None = None, config: dict[str, Any] | None = None,
                        vehicle: Vehicle | None = None) -> dict[str, Any]:
    """Free-surface boat window. With the FluidX3D plugin enabled in `config` (and a `vehicle`) it replaces interFoam
    (BRIEF 2.6); otherwise interFoam at the planner's resolution with the two-grid GCI (cafe.cfd.characterize_free_surface):
    resistance and vertical force per speed with the GCI of each. `runner` defaults to cfd's."""
    from cafe.pm.stage3 import fluidx3d
    if vehicle is not None and fluidx3d.available(config)[0]:
        out: dict[float, dict[str, Any]] = {}
        for U in speeds:
            r = fluidx3d_window(vehicle, WindowSpec(velocity=(float(U), 0.0, 0.0), steps=1000), config,
                                pathlib.Path(workdir) / f"U{U:g}", str(stl), True, draft)
            out[float(U)] = dict(resistance=float(r["drag"][int(len(r["drag"]) * 0.3):].mean()), gci=None, fz=None)
        return dict(speeds=out, cells=None, coarse_cells=None, source="fluidx3d")
    from cafe import cfd
    run = runner or cfd.characterize_free_surface
    r = run(str(stl), draft, pathlib.Path(workdir), list(speeds))
    return dict(speeds={float(U): dict(resistance=v["resistance"], gci=v.get("gci"), lift=v.get("lift"), std=v.get("resistance_std"))
                        for U, v in r["speeds"].items()},
                cells=r.get("mesh", {}).get("cells"), coarse_cells=r.get("coarse_cells"), source="interfoam")
