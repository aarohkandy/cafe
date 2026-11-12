"""On orca, a shared machine, the runners stay inside ~/cafe-worker. These read what bin/pmx.sh and pm.sh would send, with ssh and rsync replaced by loggers."""
import ctypes
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import time

import pytest

from cafe.pm import acceptance, audit, budget, config, report

ROOT = config.ROOT


def sent(tmp_path, script, *args, owned=True, **env):
    """(exit code, every ssh and rsync argument line) of running `script` with PATH's ssh and rsync replaced."""
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    log = tmp_path / "sent.log"
    for name in ("ssh", "rsync"):
        (tools / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\ncase "$*" in *.cafe-worker-owned) exit {0 if owned else 1} ;; esac\n')
        (tools / name).chmod(stat.S_IRWXU)
    e = {"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(tmp_path), "PM_HOST": "worker", **env}
    r = subprocess.run(["sh", str(ROOT / script), *args], cwd=ROOT, env=e, capture_output=True, text=True, timeout=30)
    return r.returncode, log.read_text() if log.exists() else ""


@pytest.mark.parametrize("script, env", [("bin/pmx.sh", dict(PMX="pm_t")), ("bin/pmx.sh", dict(PMX="pm_t", TM="job")), ("pm.sh", {})])
def test_the_proot_path_names_nothing_outside_cafe_worker(tmp_path, script, env):
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", **env)
    assert rc == 0 and "cafe-worker/cafe/" in out
    assert "work/cafe" not in out.replace("cafe-worker/cafe", "") and "$HOME/logs" not in out and "docker" not in out
    assert ("cafe-worker/logs/job.log" in out and "TMUX_TMPDIR=$HOME/cafe-worker/logs" in out) if "TM" in env else True


@pytest.mark.parametrize("script", ["bin/pmx.sh", "pm.sh"])
def test_nothing_is_sent_to_a_machine_without_our_marker(tmp_path, script):
    rc, out = sent(tmp_path, script, "true", owned=False, PM_RUNTIME="proot")
    assert rc == 1 and "rsync" not in out and "true" not in out


@pytest.mark.parametrize("runtime", ["docker", "proot"])
@pytest.mark.parametrize("name", [dict(PMX=".."), dict(PMX="../x"), dict(PMX="a/b"), dict(TM="../x"), dict(PMX="pmdata"), dict(PMX="data"), dict(PMX="pm"),
                                  dict(PMX="tmp"), dict(PMX="pm_"), dict(PMX="pm_a/b"), dict(PMX="pm_a b"), dict(PMX="pm_a;x"),
                                  dict(PMX="pm_a\n.."), dict(TM="a b"), dict(TM="a;x")])
def test_a_name_cannot_point_rsync_delete_or_a_log_outside(tmp_path, name, runtime):
    """M-28: PMX=pmdata (or data, pm, tmp) made `rsync --delete` empty the shared data; docker mode had no filter at all."""
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME=runtime, **name)
    assert rc == 2 and out == ""


@pytest.mark.parametrize("runtime", ["docker", "proot"])
@pytest.mark.parametrize("name, dest", [({}, "pm_x/"), (dict(PMX="pm_a"), "pm_a/"), (dict(PMX="pm_r9e-2_x"), "pm_r9e-2_x/"),
                                       (dict(PMX="pm_a", TM="job_1-b"), "pm_a/")])
def test_the_names_that_were_valid_still_sync_where_they_did(tmp_path, name, dest, runtime):
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME=runtime, **name)
    assert rc == 0 and f"/{dest}" in out


@pytest.mark.parametrize("script, env", [("bin/pmx.sh", dict(PMX="pm_t")), ("bin/pmx.sh", dict(PMX="pm_t", TM="job")), ("pm.sh", {})])
@pytest.mark.parametrize("grace, sent_as", [("60", "PM_STOP_GRACE=60 "), (None, "PM_STOP_GRACE=10 "), ("", "PM_STOP_GRACE=10 ")])
def test_the_stop_grace_reaches_proot_run_on_the_worker(tmp_path, script, env, grace, sent_as):
    """The wrapper on the worker read PM_STOP_GRACE, but the laptop's scripts never sent it: the 10 s default was all anyone got."""
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", **env, **({} if grace is None else {"PM_STOP_GRACE": grace}))
    assert rc == 0 and sent_as + "sh $HOME/cafe-worker/cafe/" in out


@pytest.mark.parametrize("script, env", [("bin/pmx.sh", dict(PMX="pm_t")), ("pm.sh", {})])
@pytest.mark.parametrize("grace", ["1;x", "1 2", "-1", "x", "$(id)"])
def test_a_stop_grace_that_is_not_whole_seconds_is_refused_before_anything_is_sent(tmp_path, script, env, grace):
    """The value is pasted into the command line that the worker's shell parses, so it is checked here, not only by proot_run.sh."""
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", PM_STOP_GRACE=grace, **env)
    assert rc == 2 and out == ""


BOTH = [("bin/pmx.sh", dict(PMX="pm_t")), ("pm.sh", {})]


@pytest.mark.parametrize("script, env", BOTH)
@pytest.mark.parametrize("var, value, runtime", [
    *[("PM_CPUS", v, r) for v in ("2,", "2;x", "0", "1.5", "-1", "$(id)", "2 3", "02") for r in ("docker", "proot")],
    *[("CAFE_MIN_FREE_GB", v, "proot") for v in ("1;echo INJ", "6 0", "x", "-1")],
    *[("PM_THREADS", v, "proot") for v in ("2;x", "0", "2 2")],
    *[(n, v, "docker") for n in ("PM_MEM", "PM_SHM") for v in ("8g;x", "g", "0g", "8 g", "8gb;x", "$(id)")]])
def test_m23_a_number_pasted_into_the_remote_command_line_is_refused_before_anything_is_sent(tmp_path, script, env, var, value, runtime):
    """M-23: PM_CPUS='2;x' ran `x` on the worker and '2,' became CAFE_WORKERS=2,; only PM_STOP_GRACE and PM_ENTRY had been checked."""
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME=runtime, **env, **{var: value})
    assert rc == 2 and out == ""


@pytest.mark.parametrize("runtime", ["docker", "proot"])
@pytest.mark.parametrize("tm", ["x", "-x", "_x", "-", "a b", "a;x"])
def test_m23_a_name_that_tmux_or_docker_refuses_is_refused_here(tmp_path, tm, runtime):
    """M-23: TM=x passed the character test and docker then refused the name; a leading '-' is an option to tmux."""
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME=runtime, PMX="pm_t", TM=tm)
    assert rc == 2 and out == ""


@pytest.mark.parametrize("script, env", BOTH)
@pytest.mark.parametrize("runtime", ["docker", "proot"])
@pytest.mark.parametrize("extra", [{}, dict(PM_CPUS="2"), dict(PM_CPUS="16"), dict(PM_CPUS=""), dict(PM_MEM="8g", PM_SHM="512m", PM_CPUS="4"),
                                   dict(PM_MEM="28G"), dict(PM_MEM="8gb", PM_SHM="64MB"), dict(PM_MEM="8192"), dict(CAFE_MIN_FREE_GB="1"),
                                   dict(PM_THREADS="2")])
def test_m23_what_was_valid_is_still_sent(tmp_path, script, env, runtime, extra):
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME=runtime, **env, **extra)
    assert rc == 0 and "rsync" in out


@pytest.mark.parametrize("tm", ["ab", "a1", "1a", "job_1-b", "q10"])
def test_m23_a_two_character_name_with_a_letter_or_digit_first_is_a_tmux_session(tmp_path, tm):
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="proot", PMX="pm_t", TM=tm)
    assert rc == 0 and f"tmux new-session -d -s {tm} " in out


def test_m23_proot_run_refuses_a_cpu_count_that_is_not_a_number_when_started_by_hand(tmp_path):
    home, env = live(tmp_path)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "pm_t", "true"], {**env, "PM_CPUS": "2,"})
    assert r.returncode == 2 and "PM_CPUS" in r.stderr


@pytest.mark.parametrize("runtime, script, cpus, mem", [("docker", "bin/pmx.sh", "2", "12g"), ("docker", "pm.sh", "8", "28g")])
def test_m31_the_docker_defaults_are_two_cpus_and_12g_on_the_pmx_path_and_the_whole_box_on_pm_sh(tmp_path, runtime, script, cpus, mem):
    rc, out = sent(tmp_path, script, "true")
    assert rc == 0 and f"--cpus {cpus} --memory {mem} --shm-size 16g" in out
    rc, out = sent(tmp_path, script, "true", PM_CPUS="6", PM_MEM="24g", PM_SHM="4g")
    assert rc == 0 and "--cpus 6 --memory 24g --shm-size 4g" in out                      # a number asked for is what is sent


def docker_gb(size):
    """What `par.memory_gb()` reads in a container started with `--memory <size>`: the cgroup limit in bytes over 1e9."""
    n, unit = re.fullmatch(r"(\d+)([kmg]?)b?", size.lower()).groups()
    return int(n) * 1024 ** ("", "k", "m", "g").index(unit) / 1e9


def documented_demo_runs():
    """(file, line, budget, PM_MEM named on the line or None) of every command in the documents that runs the demo mission through bin/pmx.sh."""
    out = []
    for f in ("CLAUDE.md", "HANDOFF.md", *sorted(str(p.relative_to(ROOT)) for p in (ROOT / "docs").glob("*.md"))):
        for n, line in enumerate((ROOT / f).read_text().splitlines(), 1):
            if "bin/pmx.sh" in line and "missions/tepex_c_demo.yaml" in line:
                mem = re.search(r"PM_MEM=(\w+)", line)
                out.append((f, n, re.search(r"--budget (\w+)", line).group(1), mem and mem.group(1)))
    return out


def test_m31_every_documented_demo_run_through_pmx_sh_gets_the_memory_the_plan_needs(tmp_path):
    """M-31: the 8g default made the quick demo of CLAUDE.md refuse to start (plan needs the 9 GB environment plus 0.9 GB for a worker)."""
    runs = documented_demo_runs()
    assert any(f == "CLAUDE.md" and m is None for f, _, _, m in runs)              # the one that names no PM_MEM, and so takes the default
    default = re.search(r"--memory (\S+)", sent(tmp_path, "bin/pmx.sh", "true")[1]).group(1)
    mission = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
    for f, n, b, mem in runs:
        try:
            budget.plan(b, 0, mission, thr={}, mem_gb=docker_gb(mem or default))
        except budget.PlanError as e:
            assert "is available" not in str(e), f"{f}:{n}: --memory {mem or default} is below what the plan needs: {e}"


def test_m31_the_memory_check_sees_a_default_below_the_floor():
    """The check above can fail: 8g (the old default) is refused by plan, 12g is not."""
    mission = config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")
    with pytest.raises(budget.PlanError, match="is available"):
        budget.plan("quick", 0, mission, thr={}, mem_gb=docker_gb("8g"))
    budget.plan("quick", 0, mission, thr={}, mem_gb=docker_gb("12g"))


@pytest.mark.parametrize("script, env, cpus", [("bin/pmx.sh", dict(PMX="pm_t"), "2"), ("bin/pmx.sh", dict(PMX="pm_t", TM="job"), "2"), ("pm.sh", {}, "8")])
def test_m31_the_proot_default_is_two_cpus_on_the_pmx_path_and_eight_on_pm_sh_and_pm_threads_is_passed_on_only_when_set(tmp_path, script, env, cpus):
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", **env)
    assert rc == 0 and f"PM_CPUS={cpus} CAFE_MIN_FREE_GB=60 " in out and "PM_THREADS" not in out
    (tmp_path / "sent.log").unlink()
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", PM_CPUS="3", PM_THREADS="3", **env)
    assert rc == 0 and "PM_CPUS=3 PM_THREADS=3 CAFE_MIN_FREE_GB=60 " in out
    (tmp_path / "sent.log").unlink()
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="docker", PM_THREADS="3", **env)
    assert rc == 0 and "PM_THREADS" not in out                                           # docker sizes nothing by it


