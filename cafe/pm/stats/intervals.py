"""Binomial intervals and the GO / MARGINAL / NO-GO verdict for an ensemble of pass/fail members.

Intervals: Wilson (1927) score interval; Agresti & Coull (1998) "add z^2/2" interval; the switch between them follows
Brown, Cai & DasGupta (2001, Statistical Science 16(2), Sec. 5 recommendations): Wilson for n <= 40, Agresti-Coull above.
Difference of two proportions: Newcombe (1998, Statistics in Medicine 17:873-890, method 10), the hybrid score interval built from
the two Wilson intervals (`newcombe_diff`).
Rule of three: Hanley & Lippman-Hand (1983, JAMA 249): with 0 failures in n runs, P(fail) < 3/n at ~95 % one-sided.

Verdict thresholds are those of cafe/mission.py `_verdict` (success rate p, Wilson lower bound lo, both on success):
  GO       p >= 0.90 and lo >= 0.75     (lo is the 90 % two-sided Wilson bound, z = 1.645, as `_rate`)
  NO-GO    p <  0.60
  MARGINAL otherwise.
`interval_region` is the stricter, interval-only reading the sequential stopper uses (BRIEF 2.5): the whole interval on
P(fail) sits at or below 0.10 (GO) or above 0.40 (NO-GO). Interval inside GO implies `verdict` GO, inside NO-GO
implies NO-GO (tested), so stopping never contradicts the final verdict.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.stats import binom, norm

P_FAIL_GO = 0.10        # GO needs success >= 0.9 (mission.py _verdict)
P_FAIL_NOGO = 0.40      # NO-GO is success < 0.6
LO_SUCCESS_GO = 0.75    # GO also needs the Wilson lower bound on success >= 0.75
SWITCH_N = 40           # Brown, Cai & DasGupta 2001: Wilson for n <= 40


def _kappa(conf: float) -> float:
    """Two-sided normal quantile for confidence `conf` (1.95996 for 0.95, 1.64485 for 0.90)."""
    return float(norm.ppf(0.5 + conf / 2))


def wilson(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for k events in n trials."""
    z = _kappa(conf)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (0.0 if k == 0 else max(0.0, c - h)), (1.0 if k == n else min(1.0, c + h))   # exact ends, no float dust


