"""Round 18, batch E: atomic writers, locks and the store replace (M-8, M-9, M-13, and the A-4 and A-6 tests of M-16). Each test names its finding; the new
tests were run against the tree at the base commit d69be8f and seen to fail where the finding is a defect, then to pass with the fix
(review/round_18/handbacks/r18_handback_E.md)."""
import contextlib
import errno
import os
import pathlib
import stat
import subprocess
import sys
import threading

import pytest

from cafe import atomic
from cafe.pm import emulator as E
from cafe.pm.config import ConfigError
from cafe.pm.env import hycom as h, remote
from tests import lockprobe
from tests.test_hycom import fx, truth, _steps_of  # noqa: F401  (fx and truth are fixtures)


@contextlib.contextmanager
def umask(m):
    old = os.umask(m)
    try:
        yield
    finally:
        os.umask(old)


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


# ---- M-8: a link as the source of `replace_from` is refused whether or not the target exists ------------------------------------------------------------

@pytest.mark.parametrize("follow", [False, True])
def test_r18_m8_a_link_as_the_source_is_eloop_for_a_new_target_too(tmp_path, follow):
    """`O_NOFOLLOW` sat inside `if mode is not None:`, so for a target that does not exist (the first fetch of a file, the case of both callers) a link at the
    source was renamed onto the target and `final` became a link to whatever it pointed at."""
    secret = tmp_path / "secret.txt"
    secret.write_text("S")
    src, final = tmp_path / "s.part", tmp_path / "final"
    src.symlink_to(secret)
    with pytest.raises(OSError) as e:
        atomic.replace_from(src, final, follow_symlinks=follow)
    assert e.value.errno == errno.ELOOP and not final.exists() and not final.is_symlink() and src.is_symlink() and secret.read_text() == "S"
    dangling = tmp_path / "dangling"                                       # a new target reached through a dangling link (follow) is a new target as well
    (tmp_path / "t.part").symlink_to(secret)
    if follow:
        dangling.symlink_to(tmp_path / "made")
        with pytest.raises(OSError) as e:
            atomic.replace_from(tmp_path / "t.part", dangling, follow_symlinks=True)
        assert e.value.errno == errno.ELOOP and not (tmp_path / "made").exists()


def test_r18_m8_a_regular_source_for_a_new_target_still_moves_with_the_umasks_mode_and_leaves_no_file_behind(tmp_path):
    src, final = tmp_path / "s.part", tmp_path / "final"
    src.write_bytes(b"whole")
    src.chmod(0o640)
    atomic.replace_from(src, final)
    assert final.read_bytes() == b"whole" and mode(final) == 0o640 and sorted(p.name for p in tmp_path.iterdir()) == ["final"]
    with pytest.raises(FileNotFoundError):                                 # a missing source is the same error as before (the rename's)
        atomic.replace_from(tmp_path / "none", tmp_path / "other")
    assert final.read_bytes() == b"whole"


# ---- M-9: the emulator table's lock follows the rules of the table's writers ------------------------------------------------------------------------------

def test_r18_m9_the_emulator_lock_is_opened_without_following_links_close_on_exec_and_0o666(tmp_path, monkeypatch):
    seen = []
    real = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: (seen.append((str(p), f, a)), real(p, f, *a, **k))[1])
    with E.locked(tmp_path / "train.parquet"):
        pass
    [(name, flags, args)] = [s for s in seen if s[0].endswith(".lock")]
    assert name == str(tmp_path / "train.parquet.lock") and flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC and flags & os.O_CREAT and args == (0o666,)


def test_r18_m9_the_emulator_lock_takes_the_umask_and_never_changes_the_mode_of_one_that_exists(tmp_path):
    t = tmp_path / "train.parquet"
    with umask(0o002):
        with E.locked(t):
            pass
    assert mode(tmp_path / "train.parquet.lock") == 0o664
    (tmp_path / "train.parquet.lock").chmod(0o640)
    with umask(0o000):
        with E.locked(t):
            pass
    assert mode(tmp_path / "train.parquet.lock") == 0o640


