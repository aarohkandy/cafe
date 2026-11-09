"""Process-parallel tasks for the stage-1 ensemble: every CPU the run may use, the same bits as one.

`with par.Pool(n):` makes a pool the active one; `par.submit(fn, *args)` runs `fn(*args)` in it and returns a Future (inline, already done,
when no pool of more than one worker is active, and inside a worker: a task never fans out again). Workers are spawned, not forked: the
parent has the jax CPU backend running, and a fork of a process with live XLA threads hangs (DECISIONS 149).

`adopt(env)` writes every array of at least SHARE_MIN_BYTES once into an .npy file, in /dev/shm when it has SHM_MIN_FREE and the temporary
directory otherwise, and returns the object with read-only memory maps of those files in their place: the demo's 9 GB environment is then in
memory once, however many workers read it. A task's function and arguments travel as one pickle in which such a map is its file name and
everything else is its value. A file's name is never reused, and the file goes when the last of the parent's maps of it does (an
environment the pipeline rebuilds takes its files with it); a queued task's maps are alive in the parent until its result is back (`Pool.submit` holds
the task's arguments, not only their pickle, until its future is done).
The pickles pass only between this process and the workers it spawned, never through a file another user can write."""
from __future__ import annotations

import atexit, concurrent.futures as cf, contextlib, faulthandler, importlib, io, itertools, mmap, multiprocessing as mp, os, pathlib, pickle, shutil, tempfile
import threading, weakref
from collections.abc import Callable, Iterator
from typing import Any

import numpy as np

SHARE_MIN_BYTES = 1 << 20          # smaller arrays travel inside the pickle: a file per array would cost more than it saves
SHM = pathlib.Path("/dev/shm")
SHM_MIN_FREE = 12 * 2 ** 30        # the demo's environment is about 9 GB: docker run --shm-size 16g (pm.sh), else the files go to disk
STATE = (("cafe.pm.env.subgrid", "_RUN_CAL"), ("cafe.pm.stats.intervals", "P_FAIL_GO"), ("cafe.pm.stats.intervals", "P_FAIL_NOGO"),
         ("cafe.pm.stats.intervals", "LO_SUCCESS_GO"))   # module state the parent sets (the run's sub-grid calibration, the mission's verdict cut-offs)
_active: Pool | None = None
_in_worker = False
_limit: int | None = None                                           # set by `limit`: the plan's worker count when memory cut it below the CPUs
_dir: pathlib.Path | None = None
_names = itertools.count()                                          # a file name never repeats (one was once written over a file a task still named)
_refs: dict[str, int] = {}                                         # file -> the parent's live maps of it
_lock = threading.RLock()                                           # threads (stage1.run's batches) and finalizers, which run inside a collection


def _child() -> bool:
    """A worker, or any process multiprocessing started: true from its first line, before the initializer runs (a spawned child re-imports the
    parent's main script, and one without an `if __name__ == "__main__"` guard would otherwise build and share an environment of its own)."""
    return _in_worker or mp.parent_process() is not None


def env_count(name: str) -> int | None:
    """The whole number of at least 1 in the environment variable `name`; None when it is unset or empty; anything else is a `ConfigError` naming it."""
    v = os.environ.get(name)
    if not v:
        return None
    try:
        n = int(v)
    except ValueError:
        n = 0
    if n < 1:
        from .config import ConfigError
        raise ConfigError(f"{name}={v!r} is not a whole number of at least 1; set {name}=N or unset it")
    return n


