"""cafe.pm.audit: broken ledgers, banned tokens and commented-out code are all caught; rulers and prose are not."""
import json
import os
import pathlib
import platform
import runpy
import shutil
import sys

import pytest

from cafe.pm import audit, ledger
from cafe.pm.env.remote import sha256
from cafe.pm.env import surface
from cafe.pm.physics import comms
from cafe.pm.ledger import Ledger


def make_run(tmp_path, stages=audit.STAGES, extra_inputs=None):
    """A run dir whose ledgers chain the way pipeline.py writes them: each stage lists the previous stage's ledger as an input, and any file of
    `extra_inputs` ({stage: [path]}) as well."""
    run = tmp_path / "run"
    prev = None
    for st in stages:
        out = run / f"{st}.out"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(st)
        with Ledger(run, st, "cfg") as L:
            if prev is not None:
                L.input(prev)
            for f in (extra_inputs or {}).get(st, []):
                L.input(f)
            L.check("c", True)
            L.output(out)
        prev = run / "checkpoints" / st / "ledger.json"
    return run


def ledger_path(run, st):
    return run / "checkpoints" / st / "ledger.json"


def edit(run, st, fn):
    p = ledger_path(run, st)
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d))


def test_a_complete_chained_run_is_clean(tmp_path):
    assert audit.ledger_problems(make_run(tmp_path)) == []


def test_missing_ledger_is_reported_and_resets_the_chain(tmp_path):
    run = make_run(tmp_path)
    ledger_path(run, "stage1").unlink()
    probs = audit.ledger_problems(run)
    assert any("stage stage1: no ledger" in p for p in probs)
    assert not any("chain broken" in p for p in probs)               # the next stage has nothing to chain to, so it is not also blamed


def test_a_not_ok_ledger_and_a_failed_check_are_reported(tmp_path):
    run = make_run(tmp_path)
    edit(run, "hangar", lambda d: d.update(ok=False, error="ValueError: boom"))
    edit(run, "stage1", lambda d: d["checks"].append(dict(name="lhs", ok=False, value=3, limit=1)))
    probs = audit.ledger_problems(run)
    assert any("stage hangar: ok=false (ValueError: boom)" in p for p in probs)
    assert any("stage stage1: self-check lhs failed (value 3, limit 1)" in p for p in probs)


def test_changed_input_changed_output_and_missing_output_are_reported(tmp_path):
    run = make_run(tmp_path)
    src = tmp_path / "src.txt"
    src.write_text("v1")
    with Ledger(run, "ingest", "cfg") as L:
        L.input(src)
        L.input("https://example.org/remote.nc")                     # not a file here: nothing to rehash
        L.output(run / "ingest.out")
    src.write_text("v2")
    (run / "hangar.out").write_text("tampered")
    (run / "stage1.out").unlink()
    probs = audit.ledger_problems(run)
    assert any(f"stage ingest: input {src} changed since the stage ran" in p for p in probs)
    assert any("stage hangar: output" in p and "changed since the stage ran" in p for p in probs)
    assert any("stage stage1: output" in p and "is missing" in p for p in probs)
    assert not any("remote.nc" in p for p in probs)


def test_a_moved_run_is_audited_where_it_is_now_not_where_it_was_made(tmp_path):
    made = make_run(tmp_path / "a")
    here = tmp_path / "b" / "run"
    here.parent.mkdir()
    shutil.move(str(made), str(here))                                   # every recorded path still names a/run/...
    assert audit.ledger_problems(here) == []


def test_a_copy_of_a_run_is_checked_against_its_own_files(tmp_path):
    made = make_run(tmp_path / "a")
    copy = tmp_path / "b" / "run"
    shutil.copytree(made, copy)
    (copy / "stage1.out").write_text("tampered in the copy")           # the original is intact and still exists at the recorded path
    probs = audit.ledger_problems(copy)
    assert any("stage stage1: output" in p and str(copy) in p and "changed since the stage ran" in p for p in probs)
    assert audit.ledger_problems(made) == []


def test_relative_ledger_paths_chain_when_the_run_is_audited_by_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_run(pathlib.Path("."))
    assert json.loads(ledger_path(tmp_path / "run", "hangar").read_text())["inputs"][0]["ref"].startswith("run/")
    assert audit.ledger_problems(tmp_path / "run") == []
    assert audit.ledger_problems("run") == []


def test_a_path_through_the_run_name_that_is_not_under_the_run_stays_where_it_was_recorded(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    assert ledger.resolve("/elsewhere/run/gone.txt", run, set()) == pathlib.Path("/elsewhere/run/gone.txt")
    assert ledger.resolve("/elsewhere/other/x", run, set()) == pathlib.Path("/elsewhere/other/x")


def make_laid_out_run(root):
    """A run the way the pipeline lays it out: each stage's output in its own directory, one input outside the run, the ledgers chained."""
    run = root / "q9"
    ext = root / "config" / "limits.yaml"
    ext.parent.mkdir(parents=True)
    ext.write_text("a: 1")
    prev = None
    for st in audit.STAGES:
        out = run / st / "out.json"
        out.parent.mkdir(parents=True)
        out.write_text(st)
        with Ledger(run, st, "cfg") as L:
            if prev is not None:
                L.input(prev)
            L.input(ext)
            L.output(out)
        prev = run / "checkpoints" / st / "ledger.json"
    return run


def test_r9_m19_a_copy_under_another_name_is_checked_against_its_own_files_with_the_original_present(tmp_path):
    made = make_laid_out_run(tmp_path)
    copy = tmp_path / "quick"
    shutil.copytree(made, copy)
    assert audit.ledger_problems(copy) == []                                       # was 8 x "chain broken", and the hashes were the original's
    (copy / "stage3" / "out.json").write_text("tampered in the copy")
    probs = audit.ledger_problems(copy)
    assert len(probs) == 1 and f"stage stage3: output {copy / 'stage3' / 'out.json'} changed since the stage ran" in probs[0]
    assert audit.ledger_problems(made) == []


def test_r9_m19_a_copy_under_another_name_is_clean_with_the_original_removed(tmp_path):
    made = make_laid_out_run(tmp_path)
    copy = tmp_path / "quick"
    shutil.copytree(made, copy)
    shutil.rmtree(made)
    assert audit.ledger_problems(copy) == []                                       # was "missing" lines for every output and input ledger
    (copy / "report" / "out.json").unlink()
    assert audit.ledger_problems(copy) != []                                       # a file the copy lost is still reported


def zstore(path, attrs, name="zarr.json"):
    path.mkdir(parents=True)
    (path / name).write_text(json.dumps({"attributes": attrs} if name == "zarr.json" else attrs))
    return path


@pytest.mark.parametrize("name", ["zarr.json", ".zattrs"])
def test_a_directory_input_is_checked_against_the_manifest_hash_the_store_carries(tmp_path, name):
    run = make_run(tmp_path)
    ocean = zstore(tmp_path / "gofs.zarr", {"manifest_sha256": "a" * 64}, name)
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(ocean, sha="a" * 64, kind="ocean store")
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []
    (ocean / name).write_text(json.dumps({"attributes": {"manifest_sha256": "b" * 64}} if name == "zarr.json" else {"manifest_sha256": "b" * 64}))
    assert any(f"input {ocean} changed since the stage ran (store manifest bbbbbbbbbbbb, ledger aaaaaaaaaaaa)" in p for p in audit.ledger_problems(run))


def test_the_derived_surface_layer_is_rehashed_over_every_file_of_the_store(tmp_path):
    """Round 4 M-2: derived.zarr was in no ledger, so a store edited after ingest left the audit clean. Its input hash is over the path and bytes of every
    file (surface.store_sha256), and a changed byte, an added file or a removed one are all caught."""
    from cafe.pm.env.surface import store_sha256
    run = make_run(tmp_path)
    store = zstore(tmp_path / "cache" / "derived.zarr", {"layout_version": 2})
    (store / "ustar" / "c").mkdir(parents=True)
    (store / "ustar" / "c" / "0.0").write_bytes(b"\x00\x01\x02")
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(store, sha=store_sha256(store), kind="derived surface layer")
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []
    for change in (lambda: (store / "ustar" / "c" / "0.0").write_bytes(b"\x00\x01\x03"), lambda: (store / "extra").write_text("x"),
                   lambda: (store / "ustar" / "c" / "0.0").unlink()):
        change()
        assert any(f"input {store} (the derived surface layer) changed since the stage ran" in p for p in audit.ledger_problems(run))
        (store / "extra").unlink(missing_ok=True)
        (store / "ustar" / "c" / "0.0").write_bytes(b"\x00\x01\x02")
        assert audit.ledger_problems(run) == []


def test_a_directory_input_without_a_manifest_attribute_cannot_be_checked_and_is_not_blamed(tmp_path):
    run = make_run(tmp_path)
    bare = tmp_path / "plain_dir"
    bare.mkdir()
    noattr = zstore(tmp_path / "noattr.zarr", {})
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(bare, sha="a" * 64)
        L.input(noattr, sha="a" * 64)
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []


def test_the_orca_cache_manifest_names_the_hash_of_every_hourly_part_and_the_parts_are_rehashed(tmp_path):
    run = make_run(tmp_path)
    orca_dir = tmp_path / "orca"
    (orca_dir / "hours").mkdir(parents=True)
    (orca_dir / "hours" / "wrf_a.npz").write_bytes(b"one")
    (orca_dir / "hours" / "wrf_b.npz").write_bytes(b"two")
    man = orca_dir / "manifest.json"
    man.write_text(json.dumps({"parts": {"wrf_a.npz": sha256(orca_dir / "hours" / "wrf_a.npz"), "wrf_b.npz": sha256(orca_dir / "hours" / "wrf_b.npz"),
                                         "wrf_gone.npz": "0" * 64}}))
    other = tmp_path / "tao" / "manifest.json"
    other.parent.mkdir()
    other.write_text(json.dumps({"t0": 1}))                                # a manifest with no parts is not the orca cache
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(man)
        L.input(other)
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []                                # a part that is no longer on disk is not blamed
    (orca_dir / "hours" / "wrf_b.npz").write_bytes(b"TWO")
    probs = audit.ledger_problems(run)
    assert probs == [f"run: stage report: orca part {orca_dir / 'hours' / 'wrf_b.npz'} changed since the cache was assembled"]


def test_a_rerun_stage_without_the_ones_after_it_breaks_the_chain(tmp_path):
    run = make_run(tmp_path)
    edit(run, "stage1", lambda d: d.update(inputs=[]))
    assert any("stage stage1: does not record the hangar ledger as an input (chain broken)" in p for p in audit.ledger_problems(run))


@pytest.mark.parametrize("line", [
    "# x = foo(1)", "    # result = np.zeros((3, 4))", "# import os; import sys", "# return x + 1", "# for i in range(3): pass", "# print(x)",
    "# d['a'] = [1, 2]", "# if x > 1: y = 2",
])
def test_commented_out_code_is_caught(line):
    assert audit._commented_code(line)


@pytest.mark.parametrize("line", [
    "x = 1", "#!/usr/bin/env python", "# -*- coding: utf-8 -*-", "# ---------- stage 1 ----------", "# ===== results =====", "# .. note",
    "# -- ingest --", "# short", "# Note:", "# Compute the drift (m/s) per hour, then average it.", "# this is just prose, fine.", "# 12345678 !!!",
    "# print; print", "# x y z = broken syntax (", "#", "# lon, lat = positions in degrees east",
])
def test_rulers_prose_and_syntax_errors_are_not_commented_out_code(line):
    assert not audit._commented_code(line)


def tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text) if isinstance(text, str) else p.write_bytes(text)
    return tmp_path


