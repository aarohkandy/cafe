"""Vehicle-following LBM nest: fixed-size arrays, whole-cell shifts, one-way coarse -> fine coupling, vmapped over vehicles.

The nest is a fixed (nx, ny, nz) block of fine cells that follows a vehicle (the GO-MELT idea named in the BRIEF: a moving
fine domain with fixed-size arrays that shifts by whole cells instead of re-meshing). The populations are held in the ground
frame; the vehicle is a fixed solid mask in the grid whose walls move at the vehicle velocity (moving-wall
bounce-back, Ladd 1994). Each step:
  collide (Smagorinsky + wall model) -> stream -> bounce-back (+ momentum-exchange force) -> shift -> refill -> sponge.
shift   when the vehicle has moved a whole cell from the grid's anchor, `jnp.roll` every population by one cell and
        advance the integer world offset `ix` (at most one cell per axis per step, so the vehicle speed must stay
        below one cell per step; lattice speed ~0.05 makes that true by a factor 20).
refill  the outermost layer of the non-periodic faces is set to the equilibrium of the coarse velocity there
        (trilinear Dirichlet inflow). A shift wraps old trailing-edge populations into the leading layer; refill
        replaces them. `refill=False` exists to test exactly that.
sponge  the next `sponge` layers relax towards the coarse velocity with a quadratic ramp (Davies 1976, Q. J. R.
        Meteorol. Soc. 102, 405), which absorbs the wake leaving through the downstream faces.
The coarse field is a function u(x, y, z, t) -> (3, ...) in m/s in ground coordinates, supplied by the caller (environment
+ synthetic turbulence); `grid_field` wraps a gridded coarse snapshot with trilinear interpolation. Coupling is one-way:
the fine solution never feeds back into WRF/HYCOM (not attempted); `residual_forcing` returns the fine-minus-coarse
residual for diagnostics and sub-grid calibration only.

2:1 coupling: XLB 0.3.1 has no multi-resolution grid (no Neon), so coarse and fine nests are separate `Nest`s and the
fine one reads the coarse one through `grid_field` (trilinear in space, frozen between coarse snapshots); the
non-equilibrium rescaling factor for a population-level interface is `neq_ratio` (Dupuis & Chopard 2003, Phys. Rev. E 67, 066707).
"""
from __future__ import annotations

import json
import math
import os
import pathlib
import time
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray
import jax
import jax.numpy as jnp
from jax.scipy.ndimage import map_coordinates

import cafe.receipts as cr
from cafe.receipts import bracket
from cafe.pm.stage3 import lbm, wallmodel as wm

UEnv = Callable[[jax.Array, jax.Array, jax.Array, Any], jax.Array]       # coarse velocity u(x, y, z, t) -> (3, ...)
Traj = Callable[[Any, Any], tuple[Any, Any]]                              # t, params -> (position, velocity)


@dataclass(frozen=True)
class NestSpec:
    """Static description of a nest. U_ref sets the time step: dt = u_lat dx / U_ref (lattice speed u_lat for U_ref)."""
    shape: tuple[int, ...]
    dx: float
    U_ref: float
    nu: float
    u_lat: float = lbm.U_LAT
    cs: float = 0.17
    mode: str = "reg"
    storage: str = "fp32"
    sponge: int = 4
    periodic: tuple[bool, ...] = (False, False, False)
    wall_model: bool = True
    body_force: tuple[float, ...] = (0.0, 0.0, 0.0)      # lattice units per step, uniform (channel receipt)
    rans_layer: float | None = None          # cells: near-wall mixing-length layer; None = the matching height
    nu_floor: float = 0.0                    # lattice viscosity floor: BGK at tau - 1/2 < ~1e-4 is NaN in float32 on coarse grids (Re distorted)

    @property
    def dt(self) -> float:
        return self.u_lat * self.dx / self.U_ref

    @property
    def nu_lat(self) -> float:
        return max(self.nu * self.dt / self.dx ** 2, self.nu_floor)

    @property
    def tau0(self) -> float:
        return lbm.tau_from_nu(self.nu_lat)

    @property
    def force_scale(self) -> float:
        """lattice force -> newtons per unit density: multiply by rho * dx^4 / dt^2."""
        return self.dx ** 4 / self.dt ** 2


