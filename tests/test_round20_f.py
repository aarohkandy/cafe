"""Round 20, batch F (M-9): every public function of `stats.intervals` and `stats.sequential` that takes a count or a probability goes through the one shared
check (`intervals._count`, `_check`, `_unit`, `_closed`). Round 19 (M-8) fixed five named functions and round 20 found `coverage`, `verdict`, `wilson` with a
huge int and `sprt_decide`'s alpha and beta; this file lists the whole of both modules, so a function added later without a place in the table fails.

Each test names the fix it holds and what the unfixed tree did. The last one (the grid) is the proof that no ordinary answer moved by a bit: its digest was
taken on the tree before the fix (8e22951) and is the same on the fixed one."""
import hashlib
import inspect
import json

import numpy as np
import pytest

from cafe.pm.stats import intervals as I
from cafe.pm.stats import sequential as Q

NAN = float("nan")
TOP = 2 ** 53
HUGE_COUNTS = [10 ** 400, TOP + 1, np.uint64(2 ** 64 - 1)]
BAD_PROBS = [NAN, 0, 1, -0.5, 1.5, "0.95", None, True]            # not a probability in (0, 1)
ALL = ("GO", "MARGINAL", "NO-GO")


@pytest.fixture(autouse=True)
def _demo_thresholds(monkeypatch):
    """The module's cut-offs are state that other tests set: these tests read the demo's (0.9, 0.6), and the fixture puts back whatever it found."""
    monkeypatch.setattr(I, "P_FAIL_GO", 0.10)
    monkeypatch.setattr(I, "P_FAIL_NOGO", 0.40)
    monkeypatch.setattr(I, "LO_SUCCESS_GO", 0.75)


# ---- the table: every public function, and what it takes ------------------------------------------------------------------------------------------------

# "counts": k, n, n_min or n_max (the huge-count and the kind tests below); "probs": a confidence, a level or a probability (the open and the closed tests);
# "none": nothing a caller can get wrong. `receipts` builds the published receipts and takes no argument.
TAKES = {
    "set_thresholds": "probs", "wilson": "counts probs", "newcombe_diff": "counts probs", "agresti_coull": "counts probs", "interval": "counts probs",
    "rule_of_three": "counts", "n_certify": "probs", "n_certify_one_sided": "probs", "verdict_from_p": "probs", "verdict_band": "probs", "band_in": "probs",
    "verdict": "counts probs", "interval_region": "counts probs", "decided_region": "counts probs", "coverage": "counts probs", "receipts": "none",
    "sprt_indifference": "probs", "sprt_decide": "counts probs", "ensemble_stop": "counts probs",
}


def _public(module):
    return {n for n, f in inspect.getmembers(module, inspect.isfunction) if not n.startswith("_") and f.__module__ == module.__name__}


def test_r20_m9_every_public_function_of_both_modules_is_in_the_table():
    """A new public function with a count or a probability must be put in the table, and so in the tests that read it: no sibling is left for the next round."""
    assert _public(I) | _public(Q) == set(TAKES)


# Per function, one call per count argument, the count being `x` and the rest valid.
COUNT_CALLS = {
    "wilson": [lambda x: I.wilson(x, x), lambda x: I.wilson(1, x)],
    "agresti_coull": [lambda x: I.agresti_coull(x, x), lambda x: I.agresti_coull(1, x)],
    "interval": [lambda x: I.interval(x, x), lambda x: I.interval(1, x)],
    "interval_region": [lambda x: I.interval_region(x, x), lambda x: I.interval_region(1, x)],
    "decided_region": [lambda x: I.decided_region(x, x), lambda x: I.decided_region(1, x)],
    "verdict": [lambda x: I.verdict(x, x), lambda x: I.verdict(1, x)],
    "newcombe_diff": [lambda x: I.newcombe_diff(x, x, 1, 5), lambda x: I.newcombe_diff(1, x, 1, 5), lambda x: I.newcombe_diff(1, 5, x, x),
                      lambda x: I.newcombe_diff(1, 5, 1, x)],
    "rule_of_three": [lambda x: I.rule_of_three(x)],
    "coverage": [lambda x: I.coverage(x, np.array([0.3]))],
    "sprt_decide": [lambda x: Q.sprt_decide(x, x, 0.05, 0.15), lambda x: Q.sprt_decide(1, x, 0.05, 0.15)],
    "ensemble_stop": [lambda x: Q.ensemble_stop(x, x), lambda x: Q.ensemble_stop(1, x), lambda x: Q.ensemble_stop(1, 5, n_min=x),
                      lambda x: Q.ensemble_stop(1, 5, n_max=x)],
}


