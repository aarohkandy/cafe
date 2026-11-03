"""run_premission: mission yaml -> report, through checkpointed stages (BRIEF 2.9).

    ingest -> hangar -> stage1 -> windows -> stage3 -> refit -> stage1b -> emulator -> report

Every stage writes run_dir/checkpoints/<stage>/ledger.json (cafe.pm.ledger) naming the previous stage's ledger as an input,
so `make audit` can walk the chain; `resume=True` skips a stage whose ledger is clean for the same config hash and whose
outputs are unchanged. Stage products live next to the ledgers:

    run_dir/plan.json                     budget plan (cafe.pm.budget) for this machine
    run_dir/mission.yaml                  the mission as run
    run_dir/stage1/summary.json, res.pkl  verdicts per vehicle/link; members' tracks, flags and sampled parameters
    run_dir/windows/windows.json          the worst windows per vehicle that stage 3 resolves
    run_dir/stage3/windows.json           window coefficients, checks, FEA utilization
    run_dir/refit/refit.json              Stage-1 multipliers from the windows (or why none were used)
    run_dir/stage1b/summary.json, res.pkl the rerun with the refit multipliers (a copy of stage 1 when nothing was refit)
    run_dir/emulator/holdout.json         per vehicle: its class's emulator hold-out scores and acceptance, or why it is not trained
    run_dir/emulator/flip.json            per non-GO vehicle: the smallest mission change that flips the verdict (emulator-first), what was tried
    run_dir/emulator/design.json          the variant runs added to the training table (and those skipped, with why) and the budget they used
    run_dir/emulator/train_input.parquet  the training table as the emulator stage found it, minus this run's own rows: what the emulator trains on
                                          (plus this run's rows); a ledger input, so the emulator is a function of a hashed input
    $CAFE_DATA/emulator/train.parquet     the shared training table, one row per vehicle per Stage-1 run (cafe.pm.whatif); this run appends to it
                                          after training, so it never changes this run's emulator (`run --emulator-table` / $CAFE_EMULATOR_TABLE names another)
    run_dir/report/index.html, report.json
"""
from __future__ import annotations

import contextlib, datetime as dt, io, json, os, pathlib, pickle, re, shutil, time, warnings, zipfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import chi2

from . import budget, ledger, par, stage1
from .audit import STAGES
from .config import ConfigError, digest, env_sigmas, load_mission, utc
from .env import bathy, conventions as cv, hycom, ocean as ocean_mod, orca, subgrid
from .env.hycom import FetchError
from .env.remote import sha256
from .ledger import Ledger

if TYPE_CHECKING:
    from .env.environment import GriddedEnv

DATA = pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


def code_digest() -> str:
    """sha256 over every `cafe/**/*.py` (the pipeline imports cafe.cfd, cafe.fea, cafe.emulator, cafe.reach, cafe.receipts from outside cafe/pm),
    the schemas (`cafe/schemas/*.json`, the contract ingest and `load_mission` read), the config and platform files, and the installed version of every
    library `ledger.versions()` lists that is installed (Python as major.minor): a resumed stage is reused only if none changed."""
    import hashlib
    root = pathlib.Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    for p in sorted([*root.joinpath("cafe").rglob("*.py"), *root.joinpath("cafe", "schemas").glob("*.json"), *root.joinpath("config").rglob("*.*"),
                     *root.joinpath("platforms").glob("*.yaml")]):
        rel = p.relative_to(root)
        if "__pycache__" not in rel.parts and "site" not in rel.parts:
            h.update(str(rel).encode() + b"\0" + p.read_bytes())
    v = {k: x for k, x in ledger.versions().items() if x is not None}
    v["python"] = ".".join(v["python"].split(".")[:2])
    h.update(json.dumps(v, sort_keys=True).encode())
    return h.hexdigest()


def gpu_memory_gb() -> float | None:
    """Memory of the first GPU [GB] from `nvidia-smi`, or None when there is no nvidia-smi or it does not answer (the planner then has no memory to guard)."""
    import subprocess
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30)
        return float(out.stdout.split()[0]) / 1024.0 if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def gpu_visible() -> bool:
    """A CUDA device that warp can see, or nvidia-smi on the path: whether `--gpus N` has anything to run on here (`run` refuses N > 0 without it)."""
    from .stage3 import lbm
    return lbm.pick_backend() == "warp" or shutil.which("nvidia-smi") is not None


def emulator_table(explicit: str | pathlib.Path | None = None) -> pathlib.Path:
    """The emulator's training table: `explicit` (`run --emulator-table`), else $CAFE_EMULATOR_TABLE, else $CAFE_DATA/emulator/train.parquet."""
    return pathlib.Path(explicit or os.environ.get("CAFE_EMULATOR_TABLE") or DATA / "emulator" / "train.parquet")


class Context:
    """What the stages share: the mission, the plan, where things live, and the environment (built once, lazily)."""

    def __init__(self, mission_path: str | pathlib.Path, budget_name: str | None, gpus: int, run_dir: str | pathlib.Path,
                 log: Callable[[str], None] = print, seed: int | None = None, emulator_table: str | pathlib.Path | None = None,
                 gpu_mem_gb: float | None = None, hash_budget: str | None = None) -> None:
        """`budget_name` None: no plan (`fetch`: ingest needs the mission and its window, never a budget, so a mission no budget can run still downloads).
        `hash_budget`: the budget the resume hash names when there is no plan, so that a fetch into a run directory leaves its ledgers current for `run`.
        `gpu_mem_gb`: the device memory the planner sizes the nests against (budget.plan refuses a nest over 85 % of it)."""
        self.mission_path = pathlib.Path(mission_path)
        self.mission = load_mission(mission_path)
        if seed is not None:
            self.mission["seed"] = seed                                  # `run --seed`: the one seed every stage reads; it is in the resume hash below
        self.run_dir = pathlib.Path(run_dir)
        self.cache = DATA / "cache" / self.mission["name"]
        self.log = log
        self.classes = stage1._classes(self.mission)
        self.plan: dict[str, Any] = {}
        if budget_name is not None:
            mem = par.memory_gb()
            self.plan = budget.plan(budget_name, gpus, self.mission, gpu_mem_gb=gpu_mem_gb, vehicle_classes=self.classes, mem_gb=mem,
                                    env_gb=None if mem is None else budget.env_gb(self.mission, self.cache))
            if seed is not None:
                self.plan["seed_override"] = seed
            self.plan["refit_iterations_max"] = self.plan["refit_iterations"]            # the cap; stage 1b records the passes done
            self.plan["stage3"] = budget.stage3_plan(self.plan, self.classes, budget.stage3_assumptions())      # every size stage 3 uses
            self.plan["emulator"] = budget.emulator_plan(self.plan)
        self._table = emulator_table
        subgrid.use_calibration(None)                                    # the shipped sub-grid calibration until a stage after stage 3 loads the run's own
        self.code_digest = code_digest()
        mission = {k: v for k, v in self.mission.items() if k != "_path"}                                 # not the spelling of the path it was read from
        self.hash = digest(dict(mission=mission, budget=budget_name or hash_budget, gpus=gpus, code=self.code_digest))
        self._env: GriddedEnv | None = None

    def stage_hash(self, name: str) -> str:
        """The config hash a stage's ledger carries: `hash`, and for the emulator and the stages after it also the emulator plan and the workers it
        was sized on (the variants depend on them), so a resume under another CPU count reruns those and reuses stage 1 and 1b."""
        if not self.plan or STAGES.index(name) < STAGES.index("emulator"):
            return self.hash
        return digest(dict(config=self.hash, emulator=self.plan["emulator"], workers=self.plan["workers"]))

    @property
    def env(self) -> GriddedEnv:
        """GriddedEnv over the cache. The surface layer honours the mission's warm_layer / rain_lens switches; the sigmas the values
        are tagged with are config/assumptions.yaml's, replaced by the TAO fit (ingest/env_sigmas_fitted.json) once ingest wrote it."""
        if self._env is None:
            from .env import surface
            from .env.environment import GriddedEnv
            e = self.mission["environment"]
            sub = None                                                                                        # built by ingest
            if _derived_current(self.cache):
                why = _derived_span_problem(self.cache, self.window_s())
                if why:
                    raise ConfigError(f"{self.cache}/derived.zarr: {why}; rerun `python -m cafe.pm fetch --mission {self.mission_path}` to rebuild it")
                sub = surface.SurfaceLayer(self.cache, warm_layer=subgrid.switch(e, "warm_layer"), rain_lens=subgrid.switch(e, "rain_lens"))
            sig, fit = env_sigmas(), self.run_dir / "ingest" / "env_sigmas_fitted.json"
            if fit.is_file():
                sig.update(json.loads(fit.read_text()))
            self._env = par.adopt(GriddedEnv(self.cache, sig, ocean=ocean(self), subgrid=sub))     # one copy, shared with the stage-1 workers
        return self._env

    def window_s(self) -> tuple[float, float]:
        """The mission window as (start, end) seconds since 1970."""
        w = self.mission["window"]
        return utc(w["start"]).timestamp(), utc(w["end"]).timestamp()

    @property
    def table(self) -> pathlib.Path:
        """The training table this run reads and appends to (see `emulator_table`)."""
        return emulator_table(self._table)

    def path(self, *parts: str) -> pathlib.Path:
        p = self.run_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


DRIFT_MS = 0.5                   # the drift speed `padding` sizes a pad from: about the fastest sustained surface current (6 d: 2.3, padded 2.5 deg)
MAX_PAD_DEG = 10.0               # config/schemas mission.json: box.pad_deg <= 10


def padding(m: dict[str, Any]) -> float:
    """The box pad [deg]: the mission's `pad_deg`, else the window length x DRIFT_MS rounded up to 0.5 deg (at most MAX_PAD_DEG), so that a drifting
    vehicle stays inside the downloaded data unless the window is longer than MAX_PAD_DEG / DRIFT_MS days. s_ingest says which one it used."""
    b = m["box"]
    if "pad_deg" in b:
        return float(b["pad_deg"])
    days = (utc(m["window"]["end"]) - utc(m["window"]["start"])).total_seconds() / 86400.0
    return float(min(MAX_PAD_DEG, np.ceil(days * 86400.0 * DRIFT_MS / 111e3 * 2.0) / 2.0))


def ocean_box(m: dict[str, Any]) -> tuple[float, float, float, float]:
    """(south, north, west, east) of mission m's box plus its pad: what the ocean store, GEBCO and TAO are cut to."""
    b = m["box"]
    pad = padding(m)
    return (b["lat_min"] - pad, b["lat_max"] + pad, b["lon_min"] - pad, b["lon_max"] + pad)


def _offline() -> bool:
    """CAFE_OFFLINE set (and not 0): nothing is ever downloaded."""
    return os.environ.get("CAFE_OFFLINE", "") not in ("", "0")


