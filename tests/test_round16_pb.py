"""Round 16, prefix B: the live app and the runners (cafe/*.py outside cafe/pm, run.sh, sync.sh). Each test names its finding; the fix was removed in a
throwaway detached worktree and the test was seen to fail, then to pass with it (review/orca/PROBLEMS.md has the runs)."""
import ast
import datetime as dt
import errno
import json
import os
import pathlib
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
        ones = {n: np.ones((k1 - k0, d1 - d0, j1 - j0, i1 - i0)) for n in json.loads(args[3])}
        atomic.write_with(args[4], lambda fh: np.savez(fh, **ones))  # as the real child
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
    """Sweep of cafe/*.py: a `savez` / `savez_compressed` / `save` is the argument of `atomic.write_with`, or is the pressure `.npy` of one OpenFOAM case that
    nothing in cafe/ reads back. (Until round 16 two child writes of ocean.py were named here: a part file opened by name with a pid in it, S2.)"""
    found = {}
    for p in sorted((ROOT / "cafe").glob("*.py")):
        tree = ast.parse(p.read_text())
        inside = {id(c) for w in ast.walk(tree) if isinstance(w, ast.Call) and getattr(w.func, "attr", "") == "write_with" for c in ast.walk(w)}
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") in ("savez", "savez_compressed", "save", "savetxt") and id(n) not in inside:
                found[p.name] = found.get(p.name, 0) + 1
    assert found == {"cfd.py": 1}  # round 16, S2: the two child writes of ocean.py go through write_with too


# ---- round 16 (S1, M-21): write_text and write_with are one implementation -----------------------------------------------------------------------------------

WRITERS = [pytest.param(lambda p, **k: atomic.write_text(p, "new", **k), id="write_text"),
           pytest.param(lambda p, **k: atomic.write_with(p, lambda fh: fh.write(b"new"), **k), id="write_with")]


@pytest.fixture
def umask():
    old = os.umask(0o022)
    yield os.umask
    os.umask(old)


@pytest.mark.parametrize("write", WRITERS)
@pytest.mark.parametrize("old_mode, mask, new_mode", [(0o600, 0o022, 0o600), (0o664, 0o077, 0o664), (0o666, 0o022, 0o666), (0o444, 0o022, 0o444)])
def test_r16_s1_an_existing_file_keeps_its_mode_and_a_new_one_gets_the_umasks_for_both_writers(tmp_path, umask, write, old_mode, mask, new_mode):
    """`write_with` made its temporary with `open(..., "xb")` (the umask's mode) and never set the old file's mode: a 0o600 `.npz` became 0o644 (S1)."""
    umask(mask)
    f = tmp_path / "f.bin"
    f.write_bytes(b"old")
    f.chmod(old_mode)
    write(f)
    assert f.read_bytes() == b"new" and stat.S_IMODE(f.stat().st_mode) == new_mode
    g = tmp_path / "new.bin"
    write(g)
    assert g.read_bytes() == b"new" and stat.S_IMODE(g.stat().st_mode) == 0o666 & ~mask and sorted(p.name for p in tmp_path.iterdir()) == ["f.bin", "new.bin"]


@pytest.mark.parametrize("write", WRITERS)
def test_r16_s1_a_temporary_is_never_readable_more_widely_than_the_file_it_becomes_for_both_writers(tmp_path, monkeypatch, umask, write):
    umask(0o022)
    f = tmp_path / "secret.bin"
    f.write_bytes(b"old")
    f.chmod(0o600)
    seen = []
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)                                                                   # noqa: E731
    real_replace, real_fchmod = os.replace, os.fchmod
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(mode(a)), real_replace(a, b))[1])
    monkeypatch.setattr(os, "fchmod", lambda fd, m: (seen.append(stat.S_IMODE(os.fstat(fd).st_mode)), real_fchmod(fd, m))[1])
    write(f)
    assert seen and all(m & ~0o600 == 0 for m in seen), [oct(m) for m in seen]


