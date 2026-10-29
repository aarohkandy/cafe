"""Equilibrium log-law wall stress for the native LBM kernel (no wall-resolved LES: BRIEF 2.6).

Law of the wall, u+ = ln(y+)/kappa + B with kappa = 0.41, B = 5.2 (constants of BRIEF 2.6; Pope 2000, Turbulent Flows, ch. 7),
evaluated at the matching point 2.5 cells off the wall (the centre of the third cell). Below y+ = 11.06, where the log law
meets u+ = y+, the viscous law u_tau = sqrt(nu u / y) is used.

How the stress enters the LBM (a wall-stress boundary condition in the family of Malaspinas & Sagaut 2014, J. Comput. Phys. 275,
25-40, the reference for imposing a modelled wall shear in an LBM; their regularized-collision algorithm itself is not reproduced):
  * the wall exchanges no tangential momentum. On axis-aligned flat faces the bounce-back is replaced by specular reflection
    (lbm.specular: normal component reversed, tangential kept, exact free slip). On curved/voxel-edge cells a bounce-back whose wall
    velocity is the cell's own tangential velocity after the stress kick does the same approximately;
  * the log-law stress rho u_tau^2 is removed from the wall cell's momentum along the relative tangential flow (and added to the
    body's force), times the face area 1/(|n_x|+|n_y|+|n_z|) of the voxel wall;
  * between the wall and the matching point (or `rans_layer` cells) the eddy viscosity is nu_t = kappa u_tau y, the mixing length for
    which the log law is the equilibrium solution (near_wall_tau). Smagorinsky's C_s dx = 0.17 cells is 6x too short at y = 1 cell and
    15x at 2.5, so without this the stress cannot be carried from the outer flow to the wall (the channel receipt fails by >50 %).
    The usual WMLES limiter l = min(C_s dx, kappa y) never exceeds C_s dx for y >= 0.5 cells and would change nothing here.
Rejected before this (measured, flat plate, lattice units): a no-slip wall with an effective viscosity chosen to match the stress
delivered 1.3-2.6x the log-law stress (bounce-back transmits c_s^2 u_1 per face regardless of the viscosity, lbm.bounce_back); a slip
velocity chosen to leave exactly u_tau^2 (a difference of two large numbers, measured as noise); a free-slip moving wall at u_1 with
no near-wall eddy viscosity (C_f 70 % under ITTC-57 at CI size: the bounce-back returned ~60 % of the stress, and the second cell
dipped to 0.46 U).
Matching point and normal come from a smoothed solid indicator, so any voxelised body works; the wall speed is subtracted (moving
vehicle).
Receipts (receipts()): a periodic channel driven by a body force g (thin in x and z): wall stress = g h within 1 %, bulk C_f within
10 % of Dean (1978), matching point in the log layer, bounce-back tangential exchange < 1 % of the shear. ITTC-57 is a turbulent
correlation; the flat plate is compared with it only at Re_L >= 1e6 (stored slow run), where it applies.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
from typing import Any, NamedTuple

import numpy as np
from scipy import ndimage

import jax.numpy as jnp

from cafe.pm.stage3 import lbm

KAPPA, B_LOG = 0.41, 5.2
Y_MATCH = 2.5                 # cells: centre of the third cell from the wall surface
YPLUS_LAM = 11.06             # y+ where ln(y+)/kappa + B = y+
NU_MAX = 0.5                  # tau <= 1.5: beyond that BGK is not trusted
PLATE_CI: dict[str, Any] = dict(length=96, nu_lat=4e-5, half=36, span=4, nose=10, thick=1, steps=12000)      # ~1 min on 4 CPUs
YPLUS_OK = (30.0, 300.0)      # window in which the log law holds at the matching point (BRIEF 5.5)


class WallSet(NamedTuple):
    """Static description of the wall cells of one body (padded to a common length so bodies can be stacked and vmapped)."""
    cell: Any       # (3, N) int  wall-adjacent fluid cells
    sten: Any       # (3, 8, N) int  trilinear stencil around the matching point
    wgt: Any        # (8, N) float
    nrm: Any       # (3, N) float  unit normal pointing into the fluid
    phi: Any        # (N,) float  distance of the cell centre to the wall surface, cells
    valid: Any      # (N,) bool
    near: Any       # (3, M) int  fluid cells within the near-wall (RANS) layer of the wall
    near_phi: Any   # (M,) float  their distance to the wall surface, cells
    near_src: Any   # (M,) int  index of the nearest wall cell (its u_tau is used)
    near_damp: Any  # (M,) float  (1 - y/layer) outside the default layer, else 1; 0 for padding


def utau_loglaw(u, y, nu, kappa=KAPPA, B=B_LOG):
    """Friction velocity from the speed u at distance y: Newton on u = u_tau (ln(y u_tau / nu)/kappa + B), viscous law below
    y+ = 11.06. Works on arrays; all in consistent (lattice or SI) units."""
    ul = jnp.sqrt(nu * jnp.maximum(u, 0.0) / y)                              # viscous-sublayer value, also the start point
    ut = jnp.maximum(ul, 1e-7)
    for _ in range(10):
        a = jnp.log(y * ut / nu) / kappa + B
        ut = jnp.maximum(ut - (ut * a - u) / (a + 1 / kappa), 1e-7)
    return jnp.where(y * ut / nu < YPLUS_LAM, ul, ut)


def wall_set(solid: np.ndarray, link: np.ndarray, pad_to: int | None = None, y_match: float = Y_MATCH,
             rans_layer: float | None = None) -> WallSet:
    """Wall cells, normals, distances and matching-point stencils for a boolean solid mask (cells).
    `link` is lbm.links(solid): a wall cell has a solid neighbour on any of the 18 lattice links."""
    solid = np.asarray(solid, bool)
    wc = np.argwhere(np.asarray(link).any(0)).T                              # (3, N)
    dist = ndimage.distance_transform_edt(~solid) - 0.5                      # cells to the halfway-bounce-back surface
    g = np.stack(np.gradient(ndimage.gaussian_filter(solid.astype(float), 1.5)))
    nrm = -g[:, wc[0], wc[1], wc[2]]
    nrm /= np.maximum(np.linalg.norm(nrm, axis=0), 1e-12)
    phi = np.maximum(dist[wc[0], wc[1], wc[2]], 0.5)
    pos = wc + (y_match - phi) * nrm                                         # matching points, cell-index coordinates
    lo = np.floor(pos).astype(int)
    fr = pos - lo
    st_l, wg_l = [], []
    shape = np.array(solid.shape).reshape(3, 1)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                off = np.array([dx, dy, dz]).reshape(3, 1)
                ix = np.clip(lo + off, 0, shape - 1)
                w = np.prod(np.where(off == 1, fr, 1 - fr), axis=0) * ~solid[ix[0], ix[1], ix[2]]
                st_l.append(ix)
                wg_l.append(w)
    sten, wgt = np.stack(st_l, 1), np.stack(wg_l)
    wsum = wgt.sum(0)
    bad = wsum < 1e-6                                                        # whole stencil in solid: fall back to the wall cell
    wgt = np.where(bad, 0.0, wgt / np.maximum(wsum, 1e-12))
    sten[:, :, bad] = wc[:, None, bad]
    wgt[0, bad] = 1.0
    n = wc.shape[1]
    ly = y_match if rans_layer is None else rans_layer
    nm = np.argwhere((~solid) & (dist > 0) & (dist <= ly + 1e-6)).T
    nphi = np.maximum(dist[nm[0], nm[1], nm[2]], 0.5)
    if nm.shape[1] and n:
        from scipy.spatial import cKDTree
        src = cKDTree(wc.T).query(nm.T)[1]
    else:
        src = np.zeros(nm.shape[1], int)
    damp = np.ones(nm.shape[1]) if rans_layer is None else np.clip(1 - nphi / rans_layer, 0.0, 1.0)
    ws = WallSet(wc, sten, wgt, nrm, phi, np.ones(n, bool), nm, nphi, src, damp)
    return pad_wall_set(ws, pad_to) if pad_to else ws


def pad_wall_set(ws: WallSet, n: int, m: int | None = None) -> WallSet:
    """Pad with inert entries (cell 0, weight 0, valid False) so differently sized bodies stack. `m` pads the near-wall list."""
    k = n - ws.cell.shape[1]
    if k < 0:
        raise ValueError(f"wall set has {ws.cell.shape[1]} cells, pad_to={n}")
    m = ws.near.shape[1] if m is None else m
    km = m - ws.near.shape[1]
    if km < 0:
        raise ValueError(f"wall set has {ws.near.shape[1]} near-wall cells, pad near to {m}")
    z = lambda a, k_, v=0: np.concatenate([a, np.full(a.shape[:-1] + (k_,), v, a.dtype)], -1)       # noqa: E731
    return WallSet(z(ws.cell, k), z(ws.sten, k), z(ws.wgt, k), z(ws.nrm, k), z(ws.phi, k, 1.0), z(ws.valid, k, False),
                   z(ws.near, km), z(ws.near_phi, km, 1.0), z(ws.near_src, km), z(ws.near_damp, km, 0.0))


def wall_state(u, ws: WallSet, nu_lat, u_wall=(0.0, 0.0, 0.0), y_match: float = Y_MATCH):
    """Per wall cell: friction velocity, y+ at the matching point, the wall velocity for the bounce-back, and the wall shear.
    The stress is applied as a force, not through the collision: bounce-back with the wall velocity set to the cell's own
    tangential velocity (u_w = u_body + u_1t) exchanges no tangential momentum -- a free-slip wall -- and the log-law stress
    rho u_tau^2 is added to the wall cell's momentum along -u_1t (and to the body's force along +u_1t) per unit face area.
    (A no-slip bounce-back wall delivers c_s^2 u_1 per face, ~10^3 times u_tau^2 at these speeds; a slip velocity chosen to
    leave exactly u_tau^2 is a cancellation of two large numbers and measured as noise, so the stress is imposed directly:
    the wall-stress boundary condition of the wall-modelled LES literature, here on a voxel wall with the lattice-link
    face area 1/(|n_x|+|n_y|+|n_z|) per wall cell.) Returns lattice units."""
    uw = jnp.asarray(u_wall, jnp.float32).reshape(3, 1)
    cell = tuple(ws.cell)
    um = (u[:, ws.sten[0], ws.sten[1], ws.sten[2]] * ws.wgt[None]).sum(1) - uw        # relative velocity at the matching point
    n = jnp.asarray(ws.nrm, jnp.float32)
    um_t = um - (um * n).sum(0) * n
    u1 = u[(slice(None),) + cell] - uw
    u1_t = u1 - (u1 * n).sum(0) * n
    sp = jnp.sqrt((um_t ** 2).sum(0))
    ut = utau_loglaw(sp, y_match, nu_lat)
    s1 = jnp.sqrt((u1_t ** 2).sum(0))
    area = 1.0 / jnp.maximum(jnp.abs(n).sum(0), 1e-6)                                      # padded entries have n = 0
    fw = ut ** 2 * area * u1_t / jnp.maximum(s1, 1e-9) * jnp.asarray(ws.valid)          # force on the body, along the relative flow
    # the wall velocity is the cell's tangential velocity AFTER the stress kick (-fw per unit volume): with the pre-kick velocity
    # the bounce-back would hand back ~60 % of the stress (measured on the flat plate: F_BB = -0.6 F_shear)
    return dict(utau=ut, yplus=y_match * ut / nu_lat, u_slip=uw + u1_t - fw, u1=u1_t, um=um_t, fw=fw)


def near_wall_tau(tau, ws: WallSet, st, nu_lat):
    """Mixing-length eddy viscosity nu_t = kappa u_tau y (times the damping of the near-wall layer) as a relaxation time, never
    below what Smagorinsky gave. Smagorinsky's length C_s*dx = 0.17 cells is 6x too short at y = 1 cell and 6x at 2.5 (the log law
    needs l = kappa y): the stress cannot be carried from the outer flow to the wall without it. NB the usual WMLES limiter
    l = min(C_s dx, kappa y) never exceeds C_s dx for y >= 0.5 cells, so it would change nothing; the log-consistent length is
    kappa y."""
    c = tuple(ws.near)
    nut = KAPPA * st["utau"][ws.near_src] * jnp.asarray(ws.near_phi, jnp.float32) * jnp.asarray(ws.near_damp, jnp.float32)
    new = jnp.maximum(tau[c], lbm.tau_from_nu(nu_lat + nut))
    return tau.at[c].set(jnp.where(jnp.asarray(ws.near_damp) > 0, new, tau[c]))


def wall_force(f_post, ws: WallSet, st, count=None):
    """Add the wall shear to the post-collision populations of the wall cells (momentum -fw per step, first-order forcing
    3 w_q c_q . dF) and return (f, shear force on the body). `count` (bool per wall cell) limits the reported force to the
    cells whose force is wanted (a strip of a plate); the fluid always receives the full stress."""
    cell = (slice(None),) + tuple(ws.cell)
    df = 3 * lbm.Wj[:, None] * jnp.tensordot(lbm.Cj, -st["fw"], axes=(1, 0))
    fw = st["fw"] if count is None else st["fw"] * jnp.asarray(count)[None]
    return f_post.at[cell].add(df), fw.sum(1)


def wall_field(u_body, ws: WallSet, st, shape) -> "jnp.ndarray":
    """Dense (3, nx, ny, nz) wall-velocity field for lbm.bounce_back: the body velocity everywhere, the free-slip velocity at the
    valid wall cells."""
    base = jnp.broadcast_to(jnp.asarray(u_body, jnp.float32).reshape(3, 1, 1, 1), (3,) + tuple(shape))
    cell = (slice(None),) + tuple(ws.cell)
    return base.at[cell].set(jnp.where(jnp.asarray(ws.valid)[None], st["u_slip"], base[cell]))


def yplus_fraction(yplus, valid, lo: float = YPLUS_OK[0], hi: float = YPLUS_OK[1]) -> float:
    """Share of valid wall cells whose matching point is inside the log layer."""
    yp, v = np.asarray(yplus), np.asarray(valid)
    return float(((yp >= lo) & (yp <= hi) & v).sum() / max(v.sum(), 1))


def ittc57(re_: float) -> float:
    """ITTC-1957 model-ship correlation line, C_f = 0.075 / (log10 Re - 2)^2."""
    return 0.075 / (math.log10(re_) - 2) ** 2


def plate_mask(shape, x0: int, length: int, yc: float, half: float, nose: int) -> np.ndarray:
    """Streamlined plate: semi-ellipse nose and tail of `nose` cells, half-thickness `half` cells, full span. A blunt voxel edge
    separates at these Reynolds numbers and the bubble, not the boundary layer, then sets the wall-model input."""
    x, y = np.meshgrid(np.arange(shape[0]) + 0.5, np.arange(shape[1]) + 0.5, indexing="ij")
    dx = np.maximum(np.maximum(x0 + nose - x, x - (x0 + length - nose)), 0.0) / nose
    h = half * np.sqrt(np.clip(1 - dx ** 2, 0.0, 1.0))
    m2 = (np.abs(y - yc) <= h) & (x >= x0) & (x <= x0 + length)
    return np.repeat(m2[:, :, None], shape[2], axis=2)


def ittc57_mean(re_a: float, re_b: float) -> float:
    """Mean C_f of the strip between Re_x = re_a and re_b of a plate whose boundary layer starts at the leading edge:
    (re_b C(re_b) - re_a C(re_a)) / (re_b - re_a), C the ITTC-57 line (total friction up to x)."""
    return (re_b * ittc57(re_b) - re_a * ittc57(re_a)) / (re_b - re_a)


def inflow_turbulence(tu: float, modes: int = 16, seed: int = 0):
    """Uniform unit stream plus frozen random Fourier modes of intensity `tu` (wavelengths 6-24 cells, convected at U = 1 lattice
    unit scaled by the caller): stands in for the synthetic turbulence box of BRIEF 2.2 so the wall-modelled boundary layer has
    resolved turbulent transport. Lattice-coordinate function u(x, y, z, t) in units of the stream speed; dx = 1, U_ref = 1."""
    import jax.numpy as jnp
    rng = np.random.default_rng(seed)
    k = 2 * math.pi / rng.uniform(6, 24, (modes, 3)) * rng.choice([-1, 1], (modes, 3))
    ph = rng.uniform(0, 2 * math.pi, modes)
    amp = rng.normal(size=(modes, 3))
    amp = amp * tu / np.sqrt((amp ** 2).sum(0).mean() / 2)                  # rms of each component = tu

    def env(x, y, z, t):
        arg = k[:, 0, None] * (x.ravel()[None] - t) + k[:, 1, None] * y.ravel()[None] + k[:, 2, None] * z.ravel()[None] + ph[:, None]
        up = jnp.einsum("md,mn->dn", jnp.asarray(amp, jnp.float32), jnp.cos(arg)).reshape((3,) + x.shape)
        return up + jnp.stack([jnp.ones_like(x), jnp.zeros_like(x), jnp.zeros_like(x)])
    return env


def flat_plate(length: int = 192, nu_lat: float = 4e-5, half: int = 40, span: int = 8, steps: int = 20000,
               wall_model: bool = True, nose: int = 16, thick: int = 3, tu: float = 0.0) -> dict:
    """Two-sided streamlined flat plate (2 `thick` cells thick) in a uniform stream, wall-modelled on both faces, periodic
    in the span. Friction is the momentum exchange on the links of the flat part (nose and tail excluded), averaged over the
    last 40 % of the run, C_f = F / (rho U^2 L_m W) over both sides, compared with the ITTC-57 line averaged over the same
    strip (ittc57_mean) at Re_x = U x / nu from the leading edge. Lattice units: dx = 1, u_lat = lbm.U_LAT."""
    import jax.numpy as jnp
    from cafe.pm.stage3 import nest
    ul = lbm.U_LAT
    pre, post = 24, 40
    shape = (pre + length + post, 2 * half + 2 * thick + 2, span)
    spec = nest.NestSpec(shape, 1.0, 1.0, nu_lat / ul, u_lat=ul, periodic=(False, False, True), sponge=4,
                         wall_model=wall_model)
    solid = plate_mask(shape, pre, length, shape[1] / 2, thick, nose)
    x1, x2 = pre + nose + 4, pre + length - nose
    region = np.zeros(shape, bool)
    region[x1:x2, :, :] = True
    geom = nest.make_geom(solid, np.array(shape) // 2, periodic=spec.periodic, force_region=region)
    env = inflow_turbulence(tu)
    p0 = np.array(shape) // 2 + 0.5
    params = (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32))
    _, ser = nest.simulate(spec, env, geom, p0, params, steps)
    k = int(steps * 0.6)
    fx = ser["F"][k:, 0].mean()
    cf = float(fx / (ul ** 2 * (x2 - x1) * span))                            # F / (rho U^2 L W), rho = 1, both sides
    ra, rb = ul * (x1 - pre) / nu_lat, ul * (x2 - pre) / nu_lat
    ref = ittc57_mean(ra, rb)
    return dict(cf=cf, re=rb, re_a=ra, ittc=ref, err=abs(cf / ref - 1), yfrac=float(ser["yfrac"][k:].mean()),
                utau=float(ser["utau"][k:].mean()), mach_max=float(ser["umax"][k:].max() * math.sqrt(3)), force=ser["F"][:, 0])


def dean_cf(re_b: float) -> float:
    """Dean (1978) channel friction: C_f = tau_w / (rho U_b^2 / 2) = 0.073 Re_b^-0.25, Re_b = U_b 2h / nu (J. Fluids Eng. 100, 215)."""
    return 0.073 * re_b ** -0.25


def channel(h: int = 12, re_tau: float = 1000.0, u_tau: float = 0.003, steps: int = 150000, span: int = 4, rans: bool = True,
            wall_model: bool = True, chunk: int = 5000) -> dict:
    """Plane channel of half-height h cells between two walls, driven by a uniform body force g = u_tau^2 / h, periodic in x and z
    (span cells each: thin = effectively 1-D, `span` ~ 4 h would resolve turbulence). Walls: specular reflection + log-law stress
    at the 3rd cell. rans=True gives the whole channel the mixing-length eddy viscosity kappa u_tau y (1 - y/h) (a 1-D channel has no
    resolved turbulence to carry the stress); rans=False leaves Smagorinsky beyond the matching height.
    Receipts: the steady wall stress equals g h (momentum balance), bulk C_f vs Dean 1978, y+ and y/h of the matching point,
    and the bounce-back tangential exchange as a fraction of the wall shear. Lattice units, dx = 1, nu_lat = h u_tau / Re_tau."""
    import jax.numpy as jnp
    from cafe.pm.stage3 import nest
    ul = lbm.U_LAT
    nu_lat = h * u_tau / re_tau
    g = u_tau ** 2 / h
    ny = 2 * h + 4
    shape = (span, ny, span)
    spec = nest.NestSpec(shape, 1.0, 1.0, nu_lat / ul, u_lat=ul, periodic=(True, True, True), body_force=(g, 0.0, 0.0),
                         rans_layer=float(h) if rans else None, wall_model=wall_model)
    solid = np.zeros(shape, bool)
    solid[:, :2], solid[:, -2:] = True, True
    geom = nest.make_geom(solid, np.array(shape) // 2, periodic=spec.periodic, rans_layer=spec.rans_layer)

    def env(x, y, z, t):                                                      # start from the log profile: converges in O(10^4) steps
        phi = jnp.clip(jnp.minimum(y - 2.0, ny - 2.0 - y), 0.5, h)
        prof = u_tau * (jnp.log(jnp.maximum(phi * u_tau / nu_lat, 1.0)) / wm_kappa() + B_LOG)
        return jnp.stack([prof / ul, jnp.zeros_like(x), jnp.zeros_like(x)])
    p0 = np.array(shape) // 2 + 0.5
    params = (jnp.asarray(p0, jnp.float32), jnp.zeros(3, jnp.float32))
    state, ser = nest.simulate(spec, env, geom, p0, params, steps, chunk=chunk)
    _, u = lbm.moments(state.f)
    ux = np.asarray(u[0])[:, 2:ny - 2, :]
    ub = float(ux.mean())
    k = int(steps * 0.7)
    area = 2.0 * span * span
    tau_w = float(ser["Fw"][k:, 0].mean() / area)
    tau_bb = float((ser["F"][k:, 0] - ser["Fw"][k:, 0]).mean() / area)
    re_b = ub * 2 * h / nu_lat
    cf = tau_w / (0.5 * ub ** 2)
    ut = float(ser["utau"][k:].mean())
    return dict(tau_w=tau_w, tau_target=g * h, balance_err=abs(tau_w / (g * h) - 1), ub=ub, re_b=re_b, cf=cf, cf_dean=dean_cf(re_b),
                err=abs(cf / dean_cf(re_b) - 1), utau_model=ut, yplus_m=Y_MATCH * ut / nu_lat, ym_over_h=Y_MATCH / h,
                bb_tangential_frac=abs(tau_bb) / max(abs(tau_w), 1e-30), mach_max=float(ser["umax"][k:].max() * math.sqrt(3)),
                profile=ux.mean((0, 2)))


def wm_kappa() -> float:
    return KAPPA


PLATE_SLOW: dict[str, Any] = dict(length=384, nu_lat=1.5e-5, half=48, span=8, nose=16, thick=1, steps=30000, tu=0.03)
SLOW_DIR = pathlib.Path(os.environ.get("CAFE_DATA", "/data")) / "receipts"
PLATE_TOL = 0.20
CHANNEL_CI: dict[str, Any] = dict(h=12, re_tau=1000.0, u_tau=0.0026, steps=150000, span=4)      # ~15 s


def slow_path() -> pathlib.Path:
    return SLOW_DIR / "wm_flat_plate.json"


def channel_path() -> pathlib.Path:
    return SLOW_DIR / "wm_channel.json"


def stored_wall_error() -> float | None:
    """Smallest relative error of the stored wall-model receipts (flat plate vs ITTC-57, channel vs Dean), None when none is stored.
    windows.stage3_checks fails every window until this is within PLATE_TOL."""
    errs = []
    for f in (slow_path(), channel_path()):
        if f.exists():
            errs.append(float(json.loads(f.read_text())["err"]))
    return min(errs) if errs else None


def receipts(plate: dict | None = None, chan: dict | None = None) -> list:
    """Wall-model receipts. Channel (CI size, ~15 s): wall stress equals g h within 1 %, bulk C_f vs Dean 1978 within 10 %, the
    matching point in the log layer (y+ 30-300, y/h < 0.3), bounce-back tangential exchange < 1 % of the wall shear. Flat plate vs
    ITTC-57 from `plate`, else the stored slow run (Re_L >= 1e6), else a context row. Log-law identity."""
    import cafe.receipts as cr
    from cafe.receipts import bracket, context, receipt
    g = "LBM wall model"
    yp, ut, nu = 100.0, 2e-3, 2e-5
    y = yp * nu / ut
    u = ut * (math.log(yp) / KAPPA + B_LOG)
    receipt(g, "Log law inverted for u_tau (kappa 0.41, B 5.2) at y+ = 100", float(utau_loglaw(jnp.float32(u), y, nu)), ut, 0.005, "m/s",
            "u+ = ln(y+)/kappa + B, Pope 2000 ch. 7")
    c = chan or channel(**CHANNEL_CI)
    receipt(g, f"Channel (Re_tau {CHANNEL_CI['re_tau']:g}): wall stress / (g h)", c["tau_w"], c["tau_target"], 0.01, "", "momentum balance, steady state")
    receipt(g, f"Channel: bulk C_f at Re_b = {c['re_b']:.3g} vs Dean", c["cf"], c["cf_dean"], 0.10, "", "Dean 1978: 0.073 Re_b^-0.25")
    bracket(g, "Channel: matching-point y+", c["yplus_m"], YPLUS_OK[0], YPLUS_OK[1], "", "BRIEF 5.5")
    bracket(g, "Channel: matching height y/h", c["ym_over_h"], 0.0, 0.3, "", "log layer: y/h < ~0.3 (Pope 2000, ch. 7)")
    bracket(g, "Channel: bounce-back tangential exchange / wall shear", c["bb_tangential_frac"], 0.0, 0.01, "", "specular reflection exchanges none")
    f = slow_path()
    if plate is None and f.exists():
        plate = json.loads(f.read_text())
    if plate:
        receipt(g, f"Flat plate C_f at Re_L = {plate['re']:.3g}, wall-modelled (stored slow run)", plate["cf"], plate["ittc"], PLATE_TOL, "",
                "ITTC-57: 0.075/(log10 Re - 2)^2, averaged over the same strip")
        bracket(g, "... share of wall cells with y+ at the matching point in 30-300", plate["yfrac"], 0.9, 1.0, "", "BRIEF 5.5 stage3 check")
    else:   # ITTC-57 is a turbulent correlation: a CI-size plate (Re_L ~ 1e5, laminar nu_lat) is ill-posed, so only the slow run counts
        context(g, "Flat plate C_f vs ITTC-57 at Re_L >= 1e6: slow run not stored", 0.0, 0.0, "", "python -m cafe.pm.stage3.wallmodel slow")
    return [r for r in cr.OUT if r["group"] == g]


def main(argv: list) -> int:
    """python -m cafe.pm.stage3.wallmodel [slow|channel|receipts]"""
    if argv[:1] == ["channel"]:
        r = channel(**CHANNEL_CI)
        r.pop("profile")
        SLOW_DIR.mkdir(parents=True, exist_ok=True)
        channel_path().write_text(json.dumps(dict(r, params=CHANNEL_CI), default=float))
        print(json.dumps(r, default=float))
        return 0
    if argv[:1] == ["slow"]:
        r = flat_plate(**PLATE_SLOW)
        r.pop("force")
        SLOW_DIR.mkdir(parents=True, exist_ok=True)
        slow_path().write_text(json.dumps(dict(r, params=PLATE_SLOW), default=float))
        print(json.dumps(r, default=float))
        return 0
    import cafe.receipts as cr
    receipts()
    return int(any(not r["ok"] for r in cr.OUT if r["ok"] is not None))


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main(sys.argv[1:]))
