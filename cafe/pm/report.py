"""The report stage (BRIEF 2.9, 5.5): run directory -> run_dir/report/{index.html, report.json, credibility.html, credibility.json}.

    write(run_dir, mission, plan, env=None) -> [Path, ...]      what the pipeline records as the report ledger's outputs
    check_traceability(report) -> [str]                          empty when every number traces to a ledger and a receipt
    check_rendered(report, html_text) -> [str]                   empty when every number in the JSON shows up in the HTML

report.json is the source of truth; index.html is rendered from it and nothing else. Every number in it is a node
{value | values, unit, stage, source, uncertainty, receipt, ledger}: `stage` produced it, `source` is the file and field it was
read from, `uncertainty` is its 1-sigma or interval (None when exact), `receipt` is the id of a row of the report's `receipts`
table (a ledger check by name, else the sha-256 of the stage output the number was read from, else the stage's config hash) and
`ledger` is the run-relative path of that stage's ledger.json (for a model-receipt group: runs/receipts.json). A number outside a node, a
receipt that is missing, or a ledger check that failed, is what check_traceability reports. A link is provenance, not a pass: an `output`
receipt carries the output's own quality bit (windows.json of stage 3 is ok only if some window passed its self-checks) and each verdict
cites the model-receipt group of its vehicle class or link (`physics:<group>`: pass and fail counts from runs/receipts.json, "not run" when
that table is not there, "stale: made by other code" when runs/receipts.meta.json does not hold the code digest of the run's own
ledgers). A receipt with ok False is shown, never hidden, and does not by itself make the traceability check fail. Verdicts
are those of the final ensemble, stage1b (a copy of stage 1 when nothing was refit). res.pkl is unpickled only after its sha-256 matches the
ledger's record of it.

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
from .config import json_object
from .audit import STAGES
from .stage1 import _classes, path_speed as _member_speeds
from .env.remote import sha256
from .stats import intervals, sequential

SCHEMA = "cafe.pm.report/1"
RECEIPTS_NAME = "runs/receipts.json"                                          # the model receipts (python -m cafe.pm receipts), relative to the repo
RECEIPTS = credibility.ROOT / RECEIPTS_NAME
META_NAME = "receipts.meta.json"                                              # beside the table: {code_digest, git_sha, made_at} of the code that made it
STALE = "stale: made by other code"
USV_RATIO_NOTE = ("The mission ratio is lowered by the westward current (in the demo mission it turns a beam reach into a close-hauled course, and the speed "
                  "through the water falls); the calibration may already include part of the current effect, a possible double penalty that is not "
                  "established.")
UAS_ATTITUDE_NOTE = ("Attitude exceedance cannot fire in this controller model (the tilt clamp, 35 deg, is below the 42 deg exceedance), so the UAS verdict "
                     "rests on the battery and on finishing the profile inside the time limit.")
UAS_ATTITUDE_NOTE_NO_PROFILE = ("Attitude exceedance cannot fire in this controller model (the tilt clamp, 35 deg, is below the 42 deg exceedance), so the UAS "
                                "verdict rests on battery alone below about 12 m/s of wind.")      # a summary from before the profile was counted
MODE_TEXT = dict(profile_incomplete="a flown sortie returned (time limit or battery reserve) before its last pattern waypoint, so it did not deliver "
                                    "the full profile",
                 no_current_data="there was no finite wind, current or wave state at the vehicle's position (a land block, a masked cell or a hole in the sea "
                                 "mask), or no finite insolation there, so its motion or its battery could not be computed",
                 capsize_proxy="the roll peak passed the limit, or the wind relative to the water was above the polar's top (30 m/s: outside the model, "
                               "counted as a failure, not a pass)")
SENS_SCOPE = ("These indices rank only the sampled columns (the member-wide biases and scales of the forcing and of the vehicle). The larger errors are "
              "per-member random streams that are not columns and are not ranked: the hourly wind error{wind}, half of the current error (the 100 km random "
              "field), the ocean SDE, the UAS turbulence and gusts, and the Iridium draws.")
CHIODI_RATIO = 0.96 / 5.4                                                     # platforms/saildrone_explorer.yaml chiodi_mean_sog_ms / chiodi_mean_wind_ms
PHYSICS = dict(glider="pm.physics.glider", usv="pm.physics.usv", uas="pm.physics.uas", link="pm.physics.comms")     # vehicle class or link -> group
SENSITIVITY = "sensitivity_cases.json"             # stage1b/: {vid: [{case, k_fail, n, verdict, note}]}, written by whoever runs a case
FORCING = {"glider": ("surface current speed", "m/s"), "usv": ("significant wave height", "m"), "uas": ("10 m wind speed", "m/s")}
NOT_PRESENT = "{} is not in the run directory"


def _jl(p: pathlib.Path) -> Any:
    return json_object(p) if p.is_file() else None


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
        self.table = self._table()
        self.stale = self._stale()

    def _table(self) -> tuple[list[dict[str, Any]], str] | str:
        """The model-receipts table (rows, sha-256), or the reason there is none."""
        if not RECEIPTS.is_file():
            return f"{RECEIPTS_NAME} is not there: run `python -m cafe.pm receipts` and rerun the report"
        try:
            return json.loads(RECEIPTS.read_text()), sha256(RECEIPTS)
        except ValueError as e:
            return f"{RECEIPTS_NAME} is not valid JSON ({e})"

    def _stale(self) -> str | None:
        """Why the receipts table is not for this run's code, or None: the table's meta file (receipts.run writes it) must hold the code digest the run's
        own ledgers hold. A missing meta file or digest is as stale as a different one: nothing says the table was made by this code."""
        meta = RECEIPTS.with_name(META_NAME)
        try:
            md = json.loads(meta.read_text())
            made, part = md.get("code_digest"), md.get("only")
        except (OSError, ValueError, AttributeError):
            return f"{RECEIPTS_NAME} has no readable {META_NAME} beside it, so nothing says which code made it: rerun `python -m cafe.pm receipts`"
        if part:                                                                   # a table made with `--only` (older meta files have no key or null)
            return (f"{RECEIPTS_NAME} was made with --only {','.join(part)}: it holds a part of the receipts; rerun `python -m cafe.pm receipts` "
                    "(the receipts below are not counted as a pass)")
        mine = next((L["code_digest"] for L in self.led.values() if L and L.get("code_digest")), None)
        if mine is None or made != mine:
            return (f"{RECEIPTS_NAME} was made by code {str(made)[:12]}, this run by {str(mine)[:12]}: rerun `python -m cafe.pm receipts` "
                    "(the receipts below describe other code and are not counted as a pass)")
        return None

    def _row(self, stage: str, rid: str, kind: str, name: str, ok: bool, got: str = "", limit: str = "", sha: str = "", ledger: str | None = None,
             state: str | None = None) -> None:
        """`ok` is the boolean the traceability count uses; `state` says why a row is not ok: fail (a check failed), stale (made by other code), not_run."""
        self.rows.setdefault(rid, dict(id=rid, stage=stage, ledger=ledger or f"checkpoints/{stage}/ledger.json", kind=kind, name=name, ok=ok,
                                       state=state or ("pass" if ok else "fail"), got=got, limit=limit, sha256=sha))

    def quality(self, stage: str, output: str) -> tuple[bool, str, str]:
        """The output's own quality bit and state: stage 3's windows.json is ok only if some window passed its self-checks (the other outputs have none).
        When none passed it is `fail` only if a window ran (has checks, or was cut) and failed; if every window was skipped with a reason (the planner's
        "not run: ..." rows, a becalmed USV, a killed window) it is `not_run`, which is not a failure."""
        if (stage, output) != ("stage3", "windows.json"):
            return True, "", "pass"
        ws = [w for v in (_jl(self.run / "stage3" / "windows.json") or {}).values() for w in v]
        n = sum(bool(w.get("ok")) for w in ws)
        ran = sum(bool(w.get("checks")) or bool(w.get("cut")) for w in ws)
        if n:
            return True, f"{n} of {len(ws)} windows passed their self-checks", "pass"
        if not ran:
            return False, f"0 of {len(ws)} windows ran: each was skipped with a stated reason", "not_run"
        return False, f"0 of {len(ws)} windows passed their self-checks ({ran} ran and failed)", "fail"

    def physics(self, key: str) -> dict[str, Any]:
        """The model receipts of a vehicle class or `link`: the pass and fail counts of its group in runs/receipts.json, as nodes behind the row
        `physics:<group>` (ok only when none failed), or status "not run" with the reason. Context rows are not counted."""
        group = PHYSICS[key]
        if isinstance(self.table, str):
            return dict(group=group, status="not run", reason=self.table, failures=[])
        rows = [r for r in self.table[0] if (r["module"] == group or r["module"].startswith(group + ".")) and r.get("kind") in ("pass", "fail")]
        if not rows:
            return dict(group=group, status="not run", reason=f"no receipt of group {group} in {RECEIPTS_NAME}", failures=[])
        bad = [r["name"] for r in rows if not r["ok"]]
        rid, name = f"physics:{group}", RECEIPTS_NAME
        if self.stale:
            self._row("model receipts", rid, "physics", group, False, STALE, sha=self.table[1], ledger=name, state="stale")
            return dict(group=group, status=STALE, reason=self.stale, failures=[])
        self._row("model receipts", rid, "physics", group, not bad, f"{len(rows) - len(bad)} pass, {len(bad)} fail", sha=self.table[1], ledger=name)
        ref = dict(stage="model receipts", ledger=name, receipt=rid)
        return dict(group=group, status="FAILED" if bad else "ok", reason=None, failures=bad,
                    passed=num(len(rows) - len(bad), "receipts", ref, f"{name} group {group}"), failed=num(len(bad), "receipts", ref, f"{name} group {group}"))

    def ref(self, stage: str, check: str | None = None, output: str | None = None, label: str | None = None) -> dict[str, Any]:
        """The receipt for a number from `stage`: the first ledger check named `check*`, else the hash of its `output` file,
        else the config hash of the stage's ledger; a missing ledger gives a receipt that check_traceability flags."""
        L = self.led.get(stage)
        if not L:
            rid = f"{stage}:missing-ledger"
            self._row(stage, rid, "missing", "no ledger", False, state="not_run")
        else:
            c = next((c for c in L["checks"] if check and c["name"].startswith(check)), None)
            o = next((o for o in L["outputs"] if output and o["path"].endswith("/" + (output or ""))), None)
            if c:
                rid = f"{stage}:check:{c['name']}"
                self._row(stage, rid, "check", c["name"], c["ok"], repr(c["value"]), repr(c["limit"]))
            elif o:
                rid = f"{stage}:output:{output}"
                ok, got, state = self.quality(stage, output or "")
                self._row(stage, rid, "output", output or "", ok, got, sha=o["sha256"], state=state)
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
    """Every number is a node with stage, source, uncertainty, unit, receipt and ledger, and its receipt is a row of the receipts table whose ledger
    it names. A missing ledger or a failed ledger check is a problem; an output or model-receipt row with ok False is a result, shown as FAILED."""
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
        elif not r["ok"] and r["kind"] in ("missing", "check"):
            bad.append(f"{path}: receipt {r['id']!r} is missing or its check failed")
    return bad


