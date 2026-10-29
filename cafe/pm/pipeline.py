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
    run_dir/emulator/holdout.json         emulator hold-out scores (members -> per-vehicle failure)
    run_dir/report/index.html, report.json
"""
import json, os, pathlib, pickle, shutil, time

import numpy as np

from . import budget, ledger, stage1
from .audit import STAGES
from .config import digest, env_sigmas, load_mission, utc

DATA = pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


def code_digest():
    """sha256 over the pipeline's code, config and platform files: a resumed stage is reused only if none changed."""
    import hashlib
    root = pathlib.Path(__file__).resolve().parents[2]
    h = hashlib.sha256()
    for p in sorted([*root.joinpath("cafe", "pm").rglob("*.py"), *root.joinpath("config").rglob("*.*"), *root.joinpath("platforms").glob("*.yaml")]):
        if "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode() + b"\0" + p.read_bytes())
    return h.hexdigest()


class Context:
    """What the stages share: the mission, the plan, where things live, and the environment (built once, lazily)."""

    def __init__(self, mission_path, budget_name, gpus, run_dir, log=print):
        self.mission_path = pathlib.Path(mission_path)
        self.mission = load_mission(mission_path)
        self.run_dir = pathlib.Path(run_dir)
        self.cache = DATA / "cache" / self.mission["name"]
        self.log = log
        self.classes = stage1._classes(self.mission)
        self.plan = budget.plan(budget_name, gpus, self.mission, vehicle_classes=self.classes)
        self.hash = digest(dict(mission=self.mission, budget=budget_name, gpus=gpus, code=code_digest()))
        self._env = None

    @property
    def env(self):
        if self._env is None:
            from .env import surface
            from .env.environment import GriddedEnv
            sub = surface.SurfaceLayer(self.cache) if _derived_current(self.cache) else None              # built by ingest
            self._env = GriddedEnv(self.cache, env_sigmas(), ocean=ocean(self), subgrid=sub)
        return self._env

    def path(self, *parts):
        p = self.run_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def ocean(ctx):
    """The ocean source the mission names (GOFS 3.1 or the lab's HYCOM), from the cache hycom.py writes."""
    from .env.ocean import open_ocean
    b = ctx.mission["box"]
    pad = b.get("pad_deg", 0.0)
    box = (b["lat_min"] - pad, b["lat_max"] + pad, b["lon_min"] - pad, b["lon_max"] + pad)       # (south, north, west, east)
    return open_ocean(ctx.mission["environment"]["ocean"], ctx.cache, ctx.mission["name"], box)


# res.pkl is only ever read back by this pipeline from its own run directory, and every reader names it as a ledger input,
# whose sha256 `make audit` re-checks: it is a private checkpoint format, never loaded from anywhere else.
def _dump(obj, path):
    path.write_text(json.dumps(obj, indent=1, default=ledger._jsonable))
    return path


# ------------------------------------------------------------------------------------------------------------------ stages

