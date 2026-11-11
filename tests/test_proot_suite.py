"""bin/proot_suite.sh (the worker side) and bin/orca_gate.sh (the laptop side) of the suite on orca, with a stand-in for proot_run.sh."""
import os
import signal
import stat
import subprocess
import sys
import time

import pytest

from cafe.pm import audit, config

ROOT = config.ROOT

STUB = r"""#!/bin/sh
# stands for bin/proot_run.sh: `proot_run.sh <dir> <command...>`. Logs the call; the shares step really runs (paths of /data mapped to pmdata).
D=$1; shift
[ -z "${FAKE_PARTIAL:-}" ] || printf 'half a line'
n=$(echo "$*" | sed -n 's#.*@/data/shards/[^/]*/\(s[0-9]*\|serial\)\.args.*#\1#p')
echo "$*" >> "$HOME/calls.log"
echo "${PM_CPUS:-unset} ${PM_THREADS:-unset}" >> "$HOME/threads.log"
[ -z "$n" ] || echo "start $n $(date +%s.%N)" >> "$HOME/calls.log"
trap 'kill $(jobs -p) 2>/dev/null; echo "term $n" >> "$HOME/calls.log"; exit 143' TERM
case "$*" in *"${FAKE_FAIL:-no match at all}"*) echo "boom"; exit 1 ;; esac
case "$*" in *"${FAKE_HANG:-no match at all}"*) echo "hang $*" >> "$HOME/calls.log"; sleep 30 & wait $!; exit 0 ;; esac
case "$*" in
  *cafe.pm.shares*)
    shift; for a in "$@"; do case "$a" in /data/*) a="$HOME/cafe-worker/cafe/pmdata/${a#/data/}" ;; esac; set -- "$@" "$a"; shift; done
    cd "$REPO" && exec "$PYTHON" "$@" ;;
esac
if [ -n "${FAKE_SLEEP:-}" ] && [ -n "$n" ]; then sleep "$FAKE_SLEEP" & wait $!; fi
[ -z "$n" ] || echo "end $n $(date +%s.%N)" >> "$HOME/calls.log"
x=$(echo "$*" | sed -n 's#.*--junitxml=/data/\([^ ]*\) .*#\1#p')
case "$n" in "${FAKE_NOJUNIT:-no match}") x= ;; esac
j="<testsuites><testsuite name=\"pytest\" errors=\"0\" failures=\"${FAKE_JUNIT_FAILURES:-0}\" tests=\"3\"></testsuite></testsuites>"
[ -z "$x" ] || echo "$j" > "$HOME/cafe-worker/cafe/pmdata/$x"
exit 0
"""


def world(tmp_path, tag="t1"):
    """(home, env, calls): a scratch HOME with a cafe-worker marker, the checkout's dir pm_t with the stand-in proot_run.sh, and pmdata."""
    home = tmp_path / "home"
    c = home / "cafe-worker" / "cafe"
    (c / "pm_t" / "bin").mkdir(parents=True)
    (c / "pmdata").mkdir()
    (c / "pm_t" / "bin" / "proot_run.sh").write_text(STUB)
    (home / "cafe-worker" / ".cafe-worker-owned").write_text("")
    env = {**os.environ, "HOME": str(home), "REPO": str(ROOT), "PYTHON": sys.executable}
    return home, env, home / "calls.log"


def suite(env, *args, **kw):
    return subprocess.run(["sh", str(ROOT / "bin/proot_suite.sh"), *args], env=env, capture_output=True, text=True, timeout=120, **kw)


def calls(path):
    return path.read_text().splitlines() if path.exists() else []


