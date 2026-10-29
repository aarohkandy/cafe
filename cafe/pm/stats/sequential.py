"""Sequential stopping for a vehicle's ensemble: Wald's SPRT with an indifference region, and the interval rule.

SPRT: Wald (1945, Ann. Math. Stat. 16). H0: P(fail) = p0 against H1: P(fail) = p1 (p0 < p1); after k failures in n runs
LLR = k ln(p1/p0) + (n-k) ln((1-p1)/(1-p0)); accept H1 at LLR >= ln((1-beta)/alpha), accept H0 at LLR <= ln(beta/(1-alpha)).
The indifference region (p0, p1) around a cut-off is Younes & Simmons (2006, Information and Computation 204):
true P(fail) inside it may go either way; outside it the error rates are alpha (wrongly says no-go) and beta.
"accept_go" means H0 (P(fail) low); "accept_nogo" means H1 (P(fail) high). Test one cut-off at a time: GO cut 0.10,
NO-GO cut 0.40 (see intervals.py), e.g. `sprt_indifference(0.10, 0.05)` -> (0.05, 0.15).
"""
from __future__ import annotations

import math
from typing import Any

from . import intervals


def sprt_indifference(cut: float, delta: float) -> tuple[float, float]:
    """(p0, p1) = (cut - delta, cut + delta): the indifference region around a P(fail) cut-off."""
    return cut - delta, cut + delta


def sprt_decide(k: int, n: int, p0: float, p1: float, alpha: float = 0.05, beta: float = 0.05) -> str:
    """"accept_go" | "accept_nogo" | "continue" for k failures in n runs."""
    if not 0 < p0 < p1 < 1:
        raise ValueError("need 0 < p0 < p1 < 1")
    llr = k * math.log(p1 / p0) + (n - k) * math.log((1 - p1) / (1 - p0))
    if llr >= math.log((1 - beta) / alpha):
        return "accept_nogo"
    if llr <= math.log(beta / (1 - alpha)):
        return "accept_go"
    return "continue"


def ensemble_stop(k_fail: int, n: int, conf: float = 0.95, n_min: int = 0, n_max: int | None = None) -> dict[str, Any]:
    """Called by Stage 1 between batches. Stop when the Wilson/Agresti-Coull interval is wholly inside GO or NO-GO.

    `n_min` (73 outside --budget quick) stops it ending before the certifying size; `n_max` is the budget cap and ends
    the ensemble with whatever `intervals.verdict` says. Repeated looks at a fixed-sample interval inflate its error
    rate slightly; the interval is wide (conf 0.95) and the SPRT above is the test with controlled error.
    """
    region = intervals.interval_region(k_fail, n, conf) if n >= n_min else None
    if region:
        return dict(stop=True, verdict=region, reason="interval inside " + region)
    if n_max is not None and n >= n_max:
        return dict(stop=True, verdict=intervals.verdict(k_fail, n)["verdict"], reason="n_max reached")
    return dict(stop=False, verdict=None, reason="interval straddles a cut-off")
