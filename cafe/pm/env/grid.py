"""Multilinear interpolation on separable, monotonic axes (time, depth, lat, lon), vectorized and NaN-aware.

NaN corners (land in UMWM, below-seafloor HYCOM levels) are dropped and the remaining weights renormalized; a point with
no valid corner is NaN. Outside an axis the nearest edge is used and `inside` says so, so callers can refuse or flag.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray


class Axis:
    def __init__(self, x: ArrayLike, name: str = "") -> None:
        x = np.asarray(x, float)
        if x.ndim != 1 or len(x) < 1:
            raise ValueError(f"axis {name}: need a 1-D array, got shape {x.shape}")
        if not np.all(np.isfinite(x)):                                  # NaN, or infinity (a NaT read as a number is neither: environment.seconds refuses it)
            raise ValueError(f"axis {name}: must be finite")
        if len(x) > 1 and not np.all(np.diff(x) > 0):
            raise ValueError(f"axis {name}: must be strictly increasing")
        self.x, self.name = x, name
        self.dx, self.top = np.diff(x), len(x) - 2                      # per call these were the hot spot (np.clip is slow on a handful of points)

    def locate(self, q: ArrayLike) -> tuple[NDArray[np.intp], NDArray[np.float64], NDArray[np.bool_]]:
        q = np.asarray(q, float)
        inside = (q >= self.x[0]) & (q <= self.x[-1])
        if len(self.x) == 1:
            return np.zeros(q.shape, int), np.zeros(q.shape), inside
        i = np.minimum(np.maximum(np.searchsorted(self.x, q, side="right") - 1, 0), self.top)
        w = np.minimum(np.maximum((q - self.x[i]) / self.dx[i], 0.0), 1.0)        # what np.clip gives, NaN included
        return i, w, inside


def interp(field: ArrayLike, axes: Sequence[Axis], qs: Sequence[ArrayLike]) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """field[..., n0, n1, ...] at query arrays qs (broadcast together), one axis per trailing dimension of `field`. Returns (values, inside_all);
    values has the leading dimensions of `field` in front (each one interpolated exactly as on its own: one call for every level of a 3-D field).

    All 2^d corners are gathered in one flat-index take (corner offsets from the strides), so the cost per call is a few
    numpy operations whatever d is: Stage-1 calls this ~10^6 times on a handful of points, where per-call overhead is all."""
    bq = [np.asarray(q, float) for q in qs]
    if any(q.shape != bq[0].shape for q in bq):                         # broadcast_arrays costs ~10 us, most calls do not need it
        bq = list(np.broadcast_arrays(*bq))
    shape = bq[0].shape
    f = np.asarray(field)
    lead = f.shape[:f.ndim - len(axes)]
    if 0 in shape:                                                       # an empty query (no points): nothing to gather, and the reshape below cannot take it
        return np.empty(lead + shape), np.ones(shape, bool)
    flat = f.reshape(lead + (-1,))
    stride, n = [], 1
    for k in reversed(f.shape[len(lead):]):
        stride.append(n)
        n *= k
    stride.reverse()
    base = np.zeros(shape, np.intp)
    offs = np.zeros(1, np.intp)
    wts = np.ones(shape + (1,))
    inside = np.ones(shape, bool)
    for a, q, st in zip(axes, bq, stride, strict=True):
        i, w, ins = a.locate(q)
        inside &= ins
        base += i * st
        step = st if len(a.x) > 1 else 0                                # a one-point axis has no second corner
        offs = np.add.outer(offs, (0, step)).ravel()
        pair = np.empty(shape + (2,))
        pair[..., 0], pair[..., 1] = 1.0 - w, w
        wts = (wts[..., :, None] * pair[..., None, :]).reshape(shape + (-1,))
    v = flat[..., base[..., None] + offs]
    ok = np.isfinite(v) & (wts > 0)
    num = np.where(ok, wts * np.where(ok, v, 0.0), 0.0).sum(-1)
    den = np.where(ok, wts, 0.0).sum(-1)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan), inside
