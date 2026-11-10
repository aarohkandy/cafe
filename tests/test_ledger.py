"""cafe.pm.ledger: a stage proves what it read, ran and wrote; a tampered output or a failed check is caught."""
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess

import numpy as np
import pytest

from cafe.pm import audit, ledger
from cafe.pm.env.remote import sha256
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


def test_l0_machine_records_the_other_machine_warning_where_the_stage_ran(monkeypatch, tmp_path):
    """The warning is judged where the stage runs and kept in its ledger (the report reads it back): None without a bench block or when it matches."""
    from cafe.pm import budget
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    assert ledger.machine()["warning"] is None
    (tmp_path / "config").mkdir()
    block = {"machine": {"id": "bench", "cpus": 999, "cpu": budget.cpu_model(), "measured": "2026-10-29"}}
    (tmp_path / "config" / "throughput.json").write_text(json.dumps(block))
    w = ledger.machine()["warning"]
    assert w == budget.machine_warning(block) and f"{os.cpu_count()} CPUs, not 999" in w
    block["machine"]["cpus"] = os.cpu_count()
    (tmp_path / "config" / "throughput.json").write_text(json.dumps(block))
    assert ledger.machine()["warning"] is None
    assert Ledger(tmp_path, "s", "h").d["machine"]["warning"] is None


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


def test_machine_records_the_stage_1_workers_beside_the_host_cpu_count(monkeypatch, tmp_path):
    """Round 5 M-15: `cpus` is the host's; the plan was sized on the workers (CAFE_WORKERS, or the CPUs the container may use)."""
    from cafe.pm import par
    monkeypatch.setenv("CAFE_WORKERS", "3")
    m = ledger.machine()
    assert m["workers"] == 3 and m["cpus"] >= 1
    with par.limit(2):
        assert Ledger(tmp_path, "s", "h").d["machine"]["workers"] == 2                                  # what the run's pool has, not what the env var says


# ---- review round 8: M-4 (the contents of a directory input), M-23 (an unreadable ledger), M-35 (Bellhop and more libraries in the versions)

def test_r8_m4_a_changed_or_damaged_directory_input_breaks_done(tmp_path):
    """The ocean store is a directory: `done` re-hashed only file inputs, so a value edited in it, a chunk deleted from it or a file added was 'up to date'."""
    store = tmp_path / "ocean.zarr"
    (store / "water_u" / "c").mkdir(parents=True)
    (store / "water_u" / "c" / "0").write_bytes(b"\x01\x02\x03")
    (store / "zarr.json").write_text('{"attributes": {"manifest_sha256": "abc"}}')
    with Ledger(tmp_path, "ingest", "h1") as L:
        L.input(store, sha="abc", tree=ledger.tree_sha256(store), kind="ocean store")
    d = done(tmp_path, "ingest", "h1")
    assert d is not None and d["inputs"][0]["tree_sha256"] == ledger.tree_sha256(store) and d["inputs"][0]["sha256"] == "abc"
    chunk = store / "water_u" / "c" / "0"
    for change, undo in ((lambda: chunk.write_bytes(b"\x01\x02\x04"), lambda: chunk.write_bytes(b"\x01\x02\x03")),
                         (lambda: chunk.unlink(), lambda: chunk.write_bytes(b"\x01\x02\x03")),
                         (lambda: (store / "extra").write_text("x"), lambda: (store / "extra").unlink())):
        change()
        assert done(tmp_path, "ingest", "h1") is None
        undo()
        assert done(tmp_path, "ingest", "h1") is not None


def test_r8_m4_a_directory_input_recorded_without_a_tree_hash_is_not_rehashed(tmp_path):
    """Ledgers written before round 8 hold the manifest hash only: their directories stay as they were."""
    store = tmp_path / "ocean.zarr"
    store.mkdir()
    with Ledger(tmp_path, "ingest", "h1") as L:
        L.input(store, sha="abc")
    assert "tree_sha256" not in json.loads((tmp_path / "checkpoints" / "ingest" / "ledger.json").read_text())["inputs"][0]
    (store / "new").write_text("x")
    assert done(tmp_path, "ingest", "h1") is not None


def test_r8_m23_a_truncated_or_garbage_ledger_is_a_stage_not_done_and_says_so(tmp_path, capsys):
    run_stage(tmp_path)
    p = tmp_path / "checkpoints" / "stage1" / "ledger.json"
    good = p.read_text()
    assert len(good) > 200 and done(tmp_path, "stage1", "h1") is not None
    for bad in (good[:200], "", "\x00\x00garbage", "[1, 2]", "null"):
        p.write_text(bad)
        assert done(tmp_path, "stage1", "h1") is None
        err = capsys.readouterr().err
        assert f"ledger {p} is unreadable" in err and "the stage runs again" in err
    p.write_text(good)
    assert done(tmp_path, "stage1", "h1") is not None and capsys.readouterr().err == ""


