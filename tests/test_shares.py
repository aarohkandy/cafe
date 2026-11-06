"""cafe.pm.shares: the test files split into K shares for bin/proot_suite.sh."""
import pathlib
import runpy
import sys

import pytest

from cafe.pm import audit, shares

JUNIT = '<testsuites><testsuite>{}</testsuite></testsuites>'


def junit(path, rows):
    """A junit file with one testcase per (classname, seconds)."""
    path.write_text(JUNIT.format("".join(f'<testcase classname="{c}" name="t" time="{s}"/>' for c, s in rows)))
    return path


def tree(tmp_path, sizes):
    """tests/<name> files of the given sizes, and a subfolder with one more, one fixture that is no test, and bytecode."""
    (tmp_path / "tests" / "sub").mkdir(parents=True)
    (tmp_path / "tests" / "__pycache__").mkdir()
    for n, size in sizes.items():
        (tmp_path / "tests" / n).write_text("#" * size)
    (tmp_path / "tests" / "conftest.py").write_text("")
    (tmp_path / "tests" / "__pycache__" / "test_cached.py").write_text("")
    return tmp_path


def test_the_test_files_are_those_pytest_collects_sorted(tmp_path):
    root = tree(tmp_path, {"test_b.py": 1, "test_a.py": 1})
    (root / "tests" / "sub" / "test_c.py").write_text("")
    assert shares.test_files(root) == ["tests/sub/test_c.py", "tests/test_a.py", "tests/test_b.py"]
    assert shares.test_files(pathlib.Path(audit.ROOT)) and all(f.startswith("tests/test_") for f in shares.test_files(audit.ROOT))


def test_seconds_are_summed_per_file_a_class_counts_for_its_module_and_a_later_junit_replaces_an_earlier(tmp_path):
    files = ["tests/test_a.py", "tests/test_b.py"]
    first = junit(tmp_path / "1.xml", [("tests.test_a", 1.5), ("tests.test_a.TestX", 2.0), ("tests.test_b", 7), ("tests.gone", 9), ("", 4)])
    later = junit(tmp_path / "2.xml", [("tests.test_b", 3), ("tests.test_b", 1)])
    assert shares.file_seconds([first], files) == {"tests/test_a.py": 3.5, "tests/test_b.py": 7.0}
    assert shares.file_seconds([first, later], files) == {"tests/test_a.py": 3.5, "tests/test_b.py": 4.0}


def test_a_file_the_junit_does_not_know_weighs_its_size_at_the_rate_of_the_known_ones(tmp_path):
    root = tree(tmp_path, {"test_a.py": 100, "test_new.py": 50})
    w = shares.weights(["tests/test_a.py", "tests/test_new.py"], {"tests/test_a.py": 10.0}, root)
    assert w == {"tests/test_a.py": 10.0, "tests/test_new.py": 5.0}
    assert shares.weights(["tests/test_a.py", "tests/test_new.py"], {}, root) == {"tests/test_a.py": 100, "tests/test_new.py": 50}        # no junit: size alone
    free = shares.weights(["tests/test_a.py", "tests/test_new.py"], {"tests/test_a.py": 0.0}, root)
    assert free["tests/test_new.py"] == 50                                   # a rate of 0 must not make a file free


def test_split_puts_every_file_in_exactly_one_share_heaviest_first_into_the_lightest():
    w = {"a": 9.0, "b": 8.0, "c": 5.0, "d": 4.0, "e": 3.0, "f": 1.0}
    got = shares.split(w, 2)
    assert sorted(f for s in got for f in s) == sorted(w) and got == [["a", "d", "e"], ["b", "c", "f"]]
    assert abs(sum(w[f] for f in got[0]) - sum(w[f] for f in got[1])) <= 2
    assert shares.split({"x": 1.0, "y": 1.0}, 2) == [["x"], ["y"]] and shares.split(w, 1) == [sorted(w)]          # ties by name; one share is everything
    for k in (0, 7):
        with pytest.raises(ValueError, match="shares for 6 test files"):
            shares.split(w, k)                                               # an empty share would make pytest collect all of tests/


def test_main_writes_the_argument_files_with_the_serial_tests_deselected_and_dropped_from_a_larger_k(tmp_path, capsys):
    root = tree(tmp_path, {"test_a.py": 10, "test_b.py": 20, "test_c.py": 30})
    out = tmp_path / "out"
    j = junit(tmp_path / "j.xml", [("tests.test_a", 5), ("tests.test_b", 1), ("tests.test_c", 1)])
    assert shares.main(["3", str(out), str(j)], root) == 0
    assert sorted(p.name for p in out.iterdir()) == ["s1.args", "s2.args", "s3.args", "serial.args"]
    deselects = "".join(f"--deselect={t}\n" for t in audit.SERIAL_TESTS)
    assert (out / "s1.args").read_text() == "tests/test_a.py\n" + deselects
    assert (out / "serial.args").read_text() == "".join(f"{t}\n" for t in audit.SERIAL_TESTS)
    assert "s1: 1 files, planned 5 s" in capsys.readouterr().out
    assert shares.main(["2", str(out)], root) == 0                          # the s3 of the larger K is gone, not left to be run twice
    assert sorted(p.name for p in out.iterdir()) == ["s1.args", "s2.args", "serial.args"]
    every = [l for n in ("s1", "s2") for l in (out / f"{n}.args").read_text().splitlines() if not l.startswith("--")]
    assert sorted(every) == ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"]


def test_main_refuses_a_k_that_is_not_a_number_and_runs_as_a_script(tmp_path, monkeypatch, capsys):
    assert shares.main(["x", str(tmp_path)]) == 2 and shares.main([]) == 2 and "python -m cafe.pm.shares" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["shares", "2", str(tmp_path / "o")])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm.shares", run_name="__main__")
    assert e.value.code == 0 and (tmp_path / "o" / "s2.args").is_file()