def test_r20_m9_the_count_table_covers_every_function_that_takes_a_count():
    assert {n for n, t in TAKES.items() if "counts" in t} == set(COUNT_CALLS)


@pytest.mark.parametrize("name", sorted(COUNT_CALLS))
@pytest.mark.parametrize("bad", HUGE_COUNTS, ids=["10**400", "2**53+1", "uint64max"])
def test_r20_m9_a_count_above_two_to_the_53_is_a_value_error_in_every_function(name, bad):
    """`wilson(1, 10**400)` was an OverflowError (`z * z / n`), and `rule_of_three(10**400)`, `sprt_decide(.., 10**400)` the same: not the module's error."""
    for call in COUNT_CALLS[name]:
        with pytest.raises(ValueError, match=r"must be at most 9007199254740992 \(2\*\*53\)"):
            call(bad)


def test_r20_m9_two_to_the_53_itself_is_a_count_and_the_bound_is_one_number():
    """The bound is not moved by one in either direction: 2**53 is answered, 2**53 + 1 is not (above)."""
    assert I.MAX_COUNT == TOP and I._count(TOP, "n") == TOP and type(I._count(np.uint64(TOP), "n")) is int
    lo, hi = I.wilson(1, TOP)
    assert 0 <= lo < hi < 1e-15 and I.wilson(0, TOP)[0] == 0.0 and I.wilson(TOP, TOP)[1] == 1.0
    assert I.agresti_coull(1, TOP)[1] > 0 and I.interval(1, TOP)[2] == "wilson"
    assert I.rule_of_three(TOP) == 3.0 / TOP
    assert I.verdict(0, TOP)["verdict"] == "GO" and I.interval_region(0, TOP) == "GO" and I.decided_region(TOP, TOP) == "NO-GO"
    assert I.newcombe_diff(1, TOP, 1, TOP)[0] < 0 < I.newcombe_diff(1, TOP, 1, TOP)[1]
    assert Q.sprt_decide(0, TOP, 0.05, 0.15) == "accept_go" and Q.sprt_decide(TOP, TOP, 0.05, 0.15) == "accept_nogo"
    assert Q.ensemble_stop(0, TOP, n_min=TOP, n_max=TOP)["stop"] is True


def test_r20_m9_a_huge_negative_count_is_still_the_range_error():
    """Only the top is bounded in `_count`; below it the callers' own range checks speak, with their own messages."""
    with pytest.raises(ValueError, match=r"need 0 <= k <= n and n >= 1"):
        I.wilson(-10 ** 400, 5)
    with pytest.raises(ValueError, match=r"need 0 <= k <= n, got"):
        Q.sprt_decide(-10 ** 400, 5, 0.05, 0.15)


# ---- coverage: a narrow numpy count wrapped, and a p outside 0..1 was a coverage of 0 ------------------------------------------------------------------

P3 = np.array([0.1, 0.5, 0.9])


@pytest.mark.parametrize("dt, n", [(np.uint8, 255), (np.int8, 127)], ids=lambda x: getattr(x, "__name__", x))
def test_r20_m9_coverage_of_the_largest_narrow_count_is_the_python_int_answer(dt, n):
    """`coverage(np.uint8(255), ..)` was a RuntimeWarning and an IndexError (`n + 1` wrapped to 0, `ks` empty); the same for `np.int8(127)`."""
    got = I.coverage(dt(n), P3)
    assert got.shape == (3,) and np.array_equal(got, I.coverage(n, P3))


@pytest.mark.parametrize("dt", [np.uint8, np.int8, np.uint16, np.int16, np.int32, np.int64, np.intp], ids=lambda d: d.__name__)
def test_r20_m9_coverage_of_a_narrow_count_equals_the_python_int_answer_for_both_methods(dt):
    for method in ("wilson", "agresti_coull"):
        assert np.array_equal(I.coverage(dt(100), P3, method=method), I.coverage(100, P3, method=method))


