"""Round 23, batch C (M-6, M-7): the one YAML reader and the stored vector refuse what they cannot use with the error the caller expects.

M-6: an integer of 4,301 or more decimal digits (PyYAML's `int()` raises the interpreter's own ValueError), a hex integer whose decimal form is that long
(`_finite` used to call `str` on it), and a list or a mapping used as a mapping key (`seen.add` raised TypeError) are a ConfigError of the reader, never a
bare ValueError or TypeError; `hangar --platform` exits 2 with `error:`; `ledger.values_sha256` gives "".
M-7: `vehicle._vec3` of a result with no `force`, `moment` or `viscous` key is the named ValueError, never a KeyError."""
import math
import re
import sys

import numpy as np
import pytest

from cafe import cfd, vehicle
from cafe.pm import __main__ as cli, config, ledger
from tests.test_round22_d import FIELDS, incidence, quad_external, sample



def _read(tmp_path, text):
    p = tmp_path / "x.yaml"
    p.write_text(text)
    return p


BIG_LITERALS = {
    "dec 399": "1" * 399, "dec 400": "1" * 400, "dec 401": "1" + "0" * 400, "dec 4300": "1" * 4300, "dec 4301": "1" * 4301, "dec 5000": "1" * 5000,
    "neg dec 400": "-" + "1" * 400, "neg dec 5000": "-" + "1" * 5000, "underscored 5000": "1_" + "1" * 4999, "plus 5000": "+" + "1" * 5000,
    "hex 3999": "0x" + "f" * 3999, "hex 4000": "0x" + "f" * 4000, "neg hex 4000": "-0x" + "f" * 4000, "hex 200000": "0x" + "f" * 200000,
    "hex 300": "0x" + "f" * 300, "hex 256": "0x1" + "0" * 255,
}


@pytest.mark.parametrize("name", list(BIG_LITERALS))
def test_m6_an_integer_too_big_for_a_float_is_a_config_error_at_any_length(tmp_path, name):
    """Over the digit counts 399 to 5,000, both signs, underscores and hex: never a ValueError or TypeError that is not a ConfigError; a literal that fits a
    float (hex 256 digits is 2**1020: it fits; 399 decimal digits: it does not) is read as it was."""
    lit = BIG_LITERALS[name]
    p = _read(tmp_path, f"a: {lit}\nb:\n  - c: 1\n")
    fits = name in ("hex 256",)
    if fits:
        assert config.read_yaml(p) == {"a": int(lit.replace("_", ""), 16), "b": [{"c": 1}]}
        return
    with pytest.raises(config.ConfigError) as e:
        config.read_yaml(p)
    assert type(e.value) is config.ConfigError and str(e.value).startswith(f"{p}: ")
    assert lit not in str(e.value) and len(str(e.value)) < 600                                    # the literal is never printed
    assert ledger.values_sha256(p) == ""


@pytest.mark.parametrize("digits", [399, 400, 401, 1000, 4299, 4300])
def test_m6_the_message_counts_the_digits_exactly_for_both_signs_and_does_not_count_the_sign(tmp_path, digits):
    """The old message was `len(str(n))`: a negative number's minus sign was counted as a digit."""
    for sign in ("", "-"):
        p = _read(tmp_path, f"a: {sign}{'1' * digits}\n")
        with pytest.raises(config.ConfigError, match=rf"x\.yaml: a: an integer of {digits} digits is not a finite number; "):
            config.read_yaml(p)


@pytest.mark.parametrize("hexdigits", [250, 257, 3999, 4000, 4001, 9000])
def test_m6_a_hex_integer_is_counted_in_decimal_digits_without_str(tmp_path, hexdigits):
    n = int("1" + "0" * (hexdigits - 1), 16)
    p = _read(tmp_path, f"a: 0x1{'0' * (hexdigits - 1)}\n")
    if n.bit_length() <= 1023:
        assert config.read_yaml(p) == {"a": n}
        return
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)                                                                # the oracle: the exact count by str, with the limit off
    try:
        digits = len(str(n))
    finally:
        sys.set_int_max_str_digits(old)
    with pytest.raises(config.ConfigError, match=rf"a: an integer of {digits} digits is not a finite number; "):
        config.read_yaml(p)


@pytest.mark.parametrize("key", ["? [1, 2]\n: x", "? {a: 1}\n: x", "? [[1], [2]]\n: x", "? !!set {a}\n: x"])
def test_m6_an_unhashable_mapping_key_is_a_config_error_naming_the_line(tmp_path, key):
    p = _read(tmp_path, f"ok: 1\nm:\n  {key.replace(chr(10), chr(10) + '  ')}\n")
    with pytest.raises(config.ConfigError, match=r"(?s)not valid YAML \(.*unhashable key"):
        config.read_yaml(p)
    assert ledger.values_sha256(p) == ""
    p = _read(tmp_path, key + "\n")                                                              # at the top level too
    with pytest.raises(config.ConfigError, match=r"unhashable key"):
        config.read_yaml(p)


def test_m6_a_repeated_key_and_a_hashable_key_of_any_kind_are_as_before(tmp_path):
    with pytest.raises(config.ConfigError, match=r"line 2: duplicate key 'a'"):
        config.read_yaml(_read(tmp_path, "a: 1\na: 2\n"))
    with pytest.raises(config.ConfigError, match=r"duplicate key 1"):
        config.read_yaml(_read(tmp_path, "1: x\n1: y\n"))
    assert config.read_yaml(_read(tmp_path, "7: x\n2.5: y\ntrue: z\n? null\n: w\n")) == {7: "x", 2.5: "y", True: "z", None: "w"}