@pytest.mark.parametrize("line,word", [
    ("# TODO later", "TODO"), ("x = 1  # FIXME", "FIXME"), ("# XXX", "XXX"), ("raise NotImplementedError", "NotImplementedError"),
    ("pass  # placeholder", "placeholder"), ("pytest.skip('x')", "pytest.skip"), ("@pytest.mark.skip", "mark.skip"),
    ("@pytest.mark.skipif(True)", "skipif"), ("@pytest.mark.xfail", "xfail"),
    ("items.skip(1)", "skip("),
])
def test_each_banned_token_is_caught_with_file_and_line(tmp_path, line, word):
    root = tree(tmp_path, {"cafe/pm/a.py": f"x = 1\n{line}\n"})
    hits = audit.banned(root)
    assert len(hits) == 1 and hits[0].startswith("cafe/pm/a.py:2: banned pattern") and word in hits[0]


def test_banned_words_inside_longer_words_are_fine(tmp_path):
    root = tree(tmp_path, {"cafe/pm/a.py": "y = 'todo_list'\nclass XXXL: pass\nplaceholders = 1\n"})
    assert audit.banned(root) == []


def test_commented_out_code_is_reported_and_rulers_and_prose_are_not(tmp_path):
    root = tree(tmp_path, {"cafe/pm/a.py": "# ---------- section ----------\n# x = foo(1)\n# plain prose, nothing to see\nok = 1\n"})
    assert audit.banned(root) == ["cafe/pm/a.py:2: commented-out code: # x = foo(1)"]


def test_commented_code_is_only_looked_for_in_python_files(tmp_path):
    root = tree(tmp_path, {"config/c.yaml": "# x = foo(1)\n", "docs/RUNBOOK.md": "# x = foo(1)\n"})
    assert audit.banned(root) == []


def test_exempt_paths_single_file_scan_entries_and_unreadable_files(tmp_path):
    root = tree(tmp_path, {
        "tests/fixtures/broken/wave.py": "# TODO\n", "tests/test_audit.py": "# TODO\n", "cafe/pm/audit.py": "# TODO\n",
        "cafe/pm/__pycache__/a.py": "# TODO\n", "cafe/pm/data.bin": "TODO\n", "cafe/pm/binary.py": b"\xff\xfe\x00TODO", "Makefile": "x: # FIXME\n",
        "docs/RUNBOOK.md": "TODO write\n", "bench/b.py": "x = 1\n",
    })
    hits = sorted(audit.banned(root))
    assert [h.split(":")[0] for h in hits] == ["Makefile", "docs/RUNBOOK.md"]


def cov(tmp_path, files):
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps({"files": {f: {"summary": {"num_statements": n, "covered_lines": c}} for f, (n, c) in files.items()}}))
    return p


def test_coverage_gates_per_package(tmp_path):
    ok = cov(tmp_path, {"cafe/pm/a.py": (100, 95), "cafe/pm/env/x.py": (10, 10), "cafe/pm/physics/y.py": (10, 10), "cafe/pm/stats/z.py": (5, 5)})
    assert audit.coverage_problems(ok) == []
    bad = cov(tmp_path, {"cafe/pm/a.py": (100, 80), "cafe/pm/env/x.py": (10, 9), "cafe/pm/physics/y.py": (10, 10)})
    probs = audit.coverage_problems(bad)
    assert "coverage cafe/pm: 82.5 % < 90 %" in probs and "coverage cafe/pm/env: 90.0 % < 100 %" in probs
    assert not any("physics" in p or "stats" in p for p in probs)         # no statements at all counts as covered


def test_run_returns_code_and_the_tail_of_the_output():
    rc, out = audit._run([sys.executable, "-c", "print('x' * 5000); import sys; sys.exit(3)"])
    assert rc == 3 and len(out) == 4000 and set(out.strip()) == {"x"}


def test_main_code_only_reports_ledger_and_banned_problems(tmp_path, monkeypatch, capsys):
    run = make_run(tmp_path)
    ledger_path(run, "report").unlink()
    monkeypatch.setattr(audit, "banned", lambda: ["cafe/pm/x.py:1: banned pattern: TODO"])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    monkeypatch.setattr(audit, "_run", lambda cmd: pytest.fail("--code-only must not run the tools"))
    assert audit.main([str(run), "--code-only"]) == 1
    out = capsys.readouterr().out
    assert "AUDIT FAIL: run: stage report: no ledger" in out and "AUDIT FAIL: cafe/pm/x.py:1" in out and "audit: 2 problem(s)" in out


def test_main_runs_ruff_mypy_pytest_and_the_coverage_gates(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    def fake(cmd):
        calls.append(cmd[0] if cmd[0] != sys.executable else "pytest-cov-append" if "--cov-append" in cmd else "pytest")
        return (1, f"{cmd[0]} failed") if cmd[0] in ("ruff", "mypy") else (0, "")
    monkeypatch.setattr(audit, "_run", fake)
    cov(tmp_path, {"cafe/pm/a.py": (10, 1)})
    assert audit.main([]) == 1
    out = capsys.readouterr().out
    # the test step is two passes (round 6, L-W1): the suite by file over the workers, then the real-time tests with --cov-append
    assert calls == ["ruff", "mypy", "pytest", "pytest-cov-append"] and "AUDIT FAIL: ruff:\nruff failed" in out and "AUDIT FAIL: mypy:" in out
    assert "coverage cafe/pm: 10.0 % < 90 %" in out and "audit: 3 problem(s)" in out
    monkeypatch.setattr(audit, "_run", lambda cmd: (1, "pytest output") if cmd[0] == sys.executable else (0, ""))
    (tmp_path / "coverage.json").unlink()
    assert audit.main([]) == 1 and "AUDIT FAIL: pytest:\npytest output" in capsys.readouterr().out


def pytest_done_root(tmp_path, monkeypatch, receipt=True, coverage=True):
    """A repo in miniature for --pytest-done: cafe/pm/a.py and tests/test_a.py, a coverage.json, and the receipt of a suite that passed on them."""
    (tmp_path / "cafe" / "pm" / "__pycache__").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "cafe" / "pm" / "a.py").write_text("x = 1\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    pass\n")
    (tmp_path / "cafe" / "pm" / "__pycache__" / "a.pyc").write_bytes(b"")             # running the tests writes bytecode: it must not count
    if coverage:
        cov(tmp_path, {"cafe/pm/a.py": (10, 10)})
    if coverage and receipt:
        audit.write_pytest_receipt(tmp_path)
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    monkeypatch.setattr(audit, "ROOT", tmp_path)


def test_pytest_done_runs_everything_but_pytest_and_needs_the_receipt_of_a_suite_that_passed_on_this_code(tmp_path, monkeypatch, capsys):
    """The suite can run elsewhere in pieces (bin/proot_suite.sh); the audit then must not read as a pass without those tests having run on this code."""
    calls = []
    monkeypatch.setattr(audit, "_run", lambda cmd: calls.append(cmd[0]) or (0, ""))
    pytest_done_root(tmp_path, monkeypatch)
    assert audit.main(["--pytest-done"]) == 0 and calls == ["ruff", "mypy"]              # no pytest pass, and a receipted coverage.json is read for the gates
    assert "audit: 0 problem(s)" in capsys.readouterr().out
    cov(tmp_path, {"cafe/pm/a.py": (10, 1)})
    audit.write_pytest_receipt(tmp_path)
    assert audit.main(["--pytest-done"]) == 1 and "coverage cafe/pm: 10.0 % < 90 %" in capsys.readouterr().out


def edit_keeping_mtime(path, text):
    t = path.stat().st_mtime_ns
    path.write_text(text)
    os.utime(path, ns=(t, t))                                                              # what `rsync -a` leaves of a file edited during the run


