"""Mission-level emulator: training rows from Stage 1, the per-class emulators, the flip search and the what-if answer (BRIEF 2.5, 2.7, 2.9).

One row per vehicle per Stage-1 run is appended to `$CAFE_DATA/emulator/train.parquet`:

    features   deploy_h (hours from the window start to the deploy, or for a UAS to its first sortie), lon, lat (deploy point or ship),
               the numeric task parameters of the vehicle's class, and the mean and 90th percentile of 10 m wind, Hs and surface
               current along the ensemble-median track (a UAS: at the ship at its sortie times)
    targets    p_fail, t_fail_h (median hours from start to the first failure among failed members; the exposure length when none
               failed, i.e. right-censored), mode_<name> (fraction of members that failed in that mode)
    metadata   cls, vehicle, mission, variant, key (run_id|vehicle|variant: a rerun of the same run replaces its rows), run_id, n_members,
               fidelity (0 = Stage 1, 1 = Stage-1b rerun with the stage-3 refit), git_sha, code_digest

Vehicles of different classes have different features and failure modes, so there is one emulator (cafe.pm.emulator.Emulator, GP plus split
conformal) per class, fitted on all rows of that class. It is trained only from `MIN_ROWS` rows; below that `trained` is False and says why.

A "mission change" is a dict per vehicle: shift_h (deploy later; a UAS: its daily sorties later in the day), dlon/dlat in degrees (a UAS
moves with its ship) and duty (<= 1: glider dive depth x duty, UAS every_days / duty). `apply` makes the changed mission or raises Invalid.
Candidate changes for the flip search are single changes, ranked by `cost` in units of "one notch": 6 h, 0.5 degree, 25 % of duty.
"""
from __future__ import annotations

import copy
import datetime as dt
import re
import time
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import qmc

from . import budget, report, stage1
from .config import ConfigError, _in_box, utc
from .emulator import Emulator, read_table, store_path, write_table
from .stats import intervals

BASE = ["deploy_h", "lon", "lat", "wind_mean", "wind_p90", "hs_mean", "hs_p90", "cur_mean", "cur_p90"]
TASK = dict(glider=["dive_depth_m", "radius_km", "lost_after_h"], usv=["track_tolerance_km", "becalmed_after_h"],
            uas=["every_days", "duration_min", "max_mean_wind_ms"])
MIN_ROWS = 100                    # per class: with a 20 % hold-out that is 20 test rows, the least that can say anything about 90 % coverage
MODES_MAX = 4                     # failure modes with their own GP (most variable first); the others stay in the table
LIMITS = dict(rmse=0.05, coverage=0.05, query_ms=10.0)          # BRIEF 2.7 acceptance
SHIFTS, MOVES, DUTIES = (6.0, 12.0, 24.0, 48.0), (0.5, 1.0), (0.75, 0.5)
FALLBACK_K = 3                    # Stage-1 candidates tried, nearest first, when the emulator cannot answer
TRAIN_FRAC = 0.7                  # of the emulator share the variant runs may use; the rest is for the flip search's Stage-1 fallback


class Invalid(ConfigError):
    """The mission change leaves the window, the box, or has nothing to change."""


# ------------------------------------------------------------------------------------------------------ mission changes

def vehicle(mission: dict, vid: str) -> dict:
    v = next((v for v in mission["vehicles"] if v["id"] == vid), None)
    if v is None:
        raise Invalid(f"no vehicle {vid!r} in the mission ({[x['id'] for x in mission['vehicles']]})")
    return v


def _wrap(lon: Any) -> Any:
    return (np.asarray(lon, float) + 180.0) % 360.0 - 180.0


def _window(m: dict) -> tuple[float, float]:
    return utc(m["window"]["start"]).timestamp(), utc(m["window"]["end"]).timestamp()


def _points(v: dict, ship: dict | None) -> list[list[float]]:
    """Every [lon, lat] a vehicle's task refers to (deploy, station, waypoints; a UAS: the ship)."""
    if "base" in v:
        return [[ship["lon"], ship["lat"]]] if ship else []
    t = v["task"]
    return [[v["deploy"]["lon"], v["deploy"]["lat"]]] + ([[t["lon"], t["lat"]]] if "lon" in t else []) + [list(p) for p in t.get("waypoints", [])]


