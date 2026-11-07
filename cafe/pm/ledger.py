"""Checkpoint ledgers: every stage proves what it read, what it ran, which self-checks passed, and what it wrote.

    with Ledger(run_dir, "stage1", config) as L:
        L.input(path_or_url, sha=None)     # hashed now unless given (remote inputs: the hash of the bytes extracted)
        L.seed("lhs", 1234)
        L.check("lhs_stratified", ok, value=..., limit=..., note=...)
        L.output(path)                     # hashed on close
    -> run_dir/checkpoints/stage1/ledger.json; L.ok is False if any check failed (the stage raises StageFailed)

`resume`: a stage whose ledger exists, has ok=true, and whose inputs/config hash still match is skipped.
"""
from __future__ import annotations

import datetime as dt, importlib.metadata, json, math, os, pathlib, platform, shutil, subprocess, sys, time
from types import TracebackType
from typing import Any, Literal

from .env.remote import sha256, tree_sha256

ROOT = pathlib.Path(__file__).resolve().parents[2]
STAGES = ["ingest", "hangar", "stage1", "windows", "stage3", "refit", "stage1b", "emulator", "report"]       # also the names of a run's output directories
RUN_DIRS = {"checkpoints", *STAGES}
DIST = {"sklearn": "scikit-learn", "yaml": "PyYAML"}  # import name -> distribution name, where they differ (for libraries with no __version__)
LIBS = ["numpy", "scipy", "xarray", "zarr", "h5py", "jax", "xlb", "gsw", "pycoare", "mannrs", "sklearn", "smt", "statsmodels",
        "pandas", "pyarrow", "arlpy", "yaml", "jsonschema", "netCDF4"]


class StageFailed(RuntimeError):
    pass


def git_sha() -> str:
    """HEAD of the checkout, else $CAFE_GIT_SHA (a copy synced without .git, e.g. into the container), else "none"."""
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return sha or os.environ.get("CAFE_GIT_SHA", "none")


def git_dirty() -> bool | None:
    """Whether the checkout has uncommitted changes (`git status --porcelain` is not empty); for a copy synced without .git, $CAFE_GIT_DIRTY
    ("1" or "0", which pm.sh sets from the laptop's checkout); None when neither can say."""
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        r = None
    if r is not None and r.returncode == 0:
        return bool(r.stdout.strip())
    flag = os.environ.get("CAFE_GIT_DIRTY")
    return None if flag not in ("0", "1") else flag == "1"


def _version(m: str) -> str:
    """The module's `__version__`, else the installed distribution's version (pycoare and mannrs have no `__version__`), else "?"."""
    mod = __import__(m)
    v = getattr(mod, "__version__", None)
    if v is not None:
        return str(v)
    try:
        return importlib.metadata.version(DIST.get(m, m))
    except importlib.metadata.PackageNotFoundError:
        return "?"


def versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {"python": sys.version.split()[0]}
    for m in LIBS:
        try:
            out[m] = _version(m)
        except ImportError:
            out[m] = None
    out["bellhop"] = bellhop()
    return out


def bellhop() -> str:
    """The sha256 of the `bellhop.exe` the acoustic links would use (`comms._bellhop_dir`), or "absent": installing it after a run changes the code
    digest, so the Thorp-only stage 1 is not resumed as if Bellhop had been asked."""
    from .physics import comms
    d = comms._bellhop_dir()
    return "absent" if d is None else sha256(pathlib.Path(d) / "bellhop.exe")


def machine() -> dict[str, Any]:
    """Which benchmarked machine this is: the `machine` block of config/throughput.json written by bench/, plus the host, its CPU count and the
    stage-1 workers this process runs (`par.workers()`: the CPUs it may use, or CAFE_WORKERS, or the run's planned count), and `warning`: why that
    block's rates may not be this host's (`budget.machine_warning`), or None. It is judged here, once, on the host that runs the stage, so a later
    `report --run` on another machine reads what the run saw instead of comparing throughput.json with the machine that renders (round 9, L0)."""
    from . import par
    from .budget import machine_warning
    p = ROOT / "config" / "throughput.json"
    from .config import THROUGHPUT_FIX, json_object
    thr = json_object(p, THROUGHPUT_FIX) if p.exists() else {}
    m = thr.get("machine", {})
    return dict(host=platform.node(), cpus=os.cpu_count(), workers=par.workers(), bench_id=m.get("id"), bench_measured=m.get("measured"),
                warning=machine_warning(thr))