@pytest.mark.parametrize("how, said", [
    ("no coverage", "no coverage.json"),
    ("no receipt", "no coverage.receipt.json: nothing says the suite passed"),
    ("code edited", "differs from what the suite ran on"),
    ("test edited", "differs from what the suite ran on"),
    ("code edited, older mtime", "differs from what the suite ran on"),
    ("other coverage", "coverage.json is not the one the suite's receipt was written for"),
    ("receipt says failed", "does not say the suite passed"),
    ("receipt damaged", "is not valid JSON"),
])
def test_r11_m10_pytest_done_fails_without_a_passed_suite_on_this_exact_code(tmp_path, monkeypatch, capsys, how, said):
    """A file edited after the run with its time set back (rsync -a) passed `coverage_stale`, as did a coverage.json written by a suite that failed."""
    monkeypatch.setattr(audit, "_run", lambda cmd: (0, ""))
    pytest_done_root(tmp_path, monkeypatch, receipt=how != "no receipt", coverage=how != "no coverage")
    src, test, rec = tmp_path / "cafe" / "pm" / "a.py", tmp_path / "tests" / "test_a.py", tmp_path / audit.PYTEST_RECEIPT
    if how == "code edited":
        src.write_text("x = 2\n")
    elif how == "test edited":
        test.write_text("def test_a():\n    assert False\n")
    elif how == "code edited, older mtime":
        edit_keeping_mtime(src, "x = 2\n")
    elif how == "other coverage":
        cov(tmp_path, {"cafe/pm/a.py": (10, 9)})
    elif how == "receipt says failed":
        rec.write_text(json.dumps(dict(json.loads(rec.read_text()), suite_ok=False)))
    elif how == "receipt damaged":
        rec.write_text("{not json")
    assert audit.main(["--pytest-done"]) == 1
    assert said in capsys.readouterr().out


def test_r11_m10_the_receipt_is_written_only_by_its_own_option_for_a_coverage_json_that_is_there(tmp_path, monkeypatch, capsys):
    pytest_done_root(tmp_path, monkeypatch, receipt=False, coverage=False)
    assert audit.main(["--pytest-receipt"]) == 2 and "no coverage.json" in capsys.readouterr().out and not (tmp_path / audit.PYTEST_RECEIPT).exists()
    cov(tmp_path, {"cafe/pm/a.py": (10, 10)})
    assert audit.main(["--pytest-receipt", "--code-only"]) == 2 and "takes no other option" in capsys.readouterr().out
    assert audit.main(["--pytest-receipt"]) == 0 and "wrote coverage.receipt.json" in capsys.readouterr().out
    rec = json.loads((tmp_path / audit.PYTEST_RECEIPT).read_text())
    assert rec["suite_ok"] is True and rec["code_digest"] == audit.suite_digest(tmp_path) and rec["coverage_sha256"] == sha256(tmp_path / "coverage.json")
    assert audit.coverage_stale(tmp_path) == []


def test_pytest_done_takes_no_other_option_and_the_full_audit_still_runs_pytest(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit, "_run", lambda cmd: pytest.fail("a step ran"))
    for other in ("--code-only", "--ledgers-only", "--mutation-record", "--pytest-receipt"):
        assert audit.main(["--pytest-done", other]) == 2 and "--pytest-done takes no other option" in capsys.readouterr().out
    calls = []
    monkeypatch.setattr(audit, "_run", lambda cmd: calls.append(cmd) or (0, ""))
    pytest_done_root(tmp_path, monkeypatch, receipt=False, coverage=False)
    audit.main([])
    assert sum("pytest" in c for c in calls) == 2                                          # without the option nothing changed


def test_audit_mypy_step_reads_pyproject_and_fails_on_a_strict_only_error(tmp_path, monkeypatch):
    """`_run(["mypy"])` picks up [tool.mypy] from the project root: an unannotated def passes plain mypy and fails strict."""
    (tmp_path / "pyproject.toml").write_text((audit.ROOT / "pyproject.toml").read_text())
    (tmp_path / "cafe" / "pm").mkdir(parents=True)
    (tmp_path / "cafe" / "pm" / "bad.py").write_text("def f(x):\n    return x\n")
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    rc, out = audit._run(["mypy"])
    assert rc != 0 and "no-untyped-def" in out and "bad.py" in out


def test_main_is_clean_when_everything_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    monkeypatch.setattr(audit, "_run", lambda cmd: (0, ""))
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    assert audit.main([str(make_run(tmp_path))]) == 0 and "audit: 0 problem(s)" in capsys.readouterr().out


# ---- mutation: the stored result of `make mutation` ---------------------------------------------------------------------


def mut_root(tmp_path, killed=90, total=100, **extra):
    """A repo in miniature: one file each in physics and stats, a test, conftest, the [tool.mutmut] test selection, and mutmut's counts."""
    root = tree(tmp_path, {
        "pyproject.toml": '[tool.mutmut]\npytest_add_cli_args_test_selection = ["tests/test_a.py"]\n',
        "cafe/pm/physics/a.py": "G = 9.81\n", "cafe/pm/stats/b.py": "Z = 1.96\n", "cafe/pm/other.py": "O = 1\n",
        "cafe/pm/physics/__pycache__/a.pyc": "junk", "tests/test_a.py": "def test_a(): assert True\n", "tests/conftest.py": "",
        "tests/test_unlisted.py": "",
    })
    counts = dict(killed=killed, survived=total - killed, timeout=0, no_tests=0, suspicious=0, skipped=0, segfault=0, total=total, **extra)
    tree(tmp_path, {audit.MUTATION_STATS: json.dumps(counts)})
    return root


def store(root, monkeypatch):
    monkeypatch.setattr(audit.importlib.metadata, "version", lambda name: "9.9.9")
    (root / "docs").mkdir(exist_ok=True)
    (root / audit.MUTATION_FILE).write_text(json.dumps(audit.mutation_record(root)))


def test_mutation_result_missing_is_a_failure_naming_the_command(tmp_path):
    probs = audit.mutation_problems(mut_root(tmp_path))
    assert len(probs) == 1
    assert f"no stored result at {audit.MUTATION_FILE}" in probs[0]
    assert "`make mutation`" in probs[0]
    assert "`./pm.sh make mutation`" in probs[0]


def test_record_holds_counts_score_digest_tests_date_and_version(tmp_path, monkeypatch):
    root = mut_root(tmp_path, killed=170, total=200)
    store(root, monkeypatch)
    rec = json.loads((root / audit.MUTATION_FILE).read_text())
    assert (rec["killed"], rec["survived"], rec["timeout"], rec["total"], rec["score"]) == (170, 30, 0, 200, 0.85)
    assert rec["code_digest"] == audit.mutation_digest(root) and rec["tests"] == ["tests/test_a.py"] and rec["sources"] == audit.MUTATED
    assert rec["mutmut"] == "9.9.9" and rec["date"].endswith("+00:00") and len(rec["date"]) == 25
    assert audit.mutation_problems(root) == []                       # exactly 85 % passes


def test_score_below_85_percent_fails_and_the_stored_score_field_is_not_trusted(tmp_path, monkeypatch):
    root = mut_root(tmp_path, killed=169, total=200)
    store(root, monkeypatch)
    probs = audit.mutation_problems(root)
    assert len(probs) == 1 and "169/200 mutants killed = 84.5% < 85%" in probs[0] and "make mutation" in probs[0]
    path = root / audit.MUTATION_FILE
    path.write_text(json.dumps(dict(json.loads(path.read_text()), score=1.0)))
    assert "84.5%" in audit.mutation_problems(root)[0]


def test_survivors_timeouts_and_unreached_mutants_all_count_against_the_score():
    assert audit.mutation_score(dict(killed=85, total=100, survived=5, timeout=5, no_tests=5)) == 0.85
    assert audit.mutation_score(dict(killed=0, total=0)) == 0.0         # nothing mutated is not a pass


@pytest.mark.parametrize("edit", ["cafe/pm/physics/a.py", "cafe/pm/stats/b.py", "tests/test_a.py", "tests/conftest.py"])
def test_a_stale_result_fails_when_mutated_code_or_its_tests_change(tmp_path, monkeypatch, edit):
    root = mut_root(tmp_path)
    store(root, monkeypatch)
    assert audit.mutation_problems(root) == []
    with (root / edit).open("a") as f:
        f.write("# changed\n")
    probs = audit.mutation_problems(root)
    assert len(probs) == 1 and "made by different physics/stats code or tests" in probs[0] and "make mutation" in probs[0]


@pytest.mark.parametrize("edit", ["cafe/pm/other.py", "tests/test_unlisted.py", "cafe/pm/physics/__pycache__/a.pyc"])
def test_a_result_survives_edits_outside_the_mutated_code_and_its_tests(tmp_path, monkeypatch, edit):
    root = mut_root(tmp_path)
    store(root, monkeypatch)
    with (root / edit).open("a") as f:
        f.write("changed\n")
    assert audit.mutation_problems(root) == []


def test_digest_depends_on_the_test_selection_in_pyproject(tmp_path):
    root = mut_root(tmp_path)
    d = audit.mutation_digest(root)
    (root / "pyproject.toml").write_text('[tool.mutmut]\npytest_add_cli_args_test_selection = ["tests/test_a.py", "tests/test_unlisted.py"]\n')
    assert audit.mutation_digest(root) != d and audit.mutation_tests(root) == ["tests/test_a.py", "tests/test_unlisted.py"]


def test_the_repo_selection_names_existing_test_files_and_the_audit_reads_the_repo_result():
    assert audit.mutation_tests() and all((audit.ROOT / t).is_file() for t in audit.mutation_tests())
    assert all((audit.ROOT / d).is_dir() for d in audit.MUTATED)


def test_main_reports_a_mutation_problem_and_record_flag_writes_the_file(tmp_path, monkeypatch, capsys):
    root = mut_root(tmp_path)
    monkeypatch.setattr(audit, "ROOT", root)
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit.importlib.metadata, "version", lambda name: "9.9.9")
    assert audit.main(["--code-only"]) == 1 and f"AUDIT FAIL: mutation: no stored result at {audit.MUTATION_FILE}" in capsys.readouterr().out
    (root / "docs").mkdir()
    assert audit.main(["--mutation-record"]) == 0 and f"wrote {audit.MUTATION_FILE}" in capsys.readouterr().out
    assert json.loads((root / audit.MUTATION_FILE).read_text())["killed"] == 90
    assert audit.main(["--code-only"]) == 0 and "audit: 0 problem(s)" in capsys.readouterr().out