@pytest.mark.parametrize("bad", [[1.1], [-0.1], [NAN], [0.5, 1 + 1e-12], [-1e-12, 0.5], [[0.5]], 0.5, "0.5x"], ids=repr)
def test_r20_m9_coverage_refuses_a_p_grid_that_is_not_probabilities(bad):
    """A p above 1 or a NaN was a coverage of 0.0 (no k's interval holds it), a 2-d grid iterated rows, a scalar was a TypeError."""
    with pytest.raises(ValueError):
        I.coverage(10, bad)


def test_r20_m9_coverage_takes_the_closed_ends_and_a_list():
    """p = 0 and p = 1 are probabilities (k = 0 and k = n hold them: coverage 1); a list is read as the array of its floats, bit for bit."""
    assert I.coverage(10, [0.0, 1.0]).tolist() == [1.0, 1.0]
    assert np.array_equal(I.coverage(10, [0.2, 0.7]), I.coverage(10, np.array([0.2, 0.7])))


@pytest.mark.parametrize("kw", [dict(conf=0.0), dict(conf=1.0), dict(conf=NAN), dict(conf="0.95"), dict(conf=None)], ids=repr)
def test_r20_m9_coverage_refuses_a_conf_outside_0_1(kw):
    with pytest.raises(ValueError, match="need 0 < conf < 1"):
        I.coverage(10, P3, **kw)


# ---- verdict: the dict holds Python numbers ----------------------------------------------------------------------------------------------------------------

NARROW = [np.uint8, np.int8, np.uint16, np.int16, np.uint32, np.int32, np.uint64, np.int64, np.intp]


@pytest.mark.parametrize("dt", NARROW, ids=lambda d: d.__name__)
def test_r20_m9_verdict_of_numpy_counts_is_the_python_dict_and_json_serialisable(dt):
    """`json.dumps(verdict(np.uint8(3), np.uint8(100)))` was a TypeError (`n` and `k_fail` were stored as given); the dict equals the Python-int dict."""
    for k, n in ((3, 100), (0, 20), (20, 20), (0, 100)):
        d = I.verdict(dt(k), dt(n))
        assert d == I.verdict(k, n)
        assert type(d["n"]) is int and type(d["k_fail"]) is int and type(d["n_certify"]) is int and type(d["p_fail"]) is float
        assert json.dumps(d) == json.dumps(I.verdict(k, n))


@pytest.mark.parametrize("conf", [np.float32(0.9), np.float64(0.9), 0.9], ids=lambda c: type(c).__name__)
def test_r20_m9_verdict_stores_conf_as_a_python_float(conf):
    """A numpy float32 (or a float64: it is a float subclass, and an exact one is not what `json` wants either way) is stored as the float it is."""
    d = I.verdict(3, 100, conf)
    assert type(d["conf"]) is float and d["conf"] == float(conf)
    assert json.loads(json.dumps(d))["conf"] == float(conf)
    assert type(d["fail_lo"]) is float and type(d["fail_hi"]) is float and type(d["success_lo"]) is float


def test_r20_m9_the_verdict_dict_of_python_ints_is_what_it_was():
    """Every key and value of an ordinary call, written out: the same keys in the same order, so a report.json built from it is the same text."""
    d = I.verdict(3, 100)
    assert list(d) == ["verdict", "n", "k_fail", "p_fail", "fail_lo", "fail_hi", "success_lo", "conf", "method", "n_certify", "note"]
    assert (d["verdict"], d["n"], d["k_fail"], d["p_fail"], d["conf"], d["method"], d["n_certify"]) == ("GO", 100, 3, 0.03, 0.9, "wilson", 73)


@pytest.mark.parametrize("call", [lambda: I.verdict(5, 3), lambda: I.verdict(-1, 3), lambda: I.verdict(1, 0), lambda: I.verdict(1.5, 3),
                                  lambda: I.verdict(True, 3), lambda: I.verdict(1, 3, conf=1.0), lambda: I.verdict(1, 3, level=0.0),
                                  lambda: I.verdict(1, 3, cert_conf=1.0)])
def test_r20_m9_verdict_refuses_its_arguments_before_anything_is_stored(call):
    with pytest.raises(ValueError):
        call()


# ---- confidences and levels: a non-number is the module's error ----------------------------------------------------------------------------------------

