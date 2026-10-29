"""Lattice-Boltzmann solvers behind one interface, plus the resolution rule and memory model the planner reads.

Backends (`backend=`):
  "jax"    XLB 0.3.1 on its JAX backend (CPU always; also runs on a GPU through JAX).
  "warp"   XLB 0.3.1 on its Warp backend (CUDA when a device exists; warp 1.12 also has a CPU device, which this
           module uses, so the Warp code path is exercised on a GPU-less box).
  "native" the D3Q19 kernel in this file (pure JAX): the engine of the wall-modelled moving nest, because XLB 0.3.1
           has no wall-model BC, no moving nest and no vmap-able boundary state (see nest.py).
  "fluidx3d" external binary, disabled by default (fluidx3d.py, docs/LICENSES.md).
`pick_backend()` returns "warp" when warp sees a CUDA device and "jax" otherwise: the GPU path is the same code.

XLB 0.3.1 has no Neon / multi-resolution grids (checked: no `neon`, no refinement operator in the installed package),
so the 2:1 coupling is ours (nest.py). Its `SmagorinskyLESBGK` uses 36 Cs^2 |Pi| under the square root where
Hou et al. (1996, eq. 8) derive 18 sqrt(2) Cs^2 |Pi|; XLB's Cs = 0.17 therefore acts as Cs = 0.17 * (36 / (18 sqrt 2))^0.5
= 0.202. `XLB_CS_SCALE` converts; test_lbm checks the two collision operators agree after the conversion.

Storage precision: `storage="fp32"` or `"fp16"` ("auto": fp16 on a GPU, fp32 on CPU). `--fp32-storage` on the command line
forces fp32. XLB's FP32FP16 policy stores the raw populations in IEEE half precision (about 1e-3 relative), which is
the size of the non-equilibrium part, so it cannot hold a decay rate; the native kernel stores f - w_i in half
precision instead (FluidX3D's FP16S idea; Lehmann, Krauzig & Schmid, Phys. Rev. E 106, 015308, 2022), which keeps the fluctuation to ~1e-3 of itself.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import pathlib
import sys
import time
from functools import partial
from typing import Callable

import numpy as np

import jax
import jax.numpy as jnp

from cafe.planner import boundary_layer
import cafe.receipts as cr
from cafe.receipts import receipt, bracket

# ---------------------------------------------------------------------------------------------------- D3Q19 (native)
_AX = [(0, 0, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
_DG = [(a, b, 0) for a in (1, -1) for b in (1, -1)] + [(a, 0, b) for a in (1, -1) for b in (1, -1)] \
    + [(0, a, b) for a in (1, -1) for b in (1, -1)]
C19 = np.array(_AX + _DG, dtype=np.int32)                                   # (19, 3)
W19 = np.array([1 / 3] + [1 / 18] * 6 + [1 / 36] * 12)
OPP19 = np.array([int(np.where((C19 == -c).all(1))[0][0]) for c in C19])
CS2 = 1.0 / 3.0
XLB_CS_SCALE = (36.0 / (18.0 * math.sqrt(2.0))) ** 0.5                       # Cs_effective / Cs_coefficient in XLB
MACH_MAX = 0.1
U_LAT_SPHERE = 0.05                # lattice speed of the sphere runs (lbm.sphere, nest.sphere_drag)
U_LAT = 0.04                       # reference lattice speed: 0.04 * sqrt(3) = Ma 0.069, leaves 44 % local overshoot before Ma 0.1

# Memory per cell (BRIEF section 3, from FluidX3D's documented layout, Lehmann 2022).
BYTES_PER_CELL = {"fp32": 93.0, "fp16": 55.0}
# The JAX/XLB path keeps f, a streamed copy, the collision output and moments alive: the BRIEF says 2-3x FluidX3D.
# `measure_jax_bytes_per_cell` measured 182 B/cell (fp32, periodic native step, homebase) = 1.96x; the nest adds link and force
# masks (38 B/cell), so 2.5 is used.
JAX_MEM_FACTOR = 2.5
MEM_LIMIT = 0.85


class MemoryGuardError(ValueError):
    """The requested cell count does not fit the device; the message says what to change."""


def pick_backend() -> str:
    try:
        import warp as wp
        wp.config.quiet = True
        wp.init()
        if wp.get_cuda_device_count() > 0:
            return "warp"
    except Exception:                                                        # warp missing or broken: fall back
        pass
    return "jax"


def storage_for(storage: str = "auto", fp32_storage: bool = False) -> str:
    """"fp16" on a GPU, "fp32" on CPU unless forced: half storage only pays where bandwidth is the limit."""
    if fp32_storage:
        return "fp32"
    if storage != "auto":
        if storage not in BYTES_PER_CELL:
            raise ValueError(f"storage must be fp32, fp16 or auto, not {storage!r}")
        return storage
    return "fp16" if jax.devices()[0].platform == "gpu" else "fp32"


def device_memory_bytes() -> float:
    """GPU memory limit from JAX when there is a GPU; otherwise the container's cgroup limit or physical RAM."""
    d = jax.devices()[0]
    if d.platform == "gpu":
        return float(d.memory_stats()["bytes_limit"])
    for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            v = pathlib.Path(p).read_text().strip()
            if v.isdigit() and int(v) < 1 << 60:
                return float(v)
        except OSError:
            pass
    return float(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))


def memory_bytes(cells: float, storage: str = "fp32", backend: str = "warp") -> float:
    """Device bytes for `cells` lattice cells: FluidX3D layout on warp/fluidx3d, JAX_MEM_FACTOR times that on jax/native."""
    b = BYTES_PER_CELL[storage] * cells
    return b * JAX_MEM_FACTOR if backend in ("jax", "native") else b


