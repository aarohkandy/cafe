"""cafe.pm.ledger: a stage proves what it read, ran and wrote; a tampered output or a failed check is caught."""
import datetime as dt
import json
import pathlib
import subprocess

import numpy as np
import pytest

from cafe.pm import ledger
from cafe.pm.ledger import Ledger, StageFailed, done


def run_stage(tmp_path, name="stage1", cfg="h1", ok=True, data=b"payload"):
    out = tmp_path / "out.bin"
    out.write_bytes(data)
    with Ledger(tmp_path, name, cfg) as L:
        L.check("fine", ok, value=1.0, limit=2.0)
        L.output(out)
    return out


def test_ledger_records_inputs_seeds_checks_notes_and_hashes_outputs(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("abc")
    out = tmp_path / "out.bin"
    out.write_bytes(b"xyz")
    with Ledger(tmp_path, "stage1", "cfg") as L:
        L.input(src, kind="file")
        L.input("https://example.org/f.nc", sha="deadbeef", kind="remote")
        L.input("https://example.org/g.nc")
        L.seed("lhs", 1234.0)
        assert L.check("lhs_stratified", True, value=3, limit=4, note="n") is True
        L.note("hello")
        L.output(out)
        assert L.ok
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["ok"] is True and d["error"] is None and d["config_hash"] == "cfg" and d["seeds"] == {"lhs": 1234}
    assert d["inputs"][0]["sha256"] == ledger.sha256(src) and d["inputs"][0]["kind"] == "file"
    assert d["inputs"][1]["sha256"] == "deadbeef" and d["inputs"][2]["sha256"] is None
    assert d["checks"] == [dict(name="lhs_stratified", ok=True, value=3, limit=4, note="n")] and d["notes"] == ["hello"]
    assert [o["path"] for o in d["outputs"]] == [str(out)] and d["outputs"][0]["sha256"] == ledger.sha256(out)
    assert d["wall_s"] >= 0 and {"python", "numpy"} <= set(d["versions"]) and "host" in d["machine"]
    assert not list((tmp_path / "checkpoints" / "stage1").glob("*.tmp"))


def test_a_registered_output_that_was_never_written_fails_the_stage_and_the_ledger_says_so(tmp_path):
    out = tmp_path / "out.bin"
    out.write_bytes(b"xyz")
    with pytest.raises(StageFailed, match="never written"):
        with Ledger(tmp_path, "stage1", "cfg") as L:
            L.output(out)
            L.output(tmp_path / "never_written.bin")
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["ok"] is False and "never_written.bin" in d["error"]
    assert [(pathlib.Path(o["path"]).name, o["sha256"] is None) for o in d["outputs"]] == [("out.bin", False), ("never_written.bin", True)]
    assert done(tmp_path, "stage1", "cfg") is None


def test_a_missing_output_does_not_hide_the_exception_that_ended_the_stage(tmp_path):
    with pytest.raises(KeyError):
        with Ledger(tmp_path, "stage1", "cfg") as L:
            L.output(tmp_path / "never_written.bin")
            raise KeyError("boom")
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["error"] == "KeyError: 'boom'" and d["ok"] is False


def test_every_ledger_carries_the_dirty_flag_and_the_code_digest(tmp_path):
    with Ledger(tmp_path, "stage1", "cfg", "d" * 64) as L:
        L.check("fine", True)
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["code_digest"] == "d" * 64 and d["git_dirty"] in (True, False, None)
    with Ledger(tmp_path, "stage2", "cfg") as L:
        pass
    assert json.loads((tmp_path / "checkpoints" / "stage2" / "ledger.json").read_text())["code_digest"] is None


def test_git_dirty_reads_the_working_tree_then_the_environment(monkeypatch, tmp_path):
    def status(out, rc=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, rc, stdout=out, stderr="")
    monkeypatch.setattr(ledger.subprocess, "run", status(" M cafe/pm/pipeline.py\n"))
    assert ledger.git_dirty() is True
    monkeypatch.setattr(ledger.subprocess, "run", status(""))
    assert ledger.git_dirty() is False
    monkeypatch.setenv("CAFE_GIT_DIRTY", "1")
    assert ledger.git_dirty() is False                                               # a real checkout wins over the variable
    monkeypatch.setattr(ledger.subprocess, "run", status("", rc=128))                 # a copy without .git: what pm.sh passed in
    assert ledger.git_dirty() is True
    monkeypatch.setenv("CAFE_GIT_DIRTY", "0")
    assert ledger.git_dirty() is False
    monkeypatch.setenv("CAFE_GIT_DIRTY", "maybe")
    assert ledger.git_dirty() is None
    monkeypatch.delenv("CAFE_GIT_DIRTY")
    assert ledger.git_dirty() is None

    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(ledger.subprocess, "run", no_git)
    monkeypatch.setenv("CAFE_GIT_DIRTY", "1")
    assert ledger.git_dirty() is True


def test_done_returns_the_ledger_only_for_a_clean_unchanged_stage(tmp_path):
    assert done(tmp_path, "stage1", "h1") is None
    run_stage(tmp_path)
    assert done(tmp_path, "stage1", "h1")["config_hash"] == "h1"
    assert done(tmp_path, "stage1", "other_config") is None


def test_a_tampered_output_breaks_done(tmp_path):
    out = run_stage(tmp_path)
    assert done(tmp_path, "stage1", "h1") is not None
    out.write_bytes(b"payloaD")
    assert done(tmp_path, "stage1", "h1") is None


def test_a_changed_file_input_breaks_done_but_a_remote_or_unhashed_one_does_not(tmp_path):
    src = tmp_path / "in.txt"
    src.write_text("abc")
    with Ledger(tmp_path, "stage1", "h1") as L:
        L.input(src)
        L.input("https://example.org/f.nc", sha="deadbeef")
        L.input(tmp_path / "not_there.txt")
    assert done(tmp_path, "stage1", "h1") is not None
    src.write_text("abd")
    assert done(tmp_path, "stage1", "h1") is None


def test_a_deleted_output_breaks_done(tmp_path):
    out = run_stage(tmp_path)
    out.unlink()
    assert done(tmp_path, "stage1", "h1") is None


def test_the_failure_message_carries_the_notes_of_the_first_three_failed_checks_and_the_count_of_the_rest(tmp_path):
    """Round 4 M-22: the message used to list bare check names; the actionable text (what to run) was only in the ledger json."""
    with pytest.raises(StageFailed) as e:
        with Ledger(tmp_path, "ingest", "h1") as L:
            L.check("fine", True, note="not shown")
            for n in "abcde":
                L.check(f"{n}_present", False, note=f"{n} is not cached: run `fetch`" if n != "b" else "")
    msg = str(e.value)
    first = "a_present: a is not cached: run `fetch`; b_present; c_present: c is not cached: run `fetch`"
    assert msg.startswith(f"stage ingest: self-checks failed: {first} and 2 more (ledger: ")
    assert msg.endswith(f"{tmp_path / 'checkpoints' / 'ingest' / 'ledger.json'})") and "not shown" not in msg and "d_present" not in msg


def test_failed_check_raises_stagefailed_and_still_writes_the_ledger(tmp_path):
    with pytest.raises(StageFailed, match=r"stage stage1: self-checks failed: bad \(ledger: .*ledger\.json\)"):
        with Ledger(tmp_path, "stage1", "h1") as L:
            L.check("good", True)
            assert L.check("bad", False, value=5, limit=1) is False
            assert not L.ok
    p = tmp_path / "checkpoints" / "stage1" / "ledger.json"
    d = json.loads(p.read_text())
    assert d["ok"] is False and d["error"] is None and [c["name"] for c in d["checks"] if not c["ok"]] == ["bad"]
    assert done(tmp_path, "stage1", "h1") is None


def test_an_exception_in_the_stage_is_recorded_and_propagates(tmp_path):
    with pytest.raises(ValueError, match="boom"):
        with Ledger(tmp_path, "stage1", "h1") as L:
            L.check("fine", True)
            raise ValueError("boom")
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["ok"] is False and d["error"] == "ValueError: boom"
    assert done(tmp_path, "stage1", "h1") is None


def test_ledger_serialises_arrays_datetimes_and_other_objects(tmp_path):
    when = dt.datetime(2023, 3, 1, 12, tzinfo=dt.timezone.utc)
    with Ledger(tmp_path, "stage1", "h1") as L:
        L.check("arr", True, value=np.array([1.0, 2.0]), limit=when, note=object.__name__)
        L.note(str(when))
        L.d["extra"] = {1, 2}
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["checks"][0]["value"] == [1.0, 2.0] and d["checks"][0]["limit"] == when.isoformat() and d["extra"] == "{1, 2}"


def test_jsonable_branches():
    assert ledger._jsonable(np.arange(2)) == [0, 1]
    assert ledger._jsonable(dt.date(2023, 3, 1)) == "2023-03-01"
    assert ledger._jsonable(object).startswith("<class")


def test_git_sha_real_and_when_git_is_missing(monkeypatch):
    real = ledger.git_sha()
    assert real == "none" or len(real) == 40

    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(ledger.subprocess, "run", no_git)
    monkeypatch.delenv("CAFE_GIT_SHA", raising=False)
    assert ledger.git_sha() == "none"
    monkeypatch.setenv("CAFE_GIT_SHA", "abc123")
    assert ledger.git_sha() == "abc123"
    monkeypatch.setattr(ledger.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 128, stdout="", stderr="not a repo"))
    assert ledger.git_sha() == "abc123"                                            # a copy without .git: the sha it was synced from
    monkeypatch.delenv("CAFE_GIT_SHA")
    assert ledger.git_sha() == "none"


