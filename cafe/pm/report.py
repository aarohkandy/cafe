"""The report stage (BRIEF 2.9, 5.5): run directory -> run_dir/report/{index.html, report.json, credibility.html, credibility.json}.

    write(run_dir, mission, plan, env=None) -> [Path, ...]      what the pipeline records as the report ledger's outputs
    check_traceability(report) -> [str]                          empty when every number traces to a ledger and a receipt
    check_rendered(report, html_text) -> [str]                   empty when every number in the JSON shows up in the HTML

report.json is the source of truth; index.html is rendered from it and nothing else. Every number in it is a node
{value | values, unit, stage, source, uncertainty, receipt, ledger}: `stage` produced it, `source` is the file and field it was
read from, `uncertainty` is its 1-sigma or interval (None when exact), `receipt` is the id of a row of the report's `receipts`
table (a ledger check by name, else the sha-256 of the stage output the number was read from, else the stage's config hash) and
`ledger` is the run-relative path of that stage's ledger.json. A number outside a node, or a receipt that is missing or whose
check failed, is what check_traceability reports. Verdicts are those of the final ensemble, stage1b (a copy of stage 1 when
nothing was refit). res.pkl is unpickled only after its sha-256 matches the ledger's record of it.

The environment along the tracks is queried only when the caller passes `env` (an Environment, cafe.pm.env.protocol); res.pkl
holds positions and flags, not wind, waves or current, and the report says so when it cannot query them.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import pathlib
import pickle
import re
import warnings
from collections.abc import Iterator
from typing import Any

import numpy as np
from numpy.typing import NDArray

from . import budget, credibility
from .audit import STAGES
from .stage1 import _classes
from .env.remote import sha256

SCHEMA = "cafe.pm.report/1"
FORCING = {"glider": ("surface current speed", "m/s"), "usv": ("significant wave height", "m"), "uas": ("10 m wind speed", "m/s")}
NOT_PRESENT = "{} is not in the run directory"


def _jl(p: pathlib.Path) -> Any:
    return json.loads(p.read_text()) if p.is_file() else None


def _f(x: Any) -> Any:
    """A JSON-safe scalar: numpy scalars unwrapped, NaN and infinity become None."""
    x = x.item() if hasattr(x, "item") else x
    return None if isinstance(x, float) and not math.isfinite(x) else x


def _utc(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


# ------------------------------------------------------------------------------------------------------ the receipts table

class Trace:
    """Ledgers by stage, and the receipts table the numbers point into."""

    def __init__(self, run: pathlib.Path):
        self.run = run
        self.led = {st: _jl(run / "checkpoints" / st / "ledger.json") for st in STAGES}
        self.rows: dict[str, dict[str, Any]] = {}

    def _row(self, stage: str, rid: str, kind: str, name: str, ok: bool, got: str = "", limit: str = "", sha: str = "") -> None:
        self.rows.setdefault(rid, dict(id=rid, stage=stage, ledger=f"checkpoints/{stage}/ledger.json", kind=kind, name=name, ok=ok,
                                       got=got, limit=limit, sha256=sha))

    def ref(self, stage: str, check: str | None = None, output: str | None = None, label: str | None = None) -> dict[str, Any]:
        """The receipt for a number from `stage`: the first ledger check named `check*`, else the hash of its `output` file,
        else the config hash of the stage's ledger; a missing ledger gives a receipt that check_traceability flags."""
        L = self.led.get(stage)
        if not L:
            rid = f"{stage}:missing-ledger"
            self._row(stage, rid, "missing", "no ledger", False)
        else:
            c = next((c for c in L["checks"] if check and c["name"].startswith(check)), None)
            o = next((o for o in L["outputs"] if output and o["path"].endswith("/" + (output or ""))), None)
            if c:
                rid = f"{stage}:check:{c['name']}"
                self._row(stage, rid, "check", c["name"], c["ok"], repr(c["value"]), repr(c["limit"]))
            elif o:
                rid = f"{stage}:output:{output}"
                self._row(stage, rid, "output", output or "", True, sha=o["sha256"])
            else:
                rid = f"{stage}:config:{L['config_hash'][:12]}"
                self._row(stage, rid, "config", "config_hash", True, sha=L["config_hash"])
        return dict(stage=label or stage, ledger=f"checkpoints/{stage}/ledger.json", receipt=rid)

    def file_ref(self, path: pathlib.Path) -> dict[str, Any]:
        """A file the report stage itself writes: its hash now, its ledger when the stage closes."""
        rid = f"report:output:{path.name}"
        self._row("report", rid, "output", path.name, True, sha=sha256(path))
        return dict(stage="report", ledger="checkpoints/report/ledger.json", receipt=rid)


def num(v: Any, unit: str, ref: dict[str, Any], source: str, unc: Any = None, **extra: Any) -> dict[str, Any]:
    return dict(value=_f(v), unit=unit, stage=ref["stage"], source=source, uncertainty=credibility._clean(unc), receipt=ref["receipt"],
                ledger=ref["ledger"], **extra)


def vals(v: Any, unit: str, ref: dict[str, Any], source: str, unc: Any = None, **extra: Any) -> dict[str, Any]:
    return dict(values=credibility._clean(np.asarray(v, float).tolist()), unit=unit, stage=ref["stage"], source=source, uncertainty=credibility._clean(unc),
                receipt=ref["receipt"], ledger=ref["ledger"], **extra)


def tnum(t: float | None, ref: dict[str, Any], source: str) -> dict[str, Any] | None:
    return None if t is None else num(t, "s since 1970-01-01T00:00:00Z", ref, source, utc=_utc(t))


