"""cafe.pm.stats pinned to closed forms, hand-worked cases and exact return values, so that a flipped sign, a swapped bound, a shifted
index or a renamed result key in any of them fails a test. (tests/test_stats.py checks the statistics; these check the arithmetic.)"""
import hashlib
import inspect
import math

import numpy as np
import pytest
import yaml
from scipy import stats as sp

from cafe.pm.stats import intervals as I, rare, sampling as S, sensitivity as SE, sequential as Q


SEED_7_3_WIND = 11906533915989906240


def default(fn, name):
    return inspect.signature(fn).parameters[name].default


# ---- intervals ----------------------------------------------------------------------------------------------------------
def test_documented_defaults():
    assert default(I.wilson, "conf") == default(I.agresti_coull, "conf") == default(I.interval, "conf") == 0.95
    assert default(I.newcombe_diff, "conf") == default(I.interval_region, "conf") == default(I.decided_region, "conf") == 0.95
    assert default(I.coverage, "conf") == 0.95 and default(I.coverage, "method") == "wilson"
    assert (default(I.verdict, "conf"), default(I.verdict, "level"), default(I.verdict, "cert_conf")) == (0.90, 0.05, 0.95)
    assert (default(I.n_certify, "level"), default(I.n_certify, "conf"), default(I.n_certify_one_sided, "conf")) == (0.05, 0.95, 0.95)
    assert default(Q.ensemble_stop, "conf") == Q.STOP_CONF == 0.95 and default(Q.ensemble_stop, "n_min") == 0
    assert (default(Q.sprt_decide, "alpha"), default(Q.sprt_decide, "beta")) == (0.05, 0.05)


@pytest.mark.parametrize("n,conf", [(1, 0.95), (7, 0.8), (40, 0.99), (200, 0.9), (1000, 0.95)])
def test_wilson_ends_are_exact_and_the_interval_is_inside_0_1(n, conf):
    assert I.wilson(0, n, conf)[0] == 0.0 and I.wilson(n, n, conf)[1] == 1.0
    for k in range(n + 1):
        lo, hi = I.wilson(k, n, conf)
        assert 0.0 <= lo <= hi <= 1.0


def test_wilson_upper_bound_never_exceeds_one_even_in_floating_point():
    for n in (10 ** 3, 10 ** 6, 10 ** 9, 10 ** 12):
        assert I.wilson(n - 1, n)[1] <= 1.0 and I.agresti_coull(n - 1, n)[1] <= 1.0


def test_wilson_worked_case_k0_n10_is_z2_over_n_plus_z2():
    """Zero events: the upper bound is z^2/(n + z^2) (the closed form behind n_certify)."""
    z = sp.norm.ppf(0.975)
    assert I.wilson(0, 10)[1] == pytest.approx(z * z / (10 + z * z), rel=1e-12) and I.wilson(0, 10)[0] == 0.0


def test_agresti_coull_clips_at_zero_and_one():
    assert I.agresti_coull(0, 5)[0] == 0.0 and I.agresti_coull(5, 5)[1] == 1.0