def test_a_failed_copy_does_not_run_the_job_on_stale_code(tmp_path):
    rc, out = sent(tmp_path, "bin/pmx.sh", "true")
    assert rc == 0 and "work/cafe/pm_x/" in out and "docker run" in out          # docker keeps its paths
    (tmp_path / "tools" / "rsync").write_text("#!/bin/sh\nexit 23\n")
    (tmp_path / "sent.log").unlink()
    r = subprocess.run(["sh", str(ROOT / "bin/pmx.sh"), "true"], cwd=ROOT, capture_output=True, text=True, timeout=30,
                       env={"PATH": f"{tmp_path / 'tools'}:{os.environ['PATH']}", "HOME": str(tmp_path), "PM_HOST": "worker"})
    log = tmp_path / "sent.log"
    after = log.read_text() if log.exists() else ""                                  # the owner marker is read before the copy (M-33); nothing may follow it
    assert r.returncode == 1 and "docker run" not in after and ".pmx.owner >" not in after and "rsync" not in after


def test_the_worker_side_scripts_stay_inside_too():
    run = (ROOT / "bin/proot_run.sh").read_text()
    assert 'C="$W/cafe"' in run and "work/cafe" not in run
    copy = (ROOT / "bin/orca_sync.sh").read_text()
    assert "-C cafe-worker/cafe/$p" in copy and "-C work/cafe" not in copy


# ---------------------------------------------------------------------------------------------------------------------------------------------------------
# The scripts that really run: ssh executes its command here, in a scratch HOME, as the remote login shell would; docker, tmux and tar are stand-ins.

TOOLS = {
    "ssh": '#!/bin/sh\nshift 3; cd "$HOME" || exit 1; exec sh -c "$*"\n',                                         # ssh -i KEY HOST CMD...
    "rsync": '#!/bin/sh\necho "rsync $*" >> "$HOME/rsync.log"\n',
    "docker": """#!/bin/sh
case "$1" in
  run) while [ "$1" != cafe-pm ]; do shift; done; shift; exec "$@" ;;
  image) echo sha256:abc123 ;;
  create) echo fakecid ;;
  export) tar cf - -C "$FAKE_IMAGE" .; exit ${FAKE_EXPORT_RC:-0} ;;
esac
""",
    "tmux": """#!/bin/sh
S="$HOME/tmuxstate"; mkdir -p "$S"
case "$1" in
  new-session) shift; while [ "$1" != -s ]; do shift; done; rm -f "$S/.env.$2"; : > "$S/$2"
    ( sh -c "$3"; rm -f "$S/$2" "$S/.env.$2" ) </dev/null >/dev/null 2>&1 & ;;
  has-session) [ -e "$S/${3#=}" ] ;;
  set-environment) [ -e "$S/${3#=}" ] && printf '%s=%s\\n' "$4" "$5" > "$S/.env.${3#=}" ;;
  show-environment) grep "^$4=" "$S/.env.${3#=}" 2>/dev/null || echo "-$4" ;;
  ls) for f in "$S"/*; do [ -e "$f" ] && echo "$(basename "$f"): 1 windows (created now)"; done; exit 0 ;;
esac
""",
}


