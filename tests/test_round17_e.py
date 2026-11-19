"""Round 17, batch E (CFD): the cache key covers the numbers and texts written in the code (M-4), a finished result is not lost to the cache and a bad cache
file heals (M-10), hostile arguments are refused before anything is deleted or meshed (M-11), `_seed` reads `$CAFE_WORK` (M-12), and the two round 16
mutants that no named test killed (M-21). No test runs OpenFOAM: `sh` is replaced wherever a case would be meshed."""
import ast
import inspect
import json
import math
import os
import re
import subprocess
import sys

import numpy as np
import pytest
import trimesh

from cafe import cfd
from cafe.pm import config, par

ROOT = config.ROOT
SRC = (ROOT / "cafe" / "cfd.py").read_text()


@pytest.fixture
def stl(tmp_path):
    p = tmp_path / "m.stl"
    trimesh.creation.box(extents=(2.0, 1.0, 0.5)).export(p)
    return p


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "cfdcache")
    return tmp_path / "cfdcache"


def run_cached(stl, compute, key=("external", "water", 1.5)):
    log = []
    return cfd.cached(key, stl, log.append, compute), log


# ---- M-4: the numbers and texts in the code are in the key --------------------------------------------------------------------------------------------


def base():
    return cfd._literals(SRC)


def keyed_functions(tree):
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name not in cfd.NOT_KEYED]


@pytest.mark.parametrize("old, new", [
    ("iters=1500", "iters=1501"),                                          # external's default iteration count
    ("D, h0 = 4 * L, L / 4", "D, h0 = 5 * L, L / 4"),                      # the domain
    ("D, h0 = 4 * L, L / 4", "D, h0 = 4 * L, L / 5"),                      # the base cell
    ("min(L / 200,", "min(L / 201,"),                                      # the surface cell
    ("extents.min() / 16", "extents.min() / 17"),
    ("def tail_stats(series, frac=0.2)", "def tail_stats(series, frac=0.25)"),
    ("refine_above=0.3", "refine_above=0.4"),
    ("includedAngle 150", "includedAngle 140"),                            # an inline text (twice in the file: the first is the external one)
    ("0.713 * D", "0.714 * D"),                                            # locationInMesh
    ("loc=(-0.71 * L,", "loc=(-0.72 * L,"),
    ("loc=(-0.71 * L,", "loc=(0.71 * L,"),                                  # the sign alone (round 18, M-2)
    ("surf_level=1)", "surf_level=2)"),
    ("for sl in (1, 0):", "for sl in (2, 0):"),
    ("alphas=INCIDENCE_ALPHAS, planes=(\"+y\", \"+z\")", "alphas=INCIDENCE_ALPHAS, planes=(\"+y\", \"-z\")"),
    ("tolerance 1e-7; relTol 0.01; }\n    \"(U|k|omega)\"", "tolerance 1e-7; relTol 0.02; }\n    \"(U|k|omega)\""),   # the inline fvSolution of external
    ("relaxationFactors { equations { U 0.9;", "relaxationFactors { equations { U 0.8;"),
    ("div(phi,U) bounded Gauss linearUpwindV grad(U);", "div(phi,U) bounded Gauss upwind;"),                                 # the inline fvSchemes
    ("transportModel Newtonian;\\nnu {fl['nu']:.6g};", "transportModel Newtonian;\\nnu {fl['nu']:.7g};"),                    # the transportProperties f-string
    ("deltaT 1;", "deltaT 2;"),                                                                                              # _control's f-string
    ("nu 1.48e-05; rho 1;", "nu 1.5e-05; rho 1;"),                                                                           # the air of the free-surface case
    ("pts = m.sample(4000)", "pts = m.sample(4001)"),                                                                      # symmetric_y: the half domain
    ("-1e9 -1e9 -1e9", "-1e8 -1e9 -1e9"),                                                                                    # setFieldsDict's box
])
def test_r17_m4_an_edit_of_a_number_or_an_inline_text_in_the_code_changes_the_key(old, new):
    """`SETTINGS` listed module constants only: every number and inline OpenFOAM text inside `external`, `free_surface` and `characterize_*` could be edited
    and `recipe()` and the cache file name stayed, so the Hangar's drag, lift and hull-resistance tables came back as "an identical earlier run" made with
    other sizes, iteration counts or averaging windows."""
    assert old in SRC, old
    assert cfd._literals(SRC.replace(old, new, 1)) != base()