def test_interval_is_wilson_at_every_n_and_forwards_conf():
    """M-5: one interval at every n, so the printed bound, interval_region, the stopper and n_certify cannot disagree."""
    assert not hasattr(I, "SWITCH_N")
    for n in (3, 40, 41, 73, 200):
        for conf in (0.8, 0.9, 0.95):
            assert I.interval(n // 4, n, conf) == (*I.wilson(n // 4, n, conf), "wilson")
    assert I.interval(3, 41, 0.9)[:2] != I.interval(3, 41)[:2]


def test_zero_failure_bound_crosses_five_percent_exactly_at_n_certify():
    """M-5: Agresti-Coull above 40 printed 0.0599 at n = 73 while n_certify() says 73 certifies 5 %."""
    need = I.n_certify()
    assert need == 73 and I.interval(0, 73)[1] < 0.05 <= I.interval(0, 72)[1]
    assert all((I.interval(0, n)[1] < 0.05) == (n >= need) for n in range(1, 301))
    assert all(I.interval_region(0, n) == "GO" for n in range(40, 80))         # was undecided from n = 41 (upper bound 0.1021)
    assert Q.ensemble_stop(0, 41)["stop"] is True and Q.ensemble_stop(0, 73, n_min=73)["verdict"] == "GO"


@pytest.mark.parametrize("k,n", [(0, 0), (-1, 5), (6, 5), (1, -3)])
def test_interval_rejects_each_bad_pair_with_the_pair_in_the_message(k, n):
    with pytest.raises(ValueError, match=rf"need 0 <= k <= n and n >= 1, got k={k}, n={n}"):
        I.interval(k, n)


def test_n_certify_and_rule_of_three_closed_forms():
    assert I.rule_of_three(30) == 0.1 and I.rule_of_three(60) == 0.05
    z2 = sp.norm.ppf(0.975) ** 2
    assert I.n_certify() == math.floor(z2 * 19) + 1 == 73 and I.n_certify(0.1, 0.9) == math.floor(sp.norm.ppf(0.95) ** 2 * 9) + 1
    assert I.wilson(0, I.n_certify())[1] < 0.05 <= I.wilson(0, I.n_certify() - 1)[1]
    assert I.n_certify_one_sided() == 59 and (1 - 0.05) ** 59 <= 0.05 < (1 - 0.05) ** 58
    assert I.n_certify_one_sided(0.1, 0.9) == 22 and I.n_certify_one_sided(0.05, 0.99) == 90


def test_verdict_from_p_cut_offs_belong_to_the_lower_verdict():
    assert [I.verdict_from_p(p) for p in (0.0, 0.1, 0.1000001, 0.4, 0.4000001, 1.0)] == ["GO", "GO", "MARGINAL", "MARGINAL", "NO-GO", "NO-GO"]


def test_verdict_returns_every_field_with_its_value_zero_failures_below_the_certifying_n():
    v = I.verdict(0, 30)
    hi = I.wilson(0, 30, 0.90)[1]
    assert v == dict(verdict="GO", n=30, k_fail=0, p_fail=0.0, fail_lo=0.0, fail_hi=hi, success_lo=1 - hi, conf=0.90, method="wilson", n_certify=73,
                     note="P(fail) < 3/n = 0.100 at 95% confidence, one-sided (n = 30); 60 members would be needed for that bound to reach 5%. "
                          "The report's certification count, 73, is for the two-sided 95% Wilson upper bound.")
    assert list(v) == ["verdict", "n", "k_fail", "p_fail", "fail_lo", "fail_hi", "success_lo", "conf", "method", "n_certify", "note"]


def test_verdict_with_failures_above_forty_members_has_no_note_and_its_own_confidence():
    v = I.verdict(5, 100, conf=0.95)
    lo, hi = I.wilson(5, 100, 0.95)
    assert v == dict(verdict="GO", n=100, k_fail=5, p_fail=0.05, fail_lo=lo, fail_hi=hi, success_lo=1 - hi, conf=0.95, method="wilson",
                     n_certify=73, note="")
    assert I.verdict(0, 80)["note"] == "" and I.verdict(1, 30)["note"] == ""            # a note only for zero failures below the certifying n
    assert I.verdict(0, 72)["note"] != "" and I.verdict(0, 73)["note"] == ""
    w = I.verdict(0, 20, level=0.1, cert_conf=0.9)
    assert w["n_certify"] == I.n_certify(0.1, 0.9) and "reach 10%" in w["note"] and "two-sided 90% Wilson" in w["note"] and "30 members" in w["note"]


def test_verdict_rules_p_and_lower_success_bound():
    assert I.verdict(1, 10)["verdict"] == "MARGINAL" and I.verdict(1, 10)["p_fail"] == 0.1          # p = 0.9 but the lower bound is below 0.75
    assert I.verdict(3, 10)["verdict"] == "MARGINAL" and I.verdict(4, 10)["verdict"] == "MARGINAL"   # p = 0.7, 0.6: marginal down to 0.6
    assert I.verdict(5, 10)["verdict"] == "NO-GO"                                                    # p = 0.5
    assert I.verdict(0, 100)["verdict"] == "GO" and I.verdict(100, 100)["verdict"] == "NO-GO"
    v = I.verdict(10, 100)                                                                           # p = 0.90 exactly meets the first condition
    assert v["success_lo"] == 1 - v["fail_hi"] and (v["success_lo"] >= 0.75) == (v["verdict"] == "GO")


def test_interval_region_reads_the_whole_interval_at_the_given_confidence():
    assert I.interval_region(0, 100) == "GO" and I.interval_region(100, 100) == "NO-GO" and I.interval_region(10, 100) is None
    assert I.interval_region(0, 80, conf=0.5) == "GO" and I.interval_region(0, 80, conf=0.999) is None          # conf reaches the interval
    assert I.interval_region(45, 100, conf=0.5) == "NO-GO" and I.interval_region(45, 100) is None
    assert I.interval_region(55, 100) == "NO-GO" and I.interval_region(55, 100, conf=0.999) is None
    assert (I.interval(0, 29)[1] > 0.10) and I.interval_region(0, 29) is None and I.interval_region(0, 100) == "GO"        # hi must be <= 0.10


def test_decided_region_marginal_needs_the_whole_interval_between_the_cut_offs():
    assert I.decided_region(0, 100) == "GO" and I.decided_region(100, 100) == "NO-GO" and I.decided_region(10, 100) is None
    assert I.decided_region(150, 400, conf=0.5) == "MARGINAL" and I.decided_region(150, 400) is None
    assert I.decided_region(50, 400, conf=0.5) == "MARGINAL" and I.decided_region(50, 400, conf=0.999) is None
    assert I.decided_region(25, 400, conf=0.5) == "GO" and I.decided_region(55, 100) == "NO-GO"
    lo, hi, _ = I.interval(150, 400, 0.5)
    assert I.P_FAIL_GO < lo and hi <= I.P_FAIL_NOGO


def test_newcombe_difference_symmetry_and_published_value():
    lo, hi = I.newcombe_diff(56, 70, 48, 80)                                                         # Newcombe 1998 Table II, example 1
    assert (round(lo, 4), round(hi, 4)) == (0.0524, 0.3339)
    a, b = I.newcombe_diff(20, 50, 10, 40), I.newcombe_diff(10, 40, 20, 50)
    assert a[0] == pytest.approx(-b[1], abs=1e-12) and a[1] == pytest.approx(-b[0], abs=1e-12)
    lo90, hi90 = I.newcombe_diff(20, 50, 10, 40, 0.90)
    assert lo90 > a[0] and hi90 < a[1]                                                               # a lower confidence is a narrower interval
    assert I.newcombe_diff(5, 10, 5, 10)[0] < 0 < I.newcombe_diff(5, 10, 5, 10)[1]


def test_coverage_is_the_binomial_mass_of_the_k_whose_interval_holds_p():
    p = np.array([0.1, 0.3, 0.5])
    for method, f in (("wilson", I.wilson), ("agresti_coull", I.agresti_coull)):
        got = I.coverage(10, p, method=method)
        want = [sum(sp.binom.pmf(k, 10, q) for k in range(11) if f(k, 10)[0] <= q <= f(k, 10)[1]) for q in p]
        assert got == pytest.approx(want, abs=1e-12)
    assert I.coverage(10, p, conf=0.5) != pytest.approx(I.coverage(10, p), abs=1e-3)
    assert I.coverage(1, np.array([0.5])).shape == (1,)
    edge_lo, edge_hi = I.wilson(1, 4)[0], I.wilson(0, 4)[1]                                          # a p exactly on an interval end is covered
    assert I.coverage(4, np.array([edge_lo]))[0] >= sp.binom.pmf(1, 4, edge_lo) - 1e-12
    assert I.coverage(4, np.array([edge_hi]))[0] >= sp.binom.pmf(0, 4, edge_hi) - 1e-12


# ---- sequential ---------------------------------------------------------------------------------------------------------
def test_sprt_indifference_is_cut_minus_and_plus_delta():
    assert Q.sprt_indifference(0.10, 0.05) == pytest.approx((0.05, 0.15), abs=1e-15) and Q.sprt_indifference(0.4, 0.1) == pytest.approx((0.3, 0.5))


@pytest.mark.parametrize("p0,p1", [(0.0, 0.5), (0.5, 0.5), (0.6, 0.5), (0.2, 1.0), (0.2, 2.0), (-0.1, 0.5)])
def test_sprt_rejects_each_bad_pair_of_hypotheses(p0, p1):
    with pytest.raises(ValueError, match=r"need 0 < p0 < p1 < 1"):
        Q.sprt_decide(1, 5, p0, p1)


def test_sprt_exact_boundaries_accept_at_equality_and_wald_thresholds_are_used():
    """p0 = 1/4, p1 = 3/4, alpha = beta = 1/4: LLR = (2k - n) ln 3 and both thresholds are +-ln 3, hit exactly at n = 1 and n = 3."""
    kw = dict(p0=0.25, p1=0.75, alpha=0.25, beta=0.25)
    assert Q.sprt_decide(1, 1, **kw) == "accept_nogo" and Q.sprt_decide(0, 1, **kw) == "accept_go"
    assert Q.sprt_decide(2, 3, **kw) == "accept_nogo" and Q.sprt_decide(1, 3, **kw) == "accept_go"
    assert Q.sprt_decide(1, 2, **kw) == "continue"
    # asymmetric errors move the two thresholds independently: ln((1 - beta)/alpha) and ln(beta/(1 - alpha))
    assert Q.sprt_decide(1, 1, 0.25, 0.75, alpha=0.01, beta=0.25) == "continue" and Q.sprt_decide(1, 1, 0.25, 0.75, alpha=0.25, beta=0.99) == "accept_nogo"
    assert Q.sprt_decide(0, 1, 0.25, 0.75, alpha=0.25, beta=0.01) == "continue" and Q.sprt_decide(0, 1, 0.25, 0.75, alpha=0.99, beta=0.25) == "accept_go"
    assert Q.sprt_decide(0, 1, 0.25, 0.75, alpha=0.01, beta=0.25) == "continue" and Q.sprt_decide(1, 1, 0.25, 0.75, alpha=0.25, beta=0.01) == "continue"


def test_sprt_follows_the_defaults_alpha_beta_0_05():
    p0, p1 = Q.sprt_indifference(0.10, 0.05)
    assert Q.sprt_decide(0, 30, p0, p1) == "accept_go" and Q.sprt_decide(0, 20, p0, p1) == "continue"
    assert Q.sprt_decide(8, 20, p0, p1) == "accept_nogo" and Q.sprt_decide(2, 20, p0, p1) == "continue"
    assert 20 * math.log((1 - p1) / (1 - p0)) > math.log(0.05 / 0.95) > 30 * math.log((1 - p1) / (1 - p0))


def test_ensemble_stop_fields_reasons_and_the_n_min_n_max_rules():
    go = Q.ensemble_stop(0, 100)
    assert go == dict(stop=True, verdict="GO", reason="interval inside GO") and list(go) == ["stop", "verdict", "reason"]
    assert Q.ensemble_stop(100, 100) == dict(stop=True, verdict="NO-GO", reason="interval inside NO-GO")
    assert Q.ensemble_stop(20, 100) == dict(stop=False, verdict=None, reason="interval straddles a cut-off")
    assert Q.ensemble_stop(0, 100, n_min=101)["stop"] is False and Q.ensemble_stop(0, 100, n_min=100)["stop"] is True       # n_min is inclusive
    cap = Q.ensemble_stop(20, 100, n_max=100)
    assert cap == dict(stop=True, verdict=I.verdict(20, 100)["verdict"], reason="n_max reached")
    assert Q.ensemble_stop(20, 100, n_max=101)["stop"] is False and Q.ensemble_stop(20, 100, n_max=0)["reason"] == "n_max reached"
    assert Q.ensemble_stop(0, 100, conf=0.5) == dict(stop=True, verdict="GO", reason="interval inside GO")
    assert Q.ensemble_stop(0, 30, conf=0.999)["stop"] is False
    assert Q.ensemble_stop(0, 100, n_min=0, n_max=None)["stop"] is True


# ---- sampling -----------------------------------------------------------------------------------------------------------
def test_marginals_default_to_standard_location_and_scale():
    assert S.marginal(dict(dist="normal", sd=2.0)).ppf(0.5) == 0.0 and S.marginal(dict(dist="normal", mean=3.0, sd=2.0)).ppf(0.5) == 3.0
    assert S.marginal(dict(dist="normal", mean=3.0, sd=2.0)).std() == 2.0
    assert S.marginal(dict(dist="lognormal", sigma=0.5)).ppf(0.5) == pytest.approx(1.0, rel=1e-12)
    assert S.marginal(dict(dist="lognormal", sigma=0.5, median=4.0)).ppf(0.5) == pytest.approx(4.0, rel=1e-12)
    assert S.marginal(dict(dist="lognormal", sigma=0.5, median=4.0)).ppf(0.8413447460685429) == pytest.approx(4.0 * math.exp(0.5), rel=1e-9)
    u = S.marginal(dict(dist="uniform", lo=2.0, hi=5.0))
    assert u.ppf(0.0) == 2.0 and u.ppf(1.0) == 5.0 and u.mean() == 3.5


def test_truncated_normal_median_is_the_closed_form_and_its_support_is_lo_hi():
    spec = dict(dist="truncnorm", mean=1.0, sd=2.0, lo=-1.0, hi=4.0)
    d = S.marginal(spec)
    a, b = (-1.0 - 1.0) / 2.0, (4.0 - 1.0) / 2.0
    assert d.ppf(0.0) == pytest.approx(-1.0, abs=1e-12) and d.ppf(1.0) == pytest.approx(4.0, abs=1e-12)
    assert d.ppf(0.5) == pytest.approx(1.0 + 2.0 * sp.norm.ppf((sp.norm.cdf(a) + sp.norm.cdf(b)) / 2), rel=1e-9)
    z = S.marginal(dict(dist="truncnorm", sd=1.0, lo=-1.0, hi=3.0))                                   # mean defaults to 0
    assert z.ppf(0.5) == pytest.approx(sp.norm.ppf((sp.norm.cdf(-1.0) + sp.norm.cdf(3.0)) / 2), rel=1e-9) and z.ppf(0.0) == pytest.approx(-1.0)


def test_unknown_distribution_is_named():
    with pytest.raises(ValueError, match=r"unknown distribution 'weibull'"):
        S.marginal(dict(dist="weibull"))


def test_load_perturbations_names_the_entry_and_the_missing_fields(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(dict(a=dict(value=1, unit="m", kind="prior"))))
    with pytest.raises(ValueError, match=r"perturbation 'a': missing \['citation'\] or kind not prior/assumed"):
        S.load_perturbations(p)
    p.write_text(yaml.safe_dump(dict(a=dict(value=1, unit="m", citation="x", kind="guess"))))
    with pytest.raises(ValueError, match=r"perturbation 'a': missing \[\] or kind not prior/assumed"):
        S.load_perturbations(p)
    p.write_text(yaml.safe_dump(dict(yaml.safe_load(S.PERTURBATIONS.read_text()),                       # the required entries are there (round 14, M-13)
                                     a=dict(dist="normal", value=1, unit="m", citation="x", kind="assumed"),
                                     b=dict(dist="normal", value=2, unit="s", citation="y", kind="prior")), sort_keys=False))
    assert list(S.load_perturbations(p))[-2:] == ["a", "b"] and S.load_perturbations(str(p))["b"]["value"] == 2


FIELDS = dict(unit="m", citation="c", kind="prior")


@pytest.mark.parametrize("entry, words", [
    (3, r"perturbation 'e': an entry is a mapping .*not 3"),
    (dict(value=1.0), r"perturbation 'e': dist is None, not one of normal, lognormal, uniform, fixed"),
    (dict(dist="weibull", value=1.0), r"perturbation 'e': dist is 'weibull'"),
    (dict(dist="truncnorm", value=1.0, lo=-1, hi=1), r"perturbation 'e': dist is 'truncnorm'"),
    (dict(dist="uniform", lo=2.0, hi=1.0, value=0.0), r"perturbation 'e': a uniform prior needs finite numbers lo < hi, got lo 2.0 and hi 1.0"),
    (dict(dist="uniform", lo=1.0, hi=1.0, value=0.0), r"lo < hi, got lo 1.0 and hi 1.0"),
    (dict(dist="uniform", hi=1.0, value=0.0), r"got lo None and hi 1.0"),
    (dict(dist="uniform", lo=0.0, value=0.0), r"got lo 0.0 and hi None"),
    (dict(dist="uniform", lo=float("nan"), hi=1.0, value=0.0), r"lo nan"),
    (dict(dist="uniform", lo=0.0, hi=float("inf"), value=0.0), r"hi inf"),
    (dict(dist="uniform", lo=True, hi=2.0, value=0.0), r"lo True"),
    (dict(dist="uniform", lo="0", hi=2.0, value=0.0), r"lo '0'"),
    (dict(dist="normal", value=True), r"perturbation 'e': the sd is True; a normal prior needs a finite sd > 0"),
    (dict(dist="lognormal", value=True), r"the sd is True; a lognormal prior"),
    (dict(dist="normal", value=10 ** 400), r"a normal prior needs a finite sd > 0"),
    (dict(dist="normal", value=1.0, mean=float("nan")), r"perturbation 'e': the mean is nan; a normal prior needs a finite mean$"),
    (dict(dist="normal", value=1.0, mean="0"), r"the mean is '0'"),
    (dict(dist="lognormal", value=0.3, median=0.0), r"perturbation 'e': the median is 0.0; a lognormal prior needs a finite median > 0$"),
    (dict(dist="lognormal", value=0.3, median=float("inf")), r"the median is inf"),
])
def test_one_check_refuses_every_entry_that_would_give_nan_members_or_a_traceback(tmp_path, entry, words):
    """Round 13, M-28. These were an AttributeError, a KeyError, NaN members from `lhs` (a reversed uniform), a bool read as an sd of 1, or a
    ZeroDivisionError; now a ValueError naming the entry, from `load_perturbations` and from `to_marginals` (a fitted prior bypasses the file)."""
    with pytest.raises(ValueError, match=words):
        S.check_entry("e", entry)
    with pytest.raises(ValueError, match=words):
        S.to_marginals({"e": entry}, ["e"])
    if isinstance(entry, dict):
        p = tmp_path / "p.yaml"
        p.write_text(yaml.safe_dump(dict(good=dict(dist="fixed", value=0.0, **FIELDS), e=dict(entry, **FIELDS))))
        with pytest.raises(ValueError, match=words):
            S.load_perturbations(p)
    else:
        p = tmp_path / "p.yaml"
        p.write_text(yaml.safe_dump(dict(e=entry)))
        with pytest.raises(ValueError, match=words):
            S.load_perturbations(p)


def test_to_marginals_checks_every_entry_it_builds_by_default_and_only_the_named_ones_otherwise():
    cfg = dict(ok=dict(dist="normal", value=1.0), bad=dict(dist="uniform", lo=2.0, hi=1.0))
    with pytest.raises(ValueError, match="perturbation 'bad'"):
        S.to_marginals(cfg)
    assert list(S.to_marginals(cfg, ["ok"])) == ["ok"]
    with pytest.raises(ValueError, match="perturbation 'nodist'"):
        S.to_marginals(dict(nodist=dict(value=1.0)))


@pytest.mark.parametrize("text, words", [("", r"p\.yaml: expected a mapping of perturbation entries, found nothing"),
                                         ("{}", r"found nothing"),
                                         ("- 1\n- 2\n", r"found list"),
                                         ("foo: 3\n", r"perturbation 'foo': an entry is a mapping .*not 3")])
def test_load_perturbations_refuses_an_empty_file_or_one_that_is_not_a_mapping_of_mappings(tmp_path, text, words):
    p = tmp_path / "p.yaml"
    p.write_text(text)
    with pytest.raises(ValueError, match=words):
        S.load_perturbations(p)


def test_a_valid_uniform_with_a_nonzero_value_and_a_numpy_number_still_load_and_the_shipped_file_passes_unchanged():
    S.check_entry("u", dict(dist="uniform", lo=np.float64(-1.0), hi=np.int64(2), value=5.0))                 # `value` is unused for a uniform: not checked
    S.check_entry("n", dict(dist="normal", value=np.float64(2.0), mean=np.int64(-3)))
    S.check_entry("f", dict(dist="fixed", value=0.0))
    cfg = S.load_perturbations()
    for k, e in cfg.items():
        S.check_entry(k, e)
    assert len(cfg) == 12 and sorted({e["dist"] for e in cfg.values()}) == ["fixed", "lognormal", "normal", "uniform"]


def test_to_marginals_maps_value_to_sd_or_sigma_and_defaults_the_location():
    cfg = dict(n1=dict(dist="normal", value=2.0), n2=dict(dist="normal", value=2.0, mean=5.0), l1=dict(dist="lognormal", value=0.3),
               l2=dict(dist="lognormal", value=0.3, median=7.0), u=dict(dist="uniform", value=0, lo=1.0, hi=2.0), f=dict(dist="fixed", value=9))
    out = S.to_marginals(cfg)
    assert out == dict(n1=dict(dist="normal", mean=0.0, sd=2.0), n2=dict(dist="normal", mean=5.0, sd=2.0),
                       l1=dict(dist="lognormal", median=1.0, sigma=0.3), l2=dict(dist="lognormal", median=7.0, sigma=0.3),
                       u=dict(dist="uniform", lo=1.0, hi=2.0))
    assert list(S.to_marginals(cfg, ["l2", "n1"])) == ["l2", "n1"]
    with pytest.raises(ValueError, match=r"'f' has dist 'fixed': not a sampled parameter"):
        S.to_marginals(cfg, ["f"])


def test_lhs_unit_jitters_every_cell_independently_and_is_seeded():
    u = S.lhs_unit(50, 3, np.random.default_rng(1))
    frac = (u * 50) % 1.0
    assert len(np.unique(np.round(frac, 12))) == 150 and frac.min() >= 0 and frac.max() < 1 and u.shape == (50, 3)
    assert np.array_equal(u, S.lhs_unit(50, 3, np.random.default_rng(1))) and not np.array_equal(u, S.lhs_unit(50, 3, np.random.default_rng(2)))


def test_antithetic_pairs_flip_independently_and_carry_a_fresh_jitter():
    n = 200
    u = S.lhs_unit(n, 2, np.random.default_rng(3), antithetic=(1,))
    first_half_high = np.sum(u[:n // 2, 1] >= 0.5)
    assert 30 < first_half_high < 70 and np.allclose(u[n // 2:, 1], 1 - u[:n // 2, 1])
    assert len(np.unique(np.round((u[:n // 2, 1] * n) % 1.0, 12))) == n // 2                      # a fresh jitter per pair
    assert np.array_equal(np.sort(np.floor(u[:, 1] * n).astype(int)), np.arange(n)) and np.array_equal(np.sort(np.floor(u[:, 0] * n).astype(int)), np.arange(n))
    with pytest.raises(ValueError, match=r"antithetic pairs need an even n"):
        S.lhs_unit(5, 1, np.random.default_rng(0), antithetic=(0,))
    assert S.lhs_unit(5, 1, np.random.default_rng(0)).shape == (5, 1)                                # odd n is fine without antithetics


def test_lhs_is_deterministic_in_its_seed_and_the_default_seed_is_zero():
    params = dict(a=dict(dist="normal", sd=1.0), b=dict(dist="uniform", lo=0.0, hi=1.0))
    u0, x0 = S.lhs(20, params)
    u1, x1 = S.lhs(20, params, seed=0)
    assert np.array_equal(u0, u1) and np.array_equal(x0["a"], x1["a"]) and np.array_equal(u0, S.lhs_unit(20, 2, np.random.default_rng(0)))
    assert not np.array_equal(u0, S.lhs(20, params, seed=1)[0])
    assert np.array_equal(x0["a"], sp.norm.ppf(u0[:, 0])) and np.array_equal(x0["b"], u0[:, 1])
    ua, _ = S.lhs(20, params, seed=4, antithetic=("b",))
    assert np.allclose(ua[10:, 1], 1 - ua[:10, 1]) and not np.allclose(ua[10:, 0], 1 - ua[:10, 0])


def test_stratification_report_of_the_centred_grid_and_of_the_left_edges():
    centred = (np.arange(10) + 0.5)[:, None] / 10
    r = S.stratification_report(centred)
    assert r == dict(n=10, d=1, strata_exact=True, ks_d_max=pytest.approx(0.05), ks_bound=0.1, ok=True)
    assert list(r) == ["n", "d", "strata_exact", "ks_d_max", "ks_bound", "ok"]
    assert isinstance(r["ks_d_max"], float) and isinstance(r["strata_exact"], bool) and isinstance(r["ok"], bool)
    edge = np.arange(10)[:, None] / 10                                                               # KS distance exactly 1/n: still ok
    assert S.stratification_report(edge)["ok"] is True and S.stratification_report(edge)["ks_d_max"] == pytest.approx(0.1)
    two = np.hstack([centred, centred[::-1]])
    assert S.stratification_report(two)["d"] == 2
    bad = centred.copy()
    bad[1, 0] = bad[0, 0]                                                                            # two points in one stratum
    rb = S.stratification_report(bad)
    assert rb["strata_exact"] is False and rb["ok"] is False
    shifted = np.hstack([centred, np.full((10, 1), 0.05)])
    assert S.stratification_report(shifted)["ok"] is False and S.stratification_report(shifted)["ks_d_max"] > 0.5


def test_marginal_report_is_the_ks_distance_of_each_column_to_its_marginal():
    params = dict(a=dict(dist="uniform", lo=0.0, hi=2.0))
    x = {"a": np.array([0.5, 1.5])}
    assert S.marginal_report(x, params) == {"a": pytest.approx(0.25)}


def test_stream_ids_member_seeds_and_generators_are_pinned():
    assert S._stream_id("wind") == int.from_bytes(hashlib.sha256(b"wind").digest()[:8], "big") and S._stream_id("wind") < 2 ** 64
    assert S._stream_id("wind") != S._stream_id("wave")
    seq = np.random.SeedSequence(entropy=7, spawn_key=(3, S._stream_id("wind")))
    assert S.member_seed(7, 3, "wind") == int(seq.generate_state(1, np.uint64)[0]) == SEED_7_3_WIND
    assert S.member_seed(7, 3, "wave") != S.member_seed(7, 4, "wind") != S.member_seed(8, 3, "wind")
    assert np.array_equal(S.member_rng(7, 3, "wind").standard_normal(5), np.random.default_rng(seq).standard_normal(5))
    assert not np.array_equal(S.member_rng(7, 3, "wind").standard_normal(5), S.member_rng(7, 3, "wave").standard_normal(5))


# ---- sensitivity --------------------------------------------------------------------------------------------------------
def easi_reference(x, y, m, correct=True):
    """EASI from the definition: sort by x, even ranks ascending then odd ranks descending, power share of harmonics 1..m."""
    n, d = x.shape
    y = np.asarray(y, float) - np.mean(y)
    out = []
    for i in range(d):
        o = np.argsort(x[:, i], kind="stable")
        seq = y[np.concatenate([o[0::2], o[1::2][::-1]])]
        power = np.abs(np.fft.rfft(seq)) ** 2
        s = 2 * power[1:m + 1].sum() / (2 * power[1:(n - 1) // 2 + 1].sum() + (power[n // 2] if n % 2 == 0 else 0))
        lam = 2 * m / n
        out.append(min(max(s - lam / (1 - lam) * (1 - s) if correct else s, 0.0), 1.0))
    return np.array(out)


def sample(n=64, d=3, seed=1):
    rng = np.random.default_rng(seed)
    x = rng.random((n, d))
    return x, np.sin(2 * math.pi * x[:, 0]) + 0.5 * x[:, 1] + 0.1 * rng.standard_normal(n)


@pytest.mark.parametrize("m", [1, 2, 6])
@pytest.mark.parametrize("correct", [True, False])
def test_first_order_matches_a_reimplementation_from_the_definition(m, correct):
    x, y = sample()
    assert SE.first_order(x, y, m, correct) == pytest.approx(easi_reference(x, y, m, correct), abs=1e-12)


def test_first_order_defaults_clip_and_offset_invariance():
    assert default(SE.first_order, "harmonics") is default(SE.noise_floor, "harmonics") is default(SE.dominant, "harmonics") is None
    assert default(SE.first_order, "correct") is True and default(SE.noise_floor, "perms") == 2000 and default(SE.noise_floor, "level") == 0.95
    assert default(SE.noise_floor, "seed") == 0
    x, y = sample()
    s = SE.first_order(x, y)
    assert np.array_equal(s, SE.first_order(x, y, SE.default_harmonics(len(x)), True))
    assert s == pytest.approx(SE.first_order(x, y + 1000.0), abs=1e-9)
    assert s == pytest.approx(SE.first_order(x, 3 * y), abs=1e-9)
    assert s.min() >= 0 and s.max() <= 1 and s[0] > 0.5 > s[2]
    assert np.all(SE.first_order(x, np.full(64, 5.0)) == 0.0) and SE.first_order(x, np.full(64, 5.0)).shape == (3,)
    assert SE.first_order(x[:, :1], y).shape == (1,)


def test_first_order_uses_a_stable_sort_so_ties_in_x_keep_their_order():
    x = np.array([[0.0], [0.0], [1.0], [1.0], [2.0], [2.0], [3.0], [3.0]])
    y = np.array([4.0, 1.0, 3.0, 8.0, 2.0, 7.0, 6.0, 5.0])
    assert SE.first_order(x, y, 2, False) == pytest.approx(easi_reference(x, y, 2, False), abs=1e-12)


def test_first_order_of_a_response_that_is_a_pure_harmonic_of_the_sorted_x_is_one_before_the_correction():
    n = 64
    x = (np.arange(n) + 0.5)[:, None] / n
    y = np.cos(2 * math.pi * np.arange(n) / n)                                 # after reordering this is (nearly) one harmonic only
    s_raw = SE.first_order(x, y, harmonics=2, correct=False)[0]
    assert 0.5 < s_raw <= 1.0 and SE.first_order(x, y, harmonics=2, correct=True)[0] <= 1.0


def test_noise_floor_is_the_level_quantile_of_the_permuted_maxima():
    x, y = sample(40, 3, 2)
    rng = np.random.default_rng(5)
    null = [SE.first_order(x, rng.permutation(y), 4).max() for _ in range(30)]
    assert SE.noise_floor(x, y, perms=30, level=0.9, seed=5, harmonics=4) == pytest.approx(float(np.quantile(null, 0.9)), abs=1e-12)
    assert SE.noise_floor(x, y, perms=30, seed=5) != SE.noise_floor(x, y, perms=30, seed=6)
    assert SE.noise_floor(x, y, perms=30, seed=5) == SE.noise_floor(x, y, perms=30, seed=5)
    assert SE.noise_floor(x, y, perms=30, seed=5, harmonics=2) != SE.noise_floor(x, y, perms=30, seed=5, harmonics=6)
    ints = np.arange(40) % 2
    assert SE.noise_floor(x, ints, perms=10, seed=1) == pytest.approx(SE.noise_floor(x, ints.astype(float), perms=10, seed=1), abs=1e-15)


def test_dominant_names_the_largest_s1_only_above_the_floor_and_checks_the_names():
    x, y = sample(128, 3, 4)
    name, s, floor = SE.dominant(["a", "b", "c"], x, y)
    assert name == "a" and list(s) == ["a", "b", "c"] and all(isinstance(v, float) for v in s.values())
    assert list(s.values()) == pytest.approx(list(SE.first_order(x, y, 6)), abs=1e-15) and floor == SE.noise_floor(x, y, harmonics=6)
    n2, _, f2 = SE.dominant(["a", "b", "c"], x, y, harmonics=3)
    assert f2 == SE.noise_floor(x, y, harmonics=3) and f2 != floor and n2 == "a"
    s3 = SE.first_order(x, y, 3)
    assert dict(zip("abc", s3, strict=True)) == pytest.approx(SE.dominant(list("abc"), x, y, 3)[1], abs=1e-15)
    rng = np.random.default_rng(0)
    assert SE.dominant(["a", "b", "c"], rng.random((32, 3)), rng.standard_normal(32))[0] is None
    with pytest.raises(ValueError):
        SE.dominant(["a"], x, y)                                                                          # one name for three columns
    assert SE.dominant(["c", "b", "a"], x, y)[0] == "c"                                                   # the first name goes with the first column


# ---- rare ---------------------------------------------------------------------------------------------------------------
class Scripted:
    """A rng whose draws are fixed, so that a Metropolis step can be worked by hand."""

    def __init__(self, normal, uniform):
        self.normal, self.uniform = normal, uniform

    def standard_normal(self, shape):
        return np.full(shape, self.normal)

    def random(self, shape):
        return np.full(shape, self.uniform)


def test_gamma_matches_the_hand_worked_chain_correlation():
    ind = np.array([[1, 0], [1, 1], [0, 1], [1, 1]])                                 # 4 samples per chain, 2 chains: p = 3/4, r0 = 3/16
    assert rare._gamma(ind) == pytest.approx(-1.0, abs=1e-12)                        # rho_k = -1/3 for k = 1, 2, 3; 2 (3/4 + 1/2 + 1/4)(-1/3) = -1
    assert rare._gamma(np.ones((5, 3), bool)) == 0.0 and rare._gamma(np.zeros((5, 3), bool)) == 0.0
    perfect = np.array([[1, 0]] * 6)                                                  # chain 0 always in F, chain 1 never: fully correlated in time
    assert rare._gamma(perfect) == pytest.approx(2 * sum(1 - k * 2 / 12 for k in range(1, 6)), abs=1e-12)


def test_gamma_agrees_with_au_and_beck_eq_29_30_on_random_indicators():
    rng = np.random.default_rng(0)
    for ns, nc in ((4, 3), (7, 2), (10, 5)):
        ind = rng.random((ns, nc)) < 0.4
        n, p = ns * nc, ind.mean()
        r0 = p * (1 - p)
        rho = []
        for k in range(1, ns):
            s = sum(int(ind[i, j]) * int(ind[i + k, j]) for j in range(nc) for i in range(ns - k))
            rho.append((s / (n - k * nc) - p * p) / r0)
        assert rare._gamma(ind) == pytest.approx(2 * sum((1 - k * nc / n) * r for k, r in enumerate(rho, 1)), abs=1e-12)


def test_mma_moves_by_width_times_the_normal_draw_and_returns_length_samples():
    u, g = np.array([[0.0], [1.0]]), np.array([0.0, 1.0])
    us, gs = rare._mma(u, g, -100.0, lambda c: c[:, 0], Scripted(2.0, 0.0), 4, 0.5)
    assert us.shape == (4, 2, 1) and gs.shape == (4, 2)
    assert np.allclose(us[:, :, 0], np.array([[0.0, 1.0], [1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])) and np.allclose(gs, us[:, :, 0])
    assert np.array_equal(us[0], u) and np.array_equal(gs[0], g)                      # the first sample of a chain is its seed


def test_mma_accepts_a_component_when_the_uniform_is_below_the_density_ratio_and_not_at_equality():
    fn = lambda c: np.zeros(len(c))
    u = np.array([[1.0]])
    stay, _ = rare._mma(u, np.zeros(1), -1.0, fn, Scripted(-2.0, 1.0), 2, 1.0)        # cand = -1: ratio exp(0) = 1, uniform 1.0: strict < rejects
    assert stay[1, 0, 0] == 1.0
    move, _ = rare._mma(u, np.zeros(1), -1.0, fn, Scripted(-2.0, 0.999), 2, 1.0)
    assert move[1, 0, 0] == -1.0
    capped, _ = rare._mma(np.array([[2.0]]), np.zeros(1), -1.0, fn, Scripted(-2.0, 1.5), 2, 1.0)      # ratio e^2 is capped at 1: uniform 1.5 never accepts
    assert capped[1, 0, 0] == 2.0
    toward, _ = rare._mma(np.array([[2.0]]), np.zeros(1), -1.0, fn, Scripted(-2.0, 0.5), 2, 1.0)
    assert toward[1, 0, 0] == 0.0
    away, _ = rare._mma(np.array([[0.0]]), np.zeros(1), -1.0, fn, Scripted(2.0, 0.5), 2, 1.0)           # cand = 2: ratio exp(-2) = 0.135 < 0.5: rejected
    assert away[1, 0, 0] == 0.0


def test_mma_keeps_the_chain_inside_the_failure_set_and_accepts_exactly_on_the_threshold():
    fn = lambda c: c[:, 0]
    u, g = np.array([[0.0]]), np.array([0.0])
    on, gon = rare._mma(u, g, 1.0, fn, Scripted(1.0, 0.0), 3, 1.0)                    # g(cand) == b exactly: still in F_i
    assert np.allclose(on[:, 0, 0], [0.0, 1.0, 2.0]) and np.allclose(gon[:, 0], [0.0, 1.0, 2.0])
    off, goff = rare._mma(u, g, 1.5, fn, Scripted(1.0, 0.0), 3, 1.0)                  # g(cand) = 1 < 1.5: the whole move is refused
    assert np.allclose(off[:, 0, 0], 0.0) and np.allclose(goff[:, 0], 0.0)
    mixed, gm = rare._mma(np.array([[0.0], [5.0]]), np.array([0.0, 5.0]), 3.0, fn, Scripted(1.0, 0.0), 2, 1.0)
    assert np.allclose(mixed[1, :, 0], [0.0, 6.0]) and np.allclose(gm[1], [0.0, 6.0])


def test_subset_simulation_signature_defaults():
    p = inspect.signature(rare.subset_simulation).parameters
    assert (p["n"].default, p["p0"].default, p["seed"].default, p["max_levels"].default, p["width"].default) == (1000, 0.1, 0, 20, 1.0)


def test_subset_simulation_with_an_event_that_is_not_rare_is_plain_monte_carlo():
    g = lambda u: u[:, 0]
    n, seed, target = 400, 3, 0.5
    r = rare.subset_simulation(g, 1, target, n=n, seed=seed)
    frac = float(np.mean(np.random.default_rng(seed).standard_normal((n, 1))[:, 0] >= target))
    assert r == dict(p=frac, cov=pytest.approx(math.sqrt((1 - frac) / (frac * n))), levels=[target], n_evals=n, converged=True)
    sure = rare.subset_simulation(g, 1, -50.0, n=100, seed=seed)
    assert sure == dict(p=1.0, cov=0.0, levels=[-50.0], n_evals=100, converged=True)


def test_subset_simulation_rounds_n_to_a_multiple_of_the_chain_count():
    r = rare.subset_simulation(lambda u: u[:, 0], 1, -50.0, n=107, p0=0.1, seed=2)      # round(10.7) = 11 chains of 107 // 11 = 9
    assert r["n_evals"] == 99


def test_subset_simulation_uses_the_realised_level_probability_in_the_cov_and_the_product(monkeypatch):
    """Round 13, M-34. n = 1000, p0 = 0.3 gives 300 chains of 3 = 900 samples, so the level probability is 300/900 = 1/3, not 0.3: the c.o.v. term
    (1 - q)/(q n) used 0.3 (0.002593) while the probability used 1/3 (0.002222). Chains held constant and the chain correlation set to 0, so the
    answer is a closed form: level 0 and the final level each add (2/3)/((1/3) 900)."""
    x = np.sort(np.random.default_rng(5).standard_normal((900, 1))[:, 0])[::-1]                  # the first draw of subset_simulation(seed=5): 900 samples
    target = 0.5 * (x[99] + x[100])                                                              # between the 100th and 101st of the 300 seeds
    monkeypatch.setattr(rare, "_gamma", lambda ind: 0.0)
    monkeypatch.setattr(rare, "_mma", lambda u, g, b, fn, rng, length, width: (np.repeat(u[None], length, 0), np.repeat(g[None], length, 0)))
    r = rare.subset_simulation(lambda u: u[:, 0], 1, target, n=1000, p0=0.3, seed=5)
    assert r["converged"] is True and len(r["levels"]) == 2
    assert r["p"] == pytest.approx(1 / 9, rel=1e-12)                                              # (300/900) * (300 of 900 samples at or above the target)
    assert r["cov"] == pytest.approx(math.sqrt(2 * (2 / 3) / ((1 / 3) * 900)), rel=1e-12)
    assert r["cov"] != pytest.approx(math.sqrt((1 - 0.3) / (0.3 * 900) + (2 / 3) / ((1 / 3) * 900)), rel=1e-3)      # the nominal-p0 term it replaced


@pytest.mark.parametrize("n, p0, words", [(4, 0.1, "0 seeds and chains of length 0"), (10, 0.04, "0 seeds"), (10, 0.6, "6 seeds and chains of length 1"),
                                          (5, 0.9, "4 seeds and chains of length 1")])
def test_subset_simulation_refuses_an_n_and_p0_that_leave_no_seed_or_a_chain_of_one(n, p0, words):
    """n = 4 with p0 = 0.1 rounds to no seed (ZeroDivisionError); a chain of length 1 is an IndexError on `order[nc]`."""
    with pytest.raises(ValueError, match=words):
        rare.subset_simulation(lambda u: u[:, 0], 1, 1.0, n=n, p0=p0)
    assert rare.subset_simulation(lambda u: u[:, 0], 1, -50.0, n=10, p0=0.5)["n_evals"] == 10        # 5 seeds of chains of 2: the smallest that runs


def test_subset_simulation_pinned_two_level_run():
    r = rare.subset_simulation(lambda u: u[:, 0], 1, 2.5, n=200, seed=3)
    assert r["converged"] is True
    assert r["n_evals"] == 560
    assert r["p"] == pytest.approx(0.0041, rel=1e-12)
    assert r["cov"] == pytest.approx(0.43665008377114367, rel=1e-9)
    assert r["levels"] == pytest.approx([1.387835253675902, 2.2828661922404923, 2.5], rel=1e-12)
    assert list(r) == ["p", "cov", "levels", "n_evals", "converged"] and isinstance(r["levels"][0], float) and isinstance(r["cov"], float)
    assert abs(r["p"] - sp.norm.sf(2.5)) < 3 * r["p"] * r["cov"] + 1e-3


def test_subset_simulation_pinned_run_with_other_p0_and_width():
    r = rare.subset_simulation(lambda u: u[:, 0], 1, 2.5, n=200, seed=3, p0=0.2, width=0.5)
    assert r["converged"] is True
    assert r["n_evals"] == 520
    assert r["p"] == pytest.approx(0.0102, rel=1e-9)
    assert r["cov"] == pytest.approx(0.3602470957711304, rel=1e-9)
    assert r["levels"] == pytest.approx([0.8442612088388082, 1.7019619732445643, 2.5], rel=1e-12)
    two = rare.subset_simulation(lambda u: u[:, 0], 1, 1.5, n=200, seed=3)
    assert two["levels"][-1] == 1.5 and len(two["levels"]) == 2 and two["converged"] is True
    # the c.o.v. of the p0^m part alone: (1 - p0)/(p0 n) per level, more with chain correlation
    assert two["cov"] > math.sqrt((1 - 0.1) / (0.1 * 200))


def test_subset_simulation_gives_up_on_ties_and_on_too_few_levels():
    r = rare.subset_simulation(lambda u: np.zeros(len(u)), 1, 1.0, n=100, seed=1)
    assert r == dict(p=0.0, cov=float("inf"), levels=[0.0], n_evals=190, converged=False)
    short = rare.subset_simulation(lambda u: u[:, 0], 1, 6.0, n=100, seed=1, max_levels=2)
    assert short["converged"] is False and short["p"] == 0.0 and short["cov"] == float("inf") and len(short["levels"]) == 2
    assert short["n_evals"] == 100 + 2 * 9 * 10
    assert rare.subset_simulation(lambda u: u[:, 0], 1, 6.0, n=100, seed=1)["converged"] is True
    none = rare.subset_simulation(lambda u: u[:, 0], 1, 6.0, n=100, seed=1, max_levels=0)
    assert none == dict(p=0.0, cov=float("inf"), levels=[], n_evals=100, converged=False)


def test_default_harmonics_scale_with_the_member_count():
    """M-23: six harmonics at 32 members put the permutation floor at 0.53-0.60; the default is min(6, max(2, n // 16))."""
    assert [SE.default_harmonics(n) for n in (8, 31, 32, 47, 48, 64, 95, 96, 1000)] == [2, 2, 2, 2, 3, 4, 5, 6, 6]
    x, y = sample(32, 3, 4)
    assert np.array_equal(SE.first_order(x, y), SE.first_order(x, y, 2))
    assert SE.noise_floor(x, y, perms=30) == SE.noise_floor(x, y, perms=30, harmonics=2)


def test_noise_floor_at_32_members_is_about_a_third_not_a_half():
    """M-23, measured: x uniform (32, 10), y with 4, 8 or 16 ones. Six harmonics gave 0.595, 0.556, 0.535; the default gives about 0.30."""
    rng = np.random.default_rng(0)
    x = rng.random((32, 10))
    for ones in (4, 8, 16):
        y = np.r_[np.ones(ones), np.zeros(32 - ones)]
        floor = SE.noise_floor(x, y, perms=200)
        assert 0.2 < floor < 0.42 and SE.noise_floor(x, y, perms=200, harmonics=6) > 0.5


def test_subset_simulation_takes_the_chain_correlation_on_the_new_threshold_at_every_level(monkeypatch):      # round 7, M-26
    calls = []
    real = rare._gamma

    def spy(ind):
        calls.append((float(ind.mean()), real(ind)))
        return calls[-1][1]
    monkeypatch.setattr(rare, "_gamma", spy)
    rare.subset_simulation(lambda u: u[:, 0], 1, 3.5, n=1000, seed=1)
    assert len(calls) >= 3
    assert calls[0][0] < 1.0 and calls[0][1] != 0.0                      # the first intermediate level: not the all-ones indicator of the old threshold
    assert all(m < 1.0 for m, _ in calls)


def test_subset_simulation_cov_is_not_far_below_the_empirical_one():      # round 7, M-26: 2.5 x too low before the fix
    est = [rare.subset_simulation(lambda u: u[:, 0], 1, 3.5, n=500, seed=s) for s in range(40)]
    ps = np.array([e["p"] for e in est])
    assert np.mean([e["cov"] for e in est]) * 1.8 > ps.std() / ps.mean()


# ---------------------------------------------------------------------------------------------------------- round 13, look-ahead L1
@pytest.mark.parametrize("mean", [math.nan, math.inf, 0, 0.0, -5, True, "100", None])
def test_r13_l1_a_fixed_correlation_length_that_is_nan_zero_or_negative_is_refused_where_every_reader_sees_it(tmp_path, mean):
    """`check_entry` had no branch for dist 'fixed', so `current_correlation_length` with mean .nan (all-NaN current fields), 0 (ZeroDivisionError) or
    -5 (numpy's 'scale < 0') loaded with no word. The setting is a length the random-field generator divides by."""
    words = r"perturbation 'current_correlation_length': the fixed setting \(mean\) is .*finite and > 0"
    e = dict(dist="fixed", mean=mean, value=0.0, **FIELDS)
    with pytest.raises(ValueError, match=words):
        S.check_entry("current_correlation_length", e)
    cfg = yaml.safe_load(S.PERTURBATIONS.read_text())
    cfg["current_correlation_length"] = e
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match=words):
        S.load_perturbations(p)


def test_r13_l1_a_fixed_correlation_length_must_be_given_and_any_other_fixed_setting_is_checked_only_when_it_has_a_mean():
    with pytest.raises(ValueError, match=r"the fixed setting \(mean\) is None"):
        S.check_entry("current_correlation_length", dict(dist="fixed", value=0.0))
    S.check_entry("other_setting", dict(dist="fixed", value=0.0))                       # a fixed entry with no mean that no code divides by stays valid
    with pytest.raises(ValueError, match=r"perturbation 'other_setting': the fixed setting"):
        S.check_entry("other_setting", dict(dist="fixed", mean=math.nan, value=0.0))
    S.check_entry("current_correlation_length", dict(dist="fixed", mean=np.float64(5e4), value=0.0))


# ---------------------------------------------------------------------------------------------------------- round 13, merge look-ahead
@pytest.mark.parametrize("entry", [dict(dist="normal", value=1000.0), dict(dist="normal", mean=5e4, value=1000.0),
                                   dict(dist="lognormal", value=0.5), dict(dist="uniform", lo=1.0, hi=2.0, value=0.0),
                                   dict(dist="fixed", mean=1e-310, value=0.0), dict(dist="fixed", mean=1e-320, value=0.0),
                                   dict(dist="fixed", mean=5e-324, value=0.0), dict(dist="fixed", mean=1e300, value=0.0),
                                   dict(dist="fixed", mean=1e-200, value=0.0), dict(dist="fixed", mean=1e200, value=0.0)])
def test_r13_merge_the_correlation_length_is_a_fixed_setting_whose_inverse_is_finite_whatever_the_entry_says(tmp_path, entry):
    """`check_entry` tested the correlation length only inside its 'fixed' branch: a normal or uniform one loaded and `PerturbedEnv` raised KeyError 'mean',
    and a fixed mean of 1e-310 (1/ell is inf) gave NaN current fields."""
    from cafe.pm.env.perturb import Field
    e = dict(entry, **FIELDS)
    words = r"perturbation 'current_correlation_length': (dist is .* fixed setting|the fixed setting \(mean\) is .*finite and > 0)"
    with pytest.raises(ValueError, match=words):
        S.check_entry("current_correlation_length", e)
    cfg = yaml.safe_load(S.PERTURBATIONS.read_text())
    cfg["current_correlation_length"] = e
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match=words):
        S.load_perturbations(p)
    for good in (1e-100, 1e100):                                    # the bound is not tighter than it needs to be: the field is finite inside it
        S.check_entry("current_correlation_length", dict(dist="fixed", mean=good, value=0.0, **FIELDS))
        assert np.isfinite(Field(1, [0, 1], "s", good)(np.zeros((2, 3)) + 1.0, np.zeros((2, 3)) + 2.0)).all()
    S.check_entry("another_normal", dict(dist="normal", value=1000.0, **FIELDS))                        # other entries keep their dist


# ---------------------------------------------------------------------------------------------------------- round 14, M-8, M-9, M-13
def shipped():
    return yaml.safe_load(S.PERTURBATIONS.read_text())


def test_r14_m8_a_named_fixed_entry_is_refused_and_an_unnamed_one_is_left_out():
    """The docstring said fixed entries are left out unless named; a named one reaches the else branch and raises."""
    cfg = S.load_perturbations()
    assert "current_correlation_length" not in S.to_marginals(cfg) and "current_correlation_length" not in S.to_marginals(cfg, [])
    with pytest.raises(ValueError, match="'current_correlation_length' has dist 'fixed': not a sampled parameter"):
        S.to_marginals(cfg, ["current_correlation_length"])
    assert "left out" not in S.to_marginals.__doc__ and "raises ValueError" in S.to_marginals.__doc__


PERCENT = r"perturbation 'usv_vpp_bias': (lo|hi|mean|value) is .*a fraction of speed .* not a percent"
FACTOR1 = r"perturbation 'usv_vpp_bias': the speed factor 1 \+ x reaches .* must stay > 0"


@pytest.mark.parametrize("name", ["usv_vpp_bias", "usv_vpp_bias_brief"])
@pytest.mark.parametrize("entry, words", [
    (dict(dist="uniform", lo=-35.0, hi=-30.0), r"lo is -35.0; this prior is a fraction of speed .* not a percent"),     # the brief's -30 to -35 % as typed
    (dict(dist="uniform", lo=-0.35, hi=30.0), r"hi is 30.0; .* not a percent"),
    (dict(dist="uniform", lo=-1.0, hi=-0.3), r"lo is -1.0; .* not a percent"),                                  # exactly -100 %: the factor 0
    (dict(dist="uniform", lo=0.2, hi=1.0), r"hi is 1.0; .* not a percent"),
    (dict(dist="normal", mean=-30.0, value=2.0), r"mean is -30.0; .* not a percent"),
    (dict(dist="normal", mean=-0.3, value=50.0), r"value is 50.0; .* not a percent"),
    (dict(dist="lognormal", median=50.0, value=0.5), r"median is 50.0; .* not a percent"),                  # a lognormal fraction names its median (round 15 M-7)
    (dict(dist="normal", mean=-0.25, value=0.2), r"the speed factor 1 \+ x reaches -0.45 or less .*mean - 6 sd = -1.45"),      # 6 sd: past -100 %
    (dict(dist="normal", value=0.17), r"mean - 6 sd = -1.02"),                                                  # a normal with the default mean 0
])
def test_r14_m9_a_speed_fraction_must_be_a_fraction_and_keep_its_speed_factor_positive(name, entry, words):
    """`usv_vpp_bias` is read as the factor 1 + x (stage1._run_usv); -35..-30 typed for -0.35..-0.30 made the USV fly at a speed factor of about -30."""
    e = dict(entry, unit="x", citation="c", kind="prior", **({} if "value" in entry else dict(value=0.0)))
    with pytest.raises(ValueError, match=rf"perturbation '{name}': .*{words}"):
        S.check_entry(name, e)
    with pytest.raises(ValueError, match=rf"perturbation '{name}'"):
        S.to_marginals({name: e}, [name])


@pytest.mark.parametrize("entry", [dict(dist="uniform", lo=-0.2565, hi=-0.2280, value=0.0), dict(dist="uniform", lo=-0.35, hi=-0.30, value=0.0),
                                   dict(dist="uniform", lo=-0.99, hi=0.99, value=0.0), dict(dist="normal", mean=-0.25, value=0.1),
                                   dict(dist="normal", mean=-0.25, value=0.12), dict(dist="lognormal", median=0.2, value=0.5)])
def test_r14_m9_what_physics_allows_of_a_speed_fraction_is_allowed(entry):
    """The limits are the factor's, not chosen ranges: 1 + lo > 0 and 1 + mean - 6 sd > 0 (here 1 - 0.25 - 0.72 = 0.03)."""
    S.check_entry("usv_vpp_bias", dict(entry, unit="x", citation="c", kind="prior"))


@pytest.mark.parametrize("name", S.FACTORS)
@pytest.mark.parametrize("entry, words", [
    (dict(dist="uniform", lo=0.0, hi=2.0), r"the factor x reaches 0 or less at the low end of the uniform prior \(lo = 0\)"),
    (dict(dist="uniform", lo=-1.0, hi=2.0), r"factor x reaches -1 or less"),
    (dict(dist="normal", mean=1.0, value=0.2), r"normal prior \(mean - 6 sd = -0.2\)"),
    (dict(dist="normal", value=0.1), r"mean - 6 sd = -0.6"),
])
def test_r14_m9_a_scale_prior_is_a_factor_that_stays_positive_over_its_support(name, entry, words):
    """Sibling of the fraction: `glider_speed_scale`, `hs_scale`, ... multiply a speed or a height as x itself, and `current_speed_scale` takes its log."""
    with pytest.raises(ValueError, match=rf"perturbation '{name}': .*{words}"):
        S.check_entry(name, dict(entry, unit="x", citation="c", kind="prior", **({} if "value" in entry else dict(value=0.0))))


@pytest.mark.parametrize("name", S.FACTORS)
def test_r14_m9_a_positive_scale_prior_of_any_shape_passes(name):
    for e in (dict(dist="lognormal", median=1e-3, value=5.0), dict(dist="uniform", lo=0.5, hi=1.5, value=0.0), dict(dist="normal", mean=1.0, value=0.1)):
        S.check_entry(name, dict(e, unit="x", citation="c", kind="prior"))


@pytest.mark.parametrize("name", S.FACTORS + ("tp_bias",))
@pytest.mark.parametrize("entry", [
    dict(dist="lognormal", value=1000.0), dict(dist="lognormal", median=1e-300, value=0.5), dict(dist="lognormal", median=1e300, value=0.5),
    dict(dist="lognormal", median=1.0, value=116.0), dict(dist="lognormal", median=5e-324, value=0.1),
    dict(dist="normal", mean=1e308, value=1e308), dict(dist="normal", mean=1.0, value=1e308), dict(dist="uniform", lo=-1e308, hi=1e308)])
def test_r14_m9_a_sampled_prior_whose_support_is_not_a_finite_float_is_refused(name, entry):
    """The adversary's repro: hs_scale value 1000 gave ppf [0, 1, inf], so a member's Hs factor was inf; median 1e-300 and 1e300 the same."""
    e = dict(entry, unit="x", citation="c", kind="prior", **({} if "value" in entry else dict(value=0.0)))
    with pytest.raises(ValueError, match=rf"perturbation '{name}': the {entry['dist']} prior reaches .* not a finite float"):
        S.check_entry(name, e)
    with pytest.raises(ValueError, match=rf"perturbation '{name}'"):
        S.to_marginals({name: e}, [name])


@pytest.mark.parametrize("name", S.FACTORS + ("tp_bias",))
def test_r14_m9_a_prior_with_a_large_but_finite_support_stays_allowed_and_its_members_are_finite(name):
    """Only finiteness is refused (row 456: how wide an sd may be is a lab number): sigma 50 and a 1e9 s sd give finite members."""
    e = dict(dist="normal", value=1e9) if name == "tp_bias" else dict(dist="lognormal", median=1.0, value=50.0)         # a normal factor must stay > 0
    e = dict(e, unit="x", citation="c", kind="prior")
    S.check_entry(name, e)
    x = S.marginal(S.to_marginals({name: e})[name]).ppf([1e-6, 0.5, 1 - 1e-6])
    assert np.isfinite(x).all() and (name == "tp_bias" or (x > 0).all())


def test_r14_m9_the_percent_check_does_not_read_a_number_the_other_checks_refuse_and_other_priors_are_not_percent_checked():
    with pytest.raises(ValueError, match="needs finite numbers lo < hi"):
        S.check_entry("usv_vpp_bias", dict(dist="uniform", lo="-35", hi=-30.0))                 # not a TypeError out of abs()
    S.check_entry("usv_vpp_bias", dict(dist="fixed", lo="x", mean=0.3, value=0.0))             # a fixed entry's other fields are nobody's
    S.check_entry("wind_speed_bias", dict(dist="normal", mean=-40.0, value=50.0))              # m/s: a magnitude of 50 is a number, not a percent
    S.check_entry("tp_bias", dict(dist="normal", value=1e9))


def test_r14_m9_the_shipped_priors_pass_every_check_unchanged():
    cfg = S.load_perturbations()
    for k, e in cfg.items():
        S.check_entry(k, e)
    assert (cfg["usv_vpp_bias"]["lo"], cfg["usv_vpp_bias"]["hi"]) == (-0.2565, -0.2280)
    assert (cfg["usv_vpp_bias_brief"]["lo"], cfg["usv_vpp_bias_brief"]["hi"]) == (-0.35, -0.30)
    assert set(S.REQUIRED) | {"usv_vpp_bias_brief"} == set(cfg)


def test_r14_m9_a_percent_in_the_file_is_refused_where_every_reader_sees_it(tmp_path):
    cfg = shipped()
    cfg["usv_vpp_bias"].update(lo=-35, hi=-30)
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match=PERCENT):
        S.load_perturbations(p)


@pytest.mark.parametrize("gone", S.REQUIRED)
def test_r14_m13_a_deleted_required_prior_is_named_where_the_file_is_read(tmp_path, gone):
    """tp_bias gone was a KeyError in config.env_sigmas; current_correlation_length gone loaded and failed at the first environment."""
    cfg = shipped()
    del cfg[gone]
    p = tmp_path / "p.yaml"
    p.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match=rf"perturbation '{gone}': missing from {p}$"):
        S.load_perturbations(p)
    other = "wind_speed_bias" if gone != "wind_speed_bias" else "tp_bias"                  # two gone: the first in REQUIRED's order is named, the rest listed
    del cfg[other]
    p.write_text(yaml.safe_dump(cfg))
    first, second = sorted((gone, other), key=S.REQUIRED.index)
    with pytest.raises(ValueError, match=rf"perturbation '{first}': missing from {p} \(and '{second}'\)$"):
        S.load_perturbations(p)


def test_r14_m13_the_deleted_prior_reaches_env_sigmas_as_that_error_and_the_brief_case_stays_optional(tmp_path, monkeypatch):
    from cafe.pm import config, stage1
    cfg = shipped()
    del cfg["tp_bias"]
    (tmp_path / "perturbations.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(config, "CONFIG", tmp_path)
    with pytest.raises(ValueError, match=r"perturbation 'tp_bias': missing from .*perturbations.yaml"):
        config.env_sigmas()
    cfg = shipped()
    del cfg["usv_vpp_bias_brief"]                                                       # legitimately optional until the sensitivity case runs
    p = tmp_path / "nobrief.yaml"
    p.write_text(yaml.safe_dump(cfg))
    pri = S.load_perturbations(p)
    assert "usv_vpp_bias_brief" not in pri
    with pytest.raises(config.ConfigError, match="prior 'usv_vpp_bias_brief' is not a uniform entry of config/perturbations.yaml"):
        stage1.check_case("usv_vpp_bias_brief", 4, pri)
