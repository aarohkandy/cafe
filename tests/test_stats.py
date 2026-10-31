"""Tests for cafe.pm.stats: intervals, sampling, sequential, sensitivity, rare."""
import math

import numpy as np
import pytest
import yaml
from hypothesis import given, settings, strategies as st
from scipy.stats import norm
from statsmodels.stats.proportion import proportion_confint

from cafe.pm.stats import intervals as I, rare, sampling as S, sensitivity as SE, sequential as Q

kn = st.integers(1, 400).flatmap(lambda n: st.tuples(st.integers(0, n), st.just(n)))


# ---- intervals -----------------------------------------------------------------------------------------------------
@given(kn, st.sampled_from([0.8, 0.9, 0.95, 0.99]))
def test_wilson_and_ac_match_statsmodels(kn_, conf):
    k, n = kn_
    for f, m in ((I.wilson, "wilson"), (I.agresti_coull, "agresti_coull")):
        lo, hi = f(k, n, conf)
        slo, shi = proportion_confint(k, n, alpha=1 - conf, method=m)
        assert math.isclose(lo, max(slo, 0.0), abs_tol=1e-9) and math.isclose(hi, min(shi, 1.0), abs_tol=1e-9)


@given(kn)
def test_interval_properties(kn_):
    k, n = kn_
    lo, hi, method = I.interval(k, n)
    assert 0 <= lo <= k / n <= hi <= 1 or (method == "agresti-coull" and 0 <= lo <= hi <= 1)
    assert method == ("wilson" if n <= 40 else "agresti-coull")
    if k < n:                                       # more failures -> interval moves up
        lo2, hi2, _ = I.interval(k + 1, n)
        assert lo2 >= lo and hi2 >= hi
    lo_w, hi_w = I.wilson(k, n)
    lo_s, hi_s = I.wilson(n - k, n)                 # symmetry p -> 1 - p
    assert math.isclose(lo_w, 1 - hi_s, abs_tol=1e-12) and math.isclose(hi_w, 1 - lo_s, abs_tol=1e-12)


def test_interval_rejects_bad_input():
    for k, n in ((1, 0), (-1, 5), (6, 5)):
        with pytest.raises(ValueError):
            I.interval(k, n)


def test_certifying_n_is_computed_not_assumed():
    assert I.n_certify() == 73 and I.n_certify_one_sided() == 59 and I.rule_of_three(60) == 0.05
    # 73 is the smallest: zero-failure Wilson upper bound k^2/(n+k^2) is < 5 % at 73 and not at 72
    k2 = norm.ppf(0.975) ** 2
    assert k2 / (73 + k2) < 0.05 <= k2 / (72 + k2)
    assert math.isclose(I.wilson(0, 73)[1], k2 / (73 + k2))
    # other levels move it the right way (a change of level or confidence cannot return the same constant)
    assert I.n_certify(0.10) < 73 < I.n_certify(0.01) and I.n_certify(0.05, 0.90) < 73
    assert I.n_certify_one_sided(0.10) < 59 < I.n_certify_one_sided(0.01)
    assert (1 - 0.05) ** 59 <= 0.05 < (1 - 0.05) ** 58


def _legacy_rate(k_ok, n):
    """cafe/mission.py `_rate`/`_verdict` copied verbatim (importing mission pulls the whole app)."""
    p, z = k_ok / n, 1.645
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return p, max(0.0, c - h), min(1.0, c + h)


def _legacy_verdict(p, lo):
    return "GO" if (p >= 0.9 and lo >= 0.75) else "MARGINAL" if p >= 0.6 else "NO-GO"


def test_verdict_equals_existing_app_rule_for_wilson_range():
    for n in range(2, 41):
        for k in range(n + 1):
            p, lo, _ = _legacy_rate(n - k, n)
            assert I.verdict(k, n)["verdict"] == _legacy_verdict(p, lo), (k, n)


