"""Round 20, batch E (M-8): the `mv` that `hycom.leftover_note` offers is the newest aside by modification time, and a half-deleted `.dead.tmp` beside a store
is named with its size (`hycom.dead_note`, said by `pipeline._need` whether the store is there or not). Each test fails on the tree at 8e22951."""
import os
import pathlib
import shlex

import pytest

from cafe.pm import ledger, pipeline
from cafe.pm.env import hycom as h
from tests.test_ingest_fetch import data, data_copy  # noqa: F401  (fixtures)
from tests.test_pipeline import check_of, ctx_for, read_ledger, run_stage
from tests.test_round19_e import _kill_the_store


def _dir(path: pathlib.Path, mtime: float, nbytes: int = 0) -> pathlib.Path:
    path.mkdir()
    if nbytes:
        (path / "c").write_bytes(b"x" * nbytes)
    os.utime(path, (mtime, mtime))
    return path


def _dead(store: pathlib.Path, digits: str) -> pathlib.Path:
    return store.with_name(f"{h._aside_stem(store)}{digits}.dead.tmp")


@pytest.mark.parametrize("newest_name", ["000000000000", "ffffffffffff"])
def test_r20_m8_the_mv_offers_the_newest_aside_whatever_the_random_names(tmp_path, newest_name):
    """The names are random, so sorting by name made the offered one a coin toss; the reviewer's two orders."""
    store = tmp_path / "lab_x.zarr"
    stem = h._aside_stem(store)
    names = ("000000000000", "ffffffffffff")
    new = _dir(tmp_path / f"{stem}{newest_name}.old.tmp", 2_000_000_000.0)
    (older,) = (_dir(tmp_path / f"{stem}{n}.old.tmp", 1_900_000_000.0) for n in names if n != newest_name)
    note = h.leftover_note(store, True)
    assert f"`mv {new} {store}` puts it back" in note and f"mv {older} " not in note
    assert note.index(str(new)) < note.index(str(older))                                # the newest is listed first
    assert f"{new} (0.0 GB, newest, modified 2033-05-18 03:33 UTC)" in note and f"{older} (0.0 GB, older, modified 2030-03-17 17:46 UTC)" in note


def test_r20_m8_a_vanished_directory_has_no_time(tmp_path):
    assert h._mtime(tmp_path / "gone") == 0.0


def test_r20_m8_a_dead_leftover_is_named_with_its_size_and_how_to_delete_it(tmp_path):
    store = tmp_path / "gofs_x.zarr"
    assert h.dead_note(store) == ""                                                     # nothing beside the store: nothing to add
    a, b = _dir(_dead(store, "0123456789ab"), 1e9, 2_000_000), _dir(_dead(store, "0123456789cd"), 1e9)
    (tmp_path / "gofs_y.zarr").mkdir()
    _dir(_dead(tmp_path / "gofs_y.zarr", "0123456789ab"), 1e9)                          # another store's: not named
    note = h.dead_note(store)
    assert f"{a} (0.0 GB)" in note and f"{b} (0.0 GB)" in note and "safe to delete" in note and f"`rm -r {a} {b}`" in note
    assert "gofs_y" not in note
    store.mkdir()
    assert h.dead_note(store) == note                                                   # a store that is there: `leftover_note` says "", this does not


def test_r20_m8_need_passes_a_present_store_and_says_the_dead_leftover_beside_it(tmp_path):
    store = tmp_path / "gofs_x.zarr"
    store.mkdir()
    gone = _dir(_dead(store, "0123456789ab"), 1e9)
    seen: list[str] = []
    ctx = ctx_for(tmp_path / "r", log=seen.append)
    with ledger.Ledger(ctx.run_dir, "ingest", ctx.hash) as L:
        assert pipeline._need(ctx, L, "x", "the store", lambda: True, lambda: None, leftover=lambda: h.leftover_note(store, False) + h.dead_note(store))
    (c,) = L.d["checks"]
    assert c["ok"] and c["note"].startswith("the store; a half-deleted leftover") and str(gone) in c["note"] and "safe to delete" in c["note"]
    assert seen == [f"ingest: {c['note']}"]
    seen.clear()                                                                        # nothing beside it: the note and the log are as they were
    with ledger.Ledger(ctx.run_dir, "ingest2", ctx.hash) as L2:
        assert pipeline._need(ctx, L2, "x", "the store", lambda: True, lambda: None, leftover=lambda: "")
    assert L2.d["checks"][0]["note"] == "the store" and seen == []


def test_r20_m8_ingest_passes_with_a_dead_leftover_beside_the_store_and_fails_naming_both_when_the_store_is_gone(tmp_path, data_copy):  # noqa: F811
    store, aside = _kill_the_store(data_copy)
    os.replace(aside, store)                                                            # the store is back, whole
    gone = _dir(_dead(store, "0123456789ab"), 1e9, 1000)
    seen: list[str] = []
    ledger_d = run_stage(pipeline.s_ingest, ctx_for(tmp_path / "ok", log=seen.append), "ingest")
    note = check_of(ledger_d, "ocean_store_present")["note"]
    assert check_of(ledger_d, "ocean_store_present")["ok"] and str(gone) in note and "safe to delete" in note and any(str(gone) in s for s in seen)
    os.replace(store, h._aside_name(store))                                             # killed again between the renames: no store, an aside and a dead one
    with pytest.raises(ledger.StageFailed, match="ocean_store_present"):
        run_stage(pipeline.s_ingest, ctx_for(tmp_path / "bad"), "ingest")
    note = check_of(read_ledger(tmp_path / "bad", "ingest"), "ocean_store_present")["note"]
    assert f"mv {shlex.quote(str(next(iter(h.asides(store)))))} " in note and str(gone) in note and note.index("mv ") < note.index("safe to delete")
