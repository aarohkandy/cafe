"""Round 18, merge step (job 1 and job 2): the combination of the six batches and the follow-ups they handed over. Each test names its item. The tests of job 2
were run against the tree at a4073db (the merge before this step's code) and seen to fail where the item is a defect (review/round_18/handbacks and the
merge step's report)."""
import contextlib
import html
import inspect
import json
import os
import re
import shutil
import sys
import threading
import types

import numpy as np
import pytest
import yaml

from cafe import cfd, fea
from cafe.pm import config, credibility, pipeline, report, stage1
from cafe.pm.env import hycom as h, remote, surface as S
from cafe.pm.env.environment import GriddedEnv
from cafe.pm.stats import intervals, sequential as Q
from tests.fixtures import pm_run
from tests.test_hycom import fx, truth  # noqa: F401  (fixtures)
from tests.test_round18_e import _KILL, _store, _tree

ROOT = config.ROOT


# ---------------------------------------------------------------- job 1: the link card (batch A) and L23, the docstring and PHYSICS 12.1 (batch B)

CARD_CASES = {                                   # (the heights of the two ends [m]) -> the sentence of `_low_antenna_note`
    "both low": (0.5, 0.3), "one below 0.5 m": (0.3, 2.2), "an end of 0.5 m": (0.5, 2.2),
}


def _card(kind):
    """The real `report._low_antenna_note` for a link whose two ends have the given heights: a glider and a USV (or a second glider) with the platform
    heights patched in, so the sentence is the one a mission with those antennas prints."""
    ha, hb = CARD_CASES[kind]
    mission = dict(vehicles=[dict(id="a", platform="pa"), dict(id="b", platform="pb")])
    lk = dict(kind="rf", a="a", b="b")
    from cafe.pm.physics import glider, usv
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(report, "_classes", lambda m: dict(a="glider", b="usv" if hb == 2.2 else "glider"))
        mp.setattr(glider, "load_platform", lambda p: dict(antenna_height_m={"pa": ha, "pb": hb}[p]))
        mp.setattr(usv, "load_platform", lambda p: dict(rf_antenna_height_m=hb))
        return report._low_antenna_note(lk, mission)


def test_m1_the_link_card_and_l23_and_the_docstring_and_physics_state_the_same_figures():
    """Batch A's card sentences and batch B's L23, `two_ray_curved_db` docstring and PHYSICS 12.1 paragraph were written by two batches. Since the round 18
    addendum (DECISIONS 991) they all print the figures of `comms.LOW_ANTENNA_PAIR_BAND` row by row: every row's minimum, median and maximum is in the docstring
    ('/' form), in L23 and in the card of a link that has that pair, and in PHYSICS 12.1; the range (300 m to the horizon) and the 'nearer than 300 m is not
    stated' sentence agree too (tests/test_round18_x.py holds each row against a recomputation and every direction word against its sign)."""
    from cafe.pm.physics import comms
    l23 = next(x["text"] for x in credibility.LIMITATIONS if x["id"] == "L23")
    doc = " ".join(inspect.getdoc(comms.two_ray_curved_db).split())                           # (the docstring wraps lines inside a figure)
    para = " ".join(next(p for p in (ROOT / "docs" / "PHYSICS.md").read_text().split("\n\n") if p.startswith("**Low antennas**")).split())
    for (lo, hi), (mn, md, mx) in comms.LOW_ANTENNA_PAIR_BAND.items():
        assert f"{mn:+.1f} / {md:+.1f} / {mx:+.1f}" in doc, (lo, hi)
        assert credibility.pair_figures((lo, hi)) in l23, (lo, hi)
        assert f"{mn:+.1f} to {mx:+.1f}" in para and f"({md:+.1f})" in para, (lo, hi)
    cards = {k: _card(k) for k in CARD_CASES}
    assert all(cards.values())
    for kind, sentence in cards.items():
        lo, hi = sorted(CARD_CASES[kind])
        assert credibility.pair_figures((lo, hi)) in sentence, kind
        assert "300 m" in sentence and "nearer than 300 m this is not stated" in sentence
    for text in (l23, doc, para):
        assert "300 m" in text and re.search(r"[Nn]earer than 300 m|Below 300 m", text)
    assert cards["both low"].startswith("Both ends of this RF link")
    assert cards["one below 0.5 m"].startswith("An end of this RF link has an antenna below 0.5 m:")
    assert cards["an end of 0.5 m"].startswith("An end of this RF link has an antenna of 0.5 m:")
    for text in (l23, *cards.values()):
        assert "never too high" not in text and "are not affected" not in text


