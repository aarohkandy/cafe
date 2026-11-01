"""cafe.pm.par: stage 1 on several worker processes gives the same members and the same bits as on one."""
import pathlib
import pickle

import numpy as np

from cafe.pm import config, par, pipeline, stage1
from cafe.pm.env import subgrid
from cafe.pm.stats import intervals

MISSION = config.load_mission(config.ROOT / "missions" / "ci_fixture.yaml")


def same(a, b, path="res"):
    """Assert a == b all the way down (arrays bit for bit, NaN equal to NaN); wall times are timings, not results."""
    if isinstance(a, dict):
        assert list(a) == list(b), path
        for k in a:
            if k != "wall_s":
                same(a[k], b[k], f"{path}[{k!r}]")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            same(x, y, f"{path}[{i}]")
    elif isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        assert np.array_equal(np.asarray(a), np.asarray(b), equal_nan=np.asarray(a).dtype.kind in "fc"), path
    elif isinstance(a, float) and np.isnan(a):
        assert isinstance(b, float) and np.isnan(b), path
    else:
        assert a == b, path


def test_stage1_on_two_workers_is_the_same_bits_as_on_one(ci_full, monkeypatch):
    """Every glider, USV and UAS sortie of a batch is a task, and the n_min wave runs two batches at once from two threads; the result, the
    members, the random-stream seeds and the 3-D wind counts equal the one-process run's."""
    plan = dict(batch=4, n_min=8, n_max=8)
    with ci_full.lenient():
        one = stage1.run(MISSION, ci_full, plan, log=lambda *_: None)
        monkeypatch.setenv("CAFE_WORKERS", "2")
        two = stage1.run(MISSION, ci_full, plan, log=lambda *_: None)
    assert par._dir is not None and any(pathlib.Path(p).exists() for _, p in par._shared.values())   # the workers read shared files
    assert one["n"] == two["n"] == 8
    same(one["res"], two["res"])
    for r in (one, two):
        for v in r["res"]["vehicles"].values():
            v.pop("wall_s", None)
    assert pipeline.res_bytes(one["res"]) == pipeline.res_bytes(two["res"])          # res.pkl, hashed into the report's receipts, too
    assert pickle.loads(pipeline.res_bytes(one["res"])).keys() == one["res"].keys()
    same(one["summary"], two["summary"], "summary")


def test_a_wave_is_what_n_min_needs_or_what_fills_the_workers():
    assert stage1.wave(0, 32, 32, 64, 1, 9) == 1
    assert stage1.wave(0, 4, 8, 8, 1, 9) == 2                          # n_min needs both whatever the stopping rule says
    assert stage1.wave(0, 32, 32, 512, 32, 8) == 4                     # 32 workers, 8 tasks a batch
    assert stage1.wave(480, 32, 73, 512, 32, 8) == 1                   # never past n_max
    assert stage1.wave(0, 32, 32, 64, 8, 0) == 2


def test_workers_is_the_environment_override_or_the_cpus_and_one_inside_a_pool(monkeypatch):
    monkeypatch.setenv("CAFE_WORKERS", "3")
    assert par.workers() == 3
    monkeypatch.delenv("CAFE_WORKERS")
    assert 1 <= par.workers() <= len(__import__("os").sched_getaffinity(0))
    monkeypatch.setattr(par, "_in_worker", True)
    assert par.workers() == 1
    with par.Pool(4):
        assert par.width() == 1                                        # a worker never fans out again


def test_a_task_sees_the_module_state_the_parent_set(monkeypatch):
    """A spawned worker starts from the shipped sub-grid calibration and verdict cut-offs; stage 1b runs with the run's own calibration."""
    monkeypatch.setattr(subgrid, "_RUN_CAL", {"from": "the run"})
    monkeypatch.setattr(intervals, "P_FAIL_GO", 0.05)
    with par.Pool(2):
        cfg = par.submit(subgrid.load_config).result()
        there = par.submit(par.state).result()
    assert cfg["calibration"] == {"from": "the run"} and there == par.state() and there[1] == 0.05


def test_an_adopted_object_holds_its_large_arrays_once_as_shared_read_only_maps(monkeypatch):
    """The parent's environment becomes the maps its workers read (one copy in memory), and a map travels as its file name, not its bytes."""
    monkeypatch.setenv("CAFE_WORKERS", "2")
    big, small = np.arange(par.SHARE_MIN_BYTES // 8 + 1, dtype=float), np.arange(3.0)
    got = par.adopt(dict(big=big, small=small))
    assert isinstance(got["big"], np.memmap) and np.array_equal(got["big"], big) and type(got["small"]) is np.ndarray
    assert not got["big"].flags.writeable
    assert len(par.dumps(got)) < 1000 < big.nbytes
    del big
    assert pathlib.Path(got["big"].filename).exists()                  # the original is gone; its file stays while a map reads it
    monkeypatch.setenv("CAFE_WORKERS", "1")
    assert par.adopt(small) is small


def test_a_task_runs_from_its_pickle_and_an_inline_task_keeps_its_exception(monkeypatch):
    """What a worker does with a task (here, in this process, where coverage sees it), and the inline path's error, raised where a pool's is."""
    assert par._run(par.dumps((par.state(), sum, ([1, 2],)))) == 3
    monkeypatch.setattr(par, "_in_worker", False)
    par._init()
    assert par._in_worker and par.workers() == 1
    monkeypatch.setattr(par, "_in_worker", False)
    f = par.submit(int, "not a number")
    assert f.done() and isinstance(f.exception(), ValueError)
