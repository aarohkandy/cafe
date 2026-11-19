"""Round 21, batch D (M-5 and the reader, the seed and the wrapper of M-9).

M-5: a CFD grid index that is not trusted (NaN, inf, a missing key, or above `vv.GCI_TRUSTED` = 0.3) gives `mission.drag_sigma` exactly the spread of an
ESTIMATE, and a worse index never gives a narrower spread; before, an index of 1.5 gave 1.503, the mean-preserving lognormal of that spread has a median
drag scale of 0.32, and most members were BELOW nominal drag where the grid warning said "verdicts lean MARGINAL". A missing `gci` key is inf, not 0.0 (a
converged grid), in `vehicle.build` and `vv.gci_value`.
M-9: `config.load_json` is the one reader (an integer that does not fit a float and nesting too deep are `ValueError`, NaN stays readable), `finite_real` the
one finite-real test (`_seed._num` and the seed's `gci` check, `vv.gci_value` use it), and `damaged_run_files` takes an `ArithmeticError` for damage.
Each test fails on the tree at 7599881 and passes with the fix."""
import json
import math
import pathlib
import subprocess
import sys
import types

import numpy as np
import pytest

from cafe import _seed, geom, mission, vehicle
from cafe.pm import config, jsonio, vv
from tests.test_round19_d import external, put
from tests.test_round20_d import not_seeded, work  # noqa: F401  (work is a fixture)

NAN, INF = float("nan"), float("inf")
ROOT = pathlib.Path(__file__).parent.parent
REAL = pathlib.Path(__file__).parent / "fixtures" / "cfd_real"
H, EST = mission.SIG["drag_cfd"], mission.SIG["drag_est"]


def fake(resistance=None, drag=None, sources=None, **limits):
    return types.SimpleNamespace(resistance=resistance, drag={i: (0, 0, 0, g) for i, g in enumerate(drag or [])}, sources=sources or {}, limits=limits)


BAD = [NAN, INF, -INF, None, "0.1", True, False, [0.1], {}, 10 ** 400, -(10 ** 400)]
BAD_IDS = ["nan", "inf", "-inf", "none", "text", "true", "false", "list", "dict", "10**400", "-10**400"]


# ---------------------------------------------------------------------------------------------------------- M-5

def test_m5_the_trust_threshold_is_one_constant_and_one_reader():
    assert vv.GCI_TRUSTED == 0.3 and type(vv.GCI_TRUSTED) is float
    assert vv.gci_trusted(0.3) and not vv.gci_trusted(np.nextafter(0.3, 1.0)) and vv.gci_trusted(np.nextafter(0.3, 0.0))  # the bound itself is trusted
    for good in (0, 0.0, 0.05, 0.25, np.float64(0.3)):
        assert vv.gci_trusted(good)
    assert vv.gci_trusted(-0.0) and not vv.gci_trusted(-1e-12) and not vv.gci_trusted(-0.1)             # an index is a magnitude
    for bad in (0.31, 1.0, 1.5, 3.0, 1e200, *BAD):
        assert not vv.gci_trusted(bad)
    assert type(vv.gci_trusted(0.1)) is bool and type(vv.gci_trusted(None)) is bool


def test_m5_a_missing_key_is_an_index_that_cannot_be_trusted_not_a_converged_grid():
    """`r.get("gci")` of a result without the key is None: inf. The Hangar's readers had `r.get("gci", 0.0)`: a perfect grid."""
    assert vv.gci_value({}.get("gci")) == INF and not vv.gci_trusted({}.get("gci"))
    assert vv.worst_gci(r.get("gci") for r in ({"gci": 0.01}, {})) == INF and vv.worst_gci(r.get("gci") for r in ({"gci": 0.01}, {"gci": 0.2})) == 0.2


def test_m5_an_oversized_integer_is_no_index(monkeypatch):
    assert vv.gci_value(10 ** 400) == INF and vv.gci_value(-(10 ** 400)) == INF
    assert vv.gci_value(10 ** 308) == 1e308                                      # one that fits a float is an index
    assert vv.worst_gci([0.1, 10 ** 400]) == INF