def test_module_entry_point_exits_with_the_audit_status(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["audit", "--code-only"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm.audit", run_name="__main__")
    assert e.value.code in (0, 1)


# ---- review round 2, M-34: the older cafe/ modules the pipeline imports are inside the banned-token scan and (those that pass) ruff

def imported_cafe_modules():
    """The top-level cafe/<name>.py modules that cafe/pm imports (`from cafe import x`, `import cafe.x`, `from cafe.x import y`), directly."""
    import ast
    found = set()
    for f in (audit.ROOT / "cafe" / "pm").rglob("*.py"):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module == "cafe":
                found |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and n.module.startswith("cafe.") and not n.module.startswith("cafe.pm"):
                found.add(n.module.split(".")[1])
            elif isinstance(n, ast.Import):
                found |= {a.name.split(".")[1] for a in n.names if a.name.startswith("cafe.") and not a.name.startswith("cafe.pm")}
    return {m for m in found if (audit.ROOT / "cafe" / f"{m}.py").is_file()}


def test_every_cafe_module_the_pipeline_imports_is_in_the_banned_token_scan():
    mods = imported_cafe_modules()
    assert {"cfd", "fea", "emulator", "reach", "receipts"} <= mods
    assert {f"cafe/{m}.py" for m in mods} <= set(audit.SCAN)
    assert all((audit.ROOT / s).exists() for s in audit.SCAN)


def test_those_modules_are_linted_where_they_pass_ruff():
    import tomllib
    inc = tomllib.loads((audit.ROOT / "pyproject.toml").read_text())["tool"]["ruff"]["include"]
    assert {"cafe/cfd.py", "cafe/emulator.py", "cafe/fea.py", "cafe/reach.py", "cafe/receipts.py"} <= set(inc)
    assert "cafe/planner.py" not in inc and "cafe/planner.py" in audit.SCAN                      # scanned for banned tokens, not linted (see audit.IMPORTED)


def test_a_banned_token_in_an_imported_older_module_is_caught(tmp_path):
    for s in audit.SCAN:
        p = tmp_path / s
        if s.endswith((".py", ".md", ".js")) or s == "Makefile":
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x = 1\n")
        else:
            p.mkdir(parents=True, exist_ok=True)
    (tmp_path / "cafe" / "fea.py").write_text("x = 1\n# TODO later\n")
    assert audit.banned(tmp_path) == ["cafe/fea.py:2: banned pattern: # TODO later"]


def test_the_older_modules_the_scan_names_are_clean_today():
    older = tuple(audit.IMPORTED)
    assert len(older) == 15 and not [h for h in audit.banned() if h.startswith(older)]


def test_the_whole_scanned_tree_has_no_banned_token_today():
    """Round 13 gate: a test helper's docstring held a banned stand-in word for five commits; only the gate's audit step found it. The scan is the same
    one, so a hit fails here, in the file's own run, with its file and line."""
    assert audit.banned() == []


# ---- review round 3, M-24 and M-27

def test_ledgers_only_audits_the_run_dirs_given_and_nothing_else(tmp_path, monkeypatch, capsys):
    """`make ci` ends with --ledgers-only on the run it made: a corrupted output hash fails it; no repo scan, no mutation record."""
    monkeypatch.setattr(audit, "banned", lambda: pytest.fail("--ledgers-only must not scan the repo"))
    monkeypatch.setattr(audit, "mutation_problems", lambda root: pytest.fail("--ledgers-only must not read the mutation record"))
    monkeypatch.setattr(audit, "_run", lambda cmd: pytest.fail("--ledgers-only must not run the tools"))
    run = make_run(tmp_path)
    assert audit.main([str(run), "--ledgers-only"]) == 0
    (run / "ingest.out").write_text("tampered")
    assert audit.main([str(run), "--ledgers-only"]) == 1
    assert "AUDIT FAIL: run: stage ingest" in capsys.readouterr().out


@pytest.mark.parametrize("level", [None, "1"])
def test_make_ci_ends_with_the_ledger_audit_of_the_run_it_made(level, monkeypatch):
    """Round 8 M-41: under `make audit` pytest inherits MAKELEVEL, and a nested make then prints "Entering/Leaving directory" after the command."""
    import subprocess
    monkeypatch.delenv("MAKELEVEL", raising=False)
    if level:
        monkeypatch.setenv("MAKELEVEL", level)
    out = subprocess.run(["make", "--no-print-directory", "-n", "ci"], cwd=audit.ROOT, capture_output=True, text=True, check=True).stdout.strip().splitlines()
    assert out[-1] == "python -m cafe.pm.audit --ledgers-only runs/ci" and "--out runs/ci" in out[-2]


def test_the_static_app_script_is_scanned_the_vendored_libraries_and_the_html_are_not(tmp_path):
    root = tree(tmp_path, {"cafe/static/app.js": "let a = 1;\n// TODO fix\nf.mass.placeholder = 'x';\nq.skip(2);\n",
                           "cafe/static/vendor/three.js": "// TODO\n", "cafe/static/index.html": '<input placeholder="x">\n'})
    assert audit.banned(root) == ["cafe/static/app.js:2: banned pattern: // TODO fix", "cafe/static/app.js:4: banned pattern: q.skip(2);"]


def test_an_assert_that_ends_in_or_True_is_a_banned_pattern_and_other_uses_of_it_are_not(tmp_path):
    """Round 6, M-26: `assert a or True` cannot fail and passed the token audit (tests/test_glider.py:413); a callback returning `... or True` is fine."""
    root = tree(tmp_path, {"tests/test_a.py": 'def test_a():\n    assert (h["lon"] < 0).any() or (s.lon < 0).all() or True\n    assert x == 1  \n'
                                              "    opened = lambda url: log.append(url) or True\n    assert flag or not True\n"})
    assert audit.banned(root) == ['tests/test_a.py:2: banned pattern: assert (h["lon"] < 0).any() or (s.lon < 0).all() or True']


def test_review_round_6_m20_a_wrong_path_or_option_is_refused_before_any_step_runs(tmp_path, monkeypatch, capsys):
    """The audit started ruff, mypy and the whole suite (an hour) before saying that the run directory did not exist, and dropped an unknown --flag."""
    def never(cmd):
        raise AssertionError(f"a step ran: {cmd}")
    monkeypatch.setattr(audit, "_run", never)
    monkeypatch.setattr(audit, "banned", never)
    assert audit.main(["/nonexistent"]) == 2
    assert "error: /nonexistent is not a run directory (the run directories are runs/quick, runs/overnight, runs/4h)" in capsys.readouterr().out
    assert audit.main(["--ledger-only", str(make_run(tmp_path))]) == 2
    assert "error: unknown option --ledger-only (--code-only, --ledgers-only, --mutation-record, --pytest-done, --pytest-receipt)" in capsys.readouterr().out
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    assert audit.main(["--ledgers-only", str(make_run(tmp_path / "ok"))]) == 0                  # a good run directory and a known option still go through


def test_l_w1_the_test_step_runs_both_passes_and_reports_a_failure_of_either(monkeypatch, capsys):
    calls = []

    def fake(cmd):
        calls.append(cmd)
        return (1, "boom") if "--cov-append" in cmd else (0, "")
    monkeypatch.setattr(audit, "_run", fake)
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "mutation_problems", lambda root: [])
    monkeypatch.setattr(audit, "coverage_problems", lambda p: [])
    assert audit.main([]) == 1
    pytests = [c for c in calls if "pytest" in c]
    assert len(pytests) == 2 and "-n" in pytests[0] and "--cov-append" in pytests[1] and "AUDIT FAIL: pytest:\nboom" in capsys.readouterr().out


def test_run_keeps_the_tail_for_the_message_and_the_whole_output_in_the_log(tmp_path, monkeypatch):
    """Round 7 integration: on the hosted runner 12 tests failed and the audit printed only the last 4000 characters of pytest's output, the summary
    without one traceback, so nothing could be diagnosed. `_run` appends every step's whole output to audit.log, which CI uploads."""
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    rc, out = audit._run([sys.executable, "-c", "print('a' * 6000); print('end')"])
    log = (tmp_path / audit.LOG).read_text()
    assert rc == 0 and len(out) == 4000 and out.rstrip().endswith("end")
    assert "a" * 6000 in log and log.endswith("rc=0\n") and log.startswith(f"$ {sys.executable} -c")


# ---- review round 8: M-4 (the tree hash of a directory input), M-23 (an unreadable ledger), M-40 (the lines a coverage gate misses)

def _store_with_a_tree_hash(tmp_path, run):
    from cafe.pm.env.remote import tree_sha256
    store = zstore(tmp_path / "gofs.zarr", {"manifest_sha256": "a" * 64})
    (store / "water_u" / "c").mkdir(parents=True)
    (store / "water_u" / "c" / "0").write_bytes(b"\x01\x02\x03")
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(store, sha="a" * 64, tree=tree_sha256(store), kind="ocean store")
        L.output(run / "report.out")
    return store


def test_r8_m4_a_directory_input_is_rehashed_over_every_file_and_a_changed_value_or_a_deleted_chunk_is_named(tmp_path):
    """The manifest attribute is written at assembly and is not changed by later damage; the tree hash is."""
    run = make_run(tmp_path)
    store = _store_with_a_tree_hash(tmp_path, run)
    assert audit.ledger_problems(run) == []
    chunk = store / "water_u" / "c" / "0"
    chunk.write_bytes(b"\x09\x09\x09")
    probs = audit.ledger_problems(run)
    assert len(probs) == 1 and f"run: stage report: input {store} changed since the stage ran (tree " in probs[0]
    assert "delete it and run `fetch` again" in probs[0]
    chunk.unlink()
    assert any(f"input {store} changed since the stage ran (tree " in p for p in audit.ledger_problems(run))
    chunk.write_bytes(b"\x01\x02\x03")
    assert audit.ledger_problems(run) == []


def test_r8_m23_an_unreadable_ledger_is_a_problem_naming_the_file_not_a_traceback(tmp_path):
    run = make_run(tmp_path)
    p = ledger_path(run, "stage1")
    good = p.read_text()
    for bad in (good[:200], "", "[1]"):
        p.write_text(bad)
        probs = audit.ledger_problems(run)
        assert any(f"run: stage stage1: {p} is not valid JSON (" in x and "delete it and run the stage again" in x for x in probs), (bad, probs)
        assert not any("chain broken" in x for x in probs)  # the next stage has nothing to chain to, as for a missing ledger
    p.write_text(good)
    assert audit.ledger_problems(run) == []


def test_r8_m40_a_coverage_gate_of_100_names_the_files_and_lines_it_misses(tmp_path):
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps({"files": {
        "cafe/pm/physics/comms.py": {"summary": {"num_statements": 219, "covered_lines": 216}, "missing_lines": [273, 275, 287]},
        "cafe/pm/physics/usv.py": {"summary": {"num_statements": 1639, "covered_lines": 1639}, "missing_lines": []},
        "cafe/pm/a.py": {"summary": {"num_statements": 100, "covered_lines": 80}, "missing_lines": [1, 2, 3]}}}))
    probs = audit.coverage_problems(p)
    assert "coverage cafe/pm/physics: 99.8 % < 100 % (comms.py: 273, 275, 287)" in probs
    assert not any(x.startswith("coverage cafe/pm:") for x in probs)                             # 98.8 % of 1958 statements is over the 90 % gate
    p.write_text(json.dumps({"files": {"cafe/pm/a.py": {"summary": {"num_statements": 100, "covered_lines": 80}, "missing_lines": [1, 2, 3]}}}))
    assert audit.coverage_problems(p) == ["coverage cafe/pm: 80.0 % < 90 %"]                      # a package gate under 100 % does not list lines


