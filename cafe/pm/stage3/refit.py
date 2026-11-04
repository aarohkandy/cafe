"""Refit: window coefficient estimates -> a perturbation distribution for Stage 1, and the verdict-convergence loop.

Each window gives a mean coefficient and a standard error (windows.coefficients). The windows are different conditions
(wind, current, gusts), so their means differ by more than their errors: the pooled estimate is a random-effects
combination (DerSimonian & Laird 1986, Controlled Clinical Trials 7, 177: tau^2 = max(0, (Q - (k-1)) / (S1 - S2/S1)),
w_i* = 1/(se_i^2 + tau^2)). The distribution Stage 1 should sample a drag/lift/added-resistance multiplier from is
Normal(mean = pooled / hangar value, sigma = sqrt(se_pooled^2 + tau^2) / hangar value): the spread of a *new* window's
coefficient, not only the error of the mean. Multipliers are relative to the Hangar (RANS) coefficient Stage 1 used.

A single window (the ci and quick budgets) has no between-window spread (tau^2 = 0) and its standard error is the batch-means error of one run, a
few hundredths of a percent: not the uncertainty of a drag multiplier. So the sigma carries two floors, both stated in the output (`floor`):
the between-window spread is at least `between_window_frac` of the pooled value when fewer than two windows exist, and the discretisation error
(`discretisation_frac` of the pooled value: the larger of the assumed default and the finest stored sphere grid's distance to its
Richardson extrapolation, nest.sphere_discretisation; a study can raise the floor, never lower it) is always added in
quadrature. `refit(..., floor={})` pools without them.
"""
from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
from numpy.typing import ArrayLike

from .. import budget

MAX_ITER = 2


def pool(means: ArrayLike, ses: ArrayLike) -> dict[str, float]:
    """Random-effects pooled mean, its standard error and the between-window variance tau^2 (DerSimonian-Laird)."""
    m, se = np.asarray(means, float), np.asarray(ses, float)
    if m.shape != se.shape or m.ndim != 1 or len(m) == 0:
        raise ValueError("means and ses must be 1-D arrays of equal, non-zero length")
    if (se <= 0).any():
        raise ValueError("standard errors must be positive")
    w = 1 / se ** 2
    fixed = (w * m).sum() / w.sum()
    k = len(m)
    q = (w * (m - fixed) ** 2).sum()
    denom = w.sum() - (w ** 2).sum() / w.sum()
    tau2 = max(0.0, (q - (k - 1)) / denom) if k > 1 and denom > 0 else 0.0
    ws = 1 / (se ** 2 + tau2)
    mean = (ws * m).sum() / ws.sum()
    return dict(mean=float(mean), se=float(math.sqrt(1 / ws.sum())), tau2=float(tau2), n=k, q=float(q))


def default_floor() -> dict[str, Any]:
    """The sigma floors `refit` applies unless told otherwise: the assumed between-window fraction (config/assumptions.yaml `stage3.refit.*`)
    and the discretisation fraction: the larger of the assumed one and the stored sphere grid study's (a study of two or three grids
    that happen to agree is no evidence of a smaller error than the assumption; round 7 M-9)."""
    from .nest import sphere_discretisation
    a = budget.stage3_assumptions()
    disc = sphere_discretisation()
    assumed = float(a["refit.discretisation_frac"])
    return dict(between_window_frac=float(a["refit.between_window_frac"]),
                between_window_source="ASSUMED (config/assumptions.yaml stage3.refit.between_window_frac)",
                discretisation_frac=assumed if disc is None else max(assumed, disc[0]),
                discretisation_source="ASSUMED: no stored sphere grid study (needs two grids of one Re)" if disc is None else
                f"{disc[1]}: floor = max(assumed {assumed:g}, study {disc[0]:.3g})")


def _sigma(mean: float, se: float, tau: float, windows: float, floor: dict[str, Any]) -> dict[str, float]:
    """Total sigma and its parts. `mean`, `se`, `tau` in the units of the quantity; the floors are fractions of |mean|."""
    between = max(tau, floor["between_window_frac"] * abs(mean)) if windows < 2 and floor else tau
    disc = floor["discretisation_frac"] * abs(mean) if floor else 0.0
    return dict(sigma=math.sqrt(se ** 2 + between ** 2 + disc ** 2), sigma_statistical=math.sqrt(se ** 2 + tau ** 2), sigma_between=between,
                sigma_discretisation=disc)


