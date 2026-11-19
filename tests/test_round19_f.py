"""Round 19, batch F: the count rule of the interval functions and of `sprt_decide` (M-8: a narrow numpy integer wrapped in `4 * n * n`, and k above n was
answered), and the surviving mutants of the hull grammar and of `sprt_decide` (M-16, A-8)."""
import numpy as np
import pytest

from cafe import fea
from cafe.pm.stats import intervals as I
from cafe.pm.stats import sequential as Q

# the integer types a count can arrive in: a sum of flags is int64, a stored column may be any width
DTYPES = [np.uint8, np.int8, np.uint16, np.int16, np.uint32, np.int32, np.uint64, np.int64, np.intp]


def _top(dt, cap=40_000):
    """The largest n this dtype holds, up to `cap`: where `4 * n * n` is past 2**7, 2**15 and 2**31 for the narrow types."""
    return min(int(np.iinfo(dt).max), cap)


# ---- M-8: the count rule gives a Python int and every use takes it --------------------------------------------------------------------------------------

@pytest.mark.parametrize("dt", DTYPES, ids=lambda d: d.__name__)
def test_r19_m8_count_returns_a_python_int(dt):
    got = I._count(dt(7), "k")
    assert got == 7 and type(got) is int


def test_r19_m8_check_returns_both_counts_as_python_ints():
    k, n = I._check(np.uint8(3), np.int16(10), 0.95)
    assert (k, n) == (3, 10) and type(k) is int and type(n) is int
    k, n = I._check(np.uint8(3), np.int16(10), 0.95, ("k1", "n1"))
    assert (k, n) == (3, 10)


@pytest.mark.parametrize("dt", DTYPES, ids=lambda d: d.__name__)
@pytest.mark.parametrize("f", [I.wilson, I.agresti_coull, I.interval, I.verdict, I.interval_region, I.decided_region], ids=lambda f: f.__name__)
def test_r19_m8_a_narrow_integer_gives_the_python_int_answer(dt, f):
    """`wilson(np.uint8(30), np.uint8(100))` was (0.0, 0.778) against (0.219, 0.396): `4 * n * n` wrapped in the caller's width. Largest n the type holds (up
    to 40,000) and a third of it as k, and a small one."""
    for n in (_top(dt), 10):
        k = n // 3
        assert f(dt(k), dt(n)) == f(k, n)
        assert f(dt(0), dt(n)) == f(0, n) and f(dt(n), dt(n)) == f(n, n)


