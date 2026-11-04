"""Mission-level emulator: training rows from Stage 1, the per-class emulators, the flip search and the what-if answer (BRIEF 2.5, 2.7, 2.9).

One row per vehicle per Stage-1 run is appended to `$CAFE_DATA/emulator/train.parquet`:

    features   deploy_h (hours from the window start to the deploy, or for a UAS to its first sortie), lon, lat (deploy point or ship),
               the numeric task parameters of the vehicle's class, and the mean and 90th percentile of 10 m wind, Hs and surface
               current along the ensemble-median track (a UAS: at the ship at its sortie times)
    targets    p_fail, t_fail_h (median hours from start to the first failure among failed members; the exposure length when none
               failed, i.e. right-censored), mode_<name> (fraction of members that failed in that mode)
    metadata   cls, vehicle, mission, variant, key (a hash of mission, class, vehicle, variant and the features: a rerun of the same mission
               replaces its rows, whichever directory it ran in), run_id, n_members, fidelity (0 = Stage 1, 1 = Stage-1b rerun with the stage-3
               refit), git_sha, code_digest

Vehicles of different classes have different features and failure modes, so there is one emulator (cafe.pm.emulator.Emulator, GP plus split
conformal) per class, fitted on the rows of that class made by the current code (`code_digest`; older rows stay in the table). It is trained
only from `MIN_ROWS` distinct feature points; below that `trained` is False and says why.

A "mission change" is a dict per vehicle: shift_h (deploy later; a UAS: its daily sorties later in the day), dlon/dlat in degrees (a UAS
moves with its ship) and duty (<= 1: glider dive depth x duty, UAS every_days / duty rounded up to whole days). `apply` makes the changed
mission or raises Invalid; a UAS shift of a whole number of days is Invalid (the same launch time of day).
Candidate changes for the flip search are single changes, ranked by `cost` in units of "one notch": 6 h, 0.5 degree, 25 % of duty.
"""
from __future__ import annotations

import concurrent.futures as cf
import contextlib
import copy
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import time
import warnings
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.stats import binom, qmc

from . import budget, par, report, stage1
from .config import ConfigError, _in_box, utc
from .emulator import Emulator, FreshDraw, locked, read_table, store_path, write_table
from .env.environment import OutsideData
from .stats import intervals

Track = tuple[NDArray[Any], NDArray[Any], NDArray[Any]]                    # (t, lon, lat)
BASE = ["deploy_h", "lon", "lat", "wind_mean", "wind_p90", "hs_mean", "hs_p90", "cur_mean", "cur_p90"]
TASK = dict(glider=["dive_depth_m", "radius_km", "lost_after_h"], usv=["track_tolerance_km", "becalmed_after_h"],
            uas=["every_days", "duration_min", "max_mean_wind_ms"])
MIN_ROWS = budget.EMULATOR_MIN_POINTS     # distinct feature points per class (budget.py holds it with the plan that sizes the variants):
#                                   with a 20 % hold-out that is 20 test points, enough to say anything of 90 % coverage. Never lowered to make a run train.
MODES_MAX = 4                     # failure modes with their own GP (most variable first); the others stay in the table
LIMITS = dict(rmse=0.05, coverage=0.05, query_ms=10.0)          # BRIEF 2.7 acceptance
SHIFTS, MOVES, DUTIES = (6.0, 12.0, 24.0, 48.0), (0.5, 1.0), (0.75, 0.5)
FALLBACK_K = 3                    # Stage-1 candidates tried, nearest first, when the emulator cannot answer
TRAIN_FRAC = budget.TRAIN_FRAC    # of the emulator share the variant runs may use; the rest is for the flip search's Stage-1 fallback


class Invalid(ConfigError):
    """The mission change leaves the window, the box, or has nothing to change."""


# ------------------------------------------------------------------------------------------------------ mission changes

def vehicle(mission: dict[str, Any], vid: str) -> dict[str, Any]:
    v: dict[str, Any] | None = next((v for v in mission["vehicles"] if v["id"] == vid), None)
    if v is None:
        raise Invalid(f"no vehicle {vid!r} in the mission ({[x['id'] for x in mission['vehicles']]})")
    return v


def _wrap(lon: Any) -> Any:
    return (np.asarray(lon, float) + 180.0) % 360.0 - 180.0


def _window(m: dict[str, Any]) -> tuple[float, float]:
    return utc(m["window"]["start"]).timestamp(), utc(m["window"]["end"]).timestamp()


def _points(v: dict[str, Any], ship: dict[str, Any] | None) -> list[list[float]]:
    """Every [lon, lat] a vehicle's task refers to (deploy, station, waypoints; a UAS: the ship)."""
    if "base" in v:
        return [[ship["lon"], ship["lat"]]] if ship else []
    t = v["task"]
    return [[v["deploy"]["lon"], v["deploy"]["lat"]]] + ([[t["lon"], t["lat"]]] if "lon" in t else []) + [list(p) for p in t.get("waypoints", [])]


def _whole_days(h: float) -> bool:
    """A launch shift of a whole number of days: the same time of day."""
    return bool(h) and int(round(h * 60)) % 1440 == 0


