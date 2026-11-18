"""Round 18, batch D (CFD, its seed and the count parser): the sign of a literal is in the CFD cache key (M-2), a count variable of thousands of digits and a
direction label that is not a string are refused with their own messages (M-11), `_seed` says what it did and cleans up after itself (M-12), and the two
mutants of round 17's key and write guard that no test killed (M-16, A-3). No test runs OpenFOAM and none reads or writes the shared CFD cache: every `cached`
call is under a private `CACHE`."""
import ast
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pytest
import trimesh

from cafe import _seed, cfd
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


def keyed_functions(tree):
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name not in cfd.NOT_KEYED]


def excluded_ids(tree):
    """The nodes under a `raise` or a `log(...)` / `print(...)` call of a keyed function: the key leaves them out by decision."""
    return {id(c) for fn in keyed_functions(tree) for top in ast.walk(fn)
            if isinstance(top, ast.Raise) or (isinstance(top, ast.Call) and isinstance(top.func, ast.Name) and top.func.id in ("log", "print"))
            for c in ast.walk(top)}


def signed_sites(tree):
    return [c for fn in keyed_functions(tree) for c in ast.walk(fn)
            if isinstance(c, ast.UnaryOp) and isinstance(c.op, (ast.USub, ast.UAdd)) and isinstance(c.operand, ast.Constant)]


# ---- M-2: the sign of a literal is in the key -----------------------------------------------------------------------------------------------------------

def test_r18_m2_the_minus_of_a_negative_literal_is_in_the_cfd_key():
    """`loc=(-0.71 * L, ...)` is `UnaryOp(USub, Constant(0.71))`: the walker listed the 0.71 and dropped the minus, so a source edit that moved the free-surface
    mesh's `locationInMesh` to the opposite back corner left every cache file name where it was."""
    old = "loc=(-0.71 * L, -0.83 * L, -0.37 * L)"
    assert old in SRC
    assert cfd._literals(SRC.replace(old, "loc=(0.71 * L, 0.83 * L, 0.37 * L)", 1)) != cfd._literals(SRC)
    assert cfd._literals(SRC.replace(old, "loc=(-0.71 * L, 0.83 * L, -0.37 * L)", 1)) != cfd._literals(SRC)       # one sign alone


def test_r18_m2_turning_any_signed_literal_of_the_keyed_code_to_the_other_sign_moves_the_key():
    """The sweep that cannot miss a future sign: every `-n` and `+n` of every keyed function (outside a `raise`, a `log(...)` and a `print(...)`) is turned to
    the other sign, one at a time, and the digest of the edited text differs; under a `raise` or a log call it does not. Round 17's sweep raised each number
    by one, which never turned a minus into a plus."""
    unedited = cfd._literals(ast.unparse(ast.parse(SRC)))
    n_sites = len(signed_sites(ast.parse(SRC)))
    n_moved = n_kept = 0
    for i in range(n_sites):
        tree = ast.parse(SRC)
        target = signed_sites(tree)[i]
        skipped = id(target) in excluded_ids(tree)
        target.op = ast.UAdd() if isinstance(target.op, ast.USub) else ast.USub()
        moved = cfd._literals(ast.unparse(tree)) != unedited
        assert moved == (not skipped), (i, target.lineno, ast.unparse(target))
        n_moved += moved
        n_kept += not moved
    assert n_sites >= 10 and n_moved >= 10            # measured at the base commit: 10 of the file's 27 are in a keyed function


def test_r18_m2_the_other_signed_literals_of_the_file_are_module_constants_that_the_recipe_hashes_with_their_signs():
    """DIRS, FS_DOMAIN, FS_Z and FS_BOXES hold 17 signed literals; they reach the key through `json.dumps` of `SETTINGS`, which writes the sign."""
    tree = ast.parse(SRC)
    sites = [(n, c) for n in tree.body if isinstance(n, ast.Assign) for c in ast.walk(n)
             if isinstance(c, ast.UnaryOp) and isinstance(c.operand, ast.Constant)]
    assert len(sites) == 17
    assert all(n.targets[0].id in cfd.SETTINGS for n, c in sites)
    assert all(json.dumps(getattr(cfd, n.targets[0].id)).count("-") >= 1 for n, c in sites)


def test_r18_m2_a_sign_is_one_item_with_its_number_and_only_a_literal_has_one():
    def digest(body):
        return cfd._literals(f"def f(x):\n    return {body}\n")
    assert len({digest("1"), digest("-1"), digest("+1"), digest("~1"), digest("- -1"), digest("-+1")}) == 6
    assert digest("-1") != digest("-2") and digest("-1.0") != digest("-1")
    assert digest("-x") == digest("x") == digest("not x")                         # the logic of the code is outside the key (DECISIONS 929)
    assert digest("-x + 1") == digest("x - 1") == digest("x * 1")                 # and so is a binary operator: only its numbers
    assert cfd._literals("def f():\n    raise ValueError(-1)\n") == cfd._literals("def f():\n    raise ValueError(+1)\n")
    assert cfd._literals("def f():\n    print(-1)\n") == cfd._literals("def f():\n    print(+1)\n")
    assert cfd._literals("def f(a=-1):\n    return a\n") != cfd._literals("def f(a=1):\n    return a\n")               # a signed default


