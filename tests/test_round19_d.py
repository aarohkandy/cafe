"""Round 19, batch D (the CFD key, `_seed`, `atomic.replace_from`, the count parser): a function under a top-level `if` or `try`, or an `async def`, is in
the CFD cache key (M-9); `python -m cafe._seed` looks at what it seeds before it writes anything (M-14); and the tests that kill three mutants of round 18's
tests that survived (M-16, A-7: N5 the wording of `env_count`'s refusal, D7 the warning `_seed` prints, A3 the mode `replace_from` gives a new name). No test
runs OpenFOAM and none reads or writes the shared CFD cache: every `cached` call is under a private `CACHE`."""
import contextlib
import json
import os
import stat
import tempfile

import numpy as np
import pytest

from cafe import _seed, atomic, cfd, geom
from cafe.pm import config, par

ROOT = config.ROOT


# ---- M-9: a function anywhere in the file is keyed --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("wrapper", [
    "if True:\n{body}",
    "if False:\n    pass\nelse:\n{body}",
    "try:\n{body}except ImportError:\n    pass\n",
    "try:\n    import os\nexcept ImportError:\n{body}",
    "try:\n    pass\nfinally:\n{body}",
    "with open('x') as fh:\n{body}",
    "for _ in range(1):\n{body}",
    "while False:\n{body}",
])
def test_r19_m9_a_function_under_a_top_level_statement_moves_the_key_when_a_number_in_it_changes(wrapper):
    """`cfd._literals` walked `ast.parse(src).body` one level: a function a refactor put under `try: import x` or `if` was outside the key, and an edit of its
    mesh size kept every cache file name. Fails on the unfixed code: the two digests are equal."""
    body = "    def f():\n        return {}\n"
    assert cfd._literals(wrapper.replace("{body}", body.format(1))) != cfd._literals(wrapper.replace("{body}", body.format(2)))


def test_r19_m9_an_async_def_and_a_method_of_a_class_under_an_if_are_keyed():
    assert cfd._literals("async def f():\n    return 1\n") != cfd._literals("async def f():\n    return 2\n")
    assert cfd._literals("if True:\n    async def f():\n        return 1\n") != cfd._literals("if True:\n    async def f():\n        return 2\n")
    assert cfd._literals("if True:\n    class C:\n        def m(self):\n            return 1\n") != cfd._literals(
        "if True:\n    class C:\n        def m(self):\n            return 2\n")


def test_r19_m9_the_exempt_names_and_the_rules_of_a_keyed_function_hold_wherever_it_sits():
    """`main` (in `NOT_KEYED`) under an `if` is exempt as at top level; a docstring, a `log(...)` call and a `raise` under one are left out as
before; a def inside
    a def is keyed once, through its parent (a number in it moves the key and nothing is listed twice)."""
    assert cfd._literals("if True:\n    def main():\n        return 1\n") == cfd._literals("if True:\n    def main():\n        return 2\n")
    assert cfd._literals("if True:\n    def f():\n        'a'\n        log('x')\n        raise ValueError('y')\n") == cfd._literals(
        "if True:\n    def f():\n        'b'\n        log('z')\n        raise ValueError('w')\n")
    outer = "def f():\n    def g():\n        return {}\n    return g\n"
    assert cfd._literals(outer.format(1)) != cfd._literals(outer.format(2))
    assert cfd._literals(outer.format(1)) == cfd._literals("if True:\n" + "".join("    " + x + "\n" for x in outer.format(1).splitlines())) != cfd._literals("")


def test_r19_m9_the_shipped_file_has_the_key_it_had_before_so_no_cached_result_is_renamed():
    """No function of `cafe/cfd.py` sits under an `if` or `try` (the only such statement is the `__main__` guard), so the walk finds the same
functions as before:
    `recipe()` and the literals' digest are the values measured at 51eb433 (on orca, the Python of the image). A cache file made by the code of round 18 is read
    by this code: a Hangar user sees "reusing an identical earlier run", not a CFD of hours."""
    assert cfd._code_literals() == "9a7181651627013ab5dbd3c6e78f833a798f6aac"
    assert cfd.recipe() == "a091d933b7537473"


# ---- M-14: _seed looks at what it seeds -------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def work(tmp_path, monkeypatch):
    """A private `$CAFE_WORK` with a private cache and a private temporary directory (the shared cache on orca is never named)."""
    w = tmp_path / "work"
    monkeypatch.setattr(cfd, "CACHE", w / "cfdcache")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return w


