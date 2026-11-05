"""On orca, a shared machine, the runners stay inside ~/cafe-worker. These read what bin/pmx.sh and pm.sh would send, with ssh and rsync replaced by loggers."""
import os
import stat
import subprocess

import pytest

from cafe.pm import config

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


@pytest.mark.parametrize("name", [dict(PMX=".."), dict(PMX="../x"), dict(PMX="a/b"), dict(TM="../x")])
def test_a_name_cannot_point_rsync_delete_or_a_log_outside(tmp_path, name):
    rc, out = sent(tmp_path, "bin/pmx.sh", "true", PM_RUNTIME="proot", **name)
    assert rc == 2 and out == ""


def test_a_failed_copy_does_not_run_the_job_on_stale_code(tmp_path):
    rc, out = sent(tmp_path, "bin/pmx.sh", "true")
    assert rc == 0 and "work/cafe/pm_x/" in out and "docker run" in out          # docker keeps its paths
    (tmp_path / "tools" / "rsync").write_text("#!/bin/sh\nexit 23\n")
    (tmp_path / "sent.log").unlink()
    r = subprocess.run(["sh", str(ROOT / "bin/pmx.sh"), "true"], cwd=ROOT, capture_output=True, text=True, timeout=30,
                       env={"PATH": f"{tmp_path / 'tools'}:{os.environ['PATH']}", "HOME": str(tmp_path), "PM_HOST": "worker"})
    assert r.returncode == 1 and not (tmp_path / "sent.log").exists()


def test_the_worker_side_scripts_stay_inside_too():
    run = (ROOT / "bin/proot_run.sh").read_text()
    assert 'C="$W/cafe"' in run and "work/cafe" not in run
    copy = (ROOT / "bin/orca_sync.sh").read_text()
    assert "-C cafe-worker/cafe/$p" in copy and "-C work/cafe" not in copy