# ---------------------------------------------------------------- job 2 (a): store_lock's `log` is passed by every caller that has a logger

def test_a_the_ingests_shared_store_lock_that_cannot_be_opened_says_so_in_the_runs_log(tmp_path, monkeypatch):
    """`store_lock` got a `log` in batch E, but the ingest's `_shared_store` did not pass it: a lock that could not be opened (a link at its name) ran the fetch
    unlocked in silence."""
    monkeypatch.setenv("CAFE_OFFLINE", "0")
    said = []
    ctx = types.SimpleNamespace(log=said.append)
    d = tmp_path / "ocean"
    d.mkdir()
    (d / "gofs_x.zarr.lock").symlink_to(tmp_path / "nowhere")                          # O_NOFOLLOW: no lock
    with pipeline._shared_store(ctx, d, "gofs_x.zarr.lock", "the ocean store gofs_x.zarr"):
        pass
    assert len(said) == 1 and "gofs_x.zarr.lock is not locked" in said[0] and "runs without the lock" in said[0]


@pytest.fixture
def spy(monkeypatch):
    """Records, for every `store_lock` taken through `surface` (the name `pipeline` and `surface.build` call), the function that called it and its `log`."""
    calls = []
    real = S.store_lock

    def spying(*a, **k):
        calls.append((sys._getframe(1).f_code.co_name, k.get("log")))
        return real(*a, **k)
    monkeypatch.setattr(S, "store_lock", spying)
    return calls


def test_a_every_store_lock_of_the_pipeline_and_the_surface_build_passes_the_runs_logger(tmp_path, monkeypatch, spy):
    said = []
    ctx = types.SimpleNamespace(cache=tmp_path / "cache", window_s=lambda: (0.0, 1.0), log=said.append, env=None, _env=None, run_dir=tmp_path / "run")
    ctx.cache.mkdir()
    # `_derived_record` (the decision and the build) and `_derived_unchanged` (the hash of the store)
    monkeypatch.setattr(pipeline, "_derived_span_problem", lambda cache, window: None)

    def build(env, cache, key, log=print):
        (cache / "derived.zarr").mkdir()
        (cache / "derived.zarr" / "zarr.json").write_text('{"attributes": {"layout_version": %d, "built_from": "K"}}' % S.LAYOUT_VERSION)
        config.write_json(cache / S.DIGEST, dict(built_from="K", store_sha256=S.store_sha256(cache / "derived.zarr")))
    monkeypatch.setattr(S, "build", build)
    rec = pipeline._derived_record(ctx, "K")
    ledger = types.SimpleNamespace(input=lambda *a, **k: None, check=lambda *a, **k: None)
    (ctx.run_dir / "ingest").mkdir(parents=True)
    (ctx.run_dir / "ingest" / S.DIGEST).write_text('{"store_sha256": "%s"}' % rec["store_sha256"])
    ctx.mission_path = "m.yaml"
    ctx.env = types.SimpleNamespace(subgrid=object())
    pipeline._derived_unchanged(ctx, ledger)
    del ctx.env                                                                       # (it is a property of the real Context: the next call goes through it)
    # `Context.env`: the layer checked is the layer loaded, under one hold
    monkeypatch.setattr(pipeline, "ocean", lambda c: None)
    monkeypatch.setattr(pipeline.par, "adopt", lambda e: e)
    monkeypatch.setattr(sys.modules["cafe.pm.env.environment"], "GriddedEnv", lambda *a, **k: types.SimpleNamespace())
    monkeypatch.setattr(S, "SurfaceLayer", lambda *a, **k: types.SimpleNamespace())
    ctx.mission = dict(environment={})
    pipeline.Context.env.fget(ctx)
    # the ingest's shared store
    monkeypatch.setenv("CAFE_OFFLINE", "0")
    with pipeline._shared_store(ctx, tmp_path / "ocean", "gofs_x.zarr.lock", "the ocean store"):
        pass
    # `_derived_current`, `store_span` and `SurfaceLayer` take the lock inside one of the holds above (re-entrant: no log is due) or have no logger
    where = {name: [log for n, log in spy if n == name] for name in ("_derived_record", "_derived_unchanged", "env", "_shared_store")}
    assert all(len(v) == 1 and v[0] is ctx.log for v in where.values()), where