def test_k_shares_run_at_once_each_one_pytest_process_with_its_own_junit_log_and_argument_file_then_the_serial_tests(tmp_path):
    home, env, log = world(tmp_path)
    r = suite({**env, "FAKE_SLEEP": "1"}, "pm_t", "3", "t1")
    assert r.returncode == 0 and "suite ok: 3 shares and the serial tests" in r.stdout, r.stdout + r.stderr
    assert "s3: " in r.stdout and "rc=" not in r.stdout                                  # the shares' plan; not the rc= of the shares log
    lines = calls(log)
    assert lines[0].startswith("python -m cafe.pm.shares 3 /data/shards/t1")
    pytests = sorted((l for l in lines if l.startswith("python -m pytest")), key=lambda l: l.split("@")[-1])                 # they run at once: in no set order
    assert len(pytests) == 4
    for i, l in enumerate(pytests[:3], 1):
        assert f"-p no:cacheprovider -vv -m not network --junitxml=/data/shards/t1/s{i}.xml @/data/shards/t1/s{i}.args" in l
        assert "-n " not in l and "--cov" not in l
    assert "--junitxml=/data/shards/t1/serial.xml @/data/shards/t1/serial.args" in pytests[3]
    stamps = {(l.split()[0], l.split()[1]): float(l.split()[2]) for l in lines if l.startswith(("start ", "end "))}
    assert max(stamps[("start", f"s{i}")] for i in (1, 2, 3)) < min(stamps[("end", f"s{i}")] for i in (1, 2, 3))          # all three ran at the same time
    assert stamps[("start", "serial")] > max(stamps[("end", f"s{i}")] for i in (1, 2, 3))                  # and the serial tests after all of them
    logs = home / "cafe-worker/logs"
    assert sorted(p.name for p in logs.iterdir()) == ["t1_s1.log", "t1_s2.log", "t1_s3.log", "t1_serial.log", "t1_shares.log"]
    assert all(p.read_text().endswith("rc=0\n") for p in logs.iterdir())
    shards = home / "cafe-worker/cafe/pmdata/shards/t1"
    assert sorted(p.name for p in shards.iterdir() if p.name != ".start") == [f"{n}.{x}" for n in ("s1", "s2", "s3", "serial") for x in ("args", "xml")]
    every = [l for i in (1, 2, 3) for l in (shards / f"s{i}.args").read_text().splitlines() if not l.startswith("--")]
    assert sorted(every) == sorted(f"tests/{p.name}" for p in (ROOT / "tests").glob("test_*.py"))                        # every test file in exactly one share
    assert (shards / "serial.args").read_text().splitlines() == list(audit.SERIAL_TESTS)


def test_every_job_gets_its_cpus_as_its_thread_cap(tmp_path):
    """Orca-go P-20: 8 jobs of 2 CPUs were at 29 of 32 CPUs because each library started a pool for the 64 CPUs nproc shows."""
    home, env, log = world(tmp_path)
    assert suite({**env, "PM_THREADS": "9"}, "pm_t", "3", "t1", "--cov").returncode == 0   # one the caller set is not passed on
    seen = (home / "threads.log").read_text().splitlines()
    assert len(seen) == 1 + 3 + 1 + 1 and set(seen) == {"2 2"}                                                           # shares step, 3 shares, serial, audit


def test_a_failed_job_is_named_the_others_and_the_serial_tests_still_run_and_the_exit_is_nonzero(tmp_path):
    home, env, log = world(tmp_path)
    r = suite({**env, "FAKE_FAIL": "s2.args"}, "pm_t", "3", "t1")
    assert r.returncode == 1 and "FAILED: s2(rc=1)" in r.stdout and "suite ok" not in r.stdout
    assert (home / "cafe-worker/logs/t1_s2.log").read_text() == "boom\nrc=1\n" and (home / "cafe-worker/logs/t1_s1.log").read_text() == "rc=0\n"
    assert any("serial.args" in l for l in calls(log))
    r = suite({**env, "FAKE_FAIL": "serial.args"}, "pm_t", "2", "t2")
    assert r.returncode == 1 and "FAILED: serial(rc=1)" in r.stdout
    r = suite({**env, "FAKE_FAIL": "cafe.pm.shares"}, "pm_t", "2", "t3")
    assert r.returncode == 1 and "the shares step failed" in r.stderr and not [l for l in calls(log) if "pytest" in l and "t3" in l]