def test_r8_m35_the_versions_carry_bellhop_and_the_libraries_the_verdicts_depend_on(monkeypatch, tmp_path):
    from cafe.pm.physics import comms
    v = ledger.versions()
    for lib in ("pandas", "pyarrow", "arlpy", "yaml", "jsonschema", "netCDF4", "bellhop"):
        assert lib in v, lib
    assert v["pandas"] and v["yaml"]
    monkeypatch.setattr(comms, "_bellhop_dir", lambda: None)
    assert ledger.versions()["bellhop"] == "absent"
    (tmp_path / "bellhop.exe").write_bytes(b"one")
    monkeypatch.setattr(comms, "_bellhop_dir", lambda: str(tmp_path))
    assert ledger.versions()["bellhop"] == ledger.sha256(tmp_path / "bellhop.exe") != "absent"
    (tmp_path / "bellhop.exe").write_bytes(b"two")
    assert ledger.versions()["bellhop"] == ledger.sha256(tmp_path / "bellhop.exe")


# ---- review round 8, lead item L0: an input that was hashed and is gone

def test_r8_l0_a_deleted_hashed_input_breaks_done_but_a_url_and_an_unhashed_one_do_not(tmp_path):
    """done() checked an input only if it still existed, so a store or file removed entirely was 'up to date' and the stage was resumed on data that is gone."""
    store = tmp_path / "ocean.zarr"
    (store / "water_u" / "c").mkdir(parents=True)
    (store / "water_u" / "c" / "0").write_bytes(b"\x01")
    (store / "zarr.json").write_text('{"attributes": {"manifest_sha256": "abc"}}')
    src = tmp_path / "src.txt"
    src.write_text("v1")
    with Ledger(tmp_path, "ingest", "h1") as L:
        L.input(store, sha="abc", tree=ledger.tree_sha256(store), kind="ocean store")
        L.input(src)
        L.input("https://example.org/remote.nc", sha="b" * 64)         # the hash of the bytes extracted from a URL: no path to look for
        L.input(tmp_path / "never_there.txt")                          # recorded without a hash (it did not exist)
    assert done(tmp_path, "ingest", "h1") is not None
    src.unlink()
    assert done(tmp_path, "ingest", "h1") is None
    src.write_text("v1")
    assert done(tmp_path, "ingest", "h1") is not None
    shutil.rmtree(store)
    assert done(tmp_path, "ingest", "h1") is None
    assert ledger.hashed(dict(ref="s3://b/k", sha256="x")) is False and ledger.hashed(dict(ref="/x", sha256=None)) is False
    assert ledger.hashed(dict(ref="/x", tree_sha256="t")) is True


def test_r8_l0_a_damaged_throughput_file_stops_the_ledger_with_the_config_error_not_a_json_traceback(tmp_path, monkeypatch):
    """`machine()` (every Ledger's header) read config/throughput.json with a bare json.loads, the file budget.throughput now guards."""
    from cafe.pm import config
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    f = root / "config" / "throughput.json"
    monkeypatch.setattr(ledger, "ROOT", root)
    f.write_text('{"machine": {"id": "x"')
    with pytest.raises(config.ConfigError, match=r"throughput.json: not a JSON object .*make bench"):
        ledger.machine()
    f.write_text('{"machine": {"id": "m1", "measured": "d"}}')
    assert ledger.machine()["bench_id"] == "m1"


# ---- review round 9: M-19 (one resolver for a recorded path, used by audit and done), M-16 (report --run records what it rewrote)

def laid_out(root, name):
    """A run directory `root/name` whose report stage ledger records its output as the absolute path it was written to."""
    run = root / name
    out = run / "stage3" / "windows" / "w.json"
    out.parent.mkdir(parents=True)
    out.write_text("v1")
    with Ledger(run, "stage3", "h1") as L:
        L.output(out)
    return run, out