def test_versions_reports_missing_libraries_as_none_and_unversioned_as_question_mark(monkeypatch):
    monkeypatch.setattr(ledger, "LIBS", ["numpy", "definitely_not_installed_xyz", "colorsys"])
    v = ledger.versions()
    assert v["numpy"] == np.__version__ and v["definitely_not_installed_xyz"] is None and v["colorsys"] == "?"


def test_versions_falls_back_to_the_installed_distribution_for_a_library_without_a_version_attribute(monkeypatch):
    seen = []

    def meta(name):
        seen.append(name)
        if name == "gone":
            raise ledger.importlib.metadata.PackageNotFoundError(name)
        return "9.9.9"
    monkeypatch.setattr(ledger.importlib.metadata, "version", meta)
    monkeypatch.setattr(ledger, "DIST", {"colorsys": "color-dist", "string": "gone"})
    monkeypatch.setattr(ledger, "LIBS", ["numpy", "colorsys", "string", "keyword"])
    v = ledger.versions()
    assert v["numpy"] == np.__version__ and v["colorsys"] == "9.9.9" and v["string"] == "?" and v["keyword"] == "9.9.9"
    assert seen == ["color-dist", "gone", "keyword"]


def test_machine_reads_the_bench_block_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    assert ledger.machine()["bench_id"] is None
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "throughput.json").write_text(json.dumps({"machine": {"id": "az_serv", "measured": "2026-10-29"}}))
    m = ledger.machine()
    assert m["bench_id"] == "az_serv" and m["bench_measured"] == "2026-10-29" and m["cpus"] >= 1
    (tmp_path / "config" / "throughput.json").write_text("{}")
    assert ledger.machine()["bench_id"] is None


