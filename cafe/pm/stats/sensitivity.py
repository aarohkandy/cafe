"""First-order Sobol indices from an existing sample (no extra model runs) for the "most sensitive parameter" line.

Estimator: EASI, Plischke (2010, Reliability Eng. & System Safety 95(4), 354-360): sort the sample by X_i, reorder it
into a periodic sequence (even ranks ascending, odd ranks descending), and take the share of the output's spectral
power in the first M harmonics as S_i = Var(E[Y|X_i]) / Var(Y). Small-sample bias is removed with the
Plischke (2012, "Sensitivity analysis from given data", Plischke, Borgonovo & Smith) correction
S~ = S - lam/(1 - lam) * (1 - S), lam = 2M/N. Works on any design (LHS here) and for a 0/1 failure indicator as well
as continuous margins; for an indicator S_i is the share of the indicator's variance explained by parameter i.
"""
from __future__ import annotations

import numpy as np


def first_order(x: np.ndarray, y: np.ndarray, harmonics: int = 6, correct: bool = True) -> np.ndarray:
    """S1 for each column of x (n, d) against y (n,). Values are clipped to [0, 1]. Constant y gives zeros."""
    n, d = x.shape
    y = np.asarray(y, float) - np.mean(y)
    out = np.zeros(d)
    if not np.any(y):
        return out
    m = harmonics
    lam = 2 * m / n
    for i in range(d):
        order = np.argsort(x[:, i], kind="stable")
        seq = y[np.concatenate([order[0::2], order[1::2][::-1]])]
        p = np.abs(np.fft.fft(seq)) ** 2
        s = 2 * p[1:m + 1].sum() / p[1:].sum() if p[1:].sum() > 0 else 0.0
        out[i] = s - lam / (1 - lam) * (1 - s) if correct else s
    return np.clip(out, 0.0, 1.0)


def noise_floor(x: np.ndarray, y: np.ndarray, perms: int = 200, level: float = 0.95, seed: int = 0, harmonics: int = 6) -> float:
    """The largest S1 over all columns that y unrelated to x reaches with probability 1 - level: the `level` quantile of
    max_i S1_i over `perms` random permutations of y (a family-wise permutation test). With 32 members it is ~0.3, so an S1
    below it is no evidence that the parameter matters."""
    rng = np.random.default_rng(seed)
    null = [first_order(x, rng.permutation(np.asarray(y, float)), harmonics).max() for _ in range(perms)]
    return float(np.quantile(null, level))


def dominant(names: list[str], x: np.ndarray, y: np.ndarray, harmonics: int = 6) -> tuple[str | None, dict[str, float], float]:
    """(name of the parameter with the largest S1, or None when no S1 clears the permutation noise floor; {name: S1}; the floor)
    for the verdict's "most sensitive to" field."""
    s = first_order(x, y, harmonics)
    floor = noise_floor(x, y, harmonics=harmonics)
    return (names[int(np.argmax(s))] if s.max() > floor else None), dict(zip(names, map(float, s), strict=True)), floor
