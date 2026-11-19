"""Round 21, batch E (the JSON sweep, M-9) and the count message (D-6, M-13): no raw `json.loads(` / `json.load(` is left in `cafe/` outside an allow-list
that says why, the scalar `math.isfinite` calls are the ones listed (each with its reason), every reader of a user-editable or run-written file refuses an
oversized integer, nesting that exhausts the stack and the rest of the hostile documents with its own message or a ValueError (never an OverflowError, a
RecursionError or a traceback), the app's request bodies and the mission YAML refuse a number that does not fit, and `acceptance._damage` quotes the one rule of
a stored count."""
import ast
import copy
import math
import pathlib

import pytest

from cafe import _seed, cfd, hangar, receipts as cafe_receipts, worker
from cafe.pm import acceptance as acc, audit, config, credibility as cr, jsonio, ledger, vv
from cafe.pm.env import hycom, orca, subgrid, tao
from cafe.pm.stage3 import lbm

ROOT = pathlib.Path(__file__).resolve().parents[1]
CAFE = ROOT / "cafe"

# ---------------------------------------------------------------------------------------------------------------------------- the grep tests
# Every call of json.load / json.loads in cafe/ (any alias of the module, `from json import loads`): the ONE reader of a user-editable or run-written file is
# `cafe.pm.jsonio.load_json` (`config.load_json`). What may stay raw, and why. The count is exact, so a site that moves or a new one fails the test.
RAW_JSON = {
    "cafe/pm/jsonio.py": (1, "the reader itself"),
    "cafe/pm/config.py": (1, "the package's own JSON schema (cafe/pm/schemas), shipped with the code: not user data"),
    "cafe/pm/env/orca.py": (1, "the package's own schema of the WRF and UMWM output, shipped with the code"),
    "cafe/pm/env/hycom.py": (1, "the package's own schema of the HYCOM store, shipped with the code"),
    "cafe/pm/report.py": (1, "the report's own list of report.json paths, which it wrote into the HTML it is checking (`data-paths`)"),
    "cafe/hangar.py": (1, "`_write_result`: the round trip of the text the same call has just dumped, to turn a non-finite float into null"),
    "cafe/app.py": (1, "the round trip of the text its own `json.dumps(..., allow_nan=False)` has just made"),
    "cafe/_tepex_api.py": (1, "a stand-alone client script of the deployed API that imports nothing of cafe: the text is an HTTP response, not a file"),
}

# Every use of math.isfinite (a call, or a reference such as `map(math.isfinite, ...)`) in cafe/: none is on a number that comes straight out of JSON. A number
# read from a file enters through `load_json` (an integer that does not fit a float is a ValueError there: `math.isfinite` and `float` of one that fits cannot
# overflow), a request body's through `jsonio.finite_real`, a YAML number through `config._finite`. A new use fails this test until it is listed with its
# reason.
RAW_ISFINITE = {
    "cafe/app.py": (4, "127 and 447: of a `float(...)` made inside a try that catches OverflowError; 327 and 353: FastAPI-typed float query parameters"),
    "cafe/cfd.py": (1, "`_finite_positive`: of `float(v)` of a design number (spec.json is read by `load_json`, so an integer fits; keyed code: not edited)"),
    "cafe/pm/budget.py": (1, "`--gpu-mem-gb`: an argparse float"),
    "cafe/pm/config.py": (1, "`_is_float`: of `float(text)`, a string (never an OverflowError)"),
    "cafe/pm/env/environment.py": (2, "of `float(a[...])` of a store attribute inside a try that catches OverflowError"),
    "cafe/pm/jsonio.py": (1, "`finite_real`, the test itself (OverflowError caught)"),
    "cafe/pm/ledger.py": (1, "`clean`: of a value that `isinstance(x, float)` says is a float"),
    "cafe/pm/receipts.py": (3, "values computed in this process by `cafe.receipts` (floats); a stored row is read by `load_json` and its arithmetic by a "
                               "wrapper that catches ArithmeticError"),
    "cafe/pm/report.py": (1, "`_f`: of a value that `isinstance(x, float)` says is a float"),
    "cafe/pm/stage3/fluidx3d.py": (1, "`case_dict`: the solver's own float parameters"),
    "cafe/pm/stage3/freesurface.py": (3, "`float(...)` of a stored number (read by `load_json`, an integer fits) and a float the check made"),
    "cafe/pm/stage3/lbm.py": (1, "`positive_float`: of `float(text)` of a command-line string"),
    "cafe/pm/stats/intervals.py": (2, "of the result of the arithmetic (a float), which is the check batch F added"),
    "cafe/pm/stats/sampling.py": (3, "`_check_range`, after `_num` (which catches OverflowError) has passed every number of the entry; floats"),
    "cafe/pm/stats/sequential.py": (1, "of a float ratio"),
    "cafe/pm/vv.py": (6, "of floats the grid-convergence arithmetic made, and of the float arguments of `gci_two_grid`"),
    "cafe/pm/whatif.py": (2, "of floats made by `float()` of a command-line number (`mod` is built by `__main__._whatif` from `--shift`, `--move`, `--duty`)"),
}