def test_r17_m4_every_number_in_the_keyed_code_moves_the_key_unless_it_is_in_a_log_a_raise_or_a_docstring():
    """The sweep that cannot miss a future literal: each int and float constant of every function that is not in `NOT_KEYED` is raised by one, one at a time,
    and the digest of the edited module text differs from the digest of the unedited one when the constant is under neither a `log(...)` or `print(...)`
    call nor a `raise`, and is the same when it is."""
    base_tree = ast.parse(SRC)
    unedited = cfd._literals(ast.unparse(base_tree))
    n_moved = n_kept = 0
    n_nodes = sum(isinstance(c, ast.Constant) and type(c.value) in (int, float) for fn in keyed_functions(base_tree) for c in ast.walk(fn))
    for i in range(n_nodes):
        tree = ast.parse(SRC)
        mutable = [c for fn in keyed_functions(tree) for c in ast.walk(fn) if isinstance(c, ast.Constant) and type(c.value) in (int, float)]
        excluded = {id(c) for fn in keyed_functions(tree) for top in ast.walk(fn)
                    if isinstance(top, ast.Raise) or (isinstance(top, ast.Call) and isinstance(top.func, ast.Name) and top.func.id in ("log", "print"))
                    for c in ast.walk(top)}
        target = mutable[i]
        target.value += 1
        moved = cfd._literals(ast.unparse(tree)) != unedited
        assert moved == (id(target) not in excluded), (i, target.value - 1, target.lineno)
        n_moved += moved
        n_kept += not moved
    assert n_nodes > 100 and n_moved > 100 and n_kept >= 3                      # the sweep saw the file's numbers, and the log lines' numbers


def test_r17_m4_a_comment_a_docstring_a_log_line_a_message_or_an_exempt_function_keeps_the_key():
    """What round 16 kept on purpose: editing text that is not a number or an OpenFOAM text does not recompute hours of CFD."""
    for old, new in [("# the free-surface recipe, in hull lengths", "# the recipe of the free surface, in hull lengths"),
                     ('"""Steady RANS on one mesh', '"""Steady RANS (one mesh)'),
                     ("log(f\"mesh: {ms['cells']} cells, level {lvl}, {time.time() - t0:.0f}s\")",
                      "log(f\"mesh {ms['cells']} cells, {time.time() - t0:.1f}s\")"),
                     ('raise ValueError(f"unknown fluid', 'raise ValueError(f"no such fluid'),
                     ('raise ValueError(f"{what} must be a finite number above 0, got {v!r}")', 'raise ValueError(f"{what} {v!r} is not above 0")'),
                     ("fl = FLUIDS[fluid]", "fl = FLUIDS[fluid]  # the fluid"),
                     ("def main(argv: list[str]) -> pathlib.Path:", "def main(argv: list[str], x=7) -> pathlib.Path:"),
                     ('NPROC = _par.env_count("CAFE_NPROC") or 6', 'NPROC = _par.env_count("CAFE_NPROC") or 7')]:
        assert old in SRC, old
        assert cfd._literals(SRC.replace(old, new, 1)) == base(), old


def test_r17_m4_a_new_function_with_a_literal_is_keyed_unless_it_is_named_in_not_keyed():
    """The default is "keyed": a function added later needs no list entry to be covered."""
    assert cfd._literals(SRC + "\n\ndef later(x=3):\n    return x * 2\n") != base()
    assert cfd._literals(SRC + "\n\nclass Later:\n    pass\n") != base()
    assert cfd._literals(SRC + "\n\ndef main_later(x):\n    return x\n") != base()
    assert cfd._literals(SRC + "\n\ndef cached(x=3):\n    return x\n") == base()             # the exempt names are exactly NOT_KEYED


def test_r17_m4_not_keyed_names_functions_that_exist_and_each_does_not_shape_a_result():
    defs = {n.name for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef)}
    assert set(cfd.NOT_KEYED) <= defs
    assert set(cfd.NOT_KEYED) == {"recipe", "cached", "_code_literals", "_literals", "_text_and_numbers", "_plain", "main"}