def live(tmp_path, *names, **extra):
    """(home, env): `home` is the scratch HOME with the cafe-worker marker; PATH puts the stand-ins named in `names` first.
    `tar` passes FAKE_TAR_RC for the call that makes an archive."""
    home = tmp_path / "home"
    (home / "cafe-worker").mkdir(parents=True, exist_ok=True)
    (home / "cafe-worker" / ".cafe-worker-owned").write_text("")
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    scripts = {n: TOOLS[n] for n in names}
    scripts["tar"] = f'#!/bin/sh\n{shutil.which("tar")} "$@"; r=$?\ncase "$1" in -I) [ -z "$FAKE_TAR_RC" ] || exit $FAKE_TAR_RC ;; esac\nexit $r\n'
    for n, body in scripts.items():
        (tools / n).write_text(body)
        (tools / n).chmod(stat.S_IRWXU)
    return home, {"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(home), "PM_HOST": "worker", "PM_KEY": "k", **extra}


def run(argv, env, cwd=ROOT, timeout=60):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


# ---- M-34: a detached job is judged by its own session and its own exit code -------------------------------------------------------------------------

@pytest.mark.parametrize("runtime", ["docker", "proot"])
@pytest.mark.parametrize("cmd, others, rc", [("false", ["rev9a_one", "rev9b_edge"], 1), ("true", [], 0), ("sleep 5", ["rev9a_one"], 0)])
def test_a_detached_job_is_judged_by_its_own_session_and_exit_code(tmp_path, runtime, cmd, others, rc):
    """M-34: `tmux ls | grep $TM` counted another session whose name contains $TM as success for a dead job,
    and a job that ended at once, successfully, as a failure."""
    home, env = live(tmp_path, "ssh", "rsync", "docker", "tmux", PM_RUNTIME=runtime, TM="rev9", PMX="pm_t")
    (home / "tmuxstate").mkdir()
    for o in others:
        (home / "tmuxstate" / o).write_text("")                                      # sessions of someone else, alive, with rev9 in the name
    if runtime == "proot":
        (home / "cafe-worker" / "cafe" / "pm_t" / "bin").mkdir(parents=True)
        (home / "cafe-worker" / "cafe" / "pm_t" / "bin" / "proot_run.sh").write_text('shift; exec "$@"\n')             # what the worker runs: the job itself
    r = run(["sh", str(ROOT / "bin/pmx.sh"), *cmd.split()], env)
    assert r.returncode == rc, r.stderr
    assert ("ended: rc=1" in r.stderr) == (rc == 1)


@pytest.mark.parametrize("runtime", ["docker", "proot"])
def test_p26_a_job_stopped_by_kill_session_still_ends_its_log_with_rc(tmp_path, runtime):
    """P-26: `tmux kill-session` hangs up the pane's shell, which died before its trailing `echo rc=$?`: the log of a stopped job had no rc= line, so a
    wait loop on it never ended. The pane shell is run here as tmux runs it (its own session) and hung up as tmux does: the HUP goes to the shell, and
    when the shell is gone the kernel hangs up its foreground group. The log must end in rc=N, the job's own status (a HUP kills the stand-in: 129)."""
    home, env = live(tmp_path, "ssh", "rsync", "docker", PM_RUNTIME=runtime, TM="p26", PMX="pm_t")
    (home / "tmuxstate").mkdir()
    (tmp_path / "tools" / "tmux").write_text('#!/bin/sh\ncase "$1" in\n  new-session) shift; while [ "$1" != -s ]; do shift; done;\n'
                                             '    printf %s "$3" > "$HOME/pane_cmd" ;;\n  has-session) exit 0 ;;\nesac\n')
    (tmp_path / "tools" / "tmux").chmod(stat.S_IRWXU)
    job = tmp_path / "job.sh"
    job.write_text("echo up\nexec sleep 60\n")
    if runtime == "proot":
        (home / "cafe-worker" / "cafe" / "pm_t" / "bin").mkdir(parents=True)
        (home / "cafe-worker" / "cafe" / "pm_t" / "bin" / "proot_run.sh").write_text('shift; exec "$@"\n')
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "sh", str(job)], env).returncode == 0
    log = home / ("cafe-worker/logs" if runtime == "proot" else "logs") / "p26.log"
    pane = subprocess.Popen(["sh", "-c", (home / "pane_cmd").read_text()], env=env, cwd=home, start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if log.exists() and "up" in log.read_text():
                break
            time.sleep(0.1)
        assert log.read_text().startswith("up")
        pane.send_signal(signal.SIGHUP)                                                  # tmux hangs up the shell
        try:
            pane.wait(timeout=2)
            os.killpg(pane.pid, signal.SIGHUP)                                           # the shell is gone: the kernel hangs up the foreground group
        except subprocess.TimeoutExpired:
            pane.wait(timeout=20)
        except ProcessLookupError:
            pass
        for _ in range(100):
            if log.read_text().rstrip("\n").rsplit("\n", 1)[-1].startswith("rc="):
                break
            time.sleep(0.1)
        assert log.read_text().rstrip("\n").rsplit("\n", 1)[-1] == "rc=129"
    finally:
        try:
            os.killpg(pane.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        pane.wait()


def real_rsync_without_modes(tmp_path):
    """Put the real rsync first on PATH with --no-perms: its chmod fails under proot on orca's kernel 5.10 ("failed to set permissions ...: No such file or
    directory", even for `rsync -a /a/ /b/`; glibc's fchmodat goes through /proc/self/fd, which proot cannot translate: orca-go P-16). The tests that use it
    are about which files are sent and deleted, not their modes. --no-perms goes after the arguments, so that the script's -a does not switch it on again."""
    real = shutil.which("rsync")
    (tmp_path / "tools" / "rsync").write_text(f'#!/bin/sh\ncase "$1" in --server*) exec {real} "$@" ;; esac\nexec {real} "$@" --no-perms\n')
    (tmp_path / "tools" / "rsync").chmod(stat.S_IRWXU)


# ---- M-39: pm.sh and bin/pmx.sh sync with --delete and keep what the server wrote ------------------------------------------------------------------

def server_outputs():
    """Every path a job or a gate writes into the tree on the server, from the code that writes it."""
    return [audit.MUTATION_FILE, audit.LOG, "coverage.json", ".coverage", ".coverage.host.1.x", audit.MUTATION_STATS, report.RECEIPTS_NAME,
            "runs/quick/report.json",
            "runs/acceptance/acceptance.json", str(acceptance.GOLDEN.relative_to(ROOT)), str(budget.THROUGHPUT.relative_to(ROOT)), "config/subgrid.json",
            "emulator/train.parquet", "emulator/train.csv", ".hypothesis/x", ".pytest_cache/x", ".mypy_cache/x", ".ruff_cache/x", "report/tepex.json",
            "checkpoints/x", "cache/x",
            ".work/sitl/x"]


@pytest.mark.parametrize("script, server_dir", [("pm.sh", "pm"), ("bin/pmx.sh", "pm_t")])
def test_a_file_removed_from_the_tree_is_removed_on_the_server_and_what_the_server_wrote_stays(tmp_path, script, server_dir):
    """M-39: pm.sh had no --delete, so a deleted test or module still ran on the server; bin/pmx.sh's --delete wiped outputs.
    One list (bin/sync_filters) serves both."""
    home, env = live(tmp_path, "ssh", "docker", PMX="pm_t")
    real_rsync_without_modes(tmp_path)
    src = tmp_path / "checkout"
    for f in ("cafe/pm/kept.py", "tests/test_kept.py"):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        (src / f).write_text("local")
    dest = home / "work" / "cafe" / server_dir
    stale = ["cafe/pm/old.py", "tests/test_x.py", "docs/gone.md"]
    for f in stale + server_outputs():
        (dest / f).parent.mkdir(parents=True, exist_ok=True)
        (dest / f).write_text("server")
    (src / "config").mkdir()
    (src / "config" / "throughput.json").write_text("local")                    # a tracked file in the checkout: the checkout's copy goes over, as always
    r = run(["sh", str(ROOT / script), "true"], env, cwd=src)
    assert r.returncode == 0, r.stderr
    assert [f for f in stale if (dest / f).exists()] == []
    assert [f for f in server_outputs() if f != "config/throughput.json" and (dest / f).read_text() != "server"] == []
    assert (dest / "cafe/pm/kept.py").read_text() == "local" and (dest / "config/throughput.json").read_text() == "local"


@pytest.mark.parametrize("script, server_dir", [("pm.sh", "pm"), ("bin/pmx.sh", "pm_t")])
def test_l2_a_file_the_server_wrote_inside_a_protected_directory_survives_when_the_checkout_has_that_directory_too(tmp_path, script, server_dir):
    """Round 9 L2: `P /tests/golden/` and `P /report/` match the directory entry only. The checkout has both directories, so rsync recurses into them and a
    golden file with a new name or a report page written on the server was deleted by the next sync."""
    home, env = live(tmp_path, "ssh", "docker", PMX="pm_t")
    real_rsync_without_modes(tmp_path)
    src = tmp_path / "checkout"
    dest = home / "work" / "cafe" / server_dir
    for d, tracked in (("tests/golden", "a.json"), ("report", "build.py")):
        (src / d).mkdir(parents=True)
        (src / d / tracked).write_text("local")
        (dest / d / "deeper").mkdir(parents=True)
        (dest / d / "from_server.txt").write_text("server")
        (dest / d / "deeper" / "x").write_text("server")
    r = run(["sh", str(ROOT / script), "true"], env, cwd=src)
    assert r.returncode == 0, r.stderr
    for d, tracked in (("tests/golden", "a.json"), ("report", "build.py")):
        assert (dest / d / "from_server.txt").read_text() == "server" and (dest / d / "deeper" / "x").read_text() == "server", d
        assert (dest / d / tracked).read_text() == "local", d


# ---- M-29, M-36: bin/orca_sync.sh -------------------------------------------------------------------------------------------------------------------

def sync_world(tmp_path, **extra):
    """A homebase and an orca that are both this scratch HOME: pmdata and data to copy, an image to export, proot already there."""
    home, env = live(tmp_path, "ssh", "docker", ORCA_VIA="worker", ORCA_SRC="sh -c", ORCA_DST="sh -c", CAFE_MIN_FREE_GB="0",
                     FAKE_IMAGE=str(tmp_path / "image"), **extra)
    for d in ("bin", "dtmb5415", "bathy", "tao", "cache", "ocean"):
        (home / "work/cafe/pmdata" / d).mkdir(parents=True)
        (home / "work/cafe/pmdata" / d / "f").write_text(d)
    (home / "work/cafe/data").mkdir(parents=True)
    (home / "work/cafe/data/f").write_text("data")
    (tmp_path / "image/usr/bin").mkdir(parents=True)
    (tmp_path / "image/usr/bin/env").write_text("")
    (tmp_path / "image/usr/bin/env").chmod(stat.S_IRWXU)
    (tmp_path / "image/venv/lib").mkdir(parents=True)
    (home / "cafe-worker/bin").mkdir()
    (home / "cafe-worker/bin/proot").write_text("")
    (home / "cafe-worker/bin/proot").chmod(stat.S_IRWXU)
    return home, env


def sync(env, *parts):
    return run(["sh", str(ROOT / "bin/orca_sync.sh"), "100.1.2.3", *parts], env)


@pytest.mark.parametrize("part", ["pmdata", "data"])
def test_a_copy_whose_tar_failed_leaves_no_marker_and_a_whole_one_does(tmp_path, part):
    """M-29: `tar cf - $dirs | gzip -1` reported gzip's status, so a missing directory gave a short valid archive, exit 0 and the .done marker."""
    home, env = sync_world(tmp_path)
    marker = home / f"cafe-worker/{part}.done"
    if part == "pmdata":
        shutil.rmtree(home / "work/cafe/pmdata/ocean")
    else:
        (home / "work/cafe/data/f").unlink()                                      # nothing arrives: an empty copy is not a copy
    r = sync(env, part)
    assert r.returncode != 0 and not marker.exists() and "== done" not in r.stdout
    if part == "pmdata":
        (home / "work/cafe/pmdata/ocean").mkdir()
        (home / "work/cafe/pmdata/ocean/f").write_text("ocean")
    else:
        (home / "work/cafe/data/f").write_text("data")
    r = sync(env, part)
    assert r.returncode == 0 and marker.exists() and "== done" in r.stdout, r.stderr
    assert (home / "cafe-worker/cafe" / part / ("ocean/f" if part == "pmdata" else "f")).exists()


@pytest.mark.parametrize("rc, ok", [("1", True), ("2", False)])
def test_gnu_tar_one_file_changed_is_tolerated_two_is_not(tmp_path, rc, ok):
    home, env = sync_world(tmp_path, FAKE_TAR_RC=rc)
    r = sync(env, "pmdata")
    assert (r.returncode == 0) == ok and (home / "cafe-worker/pmdata.done").exists() == ok


def test_a_stale_marker_does_not_survive_a_copy_that_is_cut(tmp_path):
    home, env = sync_world(tmp_path)
    (home / "cafe-worker/pmdata.done").write_text("")
    shutil.rmtree(home / "work/cafe/pmdata/tao")
    assert sync(env, "pmdata").returncode != 0 and not (home / "cafe-worker/pmdata.done").exists()


@pytest.mark.parametrize("parts", [["pmdta"], ["pmdata/"], ["root", "dta"], ["data", "*"], ["Root"]])
def test_an_unknown_part_name_stops_the_script_before_anything_is_touched(tmp_path, parts):
    """M-36: `orca_sync.sh <ip> pmdta` copied nothing and printed `== done`."""
    home, env = sync_world(tmp_path)
    r = sync(env, *parts)
    assert r.returncode == 1 and "unknown part" in r.stderr and "== " not in r.stdout
    assert sorted(p.name for p in (home / "cafe-worker").iterdir()) == [".cafe-worker-owned", "bin"]


def test_root_is_not_replaced_under_a_running_job_and_a_cut_export_is_no_root(tmp_path):
    """M-36: `rm -rf root && mv root.new root` ran with no check for a job running from root. M-29: `docker export | gzip` hid a failed export."""
    home, env = sync_world(tmp_path)
    root = home / "cafe-worker/root"
    r = sync(env, "root")                                                       # nothing runs: the first copy
    assert r.returncode == 0 and (root / "usr/bin/env").exists() and (home / "cafe-worker/root.done").read_text() == "sha256:abc123", r.stderr
    (root / "kept").write_text("")
    (root / "bin").mkdir(exist_ok=True)
    job = root / "bin" / "sleeper"
    shutil.copy(shutil.which("sleep"), job)
    p = subprocess.Popen([str(job), "60"])
    try:
        time.sleep(0.3)
        r = sync(env, "root")
        assert r.returncode == 1 and "a job of ours runs" in r.stderr and (root / "kept").exists()
        r = sync(env)                                                           # no part named, image unchanged: nothing to do, nothing to refuse
        assert r.returncode == 0 and "== root" not in r.stdout
        r = sync({**env, "ORCA_FORCE": "1"}, "root")
        assert r.returncode == 0 and not (root / "kept").exists()
    finally:
        p.kill()
        p.wait()
    (root / "kept").write_text("")
    r = sync({**env, "FAKE_EXPORT_RC": "1"}, "root")
    assert r.returncode != 0 and (root / "kept").exists()                       # the old root stays: the cut export was not swapped in


# ---- M-37: bin/orca_setup.sh undo ---------------------------------------------------------------------------------------------------------------------

def setup_world(tmp_path, logout="ok"):
    """Our folder with a stub tailscale that records whether tailscaled still ran when it was asked to log out.
    Daemons are copies of `sleep` or `sh` made in the folder (see `daemon`), so their program lives there."""
    home, env = live(tmp_path)
    w = home / "cafe-worker"
    for d in ("bin", "ts", "ssh", "env/bin"):
        (w / d).mkdir(parents=True, exist_ok=True)
    (w / "bin/tailscale").write_text(
        '#!/bin/sh\np=$(cat "$HOME/cafe-worker/ts/tailscaled.pid")\n'
        'if [ -n "$(readlink /proc/$p/exe 2>/dev/null)" ]; then echo "$* daemon=up" >> "$HOME/calls.log"; else echo "$* daemon=down" >> "$HOME/calls.log"; fi\n'
        + ('echo "logout: boom" >&2; exit 1\n' if logout == "fail" else "exit 0\n"))
    (w / "bin/tailscale").chmod(stat.S_IRWXU)
    return home, env, w


def daemon(w, name, pidfile, *argv):
    exe = w / name
    shutil.copy(shutil.which("sleep") if not argv else shutil.which("sh"), exe)
    p = subprocess.Popen([str(exe), *(argv or ("300",))], start_new_session=True)
    (w / pidfile).write_text(str(p.pid))
    return p


def test_undo_logs_out_while_tailscaled_serves_and_waits_for_the_daemons_before_deleting(tmp_path):
    """M-37: `stop_ours; tailscale logout 2>/dev/null || true; rm -rf` logged out against a socket nobody served, hid the failure,
    and deleted after a fixed `sleep 1`."""
    home, env, w = setup_world(tmp_path)
    sshd = daemon(w, "env/bin/sshd", "ssh/sshd.pid")
    slow = daemon(w, "bin/tailscaled", "ts/tailscaled.pid", "-c", 'trap "sleep 2; exit 0" TERM; while :; do sleep 1; done')
    time.sleep(0.3)
    try:
        r = run(["bash", str(ROOT / "bin/orca_setup.sh"), "undo"], env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "logout daemon=up" in (home / "calls.log").read_text() and not w.exists()
        assert sshd.poll() is not None and slow.poll() is not None              # gone before the folder was deleted, not still shutting down
    finally:
        for p in (sshd, slow):
            p.kill()
            p.wait()


def test_undo_says_when_the_logout_failed(tmp_path):
    home, env, w = setup_world(tmp_path, logout="fail")
    r = run(["bash", str(ROOT / "bin/orca_setup.sh"), "undo"], env)
    assert r.returncode == 0 and "boom" in r.stderr and "logout failed" in r.stdout and not w.exists()


def test_undo_refuses_while_a_job_of_ours_runs_and_touches_nothing(tmp_path):
    home, env, w = setup_world(tmp_path)
    ts = daemon(w, "bin/tailscaled", "ts/tailscaled.pid")
    (w / "cafe").mkdir()
    shutil.copy(shutil.which("sleep"), w / "cafe/job")
    job = subprocess.Popen([str(w / "cafe/job"), "300"], start_new_session=True)
    time.sleep(0.3)
    try:
        r = run(["bash", str(ROOT / "bin/orca_setup.sh"), "undo"], env)
        assert r.returncode == 1 and f"pid {job.pid} " in r.stdout and w.exists() and not (home / "calls.log").exists()
        assert ts.poll() is None and job.poll() is None
    finally:
        for p in (ts, job):
            p.kill()
            p.wait()


# ---- M-40: bin/proot_run.sh stops its job and sweeps what a killed wrapper left ------------------------------------------------------------------------

def proot_world(tmp_path, **extra):
    """A worker whose proot is a stand-in that ignores TERM and runs a child that does too."""
    home, env = live(tmp_path, CAFE_MIN_FREE_GB="0", **extra)
    w = home / "cafe-worker"
    (w / "bin").mkdir()
    (w / "bin/proot").write_text("#!/bin/sh\ntrap '' TERM\nsleep 300 &\nwait\n")
    (w / "bin/proot").chmod(stat.S_IRWXU)
    (w / "root/usr/bin").mkdir(parents=True)
    (w / "root/usr/bin/env").write_text("")
    (w / "root/usr/bin/env").chmod(stat.S_IRWXU)
    (w / "root.done").write_text("x")
    for d in ("app", "pmdata", "data"):
        (w / "cafe" / d).mkdir(parents=True)
    return w, env


def group(pgid, zombies=False):
    """pids of the live (not zombie, unless `zombies`) processes in process group `pgid`."""
    out = []
    for d in pathlib.Path("/proc").iterdir():
        if d.name.isdigit():
            try:
                state, pgrp = (lambda t: (t[0], int(t[2])))(d.joinpath("stat").read_text().rsplit(")", 1)[1].split())
            except (OSError, IndexError, ValueError):
                continue
            if pgrp == pgid and (state != "Z" or zombies):
                out.append(int(d.name))
    return out


def start(w, env):
    """(wrapper process, its run directory, the process group of its proot) once the proot runs."""
    p = subprocess.Popen(["sh", str(ROOT / "bin/proot_run.sh"), "app", "x"], env=env, stdin=subprocess.DEVNULL, start_new_session=True)
    t = time.time() + 15
    while time.time() < t:
        for d in (w / "cafe/tmp").glob("run.*"):
            pids = (d / ".pids").read_text().split() if (d / ".pids").exists() else []
            if len(pids) == 2 and int(pids[0]) == p.pid and group(int(pids[1])):
                return p, d, int(pids[1])
        time.sleep(0.05)
    p.kill()
    raise AssertionError("the job did not start")


def reap(pids):
    """The orphans of a killed wrapper come to this process (subreaper): reap them, as the init of a real machine does. `kill -0` is true for a zombie."""
    for pid in pids:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


def dead(pgid, within=10):
    t = time.time() + within
    while group(pgid) and time.time() < t:
        time.sleep(0.05)
    return not group(pgid)


@pytest.mark.parametrize("grace, low, high", [("1", 0.9, 8), (None, 9.5, 25)])
def test_a_term_stops_the_whole_job_after_the_grace_and_removes_its_directory(tmp_path, grace, low, high):
    """M-40: TERM to the group, KILL after 10 s (PM_STOP_GRACE): stated in ORCA_RUNNER.md and never run.
    The stand-in proot ignores TERM, so only the KILL ends it."""
    w, env = proot_world(tmp_path, **({"PM_STOP_GRACE": grace} if grace else {}))
    p, d, pgid = start(w, env)
    try:
        t0 = time.time()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=40) == 143
        assert low <= time.time() - t0 < high
        assert not d.exists() and dead(pgid)
    finally:
        p.kill()
        p.wait()
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_a_killed_wrapper_leaves_its_job_and_directory_and_the_next_start_sweeps_only_when_the_job_has_ended(tmp_path):
    w, env = proot_world(tmp_path, PM_STOP_GRACE="1")
    ctypes.CDLL(None).prctl(36, 1, 0, 0, 0)                                      # PR_SET_CHILD_SUBREAPER
    groups, procs = [], []
    try:
        p1, d1, g1 = start(w, env)
        groups.append(g1)
        p1.kill()
        p1.wait()
        assert d1.exists() and group(g1)                                        # the job runs on, and so does its directory
        p2, d2, g2 = start(w, env)                                              # a second job while the first still runs
        groups.append(g2)
        procs.append(p2)
        assert d1.exists() and d2.exists()                                      # the live orphan's directory is not swept
        p2.send_signal(signal.SIGTERM)
        assert p2.wait(timeout=20) == 143 and not d2.exists() and d1.exists()
        members = group(g1, zombies=True)
        os.killpg(g1, signal.SIGKILL)
        assert dead(g1)
        reap(members)
        p3, d3, g3 = start(w, env)                                              # the orphan has ended: the next start removes its directory
        groups.append(g3)
        procs.append(p3)
        assert not d1.exists() and d3.exists()
        p3.send_signal(signal.SIGTERM)
        assert p3.wait(timeout=20) == 143 and not d3.exists()
    finally:
        for g in groups:
            try:
                os.killpg(g, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for p in procs:
            p.kill()
            p.wait()


def test_the_sweep_removes_the_directory_of_a_job_that_is_only_a_zombie(tmp_path):
    """`kill -0` is true for a zombie, which a PID 1 that does not reap orphans leaves for good: the directory was then never swept."""
    w, env = proot_world(tmp_path, PM_STOP_GRACE="1")
    zombie = subprocess.Popen(["true"])                                          # exited, not waited for: a zombie of this process
    t = time.time() + 10
    while pathlib.Path(f"/proc/{zombie.pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z" and time.time() < t:
        time.sleep(0.02)
    stale = w / "cafe/tmp/run.zombie"
    stale.mkdir(parents=True)
    (stale / ".pids").write_text(f"{zombie.pid} {zombie.pid}\n")
    p, d, pgid = start(w, env)
    try:
        assert not stale.exists() and d.exists()
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=20) == 143
    finally:
        p.kill()
        p.wait()
        zombie.wait()
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


# ---- round 9, L1: the shared pm/ has one owner --------------------------------------------------------------------------------------------------------

def test_l1_pm_sh_will_not_delete_the_files_of_the_checkout_that_owns_the_shared_dir(tmp_path):
    """M-39 sibling: with --delete, ./pm.sh from a second checkout removed the first one's new files under its running job."""
    home, env = live(tmp_path, "ssh", "docker")
    real_rsync_without_modes(tmp_path)
    dest = home / "work" / "cafe" / "pm"
    dest.mkdir(parents=True)
    a, b = tmp_path / "lead", tmp_path / "other"
    for src, files in ((a, ("common.py", "test_new.py")), (b, ("common.py",))):
        src.mkdir()
        for f in files:
            (src / f).write_text(src.name)
    assert run(["sh", str(ROOT / "pm.sh"), "true"], env, cwd=a).returncode == 0
    r = run(["sh", str(ROOT / "pm.sh"), "true"], env, cwd=b)
    assert r.returncode == 1 and "belongs to" in r.stderr and str(a.resolve()) in r.stderr
    assert sorted(p.name for p in dest.iterdir()) == ["common.py", "test_new.py"] and (dest / "common.py").read_text() == "lead"      # nothing was sent
    (a / "common.py").write_text("lead2")
    assert run(["sh", str(ROOT / "pm.sh"), "true"], env, cwd=a).returncode == 0 and (dest / "common.py").read_text() == "lead2"      # the owner again
    r = run(["sh", str(ROOT / "pm.sh"), "true"], {**env, "PM_TAKE": "1"}, cwd=b)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir()) == ["common.py"]                                                       # taken over: --delete as before
    assert run(["sh", str(ROOT / "pm.sh"), "true"], env, cwd=a).returncode == 1                                          # and now a is the other one


# ---- bin/orca_watch.sh counts the failures of a -vv log (round 9 P-6)

def watch_once(tmp_path, logs):
    """Run the flight recorder for one look at the job logs `logs` ({name: text}) in a scratch HOME; returns the problems.log lines (one tuple each)."""
    home, cg = tmp_path / "home", tmp_path / "cgroup"
    (home / "cafe-worker/logs").mkdir(parents=True)
    (home / "cafe-worker/.cafe-worker-owned").write_text("")
    cg.mkdir()
    (cg / "cpu.stat").write_text("usage_usec 0\nnr_throttled 0\n")
    (cg / "memory.current").write_text("0\n")
    (cg / "memory.events").write_text("oom_kill 0\n")
    for name, text in logs.items():
        (home / "cafe-worker/logs" / f"{name}.log").write_text(text)
    r = subprocess.run(["sh", str(ROOT / "bin/orca_watch.sh")], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(home), "WATCH_SLEEP": "0", "WATCH_ONCE": "1", "WATCH_CGROUP": str(cg), "CAFE_MIN_FREE_GB": "0"})
    assert r.returncode == 0, r.stderr
    p = home / "cafe-worker/logs/watch/problems.log"
    return [tuple(l.split("\t")[1:]) for l in p.read_text().splitlines()] if p.exists() else []


def test_the_recorder_counts_the_failed_and_error_lines_of_a_vv_log_but_not_the_summary_that_repeats_them(tmp_path):
    plain = ("tests/test_a.py::test_one PASSED                                    [ 20%]\n"
             "tests/test_a.py::test_two FAILED                                    [ 40%]\n"
             "tests/test_b.py::test_three[a b] ERROR                              [ 60%]\n"
             "tests/test_b.py::test_four PASSED                                   [ 80%]\n"
             "=========================== short test summary info ============================\n"
             "FAILED tests/test_a.py::test_two - assert 1 == 2\n"
             "ERROR tests/test_b.py::test_three[a b] - boom\n"
             "rc=1\n")
    xdist = ("[gw0] [ 25%] PASSED tests/test_a.py::test_one\n[gw1] [ 50%] FAILED tests/test_a.py::test_two\n[gw0] FAILED tests/test_b.py::test_x[1 2]\n"
             "FAILED tests/test_a.py::test_two - assert 1 == 2\n")
    clean = "tests/test_a.py::test_one PASSED  [100%]\nrc=0\n"
    dots = "..F.E. [ 50%]\n"
    got = dict(watch_once(tmp_path, {"plain": plain, "xdist": xdist, "clean": clean, "dots": dots}))
    assert got == {"plain": "failed tests 2, error lines 0, rc=1", "xdist": "failed tests 2, error lines 0, still running",
                   "dots": "failed tests 2, error lines 0, still running"}                      # a clean log with rc=0 is no problem; the dots still count


# ---- orca-go P-18: proot returns the status of the last process of the job to end

LAST_TRACEE = """#!/bin/sh
# What proot does about the exit status (rehearsed on orca: `(sleep 3; exit 0) & exit 1` gives 0): run the command, wait for every process it left behind,
# and answer with the status of the last one to end. The command comes after `/usr/bin/env -i VAR=value...`; its /tmp is $PROOT_TMP_DIR here.
while [ "$1" != /usr/bin/env ]; do shift; done
shift 2
while case "$1" in [A-Z_]*=*) true ;; *) false ;; esac; do shift; done
for a in "$@"; do set -- "$@" "$(printf '%s' "$a" | sed "s#/tmp/#$PROOT_TMP_DIR/#g")"; shift; done
"$@"
wait
exit "${LAST_STATUS:-0}"
"""


@pytest.mark.parametrize("job, want", [("exit 3", 3), ("(sleep 1; exit 0) & exit 3", 3), ("(sleep 1; exit 7) & exit 3", 3), ("true", 0),
                                       ("(sleep 1) & exit 0", 0)])
def test_the_exit_status_of_a_job_is_its_own_not_that_of_a_child_that_outlives_it(tmp_path, job, want):
    """The resource tracker of a spawned pool outlives the process and exits 0: a pytest run with a failure was rc=0 and the gate would have said ok."""
    w, env = proot_world(tmp_path, LAST_STATUS="0")
    (w / "bin/proot").write_text(LAST_TRACEE)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "sh", "-c", job], env)
    assert r.returncode == want, r.stderr
    assert not list((w / "cafe/tmp").glob("run.*"))