def _modules():
    for p in sorted(CAFE.rglob("*.py")):
        yield p.relative_to(ROOT).as_posix(), ast.parse(p.read_text())


def raw_json_calls():
    found: dict[str, int] = {}
    for rel, tree in _modules():
        aliases, bare = set(), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                aliases |= {a.asname or a.name for a in n.names if a.name == "json"}
            elif isinstance(n, ast.ImportFrom) and n.module == "json":
                bare |= {a.asname or a.name for a in n.names if a.name in ("load", "loads")}
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr in ("load", "loads") and isinstance(f.value, ast.Name) and f.value.id in aliases) or \
               (isinstance(f, ast.Name) and f.id in bare):
                found[rel] = found.get(rel, 0) + 1
    return found


def isfinite_uses():
    found: dict[str, int] = {}
    for rel, tree in _modules():
        for n in ast.walk(tree):
            if (isinstance(n, ast.Attribute) and n.attr == "isfinite" and isinstance(n.value, ast.Name) and n.value.id == "math") or \
               (isinstance(n, ast.ImportFrom) and n.module == "math" and any(a.name == "isfinite" for a in n.names)):
                found[rel] = found.get(rel, 0) + 1
    return found


def test_no_raw_json_load_is_left_in_cafe_outside_the_allow_list():
    """Before the sweep: 79 call sites in 31 files read a run's or a user's file with `json.loads`, so an integer of 400 digits (an OverflowError at the first
    `float`, `isfinite` or product of it) or nesting of a few hundred brackets (a RecursionError) was a traceback at each of them, guarded one at a time."""
    found = raw_json_calls()
    assert found == {k: n for k, (n, _) in RAW_JSON.items()}, f"raw json.load(s) calls: {found}; use `jsonio.load_json` or list the call with its reason"
    for rel, (_, why) in RAW_JSON.items():
        assert why and (ROOT / rel).is_file(), rel


def test_every_scalar_math_isfinite_in_cafe_is_one_that_is_listed_with_its_reason():
    found = isfinite_uses()
    assert found == {k: n for k, (n, _) in RAW_ISFINITE.items()}, f"math.isfinite uses: {found}; use `jsonio.finite_real` or list the use with its reason"
    assert all(why for _, why in RAW_ISFINITE.values())


# The modules the live app image loads (it has no pyyaml, which `cafe.pm.config` imports). `cafe/receipts.py` is the pipeline's and imports config for its own
# stored-result functions (always did): it only needs to reach the reader through `jsonio` like the others.
APP_IMAGE = {"app.py", "hangar.py", "mission.py", "vehicle.py", "_seed.py", "worker.py", "emulator.py", "ocean.py", "cfd.py", "_site_data.py", "planner.py"}