def test_r9_m19_resolve_rebases_on_the_run_layout_longest_tail_first(tmp_path):
    run = tmp_path / "now"
    (run / "stage3" / "windows").mkdir(parents=True)
    (run / "windows").mkdir()
    (run / "stage3" / "windows" / "x").write_text("a")
    (run / "windows" / "x").write_text("b")
    roots = {("/", "data", "runs", "q9")}
    assert ledger.resolve("/data/runs/q9/stage3/windows/x", run, roots) == run / "stage3" / "windows" / "x"          # not windows/x
    assert ledger.resolve("/data/runs/q9/windows/x", run, roots) == run / "windows" / "x"
    assert ledger.resolve("/data/runs/now/windows/x", run, roots) == run / "windows" / "x"                           # the name first
    assert ledger.resolve("/data/runs/q9/stage3/windows/gone", run, roots) == run / "stage3" / "windows" / "gone"   # nothing there: in the run (L1)
    assert ledger.resolve("/app/config/mission.yaml", run, roots) == pathlib.Path("/app/config/mission.yaml")       # outside the run


def test_r9_l_resolve_leaves_a_path_outside_the_run_alone_even_through_a_directory_named_like_a_stage(tmp_path):
    run = tmp_path / "quick"
    (run / "report").mkdir(parents=True)
    (run / "report" / "index.html").write_text("the run's")
    (run / "secret").write_text("x")
    roots = ledger.run_roots(dict(outputs=[dict(path="/data/runs/q9/report/index.html"), dict(path="/data/runs/q9/checkpoints/report/ledger.json")]))
    assert ledger.resolve("/data/runs/q9/report/index.html", run, roots) == run / "report" / "index.html"
    ext = pathlib.Path("/data/cache/report/index.html")
    assert ledger.resolve(ext, run, roots) == ext                                                     # was <run>/report/index.html
    assert ledger.resolve(ext, run, set()) == ext
    assert ledger.resolve("/a/report/../secret", run, {("/", "a")}) == pathlib.Path("/a/report/../secret")      # never out of the run by `..`
    assert ledger.resolve("/data/runs/q9/report/../report/index.html", run, roots) == pathlib.Path("/data/runs/q9/report/../report/index.html")


def test_r9_m19_done_reads_a_copy_under_another_name_from_its_own_files(tmp_path):
    run, out = laid_out(tmp_path, "q9")
    copy = tmp_path / "quick"
    shutil.copytree(run, copy)
    assert done(copy, "stage3", "h1") is not None
    (copy / "stage3" / "windows" / "w.json").write_text("v2")                      # the original is intact at the recorded path
    assert done(copy, "stage3", "h1") is None                                      # was the original's hash: the stage was skipped on changed output
    (copy / "stage3" / "windows" / "w.json").write_text("v1")
    shutil.rmtree(run)
    assert done(copy, "stage3", "h1") is not None                                  # was None: the recorded path was gone


def test_r9_m16_rerecord_takes_the_new_hash_adds_a_note_and_leaves_the_checks(tmp_path):
    run, out = laid_out(tmp_path, "q9")
    before = json.loads((run / "checkpoints" / "stage3" / "ledger.json").read_text())
    out.write_text("v2")
    extra = run / "stage3" / "extra.json"
    extra.write_text("new")
    assert ledger.rerecord(run, "stage3", [out, extra], "dig1") is True
    d = json.loads((run / "checkpoints" / "stage3" / "ledger.json").read_text())
    assert [(o["path"], o["sha256"]) for o in d["outputs"]] == [(str(out), ledger.sha256(out)), (str(extra), ledger.sha256(extra))]
    assert d["notes"] == [f"re-rendered by report --run (git_sha {ledger.git_sha()}, code_digest dig1)"]
    assert (d["checks"], d["config_hash"], d["git_sha"], d["ok"]) == (before["checks"], before["config_hash"], before["git_sha"], True)
    assert done(run, "stage3", "h1") is not None
    assert ledger.rerecord(run, "stage1", [out], None) is False                    # no ledger for that stage: nothing to update


def test_l1_machine_records_a_warning_for_an_entry_of_another_machine_when_the_machine_block_matches(monkeypatch, tmp_path):
    from cafe.pm import budget
    monkeypatch.setattr(ledger, "ROOT", tmp_path)
    (tmp_path / "config").mkdir()
    here = dict(cpus=os.cpu_count(), cpu=budget.cpu_model())
    thr = {"machine": dict(id="bench", measured="2026-11-05", **here), "jax-lbm-d3q19-cpu": dict(cpus=999, cpu=here["cpu"], measured="2026-10-28")}
    (tmp_path / "config" / "throughput.json").write_text(json.dumps(thr))
    w = ledger.machine()["warning"]
    assert w == budget.machine_warning(thr) and "jax-lbm-d3q19-cpu (999 CPUs" in w