@pytest.mark.parametrize("job, last, want", [("kill -9 $PPID", "0", 1), ("mkdir /tmp/.rc; exit 0", "0", 1), ("kill -9 $PPID", "137", 137)])
def test_a_job_that_leaves_no_status_is_failed_when_proot_says_0_and_keeps_a_status_proot_gave(tmp_path, job, last, want):
    """No status file, from a killed job shell or a full disk, must not fall back on proot's 0: that is the last process's status (P-18), so a dead job
    read as passed."""
    w, env = proot_world(tmp_path, LAST_STATUS=last)
    (w / "bin/proot").write_text(LAST_TRACEE)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "sh", "-c", job], env)
    assert r.returncode == want, r.stderr
    assert ("left no exit status" in r.stderr) == (want == 1)


# ---- orca-go P-20: the thread pools of a job sized to the 64 CPUs nproc shows, not to its PM_CPUS

RECORD_ARGV = """#!/bin/sh
printf '%s\\n' "$@" > "$HOME/argv"
"""


@pytest.mark.parametrize("threads", ["1", "2", "16"])
def test_pm_threads_caps_the_blas_and_openmp_pools_of_the_job(tmp_path, threads):
    """8 jobs of 2 CPUs were at 29 of 32 CPUs in the first minutes of a suite: numpy's BLAS started 64 threads per job (a probe on orca: 17 CPUs busy for
    one matrix product, 1.9 with the cap)."""
    w, env = proot_world(tmp_path, PM_THREADS=threads)
    (w / "bin/proot").write_text(RECORD_ARGV)
    run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    argv = (tmp_path / "home/argv").read_text().splitlines()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        assert f"{var}={threads}" in argv
    assert argv.index("/usr/bin/env") < argv.index(f"OMP_NUM_THREADS={threads}") < argv.index("/bin/sh")   # in the job's environment, before its command