CONF_CALLS = {
    "wilson": lambda c: I.wilson(3, 10, conf=c), "agresti_coull": lambda c: I.agresti_coull(3, 10, conf=c), "interval": lambda c: I.interval(3, 10, conf=c),
    "newcombe_diff": lambda c: I.newcombe_diff(3, 10, 4, 10, conf=c), "interval_region": lambda c: I.interval_region(3, 10, conf=c),
    "decided_region": lambda c: I.decided_region(3, 10, conf=c), "verdict": lambda c: I.verdict(3, 10, conf=c),
    "coverage": lambda c: I.coverage(10, P3, conf=c),
    "ensemble_stop": lambda c: Q.ensemble_stop(3, 10, conf=c), "n_certify": lambda c: I.n_certify(conf=c), "n_certify_level": lambda c: I.n_certify(level=c),
    "n_certify_one_sided": lambda c: I.n_certify_one_sided(conf=c), "n_certify_one_sided_level": lambda c: I.n_certify_one_sided(level=c),
    "verdict_level": lambda c: I.verdict(3, 10, level=c), "verdict_cert_conf": lambda c: I.verdict(3, 10, cert_conf=c),
}


@pytest.mark.parametrize("name", sorted(CONF_CALLS))
@pytest.mark.parametrize("bad", BAD_PROBS, ids=repr)
def test_r20_m9_a_confidence_or_level_outside_0_1_or_not_a_number_is_a_value_error(name, bad):
    """`wilson(3, 10, conf="0.95")` and `conf=None` were a TypeError from the comparison; 0, 1, NaN, a boolean were refused already, and stay so."""
    with pytest.raises(ValueError, match=r"need 0 < "):
        CONF_CALLS[name](bad)


def test_r20_m9_a_numpy_float_is_a_confidence_and_the_edges_of_the_open_interval_are_not():
    for c in (np.float32(0.5), np.float32(0.9), np.float32(0.95)):         # the quantile was computed in single precision: 0.2127148644 against 0.2127148628
        assert I.wilson(3, 10, conf=c) == I.wilson(3, 10, conf=float(c)) and I.agresti_coull(3, 10, conf=c) == I.agresti_coull(3, 10, conf=float(c))
        assert I.newcombe_diff(3, 10, 4, 10, conf=c) == I.newcombe_diff(3, 10, 4, 10, conf=float(c)) and I.n_certify(conf=c) == I.n_certify(conf=float(c))
        assert I._kappa(c) == I._kappa(float(c)) and type(I._kappa(c)) is float
    assert I.wilson(3, 10, conf=np.float64(0.95)) == I.wilson(3, 10)
    assert I.n_certify(level=np.float64(0.05), conf=np.float64(0.95)) == 73
    for c in (1e-12, 1 - 1e-12):
        lo, hi = I.wilson(3, 10, conf=c)
        assert 0 <= lo <= hi <= 1


# ---- the probabilities of the verdict functions: 0 <= p <= 1, a NaN was NO-GO ---------------------------------------------------------------------------

BAD_CLOSED = [NAN, -1e-12, 1 + 1e-12, -0.5, 1.5, "0.5", None, True, False, np.bool_(True)]


@pytest.mark.parametrize("bad", BAD_CLOSED, ids=repr)
def test_r20_m9_verdict_from_p_refuses_what_is_not_a_probability(bad):
    """`verdict_from_p(nan)` was "NO-GO" (every comparison with a NaN is False) and `verdict_from_p(True)` was "NO-GO" too."""
    with pytest.raises(ValueError, match=r"need 0 <= p_fail <= 1, got p_fail="):
        I.verdict_from_p(bad)


def test_r20_m9_verdict_from_p_takes_the_closed_ends_and_numpy_floats():
    assert I.verdict_from_p(0.0) == "GO" and I.verdict_from_p(1.0) == "NO-GO"
    assert I.verdict_from_p(np.float32(0.25)) == "MARGINAL" and I.verdict_from_p(np.float64(0.05)) == "GO" and I.verdict_from_p(1) == "NO-GO"


@pytest.mark.parametrize("which", ["p_fail", "lo", "hi"])
@pytest.mark.parametrize("bad", BAD_CLOSED, ids=repr)
def test_r20_m9_verdict_band_refuses_each_of_its_three_probabilities(which, bad):
    args = dict(p_fail=0.2, lo=0.1, hi=0.3)
    args[which] = bad
    with pytest.raises(ValueError, match=rf"need 0 <= {which} <= 1, got {which}="):
        I.verdict_band(**args)


