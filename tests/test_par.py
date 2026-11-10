"""cafe.pm.par: stage 1 on several worker processes gives the same members and the same bits as on one."""
import contextlib
import functools
import gc
import itertools
import os
import pathlib
import pickle
import signal
import subprocess
import sys
import textwrap
import threading
import time
import types

import numpy as np
import pytest

from cafe.pm import budget, config, par, pipeline, stage1
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
        written = []
        real = par._share
        monkeypatch.setattr(par, "_share", lambda a: written.append(real(a)) or written[-1])
        two = stage1.run(MISSION, ci_full, plan, log=lambda *_: None)
    assert written                                                      # the workers read the environment from shared files
    assert one["n"] == two["n"] == 8
    same(one["res"], two["res"])
    for r in (one, two):
        for v in r["res"]["vehicles"].values():
            v.pop("wall_s", None)
    assert pipeline.res_bytes(one["res"]) == pipeline.res_bytes(two["res"])          # res.pkl, hashed into the report's receipts, too
    assert pickle.loads(pipeline.res_bytes(one["res"])).keys() == one["res"].keys()
    same(one["summary"], two["summary"], "summary")


def test_a_wave_is_what_n_min_needs_or_what_fills_the_workers():
    assert stage1.wave(0, 32, 32, 64, 1) == 1
    assert stage1.wave(0, 4, 8, 8, 1) == 2                             # n_min needs both whatever the stopping rule says
    assert stage1.wave(0, 32, 32, 512, 4) == 4
    assert stage1.wave(480, 32, 73, 512, 4) == 1                       # never past n_max


def test_a_batch_of_uneven_tasks_keeps_work_over_its_longest_task_workers_busy():
    """8 workers ran one 9-task demo batch at a time (8 // 9), with half of them idle: its tasks are uneven (100 s of work, a 27 s USV), so a batch
    keeps about 3.7 workers busy and 8 workers take 2 batches; without costs the plan falls back to one batch per `tasks` workers."""
    cost = dict(glider_eq=(3.0, 0.0), glider_2n=(3.0, 0.0), usv=(4.5, 0.0), uas=(6.0, 0.0))           # s per batch-day: 18, 18, 27, 36 s over 6 days
    plan = dict(batch=32, days=6.0, workers=8, tasks=dict(glider_eq=1, glider_2n=1, usv=1, uas=6),
                member_cost={k: dict(s_per_batch_day=a, s_per_member_day=b) for k, (a, b) in cost.items()})
    assert budget.batches_at_once(plan) == 2 and budget.batches_at_once(dict(plan, workers=4)) == 1
    assert budget.batches_at_once(dict(plan, workers=32)) == 8 and budget.batches_at_once(dict(plan, workers=1)) == 1
    assert budget.batches_at_once(dict(workers=32, tasks=plan["tasks"])) == 3


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
    assert len(par.dumps(got)) < 1000 < big.nbytes and len(par.dumps(big)) > big.nbytes          # a task sends a map by name, an array by value
    del big
    assert pathlib.Path(got["big"].filename).exists()                  # the original is gone; its file stays while a map reads it
    monkeypatch.setenv("CAFE_WORKERS", "1")
    assert par.adopt(small) is small