def external(fluid="air", speed=10.0):
    return dict(fluid=fluid, rho=1.2, nu=1.5e-5, speed=speed, L=1.0,
                dirs={d: dict(force=[-1.0, 0.0, 0.0], moment=[0.0, 0.0, 0.0], viscous=[-0.5, 0.0, 0.0], gci=0.01) for d in cfd.DIRS})


def six(**plus_x):
    """The six directions of `external()` with the fields of `+x` replaced by `plus_x` (a bad vector in one direction, the other five good)."""
    return {**external()["dirs"], "+x": plus_x}


def put(work, run, name, content):
    d = work / "runs" / run
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    if isinstance(content, bytes):
        f.write_bytes(content)
    else:
        f.write_text(content if isinstance(content, str) else json.dumps(content))
    return f


def wigley():
    s = geom.SAMPLES["wigley"]
    hs = geom.hydrostatics(s["make"](), s["spec"]["mass"])
    return hs, [float(fn * np.sqrt(9.81 * hs["lwl"])) for fn in (0.2, 0.3, 0.4)]


def cached_files(work):
    return sorted((work / "cfdcache").glob("*.json")) if (work / "cfdcache").exists() else []


def drop(d, *path):
    """`d` (a deep copy through JSON) without the key at `path`."""
    d = json.loads(json.dumps(d))
    x = d
    for k in path[:-1]:
        x = x[k]
    del x[path[-1]]
    return d


BAD_EXTERNAL = {
    "a list": "[1, 2]",
    "a number": "5",
    "null": "null",
    "not json": "{not json",
    "empty": "",
    "no keys": "{}",
    "no dirs": json.dumps(drop(external(), "dirs")),
    "no rho": json.dumps(drop(external(), "rho")),
    "L a string": json.dumps({**external(), "L": "1"}),
    "nu a bool": json.dumps({**external(), "nu": True}),
    "NaN in L": '{"fluid": "air", "rho": 1.2, "nu": 1.5e-5, "speed": 10.0, "L": NaN, "dirs": {}}',
    "no force": json.dumps(drop(external(), "dirs", "+x", "force")),
    "a force of two numbers": json.dumps({**external(), "dirs": six(force=[1.0, 2.0], moment=[0, 0, 0], viscous=[0, 0, 0], gci=0.0)}),
    "a force with a string": json.dumps({**external(), "dirs": six(force=[1.0, 2.0, "3"], moment=[0, 0, 0], viscous=[0, 0, 0], gci=0.0)}),
    "a direction that is no axis": json.dumps({**external(), "dirs": {**external()["dirs"], "+q": external()["dirs"]["+x"]}}),
    "empty dirs": json.dumps({**external(), "dirs": {}}),
    "a direction that is a list": json.dumps({**external(), "dirs": {**external()["dirs"], "+x": [1, 2, 3]}}),
    "the fluid of another case": json.dumps(external("water", 1.5)),
    "the speed of another case": json.dumps(external("air", 5.0)),
    "invalid UTF-8": b"\xff\xfe{",
}


@pytest.mark.parametrize("name", list(BAD_EXTERNAL))
def test_r19_m14_a_file_that_is_not_a_result_is_not_seeded_and_the_exit_is_1(work, capsys, name):
    """`[1,2]` printed `seeded quad ...` and exit 0 (the list was the cached result under the real key); `{not json` was a raw `JSONDecodeError`
traceback with no
    file name. Each is now `NOT seeded <file> - <reason>`, exit 1, and the cache is not written."""
    f = put(work, "q1", "quad.external.json", BAD_EXTERNAL[name])
    assert _seed.main() == 1
    cap = capsys.readouterr()
    assert f"NOT seeded {f} - " in cap.out and "seeded quad" not in cap.out.replace("NOT seeded", "") and "nothing was seeded" in cap.err
    assert cached_files(work) == [] and not (work / "cfdcache").exists()


def test_r19_m14_a_file_that_cannot_be_read_is_named(work, capsys):
    """A directory where the file should be: `OSError`, not a traceback."""
    f = work / "runs" / "q1" / "quad.external.json"
    f.mkdir(parents=True)
    assert _seed.main() == 1
    out = capsys.readouterr().out
    assert f"NOT seeded {f} - " in out and "Is a directory" in out