def test_git_sha_falls_back_to_the_environment_when_the_copy_has_no_git(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger, "ROOT", tmp_path)                                  # not a repository: git prints nothing
    monkeypatch.setenv("CAFE_GIT_SHA", "abc123")
    assert ledger.git_sha() == "abc123"
    monkeypatch.delenv("CAFE_GIT_SHA")
    assert ledger.git_sha() == "none"


# ---- review round 2, M-30: strict JSON

def reject(name):
    raise ValueError(f"non-standard JSON constant {name}")


def test_a_ledger_with_nan_and_infinite_values_is_strict_json(tmp_path):
    with Ledger(tmp_path, "stage1", "h1") as L:
        L.check("unbounded", True, value=float("nan"), limit=float("inf"), note="n")
        L.check("array", True, value=np.array([1.0, np.nan, -np.inf]), limit=np.float32("nan"))
        L.d["extra"] = {"nested": [float("inf"), {"x": np.float64("nan")}], "n": np.int64(3), "ok": np.bool_(True)}
    text = (tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text()
    assert "NaN" not in text and "Infinity" not in text
    d = json.loads(text, parse_constant=reject)                                                       # what jq and JSON.parse accept
    assert d["checks"][0]["value"] is None and d["checks"][0]["limit"] is None
    assert d["checks"][1]["value"] == [1.0, None, None] and d["checks"][1]["limit"] is None
    assert d["extra"] == {"nested": [None, {"x": None}], "n": 3, "ok": True}


def test_clean_keeps_finite_numbers_strings_and_none_and_makes_numpy_and_dates_plain():
    assert ledger.clean({"a": 1, "b": 1.5, "c": "s", "d": None, "e": True, "f": (1, 2)}) == {"a": 1, "b": 1.5, "c": "s", "d": None, "e": True, "f": [1, 2]}
    assert ledger.clean([np.arange(2), dt.date(2023, 3, 1), float("-inf")]) == [[0, 1], "2023-03-01", None]