def test_without_pm_threads_the_pools_of_the_job_are_its_pm_cpus(tmp_path):
    """Round 15 (P-R14V5, amends the test that pinned "NUM_THREADS not in argv", DECISIONS 524): with PM_THREADS unset the pools are PM_CPUS, or 8 like
    CAFE_WORKERS."""
    w, env = proot_world(tmp_path)
    (w / "bin/proot").write_text(RECORD_ARGV)
    run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    argv = (tmp_path / "home/argv").read_text().splitlines()
    assert "CAFE_WORKERS=8" in argv and "OMP_NUM_THREADS=8" in argv and "OPENBLAS_NUM_THREADS=8" in argv and "MKL_NUM_THREADS=8" in argv


@pytest.mark.parametrize("bad", ["0", "02", "x", "2;ls", "-1", "1.5"])
def test_pm_threads_must_be_a_whole_number_from_one(tmp_path, bad):
    w, env = proot_world(tmp_path, PM_THREADS=bad)
    (w / "bin/proot").write_text(RECORD_ARGV)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    assert r.returncode == 2 and "PM_THREADS" in r.stderr and not (tmp_path / "home/argv").exists()


# ---- round 15, P-R14V5: under proot nothing kept a job to its PM_CPUS; it is pinned to that many cores and its pools sized to it

def cores_free_to_us():
    return sorted(os.sched_getaffinity(0))


DONE = 'echo 0 > "$PROOT_TMP_DIR/.rc"\n'          # the job's own exit status, which the wrapper insists on (see the tests above)


def pin_world(tmp_path, cpus, stand_in=RECORD_ARGV + DONE, **extra):
    """proot_world with a stand-in `taskset` that logs the pin and runs the rest (the query -pc goes to the real one); (world, env, log of pins)."""
    w, env = proot_world(tmp_path, PM_CPUS=str(cpus), **extra)
    (w / "bin/proot").write_text(stand_in)
    log = tmp_path / "taskset.log"
    real = shutil.which("taskset")
    (tmp_path / "tools" / "taskset").write_text(f'#!/bin/sh\ncase "$1" in -pc) exec {real} "$@" ;; esac\necho "$*" >> "{log}"\nshift 2\nexec "$@"\n')
    (tmp_path / "tools" / "taskset").chmod(stat.S_IRWXU)
    return w, env, log


def pinned(log):
    """The core lists of the pins in `log`, one set per job."""
    return [{int(c) for c in line.split()[1].split(",")} for line in log.read_text().splitlines()]


def two_or_one():
    return 2 if len(cores_free_to_us()) > 2 else 1


def test_r15_pb_the_job_is_pinned_to_pm_cpus_cores_and_its_pools_are_sized_to_them(tmp_path):
    """P-R14V5: a JAX matmul loop of a PM_CPUS=2 job under proot was at cpu/wall 32.1 on orca (the 32-CPU quota); pinned to 2 cores, pools at 2: 1.82."""
    n = two_or_one()
    w, env, log = pin_world(tmp_path, n)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    assert r.returncode == 0, r.stderr
    (cores,) = pinned(log)
    assert len(cores) == n and cores <= set(cores_free_to_us())
    assert f"pinned to cores {','.join(str(c) for c in sorted(cores))} (PM_CPUS={n})" in r.stderr
    assert log.read_text().split()[2] in ("setsid", str(w / "bin/proot"))               # the pin is in front of proot (and of setsid)
    argv = (tmp_path / "home/argv").read_text().splitlines()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        assert f"{var}={n}" in argv
    assert f"XLA_FLAGS=--xla_cpu_multi_thread_eigen=true intra_op_parallelism_threads={n}" in argv
    assert argv.index("/usr/bin/env") < argv.index(f"OMP_NUM_THREADS={n}") < argv.index("/bin/sh")


def test_r15_pb_pm_threads_sets_the_pools_to_its_own_number_and_the_pin_stays_at_pm_cpus(tmp_path):
    n = two_or_one()
    w, env, log = pin_world(tmp_path, n, PM_THREADS="1")
    assert run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env).returncode == 0
    argv = (tmp_path / "home/argv").read_text().splitlines()
    assert "OMP_NUM_THREADS=1" in argv and "intra_op_parallelism_threads=1" in " ".join(argv) and len(pinned(log)[0]) == n


def test_r15_pb_a_job_started_by_the_real_taskset_sees_only_its_pm_cpus_cores(tmp_path):
    """Not a stand-in: the job (the stand-in proot) reads the affinity it was started with from /proc."""
    n = two_or_one()
    w, env = proot_world(tmp_path, PM_CPUS=str(n))
    (w / "bin/proot").write_text('#!/bin/sh\ngrep Cpus_allowed_list /proc/self/status > "$HOME/allowed"\n' + DONE)
    assert run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env).returncode == 0
    listed = (tmp_path / "home/allowed").read_text().split(":")[1].strip()
    cores = {c for part in listed.split(",") for c in range(int(part.split("-")[0]), int(part.split("-")[-1]) + 1)}
    assert len(cores) == n and cores <= set(cores_free_to_us())


def test_r15_pb_two_jobs_started_at_once_get_different_cores_and_their_claims_go_with_them(tmp_path):
    """The K jobs of a gate start together; each takes the least busy cores, so without a claim they would all take the same ones."""
    w, env, log = pin_world(tmp_path, 1, stand_in="#!/bin/sh\nsleep 3\n" + DONE)
    jobs = [subprocess.Popen(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(2)]
    assert [j.wait(timeout=60) for j in jobs] == [0, 0]
    a, b = pinned(log)
    assert len(a) == len(b) == 1 and a != b
    assert not list((w / "cafe/tmp").glob("cpu.*")) and not list((w / "cafe/tmp").glob("run.*"))


def claim(w, core, pid):
    d = w / "cafe/tmp" / f"cpu.{core}"
    d.mkdir(parents=True)
    (d / "pid").write_text(f"{pid}\n")


def test_r15_pb_a_core_claimed_by_a_live_job_is_not_taken_and_one_claimed_by_a_dead_job_is(tmp_path):
    w, env, log = pin_world(tmp_path, 1)
    dead = subprocess.Popen(["true"])
    dead.wait()
    free = cores_free_to_us()
    for c in free[:-1]:
        claim(w, c, os.getpid())                                                      # alive: this process
    claim(w, free[-1], dead.pid)                                                      # its wrapper is gone
    assert run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env).returncode == 0
    assert pinned(log) == [{free[-1]}]


def test_r15_pb_with_every_core_claimed_the_job_still_runs_pinned_and_says_it_shares(tmp_path):
    w, env, log = pin_world(tmp_path, 1)
    for c in cores_free_to_us():
        claim(w, c, os.getpid())
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    assert r.returncode == 0 and "no free core for PM_CPUS=1, sharing core" in r.stderr
    assert len(pinned(log)[0]) == 1
    assert len(list((w / "cafe/tmp").glob("cpu.*"))) == len(cores_free_to_us())          # the claims of others are left


def cpus_in_proc_stat():
    return len(re.findall(r"^cpu\d+", pathlib.Path("/proc/stat").read_text(), re.M))


def test_r15_l0_jobs_started_at_once_over_stale_claims_get_distinct_cores_and_none_dies(tmp_path):
    """Round 15 look-ahead L0: the takeover of a stale claim was `rm -rf` then `mkdir` on the path, after the pid had been read. Jobs that read the same dead
    pid each removed the other's new claim: two jobs on the same cores, and one died writing its pid into the removed directory (8 jobs over 16 stale claims:
    cores pinned twice in 4 rounds of 6, a job dead in 3). The claim phase now runs under flock. The shell is told every CPU of /proc/stat may be used,
    so there are as many jobs as the machine has CPUs (at most 8), one core each, all started together."""
    n = cpus_in_proc_stat()
    jobs_n = min(8, n)
    w, env = proot_world(tmp_path, PM_CPUS="1")
    (w / "bin/proot").write_text("#!/bin/sh\nsleep 2\n" + DONE)
    log = tmp_path / "taskset.log"
    (tmp_path / "tools" / "taskset").write_text(f'#!/bin/sh\ncase "$1" in -pc) echo "pid 1 current affinity list: 0-{n - 1}"; exit 0 ;; esac\n'
                                                f'echo "$*" >> "{log}"\nshift 2\nexec "$@"\n')
    (tmp_path / "tools" / "taskset").chmod(stat.S_IRWXU)
    go = tmp_path / "go"
    dead = subprocess.Popen(["true"])
    dead.wait()
    for attempt in range(4):
        log.write_text("")
        for old in (w / "cafe/tmp").glob("cpu.*"):
            shutil.rmtree(old)
        for c in range(n):
            claim(w, c, dead.pid)
        go.unlink(missing_ok=True)
        wait_then_run = f'while [ ! -e "{go}" ]; do :; done; exec sh "$0" app true'
        procs = [subprocess.Popen(["sh", "-c", wait_then_run, str(ROOT / "bin/proot_run.sh")], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.PIPE, text=True) for _ in range(jobs_n)]
        go.write_text("")
        results = [(q.wait(timeout=120), q.stderr.read()) for q in procs]
        pins = pinned(log)
        assert [r for r, _ in results] == [0] * jobs_n, results
        assert len(pins) == jobs_n and all(len(x) == 1 for x in pins) and len({min(x) for x in pins}) == jobs_n, (attempt, pins)
        assert not any("sharing core" in e for _, e in results)
        left = [d for d in (w / "cafe/tmp").glob("cpu.*")]                                # only the stale claims nobody needed
        assert all((d / "pid").read_text().split() == [str(dead.pid)] for d in left)
        assert len(left) == n - jobs_n