def test_the_modules_outside_the_package_that_read_json_import_the_stdlib_only_reader_never_config():
    """`cafe/*.py` outside `cafe/pm` reaches the reader through `cafe.pm.jsonio`, and the modules of the app image never import `cafe.pm.config`."""
    for p in sorted(CAFE.glob("*.py")):
        tree = ast.parse(p.read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "cafe.pm" for a in n.names}
        if any(isinstance(n, ast.Name) and n.id == "load_json" for n in ast.walk(tree)):
            assert "cafe.pm.jsonio" in mods, p.name
        if p.name in APP_IMAGE:
            assert "cafe.pm.config" not in mods and "config" not in names, p.name


def test_the_reader_and_the_finite_test_are_one_function_each():
    assert config.load_json is jsonio.load_json and config.finite_real is jsonio.finite_real
    assert vv.finite_real is jsonio.finite_real and _seed.finite_real is jsonio.finite_real and _seed.load_json is jsonio.load_json
    assert cr.real_ok(10 ** 400) is False and cr.real_ok(1.5) is True


# ---------------------------------------------------------------------------------------------------------------------------- hostile documents
BIG = "1" + "0" * 400                                                  # an integer no float holds
DEEP = "[" * 20000 + "]" * 20000                                       # more nesting than the interpreter's stack allows
NESTED_BIG = '{"a": [{"b": ' + BIG + '}], "c": 1}'
NAN_INF = '{"x": NaN, "gci": [Infinity, -Infinity], "n": NaN}'                  # tokens Python reads and the project writes (a NaN gci)
BOOLS = '{"x": true, "gci": false, "n": true, "value": true}'                    # a bool where a number is read
DOCS = {"big": BIG, "deep": DEEP, "nested_big": NESTED_BIG, "nan_inf": NAN_INF, "bools": BOOLS, "bare_true": "true", "bare_nan": "NaN"}


def write(tmp_path, text, name="x.json"):
    p = tmp_path / name
    p.write_text(text)
    return p


def reader_load_json(tmp_path, text, mp):
    return config.load_json(text)


def reader_load_json_path(tmp_path, text, mp):
    return config.load_json(write(tmp_path, text))


def reader_json_object(tmp_path, text, mp):
    return config.json_object(write(tmp_path, text))


def reader_audit(tmp_path, text, mp):
    return audit._read_json(write(tmp_path, text))


def reader_orca(tmp_path, text, mp):
    return orca.read_json(write(tmp_path, text))


def reader_credibility(tmp_path, text, mp):
    return cr._json(write(tmp_path, text))


def reader_copy_manifest(tmp_path, text, mp):
    return ledger.copy_manifest(write(tmp_path, text), tmp_path / "copy" / "m.json")


def reader_ledger_done(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "stage1").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "stage1", text, "ledger.json")
    return ledger.done(tmp_path, "stage1", "abc")


def reader_ledger_rerecord(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "stage1").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "stage1", text, "ledger.json")
    return ledger.rerecord(tmp_path, "stage1", [], None)


def reader_acceptance_ledger(tmp_path, text, mp):
    (tmp_path / "checkpoints" / "ingest").mkdir(parents=True)
    write(tmp_path / "checkpoints" / "ingest", text, "ledger.json")
    return acc._ledger(tmp_path)


def reader_lbm_stored(tmp_path, text, mp):
    return lbm.read_stored(write(tmp_path, text))


def reader_subgrid(tmp_path, text, mp):
    return subgrid._load(str(write(tmp_path, text)))


def reader_hycom_is_array(tmp_path, text, mp):
    write(tmp_path, text, "zarr.json")
    return hycom._is_array(tmp_path)


def reader_tao(tmp_path, text, mp):
    write(tmp_path, text, "manifest.json")
    return tao.verify(tmp_path)


def reader_worker(tmp_path, text, mp):
    write(tmp_path, text, "status.json")
    return worker.state(tmp_path)


