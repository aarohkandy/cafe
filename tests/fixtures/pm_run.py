"""A small synthetic run directory that follows the contract in cafe/pm/pipeline.py, for the report and credibility tests.

Built with the real code where a number comes from: `stage1.merge` and `stage1.summarize` (which call `intervals.verdict` and
`sensitivity.dominant`) on synthetic member arrays, `budget.plan` for plan.json, `ledger.Ledger` for every ledger, `refit.refit`
for refit.json. Only the arrays, the stage-3 window rows and the emulator hold-out are typed in.
"""
import json
import pathlib
import pickle
import shutil

import numpy as np

from cafe.pm import budget, config, ledger, stage1
from cafe.pm.audit import STAGES
from cafe.pm.stage3 import refit as refit_mod
from cafe.pm.stats import intervals

ROOT = config.ROOT
T0 = 1677672000.0                      # 2023-03-01 12:00 UTC
NT = 36


def mission():
    return config.load_mission(ROOT / "missions" / "tepex_c_demo.yaml")


def _batch(rng, M, names, fail_frac):
    """One batch of M members: tracks, failure flags (driven by the first sampled parameter so the sensitivity has something to find), links."""
    t = T0 + 600.0 * np.arange(NT)
    U = rng.random((M, len(names)))
    X = {k: U[:, i] for i, k in enumerate(names)}
    vehicles = {}

    def track(lon0, lat0, spread):
        lon = lon0 + np.cumsum(rng.normal(0, spread, (NT, M)), 0)
        lat = lat0 + np.cumsum(rng.normal(0, spread, (NT, M)), 0)
        return lon, lat

    def mode(fail, t_fail):
        return fail, np.where(fail, t_fail, np.nan)

    for vid, cls, lon0, lat0, p in (("glider_eq", "glider", -170.0, 0.0, fail_frac), ("glider_2n", "glider", -170.0, 2.0, 0.0),
                                    ("usv", "usv", -165.0, 0.0, 0.18), ("uas", "uas", -165.0, 0.0, 0.7)):
        lon, lat = track(lon0, lat0, 0.01)
        f = U[:, 0] > 1.0 - p
        ft = T0 + 3600.0 * (2 + 20 * U[:, 1])
        lon[NT // 2:, f] = np.nan                                    # a failed member stops reporting
        lat[NT // 2:, f] = np.nan
        r = dict(t=t, lon=lon, lat=lat, depth=np.zeros_like(lon), surfaced=np.ones_like(lon, bool), antenna_m=1.0, **{"class": cls})
        if cls == "uas":
            r.update(alt=np.zeros_like(lon), airborne=np.zeros_like(lon, bool))
            fa, fi = mode(f, ft)
            fb, fj = mode(np.zeros(M, bool), ft)
            r["fail"], r["first"] = dict(gust_front=fa, battery=fb), dict(gust_front=fi, battery=fj)
        else:
            fa, fi = mode(f, ft)
            r["fail"], r["first"] = dict(station_lost=fa), dict(station_lost=fi)
        vehicles[vid] = r
    links = {}
    for lid, p in (("usv-uas-rf", 0.0), ("glider_eq-ship-acoustic", 0.3)):
        ok = U[:, 2] > p
        links[lid] = dict(frac=np.where(ok, 0.97, 0.5), success=ok, margin_db=rng.normal(6.0, 3.0, (NT, M)), method="two-ray (synthetic)", t=t)
    links["usv-shore-iridium"] = dict(frac=np.ones(M), success=np.ones(M, bool), margin_db=np.full((NT, M), np.nan), method="Iridium (synthetic)", t=t)
    return dict(U=U, X=X, vehicles=vehicles, links=links)


def make_res(seed=1, fail_frac=0.4, M=48):
    """Two batches merged by stage1.merge, then summarized by stage1.summarize. -> (res, summary dict as stage1.run returns it)."""
    m = mission()
    pri, marg = stage1.priors_for(m)
    names = list(marg)
    rng = np.random.default_rng(seed)
    res = stage1.merge([_batch(rng, M // 2, names, fail_frac), _batch(rng, M // 2, names, fail_frac)])
    summ = stage1.summarize(res, names, m, intervals.n_certify())
    top = dict(summary=summ, names=names, priors={k: marg[k] for k in names}, n=len(res["U"]), certify=len(res["U"]) >= intervals.n_certify(),
               n_certify=intervals.n_certify(), t0="2023-03-01T12:00:00+00:00")
    return res, top


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=ledger._jsonable))
    return path


def _dump_stage1(run, name, res, top):
    (run / name).mkdir(parents=True, exist_ok=True)
    with open(run / name / "res.pkl", "wb") as f:
        pickle.dump(res, f)
    _write(run / name / "summary.json", top)
    return [run / name / "res.pkl", run / name / "summary.json"]


def check_row(name, value, limit, ok, **kw):
    return dict(name=name, value=float(value), limit=limit, ok=bool(ok), **kw)


def stage3_rows(vehicle_ids):
    rows = {}
    for vid in vehicle_ids:
        good = dict(ok=True, cd=1.1, cd_spread=0.05, cd_hangar=1.0, cl=None, checks=[check_row("mach_max", 0.05, 0.1, True),
                    check_row("nest_shift_count", 3, float("inf"), True, note="whole-cell shifts")])
        bad = dict(good, ok=False, cd=1.2, checks=[check_row("mach_max", 0.4, 0.1, False), check_row("courant_max", 0.1, 0.3, True)])
        rows[vid] = [good, bad] if vid == "uas" else [dict(good, cd=1.05), dict(good, cd=1.15)] if vid == "glider_eq" else [good]
    return rows


def refit_rows(rows):
    """What pipeline.s_refit builds: refit.refit on the passing windows of glider_eq; the others are not used, with a reason."""
    out = {}
    for vid, ws in rows.items():
        good = [w for w in ws if w.get("ok")]
        if vid == "glider_eq":
            out[vid] = dict(used=True, **refit_mod.refit(good, dict(cd=good[0]["cd_hangar"], cl=None)))
        elif vid == "uas":
            out[vid] = dict(used=False, reason="no window passed its stage-3 self-checks; Stage 1 keeps the Hangar coefficients",
                            failed_checks=sorted({c["name"] for w in ws for c in w["checks"] if not c["ok"]}))
        elif vid == "glider_2n":
            out[vid] = dict(used=False, reason="budget ci: no refit")
    return out                                                       # usv has stage-3 rows but no refit entry


def make_run(run, *, budget_name="quick", thr=None, git="abc1234", ledgers=True, res=True, stage3=True, refit=True, emulator=True, summary_only=False,
             stage1b_differs=True, M=48):
    """Write a run directory. Flags remove parts to exercise the degraded paths. -> (mission, plan)."""
    run = pathlib.Path(run)
    m = mission()
    plan = budget.plan(budget_name, 0, m, thr={} if thr is None else thr, vehicle_classes=stage1._classes(m))
    run.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "missions" / "tepex_c_demo.yaml", run / "mission.yaml")
    _write(run / "plan.json", plan)
    r1, top1 = make_res(seed=1, fail_frac=0.4, M=M)
    r1b, top1b = make_res(seed=2, fail_frac=0.0, M=M) if stage1b_differs else (r1, top1)
    for v in r1["vehicles"].values():
        v.pop("sim", None)
    if summary_only:
        _write(run / "stage1b" / "summary.json", top1b)
        return m, plan
    out = {"stage1": _dump_stage1(run, "stage1", r1, top1)}
    out["stage1b"] = _dump_stage1(run, "stage1b", r1b, top1b)
    vids = list(top1["summary"]["vehicles"])
    wins = {vid: [dict(t=T0 + 3600.0 * (10 + 8 * i), stress=8.0 + i, lon=-170.0 + i, lat=0.5 * i, basis="failed members" if i == 0 else "all members")
                  for i in range(2 if vid == "glider_eq" else 1)] for vid in vids}
    out["windows"] = [_write(run / "windows" / "windows.json", wins)]
    rows = stage3_rows(vids)
    if stage3:
        out["stage3"] = [_write(run / "stage3" / "windows.json", rows)]
    if refit:
        out["refit"] = [_write(run / "refit" / "refit.json", refit_rows(rows))]
    if emulator:
        h = dict(trained=True, n_test=10, nominal=0.9, rmse=dict(p_fail=0.04), coverage=dict(p_fail=0.9), n_train=38)
        untrained = dict(trained=False, reason="48 members, 0 failures: nothing to learn")
        out["emulator"] = [_write(run / "emulator" / "holdout.json", dict(glider_eq=h, usv=untrained))]
    out["hangar"] = [_write(run / "hangar" / "hangar.json", {})]
    out["ingest"] = [_write(run / "ingest" / "manifest.json", {})]
    if not ledgers:
        return m, plan
    real = ledger.git_sha
    ledger.git_sha = lambda: git
    try:
        prev = None
        for st in STAGES[:-1]:
            if not res and st == "stage1b":
                (run / "stage1b" / "res.pkl").unlink()
            with ledger.Ledger(run, st, "cfg-" + "0" * 20) as L:
                if prev:
                    L.input(prev)
                if st == "ingest":
                    L.input("https://orca.example/run_synthetic", sha=None, kind="remote", note="synthetic")
                    L.check("orca_hours_cover_window", True, value=145, limit=145)
                if st in ("stage1", "stage1b"):
                    L.seed("mission", 20230301)
                    L.check("lhs_stratified_batch1", True, value=0.1, limit=0.2)
                for p in out.get(st, []):
                    if p.exists():
                        L.output(p)
            prev = run / "checkpoints" / st / "ledger.json"
    finally:
        ledger.git_sha = real
    return m, plan