def test_r18_m9_a_link_planted_at_the_emulator_lock_is_refused_and_its_target_is_not_made(tmp_path):
    victim = tmp_path / "victim"
    t = tmp_path / "train.parquet"
    (tmp_path / "train.parquet.lock").symlink_to(victim)
    ran = []
    with pytest.raises(ConfigError) as e:
        with E.locked(t):
            ran.append(1)
    assert ran == [] and not victim.exists() and str(tmp_path / "train.parquet.lock") in str(e.value) and "never followed" in str(e.value)
    victim.write_text("KEEP")                                              # and an existing target is neither opened nor changed
    with pytest.raises(ConfigError):
        with E.locked(t):
            ran.append(2)
    assert ran == [] and victim.read_text() == "KEEP"


def test_r18_m9_a_lock_that_cannot_be_opened_is_a_config_error_that_names_the_file_its_owner_and_the_remedy(tmp_path, monkeypatch):
    t = tmp_path / "train.parquet"
    lock = tmp_path / "train.parquet.lock"
    lock.write_text("")
    lock.chmod(0o600)                                                      # what a run under umask 077 left; the second account's open is refused
    real = os.open

    def refuse(p, f, *a, **k):
        if str(p).endswith(".lock"):
            raise PermissionError(errno.EACCES, "Permission denied", str(p))
        return real(p, f, *a, **k)
    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(pathlib.Path, "owner", lambda self: "alice")        # (orca's accounts have no passwd entry: `Path.owner` is KeyError there)
    with pytest.raises(ConfigError) as e:
        with E.locked(t):
            raise AssertionError("the block must not run unlocked")
    msg = str(e.value)
    assert str(lock) in msg and "PermissionError" in msg and "alice" in msg and "0600" in msg and "chmod g+w" in msg and "losing each other's rows" in msg


def test_r18_m9_what_stands_at_the_lock_name_decides_the_remedy(tmp_path, monkeypatch):
    t = tmp_path / "d" / "train.parquet"
    lock = tmp_path / "d" / "train.parquet.lock"
    lock.mkdir(parents=True)                                               # a directory: the open fails (EISDIR) whoever runs it
    with pytest.raises(ConfigError, match="not a file stands at that name"):
        with E.locked(t):
            pass
    lock.rmdir()
    lock.write_text("")
    real = os.open
    monkeypatch.setattr(os, "open", lambda p, f, *a, **k: (_ for _ in ()).throw(PermissionError(errno.EACCES, "Permission denied", str(p)))
                        if str(p).endswith(".lock") else real(p, f, *a, **k))
    monkeypatch.setattr(pathlib.Path, "owner", lambda self: (_ for _ in ()).throw(KeyError("uid not found")))     # a container with no passwd entry
    with pytest.raises(ConfigError, match="writable by this account"):
        with E.locked(t):
            pass
    monkeypatch.undo()
    (tmp_path / "f").write_text("a file where the table's directory should be")
    with pytest.raises(ConfigError, match="writable by this account"):     # the directory cannot be made: the same error, no bare OSError
        with E.locked(tmp_path / "f" / "train.parquet"):
            pass


def test_r18_m9_the_emulator_lock_is_released_when_the_block_raises(tmp_path):
    t = tmp_path / "train.parquet"
    with pytest.raises(RuntimeError), E.locked(t):
        assert lockprobe.held(tmp_path / "train.parquet.lock")
        raise RuntimeError("boom")
    assert not lockprobe.held(tmp_path / "train.parquet.lock")
    with E.locked(t):                                                      # and it can be taken again
        assert lockprobe.held(tmp_path / "train.parquet.lock")