def apply(mission: dict[str, Any], mods: dict[str, Any] | None = None, drop: Sequence[str] = ()) -> dict[str, Any]:
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
            if _whole_days(h):
                raise Invalid(f"{vid}: launching {h:+g} h later is a whole number of days, the same launch time of day: nothing changes")
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
                v["sorties"]["every_days"] = _duty_days(float(v["sorties"].get("every_days", 1)), duty)
            elif "dive_depth_m" in v["task"]:
                v["task"]["dive_depth_m"] = v["task"]["dive_depth_m"] * duty
            else:
                raise Invalid(f"{vid}: the task has no duty cycle to lower (a glider dive_depth_m, UAS sorties every_days)")
    return m


def _duty_days(every: float, duty: float) -> float:
    """The sortie period at a duty: every / duty, rounded up to whole days once it is a day or more (a fraction of a day moves the launch off the
    mission's time of day)."""
    x = every / duty
    return float(math.ceil(x - 1e-9)) if x >= 1.0 else x


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def solo(mission: dict[str, Any], vid: str) -> dict[str, Any]:
    """The mission with only this vehicle and no links: vehicles do not interact in Stage 1, so its result is the same and it costs less."""
    m = copy.deepcopy(mission)
    m["vehicles"], m["links"] = [vehicle(m, vid)], []
    return m


def describe(mod: dict[str, Any], v: dict[str, Any] | None = None) -> str:
    """The change in words."""
    h, dlon, dlat, duty = (float(mod.get(k, d)) for k, d in (("shift_h", 0.0), ("dlon", 0.0), ("dlat", 0.0), ("duty", 1.0)))
    what = "launch the sorties" if v is not None and "base" in v else "deploy"
    out: list[str] = []
    if h:
        out.append(f"{what} {abs(h):g} h {'later' if h > 0 else 'earlier'}")
    for d, pos, neg in ((dlon, "east", "west"), (dlat, "north", "south")):
        if d:
            out.append(f"move {abs(d):g} deg {pos if d > 0 else neg}")
    if duty != 1.0:
        if v is not None and "base" in v:
            x = float(v["sorties"].get("every_days", 1))
            up = " (rounded up to whole days)" if x / duty >= 1.0 and x / duty != _duty_days(x, duty) else ""
            out.append(f"fly sorties every {_duty_days(x, duty):g} d instead of {x:g}{up}")
        else:
            d0 = (v or {}).get("task", {}).get("dive_depth_m")
            out.append(f"dive {100 * (1 - duty):.0f} % shallower" + (f" ({d0:g} m to {d0 * duty:g} m)" if d0 else ""))
    return " and ".join(out) or "no change"


# ------------------------------------------------------------------------------------------------------ features and rows

WIND_MODEL_2D = ("UAS what-if answers use the 10 m scaled profile for the candidate and the baseline: the WRF 3-D wind fields cover only the ingested "
                 "hours, so a shifted sortie would otherwise change the wind model as well as the sortie.")


@contextlib.contextmanager
def wind_2d(env: Any, cls: str) -> Iterator[None]:
    """A UAS run with the environment's 3-D wind switched off (`GriddedEnv.use_3d`), restored after; any other class, or an environment without the
    switch, is left alone. Both sides of a UAS comparison run inside it."""
    if cls != "uas" or not hasattr(env, "use_3d"):
        yield
        return
    old, env.use_3d = env.use_3d, False
    try:
        yield
    finally:
        env.use_3d = old

def uas_track(mission: dict[str, Any], vid: str) -> Track:
    """(t, lon, lat) for a UAS: the ship at the middle of each sortie of the window (the window's middle when none fits)."""
    v, s = vehicle(mission, vid), mission["ship"]
    t0, t1 = _window(mission)
    dur = 60.0 * float(v["sorties"]["duration_min"])
    ts = stage1.launch_times(v["sorties"], s["lon"], t0, t1, dur) + dur / 2
    ts = ts if len(ts) else np.array([(t0 + t1) / 2])
    return ts, np.full(len(ts), float(s["lon"])), np.full(len(ts), float(s["lat"]))


def track_points(r: dict[str, Any], mission: dict[str, Any], n: int = 24) -> Track:
    """(t, lon, lat) of the ensemble-median track at up to n records, longitudes in [-180, 180)."""
    lon, lat = report._median_track(r, _centre(mission))
    ok = np.isfinite(lon) & np.isfinite(lat)
    i = np.flatnonzero(ok)[np.unique(np.linspace(0, max(int(ok.sum()) - 1, 0), min(int(ok.sum()), n)).astype(int))]
    return np.asarray(r["t"], float)[i], _wrap(lon[i]), lat[i]


def _centre(m: dict[str, Any]) -> float:
    return float(m["box"]["lon_min"] + ((m["box"]["lon_max"] - m["box"]["lon_min"]) % 360.0) / 2)