def test_r18_m2_the_sign_changes_the_recipe_and_so_the_cache_file(stl, cache, monkeypatch):
    compute = lambda: dict(cd=0.25)                                                                              # noqa: E731
    run_cached(stl, compute)
    before = cfd.recipe()
    monkeypatch.setattr(cfd, "_code_literals", lambda: cfd._literals(SRC.replace("loc=(-0.71 * L,", "loc=(0.71 * L,", 1)))
    assert cfd.recipe() != before and run_cached(stl, compute)[1] == []                                          # computed again, not reused
    assert len(list(cache.glob("*.json"))) == 2


# ---- M-11: a count of thousands of digits, a direction that is not a string -------------------------------------------------------------------------------

@pytest.mark.parametrize("digits", [10, 11, 4300, 5000])
def test_r18_m11_a_count_longer_than_nine_digits_is_a_config_error_that_names_the_variable(monkeypatch, digits):
    """`CAFE_X="9"*5000` was a bare `ValueError: Exceeds the limit (4300 digits)` from `int`, and `CAFE_NPROC=99999999999` reached `mpirun -np`."""
    for name in ("CAFE_X", "CAFE_WORKERS", "CAFE_NPROC"):
        monkeypatch.setenv(name, "9" * digits)
        with pytest.raises(config.ConfigError, match=f"{name}=") as e:
            par.env_count(name) if name != "CAFE_WORKERS" else par.workers()
        assert "9 digits" in str(e.value) and len(str(e.value)) < 300 and "9" * 41 not in str(e.value)              # the message does not print 5,000 digits


def test_r18_m11_a_count_of_up_to_nine_digits_is_still_a_count(monkeypatch):
    for v, n in (("999999999", 999999999), ("000000009", 9), ("8", 8)):
        monkeypatch.setenv("CAFE_X", v)
        assert par.env_count("CAFE_X") == n
    monkeypatch.setenv("CAFE_X", "0")
    with pytest.raises(config.ConfigError, match="not a whole number of at least 1"):
        par.env_count("CAFE_X")


def test_r18_m11_importing_cfd_with_a_huge_cafe_nproc_names_the_variable():
    """`NPROC = par.env_count("CAFE_NPROC") or 6` runs at import: round 16's M-26 made a bad value a ConfigError, and 5,000 digits was still a ValueError."""
    r = subprocess.run([sys.executable, "-c", "import cafe.cfd"], cwd=ROOT, capture_output=True, text=True, timeout=600,
                       env={**os.environ, "PYTHONPATH": str(ROOT), "CAFE_NPROC": "9" * 5000})
    assert r.returncode != 0 and "ConfigError" in r.stderr and "CAFE_NPROC=" in r.stderr and "Exceeds the limit" not in r.stderr, r.stderr[-500:]


@pytest.mark.parametrize("label", [None, ["+x"], 5, 1.5, b"+x", ("+x",), {"+x"}, object()])
def test_r18_m11_a_direction_label_that_is_not_a_string_is_a_bad_direction_not_a_type_error(label):
    """`dvec(None)` and `dvec(["+x"])` raised `TypeError` (`d in DIRS` unhashable, `re.fullmatch` on a non-string); DECISIONS 931 says `ValueError`."""
    with pytest.raises(ValueError, match="bad direction"):
        cfd.dvec(label)


def test_r18_m11_external_refuses_a_label_that_is_not_a_string_before_the_case_is_touched(stl, tmp_path, monkeypatch):
    def started(*a, **k):
        raise AssertionError("an OpenFOAM command was started")
    monkeypatch.setattr(cfd, "sh", started)
    case = tmp_path / "case"
    (case / "constant").mkdir(parents=True)
    (case / "constant" / "earlier_run.txt").write_text("hours of work")
    with pytest.raises(ValueError, match="bad direction"):
        cfd.external(stl, case, dirs=("+x", ["+y"]))
    assert (case / "constant" / "earlier_run.txt").read_text() == "hours of work"


def test_r18_m11_the_labels_that_were_directions_still_are():
    assert np.allclose(cfd.dvec("+x"), (1, 0, 0)) and np.allclose(cfd.dvec("-z"), (0, 0, -1)) and np.allclose(cfd.dvec("x+z90"), (0, 0, 1), atol=1e-12)