def newcombe_diff(k1: int, n1: int, k2: int, n2: int, conf: float = 0.95) -> tuple[float, float]:
    """Newcombe (1998, Stat. Med. 17:873, method 10) hybrid score interval for p1 - p2, from the Wilson intervals (l, u) of p1 and p2:
    L = d - sqrt((p1 - l1)^2 + (u2 - p2)^2), U = d + sqrt((u1 - p1)^2 + (p2 - l2)^2), d = p1 - p2."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, conf)
    l2, u2 = wilson(k2, n2, conf)
    d = p1 - p2
    return d - math.hypot(p1 - l1, u2 - p2), d + math.hypot(u1 - p1, p2 - l2)


def agresti_coull(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """Agresti-Coull interval: Wald interval around p~ = (k + z^2/2)/(n + z^2)."""
    z = _kappa(conf)
    nt = n + z * z
    pt = (k + z * z / 2) / nt
    h = z * math.sqrt(pt * (1 - pt) / nt)
    return max(0.0, pt - h), min(1.0, pt + h)


def interval(k: int, n: int, conf: float = 0.95) -> tuple[float, float, str]:
    """Wilson for n <= 40, Agresti-Coull above (Brown, Cai & DasGupta 2001). Returns (lo, hi, method)."""
    if n < 1 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n >= 1, got k={k}, n={n}")
    if n <= SWITCH_N:
        return (*wilson(k, n, conf), "wilson")
    return (*agresti_coull(k, n, conf), "agresti-coull")


def rule_of_three(n: int) -> float:
    """Upper bound on P(fail) after n runs with zero failures: 3/n."""
    return 3.0 / n


def n_certify(level: float = 0.05, conf: float = 0.95) -> int:
    """Smallest n whose zero-failure two-sided Wilson upper bound k^2/(n+k^2) is below `level` (73 at 5 %, 95 %)."""
    k2 = _kappa(conf) ** 2
    return int(math.floor(k2 * (1 / level - 1))) + 1


def n_certify_one_sided(level: float = 0.05, conf: float = 0.95) -> int:
    """Smallest n with (1 - level)^n <= 1 - conf: zero failures then rule out P(fail) >= level (59 at 5 %, 95 %)."""
    return math.ceil(math.log(1 - conf) / math.log(1 - level))


def verdict_from_p(p_fail: float) -> str:
    """The verdict implied by a (predicted) P(fail) alone: <= 0.10 GO, > 0.40 NO-GO, else MARGINAL."""
    return "GO" if p_fail <= P_FAIL_GO else "NO-GO" if p_fail > P_FAIL_NOGO else "MARGINAL"


def verdict(k_fail: int, n: int, conf: float = 0.90, level: float = 0.05, cert_conf: float = 0.95) -> dict[str, Any]:
    """GO / MARGINAL / NO-GO for k_fail failures in n members, with the interval and the honest caveat.

    `note` is "P(fail) < 3/n ..." when there are no failures and n is below `n_certify(level, cert_conf)`.
    """
    lo, hi, method = interval(k_fail, n, conf)
    p = (n - k_fail) / n
    v = "GO" if (p >= 1 - P_FAIL_GO and 1 - hi >= LO_SUCCESS_GO) else "MARGINAL" if p >= 1 - P_FAIL_NOGO else "NO-GO"
    need = n_certify(level, cert_conf)
    note = ""
    if k_fail == 0 and n < need:
        note = (f"P(fail) < 3/n = {rule_of_three(n):.3f} (n = {n}; {need} members are needed to certify P(fail) < "
                f"{level:.0%} at {cert_conf:.0%} confidence)")
    return dict(verdict=v, n=n, k_fail=k_fail, p_fail=k_fail / n, fail_lo=lo, fail_hi=hi, success_lo=1 - hi,
                conf=conf, method=method, n_certify=need, note=note)


def interval_region(k_fail: int, n: int, conf: float = 0.95) -> str | None:
    """"GO" if the whole P(fail) interval is <= 0.10, "NO-GO" if it is all > 0.40, else None (undecided)."""
    lo, hi, _ = interval(k_fail, n, conf)
    return "GO" if hi <= P_FAIL_GO else "NO-GO" if lo > P_FAIL_NOGO else None


def decided_region(k_fail: int, n: int, conf: float = 0.95) -> str | None:
    """interval_region, plus "MARGINAL" when the whole P(fail) interval lies above 0.10 and at or below 0.40: a verdict more members would
    not change either. None only when the interval spans a threshold. (The stopper keeps using interval_region: a MARGINAL is not a reason to stop.)"""
    lo, hi, _ = interval(k_fail, n, conf)
    return interval_region(k_fail, n, conf) or ("MARGINAL" if P_FAIL_GO < lo and hi <= P_FAIL_NOGO else None)


def coverage(n: int, p_grid: np.ndarray, conf: float = 0.95, method: str = "wilson") -> np.ndarray:
    """Exact coverage of the interval at each true p: sum of Binomial(n, p) pmf over the k whose interval holds p."""
    f = wilson if method == "wilson" else agresti_coull
    ks = np.arange(n + 1)
    lohi = np.array([f(int(k), n, conf) for k in ks])
    return np.array([binom.pmf(ks, n, p)[(lohi[:, 0] <= p) & (p <= lohi[:, 1])].sum() for p in p_grid])


def receipts() -> list[dict[str, Any]]:
    """Reproduce published numbers; each can fail (a wrong kappa or a wrong formula breaks them)."""
    from statsmodels.stats.proportion import proportion_confint

    from cafe import receipts as R

    n0 = len(R.OUT)
    g = "pm.stats.intervals"
    for k, n, m, name in [(3, 30, "wilson", "wilson"), (7, 200, "agresti_coull", "agresti_coull")]:
        lo, hi = (wilson if m == "wilson" else agresti_coull)(k, n)
        slo, shi = proportion_confint(k, n, alpha=0.05, method=m)
        R.receipt(g, f"{name} lower bound k={k} n={n} vs statsmodels", lo, float(slo), 1e-9, source="statsmodels 0.15 "
                  "proportion_confint", rel=False)
        R.receipt(g, f"{name} upper bound k={k} n={n} vs statsmodels", hi, float(shi), 1e-9, source="statsmodels 0.15 "
                  "proportion_confint", rel=False)
    R.receipt(g, "smallest n certifying P(fail) < 5 % at 95 % (zero-failure Wilson upper bound)", n_certify(), 73, 0,
              source="BRIEF 2.5; Wilson upper bound k^2/(n+k^2)", rel=False)
    R.receipt(g, "zero-failure Wilson upper bound at n=73 is just under 5 %", wilson(0, 73)[1], 0.05, 1e-3,
              source="k^2/(n+k^2), k = 1.95996", rel=False)
    R.receipt(g, "one-sided n for 5 % at 95 % (rule of three region)", n_certify_one_sided(), 59, 0,
              source="(1-0.05)^n <= 0.05; Hanley & Lippman-Hand 1983", rel=False)
    cov = float(np.mean(coverage(40, np.linspace(0.02, 0.98, 97))))
    R.bracket(g, "Wilson mean exact coverage over p at n=40 (nominal 95 %)", cov, 0.93, 0.97,
              source="Brown, Cai & DasGupta 2001 Fig. 4: Wilson oscillates about nominal")
    return R.OUT[n0:]