def reader_cafe_receipts(tmp_path, text, mp):
    return cafe_receipts.stored(write(tmp_path, text), "g")


def reader_hangar_load_vehicle(tmp_path, text, mp):
    write(tmp_path, text, "spec.json")
    return hangar.load_vehicle(tmp_path)


def reader_fluidx3d_config(tmp_path, text, mp):
    from cafe.pm.stage3 import freesurface
    mp.setattr(freesurface, "CONFIG_FILE", write(tmp_path, text, "premission.json"))
    return freesurface.fluidx3d_config()


def reader_app_read(tmp_path, text, mp):
    from cafe import app
    return app._read(write(tmp_path, text))


READERS = {fn.__name__[len("reader_"):]: fn for fn in (
    reader_load_json, reader_load_json_path, reader_json_object, reader_audit, reader_orca, reader_credibility, reader_copy_manifest, reader_ledger_done,
    reader_ledger_rerecord, reader_acceptance_ledger, reader_lbm_stored, reader_subgrid, reader_hycom_is_array, reader_tao, reader_worker,
    reader_cafe_receipts, reader_hangar_load_vehicle, reader_fluidx3d_config, reader_app_read)}


def clear_refusal(e: BaseException) -> bool:
    """What a refusal may be: a ValueError (the module's own ConfigError is one), or an error class this program defines on purpose (audit's _Unreadable)."""
    return isinstance(e, ValueError) or type(e).__module__.split(".")[0] == "cafe"


# What a reader does not promise: to take a document of any SHAPE (valid JSON that is no object, or an object lacking its keys). These return what they read
# and leave the shape to the caller (`damaged_run_files` turns a KeyError or TypeError into the damaged-file message); they are fed the oversized integer and
# the nesting, which fail at the reader, and not the documents that are valid JSON of the wrong shape (NaN, a bool, an infinity).
SHAPE_IS_THE_CALLERS = {"ledger_rerecord", "acceptance_ledger", "tao", "hangar_load_vehicle", "subgrid", "fluidx3d_config"}
VALID_JSON = {"nan_inf", "bools", "bare_true", "bare_nan"}
CASES = [(n, d) for n in sorted(READERS) for d in sorted(DOCS) if not (n in SHAPE_IS_THE_CALLERS and d in VALID_JSON)]


@pytest.mark.parametrize("name, doc", CASES)
def test_every_reader_of_a_file_answers_a_hostile_document_clearly_or_not_at_all_and_never_with_a_traceback(tmp_path, monkeypatch, name, doc):
    """The reader returns (its own 'no record' answer: None, {}, a reason, or what it makes of a NaN, an infinity, a bool where a number stands) or raises a
    ValueError or its own error: never an OverflowError, a RecursionError or any other traceback. Before: an integer of 400 digits reached `float`,
    `math.isfinite` or a product, nesting of 20000 brackets reached the stack."""
    try:
        READERS[name](tmp_path, DOCS[doc], monkeypatch)
    except BaseException as e:                                       # noqa: BLE001
        assert not isinstance(e, (OverflowError, RecursionError)) and clear_refusal(e), f"{name} on {doc}: {type(e).__name__}: {str(e)[:200]}"


def test_a_400_digit_integer_and_deep_nesting_are_value_errors_with_a_message_that_does_not_print_them():
    with pytest.raises(ValueError, match=r"an integer of 401 characters is too large for a number") as e:
        config.load_json(BIG)
    assert BIG not in str(e.value)
    with pytest.raises(ValueError, match="nested too deeply"):
        config.load_json(DEEP)
    assert config.load_json("1" + "0" * 308) == 10 ** 308                                          # the largest that fits a float is read
    assert config.load_json("[NaN, Infinity, -Infinity]")[0] != config.load_json("[NaN]")[0]       # NaN stays readable (nan != nan): `cfd.gci` writes one