def test_r20_m9_verdict_band_takes_the_closed_ends():
    assert I.verdict_band(0.0, 0.0, 0.0) == "GO" and I.verdict_band(1.0, 1.0, 1.0) == "NO-GO"
    assert I.verdict_band(0.05, 0.0, 1.0) == "MARGINAL"             # the band's upper end (1 - 0.75 = 0.25 at most for a GO) is read, p alone is not enough
    assert I.verdict_band(np.float32(0.05), np.float32(0.0), np.float32(0.2)) == "GO"


@pytest.mark.parametrize("which", ["lo", "hi"])
@pytest.mark.parametrize("bad", BAD_CLOSED, ids=repr)
def test_r20_m9_band_in_refuses_each_end_of_the_band(which, bad):
    args = dict(lo=0.1, hi=0.3)
    args[which] = bad
    with pytest.raises(ValueError, match=rf"need 0 <= {which} <= 1, got {which}="):
        I.band_in(want=ALL, **args)


def test_r20_m9_band_in_takes_the_closed_ends_and_still_reads_the_whole_band():
    assert I.band_in(0.0, 1.0, ALL) is True and I.band_in(0.0, 1.0, ("GO",)) is False
    assert I.band_in(0.01, 0.05, ("GO",)) is True and I.band_in(0.05, 0.2, ("GO",)) is False


# ---- set_thresholds ---------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("go, nogo", [(NAN, 0.5), (0.9, NAN), ("0.9", 0.5), (0.9, None), (True, 0.5), (0.9, False), (np.bool_(True), 0.5), (0.5, 0.5)],
                         ids=repr)
def test_r20_m9_set_thresholds_refuses_what_is_not_a_pair_of_probabilities(go, nogo):
    """`set_thresholds("0.9", 0.5)` was a TypeError and `set_thresholds(True, 0.5)` was accepted as go = 1 (a boolean is an int)."""
    before = (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO)
    with pytest.raises(ValueError, match=r"need 0 < nogo < go <= 1"):
        I.set_thresholds(go, nogo)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == before


def test_r20_m9_set_thresholds_keeps_python_floats_as_module_state():
    """A numpy float32 or an int was kept as a numpy scalar or an int by `round`: the state is floats, whatever was passed."""
    I.set_thresholds(np.float32(0.5), np.float32(0.25))
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == (0.5, 0.75, 0.5)
    assert type(I.P_FAIL_GO) is float and type(I.P_FAIL_NOGO) is float and type(I.LO_SUCCESS_GO) is float
    I.set_thresholds(1, 0.5)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == (0.0, 0.5, 0.75) and type(I.P_FAIL_GO) is float
    I.set_thresholds(0.9, 0.6)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == (round(1 - 0.9, 12), round(1 - 0.6, 12), 0.75)


# ---- sequential ------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [0, 0.0, -1, 1, 1.0, 1.5, NAN, "0.05", None, True], ids=repr)
def test_r20_m9_sprt_decide_refuses_an_alpha_outside_0_1(bad):
    """`alpha=0` was a ZeroDivisionError, `alpha=-1` a math domain error, `alpha=1` a log of 0 or a wrong answer."""
    with pytest.raises(ValueError, match=r"need 0 < alpha < 1 and 0 < beta < 1, got alpha="):
        Q.sprt_decide(1, 10, 0.05, 0.15, alpha=bad)


@pytest.mark.parametrize("bad", [0, 0.0, -1, 1, 1.0, 1.5, NAN, "0.05", None, True], ids=repr)
def test_r20_m9_sprt_decide_refuses_a_beta_outside_0_1(bad):
    """`beta=1` was a math domain error, `beta=0` a log of 0."""
    with pytest.raises(ValueError, match=r"need 0 < alpha < 1 and 0 < beta < 1, got alpha=0.05, beta="):
        Q.sprt_decide(1, 10, 0.05, 0.15, beta=bad)


def test_r20_m9_sprt_decide_takes_alpha_and_beta_close_to_the_edges_and_numpy_floats():
    for e in (1e-12, 1 - 1e-12):
        assert Q.sprt_decide(1, 10, 0.05, 0.15, alpha=e, beta=0.05) in ("accept_go", "accept_nogo", "continue")
        assert Q.sprt_decide(1, 10, 0.05, 0.15, alpha=0.05, beta=e) in ("accept_go", "accept_nogo", "continue")
    assert Q.sprt_decide(0, 60, 0.05, 0.15, np.float32(0.05), np.float64(0.05)) == "accept_go"
    assert Q.sprt_decide(12, 40, 0.05, 0.15, alpha=0.01, beta=0.01) == "accept_nogo"
    assert Q.sprt_decide(1, 10, 0.05, 0.15, alpha=0.001, beta=0.001) == "continue"


