"""Round 21, batch F (M-13, D-7): a statistics function that passes its guard and then fails in its arithmetic.

Round 19 fixed five functions' inputs and round 20 swept the INPUT checks of all 19 public ones; round 21 found two that pass the guard and fail in the
arithmetic (`n_certify(5e-324)` an OverflowError, `n_certify_one_sided(1e-17)` a ZeroDivisionError, `n_certify_one_sided(0.05, 1e-20)` a count of 0). This
file closes the class: the certification counts are checked after the arithmetic (one rule, `intervals._no_count`), and every public function of
`cafe/pm/stats` (all five modules) is run over its whole guarded domain, the edges included (the smallest and largest probabilities, counts 0, 1 and
MAX_COUNT), by hypothesis, asserting a finite sane value or the module's ValueError and nothing else. The sweep found these siblings, each with its
own test below: `sprt_indifference` with a huge int, `sprt_decide` with a p0 under 5.6e-309 ("continue" for a run of 100 passes), `set_thresholds` for two
cut-offs inside 1e-12, `first_order` for a constant y of 47 members (S1 of 0.29), a y of 1e160 (NaN) or 1e-200 (zeros), a NaN y and a negative `harmonics`,
`noise_floor` with no permutation, `extreme_ranks` with no member, `subset_simulation` with an infinite p0 or a huge n, `stratification_report` of no member.
The digest test of round 20 (tests/test_round20_f.py) is unchanged and still holds: the checks below that an ordinary answer did not move are exact."""
import math
import warnings
from decimal import Decimal, getcontext

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cafe.pm.stats import intervals as I
from cafe.pm.stats import rare as R
from cafe.pm.stats import sampling as M
from cafe.pm.stats import sensitivity as S
from cafe.pm.stats import sequential as Q

TOP = I.MAX_COUNT
NOT_A_COUNT = r"is not a finite count at most 9007199254740992 \(2\*\*53\)"
ONE_BELOW = float(np.nextafter(1.0, 0.0))                           # 0.9999999999999999, the largest probability below 1
EDGE_PROBS = [5e-324, 1e-320, 5.6e-309, 2.3e-308, 1e-300, 1e-17, 1.1e-16, 3.3e-16, 1e-10, 1e-3, 0.0010000000000000002, 0.05, 0.5, 0.95, 1 - 1e-10, 1 - 1.1e-16,
              ONE_BELOW]
EDGE_COUNTS = [0, 1, 2, 3, 10, 73, 10 ** 6, TOP - 1, TOP]
SLOW = dict(deadline=None, derandomize=True, database=None, suppress_health_check=list(HealthCheck))


@pytest.fixture(autouse=True)
def _demo_thresholds(monkeypatch):
    """The module's cut-offs are state that other tests set (and the sweep sets them): these tests read the demo's, and the fixture puts back what it found."""
    monkeypatch.setattr(I, "P_FAIL_GO", 0.10)
    monkeypatch.setattr(I, "P_FAIL_NOGO", 0.40)
    monkeypatch.setattr(I, "LO_SUCCESS_GO", 0.75)


# ---- D-7 as the reviewer ran it ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("call", [lambda: I.n_certify(5e-324), lambda: I.n_certify(1e-320), lambda: I.n_certify_one_sided(1e-17),
                                  lambda: I.verdict(0, 10, level=1e-17)],
                         ids=["n_certify 5e-324", "n_certify 1e-320", "one-sided 1e-17", "verdict level 1e-17"])
def test_r21_m13_the_four_inputs_of_the_finding_are_the_modules_value_error(call):
    """OverflowError (`floor(inf)`), OverflowError, ZeroDivisionError (`log(1 - 1e-17)` is 0) and a count of 3.8e17 handed back without a word."""
    with pytest.raises(ValueError, match=NOT_A_COUNT):
        call()


def test_r21_m13_a_tiny_confidence_is_one_member_not_none():
    """`n_certify_one_sided(0.05, 1e-20)` returned 0: `1 - 1e-20` is 1, so its log was 0. Zero members cannot certify anything; the answer is the smallest
    n with 0.95^n <= 1 - 1e-20, which is 1."""
    assert I.n_certify_one_sided(0.05, 1e-20) == 1
    assert I.n_certify_one_sided(0.05, 5e-324) == 1
    assert I.n_certify_one_sided(0.05, 1e-17) == 1
    assert I.n_certify_one_sided(5e-324, 5e-324) == 1               # (1 - c)^1 <= 1 - c: the quotient is 1


def test_r21_m13_a_count_that_underflows_to_zero_is_still_one_member():
    """A confidence of 5e-324 over a level of 1 - 1.1e-16: the quotient is 5e-324 / 36.7, which underflows to 0.0 and `ceil` of that is 0. `max(1, ..)`."""
    assert I.n_certify_one_sided(ONE_BELOW, 5e-324) == 1