# ---- review round 8, lead item L0: a damaged JSON input is a line, a removed input is a line

def _report_with_inputs(run, *inputs, **kw):
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        for i in inputs:
            L.input(i, **kw)
        L.output(run / "report.out")


def test_r8_l0_a_truncated_orca_or_tao_manifest_is_a_problem_naming_the_file_not_a_traceback(tmp_path):
    """M-23 guarded the ledger.json read only; any input named manifest.json was re-read with a bare json.loads (the TAO manifest, the orca cache's)."""
    run = make_run(tmp_path)
    man = tmp_path / "orca" / "manifest.json"
    man.parent.mkdir()
    good = json.dumps({"parts": {"a.npz": "0" * 64}, "pad": "x" * 6000})
    man.write_text(good)
    _report_with_inputs(run, man)
    for bad in (good[:5000], "[1,2", "", "[1]"):                      # the first cut is a disk-full or killed write
        man.write_text(bad)
        probs = audit.ledger_problems(run)
        assert any(f"run: stage report: input {man} is not valid JSON (" in x and "delete it and run `fetch` again" in x for x in probs), (bad, probs)
    man.write_text(good)
    assert audit.ledger_problems(run) == []


def test_r8_l0_a_store_with_a_truncated_zarr_json_is_a_problem_naming_the_file_not_a_traceback(tmp_path):
    run = make_run(tmp_path)
    store = zstore(tmp_path / "gofs.zarr", {"manifest_sha256": "a" * 64})
    _report_with_inputs(run, store, sha="a" * 64)
    assert audit.ledger_problems(run) == []
    for bad in ('{trunc', "", "[1]"):
        (store / "zarr.json").write_text(bad)
        probs = audit.ledger_problems(run)
        assert probs and all(f"run: stage report: input {store / 'zarr.json'} is not valid JSON (" in x for x in probs), (bad, probs)


def test_r8_l0_a_truncated_orca_part_manifest_is_a_problem_when_the_orca_check_reads_it(tmp_path):
    man = tmp_path / "manifest.json"
    man.write_text('{"parts": {"a": ')
    with pytest.raises(audit._Unreadable, match="manifest.json is not valid JSON"):
        audit._orca_problems("run", "ingest", man)


def test_r8_l0_an_input_that_was_hashed_and_is_gone_is_a_problem_but_a_url_or_an_unhashed_one_is_not(tmp_path):
    run = make_run(tmp_path)
    src = tmp_path / "src.txt"
    src.write_text("v1")
    store = zstore(tmp_path / "gofs.zarr", {"manifest_sha256": "a" * 64})
    from cafe.pm.env.remote import tree_sha256
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(src)
        L.input(store, sha="a" * 64, tree=tree_sha256(store))
        L.input("https://example.org/remote.nc", sha="b" * 64)       # a remote reference with the hash of the bytes extracted: no path to find
        L.input(tmp_path / "never_there.txt")                        # recorded unhashed (it did not exist then)
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []
    src.unlink()
    shutil.rmtree(store)
    probs = audit.ledger_problems(run)
    assert sorted(probs) == sorted([f"run: stage report: input {src} is missing (the stage read it); restore it, or run `fetch` / the stage again",
                                    f"run: stage report: input {store} is missing (the stage read it); restore it, or run `fetch` / the stage again"])


# ---- review round 10, P-32: a ledger that hashed a shared cache manifest failed every earlier run's audit once the cache grew

def _run_with_manifest_copy(tmp_path, man, copy_to="report/manifest_copy.json"):
    """A run whose report stage recorded `man` the way ingest does: a copy in the run, with where it came from."""
    run = make_run(tmp_path)
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.snapshot(man, run / copy_to, kind="cache manifest")
        (run / "report" / "r.out").write_text("r")                                    # an output in the run's layout: where `_same_place` finds the run
        L.output(run / "report" / "r.out")
    return run


def _orca_cache(tmp_path):
    cache = tmp_path / "cache" / "orca"
    (cache / "hours").mkdir(parents=True)
    parts = {}
    for n in ("wrf_a.npz", "wrf_b.npz"):
        (cache / "hours" / n).write_bytes(n.encode())
        parts[n] = sha256(cache / "hours" / n)
    (cache / "manifest.json").write_text(json.dumps({"hours": 2, "parts": parts}))
    return cache, parts


def test_p32_a_cache_that_only_grew_passes_and_a_changed_part_fails_naming_it(tmp_path):
    cache, parts = _orca_cache(tmp_path)
    run = _run_with_manifest_copy(tmp_path, cache / "manifest.json")
    assert audit.ledger_problems(run) == []
    (cache / "hours" / "wrf_c.npz").write_bytes(b"c")                                 # a later run: one more hour, a rewritten manifest
    (cache / "manifest.json").write_text(json.dumps({"hours": 3, "parts": {**parts, "wrf_c.npz": sha256(cache / "hours" / "wrf_c.npz")}}))
    assert audit.ledger_problems(run) == []                                           # was: input .../manifest.json changed since the stage ran
    (cache / "manifest.json").write_text("[1,2")                                      # the shared manifest is no part of the check, damaged or not
    assert audit.ledger_problems(run) == []
    (cache / "hours" / "wrf_b.npz").write_bytes(b"edited")
    probs = audit.ledger_problems(run)
    assert len(probs) == 1 and f"run: stage report: input {cache / 'hours' / 'wrf_b.npz'} changed since the stage ran" in probs[0]
    assert parts["wrf_b.npz"][:12] in probs[0] and sha256(cache / "hours" / "wrf_b.npz")[:12] in probs[0] and "manifest_copy.json" in probs[0]
    (cache / "hours" / "wrf_b.npz").unlink()
    assert audit.ledger_problems(run) == []                                           # a part that is gone: the stores that were read are inputs of their own


def test_p32_a_tao_file_that_is_gone_or_changed_fails_naming_it_and_a_new_manifest_does_not(tmp_path):
    tdir = tmp_path / "tao" / "s2"
    (tdir / "T0N165W").mkdir(parents=True)
    f = tdir / "T0N165W" / "OS_wind.nc"
    f.write_bytes(b"wind")
    man = tdir / "manifest.json"
    man.write_text(json.dumps({"t0": 0, "t1": 1, "files": {"T0N165W/OS_wind.nc": {"sha256": sha256(f)}}, "selected": {}}))
    run = _run_with_manifest_copy(tmp_path, man)
    assert audit.ledger_problems(run) == []
    man.write_text(json.dumps({"t0": -9, "t1": 9, "files": {}, "selected": {}}))      # another window replaced the list: the file is still there
    assert audit.ledger_problems(run) == []
    f.write_bytes(b"edited")
    assert [x.split(" changed")[0] for x in audit.ledger_problems(run)] == [f"run: stage report: input {f}"]
    f.unlink()
    assert audit.ledger_problems(run) == [f"run: stage report: input {f} is missing (the stage read it, manifest_copy.json lists it); run `fetch` again"]


def test_p32_without_the_cache_directory_a_run_in_its_own_place_is_told_and_a_copied_one_is_checked_by_its_copy(tmp_path, capsys):
    """A deleted or moved cache directory used to audit clean for the run that read it (nothing else hashes the TAO files)."""
    cache, _ = _orca_cache(tmp_path)
    run = _run_with_manifest_copy(tmp_path, cache / "manifest.json")
    copy = tmp_path / "elsewhere" / "run"
    shutil.copytree(run, copy)
    shutil.rmtree(cache)
    gone = f"run: stage report: cache directory {cache} is missing (the stage read manifest_copy.json from it); run `fetch` again"
    assert audit.ledger_problems(run) == [gone]
    capsys.readouterr()
    assert audit.ledger_problems(copy) == []                                          # copied: the machine and place differ from what the ledger says
    assert f"note: run: stage report: cache directory {cache} is not here" in capsys.readouterr().err
    (copy / "report" / "manifest_copy.json").write_text('{"parts": {')
    probs = audit.ledger_problems(copy)
    assert any("manifest_copy.json changed since the stage ran" in x for x in probs) and not any("Traceback" in x for x in probs)