def test_r17_m4_recipe_carries_the_code_digest_and_the_cache_file_follows_it(stl, cache, monkeypatch):
    """The recipe changes with the code's numbers: a call computed under the old digest recomputes under the new one, and the old entry stays."""
    compute = lambda: dict(cd=0.25)                                                                              # noqa: E731
    before = cfd.recipe()
    assert cfd._code_literals() == base() and run_cached(stl, compute)[1] == []
    assert run_cached(stl, compute)[1][0].startswith("CFD: reusing")
    monkeypatch.setattr(cfd, "_code_literals", lambda: "another edit")
    assert cfd.recipe() != before and run_cached(stl, compute)[1] == []                                          # computed again, not reused
    monkeypatch.undo()
    monkeypatch.setattr(cfd, "CACHE", cache)
    assert cfd.recipe() == before and run_cached(stl, compute)[1][0].startswith("CFD: reusing")
    assert len(list(cache.glob("*.json"))) == 2


def test_r17_m4_the_incidence_angles_are_one_named_setting_that_the_hangar_reads_not_writes(monkeypatch):
    """`hangar.py` wrote `(5.0, 10.0)` in its key by hand while `characterize_incidence` had its own default: one could change without the other."""
    assert cfd.INCIDENCE_ALPHAS == (5.0, 10.0) and "INCIDENCE_ALPHAS" in cfd.SETTINGS
    assert inspect.signature(cfd.characterize_incidence).parameters["alphas"].default is cfd.INCIDENCE_ALPHAS
    h = (ROOT / "cafe" / "hangar.py").read_text()
    assert "(5.0, 10.0)" not in h and 'round(speed, 3), cfd.INCIDENCE_ALPHAS, "3-grid")' in h


def test_r17_m21_the_stored_result_is_what_a_hit_returns_and_a_reordered_literal_keeps_the_key(stl, cache, monkeypatch):
    """Two mutants of round 16's key that no named test killed (A-4): a hit that returned the whole file, and a recipe hashed without `sort_keys`."""
    assert run_cached(stl, lambda: dict(cd=0.25))[0] == dict(cd=0.25)
    r, log = run_cached(stl, lambda: dict(cd=9.0))
    assert r == dict(cd=0.25) and log[0].startswith("CFD: reusing")                                              # the stored result, not {"recipe", ...}
    was = cfd.recipe()
    monkeypatch.setattr(cfd, "FLUIDS", {"air": cfd.FLUIDS["air"], "water": dict(nu=cfd.FLUIDS["water"]["nu"], rho=cfd.FLUIDS["water"]["rho"])})
    assert list(cfd.FLUIDS) == ["air", "water"] and cfd.recipe() == was


# ---- M-10: a finished result is returned whatever the cache does; a bad cache file heals ---------------------------------------------------------------

def test_r17_m10_an_unwritable_cache_returns_the_result_with_a_warning(stl, tmp_path, monkeypatch):
    """`cfd.CACHE` below a regular file (a read-only mount, a full disk behave alike): `compute()` ran for hours and the result was an OSError."""
    (tmp_path / "file").write_text("x")
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "file" / "cfdcache")
    calls = []
    r, log = run_cached(stl, lambda: calls.append(1) or dict(cd=0.25))
    assert r == dict(cd=0.25) and calls == [1]
    assert len(log) == 1 and log[0].startswith("warning: the CFD result was not cached, so the next run computes it again (")
    assert run_cached(stl, lambda: calls.append(1) or dict(cd=0.5))[0] == dict(cd=0.5) and calls == [1, 1]     # nothing was kept


def test_r17_m10_a_result_with_an_array_is_cached_as_lists_and_returned_as_it_was(stl, cache):
    """`default=float` of an array of two numbers was a TypeError after the compute."""
    made = dict(force=np.array([1.0, 2.0]), cd=np.float64(0.25))
    r, log = run_cached(stl, lambda: made)
    assert r is made and log == []
    assert json.loads(next(cache.glob("*.json")).read_text())["result"] == dict(force=[1.0, 2.0], cd=0.25)
    again, log = run_cached(stl, lambda: dict())
    assert again == dict(force=[1.0, 2.0], cd=0.25) and log[0].startswith("CFD: reusing")