@pytest.mark.parametrize("g", [1.5, 3.0, 0.4, 1.0, 1e6, 1e200, 10 ** 400, INF, NAN, None], ids=lambda g: str(g)[:8])
def test_m5_an_index_that_is_not_trusted_gives_an_estimates_spread_in_any_direction_and_for_the_lift_and_the_resistance(g):
    """Before: 1.5 gave 1.503 (and 3.0 gave 3.0), the mean-preserving lognormal of which puts most members below nominal drag; 1e200 overflowed `sig ** 2`."""
    for kw in (dict(drag=[g], sources=dict(drag="cfd")), dict(drag=[0.05, g, 0.02], sources=dict(drag="cfd")),
               dict(drag=[0.05, 0.02], lift_gci=g, sources=dict(drag="cfd")), dict(resistance=1, resistance_gci=g)):
        assert mission.drag_sigma(fake(**kw)) == EST


def test_m5_the_median_member_is_never_far_below_nominal_drag_whatever_the_index():
    """The lognormal of `Drone.__init__` is `exp(N(-s**2/2, s))`: its median is `exp(-s**2/2)`. 1.5 gave 0.326 (77 % of members below nominal), 3.0 gave 0.011.
    Now the widest spread is an estimate's, and its median 0.956: the one number that does not depend on which of the readers saw the index."""
    for g in (*np.linspace(0, 5, 101), 10, 1e6, 1e200, INF, NAN):
        s = mission.drag_sigma(fake(drag=[g], sources=dict(drag="cfd")))
        assert s <= EST and math.exp(-s ** 2 / 2) >= math.exp(-EST ** 2 / 2) > 0.95


def test_m5_the_spread_never_narrows_as_the_index_worsens_and_the_cap_is_the_trust_threshold():
    """`min(hypot(0.10, g), 0.30)`: at `GCI_TRUSTED` (0.3) hypot is 0.316, above the estimate's, so there was no jump to 0.30 to fall into (a trusted 0.3
    gave a wider spread than 0.31, which is untrusted). The cap and the threshold agree for the constants as they are: if either moves, this says so."""
    gs = [*np.linspace(0, 1, 2001), 1.5, 3.0, INF]
    s = [mission.drag_sigma(fake(drag=[g], sources=dict(drag="cfd"))) for g in gs]
    assert all(a <= b for a, b in zip(s, s[1:], strict=False)) and s[0] == pytest.approx(H) and s[-1] == EST
    assert math.hypot(H, vv.GCI_TRUSTED) > EST > math.hypot(H, 0.28) and math.sqrt(EST ** 2 - H ** 2) < vv.GCI_TRUSTED
    for g, v in zip(gs, s, strict=True):
        assert v == (pytest.approx(min(math.hypot(H, g), EST), abs=1e-15) if vv.gci_trusted(g) else EST)


def test_m5_a_negative_index_is_no_wider_than_an_estimate_whatever_its_sign():
    """`hypot` takes the magnitude, so a hand-edited -5 is a spread of 5 before the cap, as +5 is (a small negative one, -0.2, is not pinned: no real
    index is negative, and `gci_trusted` refuses it)."""
    for g in (-5.0, -1.5, -0.4):
        assert mission.drag_sigma(fake(drag=[g], sources=dict(drag="cfd"))) == EST


def test_m5_trusted_indices_combine_as_before():
    assert mission.drag_sigma(fake(drag=[0.05, 0.2], sources=dict(drag="cfd"))) == pytest.approx(math.hypot(H, 0.2))
    assert mission.drag_sigma(fake(drag=[0.05, 0.2], lift_gci=0.25, sources=dict(drag="cfd"))) == pytest.approx(math.hypot(H, 0.25))
    assert mission.drag_sigma(fake(drag=[0.0], sources=dict(drag="cfd"))) == pytest.approx(H)
    assert mission.drag_sigma(fake(resistance=1, resistance_gci=0.0)) == pytest.approx(H)
    assert mission.drag_sigma(fake(drag=[], sources=dict(drag="cfd"))) == pytest.approx(H)  # no direction at all: the 10 % of the CFD, as before


def test_m5_a_missing_lift_study_is_not_an_index_but_a_missing_resistance_index_is():
    cfd_ = dict(sources=dict(drag="cfd"))
    assert mission.drag_sigma(fake(drag=[0.05], **cfd_)) == pytest.approx(math.hypot(H, 0.05)) and "lift_gci" not in fake(drag=[0.05], **cfd_).limits
    assert mission.drag_sigma(fake(drag=[0.05], lift_gci=None, **cfd_)) == EST  # a lift study whose index is None is an index that cannot be trusted
    assert mission.drag_sigma(fake(resistance=1)) == EST


