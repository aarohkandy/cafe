"""Round 19, batch E: the lock's re-entry by the file's identity (M-7), the half-deleted aside and the advice for a missing store (M-11), and the two surviving
mutants of `hycom.asides` (M-16, A-6). Each test names its item; the defects were seen to fail on the tree at 51eb433 (the hand-back says how)."""
import os
import pathlib
import shutil
import threading

import pytest

from cafe.pm import config, ledger, pipeline
from cafe.pm.env import hycom as h, remote
from tests import lockprobe
from tests.test_hycom import fx, truth  # noqa: F401  (fixtures)
from tests.test_ingest_fetch import CMD, data, data_copy  # noqa: F401  (fixtures)
from tests.test_pipeline import MISSION_PATH, check_of, ctx_for, read_ledger, run_stage
from tests.test_round18_e import _store, _tree
from tests.test_round18_m import _leftover


def _within(fn, seconds=15):
    """`fn()` on a thread of its own (the lock's hold is per thread) that must end in `seconds`: a lock that waits for itself fails the test instead of
    hanging it (the thread is a daemon; it stays blocked in `flock`, holding a file of `tmp_path`)."""
    out: list = []

    def run():
        try:
            out.append(fn())
        except BaseException as e:                                                       # noqa: BLE001  handed to the caller below
            out.append(e)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "the nested take of the same lock file waits for ever"
    if isinstance(out[0], BaseException):
        raise out[0]
    return out[0]


# ---------------------------------------------------------------- M-7: the re-entry key is the file, not the spelling of its path

def _spellings(tmp_path, monkeypatch):
    """{what: (the cache argument and the name of the second take)} for one file, `d/sub/a.lock`, which the first take names as (d/sub, 'a.lock')."""
    d = tmp_path / "d"
    sub = d / "sub"
    sub.mkdir(parents=True)
    (d / "link").symlink_to(sub, target_is_directory=True)
    (sub / "a.lock").touch()
    os.link(sub / "a.lock", sub / "hard.lock")
    monkeypatch.chdir(d)
    return sub, {"the same": (sub, "a.lock"), "a trailing dot": (sub / ".", "a.lock"), "a dot-dot": (sub / ".." / "sub", "a.lock"),
                 "a symlinked directory": (d / "link", "a.lock"), "a relative path": (pathlib.Path("sub"), "a.lock"),
                 "a second name of the file": (sub, "hard.lock")}


@pytest.mark.parametrize("spelling", ["the same", "a trailing dot", "a dot-dot", "a symlinked directory", "a relative path", "a second name of the file"])
def test_r19_m7_the_same_thread_takes_one_lock_file_again_whatever_the_spelling_of_its_path(tmp_path, monkeypatch, spelling):
    """The key was the text of the path: `d/link` (a link to `sub`) and `d/sub/../sub` took a second `flock` on the file the thread held and waited for itself
    (two of the four spellings of the reviewers' probe hung; a relative path and a second hard link to the file did too)."""
    sub, cases = _spellings(tmp_path, monkeypatch)
    f = sub / "a.lock"
    args = cases[spelling]

    def nested():
        with remote.store_lock(sub, "a.lock") as outer:
            with remote.store_lock(*args) as inner:
                inside = lockprobe.held(f)
            return outer, inner, inside, lockprobe.held(f)                              # the inner end does not release the outer hold
    outer, inner, inside, after_inner = _within(nested)
    assert outer is True and inner is True and inside and after_inner
    assert not lockprobe.held(f)                                                        # the outer end releases it


def test_r19_m7_two_files_are_two_locks_and_each_end_releases_only_its_own(tmp_path):
    """The key must not be coarser than the file (a key of the directory would let the second name of a store through without a lock)."""
    a, b = tmp_path / "a.lock", tmp_path / "b.lock"

    def nested():
        with remote.store_lock(tmp_path, "a.lock"):
            with remote.store_lock(tmp_path, "b.lock") as inner:
                both = lockprobe.held(a) and lockprobe.held(b)
            return inner, both, lockprobe.held(a), lockprobe.held(b)
    inner, both, a_after, b_after = _within(nested)
    assert inner is True and both and a_after and not b_after
    assert not lockprobe.held(a)