class Ledger:
    def __init__(self, run_dir: str | pathlib.Path, stage: str, config_hash: str, code_digest: str | None = None) -> None:
        self.dir = pathlib.Path(run_dir) / "checkpoints" / stage
        self.path = self.dir / "ledger.json"
        self.d: dict[str, Any] = dict(stage=stage, config_hash=config_hash, git_sha=git_sha(), git_dirty=git_dirty(), code_digest=code_digest,
                      versions=versions(), machine=machine(),
                      started=dt.datetime.now(dt.timezone.utc).isoformat(), inputs=[], seeds={}, checks=[], outputs=[], notes=[])
        self._t = time.time()

    def __enter__(self) -> Ledger:
        self.dir.mkdir(parents=True, exist_ok=True)
        return self

    def input(self, ref: Any, sha: str | None = None, tree: str | None = None, **meta: Any) -> None:
        """`tree`: for a directory input (a zarr store), the sha256 over every file of it (`tree_sha256`), which `done` and the audit recompute."""
        p = pathlib.Path(str(ref))
        extra = {} if tree is None else dict(tree_sha256=tree)
        self.d["inputs"].append(dict(ref=str(ref), sha256=sha or (sha256(p) if p.is_file() else None), **extra, **meta))

    def snapshot(self, src: str | pathlib.Path, dest: str | pathlib.Path, **meta: Any) -> None:
        """A shared cache manifest (TAO, orca) is rewritten in place whenever a later run grows or replaces the cache, so a ledger that hashed it made every
        earlier run's audit say "input changed" (review round 10, P-32). The stage copies the bytes it read into the run (`dest`, atomically) and records
        the copy as the input, with `shared` = where it came from; the audit checks the copy by hash and the files it names against the shared cache
        (`audit._shared_problems`), not the shared manifest. A run directory then carries the manifest the run used."""
        dest = pathlib.Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        self.input(dest, shared=str(src), **meta)

    def seed(self, name: str, value: Any) -> None:
        self.d["seeds"][name] = int(value)

    def check(self, name: str, ok: Any, value: Any = None, limit: Any = None, note: str = "") -> bool:
        self.d["checks"].append(dict(name=name, ok=bool(ok), value=value, limit=limit, note=note))
        return bool(ok)

    def note(self, s: str) -> None:
        self.d["notes"].append(s)

    def output(self, path: str | pathlib.Path) -> None:
        self.d["outputs"].append(str(path))

    @property
    def ok(self) -> bool:
        return all(c["ok"] for c in self.d["checks"])

    def __exit__(self, et: type[BaseException] | None, ev: BaseException | None, tb: TracebackType | None) -> Literal[False]:
        self.d["wall_s"] = round(time.time() - self._t, 3)
        outs = [(p, pathlib.Path(p).is_file()) for p in self.d["outputs"]]
        missing = [p for p, here in outs if not here]
        self.d["outputs"] = [dict(path=p, sha256=sha256(p) if here else None) for p, here in outs]
        self.d["error"] = None if et is None else f"{et.__name__}: {ev}"
        if missing and et is None:
            self.d["error"] = f"outputs never written: {missing}"
        self.d["ok"] = et is None and not missing and self.ok
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(clean(self.d), indent=1, allow_nan=False))
        os.replace(tmp, self.path)
        if missing and et is None:
            raise StageFailed(f"stage {self.d['stage']}: registered outputs were never written: {missing} (ledger: {self.path})")
        if et is None and not self.ok:
            bad = [f"{c['name']}: {c['note']}" if c["note"] else c["name"] for c in self.d["checks"] if not c["ok"]]
            more = f" and {len(bad) - 3} more" if len(bad) > 3 else ""
            raise StageFailed(f"stage {self.d['stage']}: self-checks failed: {'; '.join(bad[:3])}{more} (ledger: {self.path})")
        return False


def _jsonable(x: Any) -> Any:
    if hasattr(x, "tolist"):
        return x.tolist()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return str(x)


def clean(x: Any) -> Any:
    """x as strict JSON data: numpy values and dates made plain (`_jsonable`), every non-finite float (NaN, an unbounded limit) replaced by None,
    because JSON has no NaN or Infinity and `jq` / JSON.parse reject them."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    return x if x is None or isinstance(x, (bool, int, str)) else clean(_jsonable(x))


def hashed(i: dict[str, Any]) -> bool:
    """A ledger input the stage hashed when it ran (a file or a store), so it has to be on disk for a resume or an audit to trust the ledger. A remote
    reference (a URL) is no path: it stays out."""
    return bool(i.get("sha256") or i.get("tree_sha256")) and "://" not in str(i["ref"])


def run_roots(d: dict[str, Any]) -> set[tuple[str, ...]]:
    """Where the run that wrote ledger `d` lay: for each output it recorded (always inside the run), the path parts before each directory of the run's
    layout (`RUN_DIRS`). `resolve` rebases a recorded path through the layout only when it starts with one of these, so a path outside the run that
    happens to pass through a directory named like a stage (`/data/cache/report/x`) is not mistaken for the run's own."""
    out: set[tuple[str, ...]] = set()
    for o in d.get("outputs", []):
        parts = pathlib.Path(o["path"]).parts
        out |= {parts[:i] for i, part in enumerate(parts) if part in RUN_DIRS}
    return out