def test_l1_resolve_reports_a_lost_output_of_a_copy_in_the_copy_not_at_the_original(tmp_path):
    """`cp -r runs/q9 runs/q9b` and a deleted output: the recorded path is the original's file, which exists with the right hash, so `done` returned the
    ledger and the audit found nothing missing."""
    run, out = laid_out(tmp_path, "q9")
    copy = tmp_path / "q9b"
    shutil.copytree(run, copy)
    lost = copy / "stage3" / "windows" / "w.json"
    lost.unlink()
    roots = ledger.run_roots(json.loads((copy / "checkpoints" / "stage3" / "ledger.json").read_text()))
    assert ledger.resolve(out, copy, roots) == lost                                                  # was the original's file
    assert done(copy, "stage3", "h1") is None and done(run, "stage3", "h1") is not None
    probs = audit.ledger_problems(copy)
    assert any("stage stage3: output" in p and str(lost) in p and "is missing" in p for p in probs)
    ext = pathlib.Path("/data/cache/stage3/x")
    assert ledger.resolve(ext, copy, roots) == ext                                                   # outside the run's places: as recorded


def test_p32_a_snapshot_is_the_input_the_stage_read_and_a_resume_ignores_what_a_later_run_did_to_the_shared_file(tmp_path):
    """A shared manifest rewritten by a later run made `done` rerun every earlier stage that had hashed it; the copy in the run is what is hashed."""
    shared = tmp_path / "cache" / "manifest.json"
    shared.parent.mkdir()
    shared.write_text('{"parts": {"a": "1"}}')
    run = tmp_path / "run"
    dest = run / "ingest" / "m.json"
    dest.parent.mkdir(parents=True)
    out = run / "ingest" / "o.json"
    out.write_text("o")
    with Ledger(run, "ingest", "h") as L:
        L.snapshot(shared, dest, kind="cache manifest")
        L.output(out)
    d = json.loads((run / "checkpoints" / "ingest" / "ledger.json").read_text())
    assert d["inputs"] == [dict(ref=str(dest), sha256=sha256(shared), shared=str(shared), kind="cache manifest")]
    assert dest.read_bytes() == shared.read_bytes() and not list(dest.parent.glob("*.part"))
    shared.write_text('{"parts": {"a": "1", "b": "2"}}')                                     # a later run grew the cache
    assert dest.read_text() == '{"parts": {"a": "1"}}'
    assert done(run, "ingest", "h") is not None                                              # was None with the shared file as the input
    dest.write_text("edited")
    assert done(run, "ingest", "h") is None


def test_p32_a_resume_notices_that_a_file_the_copy_names_changed_or_the_cache_is_gone(tmp_path):
    """`done` hashed the copy only, so a TAO file replaced after the run (the manifest rewritten with its new hash) still resumed the stale ingest."""
    tdir = tmp_path / "cache" / "s2"
    (tdir / "M").mkdir(parents=True)
    f = tdir / "M" / "w.nc"
    f.write_bytes(b"one")
    man = tdir / "manifest.json"
    man.write_text(json.dumps({"files": {"M/w.nc": {"sha256": sha256(f)}}}))
    run = tmp_path / "run"
    out = run / "ingest" / "o.json"
    out.parent.mkdir(parents=True)
    out.write_text("o")
    with Ledger(run, "ingest", "h") as L:
        L.snapshot(man, run / "ingest" / "m.json", kind="cache manifest")
        L.output(out)
    assert done(run, "ingest", "h") is not None
    (tdir / "M" / "new.nc").write_bytes(b"x")                                                # the cache grew: still done
    man.write_text(json.dumps({"files": {"M/w.nc": {"sha256": sha256(f)}, "M/new.nc": {"sha256": "x"}}}))
    assert done(run, "ingest", "h") is not None
    f.write_bytes(b"two")                                                                    # a file the run read was replaced, the manifest rewritten to match
    man.write_text(json.dumps({"files": {"M/w.nc": {"sha256": sha256(f)}}}))
    assert done(run, "ingest", "h") is None
    f.write_bytes(b"one")
    assert done(run, "ingest", "h") is not None
    shutil.rmtree(tdir)                                                                      # the cache directory is gone
    assert done(run, "ingest", "h") is None


# ---- look-ahead batch LB0, RC-1 sibling: a ledger that is valid JSON of the wrong shape

@pytest.mark.parametrize("edit", [lambda d: d.pop("outputs"), lambda d: d.pop("inputs"), lambda d: d.update(outputs=[{"sha256": "x"}]),
                                  lambda d: d.update(inputs=[{"sha256": "x"}]), lambda d: d.update(outputs="x"), lambda d: d.update(inputs=5)],
                         ids=["no_outputs", "no_inputs", "output_without_path", "input_without_ref", "outputs_a_string", "inputs_a_number"])