def test_verdict_cut_offs():
    assert I.verdict(0, 73)["verdict"] == "GO" and I.verdict(0, 10)["verdict"] == "GO"
    assert I.verdict(1, 10)["verdict"] == "MARGINAL"           # p = 0.9 but the Wilson lower bound is below 0.75
    assert I.verdict(4, 10)["verdict"] == "MARGINAL" and I.verdict(5, 10)["verdict"] == "NO-GO"
    assert I.verdict(10, 100)["verdict"] == "GO" and I.verdict(12, 100)["verdict"] == "MARGINAL"
    assert I.verdict(40, 100)["verdict"] == "MARGINAL"
    assert I.verdict(41, 100)["verdict"] == "NO-GO"
    assert [I.verdict_from_p(p) for p in (0.0, 0.1, 0.11, 0.4, 0.41)] == ["GO", "GO", "MARGINAL", "MARGINAL", "NO-GO"]


def test_verdict_note_only_for_zero_failures_below_certifying_n():
    v = I.verdict(0, 30)
    assert "P(fail) < 3/n" in v["note"] and "73" in v["note"] and "0.100" in v["note"]
    assert I.verdict(0, 73)["note"] == "" and I.verdict(0, 72)["note"] != "" and I.verdict(1, 30)["note"] == ""
    assert I.verdict(0, 59, level=0.05, cert_conf=0.90)["note"] == "" and I.verdict(2, 50)["fail_hi"] > 0.04


@given(kn)
@settings(max_examples=300)
def test_stopping_region_never_contradicts_verdict(kn_):
    k, n = kn_
    r = I.interval_region(k, n)
    if r:
        assert I.verdict(k, n)["verdict"] == r


def test_newcombe_method_10_reproduces_table_ii_of_newcombe_1998():
    """Newcombe 1998 (Stat. Med. 17:873-890) Table II, 56/70 against 48/80: difference 0.2, method 10 interval 0.0524 to 0.3339."""
    lo, hi = I.newcombe_diff(56, 70, 48, 80)
    assert (round(lo, 4), round(hi, 4)) == (0.0524, 0.3339)


@given(kn, kn, st.sampled_from([0.9, 0.95, 0.995]))
def test_newcombe_difference_interval_properties(a, b, conf):
    (k1, n1), (k2, n2) = a, b
    lo, hi = I.newcombe_diff(k1, n1, k2, n2, conf)
    d = k1 / n1 - k2 / n2
    assert -1 - 1e-12 <= lo <= d <= hi <= 1 + 1e-12
    rlo, rhi = I.newcombe_diff(k2, n2, k1, n1, conf)
    assert math.isclose(rlo, -hi, abs_tol=1e-12) and math.isclose(rhi, -lo, abs_tol=1e-12)
    wide = I.newcombe_diff(k1, n1, k2, n2, 0.999)
    assert wide[0] <= lo + 1e-12 and hi <= wide[1] + 1e-12


def test_newcombe_excludes_0_for_a_clear_gap_and_holds_it_for_equal_counts():
    assert I.newcombe_diff(0, 32, 16, 32)[1] < 0 < I.newcombe_diff(16, 32, 0, 32)[0]
    assert I.newcombe_diff(4, 32, 1, 32)[0] < 0 < I.newcombe_diff(4, 32, 1, 32)[1]
    lo, hi = I.newcombe_diff(7, 50, 7, 50)
    assert lo < 0 < hi and math.isclose(lo, -hi)


def test_the_stopper_and_the_report_share_one_confidence():
    import inspect
    assert Q.STOP_CONF == 0.95 and inspect.signature(Q.ensemble_stop).parameters["conf"].default == Q.STOP_CONF


def test_decided_region_adds_a_marginal_whose_whole_interval_is_between_the_thresholds():
    assert I.decided_region(40, 200) == "MARGINAL" and I.interval_region(40, 200) is None    # Wilson 95 %: 0.150 to 0.261
    assert I.decided_region(0, 100) == "GO" and I.decided_region(80, 100) == "NO-GO"
    assert I.decided_region(4, 32) is None and I.decided_region(16, 32) is None               # span 0.10 / span 0.40
    for k in range(201):                                                                      # a decided MARGINAL is always the MARGINAL verdict
        if I.decided_region(k, 200) == "MARGINAL":
            assert I.verdict(k, 200)["verdict"] == "MARGINAL"


