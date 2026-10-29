"""Subset simulation for rare failures (Au & Beck 2001, Probabilistic Eng. Mechanics 16(4), 263-277).

P(F) = P(F1) prod P(F_{i+1} | F_i) with nested F_i = {g(u) >= b_i}; each level keeps the top p0 fraction of its samples as
seeds and moves them with the modified Metropolis algorithm (component-wise accept/reject against the standard
normal, then reject the whole move if it leaves F_i). The problem must be posed in standard-normal space u: the caller
maps LHS uniforms through the normal quantile. Failure is g(u) >= `target`. The c.o.v. follows Au & Beck 2001
Sec. 5 (binomial term inflated by the chain correlation gamma_i, sum of squares over levels).
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np


def _mma(u: np.ndarray, g: np.ndarray, b: float, fn: Callable[[np.ndarray], np.ndarray], rng: np.random.Generator,
         length: int, width: float) -> tuple[np.ndarray, np.ndarray]:
    """Grow each seed into a chain of `length` samples inside {g >= b}; returns u (length, chains, d), g (length, chains)."""
    chains, d = u.shape
    us, gs = [u], [g]
    for _ in range(length - 1):
        cand = u + width * rng.standard_normal((chains, d))
        keep = rng.random((chains, d)) < np.minimum(1.0, np.exp(-0.5 * (cand ** 2 - u ** 2)))
        cand = np.where(keep, cand, u)
        gc = fn(cand)
        ok = gc >= b
        u, g = np.where(ok[:, None], cand, u), np.where(ok, gc, g)
        us.append(u)
        gs.append(g)
    return np.array(us), np.array(gs)


def _gamma(ind: np.ndarray) -> float:
    """Au & Beck 2001 eq. (29)-(30): chain-correlation factor from an indicator array (length, chains)."""
    ns, nc = ind.shape
    n = ns * nc
    p = ind.mean()
    r0 = p * (1 - p)
    if r0 == 0:
        return 0.0
    rho = [((ind[:ns - k] * ind[k:]).sum() / (n - k * nc) - p * p) / r0 for k in range(1, ns)]
    return float(2 * sum((1 - k * nc / n) * r for k, r in enumerate(rho, 1)))


def subset_simulation(fn: Callable[[np.ndarray], np.ndarray], d: int, target: float, n: int = 1000, p0: float = 0.1,
                      seed: int = 0, max_levels: int = 20, width: float = 1.0) -> dict[str, Any]:
    """P(g(u) >= target) for u ~ N(0, I_d); `fn` maps (m, d) -> (m,).

    n is rounded to a multiple of the chain count. Returns dict(p, cov, levels, n_evals, converged); converged is False
    (p = 0, cov = inf) if the thresholds stop rising (ties) or max_levels is spent.
    """
    rng = np.random.default_rng(seed)
    nc = int(round(n * p0))
    length = n // nc
    n = nc * length
    u = rng.standard_normal((n, d))
    g = fn(u)
    n_evals, d2, p = n, 0.0, 1.0
    levels: list[float] = []
    for lvl in range(max_levels):
        gam = _gamma(g.reshape(length, nc) >= levels[-1]) if lvl else 0.0
        order = np.argsort(-g)
        b = 0.5 * (g[order[nc - 1]] + g[order[nc]])
        if b >= target:
            frac = float(np.mean(g >= target))
            gam = _gamma(g.reshape(length, nc) >= target) if lvl else 0.0
            d2 += (1 - frac) / (frac * n) * (1 + gam) if frac > 0 else np.inf
            levels.append(float(target))
            return dict(p=p * frac, cov=float(np.sqrt(d2)), levels=levels, n_evals=n_evals, converged=True)
        if lvl and b <= levels[-1]:
            break
        d2 += (1 - p0) / (p0 * n) * (1 + gam)
        p *= nc / n
        levels.append(float(b))
        us, gs = _mma(u[order[:nc]], g[order[:nc]], b, fn, rng, length, width)
        n_evals += (length - 1) * nc
        u, g = us.reshape(-1, d), gs.reshape(-1)
    return dict(p=0.0, cov=float("inf"), levels=levels, n_evals=n_evals, converged=False)