def test_a_the_surface_layer_build_passes_its_log_to_the_lock(ci_env, tmp_path, spy):
    d = tmp_path / "cache"
    for s in ("wrf.zarr", "umwm.zarr"):
        shutil.copytree(ci_env.cache / "orca" / s, d / "orca" / s)
    said = []
    S.build(GriddedEnv(d, config.env_sigmas()), d, "k", log=said.append)
    assert [(n, lg == said.append) for n, lg in spy if n == "build"] == [("build", True)]
    (d / "derived.lock").unlink()
    (d / "derived.lock").symlink_to(tmp_path / "nowhere")                              # the lock cannot be opened: the build is logged as unlocked
    S.build(GriddedEnv(d, config.env_sigmas()), d, "k2", log=said.append)
    assert any("derived.lock is not locked" in m for m in said)


def test_a_an_error_raised_in_an_unlocked_block_does_not_carry_the_failed_open_as_its_context(tmp_path):
    """`store_lock` yielded `False` from inside its `except` clause, so whatever the caller's block raised got the lock's `FileNotFoundError` (or the link's
    ELOOP) as `__context__`, replacing the context the block's own code had given it (batch E's put-back test saw 'No such file ... .lock' as the first
    failure of `write_store`)."""
    (tmp_path / "a.lock").symlink_to(tmp_path / "nowhere")                          # a link at the name: the open fails (ELOOP), the block runs unlocked
    for name, create in (("a.lock", True), ("none.lock", False)):                     # and no lock file at all with create=False
        first = KeyError("the block's own first failure")
        with pytest.raises(ValueError) as e, remote.store_lock(tmp_path, name, create=create) as held:
            assert held is False
            try:
                raise first
            except KeyError:
                raise ValueError("the block's second failure") from first
        assert e.value.__context__ is first and e.value.__cause__ is first


# ---------------------------------------------------------------- job 2 (b): the leftover of a killed replace of the ocean store

def _leftover(tmp_path, out, truth_ds, generation="old"):
    """`out` holds a store; a copy of it under the name an earlier, killed `write_store` of `out` would have left."""
    _store(truth_ds, out, generation)
    left = out.with_name(h._aside_name(out).name)
    shutil.copytree(out, left)
    return left


def test_b_a_leftover_has_the_name_of_its_own_store_and_only_that_one_is_found(tmp_path):
    out, other = tmp_path / "gofs_x.zarr", tmp_path / "gofs_y.zarr"
    mine, theirs = h._aside_name(out), h._aside_name(other)
    live = tmp_path / ".0123456789ab.tmp"                                               # `atomic.tmp_name`: a build in progress of any store
    for q in (mine, theirs, live, tmp_path / (mine.name + "x"), tmp_path / mine.name.replace(".old.tmp", ".old")):
        q.mkdir()
    file_ = tmp_path / h._aside_name(out).name
    file_.write_text("a file, not a directory")
    assert h.asides(out) == [mine] and h.asides(other) == [theirs]
    assert mine.name != theirs.name and mine.name.startswith(".") and mine.name.endswith(".tmp") and len(mine.name) == 38
    assert h._aside_name(out) != h._aside_name(out)                                     # one name per call: two writers never share one
    long = tmp_path / ("x" * 240 + ".zarr")
    assert len(h._aside_name(long).name) == 38                                          # whatever the store is called


def test_b_a_missing_directory_has_no_leftovers_and_a_file_that_goes_while_sized_is_not_counted(tmp_path, monkeypatch):
    assert h.asides(tmp_path / "no" / "such" / "gofs_x.zarr") == []                    # a store in a directory that is not there: the refusal stays
    d = tmp_path / "d"
    (d / "sub").mkdir(parents=True)
    (d / "a").write_bytes(b"x" * 1000)
    (d / "sub" / "b").write_bytes(b"y" * 2000)
    assert h._size_bytes(d) == 3000
    real = os.lstat

    def lstat(p, *a, **k):
        if str(p).endswith("b"):
            raise FileNotFoundError(p)
        return real(p, *a, **k)
    monkeypatch.setattr(os, "lstat", lstat)
    assert h._size_bytes(d) == 1000