def _walk(o: Any, path: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield ("node", path, d) for every number node and ("bare", path, x) for a number outside one."""
    if isinstance(o, dict):
        if "values" in o or ("value" in o and (o["value"] is None or isinstance(o["value"], (int, float)))):
            yield "node", path, o
            return
        for k, v in o.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield "bare", path, o


def check_traceability(report: dict[str, Any]) -> list[str]:
    """Every number is a node with stage, source, uncertainty, unit, receipt and ledger, and its receipt is a passing row of the receipts table."""
    rows = {r["id"]: r for r in report.get("receipts", [])}
    bad = []
    for kind, path, o in _walk(report):
        if kind == "bare":
            bad.append(f"{path}: the number {o!r} is outside a traced value node")
            continue
        miss = [k for k in ("unit", "stage", "source", "uncertainty", "receipt", "ledger") if k not in o or (k not in ("unit", "uncertainty") and not o[k])]
        r = rows.get(o.get("receipt"))
        if miss:
            bad.append(f"{path}: missing {miss}")
        elif r is None:
            bad.append(f"{path}: receipt {o['receipt']!r} is not a row of the receipts table")
        elif r["ledger"] != o["ledger"]:
            bad.append(f"{path}: ledger {o['ledger']!r} is not the ledger of receipt {r['id']!r}")
        elif not r["ok"]:
            bad.append(f"{path}: receipt {r['id']!r} is missing or its check failed")
    return bad


# ------------------------------------------------------------------------------------------------------ builders

def _stat(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any]:
    """The verdict block shared by a vehicle and a link."""
    v = e["verdict"]
    unc = dict(kind=f"{v['method']} interval", conf=v["conf"], lo=v["fail_lo"], hi=v["fail_hi"])
    d = dict(verdict=v["verdict"], p_fail=num(v["p_fail"], "fraction", ref, src, unc), n=num(e["n"], "members", ref, src),
             k_fail=num(e["k_fail"], "members", ref, src), n_certify=num(v["n_certify"], "members", ref, src), note=v["note"], certify_statement=None)
    if e["n"] < v["n_certify"]:
        d["certify_statement"] = (f"P(fail) < 5 % cannot be certified at n = {e['n']}: {v['n_certify']} members are needed "
                                  f"(with zero failures n members only show P(fail) < 3/n = {3 / e['n']:.3f}).")
    return d


def _sens(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any]:
    p = e["sensitivity"]["param"]
    return dict(param=p, s1=None if p is None else num(e["sensitivity"]["S1"][p], "fraction of variance", ref, src))


def _top3(e: dict[str, Any], ref: dict[str, Any], src: str) -> list[Any]:
    """The three perturbation parameters with the largest Sobol first-order index (EASI estimate, stats.sensitivity), largest first."""
    s1 = e["sensitivity"]["S1"] or {}
    return [dict(param=p, s1=num(x, "fraction of variance", ref, f"{src}.sensitivity.S1.{p}")) for p, x in sorted(s1.items(), key=lambda kv: -kv[1])[:3]]


def _fix(flip: dict[str, Any] | None, vid: str, tr: Trace) -> dict[str, Any]:
    """The "what would fix it" line of one vehicle from emulator/flip.json (BRIEF 2.5): the smallest change that flips the verdict, and what was tried."""
    if flip is None:
        return dict(available=False, reason=NOT_PRESENT.format("emulator/flip.json"))
    f = flip["vehicles"].get(vid)
    if f is None:
        return dict(available=True, needed=False)
    ref, src = tr.ref("emulator", output="flip.json"), f"emulator/flip.json vehicles.{vid}"

    def one(t: dict[str, Any], path: str) -> dict[str, Any]:
        """A tried change: its P(fail) with the interval of its method, and how it was answered."""
        kind = "conformal 90 % interval (emulator)" if t["method"] == "EMULATED" else "Wilson interval (Stage 1)"
        d = dict(change=t["change"], method=t["method"], reason=t["reason"], verdict=t.get("verdict"),
                 cost=num(t["cost"], "notches", ref, src + path + ".cost"))
        d["p_fail"] = num(t["p_fail"], "fraction", ref, src + path + ".p_fail", dict(kind=kind, lo=t["lo"], hi=t["hi"])) if "p_fail" in t else None
        d["distance"] = num(t["distance"], "z-scored", ref, src + path + ".distance") if "distance" in t else None
        d["threshold"] = num(t["threshold"], "z-scored", ref, src + path + ".threshold") if "threshold" in t else None
        d["n"] = num(t["n"], "members", ref, src + path + ".n") if "n" in t else None
        return d
    return dict(available=True, needed=True, found=bool(f["found"]), target=f["target"], emulator_trained=bool(f["emulator"]),
                verdict_before=f["verdict"], p_fail_before=num(f["p_fail"], "fraction", ref, src + ".p_fail"),
                best=one(f["best"], ".best") if f["best"] else None, tried=[one(t, f".tried[{i}]") for i, t in enumerate(f["tried"])])


def _vehicles(s1b: dict[str, Any], s1: dict[str, Any] | None, mission: dict[str, Any], cred: dict[str, Any], tr: Trace, cred_ref: dict[str, Any],
              flip: dict[str, Any] | None = None) -> dict[str, Any]:
    ref = tr.ref("stage1b", check="lhs_stratified", output="summary.json")
    plat = {v["id"]: v["platform"] for v in mission["vehicles"]}
    out = {}
    for vid, e in s1b["summary"]["vehicles"].items():
        src = f"stage1b/summary.json summary.vehicles.{vid}"
        before = ((s1 or {}).get("summary") or {}).get("vehicles", {}).get(vid)
        p = plat.get(vid)
        out[vid] = dict(cls=e["cls"], platform=p, **_stat(e, ref, src + ".verdict (stats.intervals.verdict)"),
                        dominant_mode=e["dominant"], modes={k: num(n, "members", ref, f"{src}.modes") for k, n in e["modes"].items()},
                        first_fail=tnum(e["first_fail_t"], ref, f"{src}.first_fail_t"), median_fail=tnum(e["median_fail_t"], ref, f"{src}.median_fail_t"),
                        sensitivity=_sens(e, ref, f"{src}.sensitivity (stats.sensitivity, EASI first-order)"), top3=_top3(e, ref, src),
                        fix=_fix(flip, vid, tr),
                        verdict_stage1=before["verdict"]["verdict"] if before else None,
                        changed_by_refit=bool(before and before["verdict"]["verdict"] != e["verdict"]["verdict"]),
                        assumed_platform_inputs=num(cred["platform_assumed_counts"].get(p, 0), "inputs", cred_ref, "credibility.json platform_assumed_counts"),
                        assumed_anchor=f"credibility.html#plat-{p}")
    return out


def _links(s1b: dict[str, Any], tr: Trace) -> dict[str, Any]:
    ref = tr.ref("stage1b", check="lhs_stratified", output="summary.json")
    out = {}
    for lid, e in s1b["summary"]["links"].items():
        src = f"stage1b/summary.json summary.links.{lid}"
        out[lid] = dict(**_stat(e, ref, src + ".verdict (stats.intervals.verdict)"), method=e["method"], sensitivity=_sens(e, ref, src + ".sensitivity"),
                        top3=_top3(e, ref, src),
                        frac_median=num(e["frac_median"], "fraction", ref, src), frac_p10=num(e["frac_p10"], "fraction", ref, src),
                        margin_db_median=None if e["margin_db_median"] is None else num(e["margin_db_median"], "dB", ref, src))
    return out


def _load_res(run: pathlib.Path, tr: Trace) -> tuple[dict[str, Any] | None, str]:
    """res.pkl of stage 1b, unpickled only if its hash matches the ledger's record of it."""
    p = run / "stage1b" / "res.pkl"
    L = tr.led["stage1b"]
    rec = next((o["sha256"] for o in (L or {}).get("outputs", []) if o["path"].endswith("/res.pkl")), None)
    if not p.is_file():
        return None, NOT_PRESENT.format("stage1b/res.pkl")
    if rec is None or sha256(p) != rec:
        return None, "stage1b/res.pkl does not match the sha-256 in the stage1b ledger, so it was not loaded"
    # hash-verified against the ledger just above: the file is this pipeline's own checkpoint, never foreign data
    return pickle.loads(p.read_bytes()), ""


def _failed(r: dict[str, Any]) -> np.ndarray:
    return np.logical_or.reduce([np.asarray(v, bool) for v in r["fail"].values()]) if r["fail"] else np.zeros(r["lon"].shape[1], bool)


def _unwrap(lon: np.ndarray, c: float) -> np.ndarray:
    return np.mod(np.asarray(lon, float) - c + 180.0, 360.0) - 180.0 + c


def _pts(lon: np.ndarray, lat: np.ndarray, n: int = 120) -> list[Any]:
    """[lon, lat] pairs without NaN, at most n of them, longitudes in [-180, 180)."""
    ok = np.isfinite(lon) & np.isfinite(lat)
    lon, lat = lon[ok], lat[ok]
    i: Any = np.unique(np.linspace(0, max(len(lon) - 1, 0), min(len(lon), n)).astype(int)) if len(lon) else []
    return [[float(np.mod(lon[j] + 180.0, 360.0) - 180.0), float(lat[j])] for j in i]


def _median_track(r: dict[str, Any], c: float) -> tuple[np.ndarray, np.ndarray]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmedian(_unwrap(r["lon"], c), 1), np.nanmedian(np.asarray(r["lat"], float), 1)


def _map(mission: dict[str, Any], res: dict[str, Any] | None, why: str, wins: dict[str, Any] | None, tr: Trace, cfg: dict[str, Any]) -> dict[str, Any]:
    if res is None:
        return dict(available=False, reason=why)
    b = mission["box"]
    lo, hi = b["lon_min"], b["lon_max"]
    c = lo + ((hi - lo) % 360.0) / 2
    ref = tr.ref("stage1b", output="res.pkl")
    box = vals([lo, hi, b["lat_min"], b["lat_max"]], "deg", cfg, "mission.yaml box (lon_min, lon_max, lat_min, lat_max)")
    out: dict[str, Any] = dict(available=True, box=box, ship=None, vehicles={}, windows={})
    if "ship" in mission:
        out["ship"] = vals([mission["ship"]["lon"], mission["ship"]["lat"]], "deg", cfg, "mission.yaml ship (lon, lat)")
    deploy = {v["id"]: v["deploy"] for v in mission["vehicles"] if "deploy" in v}
    for vid, r in res["vehicles"].items():
        src = f"stage1b/res.pkl vehicles.{vid}.lon/lat"
        lon, lat = _median_track(r, c)
        f = _failed(r)
        pick = list(np.flatnonzero(f)[:2]) + list(np.flatnonzero(~f)[:2])
        unc = dict(kind="ensemble spread", members=int(f.size))
        out["vehicles"][vid] = dict(
            cls=r["class"], deploy=vals([deploy[vid]["lon"], deploy[vid]["lat"]], "deg", cfg, "mission.yaml deploy (lon, lat)") if vid in deploy else None,
            median=vals(_pts(lon, lat), "deg", ref, src + " (median over members, [lon, lat])", unc),
            members=[dict(label=f"member {m}" + (" (failed)" if f[m] else ""), failed=bool(f[m]),
                          track=vals(_pts(_unwrap(r["lon"][:, m], c), np.asarray(r["lat"][:, m], float)), "deg", ref, src + f"[:, {m}]", None)) for m in pick])
    wref = tr.ref("windows", output="windows.json")
    for vid, ws in (wins or {}).items():
        out["windows"][vid] = [dict(label=f"W{i + 1}", t=tnum(w["t"], wref, f"windows/windows.json {vid}[{i}].t"),
                                    position=vals([w["lon"], w["lat"]], "deg", wref, f"windows/windows.json {vid}[{i}].lon/lat")) for i, w in enumerate(ws)]
    return out


def _reach(mission: dict[str, Any], env: Any, tr: Trace) -> dict[str, Any]:
    """Where each drifting vehicle can get to within reach.horizon_h of its deploy, in the environment's currents at the deploy time: the fastest
    route over a 41 x 41 grid (cafe.reach: Zermelo speed made good, Dijkstra over 16 neighbours; land and water outside the ingested data blocked), drawn as the
    farthest reachable cell in each of 24 bearings. A UAS is not drawn: it flies sorties from the ship."""
    from cafe import reach as legacy
    from .config import assumptions
    if env is None:
        return dict(available=False, reason="The report was not given an Environment, so there are no currents to route through.", vehicles={})
    a = assumptions()
    ref = tr.ref("ingest", check="ocean_source", label="report (reach map routed through the environment's currents at the deploy time)")
    hours, allow, cls = a["reach.horizon_h"]["value"], a["reach.fluid_allowance_ms"]["value"], _classes(mission)
    out: dict[str, Any] = {}
    for v in mission["vehicles"]:
        vid = v["id"]
        if cls[vid] == "uas":
            out[vid] = dict(available=False, reason="A UAS flies its sorties from the ship; how far it gets is a battery and wind question "
                                                    "(physics.uas), not a drift route.")
            continue
        src = f"cafe.reach._dijkstra over env.current at the deploy time; speed from config/assumptions.yaml reach.speed_ms.{cls[vid]}"
        try:
            out[vid] = _reach_one(legacy, env, v, cls[vid], a[f"reach.speed_ms.{cls[vid]}"]["value"], hours, allow, ref, src)
        except Exception as ex:                                           # noqa: BLE001  any failure of the environment is reported, not hidden
            out[vid] = dict(available=False, reason=f"{type(ex).__name__}: {ex}")
    return dict(available=True, vehicles=out, horizon=num(hours, "h", ref, "config/assumptions.yaml reach.horizon_h"))


def _reach_one(legacy: Any, env: Any, v: dict[str, Any], cls: str, speed: float, hours: float, allow: float, ref: dict[str, Any], src: str, n: int = 41,
               nb: int = 24) -> dict[str, Any]:
    d = v["deploy"]
    R = (speed + allow) * hours * 3600.0
    xs = np.linspace(-R, R, n)
    NN, EE = np.meshgrid(xs, xs, indexing="ij")
    lat = d["lat"] + np.degrees(NN.ravel() / 6.371e6)
    lon = ((d["lon"] + np.degrees(EE.ravel() / (6.371e6 * math.cos(math.radians(d["lat"])))) + 180.0) % 360.0) - 180.0
    t = np.full(lat.size, utc_s(d["time"]))
    ins = np.asarray(env.inside(lon, lat, t), bool) if hasattr(env, "inside") else np.ones(lat.size, bool)    # outside the ingested data: unknown water
    zs = np.linspace(-5.0, -100.0, 6) if cls == "glider" else [0.0]                 # a glider feels the current over its dive band
    cur = np.full((lat.size, 2), np.nan)
    cur[ins] = np.mean([np.asarray(env.current(lon[ins], lat[ins], z, t[ins]).value, float) for z in zs], 0)
    flow = cur[:, ::-1].reshape(n, n, 2)                                              # (east, north) -> (north, east)
    land = np.zeros(lat.size, bool)
    land[ins] = np.asarray(env.depth(lon[ins], lat[ins]).value, float) <= 0.0
    land = land.reshape(n, n)
    h, c0 = xs[1] - xs[0], n // 2
    if land[c0, c0] or not np.isfinite(flow[c0, c0]).all():
        raise ValueError("the deploy point is on land or has no current data")
    tt = legacy._dijkstra(np.nan_to_num(flow, nan=1e3), land | ~np.isfinite(flow).all(2), speed, h, hours * 3600.0)
    ok = tt <= hours * 3600.0
    ang = np.degrees(np.arctan2(EE, NN)) % 360.0
    rad = np.hypot(NN, EE)
    far, th = np.zeros(nb), np.zeros(nb)
    for k in range(nb):                                                              # the farthest reachable cell of each 15-degree sector, at its own bearing
        m = ok & (ang // (360.0 / nb) == k)
        if m.any():
            i = np.argmax(np.where(m, rad, -1.0))
            far[k], th[k] = rad.ravel()[i], np.radians(ang.ravel()[i])
    pl = [[float(((d["lon"] + math.degrees(r * math.sin(a) / (6.371e6 * math.cos(math.radians(d["lat"])))) + 180.0) % 360.0) - 180.0),
           float(d["lat"] + math.degrees(r * math.cos(a) / 6.371e6))] for r, a in zip(far, th, strict=True)]
    return dict(available=True, polygon=vals(pl, "deg", ref, src + " (farthest reachable cell per bearing, [lon, lat])"),
                max_range_km=num(far.max() / 1e3, "km", ref, src), speed=num(speed, "m/s", ref, f"config/assumptions.yaml reach.speed_ms.{cls}"),
                flow_max=num(float(np.nanmax(np.hypot(flow[..., 0], flow[..., 1]))), "m/s", ref, src + " (largest current on the grid)"),
                deploy=vals([d["lon"], d["lat"]], "deg", ref, "mission.yaml deploy (lon, lat)"))


def utc_s(s: str) -> float:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc).timestamp()


def _env(mission: dict[str, Any], env: Any, res: dict[str, Any] | None, wins: dict[str, Any] | None, summ: dict[str, Any], tr: Trace) -> dict[str, Any]:
    cls = {v: e["cls"] for v, e in summ["summary"]["vehicles"].items()}
    wref = tr.ref("windows", output="windows.json")
    forcing = {}
    for vid, ws in (wins or {}).items():
        name, unit = FORCING[cls[vid]]
        src = f"windows/windows.json {vid}"
        forcing[vid] = dict(quantity=name, windows=[
            dict(t=tnum(w["t"], wref, f"{src}[{i}].t"),
                 forcing=num(w["stress"], unit, wref, f"{src}[{i}].stress (queried by the windows stage)", basis=w["basis"]))
            for i, w in enumerate(ws)])
    out: dict[str, Any] = dict(forcing_at_windows=forcing if wins else {}, vehicles={})
    if env is None or res is None:
        no_env = ("The report was not given an Environment and res.pkl holds positions and flags only, so wind, Hs and current along the tracks "
                  "cannot be queried here; this section shows only the forcing the windows stage recorded at the worst moments.")
        out.update(available=False, how=no_env if env is None else "res.pkl is not available, so there is no track to query the environment along.")
        return out
    b = mission["box"]
    c = b["lon_min"] + ((b["lon_max"] - b["lon_min"]) % 360.0) / 2
    ref = tr.ref("stage1b", output="res.pkl", label="report (environment queried along stage1b track)")
    for vid, r in res["vehicles"].items():
        lon, lat = _median_track(r, c)
        ok = np.isfinite(lon) & np.isfinite(lat)
        n_ok = int(ok.sum())
        i = np.flatnonzero(ok)[np.unique(np.linspace(0, max(n_ok - 1, 0), min(n_ok, 24)).astype(int))]
        t, lo, la = np.asarray(r["t"], float)[i], lon[i], lat[i]
        w, h, cur = env.wind(lo, la, 10.0, t), env.waves(lo, la, t)["Hs"], env.current(lo, la, 0.0, t)

        def speed(a: Any) -> NDArray[np.float64]:
            return np.asarray(np.hypot(*np.moveaxis(np.asarray(a.value, np.float64), -1, 0)), np.float64)

        def q(a: Any, v: np.ndarray, unit: str, what: str) -> dict[str, Any]:
            return vals(v, unit, ref, f"{a.source} ({what} at the stage1b median track)", None if a.uncertainty is None else float(np.mean(a.uncertainty)))
        out["vehicles"][vid] = dict(t=vals(t, "s since 1970-01-01T00:00:00Z", ref, "stage1b/res.pkl vehicles.t"),
                                    wind10=q(w, speed(w), "m/s", "10 m wind speed"), hs=q(h, np.asarray(h.value, float), "m", "Hs"),
                                    current=q(cur, speed(cur), "m/s", "surface current speed"))
    out.update(available=True, how=f"Queried from the Environment passed to report.write ({type(env).__name__}) at up to 24 points of each "
                                   "vehicle's stage1b median track: wind at 10 m, Hs from waves(), current at z = 0.")
    return out


def _stage3(plan: dict[str, Any], wins: dict[str, Any] | None, st3: dict[str, Any] | None, refit: dict[str, Any] | None, tr: Trace,
            pref: dict[str, Any]) -> dict[str, Any]:
    les = plan["les"]
    out: dict[str, Any] = dict(label=les["label"], cpu_fallback=bool(les["cpu_fallback"]), backend=les["backend"], rate_source=les["rate_source"],
                               rate=num(les["rate"], "cell-updates/s", pref, "plan.json les.rate"), vehicles={}, refit={})
    if st3 is None:
        return dict(out, available=False, reason=NOT_PRESENT.format("stage3/windows.json"))
    r3, rr, wref = tr.ref("stage3", output="windows.json"), tr.ref("refit", output="refit.json"), tr.ref("windows", output="windows.json")
    for vid, ws in st3.items():
        rv = (refit or {}).get(vid)
        rows = []
        for i, w in enumerate(ws):
            src = f"stage3/windows.json {vid}[{i}]"
            failed = [c["name"] for c in w.get("checks", []) if not c["ok"]]
            used = bool(rv and rv.get("used") and w.get("ok"))
            if used:
                why = None
            elif not w.get("ok"):
                why = "failed self-checks: " + ", ".join(failed)
            elif rv is not None:
                why = rv.get("reason") or "the refit did not use this vehicle"
            else:
                why = NOT_PRESENT.format("refit/refit.json") if refit is None else "no refit entry for this vehicle"
            at = (wins or {}).get(vid, [])
            rows.append(dict(
                label=f"W{i + 1}", ok=bool(w.get("ok")), used_in_refit=used, not_used_because=why,
                t=tnum(at[i]["t"], wref, "windows/windows.json") if i < len(at) else None,
                checks=[dict(name=c["name"], ok=bool(c["ok"]), value=num(c["value"], "", r3, src + ".checks"), limit=num(c["limit"], "", r3, src + ".checks"),
                             note=c.get("note", "")) for c in w.get("checks", [])],
                coefficients={k: num(w[k], "-", r3, f"{src}.{k}") for k in ("cd", "cd_spread", "cd_hangar", "cl") if w.get(k) is not None}))
        out["vehicles"][vid] = rows
        if rv is not None:
            drag = rv.get("drag", {})
            keys = ("mean", "sigma", "change_vs_hangar")
            out["refit"][vid] = dict(used=bool(rv["used"]), reason=rv.get("reason"), failed_checks=list(rv.get("failed_checks", [])),
                                     drag={k: num(drag[k], "-", rr, f"refit/refit.json {vid}.drag.{k}") for k in keys if k in drag})
    return dict(out, available=True)


def _emulator(emu: dict[str, Any] | None, design: dict[str, Any] | None, tr: Trace) -> dict[str, Any]:
    if emu is None:
        return dict(available=False, reason=NOT_PRESENT.format("emulator/holdout.json"), vehicles={})
    ref = tr.ref("emulator", output="holdout.json")
    out = {}
    for vid, e in emu.items():
        s = f"emulator/holdout.json {vid}"
        if not e.get("trained"):
            out[vid] = dict(trained=False, reason=e.get("reason", "no reason recorded"), **({"rows": num(e["rows"], "rows", ref, s)} if "rows" in e else {}))
            continue

        def unit(k: str) -> str:
            return "h" if k == "t_fail_h" else "fraction"

        d = dict(trained=True, n_train=num(e["n_train"], "members", ref, s), n_test=num(e["n_test"], "members", ref, s),
                 nominal=num(e["nominal"], "fraction", ref, s), rmse={k: num(x, unit(k), ref, s + ".rmse") for k, x in e["rmse"].items()},
                 coverage={k: num(x, "fraction", ref, s + ".coverage") for k, x in e["coverage"].items()}, cls=e.get("cls"), acceptance=None)
        if "acceptance" in e:

            def lim(v: Any, u: str) -> dict[str, Any]:
                return num(v, u, ref, "cafe/pm/whatif.py LIMITS (BRIEF 2.7 acceptance)")

            ac = e["acceptance"]
            d["acceptance"] = dict(rmse_ok=bool(ac["rmse_ok"]), coverage_ok=bool(ac["coverage_ok"]), query_ok=bool(ac["query_ok"]),
                                   query_ms=num(e["query_ms"], "ms", ref, s + ".query_ms"),
                                   noise_floor_rmse=num(e["noise_floor_rmse"], "fraction", ref, s + ".noise_floor_rmse"),
                                   rmse_debiased=num(e["rmse_debiased"], "fraction", ref, s + ".rmse_debiased"),
                                   rows=num(e["rows"], "rows", ref, s + ".rows"),
                                   limits=dict(rmse=lim(0.05, "fraction"), coverage=lim(0.05, "fraction"), query_ms=lim(10.0, "ms")))
        out[vid] = d
    dd = None
    if design is not None:
        dref, s = tr.ref("emulator", output="design.json"), "emulator/design.json"
        dd = dict(share=num(design["share_s"], "s", dref, s), variant=num(design["variant_s"], "s", dref, s), variant_source=design["variant_s_source"],
                  variants=num(len(design["variants"]), "runs", dref, s), spent=num(design["spent_s"], "s", dref, s),
                  flip_spent=num(design["flip_spent_s"], "s", dref, s), rows_added=num(design["rows_added"], "rows", dref, s),
                  table_rows=num(design["table_rows"], "rows", dref, s), table=design["table"], stage1b_free=bool(design["stage1b_free"]))
    return dict(available=True, vehicles=out, design=dd)


def _machine(plan: dict[str, Any], tr: Trace, pref: dict[str, Any]) -> dict[str, Any]:
    live = {st: L for st, L in tr.led.items() if L}
    first = next(iter(live.values()), None)
    costs = {}
    for vid, c in plan["member_cost"].items():
        costs[vid] = dict(s_per_batch_day=num(c["s_per_batch_day"], "s/batch/day", pref, "plan.json member_cost"),
                          s_per_member_day=num(c["s_per_member_day"], "s/member/day", pref, "plan.json member_cost"), source=c["source"],
                          measured=not c["source"].startswith("NOT MEASURED"))
    units = dict(budget_s="s", gpus="GPU", n_min="members", n_max="members", batch="members", sitl_members="members", days="days",
                 refit_iterations="iterations")
    cpus = None if first is None else num(first["machine"]["cpus"], "cores", tr.ref("ingest"), "checkpoints/ingest/ledger.json machine.cpus")
    return dict(describe=budget.describe(plan), notes=list(plan["notes"]), member_costs=costs,
                plan={k: num(plan[k], u, pref, f"plan.json {k}") for k, u in units.items()},
                wall_s={st: num(L["wall_s"], "s", tr.ref(st), f"checkpoints/{st}/ledger.json wall_s") for st, L in live.items()},
                git_sha=sorted({L["git_sha"] for L in live.values()}), versions=(first or {}).get("versions", {}),
                machine=None if first is None else dict(host=first["machine"]["host"], bench_id=first["machine"]["bench_id"], cpus=cpus))


def _assumed(cred: dict[str, Any], cred_ref: dict[str, Any]) -> dict[str, Any]:
    by: dict[str, int] = {}
    for i in cred["assumed_inputs"]:
        by[i["file"]] = by.get(i["file"], 0) + 1
    return dict(page="credibility.html", total=num(len(cred["assumed_inputs"]), "inputs", cred_ref, "credibility.json assumed_inputs"),
                by_file={f: num(n, "inputs", cred_ref, "credibility.json assumed_inputs") for f, n in sorted(by.items())},
                items=[dict(id=i["id"], kind=i["kind"], value=i["value"], unit=i["unit"], why=i["why"], href=f"credibility.html#{i['anchor']}")
                       for i in cred["assumed_inputs"]],
                factors=[dict(name=f["name"], level=f"{f['level']} of 4") for f in cred["factors"]])


def build(run: pathlib.Path, mission: dict[str, Any], plan: dict[str, Any], env: Any = None) -> dict[str, Any]:
    tr = Trace(run)
    cred = json.loads((run / "report" / "credibility.json").read_text())
    s1b = _jl(run / "stage1b" / "summary.json")
    if s1b is None:
        raise FileNotFoundError(f"{run / 'stage1b' / 'summary.json'}: {NOT_PRESENT.format('stage1b/summary.json')}; run the stage1b stage first")
    res, why = _load_res(run, tr)
    files = (("windows", "windows.json"), ("stage3", "windows.json"), ("refit", "refit.json"), ("emulator", "holdout.json"), ("emulator", "flip.json"),
             ("emulator", "design.json"))
    wins, st3, refit, emu, flip, design = (_jl(run / d / f) for d, f in files)
    cfg, pref = tr.ref("ingest", label="mission"), tr.ref("ingest", label="plan")
    cred_ref = tr.file_ref(run / "report" / "credibility.json")
    ing = tr.led["ingest"] or {"inputs": []}
    b = mission["box"]
    rep: dict[str, Any] = dict(
        schema=SCHEMA, run=run.name,
        mission=dict(name=mission["name"], description=str(mission.get("description", "")).strip(), window=dict(mission["window"]),
                     seed=num(mission["seed"], "", cfg, "mission.yaml seed"),
                     box=vals([b["lon_min"], b["lon_max"], b["lat_min"], b["lat_max"]], "deg", cfg, "mission.yaml box (lon_min, lon_max, lat_min, lat_max)"),
                     data_consumed=dict(inputs=[dict(ref=i["ref"], sha256=i.get("sha256"), note=i.get("note", "")) for i in ing["inputs"]],
                                        variables="cafe/schemas/wrfout.json and cafe/schemas/umwmout.json (read per hour over the mission window)")),
        verdict_source="stage1b (stage 1 rerun with the stage-3 refit multipliers; a copy of stage 1 when nothing was refit)",
        vehicles=_vehicles(s1b, _jl(run / "stage1" / "summary.json"), mission, cred, tr, cred_ref, flip), links=_links(s1b, tr),
        map=_map(mission, res, why, wins, tr, cfg), reach=_reach(mission, env, tr), environment=_env(mission, env, res, wins, s1b, tr),
        stage3=_stage3(plan, wins, st3, refit, tr, pref), emulator=_emulator(emu, design, tr), machine=_machine(plan, tr, pref),
        assumed_inputs=_assumed(cred, cred_ref))
    rep["receipts"] = sorted(tr.rows.values(), key=lambda r: r["id"])
    rep["traceability_problems"] = check_traceability(rep)
    return rep


# ------------------------------------------------------------------------------------------------------ HTML (from the JSON only)

def _txt(n: dict[str, Any]) -> str:
    if n.get("utc"):
        return str(n["utc"])
    unit = f" {n['unit']}" if n["unit"] not in ("", "-", "fraction") else ""
    if "values" in n:
        return f"{len(n['values'])} values{unit}"
    v = n["value"]
    return ("n/a" if v is None else f"{v:.4g}" if isinstance(v, float) else str(v)) + unit


def _rid(receipt: str) -> str:
    return "r-" + re.sub(r"[^A-Za-z0-9]+", "-", receipt)


def _n(n: dict[str, Any] | None) -> str:
    """A number as text plus links to its ledger (L) and to its row of the receipts table (R)."""
    if n is None:
        return "n/a"
    tip = f"{n['stage']}: {n['source']}" + ("" if n["uncertainty"] is None else f"; uncertainty {json.dumps(n['uncertainty'])}")
    return (f'<span class=n>{html.escape(_txt(n))}<a class=lk href="../{html.escape(n["ledger"])}" title="{html.escape(tip)}">L</a>'
            f'<a class=lk href="#{_rid(n["receipt"])}" title="{html.escape(n["receipt"])}">R</a></span>')


def _badge(v: str) -> str:
    return f'<span class="badge {v.lower().replace("-", "")}">{html.escape(v)}</span>'


def _stat_html(d: dict[str, Any]) -> str:
    u = d["p_fail"]["uncertainty"]
    h = (f"<p>P(fail) = {_n(d['p_fail'])}, {u['conf']:.0%} {html.escape(u['kind'])} {u['lo']:.3g} to {u['hi']:.3g}; "
         f"{_n(d['k_fail'])} failed of {_n(d['n'])} (certifying P(fail) &lt; 5 % needs {_n(d['n_certify'])}).</p>")
    if d["certify_statement"]:
        h += f"<p class=warn>{html.escape(d['certify_statement'])}</p>"
    return h + (f"<p class=muted>{html.escape(d['note'])}</p>" if d["note"] else "")


def _sens_html(s: dict[str, Any]) -> str:
    if s["param"] is None:
        return "none (all-pass, all-fail, or fewer than 16 members)"
    return f"<code>{html.escape(s['param'])}</code> (S1 {_n(s['s1'])})"


def _top3_html(top: list[Any]) -> str:
    if not top:
        return "<p class=muted>Top sensitivities: none (all-pass, all-fail, or fewer than 16 members).</p>"
    items = "; ".join(f"<code>{html.escape(t['param'])}</code> {_n(t['s1'])}" for t in top)
    return f"<p>Top sensitivities (Sobol first-order, share of the variance of failure): {items}.</p>"


def _tried_html(t: dict[str, Any]) -> str:
    e = html.escape
    how = ("n/a" if t["method"] == "not evaluated" else t["method"]) + (f", n = {_n(t['n'])}" if t["n"] else "") \
        + (f", distance {_n(t['distance'])} of {_n(t['threshold'])}" if t["distance"] else "")
    return (f"<tr><td>{e(t['change'])}<td>{_n(t['cost'])}<td>{e(how)}<td>{_n(t['p_fail'])}<td>{e(str(t['verdict'] or ''))}<td>{e(t['reason'])}</tr>")


def _fix_html(f: dict[str, Any]) -> str:
    """The "what would fix it" line (BRIEF 2.5) and the candidates behind it."""
    e = html.escape
    if not f["available"]:
        return f"<p class=warn>What would fix it: not available. {e(f['reason'])}</p>"
    if not f["needed"]:
        return "<p class=muted>What would fix it: nothing needed, the verdict is GO.</p>"
    b = f["best"]
    if b:
        u = b["p_fail"]["uncertainty"]
        how = (f"EMULATED, training-set distance {_n(b['distance'])} of {_n(b['threshold'])}" if b["method"] == "EMULATED" else f"Stage 1, n = {_n(b['n'])}")
        line = (f"<b>{e(b['change'])}</b>: P(fail) {_n(f['p_fail_before'])} becomes {_n(b['p_fail'])} ({u['lo']:.3g} to {u['hi']:.3g}, {e(u['kind'])}), "
                f"{_badge(f['verdict_before'])} to {_badge(b['verdict'])} ({how}).")
    else:
        line = (f"no single change among the {len(f['tried'])} candidates reaches {e(f['target'])} (P(fail) now {_n(f['p_fail_before'])}); "
                + ("the emulator answered those in its range." if f["emulator_trained"] else "no emulator is trained yet, so only a few were run in Stage 1."))
    rows = "".join(_tried_html(t) for t in f["tried"])
    return (f"<p>What would fix it ({e(f['target'])}): {line}</p><details><summary>All {len(f['tried'])} candidates</summary><div class=scroll><table>"
            f"<tr><th>Change<th>Cost (notches)<th>Answered by<th>P(fail)<th>Verdict<th>Note</tr>{rows}</table></div></details>")


def _vehicle_html(vid: str, v: dict[str, Any]) -> str:
    e = html.escape
    modes = ", ".join(f"{e(k)}: {_n(n)}" for k, n in v["modes"].items()) or "none"
    ch = ""
    if v["changed_by_refit"]:
        ch = f"<p class=warn>The verdict changed from {_badge(v['verdict_stage1'])} to {_badge(v['verdict'])} after the stage-3 refit.</p>"
    return (f"<div class=card><h3>{e(vid)} {_badge(v['verdict'])} <span class=muted>{e(v['cls'])}, {e(str(v['platform']))}</span></h3>"
            f"{_stat_html(v)}{ch}<p>Dominant failure mode: <b>{e(str(v['dominant_mode']))}</b> (all modes: {modes}).<br>"
            f"First failure: {_n(v['first_fail'])}; median failure: {_n(v['median_fail'])}.<br>Most sensitive to: {_sens_html(v['sensitivity'])}.</p>"
            f"{_top3_html(v['top3'])}{_fix_html(v['fix'])}<p class=muted>Depends on {_n(v['assumed_platform_inputs'])} assumed platform inputs, listed in the "
            f"<a href='{e(v['assumed_anchor'])}'>credibility report</a>.</p></div>")


def _link_html(lid: str, k: dict[str, Any]) -> str:
    e = html.escape
    return (f"<div class=card><h3>{e(lid)} {_badge(k['verdict'])}</h3>{_stat_html(k)}<p>Method: {e(k['method'])}.<br>"
            f"Fraction of required moments met: median {_n(k['frac_median'])}, 10th percentile {_n(k['frac_p10'])}; "
            f"median margin {_n(k['margin_db_median'])}.<br>Most sensitive to: {_sens_html(k['sensitivity'])}.</p>{_top3_html(k['top3'])}</div>")


def _svg(m: dict[str, Any], reach: dict[str, Any]) -> str:
    if not m["available"]:
        return f"<p class=warn>Map not drawn: {html.escape(m['reason'])}</p>"
    e = html.escape
    box = m["box"]["values"]
    c = box[0] + ((box[1] - box[0]) % 360.0) / 2

    def rel(x: float) -> float:
        return float((x - c + 180.0) % 360.0 - 180.0)

    pts = [[box[0], box[2]], [box[1], box[3]]] + ([m["ship"]["values"]] if m["ship"] else [])
    for v in m["vehicles"].values():
        pts += v["median"]["values"] + [p for mem in v["members"] for p in mem["track"]["values"]] + ([v["deploy"]["values"]] if v["deploy"] else [])
    for ws in m["windows"].values():
        pts += [w["position"]["values"] for w in ws]
    rch = {vid: r for vid, r in reach["vehicles"].items() if r["available"]}
    for r in rch.values():
        pts += r["polygon"]["values"]
    xs, ys = [rel(p[0]) for p in pts], [p[1] for p in pts]
    x0, y0, y1 = min(xs), min(ys), max(ys)
    k = math.cos(math.radians((y0 + y1) / 2))
    s = min(720.0 / max((max(xs) - x0) * k, 1e-6), 520.0 / max(y1 - y0, 1e-6))

    def P(lon: float, lat: float) -> tuple[float, float]:
        return (30 + (rel(lon) - x0) * k * s, 30 + (y1 - lat) * s)

    def line(tr_: Any) -> str:
        return " ".join("%.1f,%.1f" % P(*p) for p in tr_)

    ax, ay = P(box[0], box[3])
    bx, by = P(box[1], box[2])
    g = [f'<rect class=box x="{ax:.1f}" y="{ay:.1f}" width="{bx - ax:.1f}" height="{by - ay:.1f}"><title>mission box</title></rect>']
    for i, (vid, v) in enumerate(m["vehicles"].items()):
        cl = f"s{i % 6}"
        if vid in rch:
            g.append(f'<polygon class="{cl}" style="fill-opacity:.1;stroke-width:1;stroke-dasharray:6 3" points="{line(rch[vid]["polygon"]["values"])}">'
                     f'<title>{e(vid)} reach within {reach["horizon"]["value"]:g} h of the deploy</title></polygon>')
        for mem in v["members"]:
            kind = " memfail" if mem["failed"] else ""
            g.append(f'<polyline class="mem {cl}{kind}" points="{line(mem["track"]["values"])}"><title>{e(vid)} {e(mem["label"])}</title></polyline>')
        g.append(f'<polyline class="trk {cl}" points="{line(v["median"]["values"])}"><title>{e(vid)} median track</title></polyline>')
        if v["deploy"]:
            x, y = P(*v["deploy"]["values"])
            g.append(f'<circle class={cl} cx="{x:.1f}" cy="{y:.1f}" r="4"><title>{e(vid)} deploy</title></circle>'
                     f'<text x="{x + 6:.1f}" y="{y - 6:.1f}">{e(vid)}</text>')
    for vid, ws in m["windows"].items():
        for w in ws:
            x, y = P(*w["position"]["values"])
            g.append(f'<circle class="win trk" cx="{x:.1f}" cy="{y:.1f}" r="8"><title>{e(vid)} stage-3 window {w["label"]}</title></circle>'
                     f'<text x="{x + 10:.1f}" y="{y + 4:.1f}">{w["label"]}</text>')
    if m["ship"]:
        x, y = P(*m["ship"]["values"])
        g.append(f'<rect class=ship x="{x - 5:.1f}" y="{y - 5:.1f}" width="10" height="10" transform="rotate(45 {x:.1f} {y:.1f})">'
                 f'<title>ship</title></rect><text x="{x + 8:.1f}" y="{y + 14:.1f}">ship</text>')
    return (f'<svg viewBox="0 0 780 {(y1 - y0) * s + 60:.0f}" role=img aria-label="Mission map: ship, deploy points, tracks and stage-3 windows">'
            f'{"".join(g)}</svg><p class=muted>Thick line: median track over members. Thin lines: a few members (dashed: failed). '
            "Square: ship. Dot: deploy point. Ring: stage-3 window. Shaded dashed outline: reach map (where the vehicle can get to within "
            "the horizon, in the currents at the deploy time).</p>")


def _reach_html(r: dict[str, Any]) -> str:
    e = html.escape
    if not r["available"]:
        return f"<p class=warn>Reach map not drawn: {e(r['reason'])}</p>"
    h = f"<p>Reach map: fastest routes within {_n(r['horizon'])} of the deploy, through the environment's currents at the deploy time.</p><ul>"
    for vid, d in r["vehicles"].items():
        h += (f"<li>{e(vid)}: " + (f"farthest reachable cell {_n(d['max_range_km'])} from {_n(d['deploy'])} at {_n(d['speed'])} through the water "
                                    f"(assumed, config/assumptions.yaml), largest current on the grid {_n(d['flow_max'])}, outline {_n(d['polygon'])}"
                                    if d["available"] else f"not drawn. {e(d['reason'])}"))
    return h + "</ul>"


def _map_html(m: dict[str, Any], reach: dict[str, Any]) -> str:
    if not m["available"]:
        return _svg(m, reach)
    e = html.escape
    tracks = "".join(f"<li>{e(v)}: median track {_n(d['median'])}" + "".join(f"; {e(x['label'])} {_n(x['track'])}" for x in d["members"])
                     for v, d in m["vehicles"].items())
    wins = "".join(f"<li>{e(v)} {w['label']}: {_n(w['t'])} at {_n(w['position'])}" for v, ws in m["windows"].items() for w in ws)
    return f"{_svg(m, reach)}<ul>{tracks}</ul><p>Mission box {_n(m['box'])}; ship {_n(m['ship'])}.</p><ul>{wins}</ul>{_reach_html(reach)}"


def _env_html(env: dict[str, Any]) -> str:
    e = html.escape
    h = f"<p>{e(env['how'])}</p>" if "how" in env else ""
    for vid, d in env["vehicles"].items():
        h += f"<p><b>{e(vid)}</b>: 10 m wind {_n(d['wind10'])}; Hs {_n(d['hs'])}; surface current {_n(d['current'])}; at times {_n(d['t'])}.</p>"
    for vid, d in env["forcing_at_windows"].items():
        rows = "; ".join(f"{_n(w['t'])}: {_n(w['forcing'])} ({e(w['forcing']['basis'])})" for w in d["windows"])
        h += f"<p><b>{e(vid)}</b>, {e(d['quantity'])} at the worst windows: {rows}.</p>"
    return h


def _window_html(w: dict[str, Any]) -> str:
    e = html.escape
    ck = "".join(f"<tr><td>{e(c['name'])}<td>{'pass' if c['ok'] else '<b>FAIL</b>'}<td>{_n(c['value'])}<td>{_n(c['limit'])}<td>{e(c['note'])}</tr>"
                 for c in w["checks"])
    co = ", ".join(f"{e(k)} {_n(x)}" for k, x in w["coefficients"].items())
    use = "used in the refit" if w["used_in_refit"] else f"not used in the refit: {e(str(w['not_used_because']))}"
    return (f"<div class=card><b>{w['label']}</b> {'passed' if w['ok'] else 'failed'} its self-checks; {use}"
            + (f". At {_n(w['t'])}" if w["t"] else "") + (f". Coefficients: {co}" if co else "")
            + f"<div class=scroll><table><tr><th>Check<th>Result<th>Value<th>Limit<th>Note</tr>{ck}</table></div></div>")


def _stage3_html(s: dict[str, Any]) -> str:
    e = html.escape
    h = f"<div class=warn><p class=big>{e(s['label'])}</p></div>" if s["cpu_fallback"] else f"<p class=big>{e(s['label'])}</p>"
    h += f"<p>Backend {e(s['backend'])} at {_n(s['rate'])} ({e(s['rate_source'])}).</p>"
    if not s["available"]:
        return h + f"<p class=warn>{e(s['reason'])}</p>"
    for vid, rows in s["vehicles"].items():
        rf = s["refit"].get(vid)
        h += f"<h3>{e(vid)}</h3>"
        if rf:
            d = rf["drag"]
            h += f"<p>Refit: {'used' if rf['used'] else 'not used'}" + (f" ({e(rf['reason'])})" if rf["reason"] else "")
            h += (f"; drag multiplier mean {_n(d['mean'])}, sigma {_n(d['sigma'])}" if "mean" in d and "sigma" in d else "") + ".</p>"
        h += "".join(_window_html(w) for w in rows)
    return h


def _emulator_html(m: dict[str, Any]) -> str:
    e = html.escape
    if not m["available"]:
        return f"<p class=warn>{e(m['reason'])}</p>"
    h = ""
    for vid, v in m["vehicles"].items():
        if not v["trained"]:
            h += f"<p><b>{e(vid)}</b>: not trained. {e(v['reason'])}" + (f" ({_n(v['rows'])} of this class.)" if "rows" in v else "") + "</p>"
            continue
        sc = "; ".join(f"{e(k)} RMSE {_n(x)}, coverage {_n(v['coverage'][k])} (nominal {_n(v['nominal'])})" for k, x in v["rmse"].items())
        kind = f" ({e(v['cls'])} emulator)" if v["cls"] else ""
        h += f"<p><b>{e(vid)}</b>{kind}: trained on {_n(v['n_train'])}, scored on {_n(v['n_test'])} held-out; {sc}.</p>"
        a = v["acceptance"]
        if a:

            def ok(b: Any) -> str:
                return "met" if b else "<b>MISSED</b>"

            h += (f"<p class=muted>BRIEF 2.7 acceptance: P(fail) RMSE against the true P(fail) {_n(a['rmse_debiased'])} &le; "
                  f"{_n(a['limits']['rmse'])} {ok(a['rmse_ok'])} (the held-out RMSE against the member-count targets, less their own "
                  f"Monte-Carlo noise {_n(a['noise_floor_rmse'])} in quadrature); coverage within {_n(a['limits']['coverage'])} of nominal "
                  f"{ok(a['coverage_ok'])}; query {_n(a['query_ms'])} "
                  f"&le; {_n(a['limits']['query_ms'])} {ok(a['query_ok'])}; {_n(a['rows'])} rows of this class.</p>")
    d = m["design"]
    if d:
        h += (f"<p>Training table {e(d['table'])}: {_n(d['table_rows'])} rows, {_n(d['rows_added'])} added by this run. "
              f"{_n(d['variants'])} variant run(s) of the mission "
              f"({_n(d['variant'])} each, from {e(d['variant_source'])}) used {_n(d['spent'])} of the emulator share {_n(d['share'])}"
              f"{' (including stage 1b, which was a copy)' if d['stage1b_free'] else ''}; the flip search ran {_n(d['flip_spent'])} of Stage 1.</p>")
    return h


def _machine_html(m: dict[str, Any]) -> str:
    e = html.escape
    cost = "".join(f"<tr><td>{e(v)}<td>{_n(c['s_per_batch_day'])} + {_n(c['s_per_member_day'])}"
                   f"<td>{'measured' if c['measured'] else '<b>NOT MEASURED</b>'}: {e(c['source'])}</tr>" for v, c in m["member_costs"].items())
    wall = "".join(f"<tr><td>{e(s)}<td>{_n(n)}</tr>" for s, n in m["wall_s"].items())
    ver = ", ".join(f"{e(k)} {e(str(v))}" for k, v in m["versions"].items())
    mc = m["machine"]
    where = f"{e(str(mc['host']))}, {_n(mc['cpus'])}, bench id {e(str(mc['bench_id']))}" if mc else "unknown"
    plan = "; ".join(f"{e(k)} {_n(n)}" for k, n in m["plan"].items())
    return (f"<pre>{e(m['describe'])}</pre><div class=scroll><table><tr><th>Vehicle<th>Cost per mission day (s per batch + s per member)"
            f"<th>Source</tr>{cost}</table></div>"
            f"<div class=scroll><table><tr><th>Stage<th>Wall time</tr>{wall}</table></div><p>Plan: {plan}.</p>"
            f"<p>Code: git {e(', '.join(m['git_sha']))}. Machine: {where}.</p><p class=muted>{ver}</p>")


def _assumed_html(a: dict[str, Any]) -> str:
    e = html.escape
    rows = "".join(f"<tr><td>{e(f)}<td>{_n(n)}</tr>" for f, n in a["by_file"].items())
    fac = "".join(f"<tr><td>{e(f['name'])}<td>{e(f['level'])}</tr>" for f in a["factors"])
    lst = "".join(f"<li><a href='{e(i['href'])}'><code>{e(i['id'])}</code></a> ({e(i['kind'])}) {e(i['value'])} {e(i['unit'])}" for i in a["items"])
    return (f"<p>{_n(a['total'])} inputs are assumed or are priors, not measurements, and verdicts depend on them. Full detail: "
            f"<a href='credibility.html'>credibility report</a> (levels, V&amp;V 20 table, limitations).</p>"
            f"<div class=scroll><table><tr><th>File<th>Inputs</tr>{rows}</table></div>"
            f"<div class=scroll><table><tr><th>NASA-STD-7009B factor<th>Level</tr>{fac}</table></div>"
            f"<details><summary>All assumed inputs</summary><ul>{lst}</ul></details>")


def _receipts_html(rows: list[Any]) -> str:
    e = html.escape
    body = "".join(f"<tr id='{_rid(r['id'])}'><td><code>{e(r['id'])}</code><td>{e(r['kind'])}"
                   f"<td>{'ok' if r['ok'] else '<b>MISSING OR FAILED</b>'}<td>{e(r['got'])}<td>{e(r['limit'])}"
                   f"<td><code>{e(r['sha256'][:16])}</code><td><a href='../{e(r['ledger'])}'>ledger</a></tr>" for r in rows)
    return f"<div class=scroll><table><tr><th>Receipt<th>Kind<th>Status<th>Value<th>Limit<th>sha-256<th>Ledger</tr>{body}</table></div>"


def render(rep: dict[str, Any]) -> str:
    e = html.escape
    m = rep["mission"]
    rows = "".join(f"<tr><td><a href='#v-{e(i)}'>{e(i)}</a><td>{_badge(d['verdict'])}<td>{_n(d['p_fail'])}<td>{_n(d['n'])}</tr>"
                   for i, d in {**rep["vehicles"], **rep["links"]}.items())
    bad = rep["traceability_problems"]
    tr = (f"<p class=warn>Traceability problems: {e('; '.join(bad))}</p>" if bad
          else "<p class=muted>Traceability check: every number links to a passing ledger receipt.</p>")
    inputs = e("; ".join(i["ref"] for i in m["data_consumed"]["inputs"]) or "none recorded")
    body = (f"<h1>{e(m['name'])}: pre-mission report</h1><p>{e(m['description'])}</p>"
            f"<p class=muted>Window {e(m['window']['start'])} to {e(m['window']['end'])}; seed {_n(m['seed'])}; verdicts from {e(rep['verdict_source'])}. "
            "In the text, <b>L</b> opens the ledger of the stage that produced a number and <b>R</b> its row in the receipts table. "
            f"Inputs read: {inputs} ({e(m['data_consumed']['variables'])}).</p>{tr}"
            "<p><a href='credibility.html'>Credibility report</a> | <a href='report.json'>report.json</a></p>"
            f"<h2>Verdicts</h2><div class=scroll><table><tr><th>Vehicle or link<th>Verdict<th>P(fail)<th>Members</tr>{rows}</table></div>"
            + "".join(f"<div id='v-{e(i)}'>{_vehicle_html(i, d)}</div>" for i, d in rep["vehicles"].items())
            + "".join(f"<div id='v-{e(i)}'>{_link_html(i, d)}</div>" for i, d in rep["links"].items())
            + f"<h2>Map</h2>{_map_html(rep['map'], rep['reach'])}<h2>Environment along the tracks</h2>{_env_html(rep['environment'])}"
            f"<h2>Stage 3 and refit</h2>{_stage3_html(rep['stage3'])}<h2>Emulator</h2>{_emulator_html(rep['emulator'])}"
            f"<h2>Machine and budget</h2>{_machine_html(rep['machine'])}<h2>Assumed inputs</h2>{_assumed_html(rep['assumed_inputs'])}"
            f"<h2 id=receipts>Receipts</h2>{_receipts_html(rep['receipts'])}")
    return credibility.page(f"{m['name']} report", body)


def check_rendered(rep: dict[str, Any], html_text: str) -> list[str]:
    """Every number node's text is in the page (the HTML is rendered from the JSON; this catches a section that drops a number)."""
    return [f"{p}: {_txt(o)!r} is not in the HTML" for k, p, o in _walk(rep) if k == "node" and html.escape(_txt(o)) not in html_text]


def write(run_dir: str | pathlib.Path, mission: dict[str, Any], plan: dict[str, Any], env: Any = None) -> list[pathlib.Path]:
    """Write credibility.{html,json}, then report.json and index.html. Returns every path written, for the report ledger."""
    run = pathlib.Path(run_dir)
    cred = credibility.write(run)
    rep = build(run, mission, plan, env)
    j, h = run / "report" / "report.json", run / "report" / "index.html"
    j.write_text(json.dumps(rep, indent=1, allow_nan=False))
    h.write_text(render(rep))
    return [h, j, *cred]