def _umwm_depth(cache: str | pathlib.Path) -> dict[str, NDArray[np.float64]] | None:
    """UMWM's depth on its grid (0 on land) from the orca cache, for bathy.choose's last fallback; None before orca is ingested."""
    import xarray as xr
    p = pathlib.Path(cache) / "orca" / "umwm.zarr"
    if not p.exists():
        return None
    u = xr.open_zarr(p)
    return dict(lon=u.lon.values, lat=u.lat.values, depth=np.where(u["seamask"].values > 0, u["depth"].values.astype("f8"), 0.0))


def ocean(ctx: Context) -> Any:
    """The ocean source the mission names (GOFS 3.1 or the lab's HYCOM), from the cache hycom.py writes. Bathymetry falls back
    GEBCO -> the store's floor -> UMWM's depth; a missing GEBCO cut is downloaded only when CAFE_OFFLINE is not set."""
    from .env.ocean import open_ocean
    return open_ocean(ctx.mission["environment"]["ocean"], ctx.cache, ctx.mission["name"], ocean_box(ctx.mission), fetch_bathy=not _offline(),
                      umwm=_umwm_depth(ctx.cache))


# res.pkl is only ever read back by this pipeline from its own run directory, and every reader names it as a ledger input,
# whose sha256 `make audit` re-checks: it is a private checkpoint format, never loaded from anywhere else.
def _dump(obj: Any, path: pathlib.Path) -> pathlib.Path:
    """`obj` as strict JSON: a NaN or an infinity (an unbounded check limit, a missing SST bias) is written as null, which `jq` and JSON.parse read."""
    path.write_text(json.dumps(ledger.clean(obj), indent=1, allow_nan=False))
    return path


# ------------------------------------------------------------------------------------------------------------------ stages

GOFS_DEADLINE_S = 1500.0         # hycom.fetch_gofs kills a request that has not answered in this long (it measured 193-335 s per step)


def _need(ctx: Context, L: Ledger, name: str, what: str, present: Callable[[], bool], fetch: Callable[[], Any], hint: str | None = None) -> bool:
    """The one place a download starts. `present()` says whether the input is cached and good (hash-checked); if not, `fetch()` downloads
    it (resumable, so a rerun continues), unless CAFE_OFFLINE is set, which fails the check `<name>_present` naming the command to run
    with network access (`hint` replaces that command for inputs `fetch` cannot make). A failed download is the same failed check, with
    the error. Returns whether the input is there."""
    note = what
    if not present():
        cmd = hint or f"python -m cafe.pm fetch --mission {ctx.mission_path}"
        if _offline():
            again = "run" if hint else "unset CAFE_OFFLINE and run"  # `fetch` is the command that was just run (or `run`, which fetches)
            note = f"{what} is not cached and CAFE_OFFLINE is set, so nothing is downloaded: {again} `{cmd}`"
        else:
            ctx.log(f"ingest: fetching {what}")
            t = time.time()
            try:
                got = fetch()
                what_got = f"{got} parts" if isinstance(got, int) else what
                L.note(f"cold fetch: {what_got}, {time.time() - t:.0f} s (the network step; --budget does not count it)")
            except (OSError, ValueError, LookupError, FetchError) as e:
                note = f"fetching {what} failed ({type(e).__name__}: {e}); parts already fetched are kept, rerun `{cmd}` to resume"
    ok = present()
    L.check(f"{name}_present", ok, note=what if ok else note)
    return ok


def _ocean_cached(path: pathlib.Path, box: tuple[float, float, float, float], steps: Any) -> bool:
    """The GOFS store at `path` has every 3-hourly step and spans `box` (to the 0.1 degree grid snap), and its recorded parts-manifest
    hash is the one on disk when the parts are still there (assemble_gofs hash-checks every part against that manifest)."""
    if not path.exists():
        return False
    ds = hycom.open_store(path)
    s, n, w, e = hycom.box360(box)
    ok = bool(np.isin(steps, ds.time.values).all() and ds.lat.values.min() <= s + 0.1 and ds.lat.values.max() >= n - 0.1
              and ds.lon.values.min() <= w + 0.1 and ds.lon.values.max() >= e - 0.1)
    man = path.with_name(path.stem + ".parts") / "manifest.json"
    return ok and (not man.is_file() or ds.attrs.get("manifest_sha256") == sha256(man))


def _tao_cached(tdir: pathlib.Path, box: tuple[float, float, float, float], t0: float, t1: float) -> bool:
    """TAO manifest covers the box and window and every file still hashes to it (tao.verify)."""
    from .env import tao
    mp = tdir / "manifest.json"
    if not mp.is_file():
        return False
    m = json.loads(mp.read_text())
    s, n, w, e = hycom.box360(box)
    if not (m["t0"] <= t0 and m["t1"] >= t1 and m["box"][0] <= s and m["box"][1] >= n and m["box"][2] <= w and m["box"][3] >= e):
        return False
    try:
        tao.verify(tdir)
    except ValueError:
        return False
    return True


def _gebco_cached(path: pathlib.Path) -> bool:
    """The GEBCO cut exists and its raster still has the SHA-256 recorded at download (bathy.from_gebco)."""
    try:
        bathy.from_gebco(path)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False
    return True