def test_a_poisoned_cfd_cache_entry_is_recomputed_not_a_traceback_and_the_key_has_not_moved(tmp_path, monkeypatch):
    """`cfd.cached` reads the cache through `load_json`: an entry with a 400-digit `gci` that a hand edit or an older seed left is removed and the case computed
    again. `cached` is one of the functions the cache key leaves out (`NOT_KEYED`), so reading it differently moves no key (both are the digests of 7599881)."""
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "cache")
    stl = tmp_path / "m.stl"
    stl.write_bytes(b"solid x")
    import hashlib
    import json
    key = {"a": 1}
    h = hashlib.sha1(stl.read_bytes() + json.dumps(key).encode() + cfd.recipe().encode()).hexdigest()[:16]
    (tmp_path / "cache").mkdir()
    entry = tmp_path / "cache" / f"{h}.json"
    entry.write_text('{"recipe": "x", "result": {"gci": ' + BIG + "}}")
    log = []
    assert cfd.cached(key, stl, log.append, lambda: {"gci": 0.1}) == {"gci": 0.1}
    assert any("cannot be read (ValueError" in x and "computing again" in x for x in log)
    assert cfd._code_literals() == "9a7181651627013ab5dbd3c6e78f833a798f6aac" and cfd.recipe() == "a091d933b7537473"


# ---------------------------------------------------------------------------------------------------------------------------- numbers
NOT_NUMBERS = [10 ** 400, -(10 ** 400), math.nan, math.inf, -math.inf, True, False, "1", None, [1], {}, 1j]
NOT_IDS = ["big", "-big", "nan", "inf", "-inf", "true", "false", "text", "none", "list", "dict", "complex"]


@pytest.mark.parametrize("x", NOT_NUMBERS, ids=NOT_IDS)
def test_every_finite_real_test_answers_no_to_what_is_not_a_finite_real_and_never_raises(x):
    assert config.finite_real(x) is False and cr.real_ok(x) is False and cr.conf_ok(x) is False and _seed._num(x) is False
    assert vv.gci_value(x) == math.inf and vv.gci_trusted(x) is False
    assert math.isnan(cr._num(x)) and cr._num(None) != cr._num(None)


@pytest.mark.parametrize("x", [0, 1, -1, 0.5, 1e308, 10 ** 308, -(10 ** 308), 2 ** 53 + 1], ids=str)
def test_every_finite_real_test_answers_yes_to_a_number_that_fits_a_float(x):
    assert config.finite_real(x) is True and cr.real_ok(x) is True and _seed._num(x) is True and cr._num(x) == float(x)


# ---------------------------------------------------------------------------------------------------------------------------- the app's request bodies
def app():
    from cafe import app as a
    return a