def sample(name):
    s = geom.SAMPLES[name]
    return s["kind"], s["make"](), s["spec"]


@pytest.mark.parametrize("name, file, key, gcis", [("quad", "quad.external.json", "dirs", 0.0670), ("torpedo", "torpedo.external.json", "dirs", 0.1254),
                                                   ("wigley", "wigley.surface.json", "speeds", 0.0319)])
def test_m5_the_real_results_of_the_repo_give_the_spread_they_gave(name, file, key, gcis):
    """The six real results the seed's cases take (GCIs 0.001 to 0.125): no index above 0.3, none missing, so `q23` has the vehicle spreads of `q22`."""
    res = json.loads((REAL / file).read_text())
    kind, mesh, spec = sample(name)
    v = vehicle.build(kind, mesh, spec, {("fs" if key == "speeds" else "cfd"): res})
    worst = max(r["gci"] for r in res[key].values())
    assert worst == pytest.approx(gcis, abs=5e-5) and worst < vv.GCI_TRUSTED
    assert mission.drag_sigma(v) == pytest.approx(math.hypot(H, worst), abs=1e-12) and mission.drag_sigma(v) < EST


@pytest.mark.parametrize("name, file, key", [("quad", "quad.external.json", "dirs"), ("torpedo", "torpedo.external.json", "dirs")])
@pytest.mark.parametrize("at", [0, 3, 5])
def test_m5_a_direction_whose_gci_key_is_missing_is_inf_in_the_drag_table_and_the_spread_is_an_estimates(name, file, key, at):
    """Before: `r.get("gci", 0.0)`, a converged grid (the spread stayed that of the other five directions)."""
    res = json.loads((REAL / file).read_text())
    del res[key][list(res[key])[at]]["gci"]
    kind, mesh, spec = sample(name)
    v = vehicle.build(kind, mesh, spec, {"cfd": res})
    g = [c[3] for c in v.drag.values()]
    assert sum(x == INF for x in g) == 1 and mission.drag_sigma(v) == EST


@pytest.mark.parametrize("at", [0, 1, 2])
def test_m5_a_speed_whose_gci_key_is_missing_makes_the_resistance_index_inf(at):
    res = json.loads((REAL / "wigley.surface.json").read_text())
    del res["speeds"][list(res["speeds"])[at]]["gci"]
    kind, mesh, spec = sample("wigley")
    v = vehicle.build(kind, mesh, spec, {"fs": res})
    assert v.limits["resistance_gci"] == INF and mission.drag_sigma(v) == EST


def test_m5_a_real_direction_with_a_wide_index_gives_an_estimates_spread():
    """The real torpedo with one direction's GCI at 1.5 (SUBOFF's study had ~150 %): the whole vehicle's spread is an estimate's, not 1.503."""
    res = json.loads((REAL / "torpedo.external.json").read_text())
    res["dirs"]["+x"]["gci"] = 1.5
    kind, mesh, spec = sample("torpedo")
    v = vehicle.build(kind, mesh, spec, {"cfd": res})
    assert max(c[3] for c in v.drag.values()) == 1.5 and mission.drag_sigma(v) == EST


# ---------------------------------------------------------------------------------------------------------- M-9: the reader

def test_m9_one_reader_and_one_finite_test_under_the_names_the_other_batches_use():
    assert config.load_json is jsonio.load_json and config.finite_real is jsonio.finite_real and vv.finite_real is jsonio.finite_real