def apply(mission: dict, mods: dict | None = None, drop: tuple | list = ()) -> dict:
    """A copy of the mission with the changes `mods` = {vid: dict(shift_h, dlon, dlat, duty)} and the vehicles `drop` (with their links) removed."""
    m = copy.deepcopy(mission)
    t0, t1 = _window(m)
    for vid in drop:
        vehicle(m, vid)
    m["vehicles"] = [v for v in m["vehicles"] if v["id"] not in drop]
    m["links"] = [k for k in m["links"] if k["a"] not in drop and k["b"] not in drop]
    ship_moved = False
    for vid, mod in (mods or {}).items():
        if vid in drop:
            continue
        v = vehicle(m, vid)
        h, dlon, dlat, duty = (float(mod.get(k, d)) for k, d in (("shift_h", 0.0), ("dlon", 0.0), ("dlat", 0.0), ("duty", 1.0)))
        if h and "base" in v:
            hh, mm = (int(x) for x in v["sorties"]["local_solar_time"].split(":"))
            tot = (hh * 60 + mm + int(round(h * 60))) % 1440
            v["sorties"]["local_solar_time"] = f"{tot // 60:02d}:{tot % 60:02d}"
        elif h:
            t = utc(v["deploy"]["time"]).timestamp() + 3600.0 * h
            if not t0 <= t < t1 - 3600.0:
                raise Invalid(f"{vid}: deploying {h:+g} h gives {_iso(t)}, outside the window {m['window']['start']} .. {m['window']['end']}")
            v["deploy"]["time"] = _iso(t)
        if dlon or dlat:
            if "base" in v:
                if not ship_moved:
                    m["ship"]["lon"], m["ship"]["lat"] = float(_wrap(m["ship"]["lon"] + dlon)), m["ship"]["lat"] + dlat
                ship_moved = True
            else:
                v["deploy"]["lon"], v["deploy"]["lat"] = float(_wrap(v["deploy"]["lon"] + dlon)), v["deploy"]["lat"] + dlat
                t = v["task"]
                if "lon" in t:
                    t["lon"], t["lat"] = float(_wrap(t["lon"] + dlon)), t["lat"] + dlat
                if "waypoints" in t:
                    t["waypoints"] = [[float(_wrap(a + dlon)), b + dlat] for a, b in t["waypoints"]]
            for lon, lat in _points(v, m.get("ship")):
                if not _in_box(lon, lat, m["box"]):
                    raise Invalid(f"{vid}: moving ({dlon:+g}, {dlat:+g}) deg puts ({lon:.2f}, {lat:.2f}) outside the mission box {m['box']}")
        if duty != 1.0:
            if "base" in v:
                v["sorties"]["every_days"] = float(v["sorties"].get("every_days", 1)) / duty
            elif "dive_depth_m" in v["task"]:
                v["task"]["dive_depth_m"] = v["task"]["dive_depth_m"] * duty
            else:
                raise Invalid(f"{vid}: the task has no duty cycle to lower (a glider dive_depth_m, UAS sorties every_days)")
    return m


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def solo(mission: dict, vid: str) -> dict:
    """The mission with only this vehicle and no links: vehicles do not interact in Stage 1, so its result is the same and it costs less."""
    m = copy.deepcopy(mission)
    m["vehicles"], m["links"] = [vehicle(m, vid)], []
    return m


def describe(mod: dict, v: dict | None = None) -> str:
    """The change in words."""
    h, dlon, dlat, duty = (float(mod.get(k, d)) for k, d in (("shift_h", 0.0), ("dlon", 0.0), ("dlat", 0.0), ("duty", 1.0)))
    what = "launch the sorties" if v is not None and "base" in v else "deploy"
    out = []
    if h:
        out.append(f"{what} {abs(h):g} h {'later' if h > 0 else 'earlier'}")
    for d, pos, neg in ((dlon, "east", "west"), (dlat, "north", "south")):
        if d:
            out.append(f"move {abs(d):g} deg {pos if d > 0 else neg}")
    if duty != 1.0:
        if v is not None and "base" in v:
            out.append(f"fly sorties every {float(v['sorties'].get('every_days', 1)) / duty:g} d instead of {float(v['sorties'].get('every_days', 1)):g}")
        else:
            d0 = (v or {}).get("task", {}).get("dive_depth_m")
            out.append(f"dive {100 * (1 - duty):.0f} % shallower" + (f" ({d0:g} m to {d0 * duty:g} m)" if d0 else ""))
    return " and ".join(out) or "no change"


