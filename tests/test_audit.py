"""cafe.pm.audit: broken ledgers, banned tokens and commented-out code are all caught; rulers and prose are not."""
import json
import runpy
import sys

import pytest

from cafe.pm import audit
from cafe.pm.ledger import Ledger


def make_run(tmp_path, stages=audit.STAGES):
    """A run dir whose ledgers chain the way pipeline.py writes them: each stage lists the previous stage's ledger as an input."""
    run = tmp_path / "run"
    prev = None
    for st in stages:
        out = run / f"{st}.out"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(st)
        with Ledger(run, st, "cfg") as L:
            if prev is not None:
                L.input(prev)
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
    monkeypatch.setattr(audit, "_run", lambda cmd: pytest.fail("--code-only must not run the tools"))
    assert audit.main([str(run), "--code-only"]) == 1
    out = capsys.readouterr().out
    assert "AUDIT FAIL: run: stage report: no ledger" in out and "AUDIT FAIL: cafe/pm/x.py:1" in out and "audit: 2 problem(s)" in out


def test_main_runs_ruff_mypy_pytest_and_the_coverage_gates(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "ROOT", tmp_path)

    def fake(cmd):
        calls.append(cmd[0] if cmd[0] != sys.executable else "pytest")
        return (1, f"{cmd[0]} failed") if cmd[0] in ("ruff", "mypy") else (0, "")
    monkeypatch.setattr(audit, "_run", fake)
    cov(tmp_path, {"cafe/pm/a.py": (10, 1)})
    assert audit.main([]) == 1
    out = capsys.readouterr().out
    assert calls == ["ruff", "mypy", "pytest"] and "AUDIT FAIL: ruff:\nruff failed" in out and "AUDIT FAIL: mypy:" in out
    assert "coverage cafe/pm: 10.0 % < 90 %" in out and "audit: 3 problem(s)" in out
    monkeypatch.setattr(audit, "_run", lambda cmd: (1, "pytest output") if cmd[0] == sys.executable else (0, ""))
    (tmp_path / "coverage.json").unlink()
    assert audit.main([]) == 1 and "AUDIT FAIL: pytest:\npytest output" in capsys.readouterr().out


def test_main_is_clean_when_everything_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audit, "banned", lambda: [])
    monkeypatch.setattr(audit, "_run", lambda cmd: (0, ""))
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    assert audit.main([str(make_run(tmp_path))]) == 0 and "audit: 0 problem(s)" in capsys.readouterr().out


def test_module_entry_point_exits_with_the_audit_status(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["audit", "--code-only"])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("cafe.pm.audit", run_name="__main__")
    assert e.value.code in (0, 1)
