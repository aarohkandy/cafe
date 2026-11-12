"""Round 16, prefix B: the live app and the runners (cafe/*.py outside cafe/pm, run.sh, sync.sh). Each test names its finding; the fix was removed in a
throwaway detached worktree and the test was seen to fail, then to pass with it (review/orca/PROBLEMS.md has the runs)."""
import ast
import datetime as dt
import json
import os
import stat
import subprocess
import sys

import numpy as np
import pytest

from cafe import atomic, cfd, fea, ocean
from cafe.pm import config

ROOT = config.ROOT


# ---- P-R15L0-3: the app reads the hull mesh from config/assumptions.yaml, so run.sh must send config/ with cafe/ --------------------------------------

def remote_copy(tmp_path, script):
    """Runs `script` (run.sh or sync.sh) from the checkout with ssh logged and rsync replaced by a local copy into `tmp_path/home/work/cafe/src`, the
    directory the live app mounts at /app. Returns (exit code, the ssh command lines, the remote tree)."""
    tools, remote, log = tmp_path / "tools", tmp_path / "remote", tmp_path / "ssh.log"
    tools.mkdir()
    (tools / "ssh").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    # rsync [-az --delete --exclude X ...] -e <ssh> SRC azureuser@host:DEST: SRC is a directory (a trailing slash means its content); DEST is under `remote`
    (tools / "rsync").write_text(f'''#!/bin/sh
for last; do :; done
src=""; while [ $# -gt 1 ]; do src=$1; shift; done
dest="{remote}/${{last#*:}}"
mkdir -p "$dest" && cp -R "$src". "$dest" && find "$dest" -name __pycache__ -prune -exec rm -rf {{}} +
''')
    for t in ("ssh", "rsync"):
        (tools / t).chmod(stat.S_IRWXU)
    r = subprocess.run(["sh", str(ROOT / script), "true"], cwd=ROOT, capture_output=True, text=True, timeout=120,
                       env={"PATH": f"{tools}:{os.environ['PATH']}", "HOME": str(tmp_path)})
    return r.returncode, log.read_text() if log.exists() else "", remote / "work/cafe/src"


def test_p_r15l0_3_the_app_tree_after_run_sh_reads_the_hull_mesh_number_of_this_checkout(tmp_path):
    """`run.sh` copied only `cafe/` to `~/work/cafe/src` (mounted at /app), so after an edit of `config/` the app's `fea.hull_elements_along()` read
    /app/config/assumptions.yaml as the last `sync.sh` left it: an older number (the Hangar's hull case then meshed by L/20 where the pipeline meshed by L/70),
    or FileNotFoundError on a tree that never had `config/`. The remote starts with a stale file, then with none; each run must leave this checkout's,
    so the app reads the number the pipeline reads."""
    for stale in (True, False):
        work = tmp_path / str(stale)
        work.mkdir()
        if stale:
            (work / "remote/work/cafe/src/config").mkdir(parents=True)
            (work / "remote/work/cafe/src/config/assumptions.yaml").write_text("stage3:\n  fea_elements_along:\n    value: 20\n")
        rc, ssh, src = remote_copy(work, "run.sh")
        assert rc == 0 and src == work / "remote/work/cafe/src"
        assert (src / "config/assumptions.yaml").read_bytes() == (ROOT / "config/assumptions.yaml").read_bytes() and (src / "cafe/fea.py").is_file()
        seen = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.'); from cafe import fea; print(fea.hull_elements_along())"],
                              cwd=src, capture_output=True, text=True, timeout=120)
        assert seen.returncode == 0 and seen.stdout.strip() == str(fea.hull_elements_along()), seen.stderr[-400:]