# ------------------------------------------------------------------------------------------------------ features and rows

def uas_track(mission: dict, vid: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t, lon, lat) for a UAS: the ship at the middle of each sortie of the window (the window's middle when none fits)."""
    v, s = vehicle(mission, vid), mission["ship"]
    t0, t1 = _window(mission)
    dur = 60.0 * float(v["sorties"]["duration_min"])
    ts = stage1.launch_times(v["sorties"], s["lon"], t0, t1, dur) + dur / 2
    ts = ts if len(ts) else np.array([(t0 + t1) / 2])
    return ts, np.full(len(ts), float(s["lon"])), np.full(len(ts), float(s["lat"]))


def track_points(r: dict, mission: dict, n: int = 24) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t, lon, lat) of the ensemble-median track at up to n records, longitudes in [-180, 180)."""
    lon, lat = report._median_track(r, _centre(mission))
    ok = np.isfinite(lon) & np.isfinite(lat)
    i = np.flatnonzero(ok)[np.unique(np.linspace(0, max(int(ok.sum()) - 1, 0), min(int(ok.sum()), n)).astype(int))]
    return np.asarray(r["t"], float)[i], _wrap(lon[i]), lat[i]


def _centre(m: dict) -> float:
    return m["box"]["lon_min"] + ((m["box"]["lon_max"] - m["box"]["lon_min"]) % 360.0) / 2


def shift_track(trk: tuple, mod: dict, mission: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The base median track under a change: later by shift_h and moved by dlon/dlat, cut at the window end (the last point is kept)."""
    t, lon, lat = trk
    t2 = t + 3600.0 * float(mod.get("shift_h", 0.0))
    keep = t2 <= _window(mission)[1]
    keep = keep if keep.any() else np.arange(len(t2)) == len(t2) - 1
    return t2[keep], _wrap(lon[keep] + float(mod.get("dlon", 0.0))), lat[keep] + float(mod.get("dlat", 0.0))


def params(mission: dict, vid: str, cls: str) -> dict:
    """The mission-parameter features of one vehicle (BASE[:3] and TASK[cls])."""
    v, (t0, t1) = vehicle(mission, vid), _window(mission)
    c = _centre(mission)
    if cls == "uas":
        s, so = mission["ship"], v["sorties"]
        ts = stage1.launch_times(so, s["lon"], t0, t1, 60.0 * float(so["duration_min"]))
        d = dict(deploy_h=float(ts[0] - t0) / 3600.0 if len(ts) else 0.0, lon=float(s["lon"]), lat=float(s["lat"]),
                 every_days=float(so.get("every_days", 1)), duration_min=float(so["duration_min"]),
                 max_mean_wind_ms=float(v.get("launch_rules", {}).get("max_mean_wind_ms", 0.0)))
    else:
        dp = v["deploy"]
        d = dict(deploy_h=(utc(dp["time"]).timestamp() - t0) / 3600.0, lon=dp["lon"], lat=dp["lat"], **{k: float(v["task"].get(k, 0.0)) for k in TASK[cls]})
    d["lon"] = float((d["lon"] - c + 180.0) % 360.0 - 180.0 + c)             # unwrapped about the box centre, so a box over the dateline is continuous
    return d


def env_stats(env: Any, t: np.ndarray, lon: np.ndarray, lat: np.ndarray) -> dict:
    """Mean and 90th percentile of 10 m wind speed, Hs and surface current speed along a track (the report's queries)."""
    w = np.asarray(env.wind(lon, lat, 10.0, t).value, float)
    h = np.asarray(env.waves(lon, lat, t)["Hs"].value, float)
    c = np.asarray(env.current(lon, lat, 0.0, t).value, float)
    out = {}
    for name, a in (("wind", np.hypot(w[..., 0], w[..., 1])), ("hs", h), ("cur", np.hypot(c[..., 0], c[..., 1]))):
        out[f"{name}_mean"], out[f"{name}_p90"] = float(np.nanmean(a)), float(np.nanpercentile(a, 90))
    return out