def test_r15_l0_a_core_whose_wrapper_was_killed_but_whose_job_runs_is_not_taken_over(tmp_path):
    """Round 15 look-ahead L0: a claim held only the wrapper's pid, and `kill -9` of the wrapper leaves the job running (docs/ORCA_RUNNER.md) with its claims
    behind. The next job took that claim over as stale and pinned itself to cores the first job still ran on, with no warning, while the run.* directory of the
    same job is kept until its proot ends. A claim is live while the wrapper's or the job's pid is."""
    w, env, log = pin_world(tmp_path, 1, stand_in='#!/bin/sh\necho $$ >> "$HOME/jobpid"\nsleep 8\n' + DONE)
    free = cores_free_to_us()
    for c in free[1:]:
        claim(w, c, os.getpid())                                                      # alive: this process; only free[0] is left to take
    first = subprocess.Popen(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    job = tmp_path / "home/jobpid"                                                    # one line per job started: the first is `first`'s

    def first_job():
        return job.read_text().split()[0] if job.exists() and job.read_text().split() else ""
    try:
        for _ in range(200):
            if first_job():
                break
            time.sleep(0.1)
        time.sleep(0.5)                                                               # the wrapper writes the job's pid into its claims right after the start
        first.kill()
        first.wait()
        r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
        assert r.returncode == 0, r.stderr
        # P-R15G4: the core it shares is the least busy claimed one, so the load decides; assert it is one of ours and free[0]'s claim is left
        shared = re.search(r"no free core for PM_CPUS=1, sharing core (\d+) ", r.stderr)
        assert shared and int(shared.group(1)) in free, r.stderr
        assert (w / "cafe/tmp" / f"cpu.{free[0]}" / "pid").read_text().split()[-1] == first_job()
    finally:
        pid = first_job()
        if pid.isdigit():
            try:
                os.kill(int(pid), signal.SIGKILL)                                     # the stand-in job this test started, by its exact pid
            except OSError:
                pass


@pytest.mark.parametrize("script, cpus_default", [("bin/pmx.sh", "2"), ("pm.sh", "8")])
def test_r15_pb_the_docker_job_gets_its_pools_at_pm_cpus_as_the_proot_job_does(tmp_path, script, cpus_default):
    """The cgroup quota of `--cpus` leaves the pools at the host's CPU count (8 on homebase): 8 threads for 2 CPUs' worth of quota."""
    for given, n in ((None, cpus_default), ("3", "3")):
        rc, out = sent(tmp_path, script, "true", **({} if given is None else {"PM_CPUS": given}))
        flags = (f"-e OMP_NUM_THREADS={n} -e OPENBLAS_NUM_THREADS={n} -e MKL_NUM_THREADS={n} "
                 f"-e 'XLA_FLAGS=--xla_cpu_multi_thread_eigen=true intra_op_parallelism_threads={n}' ")
        assert rc == 0 and f"--cpus {n} " in out and flags in out


# ---- round 14 M-19: a count of 20 digits is refused by its length, not left to a `[` that prints "Illegal number" and falls through

@pytest.mark.parametrize("script, env", BOTH)
@pytest.mark.parametrize("var, runtime", [("PM_CPUS", "docker"), ("PM_CPUS", "proot"), ("CAFE_MIN_FREE_GB", "proot"), ("PM_THREADS", "proot")])
@pytest.mark.parametrize("value, ok", [("9" * 20, False), ("1000000000", False), ("999999999", True), ("99", True)])
def test_r14_m19_a_count_of_ten_digits_or_more_is_refused_before_anything_is_sent(tmp_path, script, env, var, runtime, value, ok):
    """M-19: the length alone decides (PM_CPUS=99 stays the documented warning on the worker, 999999999 is still a number)."""
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME=runtime, **env, **{var: value})
    assert (rc == 0 and "rsync" in out) if ok else (rc == 2 and out == "")


@pytest.mark.parametrize("var", ["PM_CPUS", "PM_THREADS", "CAFE_MIN_FREE_GB"])
def test_r14_m19_proot_run_refuses_a_count_of_twenty_digits_started_by_hand_and_prints_no_shell_error(tmp_path, var):
    """M-19: PM_CPUS=99999999999999999999 printed `[: Illegal number`, then the warning, and ran; CAFE_MIN_FREE_GB made `[` fail into a STOP about the disk."""
    w, env = proot_world(tmp_path)
    (w / "bin/proot").write_text(RECORD_ARGV)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], {**env, var: "9" * 20})
    assert r.returncode == 2 and var in r.stderr and "Illegal" not in r.stderr and "xpression" not in r.stderr and "STOP" not in r.stderr
    assert not (tmp_path / "home/argv").exists()


def test_r14_m19_proot_run_still_runs_with_a_short_cpu_count_above_32_and_only_warns(tmp_path):
    w, env = proot_world(tmp_path, PM_CPUS="99")
    (w / "bin/proot").write_text(RECORD_ARGV)
    r = run(["sh", str(ROOT / "bin/proot_run.sh"), "app", "true"], env)
    assert "above orca's 32 CPUs" in r.stderr and "Illegal" not in r.stderr and (tmp_path / "home/argv").exists()


def test_r14_m19_orca_sync_refuses_a_free_space_figure_of_twenty_digits_before_anything_is_sent(tmp_path):
    """M-19 sibling: the figure is compared with `[ -ge ]` on homebase, which printed 'integer expression expected' and stopped on the wrong ground."""
    home, env = sync_world(tmp_path)
    log = log_ssh(tmp_path)
    r = run(["sh", str(ROOT / "bin/orca_sync.sh"), "orca", "root"], {**env, "CAFE_MIN_FREE_GB": "9" * 20})
    assert r.returncode == 2 and "CAFE_MIN_FREE_GB" in r.stderr and not log.exists() and r.stdout == ""


@pytest.mark.parametrize("script, env", BOTH)
def test_r14_l0_a_free_space_floor_of_zero_switches_the_disk_check_off_through_every_runner(tmp_path, script, env):
    """Round 14 L0: pm_job took CAFE_MIN_FREE_GB through pm_num (1 and up), so the 0 that proot_run.sh, orca_sync.sh and their comments document as "no disk
    check" was refused (exit 2, nothing sent) by the laptop-side first gate of pmx.sh, pm.sh, orca_gate.sh and orca_ready.sh."""
    rc, out = sent(tmp_path, script, "true", PM_RUNTIME="proot", CAFE_MIN_FREE_GB="0", **env)
    assert rc == 0 and "CAFE_MIN_FREE_GB=0 " in out


def test_r14_l0_the_one_check_of_the_job_accepts_zero_for_the_free_space_floor_and_nothing_else_it_refused(tmp_path):
    check = lambda v: subprocess.run(["sh", "-c", ". bin/pm_checks.sh; PM_RUNTIME=proot pm_job"], cwd=ROOT, env={**os.environ, "CAFE_MIN_FREE_GB": v},  # noqa: E731
                                     capture_output=True, text=True).returncode
    assert [check(v) for v in ("0", "1", "999999999")] == [0, 0, 0]
    assert [check(v) for v in ("00x", "1.5", "1000000000", "1 2")] == [2, 2, 2, 2]


# ---- round 14 M-33: one checkout owns each pm_<you> directory on the worker; the gate has no directory made from its tag

def swallow_the_marker_write(tmp_path):
    """The stand-in ssh of `live`, except that the command which writes .pmx.owner does nothing."""
    (tmp_path / "tools" / "ssh").write_text('#!/bin/sh\nshift 3\ncase "$*" in *"> "*.pmx.owner*) exit 0 ;; esac\ncd "$HOME" || exit 1\nexec sh -c "$*"\n')


def test_r14_m33_pmx_sh_will_not_empty_a_directory_another_checkout_owns_and_pm_take_takes_it(tmp_path):
    """M-33: a second `pmx.sh` onto a PMX in use (or `orca_gate.sh` with a tag that is also a directory) replaced the files of the first under its job."""
    home, env = live(tmp_path, "ssh", "docker", PMX="pm_t")
    real_rsync_without_modes(tmp_path)
    dest = home / "work" / "cafe" / "pm_t"
    dest.parent.mkdir(parents=True)
    a, b = tmp_path / "lead", tmp_path / "other"
    for src, files in ((a, ("common.py", "test_new.py")), (b, ("common.py",))):
        src.mkdir()
        for f in files:
            (src / f).write_text(src.name)
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 0
    assert str(a.resolve()) in (dest / ".pmx.owner").read_text()
    r = run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=b)
    assert r.returncode == 1 and "belongs to" in r.stderr and str(a.resolve()) in r.stderr and "PM_TAKE=1" in r.stderr
    assert sorted(p.name for p in dest.iterdir() if p.name != ".pmx.owner") == ["common.py", "test_new.py"]
    assert (dest / "common.py").read_text() == "lead"                                                                    # nothing was sent
    (a / "common.py").write_text("lead2")
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 0 and (dest / "common.py").read_text() == "lead2"      # the owner again
    r = run(["sh", str(ROOT / "bin/pmx.sh"), "true"], {**env, "PM_TAKE": "1"}, cwd=b)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in dest.iterdir() if p.name != ".pmx.owner") == ["common.py"] and str(b.resolve()) in (dest / ".pmx.owner").read_text()
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 1                                          # and now a is the other one


def test_r14_m33_a_directory_with_no_marker_is_synced_and_other_pmx_directories_are_not_touched(tmp_path):
    home, env = live(tmp_path, "ssh", "docker", PMX="pm_t")
    real_rsync_without_modes(tmp_path)
    other = home / "work" / "cafe" / "pm_other"
    other.mkdir(parents=True)
    (other / ".pmx.owner").write_text("elsewhere:/x\n")
    (other / "f.py").write_text("theirs")
    a = tmp_path / "lead"
    a.mkdir()
    (a / "f.py").write_text("mine")
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 0
    assert (home / "work/cafe/pm_t/f.py").read_text() == "mine"
    assert (other / "f.py").read_text() == "theirs" and (other / ".pmx.owner").read_text() == "elsewhere:/x\n"


def test_r14_m33_the_marker_survives_the_delete_of_the_sync_so_that_no_other_checkout_sees_a_gap(tmp_path):
    """The marker is written after the copy, so a copy that deleted it would leave a gap between the two in which a second checkout finds no owner."""
    home, env = live(tmp_path, "ssh", "docker", PMX="pm_t")
    real_rsync_without_modes(tmp_path)
    a = tmp_path / "lead"
    a.mkdir()
    (a / "f.py").write_text("1")
    dest = home / "work" / "cafe" / "pm_t"
    dest.parent.mkdir(parents=True)
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 0
    first = (dest / ".pmx.owner").read_text()
    swallow_the_marker_write(tmp_path)
    (a / "g.py").write_text("2")
    assert run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env, cwd=a).returncode == 0
    assert (dest / "g.py").exists() and (dest / ".pmx.owner").read_text() == first


def test_r14_m33_the_gate_from_a_new_worktree_runs_with_a_plain_pm_take_and_not_without(tmp_path):
    """The documented gate command is run from a new merge worktree every round, which is another checkout: PM_TAKE=1 alone must be enough."""
    home, env = live(tmp_path, "ssh", "rsync", "tmux", PMX="pm_g")
    d = home / "cafe-worker" / "cafe" / "pm_g"
    (d / "bin").mkdir(parents=True)
    (d / "bin" / "proot_suite.sh").write_text("exit 0\n")
    (d / ".pmx.owner").write_text("laptop:/elsewhere/cafe-r13m\n")
    gate = ["sh", str(ROOT / "bin/orca_gate.sh"), "8", "gate1", "--cov"]
    r = run(gate, env)
    assert r.returncode == 1 and "belongs to laptop:/elsewhere/cafe-r13m" in r.stderr and not (home / "rsync.log").exists()
    r = run(gate, {**env, "PM_TAKE": "1"})
    assert r.returncode == 0, r.stderr
    assert "--delete" in (home / "rsync.log").read_text() and (d / ".pmx.owner").read_text().strip() != "laptop:/elsewhere/cafe-r13m"


# ---- round 10 M-30: bin/orca_ready.sh takes the caller's PMX and names its marker for it; only a name of ours fails the last check