@pytest.mark.parametrize("p0, p1", [(0.0, 0.5), (0.5, 1.0), (0.3, 0.3), (0.4, 0.3), (NAN, 0.5), (0.1, NAN), ("0.1", 0.5), (None, 0.5), (0.1, True),
                                    (False, 0.5)], ids=repr)
def test_r20_m9_sprt_decide_refuses_an_indifference_region_that_is_not_0_p0_p1_1(p0, p1):
    """`sprt_decide(.., p0="0.1", ..)` was a TypeError, `(True, ..)` a division by zero, `p1=nan` an answer."""
    with pytest.raises(ValueError, match=r"need 0 < p0 < p1 < 1"):
        Q.sprt_decide(1, 10, p0, p1)


@pytest.mark.parametrize("cut, delta", [(0.1, -0.05), (0.1, 0.0), (0.1, 0.1), (0.1, 0.11), (0.4, 0.6), (0.9, 0.1), (NAN, 0.05), (0.1, NAN), ("0.1", 0.05),
                                        (0.1, None), (True, 0.05), (0.5, True)], ids=repr)
def test_r20_m9_sprt_indifference_refuses_a_region_that_is_not_inside_0_1(cut, delta):
    """A negative delta gave the two ends the wrong way round, a delta of 0 gave one point, a NaN gave NaN, and `sprt_decide` refused all of them later."""
    with pytest.raises(ValueError, match=r"need 0 < cut - delta < cut \+ delta < 1"):
        Q.sprt_indifference(cut, delta)


def test_r20_m9_sprt_indifference_takes_what_it_took_and_the_ends_just_inside():
    assert Q.sprt_indifference(0.10, 0.05) == (0.10 - 0.05, 0.10 + 0.05) and Q.sprt_indifference(0.4, 0.1) == (0.4 - 0.1, 0.4 + 0.1)
    assert Q.sprt_indifference(np.float32(0.5), 0.25) == (0.25, 0.75) and Q.sprt_indifference(0.5, np.float64(0.25)) == (0.25, 0.75)
    p0, p1 = Q.sprt_indifference(0.5, 0.5 - 1e-9)
    assert 0 < p0 < p1 < 1 and Q.sprt_decide(1, 3, p0, p1) in ("accept_go", "accept_nogo", "continue")


def test_r20_m9_ensemble_stop_checks_the_counts_before_it_decides_not_to_look():
    """`ensemble_stop(5, 3, n_min=10)` was answered (n < n_min skipped the interval and its check), as were `(-1, 3, n_min=10)` and a conf of 2."""
    for args, kw in (((5, 3), {}), ((-1, 3), {}), ((1, 0), {}), ((1, 3), dict(conf=2.0))):
        with pytest.raises(ValueError):
            Q.ensemble_stop(*args, n_min=10, **kw)
    assert Q.ensemble_stop(1, 3, n_min=10) == dict(stop=False, verdict=None, reason="interval straddles a cut-off")
    assert Q.ensemble_stop(np.uint8(1), np.uint8(3), n_min=np.int8(10), n_max=np.uint8(64)) == Q.ensemble_stop(1, 3, n_min=10, n_max=64)


@pytest.mark.parametrize("bad", [True, False, 2.5, 3.0, np.float64(3), np.bool_(True), "3", None], ids=repr)
def test_r20_m9_ensemble_stop_refuses_an_n_min_that_is_not_a_count(bad):
    """`n_min=2.5` and `n_min=True` were read as numbers in `n >= n_min`."""
    with pytest.raises(ValueError, match="n_min must be an integer count"):
        Q.ensemble_stop(1, 10, n_min=bad)


@pytest.mark.parametrize("bad", [True, False, 2.5, 3.0, np.float64(3), np.bool_(True), "3"], ids=repr)
def test_r20_m9_ensemble_stop_refuses_an_n_max_that_is_not_a_count_but_takes_none(bad):
    with pytest.raises(ValueError, match="n_max must be an integer count"):
        Q.ensemble_stop(1, 10, n_max=bad)
    assert Q.ensemble_stop(1, 10, n_max=None)["stop"] is False
    assert Q.ensemble_stop(1, 10, n_max=10) == dict(stop=True, verdict="MARGINAL", reason="n_max reached")


