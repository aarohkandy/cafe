"""Round 20, batch D (M-7 and the SEb test of M-10): `python -m cafe._seed` meets a deeply nested JSON as `NOT seeded <file> - <reason>`, not a RecursionError;
an external result must hold all six directions, each with a `gci` (the Hangar reads both: `vehicle.py` calls the drag table "cfd" for one direction in
six, `_site_data.py` reads `v["gci"]`); a `force`, `moment` or `viscous` of four numbers is refused (the mutant `len(v) >= 3` survived round 19's tests).
The real CFD results in `tests/fixtures/cfd_real` are still accepted.
No test runs OpenFOAM and none touches the shared CFD cache: every `main` call is under a private `CACHE`."""
import json
import pathlib
import shutil
import tempfile

import pytest

from cafe import _seed, cfd
from tests.test_round19_d import cached_files, external, put

REAL = pathlib.Path(__file__).parent / "fixtures" / "cfd_real"
FILES = dict(q1="quad.external.json", t1="torpedo.external.json", w1="wigley.surface.json")


@pytest.fixture
def work(tmp_path, monkeypatch):
    """A private `$CAFE_WORK` with a private cache and a private temporary directory (the shared cache on orca is never named)."""
    w = tmp_path / "work"
    monkeypatch.setattr(cfd, "CACHE", w / "cfdcache")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return w


def not_seeded(work, capsys, f):
    """`main` ended 1 with `NOT seeded <f> - <reason>` and "nothing was seeded", and wrote no cache entry (even for the good files beside it)."""
    assert _seed.main() == 1
    cap = capsys.readouterr()
    assert f"NOT seeded {f} - " in cap.out and "nothing was seeded" in cap.err
    assert "Traceback" not in cap.out + cap.err and cached_files(work) == [] and not (work / "cfdcache").exists()
    return cap.out


def test_r20_m7_a_deeply_nested_file_is_not_seeded_not_a_recursion_error(work, capsys):
    """`[` x 100000 then `]` x 100000: `json.loads` raised RecursionError, which `except (OSError, ValueError)` let through as a traceback."""
    put(work, "q1", "quad.external.json", external())
    f = put(work, "t1", "torpedo.external.json", "[" * 100000 + "]" * 100000)
    out = not_seeded(work, capsys, f)
    assert "recursion" in out and "seeded quad" not in out


def test_r20_m7_a_nested_object_file_is_not_seeded_either(work, capsys):
    f = put(work, "q1", "quad.external.json", '{"a":' * 100000 + "1" + "}" * 100000)
    not_seeded(work, capsys, f)


@pytest.mark.parametrize("keep", [("+x",), ("-x", "+y", "-y", "+z", "-z"), ("+x", "-x", "+y", "-y", "+z"), ("-z",)])
def test_r20_m7_a_result_with_some_of_the_six_directions_is_not_seeded(work, capsys, keep):
    """One direction in six was `seeded` (rc 0) and then called "cfd" by the Hangar for the whole drag table."""
    r = external()
    r["dirs"] = {d: r["dirs"][d] for d in keep}
    f = put(work, "q1", "quad.external.json", r)
    out = not_seeded(work, capsys, f)
    assert "all six directions" in out


def test_r20_m7_a_result_with_a_direction_beyond_the_six_is_not_seeded(work, capsys):
    """`vehicle.py` looks every label of `dirs` up in `DIRS`: a seventh (the angle labels of the other study) is a KeyError there."""
    r = external()
    r["dirs"]["x+y15"] = r["dirs"]["+x"]
    f = put(work, "q1", "quad.external.json", r)
    not_seeded(work, capsys, f)


@pytest.mark.parametrize("gci", ["absent", None, "0.1", True, [0.1], {"v": 1}])
def test_r20_m7_a_direction_without_a_number_in_gci_is_not_seeded(work, capsys, gci):
    """`_site_data.py` reads `v["gci"]` of every direction (a KeyError without it); `vehicle.py` reads a missing one as 0.0, a perfect grid."""
    r = external()
    if gci == "absent":
        del r["dirs"]["-z"]["gci"]
    else:
        r["dirs"]["-z"]["gci"] = gci
    f = put(work, "q1", "quad.external.json", r)
    out = not_seeded(work, capsys, f)
    assert "direction -z has no number in `gci`" in out


@pytest.mark.parametrize("gci", [0, 0.0, 3, 0.05, float("nan"), float("inf")])
def test_r20_m7_a_gci_that_is_a_number_is_seeded_nan_and_inf_included(work, capsys, gci):
    """`cfd.gci` gives NaN where a direction has no index (a zero fine value) and the study's worst is inf then: a real file holds them, so the check refuses
    the type of `gci` and not its value (a finite-only check would have refused a result the code itself made)."""
    r = external()
    r["dirs"]["+z"]["gci"] = gci
    put(work, "q1", "quad.external.json", json.dumps(r))                                            # json.dumps writes NaN and Infinity, json.loads reads them
    assert _seed.main() == 0
    assert "seeded quad" in capsys.readouterr().out and len(cached_files(work)) == 1


@pytest.mark.parametrize("field", ["force", "moment", "viscous"])
@pytest.mark.parametrize("vec", [[1.0, 2.0, 3.0, 4.0], [1.0, 2.0], [], [1.0, 2.0, float("nan")]])
def test_r20_a4_a_vector_that_is_not_three_finite_numbers_is_not_seeded(work, capsys, field, vec):
    """SEb: `_vec` with `len(v) >= 3` kept a vector of four numbers (cached under the real key) and no test noticed;
    DECISIONS 1007 says three finite numbers."""
    r = external()
    r["dirs"]["+y"][field] = vec
    f = put(work, "q1", "quad.external.json", json.dumps(r))
    out = not_seeded(work, capsys, f)
    assert "direction +y has no `force`, `moment` and `viscous` of three numbers each" in out


def test_r20_m7_the_real_results_are_still_accepted_and_hold_what_the_check_now_asks(work, capsys):
    """The three results of real runs (`tests/fixtures/cfd_real`, copied from the cache on the worker): the two external ones hold all six
    directions, each with a finite `gci`, so the stricter check refuses nothing a real run made; all three seed end to end and a second run finds them there."""
    for run, name in FILES.items():
        (work / "runs" / run).mkdir(parents=True)
        shutil.copy(REAL / name, work / "runs" / run / name)
    for name in ("quad.external.json", "torpedo.external.json"):
        dirs = json.loads((REAL / name).read_text())["dirs"]
        assert set(dirs) == set(cfd.DIRS) and all(isinstance(v["gci"], float) and v["gci"] == v["gci"] for v in dirs.values())
    assert _seed.main() == 0
    out = capsys.readouterr().out
    assert out.count("seeded ") == 3 and "NOT seeded" not in out and len(cached_files(work)) == 3
    assert _seed.main() == 0 and capsys.readouterr().out.count("already there") == 3