class Geom(NamedTuple):
    solid: jnp.ndarray
    link: jnp.ndarray
    ws: wm.WallSet
    anchor: jnp.ndarray       # (3,) grid cell that follows the vehicle position
    fmask: jnp.ndarray        # links whose momentum exchange counts as force (default: all of them)
    qd: jnp.ndarray | None = None    # (19, nx, ny, nz) wall fraction per link for curved walls (Bouzidi), None = halfway
    sp_ax: jnp.ndarray | None = None  # axis of the flat wall face of a cell (specular reflection), -1 elsewhere
    sp_sg: jnp.ndarray | None = None  # sign of its into-fluid normal


class State(NamedTuple):
    f: jnp.ndarray            # (19, nx, ny, nz) populations, post-streaming, ground frame
    n: jnp.ndarray            # step counter
    ix: jnp.ndarray           # (3,) int world offset of cell (0,0,0) in cells


def make_geom(solid: NDArray[np.bool_], anchor: ArrayLike, pad_walls: int | None = None, periodic: tuple[bool, ...] = (False, False, False),
              force_region: NDArray[np.bool_] | None = None, qdist: NDArray[np.float64] | None = None, specular: bool = True,
              rans_layer: float | None = None) -> Geom:
    """Geometry arrays for one body. The solid may only touch a face that is periodic (a plate spanning a periodic axis)."""
    solid = np.asarray(solid, bool)
    for ax in range(3):
        if not periodic[ax] and (solid.take(0, ax).any() or solid.take(-1, ax).any()):
            raise ValueError(f"solid touches the non-periodic faces of axis {ax}: the nest box is too small")
    link = np.asarray(lbm.links(jnp.asarray(solid)))
    ws = wm.wall_set(solid, link, pad_walls, rans_layer=rans_layer)
    ws = wm.WallSet(*[jnp.asarray(a) for a in ws])
    fax, fsg = lbm.flat_wall_cells(link) if specular else (np.full(solid.shape, -1, np.int8), np.zeros(solid.shape, np.int8))
    fm = link if force_region is None else link & np.asarray(force_region, bool)[None]     # force_region: fluid cells that count
    return Geom(jnp.asarray(solid), jnp.asarray(link), ws, jnp.asarray(anchor, jnp.int32), jnp.asarray(fm),
                None if qdist is None else jnp.asarray(qdist, jnp.float32), jnp.asarray(fax), jnp.asarray(fsg))


def stack_geoms(geoms: list[Geom]) -> Geom:
    """Stack bodies for vmap; wall sets are padded to the longest."""
    n = max(g.ws.cell.shape[1] for g in geoms)
    m = max(g.ws.near.shape[1] for g in geoms)
    gs = [g._replace(ws=wm.WallSet(*(jnp.asarray(a) for a in wm.pad_wall_set(wm.WallSet(*(np.asarray(a) for a in g.ws)), n, m))))
          for g in geoms]
    if any(g.qd is not None for g in gs):                                    # halfway bodies get q = 1/2 when stacked with curved ones
        gs = [g if g.qd is not None else g._replace(qd=jnp.full(g.link.shape, 0.5, jnp.float32)) for g in gs]
    return cast(Geom, jax.tree.map(lambda *a: jnp.stack(a), *gs))