def test_lb0_a_ledger_of_the_wrong_shape_is_a_stage_not_done_and_says_so(tmp_path, capsys, edit):
    """`done` read `d["outputs"]` and `o["path"]` bare: a hand-edited or foreign ledger that is valid JSON ended `run` in a KeyError or TypeError, where
    one that is not JSON runs the stage again (M-23)."""
    run_stage(tmp_path)
    p = tmp_path / "checkpoints" / "stage1" / "ledger.json"
    good = json.loads(p.read_text())
    assert done(tmp_path, "stage1", "h1") is not None
    d = json.loads(json.dumps(good))
    edit(d)
    p.write_text(json.dumps(d))
    assert done(tmp_path, "stage1", "h1") is None
    assert f"ledger {p} is damaged or incomplete" in capsys.readouterr().err


# ---- review round 11, M-8 and M-21

def orca_run(tmp_path):
    """A run whose ingest read the orca part `hours/wrf_A.npz` and kept the copy of the cache manifest that names it; -> (run, cache dir, part, snapshot)."""
    cache = tmp_path / "cache" / "orca"
    (cache / "hours").mkdir(parents=True)
    part, man = cache / "hours" / "wrf_A.npz", cache / "manifest.json"
    part.write_bytes(b"what the run read")
    man.write_text(json.dumps({"parts": {part.name: sha256(part)}}))
    run = tmp_path / "run"
    out = run / "ingest" / "o.json"
    out.parent.mkdir(parents=True)
    out.write_text("o")
    snap = run / "ingest" / "orca_manifest.json"
    with Ledger(run, "ingest", "h") as L:
        L.snapshot(man, snap, kind="cache manifest")
        L.output(out)
    return run, cache, part, snap


def test_r11_m8_a_part_a_later_ingest_refetched_under_the_same_name_is_a_rewrite_and_a_hand_edit_is_a_change(tmp_path, capsys):
    """`_drop_stale_parts` unlinks the parts cut for another box or without a new 3-D hour and the ingest fetches them again: the earlier run's audit said
    'changed since the stage ran' (and the report opened with a red banner) for a cache doing what it does."""
    from cafe.pm.env import orca
    run, cache, part, snap = orca_run(tmp_path)
    man = cache / "manifest.json"
    orca._drop_stale_parts(cache, (-2.0, 2.0, 193.0, 197.0), set())                           # no cut.json: another box, every part goes
    assert not part.exists()
    part.write_bytes(b"refetched, other bytes")
    man.write_text(json.dumps({"parts": {part.name: sha256(part)}}))                         # the later ingest's manifest vouches for them
    copy = json.loads(snap.read_text())
    changes, rewrites = ledger.shared_diff(copy, cache)
    assert changes == [] and [r[0] for r in rewrites] == [part]
    assert ledger.shared_changes(copy, cache) and done(run, "ingest", "h") is None            # a resume still reads the part again
    assert audit._shared_problems("run", "ingest", snap, man, True) == []
    assert "refetched by a later ingest" in capsys.readouterr().err
    part.write_bytes(b"edited by hand")                                                     # the manifest does not vouch for this one
    changes, rewrites = ledger.shared_diff(copy, cache)
    assert [c[0] for c in changes] == [part] and rewrites == []
    (probs,) = audit._shared_problems("run", "ingest", snap, man, True)
    assert f"input {part} changed since the stage ran" in probs


def test_r11_m8_a_part_the_live_manifest_does_not_list_or_lists_with_the_old_sha_is_a_change(tmp_path):
    run, cache, part, snap = orca_run(tmp_path)
    copy = json.loads(snap.read_text())
    part.write_bytes(b"other bytes")
    for live in ({"parts": {}}, {"parts": {part.name: copy["parts"][part.name]}}, {}, None):
        (cache / "manifest.json").write_text(json.dumps(live))
        assert [c[0] for c in ledger.shared_diff(copy, cache)[0]] == [part], live
    (cache / "manifest.json").write_text("not json")
    assert [c[0] for c in ledger.shared_diff(copy, cache)[0]] == [part]


def test_r11_m21_a_run_that_read_orca_parts_only_is_not_resumed_once_the_cache_directory_is_gone(tmp_path):
    """A manifest copy naming only `parts` has nothing `shared_changes` reports for a missing directory: `done`'s own `is_dir()` is what stops the resume
    on a deleted store (DECISIONS 575)."""
    run, cache, part, snap = orca_run(tmp_path)
    assert "files" not in json.loads(snap.read_text()) and done(run, "ingest", "h") is not None
    shutil.rmtree(cache)
    assert ledger.shared_changes(json.loads(snap.read_text()), cache) == [] and done(run, "ingest", "h") is None