def shift_track(trk: Track, mod: dict[str, Any], mission: dict[str, Any]) -> Track:
    """The base median track under a change: later by shift_h and moved by dlon/dlat, cut at the window end (the last point is kept)."""
    t, lon, lat = trk
    t2 = t + 3600.0 * float(mod.get("shift_h", 0.0))
    keep = t2 <= _window(mission)[1]
    keep = keep if keep.any() else np.arange(len(t2)) == len(t2) - 1
    return t2[keep], _wrap(lon[keep] + float(mod.get("dlon", 0.0))), lat[keep] + float(mod.get("dlat", 0.0))


def params(mission: dict[str, Any], vid: str, cls: str) -> dict[str, Any]:
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


def env_stats(env: Any, t: NDArray[Any], lon: NDArray[Any], lat: NDArray[Any]) -> dict[str, Any]:
    """Mean and 90th percentile of 10 m wind speed, Hs and surface current speed along a track (the report's queries)."""
    w = np.asarray(env.wind(lon, lat, 10.0, t).value, float)
    h = np.asarray(env.waves(lon, lat, t)["Hs"].value, float)
    c = np.asarray(env.current(lon, lat, 0.0, t).value, float)
    out: dict[str, float] = {}
    for name, a in (("wind", np.hypot(w[..., 0], w[..., 1])), ("hs", h), ("cur", np.hypot(c[..., 0], c[..., 1]))):
        out[f"{name}_mean"], out[f"{name}_p90"] = float(np.nanmean(a)), float(np.nanpercentile(a, 90))
    return out


def targets(r: dict[str, Any]) -> dict[str, Any]:
    """p_fail, t_fail_h and the fraction of members failing in each mode, from a Stage-1 vehicle result."""
    f = stage1.failed(r)
    t = np.asarray(r["t"], float)
    first = np.array([np.asarray(x, float) for x in r["first"].values()])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        tf = np.nanmin(first, 0)
    t_fail = float(np.nanmedian((tf[f] - t[0]) / 3600.0)) if f.any() else float((t[-1] - t[0]) / 3600.0)
    return dict(p_fail=float(f.mean()), t_fail_h=t_fail, **{f"mode_{k}": float(np.mean(v)) for k, v in r["fail"].items()})


def row_key(row: dict[str, Any]) -> str:
    """The identity of a training row: mission, class, vehicle, variant and the features, to 9 significant digits. A rerun of the same mission
    gives the same key whichever directory it ran in, so it replaces its predecessor instead of counting as new data."""
    feats = {k: float(f"{row[k]:.9g}") for k in BASE + TASK[row["cls"]]}
    ident = [row.get("mission", ""), row["cls"], row["vehicle"], row["variant"], feats]
    return hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:16]


def vehicle_rows(mission: dict[str, Any], res: dict[str, Any], env: Any, fidelity: dict[str, Any], meta: dict[str, Any],
                 variant: str = "base") -> list[dict[str, Any]]:
    """One training row per vehicle of a Stage-1 result `res` (stage1.merge / run_batch output) of `mission`."""
    rows: list[dict[str, Any]] = []
    for vid, r in res["vehicles"].items():
        cls = r["class"]
        trk = uas_track(mission, vid) if cls == "uas" else track_points(r, mission)
        row = dict(**params(mission, vid, cls), **env_stats(env, *trk), **targets(r), cls=cls, vehicle=vid, variant=variant,
                   n_members=int(len(stage1.failed(r))), fidelity=int(fidelity.get(vid, 0)), **meta)
        rows.append(dict(row, key=row_key(row)))
    return rows