def test_r19_m7_a_lock_file_replaced_while_held_is_another_file_and_is_taken_afresh(tmp_path):
    """Foresight for the new key: the hold is of the inode. A lock file removed and made again under the same name (an operator's `rm`, which RUNBOOK says not
    to do) is another file: the nested take is a lock of its own, not a wait for the first and not a claim that this thread holds the new file."""
    f = tmp_path / "x.lock"

    def nested():
        with remote.store_lock(tmp_path, "x.lock"):
            first = os.stat(f).st_ino
            f.unlink()
            with remote.store_lock(tmp_path, "x.lock") as inner:
                return first != os.stat(f).st_ino, inner, lockprobe.held(f)
    other_inode, inner, held_new = _within(nested)
    assert other_inode and inner is True and held_new
    assert not lockprobe.held(f)


def test_r19_m7_a_lock_held_in_one_thread_still_excludes_another_thread(tmp_path):
    """The set of held files is per thread: a second thread asking for the file that the first holds waits (it is not let in by the first's key)."""
    got = threading.Event()
    with remote.store_lock(tmp_path, "y.lock"):
        def other():
            with remote.store_lock(tmp_path, "y.lock"):
                got.set()
        t = threading.Thread(target=other, daemon=True)
        t.start()
        assert not got.wait(1.0)
    assert got.wait(15)


# ---------------------------------------------------------------- M-11: a half-deleted aside is never offered, and a missing store's advice is where run and fetch print

class Killed(BaseException):
    """A kill in the middle of the delete of a leftover (a BaseException, as the process dies: nothing between catches it)."""


def _die_in_the_delete(monkeypatch):
    """`shutil.rmtree` of an aside (`.old.tmp`) or of a renamed one (`.dead.tmp`) unlinks one file and is killed; anything else is the real one."""
    real = shutil.rmtree

    def rmtree(p, *a, **k):
        p = pathlib.Path(p)
        if p.name.endswith((".old.tmp", ".dead.tmp")) and p.is_dir():
            sorted(q for q in p.rglob("*") if q.is_file())[0].unlink()
            raise Killed
        return real(p, *a, **k)
    monkeypatch.setattr(h.shutil, "rmtree", rmtree)
    return lambda: monkeypatch.setattr(h.shutil, "rmtree", real)


def _a_store_whose_delete_was_killed(fx, truth, tmp_path, monkeypatch, in_the_sweep):  # noqa: F811
    """`out` is the new, whole store and one half-deleted leftover of it is beside it (the kill came in the delete of the write's own old store, or, with
    `in_the_sweep`, in the sweep of an earlier leftover: the store was missing when the write began, so it had no old store of its own)."""
    out = tmp_path / "gofs_x.zarr"
    if in_the_sweep:
        left = _leftover(tmp_path, out, truth)
        shutil.rmtree(out)
        old = _tree(left)
    else:
        old = _store(truth, out, "old")
    undo = _die_in_the_delete(monkeypatch)
    with pytest.raises(Killed), remote.store_lock(tmp_path, out.name + ".lock"):
        _store(truth, out, "new")
    undo()
    return out, old


@pytest.mark.parametrize("in_the_sweep", [False, True])
def test_r19_m11_a_leftover_whose_delete_was_killed_is_a_dead_name_that_is_not_offered_for_mv(fx, truth, tmp_path, monkeypatch, in_the_sweep):  # noqa: F811
    out, old = _a_store_whose_delete_was_killed(fx, truth, tmp_path, monkeypatch, in_the_sweep)
    assert h.open_store(out).attrs["generation"] == "new"                              # the store itself is the new one, whole
    assert h.asides(out) == []                                                          # before: the half-deleted tree kept its `.old.tmp` name and was offered
    (dead,) = h.dead(out)
    assert dead.name.endswith(".dead.tmp") and len(dead.name) == 39 and dead.name.startswith(h._aside_stem(out))
    assert 0 < len(_tree(dead)) < len(old)                                              # it is part of a store: what `mv` would have put back
    shutil.rmtree(out)                                                                  # what the RUNBOOK says to do with a store that will not open
    with pytest.raises(config.ConfigError) as e:
        h.open_store(out)
    assert "mv " not in str(e.value) and "BUT" not in str(e.value) and str(dead) not in str(e.value)
    assert h.leftover_note(out, False) == "" and h.leftover_note(out, True) == ""


