"""One environment per Monte-Carlo member: the gridded fields with that member's forcing errors applied.

Member m's draws come from the Stage-1 Latin hypercube (`stats.sampling.lhs`), keyed by member only, never by
vehicle: every vehicle in member m flies through the same perturbed wind, current and waves (common random numbers),
so inter-vehicle range checks are consistent.

- Wind: speed + wind_speed_bias[m] (floored at 0), direction rotated by wind_direction_bias[m].
- Current: speed x scale, rotated by a direction bias. Half of each prior's variance is member-wide (the LHS draw,
  so Sobol indices see it); half is a smooth random field with the configured correlation length (100 km), built
  from random Fourier features (Rahimi & Recht 2007) with a Gaussian covariance, seeded per member. The total
  1-sigma is the prior's.
- Ocean SDE (`sde=dict(t0, t1, dt)`, mission switch ocean_sde): the unresolved eddies as a Lagrangian stochastic perturbation,
  the Ito SDE dx = u dt + dK/dx dt + sqrt(2K) dW of `subgrid.ocean_sde_step` (Euler-Maruyama, OceanParcels form), K = Okubo's
  at the HYCOM cell size (`subgrid.sde_diffusivity`). A vehicle moves by current * dt each step, so the layer adds the velocity
  whose displacement over one vehicle step IS the Euler-Maruyama increment: (dK/dx + sqrt(2K/dt) xi) with xi the member's
  Brownian increment for that step. Each member owns one stream (`member_rng(seed, m, "ocean_sde")`, keyed by member only, so
  every vehicle in a member sees the same increments, and a member has the same ones in any batch); the increments are drawn
  once for the whole window and read by step number round((t - t0) / dt), so the layer holds no state a vehicle could
  advance out of order and repeated calls at one time give one answer. The vehicle's own step must be `dt`.
- Waves: Hs x hs_scale[m], Tp + tp_bias[m] (floored at 1 s). Stokes drift scales with Hs^2 (it is quadratic in amplitude).
Everything else (density, sound speed, depth, SST, air) passes through unchanged.

Arrays passed to the methods must have a leading member axis of length M (or broadcast to it).
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .. import Tagged
from ..stats.sampling import member_rng
from . import subgrid
from .protocol import Environment

NFEAT = 32
R_EARTH = 6.371e6


def _rot(v: Any, deg: Any) -> Any:
    r = np.radians(deg)[..., None]
    c, s = np.cos(r), np.sin(r)
    e, n = v[..., 0:1], v[..., 1:2]
    return np.concatenate([e * c[..., 0:1] + n * s[..., 0:1], -e * s[..., 0:1] + n * c[..., 0:1]], -1)  # clockwise = compass


class Field:
    """Unit-variance Gaussian random field per member over lon/lat (km scale), correlation length `ell` metres."""

    def __init__(self, base_seed: Any, members: Iterable[Any], stream: str, ell: float):
        k: list[Any] = []
        ph: list[Any] = []
        for m in members:
            r = member_rng(base_seed, int(m), stream)
            k.append(r.normal(0.0, 1.0 / ell, (NFEAT, 2)))
            ph.append(r.uniform(0, 2 * np.pi, NFEAT))
        self.k, self.ph = np.array(k), np.array(ph)          # (M, NFEAT, 2), (M, NFEAT)

    def __call__(self, lon: ArrayLike, lat: ArrayLike) -> NDArray[np.float64]:
        lon, lat = np.broadcast_arrays(np.asarray(lon, float), np.asarray(lat, float))
        x = np.radians(lon) * R_EARTH * np.cos(np.radians(lat))
        y = np.radians(lat) * R_EARTH
        M = self.k.shape[0]
        sh = lon.shape
        if sh[:1] != (M,):
            raise ValueError(f"field queried with shape {sh}; the leading axis must be the {M} members")
        xx, yy = x.reshape(M, -1, 1), y.reshape(M, -1, 1)
        arg = xx * self.k[:, None, :, 0] + yy * self.k[:, None, :, 1] + self.ph[:, None, :]
        out: NDArray[np.float64] = (np.sqrt(2.0 / NFEAT) * np.cos(arg).sum(-1)).reshape(sh)
        return out


class OceanSDE:
    """Per-member Brownian increments of the ocean SDE over [t0, t1] at step dt, and the velocity they imply (module docstring)."""

    def __init__(self, base_seed: Any, members: Iterable[Any], t0: float, t1: float, dt: float):
        self.t0, self.dt, self.n = float(t0), float(dt), int(np.ceil((float(t1) - float(t0)) / float(dt))) + 2
        self.xi = np.stack([member_rng(base_seed, int(m), "ocean_sde").standard_normal((self.n, 2)) for m in members])    # (M, n, 2)

    def velocity(self, lon: Any, lat: ArrayLike, t: ArrayLike) -> Any:
        """(M, ..., 2) m/s at member positions (leading axis = members) and time t: dK/dx + sqrt(2 K / dt) xi, from one
        `subgrid.ocean_sde_step` of length dt taken from the origin."""
        lat = np.asarray(lat, float)
        k = np.broadcast_to(np.rint((np.asarray(t, float) - self.t0) / self.dt).astype(int), lat.shape)
        if k.min() < 0 or k.max() >= self.n:
            raise ValueError(f"ocean SDE queried outside its window: step {int(k.min())}..{int(k.max())} of {self.n}")
        xi = self.xi[np.arange(len(self.xi)).reshape((-1,) + (1,) * (lat.ndim - 1)), k]
        K, gradK = subgrid.sde_diffusivity(lat)
        return subgrid.ocean_sde_step(np.zeros(lat.shape + (2,)), K, gradK, self.dt, None, xi=xi) / self.dt


class PerturbedEnv:
    def __init__(self, env: Environment, X: dict[str, ArrayLike], members: Any, base_seed: Any, priors: dict[str, Any],
                 sde: dict[str, float] | None = None):
        """X: {param: (M,) array} from the LHS; priors: config/perturbations.yaml as loaded by stats.sampling; sde: None (off) or
        dict(t0, t1, dt) [s], the window and the vehicles' step, for the ocean SDE."""
        self.env, self.X, self.bounds = env, {k: np.asarray(v, float) for k, v in X.items()}, env.bounds
        self.M = len(members)
        ell = float(priors["current_correlation_length"]["mean"])
        self.cs = float(priors["current_speed_scale"]["value"])
        self.cd = float(priors["current_direction_bias"]["value"])
        self.fs = Field(base_seed, members, "current_speed_field", ell)
        self.fd = Field(base_seed, members, "current_direction_field", ell)
        self.sde = None if sde is None else OceanSDE(base_seed, members, **sde)

    def _m(self, k: str, shape: tuple[int, ...]) -> Any:
        v = self.X.get(k)
        if v is None:
            return None
        return v.reshape((self.M,) + (1,) * (len(shape) - 1))

    def wind(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        w = self.env.wind(lon, lat, z, t)
        v = w.value
        sp = np.hypot(v[..., 0], v[..., 1])
        b = self._m("wind_speed_bias", sp.shape)
        d = self._m("wind_direction_bias", sp.shape)
        new = np.maximum(sp + (0.0 if b is None else b), 0.0)
        v = v * np.where(sp > 1e-9, new / np.where(sp > 1e-9, sp, 1.0), 0.0)[..., None]
        if d is not None:
            v = _rot(v, np.broadcast_to(d, sp.shape))
        return Tagged(v, w.source + "; member wind error applied", w.uncertainty, w.kind)

    def current(self, lon: Any, lat: Any, z: Any, t: Any) -> Tagged:
        c = self.env.current(lon, lat, z, t)
        v = c.value
        sh = v.shape[:-1]
        lonb, latb = (np.broadcast_to(np.asarray(a, float), sh) for a in (lon, lat))
        a = self._m("current_speed_scale", sh)
        logs = (np.log(a) / np.sqrt(2.0) if a is not None else 0.0) + self.cs / np.sqrt(2.0) * self.fs(lonb, latb) - self.cs ** 2 / 4
        db = self._m("current_direction_bias", sh)
        rot = (db / np.sqrt(2.0) if db is not None else 0.0) + self.cd / np.sqrt(2.0) * self.fd(lonb, latb)
        v = _rot(v * np.exp(logs)[..., None], np.broadcast_to(rot, sh))
        src = c.source + "; member current error applied (member-wide + 100 km random field)"
        if self.sde is not None:
            v = v + self.sde.velocity(lonb, latb, t)
            src += "; + ocean Lagrangian SDE (Ito, Euler-Maruyama, dK/dx drift, Okubo K at the HYCOM cell size)"
        return Tagged(v, src, c.uncertainty, c.kind)

    def waves(self, lon: Any, lat: Any, t: Any) -> dict[str, Tagged]:
        w = dict(self.env.waves(lon, lat, t))
        sh = np.shape(w["Hs"].value)
        hs = self._m("hs_scale", sh)
        tp = self._m("tp_bias", sh)
        if hs is not None:
            for k in ("Hs",):
                w[k] = w[k]._replace(value=w[k].value * hs, source=w[k].source + " x member hs_scale")
            w["stokes0"] = w["stokes0"]._replace(value=w["stokes0"].value * (hs ** 2)[..., None])
        if tp is not None:
            for k in ("Tp", "Tm"):
                w[k] = w[k]._replace(value=np.maximum(w[k].value + tp, 1.0), source=w[k].source + " + member tp_bias")
        return w

    def __getattr__(self, name: str) -> Any:                             # density, sound_speed, depth, sst, air, inside, ...
        return getattr(self.env, name)
