"""Round 17, batch F: stores, atomic writers and hand readers (M-9, M-13, M-14, M-15). Each test names its finding; the fix was removed in a throwaway
detached worktree at the base commit and the test was seen to fail, then to pass with it (review/round_17/handbacks/r17_handback_F.md)."""
import ast
import contextlib
import errno
import hashlib
import os
import stat
import threading
import time

import pandas as pd
import pytest
import yaml

from cafe import atomic, fea
from cafe.pm import config, emulator as E, ledger
from cafe.pm.env import hycom, remote


@contextlib.contextmanager
def umask(m):
    old = os.umask(m)
    try:
        yield
    finally:
        os.umask(old)


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


# ---- M-9: one download of a file at a time (the TAO `.part` has one name on purpose) -------------------------------------------------------------------

class _Slow:
    """A response whose body comes 0.15 s per read, so that two downloads of one file overlap whatever the machine's speed."""

    def __init__(self, r):
        self.r = r

    def __enter__(self):
        self.r.__enter__()
        return self

    def __exit__(self, *a):
        return self.r.__exit__(*a)

    def __getattr__(self, name):
        return getattr(self.r, name)

    def read(self, n=-1):
        time.sleep(0.15)
        return self.r.read(n)


def test_r17_m9_two_downloads_of_one_file_both_return_the_file(server, tmp_path, monkeypatch):
    """Two calls of `remote.download(url, out)` (two ingests, or two threads) shared `out.part`: the second started over the first's part (a server that
    sends no validator cannot tell it from another version), and the first died with `FileNotFoundError` or "stalled". Now the second waits for the lock,
    finds the file and returns it."""
    data = bytes(range(256)) * 10000                                       # 2.56 MB: three 1 MB reads
    u = server.put("a", data)
    real = remote._open
    monkeypatch.setattr(remote, "_open", lambda url, start=None, end=None, **kw: (lambda r: _Slow(r) if end is None else r)(real(url, start, end, **kw)))
    out = tmp_path / "s2" / "a"
    got, failed = [], []

    def go(delay):
        time.sleep(delay)
        try:
            got.append(remote.download(u, out))
        except BaseException as e:                                         # a thread's exception is the failure to report
            failed.append(repr(e))

    threads = [threading.Thread(target=go, args=(d,)) for d in (0.0, 0.1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert failed == [] and got == [out, out] and out.read_bytes() == data
    assert sorted(p.name for p in out.parent.iterdir() if p.suffix != ".lock") == ["a"]       # no part and no record of one is left


def test_r17_m9_a_second_download_waits_when_the_first_holds_the_lock_and_is_not_blocked_by_a_finished_file(server, tmp_path):
    u = server.put("a", b"payload")
    out = tmp_path / "a"
    with remote.store_lock(tmp_path, "a.lock"):                              # another process downloading `a`
        t = threading.Thread(target=lambda: remote.download(u, out))
        t.start()
        t.join(0.5)
        assert t.is_alive() and not out.exists()
    t.join(30)
    assert not t.is_alive() and out.read_bytes() == b"payload"
    n = len(server.log)
    assert remote.download(u, out) == out and len(server.log) == n         # a finished file is returned before the lock is asked for


# ---- M-13 and its siblings: a replaced file keeps its permission bits -----------------------------------------------------------------------------------

@pytest.mark.parametrize("suffix", [".parquet", ".csv"])
def test_r17_m13_write_table_keeps_the_mode_of_the_table_it_replaces(tmp_path, suffix):
    """The table every run appends to and several people share: a run under umask 077 made it 0o600, unreadable to the others."""
    t = tmp_path / f"train{suffix}"
    with umask(0o022):
        E.write_table(pd.DataFrame(dict(key=["a"], x=[1.0])), t)
    t.chmod(0o664)
    with umask(0o077):
        E.write_table(pd.DataFrame(dict(key=["a", "b"], x=[1.0, 2.0])), t)
    assert mode(t) == 0o664 and len(E.read_table(t)) == 2 and sorted(p.name for p in tmp_path.iterdir()) == [t.name]


@pytest.mark.parametrize("suffix", [".parquet", ".csv"])
def test_r17_m13_a_new_table_has_the_creation_mode_and_the_umask_applies(tmp_path, suffix):
    t = tmp_path / "new" / f"train{suffix}"
    with umask(0o027):
        E.write_table(pd.DataFrame(dict(key=["a"], x=[1.0])), t)
    assert mode(t) == 0o640 and len(E.read_table(t)) == 1


@pytest.mark.parametrize("suffix", [".parquet", ".csv"])
def test_r17_m13_a_symbolic_link_at_the_table_path_is_followed_and_stays_a_link(tmp_path, suffix):
    """OD-7: the link became a regular file and the table it pointed to kept its old rows."""
    real, link = tmp_path / f"real{suffix}", tmp_path / f"link{suffix}"
    E.write_table(pd.DataFrame(dict(key=["a"], x=[1.0])), real)
    link.symlink_to(real)
    E.write_table(pd.DataFrame(dict(key=["a", "b"], x=[1.0, 2.0])), link)
    assert link.is_symlink() and len(E.read_table(real)) == 2 and len(E.read_table(link)) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([real.name, link.name])


def test_r17_m13_the_append_of_a_row_keeps_the_mode_and_the_lock_file_stays_beside_the_table(tmp_path):
    t = tmp_path / "train.parquet"
    e = E.Emulator(["x"], ["y"], path=t)
    e.append(dict(x=1.0, y=2.0))
    t.chmod(0o664)
    with umask(0o077):
        e.append(dict(x=2.0, y=3.0))
    assert mode(t) == 0o664 and len(e.table()) == 2 and sorted(p.name for p in tmp_path.iterdir()) == ["train.parquet", "train.parquet.lock"]


def test_r17_m13_sibling_a_download_that_replaces_a_file_keeps_its_mode(server, tmp_path):
    """`remote.download` moved a `.part` made with the umask onto a stale file: the file a lab shares changed from 0o664 to 0o600."""
    u = server.put("a", b"fresh bytes")
    p = tmp_path / "a"
    p.write_bytes(b"stale")
    p.chmod(0o664)
    with umask(0o077):
        remote.download(u, p, hashlib.sha256(b"fresh bytes").hexdigest())
    assert p.read_bytes() == b"fresh bytes" and mode(p) == 0o664


def test_r17_m13_sibling_a_fetched_part_keeps_the_mode_of_the_part_it_replaces(tmp_path, monkeypatch):
    p = tmp_path / "part.nc"
    p.write_bytes(b"damaged")
    p.chmod(0o664)

    def child(args, deadline):
        with open(args[-1], "xb") as f:                                    # as `_child_ncss`: created here, with the umask
            f.write(b"whole")
    monkeypatch.setattr(hycom, "_child", child)
    with umask(0o077):
        hycom._fetch_part(["_ncss", "u"], p, 1.0)
    assert p.read_bytes() == b"whole" and mode(p) == 0o664 and sorted(q.name for q in tmp_path.iterdir()) == ["part.nc"]


def test_r17_m13_keep_mode_leaves_a_new_name_with_its_own_mode(tmp_path):
    tmp = tmp_path / "t"
    tmp.write_bytes(b"x")
    tmp.chmod(0o600)
    atomic.keep_mode(tmp, tmp_path / "absent")
    assert mode(tmp) == 0o600


def test_r17_m9_sibling_copy_manifest_uses_the_one_writer_keeps_the_mode_and_refuses_a_link(tmp_path):
    """`copy_manifest` copied to the fixed `<dest>.part` (two stages of one run shared it) and replaced `dest` with a file of the umask's mode; it is
    `atomic.write_with` now: a temporary of its own, the mode kept, and a link planted at `dest` refused as at every other writer."""
    src, dest = tmp_path / "m.json", tmp_path / "run" / "copy.json"
    src.write_text('{"t0": 1}')
    assert ledger.copy_manifest(src, dest) == {"t0": 1}
    dest.chmod(0o664)
    with umask(0o077):
        assert ledger.copy_manifest(src, dest) == {"t0": 1}
    assert mode(dest) == 0o664 and sorted(p.name for p in dest.parent.iterdir()) == ["copy.json"]
    src.write_text('{"t0": 2}')
    link = dest.parent / "link.json"
    link.symlink_to(dest)
    with pytest.raises(OSError) as e:
        ledger.copy_manifest(src, link)
    assert e.value.errno == errno.ELOOP and dest.read_text() == '{"t0": 1}'
    with pytest.raises(FileNotFoundError):
        ledger.copy_manifest(tmp_path / "absent.json", dest)
    assert sorted(p.name for p in dest.parent.iterdir()) == ["copy.json", "link.json"]


def test_r17_m9_sibling_no_module_of_the_pipeline_names_a_file_with_a_fixed_part_or_tmp_suffix_but_the_four_listed():
    """Sweep of cafe/pm: a string that is a `.part` / `.tmp` suffix. remote.py: the one `<name>.part` of `download`, resumed on purpose and held by a lock;
    bathy.py, hycom.py, pipeline.py: a name that is skipped or checked, never written. (ledger.py's `.part` was the fifth until round 17.)"""
    found = []
    root = config.ROOT / "cafe" / "pm"
    for p in sorted(root.rglob("*.py")):
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.Constant) and n.value in (".part", ".part.npz", ".tmp"):
                found.append(p.relative_to(root).as_posix())
    assert found == ["env/bathy.py", "env/hycom.py", "env/remote.py", "pipeline.py"]


# ---- M-14: the hull mesh reader --------------------------------------------------------------------------------------------------------------------------

_KEY = "stage3.fea_elements_along:"


def _read(tmp_path, monkeypatch, text):
    f = tmp_path / "assumptions.yaml"
    f.write_bytes(text.encode())
    monkeypatch.setattr(fea, "ASSUMPTIONS", f)
    return fea.hull_elements_along()


@pytest.mark.parametrize("text", [
    f"a: 1\n---\n{_KEY}\n  value: 70\n",                                    # PyYAML: ComposerError (two documents)
    f"a: 1\n...\n{_KEY}\n  value: 70\n",
    f"- a\n{_KEY}\n  value: 70\n",                                           # a list before the key
    f"{_KEY}\n  value: 70\n- a\n",                                          # a list after the entry
    f"{_KEY}\t\n  value: 70\n",                                             # a tab after the key's colon
    f"{_KEY}\t# note\n  value: 70\n",
    f"\tb: 1\n{_KEY}\n  value: 70\n",
    f"{_KEY}\n  value: 70\nb:\t1\n",
])
def test_r17_m14_the_reader_refuses_a_file_pyyaml_refuses_instead_of_returning_70(tmp_path, monkeypatch, text):
    """`a: 1`, `---`, then the entry: PyYAML raises (two documents), the reader returned 70, so the Hangar meshed a hull the pipeline could not read."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)
    with pytest.raises(ValueError, match="stage3.fea_elements_along"):
        _read(tmp_path, monkeypatch, text)


@pytest.mark.parametrize("n, ok", [(1, True), (70, True), (500, True), (501, False), (70000, False), (10 ** 25, False)])
def test_r17_m14_a_value_above_the_bound_is_refused(tmp_path, monkeypatch, n, ok):
    """OD-8: `value: 10000000000000000000000000` came back as the number of elements along the hull (h = L / 1e25: millions of shell elements until the
    deadline). 500 is about 7 times the converged study's 70."""
    text = f"{_KEY}\n  value: {n}\n"
    if ok:
        assert _read(tmp_path, monkeypatch, text) == n == yaml.safe_load(text)["stage3.fea_elements_along"]["value"]
    else:
        with pytest.raises(ValueError, match=f"above {fea.MAX_ELEMENTS_ALONG}"):
            _read(tmp_path, monkeypatch, text)
    assert fea.MAX_ELEMENTS_ALONG == 500


def test_r17_m14_the_shipped_file_still_reads_and_pyyaml_agrees_within_the_bound():
    """The stage-3 pipeline reads the key with PyYAML (pipeline_windows.assumptions), the Hangar with the line reader: one number, inside the bound."""
    from cafe.pm.stage3 import pipeline_windows as pw
    want = yaml.safe_load(fea.ASSUMPTIONS.read_text())["stage3.fea_elements_along"]["value"]
    assert fea.hull_elements_along() == want == pw.assumptions()["fea_elements_along"] and 1 <= want <= fea.MAX_ELEMENTS_ALONG


def test_r17_m14_comments_blank_lines_and_indented_text_do_not_trip_the_top_level_rule(tmp_path, monkeypatch):
    text = f"# a note\n\na: 1\n  # indented note\n   \n{_KEY}  # mesh\n  value: 70\n  why: \"- x: 1\"\nb:\n  - item\n  - more\n"
    assert _read(tmp_path, monkeypatch, text) == 70 == yaml.safe_load(text)["stage3.fea_elements_along"]["value"]


# ---- M-15: a loop of symbolic links ----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("write", [lambda p, **k: atomic.write_text(p, "x", **k), lambda p, **k: atomic.write_with(p, lambda fh: fh.write(b"x"), **k)],
                         ids=["write_text", "write_with"])