def refused(fn, *args, **kw):
    """The HTTPException a handler raises for a body it refuses (status 400)."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        fn(*args, **kw)
    assert e.value.status_code == 400
    return e.value.detail


@pytest.mark.parametrize("bad", [10 ** 400, -(10 ** 400)], ids=["big", "-big"])
def test_the_apps_request_bodies_refuse_an_integer_that_does_not_fit_a_float_with_a_400_not_an_overflow(bad, tmp_path, monkeypatch):
    """Before: `math.isfinite(10**400)`, `float(10**400)` and `np.asarray([...], float)` raised OverflowError inside the handlers (a 500)."""
    a = app()
    assert "cog" in refused(a.clean_spec, dict(cog=[bad, 0, 0]), set())
    assert "inertia" in refused(a.clean_spec, dict(inertia=[[bad, 0, 0], [0, 1, 0], [0, 0, 1]]), set())
    assert "must be [lat, lon]" in refused(a._point, [bad, 0], "start")
    shape = next(iter(a.shapes.PARAMS))
    assert "dimensions" in refused(a.create_shape_design, dict(shape=shape, dims={next(iter(a.shapes.PARAMS[shape]["params"])): bad}))
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "status.json").write_text('{"state": "done"}')
    monkeypatch.setattr(a, "DESIGNS", tmp_path)
    drone = lambda i: dict(id=i, design="d", start=[1.0, 2.0, 3.0], legs=[dict(type="hold", minutes=5)])      # noqa: E731
    fleet = dict(drones=[drone("a"), drone("b")])
    assert a.check_fleet(dict(fleet, links=[dict(a="a", b="b", max_m=100.0)]))
    assert "max_m must be a number" in refused(a.check_fleet, dict(fleet, links=[dict(a="a", b="b", max_m=bad)]))
    assert "start must be" in refused(a.create_mission, dict(drones=[dict(drone("a"), start=[bad, 2.0, 3.0])]))
    assert "seconds must be a number" in refused(a.live_step, "sid", dict(seconds=bad))


def test_the_apps_numbers_still_accept_what_they_accepted():
    a = app()
    assert a.clean_spec(dict(cog=[0.1, 0, -0.2]), set())["cog"] == [0.1, 0, -0.2]
    a._point([10.0, 20.0], "start")
    a._point([10, 20, 5], "start")
    refused(a._point, [True, 20.0], "start")                                                          # a bool is no coordinate (it was accepted by isinstance)
    refused(a._point, [91.0, 0.0], "start")


# ---------------------------------------------------------------------------------------------------------------------------- the mission YAML
def test_a_400_digit_yaml_integer_in_a_mission_is_a_config_error_naming_where(tmp_path):
    """YAML reads it as an int, the schema accepts an int as a number, and `config._finite` checked floats only: its first product was an OverflowError."""
    src = (config.ROOT / "missions" / "ci_fixture.yaml").read_text()
    assert "antenna_height_m: 15.0" in src
    import re
    bad = re.sub(r"(antenna_height_m:\s*)[0-9.]+", lambda m: m.group(1) + BIG, src, count=1)
    p = tmp_path / "m.yaml"
    p.write_text(bad)
    with pytest.raises(config.ConfigError, match=r"ship: an integer of 401 digits is not a finite number|an integer of 401 digits is not a finite number"):
        config.load_mission(p)
    with pytest.raises(config.ConfigError, match=r"nan is not a finite number"):
        config._finite(dict(a=[dict(id="v", x=math.nan)]), p)
    config._finite(dict(a=True, b=1, c=1.5, d=10 ** 308), p)                                          # a bool is the schema's business; ints that fit pass


# ---------------------------------------------------------------------------------------------------------------------------- D-6: the count rule
def test_acceptance_damage_quotes_the_one_rule_of_a_stored_count_with_its_bound():
    """Before: 'is not a count (integers, n >= 1, 0 <= k_fail <= n)' for an `n` above 2**53, which satisfies every clause it quoted."""
    rule = cr.counts_rule()
    assert rule == "integers, n >= 1, 0 <= k_fail <= n, n at most 9007199254740992"
    e = dict(k_fail=0, n=2 ** 60, p_fail=0.0, conf=0.9)
    assert acc._damage(e, "now") == [f"k_fail 0 of n {2 ** 60} now is not a count ({rule})"]
    assert acc._damage(dict(e, n=2 ** 53), "now") == [] and acc._damage(dict(e, n=2 ** 53 + 1), "in the reference")
    with pytest.raises(config.ConfigError, match=rf"k_fail 0 of n {2 ** 60} members is not a count \({rule}\)"):
        cr.check_counts(0, 2 ** 60, "summary.links.x")
    for bad in (dict(e, n=0), dict(e, k_fail=-1), dict(e, k_fail=True), dict(e, n=1.0)):
        assert acc._damage(bad, "now")[0].endswith(f"is not a count ({rule})")


def test_a_count_in_the_golden_that_is_too_large_is_one_problem_line_not_a_traceback():
    g = {"a": 1}
    bad = copy.deepcopy(dict(k_fail=0, n=2 ** 60, p_fail=0.0, conf=0.9))
    assert len(acc._damage(bad, "in the reference")) == 1 and g == {"a": 1}