def _shell(spec: NestSpec) -> tuple[NDArray[np.int_], NDArray[np.int_], NDArray[np.float32], NDArray[np.int_]]:
    """Indices and relaxation weights of the refill layer (weight 1) and sponge layers (quadratic ramp) of the open faces."""
    nx, ny, nz = spec.shape
    g = np.stack(np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij"))
    k = np.full(spec.shape, 10 ** 6)
    for ax in range(3):
        if spec.periodic[ax]:
            continue
        n = spec.shape[ax]
        k = np.minimum(k, np.minimum(g[ax], n - 1 - g[ax]))
    m = k <= spec.sponge
    idx = g[:, m]
    kk = k[m]
    w = np.where(kk == 0, 1.0, (1 - kk / (spec.sponge + 1.0)) ** 2)
    inner = idx.copy()
    for ax in range(3):
        if not spec.periodic[ax]:
            inner[ax] = np.clip(inner[ax], 1, spec.shape[ax] - 2)
    return idx, inner, w.astype(np.float32), kk


def linear_track(t: Any, p: Any) -> tuple[Any, Any]:
    """Straight-line vehicle: p = (position at t=0 (3,), velocity (3,)). Returns (position, velocity)."""
    return p[0] + p[1] * t, p[1]


def init_state(spec: NestSpec, geom: Geom, u_env: UEnv, p0: ArrayLike, v0: ArrayLike = (0.0, 0.0, 0.0)) -> State:
    """Populations at equilibrium of the coarse field (rho = 1); solid cells at the body's wall equilibrium."""
    p0 = np.asarray(p0, float)
    ix = jnp.asarray(np.floor(p0 / spec.dx).astype(np.int32)) - geom.anchor
    g = jnp.stack(jnp.meshgrid(*[jnp.arange(n) for n in spec.shape], indexing="ij"))
    x = (ix.reshape(3, 1, 1, 1) + g + 0.5) * spec.dx
    u = jnp.asarray(u_env(x[0], x[1], x[2], 0.0), jnp.float32) * (spec.dt / spec.dx)
    uw = jnp.asarray(v0, jnp.float32) * (spec.dt / spec.dx)
    f = lbm.feq(jnp.ones(spec.shape), u)
    f = jnp.where(geom.solid[None], lbm.feq(jnp.ones(spec.shape), jnp.broadcast_to(uw.reshape(3, 1, 1, 1), (3,) + spec.shape)), f)
    return State(lbm.store(f, spec.storage), jnp.int32(0), ix)


def make_step(spec: NestSpec, u_env: UEnv, traj: Traj = linear_track, refill: bool = True, wall_vel: bool = True,
              rho_override: float | None = None) -> Callable[[State, Geom, Any], tuple[State, dict[str, jax.Array]]]:
    """Returns step(state, geom, params) -> (state, series_row). Pure: scan it, jit it, vmap it over (state, geom, params).
    wall_vel=False drops the moving-wall term and rho_override replaces the refill density: test hooks that let the
    receipts' breaker tests show the checks can fail."""
    idx, inner, w, kk = _shell(spec)
    sidx, iidx = tuple(jnp.asarray(a) for a in idx), tuple(jnp.asarray(a) for a in inner)
    sw = jnp.asarray(w if refill else np.where(kk == 0, 0.0, w))
    lay1 = jnp.asarray(kk == 1)
    sh, dx, dt = jnp.asarray(idx), spec.dx, spec.dt

    def step(state: State, geom: Geom, params: Any) -> tuple[State, dict[str, jax.Array]]:
        f, n, ix = state
        t = n * dt
        p, v = traj(t, params)
        uw = (v * (dt / dx)) if wall_vel else jnp.zeros(3)
        rho0, u0 = lbm.moments(f)
        usp = jnp.where(geom.solid, 0.0, jnp.sqrt((u0 ** 2).sum(0)))
        uwall = uw
        st: dict[str, jax.Array] | None = None
        yfrac = utau = jnp.float32(0)
        if spec.wall_model:
            st = wm.wall_state(u0, geom.ws, spec.nu_lat, uw)
            ok = geom.ws.valid
            yfrac = (((st["yplus"] >= wm.YPLUS_OK[0]) & (st["yplus"] <= wm.YPLUS_OK[1])) & ok).sum() / jnp.maximum(ok.sum(), 1)
            utau = (st["utau"] * ok).sum() / jnp.maximum(ok.sum(), 1)
            uwall = wm.wall_field(uw, geom.ws, st, spec.shape)
        hook = None if st is None else (lambda uu, tau: wm.near_wall_tau(tau, geom.ws, st, spec.nu_lat))
        fp, rho, u, _ = lbm.collide(f, spec.tau0, spec.cs, spec.mode, hook)
        Fw = jnp.zeros(3)
        if st is not None:
            fp, Fw = wm.wall_force(fp, geom.ws, st, geom.fmask.any(0)[tuple(geom.ws.cell)])
        if any(spec.body_force):
            fp = fp + (3 * lbm.Wj * jnp.tensordot(lbm.Cj, jnp.asarray(spec.body_force, jnp.float32), axes=(1, 0)))[:, None, None, None]
        fs = lbm.stream(fp)
        flat = geom.sp_ax >= 0 if geom.sp_ax is not None else jnp.zeros(spec.shape, bool)
        fs, F = lbm.bounce_back(fp, fs, geom.link & ~flat[None], rho, uwall, geom.fmask & ~flat[None], 0.5 if geom.qd is None else geom.qd)
        if geom.sp_ax is not None:
            assert geom.sp_sg is not None
            fs, Fs = lbm.specular(fp, fs, geom.link, geom.sp_ax, geom.sp_sg, geom.fmask, rho, uw)
            F = F + Fs
        fs = lbm.store(fs, spec.storage)
        feq_w = lbm.feq(jnp.ones(spec.shape), jnp.broadcast_to(uw.reshape(3, 1, 1, 1), (3,) + spec.shape))
        fs = jnp.where(geom.solid[None], feq_w, fs)
        # shift: whole cells, at most one per axis per step; periodic axes roll too (the content is periodic anyway)
        p1, _ = traj((n + 1) * dt, params)
        s = jnp.clip(jnp.floor(p1 / dx).astype(jnp.int32) - geom.anchor - ix, -1, 1)
        for ax in range(3):
            fs = jnp.where(s[ax] != 0, jnp.roll(fs, -s[ax], axis=ax + 1), fs)
        ix = ix + s
        # refill + sponge from the coarse field at the new world position and time
        xw = (ix.reshape(3, 1) + sh + 0.5) * dx
        uc = jnp.asarray(u_env(xw[0], xw[1], xw[2], (n + 1) * dt), jnp.float32) * (dt / dx)
        rref = fs[:, iidx[0], iidx[1], iidx[2]].sum(0) if rho_override is None else rho_override
        cur = fs[:, sidx[0], sidx[1], sidx[2]]
        new = cur + sw * (lbm.feq(rref, uc) - cur)
        fs = fs.at[:, sidx[0], sidx[1], sidx[2]].set(new)
        _, ush = lbm.moments(new)
        res = jnp.sqrt((((ush - uc) ** 2).sum(0) * lay1).sum() / jnp.maximum(lay1.sum(), 1))
        row = dict(F=F + Fw, Fw=Fw, mass=fs.sum(), umax=usp.max(), shift=s, res=res, yfrac=yfrac, utau=utau)
        return State(fs, n + 1, ix), row

    return step


def make_run(spec: NestSpec, u_env: UEnv, steps: int, traj: Traj = linear_track, batched: bool = False, **kw: Any) -> Callable[..., Any]:
    """Jitted `run(state, geom, params) -> (state, series)` for `steps` steps (series stacked over steps). With
    batched=True the arguments carry a leading vehicle axis (vmap), series then has shape (vehicles, steps, ...)."""
    step = make_step(spec, u_env, traj, **kw)

    def run(state: State, geom: Geom, params: Any) -> tuple[State, dict[str, jax.Array]]:
        return jax.lax.scan(lambda s, _: step(s, geom, params), state, None, length=steps)

    return jax.jit(jax.vmap(run) if batched else run)


def simulate(spec: NestSpec, u_env: UEnv, geom: Geom, p0: ArrayLike, params: Any, steps: int, chunk: int = 200, v0: ArrayLike = (0, 0, 0),
             traj: Traj = linear_track, state: State | None = None, on_chunk: Callable[[State, int], None] | None = None,
             steps_hook: Callable[[int, float], float] | None = None, **kw: Any) -> tuple[State, dict[str, NDArray[Any]]]:
    """Run `steps` steps in jitted chunks. Returns (state, series dict of NumPy arrays over steps).
    steps_hook(done, elapsed_s) -> total steps: called after every chunk with the wall time since the start (compile included); the
    run goes on to min(steps, what it returns). Return a multiple of `chunk` (another chunk length is another compile)."""
    state = state or init_state(spec, geom, u_env, p0, v0)
    chunks: list[dict[str, NDArray[Any]]] = []
    done, t_start = 0, time.perf_counter()
    runs: dict[int, Callable[..., Any]] = {}
    while done < steps:
        k = min(chunk, steps - done)
        if k not in runs:
            runs[k] = make_run(spec, u_env, k, traj, **kw)
        state, ser = runs[k](state, geom, params)
        chunks.append(jax.tree.map(np.asarray, ser))
        done += k
        if on_chunk:
            on_chunk(state, done)
        if steps_hook:
            steps = min(steps, max(int(steps_hook(done, time.perf_counter() - t_start)), done))
    series = {key: np.concatenate([c[key] for c in chunks]) for key in chunks[0]}
    return state, series


# ---------------------------------------------------------------------------------------------------- coupling helpers
def grid_field(u_grid: ArrayLike, origin: ArrayLike, dx_c: float, t0: float = 0.0, u_grid1: ArrayLike | None = None, t1: float = 1.0) -> UEnv:
    """Trilinear (and optionally linear-in-time) coarse field u(x, y, z, t) from a gridded snapshot u_grid (3, nx, ny, nz) m/s
    whose cell (0,0,0) centre is at `origin` and spacing dx_c. Outside the grid the edge value is held."""
    g0 = jnp.asarray(u_grid, jnp.float32)
    g1 = g0 if u_grid1 is None else jnp.asarray(u_grid1, jnp.float32)
    org = jnp.asarray(origin, jnp.float32).reshape(3, 1)

    def sample(g: jax.Array, x: jax.Array, y: jax.Array, z: jax.Array) -> jax.Array:
        c = (jnp.stack([x.ravel(), y.ravel(), z.ravel()]) - org) / dx_c
        return jnp.stack([map_coordinates(g[d], list(c), order=1, mode="nearest") for d in range(3)]).reshape((3,) + x.shape)

    def u(x: jax.Array, y: jax.Array, z: jax.Array, t: Any) -> jax.Array:
        a = jnp.clip((t - t0) / (t1 - t0), 0.0, 1.0)
        return (1 - a) * sample(g0, x, y, z) + a * sample(g1, x, y, z)
    return u


def restrict(u: ArrayLike, r: int) -> NDArray[Any]:
    """Block-average a (3, nx, ny, nz) field by r in each direction (fine -> coarse)."""
    u = np.asarray(u)
    s = [(n // r) * r for n in u.shape[1:]]
    u = u[:, :s[0], :s[1], :s[2]]
    return u.reshape(3, s[0] // r, r, s[1] // r, r, s[2] // r, r).mean((2, 4, 6))


def residual_forcing(spec: NestSpec, state: State, u_env: UEnv, r: int = 2, t: float = 0.0) -> NDArray[Any]:
    """Fine-minus-coarse residual velocity (m/s) on the r-times coarser grid: what a two-way nest would feed back.
    Returned for diagnostics and sub-grid calibration only; nothing applies it (one-way nest)."""
    _, u = lbm.moments(state.f)
    uf = restrict(np.asarray(u) * (spec.dx / spec.dt), r)
    ix = np.asarray(state.ix)
    g = np.stack(np.meshgrid(*[(ix[a] + np.arange(n) * r + (r - 1) / 2 + 0.5) * spec.dx for a, n in enumerate(uf.shape[1:])],
                             indexing="ij"))
    cx, cy, cz = (jnp.asarray(c, jnp.float32) for c in g)
    res: NDArray[Any] = uf - np.asarray(u_env(cx, cy, cz, t))
    return res


def neq_ratio(tau_from: float, tau_to: float, r: int = 2) -> float:
    """Factor on f_neq when a population crosses a 1:r interface from a grid with tau_from to the r-times finer one with
    tau_to under acoustic scaling (dt_fine = dt_coarse / r), Dupuis & Chopard (2003, Phys. Rev. E 67, 066707): tau_to / (r tau_from)."""
    return tau_to / (r * tau_from)


# ---------------------------------------------------------------------------------------------------- self-check helpers
def running_mean_ok(x: ArrayLike, tol: float = 0.02) -> tuple[bool, float]:
    """BRIEF 5.5: the running mean over the last third of a series stays within `tol` of the last-third mean.
    Returns (ok, max relative deviation)."""
    x = np.asarray(x, float)
    seg = x[-max(len(x) // 3, 2):]
    rm = np.cumsum(seg) / np.arange(1, len(seg) + 1)
    m = seg.mean()
    dev = float(np.abs(rm - m).max() / max(abs(m), 1e-30))
    return dev <= tol, dev


def mass_drift(series: dict[str, Any]) -> float:
    """Largest relative change of the total population sum between consecutive steps."""
    m = np.asarray(series["mass"], float)
    return float(np.abs(np.diff(m) / m[:-1]).max())


# ---------------------------------------------------------------------------------------------------- receipts
RES_MAX = 0.005       # interpolation residual bound: 2x the clean run's 0.0024; the run without refill gives 0.0136
def _sphere(shape: tuple[int, ...], c: ArrayLike, r: float) -> NDArray[np.bool_]:
    g = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij"))
    m: NDArray[np.bool_] = ((g - np.asarray(c).reshape(3, 1, 1, 1)) ** 2).sum(0) <= r * r
    return m


def sphere_drag(re: float, d: int = 8, domain: tuple[float, ...] = (12, 6, 6), steps: int | None = None, lateral: str = "dirichlet",
                cs: float | None = None, u_lat: float = 0.05, sponge: int = 4, bouzidi: bool = True) -> dict[str, Any]:
    """Sphere of d cells in a uniform stream through the nest machinery (stationary nest, no wall model: bounce-back no-slip):
    Dirichlet/sponge faces, `lateral="periodic"` in y and z (an array of spheres), or `lateral="freeslip"`: specular-reflection duct
    walls in y and z (the domain is `domain` diameters across between the walls). Cd from the momentum exchange averaged
    over the last 20 % of the run. This is the native-kernel counterpart of lbm.sphere; `bouzidi` uses the exact sphere wall distance
    (curved-wall bounce-back), False the staircase halfway wall that XLB 0.3.1 has."""
    shape = tuple(int(round(a * d)) for a in domain)
    need, have = float(np.prod(shape)) * NEST_BYTES_PER_CELL, lbm.device_memory_bytes()
    if need > lbm.MEM_LIMIT * have:
        raise lbm.MemoryGuardError(f"{np.prod(shape):.3g} cells need {need / 1e9:.1f} GB of {have / 1e9:.1f} GB: shrink the box or use d smaller")
    nu = u_lat * d / re
    steps = steps or int(30 * d / u_lat)                                       # 30 flow-throughs of a diameter: Cd flat to <0.2 % at Re=100
    cs = (0.0 if re < 500 else 0.17) if cs is None else cs
    duct = 2 if lateral == "freeslip" else 0                                  # wall slab thickness, cells
    per = (False, lateral in ("periodic", "freeslip"), lateral in ("periodic", "freeslip"))
    c = np.array([shape[0] * 0.3, shape[1] / 2, shape[2] / 2]) - 0.5 + np.array([0, duct, duct])
    shape = (shape[0], shape[1] + 2 * duct, shape[2] + 2 * duct)
    spec = NestSpec(shape, 1.0, 1.0, nu / u_lat, u_lat=u_lat, wall_model=False, cs=cs, periodic=per, sponge=sponge)
    q = lbm.ellipsoid_q(shape, c, (d / 2,) * 3) if bouzidi else None
    body = _sphere(shape, c, d / 2)
    solid = body.copy()
    region = None
    if duct:
        inner = slice(1, -1)                                                  # not on the open x faces
        solid[inner, :duct], solid[inner, -duct:], solid[inner, :, :duct], solid[inner, :, -duct:] = True, True, True, True
        region = _sphere(shape, c, d)                                         # only the links near the sphere count as its force
    geom = make_geom(solid, np.round(c), periodic=per, qdist=q, force_region=region)
    env = lambda x, y, z, t: jnp.stack([jnp.ones_like(x), jnp.zeros_like(x), jnp.zeros_like(x)])    # noqa: E731
    p0 = (np.round(c) + 0.5)
    _, ser = simulate(spec, env, geom, p0, (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32)), steps)
    cd = ser["F"][:, 0] / (0.5 * u_lat ** 2 * math.pi * d * d / 4)
    tail = cd[-steps // 5:]
    solid = body
    area_vox = float(solid.any(0).sum())                                     # projected area of the voxel set, cells^2
    d_vol = (6 * solid.sum() / math.pi) ** (1 / 3)                           # volume-equivalent diameter, cells
    return dict(cd=float(tail.mean()), cd_std=float(tail.std()), history=cd[:: max(1, steps // 20)], steps=steps, shape=shape, d=d,
                cd_voxel_area=float(tail.mean() * (math.pi * d * d / 4) / area_vox), d_volume=float(d_vol), u_lat=u_lat)


def uniform_flow_force(wall_vel: bool = True, steps: int = 400, shape: tuple[int, ...] = (40, 28, 28), r: float = 5.0) -> dict[str, Any]:
    """A sphere carried by a uniform stream (flow velocity = vehicle velocity): no relative motion, so the force must be
    zero; the nest shifts every ~1/u_lat steps. Returns |F| relative to the force scale rho U^2 d^2 and the shift count."""
    ul = 0.04
    spec = NestSpec(shape, 0.01, 1.0, 1e-4, u_lat=ul, wall_model=False)
    u = np.array([1.0, 0.3, 0.0])                                            # m/s, oblique: shifts in two axes
    env = lambda x, y, z, t: jnp.stack([jnp.full_like(x, u[0]), jnp.full_like(x, u[1]), jnp.zeros_like(x)])    # noqa: E731
    c = np.array(shape) / 2
    geom = make_geom(_sphere(shape, c, r), np.round(c))
    p0 = (np.round(c) + 0.5) * spec.dx
    params = (jnp.asarray(p0, jnp.float32), jnp.asarray(u, jnp.float32))
    _, ser = simulate(spec, env, geom, p0, params, steps, v0=u, wall_vel=wall_vel)
    fs = float((2 * r) ** 2 * (ul ** 2))
    return dict(f_rel=float(np.abs(ser["F"]).max() / fs), shifts=int(np.abs(ser["shift"]).sum()), series=ser)


def shear_layer_mass(refill: bool = True, rho_override: float | None = None, steps: int = 600,
                    shape: tuple[int, ...] = (32, 48, 16)) -> dict[str, Any]:
    """The nest crosses a shear layer: world flow u_x(y) = U0 + dU tanh(y/delta) uniform in x, nest moving in +y at 0.8 U0.
    Interior stays steady; the per-step relative change of total population sum is the mass-conservation measure."""
    ul = 0.05
    spec = NestSpec(shape, 0.01, 1.0, 1e-4, u_lat=ul, wall_model=False, periodic=(False, False, True), sponge=3)
    delta = 0.06
    env = lambda x, y, z, t: jnp.stack([1.0 + 0.4 * jnp.tanh((y - 0.5) / delta), jnp.zeros_like(x), jnp.zeros_like(x)])    # noqa: E731
    geom = make_geom(np.zeros(shape, bool), np.array(shape) // 2, periodic=spec.periodic)
    p0 = np.array([0.0, 0.3, 0.0])
    vel = np.array([0.0, 0.8, 0.0])
    params = (jnp.asarray(p0, jnp.float32), jnp.asarray(vel, jnp.float32))
    _, ser = simulate(spec, env, geom, p0, params, steps, v0=vel, refill=refill, rho_override=rho_override)
    return dict(drift=mass_drift(ser), shifts=int(np.abs(ser["shift"]).sum()), res=float(np.mean(ser["res"][-100:])) / ul, series=ser)


SLOW_DIR = pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "receipts"
SPHERE_RUNS = (("100", 100.0), ("1000", 1000.0), ("1e4", 1e4))


def sphere_path(tag: str, d: int) -> pathlib.Path:
    return SLOW_DIR / f"nest_sphere_{tag}_d{d}.json"


NEST_BYTES_PER_CELL = 300.0      # populations + double buffer + masks + Bouzidi q (182 B/cell measured for the bare kernel, + 38 masks + 76 q)
DOMAIN = (12, 6, 6)              # diameters: length, width, height of the sphere runs
PLAN = {"100": (16, "d = 16 (with the d = 8 and 12 runs for the extrapolation)"), "1000": (24, "d >= 24"), "1e4": (40, "d >= 40")}


def run_plan(tag: str, d: int | None = None, domain: tuple[float, ...] = DOMAIN) -> dict[str, Any]:
    """What a stored run costs: cells, steps (30 diameter flow-throughs at lattice speed 0.05), cell-updates, memory, the command."""
    d = d or PLAN[tag][0]
    cells = int(np.prod([round(a * d) for a in domain]))
    steps = int(30 * d / lbm.U_LAT_SPHERE)
    cmd = f"python -m cafe.pm.stage3.nest slow {tag} {d} {domain[0]} {domain[1]} {domain[2]} --lateral dirichlet"
    gb = cells * NEST_BYTES_PER_CELL / 1e9
    return dict(d=d, cells=cells, steps=steps, updates=float(cells) * steps, gb=gb, command=cmd,
                eta=lbm.eta_text(float(cells) * steps) + f"; {gb:.1f} GB with --memory {max(2 * round(gb / 2) + 2, 4)}g")


def gpu_command(tag: str, d: int, domain: tuple[float, ...] = DOMAIN) -> str:
    return str(run_plan(tag, d, domain)["command"])


def richardson(ds: ArrayLike, cds: ArrayLike) -> dict[str, Any]:
    """Cd(d) = Cd_inf + b d^-p through the stored resolutions d (cells per diameter). Three or more: p from the finest three
    (Roache-style, solved by bisection) when it lies in [0.5, 3]; otherwise (or with two) first order, p = 1. Returns
    {cd_inf, p, ds}."""
    d, c = np.asarray(ds, float), np.asarray(cds, float)
    o = np.argsort(d)
    d, c = d[o], c[o]
    p = 1.0
    if len(d) >= 3 and abs(c[-2] - c[-1]) > 1e-12:
        d3, c3 = d[-3:], c[-3:]

        def f(q: float) -> float:
            return float((c3[0] - c3[1]) / (c3[1] - c3[2]) - (d3[0] ** -q - d3[1] ** -q) / (d3[1] ** -q - d3[2] ** -q))

        lo, hi = 0.5, 3.0
        if f(lo) * f(hi) < 0:
            for _ in range(60):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if f(lo) * f(mid) > 0 else (lo, mid)
            p = 0.5 * (lo + hi)
    dd, cc = d[-2:], c[-2:]
    b = (cc[0] - cc[1]) / (dd[0] ** -p - dd[1] ** -p)
    return dict(cd_inf=float(cc[1] - b * dd[1] ** -p), p=float(p), ds=[float(x) for x in d])


def sphere_receipts() -> list[dict[str, Any]]:
    """Sphere Cd vs Morrison 2013 at Re = 1e2, 1e3, 1e4 on the native kernel (curved-wall bounce-back), one pass/fail row each (10 %).
    The row is the Richardson-extrapolated Cd from the stored grids (nest_sphere_<Re>_d*.json) when there are two or more, else the
    single stored grid. Stored and within 10 %: pass; stored and outside: fail with the measured error; not stored or stored by
    different code: fail, naming the command and its run time. Each stored grid also gets a context row (the resolution study)."""
    from cafe.receipts import context
    g = "LBM native sphere"
    for tag, re in SPHERE_RUNS:
        ref = lbm.morrison(re)
        runs = sorted((json.loads(f.read_text()) for f in SLOW_DIR.glob(f"nest_sphere_{tag}_d*.json")), key=lambda r: r["d"])
        plan = run_plan(tag)
        for r in runs:
            context(g, f"  study: Re={re:g}, d={r['d']}", r["cd"], ref, "", f"{r['shape']}, {r.get('seconds', 0) / 60:.0f} min")
        rec = None
        if len(runs) >= 2:
            rc = richardson([r["d"] for r in runs], [r["cd"] for r in runs])
            shas = {r.get("code_sha") for r in runs} - {None}
            stale = sorted(shas - {lbm.physics_sha()})
            rec = dict(cd=rc["cd_inf"], ref=ref, code_sha=stale[0] if stale else None)
            claim = f"Sphere Cd at Re={re:g}, Richardson-extrapolated from d={[int(x) for x in rc['ds']]} (order {rc['p']:.2f})"
        elif runs:
            rec = dict(runs[0], ref=ref)
            claim = f"Sphere Cd at Re={re:g}, d={runs[0]['d']}"
        else:
            claim = f"Sphere Cd at Re={re:g}, native kernel with curved-wall bounce-back, {PLAN[tag][1]}"
        lbm.result_row(g, claim, rec, "cd", "ref", 0.10, plan["command"], plan["eta"],
                       "Morrison 2013; Bouzidi et al. 2001 curved wall; Dirichlet box 12 x 6 x 6 d")
    return [r for r in cr.OUT if r["group"] == g]


def main(argv: list[str]) -> int:
    """python -m cafe.pm.stage3.nest [receipts | slow RE D NX NY NZ [--lateral freeslip|dirichlet] [--needs-d N]]"""
    if argv[:1] == ["slow"]:
        sha0 = lbm.physics_sha()
        lat = argv[argv.index("--lateral") + 1] if "--lateral" in argv else "dirichlet"
        need = int(argv[argv.index("--needs-d") + 1]) if "--needs-d" in argv else None
        tag, d = argv[1], int(argv[2])
        dom = tuple(float(a) for a in argv[3:6])
        t0 = time.time()
        r = sphere_drag(float(tag), d, dom, lateral=lat)
        r.update(seconds=time.time() - t0, re=float(tag), ref=lbm.morrison(float(tag)), lateral=lat, history=[float(x) for x in r["history"]],
                 code_sha=sha0)
        if need:
            r["needs_d"] = need
        SLOW_DIR.mkdir(parents=True, exist_ok=True)
        sphere_path(tag, d).write_text(json.dumps(r, default=float))
        print(json.dumps({k: v for k, v in r.items() if k != "history"}, default=float))
        return 0
    receipts()
    return int(any(not r["ok"] for r in cr.OUT if r["ok"] is not None))


def receipts() -> list[dict[str, Any]]:
    g = "LBM nest"
    ok = uniform_flow_force()
    bracket(g, "Vehicle-following nest, uniform flow: |F| / (rho U^2 d^2) (zero expected)", ok["f_rel"], 0, 1e-4, "",
            "analytic: a body at rest in the fluid feels no force; bound is float32 round-off x link count")
    bracket(g, "... number of whole-cell shifts exercised", ok["shifts"], 10, 10 ** 6, "", "the nest actually moved")
    sh = shear_layer_mass()
    bracket(g, "Nest crossing a shear layer: max |dM|/M per step", sh["drift"], 0, 1e-3, "", "BRIEF 5.1: < 0.1 % per step")
    bracket(g, "... interpolation residual at the first sponge layer / u_lat", sh["res"], 0, RES_MAX, "", "coarse -> fine Dirichlet+sponge")
    bracket(g, "... number of whole-cell shifts exercised", sh["shifts"], 10, 10 ** 6, "", "the nest actually moved")
    out = [r for r in cr.OUT if r["group"] == g]
    return out + sphere_receipts()


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main(sys.argv[1:]))