def test_r17_m15_a_loop_of_links_is_eloop_not_a_regular_file_in_place_of_one_link(tmp_path, write):
    """`a -> b -> a` with `follow_symlinks=True` returned with no error and left `a` a regular file (and `b` a link to it)."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.symlink_to(b)
    b.symlink_to(a)
    with pytest.raises(OSError) as e:
        write(a, follow_symlinks=True)
    assert e.value.errno == errno.ELOOP and a.is_symlink() and b.is_symlink() and sorted(p.name for p in tmp_path.iterdir()) == ["a", "b"]
    with pytest.raises(OSError) as e:                                       # a link to itself
        c = tmp_path / "c"
        c.symlink_to(c)
        write(c, follow_symlinks=True)
    assert e.value.errno == errno.ELOOP and c.is_symlink()


@pytest.mark.parametrize("write", [lambda p, **k: atomic.write_text(p, "x", **k), lambda p, **k: atomic.write_with(p, lambda fh: fh.write(b"x"), **k)],
                         ids=["write_text", "write_with"])
def test_r17_m15_a_dangling_link_and_a_chain_still_work_with_follow_symlinks(tmp_path, write):
    target, mid, link = tmp_path / "target", tmp_path / "mid", tmp_path / "link"
    mid.symlink_to(target)
    link.symlink_to(mid)
    write(link, follow_symlinks=True)                                      # the target does not exist: the link is dangling, not a loop
    assert link.is_symlink() and mid.is_symlink() and target.read_bytes() == b"x"