def test_interval_region_cases():
    assert I.interval_region(0, 100) == "GO" and I.interval_region(0, 10) is None
    assert I.interval_region(80, 100) == "NO-GO" and I.interval_region(20, 100) is None


def test_coverage_of_wilson_near_nominal_and_a_wrong_kappa_is_caught():
    c = I.coverage(40, np.linspace(0.05, 0.95, 19))
    assert 0.90 < c.mean() < 0.98 and c.min() > 0.85
    assert I.coverage(30, np.array([0.3]), method="agresti_coull")[0] > 0.9


def test_intervals_receipts_pass_and_fail_when_kappa_is_wrong(monkeypatch):
    from cafe import receipts as R

    R.OUT.clear()
    rs = I.receipts()
    assert len(rs) >= 8 and all(r["ok"] for r in rs)
    monkeypatch.setattr(I, "_kappa", lambda conf: 1.0)             # z = 1, not 1.96
    R.OUT.clear()
    assert not all(r["ok"] for r in I.receipts())
    R.OUT.clear()


# ---- sampling ------------------------------------------------------------------------------------------------------
PARAMS = dict(w=dict(dist="normal", mean=1.0, sd=2.0), h=dict(dist="lognormal", median=1.0, sigma=0.15),
              u=dict(dist="uniform", lo=-3, hi=5), t=dict(dist="truncnorm", mean=0.0, sd=1.0, lo=-1.0, hi=2.0))


@given(st.integers(2, 200), st.integers(1, 6), st.integers(0, 10 ** 6))
def test_lhs_unit_is_exact_stratified(n, d, seed):
    u = S.lhs_unit(n, d, np.random.default_rng(seed))
    assert u.shape == (n, d) and (u >= 0).all() and (u < 1).all()
    for j in range(d):
        assert sorted(np.floor(u[:, j] * n).astype(int)) == list(range(n))
    assert S.stratification_report(u)["ok"]


def test_marginals_and_quantiles():
    u, x = S.lhs(256, PARAMS, seed=1)
    assert all(v <= 1 / 256 + 1e-12 for v in S.marginal_report(x, PARAMS).values())
    assert abs(x["w"].mean() - 1.0) < 0.05 and abs(x["w"].std() - 2.0) < 0.1
    assert abs(np.median(x["h"]) - 1.0) < 0.02 and x["t"].min() >= -1 and x["t"].max() <= 2 and x["u"].min() >= -3
    with pytest.raises(ValueError):
        S.marginal(dict(dist="cauchy"))


def test_stratification_report_catches_a_broken_sample():
    u = S.lhs_unit(50, 3, np.random.default_rng(0))
    assert S.stratification_report(u)["ok"]
    bad = u.copy()
    bad[0, 1] = bad[1, 1]                                           # two points in one stratum
    assert not S.stratification_report(bad)["strata_exact"] and not S.stratification_report(bad)["ok"]
    assert not S.stratification_report(np.random.default_rng(0).random((50, 3)))["ok"]          # plain MC is not LHS


def test_antithetic_pairs_mirror_and_stay_lhs():
    u, x = S.lhs(64, PARAMS, seed=2, antithetic=("w", "u"))
    assert S.stratification_report(u)["ok"]
    for j in (0, 2):
        assert np.allclose(u[32:, j], 1 - u[:32, j])
    assert np.allclose(x["w"][:32] - 1.0, -(x["w"][32:] - 1.0))     # normal: exact mirror about the mean
    assert not np.allclose(u[32:, 1], 1 - u[:32, 1])                # a non-named column is not mirrored
    with pytest.raises(ValueError):
        S.lhs(63, PARAMS, antithetic=("w",))


def test_antithetic_cancels_linear_response():
    _, x = S.lhs(64, {"w": PARAMS["w"]}, seed=5, antithetic=("w",))
    assert abs((3 * x["w"]).mean() - 3.0) < 1e-9                    # mean of a linear response is exact