@pytest.mark.parametrize("text", ["a: 2023-02-30", "a: !!int 'zz'", "a: !!float 'zz'"])
def test_m6_any_other_value_error_of_the_loader_is_a_config_error_too(tmp_path, text):
    """A calendar-invalid timestamp and a value the explicit tag cannot convert were bare ValueErrors from PyYAML's constructors."""
    p = _read(tmp_path, text + "\n")
    with pytest.raises(config.ConfigError, match=r"x\.yaml: not valid YAML \("):
        config.read_yaml(p)
    assert ledger.values_sha256(p) == ""


@pytest.mark.parametrize("name", ["dec 5000", "neg dec 5000", "hex 4000", "hex 200000", "dec 401"])
def test_m6_hangar_platform_exits_2_with_error_and_prints_nothing_on_stdout(tmp_path, capsys, name):
    p = _read(tmp_path, f"params:\n  x:\n    value: {BIG_LITERALS[name]}\n    source: s\n")
    assert cli.main(["hangar", "--platform", str(p)]) == 2
    out = capsys.readouterr()
    assert out.out == "" and out.err.startswith(f"error: {p}: ") and BIG_LITERALS[name] not in out.err


def test_m6_a_file_that_fits_is_read_as_before_and_the_reader_is_still_the_only_one(tmp_path):
    assert config.read_yaml(_read(tmp_path, "a: 10000000000\nb: 0x10\nc: 1e300\nd: [1, {e: 2}]\n")) == {"a": 10 ** 10, "b": 16, "c": 1e300, "d": [1, {"e": 2}]}
    assert ledger.values_sha256(_read(tmp_path, "k:\n  value: 1\n  why: w\n")) != ""


# ---------------------------------------------------------------------------------------------------------------- M-7: the stored vector
GOOD = [1.0, 2.0, 3.0]


@pytest.mark.parametrize("key", FIELDS)
@pytest.mark.parametrize("r", [{}, {"other": GOOD}, None, [], [GOOD], "text", 7])
def test_m7_a_result_without_the_key_is_the_named_value_error_for_any_container(key, r):
    with pytest.raises(ValueError, match=rf"direction -x: `{key}` is not three finite numbers") as e:
        vehicle._vec3(r, key, "-x")
    assert not isinstance(e.value, KeyError)


@pytest.mark.parametrize("key", FIELDS)
def test_m7_each_of_the_three_keys_missing_in_turn_while_the_others_are_there(key):
    r = {k: list(GOOD) for k in FIELDS}
    assert np.array_equal(vehicle._vec3(r, key, "+x"), GOOD)
    del r[key]
    for other in FIELDS:
        if other != key:
            assert np.array_equal(vehicle._vec3(r, other, "+x"), GOOD)
    with pytest.raises(ValueError, match=rf"direction \+x: `{key}` is not three finite numbers"):
        vehicle._vec3(r, key, "+x")


@pytest.mark.parametrize("bad", [None, math.nan, math.inf, 10 ** 400, True, "abc", [1.0, 2.0], [1.0, 2.0, 3.0, 4.0], {"a": 1}, {}],
                         ids=["null", "nan", "inf", "10**400", "bool", "text", "two", "four", "dict", "empty dict"])
def test_m7_every_other_bad_value_stays_the_same_value_error(bad):
    for key in FIELDS:
        with pytest.raises(ValueError, match=rf"direction \+x: `{key}` is not three finite numbers"):
            vehicle._vec3({key: bad}, key, "+x")


@pytest.mark.parametrize("key", ["force", "moment"])
@pytest.mark.parametrize("lab", ["+x", "+y", "+z", "x+y5", "x+y10", "x+z5", "x+z10"])
def test_m7_hull_lift_with_a_missing_fine_vector_is_a_value_error_never_a_key_error(lab, key):
    inc = incidence()
    del inc["dirs"][lab][key]
    with pytest.raises(ValueError, match=rf"direction {re.escape(lab)}: `{key}` is not three finite numbers") as e:
        vehicle.hull_lift(inc, np.zeros(3), np.zeros((3, 3)))
    assert not isinstance(e.value, KeyError)


@pytest.mark.parametrize("key", ["force_coarse", "moment_coarse"])
def test_m7_hull_lift_with_no_coarse_vector_still_has_no_index_inf(key):
    """The coarse read's `except (KeyError, ValueError)` keeps its meaning: a missing coarse key is no grid index, which is inf."""
    inc = incidence(drop=("x+y10", "x+z10"), how=key)
    assert vehicle.hull_lift(inc, np.zeros(3), np.zeros((3, 3)))[1] == math.inf


@pytest.mark.parametrize("d", list(cfd.DIRS))
@pytest.mark.parametrize("key", FIELDS)
def test_m7_build_with_a_missing_key_in_any_direction_is_a_value_error_naming_it(d, key):
    kind, mesh, spec = sample("quad")
    res = quad_external()
    del res["dirs"][d][key]
    with pytest.raises(ValueError, match=rf"direction {re.escape(d)}: `{key}` is not three finite numbers") as e:
        vehicle.build(kind, mesh, spec, {"cfd": res})
    assert not isinstance(e.value, KeyError)