@pytest.mark.parametrize("body, kind", [("not json", "JSONDecodeError"), ("[1]", "AttributeError"), ('{"parts": 5}', "AttributeError")])
def test_r11_m25_a_copied_cache_manifest_that_is_not_a_manifest_is_a_stage_not_done_with_the_reason(tmp_path, capsys, body, kind):
    """`done` catches KeyError, TypeError, AttributeError and ValueError: a copy whose hash is the ledger's but that is not JSON (ValueError) or not a
    mapping (AttributeError) reaches `shared_changes`, and each of the two types has to be in the tuple."""
    run, cache, part, snap = orca_run(tmp_path)
    snap.write_text(body)
    with Ledger(run, "ingest", "h2") as L:
        L.input(snap, shared=str(cache / "manifest.json"))                       # hashed now: the copy is as the ledger has it
        L.output(run / "ingest" / "o.json")
    assert done(run, "ingest", "h2") is None
    err = capsys.readouterr().err
    assert "is damaged or incomplete (" in err and kind in err and "the stage runs again" in err


def test_r11_m9_snapshot_returns_the_parsed_copy_it_recorded(tmp_path):
    """The stage takes what it reads of a shared manifest from the copy it recorded, not from a second read of the shared file."""
    shared = tmp_path / "manifest.json"
    shared.write_text('{"parts": {"a": "1"}, "hours": 3}')
    run = tmp_path / "run"
    dest = run / "ingest" / "m.json"
    dest.parent.mkdir(parents=True)
    with Ledger(run, "ingest", "h") as L:
        got = L.snapshot(shared, dest, kind="cache manifest")
        shared.write_text('{"parts": {}, "hours": 99}')                                      # another run rewrites it right after
    assert got == {"parts": {"a": "1"}, "hours": 3} == json.loads(dest.read_text())


def test_r11_m2_a_report_stage_that_recorded_the_runs_mission_and_plan_is_not_done_once_either_changed(tmp_path):
    """The report stage hashes `mission.yaml` and `plan.json` by their bare names: a resume with another plan (the machine's memory, a different CPU
    count) reruns the report, which prints that plan, and reuses every other stage."""
    run = tmp_path / "run"
    (run / "report").mkdir(parents=True)
    (run / "mission.yaml").write_text("seed: 1\n")
    (run / "plan.json").write_text('{"workers": 2}')
    out = run / "report" / "index.html"
    out.write_text("<p>report</p>")
    with Ledger(run, "report", "h") as L:
        for n in ledger.RUN_ROOT_FILES:
            L.input(n, sha=sha256(run / n))
        L.output(out)
    assert done(run, "report", "h") is not None
    (run / "plan.json").write_text('{"workers": 3}')
    assert done(run, "report", "h") is None
    (run / "plan.json").write_text('{"workers": 2}')
    (run / "mission.yaml").write_text("seed: 2\n")
    assert done(run, "report", "h") is None
    (run / "mission.yaml").write_text("seed: 1\n")
    assert done(run, "report", "h") is not None
    assert ledger.resolve("plan.json", tmp_path / "copy", set()) == tmp_path / "copy" / "plan.json"


# A platform file is a hashed input of the hangar stage (DECISIONS 461): a byte changed in it, a comment or a `why` too, makes `audit` say "input ... changed
# since the stage ran" for every run made before and lowers Verification and M&S management when `report --run` renders that run again. The reference runs
# of round 11 (q10lb, q11, the demo mission, base commit 3ce8e09) hashed these four. Look-ahead L0, after M-12 edited a `why` text and broke both.
# quad_uas is the file of round 14 (DECISIONS 761): the runs made before it read it as changed by design, and the pin follows the file.
REFERENCE_RUN_PLATFORMS = {"seaglider": "911a7aa781406790", "slocum": "737d9fc4bc1fc381", "saildrone_explorer": "3a197c02b49a7d68",
                           "quad_uas": "a4771e81659ff27f"}      # round 14, M-39: aa55a771899344b1 before the radio block went (DECISIONS 761)
# Round 14 look-ahead L0 (the M-39 sibling): the three platforms also lost the name keys no code read; before it seaglider was 56504a67a56e97a7,
# slocum 63fa63b48d992ea3 and saildrone_explorer 7d7f9ed5cdbc4fb9 (the files the reference runs hashed).