def ready_world(tmp_path):
    """(home, cwd, env): a scratch worker HOME that passes the completeness check, and a scratch checkout whose bin/pmx.sh is a stand-in that logs its PMX."""
    home, env = live(tmp_path, "ssh")
    w = home / "cafe-worker"
    for f in ("bin/proot", "root.done", "pmdata.done", "data.done", "env/bin/rsync", "env/bin/tmux"):
        (w / f).parent.mkdir(parents=True, exist_ok=True)
        (w / f).write_text("")
    cwd = tmp_path / "checkout"
    (cwd / "bin").mkdir(parents=True)
    for n in ("orca_ready.sh", "pm_checks.sh"):
        shutil.copy(ROOT / "bin" / n, cwd / "bin" / n)
    (cwd / "bin" / "pmx.sh").write_text('#!/bin/sh\necho "PMX=$PMX PM_CPUS=$PM_CPUS" >> "$HOME/cafe-worker/pmx.log"\n'
                                        'sleep 1\n[ -z "$LEAK" ] || touch "$HOME/$LEAK"\n')
    (cwd / "bin" / "pmx.sh").chmod(stat.S_IRWXU)
    return home, cwd, {**env, "CAFE_MIN_FREE_GB": "1", "PM_HOST": "worker"}


@pytest.mark.parametrize("given, name", [({}, "pm_ready"), (dict(PMX="pm_mine"), "pm_mine")])
def test_m30_the_go_check_uses_the_callers_pmx_and_a_start_marker_of_that_name(tmp_path, given, name):
    """M-30: `export PMX=pm_ready` overrode the caller's, so the documented PMX=pm_<you> did nothing and two checks synced onto one directory with --delete."""
    home, cwd, env = ready_world(tmp_path)
    r = run(["sh", "bin/orca_ready.sh"], {**env, **given}, cwd=cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "cafe-worker" / "pmx.log").read_text() == f"PMX={name} PM_CPUS=2\n" * 2
    assert sorted(p.name for p in (home / "cafe-worker").glob(".ready_start*")) == [f".ready_start_{name}"]
    assert r.stdout.rstrip().endswith("orca-ready")


def test_m30_a_change_outside_cafe_worker_fails_the_check_only_when_its_name_is_ours(tmp_path):
    """M-30: on the shared account any other user's file at depth 2 that was newer than the marker failed the check."""
    home, cwd, env = ready_world(tmp_path)
    r = run(["sh", "bin/orca_ready.sh"], {**env, "LEAK": "somebody_elses_file"}, cwd=cwd)
    assert r.returncode == 0 and "warning" in r.stdout and "./somebody_elses_file" in r.stdout and r.stdout.rstrip().endswith("orca-ready")
    for ours in ("cafe_leak", "pm_leak", "pmx_leak"):
        r = run(["sh", "bin/orca_ready.sh"], {**env, "LEAK": ours}, cwd=cwd)
        assert r.returncode == 1 and "STOP" in r.stderr and f"./{ours}" in r.stderr and "orca-ready" not in r.stdout


@pytest.mark.parametrize("given", [dict(PMX="pm_a;touch pwned"), dict(PMX="pmdata"), dict(CAFE_MIN_FREE_GB="1;touch pwned"),
                                   dict(PM_STOP_GRACE="1;touch pwned")])
def test_m30_what_is_pasted_into_the_ssh_command_lines_is_checked_first(tmp_path, given):
    home, cwd, env = ready_world(tmp_path)
    r = run(["sh", "bin/orca_ready.sh"], {**env, **given}, cwd=cwd)
    assert r.returncode == 2 and not (home / "pwned").exists() and not list((home / "cafe-worker").glob(".ready_start*"))


# ---- round 11 M-18, M-19, M-33: the address check, orca_ready.sh's ps, worker_setup.sh's disk and docker group, the usage line

def log_ssh(tmp_path):
    """Make the stand-in ssh of `live` note every call in ssh.log (it is not created when ssh is never called); returns that path."""
    log = tmp_path / "ssh.log"
    (tmp_path / "tools" / "ssh").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n' + TOOLS["ssh"].split("\n", 1)[1])
    return log


@pytest.mark.parametrize("ip", ["x;id", "1.2.3.4 id", "1.2.3.4 ", " 1.2.3.4", "-oProxyCommand=x", "$(id)", "a'b", "1.2.3.4\nid"])
def test_r11_m18_an_address_that_is_a_command_is_refused_before_orca_sync_sends_anything(tmp_path, ip):
    """Round 11 M-18: `sh bin/orca_sync.sh 'x;id' root` ran an ssh on homebase with the bad address before anything checked it."""
    home, env = sync_world(tmp_path)
    log = log_ssh(tmp_path)
    r = run(["sh", str(ROOT / "bin/orca_sync.sh"), ip, "root"], env)
    assert r.returncode == 2 and "orca address" in r.stderr and not log.exists() and r.stdout == ""


@pytest.mark.parametrize("ip", ["100.64.1.2", "fd7a:115c:a1e0::1", "orca.tail1234.ts.net", "orca"])
def test_r11_m18_ipv4_ipv6_and_dns_names_are_still_sent(tmp_path, ip):
    home, env = sync_world(tmp_path)
    r = run(["sh", str(ROOT / "bin/orca_sync.sh"), ip], env)
    assert r.returncode == 0 and "== done" in r.stdout, r.stderr


@pytest.mark.parametrize("w", ["u@h;id", "u@h id", "u;id@h", "u@-oProxyCommand=x", "@host", "u@", "-u@h", "$(id)@h", ""])
def test_r11_m18_a_worker_that_is_a_command_is_refused_before_worker_setup_reaches_homebase(tmp_path, w):
    """Round 11 M-18 sibling: worker_setup.sh pastes its first argument into the script homebase runs."""
    home, env = live(tmp_path, "ssh")
    log = log_ssh(tmp_path)
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), w], env)
    assert r.returncode == 2 and not log.exists()


@pytest.mark.parametrize("key", ["$(touch {home}/pwned)", "`touch {home}/pwned`", "k;touch {home}/pwned", "k touch {home}/pwned",
                                 "-oProxyCommand=x", "$HOMEx", "$HOME", "$HOME/k'x"])
def test_r11_m18_a_key_that_is_a_command_is_refused_before_worker_setup_reaches_homebase(tmp_path, key):
    """Round 11 M-18 sibling: the key argument was pasted unchecked beside the address, so `$(touch ...)` in it ran on homebase."""
    home, env, log = setup_machine(tmp_path, 100 * 1048576)
    ssh_log = log_ssh(tmp_path)
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host", key.format(home=home)], env)
    assert r.returncode == 2 and "key path" in r.stderr and not ssh_log.exists() and not (home / "pwned").exists()


@pytest.mark.parametrize("key", [[], ["$HOME/.ssh/k_1-a.pem"], ["/home/u/.ssh/k"], ["~/.ssh/k"]])
def test_r11_m18_a_key_path_is_still_sent(tmp_path, key):
    home, env, log = setup_machine(tmp_path, 100 * 1048576)
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host", *key], env)
    assert r.returncode == 0 and "rsync" in log.read_text(), r.stderr


def setup_machine(tmp_path, kb, ps_rc=0):
    """(home, env, log): worker_setup.sh with ssh running here, `df` reporting `kb` free, `docker ps` ending `ps_rc`; sudo, rsync, docker load log to `log`."""
    home, env = live(tmp_path, "ssh", "tmux")
    log = tmp_path / "setup.log"
    tools = tmp_path / "tools"
    stubs = {"df": f'#!/bin/sh\necho Filesystem\necho "/dev/x 1 1 {kb} 1% /"\n',
             "sudo": f'#!/bin/sh\necho "sudo $*" >> "{log}"\n',
             "rsync": f'#!/bin/sh\necho "rsync $*" >> "{log}"\n',
             "docker": f'#!/bin/sh\ncase "$1" in ps) exit {ps_rc} ;; load) echo "docker load" >> "{log}" ;; esac\n'}
    for n, body in stubs.items():
        (tools / n).write_text(body)
        (tools / n).chmod(stat.S_IRWXU)
    return home, env, log


def test_r11_m19_worker_setup_checks_the_25_gb_it_says_it_needs_before_installing_or_copying(tmp_path):
    home, env, log = setup_machine(tmp_path, 24 * 1048576)
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host"], env)
    assert r.returncode == 1 and "only 24 GB free" in r.stderr and "25 GB needed" in r.stderr and not log.exists()
    home, env, log = setup_machine(tmp_path, 25 * 1048576)
    run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host"], env)
    assert "rsync" in log.read_text()


WORKER_DIRS = ["pmdata/bin", "pmdata/dtmb5415", "pmdata/bathy", "pmdata/tao", "pmdata/cache", "pmdata/ocean", "data"]


def fill_worker(home, leave_out=None):
    for d in WORKER_DIRS:
        if d != leave_out:
            (home / "work" / "cafe" / d).mkdir(parents=True)


def test_l1_r11_worker_setup_run_again_on_a_finished_worker_with_less_than_25_gb_free_goes_on_to_top_it_up(tmp_path):
    """Round 11 look-ahead L1: the 25 GB check ran before the idempotent steps, so the install's own use of the disk stopped the re-run that is called safe."""
    home, env, log = setup_machine(tmp_path, 24 * 1048576)
    fill_worker(home)                                                   # the docker stand-in answers `image inspect` as an image that is there
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host"], env)
    assert r.returncode == 0 and "25 GB needed" not in r.stderr and "rsync" in log.read_text(), r.stderr


@pytest.mark.parametrize("what", [*WORKER_DIRS, "image"])
def test_l1_r11_worker_setup_still_checks_the_25_gb_when_the_image_or_a_data_directory_is_missing(tmp_path, what):
    home, env, log = setup_machine(tmp_path, 24 * 1048576)
    fill_worker(home, leave_out=what)
    if what == "image":
        (tmp_path / "tools" / "docker").write_text('#!/bin/sh\ncase "$1" in ps) exit 0 ;; image) exit 1 ;; esac\n')
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host"], env)
    assert r.returncode == 1 and "only 24 GB free" in r.stderr and not log.exists()


def test_r11_m19_worker_setup_stops_after_adding_the_login_to_the_docker_group(tmp_path):
    """Round 11 M-19: it went on to `docker load` in the session that does not have the group yet, and failed there."""
    home, env, log = setup_machine(tmp_path, 100 * 1048576, ps_rc=1)
    r = run(["sh", str(ROOT / "bin/worker_setup.sh"), "u@host"], env)
    assert r.returncode == 1 and "Log out of it and run this again" in r.stderr
    assert log.read_text().startswith("sudo usermod -aG docker") and "rsync" not in log.read_text() and "docker load" not in log.read_text()


def test_r11_m19_the_go_check_lists_process_names_and_no_accounts(tmp_path):
    """Round 11 M-19: `ps -eo user:12,pcpu,comm` printed the account of every busy process on the shared machine."""
    home, cwd, env = ready_world(tmp_path)
    (tmp_path / "tools" / "ps").write_text('#!/bin/sh\necho "$*" >> "$HOME/ps.args"\necho "  %CPU COMMAND"\n')
    (tmp_path / "tools" / "ps").chmod(stat.S_IRWXU)
    r = run(["sh", "bin/orca_ready.sh"], env, cwd=cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "ps.args").read_text() == "-eo pcpu,comm --sort=-pcpu\n"
    assert "depth 2" in (ROOT / "bin/orca_ready.sh").read_text()