def check_memory(cells: float, device_bytes: float | None = None, storage: str = "fp32", backend: str = "warp",
                 limit: float = MEM_LIMIT) -> float:
    """Refuse more than `limit` (85 %) of device memory. Returns the fraction used; on refusal says how far to cut."""
    dev = device_memory_bytes() if device_bytes is None else device_bytes
    need = memory_bytes(cells, storage, backend)
    if need <= limit * dev:
        return need / dev
    cap = limit * dev / memory_bytes(1, storage, backend)
    cut = (cells / cap) ** (1 / 3)
    other = "fp16" if storage == "fp32" else None
    opts = [f"coarsen dx by {cut:.2f}x", f"shrink the box by {cut:.2f}x per axis", f"cap at {cap:.3g} cells"]
    if other:
        opts.insert(0, f"use fp16 storage ({BYTES_PER_CELL['fp16']:.0f} instead of {BYTES_PER_CELL['fp32']:.0f} B/cell)")
    raise MemoryGuardError(f"{cells:.3g} cells need {need / 1e9:.1f} GB of {dev / 1e9:.1f} GB ({need / dev:.0%} > {limit:.0%}) "
                           f"on {backend}/{storage}: " + "; ".join(opts))


# ---------------------------------------------------------------------------------------------------- resolution rule
def tau_from_nu(nu_lat):
    """BGK relaxation time for lattice viscosity nu: nu = cs^2 (tau - 1/2) with cs^2 = 1/3, so tau = 1/2 + 3 nu."""
    return 0.5 + 3.0 * nu_lat


def lattice_params(U: float, dx: float, nu: float, u_lat: float = U_LAT) -> dict:
    """Physical -> lattice: dt = u_lat dx / U, nu_lat = nu dt / dx^2, tau = 1/2 + 3 nu_lat."""
    dt = u_lat * dx / U
    nu_lat = nu * dt / dx ** 2
    return dict(dt=dt, nu_lat=nu_lat, tau=tau_from_nu(nu_lat), mach=u_lat * math.sqrt(3), u_lat=u_lat)


def les_resolution(L: float, U: float, nu: float, cells_per_delta: tuple = (5, 10), box: tuple = (4.0, 1.0, 1.0),
                   T: float = 10.0, u_lat: float = U_LAT, storage: str = "fp32", kappa: float = 0.41, B: float = 5.2) -> dict:
    """Wall-modelled LES resolution for a body of length L at relative speed U in a fluid of viscosity nu.

    delta_te = 0.37 L Re^-1/5 (turbulent flat plate, trailing edge, 1/5-power law: Schlichting & Gersten, Boundary-Layer Theory, ch. 18;
    same as cafe.planner.boundary_layer).
    For each n in `cells_per_delta` (5-10 cells per boundary-layer thickness, BRIEF 2.6): dx = delta_te / n, the cell
    count of a box of `box` body lengths, the LBM step count for T physical seconds at lattice speed `u_lat`
    (Ma = u_lat sqrt 3 <= 0.1), tau, and y+ of the third-cell matching point y = 2.5 dx using the flat-plate skin friction
    (Schlichting: cf = 0.0592 Re^-1/5; u_tau = U sqrt(cf/2)). The 30-300 y+ window of the wall model is checked and
    reported, not forced: at the BRIEF's own 1.5 m hull this gives y+ ~ 400 at dx = 3 mm.
    """
    re = U * L / nu
    d_te = float(boundary_layer(L, U, nu))
    u_tau = U * math.sqrt(0.0592 * re ** -0.2 / 2)
    rows = {}
    for n in cells_per_delta:
        dx = d_te / n
        nx, ny, nz = (max(1, math.ceil(b * L / dx)) for b in box)
        cells = nx * ny * nz
        lp = lattice_params(U, dx, nu, u_lat)
        ym = 2.5 * dx
        yplus = ym * u_tau / nu
        rows[n] = dict(dx=dx, shape=(nx, ny, nz), cells=cells, dt=lp["dt"], steps=math.ceil(T / lp["dt"]), tau=lp["tau"],
                       nu_lat=lp["nu_lat"], mach=lp["mach"], y_plus_match=yplus, y_plus_ok=30 <= yplus <= 300,
                       gb_fluidx3d=memory_bytes(cells, storage, "warp") / 1e9, gb_jax=memory_bytes(cells, storage, "jax") / 1e9,
                       dx_for_y_plus_300=300 * nu / u_tau / 2.5)
    return dict(L=L, U=U, nu=nu, re=re, delta_te=d_te, u_tau=u_tau, kappa=kappa, B=B, rows=rows, storage=storage)


# ---------------------------------------------------------------------------------------------------- native kernel
Cj, Wj, OPPj = jnp.asarray(C19, jnp.float32), jnp.asarray(W19, jnp.float32), jnp.asarray(OPP19)


def _wshape(x):
    return Wj.reshape((19,) + (1,) * (x.ndim - 1))


def feq(rho, u):
    """D3Q19 second-order equilibrium; rho (...), u (3, ...) -> (19, ...)."""
    cu = jnp.tensordot(Cj, u, axes=(1, 0))
    return _wshape(cu) * rho * (1 + 3 * cu + 4.5 * cu * cu - 1.5 * (u * u).sum(0))


def moments(f):
    rho = f.sum(0)
    return rho, jnp.tensordot(Cj.T, f, axes=(1, 0)) / rho


