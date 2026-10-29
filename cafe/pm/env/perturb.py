"""One environment per Monte-Carlo member: the gridded fields with that member's forcing errors applied.

Member m's draws come from the Stage-1 Latin hypercube (`stats.sampling.lhs`), keyed by member only, never by
vehicle: every vehicle in member m flies through the same perturbed wind, current and waves (common random numbers),
so inter-vehicle range checks are consistent.

- Wind: speed + wind_speed_bias[m] (floored at 0), direction rotated by wind_direction_bias[m].
- Current: speed x scale, rotated by a direction bias. Half of each prior's variance is member-wide (the LHS draw,
  so Sobol indices see it); half is a smooth random field with the configured correlation length (100 km), built
  from random Fourier features (Rahimi & Recht 2007) with a Gaussian covariance, seeded per member. The total
  1-sigma is the prior's.
- Waves: Hs x hs_scale[m], Tp + tp_bias[m] (floored at 1 s). Stokes drift scales with Hs^2 (it is quadratic in amplitude).
Everything else (density, sound speed, depth, SST, air) passes through unchanged.

Arrays passed to the methods must have a leading member axis of length M (or broadcast to it).
"""
import numpy as np

from .. import Tagged
from ..stats.sampling import member_rng

NFEAT = 32
R_EARTH = 6.371e6


def _rot(v, deg):
    r = np.radians(deg)[..., None]
    c, s = np.cos(r), np.sin(r)
    e, n = v[..., 0:1], v[..., 1:2]
    return np.concatenate([e * c[..., 0:1] + n * s[..., 0:1], -e * s[..., 0:1] + n * c[..., 0:1]], -1)  # clockwise = compass


class Field:
    """Unit-variance Gaussian random field per member over lon/lat (km scale), correlation length `ell` metres."""

    def __init__(self, base_seed, members, stream, ell):
        k, ph = [], []
        for m in members:
            r = member_rng(base_seed, int(m), stream)
            k.append(r.normal(0.0, 1.0 / ell, (NFEAT, 2)))
            ph.append(r.uniform(0, 2 * np.pi, NFEAT))
        self.k, self.ph = np.array(k), np.array(ph)          # (M, NFEAT, 2), (M, NFEAT)

    def __call__(self, lon, lat):
        lon, lat = np.broadcast_arrays(np.asarray(lon, float), np.asarray(lat, float))
        x = np.radians(lon) * R_EARTH * np.cos(np.radians(lat))
        y = np.radians(lat) * R_EARTH
        M = self.k.shape[0]
        sh = lon.shape
        if sh[:1] != (M,):
            raise ValueError(f"field queried with shape {sh}; the leading axis must be the {M} members")
        xx, yy = x.reshape(M, -1, 1), y.reshape(M, -1, 1)
        arg = xx * self.k[:, None, :, 0] + yy * self.k[:, None, :, 1] + self.ph[:, None, :]
        return (np.sqrt(2.0 / NFEAT) * np.cos(arg).sum(-1)).reshape(sh)


class PerturbedEnv:
    def __init__(self, env, X, members, base_seed, priors):
        """X: {param: (M,) array} from the LHS; priors: config/perturbations.yaml as loaded by stats.sampling."""
        self.env, self.X, self.bounds = env, {k: np.asarray(v, float) for k, v in X.items()}, env.bounds
        self.M = len(members)
        ell = float(priors["current_correlation_length"]["mean"])
        self.cs = float(priors["current_speed_scale"]["value"])
        self.cd = float(priors["current_direction_bias"]["value"])
        self.fs = Field(base_seed, members, "current_speed_field", ell)
        self.fd = Field(base_seed, members, "current_direction_field", ell)

    def _m(self, k, shape):
        v = self.X.get(k)
        if v is None:
            return None
        return v.reshape((self.M,) + (1,) * (len(shape) - 1))

    def wind(self, lon, lat, z, t):
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

    def current(self, lon, lat, z, t):
        c = self.env.current(lon, lat, z, t)
        v = c.value
        sh = v.shape[:-1]
        lonb, latb = (np.broadcast_to(np.asarray(a, float), sh) for a in (lon, lat))
        a = self._m("current_speed_scale", sh)
        logs = (np.log(a) / np.sqrt(2.0) if a is not None else 0.0) + self.cs / np.sqrt(2.0) * self.fs(lonb, latb) - self.cs ** 2 / 4
        db = self._m("current_direction_bias", sh)
        rot = (db / np.sqrt(2.0) if db is not None else 0.0) + self.cd / np.sqrt(2.0) * self.fd(lonb, latb)
        v = _rot(v * np.exp(logs)[..., None], np.broadcast_to(rot, sh))
        return Tagged(v, c.source + "; member current error applied (member-wide + 100 km random field)", c.uncertainty, c.kind)

    def waves(self, lon, lat, t):
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

    def __getattr__(self, name):                             # density, sound_speed, depth, sst, air, inside, ...
        return getattr(self.env, name)