def test_a_job_that_ends_with_rc_0_but_a_junit_file_with_failures_or_none_is_not_a_pass(tmp_path):
    """Round 9 orca-go P-18: the exit status of a share (s2) was 0 with "1 failed" in its own output; the gate would have said ok."""
    home, env, log = world(tmp_path)
    r = suite({**env, "FAKE_JUNIT_FAILURES": "1"}, "pm_t", "2", "t1")
    assert r.returncode == 1 and "FAILED: s1(rc=0, but its junit file says 1 failed, 0 errors) s2(rc=0, but its junit file says 1 failed, 0 errors)" in r.stdout
    assert "serial(rc=0, but its junit file says 1 failed" in r.stdout and "suite ok" not in r.stdout
    r = suite({**env, "FAKE_NOJUNIT": "s2"}, "pm_t", "2", "t2")
    assert r.returncode == 1 and "FAILED: s2(rc=0, but no new junit file)" in r.stdout
    old = home / "cafe-worker/cafe/pmdata/shards/t3"
    old.mkdir(parents=True)
    (old / "s1.xml").write_text('<testsuites><testsuite errors="0" failures="0"></testsuite></testsuites>')       # a clean one from an earlier run
    os.utime(old / "s1.xml", (1_000_000, 1_000_000))
    r = suite({**env, "FAKE_NOJUNIT": "s1"}, "pm_t", "1", "t3")
    assert r.returncode == 1 and "FAILED: s1(rc=0, but no new junit file)" in r.stdout


def test_with_cov_each_job_has_its_own_coverage_file_and_the_combined_json_and_the_audit_follow_a_clean_run_only(tmp_path):
    home, env, log = world(tmp_path)
    stale = home / "cafe-worker/cafe/pm_t/coverage.json"
    stale.write_text("{}")
    old_receipt = home / "cafe-worker/cafe/pm_t/coverage.receipt.json"
    old_receipt.write_text("{}")
    r = suite(env, "pm_t", "2", "t1", "--cov")
    assert r.returncode == 0 and "coverage and audit" in r.stdout and not stale.exists()                          # an old coverage.json is not this run's
    assert not old_receipt.exists()                                                                               # nor an old receipt (round 11, M-10)
    lines = calls(log)
    s1 = [l for l in lines if "@/data/shards/t1/s1.args" in l][0]
    assert s1.startswith("env COVERAGE_FILE=/data/shards/t1/.coverage.s1 python -m pytest") and "--cov=cafe/pm --cov-report=" in s1
    assert "COVERAGE_FILE=/data/shards/t1/.coverage.serial" in [l for l in lines if "serial.args" in l][0]
    last = log.read_text().split("sh -c ")[-1]                                                                   # the script has two lines
    assert "coverage combine --keep" in last and "coverage json" in last and "python -m cafe.pm.audit --pytest-done" in last
    assert last.index("audit --pytest-receipt") < last.index("audit --pytest-done")        # the receipt first
    assert last.rstrip().endswith("x /data/shards/t1")
    assert (home / "cafe-worker/logs/t1_audit.log").read_text().endswith("rc=0\n")
    r = suite({**env, "FAKE_FAIL": "s1.args"}, "pm_t", "2", "t2", "--cov")
    assert r.returncode == 1 and "FAILED: s1(rc=1)" in r.stdout and "coverage and audit not run" in r.stdout
    assert not (home / "cafe-worker/logs/t2_audit.log").exists()
    r = suite({**env, "FAKE_FAIL": "audit"}, "pm_t", "2", "t3", "--cov")
    assert r.returncode == 1 and "FAILED: audit(rc=1)" in r.stdout