def test_r11_m33_run_premissions_usage_line_names_every_budget_the_command_accepts():
    """Round 11 M-33: the usage line left out `ci`."""
    usage = (ROOT / "bin/run_premission").read_text().splitlines()[1]
    assert re.search(r"--budget <([a-z0-9|]+)>", usage).group(1).split("|") == list(budget.BUDGET_S)


# ---- round 10 M-26: orca_watch.sh notes a second dip of the disk and a rerun that fails the same way

def watch_home(tmp_path):
    """(home, env): a scratch HOME and cgroup for orca_watch.sh, and a fake df whose free space is the next line of $HOME/free_seq (500 GB when it is empty)."""
    home, cg, tools = tmp_path / "home", tmp_path / "cgroup", tmp_path / "tools"
    (home / "cafe-worker/logs").mkdir(parents=True, exist_ok=True)
    (home / "cafe-worker/.cafe-worker-owned").write_text("")
    cg.mkdir(exist_ok=True)
    tools.mkdir(exist_ok=True)
    (cg / "cpu.stat").write_text("usage_usec 0\nnr_throttled 0\n")
    (cg / "memory.current").write_text("0\n")
    (cg / "memory.events").write_text("oom_kill 0\n")
    (tools / "df").write_text('#!/bin/sh\ncase "$*" in\n  *-Pk*) v=$(head -n 1 "$HOME/free_seq" 2>/dev/null); sed -i 1d "$HOME/free_seq" 2>/dev/null\n'
                              '    echo "Filesystem 1K-blocks Used Available Use% Mounted"\n'
                              '    echo "x 1 1 $(( ${v:-500} * 1048576 )) 1% /" ;;\n  *) echo x ;;\nesac\n')
    # ends the endless loop after the last value
    (tools / "sleep").write_text('#!/bin/sh\n[ -e "$HOME/stop_when_empty" ] && [ ! -s "$HOME/free_seq" ] && kill $PPID\nexit 0\n')
    for n in ("df", "sleep"):
        (tools / n).chmod(stat.S_IRWXU)
    return home, {**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(home), "WATCH_SLEEP": "0", "WATCH_CGROUP": str(cg),
                  "CAFE_MIN_FREE_GB": "10"}


def problems(home):
    p = home / "cafe-worker/logs/watch/problems.log"
    return [tuple(l.split("\t")[1:]) for l in p.read_text().splitlines()] if p.exists() else []


def test_m26_the_disk_note_is_written_again_when_the_disk_recovers_and_falls_but_not_while_it_hovers(tmp_path):
    """M-26: `low` was never cleared, so the second dip of a watch left only a timeline row. The line is FLOOR 10 + 40 = 50 GB; recovery needs 55."""
    home, env = watch_home(tmp_path)
    (home / "free_seq").write_text("".join(f"{g}\n" for g in (60, 45, 45, 52, 49, 54, 40, 55, 48, 48)))
    (home / "stop_when_empty").write_text("")
    subprocess.run(["sh", str(ROOT / "bin/orca_watch.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    got = problems(home)
    assert [g[0] for g in got] == ["disk", "disk"]            # 45 first; 52, 49, 54 and 40 are the same dip; 55 clears it; 48 is the second
    assert got[0][1].startswith("only 45 GB") and got[1][1].startswith("only 48 GB")
    assert len(list((home / "cafe-worker/logs/watch").glob("snap_*_disk.txt"))) >= 1
    assert len((home / "cafe-worker/logs/watch/timeline.tsv").read_text().splitlines()) == 11      # header and a row per look: the loop ran to the end


def look(home, env, text, mtime):
    """One look of the recorder at job log j, which has just been rewritten in place (as the shell's `>` of bin/pmx.sh does)."""
    f = home / "cafe-worker/logs/j.log"
    f.write_text(text)
    os.utime(f, (mtime, mtime))
    r = subprocess.run(["sh", str(ROOT / "bin/orca_watch.sh")], capture_output=True, text=True, timeout=60, env={**env, "WATCH_ONCE": "1"})
    assert r.returncode == 0, r.stderr
    return problems(home)


def test_m26_a_rerun_that_fails_in_the_same_way_between_two_looks_is_noted_again(tmp_path):
    """M-26: a rerun rewrites the log in place; its counts equalled the last look's, so the state comparison hid it."""
    home, env = watch_home(tmp_path)
    bad = "..F.E. [ 50%]\nrc=1\n"
    note = ("j", "failed tests 2, error lines 0, rc=1")
    assert look(home, env, bad, 1_000_000) == [note]
    assert look(home, env, bad, 1_000_000) == [note]                                  # looked at again, unchanged: no second note
    assert look(home, env, bad, 1_000_900) == [note, note]                            # the same text, written by a later run
    ok = "tests/a.py::t PASSED\nrc=0\n"
    assert look(home, env, ok, 1_002_000) == [note, note] and look(home, env, ok, 1_003_000) == [note, note]      # a passing rerun adds nothing


@pytest.mark.parametrize("tm", ["a_s2", "a_serial", "a_shares", "a_audit"])
def test_m28_a_job_name_that_is_a_log_of_the_suite_is_refused_under_proot_only(tmp_path, tm):
    """M-28: the sweep of tag a deletes a_s<i>.log; a plain TM job of that name has its log in the same folder."""
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="proot", PMX="pm_t", TM=tm)
    assert rc == 2 and out == ""
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="docker", PMX="pm_t", TM=tm)
    assert rc == 0 and "rsync" in out


def test_r13_m24_run_sh_tells_the_container_the_commit_and_whether_the_tree_is_dirty(tmp_path):
    """`./run.sh` passed neither: the synced cafe/ has no .git, so what it stamped (cafe.cfd) named git "none". A stand-in `git` answers for the checkout."""
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "git").write_text('#!/bin/sh\ncase "$1" in rev-parse) echo 0123456789abcdef0123456789abcdef01234567 ;; status) echo " M cafe/x.py" ;; esac\n')
    (tools / "git").chmod(stat.S_IRWXU)
    rc, out = sent(tmp_path, "run.sh", "python", "-m", "cafe.cfd", "external")
    assert rc == 0 and "-e CAFE_GIT_SHA=0123456789abcdef0123456789abcdef01234567 -e CAFE_GIT_DIRTY=1 " in out and "cafe python -m cafe.cfd external" in out


def test_r14_m33_a_second_sync_from_the_owning_checkout_is_refused_while_its_detached_job_runs_and_not_after(tmp_path, request):
    """M-33, first sentence: the owner marker only compares checkouts, so `pmx.sh` from the same checkout replaced the files under a TM= job."""
    home, env = live(tmp_path, "ssh", "rsync", "docker", "tmux", PMX="pm_t", TM="held")
    real_rsync_without_modes(tmp_path)
    dest = home / "work" / "cafe" / "pm_t"
    dest.parent.mkdir(parents=True)
    a = tmp_path / "lead"
    a.mkdir()
    (a / "README.md").write_text("r")
    (a / "common.py").write_text("1")
    release = tmp_path / "release"
    request.addfinalizer(lambda: release.write_text(""))       # a failed assert must not leave the job looping
    job = tmp_path / "job.sh"
    job.write_text(f"while [ ! -e {release} ]; do sleep 0.2; done\n")
    pmx = ["sh", str(ROOT / "bin/pmx.sh")]
    assert run([*pmx, "sh", str(job)], env, cwd=a).returncode == 0
    (a / "README.md").unlink()
    (a / "common.py").write_text("22")
    r = run([*pmx, "true"], {**env, "TM": "other"}, cwd=a)
    assert r.returncode == 1 and "held" in r.stderr and "still running" in r.stderr and "PM_TAKE=1" in r.stderr
    assert (dest / "README.md").exists() and (dest / "common.py").read_text() == "1"                                  # nothing was sent
    assert run([*pmx, "true"], {k: v for k, v in env.items() if k != "TM"}, cwd=a).returncode == 1                  # a foreground sync is refused the same way
    r = run([*pmx, "true"], {**{k: v for k, v in env.items() if k != "TM"}, "PM_TAKE": "1"}, cwd=a)
    assert r.returncode == 0, r.stderr                                                                             # PM_TAKE=1 syncs anyway
    assert not (dest / "README.md").exists()
    release.write_text("")
    for _ in range(100):                                                                                           # the job ends, its session is gone
        if not (home / "tmuxstate" / "held").exists():
            break
        time.sleep(0.1)
    (a / "common.py").write_text("three")
    r = run([*pmx, "true"], {k: v for k, v in env.items() if k != "TM"}, cwd=a)
    assert r.returncode == 0, r.stderr                                                                     # a finished job leaves a name only
    assert (dest / "common.py").read_text() == "three"


def wait_for_session_to_end(home, name):
    for _ in range(100):
        if not (home / "tmuxstate" / name).exists():
            return
        time.sleep(0.1)


def test_r15_pb_a_finished_jobs_directory_is_not_held_by_another_directory_that_reuses_its_tag(tmp_path, request):
    """P-R14L-OPEN (f): `.pmx.job.<dir>` holds a tag, and the sync is refused while a tmux session of that name is alive. pm_a ran a job under tag `shared` and
    finished; pm_b now runs its own job under `shared`: pm_a was refused as "still running" because of pm_b's session. pm_b's own directory stays held."""
    home, env = live(tmp_path, "ssh", "rsync", "docker", "tmux", TM="shared")
    release = tmp_path / "release"
    request.addfinalizer(lambda: release.write_text(""))                          # a failed assert must not leave the job looping
    quick, long = tmp_path / "quick.sh", tmp_path / "long.sh"
    quick.write_text("true\n")
    long.write_text(f"while [ ! -e {release} ]; do sleep 0.2; done\n")
    pmx = ["sh", str(ROOT / "bin/pmx.sh")]
    assert run([*pmx, "sh", str(quick)], {**env, "PMX": "pm_a"}).returncode == 0
    wait_for_session_to_end(home, "shared")
    assert run([*pmx, "sh", str(long)], {**env, "PMX": "pm_b"}).returncode == 0
    assert (home / "tmuxstate" / "shared").exists()                               # the tag is alive, and it is pm_b's
    plain = {k: v for k, v in env.items() if k != "TM"}
    r = run([*pmx, "true"], {**plain, "PMX": "pm_a"})
    assert r.returncode == 0, r.stderr                                           # pm_a has no job: it syncs
    r = run([*pmx, "true"], {**plain, "PMX": "pm_b"})
    assert r.returncode == 1 and "shared" in r.stderr and "still running" in r.stderr and "PM_TAKE=1" in r.stderr         # pm_b's job is real
    release.write_text("")
    wait_for_session_to_end(home, "shared")


def test_r15_pb_a_session_started_before_the_directory_was_recorded_still_holds_its_directory(tmp_path):
    """The directory is recorded in the session after the start (tmux set-environment); a session that has none (started by the previous version of
    the script) is counted as the job of the directory that names it, so an upgrade in the middle of a gate does not open the sync. The directory has no
    `.pmx.owner` here (a first sync by an older script): `1,/^---$/d` of GNU sed then deleted the job's name along with the empty owner's `---` line, and
    nothing was held."""
    home, env = live(tmp_path, "ssh", "rsync", "docker", "tmux", PMX="pm_t")
    (home / "tmuxstate").mkdir()
    (home / "tmuxstate" / "old").write_text("")
    (home / "work" / "cafe").mkdir(parents=True)
    (home / "work" / "cafe" / ".pmx.job.pm_t").write_text("old")
    r = run(["sh", str(ROOT / "bin/pmx.sh"), "true"], env)
    assert r.returncode == 1 and "old" in r.stderr and "still running" in r.stderr