# ---- M-12: _seed says what it did ------------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def seed_runs(tmp_path, monkeypatch):
    """A private `$CAFE_WORK`: one old quad run beside a private cache (the shared cache on orca is never named)."""
    work = tmp_path / "work"
    (work / "runs" / "q1").mkdir(parents=True)
    made = dict(fluid="air", rho=1.2, nu=1.5e-5, speed=10.0, L=1.0, dirs={"+x": dict(force=[-1.0, 0.0, 0.0], moment=[0.0, 0.0, 0.0], viscous=[-0.5, 0.0, 0.0])})
    (work / "runs" / "q1" / "quad.external.json").write_text(json.dumps(made))
    monkeypatch.setattr(cfd, "CACHE", work / "cfdcache")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return work, made, scratch


def test_r18_m12_seed_a_second_time_says_already_there_not_seeded(seed_runs, capsys):
    """The second `python -m cafe._seed` printed "CFD: reusing an identical earlier run" and then "seeded quad ..." for a sample that wrote nothing."""
    work, made, scratch = seed_runs
    assert _seed.main() == 0
    first = capsys.readouterr().out
    assert "seeded quad ('external', 'air', 10.0)" in first and "already there" not in first
    assert _seed.main() == 0
    second = capsys.readouterr().out
    assert "already there quad ('external', 'air', 10.0)" in second and "seeded quad" not in second and "CFD: reusing" in second
    (f,) = (work / "cfdcache").glob("*.json")
    assert json.loads(f.read_text())["result"] == made


def test_r18_m12_seed_into_a_cache_that_cannot_be_written_says_not_seeded_and_exits_1(seed_runs, capsys):
    """A read-only cache printed a warning and then "seeded quad ..." and exited 0."""
    work, made, scratch = seed_runs
    (work / "cfdcache").write_text("x")                                                    # a regular file where the cache directory should be: the write fails
    assert _seed.main() == 1
    out = capsys.readouterr().out
    assert "NOT seeded quad ('external', 'air', 10.0) - warning: the CFD result was not cached" in out and "seeded quad" not in out.replace("NOT seeded", "")


def test_r18_m12_seed_a_cache_file_that_cannot_be_read_is_replaced_and_counts_as_seeded(seed_runs, capsys):
    work, made, scratch = seed_runs
    assert _seed.main() == 0
    (f,) = (work / "cfdcache").glob("*.json")
    f.write_bytes(b"{")
    capsys.readouterr()
    assert _seed.main() == 0
    out = capsys.readouterr().out
    assert "cannot be read" in out and "seeded quad" in out and "already there" not in out
    assert json.loads(f.read_text())["result"] == made


def test_r18_m12_seed_leaves_no_temporary_directory_behind(seed_runs):
    """Each sample left a `tmp*/mesh.stl` directory."""
    work, made, scratch = seed_runs
    assert _seed.main() == 0 and _seed.main() == 0
    assert list(scratch.iterdir()) == []


# ---- M-16 (A-3): two mutants of round 17's key and write guard that survived ----------------------------------------------------------------------------

def test_r18_a3_the_command_texts_of_the_openfoam_calls_are_in_the_key():
    """Mutant `("log", "print", "sh")` took the `sh(case, "blockMesh", ...)` calls out of the key: an edited command text (`decomposePar -force`,
    `refineMesh ... -overwrite`, the log names) would then keep every cache file name. Each text constant of each `sh(...)` call of a keyed function moves the
    digest when it is edited."""
    unedited = cfd._literals(ast.unparse(ast.parse(SRC)))

    def sh_texts(tree):
        calls = [x for fn in keyed_functions(tree) for x in ast.walk(fn) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "sh"]
        return [c for call in calls for c in ast.walk(call) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    n = len(sh_texts(ast.parse(SRC)))
    assert n >= 20                                                                  # measured at the base commit: 30 text constants in 15 calls
    for i in range(n):
        tree = ast.parse(SRC)
        target = sh_texts(tree)[i]
        target.value += "x"
        assert cfd._literals(ast.unparse(tree)) != unedited, (i, target.value)
    assert cfd._literals(SRC.replace('sh(case, "decomposePar -force", "decomposeMesh")', 'sh(case, "decomposePar", "decomposeMesh")', 1)) != cfd._literals(SRC)


def test_r18_a3_a_result_that_json_refuses_with_a_value_error_is_returned_with_a_warning(stl, cache):
    """Mutant: `cached`'s write guard without `ValueError`. A circular list is `ValueError: Circular reference detected` from `json.dumps`, not a `TypeError`:
    the finished result of hours of CFD would be an exception."""
    loop: list = []
    loop.append(loop)
    r, log = run_cached(stl, lambda: dict(x=loop))
    assert r["x"] is loop
    assert len(log) == 1 and log[0].startswith("warning: the CFD result was not cached") and "ValueError" in log[0] and "Circular" in log[0]
    assert list(cache.iterdir()) == []