def test_b_a_missing_store_with_a_leftover_names_it_its_size_and_how_to_put_it_back(fx, truth, tmp_path):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    left = _leftover(tmp_path, out, truth)
    shutil.rmtree(out)
    with pytest.raises(config.ConfigError) as e:
        h.open_store(out)
    msg = str(e.value)
    assert str(left) in msg and " GB)" in msg and f"mv {left} {out}" in msg and "without a download" in msg and "cannot be read" in msg
    os.replace(left, out)                                                              # the remedy it names
    assert h.open_store(out).attrs["generation"] == "old"
    lab = tmp_path / "lab_hycom.zarr"                                                  # the lab's store: 'restore from the lab's source' stays too
    left_lab = _leftover(tmp_path, lab, truth)
    shutil.rmtree(lab)
    with pytest.raises(config.ConfigError, match="lab's source") as e2:
        h.open_store(lab)
    assert str(left_lab) in str(e2.value)


def test_b_a_missing_store_with_no_leftover_and_an_unreadable_one_say_what_they_said_before(fx, truth, tmp_path):  # noqa: F811
    out = tmp_path / "gofs_x.zarr"
    (tmp_path / h._aside_name(tmp_path / "gofs_y.zarr").name).mkdir()                  # another store's leftover is not this one's
    with pytest.raises(config.ConfigError) as e:
        h.open_store(out)
    assert "BUT" not in str(e.value) and "mv " not in str(e.value) and "delete" in str(e.value)
    _store(truth, out, "old")
    (out / "zarr.json").write_text("{garbage")                                         # there, but unreadable: no leftover of a *killed* replace is offered
    h._aside_name(out).mkdir()
    with pytest.raises(config.ConfigError) as e2:
        h.open_store(out)
    assert "BUT" not in str(e2.value)


@pytest.mark.parametrize("point", ["between", "after_in"])
def test_b_a_real_kill_leaves_one_leftover_and_the_next_write_under_the_lock_deletes_it(fx, truth, tmp_path, point):  # noqa: F811
    """The two kills of the replace that leave the old store whole (batch E's three kill points: the third leaves nothing): `between` the renames and
    `after_in`. The next `write_store` of the name, holding `<name>.lock` as the ingest does, deletes it once its own store is in place."""
    import subprocess
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    nc = tmp_path / "truth.nc"
    truth.to_netcdf(nc)
    r = subprocess.run([sys.executable, "-c", _KILL, str(nc), str(out), point], cwd=remote.ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 7, r.stderr[-2000:]
    (left,) = h.asides(out)                                                            # the killed write's aside, found by the name of this store
    assert _tree(left) == old
    with remote.store_lock(tmp_path, out.name + ".lock"):                              # `pipeline._shared_store`'s hold, taken again inside by write_store
        _store(truth, out, "again")
    assert h.asides(out) == [] and h.open_store(out).attrs["generation"] == "again"
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith(".")) == sorted([out.name, out.name + ".lock", "truth.nc"])
    # (a kill between the renames also leaves the complete NEW store in the build's own `.<12 hex>.tmp`, which nothing can tell from another store's build:
    # review/orca/PROBLEMS.md, P-R18M2)


def test_b_without_the_lock_nothing_is_deleted_and_what_is_not_this_stores_stays(fx, truth, tmp_path):  # noqa: F811
    """No lock file: no proof that no other writer of the name is between its renames, so the leftover stays (the refusal names it). With the lock, only this
    store's leftover goes: the temporary of a build in progress of any store (`.<12 hex>.tmp`), another store's leftover and a file of the right name stay."""
    out, other = tmp_path / "gofs_x.zarr", tmp_path / "gofs_y.zarr"
    left = _leftover(tmp_path, out, truth)
    _store(truth, out, "again")
    assert h.asides(out) == [left] and h.open_store(out).attrs["generation"] == "again"      # no `gofs_x.zarr.lock`: not swept, and no lock file made
    assert not (tmp_path / "gofs_x.zarr.lock").exists()
    theirs, live = h._aside_name(other), tmp_path / ".0123456789ab.tmp"
    theirs.mkdir()
    live.mkdir()
    (live / "chunk").write_bytes(b"half a store being written")
    with remote.store_lock(tmp_path, out.name + ".lock"):
        _store(truth, out, "third")
    assert h.asides(out) == [] and theirs.is_dir() and (live / "chunk").read_bytes() == b"half a store being written"
    assert h.open_store(out).attrs["generation"] == "third"