# ---- the grid: no ordinary answer moved ------------------------------------------------------------------------------------------------------------------

# sha256 of the repr of every answer below, taken on the tree before the fix (8e22951): the fixed tree gives the same bits, which is what "the verdicts,
# intervals and counts of ordinary inputs do not change" means. If it fails after an edit that was meant to move a number, regenerate it from `_grid()`.
GRID_DIGEST = "4d5c2eb6288fa5071863415132983fbc5f65991ef2c2fa7091500588995eeb44"


def _grid():
    out = []
    ns = list(range(1, 81)) + [100, 150, 200, 500, 1000]
    for n in ns:
        for k in range(0, n + 1, 1 if n <= 80 else max(1, n // 25)):
            for conf in (0.95, 0.90, 0.5):
                out.append((k, n, conf, I.wilson(k, n, conf), I.agresti_coull(k, n, conf), I.interval(k, n, conf), I.interval_region(k, n, conf),
                            I.decided_region(k, n, conf)))
            out.append((k, n, I.verdict(k, n), I.verdict(k, n, 0.95), I.verdict(k, n, 0.8, 0.10, 0.9)))
            out.append((k, n, I.verdict_from_p(k / n), I.verdict_band(k / n, *I.interval(k, n, 0.90)[:2]), I.band_in(*I.interval(k, n, 0.90)[:2], ALL),
                        I.band_in(*I.interval(k, n, 0.90)[:2], ("GO",)), I.rule_of_three(n) if k == 0 else None))
            for p0, p1 in ((0.05, 0.15), (0.3, 0.5)):
                out.append((k, n, p0, Q.sprt_decide(k, n, p0, p1), Q.sprt_decide(k, n, p0, p1, 0.01, 0.1)))
            for kw in (dict(), dict(n_min=73), dict(n_min=32, n_max=64), dict(conf=0.9, n_max=n)):
                out.append((k, n, sorted(kw), Q.ensemble_stop(k, n, **kw)))
    for k1, n1, k2, n2 in ((0, 32, 16, 32), (4, 32, 1, 32), (5, 10, 5, 10), (56, 70, 48, 80), (0, 1, 1, 1), (7, 50, 7, 50)):
        out.append((k1, n1, k2, n2, I.newcombe_diff(k1, n1, k2, n2), I.newcombe_diff(k1, n1, k2, n2, 0.9)))
    for n in (1, 10, 40):
        for method in ("wilson", "agresti_coull"):
            out.append((n, method, I.coverage(n, np.linspace(0.02, 0.98, 25), method=method).tolist(),
                        I.coverage(n, np.array([0.0, 0.3, 1.0]), 0.9, method).tolist()))
    out.append((I.n_certify(), I.n_certify(0.1, 0.9), I.n_certify_one_sided(), I.n_certify_one_sided(0.01, 0.99), Q.sprt_indifference(0.10, 0.05),
                Q.sprt_indifference(0.4, 0.1)))
    for go, nogo in ((0.9, 0.6), (0.8, 0.5), (0.95, 0.3), (1.0, 0.5)):
        I.set_thresholds(go, nogo)
        out.append((go, nogo, I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO, [I.verdict(k, 40) for k in range(41)],
                    [I.verdict_from_p(i / 20) for i in range(21)]))
    return out


def test_r20_m9_the_answers_of_ordinary_inputs_did_not_move_by_a_bit(monkeypatch):
    """Every interval, region, verdict (the whole dict), SPRT decision, stopper answer, coverage and certification count over a grid of (k, n): n = 1 to 80
    with every k, and five larger n, three confidences, the demo's and three other cut-offs. The digest is of the `repr` of the answers, so it is exact."""
    monkeypatch.setattr(I, "P_FAIL_GO", 0.10)
    monkeypatch.setattr(I, "P_FAIL_NOGO", 0.40)
    monkeypatch.setattr(I, "LO_SUCCESS_GO", 0.75)
    grid = _grid()
    assert len(grid) > 10_000
    assert hashlib.sha256(repr(grid).encode()).hexdigest() == GRID_DIGEST