@pytest.mark.parametrize("dt", DTYPES, ids=lambda d: d.__name__)
def test_r19_m8_newcombe_with_narrow_integers_gives_the_python_int_answer(dt):
    n1, n2 = _top(dt), _top(dt) // 2 + 1
    assert I.newcombe_diff(dt(n1 // 3), dt(n1), dt(n2 // 4), dt(n2)) == I.newcombe_diff(n1 // 3, n1, n2 // 4, n2)


def test_r19_m8_the_reproductions_of_the_finding():
    assert I.wilson(np.uint8(30), np.uint8(100)) == I.wilson(30, 100) == pytest.approx((0.2189488, 0.3958485), abs=1e-6)
    assert I.wilson(np.int8(3), np.int8(10)) == I.wilson(3, 10)            # a math-domain error before: sqrt of a negative from the wrapped 4 * n * n


def test_r19_m8_rule_of_three_and_the_stopper_take_narrow_integers():
    assert I.rule_of_three(np.uint8(60)) == I.rule_of_three(60) == 0.05
    assert Q.ensemble_stop(np.uint8(30), np.uint8(100)) == Q.ensemble_stop(30, 100)
    assert Q.ensemble_stop(np.uint8(0), np.uint8(100), n_min=np.uint8(73)) == Q.ensemble_stop(0, 100, n_min=73)


def test_r19_m8_int64_and_arrays_give_what_python_ints_give():
    """The callers pass `int(flags.sum())` (a Python int) or a sum a numpy array gives (int64): same numbers, bit for bit."""
    flags = np.arange(73) % 4 == 0
    k, n = flags.sum(), flags.size
    assert type(k) is np.int64
    assert I.wilson(k, n) == I.wilson(int(k), int(n)) and I.interval(k, n, 0.9) == I.interval(int(k), int(n), 0.9)
    assert I.agresti_coull(k, n) == I.agresti_coull(int(k), int(n))
    assert I.newcombe_diff(k, n, k + 1, n) == I.newcombe_diff(int(k), int(n), int(k) + 1, int(n))
    assert I.verdict(k, n) == I.verdict(int(k), int(n))
    assert Q.sprt_decide(k, n, 0.1, 0.3) == Q.sprt_decide(int(k), int(n), 0.1, 0.3)


# ---- M-8: sprt_decide checks the range a count of n runs has --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("k, n", [(5, 3), (1, 0), (-1, 3), (0, -1), (-3, -1), (4, 3)])
def test_r19_m8_sprt_decide_refuses_a_k_outside_0_to_n(k, n):
    """`sprt_decide(5, 3, ...)` was answered (accept_nogo, or accept_go from `np.uint8(5), np.uint8(3)`, whose `n - k` wrapped)."""
    with pytest.raises(ValueError, match=r"need 0 <= k <= n, got k=-?\d+, n=-?\d+"):
        Q.sprt_decide(k, n, 0.1, 0.3)


@pytest.mark.parametrize("dt", DTYPES, ids=lambda d: d.__name__)
def test_r19_m8_sprt_decide_refuses_a_narrow_k_above_n(dt):
    with pytest.raises(ValueError, match="need 0 <= k <= n, got k=5, n=3"):
        Q.sprt_decide(dt(5), dt(3), 0.1, 0.3)


def test_r19_m8_sprt_decide_keeps_the_edges_of_the_range():
    """k = 0, k = n and n = 0 (no run yet: continue) are counts, and are answered."""
    assert Q.sprt_decide(0, 0, 0.1, 0.3) == "continue"
    assert Q.sprt_decide(0, 1, 0.1, 0.3) == "continue" and Q.sprt_decide(1, 1, 0.1, 0.3) == "continue"
    assert Q.sprt_decide(0, 40, 0.1, 0.3) == "accept_go" and Q.sprt_decide(40, 40, 0.1, 0.3) == "accept_nogo"
    assert Q.sprt_decide(np.uint8(40), np.uint8(40), 0.1, 0.3) == "accept_nogo"


def test_r19_m8_sprt_decide_checks_the_kind_before_the_range():
    with pytest.raises(ValueError, match="k must be an integer count"):
        Q.sprt_decide(5.0, 3, 0.1, 0.3)
    with pytest.raises(ValueError, match="n must be an integer count"):
        Q.sprt_decide(1, True, 0.1, 0.3)


def test_r19_m8_sprt_decide_takes_both_counts_from_the_helper(monkeypatch):
    """What `_count` returns is what is used: a helper that returns 1 for k and 10 for n is read as (1, 10), not as the arguments."""
    assert Q.sprt_decide(100, 200, 0.05, 0.15) == "accept_nogo" and Q.sprt_decide(1, 10, 0.05, 0.15) == "continue"
    seen = []
    monkeypatch.setattr(I, "_count", lambda x, name: seen.append((x, name)) or {"k": 1, "n": 10}[name])
    assert Q.sprt_decide(100, 200, 0.05, 0.15) == "continue"
    assert seen == [(100, "k"), (200, "n")]


# ---- M-16, A-8: the hull grammar's refusals that no test held (G11 and G16 survived every test file that names the reader; G14 only the stage-3 rows) ----

KEY = "stage3.fea_elements_along:"
ENTRY = f"{KEY}\n  value: 70\n  unit: x\n"


def _refusal(tmp_path, monkeypatch, text):
    f = tmp_path / "assumptions.yaml"
    f.write_bytes(text.encode("utf-8"))
    monkeypatch.setattr(fea, "ASSUMPTIONS", f)
    with pytest.raises(ValueError, match="stage3.fea_elements_along") as e:
        fea.hull_elements_along()
    return str(e.value)


@pytest.mark.parametrize("word", [":a", ":8", ":-)", ":a b"])
def test_r19_a8_a_plain_text_that_starts_with_a_colon_is_outside_the_grammar(tmp_path, monkeypatch, word):
    """G11: `_NOT_PLAIN_FIRST` without the colon. `: x` and a trailing colon are refused by the plain text's own `: ` check, so only a colon followed by a
    character that is not a space tells the two apart (the docstring: a plain text does not start with one of `[]{},#&*!|>'"%@`, a backquote, `?` or `:`)."""
    msg = _refusal(tmp_path, monkeypatch, f"o:\n  why: {word}\n{ENTRY}")
    assert "line 2," in msg and "is outside the grammar" in msg


def test_r19_a8_a_colon_inside_a_plain_text_is_still_read(tmp_path, monkeypatch):
    """The neighbour of G11: the rule is about the first character only."""
    f = tmp_path / "assumptions.yaml"
    f.write_bytes(f"o:\n  why: a:b\n{ENTRY}".encode())
    monkeypatch.setattr(fea, "ASSUMPTIONS", f)
    assert fea.hull_elements_along() == 70


def test_r19_a8_a_line_outside_the_grammar_is_named_by_its_first_40_characters_only(tmp_path, monkeypatch):
    """G16, the first message: the refusal prints `ln[:40]`, not the whole line (an assumptions.yaml line may be a page of text)."""
    ln = "  why: [a, b] " + "x" * 60
    msg = _refusal(tmp_path, monkeypatch, f"o:\n{ln}\n{ENTRY}")
    assert repr(ln[:40]) in msg and ln[:41] not in msg and "x" * 40 not in msg


def test_r19_a8_an_indented_line_is_named_by_its_first_40_characters_only(tmp_path, monkeypatch):
    """G16, the second message (a line deeper than a child)."""
    ln = "    " + "k" * 60 + ": 1"
    msg = _refusal(tmp_path, monkeypatch, f"{KEY}\n  value: 70\n  unit: x\n{ln}\n")
    assert "is indented 4 spaces" in msg and repr(ln[:40]) in msg and ln[:41] not in msg


@pytest.mark.parametrize("key_line", [f"{KEY} x", f"{KEY} 5", f"{KEY} 'x'", f"{KEY} [1, 2]"])
def test_r19_a8_a_key_line_with_text_after_the_colon_is_refused_as_a_key_line(tmp_path, monkeypatch, key_line):
    """G14: with the `_MESH_KEY_LINE` check gone these lines pass the grammar (a plain, quoted or list scalar is one) and are refused later as 'has no value',
    so a key line holding a value is no longer named as one."""
    msg = _refusal(tmp_path, monkeypatch, f"{key_line}\n")
    assert "the key line is" in msg and key_line in msg