# ------------------------------------------------------------------------------------------------------ builders

def _g(x: float) -> str:
    """A number as the report prints it (the same `.4g` as a node's text)."""
    return f"{x:.4g}"


def _undecided(lo: float, hi: float) -> str:
    """One sentence for a verdict whose interval on P(fail) is not wholly inside GO or NO-GO: the level that interval is at (the stopper's,
    which differs from the verdict's own), which thresholds it spans, and that more members decide it. lo and hi are the `stop_interval` nodes."""
    cut = {"GO": intervals.P_FAIL_GO, "NO-GO": intervals.P_FAIL_NOGO}
    span = [f"{name} threshold of {_g(c)}" for name, c in cut.items() if lo <= c < hi]          # never empty: an interval that spans nothing is decided
    head = (f"At the {sequential.STOP_CONF:.0%} level the stopper uses to decide whether more members are needed, "
            f"the interval on P(fail), {_g(lo)} to {_g(hi)}, ")
    return head + f"spans the {' and the '.join(span)}, so more members (a larger --budget) would decide it."


def _stat(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any]:
    """The verdict block shared by a vehicle and a link. `region` is "GO", "MARGINAL" or "NO-GO" when the whole P(fail) interval of the stopper's confidence
    (`sequential.STOP_CONF`) lies inside that verdict's range, else None and the verdict is not `decided`. `p_fail` carries the verdict's own interval
    (its `conf`); `stop_interval` is the stopper's, and `thresholds` the verdict cut-offs, each a traced node the sentences only restate."""
    v = e["verdict"]
    unc = dict(kind=f"{v['method']} interval", conf=v["conf"], lo=v["fail_lo"], hi=v["fail_hi"])
    d: dict[str, Any] = dict(verdict=v["verdict"], p_fail=num(v["p_fail"], "fraction", ref, src, unc), n=num(e["n"], "members", ref, src),
                             k_fail=num(e["k_fail"], "members", ref, src), n_certify=num(v["n_certify"], "members", ref, src), note=v["note"],
                             certify_statement=None)
    lo, hi, method = intervals.interval(e["k_fail"], e["n"], sequential.STOP_CONF)
    sunc = dict(kind=f"{method} interval bound", conf=sequential.STOP_CONF)
    where = src + " (stats.intervals.interval at stats.sequential.STOP_CONF)"
    d["stop_interval"] = dict(lo=num(lo, "fraction", ref, where, sunc), hi=num(hi, "fraction", ref, where, sunc))
    d["thresholds"] = dict(go=num(intervals.P_FAIL_GO, "fraction", ref, "stats/intervals.py P_FAIL_GO"),
                           go_bound=num(1 - intervals.LO_SUCCESS_GO, "fraction", ref, "stats/intervals.py LO_SUCCESS_GO (1 - LO_SUCCESS_GO)"),
                           nogo=num(intervals.P_FAIL_NOGO, "fraction", ref, "stats/intervals.py P_FAIL_NOGO"))
    d["region"] = intervals.decided_region(e["k_fail"], e["n"], sequential.STOP_CONF)
    d["decided"] = d["region"] is not None
    d["undecided_statement"] = None if d["decided"] else _undecided(d["stop_interval"]["lo"]["value"], d["stop_interval"]["hi"]["value"])
    if e["n"] < v["n_certify"]:
        fail_lo = intervals.interval(e["k_fail"], e["n"], 0.95)[0]
        d["certify_statement"] = (f"P(fail) < 5 % cannot be certified at n = {e['n']}: {v['n_certify']} members (two-sided 95 % Wilson bound) are needed "
                                  f"(with zero failures n members only show P(fail) < 3/n = {_g(3 / e['n'])}, one-sided 95 %)." if fail_lo < 0.05 else
                                  f"P(fail) < 5 % is excluded by this ensemble (lower 95 % bound {fail_lo:.2f}): no number of members certifies it.")
    return d


