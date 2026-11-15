"""cafe.cfd (the old app's OpenFOAM driver) without OpenFOAM: the cache key (round 16, M-23), the module constants and the inputs that used to end in a
traceback after the case directory was deleted (M-26). `sh` is replaced wherever a case would be meshed: no test here runs OpenFOAM."""
import ast
import json
import os
import subprocess
import sys

import pytest
import trimesh

from cafe import cfd
from cafe.pm import config

ROOT = config.ROOT


@pytest.fixture
def stl(tmp_path):
    p = tmp_path / "m.stl"
    trimesh.creation.box(extents=(2.0, 1.0, 0.5)).export(p)
    return p


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cfd, "CACHE", tmp_path / "cfdcache")
    return tmp_path / "cfdcache"


def runs(stl, key=("external", "water", 1.5)):
    """Call `cached` and say whether `compute` ran."""
    log, calls = [], []
    r = cfd.cached(key, stl, log.append, lambda: calls.append(1) or dict(cd=0.25))
    return r, bool(calls), log


# ---- M-23: the key carries the solver settings --------------------------------------------------------------------------------------------------------

def changed(v):
    """A different value of the same kind."""
    if isinstance(v, str):
        return v + " x"
    if isinstance(v, (int, float)):
        return v + 1
    if isinstance(v, tuple):
        return v + (7,)
    return {**v, "extra": 1}


def test_r16_m23_a_result_is_reused_for_the_same_mesh_key_and_recipe_and_computed_again_when_any_setting_changes(stl, cache, monkeypatch):
    """`cached` keyed on the mesh bytes and the call parameters only: after `FS_LTS` or `EXT_SNAPPY` was edited the same call printed "reusing an identical
    earlier run" and returned the old result. Every constant of `cfd.SETTINGS` is in the key (the first call after each change computes; the same recipe
    reuses), and the OpenFOAM version is one of them (it is in `FOAM`)."""
    assert "openfoam2506" in cfd.FOAM and "FOAM" in cfd.SETTINGS
    assert runs(stl) == (dict(cd=0.25), True, [])
    assert runs(stl)[1] is False                                                                 # same mesh, key and recipe: reused
    for name in cfd.SETTINGS:
        was = getattr(cfd, name)
        with monkeypatch.context() as m:
            m.setattr(cfd, name, changed(was))
            r, computed, log = runs(stl)
            assert computed and log == [], name                                                  # not reused: the recipe is another
            assert runs(stl)[1] is False, name                                                   # and the new recipe is cached in turn
        assert runs(stl)[1] is False, name                                                       # back to the first recipe: its entry is still there


def test_r16_m23_the_core_count_does_not_key_the_result_but_is_recorded_in_the_file(stl, cache, monkeypatch):
    monkeypatch.setattr(cfd, "NPROC", 6)
    runs(stl)
    monkeypatch.setattr(cfd, "NPROC", 2)
    assert runs(stl)[1] is False                                                                 # the same answer, whatever the cores
    files = list(cache.glob("*.json"))
    assert len(files) == 1
    d = json.loads(files[0].read_text())
    assert set(d) == {"recipe", "nproc", "result"} and d["nproc"] == 6 and d["result"] == dict(cd=0.25) and d["recipe"] == cfd.recipe()


def test_r16_m23_a_comment_or_another_function_changes_nothing_the_recipe_is_the_constants_alone():
    """`recipe()` is a function of `SETTINGS` and of nothing else of the file, so editing a comment, a docstring or a function body keeps hours of CFD."""
    src = (ROOT / "cafe" / "cfd.py").read_text()
    names = {t.id for n in ast.parse(src).body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name) and t.id.isupper()}
    # a new constant must be named in one of the two lists
    assert names == set(cfd.SETTINGS) | set(cfd.NOT_SETTINGS) and not set(cfd.SETTINGS) & set(cfd.NOT_SETTINGS)
    assert cfd.recipe() == cfd.recipe() and len(cfd.recipe()) == 16


