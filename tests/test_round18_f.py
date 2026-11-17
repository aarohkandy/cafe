"""Round 18, batch F: the hull mesh reader's closed grammar and its differential fuzz (M-10), and the integer count of the interval functions (M-14)."""
import math
import random

import numpy as np
import pytest
import yaml

from cafe import fea
from cafe.pm.stats import intervals as I

KEY = "stage3.fea_elements_along:"


def _file(tmp_path, monkeypatch, text, name="assumptions.yaml"):
    f = tmp_path / name
    f.write_bytes(text.encode("utf-8"))
    monkeypatch.setattr(fea, "ASSUMPTIONS", f)
    return f


def _read(tmp_path, monkeypatch, text):
    _file(tmp_path, monkeypatch, text)
    return fea.hull_elements_along()


def _pyyaml(path):
    """What the pipeline's reading of the same file gives for the entry (`config._yaml` loads `path.read_text()` with a safe loader), or the error it raises."""
    try:
        return yaml.safe_load(path.read_text())[KEY[:-1]]["value"]
    except Exception as e:                                                   # any refusal: a scanner, reader or constructor error, a missing key
        return e


# ---- M-10: the shipped file ------------------------------------------------------------------------------------------------------------------------------

def test_r18_m10_the_shipped_file_is_inside_the_grammar_and_both_readers_give_70():
    """The first thing the grammar must do: read the file the repository ships (527 lines, every entry `key:` with `value`, `unit`, `why`, `replace_with`
    children, the texts in double quotes with a `: ` in some), and give the number PyYAML gives."""
    want = yaml.safe_load(fea.ASSUMPTIONS.read_text())[KEY[:-1]]["value"]
    assert fea.hull_elements_along() == want == 70


# ---- M-10: the layouts of the finding (A-9 and D-5) -------------------------------------------------------------------------------------------------------

_ENTRY = f"{KEY}\n  value: 70\n  unit: x\n"


@pytest.mark.parametrize("text", [
    f"{KEY}\n  value:\t70\n  unit: x\n",                                    # D-5: a tab after the colon of value, PyYAML ScannerError
    f"{KEY}\n  value: 70\x0c\n  unit: x\n",                                 # D-5: a form feed, PyYAML ReaderError
    f"{KEY}\n  value: 70\x0b\n  unit: x\n",                                 # D-5: a vertical tab
    f"{KEY}\n  unit: a: b\n  value: 70\n",                                  # D-5: a sibling's `a: b`, ScannerError
    f"{KEY}\n  value: 70\n  unit: x\n    deeper: 1\n",                     # A-9: a deeper line after a key other than value, ScannerError
])
def test_r18_m10_the_five_layouts_of_the_finding_are_refused_where_pyyaml_does_not_give_70(tmp_path, monkeypatch, text):
    f = _file(tmp_path, monkeypatch, text)
    assert _pyyaml(f) != 70                                                  # PyYAML raises, or gives something that is not 70
    with pytest.raises(ValueError, match="stage3.fea_elements_along"):
        fea.hull_elements_along()