def test_p41_a_ledger_written_on_another_machine_with_no_cache_directory_gives_the_note_and_no_problem(tmp_path, capsys):
    """`_same_place` is False for a host that is not this one even when the run lies where its ledger says: the cache directory it recorded is not this
    machine's to judge (found by the gate's coverage.json: the branch had no test)."""
    cache, _ = _orca_cache(tmp_path)
    run = _run_with_manifest_copy(tmp_path, cache / "manifest.json")
    shutil.rmtree(cache)
    gone = f"run: stage report: cache directory {cache} is missing (the stage read manifest_copy.json from it); run `fetch` again"
    assert audit.ledger_problems(run) == [gone]                                       # this machine, this place: a deleted cache is a problem
    edit(run, "report", lambda d: d["machine"].update(host=platform.node() + "-elsewhere"))
    capsys.readouterr()
    assert audit.ledger_problems(run) == []
    assert f"note: run: stage report: cache directory {cache} is not here; the files manifest_copy.json names were not compared" in capsys.readouterr().err


def test_p32_a_cache_path_recorded_relative_is_judged_where_it_was_not_where_the_audit_runs(tmp_path, monkeypatch):
    """`shared` was stored as given: a data directory that was relative when the run was made was read against the audit's cwd (no directory, no check)."""
    cache, _ = _orca_cache(tmp_path)
    monkeypatch.chdir(tmp_path)
    run = _run_with_manifest_copy(tmp_path, pathlib.Path("cache/orca/manifest.json"))
    assert json.loads(ledger_path(run, "report").read_text())["inputs"][-1]["shared"] == str(cache / "manifest.json")
    monkeypatch.chdir(run)
    assert audit.ledger_problems(run) == []
    (cache / "hours" / "wrf_a.npz").write_bytes(b"edited")
    assert any(f"input {cache / 'hours' / 'wrf_a.npz'} changed since the stage ran" in x for x in audit.ledger_problems(run))


def test_p32_a_damaged_copy_beside_a_cache_is_a_problem_naming_the_copy_not_a_traceback(tmp_path):
    cache, _ = _orca_cache(tmp_path)
    run = _run_with_manifest_copy(tmp_path, cache / "manifest.json")
    (run / "report" / "manifest_copy.json").write_text('{"parts": {')
    probs = audit.ledger_problems(run)
    assert any("manifest_copy.json changed since the stage ran" in x for x in probs)
    assert any(f"input {run / 'report' / 'manifest_copy.json'} is not valid JSON (" in x for x in probs)


def test_p32_a_ledger_without_a_copy_keeps_the_old_check_on_the_shared_manifest(tmp_path):
    cache, parts = _orca_cache(tmp_path)
    run = make_run(tmp_path)
    _report_with_inputs(run, cache / "manifest.json")                                 # a run made before the copy existed
    assert audit.ledger_problems(run) == []
    (cache / "manifest.json").write_text(json.dumps({"hours": 3, "parts": parts}))
    assert audit.ledger_problems(run) == [f"run: stage report: input {cache / 'manifest.json'} changed since the stage ran"]


# ---- look-ahead batch LB0

def _run_with_a_derived_layer(tmp_path, key="key-1"):
    """A run whose report stage read a derived surface layer in the cache, with the record ingest leaves of it (`ingest/derived.digest.json`)."""
    run = make_run(tmp_path)
    store = zstore(tmp_path / "cache" / "derived.zarr", {"built_from": key})
    (store / "ustar").mkdir()
    (store / "ustar" / "0").write_bytes(b"one")
    rec = run / "ingest" / surface.DIGEST
    rec.parent.mkdir(exist_ok=True)
    rec.write_text(json.dumps(dict(built_from=key, store_sha256=surface.store_sha256(store))))
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(store, sha=surface.store_sha256(store), tree=surface.store_sha256(store), kind="derived surface layer")
        L.output(run / "report.out")
    return run, store


def _rebuild(store, key, chunk=b"two"):
    """What a later run's ingest does to the one shared store when its key changed: whole new bytes under another `built_from`."""
    (store / "zarr.json").write_text(json.dumps({"attributes": {"built_from": key}}))
    (store / "ustar" / "0").write_bytes(chunk)


def test_lb0_a_derived_layer_rebuilt_from_another_key_by_a_later_run_is_not_a_problem_of_the_earlier_run(tmp_path):
    """P-34 (derived layer): the key holds the code digest, so after any code change the next run in the data directory rebuilt the one shared store in
    place and the audit of every earlier run said 'input .../derived.zarr changed since the stage ran ... delete it and run `fetch` again', which cannot
    clear it (the rebuild has the new key) and which the report turned into 'the numbers may not be what the stages produced'."""
    run, store = _run_with_a_derived_layer(tmp_path)
    assert audit.ledger_problems(run) == []
    _rebuild(store, "key-2")
    assert audit.ledger_problems(run) == []


def test_lb0_a_derived_layer_edited_under_the_key_the_run_recorded_is_still_a_problem(tmp_path):
    run, store = _run_with_a_derived_layer(tmp_path)
    _rebuild(store, "key-1", b"edited")                                       # the same key, other bytes: damage, not a rebuild
    probs = audit.ledger_problems(run)
    assert len(probs) == 1 and f"input {store} changed since the stage ran (tree " in probs[0]


@pytest.mark.parametrize("record", ["missing", "not_json", "no_key", "key_not_text"])
def test_lb0_without_the_runs_record_of_its_key_a_changed_derived_layer_is_still_a_problem(tmp_path, record):
    """What the run recorded is the only thing that tells a rebuild from damage: where it is missing or unusable the old check stands."""
    run, store = _run_with_a_derived_layer(tmp_path)
    rec = run / "ingest" / surface.DIGEST
    if record == "missing":
        rec.unlink()
    else:
        rec.write_text({"not_json": "{cut", "no_key": "{}", "key_not_text": '{"built_from": 5}'}[record])
    _rebuild(store, "key-2")
    assert any(f"input {store} changed since the stage ran" in p for p in audit.ledger_problems(run))


def test_lb0_only_the_derived_layer_gets_the_rebuild_pass(tmp_path):
    """Another store with a `built_from` of its own that differs is not excused by the record of the derived layer."""
    run, store = _run_with_a_derived_layer(tmp_path)
    other = tmp_path / "cache" / "other.zarr"
    zstore(other, {"built_from": "key-1"})
    (other / "x").write_bytes(b"1")
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(other, sha=surface.store_sha256(other), tree=surface.store_sha256(other))
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []
    (other / "zarr.json").write_text(json.dumps({"attributes": {"built_from": "key-2"}}))
    assert any(f"input {other} changed since the stage ran" in p for p in audit.ledger_problems(run))


@pytest.mark.parametrize("edit", [
    lambda d: d["checks"].append({"name": "a"}),
    lambda d: d.update(inputs=[{"sha256": "x"}]),
    lambda d: d.update(inputs="x"),
    lambda d: d.update(outputs=[{"sha256": "x"}]),
    lambda d: d.update(checks=5),
    lambda d: d.update(outputs=None),
], ids=["check_without_ok", "input_without_ref", "inputs_a_string", "output_without_path", "checks_a_number", "outputs_none"])
def test_lb0_a_ledger_that_is_json_of_the_wrong_shape_is_a_problem_line_not_a_traceback(tmp_path, capsys, edit):
    """RC-1 sibling: only a ledger that is not JSON was a line; `audit --ledgers-only`, the command the report's warning names, ended in a KeyError."""
    run = make_run(tmp_path)
    p = ledger_path(run, "stage1")
    d = json.loads(p.read_text())
    edit(d)
    p.write_text(json.dumps(d))
    probs = audit.ledger_problems(run)
    assert any(f"stage stage1: ledger {p} is damaged or incomplete" in x for x in probs)
    assert not any("chain broken" in x for x in probs)                            # the next stage has nothing to chain to, as for a missing ledger
    assert audit.main(["--ledgers-only", str(run)]) == 1 and "AUDIT FAIL" in capsys.readouterr().out


def test_lb0_the_other_readers_of_the_audit_say_a_damaged_file_is_a_problem(tmp_path, monkeypatch, capsys):
    cov = tmp_path / "coverage.json"
    for bad in ("{cut", "[1]", "{}", '{"files": {"cafe/pm/a.py": {}}}', '{"files": 5}'):
        cov.write_text(bad)
        probs = audit.coverage_problems(cov)
        assert len(probs) == 1 and probs[0].startswith(f"coverage: {cov} is damaged or incomplete"), bad
    root = mut_root(tmp_path)
    store(root, monkeypatch)
    mut = root / audit.MUTATION_FILE
    good = mut.read_text()
    assert audit.mutation_problems(root) == []
    for bad in ("{cut", "[1]"):
        mut.write_text(bad)
        probs = audit.mutation_problems(root)
        assert len(probs) == 1 and f"mutation: {audit.MUTATION_FILE} is damaged or incomplete" in probs[0], bad
    rec = json.loads(good)
    del rec["total"]
    mut.write_text(json.dumps(rec))
    assert "is damaged or incomplete (KeyError" in audit.mutation_problems(root)[0]
    mut.write_text(json.dumps(dict(rec, total="x", killed=1)))
    assert "is damaged or incomplete" in audit.mutation_problems(root)[0]
    monkeypatch.setattr(audit, "ROOT", root)                                       # `--mutation-record` from mutmut's counts that are cut short
    (root / audit.MUTATION_STATS).write_text("{cut")
    capsys.readouterr()
    assert audit.main(["--mutation-record"]) == 2 and f"error: {audit.MUTATION_STATS} cannot be used" in capsys.readouterr().out
    (root / audit.MUTATION_STATS).write_text("{}")
    assert audit.main(["--mutation-record"]) == 2 and "KeyError" in capsys.readouterr().out