def test_the_second_run_with_a_tag_balances_by_the_junit_of_the_first_and_drops_the_shares_of_a_larger_k(tmp_path):
    home, env, log = world(tmp_path)
    assert suite(env, "pm_t", "3", "t1").returncode == 0
    shards = home / "cafe-worker/cafe/pmdata/shards/t1"
    for i in (1, 2, 3):
        (shards / f"s{i}.xml").write_text('<testsuites><testsuite><testcase classname="tests.test_x" name="t" time="1"/></testsuite></testsuites>')
        os.utime(shards / f"s{i}.xml", (1_000_000 + i, 1_000_000 + i))                                       # oldest first is the order they are read in
    log.unlink()
    assert suite(env, "pm_t", "2", "t1").returncode == 0
    first = "python -m cafe.pm.shares 2 /data/shards/t1 /data/shards/t1/s1.xml /data/shards/t1/s2.xml /data/shards/t1/s3.xml"
    assert calls(log)[0].startswith(first)                                                 # this tag's junit files are the input
    assert sorted(p.name for p in shards.glob("s*.*")) == ["s1.args", "s1.xml", "s2.args", "s2.xml", "serial.args", "serial.xml"]   # s3's goes with its share
    assert not (shards / ".pid").exists()


def test_a_smaller_k_removes_the_old_logs_of_the_shares_beyond_it_of_this_tag_only(tmp_path):
    """P-30: after K=12, a run with K=8 left t1_s9.log to t1_s12.log, each ending rc=0, and a wait loop on rc= in t1_s*.log ended at once."""
    home, env, _ = world(tmp_path)
    assert suite(env, "pm_t", "3", "t1").returncode == 0
    logs = home / "cafe-worker/logs"
    others = ["t1_s3_s5.log", "t2_s9.log", "t1_audit.log", "t1_sx.log", "t1_s.log"]    # t1_s3's share 5, t2's, the audit log, names that are no share's
    for n in ["t1_s9.log", "t1_s12.log", *others]:
        (logs / n).write_text("boom\nrc=0\n")
    r = suite(env, "pm_t", "2", "t1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert sorted(p.name for p in logs.iterdir()) == sorted(["t1_s1.log", "t1_s2.log", "t1_serial.log", "t1_shares.log", *others])    # s3, s9 and s12 are gone
    assert all(p.read_text().endswith("rc=0\n") for p in logs.iterdir())


@pytest.mark.parametrize("args", [("pm_t", "17", "t"), ("pm_t", "0", "t"), ("pm_t", "08", "t"), ("pm_t", "x", "t"), ("pm_t", "2", "a/b"), ("pm_t", "2", ""),
                                  ("pm_t", "2", "t", "--cove"), ("pm_t", "2", "t", "--cov", "x"), ("pmdata", "2", "t"), ("pm_", "2", "t"), ("pm_a/b", "2", "t"),
                                  ("pm_t", "2"), ()])
def test_wrong_arguments_are_refused_before_anything_runs(tmp_path, args):
    home, env, log = world(tmp_path)
    r = suite(env, *args)
    assert r.returncode == 2 and not log.exists() and not (home / "cafe-worker/logs").exists()


def test_a_missing_marker_or_directory_or_a_tag_that_is_running_is_refused(tmp_path):
    home, env, log = world(tmp_path)
    assert suite(env, "pm_none", "2", "tg").returncode == 1
    (home / "cafe-worker/cafe/pmdata/shards/tg").mkdir(parents=True)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        (home / "cafe-worker/cafe/pmdata/shards/tg/.pid").write_text(str(sleeper.pid))
        r = suite(env, "pm_t", "2", "tg")
        assert r.returncode == 1 and f"tag tg is running (pid {sleeper.pid})" in r.stderr and not log.exists()
    finally:
        sleeper.kill()
        sleeper.wait()
    assert suite(env, "pm_t", "2", "tg").returncode == 0                                                           # a pid that is gone does not block
    (home / "cafe-worker/.cafe-worker-owned").unlink()
    assert suite(env, "pm_t", "2", "ug").returncode == 1


def test_the_rc_line_of_a_log_is_a_line_of_its_own_even_when_the_job_left_half_a_line(tmp_path):
    home, env, log = world(tmp_path)
    assert suite({**env, "FAKE_PARTIAL": "1"}, "pm_t", "2", "t1").returncode == 0
    assert (home / "cafe-worker/logs/t1_s1.log").read_text() == "half a line\nrc=0\n"


def test_a_term_to_the_suite_reaches_every_job_and_ends_it_with_143(tmp_path):
    home, env, log = world(tmp_path)
    p = subprocess.Popen(["sh", str(ROOT / "bin/proot_suite.sh"), "pm_t", "3", "t1"], env={**env, "FAKE_SLEEP": "30"}, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True, text=True)
    try:
        t = time.time() + 30
        while time.time() < t and len([l for l in calls(log) if l.startswith("start s")]) < 3:
            time.sleep(0.1)
        assert len([l for l in calls(log) if l.startswith("start s")]) == 3
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 143
    finally:
        p.kill()
        p.wait()
    assert sorted(l for l in calls(log) if l.startswith("term")) == ["term s1", "term s2", "term s3"]
    assert (home / "cafe-worker/logs/t1_s1.log").read_text().endswith("rc=143\n")
    assert not any(l.startswith("start serial") for l in calls(log)) and not (home / "cafe-worker/cafe/pmdata/shards/t1/.pid").exists()


# ---- bin/orca_gate.sh, and PM_ENTRY of bin/pmx.sh ---------------------------------------------------------------------------------------------------

def sent(tmp_path, script, *args, **env):
    """(exit code, ssh and rsync argument lines) of `script` with ssh and rsync replaced by loggers."""
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    log = tmp_path / "sent.log"
    for name in ("ssh", "rsync"):
        (tools / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
        (tools / name).chmod(stat.S_IRWXU)
    e = {"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(tmp_path), **env}
    r = subprocess.run(["sh", str(ROOT / script), *args], cwd=ROOT, env=e, capture_output=True, text=True, timeout=30)
    return r.returncode, log.read_text() if log.exists() else "", r.stderr


@pytest.mark.parametrize("args, cov", [(("8", "go1"), ""), (("16", "go2", "--cov"), " --cov")])
def test_the_gate_syncs_like_pmx_and_starts_the_suite_detached_under_the_tag(tmp_path, args, cov):
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", *args, PMX="pm_me")
    k, tag = args[:2]
    assert rc == 0, err
    assert "cafe-worker/cafe/pm_me/" in out and "--delete" in out and "sync_filters" in out                       # pmx.sh's sync
    assert f"tmux new-session -d -s {tag}" in out
    assert f"sh $HOME/cafe-worker/cafe/pm_me/bin/proot_suite.sh pm_me {k} {tag}{cov} > $HOME/cafe-worker/logs/{tag}.log" in out
    assert "proot_run.sh" not in out and "docker" not in out


def test_the_gate_defaults_the_host_and_refuses_what_proot_suite_would(tmp_path):
    rc, out, _ = sent(tmp_path, "bin/orca_gate.sh", "2", "x1", PMX="pm_me")
    assert rc == 0 and " cafe-orca " in out and "cafe-worker/cafe/pm_me/" in out
    for args in (("17", "t"), ("0", "t"), ("2",), ("x", "t"), ("2", "a/b"), ("2", ""), ("2", "t", "--cove"), ("2", "t", "--cov", "x"), ()):
        (tmp_path / "sent.log").unlink(missing_ok=True)
        rc, out, _ = sent(tmp_path, "bin/orca_gate.sh", *args, PMX="pm_me")
        assert (rc, out) == (2, ""), args                                                                        # refused here, nothing sent


@pytest.mark.parametrize("given", [{}, dict(PMX="")])
def test_r14_m33_the_gate_needs_a_pmx_of_its_own_and_no_longer_makes_one_from_the_tag(tmp_path, given):
    """M-33: `orca_gate.sh 8 q14` synced onto pm_q14, the code tree of the q14 run, with --delete: the tag names a log, not a directory."""
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", "8", "q14", **given)
    assert (rc, out) == (2, "") and "PMX=pm_<you> is required" in err
    # round 15: the message says what to type
    assert "PM_TAKE=1 PM_HOST=cafe-orca PMX=pm_<you> bin/orca_gate.sh 8 q14" in err and "does not own that directory" in err


def test_pm_entry_picks_the_worker_script_for_proot_only_and_the_docker_command_does_not_change(tmp_path):
    rc, plain, _ = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="proot", PMX="pm_t")
    assert rc == 0 and "sh $HOME/cafe-worker/cafe/pm_t/bin/proot_run.sh pm_t true" in plain                       # unset: as before
    (tmp_path / "sent.log").unlink(missing_ok=True)
    rc, suite_out, _ = sent(tmp_path, "bin/pmx.sh", "2", "t1", PM_RUNTIME="proot", PMX="pm_t", PM_ENTRY="proot_suite.sh")
    assert rc == 0 and "sh $HOME/cafe-worker/cafe/pm_t/bin/proot_suite.sh pm_t 2 t1" in suite_out
    (tmp_path / "sent.log").unlink(missing_ok=True)
    rc, bad, _ = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="proot", PMX="pm_t", PM_ENTRY="../x.sh")
    assert rc == 2 and bad == ""
    (tmp_path / "sent.log").unlink(missing_ok=True)
    rc, docker, _ = sent(tmp_path, "bin/pmx.sh", "true", PMX="pm_t", PM_ENTRY="proot_suite.sh")
    (tmp_path / "sent.log").unlink(missing_ok=True)
    rc2, docker2, _ = sent(tmp_path, "bin/pmx.sh", "true", PMX="pm_t")
    assert rc == rc2 == 0 and docker == docker2 and "docker run" in docker and "proot" not in docker             # docker: the same command with or without it


# ---- round 10 M-28: a tag must not be one of the suite's own log names

BAD_TAGS = ["a_s2", "a_s10", "a_s3_s1", "a_serial", "a_shares", "a_audit", "go1_s02"]
OK_TAGS = ["a_s", "a_sx", "a_s2x", "a_s2_x", "s2", "serial", "a_ser"]


@pytest.mark.parametrize("tag", BAD_TAGS)
def test_m28_proot_suite_refuses_a_tag_that_is_a_log_name_of_another_tag(tmp_path, tag):
    """M-28: with the tag a_s2 beside a, the P-30 sweep of tag a (K=1) deleted a_s2.log, the main log whose rc= line a waiter reads."""
    home, env, log = world(tmp_path)
    logs = home / "cafe-worker/logs"
    logs.mkdir(parents=True)
    (logs / "a_s2.log").write_text("rc=0\n")
    r = suite(env, "pm_t", "1", tag)
    assert r.returncode == 2 and "tag" in r.stderr and calls(log) == []
    assert (logs / "a_s2.log").read_text() == "rc=0\n"


@pytest.mark.parametrize("tag", OK_TAGS)
def test_m28_a_tag_that_is_no_log_name_still_runs(tmp_path, tag):
    home, env, log = world(tmp_path)
    r = suite(env, "pm_t", "1", tag)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("tag", BAD_TAGS)
def test_m28_the_gate_refuses_the_same_tags_before_anything_is_sent(tmp_path, tag):
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", "2", tag, PMX="pm_me")
    assert (rc, out) == (2, "") and "tag" in err


@pytest.mark.parametrize("tag", OK_TAGS)
def test_m28_the_gate_still_sends_the_others(tmp_path, tag):
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", "2", tag, PMX="pm_me")
    assert rc == 0 and f"tmux new-session -d -s {tag} " in out, err


# ---- look-ahead batch LB0: the tag rule is the TM rule

SHORT_TAGS = ["a", "9", "-x", "_x", "-"]


@pytest.mark.parametrize("tag", SHORT_TAGS)
def test_lb0_the_gate_and_the_suite_refuse_the_tags_pmx_would_refuse_as_a_tm(tmp_path, tag):
    """`orca_gate.sh` exports the tag as TM and `pmx.sh` needs 2 or more characters, the first a letter or digit: `pm_tag` let `a`, `-x` and `_x` through
    and the gate stopped in `pmx.sh` with a message about TM. All three scripts now refuse it with one rule, before anything is sent."""
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", "2", tag, PMX="pm_me")
    assert (rc, out) == (2, "") and err.startswith("tag: 2 or more of letters, digits, _ and -, the first a letter or digit")
    home, env, log = world(tmp_path)
    r = suite(env, "pm_t", "1", tag)
    assert r.returncode == 2 and r.stderr.startswith("tag: 2 or more") and calls(log) == []


def test_lb0_a_tm_and_a_tag_go_through_one_rule(tmp_path):
    for tm in ("a", "-x", "_x"):
        rc, out, err = sent(tmp_path, "bin/pmx.sh", "true", PMX="pm_t", TM=tm)
        assert (rc, out) == (2, "") and err.startswith("TM: 2 or more of letters, digits, _ and -, the first a letter or digit"), tm
    rc, out, err = sent(tmp_path, "bin/pmx.sh", "true", PMX="pm_t", TM="ab")
    assert rc == 0, err


# ---- round 14 M-19: a count of 20 digits is refused by its length, before a `[` can print "Illegal number" and let it through

BIG = "9" * 20


def test_r14_m19_a_k_of_twenty_digits_is_refused_with_exit_2_and_no_shell_error_by_the_gate_and_the_suite(tmp_path):
    """M-19: K=99999999999999999999 reached `[ "$1" -le 16 ]`, whose own error line ("integer expression expected" or "Illegal number") came first."""
    rc, out, err = sent(tmp_path, "bin/orca_gate.sh", BIG, "t1", PMX="pm_me")
    assert (rc, out) == (2, "") and "K: a whole number from 1 to 999999999" in err and "xpression" not in err and "Illegal" not in err
    home, env, log = world(tmp_path)
    r = suite(env, "pm_t", BIG, "t1")
    assert r.returncode == 2 and "K: a whole number from 1 to 999999999" in r.stderr and calls(log) == []
    assert "xpression" not in r.stderr and "Illegal" not in r.stderr
    r = suite(env, "pm_t", "17", "t1")
    assert r.returncode == 2 and "above orca's 32 CPUs" in r.stderr                                      # a short number out of range keeps its own message


# ---- round 14 M-38: TERM, INT and HUP act at once in the shares step and in the audit step too

@pytest.mark.parametrize("step, extra", [("cafe.pm.shares", ()), ("cafe.pm.audit", ("--cov",))])
@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_r14_m38_a_signal_during_the_shares_step_or_the_audit_step_stops_the_suite_at_once(tmp_path, step, extra, sig):
    """M-38: both steps ran in the foreground, so the trap waited for them to return: a signal left the audit (minutes of ruff, mypy and coverage) running.
    The stand-in step sleeps 30 s; the suite must be gone in a few seconds, with the step stopped, its log ended and .pid removed."""
    home, env, log = world(tmp_path)
    p = subprocess.Popen(["sh", str(ROOT / "bin/proot_suite.sh"), "pm_t", "2", "t1", *extra], env={**env, "FAKE_HANG": step}, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True, text=True)
    try:
        t = time.time() + 30
        while time.time() < t and not [l for l in calls(log) if l.startswith("hang ")]:
            time.sleep(0.1)
        assert step in log.read_text().split("hang ", 1)[1]                                  # the audit's command has two lines
        p.send_signal(sig)
        assert p.wait(timeout=10) == 143
    finally:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        p.wait()
    assert [l for l in calls(log) if l.startswith("term")]
    name = "shares" if step.endswith("shares") else "audit"
    assert (home / f"cafe-worker/logs/t1_{name}.log").read_text().endswith("rc=143\n")
    assert not (home / "cafe-worker/cafe/pmdata/shards/t1/.pid").exists()


def test_r14_m38_the_shares_and_audit_steps_keep_their_logs_and_their_failure_messages(tmp_path):
    home, env, log = world(tmp_path)
    r = suite({**env, "FAKE_FAIL": "cafe.pm.audit"}, "pm_t", "1", "t1", "--cov")
    assert r.returncode == 1 and "FAILED: audit(rc=1)" in r.stdout
    assert (home / "cafe-worker/logs/t1_audit.log").read_text() == "boom\nrc=1\n"
    assert (home / "cafe-worker/logs/t1_shares.log").read_text().endswith("rc=0\n") and "rc=0" not in r.stdout    # the plan, not the rc= line