def test_member_seed_is_common_deterministic_and_independent():
    assert S.member_seed(7, 3, "wind") == S.member_seed(7, 3, "wind")
    assert len({S.member_seed(7, m, s) for m in range(20) for s in ("wind", "waves", "current")}) == 60
    assert S.member_seed(7, 3, "wind") != S.member_seed(8, 3, "wind")
    a, b = S.member_rng(7, 3, "wind").standard_normal(2000), S.member_rng(7, 3, "waves").standard_normal(2000)
    assert abs(np.corrcoef(a, b)[0, 1]) < 0.08                      # streams do not echo each other
    assert np.array_equal(a, S.member_rng(7, 3, "wind").standard_normal(2000))
    assert S.crn_check(7, 5, ("wind", "waves"), vehicles=3)


def test_crn_check_fails_when_the_vehicle_enters_the_seed(monkeypatch):
    calls = iter(range(10 ** 6))
    monkeypatch.setattr(S, "member_rng", lambda b, m, s: np.random.default_rng(next(calls)))
    assert not S.crn_check(7, 3, ("wind",))


def test_perturbations_yaml_is_complete_and_usable(tmp_path):
    cfg = S.load_perturbations()
    assert {"wind_speed_bias", "hs_scale", "usv_vpp_bias", "glider_speed_scale"} <= cfg.keys()
    for e in cfg.values():
        assert {"value", "unit", "citation", "kind"} <= e.keys() and e["kind"] in ("prior", "assumed") and e["citation"]
        assert e["kind"] == "prior" or e["citation"].startswith("ASSUMED")             # an assumed prior says so where the report reads it
    m = S.to_marginals(cfg)
    assert "current_correlation_length" not in m and m["wind_speed_bias"]["sd"] == 2.0
    _, x = S.lhs(128, m, seed=0)
    assert 0.9 < np.std(np.log(x["hs_scale"])) / 0.15 < 1.1
    assert -0.35 <= x["usv_vpp_bias"].min() and x["usv_vpp_bias"].max() <= -0.30
    with pytest.raises(ValueError):
        S.to_marginals(cfg, ["current_correlation_length"])
    bad = tmp_path / "p.yaml"
    bad.write_text(yaml.safe_dump({"x": {"value": 1, "unit": "m", "citation": "c", "kind": "measured"}}))
    with pytest.raises(ValueError):
        S.load_perturbations(bad)
    bad.write_text(yaml.safe_dump({"x": {"value": 1, "unit": "m", "kind": "prior"}}))
    with pytest.raises(ValueError):
        S.load_perturbations(bad)


# ---- sequential ----------------------------------------------------------------------------------------------------
def test_sprt_decisions():
    p0, p1 = Q.sprt_indifference(0.10, 0.05)
    assert (p0, p1) == pytest.approx((0.05, 0.15))
    assert Q.sprt_decide(0, 60, p0, p1) == "accept_go" and Q.sprt_decide(12, 40, p0, p1) == "accept_nogo"
    assert Q.sprt_decide(1, 10, p0, p1) == "continue"
    with pytest.raises(ValueError):
        Q.sprt_decide(1, 10, 0.2, 0.1)


@pytest.mark.parametrize("p_true,expect", [(0.05, "accept_go"), (0.15, "accept_nogo")])
def test_sprt_error_rates_at_edges_of_indifference_region(p_true, expect):
    """Wald: at p0 the chance of accepting H1 is <= alpha, at p1 the chance of accepting H0 is <= beta."""
    p0, p1, a, b = 0.05, 0.15, 0.05, 0.05
    rng = np.random.default_rng(11)
    wrong = 0
    for _ in range(600):
        k = n = 0
        while (d := Q.sprt_decide(k, n, p0, p1, a, b)) == "continue":
            k += rng.random() < p_true
            n += 1
        wrong += d != expect
    assert wrong / 600 <= 0.05 + 0.025


def test_ensemble_stop():
    assert Q.ensemble_stop(0, 40)["stop"] and Q.ensemble_stop(0, 40)["verdict"] == "GO"
    assert Q.ensemble_stop(0, 40, n_min=73)["stop"] is False
    assert Q.ensemble_stop(40, 60)["verdict"] == "NO-GO"
    s = Q.ensemble_stop(5, 40)
    assert s["stop"] is False and s["verdict"] is None
    c = Q.ensemble_stop(5, 40, n_max=40)
    assert c["stop"] and c["verdict"] == "MARGINAL" and "n_max" in c["reason"]