def _cgroup_cpus(root: str = "/sys/fs/cgroup") -> int | None:
    """The CPUs the cgroup quota allows (docker --cpus), rounded down, at least 1: v2 `cpu.max`, else v1 `cpu/cpu.cfs_quota_us` over
    `cpu/cpu.cfs_period_us`. None: no quota (v2 "max", v1 -1) or none readable."""
    r = pathlib.Path(root)
    for files in (("cpu.max",), ("cpu/cpu.cfs_quota_us", "cpu/cpu.cfs_period_us")):
        try:
            quota, period = " ".join((r / f).read_text() for f in files).split()
            return max(1, int(quota) // int(period)) if quota not in ("max", "-1") else None
        except (OSError, ValueError, ZeroDivisionError):
            continue
    return None


def workers() -> int:
    """CAFE_WORKERS when set (a whole number of at least 1, else ConfigError), else the CPUs this process may use: its affinity mask, cut to the
    cgroup quota (docker --cpus); at most the `limit` of the run (the plan's memory cap); 1 in a worker."""
    if _child():
        return 1
    n = env_count("CAFE_WORKERS")
    if n is None:
        n = len(os.sched_getaffinity(0))
        q = _cgroup_cpus()
        n = n if q is None else min(n, q)
    return n if _limit is None else min(n, _limit)


@contextlib.contextmanager
def limit(n: int | None) -> Iterator[None]:
    """`workers()` is at most n inside the block (the run's planned count: memory can allow fewer workers than there are CPUs); None: no limit."""
    global _limit
    prev, _limit = _limit, n
    try:
        yield
    finally:
        _limit = prev


def resize(n: int) -> None:
    """The run's worker count becomes n from here on (the plan was made again after the ingest and memory allows fewer): `workers()` is at most n
    and the active pool, if it has not started its processes yet, is n wide. Undone with the enclosing `limit` block."""
    global _limit
    _limit = n
    if _active is not None and _active.ex is None:
        _active.n = n


def _meminfo_gb(key: str) -> float | None:
    """The GB /proc/meminfo reports for `key` (MemTotal, MemAvailable); None when unreadable."""
    try:
        return next(int(l.split()[1]) * 1024 / 1e9 for l in pathlib.Path("/proc/meminfo").read_text().splitlines() if l.startswith(key + ":"))
    except (OSError, StopIteration, ValueError, IndexError):
        return None


def memory_gb() -> float | None:
    """GB this process may use: the cgroup limit (v2 `memory.max`, v1 `memory.limit_in_bytes`) when there is one, cut to the machine's MemTotal (a
    cgroup can be given more than the machine has: orca's says 256 GiB on 251.6 GiB, round 9 P-5), else /proc/meminfo MemAvailable;
    None when neither can be read."""
    for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            b = int(pathlib.Path(f).read_text())
        except (OSError, ValueError):                                   # absent, or "max"
            continue
        if b < 2 ** 60:                                                 # cgroup v1 spells unlimited as a number near 2**63
            total = _meminfo_gb("MemTotal")
            return b / 1e9 if total is None else min(b / 1e9, total)
    return _meminfo_gb("MemAvailable")


def _mapped(path: str) -> Any:
    return np.load(path, mmap_mode="r")


def _owned(path: str) -> Any:
    """A parent's map of a shared file, counted: the file goes with the last such map (an adopted object re-maps the files of the maps it held,
    and those may die first)."""
    m = np.load(path, mmap_mode="r")
    with _lock:
        _refs[path] = _refs.get(path, 0) + 1
    weakref.finalize(m, _release, path)
    return m


def _release(path: str) -> None:
    with _lock:
        _refs[path] -= 1
        if _refs[path]:
            return
        del _refs[path]
    pathlib.Path(path).unlink(missing_ok=True)


def _share(a: np.ndarray) -> str:
    """A new .npy file holding `a` (pickle's own memo writes an array met twice in one `adopt` once)."""
    global _dir
    with _lock:
        if _dir is None:
            room = shutil.disk_usage(SHM).free if SHM.is_dir() else 0
            _dir = pathlib.Path(tempfile.mkdtemp(prefix=f"cafe-share-{os.getpid()}-", dir=SHM if room >= SHM_MIN_FREE else None))
            atexit.register(shutil.rmtree, _dir, True)
        i = next(_names)
        path = str(_dir / f"{i}.npy")
        if shutil.disk_usage(_dir).free < a.nbytes:                      # SHM_MIN_FREE is looked at once, for the directory; a long window outgrows it later
            from .config import ResourceError                         # as `env_count` does: config is not imported by a worker that never needs it
            raise ResourceError(f"{_dir} is full after {i} arrays: raise --shm-size (RUNBOOK 1) or free the disk")
    np.save(path, a)
    return path


class _Pickler(pickle.Pickler):
    def __init__(self, f: io.BytesIO, share: bool):
        super().__init__(f, protocol=5)
        self.share = share

    def reducer_override(self, obj: Any) -> Any:
        if isinstance(obj, np.memmap) and isinstance(obj.base, mmap.mmap) and _dir is not None and str(obj.filename).startswith(f"{_dir}{os.sep}"):
            return (_owned if self.share else _mapped), (str(obj.filename),)   # a whole adopted map: its own file again
        if self.share and type(obj) is np.ndarray and obj.nbytes >= SHARE_MIN_BYTES and not obj.dtype.hasobject:
            return _owned, (_share(obj),)
        return NotImplemented


def dumps(obj: Any, share: bool = False) -> bytes:
    """`obj` pickled with every adopted map as its file name; share True (`adopt`): every large array is written to a file and named too."""
    f = io.BytesIO()
    _Pickler(f, share).dump(obj)
    return f.getvalue()


def adopt(obj: Any) -> Any:
    """`obj` with every large array swapped for its shared read-only map (the one copy the workers read too); `obj` itself on one worker."""
    if workers() == 1:
        return obj
    return pickle.loads(dumps(obj, share=True))


def state() -> tuple[Any, ...]:
    """This process's values of STATE."""
    return tuple(getattr(importlib.import_module(m), a) for m, a in STATE)


def _run(blob: bytes) -> Any:
    there, fn, args = pickle.loads(blob)
    for (mod, name), v in zip(STATE, there, strict=True):               # as the parent had it when it sent the task
        setattr(importlib.import_module(mod), name, v)
    return fn(*args)


def _init() -> None:
    global _in_worker
    _in_worker = True
    faulthandler.enable()                                                 # a worker that dies in native code says where (the pool only says it broke)


class Pool:
    """n spawned worker processes, started on the first task (none for n 1); a context manager."""

    def __init__(self, n: int):
        self.n = max(1, int(n))
        self.ex: cf.ProcessPoolExecutor | None = None
        self.held: dict[cf.Future[Any], tuple[Any, ...]] = {}              # a task's arguments until its future is done: only they keep the files

    def __enter__(self) -> Pool:
        global _active
        self.prev = _active
        if _active is None and self.n > 1 and not _child():             # inside another pool's block this one stays empty: that pool serves
            _active = self
        return self

    def __exit__(self, *exc: object) -> None:
        global _active
        _active = self.prev
        if self.ex is not None:
            self.ex.shutdown(cancel_futures=True)

    def submit(self, fn: Callable[..., Any], *args: Any) -> cf.Future[Any]:
        blob = dumps((state(), fn, args))
        with _lock:
            if self.ex is None:
                self.ex = cf.ProcessPoolExecutor(self.n, mp_context=mp.get_context("spawn"), initializer=_init)
        fut = self.ex.submit(_run, blob)
        self.held[fut] = args
        fut.add_done_callback(lambda f: self.held.pop(f, None))
        return fut


def submit(fn: Callable[..., Any], *args: Any) -> cf.Future[Any]:
    """fn(*args) in the active pool, or here and now (the Future is done, holding the result or the exception) when none is active."""
    if _active is not None:
        return _active.submit(fn, *args)
    fut: cf.Future[Any] = cf.Future()
    try:
        fut.set_result(fn(*args))
    except BaseException as e:                                            # re-raised by fut.result(), where a pool's would be
        fut.set_exception(e)
    return fut


def width() -> int:
    """How many tasks the active pool runs at once (1 without one)."""
    return 1 if _active is None else _active.n