@pytest.mark.parametrize("write", WRITERS)
def test_r16_s1_a_symbolic_link_at_the_target_is_refused_unless_the_caller_follows_it_for_both_writers(tmp_path, write):
    """`write_with` replaced the link itself with a regular file (or, `open`ing the temporary by name, never looked): a planted `x.npz -> ~/.profile` is now an
    ELOOP, as for `write_text`. `follow_symlinks=True` replaces the file the link points to and keeps the link."""
    real, link = tmp_path / "real.bin", tmp_path / "x.npz"
    real.write_bytes(b"keep")
    link.symlink_to(real)
    with pytest.raises(OSError, match="symbolic link") as e:
        write(link)
    assert e.value.errno == errno.ELOOP and real.read_bytes() == b"keep" and link.is_symlink()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["real.bin", "x.npz"]
    dangling = tmp_path / "dangling.npz"
    dangling.symlink_to(tmp_path / "nowhere.bin")
    with pytest.raises(OSError, match="symbolic link"):
        write(dangling)
    assert not (tmp_path / "nowhere.bin").exists()
    write(link, follow_symlinks=True)
    assert link.is_symlink() and real.read_bytes() == b"new"


@pytest.mark.parametrize("write", WRITERS)
def test_r16_s1_the_content_goes_through_the_descriptor_of_the_file_we_created_not_a_second_open_by_name(tmp_path, monkeypatch, write):
    """A link put at the temporary's name between the create and the write must not receive the content (round 15's finding for `write_text`, now also for
    `write_with`, whose writer was handed `open(tmp, "xb")`'s file and now a file object on the descriptor `os.open(O_EXCL)` returned)."""
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM-ORIGINAL")
    real_open = os.open

    def swapping(path, *a, **k):
        fd = real_open(path, *a, **k)
        if str(path).endswith(".tmp"):
            os.unlink(path)
            os.symlink(victim, path)
        return fd
    monkeypatch.setattr(os, "open", swapping)
    write(tmp_path / "out.bin")
    monkeypatch.undo()
    assert victim.read_text() == "VICTIM-ORIGINAL"  # (out.bin is the planted link the replace moved; the content never went through it)


@pytest.mark.parametrize("write", WRITERS)
def test_r16_m21_a_temporary_name_that_exists_is_an_error_and_nothing_existing_is_touched(tmp_path, monkeypatch, write):
    """`"xb"` replaced by `"wb"` left every test green: the temporary is created with O_EXCL so that a file already at its name (a collision of the 48-bit
    random name, or a name guessed and planted) is never written into. With `tmp_name` returning an existing file the write raises FileExistsError and that
    file and the target are as they were."""
    f, planted = tmp_path / "x.npz", tmp_path / ".abcdef012345.tmp"
    f.write_bytes(b"old")
    planted.write_bytes(b"PLANTED")
    monkeypatch.setattr(atomic, "tmp_name", lambda p: planted)
    with pytest.raises(FileExistsError):
        write(f)
    assert f.read_bytes() == b"old" and planted.read_bytes() == b"PLANTED" and sorted(p.name for p in tmp_path.iterdir()) == [".abcdef012345.tmp", "x.npz"]


# ---- round 16 (S2): the part files of cafe/ocean.py have names nobody can predict and are created with O_EXCL ------------------------------------------

class FakeNetCDF:
    """`netCDF4.Dataset(url)` for the two child functions of cafe/ocean.py: a dict of numpy arrays that can be indexed like variables."""
    @staticmethod
    def Dataset(url):                                                                       # noqa: N802
        n = np.arange(24.0).reshape(2, 3, 2, 2)
        return {"time": np.array([0.0, 3.0]), "lat": np.array([0.0, 1.0]), "lon": np.array([190.0, 191.0]), "depth": np.array([0.0, 10.0, 20.0]),
                "water_u": n, "water_v": -n}


def _planted_old_names(tmp_path, victim, names):
    for n in names:
        (tmp_path / n).symlink_to(victim)


def test_r16_s2_the_axes_child_writes_through_a_temporary_of_its_own_created_with_o_excl_and_ignores_the_old_predictable_name(tmp_path, monkeypatch):
    """`<out>.<pid>.part.npz` was a predictable name opened by name: a link planted there made the child write into the victim file. Now the file is created
    by `atomic.write_with` (`tmp_name`, O_EXCL, a file object for `np.savez`)."""
    monkeypatch.setitem(sys.modules, "netCDF4", FakeNetCDF)
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM")
    out = tmp_path / "hycom_axes_k.npz"
    _planted_old_names(tmp_path, victim, [f"{out.name}.{os.getpid()}.part.npz", f"{out.name}.{os.getpid()}.part"])
    flags = []
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda path, fl, *a, **k: (flags.append((pathlib.Path(path).name, fl)), real_open(path, fl, *a, **k))[1])
    ocean._child_axes("http://x/dods", out)
    monkeypatch.undo()
    assert victim.read_text() == "VICTIM" and list(np.load(out)["depth"]) == [0.0, 10.0, 20.0]
    made = [(n, fl) for n, fl in flags if n.endswith(".tmp")]
    assert len(made) == 1 and made[0][1] & os.O_EXCL and len(made[0][0]) == 17
    assert sorted(p.name for p in tmp_path.iterdir() if not p.is_symlink()) == ["hycom_axes_k.npz", "victim.txt"]