def s_ingest(ctx: Context, L: Ledger) -> None:
    """Everything the mission needs from outside, each fetched only if not cached and good: orca (WRF + UMWM), TAO/TRITON, GEBCO, and the
    GOFS 3.1 ocean store (about 2 h for the demo box). CAFE_OFFLINE downloads nothing and fails a check naming the command instead."""
    from .env import surface, tao
    m = ctx.mission
    t0, t1 = utc(m["window"]["start"]), utc(m["window"]["end"])
    b = m["box"]
    pad = padding(m)
    if "pad_deg" not in b:
        L.note(f"box.pad_deg is not set by the mission: sized {pad:g} deg from the window ({(t1 - t0).total_seconds() / 86400:.1f} d) x {DRIFT_MS} m/s, "
               f"at most {MAX_PAD_DEG:g}; a vehicle that drifts farther leaves the data (fail mode left_data): set pad_deg")
    box = (b["lon_min"] - pad, b["lon_max"] + pad, b["lat_min"] - pad, b["lat_max"] + pad)
    sbox = ocean_box(ctx.mission)
    man = ctx.cache / "orca" / "manifest.json"

    uas_v = [v for v in m["vehicles"] if ctx.classes[v["id"]] == "uas"]
    h3 = sorted({h for v in uas_v for h in _sortie_hours(v, m["ship"]["lon"], t0, t1)})

    def fetch_orca() -> int:
        """-> the number of parts it had to fetch (orca.ingest logs it; the manifest does not say)."""
        lines: list[str] = []

        def log(line: str) -> None:
            lines.append(line)
            ctx.log(line)
        orca.ingest(t0.replace(tzinfo=None), t1.replace(tzinfo=None), box, ctx.cache / "orca", hours3d=h3, log=log)
        return int(next((m.group(1) for m in map(re.compile(r"fetching (\d+) with").search, lines) if m), 0))

    def orca_covers() -> bool:
        return man.exists() and _orca_covers(json.loads(man.read_text()), t0, t1, box, h3)

    if orca_covers():
        ctx.log(f"ingest: orca cache {man.parent} covers the window, the box and the 3-D hours")
    tdir, spec = DATA / "tao", m["environment"]["ocean"]
    gebco = bathy.cache_path(sbox, ocean_mod.DATA / "bathy")
    store = ocean_mod.store_path(spec, m["name"])
    steps = hycom.gofs_steps(t0.timestamp(), t1.timestamp())

    def fetch_ocean() -> None:
        if spec["source"] != "gofs31":
            raise ValueError(f"{store} is the lab's HYCOM, which this pipeline cannot download: write it with "
                             "`python -m cafe.pm ingest-ocean --mission M --path DIR --temperature-kind K`")
        hycom.fetch_gofs(sbox, t0.timestamp(), t1.timestamp(), store.parent, deadline_s=GOFS_DEADLINE_S, ncss=hycom.NCSS, dods=hycom.DODS,
                         name=store.stem)
    got = [_need(ctx, L, "orca", "the orca WRF/UMWM cache for the window", orca_covers, fetch_orca),
           _need(ctx, L, "tao", "the TAO/TRITON moorings for the box and window", lambda: _tao_cached(tdir, sbox, t0.timestamp(), t1.timestamp()),
                 lambda: tao.fetch_tao(sbox, t0.timestamp(), t1.timestamp(), tdir, base=tao.BASE)),
           _need(ctx, L, "gebco", "the GEBCO_2026 cut for the box", lambda: _gebco_cached(gebco),
                 lambda: bathy.fetch_gebco(sbox, gebco, bathy.GEBCO_URL)),
           _need(ctx, L, "ocean_store", f"the ocean store {store.name} for the box and window", lambda: _ocean_cached(store, sbox, steps), fetch_ocean,
                 hint=None if spec["source"] == "gofs31" else f"python -m cafe.pm ingest-ocean --mission {ctx.mission_path} --path <lab HYCOM dir> "
                                                                  "--temperature-kind <in_situ|potential>")]
    if not all(got):
        return                                                           # the failed checks above stop the stage
    d = json.loads(man.read_text())
    want = int((t1 - t0).total_seconds() // 3600) + 1
    L.input(d["base"], sha=None, kind="remote", note="orca UWIN-CM run (byte-range reads; per-hour npz cache)")
    L.input(man, kind="orca cache manifest")
    L.input(store, sha=hycom.open_store(store).attrs.get("manifest_sha256"), kind="ocean store (sha256 of its parts manifest)")
    L.input(gebco, kind="GEBCO_2026 cut")
    L.check("orca_hours_cover_window", d["hours"] >= want, value=d["hours"], limit=want)
    key = digest(dict(orca=sha256(man), ocean=hycom.open_store(store).attrs.get("manifest_sha256"), gebco=sha256(gebco), code=ctx.code_digest))
    if not (_derived_current(ctx.cache, key) and _derived_span_problem(ctx.cache, ctx.window_s()) is None):      # about a minute; every code edit rebuilds it
        shutil.rmtree(ctx.cache / "derived.zarr", ignore_errors=True)
        ctx._env = None
        surface.build(ctx.env, ctx.cache, key, log=ctx.log)
        ctx._env = None                                                  # rebuild with the surface layer just written
    rec = json.loads((ctx.cache / surface.DIGEST).read_text())
    L.input(ctx.cache / "derived.zarr", sha=rec["store_sha256"], kind="derived surface layer (sha256 of every file of the store)")
    L.output(_dump(rec, ctx.path("ingest", surface.DIGEST)))
    oc = ocean(ctx)
    _ingest_checks(ctx, L, oc, sbox)
    L.output(man)
    _tao(ctx, L, t0.timestamp(), t1.timestamp())


OCEAN_SNAP_DEG = 0.1             # the ocean store is cut to its 0.08-0.1 degree grid, so its edge may sit this far inside the requested box


def mission_points(m: dict[str, Any]) -> list[tuple[str, float, float]]:
    """(label, lon, lat) of every place the mission puts something: the ship, each vehicle's deploy point, task waypoints and station."""
    pts: list[tuple[str, float, float]] = []
    if m.get("ship"):
        pts.append(("ship", m["ship"]["lon"], m["ship"]["lat"]))
    for v in m["vehicles"]:
        t = v.get("task", {})
        if "deploy" in v:
            pts.append((f"{v['id']} deploy", v["deploy"]["lon"], v["deploy"]["lat"]))
        pts += [(f"{v['id']} waypoint {k}", p[0], p[1]) for k, p in enumerate(t.get("waypoints", []))]
        if "lon" in t:
            pts.append((f"{v['id']} station", t["lon"], t["lat"]))
    return pts


def ocean_margins(ds: Any, sbox: tuple[float, float, float, float], pts: list[tuple[str, float, float]]) -> list[tuple[str, float]]:
    """How far inside the ocean store each requirement sits [deg, negative = outside]: the four edges of the (padded) mission box, and every
    mission point against all four edges of the store."""
    s, n, w, e = hycom.box360(sbox)
    la, lo = ds.lat.values, ds.lon.values
    out = [("box south edge", float(s - la.min())), ("box north edge", float(la.max() - n)), ("box west edge", float(w - lo.min())),
           ("box east edge", float(lo.max() - e))]
    for label, lon, lat in pts:
        x = float(cv.wrap360(lon))
        out.append((label, float(min(lat - la.min(), la.max() - lat, x - lo.min(), lo.max() - x))))
    return out


def _orca_covers(d: dict[str, Any], t0: dt.datetime, t1: dt.datetime, box: tuple[float, float, float, float], hours3d: list[dt.datetime]) -> bool:
    """The orca manifest covers the window, its recorded box contains `box` (lon_min, lon_max, lat_min, lat_max; a manifest with no box was
    written before the box was recorded and cannot say) and it has every 3-D hour wanted."""
    b = d.get("box")
    return bool(_covers(d, t0, t1) and b is not None and b[0] <= box[0] and b[1] >= box[1] and b[2] <= box[2] and b[3] >= box[3]
                and {orca.stamp(h) for h in hours3d} <= set(d.get("hours3d", [])))


def _sea_sample(env: GriddedEnv, n: int = 300) -> tuple[NDArray[np.intp], NDArray[np.intp], list[int]]:
    """About `n` UMWM sea nodes (lat index, lon index) and three time indices (first, middle, last hour) to test the cached fields on."""
    jj, ii = np.nonzero(env.sea)
    k = max(1, len(jj) // n)
    nt = len(env.tu.x)
    return jj[::k], ii[::k], sorted({0, nt // 2, nt - 1})


TP_LIMIT = 0.125                 # peak period: one frequency bin (the 37 UMWM bins are spaced 1.1225)
DIR_LIMIT_DEG = 11.25            # mean direction: one direction bin of the 32 UMWM bins
MSS_LIMIT = 0.5                  # 90th percentile of the slope variance's relative error: exact where the short-sea share is not clipped, 0.35 on the q2 data


def _spectrum_errors(env: GriddedEnv) -> dict[str, float]:
    """What `waves.spectrum_from_params` does not force to match the file, at the sampled sea nodes and hours (it renormalises to the file's swh
    on the grid it integrates on, so Hs agrees by construction and is not tested): the largest relative error of the synthesised peak period
    against `dwp`, the largest error [deg] of its energy-weighted mean direction against `dwd`, the 90th percentile of the relative error of its slope variance
    against `mss`, and the fraction of points where that error exceeds 1 % (the clip on the short-sea share bit). NaN where no point had a swell."""
    from .env import waves
    jj, ii, tis = _sea_sample(env)
    th = waves.theta_compass(env.spec["th"]) if env.spec is not None else np.arange(5.625, 360, 11.25)
    f = env.spec["f"] if env.spec is not None else 0.0313 * 1.12246 ** np.arange(37)
    df = f * np.gradient(np.log(f))
    tp_err: list[float] = []
    dir_err: list[float] = []
    mss_err: list[float] = []
    for ti in tis:
        g = {key: env.U[key][ti][jj, ii] for key in ("swh", "dwp", "dwd_e", "dwd_n", "mss", "wspd")}
        ok = np.isfinite(g["swh"]) & (g["swh"] > 1e-3) & np.isfinite(g["dwp"]) & (g["dwp"] > 0) & np.isfinite(g["mss"]) & (g["mss"] > 0)
        if not ok.any():
            continue
        dto = cv.math_rad_to_compass_to(np.arctan2(g["dwd_n"], g["dwd_e"]))[ok]
        E = waves.spectrum_from_params(g["swh"][ok], g["dwp"][ok], dto, g["mss"][ok], g["wspd"][ok], f, th)
        want = 1.0 / np.clip(1.0 / g["dwp"][ok], 1.2 * f[0], f[-1] / 2)                      # the period the synthesis puts its peak at
        tp_err += list(np.abs(1.0 / f[np.argmax(E.sum(-1), 1)] - want) / want)
        Ed = np.einsum("nft,f->nt", E, df)
        mean_dir = np.degrees(np.arctan2(Ed @ np.sin(np.radians(th)), Ed @ np.cos(np.radians(th))))
        dir_err += list(np.abs((mean_dir - dto + 180.0) % 360.0 - 180.0))
        mss_err += list(np.abs(waves.mean_square_slope(E, f, th) - g["mss"][ok]) / g["mss"][ok])
    if not tp_err:
        return dict(tp=np.nan, dir_deg=np.nan, mss_p90=np.nan, mss_clipped=np.nan, n=0)
    return dict(tp=float(np.max(tp_err)), dir_deg=float(np.max(dir_err)), mss_p90=float(np.percentile(mss_err, 90)),
                mss_clipped=float(np.mean(np.asarray(mss_err) > 0.01)), n=len(tp_err))


def _ustar_agreement(env: GriddedEnv) -> tuple[int, float, float]:
    """COARE u* (the surface layer built at ingest) against UMWM's `ust` at the sample: (points, median |dif|/ust, fraction within 20 %)."""
    sl = env.subgrid
    assert sl is not None, "ingest builds the surface layer before this check"
    jj, ii, tis = _sea_sample(env)
    lon, lat = env.lou.x[ii], env.lau.x[jj]
    rel: list[float] = []
    for ti in tis:
        t = np.full(lon.shape, env.tu.x[ti])
        ins = env.inside(lon, lat, t)
        a = np.asarray(sl.surface_layer(env, lon[ins], lat[ins], t[ins])["ustar"].value, np.float64)
        b = np.asarray(env.waves(lon[ins], lat[ins], t[ins])["ustar_umwm"].value, np.float64)
        good = np.isfinite(a) & np.isfinite(b) & (b > 1e-3)
        rel += list(np.abs(a[good] - b[good]) / b[good])
    r = np.asarray(rel)
    return int(r.size), float(np.median(r)) if r.size else float("nan"), float(np.mean(r <= 0.2)) if r.size else float("nan")


def _round_trip_errors(env: GriddedEnv, oc: Any) -> dict[str, float]:
    """Direction conventions out and back on three cached fields: wind (u, v -> compass -> u, v), waves (compass toward -> math radians -> compass)
    and the ocean current. Wind and current are m/s, waves degrees; each should be zero to rounding."""
    jj, ii, tis = _sea_sample(env)
    lon, lat = env.lou.x[ii], env.lau.x[jj]
    t = np.full(lon.shape, env.tu.x[tis[len(tis) // 2]])
    ins = env.inside(lon, lat, t)
    lon, lat, t = lon[ins], lat[ins], t[ins]

    def vec_err(v: Any) -> float:
        v = np.asarray(v, np.float64)
        v = v[np.isfinite(v).all(-1)]
        return float(np.max(np.abs(cv.vec_from_to(cv.speed(v), cv.to_deg(v)) - v))) if v.size else float("nan")
    d = np.asarray(env.waves(lon, lat, t)["dir_to"].value, np.float64)
    d = d[np.isfinite(d)]
    back = cv.math_rad_to_compass_to(cv.compass_to_to_math_rad(d))
    wave = float(np.max(np.abs((back - d + 180.0) % 360.0 - 180.0))) if d.size else float("nan")
    cur = vec_err(oc.current(lon, lat, np.zeros_like(lon), t).value) if oc is not None else float("nan")
    return dict(wind_ms=vec_err(env.u10(lon, lat, t)), wave_deg=wave, current_ms=cur)


def _ingest_checks(ctx: Context, L: Ledger, oc: Any, sbox: tuple[float, float, float, float]) -> None:
    """The BRIEF 5.5 ingest self-checks that the cached data can answer: the ocean store covers the box and every mission point; the time axes
    are hourly and gap-free; no NaN in sea cells; the spectrum synthesised from the file's parameters has the file's peak period, mean direction and
    slope variance (not swh, which it is forced to: that check could not fail); COARE u* against
    UMWM `ust` (logged); the temperature kind flag; direction conventions round-trip; every mission point is inside the cached grids."""
    m, env = ctx.mission, ctx.env
    margins = ocean_margins(oc.ds, sbox, mission_points(m)) if oc is not None else []
    worst = min(margins, key=lambda x: x[1]) if margins else None
    tight = "no ocean store" if worst is None else f"tightest is {worst[0]} ({worst[1]:+.3f} deg inside the store; grid snap {OCEAN_SNAP_DEG} deg)"
    L.check("ocean_source_covers_box", worst is not None and worst[1] >= -OCEAN_SNAP_DEG, value=None if worst is None else round(worst[1], 4),
            limit=-OCEAN_SNAP_DEG, note=f"{m['environment']['ocean']}: {tight}")
    pts = mission_points(m)
    out = [lab for lab, lo, la in pts if not bool(env.inside(lo, la))]
    L.check("mission_points_inside_cached_grids", not out, value=len(out), limit=0,
            note=("outside the WRF/UMWM grids: " + ", ".join(out)) if out else f"{len(pts)} points")
    gaps = np.concatenate([np.diff(a.x) for a in (env.tw, env.tu)])
    gap = float(np.abs(gaps - 3600.0).max(initial=0.0))
    L.check("time_axes_hourly_gap_free", gap < 1.0, value=gap, limit=1.0, note="largest departure of a WRF or UMWM time step from 3600 s")
    nan = sum(int((np.isnan(a) & env.sea).sum()) for a in env.U.values()) + sum(int(np.isnan(a).sum()) for a in env.W.values())
    L.check("no_nan_in_sea_cells", nan == 0, value=nan, limit=0, note="NaN values in UMWM sea nodes and in the WRF fields")
    sp = _spectrum_errors(env)
    where = f"spectrum_from_params at {sp['n']} sampled sea points against the file's dwp / dwd / mss (Hs is forced to the file's swh, so it is not a test)"
    L.check("spectrum_peak_period_vs_file", bool(sp["tp"] <= TP_LIMIT), value=None if np.isnan(sp["tp"]) else sp["tp"], limit=TP_LIMIT,
            note=f"largest relative error of the synthesised peak period; {where}")
    L.check("spectrum_direction_vs_file", bool(sp["dir_deg"] <= DIR_LIMIT_DEG), value=None if np.isnan(sp["dir_deg"]) else sp["dir_deg"], limit=DIR_LIMIT_DEG,
            note=f"largest error of the synthesised mean direction [deg]; {where}")
    L.check("spectrum_mss_vs_file", bool(sp["mss_p90"] <= MSS_LIMIT), value=None if np.isnan(sp["mss_p90"]) else sp["mss_p90"], limit=MSS_LIMIT,
            note="90th percentile of the relative error of the synthesised slope variance; the short-wave share is clipped (slope variance then off by "
                 f"more than 1 %) at {sp['mss_clipped']:.1%} of the points; {where}")
    n, med, frac = _ustar_agreement(env)
    L.check("coare_ustar_vs_umwm_ust", n > 0 and bool(np.isfinite(med)), value=None if not n else round(frac, 4),
            note=f"{n} sampled sea points: median |COARE u* - UMWM ust| / ust = {med:.3f}, {frac:.1%} within 20 %; BRIEF 5.5 asks that the agreement is logged")
    kind = None if oc is None else oc.ds.attrs.get("temperature_kind")
    gofs = m["environment"]["ocean"]["source"] == "gofs31"
    L.check("ocean_temperature_kind_flag", kind in hycom.KINDS and (not gofs or kind == "in_situ"), value=kind,
            note="the store's temperature_kind attribute (GOFS 3.1 GLBy writes in-situ); the values themselves are not tested against it")
    rt = _round_trip_errors(env, oc)
    L.check("direction_round_trip", all(bool(v <= 1e-6) for v in rt.values()), value=rt, limit=1e-6,
            note="wind, wave and current directions out to compass and back at sampled points")


def _wind_residuals(wrf: dict[str, Any], moor: dict[str, Any]) -> dict[str, NDArray[np.float64]]:
    """Per mooring the hourly series `tao.compare` pools (same lift to 10 m, same +-30 min means, same 1 m/s floor for directions): (n, 2) =
    wind speed [m/s] and meteorological direction [deg, wrapped to +-180] of model minus mooring, NaN where the mooring has no usable sample."""
    from .env import tao
    out: dict[str, NDArray[np.float64]] = {}
    for name in sorted(set(wrf) & set(moor)):
        m, w = moor[name], wrf[name]
        if "wind" not in m:
            continue
        t, sp = m["wind"]["t"], np.hypot(m["wind"]["u"], m["wind"]["v"])
        use = all(k in m for k in ("airt", "rh", "sst"))
        air: dict[str, Any] | None = None
        if use:
            air = {k: np.interp(t, m[v]["t"], m[v]["value"]) for k, v in (("t", "airt"), ("rh", "rh"), ("sst", "sst"))}
            air.update(p=101000.0, lat=m["lat"])
        s10 = tao.wind_to_10m(sp, m["wind"]["z"], "coare" if use else "log", air)
        k = np.where(sp > 0, s10 / np.where(sp > 0, sp, 1.0), 1.0)
        tt = np.asarray(w["t"], float)
        tv = np.column_stack([tao._bin(t, m["wind"]["u"] * k, tt), tao._bin(t, m["wind"]["v"] * k, tt)])
        wv = np.asarray(w["wind10"], float)
        ok = np.isfinite(wv).all(1) & np.isfinite(tv).all(1)
        ws, ts = cv.speed(wv), cv.speed(tv)
        fast = ok & (ws >= 1.0) & (ts >= 1.0)
        out[name] = np.column_stack([np.where(ok, ws - ts, np.nan), np.where(fast, tao._wrap(cv.from_deg(wv) - cv.from_deg(tv)), np.nan)])
    return out


def fit_wind_error(series: dict[str, NDArray[np.float64]]) -> dict[str, float] | None:
    """Split the hourly model-minus-mooring error of one wind quantity into what Stage 1 can hold fixed per member and what it cannot.
    `series`: mooring -> hourly residuals (NaN gaps). persistent: the predictive sd of the error at a new site (random effects): the variance of
    the moorings' time-mean errors across moorings, less the mean sampling variance of those means (s^2 / n x (1 + rho) / (1 - rho) for an AR(1)
    series) and floored at 0, plus the variance of the fitted mean (var(means) / k for k moorings), so it is 0 only when every mean is equal.
    noise: the pooled sd of the residuals about each mooring's own mean; tau_h: its e-folding time from the lag-1 autocorrelation rho of those
    residuals (0 when rho <= 0, rho capped at 0.999).
    persistent_hi95: the same with the between-mooring variance at its 95 % one-sided upper bound ((k - 1) var / chi2_0.05(k - 1)): the data cannot
    exclude a persistent sd that large (with 11 moorings the point estimate can sit at the floor of 0 and the bound is still several tenths of a m/s).
    None when fewer than two moorings have 3 or more samples (the dispersion between moorings is then not defined)."""
    kept = [x for x in series.values() if np.isfinite(x).sum() >= 3]
    if len(kept) < 2:
        return None
    means = np.array([np.nanmean(x) for x in kept])
    n = np.array([np.isfinite(x).sum() for x in kept], float)
    s2 = np.array([np.nansum((x - m) ** 2) / (k - 1) for x, m, k in zip(kept, means, n, strict=True)])
    num = den0 = den1 = 0.0
    for x, m in zip(kept, means, strict=True):
        a, b = x[:-1] - m, x[1:] - m
        both = np.isfinite(a) & np.isfinite(b)
        num, den0, den1 = num + float(a[both] @ b[both]), den0 + float(a[both] @ a[both]), den1 + float(b[both] @ b[both])
    rho = float(np.clip(num / np.sqrt(den0 * den1), 0.0, 0.999)) if den0 > 0 and den1 > 0 else 0.0
    sampling = float(np.mean(s2 / n * (1 + rho) / (1 - rho)))
    between = float(np.var(means, ddof=1))
    hi = between * (len(kept) - 1) / float(chi2.ppf(0.05, len(kept) - 1))                       # 95 % one-sided upper bound of the between-mooring variance
    return dict(persistent=float(np.sqrt(max(between - sampling, 0.0) + between / len(kept))),
                persistent_hi95=float(np.sqrt(max(hi - sampling, 0.0) + hi / len(kept))), noise=float(np.sqrt(np.average(s2, weights=n - 1))),
                tau_h=0.0 if rho <= 0 else float(-1.0 / np.log(rho)), rho=rho, moorings=float(len(kept)))


def _tao(ctx: Context, L: Ledger, t0: float, t1: float) -> None:
    """Data validation (BRIEF 5.4): WRF 10 m wind and SST against the TAO/TRITON moorings in the box, hourly, model minus
    mooring. The wind error is split (`fit_wind_error`) into a persistent part per member (the wind bias priors) and a short-lived AR(1) part
    (`wind_speed_noise`, `wind_direction_noise`), written to ingest/priors_fitted.json; without moorings the perturbations.yaml priors stand
    and the ledger says so. With fewer than two moorings the split is not defined: the whole hourly misfit is then the persistent sd."""
    from .env import tao
    tdir = DATA / "tao"
    if not (tdir / "manifest.json").is_file():
        L.note(f"no TAO/TRITON download at {tdir}: wind priors stay the perturbations.yaml defaults (run `make fetch`)")
        return
    L.input(tdir / "manifest.json")
    moor = tao.load_tao(tdir, t0, t1)
    hours = np.arange(t0, t1 + 1, 3600.0)
    wrf = {}
    for name, m in moor.items():
        if ctx.env.inside(m["lon"], m["lat"]):
            lo, la = np.full(hours.size, float(m["lon"])), np.full(hours.size, float(m["lat"]))
            wrf[name] = dict(t=hours, wind10=ctx.env.u10(lo, la, hours), sst=ctx.env.sst(lo, la, hours).value)
    cmp = tao.compare(wrf, moor)
    n = len([k for k in cmp if k != "ALL"])
    L.check("tao_moorings_compared", n > 0, value=n, limit=1, note="moorings with usable wind in the window")
    L.output(_dump(cmp, ctx.path("ingest", "tao_compare.json")))
    if not n:
        return                                                           # the failed check above stops the stage
    a = cmp["ALL"]
    cite = f"TAO/TRITON fit (BRIEF 5.4): WRF minus {n} moorings, hourly, {ctx.mission['window']['start']}..{ctx.mission['window']['end']}"
    res = _wind_residuals(wrf, moor)
    sp, dr = (fit_wind_error({k: v[:, j] for k, v in res.items()}) for j in (0, 1))
    pooled = (float(np.sqrt(max(a["speed_rmse"] ** 2 - a["speed_bias"] ** 2, 0.0))), float(np.sqrt(max(a["dir_rmse_deg"] ** 2 - a["dir_bias_deg"] ** 2, 0.0))))
    fit: dict[str, Any] = {}
    said: list[str] = []
    for key, unit, mean, split, hourly in (("speed", "m/s", -a["speed_bias"], sp, pooled[0]), ("direction", "deg", -a["dir_bias_deg"], dr, pooled[1])):
        if split is None:
            how = f"fewer than 2 moorings, so the whole hourly misfit ({hourly:.3g} {unit}) is held as one persistent error"
        else:
            how = (f"persistent part only: the between-mooring spread of the time-mean error less its sampling variance, plus the uncertainty "
                   f"of the mean of {n} moorings; the hourly rest is wind_{key}_noise")
        value = hourly if split is None else split["persistent"]
        fit[f"wind_{key}_bias"] = dict(dist="normal", mean=mean, value=value, unit=unit, citation=f"{cite}; {how}", kind="data")
        if split is not None:
            fit[f"wind_{key}_bias"].update(value_hi95=split["persistent_hi95"], citation_hi95="95 % upper bound of the between-mooring variance, "
                                           f"{int(split['moorings']) - 1} degrees of freedom")
        said.append(f"{key} persistent {value:.3g} {unit}")
        if split is not None:
            fit[f"wind_{key}_noise"] = dict(dist="normal", value=split["noise"], tau_h=split["tau_h"], unit=unit, kind="data",
                                            citation=f"{cite}; hourly error about each mooring's own mean, AR(1) with e-folding time tau_h "
                                                     f"(lag-1 autocorrelation {split['rho']:.2f})")
            said[-1] += f", short-lived {split['noise']:.3g} {unit} (tau {split['tau_h']:.1f} h)"
    L.output(_dump(fit, ctx.path("ingest", "priors_fitted.json")))
    sig = {}
    if np.isfinite(a["sst_rmse"]):
        sig["sst_k"] = float(a["sst_rmse"])                              # WRF SST is frozen: its error against the moorings' SST is the 1-sigma
    t2 = _t2_rmse(ctx, moor, hours)
    if t2 is not None:
        sig["t2_k"] = t2
    if sig:
        L.output(_dump(sig, ctx.path("ingest", "env_sigmas_fitted.json")))
        ctx._env = None                                                  # rebuilt with these sigmas on next use (Context.env)
    L.note(f"env sigmas fitted from the moorings: {sig or 'none (no SST or AIRT in the window); config/assumptions.yaml stands'}")
    L.note("wind error split: " + "; ".join(said))


def _t2_rmse(ctx: Context, moor: dict[str, Any], hours: NDArray[np.float64]) -> float | None:
    """RMSE [K] of WRF T2 against the moorings' AIRT (+-30 min means, as tao.compare bins them) in the grid, pooled; None without any."""
    from .env import tao
    resid = []
    for m in moor.values():
        if "airt" in m and ctx.env.inside(m["lon"], m["lat"]):
            lo, la = np.full(hours.size, float(m["lon"])), np.full(hours.size, float(m["lat"]))
            r = np.asarray(ctx.env.air(lo, la, hours)["T2"].value, np.float64) - tao._bin(m["airt"]["t"], m["airt"]["value"], hours)
            resid.append(r[np.isfinite(r)])
    d = np.concatenate(resid) if resid else np.empty(0)
    return float(np.sqrt(np.mean(d ** 2))) if d.size else None


def _derived_current(cache: pathlib.Path, key: str | None = None) -> bool:
    """derived.zarr exists and has the layout this code reads (surface.LAYOUT_VERSION). With `key` (the hash of the cache files and the code, see
    s_ingest) it also was built from exactly that and its files still hash to what `build` recorded beside it."""
    from .env import surface
    p = cache / "derived.zarr" / "zarr.json"
    if not (p.exists() and json.loads(p.read_text()).get("attributes", {}).get("layout_version") == surface.LAYOUT_VERSION):
        return False
    if key is None:
        return True
    d = cache / surface.DIGEST
    rec = json.loads(d.read_text()) if d.is_file() else {}
    return bool(json.loads(p.read_text())["attributes"].get("built_from") == key and rec.get("built_from") == key
                and rec.get("store_sha256") == surface.store_sha256(cache / "derived.zarr"))


def _derived_span_problem(cache: pathlib.Path, window: tuple[float, float]) -> str | None:
    """Why the hourly fields of derived.zarr cannot serve `window` (the store would hold its edge value for the hours outside it), else None.
    One hour of slack, the step of the fields."""
    from .env import surface
    lo, hi = surface.store_span(cache)
    if lo > window[0] + 3600.0 or hi < window[1] - 3600.0:
        def f(t: float) -> str:
            return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
        return f"its hours span {f(lo)} to {f(hi)} UTC, the mission window is {f(window[0])} to {f(window[1])} UTC"
    return None


def _derived_unchanged(ctx: Context, L: Ledger) -> None:
    """The self-check of the stages that read the surface layer: the store now hashes to what ingest recorded (ingest/derived.digest.json, itself a
    ledger output of ingest), so a store edited, rebuilt or replaced since ingest fails the stage instead of feeding it."""
    from .env import surface
    if getattr(ctx.env, "subgrid", None) is None:                        # an environment without the layer (the analytic ones) reads nothing derived
        return
    rec, store = ctx.run_dir / "ingest" / surface.DIGEST, ctx.cache / "derived.zarr"
    if not rec.is_file():
        L.check("derived_unchanged", False, note=f"{rec} is missing: ingest did not record the surface layer this stage reads")
        return
    L.input(rec)
    want = json.loads(rec.read_text())["store_sha256"]
    have = surface.store_sha256(store) if store.is_dir() else None
    L.check("derived_unchanged", have == want, value=have, limit=want, note=f"{store} hashes to what ingest recorded" if have == want
            else f"{store} is not what ingest recorded (edited or rebuilt since): rerun `python -m cafe.pm fetch` and the run")


def _covers(d: dict[str, Any], t0: dt.datetime, t1: dt.datetime) -> bool:
    def f(s: str) -> dt.datetime:
        return utc(s.replace(" ", "T") + ("" if s.endswith("Z") else "Z"))
    return f(d["t0"]) <= t0 and f(d["t1"]) >= t1


def _sortie_hours(v: dict[str, Any], lon: float, t0: dt.datetime, t1: dt.datetime) -> list[dt.datetime]:
    """The whole UTC hours (naive) whose 3-D WRF fields a UAS's sorties read: from the hour of each launch to the hour after the sortie's hard stop
    (`duration_min` x the platform's `hard_stop_factor`, plus the minute of margin the turbulence box has), so a sortie that starts at :50 or lasts
    longer than an hour never leaves the 3-D fields for its last minutes."""
    from .config import load_platform
    hard = float(load_platform(v["platform"])["sortie"]["hard_stop_factor"]["value"])
    dur = 60.0 * v["sorties"].get("duration_min", 20) * hard
    out: set[dt.datetime] = set()
    for t in stage1.launch_times(v["sorties"], lon, t0.timestamp(), t1.timestamp(), dur):
        h0, h1 = int(np.floor(t / 3600)), int(np.floor((t + dur + 60.0) / 3600)) + 1
        out |= {dt.datetime.fromtimestamp(h * 3600, dt.timezone.utc).replace(tzinfo=None) for h in range(h0, h1 + 1)}
    return sorted(out)


def s_hangar(ctx: Context, L: Ledger) -> None:
    """The vehicle numbers every stage uses, with the files they came from: each platform yaml through its own model's
    loader, which refuses a number without a source or an assumed + why. This stage runs no CFD, GCI or mesh study: no vehicle CAD exists here
    (QUESTIONS_FOR_LAB), so the "baseline model coefficients" Stage 1 and the refit start from are the analytic ones of the platform models
    (Seaglider force balance, `usv.hull_resistance`, the UAS drag area), not a RANS-with-GCI Hangar result."""
    from .config import PLATFORMS
    from .physics import glider, uas, usv
    loaders: dict[str, Callable[[str], Any]] = dict(glider=glider.load_platform, usv=usv.load_platform, uas=uas.load_platform)
    rows = {}
    for v in ctx.mission["vehicles"]:
        p = PLATFORMS / f"{v['platform']}.yaml"
        L.input(p)
        cls = ctx.classes[v["id"]]
        try:
            loaders[cls](v["platform"])
            err = ""
        except ValueError as e:
            err = str(e)
        L.check(f"provenance_{v['platform']}", not err, note=err)
        rows[v["id"]] = dict(platform=v["platform"], cls=cls, file=str(p), assumed=_assumed(__import__("yaml").safe_load(p.read_text())))
    L.note("no Hangar CFD run: the baseline model coefficients are analytic (no vehicle CAD, QUESTIONS_FOR_LAB); no GCI, observed order or mesh quality exists "
           "to check; the cache key is each platform file's sha-256 (a ledger input)")
    L.output(_dump(rows, ctx.path("hangar", "hangar.json")))


def _assumed(node: Any) -> int:
    """Number of leaves marked assumed: true in a parsed platform yaml."""
    if isinstance(node, dict):
        return int(node.get("assumed") is True) + sum(_assumed(v) for v in node.values())
    return sum(_assumed(v) for v in node) if isinstance(node, list) else 0


def _lenient(env: Any) -> Any:
    """`env.lenient()` (edge values outside the cached box, so a member that leaves is recorded as `left_data` and the run goes on), or nothing for
    an environment that has no box (the analytic ones)."""
    return env.lenient() if hasattr(env, "lenient") else contextlib.nullcontext()


def res_bytes(res: Any) -> bytes:
    """`res` pickled without the memo: the bytes follow the values alone, never which equal objects happen to be one object (a vehicle run in a
    stage-1 worker comes back with its own copies of the key strings a one-process run shares), so res.pkl hashes the same on any number of workers."""
    f = io.BytesIO()
    p = pickle.Pickler(f, protocol=pickle.HIGHEST_PROTOCOL)
    p.fast = True
    p.dump(res)
    return f.getvalue()


def _stage1(ctx: Context, L: Ledger, name: str, scales: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> None:
    """`extra`: fields added to the stage's summary.json (stage 1b records `refit_iterations_performed`)."""
    a = time.time()
    fp = ctx.run_dir / "ingest" / "priors_fitted.json"
    fitted = json.loads(fp.read_text()) if fp.is_file() else None
    if fitted:
        L.input(fp)
    with _lenient(ctx.env):
        r = stage1.run(ctx.mission, ctx.env, ctx.plan, L, log=ctx.log, scales=scales, fitted=fitted)
    r.update(extra or {})
    L.seed("mission", ctx.mission["seed"])
    L.note(f"{r['n']} members in {time.time() - a:.0f} s; certify possible: {r['certify']} (n_certify {r['n_certify']})")
    _stage1_checks(ctx, L, r)
    res = r.pop("res")
    for v in res["vehicles"].values():
        v.pop("sim", None)
        v.pop("wall_s", None)                                            # a timing: res.pkl is hashed (the report's receipts) and must not carry it
    ctx.path(name, "res.pkl").write_bytes(res_bytes(res))
    L.output(ctx.path(name, "res.pkl"))
    L.output(_dump(r, ctx.path(name, "summary.json")))


def _stage1_checks(ctx: Context, L: Ledger, r: dict[str, Any]) -> None:
    """The BRIEF 5.5 stage-1 self-checks on the finished ensemble: size (>= 73 unless the budget cannot reach it, which the report then says),
    sampled marginals against the intended ones, common random numbers (the hypercube is regenerated from the seed, and the stream seeds stage 1
    used are the same for every vehicle), that every member that left the downloaded box was flagged, the Wilson interval arithmetic against
    statsmodels, and which failure modes each vehicle recorded."""
    from statsmodels.stats.proportion import proportion_confint
    from .stats import intervals, sampling
    res, n, seed = r["res"], r["n"], int(ctx.mission["seed"])
    L.check("ensemble_size", r["certify"] or ctx.plan["n_max"] < r["n_certify"], value=n, limit=r["n_certify"],
            note="below the certifying size only because the budget cannot reach it: the report says it cannot certify < 5 %")
    batch = ctx.plan["batch"]
    ks = sampling.marginal_report({k: res["X"][k] for k in r["priors"] if k in res["X"]}, r["priors"])
    L.check("sampled_marginals_match_priors", max(ks.values(), default=0.0) <= 1.0 / batch + 1e-9, value=max(ks.values(), default=0.0), limit=1.0 / batch,
            note="largest Kolmogorov-Smirnov distance of a sampled column from its prior; each batch is a Latin hypercube, so <= 1 / batch")
    _, x0 = sampling.lhs(batch, r["priors"], np.random.SeedSequence([seed, 0]), antithetic=tuple(a for a in stage1.ANTITHETIC if a in r["priors"]))
    same = all(np.array_equal(x0[k], res["X"][k][:batch]) for k in x0)
    bad = _stream_seed_problems(ctx, res, seed, batch, n)
    L.check("common_random_numbers", same and not bad, value=same,
            note=("; ".join(bad) if bad else "the first batch's draws are regenerated from the seed; the stream seeds stage 1 used are the same for every "
                  "vehicle and are member_seed(seed, first member of a batch, stream). Streams drawn once per batch (UAS turbulence, gusts, Iridium) depend "
                  f"on the batch size, {batch} here (PHYSICS 13.2)"))
    _members_inside_data(ctx, L, res)
    kn = [(int(stage1.failed(v).sum()), len(stage1.failed(v))) for v in res["vehicles"].values()]
    kn += [(int((~np.asarray(v["success"], bool)).sum()), len(v["success"])) for v in res["links"].values()]
    kn += [(0, n), (n, n)]
    diff = max(abs(a - b) for k, m in kn for c in (0.9, 0.95)
               for a, b in zip(intervals.interval(k, m, c)[:2], proportion_confint(k, m, 1 - c, method="wilson"), strict=True))
    L.check("wilson_matches_statsmodels", diff <= 1e-9, value=diff, limit=1e-9,
            note=f"interval() against statsmodels' Wilson at 90 % and 95 %, for the {len(kn)} (k, n) of this run")
    modes = {vid: {k: int(np.sum(x)) for k, x in v["fail"].items()} for vid, v in res["vehicles"].items()}
    recorded = all(m and all(len(x) == n for x in v["fail"].values()) for m, v in zip(modes.values(), res["vehicles"].values(), strict=True))
    L.check("failure_modes_recorded", recorded, value=sum(map(len, modes.values())), note="modes recorded per member; counts: " + json.dumps(modes))


def _seed_list(v: Any) -> list[int]:
    """One stream's seed or seeds (an int, a numpy scalar, a list or an array) as sorted Python ints; they exceed 2^63, which numpy floats would round."""
    v = v.tolist() if hasattr(v, "tolist") else v
    return sorted({int(x) for x in (v if isinstance(v, (list, tuple, set)) else [v])})


def _stream_seed_problems(ctx: Context, res: dict[str, Any], seed: int, batch: int, n: int) -> list[str]:
    """Common random numbers across vehicles, from the seeds stage 1 actually used (`res["seeds"][vehicle][stream]`): every vehicle's streams are
    the same, and each is member_seed(seed, first member of one of the batches, stream). A per-vehicle seed creeping in fails both."""
    from .stats import sampling
    seeds = res.get("seeds") or {}
    norm = {vid: {k: _seed_list(v) for k, v in d.items()} for vid, d in seeds.items()}
    if not norm:
        return ["stage 1 returned no stream seeds (res['seeds']), so the streams cannot be compared"] if _has_streams(ctx) else []
    vids = list(norm)
    bad = [f"{vid}'s stream seeds differ from {vids[0]}'s" for vid in vids[1:] if norm[vid] != norm[vids[0]]]
    for stream, got in norm[vids[0]].items():
        allowed = {sampling.member_seed(seed, f, stream) for f in range(0, n, batch)}
        if not set(got) <= allowed:
            bad.append(f"stream {stream}: seed {got} is not member_seed(seed, first member of a batch, stream)")
    return bad


def _has_streams(ctx: Context) -> bool:
    """The mission draws per-batch random streams: a UAS (turbulence, gusts) or an Iridium link."""
    return "uas" in ctx.classes.values() or any(lk["kind"] == "iridium" for lk in ctx.mission["links"])


def _members_inside_data(ctx: Context, L: Ledger, res: dict[str, Any]) -> None:
    """Which (vehicle, member) pairs have a record outside the downloaded box, recomputed from the stored tracks with `env.inside`, against the
    members stage 1 flagged as fail mode `left_data`. A member that leaves is a failed member of the verdict (and the report names the mode), the
    run goes on; this check fails only when one left and was not flagged, i.e. when the verdict would silently count edge-held values as data.
    value = the fraction of pairs that stayed inside (limit 1.0: below it, the box or `pad_deg` is too small for the window)."""
    inside = getattr(ctx.env, "inside", None)
    left = flagged = missed = pairs = 0
    for v in res["vehicles"].values():
        lon = np.asarray(v["lon"], float)
        out = np.zeros(lon.shape[1], bool)
        if inside is not None:
            lat = np.asarray(v["lat"], float)
            out = (np.isfinite(lon) & np.isfinite(lat) & ~np.asarray(inside(lon, lat, np.asarray(v["t"], float)[:, None]))).any(0)
        flag = np.asarray(v["fail"].get("left_data", np.zeros(lon.shape[1], bool)), bool)
        pairs, left, flagged, missed = pairs + out.size, left + int(out.sum()), flagged + int(flag.sum()), missed + int((out & ~flag).sum())
    L.check("members_inside_data", missed == 0, value=round(1.0 - left / max(pairs, 1), 6), limit=1.0,
            note=f"{left} of {pairs} vehicle-members have a record outside the downloaded box, {flagged} are flagged left_data, {missed} left unflagged"
                 + ("; a flagged member counts as failed in the verdict: widen box / pad_deg and rerun" if left else ""))


def s_stage1(ctx: Context, L: Ledger) -> None:
    _derived_unchanged(ctx, L)
    _stage1(ctx, L, "stage1")


CRITERION = dict(glider="surface current speed [m/s] of the analysis field", usv="significant wave height Hs [m] of the analysis field",
                 uas="10 m wind speed [m/s] of the analysis field")
BASIS = {True: "analysis-field forcing at the failed members' tracks, before the member perturbations",
         False: "analysis-field forcing at all members' tracks, before the member perturbations"}
MIN_SEPARATION_S = 6 * 3600.0


def window_problems(t: NDArray[np.float64], worst: NDArray[np.float64], rows: list[dict[str, Any]], k: int) -> list[str]:
    """BRIEF 5.5: the chosen windows are the argmax of the stated criterion. Row j must be the strongest record at least 6 h from rows 0..j-1,
    must carry that record's stress, and fewer than `k` rows are allowed only when no such record is left."""
    bad: list[str] = []
    idx = [int(np.argmin(np.abs(t - w["t"]))) for w in rows]
    for j, i in enumerate(idx):
        free = np.isfinite(worst)
        for m in idx[:j]:
            free &= np.abs(t - t[m]) >= MIN_SEPARATION_S
        if not free[i] or worst[i] < worst[free].max():
            bad.append(f"window {j} at record {i} is not the strongest of the {int(free.sum())} records free of the earlier windows")
        if rows[j]["stress"] != worst[i]:
            bad.append(f"window {j}: stress {rows[j]['stress']} is not the record's {worst[i]}")
    left = np.isfinite(worst)
    for m in idx:
        left &= np.abs(t - t[m]) >= MIN_SEPARATION_S
    if len(rows) < k and left.any():
        bad.append(f"only {len(rows)} of {k} windows chosen but {int(left.sum())} records are free")
    return bad


def s_windows(ctx: Context, L: Ledger) -> None:
    """Worst windows per vehicle: the record times where the members that failed (or, with none failing, all members)
    met the strongest forcing (10 m wind for surface/air vehicles, Hs for the USV hull, current speed for gliders). A UAS is only
    in the air during its sorties and sits at the ship otherwise, so its windows are chosen among the records where a selected member is
    airborne (all records, said so in the window and the ledger, when none is)."""
    res = pickle.loads(ctx.path("stage1", "res.pkl").read_bytes())
    L.input(ctx.path("stage1", "res.pkl"))
    _derived_unchanged(ctx, L)
    K = ctx.plan["les"]["windows_per_vehicle"]
    out: dict[str, list[dict[str, Any]]] = {}
    problems: list[str] = []
    for vid, r in res["vehicles"].items():
        f = stage1.failed(r)
        sel = f if f.any() else np.ones_like(f)
        t = np.asarray(r["t"])
        lon, lat = np.asarray(r["lon"])[:, sel], np.asarray(r["lat"])[:, sel]
        tt = np.broadcast_to(t[:, None], lon.shape)
        ok = np.isfinite(lon)
        records = "all records"
        if r["class"] == "uas" and "airborne" in r:
            air = np.asarray(r["airborne"], bool)[:, sel]
            if (ok & air).any():
                ok &= air
                records = "airborne records"
            else:
                records = "all records (no selected member is airborne at any record)"
                L.note(f"{vid}: {records}")
        if not ok.any():
            out[vid] = []
            continue
        stress = np.full(lon.shape, -np.inf)
        if r["class"] == "glider":
            c = ctx.env.current(lon[ok], lat[ok], np.zeros(ok.sum()), tt[ok])
            stress[ok] = np.hypot(*np.moveaxis(np.asarray(c.value, np.float64), -1, 0))
        elif r["class"] == "usv":
            stress[ok] = np.nan_to_num(ctx.env.waves(lon[ok], lat[ok], tt[ok])["Hs"].value)
        else:
            stress[ok] = np.hypot(*np.moveaxis(np.asarray(ctx.env.u10(lon[ok], lat[ok], tt[ok]), np.float64), -1, 0))
        worst = np.nanmax(stress, 1)
        idx: list[int] = []
        for i in np.argsort(-worst):                                     # K windows at least 6 h apart
            if np.isfinite(worst[i]) and all(abs(t[i] - t[j]) >= MIN_SEPARATION_S for j in idx):
                idx.append(int(i))
            if len(idx) == K:
                break
        lon_ok, lat_ok = np.where(ok, lon, np.nan), np.where(ok, lat, np.nan)
        first = np.array([np.asarray(x, float) for x in r["first"].values()])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # the failure instants of the selected members
            failed_at = sorted(float(x) for x in np.nanmin(first, 0)[f] if np.isfinite(x)) if f.any() else []
        out[vid] = [dict(t=float(t[i]), stress=float(worst[i]), lon=float(np.nanmedian(lon_ok[i])), lat=float(np.nanmedian(lat_ok[i])),
                         basis=BASIS[bool(f.any())], criterion=CRITERION[r["class"]], records=records, failed_at=failed_at) for i in idx]
        problems += [f"{vid}: {p}" for p in window_problems(t, worst, out[vid], K)]
    L.check("every_vehicle_has_a_window", all(out.values()), value=sum(map(len, out.values())))
    L.check("windows_are_the_argmax", not problems, value=len(problems), limit=0, note="; ".join(problems[:3]))
    L.output(_dump(out, ctx.path("windows", "windows.json")))


def use_run_calibration(ctx: Context, L: Ledger) -> None:
    """For the stages after stage 3: the sub-grid calibration is the run's own stage3/subgrid_calibration.json when stage 3 wrote one (a ledger input, so
    a resume sees it), else the shipped config/subgrid.json. The tracked file is never changed by a run (round 3 M-23)."""
    f = ctx.run_dir / "stage3" / "subgrid_calibration.json"
    if f.is_file():
        L.input(f)
    subgrid.use_calibration(json.loads(f.read_text()) if f.is_file() else None)


def s_stage3(ctx: Context, L: Ledger) -> None:
    from .stage3 import pipeline_windows
    wins = json.loads(ctx.path("windows", "windows.json").read_text())
    L.input(ctx.path("windows", "windows.json"))
    rows = pipeline_windows.run(ctx, wins, L)
    timing = {vid: [r.pop("timing", None) for r in rs] for vid, rs in rows.items()}      # seconds and measured rates: in the ledger, not in the hashed output
    L.note("window timings (not part of the hashed output): " + json.dumps(timing, default=ledger._jsonable))
    L.output(_dump(rows, ctx.path("stage3", "windows.json")))
    if ctx.run_dir.joinpath("stage3", "subgrid_calibration.json").is_file():
        L.output(ctx.run_dir / "stage3" / "subgrid_calibration.json")


def s_refit(ctx: Context, L: Ledger) -> None:
    from .stage3 import nest, refit
    rows = json.loads(ctx.path("stage3", "windows.json").read_text())
    L.input(ctx.path("stage3", "windows.json"))
    for tag, _ in nest.SPHERE_RUNS:                    # default_floor's discretisation floor reads these: a changed grid study reruns the refit
        for f in sorted(nest.SLOW_DIR.glob(f"nest_sphere_{tag}_d*.json")):
            L.input(f, kind="stored sphere grid study (the refit's discretisation floor)")
    out: dict[str, dict[str, Any]] = {}
    for vid, ws in rows.items():
        # Stage 1 has one drag multiplier per vehicle and it scales the water-side (or, for a UAS, the body) drag; a USV's wing is
        # a different flow, so its windows are pooled separately and reported, never mixed into the hull's multiplier. The multiplier
        # scales the VPP's whole through-water resistance (stage1.refit_drag: speed ~ drag^-1/2 at fixed force), so a USV's passing
        # free-surface windows (`hull_fs`: total resistance, wave-making included) set it when there are any, else its viscous `hull` windows
        main = next((p for p in ("hull_fs", "hull") if any(w.get("ok") and w.get("part") == p for w in ws)),
                    "hull" if any(w.get("part") == "hull" for w in ws) else "hull_fs" if any(w.get("part") == "hull_fs" for w in ws) else "body")
        good = [w for w in ws if w.get("ok") and w.get("part", main) == main]
        if ctx.plan["refit_iterations"] == 0:
            out[vid] = dict(used=False, reason="budget ci: no refit")
        elif not good:
            out[vid] = dict(used=False, reason=f"no {main} window passed its stage-3 self-checks; "
                                               "Stage 1 keeps the baseline model coefficients (analytic; no Hangar CFD run)",
                            failed_checks=sorted({c["name"] for w in ws for c in w.get("checks", []) if not c["ok"]}))
        else:
            out[vid] = dict(used=True, part=main, **refit.refit(good))      # each window against its own cd_hangar
        other = {w["part"] for w in ws if w.get("part", main) != main} if ctx.plan["refit_iterations"] else set()
        for part in sorted(other):
            pw = [w for w in ws if w.get("ok") and w.get("part") == part]
            why = {"hull": "the hull_fs windows (total resistance with the free surface) set the multiplier; this part has no wave-making",
                   "hull_fs": "no hull_fs window passed its checks: the viscous hull windows set the multiplier"}
            out[vid][f"{part}_not_used"] = dict(reason=why.get(part, "Stage 1 has no multiplier for this part"), **(refit.refit(pw) if pw else {}))
    for vid, o in out.items():
        if o["used"]:
            d = o["drag"]
            L.note(f"{vid}: drag multiplier {d['mean']:.3f} (change vs baseline model {d['change_vs_hangar']:+.1%}, "
                   f"sigma {d['sigma']:.3f} of which statistical "
                   f"{d['sigma_statistical']:.3f}) from {d['windows']} window(s)")
    L.check("refit_uses_only_windows_that_passed", all(not v["used"] or v.get("drag", {}).get("windows", 0) > 0 for v in out.values()))
    L.output(_dump(out, ctx.path("refit", "refit.json")))


def _sensitivity_cases(ctx: Context, L: Ledger, scales: dict[str, Any]) -> None:
    """The USV verdict again under the brief's literal VPP bias (stage1.BRIEF_PRIOR, DECISIONS 163), paired with the main one: the run's own
    hypercube (`res["X"]`, so the same members, the same n and the same other inputs) with only the `usv_vpp_bias` column replaced, same seed and
    refit multipliers, written to stage1b/sensitivity_cases.json for the report to show next to the calibrated verdict. Nothing is written for a
    mission without a USV."""
    if not any(stage1._classes(ctx.mission)[v["id"]] == "usv" for v in ctx.mission["vehicles"]):
        return
    fp = ctx.run_dir / "ingest" / "priors_fitted.json"
    X = pickle.loads(ctx.path("stage1", "res.pkl").read_bytes())["X"]
    fitted = json.loads(fp.read_text()) if fp.is_file() else None
    with _lenient(ctx.env):
        cases = stage1.sensitivity_case(ctx.mission, ctx.env, stage1.BRIEF_PRIOR, len(next(iter(X.values()))), fitted, scales or None, X=X)
    out = ctx.path("stage1b", "sensitivity_cases.json")
    out.write_text(json.dumps(ledger.clean(cases), indent=1, sort_keys=True, allow_nan=False))
    L.output(out)
    L.note("sensitivity case (brief VPP bias, same members and inputs, only usv_vpp_bias replaced): "
           + "; ".join(f"{v} {c[0]['k_fail']} of {c[0]['n']} {c[0]['verdict']}" for v, c in cases.items()))


def s_stage1b(ctx: Context, L: Ledger) -> None:
    """Stage 1 again with the refit multipliers, once (the brief's refit loop to convergence, capped at `refit_iterations`, is not implemented: the
    refit needs usable stage-3 windows, which a CPU run does not have). The summary records `refit_iterations_performed`: 0 (stage 1 copied) or 1."""
    from .stage3 import refit as refit_mod
    ref = json.loads(ctx.path("refit", "refit.json").read_text())
    L.input(ctx.path("refit", "refit.json"))
    L.input(ctx.path("stage1", "res.pkl"))
    _derived_unchanged(ctx, L)
    scales = {vid: r for vid, r in ref.items() if r["used"]}
    use_run_calibration(ctx, L)
    recal = (ctx.run_dir / "stage3" / "subgrid_calibration.json").is_file()
    _sensitivity_cases(ctx, L, scales)
    done = int(bool(scales))
    cap = min(ctx.plan["refit_iterations"], refit_mod.MAX_ITER)
    L.check("refit_iterations_within_cap", done <= cap, value=done, limit=cap,
            note="refit passes performed (a single pass: stage 1 reran once with the multipliers, no loop to convergence); "
                 f"the plan allows {ctx.plan['refit_iterations']}, the refit module caps it at {refit_mod.MAX_ITER}")
    if not scales and not recal:
        L.note("no vehicle was refit: stage 1b is stage 1 (copied, not rerun)")
        shutil.copy(ctx.path("stage1", "res.pkl"), ctx.path("stage1b", "res.pkl"))
        L.output(ctx.path("stage1b", "res.pkl"))
        L.output(_dump(dict(json.loads(ctx.path("stage1", "summary.json").read_text()), refit_iterations_performed=0), ctx.path("stage1b", "summary.json")))
        return
    _stage1(ctx, L, "stage1b", scales=scales, extra=dict(refit_iterations_performed=done))      # a calibrated sub-grid layer reruns stage 1 even with no refit
    was, now = ({vid: v["verdict"] for vid, v in json.loads(ctx.path(st, "summary.json").read_text())["summary"]["vehicles"].items()}
                for st in ("stage1", "stage1b"))
    changes = refit_mod.verdict_changes(was, now)
    L.check("stage1b_same_vehicles_as_stage1", set(was) == set(now), value=len(changes), note="verdict changes after the refit: " + (
        "; ".join(f"{k}: {a} -> {b}" for k, a, b in changes) or "none (converged after one rerun)"))


def s_emulator(ctx: Context, L: Ledger) -> None:
    """The mission-level emulator (BRIEF 2.7): train on the training table as this stage found it (copied into the run and named as a ledger
    input, minus this run's own earlier rows) plus this run's per-vehicle Stage-1 rows and the rows of a few mission variants (deploy shifts,
    small moves, lower duty), fit one emulator per vehicle class when that is enough rows, score it on a 20 % hold-out, and search for the
    smallest change that flips each verdict that is not GO. Then append this run's rows to the shared table, after training, so that two
    runs from the same table make the same emulator. The number of variants is the plan's (plan.json emulator); the clock is only a kill
    that stops the variants at the stage's whole share. A variant that leaves the environment data is skipped, with the reason.
    Writes emulator/train_input, holdout.json, flip.json and design.json."""
    import pandas as pd

    from . import whatif
    res = pickle.loads(ctx.path("stage1b", "res.pkl").read_bytes())
    for p in (ctx.path("stage1b", "res.pkl"), ctx.path("stage1b", "summary.json"), ctx.path("refit", "refit.json")):
        L.input(p)
    _derived_unchanged(ctx, L)
    use_run_calibration(ctx, L)
    summ = json.loads(ctx.path("stage1b", "summary.json").read_text())["summary"]["vehicles"]
    refit = json.loads(ctx.path("refit", "refit.json").read_text())
    scales = {vid: r for vid, r in refit.items() if r["used"]}
    fp = ctx.run_dir / "ingest" / "priors_fitted.json"
    fitted = json.loads(fp.read_text()) if fp.is_file() else None
    pri, marg = stage1.priors_for(ctx.mission, fitted)
    seed = int(ctx.mission["seed"])
    fid = {vid: int(vid in scales) for vid in res["vehicles"]}
    meta = dict(run_id=digest(str(ctx.run_dir.resolve()))[:12], mission=ctx.mission["name"], git_sha=ledger.git_sha(), code_digest=ctx.code_digest)
    rows = whatif.vehicle_rows(ctx.mission, res, ctx.env, fid, meta)
    train_in, snap = whatif.snapshot(ctx.table, ctx.path("emulator", "train_input"), meta["run_id"])
    L.input(snap, kind="emulator training table at the start of this stage (minus this run's rows)", source=str(ctx.table), rows=len(train_in))
    sizes = budget.emulator_plan(ctx.plan)
    free = not scales and not ctx.run_dir.joinpath("stage3", "subgrid_calibration.json").is_file()      # stage 1b was a copy of stage 1
    share = budget.emulator_share_s(ctx.plan, stage1b_free=free)
    est = sizes["variant_s"]
    n_var = sizes["variants_refit" if scales else "variants_no_refit"]
    variants: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    killed: dict[str, Any] | None = None
    walls: list[float] = []
    mvs: dict[str, dict[str, Any]] = {}                                   # variant name -> its mission, for the fresh-draw check
    batch = ctx.plan["batch"]
    t0 = time.perf_counter()
    for k, mods in enumerate(whatif.design(ctx.mission, n_var, seed)):
        if time.perf_counter() - t0 > share:                              # the safety kill: the whole stage share is gone
            killed = dict(at_variant=k, planned=n_var, reason=f"killed: the variant runs spent the emulator stage's whole wall-clock share ({share:.0f} s) "
                                                              f"before variant v{k} of {n_var}")
            break
        a = time.perf_counter()
        mv = mvs[f"v{k}"] = whatif.apply(ctx.mission, mods)
        # its own members, not the baseline's 0..batch-1: the same members would give every training row the same hypercube and noise streams (round 3 M-4)
        vrows, why = whatif.run_variant(mv, ctx.env, list(range((k + 1) * batch, (k + 2) * batch)), seed, pri, marg, scales, fid, meta, f"v{k}")
        rows += vrows
        variants.append(dict(variant=f"v{k}", mods=mods, vehicles=sorted({r["vehicle"] for r in vrows}), skipped=why))
        skipped += [dict(variant=f"v{k}", vehicle=vid, reason=r) for vid, r in why.items()]
        walls.append(time.perf_counter() - a)
    spent = len(variants) * est                                           # charged at the planner's cost, as the flip search is
    train_df = whatif.with_rows(train_in, rows)
    df, used = whatif.add_rows(ctx.table, rows)                           # after the fit is decided: the table grows for the next run, not for this one
    L.note(f"training table {used}: {len(df)} rows now; this run trained on {len(train_df)} ({len(train_in)} from {snap.name}, {len(rows)} added by this run: "
           f"{len(res['vehicles'])} vehicles x {1 + len(variants)} missions less {len(skipped)} skipped)")
    L.note(f"emulator share {share:.0f} s ({'incl. stage 1b, which was a copy' if free else 'stage 1b reran'}): {len(variants)} variant run(s) of "
           f"{est:.0f} s each ({sizes['variant_s_source']}); measured {', '.join(f'{w:.0f}' for w in walls)} s (timings are not in the hashed output)")
    for sk in skipped:
        L.note(f"variant {sk['variant']} skipped for {sk['vehicle']}: {sk['reason']}")
    want = len(res["vehicles"]) * (1 + len(variants)) - len(skipped)
    L.check("emulator_rows_appended", len(rows) == want, value=len(rows), limit=want)
    wall = sum(walls)
    L.note(f"variant runs: planned {len(variants) * est:.0f} s ({len(variants)} x {est:.0f} s), measured {wall:.0f} s, "
           f"emulator share {share:.0f} s; the planned cost is a lower bound (plan.json stage1_s_basis) and only the kill before a variant holds "
           "the share (a look-ahead from measured seconds would make the number of variants depend on the clock)")
    L.d["variant_planned_s"], L.d["variant_wall_s"] = est, [round(w, 3) for w in walls]       # timings stay out of the hashed design.json (DECISIONS 139)
    if killed:
        L.note(killed["reason"])
    by_key = {r["key"]: r for r in rows if r["variant"] != "base"}        # the base rows are 3-D-wind UAS rows, the variants' are not: not comparable
    n_fresh: list[float] = []

    def fresh(row: Any) -> tuple[float, int] | None:
        """P(fail) of one held-out variant row again, on members no training row used (blocks after the variants'): the independent estimate."""
        r = by_key.get(row["key"])
        if r is None:                                                     # a row of another run: its mission is not here
            return None
        a = time.perf_counter()
        j = len(variants) + 2 + len(n_fresh)
        try:
            m = whatif.measure(mvs[r["variant"]], r["vehicle"], ctx.env, ctx.plan, pri, marg, scales, seed, members=list(range(j * batch, (j + 1) * batch)))
        except whatif.Invalid:
            return None
        n_fresh.append(time.perf_counter() - a)
        return m["p_fail"], m["n"]
    ems = whatif.train(ctx.table, [r["class"] for r in res["vehicles"].values()], df=train_df, fresh=fresh)
    if n_fresh:
        L.note(f"fresh-draw hold-out check: {len(n_fresh)} held-out variant point(s) re-run on members used nowhere else, "
               f"{sum(n_fresh):.0f} s (not part of the hashed output)")
    out = {vid: ems[r["class"]][1] for vid, r in res["vehicles"].items()}
    for cls, (em, info) in ems.items():
        if em is None:
            L.note(f"emulator for {cls} not trained (trained: false): {info['reason']}")
            continue
        a, h = info["acceptance"], info["rmse"]["p_fail"]
        fr = (f"; against {info['fresh_points']} held-out point(s) re-run on fresh members: {info['rmse_fresh']:.3f} as observed, "
              f"{info['rmse_fresh_debiased']:.3f} less their noise {info['noise_floor_fresh']:.3f}; the larger is judged" if info["fresh_points"] else
              "; no held-out point could be re-run on fresh members (none of this run's variants is among them), so only the in-sample score is judged")
        # BRIEF 2.7 acceptance is a statistical draw on 20 to 28 held-out points (a calibrated emulator misses the coverage gate by chance with
        # `coverage_chance_fail`), not a test of the code: noted here and in holdout.json, never a check that aborts the run. A class that missed is not used.
        met = {True: "met", False: "MISSED"}
        L.note(f"emulator {cls}: BRIEF 2.7 RMSE {met[a['rmse_ok']]}: {info['rmse_gate']:.3f} against the limit {whatif.LIMITS['rmse']}; "
               f"held-out RMSE of P(fail) "
               f"against the true P(fail): {h:.3f} as observed, less the targets' own Monte-Carlo noise {info['noise_floor_rmse']:.3f} in quadrature{fr}")
        L.note(f"emulator {cls}: BRIEF 2.7 coverage {met[a['coverage_ok']]}: {info['coverage']['p_fail']:.3f} against {info['nominal']:.2f} +- "
               f"{whatif.LIMITS['coverage']}; a calibrated emulator misses this by chance with probability {info['coverage_chance_fail']:.3f} on "
               f"{info['n_test']} held-out points")
        L.note(f"emulator {cls}: BRIEF 2.7 query time {met[a['query_ok']]}: {info['query_ms']:.2f} ms against the limit {whatif.LIMITS['query_ms']} ms")
        if not info["used"]:
            L.note(f"emulator {cls} not used for answers: {info['unused_reason']}")
        L.check(f"emulator_training_points_{cls}", info["points"] >= whatif.MIN_ROWS, value=info["points"], limit=whatif.MIN_ROWS,
                note=f"distinct feature points the {cls} emulator trained on ({info['rows']} rows)")
        row = next(r for r in rows if r["cls"] == cls)
        x = pd.Series({k: float(row[k]) for k in em.features})
        far = em.query(x + 1e6)
        L.check(f"emulator_range_guard_{cls}", far["status"] == "out_of_range", value=em.distance(x), limit=em.threshold,
                note="a mission 1e6 units from every training row is refused; value is this run's own baseline mission's nearest-neighbour "
                     "distance, limit the calibrated threshold")
    L.output(_dump(out, ctx.path("emulator", "holdout.json")))
    tracks = {vid: whatif.track_points(r, ctx.mission) for vid, r in res["vehicles"].items() if r["class"] != "uas"}
    flips, fspent = whatif.flip_search(ctx.mission, {vid: summ[vid]["verdict"] for vid in summ}, tracks, ctx.env, ems, ctx.plan, pri, marg, scales, seed,
                                       share - spent, ctx.log)
    L.note(f"flip search: {sum(f['found'] for f in flips.values())} of {len(flips)} non-GO vehicles flip; {fspent:.0f} s of Stage 1 (planned cost)")
    L.output(_dump(dict(vehicles=flips), ctx.path("emulator", "flip.json")))
    L.output(_dump(dict(share_s=share, variant_s=est, variant_planned_s=est, variant_s_source=sizes["variant_s_source"], variants=variants,
                        skipped=skipped, killed=killed, spent_s=spent, flip_spent_s=fspent, rows_added=len(rows), table_rows=len(train_df),
                        table=pathlib.Path(used).name, train_input_rows=len(train_in),
                        train_fraction=whatif.TRAIN_FRAC, planned_variants=n_var, stage1b_free=free), ctx.path("emulator", "design.json")))


def s_report(ctx: Context, L: Ledger) -> None:
    from . import report
    for st in ("stage1b", "refit", "stage3", "windows", "emulator"):
        for p in sorted(ctx.run_dir.joinpath(st).glob("*.json")):
            L.input(p)
    paths = report.write(ctx.run_dir, ctx.mission, ctx.plan, env=ctx.env)
    for p in paths:
        L.output(p)
    rep = json.loads(ctx.path("report", "report.json").read_text())
    bad = report.check_traceability(rep)
    L.check("report_traceable", not bad, value=len(bad), limit=0, note="; ".join(bad[:5]))
    bad = report.check_rendered(rep, ctx.path("report", "index.html").read_text())
    L.check("report_html_matches_json", not bad, value=len(bad), limit=0, note="; ".join(bad[:5]))


FUNCS = dict(ingest=s_ingest, hangar=s_hangar, stage1=s_stage1, windows=s_windows, stage3=s_stage3, refit=s_refit,
             stage1b=s_stage1b, emulator=s_emulator, report=s_report)
assert list(FUNCS) == STAGES


def run(mission_path: str | pathlib.Path, budget_name: str, gpus: int, run_dir: str | pathlib.Path, resume: bool = True, stop_after: str | None = None,
        log: Callable[[str], None] = print, seed: int | None = None, emulator_table: str | pathlib.Path | None = None,
        gpu_mem_gb: float | None = None) -> Context:
    """`stop_after="ingest"` is `fetch`: it plans nothing, so a mission no budget can run (30 days, 20 vehicles) still downloads."""
    fetch = stop_after == "ingest"
    ctx = Context(mission_path, None if fetch else budget_name, gpus, run_dir, log, seed, emulator_table, gpu_mem_gb,
                  hash_budget=budget_name if fetch else None)
    if not fetch:
        from .emulator import read_table, store_path
        table = store_path(ctx.table)[0]
        if table.exists():
            read_table(table)  # a corrupt shared table stops the run here (ConfigError), not at the emulator stage after the others
    shutil.copy(ctx.mission_path, ctx.path("mission.yaml"))
    if seed is not None:                                                  # the copy is what `report` and `whatif` reload: it must carry the seed that was run
        ctx.path("mission.yaml").write_text(re.sub(r"(?m)^seed:.*$", f"seed: {seed}", ctx.mission_path.read_text()))
    if ctx.plan:
        _dump(ctx.plan, ctx.path("plan.json"))
        log(budget.describe(ctx.plan))
    prev, redo = None, not resume
    n = int(ctx.plan.get("workers") or par.workers())                      # the planned count: the CPUs, or fewer when memory holds fewer
    log(f"workers: {n} (the CPUs this run may use, cut to what the memory holds; CAFE_WORKERS=N overrides)")
    with par.limit(n), par.Pool(n):                                     # one pool for every stage: each worker starts and compiles once
        for name in STAGES:
            lp = ctx.run_dir / "checkpoints" / name / "ledger.json"
            if not redo and ledger.done(ctx.run_dir, name, ctx.stage_hash(name)):
                log(f"{name}: up to date (ledger {lp})")
            else:
                a, redo = time.time(), True                                   # everything after a rerun stage reruns too
                with ledger.Ledger(ctx.run_dir, name, ctx.stage_hash(name), ctx.code_digest) as L:
                    if prev is not None:
                        L.input(prev)
                    FUNCS[name](ctx, L)
                log(f"{name}: done in {time.time() - a:.0f} s")
            prev = lp
            if name == stop_after:
                break
    return ctx