def test_r19_m11_the_next_write_deletes_a_dead_leftover_locked_or_not_and_leaves_what_is_not_this_stores(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out, other = tmp_path / "gofs_x.zarr", tmp_path / "gofs_y.zarr"
    mine = h._aside_name(out).with_name(h._aside_name(out).name.replace(".old.tmp", ".dead.tmp"))
    theirs = h._aside_name(other).with_name(h._aside_name(other).name.replace(".old.tmp", ".dead.tmp"))
    for q in (mine, theirs):
        q.mkdir()
        (q / "zarr.json").write_text("{}")
    _store(truth, out, "again")                                                         # no lock file: a lab store is not locked, and a dead tree needs none
    assert not mine.exists() and theirs.is_dir() and not (tmp_path / "gofs_x.zarr.lock").exists()
    mine.mkdir()
    with remote.store_lock(tmp_path, out.name + ".lock"):                               # the ingest's hold
        _store(truth, out, "third")
    assert not mine.exists() and theirs.is_dir() and h.open_store(out).attrs["generation"] == "third"


def test_r19_m11_a_rename_of_the_aside_that_fails_leaves_it_whole_under_its_own_name_and_the_next_locked_write_sweeps_it(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    real = os.replace

    def replace(a, b, *k, **kw):
        if str(b).endswith(".dead.tmp"):
            raise PermissionError("the rename to the dead name is refused")
        return real(a, b, *k, **kw)
    monkeypatch.setattr(os, "replace", replace)
    _store(truth, out, "new")                                                           # the new store is in; the write does not fail for a leftover
    monkeypatch.setattr(os, "replace", real)
    (left,) = h.asides(out)
    assert h.open_store(out).attrs["generation"] == "new" and _tree(left) == old       # whole, so what `unreadable` offers is true
    with remote.store_lock(tmp_path, out.name + ".lock"):
        _store(truth, out, "again")
    assert h.asides(out) == [] and h.dead(out) == []


def test_r19_m11_a_dead_name_and_a_link_are_no_aside_and_the_old_name_still_is(fx, truth, tmp_path):  # noqa: F811
    """969's pattern test (`test_round18_m`) gains the new suffix: `asides` offers `.old.tmp` only, `dead` offers `.dead.tmp` only."""
    out = tmp_path / "gofs_x.zarr"
    old, gone = h._aside_name(out), h._aside_name(out).with_name(h._aside_name(out).name.replace(".old.tmp", ".dead.tmp"))
    old.mkdir()
    gone.mkdir()
    assert h.asides(out) == [old] and h.dead(out) == [gone]


def test_r19_m11_the_note_for_a_missing_store_names_the_leftover_and_says_what_stays(fx, truth, tmp_path):  # noqa: F811
    for lab in (False, True):
        store = tmp_path / ("lab_x.zarr" if lab else "gofs_x.zarr")
        aside = h._aside_name(store)
        shutil.copytree(fx["gofs_zarr"], aside)
        note = h.leftover_note(store, lab)
        assert str(aside) in note and f"mv {aside} {store}" in note and "without a download" in note and ".<12 hex>.tmp" in note and "remove it by hand" in note
        assert ("nothing deletes the leftovers of a lab store" in note) == lab           # a lab store is not locked, so nothing sweeps it
        assert ("an ingest that writes the store deletes the ones left" in note) == (not lab)
        store.mkdir()                                                                   # a store that is there: `mv` would put the aside INSIDE it
        assert h.leftover_note(store, lab) == ""
    assert h.leftover_note(tmp_path / "gofs_nothing.zarr", False) == ""                 # no leftover: nothing to add


def _kill_the_store(data_copy):
    """The ocean store of the CI tree moved to the name a killed replace leaves it under, beside the missing name."""
    store = data_copy / "ocean" / "gofs_ci_fixture.zarr"
    aside = h._aside_name(store)
    os.replace(store, aside)
    return store, aside


def test_r19_m11_run_and_fetch_print_the_leftover_where_they_meet_the_missing_store(tmp_path, data_copy, monkeypatch):
    """`s_ingest` (what `run` and `fetch` both start with) found the store missing in `_ocean_cached`, before anything opened it, so only the plain
    'not cached' note came out and `hycom.open_store`'s `mv` text was never printed. Offline, and online with a fetch that fails."""
    store, aside = _kill_the_store(data_copy)
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "off"), "ingest")
    note = check_of(read_ledger(tmp_path / "off", "ingest"), "ocean_store_present")["note"]
    assert "CAFE_OFFLINE is set" in note and f"mv {aside} {store}" in note

    monkeypatch.delenv("CAFE_OFFLINE")

    def fail(*a, **k):
        raise h.FetchError("3 of 39 parts failed")
    monkeypatch.setattr(h, "fetch_gofs", fail)
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "on"), "ingest")
    note = check_of(read_ledger(tmp_path / "on", "ingest"), "ocean_store_present")["note"]
    assert f"rerun `{CMD}`" in note and f"mv {aside} {store}" in note and "an ingest that writes the store deletes the ones left" in note