def test_p_r15l0_3_sync_sh_sends_the_whole_tree_so_config_goes_with_the_code(tmp_path):
    """`sync.sh` is the other way a tree reaches the app: it sends `./` with `--delete` and leaves out only `.git` and `__pycache__`, so `config/` is
    there (a new exclude of it would bring the problem back)."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools/rsync").write_text(f'#!/bin/sh\necho "$*" >> "{tmp_path}/rsync.log"\n')
    (tmp_path / "tools/ssh").write_text("#!/bin/sh\n")
    for t in ("ssh", "rsync"):
        (tmp_path / "tools" / t).chmod(stat.S_IRWXU)
    r = subprocess.run(["sh", str(ROOT / "sync.sh")], cwd=ROOT, capture_output=True, text=True, timeout=30,
                       env={"PATH": f"{tmp_path / 'tools'}:{os.environ['PATH']}", "HOME": str(tmp_path)})
    sent = (tmp_path / "rsync.log").read_text().split()
    excluded = [sent[i + 1] for i, w in enumerate(sent) if w == "--exclude"]
    assert r.returncode == 0 and "./" in sent and "--delete" in sent and excluded == [".git", "__pycache__"]


# ---- P-R15A-2: cafe.cfd.sh pasted the case directory into bash -c -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["a b", "x;touch pwned", "q'uote", "$HOME", "two  spaces", "-n"])
def test_p_r15a_2_an_openfoam_step_runs_in_a_case_directory_with_a_space_or_a_shell_character_in_its_name(tmp_path, monkeypatch, name):
    """`cd {case} && ...` with the path unquoted: `a b` was `cd a b` (too many arguments, a failed step and a log that does not exist, FileNotFoundError
    out of the error path), `x;touch pwned` ran `touch pwned` in the caller's directory and `$HOME` was expanded."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(cfd, "FOAM", "")
    case = tmp_path / "cases" / name
    case.mkdir(parents=True)
    cfd.sh(case, "echo ran", "step 1")                                           # the log name is pasted too
    assert (case / "log.step 1").read_text() == "ran\n" and list(elsewhere.iterdir()) == []
    assert [p.name for p in (tmp_path / "cases").iterdir()] == [name]
    with pytest.raises(RuntimeError, match="step 2 failed in .*\nbad"):
        cfd.sh(case, "(echo bad; false)", "step 2")                                # the error path reads the same log