def test_r18_m9_an_append_with_an_unusable_lock_writes_nothing_and_says_why(tmp_path):
    t = tmp_path / "train.parquet"
    e = E.Emulator(["x"], ["y"], path=t)
    e.append(dict(x=1.0, y=2.0))
    before = t.read_bytes()
    (tmp_path / "train.parquet.lock").unlink()
    (tmp_path / "train.parquet.lock").symlink_to(tmp_path / "nowhere")
    with pytest.raises(ConfigError, match="lock file"):
        e.append(dict(x=2.0, y=3.0))
    assert t.read_bytes() == before and not (tmp_path / "nowhere").exists()


def test_r18_m9_store_lock_creates_its_file_0o666_under_the_umask_and_keeps_the_mode_of_one_that_exists(tmp_path):
    """`0o644` made a lock that a second account in the group could not open read-write: its block ran unlocked, silently."""
    with umask(0o000):
        with remote.store_lock(tmp_path, "a.lock"):
            pass
    assert mode(tmp_path / "a.lock") == 0o666
    with umask(0o002):
        with remote.store_lock(tmp_path, "b.lock"):
            pass
    assert mode(tmp_path / "b.lock") == 0o664
    (tmp_path / "b.lock").chmod(0o640)
    with umask(0o000):
        with remote.store_lock(tmp_path, "b.lock"):
            pass
    assert mode(tmp_path / "b.lock") == 0o640


def test_r18_m9_store_lock_logs_once_when_its_block_runs_unlocked(tmp_path, monkeypatch):
    said = []
    (tmp_path / "x.lock").symlink_to(tmp_path / "victim")
    with remote.store_lock(tmp_path, "x.lock", log=said.append) as held:
        assert held is False and len(said) == 1                            # said before the block runs, once
    assert len(said) == 1 and str(tmp_path / "x.lock") in said[0] and "not locked" in said[0] and "without the lock" in said[0]
    assert not (tmp_path / "victim").exists()
    said.clear()
    with remote.store_lock(tmp_path / "no" / "dir", "y.lock", log=said.append) as held:       # a directory that is not there
        assert held is False
    assert len(said) == 1 and "FileNotFoundError" in said[0]
    said.clear()
    monkeypatch.setitem(sys.modules, "fcntl", None)                        # `import fcntl` raises ImportError
    with remote.store_lock(tmp_path, "z.lock", log=said.append) as held:
        assert held is False
    assert len(said) == 1 and "no fcntl" in said[0]


def test_r18_m9_store_lock_says_nothing_when_it_holds_the_lock_or_nothing_was_to_be_locked(tmp_path):
    said = []
    with remote.store_lock(tmp_path, "a.lock", log=said.append) as outer:
        with remote.store_lock(tmp_path, "a.lock", log=said.append) as inner:      # the same thread again: held, not unlocked
            assert outer is True and inner is True
    with remote.store_lock(tmp_path, "none.lock", create=False, log=said.append) as held:     # the audit: no file, no lock meant
        assert held is False
    with remote.store_lock(tmp_path, "b.lock", log=said.append) as held:
        assert held is True
    with remote.store_lock(tmp_path, "a.lock"):                            # the default (no `log`) is as before
        pass
    assert said == []
    (tmp_path / "l.lock").symlink_to(tmp_path / "victim")
    with remote.store_lock(tmp_path, "l.lock", create=False, log=said.append) as held:        # a lock that was there and cannot be opened is said
        assert held is False
    assert len(said) == 1


# ---- M-13: the ocean store is replaced by renames, never by a delete first ---------------------------------------------------------------------------------

def _tree(p):
    return {str(q.relative_to(p)): q.read_bytes() for q in sorted(pathlib.Path(p).rglob("*")) if q.is_file()}


def _store(tr, out, generation):
    h.write_store(_steps_of(tr), out, "in_situ", {"generation": generation})
    return _tree(out)