def test_ensemble_stop_error_rate_with_repeated_looks():
    """Stopping when the 95 % interval clears a cut-off, checked every 8 members, at p = cut-off: error stays small."""
    rng = np.random.default_rng(3)
    wrong = 0
    for _ in range(300):
        draws = rng.random(400) < 0.10                      # true P(fail) exactly at the GO cut-off
        for n in range(8, 401, 8):
            s = Q.ensemble_stop(int(draws[:n].sum()), n)
            if s["stop"]:
                wrong += s["verdict"] == "NO-GO"
                break
    assert wrong / 300 < 0.05


# ---- sensitivity ---------------------------------------------------------------------------------------------------
A, B = 7.0, 0.1
V = A * A / 8 + B * np.pi ** 4 / 5 + B * B * np.pi ** 8 / 18 + 0.5
ISHIGAMI_S1 = np.array([0.5 * (1 + B * np.pi ** 4 / 5) ** 2 / V, A * A / 8 / V, 0.0])      # 0.3139, 0.4424, 0


def ishigami(x):
    return np.sin(x[:, 0]) + A * np.sin(x[:, 1]) ** 2 + B * x[:, 2] ** 4 * np.sin(x[:, 0])


# RMS error over 20 LHS draws, measured over 40 draws (rmse 0.092/0.098/0.066, 0.048/0.057/0.055, 0.039/0.041/0.019,
# 0.028/0.036/0.010 for n = 64/128/256/512) with ~30 % headroom; 3 inputs.
@pytest.mark.parametrize("n,tol", [(64, 0.13), (128, 0.075), (256, 0.055), (512, 0.045)])
def test_ishigami_first_order(n, tol):
    box = {k: dict(dist="uniform", lo=-np.pi, hi=np.pi) for k in "abc"}
    err = []
    for seed in range(20):
        _, x = S.lhs(n, box, seed)
        X = np.c_[x["a"], x["b"], x["c"]]
        err.append(SE.first_order(X, ishigami(X)) - ISHIGAMI_S1)
    assert np.sqrt((np.array(err) ** 2).mean()) < tol


def test_ishigami_ranking_and_dominant():
    box = {k: dict(dist="uniform", lo=-np.pi, hi=np.pi) for k in "abc"}
    _, x = S.lhs(512, box, 0)
    X = np.c_[x["a"], x["b"], x["c"]]
    name, s, floor = SE.dominant(["a", "b", "c"], X, ishigami(X))
    assert name == "b" and s["b"] > s["a"] > s["c"] and s["c"] < 0.05 and s["a"] > floor > s["c"]


def test_noise_floor_keeps_unrelated_parameters_out_at_stage1_sizes():
    """32 members, 10 parameters, a failure indicator that depends on none of them: EASI's S1 for an unrelated column often
    reaches ~0.3 at this size (the glider_eq / usv_vpp_bias case), so `dominant` must name none in at least 90 % of draws, while
    a failure driven by one parameter (fail = u0 > 0.6) is still found."""
    names = [f"p{i}" for i in range(10)]
    hits, found = 0, 0
    for seed in range(40):
        u, _ = S.lhs(32, {k: dict(dist="uniform", lo=0, hi=1) for k in names}, seed)
        y = (np.random.default_rng(seed + 100).random(32) < 0.25).astype(float)
        hits += SE.dominant(names, u, y)[0] is not None
        found += SE.dominant(names, u, (u[:, 0] > 0.6).astype(float))[0] == "p0"
    assert hits <= 4 and found >= 36
    floor = SE.noise_floor(u, y)
    assert 0.1 < floor < 0.6 and floor == SE.noise_floor(u, y)                   # seeded: one answer
    assert SE.noise_floor(np.r_[u, u, u, u], np.r_[y, y, y, y]) < floor           # more members, lower floor