def pi_neq(fn):
    """Second moment of the non-equilibrium part, shape (3, 3, ...)."""
    return jnp.einsum("qa,qb,q...->ab...", Cj, Cj, fn)


def smagorinsky_tau(Q, rho, tau0, cs):
    """Hou et al. (1996, eq. 8): tau = (tau0 + sqrt(tau0^2 + 18 sqrt2 Cs^2 |Pi|/rho)) / 2, |Pi| the Frobenius norm."""
    return 0.5 * (tau0 + jnp.sqrt(tau0 ** 2 + 18 * math.sqrt(2.0) * cs ** 2 * Q / rho))


def collide(f, tau0, cs=0.17, mode="reg", tau_hook=None):
    """BGK collision with Smagorinsky eddy viscosity. mode "reg": the non-equilibrium part is first projected onto
    its second moment (Latt & Chopard 2006, regularized LBM), which keeps tau near 1/2 stable; "bgk": plain.
    tau_hook(u, tau) -> tau lets the wall model raise the relaxation time near walls. Returns (f_post, rho, u, tau)."""
    rho, u = moments(f)
    fe = feq(rho, u)
    fn = f - fe
    P = pi_neq(fn)
    Q = jnp.sqrt((P * P).sum((0, 1)))
    tau = smagorinsky_tau(Q, rho, tau0, cs) if cs > 0 else jnp.full_like(rho, tau0)
    if tau_hook is not None:
        tau = tau_hook(u, tau)
    if mode == "reg":
        tr = jnp.einsum("aa...->...", P)
        fn = 4.5 * _wshape(fn) * (jnp.einsum("qa,qb,ab...->q...", Cj, Cj, P) - tr / 3)
    elif mode != "bgk":
        raise ValueError(f"collision mode {mode!r}")
    return fe + (1 - 1 / tau) * fn, rho, u, tau


def stream(f):
    """Periodic streaming by whole-cell rolls (NumPy shifts: they must be concrete under jit)."""
    return jnp.stack([jnp.roll(f[q], tuple(int(x) for x in C19[q]), axis=(0, 1, 2)) for q in range(19)])


def links(solid):
    """link[q, x] = fluid cell x has a solid neighbour in direction q: where halfway bounce-back acts."""
    nb = jnp.stack([jnp.roll(solid, tuple(-int(x) for x in C19[q]), axis=(0, 1, 2)) for q in range(19)])
    return nb & ~solid[None]


def bounce_back(f_post, f_streamed, link, rho, u_wall, fmask=None, qdist=0.5):
    """Bounce-back with a moving wall (Ladd 1994): f_qbar(x) = f_q^+(x) - 6 w_q rho (c_q . u_w), wall halfway along the link.
    qdist: wall distance along each link as a fraction of the link, scalar 0.5 (halfway, staircase) or a (19, nx, ny, nz) array
    for a curved wall, then Bouzidi, Firdaouss & Lallemand (2001, Phys. Fluids 13, 3452) linear interpolation:
    q < 1/2: f_qbar = 2q f_q^+(x) + (1-2q) f_q^+(x - c_q);  q >= 1/2: f_qbar = f_q^+(x)/(2q) + (2q-1)/(2q) f_qbar^+(x).
    u_wall: (3,) for a rigid wall, or a (3, nx, ny, nz) field (the wall model sets a slip velocity per wall cell).
    Returns (f_new, F): F is the momentum-exchange force on the wall, sum over the links in `fmask` (default: all) of
    c_q (f_q^+ + f_qbar_new) (Mei et al. 2002 for the curved case). For a flat halfway wall and a fluid cell moving at u_1 the
    equilibrium part of that sum is F_t = rho c_s^2 (u_1 - u_w) per cell face (c_s^2 = 1/3)."""
    uw = jnp.asarray(u_wall, jnp.float32)
    uw = uw.reshape((3,) + (1,) * rho.ndim) if uw.ndim == 1 else uw
    cu = jnp.tensordot(Cj, uw, axes=(1, 0))
    if isinstance(qdist, float):
        reflected = f_post
    else:
        q = jnp.clip(qdist, 1e-3, 1.0)
        reflected = jnp.where(q < 0.5, 2 * q * f_post + (1 - 2 * q) * f_streamed, f_post / (2 * q) + (2 * q - 1) / (2 * q) * f_post[OPPj])
    out = reflected - 6 * _wshape(f_post) * rho[None] * cu                   # population sent back along qbar
    f_new = jnp.where(link[OPPj], out[OPPj], f_streamed)
    F = jnp.einsum("qd,q->d", Cj, jnp.where(link if fmask is None else fmask, f_post + out, 0.0).sum(tuple(range(1, f_post.ndim))))
    return f_new, F


def _mirror_table() -> np.ndarray:
    """MIR[a, q]: index of the velocity with component a reversed."""
    m = np.zeros((3, 19), int)
    for a in range(3):
        for q in range(19):
            c = C19[q].copy()
            c[a] = -c[a]
            m[a, q] = int(np.where((C19 == c).all(1))[0][0])
    return m


MIR = _mirror_table()


def flat_wall_cells(link) -> tuple:
    """Fluid cells whose solid links are exactly those of one axis-aligned flat face: (axis (nx,ny,nz) int8, sign int8), axis = -1
    elsewhere. For a wall whose solid side is at -s along axis a the links are all q with c_q[a]*s < 0 (5 of them); the sign s is
    that of the outward (into-fluid) normal. Only these cells can use specular reflection exactly."""
    link = np.asarray(link, bool)
    ax = np.full(link.shape[1:], -1, np.int8)
    sg = np.zeros(link.shape[1:], np.int8)
    for a in range(3):
        for s in (1, -1):
            toward = [q for q in range(19) if C19[q, a] * s < 0]
            other = [q for q in range(1, 19) if q not in toward]
            m = link[toward].all(0) & ~link[other].any(0)
            ax[m], sg[m] = a, s
    return ax, sg