def s_ingest(ctx, L):
    from .env import orca, surface
    m = ctx.mission
    t0, t1 = utc(m["window"]["start"]), utc(m["window"]["end"])
    b = m["box"]
    pad = b.get("pad_deg", 0.0)
    box = (b["lon_min"] - pad, b["lon_max"] + pad, b["lat_min"] - pad, b["lat_max"] + pad)
    man = ctx.cache / "orca" / "manifest.json"
    if man.exists() and _covers(json.loads(man.read_text()), t0, t1):
        ctx.log(f"ingest: orca cache {man.parent} covers the window")
    else:
        uas_v = [v for v in m["vehicles"] if ctx.classes[v["id"]] == "uas"]
        h3 = sorted({h for v in uas_v for h in _sortie_hours(v, m["ship"]["lon"], t0, t1)})
        orca.ingest(t0.replace(tzinfo=None), t1.replace(tzinfo=None), box, ctx.cache / "orca", hours3d=h3, log=ctx.log)
    d = json.loads(man.read_text())
    want = int((t1 - t0).total_seconds() // 3600) + 1
    L.input(d["base"], sha=None, kind="remote", note="orca UWIN-CM run (byte-range reads; per-hour npz cache)")
    L.check("orca_hours_cover_window", d["hours"] >= want, value=d["hours"], limit=want)
    if not _derived_current(ctx.cache):
        shutil.rmtree(ctx.cache / "derived.zarr", ignore_errors=True)
        ctx._env = None
        surface.build(ctx.env, ctx.cache, log=ctx.log)
        ctx._env = None                                                  # rebuild with the surface layer just written
    oc = ocean(ctx)
    L.check("ocean_source_covers_box", oc is not None, note=str(ctx.mission["environment"]["ocean"]))
    L.output(man)
    _tao(ctx, L, t0.timestamp(), t1.timestamp())


def _tao(ctx, L, t0, t1):
    """Data validation (BRIEF 5.4): WRF 10 m wind and SST against the TAO/TRITON moorings in the box, hourly, model minus
    mooring. The pooled wind speed and direction errors become the Stage-1 wind priors (ingest/priors_fitted.json);
    without moorings the perturbations.yaml priors stand and the ledger says so."""
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
    fit = dict(wind_speed_bias=dict(dist="normal", mean=-a["speed_bias"], value=float(np.sqrt(max(a["speed_rmse"] ** 2 - a["speed_bias"] ** 2, 0.0))),
                                    unit="m/s", citation=cite, kind="data"),
               wind_direction_bias=dict(dist="normal", mean=-a["dir_bias_deg"],
                                        value=float(np.sqrt(max(a["dir_rmse_deg"] ** 2 - a["dir_bias_deg"] ** 2, 0.0))), unit="deg", citation=cite, kind="data"))
    L.output(_dump(fit, ctx.path("ingest", "priors_fitted.json")))


def _derived_current(cache):
    """derived.zarr exists and has the layout this code reads (surface.LAYOUT_VERSION)."""
    from .env import surface
    p = cache / "derived.zarr" / "zarr.json"
    return p.exists() and json.loads(p.read_text()).get("attributes", {}).get("layout_version") == surface.LAYOUT_VERSION


def _covers(d, t0, t1):
    f = lambda s: utc(s.replace(" ", "T") + ("" if s.endswith("Z") else "Z"))
    return f(d["t0"]) <= t0 and f(d["t1"]) >= t1


def _sortie_hours(v, lon, t0, t1):
    import datetime as dt
    ts = stage1.launch_times(v["sorties"], lon, t0.timestamp(), t1.timestamp(), 60.0 * v["sorties"].get("duration_min", 20))
    out = []
    for t in ts:
        h = dt.datetime.fromtimestamp(np.floor(t / 3600) * 3600, dt.timezone.utc).replace(tzinfo=None)
        out += [h, h + dt.timedelta(hours=1)]
    return out


def s_hangar(ctx, L):
    """The vehicle numbers every stage uses, with the files they came from: each platform yaml through its own model's
    loader, which refuses a number without a source or an assumed + why."""
    from .config import PLATFORMS
    from .physics import glider, uas, usv
    loaders = dict(glider=glider.load_platform, usv=usv.load_platform, uas=uas.load_platform)
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
    L.output(_dump(rows, ctx.path("hangar", "hangar.json")))


def _assumed(node):
    """Number of leaves marked assumed: true in a parsed platform yaml."""
    if isinstance(node, dict):
        return int(node.get("assumed") is True) + sum(_assumed(v) for v in node.values())
    return sum(_assumed(v) for v in node) if isinstance(node, list) else 0


def _stage1(ctx, L, name, scales=None):
    a = time.time()
    fp = ctx.run_dir / "ingest" / "priors_fitted.json"
    fitted = json.loads(fp.read_text()) if fp.is_file() else None
    if fitted:
        L.input(fp)
    r = stage1.run(ctx.mission, ctx.env, ctx.plan, L, log=ctx.log, scales=scales, fitted=fitted)
    L.seed("mission", ctx.mission["seed"])
    L.note(f"{r['n']} members in {time.time() - a:.0f} s; certify possible: {r['certify']} (n_certify {r['n_certify']})")
    res = r.pop("res")
    for v in res["vehicles"].values():
        v.pop("sim", None)
    with open(ctx.path(name, "res.pkl"), "wb") as f:
        pickle.dump(res, f)
    L.output(ctx.path(name, "res.pkl"))
    L.output(_dump(r, ctx.path(name, "summary.json")))


def s_stage1(ctx, L):
    _stage1(ctx, L, "stage1")


def s_windows(ctx, L):
    """Worst windows per vehicle: the record times where the members that failed (or, with none failing, all members)
    met the strongest forcing (10 m wind for surface/air vehicles, Hs for the USV hull, current speed for gliders)."""
    res = pickle.loads(ctx.path("stage1", "res.pkl").read_bytes())
    L.input(ctx.path("stage1", "res.pkl"))
    K = ctx.plan["les"]["windows_per_vehicle"]
    out = {}
    for vid, r in res["vehicles"].items():
        f = stage1.failed(r)
        sel = f if f.any() else np.ones_like(f)
        t = np.asarray(r["t"])
        lon, lat = np.asarray(r["lon"])[:, sel], np.asarray(r["lat"])[:, sel]
        tt = np.broadcast_to(t[:, None], lon.shape)
        ok = np.isfinite(lon)
        if not ok.any():
            out[vid] = []
            continue
        stress = np.full(lon.shape, -np.inf)
        if r["class"] == "glider":
            c = ctx.env.current(lon[ok], lat[ok], np.zeros(ok.sum()), tt[ok])
            stress[ok] = np.hypot(*np.moveaxis(np.asarray(c.value, float), -1, 0))
        elif r["class"] == "usv":
            stress[ok] = np.nan_to_num(ctx.env.waves(lon[ok], lat[ok], tt[ok])["Hs"].value)
        else:
            stress[ok] = np.hypot(*np.moveaxis(np.asarray(ctx.env.u10(lon[ok], lat[ok], tt[ok]), float), -1, 0))
        worst = np.nanmax(stress, 1)
        idx = []
        for i in np.argsort(-worst):                                     # K windows at least 6 h apart
            if np.isfinite(worst[i]) and all(abs(t[i] - t[j]) >= 6 * 3600 for j in idx):
                idx.append(int(i))
            if len(idx) == K:
                break
        out[vid] = [dict(t=float(t[i]), stress=float(worst[i]), lon=float(np.nanmedian(lon[i])), lat=float(np.nanmedian(lat[i])),
                         basis="failed members" if f.any() else "all members") for i in idx]
    L.check("every_vehicle_has_a_window", all(out.values()), value=sum(map(len, out.values())))
    L.output(_dump(out, ctx.path("windows", "windows.json")))


def s_stage3(ctx, L):
    from .stage3 import pipeline_windows
    wins = json.loads(ctx.path("windows", "windows.json").read_text())
    L.input(ctx.path("windows", "windows.json"))
    rows = pipeline_windows.run(ctx, wins, L)
    L.output(_dump(rows, ctx.path("stage3", "windows.json")))


def s_refit(ctx, L):
    from .stage3 import refit
    rows = json.loads(ctx.path("stage3", "windows.json").read_text())
    L.input(ctx.path("stage3", "windows.json"))
    out = {}
    for vid, ws in rows.items():
        good = [w for w in ws if w.get("ok")]
        if ctx.plan["refit_iterations"] == 0:
            out[vid] = dict(used=False, reason="budget ci: no refit")
        elif not good:
            out[vid] = dict(used=False, reason="no window passed its stage-3 self-checks; Stage 1 keeps the Hangar coefficients",
                            failed_checks=sorted({c["name"] for w in ws for c in w.get("checks", []) if not c["ok"]}))
        else:
            out[vid] = dict(used=True, **refit.refit(good))                 # each window against its own cd_hangar
    L.check("refit_uses_only_windows_that_passed", all(not v["used"] or v.get("drag", {}).get("windows", 0) > 0 for v in out.values()))
    L.output(_dump(out, ctx.path("refit", "refit.json")))


def s_stage1b(ctx, L):
    ref = json.loads(ctx.path("refit", "refit.json").read_text())
    L.input(ctx.path("refit", "refit.json"))
    scales = {vid: r for vid, r in ref.items() if r["used"]}
    if not scales:
        L.note("no vehicle was refit: stage 1b is stage 1 (copied, not rerun)")
        for f in ("res.pkl", "summary.json"):
            shutil.copy(ctx.path("stage1", f), ctx.path("stage1b", f))
            L.output(ctx.path("stage1b", f))
        return
    _stage1(ctx, L, "stage1b", scales=scales)


def s_emulator(ctx, L):
    """Members -> per-vehicle failure: the emulator the what-if queries use, scored on held-out members."""
    import pandas as pd
    from .emulator import Emulator
    res = pickle.loads(ctx.path("stage1b", "res.pkl").read_bytes())
    L.input(ctx.path("stage1b", "res.pkl"))
    X = res["X"]
    feats = sorted(k for k in X if np.ptp(X[k]) > 0)
    out = {}
    for vid, r in res["vehicles"].items():
        y = stage1.failed(r).astype(float)
        df = pd.DataFrame({**{k: X[k] for k in feats}, "p_fail": y})
        if len(df) < 20 or y.min() == y.max():
            out[vid] = dict(trained=False, reason=f"{len(df)} members, {int(y.sum())} failures: nothing to learn")
            continue
        em = Emulator(feats, ["p_fail"], ctx.path("emulator", f"train_{vid}.csv"))
        out[vid] = dict(trained=True, **em.holdout_report(df))
    L.output(_dump(out, ctx.path("emulator", "holdout.json")))


def s_report(ctx, L):
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


def run(mission_path, budget_name, gpus, run_dir, resume=True, stop_after=None, log=print):
    ctx = Context(mission_path, budget_name, gpus, run_dir, log)
    shutil.copy(ctx.mission_path, ctx.path("mission.yaml"))
    _dump(ctx.plan, ctx.path("plan.json"))
    log(budget.describe(ctx.plan))
    prev, redo = None, not resume
    for name in STAGES:
        lp = ctx.run_dir / "checkpoints" / name / "ledger.json"
        if not redo and ledger.done(ctx.run_dir, name, ctx.hash):
            log(f"{name}: up to date (ledger {lp})")
        else:
            a, redo = time.time(), True                                   # everything after a rerun stage reruns too
            with ledger.Ledger(ctx.run_dir, name, ctx.hash) as L:
                if prev is not None:
                    L.input(prev)
                FUNCS[name](ctx, L)
            log(f"{name}: done in {time.time() - a:.0f} s")
        prev = lp
        if name == stop_after:
            break
    return ctx