def test_r17_m10_a_result_json_cannot_hold_is_returned_with_a_warning_and_leaves_no_file(stl, cache):
    r, log = run_cached(stl, lambda: dict(x=object()))
    assert set(r) == {"x"} and len(log) == 1 and "TypeError" in log[0] and log[0].startswith("warning: ")
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("bad", [b"", b"{", b'{"recipe": "x"}', b"[]", b"null", b'"text"', b"\xff\xfe\x00"])
def test_r17_m10_a_cache_file_that_cannot_be_read_back_is_removed_and_the_case_computed_again(stl, cache, bad):
    """Every call after a cut or foreign file raised JSONDecodeError, KeyError or TypeError (after logging "reusing an identical earlier run")."""
    run_cached(stl, lambda: dict(cd=0.25))
    f = next(cache.glob("*.json"))
    f.write_bytes(bad)
    calls = []
    r, log = run_cached(stl, lambda: calls.append(1) or dict(cd=0.5))
    assert r == dict(cd=0.5) and calls == [1]
    assert len(log) == 1 and log[0].startswith(f"CFD: the cache file {f.name} cannot be read (") and "reusing" not in log[0]
    assert json.loads(f.read_text())["result"] == dict(cd=0.5)                                   # healed: the new result is in the file
    assert run_cached(stl, lambda: calls.append(1) or dict(cd=9.0))[0] == dict(cd=0.5) and calls == [1]


def test_r17_m10_a_cache_entry_that_is_a_directory_is_computed_and_warned_about_not_raised(stl, cache):
    run_cached(stl, lambda: dict(cd=0.25))
    f = next(cache.glob("*.json"))
    f.unlink()
    f.mkdir()
    r, log = run_cached(stl, lambda: dict(cd=0.5))
    assert r == dict(cd=0.5) and log[0].startswith("CFD: the cache file") and log[-1].startswith("warning: the CFD result was not cached")


# ---- M-11: hostile arguments ---------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def no_openfoam(monkeypatch):
    def started(*a, **k):
        raise AssertionError("an OpenFOAM command was started")
    monkeypatch.setattr(cfd, "sh", started)


@pytest.fixture
def case(tmp_path):
    c = tmp_path / "case"
    (c / "constant").mkdir(parents=True)
    (c / "constant" / "earlier_run.txt").write_text("hours of work")
    return c


def untouched(case):
    return (case / "constant" / "earlier_run.txt").read_text() == "hours of work"


@pytest.mark.parametrize("label", ["x+z999", "x+z91", "x+z90.1", "x+z1.2.3", "x+z.", "x+z", "x+z-5", "x+y1e1", "x+z１０", "x+z1_0", "x+x10", "+x10", "X+z10"])
def test_r17_m11_a_direction_label_that_is_not_an_axis_or_an_angle_of_0_to_90_degrees_is_a_bad_direction(label):
    """`dvec("x+z999")` returned a vector tilted 999 degrees; `1.2.3` and `.` were the bare "could not convert string to float"."""
    with pytest.raises(ValueError, match="bad direction"):
        cfd.dvec(label)


@pytest.mark.parametrize("label, vec", [("x+z0", (1, 0, 0)), ("x+z90", (0, 0, 1)), ("x-y90", (0, -1, 0)), ("x+y10", None), ("x-z5", None),
                                        ("x+z7.5", None), ("+x", (1, 0, 0))])
def test_r17_m11_what_the_hangar_and_the_incidence_study_pass_is_still_a_direction(label, vec):
    v = cfd.dvec(label)
    assert math.isclose(float(np.linalg.norm(v)), 1.0)
    if vec is not None:
        assert np.allclose(v, vec, atol=1e-12)
    assert all(cfd.dvec(f"x{p}{a:g}") is not None for p in ("+y", "+z") for a in cfd.INCIDENCE_ALPHAS)


@pytest.mark.parametrize("kw, match", [(dict(dirs=()), "no directions"), (dict(speed=float("nan")), "speed must be a finite number above 0"),
                                       (dict(speed=0), "speed must be"), (dict(speed=-1.5), "speed must be"), (dict(speed=float("inf")), "speed must be"),
                                       (dict(speed=None), "speed must be"), (dict(fluid="oil"), r"unknown fluid 'oil': one of water, air"),
                                       (dict(dirs=("+x", "x+z999")), "bad direction")])
def test_r17_m11_external_refuses_hostile_arguments_before_the_case_is_deleted_or_meshed(stl, case, no_openfoam, kw, match):
    with pytest.raises(ValueError, match=match):
        cfd.external(stl, case, **kw)
    assert untouched(case)


@pytest.mark.parametrize("draft, speeds, match", [(float("nan"), [1.0], "draft must be"), (0.0, [1.0], "draft must be"), (-0.1, [1.0], "draft must be"),
                                                  (0.1, [], "no speeds"), (0.1, [1.0, float("nan")], "speed must be"), (0.1, [0], "speed must be"),
                                                  (0.1, [-1.0], "speed must be"), (0.1, np.array([1.0, np.inf]), "speed must be")])