@pytest.mark.parametrize("level, conf", [(5e-324, 0.95), (1e-320, 0.5), (5.6e-309, 0.95), (1e-300, 0.5), (1e-17, 0.95), (0.05, ONE_BELOW), (1e-320, 5e-324)])
def test_r21_m13_n_certify_refuses_every_pair_whose_count_is_not_one(level, conf):
    """An infinite 1 / level, an infinite z (a conf of 1 - 1.1e-16: `0.5 + conf / 2` rounds to 1), 0 * inf (a NaN) and a count above 2**53."""
    with pytest.raises(ValueError, match=NOT_A_COUNT):
        I.n_certify(level, conf)


@pytest.mark.parametrize("level, conf", [(5e-324, 0.95), (1e-17, 0.95), (1e-16, 0.95), (3e-16, 0.95), (5e-324, 1e-3), (1e-300, 1e-3)])
def test_r21_m13_n_certify_one_sided_refuses_every_pair_whose_count_is_not_one(level, conf):
    with pytest.raises(ValueError, match=NOT_A_COUNT):
        I.n_certify_one_sided(level, conf)


def test_r21_m13_the_bound_is_the_modules_count_and_is_inclusive(monkeypatch):
    """n = 73 (59) is allowed at a bound of 73 (59) and refused at 72 (58): `n > MAX_COUNT` and not `>=`; the floor-plus-one of `n_certify` and the ceil of the
    one-sided count are both the count that is compared."""
    monkeypatch.setattr(I, "MAX_COUNT", 73)
    assert I.n_certify() == 73
    monkeypatch.setattr(I, "MAX_COUNT", 72)
    with pytest.raises(ValueError, match="at most 72"):
        I.n_certify()
    monkeypatch.setattr(I, "MAX_COUNT", 59)
    assert I.n_certify_one_sided() == 59
    monkeypatch.setattr(I, "MAX_COUNT", 58)
    with pytest.raises(ValueError, match="at most 58"):
        I.n_certify_one_sided()


def test_r21_m13_the_largest_levels_the_counts_still_hold_are_answered():
    """The largest count is a number of members the module can hold (2**53 = 9.007e15), so a level of 4.3e-16 is certified by 9e15 members: answered, and one
    decade below it a ValueError. For the one-sided count, 6.9e15 at a level of 1e-16 and a confidence of 0.5."""
    assert 7e15 < I.n_certify(5e-16) <= TOP                         # k^2 / 5e-16 = 7.68e15
    with pytest.raises(ValueError, match=NOT_A_COUNT):
        I.n_certify(4e-17)
    assert I.n_certify_one_sided(1e-16, 0.5) == 6_931_471_805_599_453
    with pytest.raises(ValueError, match=NOT_A_COUNT):
        I.n_certify_one_sided(5e-17, 0.95)


# ---- the one-sided count: `log1p` below 1e-3, the old expression at and above it -----------------------------------------------------------------------------

getcontext().prec = 60


def _exact_count(level, conf):
    """The count from the decimal numbers as printed, to 60 digits: the oracle for a level or a confidence too small for `1 - x`."""
    return math.ceil((1 - Decimal(repr(conf))).ln() / (1 - Decimal(repr(level))).ln())


@pytest.mark.parametrize("level, conf", [(1e-8, 0.95), (1e-8, 0.5), (1e-12, 0.95), (1e-5, 0.95), (1e-4, 0.99), (1e-20, 1e-10), (3e-16, 1e-10), (0.05, 1e-17),
                                         (1e-16, 0.5), (0.5, 1e-5), (0.05, 5e-4)])
def test_r21_m13_the_one_sided_count_is_the_exact_one_where_one_minus_x_loses_digits(level, conf):
    """The log of `1 - 1e-8` is off by a part in 1e8 (the count 299573225 against the exact 299573226, 1e-12: 2472254323020 against ...), and 0 for 1e-17."""
    assert I.n_certify_one_sided(level, conf) == _exact_count(level, conf)


def _old_one_sided(level, conf):
    return math.ceil(math.log(1 - conf) / math.log(1 - level))


def _old_certify(level, conf):
    return int(math.floor(I._kappa(conf) ** 2 * (1 / level - 1))) + 1


def test_r21_m13_no_ordinary_certification_count_moved():
    """At and above 1e-3 both counts are the expressions of the tree before this round, for 24,000 (level, conf) decimals: including the ones where
    `log(1 - x)` and `log1p(-x)` round to different integers (0.3, 0.51 is 2 and 0.1, 0.271 is 4: a switch to `log1p` there would have moved them)."""
    levels = [i / 1000 for i in range(1, 1000, 7)] + [0.001, 0.0010000000000000002, 0.3, 0.1, 0.2]
    confs = [0.001, 0.5, 0.8, 0.9, 0.95, 0.975, 0.99, 0.999, 0.51, 0.271, 0.36, 0.488, 0.0015, 0.9999]
    n = 0
    for level in levels:
        for conf in confs:
            n += 1
            assert I.n_certify_one_sided(level, conf) == _old_one_sided(level, conf), (level, conf)
            assert I.n_certify(level, conf) == _old_certify(level, conf), (level, conf)
    assert n > 2000
    assert (I.n_certify_one_sided(0.3, 0.51), I.n_certify_one_sided(0.1, 0.271)) == (2, 4)      # log1p would give 3 and 3
    assert (I.n_certify(), I.n_certify_one_sided(), I.n_certify(0.1, 0.9), I.n_certify_one_sided(0.01, 0.99)) == (73, 59, 25, 459)