def specular(f_post, f_new, link, ax, sg, fmask=None, rho=None, u_wall=None):
    """Specular reflection at axis-aligned flat walls (free slip, exact): the population leaving toward the wall comes back with
    the wall-normal component reversed and the tangential component kept, f_new[t] = f_post[MIR[a][t]]. No tangential momentum is
    exchanged and the force on the wall is purely normal. A wall moving with velocity u_wall (the body velocity in the ground
    frame) reflects relative to the equilibrium of that velocity, f_new[t] = f_q^+ - (feq_q(u_w) - feq_t(u_w)), which keeps a fluid
    that moves with the wall exactly at rest relative to it (second-order terms included). Returns (f_new, F) with F the full
    momentum given to the wall, sum of c_q f_q^+ - c_t f_new[t] over the links in `fmask`."""
    fm = link if fmask is None else fmask
    r = jnp.ones(link.shape[1:]) if rho is None else rho
    fe = None if u_wall is None else feq(r, jnp.broadcast_to(jnp.asarray(u_wall, jnp.float32).reshape(3, 1, 1, 1), (3,) + r.shape))
    F = jnp.zeros(3)
    for a in range(3):
        for s in (1, -1):
            cells = (ax == a) & (sg == s)
            for q in range(19):
                if C19[q, a] * s < 0:                                        # leaves toward the wall
                    t = int(MIR[a, q])
                    new = f_post[q] if fe is None else f_post[q] - (fe[q] - fe[t])
                    f_new = f_new.at[t].set(jnp.where(link[q] & cells, new, f_new[t]))
                    m = fm[q] & cells
                    F = F + jnp.where(m, C19[q][:, None, None, None] * f_post[q] - C19[t][:, None, None, None] * new, 0.0).sum((1, 2, 3))
    return f_new, F


def ellipsoid_q(shape, center, radii) -> np.ndarray:
    """Fractional wall distance q (19, nx, ny, nz) for an ellipsoid: for each fluid cell and lattice direction the smallest
    t in (0, 1] with x + t c on the surface, 0.5 where the link does not cross it. Cell centres are at integer coordinates."""
    g = np.stack(np.meshgrid(*[np.arange(n) for n in shape], indexing="ij")).astype(float)
    r = np.asarray(radii, float).reshape(3, 1, 1, 1)
    p = (g - np.asarray(center, float).reshape(3, 1, 1, 1)) / r
    q = np.full((19,) + tuple(shape), 0.5)
    for k in range(1, 19):
        c = C19[k].reshape(3, 1, 1, 1) / r
        a, b, cc = (c * c).sum(0), 2 * (p * c).sum(0), (p * p).sum(0) - 1
        disc = b * b - 4 * a * cc
        t = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * a)
        hit = (disc >= -1e-12) & (cc > 0) & (t > 0) & (t <= 1 + 1e-9)            # starts outside, enters within one link (t = 1: on the node)
        q[k] = np.where(hit, np.minimum(t, 1.0), 0.5)
    return q


def store(f, storage):
    """Round-trip through the storage format. fp16 keeps f - w_i (FluidX3D FP16S idea), so the quantization error is
    relative to the fluctuation, not to f."""
    if storage == "fp32":
        return f
    return (f - _wshape(f)).astype(jnp.float16).astype(jnp.float32) + _wshape(f)


@partial(jax.jit, static_argnames=("steps", "cs", "mode", "storage"))
def periodic_run(f, tau0, steps, cs=0.0, mode="reg", storage="fp32"):
    """`steps` collide+stream steps in a fully periodic box (Taylor-Green and kernel tests)."""
    def body(f, _):
        fp, *_ = collide(f, tau0, cs, mode)
        return store(stream(fp), storage), None
    return jax.lax.scan(body, f, None, length=steps)[0]


# ---------------------------------------------------------------------------------------------------- XLB bridge
def _xlb_session(backend: str, d: int, storage: str = "fp32"):
    """xlb.init with the right velocity set / precision policy; returns (xlb module bits, grid factory)."""
    import xlb
    from xlb.compute_backend import ComputeBackend
    from xlb.precision_policy import PrecisionPolicy
    from xlb.grid import grid_factory
    from xlb.operator.boundary_condition.boundary_condition_registry import boundary_condition_registry as reg
    reg.id_to_bc.clear(), reg.bc_to_id.clear()                               # XLB's warp stepper breaks once ids pile up across runs
    reg.next_id = 1
    be = {"jax": ComputeBackend.JAX, "warp": ComputeBackend.WARP}[backend]
    pp = PrecisionPolicy.FP32FP16 if storage == "fp16" else PrecisionPolicy.FP32FP32
    vs = (xlb.velocity_set.D2Q9 if d == 2 else xlb.velocity_set.D3Q19)(precision_policy=pp, compute_backend=be)
    xlb.init(velocity_set=vs, default_backend=be, default_precision_policy=pp)
    return xlb, be, pp, vs, grid_factory