def test_r17_m11_free_surface_refuses_hostile_arguments_before_the_case_is_deleted(stl, case, no_openfoam, draft, speeds, match):
    """`free_surface(stl, nan, case, [1.0])` deleted `case` before trimesh raised."""
    with pytest.raises(ValueError, match=match):
        cfd.free_surface(stl, draft, case, speeds)
    assert untouched(case)


def test_r17_m11_the_studies_refuse_them_at_their_first_call(stl, tmp_path, no_openfoam):
    """The three `characterize_*` call the two above first, so the work directory is not made and nothing runs."""
    for run, match in [(lambda: cfd.characterize_external(stl, tmp_path / "w1", "oil", 1.5), "unknown fluid"),
                       (lambda: cfd.characterize_incidence(stl, tmp_path / "w2", "water", float("nan")), "speed must be"),
                       (lambda: cfd.characterize_free_surface(stl, float("nan"), tmp_path / "w3", [1.0]), "draft must be")]:
        with pytest.raises(ValueError, match=match):
            run()
    assert list(tmp_path.glob("w*")) == []


def test_r17_m11_good_arguments_go_on_to_the_case(stl, case, monkeypatch):
    started = []

    class Stop(Exception):
        pass

    def sh(c, cmd, log):
        started.append(cmd)
        raise Stop
    monkeypatch.setattr(cfd, "sh", sh)
    with pytest.raises(Stop):
        cfd.external(stl, case, dirs=iter(["+x", "x+z10"]), speed=np.float64(1.5))                      # an iterator and a numpy float are fine
    with pytest.raises(Stop):
        cfd.free_surface(stl, 0.1, case, np.array([1.0, 2.0]))
    assert started == ["blockMesh", "blockMesh"]


@pytest.mark.parametrize("bad", ["1_0", "１０", " 4", "4 ", "+4", "٤", "4.0", "²"])
def test_r17_m11_cafe_nproc_and_cafe_workers_take_ascii_digits_only(monkeypatch, bad):
    """`int("1_0")` is 10 and `int("１０")` is 10: both were accepted by a message that says "whole number"."""
    for name in ("CAFE_X", "CAFE_WORKERS"):
        monkeypatch.setenv(name, bad)
        with pytest.raises(config.ConfigError, match=re.escape(f"{name}={bad!r} is not a whole number of at least 1")):
            par.env_count(name) if name == "CAFE_X" else par.workers()


def test_r17_m11_plain_digits_still_count(monkeypatch):
    for v, n in (("4", 4), ("10", 10), ("007", 7)):
        monkeypatch.setenv("CAFE_X", v)
        assert par.env_count("CAFE_X") == n


# ---- M-12: _seed reads $CAFE_WORK ---------------------------------------------------------------------------------------------------------------------

def test_r17_m12_seed_with_no_old_runs_says_where_it_looked_and_exits_1(tmp_path):
    """It read a hard-coded /work/runs, found nothing and exited 0 with no output, whatever `CAFE_WORK` said."""
    work = tmp_path / "work"
    (work / "runs").mkdir(parents=True)
    r = subprocess.run([sys.executable, "-m", "cafe._seed"], cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT), "CAFE_WORK": str(work)},
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 1 and f"no old runs found under {work / 'runs'}" in r.stderr and r.stdout == "", r.stderr[-400:]
    assert not (work / "cfdcache").exists()


def test_r17_m12_seed_reads_the_runs_beside_the_cache_and_writes_the_cache(tmp_path, monkeypatch, capsys):
    from cafe import _seed
    work = tmp_path / "work"
    (work / "runs" / "q1").mkdir(parents=True)
    made = dict(fluid="air", rho=1.2, nu=1.5e-5, speed=10.0, L=1.0,
                dirs={d: dict(force=[-1.0, 0.0, 0.0], moment=[0.0, 0.0, 0.0], viscous=[-0.5, 0.0, 0.0], gci=0.01) for d in cfd.DIRS})
    (work / "runs" / "q1" / "quad.external.json").write_text(json.dumps(made))
    monkeypatch.setattr(cfd, "CACHE", work / "cfdcache")
    assert _seed.main() == 0
    assert "seeded quad ('external', 'air', 10.0)" in capsys.readouterr().out
    (f,) = (work / "cfdcache").glob("*.json")
    d = json.loads(f.read_text())
    assert d["result"] == made and d["recipe"] == cfd.recipe()