def test_m9_the_app_side_modules_import_without_yaml_or_jsonschema():
    """The live app image has no pyyaml (`atomic.py`'s docstring): `vehicle`, `mission` and `_seed` import `vv` and `jsonio`, which must not need `config`."""
    code = ("import sys; sys.modules['yaml'] = None; sys.modules['jsonschema'] = None; "
            "import cafe.pm.jsonio, cafe.pm.vv, cafe.vehicle, cafe.mission, cafe._seed; assert 'cafe.pm.config' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


@pytest.mark.parametrize("text", ["1" + "0" * 400, "-1" + "0" * 400, "[1, 2, " + "9" * 400 + "]", '{"a": {"b": [' + "9" * 309 + "]}}", str(2 ** 1024)],
                         ids=["10**400", "-10**400", "in a list", "nested", "2**1024"])
def test_m9_an_integer_too_large_for_a_float_is_a_value_error_naming_its_length(text):
    with pytest.raises(ValueError, match=r"an integer of \d+ characters is too large"):
        config.load_json(text)


def test_m9_a_literal_of_thousands_of_digits_is_a_value_error_with_the_interpreters_digit_limit_on_or_off():
    text = "[" + "7" * 5000 + "]"
    with pytest.raises(ValueError):                                                                    # the limit (4300 digits) is the interpreter's ValueError
        config.load_json(text)
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        with pytest.raises(ValueError, match="an integer of 5000 characters is too large"):
            config.load_json(text)
    finally:
        sys.set_int_max_str_digits(old)


def test_m9_the_premise_the_plain_reader_gives_an_int_that_overflows_every_later_float():
    n = json.loads("1" + "0" * 400)
    assert type(n) is int
    with pytest.raises(OverflowError):
        math.isfinite(n)


@pytest.mark.parametrize("n", [0, 1, -1, 2 ** 53, 2 ** 53 + 1, 10 ** 308, int(sys.float_info.max), -int(sys.float_info.max)])
def test_m9_an_integer_that_fits_a_float_is_read_as_an_int_unchanged(n):
    assert config.load_json(str(n)) == n and type(config.load_json(str(n))) is int


def test_m9_the_boundary_is_the_integer_that_float_refuses():
    top = int(sys.float_info.max)
    assert config.load_json(str(top + 2 ** 970 - 1)) == top + 2 ** 970 - 1  # rounds down to the largest float
    for n in (top + 2 ** 970, top + 2 ** 971):  # half way to 2**1024 rounds to it (even): float() raises OverflowError
        with pytest.raises(OverflowError):
            float(n)
        with pytest.raises(ValueError, match="too large"):
            config.load_json(str(n))


def test_m9_everything_else_is_read_as_json_loads_reads_it():
    text = '{"a": [1, 2.5, "x", null, true, {"b": -3e-5}], "c": 1e999, "d": "9' + "9" * 400 + '"}'
    assert config.load_json(text) == json.loads(text) and config.load_json(text.encode()) == json.loads(text)


def test_m9_nan_and_infinity_stay_readable_because_the_project_writes_a_nan_gci_on_purpose():
    d = config.load_json('{"gci": NaN, "x": Infinity, "y": -Infinity}')
    assert math.isnan(d["gci"]) and d["x"] == INF and d["y"] == -INF
    assert vv.gci_value(d["gci"]) == INF and not config.finite_real(d["x"])


@pytest.mark.parametrize("text", ["[" * 100000 + "]" * 100000, '{"a":' * 100000 + "1" + "}" * 100000], ids=["lists", "objects"])
def test_m9_nesting_too_deep_is_a_value_error_not_a_recursion_error(text):
    with pytest.raises(RecursionError):
        json.loads(text)  # the premise
    with pytest.raises(ValueError, match="nested too deeply"):
        config.load_json(text)


def test_m9_a_path_is_read_as_a_file_and_a_missing_one_is_an_os_error(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"a": 1}')
    assert config.load_json(p) == {"a": 1}
    p.write_text("1" + "0" * 400)
    with pytest.raises(ValueError, match="too large"):
        config.load_json(p)
    p.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError):  # UnicodeDecodeError is a ValueError
        config.load_json(p)
    with pytest.raises(OSError):
        config.load_json(tmp_path / "missing.json")
    with pytest.raises(json.JSONDecodeError):
        config.load_json("{")


def test_m9_json_loads_arguments_pass_through_but_parse_int_is_the_readers():
    assert config.load_json('{"a": 1, "b": 2}', object_pairs_hook=list) == [("a", 1), ("b", 2)]
    with pytest.raises(TypeError):
        config.load_json("1", parse_int=int)


@pytest.mark.parametrize("bad", BAD, ids=BAD_IDS)
def test_m9_finite_real_refuses_what_is_no_finite_number(bad):
    assert config.finite_real(bad) is False