def targets(r: dict) -> dict:
    """p_fail, t_fail_h and the fraction of members failing in each mode, from a Stage-1 vehicle result."""
    f = stage1.failed(r)
    t = np.asarray(r["t"], float)
    first = np.array([np.asarray(x, float) for x in r["first"].values()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        tf = np.nanmin(first, 0)
    t_fail = float(np.nanmedian((tf[f] - t[0]) / 3600.0)) if f.any() else float((t[-1] - t[0]) / 3600.0)
    return dict(p_fail=float(f.mean()), t_fail_h=t_fail, **{f"mode_{k}": float(np.mean(v)) for k, v in r["fail"].items()})


def vehicle_rows(mission: dict, res: dict, env: Any, fidelity: dict, meta: dict, variant: str = "base") -> list[dict]:
    """One training row per vehicle of a Stage-1 result `res` (stage1.merge / run_batch output) of `mission`."""
    rows = []
    for vid, r in res["vehicles"].items():
        cls = r["class"]
        trk = uas_track(mission, vid) if cls == "uas" else track_points(r, mission)
        rows.append(dict(**params(mission, vid, cls), **env_stats(env, *trk), **targets(r), cls=cls, vehicle=vid, variant=variant,
                         key=f"{meta['run_id']}|{vid}|{variant}", n_members=int(len(stage1.failed(r))), fidelity=int(fidelity.get(vid, 0)), **meta))
    return rows


def add_rows(path: Any, rows: list[dict]) -> tuple[pd.DataFrame, str]:
    """Append rows to the training table (rows with a key already in it are replaced). -> (whole table, the file used)."""
    p, _ = store_path(path)
    new = pd.DataFrame(rows)
    df = pd.concat([read_table(p)[lambda d: ~d["key"].isin(new["key"])], new], ignore_index=True) if p.exists() else new
    write_table(df, p)
    return df, str(p)


# ------------------------------------------------------------------------------------------------------ training design

def _fits(mission: dict, vid: str, mod: dict) -> dict:
    """The change shrunk (halving shift and move) until it is valid; no change when nothing fits."""
    for k in range(5):
        s = 0.5 ** k
        m = dict(mod, shift_h=mod["shift_h"] * s, dlon=mod["dlon"] * s, dlat=mod["dlat"] * s)
        try:
            apply(mission, {vid: m})
            return m
        except Invalid:
            continue
    return dict(shift_h=0.0, dlon=0.0, dlat=0.0, duty=1.0)


def design(mission: dict, n: int, seed: int) -> list[dict]:
    """n mission variants for training: per vehicle a Latin-hypercube point over shift, move and duty (each vehicle its own), so one
    Stage-1 run of the variant gives every vehicle a different row."""
    out: list[dict] = [{} for _ in range(n)]
    t0, t1 = _window(mission)
    for i, v in enumerate(mission["vehicles"]):
        u = qmc.LatinHypercube(d=4, seed=seed + i).random(n)
        if "base" in v:
            lo, hi, duty = -12.0, 12.0, True
        else:
            d = utc(v["deploy"]["time"]).timestamp()
            lo, hi, duty = -min(24.0, (d - t0) / 3600.0), min(48.0, 0.5 * (t1 - d) / 3600.0), "dive_depth_m" in v["task"]
        for k in range(n):
            mod = dict(shift_h=lo + u[k, 0] * (hi - lo), dlon=-1.0 + 2.0 * u[k, 1], dlat=-1.0 + 2.0 * u[k, 2], duty=1.0 - 0.5 * u[k, 3] if duty else 1.0)
            out[k][v["id"]] = _fits(mission, v["id"], mod)
    return out


# ------------------------------------------------------------------------------------------------------ fit and score

def _clean(df: pd.DataFrame, cls: str) -> pd.DataFrame:
    need = BASE + TASK[cls] + ["p_fail", "t_fail_h"]
    d = df[df["cls"] == cls].reindex(columns=sorted(set(df.columns) | set(need)))                  # a table of other classes has no columns of this one
    for c in [c for c in d if c.startswith("mode_")]:
        d[c] = d[c].fillna(0.0)
    return d.dropna(subset=need).reset_index(drop=True)


def fit_class(df: pd.DataFrame, cls: str, path: Any) -> tuple[Emulator | None, dict]:
    """Fit the emulator of one vehicle class on its rows and score it on a 20 % hold-out. -> (Emulator | None, info for holdout.json)."""
    d = _clean(df, cls)
    info: dict[str, Any] = dict(trained=False, cls=cls, rows=int(len(d)))
    if len(d) < MIN_ROWS:
        return None, dict(info, reason=f"{len(d)} {cls} rows in the training table, {MIN_ROWS} are needed (a 20 % hold-out must score 90 % coverage)")
    if np.ptp(d["p_fail"]) == 0:
        return None, dict(info, reason=f"P(fail) is {d['p_fail'].iloc[0]:.3f} in all {len(d)} {cls} rows: nothing to learn")
    modes = [c for c in d.columns if c.startswith("mode_") and d[c].std() > 0]
    modes = sorted(modes, key=lambda c: -d[c].std())[:MODES_MAX]
    em = Emulator(BASE + TASK[cls], ["p_fail", "t_fail_h"] + modes, path)
    em.fit(d, holdout=0.2)
    x = d.iloc[0][em.features]
    em.query(x)
    ts = []
    for _ in range(20):
        a = time.perf_counter()
        em.query(x)
        ts.append(1e3 * (time.perf_counter() - a))
    h = em.holdout or {}
    q = float(np.median(ts))
    floor = float(np.sqrt(np.mean(d["p_fail"] * (1 - d["p_fail"]) / d["n_members"])))
    deb = float(np.sqrt(max(h["rmse"]["p_fail"] ** 2 - floor ** 2, 0.0)))             # the part of the RMSE that is not the targets' own Monte-Carlo noise
    # the RMSE limit is on the error against the true P(fail): the held-out targets are themselves n-member estimates, whose binomial
    # noise (up to ~0.1 at n = 16) would otherwise fail any emulator, a perfect one included
    acc = dict(rmse_ok=bool(deb <= LIMITS["rmse"]), coverage_ok=bool(abs(h["coverage"]["p_fail"] - h["nominal"]) <= LIMITS["coverage"]),
               query_ok=bool(q <= LIMITS["query_ms"]))
    return em, dict(info, trained=True, n_train=h["n_train"], n_test=h["n_test"], nominal=h["nominal"], rmse=h["rmse"], coverage=h["coverage"],
                    query_ms=q, noise_floor_rmse=floor, rmse_debiased=deb, acceptance=acc, threshold=em.threshold, multi_fidelity=em.multi_fidelity)


def train(table: Any, classes: Any, path: Any = None) -> dict[str, tuple[Emulator | None, dict]]:
    """Fit the emulator of each class in `classes` from the stored table (all runs, all missions)."""
    p, _ = store_path(table)
    df = read_table(p) if p.exists() else pd.DataFrame(columns=["cls"] + BASE)
    return {c: fit_class(df, c, path or table) for c in sorted(set(classes))}


# ------------------------------------------------------------------------------------------------------ flip search

def candidates(mission: dict, vid: str) -> list[dict]:
    """Single changes in cost order: deploy +-6/12/24/48 h, +-0.5/1 degree in lon or lat, lower duty. Each: mod, cost (notches), change (words)."""
    v = vehicle(mission, vid)
    out: list[dict] = [dict(mod=dict(shift_h=s * h), cost=h / 6.0) for h in SHIFTS for s in (1, -1)]
    out += [dict(mod={ax: s * d}, cost=d / 0.5) for d in MOVES for ax in ("dlon", "dlat") for s in (1, -1)]
    if "base" in v or "dive_depth_m" in v["task"]:
        out += [dict(mod=dict(duty=f), cost=(1 - f) / 0.25) for f in DUTIES]
    for c in out:
        c["change"] = describe(c["mod"], v)
    return sorted(out, key=lambda c: c["cost"])


def predict(em: Emulator | None, mission: dict, vid: str, cls: str, trk: tuple | None, mod: dict, env: Any) -> dict:
    """The emulator's answer for a changed mission without running it: the mission parameters of the change, and the environment along the base
    median track `trk` moved by the change (a UAS: at the ship at the changed sortie times). Status: ok | out_of_range | no_emulator | no_track."""
    if em is None:
        return dict(status="no_emulator")
    if cls == "uas":
        track = uas_track(mission, vid)
    elif trk is None:
        return dict(status="no_track")
    else:
        track = shift_track(trk, mod, mission)
    return emulate(em, {**params(mission, vid, cls), **env_stats(env, *track)})


def emulate(em: Emulator, feats: dict) -> dict:
    """The emulator's answer for one feature dict, or why it cannot answer: status ok | out_of_range | no_track (a feature is missing)."""
    x = {k: feats.get(k, np.nan) for k in em.features}
    if not np.all(np.isfinite(list(x.values()))):
        return dict(status="no_track")
    q = em.query(x)
    if q["status"] != "ok":
        return dict(status="out_of_range", distance=q["distance"], threshold=q["threshold"])
    p = q["targets"]["p_fail"]
    return dict(status="ok", p_fail=p["value"], lo=p["lo"], hi=p["hi"], verdict=q["verdict"], distance=q["distance"], threshold=q["threshold"])


def measure(mission: dict, vid: str, env: Any, plan: dict, pri: dict, marg: dict, scales: dict | None, seed: int, n: int | None = None) -> dict:
    """Stage 1 for one vehicle of the (changed) mission: one batch of the plan's size, the base run's members (common random numbers)."""
    members = list(range(n or plan["batch"]))
    r = stage1.run_batch(solo(mission, vid), env, members, seed, pri, marg, scales)["vehicles"][vid]
    f = stage1.failed(r)
    v = intervals.verdict(int(f.sum()), len(f))
    return dict(p_fail=float(f.mean()), lo=v["fail_lo"], hi=v["fail_hi"], verdict=v["verdict"], n=int(len(f)))


def flip_search(mission: dict, verdicts: dict, tracks: dict, env: Any, ems: dict, plan: dict, pri: dict, marg: dict, scales: dict | None,
                seed: int, budget_s: float, log: Any = print) -> tuple[dict, float]:
    """For each vehicle whose verdict is not GO, the cheapest single change that makes it GO (a NO-GO: at least MARGINAL).

    Emulator first: every candidate within the emulator's training range is answered by it. Candidates it cannot answer (no emulator, no
    track, out of range) are run in Stage 1, nearest first, at most FALLBACK_K and only while `budget_s` lasts. The best candidate is the
    cheapest one in the target set among those answered. -> ({vid: result}, seconds of Stage 1 spent)."""
    out, spent = {}, 0.0
    for vid, base in verdicts.items():
        if base["verdict"] == "GO":
            continue
        cls = stage1._classes(solo(mission, vid))[vid]
        want = ("GO",) if base["verdict"] == "MARGINAL" else ("GO", "MARGINAL")
        em = (ems.get(cls) or (None, {}))[0]
        tried, left = [], []
        for c in candidates(mission, vid):
            e = dict(change=c["change"], mod=c["mod"], cost=c["cost"], method="not evaluated", reason="")
            try:
                m2 = apply(mission, {vid: c["mod"]})
            except Invalid as ex:
                tried.append(dict(e, reason=str(ex)))
                continue
            a = predict(em, m2, vid, cls, tracks.get(vid), c["mod"], env)
            if a["status"] == "ok":
                tried.append(dict(e, method="EMULATED", **{k: a[k] for k in ("p_fail", "lo", "hi", "verdict", "distance", "threshold")}))
            else:
                tried.append(dict(e, reason=a["status"].replace("_", " ")))
                left.append((len(tried) - 1, m2))
        if not any(t["method"] == "EMULATED" and t["verdict"] in want for t in tried):
            for i, m2 in left[:FALLBACK_K]:
                cost = budget.batch_cost_s(plan, [vid])
                if spent + cost > budget_s:
                    tried[i]["reason"] += "; Stage 1 not run: the emulator budget is spent"
                    break
                t0 = time.time()
                tried[i].update(method="Stage 1", **measure(m2, vid, env, plan, pri, marg, scales, seed))
                spent += time.time() - t0
                if tried[i]["verdict"] in want:
                    break
        hit = [t for t in tried if t["method"] != "not evaluated" and t["verdict"] in want]
        best = min(hit, key=lambda t: t["cost"]) if hit else None
        out[vid] = dict(verdict=base["verdict"], p_fail=base["p_fail"], target=" or ".join(want), found=best is not None, best=best, tried=tried,
                        emulator=em is not None)
        log(f"flip search {vid}: {best['change'] + ' (' + best['method'] + ')' if best else 'nothing in ' + str(len(tried)) + ' candidates flips it'}")
    return out, spent


# ------------------------------------------------------------------------------------------------------ the what-if command

def _parse(text: str, pat: str, what: str, example: str) -> re.Match:
    m = re.fullmatch(pat, text.strip(), re.I)
    if not m:
        raise ConfigError(f"{what} {text!r}: expected {example}")
    return m


def parse_shift(text: str) -> float:
    """'48h' -> 48.0, '-6h' -> -6.0, '2d' -> 48.0 (hours)."""
    m = _parse(text, r"([+-]?\d+(?:\.\d+)?)\s*([hd])", "--shift", "a number and h or d, e.g. 48h, -6h, 2d")
    return float(m[1]) * (24.0 if m[2].lower() == "d" else 1.0)


def parse_move(text: str) -> tuple[float, float]:
    """'1deg W' -> (-1.0, 0.0), '0.5deg north' -> (0.0, 0.5): (dlon, dlat) in degrees."""
    m = _parse(text, r"(\d+(?:\.\d+)?)\s*(?:deg|°)?\s*(north|south|east|west|[nsew])", "--move", "a number of degrees and a direction, e.g. '1deg W'")
    d, k = float(m[1]), m[2][0].lower()
    return {"e": (d, 0.0), "w": (-d, 0.0), "n": (0.0, d), "s": (0.0, -d)}[k]


def answer(mission: dict, ops: dict, base: dict, tracks: dict, env: Any, ems: dict, plan: dict, fitted: dict | None, scales: dict | None,
           only: list | None = None) -> dict:
    """The what-if: `ops` = dict(shift_h, dlon, dlat, drop=[ids]) applied to every vehicle (or to `only`). `base` = {vid: Stage-1 verdict dict}
    of the unchanged mission. Per changed vehicle: emulator-first, else Stage 1 at `plan`. Dropped vehicles need no run: Stage-1 vehicles do not
    interact, only the links through them go. -> dict(vehicles={vid: ...}, dropped, links_removed)."""
    pri, marg = stage1.priors_for(mission, fitted)
    seed = int(mission["seed"])
    drop = list(ops.get("drop", []))
    mod = dict(shift_h=ops.get("shift_h", 0.0), dlon=ops.get("dlon", 0.0), dlat=ops.get("dlat", 0.0))
    live = [v["id"] for v in mission["vehicles"] if v["id"] not in drop and (only is None or v["id"] in only)]
    for vid in only or []:
        vehicle(mission, vid)
    changed = {vid: mod for vid in live} if any(mod.values()) else {}
    m2 = apply(mission, changed, drop)
    out = {}
    for vid in changed:
        cls = stage1._classes(solo(m2, vid))[vid]
        b = base.get(vid)
        if b is None:
            b = measure(mission, vid, env, plan, pri, marg, scales, seed)
            b = dict(verdict=b["verdict"], p_fail=b["p_fail"])
        a = predict((ems.get(cls) or (None, {}))[0], m2, vid, cls, tracks.get(vid), mod, env)
        if a["status"] == "ok":
            out[vid] = dict(base=b, method="EMULATED", **{k: a[k] for k in ("p_fail", "lo", "hi", "verdict", "distance", "threshold")})
        else:
            out[vid] = dict(base=b, method="Stage 1", why=a["status"].replace("_", " "), **_stage1(m2, vid, env, plan, fitted, scales))
    gone = [k["id"] for k in mission["links"] if k["a"] in drop or k["b"] in drop]
    return dict(vehicles=out, dropped=drop, links_removed=gone)


def _stage1(mission: dict, vid: str, env: Any, plan: dict, fitted: dict | None, scales: dict | None) -> dict:
    """Stage 1 at the plan's budget (the sequential run, n_min .. n_max members) for one vehicle."""
    r = stage1.run(solo(mission, vid), env, plan, None, lambda *_: None, scales, fitted)
    e = r["summary"]["vehicles"][vid]
    return dict(p_fail=e["verdict"]["p_fail"], lo=e["verdict"]["fail_lo"], hi=e["verdict"]["fail_hi"], verdict=e["verdict"]["verdict"], n=e["n"])