def test_b_another_writer_holding_the_lock_is_waited_for_before_anything_is_replaced_or_deleted(fx, truth, tmp_path, monkeypatch):  # noqa: F811
    """The lock is how the sweep knows: while another holds `<name>.lock` (an ingest that may be between its own two renames, with its old store aside
    about to be put back) this write replaces nothing and deletes nothing."""
    out = tmp_path / "gofs_x.zarr"
    old = _store(truth, out, "old")
    left = out.with_name(h._aside_name(out).name)
    shutil.copytree(out, left)
    real, reached, done, errs = remote.store_lock, threading.Event(), threading.Event(), []

    @contextlib.contextmanager
    def spying(*a, **k):
        reached.set()
        with real(*a, **k) as held:
            yield held
    monkeypatch.setattr(remote, "store_lock", spying)

    def writer():
        try:
            _store(truth, out, "new")
        except BaseException as e:                                                     # noqa: BLE001
            errs.append(e)
        done.set()
    with real(tmp_path, out.name + ".lock"):
        t = threading.Thread(target=writer, daemon=True)
        t.start()
        assert reached.wait(120)
        assert not done.wait(3)                                                        # blocked at the lock, its new store built beside the name
        assert _tree(out) == old and left.is_dir() and h.open_store(out).attrs["generation"] == "old"
    assert done.wait(120) and errs == []
    assert h.asides(out) == [] and h.open_store(out).attrs["generation"] == "new"


# ---------------------------------------------------------------- job 2 (c): one figure for the low-antenna error band

def test_c_the_antenna_floor_comment_and_every_live_text_carry_the_measured_band_not_round_17s():
    """Round 17 wrote 12 to 16 dB at 0.1 m; the measured minimum is +11.4 (batch B, round 18 M-3): 11 to 16 dB. DECISIONS and CHANGELOG keep what was said
    when it was said (amended there); every file that states it now does not carry the old figure."""
    assert "11 to 16 dB too much loss at 0.1 m" in (ROOT / "cafe" / "pm" / "physics" / "__init__.py").read_text()
    stale = [str(p.relative_to(ROOT)) for p in sorted([*ROOT.joinpath("cafe").rglob("*.py"), *ROOT.joinpath("docs").glob("*.md"), ROOT / "README.md",
                                                       ROOT / "QUESTIONS_FOR_LAB.md", ROOT / "STATUS.md"])
             if "12 to 16 dB" in p.read_text()]
    assert stale == []
    q = (ROOT / "QUESTIONS_FOR_LAB.md").read_text()
    item = q[q.index("12d. **Low RF antennas"):]
    item = item[:item.index("\n    12b.")]
    assert "6 to 11 dB" in item and "11 to 16 dB" in item and "too high" in item and "a margin there is too low and a GO" not in item


# ---------------------------------------------------------------- job 2 (d): cafe.cfd imports the module `par` under an alias

def test_d_the_cfd_module_keeps_the_par_module_under_an_alias_and_its_own_function_par():
    from cafe.pm import par as module
    assert cfd._par is module and inspect.isfunction(cfd.par)
    assert cfd.par("x") == (f"mpirun --oversubscribe -np {cfd.NPROC} x -parallel" if cfd.NPROC > 1 else "x")
    import ast
    tree = ast.parse(inspect.getsource(cfd))
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "par"]
    assert uses == []                                                                  # a `par.<x>` would be the function, not the module


def test_d_the_alias_does_not_change_the_cfd_cache_key():
    """The import is outside every function and class and NPROC is not a setting: `_literals` (the numbers and texts of the functions, which is the whole
    of the key's code half) and `SETTINGS` are what they were with `from cafe.pm import par`, so no cached CFD result is renamed by this edit."""
    src = inspect.getsource(cfd)
    old = src.replace("from cafe.pm import par as _par ", "from cafe.pm import par ").replace("_par.env_count", "par.env_count")
    assert old != src and "from cafe.pm import par " in old and "par.env_count(" in old and "as _par" not in old
    assert cfd._literals(old) == cfd._literals(src) == cfd._code_literals()
    assert "NPROC" not in cfd.SETTINGS and "NPROC" in cfd.NOT_SETTINGS


# ---------------------------------------------------------------- job 2 (e): sprt_decide takes counts

BAD_COUNTS = [True, False, 1.5, 3.0, np.float64(2.0), np.bool_(True), np.float32(1.0), "3", None]