@pytest.mark.parametrize("n,tol", [(128, 0.12), (512, 0.05)])
def test_binary_failure_indicator(n, tol):
    """fail = x1 + x2 > 1 on U(0,1)^3: E[Y|x1] = x1, so S1 = (1/12)/(1/4) = 1/3 for x1 and x2, 0 for x3."""
    err = []
    for seed in range(20):
        u, _ = S.lhs(n, {k: dict(dist="uniform", lo=0, hi=1) for k in "abc"}, seed)
        err.append(SE.first_order(u, (u[:, 0] + u[:, 1] > 1).astype(float)) - np.array([1 / 3, 1 / 3, 0]))
    assert np.sqrt((np.array(err) ** 2).mean()) < tol


def test_sensitivity_invariances_and_guards():
    rng = np.random.default_rng(0)
    x = rng.random((200, 2))
    y = 3 * x[:, 0] ** 2 + 0.1 * x[:, 1]
    s = SE.first_order(x, y)
    assert np.allclose(s, SE.first_order(x[::-1], y[::-1])) and np.allclose(s, SE.first_order(x, 5 * y + 2))
    assert np.allclose(s, SE.first_order(np.exp(x), y))              # monotone transform of an input: same ordering
    assert s[0] > 0.9 and s[1] < 0.05 and (s >= 0).all() and (s <= 1).all()
    assert (SE.first_order(x, np.ones(200)) == 0).all()
    assert (SE.first_order(x, rng.random(200)) < 0.15).all()
    raw = SE.first_order(x, y, correct=False)
    assert raw[1] >= s[1]


# ---- rare ----------------------------------------------------------------------------------------------------------
def _lin(d):
    return lambda u: u.sum(1) / np.sqrt(d)


@pytest.mark.parametrize("target,n", [(3.5, 1000), (4.5, 1500)])
def test_subset_simulation_known_gaussian_tail(target, n):
    """P(Z > 3.5) = 2.33e-4, P(Z > 4.5) = 3.4e-6: mean of 10 runs within 40 %, every run within a factor 3."""
    truth = norm.sf(target)
    runs = [rare.subset_simulation(_lin(10), 10, target, n=n, seed=s) for s in range(10)]
    ratio = np.array([r["p"] for r in runs]) / truth
    assert all(r["converged"] for r in runs)
    assert abs(ratio.mean() - 1) < 0.4 and ratio.min() > 1 / 3 and ratio.max() < 3
    assert 0.05 < np.mean([r["cov"] for r in runs]) < 1.0           # Au-Beck c.o.v. is an approximation, usually low
    assert runs[0]["n_evals"] < 10 * n and runs[0]["levels"][-1] == target and len(runs[0]["levels"]) >= 3


def test_subset_simulation_high_dimension_and_easy_event():
    r = rare.subset_simulation(_lin(100), 100, 3.0, n=2000, seed=1)
    assert 0.3 < r["p"] / norm.sf(3.0) < 3
    easy = rare.subset_simulation(_lin(4), 4, 0.5, n=1000, seed=2)       # first level already above target: plain MC
    assert easy["converged"] and len(easy["levels"]) == 1 and abs(easy["p"] / norm.sf(0.5) - 1) < 0.2


def test_subset_simulation_unreachable_event_reports_not_converged():
    r = rare.subset_simulation(lambda u: np.zeros(len(u)), 3, 1.0, n=200)      # ties: thresholds cannot rise
    assert not r["converged"] and r["p"] == 0.0
    r = rare.subset_simulation(_lin(3), 3, 30.0, n=100, max_levels=2)
    assert not r["converged"]
    z = rare.subset_simulation(lambda u: np.full(len(u), 5.0), 3, 5.0, n=100)  # everything at target: p = 1
    assert z["p"] == 1.0 and z["cov"] == 0.0


def test_gamma_edge():
    assert rare._gamma(np.zeros((5, 4), bool)) == 0.0
    chain = np.tile(np.array([[True, False, True, False]]), (6, 1))     # each chain stays where it started
    assert rare._gamma(chain) > 0                                        # perfectly repeated chains are correlated
