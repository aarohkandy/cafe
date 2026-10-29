"""Multilinear interpolation on separable, monotonic axes (time, depth, lat, lon), vectorized and NaN-aware.

NaN corners (land in UMWM, below-seafloor HYCOM levels) are dropped and the remaining weights renormalized; a point with
no valid corner is NaN. Outside an axis the nearest edge is used and `inside` says so, so callers can refuse or flag.
"""
import numpy as np


class Axis:
    def __init__(self, x, name=""):
        x = np.asarray(x, float)
        if x.ndim != 1 or len(x) < 1:
            raise ValueError(f"axis {name}: need a 1-D array, got shape {x.shape}")
        if len(x) > 1 and not np.all(np.diff(x) > 0):
            raise ValueError(f"axis {name}: must be strictly increasing")
        self.x, self.name = x, name

    def locate(self, q):
        q = np.asarray(q, float)
        inside = (q >= self.x[0]) & (q <= self.x[-1])
        if len(self.x) == 1:
            return np.zeros(q.shape, int), np.zeros(q.shape), inside
        i = np.clip(np.searchsorted(self.x, q, side="right") - 1, 0, len(self.x) - 2)
        w = np.clip((q - self.x[i]) / (self.x[i + 1] - self.x[i]), 0.0, 1.0)
        return i, w, inside


def interp(field, axes, qs):
    """field[n0, n1, ...] at query arrays qs (broadcast together). Returns (values, inside_all).

    All 2^d corners are gathered in one flat-index take (corner offsets from the strides), so the cost per call is a few
    numpy operations whatever d is: Stage-1 calls this ~10^6 times on a handful of points, where per-call overhead is all."""
    qs = np.broadcast_arrays(*[np.asarray(q, float) for q in qs])
    shape = qs[0].shape
    f = np.asarray(field)
    flat = f.reshape(-1)
    stride = np.cumprod((f.shape[1:] + (1,))[::-1])[::-1]
    base = np.zeros(shape, np.intp)
    offs = np.zeros(1, np.intp)
    wts = np.ones(shape + (1,))
    inside = np.ones(shape, bool)
    for a, q, st in zip(axes, qs, stride, strict=True):
        i, w, ins = a.locate(q)
        inside &= ins
        base += i * st
        step = st if len(a.x) > 1 else 0                                # a one-point axis has no second corner
        offs = (offs[:, None] + np.array([0, step])[None, :]).reshape(-1)
        wts = (wts[..., :, None] * np.stack([1.0 - w, w], -1)[..., None, :]).reshape(shape + (-1,))
    v = flat[base[..., None] + offs]
    ok = np.isfinite(v) & (wts > 0)
    num = np.where(ok, wts * np.where(ok, v, 0.0), 0.0).sum(-1)
    den = np.where(ok, wts, 0.0).sum(-1)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan), inside