@pytest.mark.parametrize("bad", BAD_COUNTS, ids=repr)
def test_e_sprt_decide_refuses_a_k_that_is_not_an_integer_count(bad):
    with pytest.raises(ValueError, match="k must be an integer count"):
        Q.sprt_decide(bad, 10, 0.05, 0.15)


@pytest.mark.parametrize("bad", BAD_COUNTS, ids=repr)
def test_e_sprt_decide_refuses_an_n_that_is_not_an_integer_count(bad):
    with pytest.raises(ValueError, match="n must be an integer count"):
        Q.sprt_decide(1, bad, 0.05, 0.15)


def test_e_sprt_decide_takes_python_and_numpy_integers_and_gives_the_same_answer():
    kw = dict(p0=0.05, p1=0.15)
    want = [Q.sprt_decide(k, n, **kw) for k, n in ((0, 60), (12, 40), (1, 10), (0, 0))]
    assert want == ["accept_go", "accept_nogo", "continue", "continue"]
    for cast in (np.int64, np.int32, np.uint8):
        assert [Q.sprt_decide(cast(k), cast(n), **kw) for k, n in ((0, 60), (12, 40), (1, 10), (0, 0))] == want
    assert Q.sprt_decide(np.int64(0) + np.True_, 3, **kw) == Q.sprt_decide(1, 3, **kw)      # the sum of flags a simulation loop builds is an integer too


def test_e_sprt_decide_uses_the_helper_of_the_interval_functions(monkeypatch):
    seen = []
    monkeypatch.setattr(intervals, "_count", lambda x, name: seen.append((x, name)) or x)      # round 19, M-8: `_count` returns the count
    assert Q.sprt_decide(2, 5, 0.1, 0.4) == "continue"
    assert seen == [(2, "k"), (5, "n")]
    assert Q.intervals is intervals


# ------------------------------------------------------------ job 2 (f): the report lines of an outcome no input acts on, and of a USV that fails by battery

NAMES = ["wind_speed_bias", "wind_direction_bias", "current_speed_scale", "current_direction_bias", "hs_scale", "tp_bias", "usv_vpp_bias", "solar_yield_scale"]