# ---- round 11, P-34: the stores a later run rewrites whole are told from damage, not blamed on the earlier run

REBUILT = "the bytes this run read were replaced by a later fetch, and this run can no longer be re-checked against them"


def _run_with_shared_stores(tmp_path):
    """A run whose report stage recorded, as ingest does, an orca store (tree hash, and the copy of the orca manifest it was assembled with in
    `ingest/orca_manifest.json`) and an ocean store (the `manifest_sha256` it carries, and its tree hash)."""
    from cafe.pm.env.remote import tree_sha256
    run = make_run(tmp_path)
    cache = tmp_path / "cache" / "orca"
    orca = zstore(cache / "wrf.zarr", {"source": "x"})
    (orca / "WSPD").mkdir()
    (orca / "WSPD" / "0").write_bytes(b"one")
    (cache / "manifest.json").write_text(json.dumps({"hours": 2, "parts": {}}))
    ocean = zstore(tmp_path / "ocean" / "gofs_x.zarr", {"manifest_sha256": "a" * 64})
    (ocean / "water_u").mkdir()
    (ocean / "water_u" / "0").write_bytes(b"one")
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.snapshot(cache / "manifest.json", run / "ingest" / "orca_manifest.json", kind="orca cache manifest")
        L.input(orca, sha=tree_sha256(orca), tree=tree_sha256(orca))
        L.input(ocean, sha="a" * 64, tree=tree_sha256(ocean))
        L.output(run / "report.out")
    return run, orca, ocean


def _rewrite_orca(orca, chunk=b"two"):
    """What a later `orca.assemble` does: the stores whole, then the manifest."""
    (orca / "WSPD" / "0").write_bytes(chunk)
    (orca.parent / "manifest.json").write_text(json.dumps({"hours": 3, "parts": {}}))


def _rewrite_ocean(ocean, manifest="b" * 64, chunk=b"two"):
    """What a later `fetch_gofs` does: the store whole, with the hash of the parts manifest it was made from."""
    (ocean / "zarr.json").write_text(json.dumps({"attributes": {"manifest_sha256": manifest}}))
    (ocean / "water_u" / "0").write_bytes(chunk)


def test_p34_orca_and_ocean_stores_rewritten_by_a_later_run_are_a_note_and_never_the_advice_to_delete(tmp_path, capsys):
    run, orca, ocean = _run_with_shared_stores(tmp_path)
    assert audit.ledger_problems(run) == []
    assert capsys.readouterr().err == ""
    _rewrite_orca(orca)
    _rewrite_ocean(ocean)
    assert audit.ledger_problems(run) == []                                           # was: input .../wrf.zarr changed ... delete it and run `fetch` again
    err = capsys.readouterr().err
    assert sorted(err.splitlines()) == sorted(f"note: run: stage report: input {s}: {REBUILT} (what the run made is checked by its own ledgers)"
                                              for s in (orca, ocean))
    assert "delete" not in err


def test_p34_a_store_changed_with_no_later_rebuild_is_still_a_problem_and_still_says_to_fetch_again(tmp_path):
    run, orca, ocean = _run_with_shared_stores(tmp_path)
    (orca / "WSPD" / "0").write_bytes(b"edited")                                      # the manifest is the one the run kept: nobody assembled again
    (ocean / "water_u" / "0").write_bytes(b"edited")                                  # the attribute is the one the ledger has: nobody fetched again
    probs = audit.ledger_problems(run)
    assert sorted(x.split(" changed")[0] for x in probs) == sorted(f"run: stage report: input {s}" for s in (orca, ocean))
    assert all("(tree " in x and "delete it and run `fetch` again" in x for x in probs)


def test_p34_a_rebuild_is_judged_by_what_the_run_kept_and_without_it_the_change_stays_a_problem(tmp_path, capsys):
    """Same-key damage after a rebuild cannot be told, but a copy that is gone or a manifest that is gone is no evidence of a rebuild."""
    run, orca, ocean = _run_with_shared_stores(tmp_path)
    _rewrite_orca(orca)
    _rewrite_ocean(ocean, manifest="a" * 64)                                          # this ocean store has the key the run recorded: bytes only
    assert [x.split(" changed")[0] for x in audit.ledger_problems(run)] == [f"run: stage report: input {ocean}"]
    kept = run / "ingest" / "orca_manifest.json"
    was = kept.read_bytes()
    kept.unlink()
    assert any(f"input {orca} changed since the stage ran (tree " in x for x in audit.ledger_problems(run))
    kept.write_bytes(was)
    (orca.parent / "manifest.json").unlink()                                          # an assemble that was cut short: the stores are half new
    assert any(f"input {orca} changed since the stage ran (tree " in x for x in audit.ledger_problems(run))


def test_p34_a_ledger_without_the_tree_hash_keeps_the_manifest_line_for_an_ocean_store(tmp_path):
    run = make_run(tmp_path)
    ocean = zstore(tmp_path / "gofs.zarr", {"manifest_sha256": "a" * 64})
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.input(ocean, sha="a" * 64)
        L.output(run / "report.out")
    (ocean / "zarr.json").write_text(json.dumps({"attributes": {"manifest_sha256": "b" * 64}}))
    assert [x for x in audit.ledger_problems(run) if "store manifest bbbbbbbbbbbb, ledger aaaaaaaaaaaa" in x]


def test_p34_the_derived_layer_rebuilt_by_a_later_run_gets_the_same_note(tmp_path, capsys):
    run, store = _run_with_a_derived_layer(tmp_path)
    capsys.readouterr()
    _rebuild(store, "key-2")
    assert audit.ledger_problems(run) == []
    assert f"note: run: stage report: input {store}: {REBUILT}" in capsys.readouterr().err


# ---------------------------------------------------------------------------------------------------------------- review round 11, M-2

def make_recorded_run(tmp_path):
    """make_run with what the report stage records since round 11: the run's mission.yaml and plan.json by their bare names."""
    run = make_run(tmp_path)
    (run / "mission.yaml").write_text("verdict: {go: 0.9, nogo: 0.6}\n")
    (run / "plan.json").write_text('{"workers": 2}')
    p = ledger_path(run, "report")
    d = json.loads(p.read_text())
    d["inputs"] += [dict(ref=n, sha256=sha256(run / n)) for n in ledger.RUN_ROOT_FILES]
    p.write_text(json.dumps(d))
    return run


@pytest.mark.parametrize("name, text", [("mission.yaml", "verdict: {go: 0.2, nogo: 0.1}\n"), ("plan.json", '{"workers": 2} ')])
def test_r11_m2_an_edit_of_the_runs_mission_or_plan_is_an_audit_problem(tmp_path, name, text):
    run = make_recorded_run(tmp_path)
    assert audit.ledger_problems(run) == []
    (run / name).write_text(text)
    assert any(f"stage report: input {run / name} changed since the stage ran" in p for p in audit.ledger_problems(run))


def test_r11_m2_a_copy_of_the_run_finds_its_own_mission_and_plan(tmp_path):
    run = make_recorded_run(tmp_path / "a")
    copy = tmp_path / "b" / "run"
    shutil.copytree(run, copy)
    assert audit.ledger_problems(copy) == []
    (copy / "plan.json").write_text("{}")
    assert any(f"input {copy / 'plan.json'} changed" in p for p in audit.ledger_problems(copy))
    assert audit.ledger_problems(run) == []                                           # the original is not borrowed for the copy's file
    assert ledger.resolve("plan.json", tmp_path / "renamed", set()) == tmp_path / "renamed" / "plan.json"      # by its bare name, whatever the run is called


def test_r11_m2_a_run_from_before_the_record_is_clean_and_the_audit_says_what_it_cannot_see(tmp_path, capsys):
    run = make_run(tmp_path)
    assert audit.ledger_problems(run) == [] and audit.root_files_unrecorded(run)
    assert not audit.root_files_unrecorded(make_recorded_run(tmp_path / "x"))
    capsys.readouterr()
    assert audit.main(["--ledgers-only", str(run)]) == 0
    assert "records neither mission.yaml nor plan.json" in capsys.readouterr().out


def test_r11_m25_a_ledger_whose_machine_block_is_not_a_mapping_is_a_damaged_line_not_a_traceback(tmp_path):
    """`_same_place` calls `.get` on the ledger's `machine`; of the three types `ledger_problems` catches this is the AttributeError one."""
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "manifest.json").write_text("{}")
    run = make_run(tmp_path)
    snap = run / "ingest" / "m.json"
    snap.parent.mkdir(exist_ok=True)
    with Ledger(run, "report", "cfg") as L:
        L.input(ledger_path(run, "emulator"))
        L.snapshot(cache / "manifest.json", snap)
        L.output(run / "report.out")
    assert audit.ledger_problems(run) == []
    edit(run, "report", lambda d: d.update(machine="x"))
    probs = audit.ledger_problems(run)
    assert len(probs) == 1 and "stage report: ledger" in probs[0] and "is damaged or incomplete (AttributeError" in probs[0]


def test_r11_m25_a_coverage_file_with_a_summary_that_is_not_a_mapping_is_a_damaged_line_too(tmp_path):
    """The other three types of `coverage_problems`' tuple are cases of test_lb0_...; a `summary` of 5 is the TypeError one."""
    cov = tmp_path / "coverage.json"
    cov.write_text('{"files": {"cafe/pm/a.py": {"summary": 5}}}')
    probs = audit.coverage_problems(cov)
    assert len(probs) == 1 and probs[0].startswith(f"coverage: {cov} is damaged or incomplete (TypeError")


# ---------------------------------------------------------------------------------------------------------------- round 13 pre-pass, P-R12Q3

