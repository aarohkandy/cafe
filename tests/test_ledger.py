"""cafe.pm.ledger: a stage proves what it read, ran and wrote; a tampered output or a failed check is caught."""
import datetime as dt
import json
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
        L.output(tmp_path / "never_written.bin")
        assert L.ok
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["ok"] is True and d["error"] is None and d["config_hash"] == "cfg" and d["seeds"] == {"lhs": 1234}
    assert d["inputs"][0]["sha256"] == ledger.sha256(src) and d["inputs"][0]["kind"] == "file"
    assert d["inputs"][1]["sha256"] == "deadbeef" and d["inputs"][2]["sha256"] is None
    assert d["checks"] == [dict(name="lhs_stratified", ok=True, value=3, limit=4, note="n")] and d["notes"] == ["hello"]
    assert [o["path"] for o in d["outputs"]] == [str(out)] and d["outputs"][0]["sha256"] == ledger.sha256(out)     # the unwritten output is dropped
    assert d["wall_s"] >= 0 and {"python", "numpy"} <= set(d["versions"]) and "host" in d["machine"]
    assert not list((tmp_path / "checkpoints" / "stage1").glob("*.tmp"))


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


def test_a_deleted_output_breaks_done(tmp_path):
    out = run_stage(tmp_path)
    out.unlink()
    assert done(tmp_path, "stage1", "h1") is None


def test_failed_check_raises_stagefailed_and_still_writes_the_ledger(tmp_path):
    with pytest.raises(StageFailed, match=r"stage stage1: self-checks failed: \['bad'\]"):
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
    assert ledger.git_sha() == "none"


def test_versions_reports_missing_libraries_as_none_and_unversioned_as_question_mark(monkeypatch):
    monkeypatch.setattr(ledger, "LIBS", ["numpy", "definitely_not_installed_xyz", "colorsys"])
    v = ledger.versions()
    assert v["numpy"] == np.__version__ and v["definitely_not_installed_xyz"] is None and v["colorsys"] == "?"


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