def _floor(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    f = e["sensitivity"].get("noise_floor")
    return None if f is None else num(f, "fraction of variance", ref, f"{src}.sensitivity.noise_floor (stats.sensitivity.noise_floor)")


def _sens(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any]:
    p = e["sensitivity"]["param"]
    return dict(param=p, s1=None if p is None else num(e["sensitivity"]["S1"][p], "fraction of variance", ref, src), noise_floor=_floor(e, ref, src),
                computed=bool(e["sensitivity"]["S1"]), text=e["sensitivity"].get("text"), case=e["sensitivity"].get("case"),
                quantity=e["sensitivity"].get("quantity"))


def _top3(e: dict[str, Any], ref: dict[str, Any], src: str) -> list[Any]:
    """The (up to) three perturbation parameters with the largest Sobol first-order index (EASI estimate, stats.sensitivity) that
    clear the permutation noise floor, largest first."""
    s1, f = e["sensitivity"]["S1"] or {}, e["sensitivity"].get("noise_floor") or 0.0
    return [dict(param=p, s1=num(x, "fraction of variance", ref, f"{src}.sensitivity.S1.{p}"))
            for p, x in sorted(s1.items(), key=lambda kv: -kv[1])[:3] if x > f]


def _sens_scope(tr: Trace) -> dict[str, Any]:
    """What the sensitivity indices cannot see (M-17). With the fitted wind priors (ingest/priors_fitted.json) the sentence carries the hourly wind error's sd
    next to the sd of the wind-speed and direction columns; without them the sentence stands without the numbers."""
    f = _jl(tr.run / "ingest" / "priors_fitted.json") or {}
    keys = ("wind_speed_noise", "wind_direction_noise", "wind_speed_bias", "wind_direction_bias")
    if not all(isinstance(f.get(k), dict) and isinstance(f[k].get("value"), (int, float)) for k in keys):
        return dict(text=SENS_SCOPE.format(wind=""), wind_sd=None, wind_hi95={})
    ref, src = tr.ref("ingest", output="priors_fitted.json"), "ingest/priors_fitted.json"
    nodes = {k: num(f[k]["value"], f[k].get("unit", ""), ref, f"{src} {k}.value") for k in keys}
    hi = {k: num(f[k]["value_hi95"], f[k].get("unit", ""), ref, f"{src} {k}.value_hi95")          # round 5, M-10: the fit's 95 % upper bound, if it has one
          for k in keys if isinstance(f[k].get("value_hi95"), (int, float))}
    g = {k: _txt(n) + (f" (95 % upper bound {_txt(hi[k])})" if k in hi else "") for k, n in nodes.items()}
    wind = (f" (sd {g['wind_speed_noise']} and {g['wind_direction_noise']}, against {g['wind_speed_bias']} and {g['wind_direction_bias']} for the "
            "wind-speed and direction columns)")
    return dict(text=SENS_SCOPE.format(wind=wind), wind_sd=nodes, wind_hi95=hi)


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
        d["same_as_baseline"] = bool(t["lo"] <= f["p_fail"] <= t["hi"]) if "p_fail" in t else None      # a flag, not a test (round 6 M-13)
        return d
    n_ev = sum(t["method"] != "not evaluated" for t in f["tried"])
    n_inv = sum(bool(t.get("invalid")) for t in f["tried"])
    counted = src + ".tried (counted by the report)"
    b2d = f.get("base_2d")
    return dict(available=True, needed=True, found=bool(f["found"]), target=f["target"], emulator_trained=bool(f["emulator"]), wind_model=f.get("wind_model"),
                base_2d=None if b2d is None else dict(verdict=b2d["verdict"], p_fail=num(b2d["p_fail"], "fraction", ref, src + ".base_2d.p_fail")),
                evaluated=num(n_ev, "candidates", ref, counted), invalid=num(n_inv, "candidates", ref, counted),
                candidates=num(len(f["tried"]) - n_inv, "candidates", ref, counted),
                verdict_before=f["verdict"], p_fail_before=num(f["p_fail"], "fraction", ref, src + ".p_fail"),
                best=one(f["best"], ".best") if f["best"] else None, tried=[one(t, f".tried[{i}]") for i, t in enumerate(f["tried"])])


def _first_mode(r: dict[str, Any]) -> str | None:
    """The failure mode of the earliest failure of any member (the constraint that was active first), or None when nobody failed."""
    best: tuple[str, float] | None = None
    for k, v in r["first"].items():
        a = np.asarray(v, float)
        if np.isfinite(a).any() and (best is None or float(np.nanmin(a)) < best[1]):
            best = (k, float(np.nanmin(a)))
    return None if best is None else best[0]


def _drivers(e: dict[str, Any], res: dict[str, Any] | None, vid: str, ref: dict[str, Any], src: str) -> dict[str, Any]:
    """What drives a vehicle's failures: the mode of the first failure (from res.pkl, None without it) and each mode's share of the failed members."""
    k = e["k_fail"]
    shares = {m: num(n / k, "fraction of the failed members", ref, f"{src}.modes / k_fail") for m, n in e["modes"].items()} if k else {}
    r = ((res or {}).get("vehicles") or {}).get(vid)
    n_left = e["modes"].get("left_data", 0)
    t_left = None if r is None or not n_left else np.asarray(r["first"].get("left_data", []), float)
    left = None if not n_left else dict(
        members=num(n_left, "members", ref, f"{src}.modes.left_data"),
        first=None if t_left is None or not np.isfinite(t_left).any()
        else tnum(float(np.nanmin(t_left)), ref, f"stage1b/res.pkl vehicles.{vid}.first.left_data"))
    return dict(first_fail_mode=None if r is None else _first_mode(r), res_available=r is not None, mode_shares=shares, left_data=left,
                mode_notes={m: MODE_TEXT[m] for m in e["modes"] if m in MODE_TEXT})


def _cases(tr: Trace, vid: str, n: int) -> list[dict[str, Any]]:
    """Stored sensitivity cases of a vehicle (stage1b/sensitivity_cases.json): the verdict's members under another setting of one input when the case has
    the verdict's n (paired), else a separate sample of its own size, to be read next to the verdict. Nothing is computed here; an absent file is an
    empty list."""
    stored = (_jl(tr.run / "stage1b" / SENSITIVITY) or {}).get(vid, [])
    ref = tr.ref("stage1b", output=SENSITIVITY) if stored else {}
    out = []
    for i, c in enumerate(stored):
        src = f"stage1b/{SENSITIVITY} {vid}[{i}]"
        out.append(dict(case=c["case"], verdict=c["verdict"], note=c.get("note", ""), paired=c["n"] == n, k_fail=num(c["k_fail"], "members", ref, src),
                        n=num(c["n"], "members", ref, src), p_fail=num(c["k_fail"] / c["n"], "fraction", ref, src + " (k_fail / n)")))
    return out


def _vehicles(s1b: dict[str, Any], s1: dict[str, Any] | None, mission: dict[str, Any], cred: dict[str, Any], tr: Trace, cred_ref: dict[str, Any],
              flip: dict[str, Any] | None = None, res: dict[str, Any] | None = None) -> dict[str, Any]:
    ref = tr.ref("stage1b", check="lhs_stratified", output="summary.json")
    plat = {v["id"]: v["platform"] for v in mission["vehicles"]}
    task = {v["id"]: v.get("task", {}) for v in mission["vehicles"]}
    mref = tr.ref("ingest", label="mission")
    out = {}
    for vid, e in s1b["summary"]["vehicles"].items():
        src = f"stage1b/summary.json summary.vehicles.{vid}"
        before = ((s1 or {}).get("summary") or {}).get("vehicles", {}).get(vid)
        p = plat.get(vid)
        out[vid] = dict(cls=e["cls"], platform=p, **_stat(e, ref, src + ".verdict (stats.intervals.verdict)"),
                        dominant_mode=e["dominant"], modes={k: num(n, "members", ref, f"{src}.modes") for k, n in e["modes"].items()},
                        first_fail=tnum(e["first_fail_t"], ref, f"{src}.first_fail_t"), median_fail=tnum(e["median_fail_t"], ref, f"{src}.median_fail_t"),
                        sensitivity=_sens(e, ref, f"{src}.sensitivity (stats.sensitivity, EASI first-order)"), top3=_top3(e, ref, src),
                        fix=_fix(flip, vid, tr), physics=tr.physics(e["cls"]), cases=_cases(tr, vid, e["n"]), **_drivers(e, res, vid, ref, src),
                        speed_ratio=_speed_ratio(e, ref, src),
                        wind3d=_opt(e.get("wind3d_fraction"), "fraction of the sortie records", ref, src + ".wind3d_fraction"),
                        authority=_authority(e.get("authority"), ref, src + ".authority"),
                        profile=_profile(e.get("profile"), ref, src + ".profile"),
                        drift=_drift(task.get(vid, {}), e["cls"], mref, f"mission.yaml vehicles.{vid}.task.heading_to"),
                        usv_modes=_usv_modes(p, e["modes"], tr) if e["cls"] == "usv" else None,
                        verdict_stage1=before["verdict"]["verdict"] if before else None,
                        changed_by_refit=bool(before and before["verdict"]["verdict"] != e["verdict"]["verdict"]),
                        assumed_platform_inputs=num(cred["platform_assumed_counts"].get(p, 0), "inputs", cred_ref, "credibility.json platform_assumed_counts"),
                        assumed_anchor=f"credibility.html#plat-{p}")
    return out


DRIFT_MODES = "battery, seafloor, overdepth, no flight, left data"


def _drift(task: dict[str, Any], cls: str, ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """A drift glider swims one compass heading for the whole window (GliderSim's `drift` mode): its verdict is about that heading, and only the battery,
    the seafloor, the depth limit, a dive that cannot fly and leaving the data can fail it; nothing in the mission is a criterion for it (round 3 M-1)."""
    if cls != "glider" or task.get("mode") != "drift":
        return None
    return dict(heading_to=num(task.get("heading_to", 0.0), "deg", ref, src), modes=DRIFT_MODES)


def _usv_modes(platform: str | None, modes: dict[str, Any], tr: Trace) -> dict[str, Any] | None:
    """The two clocks behind a USV's calm-weather failures, from the platform file: `wing_stall_calm` after the apparent wind has been below the trim
    minimum for calm_sustain_s, `becalmed` after becalmed_after_h unable to stem the current. None for a platform without them or a run with neither mode."""
    if not {"wing_stall_calm", "becalmed"} & set(modes):
        return None
    try:
        from .config import load_platform
        pl = load_platform(platform or "")
        v = {k: pl[g][k]["value"] for g, k in (("mission_defaults", "calm_sustain_s"), ("mission_defaults", "becalmed_after_h"), ("params", "trim_min_aws_ms"))}
    except (KeyError, TypeError, ValueError):
        return None
    ref, src = tr.ref("ingest", label="platform"), f"platforms/{platform}.yaml"
    return dict(trim_min_aws=num(v["trim_min_aws_ms"], "m/s", ref, src + " trim_min_aws_ms"),
                calm_sustain=num(v["calm_sustain_s"] / 60.0, "min", ref, src + " calm_sustain_s"),
                becalmed_after=num(v["becalmed_after_h"], "h", ref, src + " becalmed_after_h"))


def _opt(x: Any, unit: str, ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """A node for a value a summary may not carry (None: not applicable to this link kind, or an older summary)."""
    return None if x is None else num(x, unit, ref, src)


def _speed_ratio(e: dict[str, Any], ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """A USV's speed over ground (stage1.path_speed) against the mean 10 m wind along its track (median of the per-member ratios), next to Chiodi et al.'s 0.178
    that the speed prior is calibrated to; None when the summary has no `speed` block (stage 1 writes it for a USV)."""
    sp = e.get("speed")
    if not sp or sp.get("ratio_median") is None:
        return None
    src += ".speed"
    return dict(ratio=num(sp["ratio_median"], "-", ref, src + ".ratio_median"), sog=_opt(sp.get("sog_ms_median"), "m/s", ref, src + ".sog_ms_median"),
                u10=_opt(sp.get("u10_ms_median"), "m/s", ref, src + ".u10_ms_median"),
                chiodi=num(sp.get("calibration_ratio", CHIODI_RATIO), "-", ref, src + ".calibration_ratio"))


def _profile(p: dict[str, Any] | None, ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """A UAS's flux-profile progress from the summary (`profile`: median waypoints flown per sortie, the pattern length, the share of the flown sorties that
    reached every waypoint), or None for a summary from before the profile was counted (M-1)."""
    if not p:
        return None
    return dict(wp_done_median=num(p["wp_done_median"], "", ref, src + ".wp_done_median"), n_wp=num(p["n_wp"], "", ref, src + ".n_wp"),
                complete_share=num(p["complete_share"], "fraction", ref, src + ".complete_share"))


def _authority(a: dict[str, Any] | None, ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """A UAS's control-authority diagnostics from the summary (`authority`: seconds the horizontal-force demand was beyond the lean-angle clamp per
    sortie, and the demand / clamp ratio), or None when the summary has none."""
    if not a:
        return None
    return dict(clamp_s_median=num(a["clamp_s_median"], "s", ref, src + ".clamp_s_median"), clamp_s_max=num(a["clamp_s_max"], "s", ref, src + ".clamp_s_max"),
                demand_ratio_median=num(a["demand_ratio_median"], "-", ref, src + ".demand_ratio_median"),
                demand_ratio_max=num(a["demand_ratio_max"], "-", ref, src + ".demand_ratio_max"))


def _links(s1b: dict[str, Any], tr: Trace, mission: dict[str, Any]) -> dict[str, Any]:
    ref = tr.ref("stage1b", check="lhs_stratified", output="summary.json")
    need = {lk["id"]: lk["required_fraction"] for lk in mission["links"]}
    out = {}
    for lid, e in s1b["summary"]["links"].items():
        src = f"stage1b/summary.json summary.links.{lid}"
        out[lid] = dict(**_stat(e, ref, src + ".verdict (stats.intervals.verdict)"), method=e["method"], sensitivity=_sens(e, ref, src + ".sensitivity"),
                        top3=_top3(e, ref, src), physics=tr.physics("link"),
                        frac_median=num(e["frac_median"], "fraction", ref, src), frac_p10=num(e["frac_p10"], "fraction", ref, src),
                        margin_db_median=None if e["margin_db_median"] is None else num(e["margin_db_median"], "dB", ref, src),
                        margin_kind=e.get("margin_kind"),
                        frac_beyond_horizon=_opt(e.get("frac_beyond_horizon"), "fraction of the needed samples", ref, src),
                        frac_out_of_range=_opt(e.get("frac_out_of_range"), "fraction of the needed samples", ref, src),
                        granularity=_granularity(e, need.get(lid), ref, src))
    return out


def _granularity(e: dict[str, Any], required: float | None, ref: dict[str, Any], src: str) -> dict[str, Any] | None:
    """How many required samples decide a member's link (stage 1's `need_count_median`), and whether one missed sample is within what the mission allows
    (`granularity_ok`: 1 / need_count <= 1 - required_fraction). None for a summary without them (older runs). A link that is not ok is "undecided:
    granularity": its pass fraction cannot tell 0.95 from 1 (round 3 M-5)."""
    if e.get("need_count_median") is None:
        return None
    n = e["need_count_median"]
    return dict(need_count=num(n, "samples", ref, src + ".need_count_median"), ok=bool(e.get("granularity_ok", True)),
                one_sample=num(1.0 / n, "fraction", ref, src + ".need_count_median (1 / need_count)") if n else None,
                allowed_miss=None if required is None else num(1.0 - required, "fraction", ref, "mission.yaml links.required_fraction (1 - required_fraction)"))


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


def path_speed(r: dict[str, Any]) -> float | None:
    """The median over members of a vehicle's speed over ground in the Stage-1 result, by `stage1.path_speed` (the one definition: the sum of the
    displacements between the stored records over the time they span, which the summary's speed block and the calibration also use); None when no
    member moved."""
    v = _member_speeds(r["lon"], r["lat"], r["t"])
    v = v[np.isfinite(v) & (v > 0)]
    return float(np.median(v)) if v.size else None


def _dive_depth(v: dict[str, Any]) -> float:
    """The depth a glider's task dives to (m): the task's dive_depth_m, else the platform's default, else 500 (as stage 1 reads it)."""
    d = (v.get("task") or {}).get("dive_depth_m")
    if d is None:
        try:
            from .config import load_platform
            d = load_platform(v["platform"])["mission_defaults"]["dive_depth_m"]["value"]
        except (KeyError, TypeError, ValueError):
            d = 500.0
    return max(float(d), 5.0)


def _reach(mission: dict[str, Any], env: Any, tr: Trace, res: dict[str, Any] | None = None, s1b: dict[str, Any] | None = None) -> dict[str, Any]:
    """Where each drifting vehicle can get to within reach.horizon_h of its deploy, in the environment's currents at the deploy time: the fastest
    route over a 41 x 41 grid (cafe.reach: Zermelo speed made good, Dijkstra over 16 neighbours; land and water outside the ingested data blocked), drawn as the
    farthest reachable cell in each of 24 bearings. A UAS is not drawn: it flies sorties from the ship. The router adds the current to a speed through the
    water: a USV is swum at the Stage-1 median speed through the water (`speed.stw_ms_median` of the summary; a summary without it falls back to the speed over
    ground of the tracks, labelled so), a glider at the assumed speed, in the mean current from 5 m to the depth its task dives to."""
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
        speed, how, kind = a[f"reach.speed_ms.{cls[vid]}"]["value"], f"assumed, config/assumptions.yaml reach.speed_ms.{cls[vid]}", "through the water"
        sref, stw = ref, ((((s1b or {}).get("summary") or {}).get("vehicles") or {}).get(vid) or {}).get("speed", {}).get("stw_ms_median")
        run_speed = path_speed(res["vehicles"][vid]) if cls[vid] == "usv" and stw is None and res is not None and vid in res["vehicles"] else None
        if cls[vid] == "usv" and stw is not None:
            speed, how = stw, ("median over members of the mean speed through the water of the Stage-1 tracks; the current is added by the router")
            sref = tr.ref("stage1b", check="lhs_stratified", output="summary.json", label="report (reach map speed from the stage1b summary)")
        elif run_speed is not None:
            speed, how, kind = run_speed, ("median mean path speed over ground of the Stage-1 ensemble, which already includes the drift in the currents "
                                           "(this run's summary has no speed through the water, so the router adds the current a second time)"), "over ground"
            sref = tr.ref("stage1b", output="res.pkl", label="report (reach map speed from the stage1b tracks)")
        src = f"cafe.reach._dijkstra over env.current at the deploy time; speed: {how}"
        try:
            out[vid] = _reach_one(legacy, env, v, cls[vid], speed, hours, allow, ref, src, how, sref, kind, _dive_depth(v))
        except Exception as ex:                                           # noqa: BLE001  any failure of the environment is reported, not hidden
            out[vid] = dict(available=False, reason=f"{type(ex).__name__}: {ex}")
    return dict(available=True, vehicles=out, horizon=num(hours, "h", ref, "config/assumptions.yaml reach.horizon_h"))


def _reach_one(legacy: Any, env: Any, v: dict[str, Any], cls: str, speed: float, hours: float, allow: float, ref: dict[str, Any], src: str, how: str,
               sref: dict[str, Any], kind: str = "through the water", dive_m: float = 100.0, n: int = 41, nb: int = 24) -> dict[str, Any]:
    d = v["deploy"]
    R = (speed + allow) * hours * 3600.0
    xs = np.linspace(-R, R, n)
    NN, EE = np.meshgrid(xs, xs, indexing="ij")
    lat = d["lat"] + np.degrees(NN.ravel() / 6.371e6)
    lon = ((d["lon"] + np.degrees(EE.ravel() / (6.371e6 * math.cos(math.radians(d["lat"])))) + 180.0) % 360.0) - 180.0
    t = np.full(lat.size, utc_s(d["time"]))
    ins = np.asarray(env.inside(lon, lat, t), bool) if hasattr(env, "inside") else np.ones(lat.size, bool)    # outside the ingested data: unknown water
    zs = np.linspace(-5.0, -dive_m, 6) if cls == "glider" else [0.0]                # a glider feels the current over the band it dives through
    band = f"mean current from 5 m to {dive_m:g} m" if cls == "glider" else "current at the surface"
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
                max_range_km=num(far.max() / 1e3, "km", ref, src), speed=num(speed, "m/s", sref, how), speed_from=how, speed_kind=kind, current_band=band,
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
                 forcing=num(w["stress"], unit, wref, f"{src}[{i}].stress (queried by the windows stage)", basis=w["basis"]),
                 failed_at=[tnum(x, wref, f"{src}[{i}].failed_at") for x in w.get("failed_at", [])])
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
        m_all = lo.size
        try:
            ins = np.asarray(env.inside(lo, la, t), bool) if hasattr(env, "inside") else np.ones(m_all, bool)       # round 7, M-11
            t, lo, la = t[ins], lo[ins], la[ins]
            dropped = (f"{m_all - lo.size} of {m_all} track points are outside the downloaded data (more than half of the members left it): not shown"
                       if lo.size < m_all else None)
            if m_all and not lo.size:
                out["vehicles"][vid] = dict(available=False, reason=dropped)
                continue
            w, h, cur = env.wind(lo, la, 10.0, t), env.waves(lo, la, t)["Hs"], env.current(lo, la, 0.0, t)
        except Exception as ex:                                           # noqa: BLE001  a failure of the environment never fails the report (as in _reach)
            out["vehicles"][vid] = dict(available=False, reason=f"{type(ex).__name__}: {ex}")
            continue

        def speed(a: Any) -> NDArray[np.float64]:
            return np.asarray(np.hypot(*np.moveaxis(np.asarray(a.value, np.float64), -1, 0)), np.float64)

        def q(a: Any, v: np.ndarray, unit: str, what: str) -> dict[str, Any]:
            return vals(v, unit, ref, f"{a.source} ({what} at the stage1b median track)", None if a.uncertainty is None else float(np.mean(a.uncertainty)))
        out["vehicles"][vid] = dict(available=True, dropped=dropped, t=vals(t, "s since 1970-01-01T00:00:00Z", ref, "stage1b/res.pkl vehicles.t"),
                                    wind10=q(w, speed(w), "m/s", "10 m wind speed"), hs=q(h, np.asarray(h.value, float), "m", "Hs"),
                                    current=q(cur, speed(cur), "m/s", "surface current speed"))
    out.update(available=True, how=f"Queried from the Environment passed to report.write ({type(env).__name__}) at up to 24 points of each "
                                   "vehicle's stage1b median track: wind at 10 m, Hs from waves(), current at z = 0.")
    return out


def _stage3(plan: dict[str, Any], wins: dict[str, Any] | None, st3: dict[str, Any] | None, refit: dict[str, Any] | None, tr: Trace,
            pref: dict[str, Any]) -> dict[str, Any]:
    les = plan["les"]
    out: dict[str, Any] = dict(label=les["label"], cpu_fallback=bool(les["cpu_fallback"]), backend=les["backend"], rate_source=les["rate_source"],
                               rate=num(les["rate"], "cell-updates/s", pref, "plan.json les.rate"), reach=_les_reach(plan), vehicles={}, refit={})
    if st3 is None:
        return dict(out, available=False, reason=NOT_PRESENT.format("stage3/windows.json"))
    r3, rr, wref = tr.ref("stage3", output="windows.json"), tr.ref("refit", output="refit.json"), tr.ref("windows", output="windows.json")
    for vid, ws in st3.items():
        rv = (refit or {}).get(vid)
        rows = []
        for i, w in enumerate(ws):
            src = f"stage3/windows.json {vid}[{i}]"
            cut = bool(w.get("cut"))                                      # a window cut at the time limit: its numbers depend on the clock, so none is read
            failed = [c["name"] for c in w.get("checks", []) if not c["ok"]]
            reasons = [str(x) for x in w.get("reasons", [])]
            used = bool(rv and rv.get("used") and w.get("ok"))
            if used:
                why = None
            elif not w.get("ok"):
                parts = ["failed self-checks: " + ", ".join(failed)] if failed else []
                why = "; ".join(parts + reasons + ([w["error"]] if w.get("error") and w["error"] not in reasons else [])
                                or (["cut at the time limit"] if cut else [])) or "no check or error recorded"
            elif rv is not None:
                why = rv.get("reason") or "the refit did not use this vehicle"
            else:
                why = NOT_PRESENT.format("refit/refit.json") if refit is None else "no refit entry for this vehicle"
            at = (wins or {}).get(vid, [])
            rows.append(dict(
                label=f"W{i + 1}", ok=bool(w.get("ok")), error=w.get("error"), used_in_refit=used, not_used_because=why, cut=cut, reasons=reasons,
                cut_statement=CUT_STATEMENT if cut else None,
                cells_per_delta=None if cut or not (w.get("resolution") or {}).get("cells_per_delta") else
                num(w["resolution"]["cells_per_delta"], "cells per boundary-layer thickness", r3, src + ".resolution.cells_per_delta"),
                nu_raised=(w.get("resolution") or {}).get("nu_floored"),
                t=tnum(at[i]["t"], wref, "windows/windows.json") if i < len(at) else None,
                checks=[] if cut else [dict(name=c["name"], ok=bool(c["ok"]), value=num(c["value"], "", r3, src + ".checks"),
                                            limit=num(c["limit"], "", r3, src + ".checks"), note=c.get("note", "")) for c in w.get("checks", [])],
                coefficients={} if cut else {k: num(w[k], "-", r3, f"{src}.{k}") for k in ("cd", "cd_spread", "cd_hangar", "cl") if w.get(k) is not None}))
        out["vehicles"][vid] = rows
        if rv is not None:
            drag = rv.get("drag", {})
            keys = ("mean", "sigma", "change_vs_hangar")
            out["refit"][vid] = dict(used=bool(rv["used"]), reason=rv.get("reason"), failed_checks=list(rv.get("failed_checks", [])),
                                     drag={k: num(drag[k], "-", rr, f"refit/refit.json {vid}.drag.{k}") for k in keys if k in drag})
    return dict(out, available=True)


CUT_STATEMENT = "window cut at the time limit: its coefficients are withheld"


def _les_reach(plan: dict[str, Any]) -> dict[str, Any]:
    """What the planner says about each LES window (plan.json stage3.les: `reachable` = its physical lattice viscosity is within the cell-updates
    its slice affords, `runs`, `skip_reason`) and its note ("no LES coefficients exist on this machine ..."). Only booleans and strings are read,
    so no number escapes the traced nodes."""
    les = (plan.get("stage3") or {}).get("les") or {}
    return dict(note=les.get("note"), windows=[dict(window=k, reachable=bool(w["reachable"]), runs=bool(w["runs"]), reason=w.get("skip_reason"))
                                               for k, w in sorted((les.get("windows") or {}).items())])


def _fresh(e: dict[str, Any], ref: dict[str, Any], s: str) -> dict[str, Any] | None:
    """The hold-out's fresh-draw check (whatif.fit_class): held-out points of this run re-estimated on members no training row used, and the emulator's
    RMSE against them, as observed and less their own noise. None when the hold-out had none (or an older holdout.json)."""
    if not e.get("fresh_points"):
        return None
    return dict(points=num(e["fresh_points"], "held-out points", ref, s + ".fresh_points"),
                n_members=num(e["fresh_n_members"], "members", ref, s + ".fresh_n_members"),
                rmse=num(e["rmse_fresh"], "fraction", ref, s + ".rmse_fresh"),
                noise_floor=num(e["noise_floor_fresh"], "fraction", ref, s + ".noise_floor_fresh"),
                rmse_debiased=num(e["rmse_fresh_debiased"], "fraction", ref, s + ".rmse_fresh_debiased"))


def _emulator(emu: dict[str, Any] | None, design: dict[str, Any] | None, tr: Trace, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    ep = budget.emulator_plan(plan) if plan else {}
    note = None if ep.get("trains", True) else str(ep["note"])                # the planner's "this budget gives N points per class, 100 are needed"
    if emu is None:
        return dict(available=False, reason=NOT_PRESENT.format("emulator/holdout.json"), vehicles={}, plan_note=note)
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
                 coverage={k: num(x, "fraction", ref, s + ".coverage") for k, x in e["coverage"].items()}, cls=e.get("cls"), acceptance=None,
                 coverage_raw_p={k: num(x, "fraction", ref, s + ".coverage_raw_p") for k, x in (e.get("coverage_raw_p") or {}).items()} or None)
        if "acceptance" in e:

            def lim(v: Any, u: str) -> dict[str, Any]:
                return num(v, u, ref, "cafe/pm/whatif.py LIMITS (BRIEF 2.7 acceptance)")

            ac = e["acceptance"]
            d["acceptance"] = dict(rmse_ok=bool(ac["rmse_ok"]), coverage_ok=bool(ac["coverage_ok"]), query_ok=bool(ac["query_ok"]),
                                   query_ms=num(e["query_ms"], "ms", ref, s + ".query_ms"),
                                   noise_floor_rmse=num(e["noise_floor_rmse"], "fraction", ref, s + ".noise_floor_rmse"),
                                   rmse_debiased=num(e["rmse_debiased"], "fraction", ref, s + ".rmse_debiased"),
                                   fresh=_fresh(e, ref, s), draws=e.get("draws"),
                                   rows=num(e["rows"], "rows", ref, s + ".rows"),
                                   coverage_chance_fail=_opt(e.get("coverage_chance_fail"), "fraction", ref, s + ".coverage_chance_fail"),
                                   limits=dict(rmse=lim(0.05, "fraction"), coverage=lim(0.05, "fraction"), query_ms=lim(10.0, "ms")))
        d["used"], d["unused_reason"] = e.get("used"), e.get("unused_reason")
        out[vid] = d
    dd = None
    if design is not None:
        dref, s = tr.ref("emulator", output="design.json"), "emulator/design.json"
        dd = dict(train_budget=num(design["share_s"] * design["train_fraction"], "s", dref, s + " share_s x train_fraction"),
                  share=num(design["share_s"], "s", dref, s), variant=num(design["variant_s"], "s", dref, s), variant_source=design["variant_s_source"],
                  variants=num(len(design["variants"]), "runs", dref, s), spent=num(design["spent_s"], "s", dref, s),
                  flip_spent=num(design["flip_spent_s"], "s", dref, s), rows_added=num(design["rows_added"], "rows", dref, s),
                  table_rows=num(design["table_rows"], "rows", dref, s), table=design["table"], stage1b_free=bool(design["stage1b_free"]))
    return dict(available=True, vehicles=out, design=dd, plan_note=note)


def _timing(plan: dict[str, Any], tr: Trace, pref: dict[str, Any]) -> dict[str, Any]:
    """What the planner charged against what the stages took (round 5, M-13): stage 1's `plan.json` stage1_s (a lower bound, `stage1_s_basis`) against its
    ledger's wall_s, and the emulator's variant runs (its ledger's `variant_planned_s` each and `variant_wall_s` measured, kept out of the hashed design.json
    by DECISIONS 139; neither is in an older run) as planned and as measured. A part whose two sides are not both there is left out."""
    out: dict[str, Any] = {}
    L = tr.led.get("stage1")
    if L and plan.get("stage1_s") is not None:
        out["stage1"] = dict(planned=num(plan["stage1_s"], "s", pref, "plan.json stage1_s"), basis=plan.get("stage1_s_basis"),
                             measured=num(L["wall_s"], "s", tr.ref("stage1"), "checkpoints/stage1/ledger.json wall_s"))
    sw = (tr.led.get("stage1b") or {}).get("sensitivity_wall_s")               # the USV rerun under the brief's VPP bias: in no share of the plan (M-17)
    if sw is not None:
        out["stage1b_sensitivity"] = dict(measured=num(sw, "s", tr.ref("stage1b"), "checkpoints/stage1b/ledger.json sensitivity_wall_s"))
    d = tr.led.get("emulator") or {}
    w = d.get("variant_wall_s")
    if w and d.get("variant_planned_s") is not None:
        ref, src = tr.ref("emulator"), "checkpoints/emulator/ledger.json"
        out["variants"] = dict(runs=num(len(w), "runs", ref, src + " variant_wall_s"),
                               planned=num(d["variant_planned_s"] * len(w), "s", ref, src + " variant_planned_s x runs"),
                               measured=num(sum(w), "s", ref, src + " variant_wall_s (sum)"))
    return out


def _machine(plan: dict[str, Any], tr: Trace, pref: dict[str, Any]) -> dict[str, Any]:
    # the report's own ledger is not written until the report is: any on disk is an earlier attempt's
    live = {st: L for st, L in tr.led.items() if L and st != "report"}
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
                timing=_timing(plan, tr, pref), git_sha=sorted({L["git_sha"] for L in live.values()}), versions=(first or {}).get("versions", {}),
                report_stage="report stage: written after this table, so its wall time and code are not in it",
                machine=None if first is None else dict(host=first["machine"]["host"], bench_id=first["machine"]["bench_id"], cpus=cpus))


def _assumed(cred: dict[str, Any], cred_ref: dict[str, Any]) -> dict[str, Any]:
    by: dict[str, int] = {}
    for i in cred["assumed_inputs"]:
        if i["kind"] != "fitted":                                          # a value this run fitted from data is listed, but not counted as assumed
            by[i["file"]] = by.get(i["file"], 0) + 1
    return dict(page="credibility.html", total=num(sum(by.values()), "inputs", cred_ref, "credibility.json assumed_inputs (kind other than fitted)"),
                by_file={f: num(n, "inputs", cred_ref, "credibility.json assumed_inputs") for f, n in sorted(by.items())},
                items=[dict(id=i["id"], kind=i["kind"], value=i["value"], unit=i["unit"], why=i["why"], href=f"credibility.html#{i['anchor']}")
                       for i in cred["assumed_inputs"]],
                factors=[dict(name=f["name"], level=f"{f['level']} of 4") for f in cred["factors"]])


def _sanity(cred: dict[str, Any], vehicles: dict[str, Any], links: dict[str, Any]) -> dict[str, Any]:
    """BRIEF section 6's expected outcome for the demo mission against this run's verdicts (the table is credibility.EXPECTED)."""
    sn = cred.get("sanity")
    if sn is None:
        return dict(applies=False, reason="BRIEF section 6 states an expected outcome for the demo mission only; this mission has none.")
    both = {**vehicles, **links}
    return dict(applies=True, mission=sn["mission"], note=sn["note"],
                rows=[dict(id=r["id"], expected=r["expected"], observed=r["observed"], agrees=r["agrees"], detail=r.get("detail", ""),
                           p_fail=both[r["id"]]["p_fail"]) for r in sn["rows"]])


def build(run: pathlib.Path, mission: dict[str, Any], plan: dict[str, Any], env: Any = None) -> dict[str, Any]:
    tr = Trace(run)
    cred = json_object(run / "report" / "credibility.json")
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
        vehicles=_vehicles(s1b, _jl(run / "stage1" / "summary.json"), mission, cred, tr, cred_ref, flip, res), links=_links(s1b, tr, mission),
        map=_map(mission, res, why, wins, tr, cfg), reach=_reach(mission, env, tr, res, s1b), environment=_env(mission, env, res, wins, s1b, tr),
        stage3=_stage3(plan, wins, st3, refit, tr, pref), emulator=_emulator(emu, design, tr, plan), machine=_machine(plan, tr, pref),
        assumed_inputs=_assumed(cred, cred_ref), sensitivity_scope=_sens_scope(tr))
    rep["sanity"] = _sanity(cred, rep["vehicles"], rep["links"])
    own = _jl(run / "stage3" / "subgrid_calibration.json")
    rep["subgrid"] = dict(source=("this run's stage3/subgrid_calibration.json" if own
                                  else "the shipped config/subgrid.json (no passed LES window in this run)"),
                          calibrated=not any(x["id"] == credibility.SUBGRID_LIMITATION["id"] for x in cred["limitations"]),
                          statement=next((x["text"] for x in cred["limitations"] if x["id"] == credibility.SUBGRID_LIMITATION["id"]), None),
                          switches=s1b["summary"].get("subgrid_switches"))          # {name: {on, defaulted}}; None for a summary from before round 5, M-7
    rep["receipts"] = sorted(tr.rows.values(), key=lambda r: r["id"])
    rep["traceability_problems"] = check_traceability(rep)
    return rep


# ------------------------------------------------------------------------------------------------------ HTML (from the JSON only)

SINGULAR = {"candidates": "candidate", "notches": "notch", "members": "member"}      # round 8, M-47: "1 candidates" read as a count of one


def _txt(n: dict[str, Any]) -> str:
    if n.get("utc"):
        return str(n["utc"])
    unit = f" {n['unit']}" if n["unit"] not in ("", "-", "fraction") else ""
    if "values" in n:
        return f"{len(n['values'])} values{unit}"
    v = n["value"]
    if v == 1 and not isinstance(v, bool):
        unit = f" {SINGULAR.get(n['unit'], n['unit'])}"
    return ("n/a" if v is None else f"{v:.4g}" if isinstance(v, float) else str(v)) + unit


def _rid(receipt: str) -> str:
    return "r-" + re.sub(r"[^A-Za-z0-9]+", "-", receipt)


def _n(n: dict[str, Any] | None) -> str:
    """A number as text plus links to its ledger (L) and to its row of the receipts table (R)."""
    if n is None:
        return "n/a"
    tip = f"{n['stage']}: {n['source']}" + ("" if n["uncertainty"] is None else f"; uncertainty {json.dumps(n['uncertainty'])}")
    href = f' href="../{html.escape(n["ledger"])}"' if n["ledger"].startswith("checkpoints/") else ""          # a model-receipt table is not in the run
    return (f'<span class=n>{html.escape(_txt(n))}<a class=lk{href} title="{html.escape(tip)}">L</a>'
            f'<a class=lk href="#{_rid(n["receipt"])}" title="{html.escape(n["receipt"])}">R</a></span>')


def _badge(v: str) -> str:
    return f'<span class="badge {v.lower().replace("-", "")}">{html.escape(v)}</span>'


def _undecided_badge(d: dict[str, Any]) -> str:
    """The badges of a verdict that is not decided: the stopping interval spans a threshold, and (a link only) the required fraction cannot be resolved on the
    samples it is judged on (granularity; a link never required at all is the extreme case). The Verdicts table and the card both use this."""
    g = d.get("granularity")
    return ("" if d["decided"] else f' <span class="badge undecided">undecided at n = {d["n"]["value"]}</span>') \
        + ("" if g is None or g["ok"] else ' <span class="badge undecided">undecided: granularity</span>')


INTERVAL_SCOPE = ("This interval is the sampling error of {n} at fixed inputs: the fitted priors enter as their point values and the other assumed inputs "
                  "are not varied beyond their stated priors (see the sensitivity scope and the credibility report).")          # round 7, M-21


def _usv_bias_html(v: dict[str, Any]) -> str:
    """Under a USV's interval: the speed factor's sampled range (computed from the prior) and the stored brief-bias case (round 7, M-15); else nothing."""
    c = next((c for c in v["cases"] if "usv_vpp_bias_brief" in c["case"]), None) if v["cls"] == "usv" else None
    return "" if c is None else (f"<p class=muted>The {credibility.usv_speed_sampling()} (the published spread of VPP over-prediction, "
                                 f"not an uncertainty of this model); the brief's bias case gives {_n(c['k_fail'])} of {_n(c['n'])} "
                                 f"({_badge(c['verdict'])}).</p>")


def _stat_html(d: dict[str, Any]) -> str:
    u = d["p_fail"]["uncertainty"]
    si, th = d["stop_interval"], d["thresholds"]
    h = (f"<p>P(fail) = {_n(d['p_fail'])}, {u['conf']:.0%} {html.escape(u['kind'])} {u['lo']:.3g} to {u['hi']:.3g} (the verdict's own level); "
         f"{_n(d['k_fail'])} failed of {_n(d['n'])} (certifying P(fail) &lt; 5 % needs {_n(d['n_certify'])}, two-sided 95 % Wilson bound).</p>"
         f"<p class=muted>{INTERVAL_SCOPE.format(n=_n(d['n']))}</p>"
         f"<p class=muted>Stopping rule: the {si['lo']['uncertainty']['conf']:.0%} {html.escape(si['lo']['uncertainty']['kind'].replace(' bound', ''))} "
         f"on P(fail) is {_n(si['lo'])} to {_n(si['hi'])}; verdict rule: GO when P(fail) is at most {_n(th['go'])} and the "
         f"{u['conf'] * 100:.0f} % Wilson upper bound on P(fail) is at most {_n(th['go_bound'])}"
         f"{' (looser than 1 - go)' if th['go_bound']['value'] > th['go']['value'] + 1e-12 else ''}; "
         f"NO-GO when P(fail) is above {_n(th['nogo'])}; MARGINAL between.</p>")
    if d["undecided_statement"]:
        h += f"<p class=warn>{html.escape(d['undecided_statement'])}</p>"
    if d["certify_statement"]:
        h += f"<p class=warn>{html.escape(d['certify_statement'])}</p>"
    return h + (f"<p class=muted>{html.escape(d['note'])}</p>" if d["note"] else "")


def _sens_html(s: dict[str, Any]) -> str:
    """The sentence stage 1 wrote for the case that applies (what was ranked, or which of "too few failures", "nothing above the floor", "all pass or all
    fail" it is); a summary without one (older runs) gets the old wording."""
    if s.get("text"):
        return html.escape(s["text"].rstrip(".")) + (f" (exact S1 {_n(s['s1'])})" if s["param"] is not None else "")
    if s["param"] is None:
        if s.get("computed") and s.get("noise_floor"):
            return f"no parameter clears the noise floor (S1 {_n(s['noise_floor'])}, the 95 % level of unrelated outcomes at this member count)"
        return "none (all-pass, all-fail, or fewer than 16 members)"
    return f"<code>{html.escape(s['param'])}</code> (S1 {_n(s['s1'])})"


def _top3_html(top: list[Any], floor: Any = None, quantity: str | None = None) -> str:
    """`quantity` is what the indices were taken on (the sensitivity entry's own: a margin, a fraction, or the failure indicator; round 5, M-2)."""
    fl = f"; the noise floor at this member count is S1 {_n(floor)}" if floor else ""
    what = "the 0/1 failure indicator" if quantity == "failure indicator" else f"the {html.escape(quantity)}" if quantity else "the ranked outcome"
    if not top:
        return f"<p class=muted>Top sensitivities: none above the noise floor (or all-pass, all-fail, or fewer than 16 members){fl}.</p>"
    items = "; ".join(f"<code>{html.escape(t['param'])}</code> {_n(t['s1'])}" for t in top)
    return f"<p>Top sensitivities (Sobol first-order, share of the variance of {what}, above the permutation noise floor): {items}{fl}.</p>"


SAME_AS_BASELINE = "not distinguishable from the baseline (its interval contains the baseline's P(fail))"


def _tried_html(t: dict[str, Any]) -> str:
    e = html.escape
    how = e("n/a" if t["method"] == "not evaluated" else t["method"]) + (f", n = {_n(t['n'])}" if t["n"] else "") \
        + (f", distance {_n(t['distance'])} of {_n(t['threshold'])}" if t["distance"] else "")
    u = (t["p_fail"] or {}).get("uncertainty")
    pf = _n(t["p_fail"]) + (f" ({u['lo']:.3g} to {u['hi']:.3g})" if u else "")
    note = e(t["reason"]) + (f"{'; ' if t['reason'] else ''}{SAME_AS_BASELINE}" if t.get("same_as_baseline") else "")
    return f"<tr><td>{e(t['change'])}<td>{_n(t['cost'])}<td>{how}<td>{pf}<td>{e(str(t['verdict'] or ''))}<td>{note}</tr>"


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
                f"{_badge(f['verdict_before'])} to {_badge(b['verdict'])} ({how}){'; ' + SAME_AS_BASELINE if b.get('same_as_baseline') else ''}.")
    elif f["evaluated"]["value"] == 0:
        line = (f"<b>not searched</b>: none of the {_n(f['candidates'])} could be evaluated (no emulator answer in range, and this vehicle's share "
                f"of the Stage-1 budget did not cover a run), so this is not a finding that nothing helps (P(fail) now {_n(f['p_fail_before'])}).")
    else:
        line = (f"{_n(f['evaluated'])} evaluated, of {_n(f['candidates'])} that could be: none reaches {e(f['target'])} "
                f"(P(fail) now {_n(f['p_fail_before'])}); "
                + ("the emulator answered those in its range." if f["emulator_trained"]
                   else "no emulator is trained yet, so only the nearest few were run in Stage 1."))
    rows = "".join(_tried_html(t) for t in f["tried"])
    b2d = f["base_2d"]
    wm = (f"<p class=muted>{e(f['wind_model'])}" + (f" The baseline under the same model: {_badge(b2d['verdict'])} P(fail) {_n(b2d['p_fail'])}." if b2d else "")
          + "</p>") if f["wind_model"] else ""
    k = len(f["tried"])
    s = "" if k == 1 else "s"
    return (f"<p>What would fix it ({e(f['target'])}): {line}</p>{wm}<details><summary>All {k} candidate{s}: {_n(f['evaluated'])} evaluated of "
            f"{_n(f['candidates'])} that can be evaluated, {_n(f['invalid'])} that cannot (off the window, the box or the data)</summary>"
            "<div class=scroll><table>"
            f"<tr><th>Change<th>Cost (notches)<th>Answered by<th>P(fail)<th>Verdict<th>Note</tr>{rows}</table></div></details>")


def _physics_html(p: dict[str, Any]) -> str:
    """The model receipts behind a verdict: pass and fail counts of its group, the failing ones named; "not run" is never shown as a pass."""
    e = html.escape
    if "passed" not in p:                                                  # not run, or stale: made by other code
        return f"<p class=warn>Model receipts (<code>{e(p['group'])}</code>): {e(p['status'])}. {e(p['reason'])}</p>"
    bad = f" Failing: {e('; '.join(p['failures']))}." if p["failures"] else ""
    return (f"<p class={'warn' if p['failures'] else 'muted'}>Model receipts (<code>{e(p['group'])}</code>): {_n(p['passed'])} pass, {_n(p['failed'])} fail."
            f"{bad} They check the model that produced this verdict against references; they are not a check of the verdict.</p>")


def _drivers_html(v: dict[str, Any]) -> str:
    e = html.escape
    shares = ", ".join(f"{e(m)} {_n(x)}" for m, x in v["mode_shares"].items())
    first = (f"the first failure was by <b>{e(v['first_fail_mode'])}</b>" if v["first_fail_mode"]
             else ("no member failed" if not shares else "res.pkl records no first-failure time for the failed members") if v.get("res_available", False)
             else "which mode failed first is not known (res.pkl is not available)")
    more = f"; share of the failed members by mode (a member can fail in several): {shares}" if shares else ""
    ld = v["left_data"]
    left = (f"<p class=warn>{_n(ld['members'])} members left the downloaded data" + (f" at about {_n(ld['first'])}" if ld["first"] else "")
            + " (counted as failed): widen <code>box</code> or <code>pad_deg</code> and rerun.</p>") if ld else ""
    notes = "".join(f"<p class=muted><code>{e(m)}</code>: {e(t)}.</p>" for m, t in v.get("mode_notes", {}).items())
    return f"<p>What drives the failures: {first}{more}.</p>{left}{notes}"


def _cases_html(cases: list[dict[str, Any]]) -> str:
    e = html.escape
    rows = "".join(f"<tr><td>{e(c['case'])}<td>{_badge(c['verdict'])}<td>{_n(c['p_fail'])}<td>{_n(c['k_fail'])} of {_n(c['n'])}<td>{e(c['note'])}</tr>"
                   for c in cases)
    if not cases:
        return ""
    same = all(c["paired"] for c in cases)
    return (("<p>Sensitivity cases (same members and same other inputs; only the named input replaced):</p>" if same else
             "<p>Sensitivity cases (a separate sample whose member count differs from the verdict's, so a difference mixes the changed input with the "
             "changed sample):</p>") + "<div class=scroll><table>"
            f"<tr><th>Case<th>Verdict<th>P(fail)<th>Failed<th>Note</tr>{rows}</table></div>")


def _speed_html(v: dict[str, Any]) -> str:
    """USV speed against the calibration target (and why the mission ratio is lower), the UAS attitude statement (M-28) with the control-authority
    numbers, and the share of UAS sortie records flown in the 3-D wind field."""
    sr, w3, au = v["speed_ratio"], v["wind3d"], v["authority"]
    out = ""
    if sr:
        out += (f"<p class=muted>Speed over ground / mean 10 m wind along the track: median of the per-member ratios {_n(sr['ratio'])}"
                + (f"; median speed over ground {_n(sr['sog'])} over median wind {_n(sr['u10'])} (the quotient of two medians is not the median ratio)"
                   if sr["sog"] and sr["u10"] else "") + f"; the speed prior is calibrated to Chiodi et al.'s "
                f"{_n(sr['chiodi'])}, a scenario that differs from the mission (no current, uniform wind, sailing to a station). {USV_RATIO_NOTE}</p>")
    if v["cls"] == "uas":
        pr = v.get("profile")
        if pr:
            out += (f"<p>Median waypoints flown per sortie: {_n(pr['wp_done_median'])} of {_n(pr['n_wp'])}; share of the flown sorties that "
                    f"reached every waypoint: {_n(pr['complete_share'])} (a sortie that returns earlier did not deliver the full profile and fails as "
                    "<code>profile_incomplete</code>).</p>")
        out += f"<p class=muted>{UAS_ATTITUDE_NOTE if pr else UAS_ATTITUDE_NOTE_NO_PROFILE}"
        if au:
            out += (f" Horizontal-force demand beyond the lean-angle clamp: {_n(au['clamp_s_median'])} per sortie (median; largest {_n(au['clamp_s_max'])}), "
                    f"demand / clamp {_n(au['demand_ratio_median'])} (median), {_n(au['demand_ratio_max'])} (largest).")
        out += "</p>"
    if w3:
        out += f"<p class=muted>Sortie records flown in the WRF 3-D wind field: {_n(w3)}; the rest used the 10 m wind scaled by the log profile.</p>"
    return out


def _task_html(v: dict[str, Any]) -> str:
    """The drift glider's task and what can fail it, and the clocks behind a USV's calm-weather modes."""
    out, d, u = "", v["drift"], v["usv_modes"]
    if d:
        out += (f"<p>Task: drift on a fixed heading of {_n(d['heading_to'])}; failure modes that can occur: {html.escape(d['modes'])}. The mission has no "
                "criterion for a drift glider (no station, no waypoint): GO means only that the battery and depth limits held on that heading.</p>")
    if u:
        out += (f"<p class=muted>Calm-weather modes: <code>wing_stall_calm</code> fires when the apparent wind stays below {_n(u['trim_min_aws'])} for "
                f"{_n(u['calm_sustain'])} (a calm leaves the wing untrimmed and the vehicle without drive); <code>becalmed</code> only after "
                f"{_n(u['becalmed_after'])} of being unable to stem the current. The two clocks differ on purpose. "
                "<code>wing_stall_angle</code> is the apparent wind inside the bow cone.</p>")
    return out


def _vehicle_html(vid: str, v: dict[str, Any]) -> str:
    e = html.escape
    modes = ", ".join(f"{e(k)}: {_n(n)}" for k, n in v["modes"].items()) or "none"
    ch = ""
    if v["changed_by_refit"]:
        ch = f"<p class=warn>The verdict changed from {_badge(v['verdict_stage1'])} to {_badge(v['verdict'])} after the stage-3 refit.</p>"
    return (f"<div class=card><h3>{e(vid)} {_badge(v['verdict'])}{_undecided_badge(v)} <span class=muted>{e(v['cls'])}, {e(str(v['platform']))}</span></h3>"
            f"{_stat_html(v)}{_usv_bias_html(v)}{_physics_html(v['physics'])}{ch}"
            f"<p>Dominant failure mode: <b>{e(str(v['dominant_mode']))}</b> (all modes: {modes}).<br>"
            f"First failure: {_n(v['first_fail'])}; median failure: {_n(v['median_fail'])}.<br>Most sensitive to: {_sens_html(v['sensitivity'])}.</p>"
            f"{_task_html(v)}{_drivers_html(v)}{_speed_html(v)}{_cases_html(v['cases'])}"
            f"{_top3_html(v['top3'], v['sensitivity']['noise_floor'], v['sensitivity'].get('quantity'))}{_fix_html(v['fix'])}"
            f"<p class=muted>Depends on {_n(v['assumed_platform_inputs'])} (assumed platform values), listed in the "
            f"<a href='{e(v['assumed_anchor'])}'>credibility report</a>.</p></div>")


def _margin_html(k: dict[str, Any]) -> str:
    """What the margin is, and the share of the needed moments the geometry alone decided (beyond the radio horizon, out of acoustic range)."""
    e = html.escape
    out = f" ({e(k['margin_kind'])})" if k["margin_kind"] else ""
    if k["frac_beyond_horizon"]:
        out += f"; beyond the radio horizon at {_n(k['frac_beyond_horizon'])}, where no margin is computed"
    if k["frac_out_of_range"]:
        out += f"; out of the acoustic model's range at {_n(k['frac_out_of_range'])}, where no margin is computed"
    return out


def _granularity_html(g: dict[str, Any] | None) -> str:
    if g is None:
        return ""
    if g["need_count"]["value"] == 0:
        return (f"<p class=warn>Required at no moment in the median member ({_n(g['need_count'])}): the link was not exercised, "
                f"so its pass fraction says nothing (the mission allows {_n(g['allowed_miss'])} to be missed); this verdict is undecided: granularity.</p>")
    miss = f"; one missed sample is {_n(g['one_sample'])} of them and the mission allows {_n(g['allowed_miss'])} to be missed"
    return (f"<p class={'muted' if g['ok'] else 'warn'}>Each member's pass fraction is decided on {_n(g['need_count'])} "
            f"(the median number of required samples per member){miss}"
            + ("." if g["ok"] else ", so this verdict is undecided: granularity (too few samples to tell the required fraction from every sample).") + "</p>")


def _link_html(lid: str, k: dict[str, Any]) -> str:
    e = html.escape
    return (f"<div class=card><h3>{e(lid)} {_badge(k['verdict'])}{_undecided_badge(k)}</h3>{_stat_html(k)}{_physics_html(k['physics'])}"
            f"{_granularity_html(k['granularity'])}"
            f"<p>Method: {e(k['method'])}.<br>"
            f"Fraction of required moments met: median {_n(k['frac_median'])}, 10th percentile {_n(k['frac_p10'])}; "
            f"median margin {_n(k['margin_db_median'])}{_margin_html(k)}.<br>Most sensitive to: {_sens_html(k['sensitivity'])}.</p>"
            f"{_top3_html(k['top3'], k['sensitivity']['noise_floor'], k['sensitivity'].get('quantity'))}</div>")


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
        h += (f"<li>{e(vid)}: " + (f"farthest reachable cell {_n(d['max_range_km'])} from {_n(d['deploy'])} at {_n(d['speed'])} {e(d['speed_kind'])} "
                                    f"({e(d['speed_from'])}; {e(d['current_band'])}), largest current on the grid {_n(d['flow_max'])}, "
                                    f"outline {_n(d['polygon'])}"
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
        if not d.get("available", True):                                  # older reports have no flag; round 7, M-11
            h += f"<p class=warn><b>{e(vid)}</b>: {e(d['reason'])}.</p>"
            continue
        h += (f"<p><b>{e(vid)}</b>: 10 m wind {_n(d['wind10'])}; Hs {_n(d['hs'])}; surface current {_n(d['current'])}; at times {_n(d['t'])}."
              + (f" {e(d['dropped'][0].upper() + d['dropped'][1:])}." if d.get("dropped") else "") + "</p>")
    for vid, d in env["forcing_at_windows"].items():
        rows = "; ".join(f"{_n(w['t'])}: {_n(w['forcing'])} ({e(w['forcing']['basis'])})"
                         + (f"; those members failed at {', '.join(_n(x) for x in w['failed_at'])}" if w["failed_at"] else "") for w in d["windows"])
        h += (f"<p><b>{e(vid)}</b>, {e(d['quantity'])} at the worst windows (each window is the record of the strongest analysis-field forcing; "
              f"it is not the instant a member failed): {rows}.</p>")
    return h


def _window_html(w: dict[str, Any]) -> str:
    e = html.escape
    ck = "".join(f"<tr><td>{e(c['name'])}<td>{'pass' if c['ok'] else '<b>FAIL</b>'}<td>{_n(c['value'])}<td>{_n(c['limit'])}<td>{e(c['note'])}</tr>"
                 for c in w["checks"])
    co = ", ".join(f"{e(k)} {_n(x)}" for k, x in w["coefficients"].items())
    use = "used in the refit" if w["used_in_refit"] else f"not used in the refit: {e(str(w['not_used_because']))}"
    state = ("passed its self-checks" if w["ok"] else "was cut at the time limit" if w["cut"] else "failed its self-checks" if w["checks"]
             else "did not run" if w["error"] else "failed with no check recorded")
    raised = "n/a" if w["nu_raised"] is None else "yes" if w["nu_raised"] else "no"
    why = "".join(f"<li>{e(x)}" for x in w["reasons"])
    return (f"<div class=card><b>{w['label']}</b> {state}; {use}"
            + (f". Reason: {e(str(w['error']))}" if w["error"] else "")
            + (f". At {_n(w['t'])}" if w["t"] else "") + (f". Coefficients: {co}" if co else "")
            + (f"<p class=warn>{e(w['cut_statement'])}</p>" if w["cut"] else "")
            + f"<p class=muted>Cells per boundary-layer thickness: {_n(w['cells_per_delta'])} (BRIEF 2.6: 5 to 10); lattice viscosity raised: {raised}.</p>"
            + (f"<ul>{why}</ul>" if why else "")
            + f"<div class=scroll><table><tr><th>Check<th>Result<th>Value<th>Limit<th>Note</tr>{ck}</table></div></div>")


def _stage3_html(s: dict[str, Any]) -> str:
    e = html.escape
    h = f"<div class=warn><p class=big>{e(s['label'])}</p></div>" if s["cpu_fallback"] else f"<p class=big>{e(s['label'])}</p>"
    h += f"<p>Backend {e(s['backend'])} at {_n(s['rate'])} ({e(s['rate_source'])}).</p>"
    h += f"<p class=warn>{e(s['reach']['note'])}</p>" if s["reach"]["note"] else ""
    for r in s["reach"]["windows"]:
        if r["reason"] or not r["reachable"]:
            h += (f"<p class=muted>LES window {e(r['window'])}: " + ("reaches" if r["reachable"] else "does not reach") + " the physical lattice viscosity in "
                  f"its slice of the budget; {'run' if r['runs'] else 'not run'}. {e(r['reason'] or '')}</p>")
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


def _chance(c: Any) -> str:
    """How often a calibrated emulator misses the coverage gate by chance on this many held-out points; empty for older runs."""
    return "" if c is None else f" (a calibrated emulator misses it by chance with probability {_n(c)} on this many held-out points)"


def _emulator_html(m: dict[str, Any]) -> str:
    e = html.escape
    note = f"<p class=warn>{e(m['plan_note'])}</p>" if m["plan_note"] else ""
    if not m["available"]:
        return f"<p class=warn>{e(m['reason'])}</p>{note}"
    h = note
    for vid, v in m["vehicles"].items():
        if not v["trained"]:
            h += f"<p><b>{e(vid)}</b>: not trained. {e(v['reason'])}" + (f" ({_n(v['rows'])} of this class.)" if "rows" in v else "") + "</p>"
            continue
        raw = v["coverage_raw_p"] or {}
        sc = "; ".join(f"{e(k)} RMSE {_n(x)}, "
                       + (f"coverage on the calibration scale (clipped logit) {_n(v['coverage'][k])}; on the raw P scale {_n(raw[k])}, where a target of "
                          "exactly 0 or 1 cannot be inside the interval" if k in raw else f"coverage {_n(v['coverage'][k])}")
                       + f" (nominal {_n(v['nominal'])})" for k, x in v["rmse"].items())
        kind = f" ({e(v['cls'])} emulator)" if v["cls"] else ""
        h += f"<p><b>{e(vid)}</b>{kind}: trained on {_n(v['n_train'])}, scored on {_n(v['n_test'])} held-out; {sc}.</p>"
        a = v["acceptance"]
        if a:

            def ok(b: Any) -> str:
                return "met" if b else "<b>MISSED</b>"

            fr = a["fresh"]
            h += (f"<p class=muted>BRIEF 2.7 acceptance: P(fail) RMSE against the true P(fail) {_n(a['rmse_debiased'])} in sample &le; "
                  f"{_n(a['limits']['rmse'])} {ok(a['rmse_ok'])}{' (on the larger of this and the fresh-draw figure below)' if fr else ''} "
                  f"(the held-out RMSE against the member-count targets, less their own "
                  f"Monte-Carlo noise {_n(a['noise_floor_rmse'])} in quadrature); coverage within {_n(a['limits']['coverage'])} of nominal "
                  f"{ok(a['coverage_ok'])}{_chance(a.get('coverage_chance_fail'))}; query {_n(a['query_ms'])} "
                  f"&le; {_n(a['limits']['query_ms'])} {ok(a['query_ok'])}; {_n(a['rows'])} rows of this class.</p>")
            if v["used"] is False:
                h += f"<p class=warn><b>Not used for answers: Stage 1 answered instead.</b> {e(v['unused_reason'] or '')}</p>"
            h += ("<p class=muted>Fresh-draw check: " + (
                f"{_n(fr['points'])} re-run on {_n(fr['n_members'])} that no training row used; the emulator's RMSE against them "
                f"{_n(fr['rmse'])}, {_n(fr['rmse_debiased'])} less their own noise {_n(fr['noise_floor'])}; the RMSE limit is judged on the larger of this "
                "and the in-sample figure." if fr else "no held-out point of this run's variants could be re-run, so the RMSE limit is judged on the in-sample "
                "figure alone.") + (f" {e(a['draws'])}" if a["draws"] else "") + "</p>")
    d = m["design"]
    if d:
        h += (f"<p>Training table {e(d['table'])}: {_n(d['table_rows'])}, {_n(d['rows_added'])} added by this run. "
              f"Variant runs of the mission: {_n(d['variants'])} "
              f"({_n(d['variant'])} each, from {e(d['variant_source'])}) were charged {_n(d['spent'])} of planned cost against the emulator share "
              f"{_n(d['share'])}, of which {_n(d['train_budget'])} is for them"
              f"{' (the share of stage 1b included, since no vehicle was refit)' if d['stage1b_free'] else ''}; "
              f"the flip search was charged {_n(d['flip_spent'])} of planned "
              "Stage-1 cost (a planned charge, not a measurement: each stage's measured time is under Machine and budget).</p>")
        if d["variants"]["value"] == 0:
            h += (f"<p class=warn>No variant run fitted: one costs {_n(d['variant'])}, more than the {_n(d['train_budget'])} they may use, so this run "
                  "added only its own rows to the table and no emulator can be trained from it at this budget; a class is trained only from rows the "
                  "table already holds. Every EMULATED answer comes from a trained emulator, so none is shown unless one was trained.</p>")
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
    tm = m.get("timing") or {}
    s1, vr = tm.get("stage1"), tm.get("variants")
    took = ""
    if s1:
        basis = f" (the plan is a lower bound: {e(s1['basis'])})" if s1["basis"] else ""
        took += f"<p>Stage 1: planned {_n(s1['planned'])}, measured {_n(s1['measured'])}{basis}.</p>"
    if sv := tm.get("stage1b_sensitivity"):
        took += ("<p>Stage 1b sensitivity case (the USV again under the brief's VPP bias): planned none, it is charged to no share; "
                 f"measured {_n(sv['measured'])}.</p>")
    if vr:
        took += f"<p>Emulator variant runs: {_n(vr['runs'])}, planned {_n(vr['planned'])}, measured {_n(vr['measured'])}.</p>"
    ing = (f"<p class=muted>Ingest took {_n(m['wall_s']['ingest'])}: it is not counted against --budget (a download over the network is a separate step, "
           "RUNBOOK 4, whose duration depends on the link).</p>") if "ingest" in m["wall_s"] else ""
    return (f"<pre>{e(m['describe'])}</pre><div class=scroll><table><tr><th>Vehicle<th>Cost per mission day (s per batch + s per member)"
            f"<th>Source</tr>{cost}</table></div>"
            f"<div class=scroll><table><tr><th>Stage<th>Wall time</tr>{wall}</table></div><p class=muted>{e(m['report_stage'])}.</p>{ing}"
            f"<p>Plan: {plan}. ArduCopter SITL is not part of the pipeline; it runs only as the slow receipts (<code>UAS SITL vs our controller</code>, "
            f"<code>UAS sortie</code>), so the ensemble is pure physics.</p>{took}"
            f"<p>Code: git {e(', '.join(m['git_sha']))}. Machine: {where}.</p><p class=muted>{ver}</p>")


def _assumed_html(a: dict[str, Any]) -> str:
    e = html.escape
    rows = "".join(f"<tr><td>{e(f)}<td>{_n(n)}</tr>" for f, n in a["by_file"].items())
    fac = "".join(f"<tr><td>{e(f['name'])}<td>{e(f['level'])}</tr>" for f in a["factors"])
    lst = "".join(f"<li><a href='{e(i['href'])}'><code>{e(i['id'])}</code></a> ({e(i['kind'])}) {e(i['value'])} {e(i['unit'])}" for i in a["items"])
    return (f"<p>{_n(a['total'])} are assumed or are priors, not measurements, and verdicts depend on them. Full detail: "
            f"<a href='credibility.html'>credibility report</a> (levels, V&amp;V 20 table, limitations).</p>"
            f"<div class=scroll><table><tr><th>File<th>Inputs</tr>{rows}</table></div>"
            f"<div class=scroll><table><tr><th>NASA-STD-7009B factor<th>Level</tr>{fac}</table></div>"
            f"<details><summary>All assumed inputs</summary><ul>{lst}</ul></details>")


def _receipts_html(rows: list[Any]) -> str:
    e = html.escape
    body = "".join(f"<tr id='{_rid(r['id'])}'><td><code>{e(r['id'])}</code><td>{e(r['kind'])}"
                   f"<td>{'ok' if r['ok'] else {'stale': 'stale', 'not_run': 'not run'}.get(r['state'], '<b>FAILED</b>')}<td>{e(r['got'])}<td>{e(r['limit'])}"
                   f"<td><code>{e(r['sha256'][:16])}</code><td><a href='../{e(r['ledger'])}'>ledger</a></tr>" for r in rows)
    return f"<div class=scroll><table><tr><th>Receipt<th>Kind<th>Status<th>Value<th>Limit<th>sha-256<th>Ledger</tr>{body}</table></div>"


def _sanity_html(sn: dict[str, Any]) -> str:
    e = html.escape
    if not sn["applies"]:
        return f"<h2>Sanity check against the brief</h2><p class=muted>{e(sn['reason'])}</p>"
    rows = "".join(f"<tr><td>{e(r['id'])}<td>{e(r['expected'])}<td>{_badge(r['observed'])} {_n(r['p_fail'])}"
                   f"<td>{'cannot be checked from the verdict' if r['agrees'] is None else 'yes' if r['agrees'] else '<b>NO</b>'}"
                   f"{'<br><span class=muted>' + e(r['detail']) + '</span>' if r['detail'] else ''}</tr>" for r in sn["rows"])
    return (f"<h2>Sanity check against the brief</h2><p class=muted>{e(sn['note'])}</p><div class=scroll><table>"
            f"<tr><th>Vehicle or link<th>Brief expects<th>This run<th>Agrees</tr>{rows}</table></div>")


def render(rep: dict[str, Any]) -> str:
    e = html.escape
    m = rep["mission"]
    rows = "".join(f"<tr><td><a href='#v-{e(i)}'>{e(i)}</a><td>{_badge(d['verdict'])}{_undecided_badge(d)}<td>{_n(d['p_fail'])}<td>{_n(d['n'])}"
                   f"<td>{_n(d.get('frac_beyond_horizon') or d.get('frac_out_of_range'))}</tr>" for i, d in {**rep["vehicles"], **rep["links"]}.items())
    bad = rep["traceability_problems"]
    by = {st: [r["id"] for r in rep["receipts"] if r["state"] == st] for st in ("fail", "stale", "not_run")}
    tr = (f"<p class=warn>Traceability problems: {e('; '.join(bad))}</p>" if bad
          else "<p class=muted>Traceability check: every number links to a receipt, which is a hashed ledger output, a ledger check, "
               "or a group of model receipts. A link is provenance, not a pass.</p>")
    tr += f"<p class=warn>{e(rep['subgrid']['statement'])}</p>" if rep["subgrid"]["statement"] else ""
    tr += f"<p class=muted>Sub-grid calibration used by the stages after stage 3: {e(rep['subgrid']['source'])}.</p>"
    sw = rep["subgrid"].get("switches")
    left = " (left out of the mission: on by default)"
    names = {k: k.replace("_", " ").replace("sde", "SDE") for k in (sw or {})}
    tr += (("<p class=muted>Sub-grid switches: " + ", ".join(f"{names[k]} {'on' if x['on'] else 'off'}{left if x['defaulted'] else ''}" for k, x in sw.items())
            + ".</p>") if sw else "")
    n = len(rep["receipts"])
    tr += (f"<p class=warn>{len(by['fail'])} of {n} receipts below failed a check and are marked FAILED: {e('; '.join(by['fail']))}.</p>" if by["fail"] else "")
    tr += (f"<p class=warn>{len(by['stale'])} of {n} are stale (made by other code; rerun <code>python -m cafe.pm receipts</code>): "
           f"{e('; '.join(by['stale']))}.</p>" if by["stale"] else "")
    tr += (f"<p class=warn>{len(by['not_run'])} of {n} were not run: {e('; '.join(by['not_run']))}.</p>" if by["not_run"] else "")
    inputs = e("; ".join(i["ref"] for i in m["data_consumed"]["inputs"]) or "none recorded")
    body = (f"<h1>{e(m['name'])}: pre-mission report</h1><p>{e(m['description'])}</p>"
            f"<p class=muted>Window {e(m['window']['start'])} to {e(m['window']['end'])}; seed {_n(m['seed'])}; verdicts from {e(rep['verdict_source'])}. "
            "In the text, <b>L</b> opens the ledger of the stage that produced a number and <b>R</b> its row in the receipts table. "
            f"Inputs read: {inputs} ({e(m['data_consumed']['variables'])}).</p>{tr}"
            "<p><a href='credibility.html'>Credibility report</a> | <a href='report.json'>report.json</a></p>"
            "<h2>Verdicts</h2><div class=scroll><table><tr><th>Vehicle or link<th>Verdict<th>P(fail)<th>Members"
            f"<th>Beyond radio horizon or out of acoustic range</tr>{rows}</table></div>"
            f"<p class=muted>{e(rep['sensitivity_scope']['text'])}</p>"
            + "".join(f"<div id='v-{e(i)}'>{_vehicle_html(i, d)}</div>" for i, d in rep["vehicles"].items())
            + "".join(f"<div id='v-{e(i)}'>{_link_html(i, d)}</div>" for i, d in rep["links"].items())
            + _sanity_html(rep["sanity"])
            + f"<h2>Map</h2>{_map_html(rep['map'], rep['reach'])}<h2>Environment along the tracks</h2>{_env_html(rep['environment'])}"
            f"<h2>Stage 3 and refit</h2>{_stage3_html(rep['stage3'])}<h2>Emulator</h2>{_emulator_html(rep['emulator'])}"
            f"<h2>Machine and budget</h2>{_machine_html(rep['machine'])}<h2>Assumed inputs</h2>{_assumed_html(rep['assumed_inputs'])}"
            f"<h2 id=receipts>Receipts</h2>{_receipts_html(rep['receipts'])}")
    return credibility.page(f"{m['name']} report", body)


def _token(text: str) -> re.Pattern[str]:
    """`text` as a whole token: not the tail of a longer number or word before it ("0 members" is not in "10 members"), nor the head of one after."""
    return re.compile(r"(?<![\w.\-])" + re.escape(html.escape(text)) + r"(?!\w|\.\d)")


def check_rendered(rep: dict[str, Any], html_text: str) -> list[str]:
    """Every number node's text is in the page as a whole token (the HTML is rendered from the JSON; this catches a section that drops a number)."""
    return [f"{p}: {_txt(o)!r} is not in the HTML" for k, p, o in _walk(rep) if k == "node" and not _token(_txt(o)).search(html_text)]


def write(run_dir: str | pathlib.Path, mission: dict[str, Any], plan: dict[str, Any], env: Any = None) -> list[pathlib.Path]:
    """Write credibility.{html,json}, then report.json and index.html. Returns every path written, for the report ledger."""
    run = pathlib.Path(run_dir)
    cred = credibility.write(run)
    rep = build(run, mission, plan, env)
    j, h = run / "report" / "report.json", run / "report" / "index.html"
    j.write_text(json.dumps(rep, indent=1, allow_nan=False))
    h.write_text(render(rep))
    return [h, j, *cred]