def _multiplier(ratios: ArrayLike, ses: ArrayLike, windows: int, floor: dict[str, Any]) -> dict[str, float]:
    p = pool(ratios, ses)
    tau = math.sqrt(p["tau2"])
    return dict(mean=p["mean"], **_sigma(p["mean"], p["se"], tau, windows, floor), change_vs_hangar=p["mean"] - 1, tau=tau, windows=windows)


def refit(windows: list[dict[str, Any]], hangar: dict[str, Any] | None = None, floor: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """windows: pipeline_windows rows / run_window results (keys cd, cd_spread, cl, cl_spread, added_resistance and, with hangar=None,
    cd_hangar and cl_hangar of each window). Returns the Stage-1 perturbation distribution plus the coefficient change vs the
    Hangar and the spread, as the `refit` ledger entry records them.
    hangar = {"cd": value, "cl": value (optional)}: one Hangar value for all windows (multiplier = pooled coefficient / hangar value).
    hangar = None: each window carries the coefficient its vehicle's Stage-1 model implies at that window's speed, and the pooled
    quantity is the per-window ratio cd / cd_hangar (its standard error cd_spread / cd_hangar); lift likewise over the windows that
    have a non-zero cl_hangar. `floor`: the sigma floors (default_floor(); {} for none), reported as out["floor"] when applied."""
    if not windows:
        raise ValueError("no windows to refit from")
    fl = default_floor() if floor is None else floor
    out: dict[str, dict[str, Any]] = {}
    if hangar is None:
        out["drag"] = _multiplier([w["cd"] / w["cd_hangar"] for w in windows], [max(w["cd_spread"], 1e-12) / w["cd_hangar"] for w in windows],
                                  len(windows), fl)
        lw = [w for w in windows if w.get("cl_hangar")]
        if lw:
            out["lift"] = _multiplier([w["cl"] / w["cl_hangar"] for w in lw], [max(w["cl_spread"], 1e-12) / abs(w["cl_hangar"]) for w in lw], len(lw), fl)
    else:
        cd = pool([w["cd"] for w in windows], [w["cd_spread"] for w in windows])
        h = hangar["cd"]
        tau = math.sqrt(cd["tau2"]) / h
        out["drag"] = dict(mean=cd["mean"] / h, **_sigma(cd["mean"] / h, cd["se"] / h, tau, cd["n"], fl), change_vs_hangar=cd["mean"] / h - 1, tau=tau,
                           windows=cd["n"])
        if hangar.get("cl") not in (None, 0):
            cl = pool([w["cl"] for w in windows], [max(w["cl_spread"], 1e-12) for w in windows])
            hl = hangar["cl"]
            tau = math.sqrt(cl["tau2"]) / abs(hl)
            out["lift"] = dict(mean=cl["mean"] / hl, **_sigma(cl["mean"] / hl, cl["se"] / abs(hl), tau, cl["n"], fl), change_vs_hangar=cl["mean"] / hl - 1,
                               tau=tau, windows=cl["n"])
    if fl:
        out["floor"] = dict(fl)
    ar = [w["added_resistance"] for w in windows if w.get("added_resistance") is not None]
    if ar:
        a = np.asarray(ar, float)
        out["added_resistance"] = dict(mean=float(a.mean()), sigma=float(a.std(ddof=1)) if len(a) > 1 else 0.0, windows=len(a))
    return out


def verdict_changes(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """Vehicles (keys) whose verdict differs between two Stage-1 runs, as (key, was, now)."""
    return [(k, before[k], after.get(k)) for k in before if after.get(k) != before[k]]


def refit_loop(stage1: Callable[[Any], dict[str, Any]], perturbation: Callable[[int], Any], max_iter: int = MAX_ITER) -> dict[str, Any]:
    """stage1(perturbation | None) -> {vehicle: verdict}; perturbation(iteration) -> distribution from the windows (refit()).
    Runs stage1, then refits and reruns up to `max_iter` times, stopping early when no verdict changes.
    Returns the history, the verdict changes of each iteration and why it stopped ("converged" or "cap")."""
    hist = [stage1(None)]
    changes: list[list[tuple[str, Any, Any]]] = []
    reason = "cap"
    for i in range(1, max_iter + 1):
        hist.append(stage1(perturbation(i)))
        ch = verdict_changes(hist[-2], hist[-1])
        changes.append(ch)
        if not ch:
            reason = "converged"
            break
    return dict(verdicts=hist, changes=changes, iterations=len(hist) - 1, reason=reason, converged=reason == "converged")