# ---- M-26: the core count ---------------------------------------------------------------------------------------------------------------------------

def nproc_in_fresh_python(value):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    if value is None:
        env.pop("CAFE_NPROC", None)
    else:
        env["CAFE_NPROC"] = value
    return subprocess.run([sys.executable, "-c", "import cafe.cfd as c; print(c.NPROC)"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("value, want", [(None, "6"), ("", "6"), ("4", "4")])
def test_r16_m26_cafe_nproc_unset_or_empty_is_six_and_a_number_is_that_number(value, want):
    """`int(os.environ.get("CAFE_NPROC", "6"))` made `CAFE_NPROC=` a ValueError at import, so even `python -m cafe.cfd --help` and the app died."""
    r = nproc_in_fresh_python(value)
    assert r.returncode == 0 and r.stdout.strip() == want, r.stderr[-400:]


@pytest.mark.parametrize("bad", ["abc", "0", "-3"])
def test_r16_m26_a_bad_cafe_nproc_is_a_config_error_naming_it_as_everywhere_else(bad):
    r = nproc_in_fresh_python(bad)
    assert r.returncode != 0 and f"CAFE_NPROC='{bad}' is not a whole number of at least 1" in r.stderr


# ---- M-26: inputs that are refused before anything is deleted or meshed --------------------------------------------------------------------------------

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


def flat_stl(tmp_path):
    p = tmp_path / "flat.stl"
    trimesh.creation.box(extents=(2.0, 1.0, 0.0)).export(p)
    return p


@pytest.mark.parametrize("run", [lambda p, c: cfd.external(p, c), lambda p, c: cfd.free_surface(p, 0.1, c, [1.0])])
def test_r16_m26_a_flat_mesh_is_refused_naming_the_file_and_the_case_directory_is_left_alone(tmp_path, case, no_openfoam, run):
    """A zero-thickness box gave `OverflowError: cannot convert float infinity to integer` after `rmtree(case)`; the case holds the log of an earlier run."""
    p = flat_stl(tmp_path)
    with pytest.raises(ValueError, match=r"flat\.stl: flat or empty mesh"):
        run(p, case)
    assert (case / "constant" / "earlier_run.txt").read_text() == "hours of work"


def test_r16_m26_an_empty_stl_is_refused_before_the_case_directory_is_touched(tmp_path, case, no_openfoam):
    p = tmp_path / "empty.stl"
    p.write_text("solid empty\nendsolid empty\n")
    with pytest.raises(ValueError):
        cfd.external(p, case)
    assert (case / "constant" / "earlier_run.txt").exists()


def test_r16_m26_a_thin_body_is_not_refused_there_is_no_relative_threshold(tmp_path):
    """Real foils are thin: any positive extent passes."""
    p = tmp_path / "foil.stl"
    trimesh.creation.box(extents=(2.0, 1.0, 1e-6)).export(p)
    assert cfd._body(p).extents.min() > 0


@pytest.mark.parametrize("dirs", [("+x", "+q"), ("x+z", ), ("+x", "x+z10", "-w")])
def test_r16_m26_a_mistyped_direction_is_found_before_the_case_is_deleted_or_meshed(stl, case, no_openfoam, dirs):
    """`dvec` was first called after the mesh was built (hours into `characterize_external`'s coarse run)."""
    with pytest.raises(ValueError, match="bad direction"):
        cfd.external(stl, case, dirs=dirs)
    assert (case / "constant" / "earlier_run.txt").exists()


def test_r16_m26_a_good_body_and_good_directions_go_on_to_the_case(stl, case, monkeypatch):
    started = []

    class Stop(Exception):
        pass

    def sh(c, cmd, log):
        started.append(cmd)
        raise Stop
    monkeypatch.setattr(cfd, "sh", sh)
    with pytest.raises(Stop):
        cfd.external(stl, case, dirs=("+x", "x+z10"))
    assert started == ["blockMesh"] and not (case / "constant" / "earlier_run.txt").exists() and (case / "constant" / "triSurface" / "body.stl").is_file()