@pytest.fixture(autouse=True)
def _no_stored_receipts(tmp_path, monkeypatch):
    """As tests/test_report.py: the credibility page reads CAFE_DATA and the receipts table, which must not be the real ones."""
    monkeypatch.setenv("CAFE_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(report, "RECEIPTS", tmp_path / "model_receipts.json")


def plain(h):
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<a class=lk[^>]*>[LR]</a>", "", h)))


def _page(run, edit):
    """A synthetic run (tests/fixtures/pm_run.py) whose stage-1b summary is edited by `edit` and the report written from it: (report.json, index.html)."""
    run.mkdir(parents=True)
    m, plan = pm_run.make_run(run)
    p = run / "stage1b" / "summary.json"
    d = json.loads(p.read_text())
    edit(d["summary"])
    p.write_text(json.dumps(d))
    report.write(run, m, plan)
    return json.loads((run / "report" / "report.json").read_text()), (run / "report" / "index.html").read_text()


def test_f_a_link_that_no_input_acts_on_prints_why_it_has_no_top_sensitivities(tmp_path):
    rng = np.random.default_rng(3)
    U = rng.random((48, len(NAMES)))
    f = rng.random(48) < 0.3
    sens = stage1._sensitivity(NAMES, U, f, set(), np.where(f, 0.2, 0.9), "fraction of the required moments the link worked")
    assert sens["case"] == "no_acting_input" and sens["S1"] == {} and sens["noise_floor"] is None

    def edit(s):
        s["links"]["usv-shore-iridium"]["sensitivity"] = sens
    rep, h = _page(tmp_path / "run", edit)
    k = rep["links"]["usv-shore-iridium"]
    assert k["sensitivity"]["case"] == "no_acting_input" and k["top3"] == [] and k["sensitivity"]["noise_floor"] is None
    t = plain(h)
    assert "No sampled input can act on the fraction of the required moments the link worked, so none is ranked" in t
    assert "Top sensitivities: none, because no sampled input acts on this outcome (it is decided by a draw of its own), so no noise floor was computed." in t
    card = t[t.index("usv-shore-iridium "):]
    assert "none above the noise floor" not in card.split("Top sensitivities:")[1][:200]
    assert report.check_rendered(rep, h) == []
    assert report._top3_html([], None, "x", "all_pass").startswith("<p class=muted>Top sensitivities: none above the noise floor")     # the other cases keep it


def test_f_a_usv_that_runs_out_of_charge_is_told_by_its_state_of_charge_not_its_cross_track_error(tmp_path):
    rng = np.random.default_rng(5)
    n = 48
    U = rng.random((n, len(NAMES)))
    soc = 0.55 - 0.5 * U[:, NAMES.index("solar_yield_scale")]                         # the charge follows the solar yield; the track error follows the steering
    xte = 800.0 + 600.0 * U[:, NAMES.index("usv_vpp_bias")]
    f = soc < 0.12
    r = {"class": "usv", "margin": xte, "energy_margin": soc}
    sens = stage1._sensitivity(NAMES, U, f, *stage1._ranked(r, "battery"))
    assert sens["case"] == "ranked" and sens["param"] == "solar_yield_scale" and sens["quantity"].startswith("lowest state of charge")

    def edit(s):
        v = s["vehicles"]["usv"]
        v["sensitivity"], v["dominant"], v["modes"] = sens, "battery", {"battery": int(f.sum())}
    rep, h = _page(tmp_path / "run", edit)
    t = plain(h)
    most = re.search(r"Most sensitive to: (solar_yield_scale has the largest first-order index \(S1 [0-9.]+\) for the lowest state of charge "
                     r"\(fraction of the pack\), above the [0-9.]+ that unrelated outcomes reach at this member count)", t)
    assert most and "cross-track" not in most.group(1)
    top = re.search(r"Top sensitivities \(Sobol first-order, share of the variance of (.*?), above the permutation noise floor\): solar_yield_scale", t)
    assert top and top.group(1) == "the lowest state of charge (fraction of the pack)"
    assert report.check_rendered(rep, h) == []


# ------------------------------------------------------------ job 2 (g): the hull reader names the file, the line and the grammar, and reads the shipped file

def test_g_the_hull_reader_returns_the_shipped_value_of_the_shipped_file():
    shipped = yaml.safe_load(fea.ASSUMPTIONS.read_text())["stage3.fea_elements_along"]["value"]
    assert fea.hull_elements_along() == shipped == 70 and fea.ASSUMPTIONS == ROOT / "config" / "assumptions.yaml"


@pytest.mark.parametrize("text,line,words", [
    ("# a\n# b\n\tx: 1\nstage3.fea_elements_along:\n  value: 70\n", 3, ("printable characters", "tab")),                  # a character outside the grammar
    ("stage3.fea_elements_along:\n  value: 70\n  unit: x\x0c\n", 3, ("printable characters",)),
    ("stage3.fea_elements_along:\n  value: 70\n  unit: x\n    deeper: 1\n", 4, ("indented 4 spaces", "indented by two spaces")),   # deeper than a child
    ("stage3.fea_elements_along:\n  value: {a: 1}\n", 2, ("outside the grammar", "one-line text", "block scalar")),             # a flow mapping
    ("stage3.fea_elements_along:\n  value: 70\nother:\n  - a\n", 4, ("outside the grammar", "`key:` and `  name: one-line text`")),    # a list item
])
def test_g_a_layout_outside_the_grammar_is_refused_naming_the_file_the_line_and_what_is_allowed(tmp_path, monkeypatch, text, line, words):
    p = tmp_path / "assumptions.yaml"
    p.write_text(text)
    monkeypatch.setattr(fea, "ASSUMPTIONS", p)
    with pytest.raises(ValueError) as e:
        fea.hull_elements_along()
    msg = str(e.value)
    assert str(p) in msg and f"line {line}" in msg, msg
    for w in words:
        assert w in msg, (w, msg)


def test_g_a_hull_reader_refusal_of_a_file_pyyaml_reads_is_the_stated_trade_off(tmp_path, monkeypatch):
    """The closed grammar refuses a layout PyYAML accepts (a block scalar after another key): the message says which line and why, so a lab edit of another
    entry is not a silent change of the Hangar's mesh."""
    p = tmp_path / "assumptions.yaml"
    p.write_text("stage3.fea_elements_along:\n  value: 70\nother:\n  why: >\n    folded text\n")
    assert yaml.safe_load(p.read_text())["stage3.fea_elements_along"]["value"] == 70
    monkeypatch.setattr(fea, "ASSUMPTIONS", p)
    with pytest.raises(ValueError, match=r"line 4, '  why: >', is outside the grammar"):
        fea.hull_elements_along()