def test_r16_s2_the_slice_child_and_its_parent_use_unpredictable_names_created_with_o_excl_and_leave_no_part_file(tmp_path, monkeypatch):
    """`currents` named the part file `<stem>.<pid>.part.npz` for the child to open by name; the child's `np.savez(out)` followed a link at that name. The
    parent now hands the child a `tmp_name`, the child writes it by `atomic.write_with` (O_EXCL), the parent reads it and removes it, also when the child
    fails."""
    monkeypatch.setitem(sys.modules, "netCDF4", FakeNetCDF)
    monkeypatch.setattr(ocean, "CACHE", tmp_path / "ocean")
    (tmp_path / "ocean").mkdir()
    monkeypatch.setattr(ocean, "_axes", lambda url: dict(time=np.arange(990.0, 1020.0, 3.0), lat=np.arange(0.0, 20.0), lon=np.arange(190.0, 210.0),
                                                         depth=np.array([0.0, 10.0, 20.0, 50.0, 100.0, 300.0])))
    victim = tmp_path / "victim.txt"
    victim.write_text("VICTIM")
    asked, flags = [], []

    def child(*args, deadline):                                                             # what `python -m cafe.ocean _slice` does, in this process
        asked.append(pathlib.Path(args[4]))
        ocean._child_slice(*map(str, args[1:]))
    monkeypatch.setattr(ocean, "_child", child)
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda path, fl, *a, **k: (flags.append((pathlib.Path(path).name, fl)), real_open(path, fl, *a, **k))[1])
    ocean.currents(ocean.EPOCH + dt.timedelta(hours=1000), 6.0, (5.0, 6.0), (200.0, 201.0))
    monkeypatch.undo()
    assert len(asked) >= 1 and all(a.name.startswith(".") and a.name.endswith(".tmp") and len(a.name) == 17 for a in asked)
    made = [(n, fl) for n, fl in flags if n.endswith(".tmp")]
    assert made and all(fl & os.O_EXCL for n, fl in made)                                   # the child's own temporaries, and the cache file's
    assert victim.read_text() == "VICTIM" and [p for p in (tmp_path / "ocean").iterdir() if p.suffix == ".npz" and not p.name.startswith(".")]
    assert not [p for p in (tmp_path / "ocean").iterdir() if p.name.startswith(".") or "part" in p.name]       # no part file and no temporary left


def test_r16_s2_a_failing_slice_child_leaves_no_part_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ocean, "CACHE", tmp_path / "ocean")
    (tmp_path / "ocean").mkdir()
    monkeypatch.setattr(ocean, "_axes", lambda url: dict(time=np.arange(990.0, 1020.0, 3.0), lat=np.arange(0.0, 20.0), lon=np.arange(190.0, 210.0),
                                                         depth=np.array([0.0, 10.0, 20.0, 50.0, 100.0, 300.0])))

    def child(*args, deadline):
        pathlib.Path(args[4]).write_bytes(b"half")                                           # the child died after it began to write
        raise RuntimeError("HYCOM read failed: x")
    monkeypatch.setattr(ocean, "_child", child)
    with pytest.raises(RuntimeError, match="HYCOM read failed"):
        ocean.currents(ocean.EPOCH + dt.timedelta(hours=1000), 6.0, (5.0, 6.0), (200.0, 201.0))
    assert [p.name for p in (tmp_path / "ocean").iterdir() if not p.name.endswith("_down")] == []             # (the `_down` marker is the outage record)


def test_r16_s2_no_writer_in_the_app_names_a_file_after_a_pid_or_a_fixed_suffix():
    """Sweep of cafe/*.py (the live app and its jobs): outside `atomic.py` no string is a `.part` / `.tmp` suffix of a name and no `getpid` builds a name. A new
    writer uses `atomic.tmp_name` / `atomic.write_with`, which make an unpredictable name with O_EXCL."""
    found = []
    for p in sorted((ROOT / "cafe").glob("*.py")):
        if p.name == "atomic.py":
            continue
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and (".part" in n.value or n.value.endswith(".tmp") or ".tmp." in n.value):
                found.append((p.name, n.value))
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "getpid":
                found.append((p.name, "getpid"))
    assert found == [("env.py", ".part")]  # env.py: a filter that leaves an old `.part` out of a catalogue, writes nothing