def _aside(tmp_path, out):
    return [p for p in tmp_path.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp") and p != out]


def test_r18_m13_the_old_store_goes_aside_whole_the_new_one_in_and_only_then_the_old_one_is_deleted(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    events = []
    real_replace, real_rmtree = os.replace, h.shutil.rmtree

    def replace(a, b, *k, **kw):
        if pathlib.Path(a).parent == tmp_path:
            events.append(("replace", pathlib.Path(a), pathlib.Path(b), _tree(a) if pathlib.Path(a).is_dir() else None))
        return real_replace(a, b, *k, **kw)

    def rmtree(p, *a, **k):
        if pathlib.Path(p).parent == tmp_path and pathlib.Path(p).is_dir() and _tree(p):          # (zarr's own `mode="w"` clears the empty new directory first)
            events.append(("rmtree", pathlib.Path(p), _tree(p)))
        return real_rmtree(p, *a, **k)
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(h.shutil, "rmtree", rmtree)
    new = _store(truth, out, "new")
    kinds = [(e[0], e[1] == out, e[2] == out if e[0] == "replace" else None) for e in events]
    aside = events[0][2]
    # out -> aside, tmp -> out, aside -> its `.dead.tmp` name (round 19, M-11: a delete killed half way leaves a name nothing offers for `mv`), rmtree(dead)
    assert kinds == [("replace", True, False), ("replace", False, True), ("replace", False, False), ("rmtree", False, None)]
    dead = events[2][2]
    assert aside.name.startswith(".") and aside.name.endswith(".old.tmp") and events[0][3] == old and events[2][1] == aside and events[2][3] == old
    assert dead.name == aside.name.replace(".old.tmp", ".dead.tmp") and events[3][1] == dead and events[3][2] == old
    assert _tree(out) == new and new != old and _aside(tmp_path, out) == []          # the aside is gone at the end


def test_r18_m13_a_first_store_is_one_rename_with_nothing_aside(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    calls = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b, *k, **kw: (calls.append((pathlib.Path(a), pathlib.Path(b))), real(a, b, *k, **kw))[1])
    _store(truth, out, "first")
    here = [c for c in calls if c[0].parent == tmp_path]
    assert len(here) == 1 and here[0][1] == out and h.open_store(out).attrs["generation"] == "first"
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]


def _fail_where(monkeypatch, tmp_path, out, which):
    """os.replace fails for the `which` rename of write_store: 'aside' (out -> .tmp), 'in' (.tmp -> out), or both ('in' and the put-back)."""
    real = os.replace
    n = {"in": 0}

    def replace(a, b, *k, **kw):
        a, b = pathlib.Path(a), pathlib.Path(b)
        if a.parent == tmp_path and a == out and which == "aside":
            raise OSError(errno.EIO, "injected: the first rename")
        if a.parent == tmp_path and b == out and a != out:                 # the rename in (1st) and the put-back (2nd)
            n["in"] += 1
            if n["in"] == 1 and which in ("in", "both"):
                raise OSError(errno.EIO, "injected: the second rename")
            if n["in"] == 2 and which == "both":
                raise OSError(errno.EIO, "injected: the put-back")
        return real(a, b, *k, **kw)
    monkeypatch.setattr(os, "replace", replace)


def test_r18_m13_a_failed_first_rename_leaves_the_old_store_where_it_was_and_no_temporary(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    _fail_where(monkeypatch, tmp_path, out, "aside")
    with pytest.raises(OSError, match="first rename"):
        _store(truth, out, "new")
    assert _tree(out) == old and sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    monkeypatch.undo()
    assert h.open_store(out).attrs["generation"] == "old"


def test_r18_m13_a_failed_second_rename_puts_the_old_store_back_whole_and_leaves_no_temporary(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    """On the unfixed code the old store was deleted before this rename: the name held nothing, and the error came with no store at all."""
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    _fail_where(monkeypatch, tmp_path, out, "in")
    with pytest.raises(OSError, match="second rename"):
        _store(truth, out, "new")
    assert _tree(out) == old and sorted(p.name for p in tmp_path.iterdir()) == [out.name]
    monkeypatch.undo()
    assert h.open_store(out).attrs["generation"] == "old"


def test_r18_m13_when_the_put_back_fails_too_the_error_is_raised_and_the_old_store_is_kept_whole_aside(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    _fail_where(monkeypatch, tmp_path, out, "both")
    with pytest.raises(OSError, match="put-back") as e:
        _store(truth, out, "new")
    assert "second rename" in str(e.value.__context__)                     # the first failure is kept as the context of the second
    monkeypatch.undo()
    assert not out.exists() and [_tree(p) for p in _aside(tmp_path, out)] == [old]          # nothing was deleted: the only copy is beside the name
    with pytest.raises(ConfigError, match="cannot be read"):               # and the name says it is missing: a clear refusal, not an empty store
        h.open_store(out)


def test_r18_m13_a_delete_of_the_old_store_that_does_not_finish_leaves_the_new_store_in_place(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    real = h.shutil.rmtree
    monkeypatch.setattr(h.shutil, "rmtree", lambda p, *a, **k: None if pathlib.Path(p).parent == tmp_path and pathlib.Path(p) != out else real(p, *a, **k))
    _store(truth, out, "new")
    assert h.open_store(out).attrs["generation"] == "new" and [_tree(p) for p in _aside(tmp_path, out)] == [old]


def test_r18_m13_a_link_at_the_store_name_is_not_replaced_and_its_target_is_untouched(fx, truth, tmp_path):  # noqa: F811
    """As before the fix (guard, not a regression): the link is no store to move aside, and the rename onto it is ENOTDIR."""
    real = tmp_path / "real.zarr"
    old = _store(truth, real, "old")
    link = tmp_path / "link.zarr"
    link.symlink_to(real)
    with pytest.raises(OSError):
        _store(truth, link, "new")
    assert link.is_symlink() and _tree(real) == old and sorted(p.name for p in tmp_path.iterdir()) == ["link.zarr", "real.zarr"]


_KILL = r'''
import os, pathlib, sys
import xarray as xr
from cafe.pm.env import hycom as h
nc, out, point = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3]
real = os.replace


def rep(a, b, *k, **kw):
    a, b = pathlib.Path(a), pathlib.Path(b)
    if a.parent == out.parent:
        if point == "before_aside" and a == out:
            os._exit(7)
        if point == "between" and b == out and a != out:
            os._exit(7)
    real(a, b, *k, **kw)
    if point == "after_in" and a.parent == out.parent and b == out and a != out:
        os._exit(7)


os.replace = rep
ds = xr.open_dataset(nc, decode_times=False).load()
steps = (h._std(ds.isel(time=slice(i, i + 1))) for i in range(ds.sizes["time"]))
h.write_store(steps, out, "in_situ", {"generation": "new"})
'''


@pytest.mark.parametrize("point", ["before_aside", "between", "after_in"])
def test_r18_m13_a_process_killed_at_any_point_of_the_replace_leaves_a_readable_store_or_a_clear_refusal(fx, truth, tmp_path, point):  # noqa: F811
    """A real kill (`os._exit` in a child at the named rename): before the old store is moved aside the name is the old store; between the two renames it is
    absent (a refusal that names the repair: never an empty or half deleted store) and the old store is whole beside it; after the second rename it is the
    new store and the old one is left whole beside it, to be deleted. Then the next write succeeds."""
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    nc = tmp_path / "truth.nc"
    truth.to_netcdf(nc)
    r = subprocess.run([sys.executable, "-c", _KILL, str(nc), str(out), point], cwd=remote.ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 7, r.stderr[-2000:]                             # the kill point was reached
    held_old = [p for p in _aside(tmp_path, out) if _tree(p) == old]       # the old store, whole, under a `.tmp` name beside the name
    if point == "before_aside":
        assert _tree(out) == old and h.open_store(out).attrs["generation"] == "old" and held_old == []
    elif point == "between":
        assert not out.exists() and len(held_old) == 1
        with pytest.raises(ConfigError, match="cannot be read"):
            h.open_store(out)
    else:
        assert h.open_store(out).attrs["generation"] == "new" and h.open_store(out).sizes["time"] == truth.sizes["time"] and len(held_old) == 1
    _store(truth, out, "again")                                            # whatever the state, the name is writable again
    assert h.open_store(out).attrs["generation"] == "again"


# ---- M-16, A-4: the re-check inside the lock and the unlocked part ---------------------------------------------------------------------------------------

def test_r18_m16_a4_a_download_that_waited_for_the_lock_finds_the_file_the_first_one_made_and_fetches_nothing(server, tmp_path):
    """The check inside the lock (`if path.exists() ...` after `store_lock`) was untested: with it replaced by `if False:` a second caller fetched the file
    again after the first had made it. The first download is played by the test: it holds the lock, makes the file, releases it."""
    data = b"payload" * 100
    u = server.put("a", data)
    out = tmp_path / "d" / "a"
    out.parent.mkdir()
    got, failed = [], []

    def second():
        try:
            got.append(remote.download(u, out))
        except BaseException as e:                                         # reported below
            failed.append(repr(e))
    with remote.store_lock(out.parent, "a.lock"):
        t = threading.Thread(target=second)
        t.start()
        t.join(0.5)
        assert t.is_alive() and not out.exists() and server.log == []      # waiting: it has not asked the server for anything
        out.write_bytes(data)
    t.join(30)
    assert failed == [] and got == [out] and server.log == [] and out.read_bytes() == data and sorted(p.name for p in out.parent.iterdir()) == ["a", "a.lock"]


class _Cut:
    """A response whose body is cut after its first read."""

    def __init__(self, r):
        self.r, self.n = r, 0

    def __enter__(self):
        self.r.__enter__()
        return self

    def __exit__(self, *a):
        return self.r.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self.r, name)

    def read(self, n=-1):
        self.n += 1
        if self.n > 1:
            raise OSError("cut")
        return self.r.read(n)


def test_r18_m16_a4_an_unlocked_download_that_fails_mid_way_removes_its_part_and_its_record(server, tmp_path, monkeypatch):
    """The `finally` of the unlocked branch of `download` (replaced by `pass`, the tests stayed green) is what removes the part of this call's own, and its
    `.id`, when the body is cut: no `.tmp` is left for every failed download."""
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.lock").symlink_to(d / "victim")                                # no lock can be taken
    u = server.put("a", b"payload" * 100)
    real = remote._open
    monkeypatch.setattr(remote, "_open", lambda url, start=None, end=None, **kw: (lambda r: _Cut(r) if end is None else r)(real(url, start, end, **kw)))
    with pytest.raises(OSError, match="cut"):
        remote.download(u, d / "a")
    assert sorted(p.name for p in d.iterdir()) == ["a.lock"]


# ---- M-16, A-6: the temporary of an existing file is never readable more widely than the file --------------------------------------------------------------

def test_r18_m16_a6_the_temporary_of_an_existing_file_is_0o600_while_it_is_written_and_a_new_files_has_the_creation_mode(tmp_path):
    """`_replace_through` makes the temporary `0o600` when the file exists (its mode goes on after the write) and `0o666 & ~umask` when it does not; a mutant
    with `0o666` for both left the tests green, so the content of a 0o600 file was readable by others for the length of the write."""
    seen = []

    def writer(f):
        seen.append(stat.S_IMODE(os.fstat(f.fileno()).st_mode))
        f.write(b"x")
    p = tmp_path / "p"
    p.write_bytes(b"old")
    p.chmod(0o640)
    with umask(0o022):
        atomic.write_with(p, writer)
    assert seen == [0o600] and mode(p) == 0o640
    with umask(0o027):
        atomic.write_with(tmp_path / "new", writer)
    assert seen == [0o600, 0o640] and mode(tmp_path / "new") == 0o640
    atomic._replace_through(p, lambda tmp, fd: seen.append(stat.S_IMODE(os.fstat(fd).st_mode)), False)      # the one implementation under write_text as well
    assert seen[-1] == 0o600
    with umask(0o000):
        atomic._replace_through(tmp_path / "new2", lambda tmp, fd: seen.append(stat.S_IMODE(os.fstat(fd).st_mode)), False)
    assert seen[-1] == 0o666