def test_l0_r11_the_platform_files_the_reference_runs_hashed_are_the_bytes_they_hashed():
    from cafe.pm import config
    root = pathlib.Path(__file__).resolve().parents[1]
    demo = config.read_yaml(root / "missions" / "tepex_c_demo.yaml")
    assert {v["platform"] for v in demo["vehicles"]} == set(REFERENCE_RUN_PLATFORMS)            # the pins cover every platform the demo's hangar stage hashes
    changed = {n: sha256(config.platform_path(n))[:16] for n, want in REFERENCE_RUN_PLATFORMS.items() if sha256(config.platform_path(n))[:16] != want}
    assert not changed, (f"platforms/{'.yaml, platforms/'.join(changed)}.yaml differs from the file the reference runs q10lb and q11 hashed at their hangar "
                         "stage: every `audit` of those runs now fails with 'input ... changed' and a re-render lowers two credibility levels, whatever the "
                         "edit was. Move a wording change to DECISIONS or the code; if a number must change, say in DECISIONS that those runs are re-run, "
                         "then update the pin")


def test_r13_a_clean_gives_every_dict_key_the_text_json_writes_so_a_native_int_and_the_same_number_as_text_cannot_collide():
    """The adversary of batch A: `clean({1: a, "1": b})` kept both keys (only converted keys were merged), `json.dumps` wrote two "1" keys, and
    `sort_keys=True` raised TypeError on the mixed key types."""
    got = ledger.clean({1: "a", "1": "b", 2.5: "c", "2.5": "d", np.int64(3): "e", "3": "f", False: "g", "false": "h", None: "i", "null": "j", "x": "k"})
    assert got == {"1": "a", "2.5": "c", "3": "e", "false": "g", "null": "i", "x": "k"}              # the first of each text wins; the others are gone
    out = json.dumps(got, sort_keys=True, allow_nan=False)
    assert out.count('"1":') == 1 and json.loads(out) == got
    assert list(ledger.clean({2: 0, "a": 1, None: 2})) == ["2", "a", "null"]
    assert ledger.clean({"k": {3: [{4: 5}]}}) == {"k": {"3": [{"4": 5}]}}                            # nested, inside lists too


def test_r13_m29_clean_makes_a_non_json_dict_key_text_and_the_ledger_keeps_the_stage_error(tmp_path):
    """`json.dumps` refuses a numpy-integer, date or tuple key; in `Ledger.__exit__` that TypeError replaced the exception the stage was leaving."""
    assert ledger.clean({np.int64(3): np.float64(1.0), dt.date(2023, 3, 1): 2, (1, 2): 3, 4: 5, "s": 6, None: 7, float("nan"): 8}) == \
        {"3": 1.0, "2023-03-01": 2, "[1, 2]": 3, "4": 5, "s": 6, "null": 7, "nan": 8}
    assert ledger.clean({np.int64(3): "first", "3": "second"}) == {"3": "first"}                    # two keys that come out the same keep the first
    assert json.loads(json.dumps(ledger.clean({np.int64(3): 1.0}), allow_nan=False)) == {"3": 1.0}
    with pytest.raises(ValueError, match="the stage's own error"):
        with Ledger(tmp_path, "stage1", "h1") as L:
            L.d["extra"] = {np.int64(3): 1.0}
            raise ValueError("the stage's own error")
    d = json.loads((tmp_path / "checkpoints" / "stage1" / "ledger.json").read_text())
    assert d["extra"] == {"3": 1.0} and d["error"] == "ValueError: the stage's own error" and d["ok"] is False


def test_r13_m21_real_follows_symlinks_and_survives_a_loop(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "ln").symlink_to(tmp_path / "a")
    (tmp_path / "loop").symlink_to(tmp_path / "loop")
    assert ledger.real(tmp_path / "ln" / "x") == (tmp_path / "a" / "x").resolve()
    assert ledger.real(tmp_path / "loop" / "x").name == "x"                                          # no RuntimeError



ASSUMED = ("a.b:\n  value: 2.0\n  unit: m\n  why: the first wording\n  replace_with: a measurement\n"
           "c:\n  value: [1, 2]\n  unit: '-'\n  why: w\n  replace_with: r\n")


def stage3_problems(run):
    return [x for x in audit.ledger_problems(run) if "stage stage3" in x]