def run_with_hangar_inputs(tmp_path, names):
    """A run whose hangar ledger lists the files `names` under platforms/, as `pipeline.s_hangar` lists the vehicle platforms and (635) the link tables."""
    files = []
    for n in names:
        f = tmp_path / "platforms" / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(n)
        files.append(f)
    return make_run(tmp_path, extra_inputs={"hangar": files})


def test_r13_q3_a_run_whose_hangar_ledger_has_no_link_table_gets_a_note_and_stays_clean(tmp_path, capsys):
    """DECISIONS 635: an edit of platforms/radios.yaml or modems.yaml after a run from before it is invisible to the audit; 594's note for mission.yaml and
    plan.json is the form, so the blind spot is said, not silent (P-R12Q3). A note, not a problem: exit 0."""
    run = make_recorded_run(tmp_path)
    assert audit.ledger_problems(run) == [] and audit.link_tables_unrecorded(run) == ["radios.yaml", "modems.yaml"]
    capsys.readouterr()
    assert audit.main(["--ledgers-only", str(run)]) == 0
    out = capsys.readouterr().out
    for n in ("radios.yaml", "modems.yaml"):
        assert f"note: {run}: the hangar ledger does not record platforms/{n}" in out
    assert "records neither mission.yaml nor plan.json" not in out and "problem" not in out.replace("0 problem(s)", "")


def test_r13_q3_a_run_that_records_the_link_tables_gets_no_note_and_each_note_stands_alone(tmp_path, capsys):
    run = run_with_hangar_inputs(tmp_path, ("seaglider.yaml", *comms.PARAMETER_FILES))
    assert audit.ledger_problems(run) == [] and audit.link_tables_unrecorded(run) == []
    capsys.readouterr()
    assert audit.main(["--ledgers-only", str(run)]) == 0
    out = capsys.readouterr().out
    assert "hangar ledger does not record" not in out and "report ledger records neither" in out                  # each note is decided by its own ledger
    old = make_run(tmp_path / "old")                                                  # neither kind recorded: both notes, in this order
    assert audit.main(["--ledgers-only", str(old)]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("note:")]
    assert len(lines) == 3 and "mission.yaml nor plan.json" in lines[0] and "platforms/radios.yaml" in lines[1] and "platforms/modems.yaml" in lines[2]


def test_r13_q3_the_note_names_the_tables_the_hangar_stage_records(tmp_path):
    """The names the note looks for are `comms.PARAMETER_FILES`, the ones `s_hangar` records, so a third table added there is looked for here too."""
    for n in comms.PARAMETER_FILES:
        assert n not in audit.link_tables_unrecorded(run_with_hangar_inputs(tmp_path / n, (n,)))
    only_vehicle = run_with_hangar_inputs(tmp_path / "v", ("seaglider.yaml",))            # a vehicle platform is not a link table
    assert audit.link_tables_unrecorded(only_vehicle) == list(comms.PARAMETER_FILES)


@pytest.mark.parametrize("ledger_text", ['{"inputs": 5}', '{"inputs": null}', "{cut", "[1]", None])
def test_r13_q3_a_hangar_ledger_that_cannot_be_read_is_no_old_run_either(tmp_path, ledger_text):
    run = make_run(tmp_path)
    p = ledger_path(run, "hangar")
    if ledger_text is None:
        p.unlink()
    else:
        p.write_text(ledger_text)
    assert audit.link_tables_unrecorded(run) == []


@pytest.mark.parametrize("ledger_text", ['{"inputs": 5}', '{"inputs": null}', "{cut", "[1]", None])
def test_r11_m25_a_report_ledger_that_cannot_be_read_is_not_a_run_from_before_the_record(tmp_path, ledger_text):
    """`root_files_unrecorded` is a note about a readable ledger; an unreadable one (`ledger_problems` names it), a missing one and one whose `inputs` is no
    list say nothing."""
    run = make_run(tmp_path)
    p = ledger_path(run, "report")
    if ledger_text is None:
        p.unlink()
    else:
        p.write_text(ledger_text)
    assert audit.root_files_unrecorded(run) is False


@pytest.mark.parametrize("where", ["platforms/p.yaml", "config/c.yaml", "missions/m.yaml", "cafe/schemas/s.json", "tests/golden/g.json", "tests/fixtures/f.nc",
                                   "cafe/receipts.py", "cafe/mission.py", "bench/throughput.py", "pyproject.toml"])      # L0, second pass
def test_l0_r11_a_data_file_the_suite_reads_edited_after_the_receipt_makes_it_stale(tmp_path, monkeypatch, capsys, where):
    """The digest hashed only the .py files, so a platform, config or mission file (or a golden or fixture) changed after a green suite passed --pytest-done."""
    monkeypatch.setattr(audit, "_run", lambda cmd: (0, ""))
    pytest_done_root(tmp_path, monkeypatch)
    f = tmp_path / where
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("a: 1\n")
    audit.write_pytest_receipt(tmp_path)
    (tmp_path / "platforms").mkdir(exist_ok=True)
    (tmp_path / "platforms" / ".DS_Store").write_bytes(b"finder")                       # not a file of the suite
    assert audit.coverage_stale(tmp_path) == []
    edit_keeping_mtime(f, "a: 2\n")                                                      # rsync -a puts the time back
    (said,) = audit.coverage_stale(tmp_path)
    assert "differs from what the suite ran on" in said and "platforms" in said
    assert audit.main(["--pytest-done"]) == 1
    assert "differs from what the suite ran on" in capsys.readouterr().out
    f.write_text("a: 1\n")
    assert audit.coverage_stale(tmp_path) == []
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "new.yaml").write_text("b: 1\n")                              # a file added after the run is a change, too
    assert audit.coverage_stale(tmp_path) != []


def test_r13_m21_a_symlink_loop_in_a_run_is_a_problem_line_not_a_runtime_error(tmp_path, capsys):
    """`Path.resolve()` raises RuntimeError on a loop (Python 3.12): a stage that read a path through a self-loop link ended audit and report in a traceback."""
    run = make_run(tmp_path)
    (run / "loop").symlink_to(run / "loop")
    edit(run, "report", lambda d: d["inputs"].append(dict(ref=str(run / "loop" / "x"))))              # the last stage: nothing chains to its ledger
    assert audit.ledger_problems(run) == []                                         # the loop is read as an absent file, not a crash, and it was never hashed
    edit(run, "report", lambda d: d["inputs"].append(dict(ref=str(run / "loop" / "y"), sha256="0" * 64)))
    (said,) = audit.ledger_problems(run)
    assert "stage report: input" in said and "is missing" in said
    assert audit.main(["--ledgers-only", str(run)]) == 1
    assert "is missing" in capsys.readouterr().out


def test_r13_l1_a_file_named_like_a_link_table_but_not_in_platforms_is_not_the_table(tmp_path, capsys):
    """P-R13L1 (a): the match was by file name only, so an input called radios.yaml from anywhere hid the note; the consumer reads `platforms/<name>`."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    for n in comms.PARAMETER_FILES:
        (elsewhere / n).write_text(n)
    run = make_run(tmp_path / "r", extra_inputs={"hangar": [elsewhere / n for n in comms.PARAMETER_FILES]})
    assert audit.link_tables_unrecorded(run) == ["radios.yaml", "modems.yaml"]
    capsys.readouterr()
    assert audit.main(["--ledgers-only", str(run)]) == 0
    assert capsys.readouterr().out.count("the hangar ledger does not record platforms/") == 2


def test_r13_l1_a_run_that_records_one_table_and_not_the_other_gets_the_note_for_the_other(tmp_path, capsys):
    """P-R13L1 (b): the note asked whether any table was recorded; a run with radios.yaml and without modems.yaml got none."""
    run = run_with_hangar_inputs(tmp_path, ("radios.yaml",))
    assert audit.link_tables_unrecorded(run) == ["modems.yaml"]
    capsys.readouterr()
    assert audit.main(["--ledgers-only", str(run)]) == 0
    out = capsys.readouterr().out
    assert "does not record platforms/modems.yaml" in out and "does not record platforms/radios.yaml" not in out
    run = run_with_hangar_inputs(tmp_path / "other", ("modems.yaml",))
    assert audit.link_tables_unrecorded(run) == ["radios.yaml"]


def test_r13_l1_a_table_input_without_a_sha256_is_not_recorded(tmp_path):
    """The hangar stage records `sha256 = None` for a file that was not there: nothing to compare an edit with."""
    run = run_with_hangar_inputs(tmp_path, comms.PARAMETER_FILES)
    assert audit.link_tables_unrecorded(run) == []
    edit(run, "hangar", lambda d: [i.update(sha256=None) for i in d["inputs"] if i["ref"].endswith("modems.yaml")])
    assert audit.link_tables_unrecorded(run) == ["modems.yaml"]


def test_r13_sweep_a_cut_write_leaves_the_old_pytest_receipt_and_mutation_record(tmp_path, monkeypatch, cut_writes):
    """Round 13, M-17 sibling: both records were written in place, so a disk that filled mid-write left three characters that `mutation_problems` and
    `--pytest-done` then read as a damaged record. Whole or not at all, newline kept."""
    pytest_done_root(tmp_path, monkeypatch)
    receipt = tmp_path / audit.PYTEST_RECEIPT
    before = receipt.read_bytes()
    assert before.endswith(b"}\n")
    cut_writes()
    with pytest.raises(OSError, match="killed"):
        audit.write_pytest_receipt(tmp_path)
    assert receipt.read_bytes() == before and not list(receipt.parent.glob("*.tmp"))
    monkeypatch.undo()
    root = mut_root(tmp_path / "m")
    monkeypatch.setattr(audit, "ROOT", root)
    (root / "docs").mkdir()
    assert audit.main(["--mutation-record"]) == 0
    record = root / audit.MUTATION_FILE
    before = record.read_bytes()
    assert before.endswith(b"}\n")
    cut_writes()
    with pytest.raises(OSError, match="killed"):
        audit.main(["--mutation-record"])
    assert record.read_bytes() == before and not list(record.parent.glob("*.tmp"))