def test_a_task_blob_maps_an_adopted_file_again_without_counting_it_and_the_file_outlives_that_map(monkeypatch):
    """A worker unpickles a task's adopted map with `_mapped`: the same file, read-only, not a reference the parent's `_release` waits for."""
    monkeypatch.setenv("CAFE_WORKERS", "2")
    big = np.arange(par.SHARE_MIN_BYTES // 8 + 1, dtype=float)
    got = par.adopt(dict(big=big))
    path, refs = got["big"].filename, dict(par._refs)
    back = pickle.loads(par.dumps(got))
    assert isinstance(back["big"], np.memmap) and back["big"].filename == path and np.array_equal(back["big"], big) and not back["big"].flags.writeable
    assert par._refs == refs                                           # only `_owned` (a parent's map) counts
    del back
    gc.collect()
    assert pathlib.Path(path).exists() and par._refs == refs           # the file goes with the last parent's map, not with a worker's



def test_a_shared_file_name_is_never_reused_when_an_array_id_is(monkeypatch):
    """The name came from len(_shared): an array that died and whose id a new array got kept the entry count, so the new array was written over
    the old one's file while a queued task still named it (an 8-worker q4 batch read a wrong environment, 0.66 degrees off from the first record)."""
    monkeypatch.setenv("CAFE_WORKERS", "2")
    names, maps = set(), []
    for _ in range(5):
        a = np.full(par.SHARE_MIN_BYTES // 8 + 1, float(len(names)))
        maps.append(par.adopt(a))
        names.add(maps[-1].filename)
        del a                                                           # its id is free for the next array
    assert len(names) == 5 and [m[0] for m in maps] == [0.0, 1.0, 2.0, 3.0, 4.0]       # each map still reads its own values


def test_a_shared_file_goes_with_the_parents_map_of_it(monkeypatch):
    """The ingest stage rebuilds the environment up to three times; each adopted copy kept its 9 GB of files until exit and /dev/shm filled."""
    monkeypatch.setenv("CAFE_WORKERS", "2")
    m = par.adopt(np.zeros(par.SHARE_MIN_BYTES // 8 + 1))
    f = pathlib.Path(m.filename)
    view = m[1:]
    del m
    assert f.exists() and view.sum() == 0.0                             # a view keeps its map, and so the file
    del view
    gc.collect()
    assert not f.exists()



def test_a_file_lives_while_any_adopted_map_of_it_does(monkeypatch):
    """The ocean adopts each field as it reads it, then the environment adopts the ocean: its maps re-map the same files. The ingest stage drops
    the first environment, whose field maps took the files with them while the adopted copy still named them (FileNotFoundError in a worker)."""
    monkeypatch.setenv("CAFE_WORKERS", "2")
    first = par.adopt(np.arange(par.SHARE_MIN_BYTES // 8 + 1, dtype=float))
    holder = par.adopt(dict(field=first))
    f = pathlib.Path(first.filename)
    assert holder["field"].filename == first.filename
    del first
    gc.collect()
    assert f.exists()
    with par.Pool(2):
        assert par.submit(np.sum, holder["field"]).result() == np.sum(np.arange(par.SHARE_MIN_BYTES // 8 + 1, dtype=float))
    del holder
    gc.collect()
    assert not f.exists()


def test_a_task_runs_from_its_pickle_and_an_inline_task_keeps_its_exception(monkeypatch):
    """What a worker does with a task (here, in this process, where coverage sees it), and the inline path's error, raised where a pool's is."""
    assert par._run(par.dumps((par.state(), sum, ([1, 2],)))) == 3
    monkeypatch.setattr(par, "_in_worker", False)
    par._init()
    assert par._in_worker and par.workers() == 1
    monkeypatch.setattr(par, "_in_worker", False)
    f = par.submit(int, "not a number")
    assert f.done() and isinstance(f.exception(), ValueError)


def test_a_process_multiprocessing_started_is_a_worker_before_its_initializer_runs():
    """A spawned child re-imports the parent's main script; without a main guard it would otherwise build, adopt and share its own environment."""
    with par.Pool(2):
        assert par.submit(par.workers).result() == 1
    assert par.workers() >= 1 and not par._child()


# ---------------------------------------------------------------------------------------------------------------- round 5: M-21, M-23, M-6

def fake_files(monkeypatch, files):
    """pathlib.Path.read_text answers `files[path]` (an exception is raised) for the named paths and reads the real file for every other."""
    real = pathlib.Path.read_text

    def read_text(self, *a, **k):
        if str(self) in files:
            if isinstance(files[str(self)], Exception):
                raise files[str(self)]
            return files[str(self)]
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)


CPU_MAX = "/sys/fs/cgroup/cpu.max"


@pytest.mark.parametrize("quota,want", [("200000 100000", 2), ("150000 100000", 1), ("50000 100000", 1), ("max 100000", 8), ("800000 100000", 8),
                                        ("1600000 100000", 8)])
def test_the_cgroup_quota_cuts_the_cpus_of_the_affinity_mask(monkeypatch, quota, want):
    """M-23: `docker --cpus 2` on an 8-CPU box is 2 workers; `quota // period` turned into `quota * period` gave 8 here and the old test still passed."""
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par.os, "sched_getaffinity", lambda pid: set(range(8)))
    fake_files(monkeypatch, {CPU_MAX: quota})
    assert par.workers() == want


@pytest.mark.parametrize("quota", [OSError("no cgroup v2"), "garbage", ""])
def test_without_a_readable_cgroup_quota_every_cpu_of_the_mask_is_a_worker(monkeypatch, quota):
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par.os, "sched_getaffinity", lambda pid: set(range(8)))
    fake_files(monkeypatch, {CPU_MAX: quota})
    assert par.workers() == 8


@pytest.mark.parametrize("v", ["abc", "2.5", "1e1", "0", "-3", " "])
def test_a_bad_cafe_workers_is_a_config_error_and_not_a_traceback_or_a_silent_one(monkeypatch, v):
    """M-21: `int("abc")` was a bare ValueError out of Context, and 0 or -3 became 1 without a word."""
    monkeypatch.setenv("CAFE_WORKERS", v)
    with pytest.raises(config.ConfigError, match=r"CAFE_WORKERS=.* is not a whole number of at least 1; set CAFE_WORKERS=N or unset it"):
        par.workers()
    monkeypatch.setenv("CAFE_WORKERS", "3")
    assert par.workers() == 3
    monkeypatch.setenv("CAFE_WORKERS", "")
    assert par.workers() >= 1                                                         # empty is unset


def test_the_limit_of_a_run_cuts_the_workers_inside_its_block_only(monkeypatch):
    monkeypatch.setenv("CAFE_WORKERS", "5")
    with par.limit(2):
        assert par.workers() == 2
        with par.limit(9):
            assert par.workers() == 5
        assert par.workers() == 2
    assert par.workers() == 5


def test_memory_is_the_cgroup_limit_else_what_the_host_has_available_else_unknown(monkeypatch):
    v2, v1, info = "/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes", "/proc/meminfo"
    meminfo = "MemTotal:       65000000 kB\nMemAvailable:   16777216 kB\nSwapTotal: 0 kB\n"
    fake_files(monkeypatch, {v2: "28000000000\n", v1: OSError(), info: meminfo})
    assert par.memory_gb() == pytest.approx(28.0)
    fake_files(monkeypatch, {v2: "max\n", v1: OSError(), info: meminfo})
    assert par.memory_gb() == pytest.approx(16777216 * 1024 / 1e9)
    fake_files(monkeypatch, {v2: OSError(), v1: str(2 ** 63 - 4096), info: meminfo})                   # cgroup v1 spells unlimited as a huge number
    assert par.memory_gb() == pytest.approx(16777216 * 1024 / 1e9)
    fake_files(monkeypatch, {v2: OSError(), v1: "8589934592", info: meminfo})
    assert par.memory_gb() == pytest.approx(8.589934592)
    for bad in (OSError(), "MemTotal: 1 kB\n", "MemAvailable:\n"):
        fake_files(monkeypatch, {v2: OSError(), v1: OSError(), info: bad})
        assert par.memory_gb() is None


def test_a_cgroup_limit_above_the_machines_memory_is_cut_to_it_and_the_plan_follows(monkeypatch):
    """Round 9 P-5: on orca the cgroup says 256 GiB (274.9 GB) on a machine of 251.6 GiB (270.2 GB), and `workers_by_memory` was 295."""
    v2, v1, info = "/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes", "/proc/meminfo"
    total = 263817216                                                                                   # kB
    fake_files(monkeypatch, {v2: "274877906944\n", v1: OSError(), info: f"MemTotal:       {total} kB\nMemAvailable:   200000000 kB\n"})
    assert par.memory_gb() == pytest.approx(total * 1024 / 1e9) and par.memory_gb() < 274.9
    from cafe.pm import budget
    mission = dict(window=dict(start="2023-03-01T12:00:00Z", end="2023-03-07T12:00:00Z"))
    here = budget.plan("quick", 0, mission, thr={}, mem_gb=par.memory_gb(), env_gb=9.0)["workers_by_memory"]
    cgroup = budget.plan("quick", 0, mission, thr={}, mem_gb=274.877906944, env_gb=9.0)["workers_by_memory"]
    assert here == int((total * 1024 / 1e9 - 9.0) // budget.WORKER_GB) and here < cgroup
    fake_files(monkeypatch, {v2: "274877906944\n", v1: OSError(), info: OSError()})                     # no MemTotal to cut it to: the limit stands
    assert par.memory_gb() == pytest.approx(274.877906944)
    fake_files(monkeypatch, {v2: OSError(), v1: "8589934592", info: f"MemTotal:       {total} kB\n"})      # a limit below the machine's memory is the limit
    assert par.memory_gb() == pytest.approx(8.589934592)


def test_a_full_directory_is_a_named_error_and_not_a_bare_errno_28(monkeypatch, tmp_path):
    """M-6: SHM_MIN_FREE was looked at once, for the first file; a long window filled /dev/shm part-way through the later arrays."""
    monkeypatch.setattr(par, "_dir", tmp_path)
    monkeypatch.setattr(par, "_names", itertools.count(7))
    monkeypatch.setattr(par.shutil, "disk_usage", lambda d: types.SimpleNamespace(free=10))
    a = np.zeros(100)
    with pytest.raises(config.ResourceError, match=rf"{tmp_path} is full after 7 arrays: raise --shm-size \(RUNBOOK 1\) or free the disk") as e:
        par._share(a)
    back = pickle.loads(pickle.dumps(e.value))                                                          # a worker's error crosses the process boundary
    assert isinstance(e.value, OSError) and type(back) is config.ResourceError and str(back) == str(e.value)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(par.shutil, "disk_usage", lambda d: types.SimpleNamespace(free=a.nbytes))
    assert pathlib.Path(par._share(a)).name == "8.npy"                                                  # exactly enough room is enough


def test_env_count_is_a_whole_number_of_at_least_one_or_a_config_error_naming_the_variable(monkeypatch):
    """M-23: CAFE_NPROC was `int()` of the string (a letter was a traceback, 0 and -3 were accepted); CAFE_WORKERS had the check, now shared."""
    monkeypatch.delenv("CAFE_X", raising=False)
    assert par.env_count("CAFE_X") is None
    monkeypatch.setenv("CAFE_X", "")
    assert par.env_count("CAFE_X") is None
    monkeypatch.setenv("CAFE_X", "4")
    assert par.env_count("CAFE_X") == 4
    for bad in ("abc", "0", "-3", "2.5"):
        monkeypatch.setenv("CAFE_X", bad)
        with pytest.raises(config.ConfigError, match=rf"CAFE_X='{bad}' is not a whole number of at least 1; set CAFE_X=N or unset it"):
            par.env_count("CAFE_X")
    monkeypatch.setenv("CAFE_WORKERS", "0")
    with pytest.raises(config.ConfigError, match="CAFE_WORKERS='0' is not a whole number of at least 1; set CAFE_WORKERS=N or unset it"):
        par.workers()


def test_resize_lowers_the_limit_and_the_width_of_a_pool_that_has_not_started(monkeypatch):
    """M-2: the plan made again after the ingest may allow fewer workers than the pool was opened for."""
    monkeypatch.setattr(par, "_limit", None)
    monkeypatch.setenv("CAFE_WORKERS", "8")
    with par.Pool(8) as pool:
        par.resize(3)
        assert par.workers() == 3 and pool.n == 3
        pool.ex = object()                                                                                       # processes already started: the width stays
        par.resize(2)
        assert par.workers() == 2 and pool.n == 3
        pool.ex = None
    par.resize(5)                                                                                                # no active pool: only the limit
    assert par.workers() == 5


@pytest.mark.parametrize("files,want", [({"cpu/cpu.cfs_quota_us": "800000", "cpu/cpu.cfs_period_us": "100000"}, 8),
                                       ({"cpu/cpu.cfs_quota_us": "150000", "cpu/cpu.cfs_period_us": "100000"}, 1),
                                       ({"cpu/cpu.cfs_quota_us": "50000", "cpu/cpu.cfs_period_us": "100000"}, 1),     # --cpus 0.5: 1, not 0 (round 13, M-37)
                                       ({"cpu/cpu.cfs_quota_us": "-1", "cpu/cpu.cfs_period_us": "100000"}, 64),
                                       ({"cpu.max": "200000 100000", "cpu/cpu.cfs_quota_us": "800000", "cpu/cpu.cfs_period_us": "100000"}, 2),
                                       ({"cpu.max": "max 100000"}, 64), ({"cpu/cpu.cfs_quota_us": "x", "cpu/cpu.cfs_period_us": "100000"}, 64),
                                       ({"cpu/cpu.cfs_quota_us": "800000", "cpu/cpu.cfs_period_us": "0"}, 64), ({}, 64)])
def test_the_cgroup_v1_cpu_quota_cuts_the_cpus_like_the_v2_one_does(monkeypatch, tmp_path, files, want):
    """Round 7 M-37: on a cgroup-v1 host `docker --cpus 8` left `workers()` at every CPU of the host (64 here); `memory_gb` already read v1."""
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text + "\n")
    monkeypatch.delenv("CAFE_WORKERS")
    monkeypatch.setattr(par.os, "sched_getaffinity", lambda pid: set(range(64)))
    monkeypatch.setattr(par, "_cgroup_cpus", functools.partial(par._cgroup_cpus, str(tmp_path)))
    assert par.workers() == want


def test_r13_m26_a_queued_tasks_adopted_files_live_until_its_result_is_back(monkeypatch):
    """The docstring said a queued task's maps stay alive in the parent, but `Pool.submit` kept only the pickle, which names the files: `del a` and a
    collection unlinked them before the worker (busy with two slow tasks) opened them, and `result()` raised FileNotFoundError."""
    import time
    monkeypatch.setenv("CAFE_WORKERS", "2")
    a = par.adopt(np.ones(par.SHARE_MIN_BYTES // 8 + 1))
    f = pathlib.Path(a.filename)
    with par.Pool(2) as pool:
        busy = [par.submit(time.sleep, 1.5), par.submit(time.sleep, 1.5)]
        fut = par.submit(np.sum, a)                                  # queued behind the two sleeps
        del a
        gc.collect()
        assert f.exists() and fut in pool.held                      # the task is queued or running: its arguments are held
        assert fut.result() == par.SHARE_MIN_BYTES // 8 + 1
        for b in busy:
            b.result()
    assert not pool.held                                             # released when the futures were done
    gc.collect()
    assert not f.exists()


# ---------------------------------------------------------------------------------------------------------------- round 14, M-25
@pytest.fixture
def private_dirs(tmp_path, monkeypatch):
    """`_share` makes its directory under tmp_path (never /dev/shm), forgets the one this process made, and the signal handlers it installs are put back."""
    monkeypatch.setattr(par.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(par, "SHM", tmp_path / "no_shm")
    monkeypatch.setattr(par, "SHM_MIN_FREE", 1 << 62)                                               # so the temporary directory is the one chosen
    monkeypatch.setattr(par, "_dir", None)
    monkeypatch.setattr(par.atexit, "register", lambda *a, **k: None)
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGHUP)}
    yield tmp_path
    for s, h in saved.items():
        signal.signal(s, h)


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def leftover(base, pid, name="abc123", files=2):
    d = base / f"cafe-share-{pid}-{name}"
    d.mkdir()
    for i in range(files):
        (d / f"{i}.npy").write_bytes(b"x" * 10)
    return d


def test_r14_m25_the_next_run_removes_the_directories_a_dead_run_of_this_user_left(private_dirs):
    """A SIGKILL runs no atexit: five killed runs left five `cafe-share-<pid>-*` directories, in /dev/shm each the size of the environment."""
    dead1, dead2 = leftover(private_dirs, dead_pid()), leftover(private_dirs, dead_pid(), "zz_9")
    mine, parent = leftover(private_dirs, os.getpid()), leftover(private_dirs, os.getppid())          # alive: stay
    (private_dirs / "no_shm").mkdir()
    in_shm = leftover(private_dirs / "no_shm", dead_pid())                                          # the other place a run may have chosen
    file_named_so, no_pid = private_dirs / f"cafe-share-{dead_pid()}-f", leftover(private_dirs, "abc", "x")
    file_named_so.write_text("a file")
    link = private_dirs / f"cafe-share-{dead_pid()}-link"
    link.symlink_to(mine)                                                                           # a link is not followed and not removed
    path = par._share(np.arange(3.0))
    assert [d.exists() for d in (dead1, dead2, in_shm)] == [False] * 3
    assert [d.exists() for d in (mine, parent, no_pid)] == [True] * 3 and file_named_so.exists() and link.is_symlink() and (mine / "0.npy").exists()
    assert pathlib.Path(path).parent.parent == private_dirs and pathlib.Path(path).parent.name.startswith(f"cafe-share-{os.getpid()}-")
    assert np.array_equal(np.load(path), np.arange(3.0))
    again = leftover(private_dirs, dead_pid(), "later")
    par._share(np.arange(3.0))                                                                      # only the first `_share` of a process sweeps
    assert again.exists()


def test_r14_m25_a_directory_of_another_user_is_never_removed(private_dirs, monkeypatch):
    d = leftover(private_dirs, dead_pid())
    monkeypatch.setattr(par.os, "getuid", lambda: d.stat().st_uid + 1)
    par._sweep(private_dirs)
    assert d.exists()
    monkeypatch.undo()
    par._sweep(private_dirs)
    assert not d.exists()


def test_r14_m25_a_missing_directory_or_one_that_vanishes_during_the_sweep_is_not_an_error(tmp_path):
    par._sweep(tmp_path / "nothing here")                                                          # no /dev/shm on this machine
    def vanished():
        raise FileNotFoundError(2, "gone")
    gone = types.SimpleNamespace(name=f"cafe-share-{dead_pid()}-x", lstat=vanished)
    par._sweep(types.SimpleNamespace(is_dir=lambda: True, glob=lambda pattern: [gone]))            # removed by its owner between the listing and the look


def test_r14_m25_a_pid_that_is_alive_for_another_user_or_unreadable_is_alive(monkeypatch):
    assert par._dead(dead_pid()) and not par._dead(os.getpid()) and not par._dead(1 << 70)

    def refuse(pid, sig):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(par.os, "kill", refuse)
    assert not par._dead(1)


def test_r14_m25_the_handlers_are_installed_only_where_nobody_has_set_one_and_only_from_the_main_thread(private_dirs):
    for s in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, signal.SIG_DFL)
    t = threading.Thread(target=par._clean_on_signals)
    t.start()
    t.join()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL                                     # signal.signal only works in the main thread: try again later
    par._clean_on_signals()
    assert signal.getsignal(signal.SIGTERM) is par._on_signal and signal.getsignal(signal.SIGHUP) is par._on_signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    mine = lambda *a: None                                                                         # noqa: E731
    signal.signal(signal.SIGHUP, mine)
    par._clean_on_signals()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_IGN and signal.getsignal(signal.SIGHUP) is mine       # an ignore (nohup) or a handler stays theirs


def test_r14_m25_the_handler_removes_the_directory_and_then_dies_of_the_signal_as_the_default_would(private_dirs, monkeypatch):
    d = leftover(private_dirs, os.getpid())
    sent = []
    monkeypatch.setattr(par, "_dir", d)
    monkeypatch.setattr(par.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    par._on_signal(signal.SIGTERM, None)
    assert not d.exists() and sent == [(os.getpid(), signal.SIGTERM)] and signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
    monkeypatch.setattr(par, "_dir", None)
    par._on_signal(signal.SIGHUP, None)                                                            # before any array was shared: nothing to remove
    assert sent[-1] == (os.getpid(), signal.SIGHUP) and signal.getsignal(signal.SIGHUP) is signal.SIG_DFL


ADOPT = textwrap.dedent("""
    import os, pathlib, signal, sys, tempfile, time
    import numpy as np
    from cafe.pm import par
    tempfile.tempdir, par.SHM = sys.argv[1], pathlib.Path(sys.argv[1]) / "no_shm"
    os.environ["CAFE_WORKERS"] = "2"
    if sys.argv[2] == "ignore":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if sys.argv[2] == "own":
        signal.signal(signal.SIGTERM, lambda *a: os._exit(3))
    m = par.adopt(np.zeros(par.SHARE_MIN_BYTES // 8 + 1))
    print(m.filename, flush=True)
    time.sleep(60)
""")


def run_adopter(tmp_path, how):
    p = subprocess.Popen([sys.executable, "-c", ADOPT, str(tmp_path), how], stdout=subprocess.PIPE, text=True, cwd=config.ROOT,
                         env=dict(os.environ, PYTHONPATH=str(config.ROOT)))
    try:
        return p, pathlib.Path(p.stdout.readline().strip()).parent
    except BaseException:
        p.kill()
        raise


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP])
def test_r14_m25_a_terminated_run_leaves_no_shared_directory_and_dies_of_the_signal(tmp_path, sig):
    """SIGTERM ran no atexit either: the directory stayed."""
    p, d = run_adopter(tmp_path, "default")
    try:
        assert d.is_dir() and d.parent == tmp_path and any(d.iterdir())
        p.send_signal(sig)
        assert p.wait(timeout=60) == -sig                                                           # killed by the signal, not an exit code
        assert not d.exists()
    finally:
        p.kill()
        p.wait()


@pytest.mark.parametrize("how, code", [("ignore", None), ("own", 3)])
def test_r14_m25_a_signal_disposition_the_program_set_is_left_alone(tmp_path, how, code):
    """The SITL and watchdog handling of TERM is not ours to take over: with an ignore or a handler set before the first share, nothing is installed."""
    p, d = run_adopter(tmp_path, how)
    try:
        p.send_signal(signal.SIGTERM)
        if code is None:
            time.sleep(2)
            assert p.poll() is None                                                                 # ignored, as it asked
        else:
            assert p.wait(timeout=60) == code                                                       # its handler ran, not ours
        assert d.is_dir()
    finally:
        p.kill()
        p.wait()


BEAT = textwrap.dedent("""
    import os, pathlib, sys, time
    from cafe.pm import par

    def beat(path):
        pathlib.Path(path + ".pid").write_text(str(os.getpid()))
        for _ in range(300):                      # at most a minute of task
            pathlib.Path(path).write_text(str(time.time()))
            time.sleep(0.2)

    if __name__ == "__main__":
        with par.Pool(2):
            par.submit(beat, sys.argv[1])
            time.sleep(120)
""")


def test_r14_m25_a_worker_leaves_when_its_parent_is_killed(tmp_path):
    """A worker reads its queue only between tasks, so a task runs to its end after `kill -9` of the parent (the three children of q-run stayed alive)."""
    script, heart = tmp_path / "beat.py", tmp_path / "heart"
    script.write_text(BEAT)
    p = subprocess.Popen([sys.executable, str(script), str(heart)], cwd=config.ROOT, env=dict(os.environ, PYTHONPATH=str(config.ROOT)))
    try:
        for _ in range(600):
            if heart.exists():
                break
            time.sleep(0.1)
        assert heart.exists()                                                                       # the worker is in its task
        p.kill()
        p.wait()
        last, still = heart.stat().st_mtime_ns, 0
        for _ in range(300):                                                                        # the beat stops within seconds, not after the minute
            time.sleep(0.1)
            now = heart.stat().st_mtime_ns
            still = still + 1 if now == last else 0
            last = now
            if still >= 20:
                break
        assert still >= 20, "the worker kept running after its parent was killed"
    finally:
        p.kill()
        pid = pathlib.Path(f"{heart}.pid")
        if pid.exists():                                                                            # a worker not told to leave would outlive the test
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid.read_text()), signal.SIGKILL)


def test_r14_m25_the_watch_on_the_parent_ends_the_worker_when_the_parent_is_gone_and_a_main_process_has_none(monkeypatch):
    calls = []
    monkeypatch.setattr(par.os, "_exit", calls.append)
    par._exit_with(types.SimpleNamespace(join=lambda: calls.append("parent gone")))
    assert calls == ["parent gone", 1]
    seen = threading.Event()
    monkeypatch.setattr(par, "_exit_with", lambda parent: seen.set() if parent == "the parent" else None)
    monkeypatch.setattr(par, "_in_worker", False)
    monkeypatch.setattr(par.mp, "parent_process", lambda: None)
    par._init()
    assert not seen.wait(0.3)                                                                       # pytest's own process: no parent, no watch
    monkeypatch.setattr(par.mp, "parent_process", lambda: "the parent")
    par._init()
    assert seen.wait(10)