class XlbRun:
    """One XLB stepper on either backend. fields() returns (rho, u) as NumPy; force() the momentum-exchange force on `body`."""

    def __init__(self, session, backend, shape, bcs, nu, rho0=None, u0=None, collision="BGK", force=None, body_bc=None):
        d = len(shape)
        xlb, be, pp, vs, gf = session
        self.xlb, self.be, self.pp, self.vs, self.backend, self.shape, self.d = xlb, be, pp, vs, backend, shape, d
        self.grid = gf(shape, compute_backend=be)
        fv = None if force is None else np.asarray(force, float)
        self.stepper = xlb.operator.stepper.IncompressibleNavierStokesStepper(
            grid=self.grid, boundary_conditions=bcs, collision_type=collision, force_vector=fv) \
            if fv is not None else xlb.operator.stepper.IncompressibleNavierStokesStepper(
                grid=self.grid, boundary_conditions=bcs, collision_type=collision)
        init = None
        if rho0 is not None or u0 is not None:
            init = lambda grid, vset, pol, cb: self._init_f(rho0, u0)               # noqa: E731
        self.f0, self.f1, self.bc_mask, self.missing = self.stepper.prepare_fields(init)
        self.omega = 1.0 / tau_from_nu(nu)
        self.t = 0
        self.body_bc = body_bc

    def _field(self, a):
        """NumPy (c, *shape) -> backend array."""
        if self.backend == "jax":
            return jnp.asarray(a, jnp.float32)
        import warp as wp
        a = np.asarray(a, np.float32)
        return wp.array(a.reshape(a.shape + (1,)) if self.d == 2 else a, dtype=wp.float32)

    def _init_f(self, rho0, u0):
        rho = self._field(np.ones((1,) + self.shape) if rho0 is None else rho0[None])
        u = self._field(np.zeros((self.d,) + self.shape) if u0 is None else u0)
        eq = self.xlb.operator.equilibrium.QuadraticEquilibrium()
        if self.backend == "jax":
            return eq(rho, u)
        f = self.grid.create_field(cardinality=self.vs.q, dtype=self.pp.store_precision)
        return eq(rho, u, f)

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            self.f0, self.f1 = self.stepper(self.f0, self.f1, self.bc_mask, self.missing, self.omega, self.t)
            self.f0, self.f1 = self.f1, self.f0
            self.t += 1

    def fields(self):
        """(rho, u) from the populations in NumPy (moments done here: XLB's warp macroscopic op rejects half storage)."""
        f = (self.f0.numpy() if hasattr(self.f0, "numpy") else np.asarray(self.f0)).astype(np.float32)
        if self.d == 2 and f.ndim == 4:
            f = f[..., 0]
        c = np.asarray(self.vs._c, float)
        rho = f.sum(0)
        return rho, np.tensordot(c, f, axes=(1, 0)) / rho

    def force(self) -> np.ndarray:
        mt = self.xlb.operator.force.MomentumTransfer(self.body_bc)
        return np.asarray(mt(self.f0, self.f1, self.bc_mask, self.missing), float)


def _idx(mask: np.ndarray) -> list:
    """Boolean mask -> XLB index lists (d lists)."""
    return [a.tolist() for a in np.nonzero(mask)]


def _rim(shape, faces):
    """Union of the named faces of a box as a boolean mask. faces: subset of {"x0","x1","y0","y1","z0","z1"}."""
    m = np.zeros(shape, bool)
    for fc in faces:
        ax, hi = "xyz".index(fc[0]), fc[1] == "1"
        sl = [slice(None)] * len(shape)
        sl[ax] = -1 if hi else 0
        m[tuple(sl)] = True
    return m


# ---------------------------------------------------------------------------------------------------- reference cases
def poiseuille(backend="jax", n=32, nu=1 / 6, g=1e-5, steps=None, storage="fp32") -> dict:
    """Force-driven plane Poiseuille flow between bounce-back walls on the lattice rim, periodic along x.
    Fits u(y) = a (y - y0)(y1 - y) to the steady profile. Receipt quantities: a = g/(2 nu) (so g_eff/g = 2 nu a / g tests
    viscosity and forcing independently of where the wall is), the relative residual of the parabola fit, and the wall
    positions. XLB 0.3.1 puts the bounce-back wall at the rim nodes (y0 ~ 0, y1 ~ n-1), not half a cell outside them
    (measured: -0.10, n-0.9 at tau = 1); the fit makes the receipt independent of that convention. tau = 1 (nu = 1/6)
    keeps the bounce-back slip error smallest ."""
    from xlb.operator.boundary_condition import HalfwayBounceBackBC
    steps = steps or int(3 * n * n / nu)
    sess = _xlb_session(backend, 2, storage)
    wall = _rim((4, n), ["y0", "y1"])
    run = XlbRun(sess, backend, (4, n), [HalfwayBounceBackBC(indices=_idx(wall))], nu, force=[g, 0.0])
    run.step(steps)
    _, u = run.fields()
    prof = u[0].mean(0)
    y = np.arange(n, dtype=float)
    co = np.polyfit(y, prof, 2)
    y0, y1 = np.sort(np.roots(co).real)
    return dict(g_ratio=float(-2 * nu * co[0] / g), y0=float(y0), y1=float(y1),
                resid=float(np.linalg.norm(prof - np.polyval(co, y)) / np.linalg.norm(prof)), profile=prof)


# Ghia, Ghia & Shin (1982) J. Comput. Phys. 48, 387, Re = 100: Table I (u on the vertical centreline x = 0.5)
# and Table II (v on the horizontal centreline y = 0.5), 129 x 129 multigrid.
GHIA_U = np.array([[1.0000, 1.00000], [0.9766, 0.84123], [0.9688, 0.78871], [0.9609, 0.73722], [0.9531, 0.68717],
                   [0.8516, 0.23151], [0.7344, 0.00332], [0.6172, -0.13641], [0.5000, -0.20581], [0.4531, -0.21090],
                   [0.2813, -0.15662], [0.1719, -0.10150], [0.1016, -0.06434], [0.0703, -0.04775], [0.0625, -0.04192],
                   [0.0547, -0.03717], [0.0000, 0.00000]])