def test_r13_l2_an_assumptions_input_is_hashed_by_its_values_so_a_reworded_why_is_no_change(tmp_path):
    """Round 13 look-ahead L2: stage 3 hashed the whole of config/assumptions.yaml, so a wording edit of a `why` or `replace_with` (no stage reads
    them) made every kept run's audit say 'changed since the stage ran'. A value, a unit or a key still does."""
    src = tmp_path / "assumptions.yaml"
    src.write_text(ASSUMED)
    with Ledger(tmp_path, "stage3", "h1") as L:
        L.input_values(src)
    rec = json.loads((tmp_path / "checkpoints" / "stage3" / "ledger.json").read_text())["inputs"][0]
    assert rec["values_only"] is True and rec["sha256"] == ledger.values_sha256(src) != sha256(src)
    src.write_text(ASSUMED.replace("the first wording", "another wording, longer").replace("a measurement", "a better one"))
    assert done(tmp_path, "stage3", "h1") is not None and stage3_problems(tmp_path) == []
    for edit in ("value: 2.0", "value: 2.5"), ("unit: m", "unit: km"), ("a.b:", "a.c:"), ("value: [1, 2]", "value: [1, 3]"):
        src.write_text(ASSUMED.replace(*edit))
        assert done(tmp_path, "stage3", "h1") is None, edit
        assert stage3_problems(tmp_path) == [f"{tmp_path.name}: stage stage3: input {src} changed since the stage ran"], edit


def test_r13_l2_a_plain_input_and_a_file_that_is_not_a_mapping_still_change_the_hash(tmp_path):
    src = tmp_path / "assumptions.yaml"
    src.write_text(ASSUMED)
    with Ledger(tmp_path, "stage3", "h1") as L:
        L.input(src)                                                      # an older ledger, or any other file: its bytes
        L.input_values(tmp_path / "absent.yaml")                          # nothing there: recorded as before, with no hash
    src.write_text(ASSUMED.replace("first", "second"))
    assert done(tmp_path, "stage3", "h1") is None
    assert ledger.values_sha256(src) != "" and ledger.values_sha256(tmp_path / "absent.yaml") == ""
    src.write_text("- a\n- b\n")
    assert ledger.values_sha256(src) == ""
    src.write_text("a: [unclosed\n")
    assert ledger.values_sha256(src) == ""


# ---- review round 14, batch B

@pytest.mark.parametrize("value", ["HEAD", "ABCDEF1234567", "abc", "abcdef1234567 "])
def test_r14_m6_a_commit_variable_that_is_set_but_is_no_commit_is_named_not_called_unset(monkeypatch, value):
    """`need_commit` said "$CAFE_GIT_SHA is not set" for `HEAD`, an upper-case sha, `abc` and a padded sha: rightly refused, the reason was wrong."""
    def no_git(*a, **k):
        raise FileNotFoundError("git")
    monkeypatch.setattr(ledger.subprocess, "run", no_git)
    monkeypatch.setenv("CAFE_GIT_SHA", value)
    with pytest.raises(ValueError, match=r"stamped: no commit to name \(\$CAFE_GIT_SHA is set to .*not a commit \(7 or more lower-case hex digits\)\)") as e:
        ledger.need_commit("stamped")
    assert repr(value) in str(e.value) and "is not set" not in str(e.value)
    for unset in ("", "none"):
        monkeypatch.setenv("CAFE_GIT_SHA", unset)
        with pytest.raises(ValueError, match="no git here and \\$CAFE_GIT_SHA is not set"):
            ledger.need_commit("stamped")
    monkeypatch.delenv("CAFE_GIT_SHA")
    with pytest.raises(ValueError, match="no git here and \\$CAFE_GIT_SHA is not set"):
        ledger.need_commit("stamped")
    monkeypatch.setenv("CAFE_GIT_SHA", "abcdef1234567")
    assert ledger.need_commit("stamped") == "abcdef1234567"


@pytest.mark.parametrize("text", ["", "{\"t0\": ", "[1, 2]", "null", "\xff\xfe"])
def test_r14_m22_a_copy_of_a_manifest_that_is_not_a_json_object_is_an_empty_record_not_a_traceback(tmp_path, text):
    """`copy_manifest` ended in a bare `json.loads` of the copy: a shared manifest that was not JSON (a damaged disk) raised JSONDecodeError out of the stage,
    where `orca.read_json` makes the same file "no record" and the cache is fetched again."""
    src = tmp_path / "manifest.json"
    src.write_bytes(text.encode("latin-1"))
    assert ledger.copy_manifest(src, tmp_path / "run" / "copy.json") == {}
    assert (tmp_path / "run" / "copy.json").read_bytes() == src.read_bytes()
    src.write_text('{"t0": 1}')
    assert ledger.copy_manifest(src, tmp_path / "run" / "copy.json") == {"t0": 1}