def test_r21_m13_the_threshold_of_log1p_is_a_level_or_a_confidence_below_1e_3():
    """Either argument under 1e-3 takes `log1p`: (0.5, 1e-5) is exact and the old expression gives another integer; a confidence of 0.95 with a level of 1e-8
    takes it through the level."""
    assert _old_one_sided(1e-8, 0.95) == 299573225 != _exact_count(1e-8, 0.95) == I.n_certify_one_sided(1e-8, 0.95)
    assert _old_one_sided(0.05, 1e-17) == 0 != I.n_certify_one_sided(0.05, 1e-17)


@pytest.mark.parametrize("dt", [np.float32, np.float64])
def test_r21_m13_a_numpy_float_level_gives_the_python_float_answer(dt):
    """`1 / level` in single precision, and an overflow warning for a float64 subnormal: both are converted first, as `_kappa` does for the confidence."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for level, conf in ((0.05, 0.95), (0.1, 0.9), (0.01, 0.5)):
            lv, cf = dt(level), dt(conf)
            assert I.n_certify(lv, cf) == I.n_certify(float(lv), float(cf))
            assert I.n_certify_one_sided(lv, cf) == I.n_certify_one_sided(float(lv), float(cf))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match=NOT_A_COUNT):
            I.n_certify(np.float64(5e-324))


# ---- set_thresholds --------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("go, nogo", [(0.9, 0.9 - 1e-13), (0.9999999999999, 0.9999999999998), (1e-300, 5e-324), (0.5, 0.4999999999999)])
def test_r21_m13_two_cut_offs_inside_1e_12_are_refused_and_change_nothing(go, nogo):
    """Rounded to 12 places they were one number: a GO and a NO-GO at the same P(fail) and no MARGINAL (1e-300 and 5e-324: both 1.0: all GO)."""
    before = (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO)
    with pytest.raises(ValueError, match="must differ by more than 1e-12"):
        I.set_thresholds(go, nogo)
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO) == before


def test_r21_m13_two_cut_offs_one_part_in_1e_12_apart_are_taken():
    I.set_thresholds(0.9, 0.899999999999)                          # 1e-12 apart: 0.1 and 0.100000000001 after the rounding
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (0.1, 0.100000000001)
    I.set_thresholds(1.0, 5e-324)                                  # the widest pair: GO needs no failure, NO-GO is any failure rate above 0
    assert (I.P_FAIL_GO, I.P_FAIL_NOGO) == (0.0, 1.0)


# ---- sequential ------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cut, delta", [(0.5, 10 ** 400), (0.5, -10 ** 400), (10 ** 400, 0.1), (-10 ** 400, 0.1), (0.5, 2 ** 1100), (10 ** 400, 10 ** 400)])
def test_r21_m13_sprt_indifference_with_a_huge_int_is_the_value_error(cut, delta):
    """`cut - delta` with a float and an int above 1.8e308 is an OverflowError; the guard compared the sum only after it."""
    with pytest.raises(ValueError, match="need 0 < cut - delta < cut \\+ delta < 1"):
        Q.sprt_indifference(cut, delta)


def test_r21_m13_sprt_indifference_keeps_its_answers():
    assert Q.sprt_indifference(0.10, 0.05) == (0.10 - 0.05, 0.10 + 0.05)
    assert Q.sprt_indifference(0.5, 0.4999999999999999) == (0.5 - 0.4999999999999999, 0.5 + 0.4999999999999999)
    for cut, delta in ((0.5, 1), (0.5, -0.1), (0.5, 0.5), (0.5, math.nan), (0.5, math.inf), (1, 0.1)):
        with pytest.raises(ValueError):
            Q.sprt_indifference(cut, delta)


@pytest.mark.parametrize("p0", [5e-324, 1e-320, 1e-310, 5.6e-309])
def test_r21_m13_sprt_decide_with_a_p0_under_the_float_range_of_a_ratio(p0):
    """p1 / p0 is inf for a p0 under about 5.6e-309, and `0 * inf` at k = 0 is NaN: the LLR was NaN, no comparison held, and a hundred passes in a row were
    "continue" (at p0 = 1e-300 the same run is accept_go). One failure is a log-likelihood ratio of about +700: accept_nogo."""
    assert Q.sprt_decide(0, 100, p0, 0.5) == "accept_go"
    assert Q.sprt_decide(1, 100, p0, 0.5) == "accept_nogo"
    assert Q.sprt_decide(1, 1, p0, 0.5) == "accept_nogo"
    assert Q.sprt_decide(0, 1, p0, 0.5) == "continue"             # ln(0.5) = -0.69 is between the two thresholds, for alpha = beta = 0.05
    assert Q.sprt_decide(0, 100, 1e-300, 0.5) == "accept_go"      # the ratio is finite there: the same decision by the old expression


def test_r21_m13_sprt_decide_ordinary_ratio_is_the_old_expression():
    """A finite ratio goes through `log(p1 / p0)` and not `log(p1) - log(p0)`, whose last bit differs: a count of failures that lands the LLR on a threshold
    is not moved (round 20's digest holds this too, for the two regions it uses)."""
    for p0, p1 in ((0.05, 0.15), (0.3, 0.5), (0.1, 0.2), (0.02, 0.06)):
        for k in range(0, 40):
            for n in range(k, 60):
                llr = k * math.log(p1 / p0) + (n - k) * math.log((1 - p1) / (1 - p0))
                want = "accept_nogo" if llr >= math.log(0.95 / 0.05) else "accept_go" if llr <= math.log(0.05 / 0.95) else "continue"
                assert Q.sprt_decide(k, n, p0, p1) == want


# ---- sensitivity -----------------------------------------------------------------------------------------------------------------------------------------

def _old_first_order(x, y, harmonics=None, correct=True):
    """The function before this round, verbatim apart from the guards: the oracle for "no ordinary S1 moved by a bit"."""
    n, d = x.shape
    y = np.asarray(y, float) - np.mean(y)
    out = np.zeros(d)
    if not np.any(y):
        return out
    m = S.default_harmonics(n) if harmonics is None else harmonics
    lam = 2 * m / n
    for i in range(d):
        order = np.argsort(x[:, i], kind="stable")
        seq = y[np.concatenate([order[0::2], order[1::2][::-1]])]
        p = np.abs(np.fft.fft(seq)) ** 2
        s = 2 * p[1:m + 1].sum() / p[1:].sum() if p[1:].sum() > 0 else 0.0
        out[i] = s - lam / (1 - lam) * (1 - s) if correct else s
    return np.clip(out, 0.0, 1.0)


def test_r21_m13_no_ordinary_first_order_index_moved_by_a_bit():
    """The power-of-two scaling and the centring after it give the bits of the old centring: 60 samples of n = 16 to 400, d = 1 to 4, y of five kinds,
    with and without the correction and with explicit harmonics. (A constant y is the one answer that moves: next test.)"""
    rng = np.random.default_rng(21)
    cases = 0
    for seed in range(60):
        n, d = int(rng.integers(16, 400)), int(rng.integers(1, 5))
        x = rng.random((n, d))
        for y in (rng.random(n), rng.standard_normal(n) * 10 ** float(rng.integers(-6, 7)), (rng.random(n) < 0.3).astype(float),
                  np.round(rng.random(n) * 20), x[:, 0] + 0.1 * rng.standard_normal(n)):
            for kw in (dict(), dict(correct=False), dict(harmonics=3)):
                cases += 1
                assert np.array_equal(S.first_order(x, y, **kw), _old_first_order(x, y, **kw)), (seed, kw)
    assert cases == 900


@pytest.mark.parametrize("n", [16, 17, 33, 47, 48, 64, 100, 211])
@pytest.mark.parametrize("v", [0.1, 0.3, 1 / 3, 7.7, 1e-5, 123456.789, -0.1, 1e300, 5e-324])
def test_r21_m13_a_constant_outcome_has_no_sensitivity_whatever_its_length(n, v):
    """The mean of 47 copies of 0.1 is not 0.1, so the centred y was not zero and the old test of it (`np.any`) let a residue through: S1 of 0.29 there. The
    documented "constant y gives zeros"."""
    x = np.random.default_rng(n).random((n, 3))
    assert not S.first_order(x, np.full(n, v)).any()
    assert not S.first_order(x, np.full(n, v), correct=False).any()


def test_r21_m13_the_constant_outcome_of_47_members_was_a_sensitivity_before():
    x = np.random.default_rng(47).random((47, 2))
    assert _old_first_order(x, np.full(47, 0.1)).max() > 0.05


def test_r21_m13_a_y_that_differs_by_one_ulp_is_not_constant():
    """The test is for one value exactly, not for "nearly": the rank of a parameter that orders y is found."""
    n = 64
    x = np.random.default_rng(5).random((n, 1))
    y = np.where(np.arange(n) % 2 == 0, 1.0, 1.0 + 2.0 ** -52)
    x[:, 0] = (np.arange(n) % 2) + 0.01 * np.random.default_rng(6).random(n)
    assert y.min() != y.max() and S.first_order(x, y)[0] > 0.5


@pytest.mark.parametrize("k", [-900, -300, -50, 50, 300, 900])
def test_r21_m13_the_index_does_not_depend_on_the_scale_of_y(k):
    """A power of two is exact, so S1 of 2**k * y is S1 of y to the bit, for scales whose squared spectrum is out of float range (1e160: NaN, 1e-200: zeros)."""
    rng = np.random.default_rng(3)
    x, y = rng.random((64, 3)), rng.standard_normal(64)
    base = S.first_order(x, y)
    assert base.max() > 0 and np.array_equal(S.first_order(x, y * 2.0 ** k), base)


def test_r21_m13_the_reproductions_of_the_scale():
    rng = np.random.default_rng(0)
    x, y = rng.random((64, 2)), np.random.default_rng(1).random(64)
    ref = S.first_order(x, y)
    for scale in (1e-200, 1e-160, 1e160, 1e200, 1e300, 1.7e308):
        got = S.first_order(x, y * scale)
        assert np.all(np.isfinite(got)) and np.allclose(got, ref, atol=1e-12), scale
    with np.errstate(all="ignore"):
        assert np.isnan(_old_first_order(x, y * 1e160)).all() and not _old_first_order(x, y * 1e-200).any()      # the old answers: NaN and zeros


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_r21_m13_a_non_finite_y_is_a_value_error_not_zeros(bad):
    """A NaN in y gave S1 of zero for every parameter, which the report reads as "no parameter matters"."""
    x, y = np.random.default_rng(1).random((32, 2)), np.random.default_rng(2).random(32)
    y[3] = bad
    with pytest.raises(ValueError, match="one finite number for each of the 32 rows"):
        S.first_order(x, y)
    with pytest.raises(ValueError, match="one finite number"):
        S.noise_floor(x, y, perms=3)
    with pytest.raises(ValueError, match="one finite number"):
        S.dominant(["a", "b"], x, y)


@pytest.mark.parametrize("y", [np.zeros(5), np.zeros((32, 1)), np.zeros(33)])
def test_r21_m13_a_y_of_the_wrong_length_is_a_value_error(y):
    """A y of 5 for 32 rows was an IndexError; a column vector was broadcast."""
    with pytest.raises(ValueError, match="one finite number for each of the 32 rows"):
        S.first_order(np.random.default_rng(1).random((32, 2)), y)


@pytest.mark.parametrize("h", [-3, -1, 0, True, False, 2.0, 2.5, "2"])
def test_r21_m13_harmonics_is_a_count_of_at_least_one(h):
    """-3 gave S1 of 1.0 for noise (lam < 0), -1 a share of 0.06, 0 zeros: none is a number of harmonics. A bool or a float is not a count."""
    x, y = np.random.default_rng(1).random((32, 2)), np.random.default_rng(2).random(32)
    with pytest.raises(ValueError, match="harmonics"):
        S.first_order(x, y, h)


def test_r21_m13_harmonics_one_is_the_smallest_and_n_over_two_is_still_refused():
    x, y = np.random.default_rng(1).random((32, 2)), np.random.default_rng(2).random(32)
    assert S.first_order(x, y, 1).shape == (2,) and np.array_equal(S.first_order(x, y, np.int16(3)), S.first_order(x, y, 3))
    assert S.first_order(x, y, 15).shape == (2,)
    with pytest.raises(ValueError, match="16 harmonics need more than 32 members"):
        S.first_order(x, y, 16)


@pytest.mark.parametrize("perms", [0, -1, 2.5, True, "3"])
def test_r21_m13_noise_floor_needs_a_count_of_permutations(perms):
    """No permutation left an empty list and `np.quantile` of it an IndexError."""
    x, y = np.random.default_rng(1).random((32, 2)), np.random.default_rng(2).random(32)
    with pytest.raises(ValueError, match="perms"):
        S.noise_floor(x, y, perms=perms)
    assert 0 <= S.noise_floor(x, y, perms=1) <= 1


def test_r21_m13_extreme_ranks_of_no_member_is_a_value_error():
    """The mean of an empty slice is NaN: it ranked every parameter as `[]` with a RuntimeWarning."""
    x = np.random.default_rng(1).random((20, 3))
    with pytest.raises(ValueError, match="marks no row"):
        S.extreme_ranks(["a", "b", "c"], x, np.zeros(20, bool))
    one = np.zeros(20, bool)
    one[4] = True
    assert len(S.extreme_ranks(["a", "b", "c"], x, one)) == 3


# ---- rare, sampling --------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("p0", [math.inf, -math.inf, math.nan, 0, 1, 1.5, -0.1, True, "0.1", None])
def test_r21_m13_subset_simulation_takes_p0_as_a_probability(p0):
    """An infinite p0 was an OverflowError from `round(n * p0)`, a bool or a string a TypeError; a p0 of 1 was a chain of length 1 (still a ValueError)."""
    with pytest.raises(ValueError, match="p0"):
        R.subset_simulation(lambda u: u[:, 0], 1, 1.0, n=100, p0=p0)


@pytest.mark.parametrize("n", [10 ** 400, TOP + 1, 1000.0, True, -5])
def test_r21_m13_subset_simulation_takes_n_as_a_count(n):
    """`n = 10**400` was an OverflowError, 2**53 a MemoryError (not tested: it would ask for 128 PiB); a float n is not a count, as everywhere in the module."""
    with pytest.raises(ValueError):
        R.subset_simulation(lambda u: u[:, 0], 1, 1.0, n=n)


def test_r21_m13_subset_simulation_with_a_numpy_n_and_p0_is_the_python_answer():
    a = R.subset_simulation(lambda u: u[:, 0], 1, 2.0, n=np.int32(200), p0=np.float32(0.5), seed=1)
    b = R.subset_simulation(lambda u: u[:, 0], 1, 2.0, n=200, p0=float(np.float32(0.5)), seed=1)
    assert a == b and a["converged"]


def test_r21_m13_a_stratification_report_of_no_member_is_a_value_error():
    """`1 / n` of zero members was a ZeroDivisionError."""
    with pytest.raises(ValueError, match="at least one member"):
        M.stratification_report(np.zeros((0, 2)))
    assert M.stratification_report(np.array([[0.5, 0.25]]))["n"] == 1


# ---- the sweep: every public function over its whole guarded domain ---------------------------------------------------------------------------------------

def _public(module):
    import inspect
    return {n for n, f in inspect.getmembers(module, inspect.isfunction) if not n.startswith("_") and f.__module__ == module.__name__}


# What each public function of the five modules is run with below (or why it is not): a function added without a place here fails the first test.
SWEPT = {
    I: {"set_thresholds": "sweep_thresholds", "wilson": "sweep_intervals", "newcombe_diff": "sweep_intervals", "agresti_coull": "sweep_intervals",
        "interval": "sweep_intervals", "rule_of_three": "sweep_intervals", "n_certify": "sweep_certify", "n_certify_one_sided": "sweep_certify",
        "verdict_from_p": "sweep_thresholds", "verdict_band": "sweep_thresholds", "band_in": "sweep_thresholds", "verdict": "sweep_intervals",
        "interval_region": "sweep_intervals", "decided_region": "sweep_intervals", "coverage": "sweep_coverage",
        "receipts": "not swept: builds the published receipts, takes no argument"},
    Q: {"sprt_indifference": "sweep_sprt", "sprt_decide": "sweep_sprt", "ensemble_stop": "sweep_intervals"},
    S: {"default_harmonics": "sweep_sensitivity", "first_order": "sweep_sensitivity", "noise_floor": "sweep_sensitivity",
        "dominant": "test_r21_m13_dominant_takes_the_refusals_of_first_order",
        "extreme_ranks": "sweep_sensitivity"},
    R: {"subset_simulation": "sweep_rare"},
    M: {"marginal": "sweep_sampling", "check_entry": "sweep_sampling", "load_perturbations": "not swept: reads a file (tests/test_stats.py)",
        "to_marginals": "sweep_sampling", "lhs_unit": "sweep_sampling", "lhs": "sweep_sampling", "stratification_report": "test above (no member)",
        "marginal_report": "sweep_sampling", "member_seed": "sweep_sampling", "member_rng": "sweep_sampling"},
}


def test_r21_m13_every_public_function_of_every_stats_module_is_in_the_sweep():
    """Round 20's table listed two of the five modules. A new public function with an argument must be given its place, so no sibling is left for round 22."""
    for module, table in SWEPT.items():
        assert _public(module) == set(table), module.__name__


def _finite(x):
    if isinstance(x, (float, np.floating)):
        return math.isfinite(x)
    if isinstance(x, (tuple, list)):
        return all(_finite(i) for i in x)
    if isinstance(x, dict):
        return all(_finite(i) for i in x.values())
    if isinstance(x, np.ndarray):
        return bool(np.isfinite(x).all())
    return True


def _run(call):
    """The result of `call`; the module's ValueError is None; anything else (an OverflowError, ZeroDivisionError, MemoryError, TypeError) fails the test."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")                              # an overflow or a divide by zero in numpy is a failure here, not a note
        try:
            return call()
        except ValueError:
            return None


def _ok(call):
    """`_run`, and the result holds no NaN or infinity."""
    r = _run(call)
    assert _finite(r), r
    return r


PROB = st.one_of(st.floats(min_value=0.0, max_value=1.0, exclude_min=True, exclude_max=True, allow_subnormal=True), st.sampled_from(EDGE_PROBS))
COUNT = st.one_of(st.integers(0, TOP), st.sampled_from(EDGE_COUNTS))
ANY_NUMBER = st.one_of(PROB, st.floats(allow_nan=True, allow_infinity=True), st.integers(-10 ** 400, 10 ** 400),
                       st.sampled_from([0, 1, -1, 10 ** 400, -10 ** 400, TOP]))


@settings(max_examples=300, **SLOW)
@given(level=PROB, conf=PROB)
def test_r21_m13_sweep_certify(level, conf):
    for f in (I.n_certify, I.n_certify_one_sided):
        n = _ok(lambda f=f: f(level, conf))
        assert n is None or (type(n) is int and 1 <= n <= TOP)


@settings(max_examples=400, **SLOW)
@given(k=COUNT, n=COUNT, conf=PROB, level=PROB, cert_conf=PROB, k2=COUNT, n2=COUNT, nmin=COUNT, nmax=st.one_of(st.none(), COUNT))
def test_r21_m13_sweep_intervals(k, n, conf, level, cert_conf, k2, n2, nmin, nmax):
    r = _ok(lambda: I.wilson(k, n, conf))
    if r is not None:
        assert 0.0 <= r[0] <= r[1] <= 1.0 and r[0] <= k / n * (1 + 1e-12) and r[1] >= k / n * (1 - 1e-12)
    r = _ok(lambda: I.agresti_coull(k, n, conf))
    assert r is None or 0.0 <= r[0] <= r[1] <= 1.0
    r = _ok(lambda: I.newcombe_diff(k, n, k2, n2, conf))
    assert r is None or -1.0 <= r[0] <= r[1] <= 1.0
    r = _ok(lambda: I.interval(k, n, conf))
    assert r is None or (0.0 <= r[0] <= r[1] <= 1.0 and r[2] == "wilson")
    r = _ok(lambda: I.rule_of_three(n))
    assert r is None or 0.0 < r <= 3.0
    v = _ok(lambda: I.verdict(k, n, conf, level, cert_conf))
    if v is not None:
        assert v["verdict"] in ("GO", "MARGINAL", "NO-GO") and 1 <= v["n_certify"] <= TOP and 0.0 <= v["fail_lo"] <= v["fail_hi"] <= 1.0
    for f in (I.interval_region, I.decided_region):
        assert _ok(lambda f=f: f(k, n, conf)) in (None, "GO", "NO-GO", "MARGINAL")
    e = _ok(lambda: Q.ensemble_stop(k, n, conf, nmin, nmax))
    assert e is None or isinstance(e["stop"], bool)


@settings(max_examples=300, **SLOW)
@given(go=PROB, nogo=PROB, p=PROB, lo=PROB, hi=PROB)
def test_r21_m13_sweep_thresholds(go, nogo, p, lo, hi):
    """`set_thresholds` leaves 0 <= P_FAIL_GO < P_FAIL_NOGO <= 1 or leaves the old pair, and the verdicts that read it answer."""
    before = (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO)
    r = _ok(lambda: I.set_thresholds(go, nogo))
    assert r is None
    now = (I.P_FAIL_GO, I.P_FAIL_NOGO, I.LO_SUCCESS_GO)
    assert now == before or 0.0 <= now[0] < now[1] <= 1.0
    assert _ok(lambda: I.verdict_from_p(p)) in ("GO", "MARGINAL", "NO-GO")
    assert _ok(lambda: I.verdict_band(p, lo, hi)) in ("GO", "MARGINAL", "NO-GO")
    assert _ok(lambda: I.band_in(min(lo, hi), max(lo, hi), ("GO", "MARGINAL"))) in (True, False)


@settings(max_examples=60, **SLOW)
@given(n=st.integers(1, 40), conf=PROB, method=st.sampled_from(["wilson", "agresti_coull"]))
def test_r21_m13_sweep_coverage(n, conf, method):
    """`coverage` lists every k from 0 to n, so a count in the billions is a request for gigabytes (a MemoryError at 2**53) and not an arithmetic fault: swept
    the sizes it is used at, and at the probabilities of its grid, ends included."""
    r = _ok(lambda: I.coverage(n, np.array([0.0, 1e-300, 0.3, 1 - 1.1e-16, 1.0]), conf, method))
    assert r is None or (r.shape == (5,) and np.all((r >= 0) & (r <= 1 + 1e-9)))


@settings(max_examples=400, **SLOW)
@given(cut=ANY_NUMBER, delta=ANY_NUMBER, k=COUNT, n=COUNT, p0=PROB, p1=PROB, alpha=PROB, beta=PROB)
def test_r21_m13_sweep_sprt(cut, delta, k, n, p0, p1, alpha, beta):
    r = _ok(lambda: Q.sprt_indifference(cut, delta))
    assert r is None or (0 < r[0] < r[1] < 1 and all(type(v) is float for v in r))
    assert _ok(lambda: Q.sprt_decide(k, n, p0, p1, alpha, beta)) in (None, "accept_go", "accept_nogo", "continue")
    assert _ok(lambda: Q.sprt_decide(k, n, min(p0, p1), max(p0, p1))) in (None, "accept_go", "accept_nogo", "continue")


@settings(max_examples=60, **SLOW)
@given(n=st.integers(16, 40), d=st.integers(1, 3), seed=st.integers(0, 5), mag=st.integers(-300, 300), kind=st.sampled_from(["const", "scaled", "values"]),
       h=st.one_of(st.none(), st.integers(-3, 25), st.sampled_from([True, 2.0])), correct=st.booleans(), bad=st.sampled_from([None, np.nan, np.inf]),
       vals=st.lists(st.floats(allow_nan=False, allow_infinity=False, width=64), min_size=40, max_size=40))
def test_r21_m13_sweep_sensitivity(n, d, seed, mag, kind, h, correct, bad, vals):
    """y constant at any magnitude, any scale from 1e-300 to 1e300, and any 40 finite floats (1.8e308 beside 5e-324 included), with any `harmonics`."""
    rng = np.random.default_rng(seed)
    x = rng.random((n, d))
    y = np.full(n, 10.0 ** (mag / 2)) if kind == "const" else rng.standard_normal(n) * 10.0 ** mag if kind == "scaled" else np.array(vals[:n])
    if bad is not None:
        y[0] = bad
    r = _ok(lambda: S.first_order(x, y, h, correct))
    assert r is None or (r.shape == (d,) and np.all((r >= 0) & (r <= 1)) and (kind != "const" or not r.any()))
    f = _ok(lambda: S.noise_floor(x, y, perms=3, harmonics=h))
    assert f is None or 0.0 <= f <= 1.0
    names = [f"p{i}" for i in range(d)]
    e = _ok(lambda: S.extreme_ranks(names, x, rng.random(n) < 0.1))
    assert e is None or (len(e) == min(3, d) and all(ranks == sorted(ranks) for _, ranks in e))
    assert _ok(lambda: S.default_harmonics(n)) in range(2, 7)


def test_r21_m13_dominant_takes_the_refusals_of_first_order():
    """`dominant` runs the 2000 permutations of `noise_floor`, so it is not in the sweep above: its inputs are first_order's."""
    x, y = np.random.default_rng(1).random((32, 2)), np.random.default_rng(2).random(32)
    assert S.dominant(["a", "b"], x, y)[0] in (None, "a", "b")
    assert S.dominant(["a", "b"], x, np.full(32, 0.1)) == (None, {"a": 0.0, "b": 0.0}, 0.0)
    with pytest.raises(ValueError, match="harmonics"):
        S.dominant(["a", "b"], x, y, harmonics=-3)


@settings(max_examples=40, **SLOW)
@given(n=st.one_of(st.integers(-3, 300), st.sampled_from([TOP + 1, 10 ** 400])), p0=st.one_of(PROB, st.sampled_from([math.inf, math.nan, 0.0, 1.0, -0.5])),
       target=st.sampled_from([-math.inf, -50.0, 0.5, 2.0, 30.0, math.inf, math.nan]))
def test_r21_m13_sweep_rare(n, p0, target):
    """The sizes that can be run (up to 300) and the counts it refuses; a count between them is a request for memory (2**53 is 128 PiB), not an arithmetic
    fault. `cov` is infinite for a run that did not converge, which is documented."""
    r = _run(lambda: R.subset_simulation(lambda u: u[:, 0], 1, target, n=n, p0=p0, seed=1, max_levels=3))
    assert r is None or (0.0 <= r["p"] <= 1.0 and isinstance(r["converged"], bool) and r["cov"] >= 0.0 and math.isfinite(r["p"]))


@settings(max_examples=60, **SLOW)
@given(dist=st.sampled_from(["normal", "lognormal", "uniform"]), a=st.floats(allow_nan=False, allow_infinity=False), b=st.floats(allow_nan=False,
       allow_infinity=False), n=st.integers(0, 12), seed=st.integers(0, 3), anti=st.booleans(), member=st.integers(0, 2 ** 40), name=st.text(max_size=5))
def test_r21_m13_sweep_sampling(dist, a, b, n, seed, anti, member, name):
    """Every entry `check_entry` lets through gives finite members through `lhs` (a lognormal of sigma 100 and a normal of sd 2e307 included): the guard
    and the arithmetic agree."""
    spec = dict(dist=dist, value=abs(b), unit="x", citation="c", kind="assumed")
    if dist == "normal":
        spec["mean"] = a
    elif dist == "lognormal":
        spec["median"] = abs(a)
    else:
        spec.update(lo=min(a, b), hi=max(a, b))
    try:
        M.check_entry("q", spec)
    except ValueError:
        return
    marg = M.to_marginals({"q": spec})
    u, xs = _ok(lambda: M.lhs(n, marg, seed, ("q",) if anti and n and n % 2 == 0 else ()))
    assert np.isfinite(xs["q"]).all() and u.shape == (n, 1) and _finite(M.marginal_report(xs, marg)) if n else xs["q"].shape == (0,)
    assert isinstance(_ok(lambda: M.member_seed(seed, member, name)), int)
    assert isinstance(_ok(lambda: M.member_rng(seed, member, name)).random(), float)
    assert _ok(lambda: M.lhs_unit(n, 2, np.random.default_rng(seed))).shape == (n, 2)
    if n:
        assert M.stratification_report(M.lhs_unit(n, 2, np.random.default_rng(seed)))["ok"] is True
    assert M.marginal(dict(dist="uniform", lo=min(a, b), hi=max(a, b))) is not None