GHIA_V = np.array([[1.0000, 0.00000], [0.9688, -0.05906], [0.9609, -0.07391], [0.9531, -0.08864], [0.9453, -0.10313],
                   [0.9063, -0.16914], [0.8594, -0.22445], [0.8047, -0.24533], [0.5000, 0.05454], [0.2344, 0.17527],
                   [0.2266, 0.17507], [0.1563, 0.16077], [0.0938, 0.12317], [0.0781, 0.10890], [0.0703, 0.10091],
                   [0.0625, 0.09233], [0.0000, 0.00000]])


def cavity(backend="jax", n=96, re=100.0, u_lid=0.05, steps=None, storage="fp32") -> dict:
    """Lid-driven cavity vs Ghia et al. (1982). Walls and lid are on the lattice rim; XLB's bounce-back wall sits at the rim
    nodes, so the unit cavity maps to node coordinates i/(n-1). The lid is an equilibrium BC (first-order accurate but the
    only lid BC that runs on both XLB backends: its Regularized and ZouHe lids do nothing on warp 1.12). Returns the max
    |u - u_Ghia|, |v - v_Ghia| over the interior Ghia points, in units of the lid speed."""
    from xlb.operator.boundary_condition import HalfwayBounceBackBC, EquilibriumBC
    nu = u_lid * n / re
    steps = steps or int(40 * n / u_lid)
    sess = _xlb_session(backend, 2, storage)
    lid = _rim((n, n), ["y1"])
    lid[0, -1] = lid[-1, -1] = False                                        # corners belong to the side walls
    wall = _rim((n, n), ["x0", "x1", "y0"]) | (_rim((n, n), ["y1"]) & ~lid)
    run = XlbRun(sess, backend, (n, n), [HalfwayBounceBackBC(indices=_idx(wall)),
                                         EquilibriumBC(1.0, (u_lid, 0.0), indices=_idx(lid))], nu)
    run.step(steps)
    _, u = run.fields()
    s = np.arange(n) / (n - 1)
    ug = np.interp(GHIA_U[:, 0], s, u[0, n // 2 - 1:n // 2 + 1].mean(0)) / u_lid
    vg = np.interp(GHIA_V[:, 0], s, u[1, :, n // 2 - 1:n // 2 + 1].mean(1)) / u_lid
    inner = lambda t: (t[:, 0] > 0.02) & (t[:, 0] < 0.98)                    # the end points are the BC itself      # noqa: E731
    eu, ev = np.abs(ug - GHIA_U[:, 1])[inner(GHIA_U)], np.abs(vg - GHIA_V[:, 1])[inner(GHIA_V)]
    return dict(err_u=float(eu.max()), err_v=float(ev.max()), ug=ug, vg=vg)


def taylor_green(backend="jax", n=64, nu=0.02, u0=0.04, steps=None, storage="fp32") -> dict:
    """Decaying 2-D Taylor-Green vortex, periodic. Kinetic energy decays as exp(-4 nu k^2 t), k = 2 pi / n. Returns the
    fitted viscosity (from the energy ratio) relative to the analytic one. backend "native" runs the 3-D kernel on a thin slab."""
    k = 2 * math.pi / n
    steps = steps or int(0.5 / (2 * nu * k * k))
    x, y = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5, indexing="ij")
    ux, uy = -u0 * np.cos(k * x) * np.sin(k * y), u0 * np.sin(k * x) * np.cos(k * y)
    rho = 1 - 3 * u0 ** 2 / 4 * (np.cos(2 * k * x) + np.cos(2 * k * y))
    if backend == "native":
        tau0 = tau_from_nu(nu)
        u3 = np.stack([ux, uy, np.zeros_like(ux)])[..., None].repeat(4, -1).astype(np.float32)
        r3 = rho[..., None].repeat(4, -1).astype(np.float32)
        f = store(feq(jnp.asarray(r3), jnp.asarray(u3)), storage)
        f = periodic_run(f, tau0, steps, 0.0, "bgk", storage)
        _, uu = moments(f)
        e = float((np.asarray(uu[:2]) ** 2).sum() / 2) / 4                      # 4-cell-thick slab
    else:
        run = XlbRun(_xlb_session(backend, 2, storage), backend, (n, n), [], nu, rho0=rho, u0=np.stack([ux, uy]))
        run.step(steps)
        _, uu = run.fields()
        e = float((uu ** 2).sum() / 2)
    e0 = float(((ux ** 2 + uy ** 2).sum()) / 2)
    nu_fit = -math.log(e / e0) / (4 * k * k * steps)
    return dict(nu_fit=nu_fit, ratio=nu_fit / nu, energy_ratio=e / e0, steps=steps)


def morrison(re: float) -> float:
    """Sphere drag coefficient, Morrison (2013) 'An Improved Correlation for the Drag of a Sphere' eq. (1), Re up to 1e6."""
    return (24 / re + 2.6 * (re / 5) / (1 + (re / 5) ** 1.52) + 0.411 * (re / 263000) ** -7.94 / (1 + (re / 263000) ** -8)
            + re ** 0.8 / 461000)


def sphere(backend="jax", re=100.0, d=16, domain=(14, 7, 7), u_in=0.05, steps=None, cs=0.17, storage="fp32",
           progress: Callable[[int, float], None] | None = None, side: str = "eq", outlet_bc: str = "equilibrium") -> dict:
    """Flow past a voxel sphere of d cells: equilibrium inlet and freestream sides, extrapolation outflow, halfway bounce-back
    on the sphere, momentum-exchange drag, Smagorinsky LES (re >= 500). Cd averaged over the last 20 % of `steps`.
    outlet_bc "equilibrium" (default) runs identically on both XLB backends; "extrapolation" (XLB's ExtrapolationOutflowBC) is
    non-reflecting on jax but returns NaN on XLB 0.3.1 / warp 1.12 (CPU device), so it is not used for the shared tests.
    The lateral faces are freestream-velocity walls: the isolated-sphere Cd needs them far away (Cd is +35 % at 6 diameters
    across, see the slow runs), `side="open"` makes them extrapolation outflows (jax only; -23 % at 6 diameters)."""
    from xlb.operator.boundary_condition import EquilibriumBC, ExtrapolationOutflowBC, HalfwayBounceBackBC
    shape = tuple(int(round(a * d)) for a in domain)
    nu = u_in * d / re
    steps = steps or int(30 * d / u_in)
    sess = _xlb_session(backend, 3, storage)
    ctr = np.array([shape[0] * 0.3, shape[1] / 2, shape[2] / 2]) - 0.5
    g = np.stack(np.meshgrid(*[np.arange(s) for s in shape], indexing="ij"))
    solid = ((g - ctr.reshape(3, 1, 1, 1)) ** 2).sum(0) <= (d / 2) ** 2
    inlet = _rim(shape, ["x0"])
    outlet = _rim(shape, ["x1"]) & ~inlet
    lat = _rim(shape, ["y0", "y1", "z0", "z1"]) & ~inlet & ~outlet
    bc_body = HalfwayBounceBackBC(indices=_idx(solid))
    bcs = [bc_body, EquilibriumBC(1.0, (u_in, 0, 0), indices=_idx(inlet)),
           (ExtrapolationOutflowBC(indices=_idx(outlet)) if outlet_bc == "extrapolation" else EquilibriumBC(1.0, (u_in, 0, 0), indices=_idx(outlet)))]
    if side == "eq":                                                         # freestream velocity on the lateral faces
        bcs.append(EquilibriumBC(1.0, (u_in, 0, 0), indices=_idx(lat)))
    else:                                                                    # open lateral faces: one extrapolation BC per face
        left = lat.copy()
        for fc in ("y0", "y1", "z0", "z1"):
            m = _rim(shape, [fc]) & left
            left &= ~m
            bcs.append(ExtrapolationOutflowBC(indices=_idx(m)))
    u0 = np.zeros((3,) + shape)
    u0[0] = u_in
    u0[:, solid] = 0
    coll = "SmagorinskyLESBGK" if re >= 500 else "BGK"
    run = XlbRun(sess, backend, shape, bcs, nu, u0=u0, collision=coll, body_bc=bc_body)
    if coll != "BGK":                                                        # XLB's coefficient -> effective Cs (see module doc)
        run.stepper.collision.smagorinsky_coef = cs / XLB_CS_SCALE
    area = math.pi * d * d / 4
    fs, t0 = [], time.time()
    chunk = max(1, steps // 50)
    for _ in range(0, steps, chunk):
        run.step(chunk)
        fs.append(run.force()[0] / (0.5 * u_in ** 2 * area))
        if progress:
            progress(run.t, fs[-1])
    tail = np.array(fs[-max(3, len(fs) // 5):])
    ref = morrison(re)
    return dict(re=re, d=d, outlet=outlet_bc, side=side, cd=float(tail.mean()), cd_std=float(tail.std()), ref=ref, err=float(abs(tail.mean() / ref - 1)),
                shape=shape, steps=steps, seconds=time.time() - t0, history=[float(x) for x in fs])


# ---------------------------------------------------------------------------------------------------- measurements
def measure_jax_bytes_per_cell(n: int = 96, storage: str = "fp32") -> float:
    """Peak resident bytes per cell of one native step on an n^3 periodic box (CPU RSS growth), to check JAX_MEM_FACTOR."""
    import resource
    f = feq(jnp.ones((n, n, n)), jnp.zeros((3, n, n, n)))
    f.block_until_ready()
    base = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    periodic_run(f, 0.51, 2, 0.17, "reg", storage).block_until_ready()
    return (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 - base) / n ** 3 + 19 * 4


# ---------------------------------------------------------------------------------------------------- receipts
SLOW_DIR = pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "receipts"


def slow_path(name: str) -> pathlib.Path:
    return SLOW_DIR / f"lbm_{name}.json"


PHYSICS_FILES = ("lbm.py", "nest.py", "wallmodel.py")
NEST_RATE_LOADED = 1.4e6          # cell-updates/s the native nest delivered on homebase at load 20-30 (3 CPUs), measured 2026-10-29
NEST_RATE_BENCH = 7.5e6           # bench/throughput.json jax-lbm-d3q19-cpu, all 8 cores unloaded


def physics_sha() -> str:
    """Hash of the executable source of the modules a stored slow result depends on: the AST without docstrings, so editing
    a comment or a docstring does not stale a multi-hour result but changing a line of code does."""
    h = hashlib.sha1()
    for f in PHYSICS_FILES:
        tree = ast.parse((pathlib.Path(__file__).parent / f).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    node.body = node.body[1:] or [ast.Pass()]
        h.update(ast.dump(tree).encode())
    return h.hexdigest()[:16]


def eta_text(updates: float) -> str:
    """Run time of `updates` cell-updates: at the loaded box's measured native rate and at the unloaded 8-core benchmark rate."""
    f = lambda r: f"{updates / r / 3600:.1f} h" if updates / r > 1800 else f"{updates / r / 60:.0f} min"      # noqa: E731
    return (f"{updates:.2g} cell-updates: ~{f(NEST_RATE_LOADED)} at the loaded-box rate {NEST_RATE_LOADED:.2g}/s, "
            f"~{f(NEST_RATE_BENCH)} at the 8-core benchmark rate")


def result_row(group: str, claim: str, rec: dict | None, value_key: str, ref_key: str, tol: float, command: str, eta: str, source: str) -> None:
    """A required pass/fail row from a stored slow result. Stored and within `tol` of the reference: pass. Stored and outside: fail with
    the measured error in the row. Not stored, or stored by different code (its `code_sha` differs from physics_sha()): FAIL,
    with the command and its run time in the note. Never a context row."""
    nan = float("nan")
    if rec is None:
        bracket(group, f"{claim} -- NOT STORED", nan, 0.0, 0.0, "", f"run: {command}   [{eta}]")
        return
    ref = rec[ref_key]
    if rec.get("code_sha") not in (None, physics_sha()):
        bracket(group, f"{claim} -- STORED BY DIFFERENT CODE", nan, ref * (1 - tol), ref * (1 + tol), "",
                f"stored {rec['code_sha']} != current {physics_sha()}; rerun: {command}   [{eta}]")
        return
    receipt(group, claim, rec[value_key], ref, tol, "", source)


SPHERE_RUNS = (("100", 100.0), ("1000", 1000.0), ("1e4", 1e4))


def receipts(backend: str = "jax") -> list:
    """Poiseuille, cavity, Taylor-Green and the sphere drag at Re = 1e2, 1e3, 1e4 on `backend`, all pass/fail. The sphere rows read the
    stored slow runs (`python -m cafe.pm.stage3.lbm slow RE D NX NY NZ`, $CAFE_DATA/receipts); XLB 0.3.1 has only the staircase
    halfway bounce-back, which overpredicts a sphere's drag ~1/d (+30 % at d = 8): those rows FAIL with the measured error until a run
    at a d that reaches 10 % is stored. The native kernel's curved-wall rows are in nest.receipts."""
    g = f"LBM {backend}"
    p = poiseuille(backend)
    receipt(g, "Poiseuille: curvature of the steady profile g_eff/g", p["g_ratio"], 1.0, 0.01, "", "u = g/(2 nu) (y-y0)(y1-y)")
    bracket(g, "Poiseuille: relative residual of the parabola fit", p["resid"], 0, 0.005, "", "analytic parabola")
    c = cavity(backend)
    bracket(g, "Cavity Re=100 max |u-u_Ghia| on the vertical centreline / U_lid", c["err_u"], 0, 0.04, "", "Ghia et al. 1982 Table I")
    bracket(g, "Cavity Re=100 max |v-v_Ghia| on the horizontal centreline / U_lid", c["err_v"], 0, 0.04, "", "Ghia et al. 1982 Table II")
    t = taylor_green(backend)
    receipt(g, "Taylor-Green decay: fitted viscosity / analytic", t["ratio"], 1.0, 0.03, "", "exp(-4 nu k^2 t)")
    for tag, re in SPHERE_RUNS:
        f = slow_path(f"sphere_{tag}")
        rec = json.loads(f.read_text()) if f.exists() else None
        d = {"100": 8, "1000": 10, "1e4": 12}[tag]
        updates = float(np.prod([a * d for a in (12, 6, 6)])) * 30 * d / U_LAT_SPHERE
        result_row(g, f"Sphere Cd at Re={re:g}, XLB halfway bounce-back (staircase), d={rec.get('d', '?') if rec else d}", rec, "cd", "ref", 0.10,
                   f"python -m cafe.pm.stage3.lbm slow {tag} {d} 12 6 6", eta_text(updates),
                   f"Morrison 2013; domain {rec['shape'] if rec else '?'}; staircase surface overpredicts ~1/d, see docstring")
    return [r for r in cr.OUT if r["group"] == g]


def main(argv: list) -> int:
    """python -m cafe.pm.stage3.lbm [receipts|slow RE [D [NX NY NZ in diameters]]|memory] [--backend jax|warp] [--fp32-storage]"""
    fp32 = "--fp32-storage" in argv
    argv = [a for a in argv if a != "--fp32-storage"]
    backend = argv[argv.index("--backend") + 1] if "--backend" in argv else pick_backend()
    st = storage_for("auto", fp32)
    cmd = argv[0] if argv else "receipts"
    if cmd == "slow":
        sha0 = physics_sha()
        re = float(argv[1])
        d = int(argv[2]) if len(argv) > 2 else 16
        dom = tuple(float(a) for a in argv[3:6]) if len(argv) >= 6 else (14, 12, 12)
        r = sphere(backend, re, d=d, domain=dom, storage=st, progress=lambda t, c: print(f"t={t} cd={c:.4f}", flush=True))
        r.pop("history", None)
        r["code_sha"] = sha0
        SLOW_DIR.mkdir(parents=True, exist_ok=True)
        slow_path(f"sphere_{argv[1]}").write_text(json.dumps(r, default=float))
        print(json.dumps(r, default=float))
        return 0
    if cmd == "memory":
        print(json.dumps(les_resolution(1.5, 1.5, 1.05e-6, storage=st), indent=1, default=float))
        print("jax bytes/cell:", measure_jax_bytes_per_cell(storage=st))
        return 0
    receipts(backend)
    return int(any(not r["ok"] for r in cr.OUT if r["ok"] is not None))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