def resolve(ref: str | pathlib.Path, run_dir: str | pathlib.Path, roots: set[tuple[str, ...]]) -> pathlib.Path:
    """Where a path a ledger recorded is now. A run that was moved, copied or renamed keeps the absolute paths of where it ran, so a recorded path is
    looked up under `run_dir` before where it was recorded, in this order: (1) through a directory named like `run_dir`, the rest of the path joined onto it;
    (2) if the path lies under a place the run was (`roots`, from `run_roots` of the same ledger), from the first directory of the run's own layout in it
    (`checkpoints` or a stage's output directory, `RUN_DIRS`), longest tail first, so `.../q9/stage3/windows/x` is tried as `stage3/windows/x` before
    `windows/x`; (3) as recorded, for what lies outside the run (`/app/config/...`, the environment cache). A candidate that exists under `run_dir` wins;
    a path in the run's layout under a place the run was (2) that does not exist there is reported at its place in `run_dir`, the first (longest) candidate,
    not as recorded, because the recorded one is the original run's file, which a copy must not borrow (round 9, L1). A path with a `..` in it is never
    rebased."""
    run_dir, p = pathlib.Path(run_dir), pathlib.Path(ref)
    if ".." in p.parts:
        return p
    for i in range(len(p.parts) - 1, -1, -1):
        if p.parts[i] == run_dir.name:
            q = run_dir.joinpath(*p.parts[i + 1:])
            if q.exists():
                return q
            break
    lost = None
    for i, part in enumerate(p.parts):
        if part in RUN_DIRS and p.parts[:i] in roots:
            q = run_dir.joinpath(*p.parts[i:])
            if q.exists():
                return q
            lost = lost or q
    return lost or p


def done(run_dir: str | pathlib.Path, stage: str, config_hash: str) -> dict[str, Any] | None:
    """The stage's ledger if it finished cleanly with this config and its outputs and hashed inputs are present and unchanged on disk, else None.
    Recorded paths are read where `resolve` finds them, so a run copied under another name resumes against its own files."""
    p = pathlib.Path(run_dir) / "checkpoints" / stage / "ledger.json"
    if not p.exists():
        return None
    try:
        d: dict[str, Any] = json.loads(p.read_text())
        if not isinstance(d, dict):
            raise ValueError("not a JSON object")
    except (ValueError, OSError) as e:                                   # a half-written ledger (killed or full-disk run): the stage runs again
        print(f"note: ledger {p} is unreadable ({e}): the stage runs again", file=sys.stderr)
        return None
    if not d.get("ok") or d.get("config_hash") != config_hash:
        return None
    try:
        roots = run_roots(d)
        for o in d["outputs"]:
            f = resolve(o["path"], run_dir, roots)
            if not f.is_file() or sha256(f) != o["sha256"]:
                return None
        for i in d["inputs"]:
            f = resolve(i["ref"], run_dir, roots)
            if hashed(i) and not f.exists():                                      # a deleted store or file: the stage ran on data that is gone
                return None
            if i.get("sha256") and f.is_file() and sha256(f) != i["sha256"]:
                return None
            if i.get("tree_sha256") and f.is_dir() and tree_sha256(f) != i["tree_sha256"]:       # a store: every file of it, not the manifest it was made from
                return None
    except (KeyError, TypeError, AttributeError) as e:                       # valid JSON of the wrong shape: as a half-written ledger, the stage runs again
        print(f"note: ledger {p} is damaged or incomplete ({type(e).__name__}: {e}): the stage runs again", file=sys.stderr)
        return None
    return d


def rerecord(run_dir: str | pathlib.Path, stage: str, written: list[pathlib.Path], code_digest: str | None) -> bool:
    """After `report --run` rewrote a finished stage's outputs: the stage's ledger takes the new sha256 of each (an output it did not list is added) and
    a note that says who re-rendered it, with which `git_sha` and `code_digest`; its checks, config hash and own `git_sha` stay what the stage recorded.
    Without that ledger there is nothing to bring up to date (False)."""
    p = pathlib.Path(run_dir) / "checkpoints" / stage / "ledger.json"
    if not p.is_file():
        return False
    d = json.loads(p.read_text())
    roots = run_roots(d)
    outs = {resolve(o["path"], run_dir, roots).resolve(): o for o in d["outputs"]}
    for w in written:
        outs.setdefault(w.resolve(), dict(path=str(w)))["sha256"] = sha256(w)
    d["outputs"] = list(outs.values())
    d["notes"].append(f"re-rendered by report --run (git_sha {git_sha()}, code_digest {code_digest})")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean(d), indent=1, allow_nan=False))
    os.replace(tmp, p)
    return True