@pytest.mark.parametrize("ch", ["\t", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x7f", "\x00", "\x85", "\u2028", "\u2029", "\ufffe"])
@pytest.mark.parametrize("where", ["comment", "other entry", "quoted text", "end"])
def test_r18_m10_a_tab_control_or_exotic_line_break_anywhere_in_the_file_is_refused(tmp_path, monkeypatch, ch, where):
    """Before `splitlines`, which splits on \\x0b, \\x0c, \\x1c to \\x1e, \\x85, U+2028 and U+2029 where YAML does not (or the other way), and before a regular
    expression's `.` or `\\s` reads one: the character in a comment, in a sibling entry's text, in a quoted text and after the entry."""
    body = {"comment": f"# a{ch}b\n{_ENTRY}", "other entry": f"o:\n  why: a{ch}b\n{_ENTRY}", "quoted text": f'o:\n  why: "a{ch}b"\n{_ENTRY}',
            "end": f"{_ENTRY}\n{ch}"}[where]
    with pytest.raises(ValueError, match="the file holds the character"):
        _read(tmp_path, monkeypatch, body)


@pytest.mark.parametrize("name, text", [
    ("deeper line after unit", f"{KEY}\n  unit: x\n    deeper: 1\n  value: 70\n"),
    ("deeper line after why in a quoted text", f"{KEY}\n  why: \"x\"\n    more\n  value: 70\n"),
    ("deeper comment-looking text is not a comment", f"{KEY}\n  value: 70\n   x # y\n"),
    ("four-space children", f"{KEY}\n    value: 70\n"),
    ("one-space children", f"{KEY}\n value: 70\n"),
    ("a child of nothing", f"  value: 70\n{KEY}\n  value: 70\n"),
    ("a child under a key with a scalar", f"a: 1\n  b: 2\n{_ENTRY}"),
    ("a child under a key with a quoted scalar", f"a: \"1\"\n  b: 2\n{_ENTRY}"),
    ("a sibling's `a: b`, in another entry", f"o:\n  unit: a: b\n{_ENTRY}"),
    ("a sibling's colon at the end", f"o:\n  unit: a:\n{_ENTRY}"),
    ("a top-level `a: b: c`", f"a: b: c\n{_ENTRY}"),
    ("a list in another entry", f"o:\n  - item\n{_ENTRY}"),
    ("a list in the entry", f"{KEY}\n  - item\n  value: 70\n"),
    ("a block scalar in another entry", f"o:\n  why: >\n    text\n{_ENTRY}"),
    ("a literal block scalar", f"o:\n  why: |\n  text\n{_ENTRY}"),
    ("a flow mapping in another entry", f"o:\n  why: {{a: 1}}\n{_ENTRY}"),
    ("a flow sequence", f"o:\n  why: [a, b]\n{_ENTRY}"),
    ("a list with a word in it", f"o:\n  why: [1, a]\n{_ENTRY}"),
    ("an empty list", f"o:\n  why: []\n{_ENTRY}"),
    ("a list with a trailing comma", f"o:\n  why: [1,]\n{_ENTRY}"),
    ("a nested list", f"o:\n  why: [[1]]\n{_ENTRY}"),
    ("a list with text after it", f"o:\n  why: [1] x\n{_ENTRY}"),
    ("a flow sequence that runs over lines", f"o:\n  why: [a,\n  value: 5]\n{_ENTRY}"),
    ("an anchor", f"o:\n  why: &a x\n{_ENTRY}"),
    ("an alias", f"o:\n  why: *a\n{_ENTRY}"),
    ("a tag", f"o:\n  why: !!str x\n{_ENTRY}"),
    ("a directive", f"%YAML 1.1\n{_ENTRY}"),
    ("a document start", f"---\n{_ENTRY}"),
    ("a document end", f"{_ENTRY}...\n"),
    ("a backslash escape PyYAML does not know", f"o:\n  why: \"a\\qb\"\n{_ENTRY}"),
    ("a backslash escape it does", f"o:\n  why: \"a\\nb\"\n{_ENTRY}"),
    ("a quote that does not end on its line", f"o:\n  why: \"abc\n  def\"\n{_ENTRY}"),
    ("a single quote that does not end", f"o:\n  why: 'abc\n{_ENTRY}"),
    ("text after a closing quote", f"o:\n  why: \"a\" b\n{_ENTRY}"),
    ("two quoted texts", f"o:\n  why: 'a' 'b'\n{_ENTRY}"),
    ("a lone dash", f"o:\n  why: -\n{_ENTRY}"),
    ("a dash and a space", f"o:\n  why: - a\n{_ENTRY}"),
    ("a question mark", f"o:\n  why: ? a\n{_ENTRY}"),
    ("a colon first", f"o:\n  why: : a\n{_ENTRY}"),
    ("a percent first", f"o:\n  why: %a\n{_ENTRY}"),
    ("a quoted key", f"o:\n  \"why\": a\n{_ENTRY}"),
    ("a key with a space", f"o:\n  a b: c\n{_ENTRY}"),
    ("a key with no space after its colon", f"o:\n  why:a\n{_ENTRY}"),
    ("a text with no key", f"o:\n  just some words\n{_ENTRY}"),
    ("a top-level text with no key", f"words\n{_ENTRY}"),
    ("a top-level list", f"- a\n{_ENTRY}"),
    ("a complex key", f"? a\n{_ENTRY}"),
    ("a merge key", f"<<: a\n{_ENTRY}"),
    ("the entry's key quoted", "\"stage3.fea_elements_along\":\n  value: 70\n"),
])
def test_r18_m10_a_line_outside_the_grammar_is_refused_wherever_it_stands(tmp_path, monkeypatch, name, text):
    """Whatever the layout: the reader raises a ValueError that names the entry. (PyYAML accepts some of these: the grammar is closed, not equal to YAML.)"""
    with pytest.raises(ValueError, match="stage3.fea_elements_along"):
        _read(tmp_path, monkeypatch, text)


@pytest.mark.parametrize("name, text", [
    ("the shipped shape", f"# a note\n\na: 1\n  # indented note\n   \n{KEY}  # mesh\n  value: 70\n  why: \"- x: 1\"\nb:\n  why: 'it''s: fine'\n"),
    ("a quoted text with a colon and a hash", f"o:\n  why: \"a: b # c\"\n{_ENTRY}"),
    ("a comment after a quoted text", f"o:\n  why: \"a\"   # note\n{_ENTRY}"),
    ("a plain text with a hash inside", f"o:\n  why: a#b\n{_ENTRY}"),
    ("a plain text with a colon not before a space", f"o:\n  why: a:b http://x\n{_ENTRY}"),
    ("a comment holding a colon", f"o:\n  why: a # b: c\n{_ENTRY}"),
    ("a list of numbers", f"o:\n  value: [0.2, 3.0]\n  unit: [-5.0,5]  # a range\n  why: [ 1 , -2.5 ]\n{_ENTRY}"),
    ("a negative number", f"o:\n  value: -0.5\n{_ENTRY}"),
    ("empty and null children", f"o:\n  why:\n  unit: # nothing\n  value: ~\n{_ENTRY}"),
    ("trailing spaces", f"{KEY}   \n  value: 70   \n  unit: x  \n"),
    ("CRLF", f"{KEY}\r\n  value: 70\r\n  unit: x\r\n"),
    ("a no-break space inside a quoted text", f"o:\n  why: \"a\u00a0b\"\n{_ENTRY}"),
    ("a non-ASCII text", f"o:\n  why: \"\u00e9 \u4e2d \U0001f642\"\n{_ENTRY}"),
    ("a top-level scalar", f"a: 1\nb: 'two'\n{_ENTRY}"),
    ("a key that is a number", f"1: a\n{_ENTRY}"),
])
def test_r18_m10_what_is_inside_the_grammar_reads_and_pyyaml_gives_the_same_number(tmp_path, monkeypatch, name, text):
    f = _file(tmp_path, monkeypatch, text)
    assert fea.hull_elements_along() == _pyyaml(f) == 70


_NOT_A_NUMBER = "not a whole number"


@pytest.mark.parametrize("value, why", [("2.5", _NOT_A_NUMBER), ("070", _NOT_A_NUMBER), ("7_0", _NOT_A_NUMBER), ("+70", _NOT_A_NUMBER),
                                        ("0x46", _NOT_A_NUMBER), ("1:10", _NOT_A_NUMBER), ("'70'", _NOT_A_NUMBER), ("\"70\"", _NOT_A_NUMBER),
                                        ("", _NOT_A_NUMBER), ("70 more", _NOT_A_NUMBER), ("0", "below 1"), ("501", "above 500")])
def test_r18_m10_the_value_is_a_plain_whole_number_from_1_to_500(tmp_path, monkeypatch, value, why):
    with pytest.raises(ValueError, match=why):
        _read(tmp_path, monkeypatch, f"{KEY}\n  value: {value}\n")


# ---- M-10: the differential fuzz --------------------------------------------------------------------------------------------------------------------------

_CHARS = ["\t", "\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\u2029", "\u00a0", "\ufeff", "\r", " ", "  ", ":", ": ", " #", "#", "\"", "'", "\\", "-", "- ",
          "[", "]", "{", "}", ",", "&", "*", "!", "|", ">", "%", "@", "`", "?", "0", "7", "_", ".", "a"]
_LINES = ["  unit: a: b", "    deeper: 1", "  deeper:", "  - x", "- x", "---", "...", "a: &x 1", "b: *x", "c: !!str 1", "d: |", "  e: f", "  value: 45",
          "  value: 70", "stage3.fea_elements_along:", "  why: \"a\\qb\"", "  why: \"a", "  why: 'a", "  ? k", "  k: [1,", "  k: {a: b}", "\ta: 1", "  # c",
          "", "   ", " x: 1", "?", ":", "%TAG", "  value:\t70", "  value: 70 # c", "  value: 70 more", "  unit: x:", "  unit: 'it''s'"]
_VALUES = ["070", "7_0", "0x46", "0o106", "0b1000110", "70.0", "7e1", "+70", "-70", "1:10", ".inf", "~", "null", "true", "'70'", "\"70\"", "70 more",
           "70#x", "70 #x", "&a 70", "!!int 70", "[70]", "{a: 70}", "501", "0", "00", "700", "7", "70\u00a0"]


def _mutate(rng, text):
    lines = text.split("\n")
    for _ in range(rng.choice([1, 1, 2, 3])):
        op = rng.randrange(10)
        i = rng.randrange(len(lines))
        ln = lines[i]
        if op == 0:
            j = rng.randint(0, len(ln))
            lines[i] = ln[:j] + rng.choice(_CHARS) + ln[j:]
        elif op == 1 and ln:
            j = rng.randrange(len(ln))
            lines[i] = ln[:j] + ln[j + 1:]
        elif op == 2 and ln:
            j = rng.randrange(len(ln))
            lines[i] = ln[:j] + rng.choice(_CHARS) + ln[j + 1:]
        elif op == 3:
            lines.insert(i, rng.choice(_LINES))
        elif op == 4:
            lines.insert(i, ln)
        elif op == 5 and len(lines) > 1:
            del lines[i]
        elif op == 6 and len(lines) > 1:
            j = rng.randrange(len(lines))
            lines[i], lines[j] = lines[j], lines[i]
        elif op == 7:
            lines[i] = (" " * rng.randint(1, 2) + ln) if rng.random() < 0.6 else ln.lstrip(" ")[rng.randint(0, 1):]
        elif op == 8:
            lines[i] = ln + rng.choice(_CHARS) + rng.choice(["", "x", "1", " #c", ": x"])
        else:
            lines[i] = ln.replace("70", rng.choice(_VALUES)) if "70" in ln else ln.replace("value", rng.choice(["value", "valu", "Value", "value "]))
    return "\n".join(lines)


def _small_base():
    """The entry, the one before it and the one after, and the file's first lines: the corpus the mutations of the entry start from."""
    lines = fea.ASSUMPTIONS.read_text().split("\n")
    heads = [n for n, ln in enumerate(lines) if ln and not ln.startswith((" ", "#"))]
    k = lines.index(KEY)
    a = heads[heads.index(k) - 1]
    b = heads[heads.index(k) + 2]
    return "\n".join(lines[:2] + lines[a:b]) + "\n"


def _fuzz(tmp_path, monkeypatch, base, count, seed):
    rng = random.Random(seed)
    f = tmp_path / "assumptions.yaml"
    monkeypatch.setattr(fea, "ASSUMPTIONS", f)
    mismatches, read, refused = [], 0, 0
    for _ in range(count):
        text = _mutate(rng, base)
        f.write_bytes(text.encode("utf-8"))
        try:
            got = fea.hull_elements_along()
        except ValueError:
            refused += 1
            continue
        read += 1
        want = _pyyaml(f)
        if want != got or isinstance(want, bool):
            mismatches.append((got, repr(want)[:80], text))
    return mismatches, read, refused


def test_r18_m10_fuzz_of_the_entry_wherever_the_reader_gives_a_number_pyyaml_gives_it_too(tmp_path, monkeypatch):
    """The claim of the reader's docstring, held by a test and not by a list of layouts (rounds 15, 16 and 17 each closed the layouts a review found, and
    round 18's two reviewers each found a fresh one by this very method): 2,000 seeded mutations of the entry and its neighbours (a character, a line, an
    indent, a value text, a tab, a form feed, a sibling's `a: b`, a deeper line, a quote, a flow collection, a list, a document marker); for each, if the reader
    returns a number, `yaml.safe_load` of the same text gives that number. The converse is not asked (the grammar is closed, YAML's is not)."""
    mismatches, read, refused = _fuzz(tmp_path, monkeypatch, _small_base(), 2000, 18)
    assert not mismatches, f"{len(mismatches)} mismatches, the first three: {mismatches[:3]}"
    assert read >= 150 and refused >= 150, (read, refused)              # the fuzz reaches both outcomes: it is not an always-refuse reader's vacuous pass


def test_r18_m10_fuzz_of_the_whole_file_wherever_the_reader_gives_a_number_pyyaml_gives_it_too(tmp_path, monkeypatch):
    """The same over the shipped file, 527 lines: a mutation that lands in another entry (a sibling's text, a list under another key, a tab in a comment) makes
    PyYAML refuse the file the pipeline reads, so the reader must refuse it too, not only the entry's own lines."""
    mismatches, read, refused = _fuzz(tmp_path, monkeypatch, fea.ASSUMPTIONS.read_text(), 400, 1818)
    assert not mismatches, f"{len(mismatches)} mismatches, the first three: {mismatches[:3]}"
    assert read >= 20 and refused >= 20, (read, refused)


def test_r18_m10_the_fuzz_is_seeded_so_a_failure_reproduces(tmp_path, monkeypatch):
    a = [_mutate(random.Random(5), _small_base()) for _ in range(3)]
    assert a == [_mutate(random.Random(5), _small_base()) for _ in range(3)] and len(set(a)) == 1 and a[0] != _small_base()


# ---- M-14: a count is an integer --------------------------------------------------------------------------------------------------------------------------

_COUNT_FUNCS = [("wilson", lambda k, n: I.wilson(k, n)), ("agresti_coull", lambda k, n: I.agresti_coull(k, n)), ("interval", lambda k, n: I.interval(k, n)),
                ("interval_region", lambda k, n: I.interval_region(k, n)), ("decided_region", lambda k, n: I.decided_region(k, n)),
                ("verdict", lambda k, n: I.verdict(k, n)), ("newcombe_diff first", lambda k, n: I.newcombe_diff(k, n, 1, 4)),
                ("newcombe_diff second", lambda k, n: I.newcombe_diff(1, 4, k, n))]


@pytest.mark.parametrize("name, f", _COUNT_FUNCS, ids=[n for n, _ in _COUNT_FUNCS])
@pytest.mark.parametrize("k, n, arg", [(1.5, 3, "k"), (True, 3, "k"), (False, 3, "k"), (1, 3.0, "n"), (3.0, 3, "k"), (1, True, "n"), (np.float64(1.0), 3, "k"),
                                       (1, np.float64(3.0), "n"), (np.bool_(True), 3, "k"), (1, np.bool_(True), "n"), (np.float32(1), 3, "k"), ("1", 3, "k"),
                                       (None, 3, "k"), (1, "3", "n"), (1, None, "n")])
def test_r18_m14_a_count_that_is_not_an_integer_is_refused_by_name(name, f, k, n, arg):
    """`wilson(1.5, 3)` gave (0.1253, 0.8747) and `wilson(True, 3)` gave (0.0615, 0.7923): an interval as if 1.5 members, or one, had failed. A float is refused
    even when it is whole (3.0): a mean of flags or `p * n` is not a sum, and no caller holds anything but an integer."""
    if name.startswith("newcombe_diff second"):
        arg += "2"
    elif name.startswith("newcombe_diff"):
        arg += "1"
    with pytest.raises(ValueError, match=rf"{arg} must be an integer count"):
        f(k, n)


@pytest.mark.parametrize("name, f", _COUNT_FUNCS, ids=[n for n, _ in _COUNT_FUNCS])
@pytest.mark.parametrize("k, n", [(np.int64(1), np.int64(3)), (np.int32(1), 3), (1, np.uint8(3)), (np.intp(0), np.intp(73)), (np.int64(3), np.int64(3))])
def test_r18_m14_a_numpy_integer_count_still_passes_and_gives_the_python_integers_answer(name, f, k, n):
    """What the demo, the what-if and Stage 1 hold: `int(f.sum())` is an int, but `len` and a numpy sum are not always Python ints; both give one answer."""
    got, want = f(k, n), f(int(k), int(n))
    assert got == want and (not isinstance(got, dict) or got["k_fail"] == int(k))


def test_r18_m14_the_ranges_are_checked_after_the_type_and_keep_their_message():
    for k, n in ((5, 3), (-1, 3), (0, 0), (1, -2)):
        with pytest.raises(ValueError, match="need 0 <= k <= n and n >= 1"):
            I.wilson(k, n)
    with pytest.raises(ValueError, match="need 0 < conf < 1"):
        I.wilson(1, 3, 1.0)
    assert I.wilson(0, 1) == (0.0, I.wilson(0, 1)[1]) and 0 < I.wilson(0, 1)[1] < 1


@pytest.mark.parametrize("n", [3.0, 2.5, True, np.float64(3), np.bool_(True), "3", None])
def test_r18_m14_rule_of_three_refuses_a_count_that_is_not_an_integer(n):
    with pytest.raises(ValueError, match="n must be an integer count"):
        I.rule_of_three(n)
    assert I.rule_of_three(np.int64(60)) == I.rule_of_three(60) == 0.05


@pytest.mark.parametrize("n", [40.0, True, np.float64(40)])
def test_r18_m14_coverage_refuses_a_count_that_is_not_an_integer_too(n):
    with pytest.raises(ValueError, match="n must be an integer count"):
        I.coverage(n, np.array([0.3]))
    assert math.isclose(float(I.coverage(np.int64(10), np.array([0.3]))[0]), float(I.coverage(10, np.array([0.3]))[0]))


def test_r18_m14_the_message_says_what_was_passed():
    with pytest.raises(ValueError, match=r"got 1\.5 \(float\)"):
        I.wilson(1.5, 3)
    with pytest.raises(ValueError, match=r"got True \(bool\)"):
        I.wilson(True, 3)
    with pytest.raises(ValueError, match=r"got np\.float64\(3\.0\) \(float64\)"):
        I.wilson(1, np.float64(3.0))