def test_p_r15a_2_no_other_module_of_the_app_builds_a_shell_command_line_out_of_a_path():
    """Sweep of cafe/*.py: the only `bash -c` or shell=True is cfd.sh; every other subprocess takes an argument list (geom.py puts its paths in a
    `python3 -c` program through repr)."""
    shells = []
    for p in sorted((ROOT / "cafe").glob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("system", "popen") and getattr(n.func.value, "id", "") == "os":
                shells.append((p.name, n.lineno))
            if isinstance(n, ast.keyword) and n.arg == "shell" and getattr(n.value, "value", None) is True:
                shells.append((p.name, n.value.lineno))
            if isinstance(n, ast.Constant) and n.value in ("bash", "sh") and p.name != "cfd.py":
                shells.append((p.name, n.lineno))
    assert shells == []


# ---- P-R15A-3: the npz caches of the app are written whole or not at all ----------------------------------------------------------------------------------

def cut_npz(monkeypatch):
    """np.savez_compressed writes the start of a zip and dies, as a kill or a full disk does: into the path it is given, or into the file object."""
    def cut(file, *a, **k):
        fh = open(file, "wb") if isinstance(file, (str, os.PathLike)) else file
        fh.write(b"PK\x03\x04 half a zip")
        fh.flush()
        raise OSError("killed")
    monkeypatch.setattr(np, "savez_compressed", cut)


WW3_CSV = "time,alt,lat,lon,Thgt,Tper,Tdir\nUTC,m,deg,deg,m,s,deg\n2026-01-01T00:00:00Z,0.0,10.0,200.0,1.5,8.0,180.0\n"


def waves_call(tmp_path, monkeypatch):
    monkeypatch.setattr(ocean, "CACHE", tmp_path / "ocean")
    monkeypatch.setattr(ocean, "_get", lambda url: WW3_CSV)
    return ocean.waves(dt.datetime(2026, 1, 1), 1.0, (9.5, 10.5), (199.5, 200.5))


def hycom_call(tmp_path, monkeypatch):
    """`ocean.currents` with the OPeNDAP reads replaced: the axes, and the child that cuts a slice into the part file it is given."""
    monkeypatch.setattr(ocean, "CACHE", tmp_path / "ocean")
    (tmp_path / "ocean").mkdir(exist_ok=True)                                                # `_axes` makes it in the real code
    monkeypatch.setattr(ocean, "_axes", lambda url: dict(time=np.arange(990.0, 1020.0, 3.0), lat=np.arange(0.0, 20.0), lon=np.arange(190.0, 210.0),
                                                         depth=np.array([0.0, 10.0, 20.0, 50.0, 100.0, 300.0])))

    def child(*args, deadline):
        k0, k1, d0, d1, j0, j1, i0, i1 = json.loads(args[2])
        np.savez(args[4], **{n: np.ones((k1 - k0, d1 - d0, j1 - j0, i1 - i0)) for n in json.loads(args[3])})
    monkeypatch.setattr(ocean, "_child", child)
    return ocean.currents(ocean.EPOCH + dt.timedelta(hours=1000), 6.0, (5.0, 6.0), (200.0, 201.0))


@pytest.mark.parametrize("call", [waves_call, hycom_call])
def test_p_r15a_3_a_cut_write_of_an_ocean_cache_leaves_no_file_and_the_next_call_fetches_again(tmp_path, monkeypatch, call):
    """`np.savez_compressed(f, ...)` wrote the cache in place: a kill left a half zip that `np.load` read at the next call as `BadZipFile`, in place of the
    refetch that follows an absent file. Now the write goes to a temporary beside it and is renamed, so a cut leaves nothing."""
    with monkeypatch.context() as m:
        cut_npz(m)
        with pytest.raises(OSError, match="killed"):
            call(tmp_path, m)
    assert list((tmp_path / "ocean").iterdir()) == []                                       # no cache file and no temporary
    out = call(tmp_path, monkeypatch)                                                         # the next call does the work and the file it leaves reads back
    caches = [p for p in (tmp_path / "ocean").iterdir() if p.suffix == ".npz"]
    assert len(caches) == 1 and not list((tmp_path / "ocean").glob(".*"))
    again = call(tmp_path, monkeypatch)                                                       # and the third call reads that file back, the same arrays
    assert again.keys() == out.keys()
    for k in out:
        np.testing.assert_equal(again[k], out[k])


def test_p_r15a_3_write_with_keeps_the_old_file_on_a_cut_names_its_temporary_as_atomic_does_and_adds_no_npz(tmp_path, monkeypatch):
    f = tmp_path / "x.npz"
    atomic.write_with(f, lambda fh: np.savez_compressed(fh, a=np.arange(3)))
    assert list(np.load(f)["a"]) == [0, 1, 2] and [p.name for p in tmp_path.iterdir()] == ["x.npz"]
    names = []
    real = atomic.tmp_name
    monkeypatch.setattr(atomic, "tmp_name", lambda p: names.append(real(p)) or names[-1])
    cut_npz(monkeypatch)
    with pytest.raises(OSError, match="killed"):
        atomic.write_with(f, lambda fh: np.savez_compressed(fh, a=np.arange(9)))
    assert list(np.load(f)["a"]) == [0, 1, 2] and [p.name for p in tmp_path.iterdir()] == ["x.npz"]       # the old file, no temporary
    assert len(names) == 1 and names[0].parent == tmp_path and names[0].name.startswith(".") and names[0].name.endswith(".tmp") and len(names[0].name) == 17


def test_p_r15a_3_every_npz_the_app_writes_goes_through_write_with_or_is_named_here():
    """Sweep of cafe/*.py: a `savez` / `savez_compressed` / `save` is the argument of `atomic.write_with`, or is one of the two child writes that land in a
    temporary of their own (ocean `_child_axes`, renamed by os.replace; `_child_slice`, a part file the parent deletes), or the pressure `.npy` of one
    OpenFOAM case that nothing in cafe/ reads back."""
    found = {}
    for p in sorted((ROOT / "cafe").glob("*.py")):
        tree = ast.parse(p.read_text())
        inside = {id(c) for w in ast.walk(tree) if isinstance(w, ast.Call) and getattr(w.func, "attr", "") == "write_with" for c in ast.walk(w)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("savez", "savez_compressed", "save", "savetxt") and id(n) not in inside:
                found[p.name] = found.get(p.name, 0) + 1
    assert found == {"ocean.py": 2, "cfd.py": 1}