def run_variant(mission: dict[str, Any], env: Any, members: list[int], seed: int, pri: dict[str, dict[str, Any]], marg: dict[str, dict[str, Any]],
                scales: dict[str, Any] | None, fidelity: dict[str, Any], meta: dict[str, Any], variant: str,
                mods: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Training rows of one mission variant: one Stage-1 batch of every vehicle. A variant that moves a vehicle past the environment data
    (GriddedEnv refuses a point outside the cache) is not an error: the batch is rerun one vehicle at a time and each vehicle whose track
    leaves the data is skipped with that reason; the others keep their rows. Skipped, not clipped: pulling a track back inside would make it a
    different variant than the one the plan counted, and what a vehicle does near the edge is what the sample would have taught the emulator.
    A vehicle whose change in `mods` is empty (`is_base`: `design` found nothing valid to change) is not run: its row would be the base mission's again.
    -> (rows, {vehicle id: why it has none})."""
    same = {vid for vid, m in (mods or {}).items() if is_base(m)}
    if same:
        left = apply(mission, drop=sorted(same))
        kept, left_why = run_variant(left, env, members, seed, pri, marg, scales, fidelity, meta, variant) if left["vehicles"] else ([], {})
        return kept, {**left_why, **dict.fromkeys(sorted(same), "the variant equals the base mission")}
    uas = "uas" if "uas" in stage1._classes(mission).values() else ""                    # the variants' UAS rows are 10 m profile rows (see wind_2d)
    try:
        with wind_2d(env, uas):
            return vehicle_rows(mission, stage1.run_batch(mission, env, members, seed, pri, marg, scales), env, fidelity, meta, variant), {}
    except OutsideData:
        pass
    def alone(v: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        one = solo(mission, v["id"])
        try:
            with wind_2d(env, stage1._classes(one)[v["id"]]):
                return vehicle_rows(one, stage1.run_batch(one, env, members, seed, pri, marg, scales), env, fidelity, meta, variant), None
        except OutsideData as e:
            return [], f"the variant leaves the environment data: {e}"
    cls = stage1._classes(mission)
    first = [v for v in mission["vehicles"] if cls[v["id"]] == "uas"]               # alone: wind_2d switches the shared environment's 3-D wind off
    rest = [v for v in mission["vehicles"] if cls[v["id"]] != "uas"]
    got = {v["id"]: alone(v) for v in first}
    with cf.ThreadPoolExecutor(par.width()) as threads:                               # the others at once, their tasks in the stage-1 workers
        got.update(zip((v["id"] for v in rest), threads.map(alone, rest) if par.width() > 1 else map(alone, rest), strict=True))
    rows = [r for v in mission["vehicles"] for r in got[v["id"]][0]]
    skipped = {v["id"]: why for v in mission["vehicles"] if (why := got[v["id"]][1]) is not None}
    return rows, skipped


def add_rows(path: Any, rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, str]:
    """Append rows to the training table (rows with a key already in it are replaced; see `row_key`). -> (whole table, the file used)."""
    p, _ = store_path(path)
    new = pd.DataFrame(rows)
    with locked(p):                                                               # concurrent runs share the table: one read-modify-write at a time
        df = pd.concat([read_table(p)[lambda d: ~d["key"].isin(new["key"])], new], ignore_index=True) if p.exists() else new
        write_table(df, p)
    return df, str(p)


# ------------------------------------------------------------------------------------------------------ training design

def _fits(mission: dict[str, Any], vid: str, mod: dict[str, Any]) -> dict[str, Any]:
    """The change shrunk until it is valid: shift and move halved together, then (a move that cannot be made at any size: a vehicle at the box
    edge) the move dropped and the shift halved with the duty kept. The all-zero change only when nothing valid is left."""
    for shift_s, move_s in [(0.5 ** k, 0.5 ** k) for k in range(5)] + [(0.5 ** k, 0.0) for k in range(5)]:
        m = dict(mod, shift_h=mod["shift_h"] * shift_s, dlon=mod["dlon"] * move_s, dlat=mod["dlat"] * move_s)
        try:
            apply(mission, {vid: m})
            return m
        except Invalid:
            continue
    return dict(shift_h=0.0, dlon=0.0, dlat=0.0, duty=1.0)


def is_base(mod: dict[str, Any]) -> bool:
    """The change moves nothing: the variant of this vehicle is the base mission again."""
    return not (mod.get("shift_h") or mod.get("dlon") or mod.get("dlat")) and mod.get("duty", 1.0) == 1.0


def design(mission: dict[str, Any], n: int, seed: int) -> list[dict[str, Any]]:
    """n mission variants for training: per vehicle a Latin-hypercube point over shift, move and duty (each vehicle its own), so one
    Stage-1 run of the variant gives every vehicle a different row."""
    out: list[dict[str, Any]] = [{} for _ in range(n)]
    t0, t1 = _window(mission)
    for i, v in enumerate(mission["vehicles"]):
        u = qmc.LatinHypercube(d=4, seed=seed + i).random(n)
        if "base" in v:
            lo, hi, duty = -12.0, 12.0, True
        else:
            d = utc(v["deploy"]["time"]).timestamp()
            lo, hi, duty = -min(24.0, (d - t0) / 3600.0), min(48.0, 0.5 * (t1 - d) / 3600.0), "dive_depth_m" in v["task"]
        for k in range(n):
            # a UAS period is whole days (see `_duty_days`), so its duty is 1 or 1/2: a continuous duty would give every training row 2 d and the baseline's 1 d
            # would be out of the emulator's range
            d_k = (1.0 if u[k, 3] < 0.5 else 0.5) if "base" in v else 1.0 - 0.5 * u[k, 3] if duty else 1.0
            mod = dict(shift_h=lo + u[k, 0] * (hi - lo), dlon=-1.0 + 2.0 * u[k, 1], dlat=-1.0 + 2.0 * u[k, 2], duty=d_k)
            out[k][v["id"]] = _fits(mission, v["id"], mod)
    return out


# ------------------------------------------------------------------------------------------------------ fit and score

def _clean(df: pd.DataFrame, cls: str) -> pd.DataFrame:
    need = BASE + TASK[cls] + ["p_fail", "t_fail_h"]
    d = df[df["cls"] == cls].reindex(columns=sorted(set(df.columns) | set(need)))                  # a table of other classes has no columns of this one
    for c in [c for c in d if c.startswith("mode_")]:
        d[c] = d[c].fillna(0.0)
    return d.dropna(subset=need).reset_index(drop=True)


DRAWS = ("Each variant of a run is run on its own members (variant k: the block of `batch` members after the ones Stage 1b used, k blocks further on), so "
         "its hypercube and noise streams are independent of every other training row of the run, the baseline row included; rows of other runs were "
         "made with their own seeds. The hold-out is therefore not scored against targets that share draws with the training points, and the `fresh` "
         "check re-estimates up to 3 held-out points of this run on members used nowhere else.")


def key_cols(cls: str) -> list[str]:
    """The columns that define a mission (where and when it starts and its task), not the environment medians of one member draw: replicates of a mission
    differ in those, and are one feature point."""
    return BASE[:3] + TASK[cls]


def fit_class(df: pd.DataFrame, cls: str, path: Any, code_digest: str | None = None, fresh: FreshDraw | None = None) -> tuple[Emulator | None, dict[str, Any]]:
    """Fit the emulator of one vehicle class on its rows and score it on a 20 % hold-out (split by distinct feature point, see
    `Emulator.holdout_report`; a point is the mission-defining columns, `key_cols`). With `code_digest`, rows made by other code (or by code
    of unknown digest) stay in the table but are not trained on.
    With `fresh` (see `Emulator.holdout_report`) the hold-out also scores the emulator against P(fail) re-estimated on fresh members, and the RMSE
    gate uses the larger of the two debiased RMSEs.
    The `MIN_ROWS` gate counts distinct feature points, so reruns of one mission cannot reach it. -> (Emulator | None, info for holdout.json)."""
    d = _clean(df, cls)
    stale = 0
    if code_digest is not None:
        keep = (d["code_digest"] == code_digest).to_numpy() if "code_digest" in d else np.zeros(len(d), bool)
        stale = int((~keep).sum())
        d = d[keep].reset_index(drop=True)
    points = int(len(d[key_cols(cls)].round(9).drop_duplicates()))
    info: dict[str, Any] = dict(trained=False, cls=cls, rows=int(len(d)), points=points, stale_rows=stale, used=False)
    if points < MIN_ROWS:
        more = f"; only {points} of them are distinct feature points" if points < len(d) else ""
        old = f"; {stale} rows made by other code are left out" if stale else ""
        why = f"{len(d)} {cls} rows in the training table, {MIN_ROWS} are needed (a 20 % hold-out must score 90 % coverage){more}{old}"
        return None, dict(info, reason=why, unused_reason=why)
    if np.ptp(d["p_fail"]) == 0:
        why = f"P(fail) is {d['p_fail'].iloc[0]:.3f} in all {len(d)} {cls} rows: nothing to learn"
        return None, dict(info, reason=why, unused_reason=why)
    modes = [c for c in d.columns if c.startswith("mode_") and d[c].std() > 0]
    modes = sorted(modes, key=lambda c: -d[c].std())[:MODES_MAX]
    em = Emulator(BASE + TASK[cls], ["p_fail", "t_fail_h"] + modes, path, point_cols=key_cols(cls))
    em.fit(d, holdout=0.2, fresh=fresh)
    x = d.iloc[0][em.features]
    em.query(x)
    ts: list[float] = []
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
    fr = h.get("fresh")
    fresh_info: dict[str, Any] = dict(fresh_points=0)
    if fr:                                                                             # the same debiasing: the fresh targets are n-member estimates too
        pf = np.array(fr["p_fresh"])
        ffloor = float(np.sqrt(np.mean(pf * (1 - pf) / fr["n_members"])))
        fresh_info = dict(fresh_points=fr["points"], fresh_n_members=fr["n_members"], rmse_fresh=fr["rmse"], noise_floor_fresh=ffloor,
                          rmse_fresh_debiased=float(np.sqrt(max(fr["rmse"] ** 2 - ffloor ** 2, 0.0))))
    gate = max(deb, fresh_info.get("rmse_fresh_debiased", 0.0))
    acc = dict(rmse_ok=bool(gate <= LIMITS["rmse"]), coverage_ok=bool(abs(h["coverage"]["p_fail"] - h["nominal"]) <= LIMITS["coverage"]),
               query_ok=bool(q <= LIMITS["query_ms"]))
    missed = [n for n, ok in (("RMSE", acc["rmse_ok"]), ("coverage", acc["coverage_ok"]), ("query time", acc["query_ok"])) if not ok]
    # a calibrated emulator's held-out hit count is Binomial(n_test, nominal); on 20 to 30 points that alone misses the +-0.05 gate often
    k = np.arange(h["n_test"] + 1)
    chance = float(binom.pmf(k[np.abs(k / max(h["n_test"], 1) - h["nominal"]) > LIMITS["coverage"] + 1e-12], h["n_test"], h["nominal"]).sum())
    return em, dict(info, trained=True, n_train=h["n_train"], n_test=h["n_test"], nominal=h["nominal"], rmse=h["rmse"], coverage=h["coverage"],
                    coverage_raw_p=h["coverage_raw_p"], coverage_chance_fail=chance, used=not missed,
                    unused_reason=f"the {cls} emulator missed BRIEF 2.7 acceptance ({', '.join(missed)}), so Stage 1 answers" if missed else None,
                    query_ms=q, noise_floor_rmse=floor, rmse_debiased=deb, rmse_gate=gate, **fresh_info,
                    draws=DRAWS, acceptance=acc, threshold=em.threshold, multi_fidelity=em.multi_fidelity)


def train(table: Any, classes: Any, path: Any = None, df: pd.DataFrame | None = None, code_digest: str | None = None,
          fresh: FreshDraw | None = None) -> dict[str, tuple[Emulator | None, dict[str, Any]]]:
    """Fit the emulator of each class in `classes` from the stored table (all runs, all missions), or from `df` when given (the pipeline
    trains on a snapshot of the table, not on whatever the table holds by now). Only rows made by the current code are trained on:
    `code_digest` (default: this checkout's, `pipeline.code_digest`); superseded rows stay in the file."""
    from . import pipeline
    p, _ = store_path(table)
    if df is None:
        df = read_table(p) if p.exists() else pd.DataFrame(columns=["cls"] + BASE)
    cd = code_digest or pipeline.code_digest()
    return {c: fit_class(df, c, path or table, cd, fresh) for c in sorted(set(classes))}


def snapshot(table: Any, dest: Any, run_id: str) -> tuple[pd.DataFrame, pathlib.Path]:
    """The training table as it is now, without the rows `run_id` wrote (its own earlier attempt), copied to `dest` (a path; its suffix is
    replaced by what the table is stored as). The run trains on this copy and names its file as a ledger input, so the emulator is a function
    of a hashed input that nothing else changes while the run goes. -> (the rows, the file)."""
    p, _ = store_path(table)
    df = read_table(p) if p.exists() else pd.DataFrame(columns=["cls", "key", "run_id"] + BASE)
    df = df[df["run_id"] != run_id].reset_index(drop=True) if "run_id" in df else df
    out, _ = store_path(pathlib.Path(dest).with_suffix(".parquet"))
    write_table(df, out)
    return df, out


def with_rows(df: pd.DataFrame, rows: list[dict[str, Any]]) -> pd.DataFrame:
    """`df` plus `rows`; a row whose key is already in `df` replaces it (what add_rows does to the stored table)."""
    new = pd.DataFrame(rows)
    if not len(new):
        return df
    return pd.concat([d for d in (df[~df["key"].isin(new["key"])] if "key" in df else df, new) if len(d)], ignore_index=True)


# ------------------------------------------------------------------------------------------------------ flip search

def usable(ems: dict[str, tuple[Emulator | None, dict[str, Any]]], cls: str) -> tuple[Emulator | None, str | None]:
    """(the class's emulator, None) when it may answer; (None, why) when there is none or it missed BRIEF 2.7 acceptance (`used` False in its info):
    Stage 1 answers then, and `why` is the reason to show beside the old "no emulator"."""
    em, info = ems.get(cls) or (None, {})
    if em is None or info.get("used", True):
        return em, info.get("unused_reason")
    return None, info.get("unused_reason")


def candidates(mission: dict[str, Any], vid: str) -> list[dict[str, Any]]:
    """Single changes in cost order: deploy +-6/12/24/48 h, +-0.5/1 degree in lon or lat, lower duty. Each: mod, cost (notches), change (words)."""
    v = vehicle(mission, vid)
    whole_days = "base" in v                                                  # a UAS shifted by whole days flies at the same time of day: not a change
    out: list[dict[str, Any]] = [dict(mod=dict(shift_h=s * h), cost=h / 6.0) for h in SHIFTS for s in (1, -1) if not (whole_days and h % 24 == 0)]
    out += [dict(mod={ax: s * d}, cost=d / 0.5) for d in MOVES for ax in ("dlon", "dlat") for s in (1, -1)]
    if "base" in v or "dive_depth_m" in v["task"]:
        out += [dict(mod=dict(duty=f), cost=(1 - f) / 0.25) for f in DUTIES]
    for c in out:
        c["change"] = describe(c["mod"], v)
    return sorted(out, key=lambda c: c["cost"])


def predict(em: Emulator | None, mission: dict[str, Any], vid: str, cls: str, trk: Track | None, mod: dict[str, Any], env: Any) -> dict[str, Any]:
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
    try:
        return emulate(em, {**params(mission, vid, cls), **env_stats(env, *track)})
    except OutsideData as e:
        raise Invalid(f"{vid}: the changed track leaves the environment data ({e})") from e


def emulate(em: Emulator, feats: dict[str, Any]) -> dict[str, Any]:
    """The emulator's answer for one feature dict, or why it cannot answer: status ok | out_of_range | no_track (a feature is missing)."""
    x = {k: feats.get(k, np.nan) for k in em.features}
    if not np.all(np.isfinite(list(x.values()))):
        return dict(status="no_track")
    q = em.query(x)
    if q["status"] != "ok":
        return dict(status="out_of_range", distance=q["distance"], threshold=q["threshold"])
    p = q["targets"]["p_fail"]
    return dict(status="ok", p_fail=p["value"], lo=p["lo"], hi=p["hi"], verdict=q["verdict"], distance=q["distance"], threshold=q["threshold"])


def measure(mission: dict[str, Any], vid: str, env: Any, plan: dict[str, Any], pri: dict[str, dict[str, Any]], marg: dict[str, dict[str, Any]],
            scales: dict[str, Any] | None, seed: int, n: int | None = None, members: list[int] | None = None) -> dict[str, Any]:
    """Stage 1 for one vehicle of the (changed) mission: one batch of the plan's size, the base run's members (common random numbers) unless `members`
    names others (the emulator's fresh-draw check)."""
    members = members or list(range(n or plan["batch"]))
    one = solo(mission, vid)
    try:
        with wind_2d(env, stage1._classes(one)[vid]):
            r = stage1.run_batch(one, env, members, seed, pri, marg, scales)["vehicles"][vid]
    except OutsideData as e:
        raise Invalid(f"{vid}: the changed mission leaves the environment data ({e})") from e
    f = stage1.failed(r)
    v = intervals.verdict(int(f.sum()), len(f))
    return dict(p_fail=float(f.mean()), lo=v["fail_lo"], hi=v["fail_hi"], verdict=v["verdict"], n=int(len(f)))


def flip_search(mission: dict[str, Any], verdicts: dict[str, Any], tracks: dict[str, Track], env: Any, ems: dict[str, tuple[Emulator | None, dict[str, Any]]],
                plan: dict[str, Any], pri: dict[str, dict[str, Any]], marg: dict[str, dict[str, Any]], scales: dict[str, Any] | None, seed: int,
                budget_s: float, log: Callable[[str], None] = print) -> tuple[dict[str, Any], float]:
    """For each vehicle whose verdict is not GO, the cheapest single change that makes it GO (a NO-GO: at least MARGINAL).

    Emulator first: every candidate within the emulator's training range is answered by it. Candidates it cannot answer (no emulator, no
    track, out of range) are run in Stage 1, nearest first, at most FALLBACK_K and only while the vehicle's share of `budget_s` lasts: the
    budget left is split equally over the vehicles still to search, so one vehicle cannot use the whole of it and a share one vehicle does not
    need goes to the next. The best candidate is the cheapest one in the target set among those answered. Each result says how many
    candidates were `evaluated`, how many are `invalid` (off the window or the box, or past the environment data: they can never be evaluated)
    and how many are `candidates` (the rest), so "nothing flips it" is never read as more than what was tried.
    -> ({vid: result}, planned seconds of Stage 1 spent: each fallback is charged `budget.batch_cost_s`, so the search does not depend on how
    fast the machine happens to be)."""
    out: dict[str, Any] = {}
    spent = 0.0
    todo = [vid for vid, base in verdicts.items() if base["verdict"] != "GO"]
    for i, vid in enumerate(todo):
        base = verdicts[vid]
        share = (budget_s - spent) / (len(todo) - i)
        used = 0.0
        cls = stage1._classes(solo(mission, vid))[vid]
        want = ("GO",) if base["verdict"] == "MARGINAL" else ("GO", "MARGINAL")
        em, no_em = usable(ems, cls)
        tried: list[dict[str, Any]] = []
        left: list[tuple[int, dict[str, Any]]] = []
        for c in candidates(mission, vid):
            e = dict(change=c["change"], mod=c["mod"], cost=c["cost"], method="not evaluated", reason="", invalid=False)
            try:
                m2 = apply(mission, {vid: c["mod"]})
                a = predict(em, m2, vid, cls, tracks.get(vid), c["mod"], env)
            except Invalid as ex:                                           # off the window or the box, or its track leaves the environment data
                tried.append(dict(e, reason=str(ex), invalid=True))
                continue
            if a["status"] == "ok":
                tried.append(dict(e, method="EMULATED", **{k: a[k] for k in ("p_fail", "lo", "hi", "verdict", "distance", "threshold")}))
            else:
                tried.append(dict(e, reason=(no_em if a["status"] == "no_emulator" and no_em else a["status"].replace("_", " "))))
                left.append((len(tried) - 1, m2))
        if not any(t["method"] == "EMULATED" and t["verdict"] in want for t in tried):
            for j, m2 in left[:FALLBACK_K]:
                cost = budget.batch_cost_s(plan, [vid])
                if used + cost > share:
                    tried[j]["reason"] += "; Stage 1 not run: this vehicle's share of the emulator budget is spent"
                    break
                try:
                    tried[j].update(method="Stage 1", **measure(m2, vid, env, plan, pri, marg, scales, seed))
                except Invalid as ex:                                       # the run left the environment data: no number, and the reason
                    tried[j].update(reason=tried[j]["reason"] + f"; Stage 1 not run: {ex}", invalid=True)
                    continue
                used += cost                                                # the planner's cost, never the clock: the same search on every run
                if tried[j]["verdict"] in want:
                    break
        wind_model, base_2d = None, None
        if cls == "uas" and hasattr(env, "use_3d"):                               # the baseline as the candidates are measured (no 3-D wind), if share is left
            wind_model = WIND_MODEL_2D
            cost = budget.batch_cost_s(plan, [vid])
            if used + cost <= share:
                try:
                    b2 = measure(mission, vid, env, plan, pri, marg, scales, seed)
                    base_2d, used = dict(verdict=b2["verdict"], p_fail=b2["p_fail"], lo=b2["lo"], hi=b2["hi"]), used + cost
                except Invalid:                                                   # the baseline left the data: no number
                    pass
        spent += used
        hit = [t for t in tried if t["method"] != "not evaluated" and t["verdict"] in want]
        best = min(hit, key=lambda t: t["cost"]) if hit else None
        evaluated, invalid = sum(t["method"] != "not evaluated" for t in tried), sum(t["invalid"] for t in tried)
        out[vid] = dict(verdict=base["verdict"], p_fail=base["p_fail"], target=" or ".join(want), found=best is not None, best=best, tried=tried,
                        emulator=em is not None, evaluated=evaluated, invalid=invalid, candidates=len(tried) - invalid, wind_model=wind_model,
                        base_2d=base_2d)
        log(f"flip search {vid}: " + (f"{best['change']} ({best['method']})" if best else
                                      f"nothing flips it among the {evaluated} evaluated of {len(tried) - invalid} candidates"))
    return out, spent


# ------------------------------------------------------------------------------------------------------ the what-if command

def _parse(text: str, pat: str, what: str, example: str) -> re.Match[str]:
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


def answer(mission: dict[str, Any], ops: dict[str, Any], base: dict[str, Any], tracks: dict[str, Track], env: Any,
           ems: dict[str, tuple[Emulator | None, dict[str, Any]]], plan: dict[str, Any], fitted: dict[str, Any] | None, scales: dict[str, Any] | None,
           only: list[str] | None = None) -> dict[str, Any]:
    """The what-if: `ops` = dict(shift_h, dlon, dlat, drop=[ids]) applied to every vehicle (or to `only`). `base` = {vid: Stage-1 verdict dict}
    of the unchanged mission. Per changed vehicle: emulator-first, else Stage 1 at `plan`. Dropped vehicles need no run: Stage-1 vehicles do not
    interact, only the links through them go. -> dict(vehicles={vid: ...}, dropped, links_removed, unchanged={vid: why}): `unchanged` holds a UAS
    whose launch shift is whole days (the same time of day), left out of `vehicles` unless a move applies to it."""
    pri, marg = stage1.priors_for(mission, fitted)
    seed = int(mission["seed"])
    drop = list(ops.get("drop", []))
    mod = dict(shift_h=ops.get("shift_h", 0.0), dlon=ops.get("dlon", 0.0), dlat=ops.get("dlat", 0.0))
    live = [v["id"] for v in mission["vehicles"] if v["id"] not in drop and (only is None or v["id"] in only)]
    for vid in only or []:
        vehicle(mission, vid)
    changed = {vid: mod for vid in live} if any(mod.values()) else {}
    unchanged: dict[str, str] = {}
    for vid in list(changed):                   # a UAS shifted by whole days keeps its launch time of day: apply() refuses it, the answer says so and goes on
        if "base" in vehicle(mission, vid) and _whole_days(mod["shift_h"]):
            unchanged[vid] = f"launching {mod['shift_h']:+g} h later keeps the same launch time of day: nothing changes"
            if mod["dlon"] or mod["dlat"]:
                changed[vid] = dict(mod, shift_h=0.0)
            else:
                del changed[vid]
    m2 = apply(mission, changed, drop)
    out: dict[str, Any] = {}
    for vid in changed:
        cls = stage1._classes(solo(m2, vid))[vid]
        b = base.get(vid)
        if b is None:
            b = measure(mission, vid, env, plan, pri, marg, scales, seed)
            b = dict(verdict=b["verdict"], p_fail=b["p_fail"])
        em, no_em = usable(ems, cls)
        a = predict(em, m2, vid, cls, tracks.get(vid), mod, env)
        if a["status"] == "ok":
            out[vid] = dict(base=b, method="EMULATED", **{k: a[k] for k in ("p_fail", "lo", "hi", "verdict", "distance", "threshold")})
        else:
            why = no_em if a["status"] == "no_emulator" and no_em else a["status"].replace("_", " ")
            out[vid] = dict(base=b, method="Stage 1", why=why, **_stage1(m2, vid, env, plan, fitted, scales))
    gone = [k["id"] for k in mission["links"] if k["a"] in drop or k["b"] in drop]
    return dict(vehicles=out, dropped=drop, links_removed=gone, unchanged=unchanged)


def _stage1(mission: dict[str, Any], vid: str, env: Any, plan: dict[str, Any], fitted: dict[str, Any] | None,
            scales: dict[str, Any] | None) -> dict[str, Any]:
    """Stage 1 at the plan's budget (the sequential run, n_min .. n_max members) for one vehicle."""
    one = solo(mission, vid)
    with wind_2d(env, stage1._classes(one)[vid]):
        r = stage1.run(one, env, plan, None, lambda *_: None, scales, fitted)
    e = r["summary"]["vehicles"][vid]
    return dict(p_fail=e["verdict"]["p_fail"], lo=e["verdict"]["fail_lo"], hi=e["verdict"]["fail_hi"], verdict=e["verdict"]["verdict"], n=e["n"])
