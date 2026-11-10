"""Latin hypercube sampling with common random numbers and antithetic pairs for the Stage-1 ensemble.

LHS: McKay, Beckman & Conover (1979, Technometrics 21): n strata per dimension, each hit exactly once, one jittered
point per stratum, strata permuted independently per dimension. Antithetic variates: Hammersley & Morton (1956);
here pair i and i + n/2 are mirrored (u -> 1 - u) on the named dominant parameters and the strata are paired
(s, n-1-s) so the sample stays an exact LHS. Common random numbers: the seed of an environment stream depends on
(base seed, member index, stream name) only, never on the vehicle, so every vehicle in member m sees the same draws.
"""
from __future__ import annotations

import hashlib
import math
import pathlib
from typing import Any

import numpy as np
from scipy import stats

PERTURBATIONS = pathlib.Path(__file__).resolve().parents[3] / "config" / "perturbations.yaml"


def marginal(spec: dict[str, Any]) -> Any:
    """Frozen scipy distribution from {"dist": normal|lognormal|uniform|truncnorm, ...}.

    normal: mean, sd. lognormal: median, sigma (log-space sd). uniform: lo, hi. truncnorm: mean, sd, lo, hi (a direct-call
    distribution: `to_marginals` does not build it from perturbations.yaml, and `marginal` does not check the numbers; `check_entry` does).
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


ELL_MIN, ELL_MAX = 1e-200, 1e200                                    # m: inside these 1/ell and x*k of the random field stay finite (1e-310: NaN fields)
DISTS = ("normal", "lognormal", "uniform", "fixed")             # what a perturbations.yaml entry may be (a "fixed" one is a setting, not sampled)
# The entries every reader indexes by name (stage1.FORCING and ACTS, perturb.PerturbedEnv, config.env_sigmas); `usv_vpp_bias_brief` is the stage-1b case's, read
# only when that case runs, where stage1.check_case names it if it is absent.
REQUIRED = ("wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "hs_scale", "tp_bias", "current_correlation_length",
            "bulk_stress_scale", "glider_speed_scale", "usv_vpp_bias", "battery_capacity_scale")
# What the stage-1 code does with a sampled prior x as a speed factor: a FRACTION is read as 1 + x (stage1._run_usv: the USV flies at that factor of its
# polar), a FACTOR as x itself. A speed factor is positive, whatever the prior says; `SUPPORT_SD` standard deviations is where a normal is taken to end.
FRACTIONS = ("usv_vpp_bias", "usv_vpp_bias_brief")
FACTORS = ("current_speed_scale", "hs_scale", "bulk_stress_scale", "glider_speed_scale", "battery_capacity_scale")
SUPPORT_SD = 6.0
BIG = 1e300                                                         # a sampled value stays inside +-BIG (a lognormal above 1/BIG); floats end at 1.8e308


def _num(x: Any) -> bool:
    """A finite real number: not a bool (YAML `true` is an int to isinstance), a string, None, NaN or infinity."""
    try:
        return isinstance(x, (int, float, np.number)) and not isinstance(x, bool) and bool(np.isfinite(x))
    except (OverflowError, TypeError):                              # an integer too large for a float
        return False


def _check_range(k: str, e: dict[str, Any]) -> None:
    """A sampled prior (normal, lognormal, uniform) stays finite over its whole support: a lognormal's `median * exp(+-SUPPORT_SD * sigma)` inside
    (1/BIG, BIG), a normal's `mean +- SUPPORT_SD sd` and a uniform's `hi - lo` finite. Otherwise `marginal(...).ppf` gives inf or 0 for a member (a
    sigma of 1000 gave Hs factors of inf: round 14, M-9, the unbounded priors). Only finiteness: how large a plausible sd is stays a lab number (row 456)."""
    d = e["dist"]
    if d == "lognormal":
        mid, half = math.log(e.get("median", 1.0)), SUPPORT_SD * e["value"]
        ok, what = abs(mid) + half < math.log(BIG), f"median * exp(+-{SUPPORT_SD:g} sigma) = exp({mid:g} +- {half:g})"
    elif d == "normal":
        mid, half = float(e.get("mean", 0.0)), SUPPORT_SD * float(e["value"])
        ok, what = math.isfinite(mid + half) and math.isfinite(mid - half), f"mean +- {SUPPORT_SD:g} sd = {mid:g} +- {half:g}"
    elif d == "uniform":
        ok, what = math.isfinite(float(e["hi"]) - float(e["lo"])), f"hi - lo = {e['hi']!r} - {e['lo']!r}"
    else:
        return
    if not ok:
        raise ValueError(f"perturbation {k!r}: the {d} prior reaches {what}, which is not a finite float (a lognormal: inside "
                         f"1/{BIG:g} to {BIG:g}); a member would be inf or 0. Check the units")


def _check_factor(k: str, e: dict[str, Any]) -> None:
    """The limit physics gives a speed-like prior (`FRACTIONS`, `FACTORS`): the factor it makes is > 0 over the whole support, so the vehicle never flies
    backwards or with a negative Hs. A fraction is also a fraction and not a percent (-30 to -35 typed for -0.30 to -0.35: round 14, M-9), so no number of
    it reaches 1 in size. Called by `check_entry` once the numbers are known finite. A lognormal is positive (and `_check_range` keeps it a finite, non-zero
    float); the support of a uniform ends at lo, of a normal SUPPORT_SD sd below the mean."""
    one = 1.0 if k in FRACTIONS else 0.0
    if one:
        for f in ("lo", "hi", "mean", "median") + (("value",) if e["dist"] == "normal" else ()):
            if f in e and _num(e[f]) and abs(e[f]) >= 1:
                raise ValueError(f"perturbation {k!r}: {f} is {e[f]!r}; this prior is a fraction of speed (the speed factor is 1 + x, so -0.3 is 30 % slower), "
                                 f"not a percent: write -0.3 for -30 %")
    low = {"uniform": lambda: e["lo"], "normal": lambda: e.get("mean", 0.0) - SUPPORT_SD * e["value"]}.get(e["dist"])
    if low is not None and one + low() <= 0:
        raise ValueError(f"perturbation {k!r}: the {'speed factor 1 + x' if one else 'factor x'} reaches {one + low():g} or less at the low end of the "
                         f"{e['dist']} prior ({'lo' if e['dist'] == 'uniform' else f'mean - {SUPPORT_SD:g} sd'} = {low():g}); a speed factor must stay > 0"
                         f"{', and a fraction is not a percent' if one else ''}")


def check_entry(k: str, e: Any) -> None:
    """Refuse a perturbations.yaml entry (or a fitted prior that replaces one) that would give NaN members or a raw traceback, naming it.

    A mapping with `dist` one of DISTS; normal and lognormal: `value` a finite sd > 0, `mean` (normal) finite and `median` (lognormal) finite > 0
    when given; uniform: finite `lo` < `hi`; fixed: `mean`, the setting itself, finite and > 0 when given. `current_correlation_length` is always
    checked, whatever its dist: it must be fixed with a mean in (ELL_MIN, ELL_MAX), the length the random-field generator divides by (NaN fields,
    a ZeroDivisionError, numpy's 'scale < 0', a KeyError 'mean' for a normal or uniform one, NaN for a mean of 1e-310; round 13, look-ahead L1 and the
    merge look-ahead). A sampled prior is also checked by `_check_range` (finite over its support: no inf or 0 member) and one of `FRACTIONS` or
    `FACTORS` by `_check_factor` (a speed factor > 0, a fraction not a percent; round 14, M-9).
    The one check, called by `load_perturbations` for every entry and by `to_marginals` for the entries it builds.
    """
    if not isinstance(e, dict):
        raise ValueError(f"perturbation {k!r}: an entry is a mapping (dist, value, unit, citation, kind), not {e!r}")
    d = e.get("dist")
    if d not in DISTS:
        raise ValueError(f"perturbation {k!r}: dist is {d!r}, not one of {', '.join(DISTS)}")
    if k == "current_correlation_length":                           # a length in metres the random field divides by: PerturbedEnv reads priors[k]["mean"]
        if d != "fixed":
            raise ValueError(f"perturbation {k!r}: dist is {d!r}; it is a fixed setting (dist fixed, with mean), not sampled: the random field reads its mean")
        m: Any = e.get("mean")
        if not (_num(m) and ELL_MIN < m < ELL_MAX):
            raise ValueError(f"perturbation {k!r}: the fixed setting (mean) is {m!r}; it is a length the random field divides by: finite and > 0, "
                             f"between {ELL_MIN:g} and {ELL_MAX:g} m so that 1/length stays a finite float")
    elif d in ("normal", "lognormal"):
        if not (_num(e.get("value")) and e["value"] > 0):
            raise ValueError(f"perturbation {k!r}: the sd is {e.get('value')!r}; a {d} prior needs a finite sd > 0 (scipy turns 0 into NaN members)")
        loc = "mean" if d == "normal" else "median"
        if loc in e and not (_num(e[loc]) and (d == "normal" or e[loc] > 0)):
            raise ValueError(f"perturbation {k!r}: the {loc} is {e[loc]!r}; a {d} prior needs a finite {loc}{' > 0' if d == 'lognormal' else ''}")
    elif d == "uniform":
        lo: Any = e.get("lo")
        hi: Any = e.get("hi")
        if not (_num(lo) and _num(hi) and lo < hi):
            raise ValueError(f"perturbation {k!r}: a uniform prior needs finite numbers lo < hi, got lo {lo!r} and hi {hi!r}")
    elif "mean" in e:                                               # any other fixed setting that gives a mean
        if not (_num(e["mean"]) and e["mean"] > 0):
            raise ValueError(f"perturbation {k!r}: the fixed setting (mean) is {e['mean']!r}; it must be finite and > 0")
    _check_range(k, e)
    if k in FRACTIONS + FACTORS:
        _check_factor(k, e)


def load_perturbations(path: str | pathlib.Path | None = None) -> dict[str, dict[str, Any]]:
    """Read config/perturbations.yaml; every entry must carry value, unit, citation and kind: prior (sourced) or assumed, and pass `check_entry`, and every
    entry of `REQUIRED` must be there (a deleted one was a KeyError at the first reader; round 14, M-13)."""
    from ..config import ConfigError, read_yaml                     # the strict reader: a repeated key or a leading-zero number is refused, as in every stage
    p = path or PERTURBATIONS
    cfg: dict[str, dict[str, Any]] = read_yaml(p)
    if not isinstance(cfg, dict) or not cfg:
        raise ConfigError(f"{p}: expected a mapping of perturbation entries, found {'nothing' if not cfg else type(cfg).__name__}")
    for k, e in cfg.items():
        if not isinstance(e, dict):
            check_entry(k, e)                                       # names the entry; the fields below need a mapping
        miss = {"value", "unit", "citation", "kind"} - e.keys()
        if miss or e["kind"] not in ("prior", "assumed"):              # assumed: no source, listed in the credibility report
            raise ValueError(f"perturbation {k!r}: missing {sorted(miss)} or kind not prior/assumed")
        check_entry(k, e)
    gone = [k for k in REQUIRED if k not in cfg]
    if gone:
        raise ValueError(f"perturbation {gone[0]!r}: missing from {p}" + (f" (and {', '.join(map(repr, gone[1:]))})" if gone[1:] else ""))
    return cfg


def to_marginals(cfg: dict[str, dict[str, Any]], names: list[str] | None = None) -> dict[str, dict[str, Any]]:
    """perturbations.yaml entries -> marginal specs for `lhs` (the `value` field is sd / sigma).

    Entries with dist "fixed" are settings (e.g. a correlation length), not sampled: they are skipped when `names` is empty or None, and a named one
    raises ValueError ("not a sampled parameter").
    """
    out = {}
    for k in names or list(cfg):
        e = cfg[k]
        check_entry(k, e)
        d = e["dist"]
        if d == "fixed" and not names:
            continue
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