def test_r19_m11_a_lab_store_that_is_missing_names_its_leftover_and_that_nothing_deletes_it(tmp_path, data_copy):
    lab = data_copy / "ocean" / "lab_x.zarr"
    aside = h._aside_name(lab)
    shutil.copytree(data_copy / "ocean" / "gofs_ci_fixture.zarr", aside)
    raw = MISSION_PATH.read_text().replace("ocean: {source: gofs31}", f"ocean: {{source: lab_hycom, path: {lab}}}")
    (tmp_path / "lab.yaml").write_text(raw)
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "r", mission=tmp_path / "lab.yaml"), "ingest")
    note = check_of(read_ledger(tmp_path / "r", "ingest"), "ocean_store_present")["note"]
    assert "cafe.pm ingest-ocean" in note and f"mv {aside} {lab}" in note and "nothing deletes the leftovers of a lab store" in note


def test_r19_m11_a_store_that_is_there_but_short_offers_no_mv(tmp_path, data_copy):
    """`mv aside store` onto a store that exists moves the aside INSIDE it: the note offers it only for a missing name."""
    store, aside = _kill_the_store(data_copy)
    shutil.copytree(aside, store)
    ctx = ctx_for(tmp_path / "r")
    with pytest.raises(ledger.StageFailed, match="x_present: the store is not cached") as e, ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
        assert pipeline._need(ctx, L, "x", "the store", lambda: False, lambda: None, leftover=lambda: h.leftover_note(store, False)) is False
    assert "mv " not in str(e.value) and "BUT" not in str(e.value)
    with pytest.raises(ledger.StageFailed, match=f"mv {aside} ") as e2, ledger.Ledger(ctx.run_dir, "ingest2", ctx.hash) as L:      # (the same, no store)
        shutil.rmtree(store)
        assert pipeline._need(ctx, L, "x", "the store", lambda: False, lambda: None, leftover=lambda: h.leftover_note(store, False)) is False


# ---------------------------------------------------------------- M-16, A-6: the two conditions of `asides` that the sweep tests did not hold (H7, H9)

def test_r19_a6_h7_a_link_with_the_name_of_an_aside_is_no_aside(tmp_path):
    out = tmp_path / "gofs_x.zarr"
    real_dir, real_aside = tmp_path / "somewhere", h._aside_name(out)
    real_dir.mkdir()
    real_aside.mkdir()
    h._aside_name(out).symlink_to(real_dir, target_is_directory=True)                   # a directory by `is_dir` (it follows the link), a link by name
    assert h.asides(out) == [real_aside]                                                # (`rmtree` of a link is refused and the link would stay for ever)


def test_r19_a6_h9_only_twelve_hex_digits_make_an_aside(tmp_path):
    out = tmp_path / "gofs_x.zarr"
    good = h._aside_name(out)
    good.mkdir()
    for digits in ("0123456789a", "0", "0123456789abc", "0123456789ag", "0123456789AB"):    # 11, 1 and 13 digits; a non-hex digit; capitals
        (tmp_path / f"{h._aside_stem(out)}{digits}.old.tmp").mkdir()
    assert h.asides(out) == [good]


def test_r19_m11_the_dead_names_are_held_by_the_same_conditions_as_the_asides(tmp_path):
    out = tmp_path / "gofs_x.zarr"
    stem, real_dir = h._aside_stem(out), tmp_path / "somewhere"
    real_dir.mkdir()
    (tmp_path / f"{stem}0123456789ab.dead.tmp").mkdir()
    (tmp_path / f"{stem}0123456789cd.dead.tmp").symlink_to(real_dir, target_is_directory=True)
    for digits in ("0123456789a", "0", "0123456789abc", "0123456789ag", "0123456789AB"):
        (tmp_path / f"{stem}{digits}.dead.tmp").mkdir()
    assert h.dead(out) == [tmp_path / f"{stem}0123456789ab.dead.tmp"] and h.asides(out) == []