def test_r19_m14_one_bad_file_stops_the_run_before_a_good_one_is_written(work, capsys):
    """Earlier samples were seeded before the bad one raised: now every file is read first, so a good quad file is not cached when the torpedo's is cut."""
    put(work, "q1", "quad.external.json", external())
    bad = put(work, "t1", "torpedo.external.json", '{"fluid": "water"')
    assert _seed.main() == 1
    cap = capsys.readouterr()
    assert f"NOT seeded {bad} - " in cap.out and "seeded quad" not in cap.out and "nothing was seeded: 1 of the 2 files" in cap.err
    assert cached_files(work) == []


def test_r19_m14_every_bad_file_is_named_not_only_the_first(work, capsys):
    q = put(work, "q1", "quad.external.json", "[1]")
    t = put(work, "t1", "torpedo.external.json", "[2]")
    assert _seed.main() == 1
    out = capsys.readouterr().out
    assert f"NOT seeded {q} - " in out and f"NOT seeded {t} - " in out


def test_r19_m14_the_results_the_hangar_reads_are_still_seeded(work, capsys):
    """The three shipped cases: a quad (air, 10 m/s), a torpedo (water, 1.5 m/s) and a wigley hull (json keys of `speeds` are strings), with the keys a real run
    adds (a `gci` per direction, a stamp, the mesh, the seconds) beside the fields the check asks for."""
    extra = dict(level=2, mesh=dict(cells=10, failed_checks=0), seconds=3.5, gci=0.0, stamp=dict(commit="abc1234"))
    put(work, "q1", "quad.external.json", {**external(), **extra})
    put(work, "t1", "torpedo.external.json", {**external("water", 1.5), **extra})
    hs, speeds = wigley()
    runs = {u: dict(resistance=3.0 + i, lift=0.1, viscous_x=1.0) for i, u in enumerate(speeds)}
    put(work, "w1", "wigley.surface.json", dict(L=hs["lwl"], half=True, speeds=runs, **extra))
    assert _seed.main() == 0
    out = capsys.readouterr().out
    assert "seeded quad ('external', 'air', 10.0)" in out and "seeded torpedo ('external', 'water', 1.5)" in out and "seeded wigley ('surface'," in out
    results = [json.loads(f.read_text())["result"] for f in cached_files(work)]
    assert len(results) == 3 and any("speeds" in r and sorted(float(u) for u in r["speeds"]) == sorted(speeds) for r in results)
    assert _seed.main() == 0                                                                        # the second run: already there, still exit 0
    assert capsys.readouterr().out.count("already there") == 3


BAD_SURFACE = {
    "no speeds": lambda hs, sp: dict(L=hs["lwl"]),
    "empty speeds": lambda hs, sp: dict(L=hs["lwl"], speeds={}),
    "speeds a list": lambda hs, sp: dict(L=hs["lwl"], speeds=[1, 2, 3]),
    "a speed that is not a number": lambda hs, sp: dict(speeds={"fast": dict(resistance=1.0)}),
    "no resistance": lambda hs, sp: dict(speeds={u: dict(lift=1.0) for u in sp}),
    "a resistance that is NaN": lambda hs, sp: dict(speeds={u: dict(resistance=float("nan")) for u in sp}),
    "the speeds of another hull": lambda hs, sp: dict(speeds={u * 2: dict(resistance=1.0) for u in sp}),
    "two of the three speeds": lambda hs, sp: dict(speeds={u: dict(resistance=1.0) for u in sp[:2]}),
}


@pytest.mark.parametrize("name", list(BAD_SURFACE))
def test_r19_m14_a_free_surface_file_of_another_shape_is_not_seeded(work, capsys, name):
    hs, speeds = wigley()
    f = put(work, "w1", "wigley.surface.json", json.dumps(BAD_SURFACE[name](hs, speeds), allow_nan=True))
    assert _seed.main() == 1
    assert f"NOT seeded {f} - " in capsys.readouterr().out and cached_files(work) == []


def test_r19_m14_no_file_at_all_is_still_the_one_line_message_and_exit_1(work, capsys):
    (work / "runs").mkdir(parents=True)
    assert _seed.main() == 1
    cap = capsys.readouterr()
    assert f"no old runs found under {work / 'runs'}" in cap.err and cap.out == ""


