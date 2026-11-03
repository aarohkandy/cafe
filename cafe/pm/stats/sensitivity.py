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


def default_harmonics(n: int) -> int:
    """M = min(6, max(2, n // 16)): the permutation-null floor of max S1 grows with M/N (lam = 2M/N); six harmonics at 32 members put it at
    0.53 to 0.60, so no index could clear it. Two harmonics at 32 members give about 0.30."""
    return min(6, max(2, n // 16))


def first_order(x: np.ndarray, y: np.ndarray, harmonics: int | None = None, correct: bool = True) -> np.ndarray:
    """S1 for each column of x (n, d) against y (n,). Values are clipped to [0, 1]. Constant y gives zeros. `harmonics` defaults to `default_harmonics(n)`."""
    n, d = x.shape
    y = np.asarray(y, float) - np.mean(y)
    out = np.zeros(d)
    if not np.any(y):
        return out
    m = default_harmonics(n) if harmonics is None else harmonics
    lam = 2 * m / n
    for i in range(d):
        order = np.argsort(x[:, i], kind="stable")
        seq = y[np.concatenate([order[0::2], order[1::2][::-1]])]
        p = np.abs(np.fft.fft(seq)) ** 2
        s = 2 * p[1:m + 1].sum() / p[1:].sum() if p[1:].sum() > 0 else 0.0
        out[i] = s - lam / (1 - lam) * (1 - s) if correct else s
    return np.clip(out, 0.0, 1.0)


def noise_floor(x: np.ndarray, y: np.ndarray, perms: int = 2000, level: float = 0.95, seed: int = 0, harmonics: int | None = None) -> float:
    """The largest S1 over all columns that y unrelated to x reaches with probability 1 - level: the `level` quantile of
    max_i S1_i over `perms` random permutations of y (a family-wise permutation test). With 32 members and the default two harmonics it is
    about 0.30 (measured, tests/test_stats.py); with six harmonics it would be 0.53 to 0.60. An S1 below it is no evidence that the parameter matters.
    2000 permutations (review round 5, M-2): the floor's own sd at 64 members falls from about 0.014 at 200 to 0.004 (tests/test_stats.py), so a driver
    0.005 above a floor is not read off one seed's noise. One test in twenty on unrelated outcomes still clears it, by construction of the 95 % level."""
    rng = np.random.default_rng(seed)
    null = [first_order(x, rng.permutation(np.asarray(y, float)), harmonics).max() for _ in range(perms)]
    return float(np.quantile(null, level))


def dominant(names: list[str], x: np.ndarray, y: np.ndarray, harmonics: int | None = None) -> tuple[str | None, dict[str, float], float]:
    """(name of the parameter with the largest S1, or None when no S1 clears the permutation noise floor; {name: S1}; the floor)
    for the verdict's "most sensitive to" field."""
    s = first_order(x, y, harmonics)
    floor = noise_floor(x, y, harmonics=harmonics)
    return (names[int(np.argmax(s))] if s.max() > floor else None), dict(zip(names, map(float, s), strict=True)), floor


def extreme_ranks(names: list[str], x: np.ndarray, members: np.ndarray, top: int = 3) -> list[tuple[str, list[int]]]:
    """For a few members (boolean mask over the rows of x): each parameter's rank of those members among all rows of x (0 = lowest value), for the `top`
    parameters whose members sit farthest from the middle rank on average, most extreme first. What can be said when too few members failed (or
    survived) for an index: a perfectly known driver shows as ranks all near 0 or all near n - 1."""
    n = len(x)
    rank = np.argsort(np.argsort(x, axis=0, kind="stable"), axis=0, kind="stable")
    far = np.abs(rank[members].mean(0) - (n - 1) / 2.0)
    return [(names[i], sorted(map(int, rank[members, i]))) for i in np.argsort(-far, kind="stable")[:top]]
