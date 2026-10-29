"""Latin hypercube sampling with common random numbers and antithetic pairs for the Stage-1 ensemble.

LHS: McKay, Beckman & Conover (1979, Technometrics 21): n strata per dimension, each hit exactly once, one jittered
point per stratum, strata permuted independently per dimension. Antithetic variates: Hammersley & Morton (1956);
here pair i and i + n/2 are mirrored (u -> 1 - u) on the named dominant parameters and the strata are paired
(s, n-1-s) so the sample stays an exact LHS. Common random numbers: the seed of an environment stream depends on
(base seed, member index, stream name) only, never on the vehicle, so every vehicle in member m sees the same draws.
"""
from __future__ import annotations

import hashlib
import pathlib
from typing import Any

import numpy as np
import yaml
from scipy import stats

PERTURBATIONS = pathlib.Path(__file__).resolve().parents[3] / "config" / "perturbations.yaml"


def marginal(spec: dict[str, Any]) -> Any:
    """Frozen scipy distribution from {"dist": normal|lognormal|uniform|truncnorm, ...}.

    normal: mean, sd. lognormal: median, sigma (log-space sd). uniform: lo, hi. truncnorm: mean, sd, lo, hi.
    """
    d = spec["dist"]
    if d == "normal":
        return stats.norm(spec.get("mean", 0.0), spec["sd"])
    if d == "lognormal":
        return stats.lognorm(s=spec["sigma"], scale=spec.get("median", 1.0))
    if d == "uniform":
        return stats.uniform(spec["lo"], spec["hi"] - spec["lo"])
    if d == "truncnorm":
        m, s = spec.get("mean", 0.0), spec["sd"]
        return stats.truncnorm((spec["lo"] - m) / s, (spec["hi"] - m) / s, loc=m, scale=s)
    raise ValueError(f"unknown distribution {d!r}")


def load_perturbations(path: str | pathlib.Path | None = None) -> dict[str, dict[str, Any]]:
    """Read config/perturbations.yaml; every entry must carry value, unit, citation and kind: prior (sourced) or assumed."""
    cfg = yaml.safe_load(pathlib.Path(path or PERTURBATIONS).read_text())
    for k, e in cfg.items():
        miss = {"value", "unit", "citation", "kind"} - e.keys()
        if miss or e["kind"] not in ("prior", "assumed"):              # assumed: no source, listed in the credibility report
            raise ValueError(f"perturbation {k!r}: missing {sorted(miss)} or kind not prior/assumed")
    return cfg


def to_marginals(cfg: dict[str, dict[str, Any]], names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """perturbations.yaml entries -> marginal specs for `lhs` (the `value` field is sd / sigma).

    Entries with dist "fixed" are settings (e.g. a correlation length), not sampled, and are left out unless named.
    """
    out = {}
    for k in names or [k for k in cfg if cfg[k]["dist"] != "fixed"]:
        e = cfg[k]
        d = e["dist"]
        if d == "normal":
            out[k] = dict(dist="normal", mean=e.get("mean", 0.0), sd=e["value"])
        elif d == "lognormal":
            out[k] = dict(dist="lognormal", median=e.get("median", 1.0), sigma=e["value"])
        elif d == "uniform":
            out[k] = dict(dist="uniform", lo=e["lo"], hi=e["hi"])
        else:
            raise ValueError(f"{k!r} has dist {d!r}: not a sampled parameter")
    return out


def lhs_unit(n: int, d: int, rng: np.random.Generator, antithetic: tuple[int, ...] = ()) -> np.ndarray:
    """(n, d) uniforms; column j has exactly one point in each of the n strata [s/n, (s+1)/n).

    Columns in `antithetic` satisfy u[i + n/2] = 1 - u[i] (n must be even) and are still exact LHS columns.
    """
    u = (rng.permuted(np.tile(np.arange(n), (d, 1)), axis=1).T + rng.random((n, d))) / n
    if antithetic:
        if n % 2:
            raise ValueError("antithetic pairs need an even n")
        m = n // 2
        for j in antithetic:
            s = rng.permutation(m)                                   # stratum pairs (s, n-1-s)
            lo = rng.random(m) < 0.5
            first = np.where(lo, s, n - 1 - s)
            u[:m, j] = (first + rng.random(m)) / n
            u[m:, j] = 1 - u[:m, j]
    return u


def lhs(n: int, params: dict[str, dict[str, Any]], seed: int | np.random.SeedSequence = 0,
        antithetic: tuple[str, ...] = ()) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """LHS over named parameters with the given marginals. Returns (U, X): uniforms (n, d) and {name: values (n,)}."""
    names = list(params)
    u = lhs_unit(n, len(names), np.random.default_rng(seed), tuple(names.index(a) for a in antithetic))
    return u, {k: marginal(params[k]).ppf(u[:, j]) for j, k in enumerate(names)}


def stratification_report(u: np.ndarray) -> dict[str, Any]:
    """The stage1 ledger entry: strata hit exactly once per column, and the marginal-uniformity statistic.

    The Kolmogorov-Smirnov distance of an exact LHS column from U(0,1) is at most 1/n, so `ok` needs D <= 1/n
    (a p-value would be ~1 for any LHS and could not fail).
    """
    n, d = u.shape
    strata = np.floor(u * n).astype(int)
    exact = bool(all(np.array_equal(np.sort(strata[:, j]), np.arange(n)) for j in range(d)))
    ks = max(stats.kstest(u[:, j], "uniform").statistic for j in range(d))
    return dict(n=n, d=d, strata_exact=exact, ks_d_max=float(ks), ks_bound=1 / n, ok=bool(exact and ks <= 1 / n + 1e-12))


def marginal_report(x: dict[str, np.ndarray], params: dict[str, dict[str, Any]]) -> dict[str, float]:
    """KS distance of each sampled column from its intended marginal (<= 1/n for an LHS draw)."""
    return {k: float(stats.kstest(v, marginal(params[k]).cdf).statistic) for k, v in x.items()}


def _stream_id(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big")


def _seq(base_seed: int, member: int, stream_name: str) -> np.random.SeedSequence:
    return np.random.SeedSequence(entropy=base_seed, spawn_key=(member, _stream_id(stream_name)))


def member_seed(base_seed: int, member: int, stream_name: str) -> int:
    """Deterministic 64-bit seed for (member, stream). No vehicle in the key: that is the common random numbers."""
    return int(_seq(base_seed, member, stream_name).generate_state(1, np.uint64)[0])


def member_rng(base_seed: int, member: int, stream_name: str) -> np.random.Generator:
    """Generator for (member, stream), built on the SeedSequence spawn key so streams are statistically independent."""
    return np.random.default_rng(_seq(base_seed, member, stream_name))


def crn_check(base_seed: int, members: int, streams: tuple[str, ...], vehicles: int = 2) -> bool:
    """Ledger self-check: each vehicle draws every stream for every member; all vehicles must see identical values."""
    draws = [[member_rng(base_seed, m, s).standard_normal(8) for m in range(members) for s in streams]
             for _ in range(vehicles)]
    return all(np.array_equal(draws[0][i], draws[v][i]) for v in range(1, vehicles) for i in range(len(draws[0])))
