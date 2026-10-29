"""Checkpoint ledgers: every stage proves what it read, what it ran, which self-checks passed, and what it wrote.

    with Ledger(run_dir, "stage1", config) as L:
        L.input(path_or_url, sha=None)     # hashed now unless given (remote inputs: the hash of the bytes extracted)
        L.seed("lhs", 1234)
        L.check("lhs_stratified", ok, value=..., limit=..., note=...)
        L.output(path)                     # hashed on close
    -> run_dir/checkpoints/stage1/ledger.json; L.ok is False if any check failed (the stage raises StageFailed)

`resume`: a stage whose ledger exists, has ok=true, and whose inputs/config hash still match is skipped.
"""
import datetime as dt, json, os, pathlib, platform, subprocess, sys, time
from typing import Any

from .env.remote import sha256

ROOT = pathlib.Path(__file__).resolve().parents[2]
LIBS = ["numpy", "scipy", "xarray", "zarr", "h5py", "jax", "xlb", "gsw", "pycoare", "mannrs", "sklearn", "smt", "statsmodels"]


class StageFailed(RuntimeError):
    pass


def git_sha():
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or "none"
    except (OSError, subprocess.SubprocessError):
        return os.environ.get("CAFE_GIT_SHA", "none")


def versions():
    out = {"python": sys.version.split()[0]}
    for m in LIBS:
        try:
            out[m] = getattr(__import__(m), "__version__", "?")
        except ImportError:
            out[m] = None
    return out


def machine():
    """Which benchmarked machine this is: the `machine` block of config/throughput.json written by bench/, plus the host."""
    p = ROOT / "config" / "throughput.json"
    m = json.loads(p.read_text()).get("machine", {}) if p.exists() else {}
    return dict(host=platform.node(), cpus=os.cpu_count(), bench_id=m.get("id"), bench_measured=m.get("measured"))


class Ledger:
    def __init__(self, run_dir, stage, config_hash):
        self.dir = pathlib.Path(run_dir) / "checkpoints" / stage
        self.path = self.dir / "ledger.json"
        self.d: dict[str, Any] = dict(stage=stage, config_hash=config_hash, git_sha=git_sha(), versions=versions(), machine=machine(),
                      started=dt.datetime.now(dt.timezone.utc).isoformat(), inputs=[], seeds={}, checks=[], outputs=[], notes=[])
        self._t = time.time()

    def __enter__(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        return self

    def input(self, ref, sha=None, **meta):
        p = pathlib.Path(str(ref))
        self.d["inputs"].append(dict(ref=str(ref), sha256=sha or (sha256(p) if p.is_file() else None), **meta))

    def seed(self, name, value):
        self.d["seeds"][name] = int(value)

    def check(self, name, ok, value=None, limit=None, note=""):
        self.d["checks"].append(dict(name=name, ok=bool(ok), value=value, limit=limit, note=note))
        return bool(ok)

    def note(self, s):
        self.d["notes"].append(s)

    def output(self, path):
        self.d["outputs"].append(str(path))

    @property
    def ok(self):
        return all(c["ok"] for c in self.d["checks"])

    def __exit__(self, et, ev, tb):
        self.d["wall_s"] = round(time.time() - self._t, 3)
        self.d["outputs"] = [dict(path=p, sha256=sha256(p)) for p in self.d["outputs"] if pathlib.Path(p).is_file()]
        self.d["error"] = None if et is None else f"{et.__name__}: {ev}"
        self.d["ok"] = et is None and self.ok
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, indent=1, default=_jsonable))
        os.replace(tmp, self.path)
        if et is None and not self.ok:
            bad = [c["name"] for c in self.d["checks"] if not c["ok"]]
            raise StageFailed(f"stage {self.d['stage']}: self-checks failed: {bad} (see {self.path})")
        return False


def _jsonable(x):
    if hasattr(x, "tolist"):
        return x.tolist()
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return str(x)


def done(run_dir, stage, config_hash):
    """The stage's ledger if it finished cleanly with this config and its outputs are unchanged on disk, else None."""
    p = pathlib.Path(run_dir) / "checkpoints" / stage / "ledger.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    if not d.get("ok") or d.get("config_hash") != config_hash:
        return None
    for o in d["outputs"]:
        if not pathlib.Path(o["path"]).is_file() or sha256(o["path"]) != o["sha256"]:
            return None
    return d