# ---- A-7, N5: the wording of env_count's refusal ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("v", ["abcdefghij", "1234567890x", "１２３４５６７８９０", "1_000_000_000", "-1234567890", " 123456789 "])
def test_r19_a7_n5_a_long_value_that_is_not_all_digits_is_not_told_it_has_more_than_nine_digits(monkeypatch, v):
    """Mutant N5 (`digits and` dropped from the wording test): any value longer than 9 characters, such as `abcdefghij`, was told it "has more than 9
digits". The
    message says what is wrong with it: it is not a whole number of at least 1. Only a value of 10 or more ASCII digits gets the other message."""
    monkeypatch.setenv("CAFE_X", v)
    with pytest.raises(config.ConfigError) as e:
        par.env_count("CAFE_X")
    assert "is not a whole number of at least 1" in str(e.value) and "9 digits" not in str(e.value) and "CAFE_X=" in str(e.value)


def test_r19_a7_n5_ten_ascii_digits_are_the_only_ones_called_too_long(monkeypatch):
    monkeypatch.setenv("CAFE_X", "1234567890")
    with pytest.raises(config.ConfigError, match="has more than 9 digits") as e:
        par.env_count("CAFE_X")
    assert "not a whole number" not in str(e.value)


# ---- A-7, D7: the warning `_seed` prints for a sample that could not be cached ----------------------------------------------------------------------------

def test_r19_a7_d7_the_not_seeded_line_names_the_last_warning_of_the_cache(work, capsys, monkeypatch):
    """Mutant D7: the first warning in place of the last. `cached` logs one `warning:` line today; this holds the rule for the day it logs two (the
line that says
    why the result was lost is the last, after any earlier note)."""
    put(work, "q1", "quad.external.json", external())

    def cached(key, stl, log, compute):
        log("warning: the first")
        log("CFD: a line that is no warning")
        r = compute()
        log("warning: the last")
        return r
    monkeypatch.setattr(cfd, "cached", cached)
    assert _seed.main() == 1
    out = capsys.readouterr().out
    assert "NOT seeded quad ('external', 'air', 10.0) - warning: the last" in out and "- warning: the first" not in out


# ---- A-7, A3: the mode `replace_from` gives a name ----------------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def umask(m):
    old = os.umask(m)
    try:
        yield
    finally:
        os.umask(old)


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.mark.parametrize("m", [0o600, 0o640, 0o644, 0o664, 0o755])
def test_r19_a7_a3_a_new_name_keeps_the_mode_of_the_part(tmp_path, m):
    """Mutant A3 (`fchmod(fd, mode or 0o600)`: `0o600` for a name that is new): a fetched part made under umask 022 is 0o644 and the file it becomes
is 0o644, as
    the writer's rule for a new name says (the process's umask, not a private mode); the mutant made every first fetch 0o600."""
    src, dest = tmp_path / "src", tmp_path / "dest"
    src.write_bytes(b"part")
    src.chmod(m)
    atomic.replace_from(src, dest)
    assert mode(dest) == m and dest.read_bytes() == b"part" and not src.exists()


def test_r19_a7_a3_an_existing_file_of_mode_zero_gives_its_mode_not_0o600(tmp_path):
    """The same line read by a mutant that tests `mode` for truth (`if mode:` or `mode or 0o600`): the mode 0 of an existing file is a mode to keep,
and a part made
    with 0o600 must not become wider than the file it replaces."""
    src, dest = tmp_path / "src", tmp_path / "dest"
    dest.write_bytes(b"old")
    dest.chmod(0)
    src.write_bytes(b"new")
    src.chmod(0o666)
    atomic.replace_from(src, dest)
    assert mode(dest) == 0 and not src.exists()
    dest.chmod(0o600)
    assert dest.read_bytes() == b"new"


def test_r19_a7_a3_the_part_made_under_a_strict_umask_is_widened_only_to_the_target_it_replaces(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "dest"
    dest.write_bytes(b"old")
    dest.chmod(0o664)
    with umask(0o077):
        src.write_bytes(b"new")
    assert mode(src) == 0o600
    atomic.replace_from(src, dest)
    assert mode(dest) == 0o664
    fresh = tmp_path / "fresh"
    with umask(0o077):
        (tmp_path / "part2").write_bytes(b"x")
    atomic.replace_from(tmp_path / "part2", fresh)
    assert mode(fresh) == 0o600                                                      # a new name: what the part was made with