@pytest.mark.parametrize("good", [0, 0.0, -1, 3, 0.05, 1e308, 10 ** 308, np.float64(0.2), -1e-300])
def test_m9_finite_real_accepts_a_finite_number(good):
    assert config.finite_real(good) is True


def test_m9_json_object_says_damaged_for_an_oversized_integer_and_for_nesting(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text('{"batch": ' + "1" * 400 + "}")
    with pytest.raises(config.ConfigError, match=r"plan.json: not a JSON object \(an integer of 400 characters is too large"):
        config.json_object(p)
    p.write_text("[" * 100000)
    with pytest.raises(config.ConfigError, match="nested too deeply"):
        config.json_object(p)
    p.write_text('{"batch": 7}')
    assert config.json_object(p) == {"batch": 7}


# ---------------------------------------------------------------------------------------------------------- M-9: the wrapper

@pytest.mark.parametrize("exc", [OverflowError("int too large to convert to float"), ZeroDivisionError("division by zero"), FloatingPointError("overflow"),
                                 ArithmeticError("x")], ids=lambda e: type(e).__name__)
def test_m9_an_arithmetic_failure_on_a_stored_number_is_the_damaged_message_not_a_traceback(tmp_path, exc):
    """`report --run` with `batch: 1e300` (a legal float) in a product that overflows, or a zero divisor: the same message as a missing key."""
    with pytest.raises(config.ConfigError, match=rf"damaged or incomplete \({type(exc).__name__}: .*run it again \(--fresh\)"):
        with config.damaged_run_files(tmp_path):
            raise exc


def test_m9_what_the_wrapper_let_through_before_it_still_lets_through():
    with pytest.raises(config.ConfigError, match="^boom$"):
        with config.damaged_run_files(pathlib.Path("run")):
            raise config.ConfigError("boom")
    with pytest.raises(RuntimeError):
        with config.damaged_run_files(pathlib.Path("run")):
            raise RuntimeError("a bug")
    with pytest.raises(config.ConfigError, match="KeyError"):
        with config.damaged_run_files(pathlib.Path("run")):
            {}["a"]


# ---------------------------------------------------------------------------------------------------------- M-9: the seed

@pytest.mark.parametrize("bad", BAD, ids=BAD_IDS)
def test_m9_the_seeds_number_test_is_the_one_finite_real_test(bad):
    assert _seed._num(bad) is False
    assert _seed._num is config.finite_real and not _seed._vec([1.0, 2.0, bad])


def test_m9_the_seeds_gci_check_takes_every_float_but_not_an_integer_that_is_no_number():
    k = ("external", "air", 10.0)
    for g in (0, 3, 0.05, NAN, INF, -INF, 10 ** 308):
        r = external()
        r["dirs"]["+x"]["gci"] = g
        assert _seed._checked("external", k, r) is r
    for g in (10 ** 400, -(10 ** 400), None, "0.1", True, False, [0.1], {}):
        r = external()
        r["dirs"]["+x"]["gci"] = g
        with pytest.raises(ValueError, match="direction \\+x has no number in `gci`"):
            _seed._checked("external", k, r)


@pytest.mark.parametrize("field", ["rho", "nu", "L", "gci", "force"])
def test_m9_a_400_digit_integer_in_a_result_is_not_seeded_and_nothing_is_written(work, capsys, field):  # noqa: F811
    """Before: `_num(10**400)` raised OverflowError (out of `main`: a traceback); a `gci` of it passed the type check and was cached, and every later
    `vehicle.build` of it crashed until the entry was deleted by hand. Now `NOT seeded <file> - <reason>`, exit 1, no cache entry."""
    text = json.dumps(external())
    big = "1" + "0" * 400
    text = {"rho": text.replace('"rho": 1.2', f'"rho": {big}'), "nu": text.replace('"nu": 1.5e-05', f'"nu": {big}'),
            "L": text.replace('"L": 1.0', f'"L": {big}'),
            "gci": text.replace('"gci": 0.01', f'"gci": {big}', 1), "force": text.replace('"force": [-1.0', f'"force": [{big}', 1)}[field]
    assert big in text
    put(work, "q1", "quad.external.json", external())
    f = put(work, "t1", "torpedo.external.json", text)
    out = not_seeded(work, capsys, f)
    assert "an integer of 401 characters is too large for a number" in out and "seeded quad" not in out
