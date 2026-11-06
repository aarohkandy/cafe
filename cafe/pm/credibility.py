"""Credibility report (BRIEF 5.4): NASA-STD-7009B factor table, ASME V&V 20 table, assumed inputs, known limitations.

    write(run_dir) -> [run_dir/report/credibility.html, run_dir/report/credibility.json]

Every level is computed from files that exist: the run directory (ledgers, summaries, plan) and the repo (platforms/, config/,
tests/, docs/). Where evidence is missing the level is 0 and the cell says what is missing. Level 4 is never awarded: it needs
independent review or field evidence, which no file in this tool can show. The 0-4 scale is BRIEF 5.4's; the rule behind each
level below is this tool's own reading of the factor, not the wording of NASA-STD-7009B (the standard was not re-read), so
the report prints the rule next to every level. A known limitation that bears on a factor caps it at 2.

ASME V&V 20 (E = S - D, U_val = sqrt(U_num^2 + U_input^2 + U_D^2), |E| <= U_val): rows come from cafe.pm.dtmb5415.tabulate
(all four uncertainty terms; files of another recipe are "not run", and a row whose U_val is half the reference or more is listed but does not
count toward Validation level 3) and from the stored slow-run receipts under $CAFE_DATA/receipts (S and D only: the runs store no
uncertainty terms, so they are listed with E and "U_val not stored", never as validated). A comparison that was not run is
listed as "not run" with the file that would hold it.
"""
from __future__ import annotations

import html
import json
import math
import os
import pathlib
from typing import Any, Iterable

from . import config, pipeline
from .audit import ledger_problems
from .ledger import STAGES
from .stage1 import NOT_EXERCISED
from .stats import intervals, sampling

ROOT = config.ROOT
LEVELS = {0: "none: no evidence", 1: "weak: evidence exists, nothing checked it", 2: "moderate: checked by this tool's own self-checks",
          3: "strong: checked against an independent reference", 4: "very strong: independent review or field evidence (never awarded here)"}

# Known honesty caveats, verbatim from the lead's list. factors: NASA factors they bear on (cap 2); where: repo files that show them.
LIMITATIONS = [
    dict(id="L01", text="acoustic 4 km MF range is true by construction", factors=["validation", "input_pedigree"],
         where=["platforms/modems.yaml", "cafe/pm/physics/comms.py"]),
    dict(id="L02", text="the USV 12 m/s point is a fit", factors=["validation"], where=["platforms/saildrone_explorer.yaml", "cafe/pm/physics/usv.py"]),
    dict(id="L03", text="the Sun et al. magnitude is 8–26 % vs the published 30–35 %", factors=["validation"], where=["cafe/pm/physics/usv.py"]),
    dict(id="L04", text="the Cd receipt is a closure", factors=["validation", "verification"], where=["cafe/pm/env/coare.py"]),
    dict(id="L05", text="several citations were recalled, not re-read", factors=["input_pedigree"],
         where=["platforms/saildrone_explorer.yaml", "platforms/seaglider.yaml", "platforms/quad_uas.yaml"]),
    dict(id="L06", text="the glider T(z) profile is assumed", factors=["input_pedigree"], where=["platforms/seaglider.yaml"]),
    dict(id="L07", text="turbulence σ_v/σ_u and σ_w/σ_u are low", factors=["validation", "uncertainty"], where=["cafe/pm/env/subgrid.py"]),
    dict(id="L08", text="LBM sphere drag is not met on CPU", factors=["validation"], where=["cafe/pm/stage3/lbm.py", "cafe/pm/stage3/nest.py"]),
    dict(id="L09", text="the wall model is not validated", factors=["validation"], where=["cafe/pm/stage3/wallmodel.py"]),
    dict(id="L10", text="the SITL return/landing is unreliable", factors=["verification", "robustness"], where=["cafe/pm/physics/uas.py"]),
    dict(id="L11", text="the UAS propulsion curve is parametric", factors=["input_pedigree"], where=["platforms/quad_uas.yaml"]),
    dict(id="L12", text="GCI values stored before the r = (N_f/N_c)^(1/3) fix were understated", factors=["verification", "uncertainty"],
         where=["cafe/pm/vv.py", "cafe/pm/dtmb5415.py"]),
    dict(id="L14", text="the wind prior's persistent and short-lived parts are split from the TAO moorings over this window: "
                        "an estimate of the order, not a measurement",
         factors=["uncertainty"], where=["cafe/pm/pipeline.py", "cafe/pm/env/perturb.py", "config/perturbations.yaml"]),
    dict(id="L15", text="no LES window can reach the lattice viscosity floor on a CPU, so none is run and the sub-grid layer and the drag refit stay "
                        "uncalibrated; no GPU run exists", factors=["validation", "robustness"],
         where=["config/assumptions.yaml", "cafe/pm/budget.py", "cafe/pm/stage3/pipeline_windows.py"]),
    dict(id="L16", text="the refit is a single pass: stage 1 is rerun once with the refitted multipliers, not looped until the verdicts stop changing",
         factors=["robustness"], where=["cafe/pm/pipeline.py"]),
    dict(id="L17", text="UAS attitude exceedance cannot fire in this controller model (tilt clamp 35 deg, exceedance 42 deg)", factors=["validation"],
         where=["cafe/pm/physics/uas.py", "platforms/quad_uas.yaml"]),
    dict(id="L18", text="the USV speed prior is calibrated in a scenario without current, and the mission's westward current then lowers the speed ratio "
                        "again; "
                        "whether Chiodi et al.'s 0.178 already includes currents is not known, so a double penalty is possible and not established",
         factors=["validation", "uncertainty"], where=["platforms/saildrone_explorer.yaml", "cafe/pm/physics/usv.py"]),
    dict(id="L19", text="the persistent wind-speed prior is a boundary moment estimate from the TAO moorings of one regime, not a measured spread: in the "
                        "evidence run q5 11 moorings over 6 days gave 0.113 m/s, with a 95 % upper bound of about 0.5 m/s (the literature prior was 2.0 m/s), "
                        "and regime-to-regime bias outside the window is not sampled",
         factors=["uncertainty", "validation"], where=["cafe/pm/pipeline.py"]),
    dict(id="L20", text="UAS turbulence is generated at one height for all legs: one Mann box per sortie, at the deck height plus the mean of the sortie's "
                        "flight altitudes, is applied to every leg, so a leg flown at another altitude sees the length scale of that height",
         factors=["validation"], where=["cafe/pm/stage1.py", "cafe/pm/env/subgrid.py"]),
]

SUBGRID = "sub-grid layer uncalibrated"
SUBGRID_LIMITATION = dict(id="L13", factors=["validation", "uncertainty"], where=["config/subgrid.json", "cafe/pm/stage3/pipeline_windows.py"])

FACTORS = [("data_pedigree", "Data pedigree"), ("verification", "Verification"), ("validation", "Validation"), ("input_pedigree", "Input pedigree"),
           ("uncertainty", "Uncertainty characterization"), ("robustness", "Results robustness"), ("use_history", "Use history"),
           ("ms_management", "M&S management"), ("people", "People qualifications")]

LEVEL_TEXT = {"data_pedigree": {3: "strong: compared with moorings (the comparison also sets the wind priors)"},
              "verification": {2: "moderate: the ledger chain audits clean and test files exist; this report does not run or read the tests "
                                  "(`make audit` does)"},
              "ms_management": {3: "strong: ledger chain audited by the tool; house rules and ruff configured (`make audit` runs ruff; this report only checks "
                                   "that it is configured); no independent reviewer"}}
# (LEVEL_TEXT replaces LEVELS[n] for the factor and level it names)
WIND_RMSE_LIMIT = (2.0, 15.0)     # pooled speed (m/s) and direction (deg) RMSE above which the mooring comparison does not earn level 3: BRIEF 5.4's prior sd
UVAL_MAX_FRAC = 0.5               # a V&V 20 row counts toward Validation level 3 only when U_val is below this fraction of the reference (DECISIONS row)
USV_CHIODI_RATIO = 0.178          # Chiodi et al. (2021) mean SOG / mean wind, 0.96 / 5.4 (platforms/saildrone_explorer.yaml)
ACOUSTIC_NEAR_KM = 3.0            # BRIEF section 6: a glider acoustic link is GO within this distance of the ship, NO-GO beyond it

RULES = {
    "data_pedigree": "1 ingest ledger names its inputs; 2 and every ingest self-check passed, the COARE u* is within "
                     f"{100 * pipeline.USTAR_AGREE_BAND:.0f} % of the UMWM ust at {100 * pipeline.USTAR_AGREE_FRACTION:.0f} % of the "
                     "sea points (BRIEF 2.1) and the wrfout/umwmout schemas exist; "
                     "3 and the WRF wind and SST were compared with TAO/TRITON moorings for this mission, with pooled wind RMSE within the brief's prior sd "
                     "(2.0 m/s, 15 deg); the comparison also sets the wind priors, so it is not independent of the run.",
    "verification": "1 a stage ledger exists; 2 every ledger is clean (ok, no failed check, chain intact, hashes reproduce) and test files exist "
                    "(this report does not read their results); "
                    "3 and a grid-convergence (GCI) study backs a V&V 20 row.",
    "validation": "1 a comparison with a reference ran; 2 and one has all of U_num, U_input, U_D; 3 and at least four such rows, "
                  "each with a converged finest grid, all satisfy |E| <= U_val with U_val below half the reference "
                  "(a wider uncertainty cannot validate it; a row whose finest grid has not converged is not judged).",
    "input_pedigree": "1 platform inputs carry provenance; 2 and at least half are sourced (not assumed, not recalled); "
                      "3 and at least 80 % are, and no perturbation prior is of kind assumed.",
    "uncertainty": "1 verdict intervals exist; 2 and the Latin-hypercube stratification checks passed; "
                   "3 and every vehicle and link that leaves P(fail) < 5 % open (95 % Wilson lower bound on P(fail) below 5 %; "
                   "a link with the verdict NOT EXERCISED is none, no member count decides it) has n >= n_certify, "
                   "and no perturbation prior is of kind assumed.",
    "robustness": "1 one ensemble ran; 2 and a first-order sensitivity clearly above chance exists (more ranked than the 5 % level allows by luck over "
                  "the report's tests), or a refit reran; "
                  "3 and a stage-3 refit reran stage 1 and no verdict changed.",
    "use_history": "1 only if docs/USE_HISTORY.md records a past prediction compared with a real outcome; otherwise 0.",
    "ms_management": "1 ledgers exist; 2 and every ledger carries a git sha, config hash, versions, and the stage-1 seeds; "
                     "3 and the ledger chain audits clean, docs/BUILDERS.md exists and ruff is configured.",
    "people": "1 only if docs/QUALIFICATIONS.md records who ran and reviewed this; otherwise 0.",
}

# What BRIEF section 6 says a correct tool should report for the demo mission: a sanity check, not a target. allowed: the verdicts that agree with the
# sentence, None where the sentence depends on something the verdict alone does not show (a gust-front window; a glider-ship distance has `distance`).
EXPECTED: dict[str, dict[str, dict[str, Any]]] = {"tepex_c_demo": {
    "glider_eq": dict(allowed=["MARGINAL", "NO-GO"], text="gliders MARGINAL or NO-GO for station-keeping against the jet"),
    "glider_2n": dict(allowed=["GO"], text="gliders GO for a drift section"),
    "usv": dict(allowed=["MARGINAL", "GO"],
                text="USV MARGINAL in the low-wind/high-current window of 7-8 March, GO otherwise (the demo window ends 7 March 12Z)"),
    "uas": dict(allowed=None, text="UAS NO-GO in any gust-front window (needs the gust-front windows, which the verdict does not show)"),
    "usv-uas-rf": dict(allowed=["GO"], text="links GO except glider acoustic at more than 3 km"),
    "usv-shore-iridium": dict(allowed=["GO"], text="links GO except glider acoustic at more than 3 km"),
    "glider_eq-ship-acoustic": dict(allowed=None, distance=True, text="glider acoustic link GO within 3 km of the ship, NO-GO beyond it"),
    "glider_2n-ship-acoustic": dict(allowed=None, distance=True, text="glider acoustic link GO within 3 km of the ship, NO-GO beyond it"),
}}
DRIFT_DETAIL = "a drift glider has no mission criterion; GO means the battery and depth limits held on its fixed heading"
SANITY_NOTE = ("BRIEF section 6, 'Expected outcome': what a correct tool should say about the demo mission, used as a sanity check and not as a "
               "target. It applies to that mission only, so no other mission has a sanity block. A disagreement is not a verdict on the model: it "
               "can be model bias, a threshold choice or the expectation itself.")


def subgrid_uncalibrated(run: pathlib.Path, root: pathlib.Path = ROOT) -> str | None:
    """"sub-grid layer uncalibrated: <reason>" when the stage-3 ledger says so (its own reason) or neither the run's stage3/subgrid_calibration.json nor
    config/subgrid.json has a source_run (no passed LES window has recalibrated it: the turbulence and gust statistics are the defaults); None when the
    layer was calibrated."""
    led = _json(run / "checkpoints" / "stage3" / "ledger.json") or {}
    note = next((n for n in led.get("notes", []) if str(n).startswith(SUBGRID)), None)
    if note:
        return str(note)
    if (_json(run / "stage3" / "subgrid_calibration.json") or {}).get("source_run"):          # this run's own calibration (round 3 M-23)
        return None
    cfg = _json(root / "config" / "subgrid.json") or {}
    if (cfg.get("calibration") or {}).get("source_run") is None:
        return (f"{SUBGRID}: config/subgrid.json calibration.source_run is null, so no passed LES window has recalibrated it; "
                "the turbulence and gust statistics are the defaults")
    return None


def usv_speed_sampling() -> str:
    """What the stage-1 USV speed prior (`usv_vpp_bias`, uniform [lo, hi] on the fractional speed change) samples, computed from config/perturbations.yaml:
    the half-width and range against the unbiased polar speed, the sd, and the half-width against the speed actually flown (1 + centre of it)."""
    e = sampling.load_perturbations()["usv_vpp_bias"]
    half, centre = (e["hi"] - e["lo"]) / 2, (e["hi"] + e["lo"]) / 2
    def pct(x: float) -> str:
        return f"{round(100 * x, 9):.1f} %"                                                  # (2.8499999999999996 is 2.85)
    return (f"speed factor is sampled within +-{pct(half)} of the unbiased polar speed (range {pct(2 * half)}, sd {pct(2 * half / math.sqrt(12))}; "
            f"+-{pct(half / (1 + centre))} of the speed flown)")


def data_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


def _json(p: pathlib.Path) -> Any:
    return config.json_object(p) if p.is_file() else None


# ------------------------------------------------------------------------------------------------------ assumed inputs

def _prov(node: Any, path: str, file: str, out: list[dict[str, Any]]) -> None:
    """Every mapping with a `value`, `source` or `assumed` key is one provenance item; recurse into the rest."""
    if not isinstance(node, dict):
        return
    a, s = node.get("assumed"), node.get("source")
    if a or s or "value" in node:
        why = str(node.get("why") or (a if isinstance(a, str) else ""))
        text = f"{why} {s or ''}"
        out.append(dict(file=file, path=path, assumed=bool(a), sourced=bool(s), recalled="recalled" in text, why=why,
                        unit=str(node.get("unit", "")), value=repr(node.get("value")), source=str(s or "")))
    for k, v in node.items():
        _prov(v, f"{path}.{k}" if path else str(k), file, out)


def platform_shipped(ref: str, root: pathlib.Path = ROOT) -> bool:
    """Whether a platform reference (a name or a path, config.platform_path) is one of root/platforms/*.yaml."""
    p = config.platform_path(ref)
    return p.suffix == ".yaml" and p.parent.resolve() in {(root / "platforms").resolve(), config.PLATFORMS.resolve()}


def platform_key(ref: str, root: pathlib.Path = ROOT) -> str:
    """What names a platform in `Facts.used`, `platform_assumed_counts` and the report's anchor: the file's stem when it is one of root/platforms/*.yaml
    (a name, or a path to one of them), else the reference as given (a file elsewhere has no stem of its own: two directories can hold a seaglider.yaml)."""
    return config.platform_path(ref).stem if platform_shipped(ref, root) else str(ref)


def platform_label(key: str, shipped: bool) -> str:
    """The `file` of a platform's items: platforms/<stem>.yaml for a key that is a stem, the path as given otherwise."""
    return f"platforms/{key}.yaml" if shipped else key


def platform_items(root: pathlib.Path = ROOT, elsewhere: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The provenance leaves of root/platforms/*.yaml (key: the stem) and of each platform file given by a path outside it, `elsewhere` (key: the path
    as given; a file that is not there is left out: the run's hangar stage fails on it)."""
    out: list[dict[str, Any]] = []
    for path, label, key in [(f, platform_label(f.stem, True), f.stem) for f in sorted((root / "platforms").glob("*.yaml"))] + \
                            [(config.platform_path(r), r, r) for r in sorted(set(elsewhere))]:
        if path.is_file():
            part: list[dict[str, Any]] = []
            _prov(config.read_yaml(path), "", label, part)
            out += [dict(i, key=key) for i in part]
    return out


def plat_anchor(key: str) -> str:
    """The html id of a platform's table in credibility.html (an id has no white space)."""
    return "plat-" + "_".join(key.split())


def dist_text(e: dict[str, Any]) -> str:
    """A perturbation prior as the distribution that is drawn: normal(mean, sigma), lognormal(median, sigma), uniform [lo, hi], or a fixed setting.
    (`value` in perturbations.yaml is the spread, and is unused for a uniform or a fixed one, so it is never printed as the setting.)"""
    d = e.get("dist")
    if d == "normal":
        return f"normal(mean {e.get('mean', 0.0)!r}, sigma {e['value']!r})"
    if d == "lognormal":
        return f"lognormal(median {e.get('median', 1.0)!r}, sigma {e['value']!r})"
    if d == "uniform":
        return f"uniform [{e['lo']!r}, {e['hi']!r}]"
    if d == "fixed":
        return f"fixed at {e.get('mean')!r} (a setting, not sampled)"
    return repr({k: e[k] for k in ("dist", "mean", "median", "value", "lo", "hi") if k in e})


def _used(spec: dict[str, Any]) -> str:
    """A marginal as the Stage-1 run recorded it (summary.json priors: normal mean/sd, lognormal median/sigma, uniform lo/hi)."""
    d = spec.get("dist")
    if d == "normal":
        return f"normal(mean {spec['mean']!r}, sigma {spec['sd']!r})"
    if d == "lognormal":
        return f"lognormal(median {spec['median']!r}, sigma {spec['sigma']!r})"
    if d == "uniform":
        return f"uniform [{spec['lo']!r}, {spec['hi']!r}]"
    return repr(spec)


def run_priors(run: pathlib.Path | None) -> dict[str, Any]:
    """The priors the run's ensemble used (stage1b/summary.json `priors`, else stage1's): the yaml entries with the TAO-fitted ones in place."""
    for st in ("stage1b", "stage1"):
        d = _json(run / st / "summary.json") if run else None
        if d and d.get("priors"):
            return dict(d["priors"])
    return {}


def assumed_inputs(root: pathlib.Path = ROOT, run: pathlib.Path | None = None, elsewhere: Iterable[str] = ()) -> list[dict[str, Any]]:
    """The full list: every assumptions.yaml key, every perturbation prior (kind prior or assumed) as its distribution, with what this run drew
    when that differs (a TAO-fitted prior), every platform leaf marked assumed (`elsewhere`: the platform files given by a path outside platforms/)."""
    items = []
    used = run_priors(run)
    fit = (_json(run / "ingest" / "env_sigmas_fitted.json") if run else None) or {}               # the TAO fit Context.env feeds back as the tagged sigmas
    for k, e in (config.read_yaml(root / "config" / "assumptions.yaml") or {}).items():
        got = fit.get(k.removeprefix("env.sigma.")) if k.startswith("env.sigma.") else None
        items.append(dict(id=f"assumptions.yaml:{k}", file="config/assumptions.yaml", kind="assumed" if got is None else "fitted",
                          value=repr(e.get("value")) if got is None else f"this run used {got:.3g} (fitted from the TAO comparison); "
                                                                         f"assumed {e.get('value')!r}",
                          unit=str(e.get("unit", "")), why=str(e.get("why", "")), replace_with=str(e.get("replace_with", ""))))
    for k, e in (config.read_yaml(root / "config" / "perturbations.yaml") or {}).items():
        assumed = e.get("kind") == "assumed" or "ASSUMED" in str(e.get("citation", ""))
        txt = dist_text(e)
        sampled = e.get("dist") in ("normal", "lognormal", "uniform")           # a fixed setting is not in the ensemble's priors
        if k in used and sampled and sampling.to_marginals({k: e}, [k])[k] != used[k]:
            txt += f"; this run drew {_used(used[k])} (fitted)"
        items.append(dict(id=f"perturbations.yaml:{k}", file="config/perturbations.yaml", kind="assumed" if assumed else "prior",
                          value=txt, unit=str(e.get("unit", "")), why=str(e.get("citation", "")), replace_with=""))
    for it in platform_items(root, elsewhere):
        if it["assumed"]:
            items.append(dict(id=f"{it['file'].split('/')[-1]}:{it['path']}", file=it["file"], key=it["key"], kind="assumed", value=it["value"],
                              unit=it["unit"], why=it["why"], replace_with=""))
    for i, it in enumerate(items):
        it["anchor"] = f"A{i}"
    return items


# ------------------------------------------------------------------------------------------------------ V&V 20 rows

def _row(rid: str, case: str, source: str, S: float | None, D: float | None, u: tuple[float, float, float] | None, note: str) -> dict[str, Any]:
    """One V&V 20 row. u = (u_num, u_input, u_D) or None when the run stored no uncertainty terms."""
    r: dict[str, Any] = dict(id=rid, case=case, source=source, status="run" if S is not None else "not run", S=S, D=D, E=None, u_num=None, u_input=None,
                             u_D=None, u_val=None, ratio=None, validated=None, u_frac=None, informative=None, note=note)
    if S is not None and D is not None:
        r["E"] = S - D
    if S is not None and u is not None:
        r["u_num"], r["u_input"], r["u_D"] = u
        r["u_val"] = math.sqrt(sum(x * x for x in u))
        r["ratio"] = abs(r["E"]) / r["u_val"] if r["u_val"] > 0 else (0.0 if r["E"] == 0 else math.inf)
        r["validated"] = r["ratio"] <= 1.0
        r["u_frac"] = r["u_val"] / abs(D) if D else math.inf                           # an uncertainty as large as the reference cannot validate it
        r["informative"] = r["u_frac"] < UVAL_MAX_FRAC
    return r


def _dtmb_rows(data: pathlib.Path) -> list[dict[str, Any]]:
    try:
        from . import dtmb5415
    except ImportError as e:
        return [_row("dtmb5415", "DTMB 5415 C_T", "cafe/pm/dtmb5415.py", None, None, None, f"not run: cafe.pm.dtmb5415 cannot be imported ({e})")]
    root = data / "dtmb5415"
    rows, notes = dtmb5415.tabulate(root), dtmb5415.row_notes(root)
    why = "; ".join(dtmb5415.stale_notes(root))                                # files tabulate skips (another recipe, or unreadable): this says why
    out = []
    for fr in dtmb5415.CT_REF:
        src = f"{root}/run_coarse.json + run_fine.json"
        if fr in rows:
            r = rows[fr]
            nt = notes[fr]
            fine = next(iter(nt["grids"].values()))
            row = _row(f"dtmb5415:Fr{fr:.2f}", f"DTMB 5415 C_T at Fr {fr:.2f} (INSEAN 2340)", src, r.S, r.D, (r.u_num, r.u_input, r.u_D),
                       "U_D and U_input are assumed (config/assumptions.yaml dtmb5415.*); the free surface is held at the static draft; "
                       f"discretization: {nt['note']}")                      # round 7, M-5: the grid sequence's own note
            if fine["reasons"]:                                                      # round 8, M-10: not True is not converged; the note names the causes
                row["note"] += f"; finest grid not converged ({'; '.join(fine['reasons'])})"
                row["validated"], row["not_judged"] = None, "not judged: the finest grid has not converged"
            out.append(row)
        else:
            out.append(_row(f"dtmb5415:Fr{fr:.2f}", f"DTMB 5415 C_T at Fr {fr:.2f} (INSEAN 2340)", src, None, None, None,
                            f"not run: {why}" if why else f"not run: no coarse+fine run for this speed under {root}"))
    return out


def _stored(f: pathlib.Path, keys: tuple[str, ...], optional: tuple[str, ...] = ()) -> tuple[dict[str, Any] | None, str]:
    """(the stored receipt, "") when `f` is a JSON object whose `keys` (and the `optional` ones that are present) are finite real numbers (not bool, str,
    None); else (None, why it cannot be a row).
    A missing file is (None, "not stored"). A tolerant read for the report side: stage 3 judges the same files in wallmodel._read_receipt and a row here
    must never raise on a hand-edited or older file (round 9, M-4)."""
    if not f.is_file():
        return None, "not stored"
    try:
        d = config.json_object(f)
    except config.ConfigError:
        return None, f"{f.name} is unreadable (rerun it)"
    bad = config.missing_numbers(d, keys, optional)                                     # the rule of lbm.read_stored (stage 3's reader of the same files)
    return (None, f"{f.name} lacks a finite number for {', '.join(bad)} (rerun it)") if bad else (d, "")


def _refused(recs: list[tuple[str, dict[str, Any]]], plate: bool = False) -> str | None:
    """The phrase for the first of `recs` (file name, receipt already read) that stage 3 refuses to count (`config.stored_receipt_problem`, the gate's own
    rule: no code sha, another code's, or a plate below Re_L 1e6), else None. Stage 3 is imported only now: its physics sha is the cost of the check
    (round 9, DECISIONS 527)."""
    from .stage3 import lbm
    sha = lbm.physics_sha()
    return next((p for n, d in recs if (p := config.stored_receipt_problem(n, d, sha, plate))), None)


def _stored_rows(data: pathlib.Path) -> list[dict[str, Any]]:
    """Slow-run receipts stored by cafe.pm.stage3: S and D only. A receipt the stage-3 gate refuses (`_refused`) is a "not run" row with the gate's phrase.
    The sphere rows are read by the gate's own readers (`nest.stored_study` for the native grids, `lbm.result_row`'s two numbers for the XLB run): a file the
    gate leaves out or fails is never a row here (P-27, DECISIONS 528)."""
    rec = data / "receipts"
    out = []
    for kind, label in (("nest_sphere", "native LBM sphere Cd"), ("lbm_sphere", "XLB sphere Cd")):
        for tag, re_ in (("100", 100.0), ("1000", 1000.0), ("1e4", 1e4)):
            rid, case = f"{kind}:Re{tag}", f"{label} at Re = {re_:g} vs Morrison 2013"
            if kind == "nest_sphere":                         # one file per resolution, nest_sphere_<tag>_d<cells>.json: the finest the gate counts
                pattern, missing = f"nest_sphere_{tag}_d*.json", f"not run: no nest_sphere_{tag}_d*.json under {rec}"
                if not any(rec.glob(pattern)):
                    out.append(_row(rid, case, f"{rec / pattern}", None, None, None, missing))
                    continue
                from .stage3 import lbm, nest
                grids, bad = nest.stored_study(tag, rec)
                if not grids and not bad:                     # only a kept rerun (..._prev.json): no grid at all
                    out.append(_row(rid, case, f"{rec / pattern}", None, None, None, missing))
                    continue
                if not grids:
                    why = (_stored(bad[0], ("d", "cd"), ("seconds",))[1]
                           or f"{bad[0].name} is no grid of the study (it needs a positive d of its own and a text code_sha; rerun it)")
                    out.append(_row(rid, case, f"{bad[0]}", None, None, None, f"not run: {why}"))
                    continue
                f, d = grids[-1]
                if refused := _refused([(q.name, g) for q, g in grids]):           # the gate judges the whole study: one grid it refuses refuses the row
                    out.append(_row(rid, case, f"{f}", None, None, None, f"not run: {refused}"))
                    continue
                ref = float(lbm.morrison(re_))                # the gate compares the grids with Morrison, whatever a file says (nest.sphere_receipts)
                also = f" (d = {' and '.join(str(int(g['d'])) for _, g in grids[:-1])} also stored)" if len(grids) > 1 else ""
                left = f"; left out as the gate leaves them out: {', '.join(q.name for q in bad)}" if bad else ""
            else:
                f = rec / f"{kind}_{tag}.json"
                x, why = _stored(f, ("cd", "ref"))            # lbm.result_row fails a run without a number for either, so the page has no Morrison fallback
                if x is None:
                    note = f"{f.name} is not stored" if why == "not stored" else why
                    out.append(_row(rid, case, f"{f}", None, None, None, f"not run: {note}"))
                    continue
                if refused := _refused([(f.name, x)]):
                    out.append(_row(rid, case, f"{f}", None, None, None, f"not run: {refused}"))
                    continue
                d, ref, also, left = x, float(x["ref"]), "", ""
            out.append(_row(rid, case, f"{f}", float(d["cd"]), ref, None, f"d = {d.get('d', '?')} cells{also}; the run stores no U_num, U_input or U_D{left}"))
    plates = (("wm_flat_plate", "wall-modelled flat plate C_f vs ITTC-57", "ittc", config.PLATE_FIELDS),
              ("wm_channel", "wall-modelled channel C_f vs Dean 1978", "cf_dean", config.CHANNEL_FIELDS))
    for name, case, dk, fields in plates:
        f = rec / f"{name}.json"
        r, why = _stored(f, fields)                                              # every field stage 3 requires of the receipt, not only the two read here
        if r is not None:                                                        # the gate's rule: the current code's sha, a plate at Re_L 1e6 or more
            why = _refused([(f.name, r)], name == "wm_flat_plate") or why
            r = None if why else r
        if r is None:
            out.append(_row(f"wallmodel:{name}", case, f"{f}", None, None, None,
                            f"not run: {f.name} is not stored" if why == "not stored" else f"not run: {why}"))
        else:
            out.append(_row(f"wallmodel:{name}", case, f"{f}", float(r["cf"]), float(r[dk]), None, "the run stores no U_num, U_input or U_D"))
    return out


def vv20_rows(data: pathlib.Path | None = None) -> list[dict[str, Any]]:
    data = data or data_root()
    return _dtmb_rows(data) + _stored_rows(data)


# ------------------------------------------------------------------------------------------------------ the factor table

class Facts:
    """What the factor rules read, loaded once."""

    def __init__(self, run: pathlib.Path, root: pathlib.Path, data: pathlib.Path):
        self.run, self.root, self.data = run, root, data
        self.ledgers = {st: _json(run / "checkpoints" / st / "ledger.json") for st in STAGES}
        self.have = {st: d for st, d in self.ledgers.items() if d}
        self.mission = config.read_yaml(run / "mission.yaml") if (run / "mission.yaml").is_file() else None
        self.s1b = _json(run / "stage1b" / "summary.json")
        self.s1 = _json(run / "stage1" / "summary.json")
        self.refit = _json(run / "refit" / "refit.json") or {}
        self.problems = [p for p in ledger_problems(run) if "stage report" not in p and ": no ledger" not in p]
        self.refs = refs = {v["platform"] for v in (self.mission or {}).get("vehicles", [])}
        links = {lk["kind"] for lk in (self.mission or {}).get("links", [])}
        tables = ({"radios"} if "rf" in links else set()) | ({"modems"} if "acoustic" in links else set())
        self.used = {platform_key(r, root): platform_label(platform_key(r, root), platform_shipped(r, root)) for r in refs} | \
                    {t: platform_label(t, True) for t in tables}                                    # key -> the `file` of its items
        self.items = platform_items(root, [r for r in refs if not platform_shipped(r, root)])
        self.perts = config.read_yaml(root / "config" / "perturbations.yaml") or {}
        self.vv = vv20_rows(data)
        why = subgrid_uncalibrated(run, root)
        sub = [] if why is None else [dict(SUBGRID_LIMITATION, text=why)]
        self.limitations = LIMITATIONS[:12] + sub + LIMITATIONS[12:]                       # L13 sits between L12 and L14

    def ev(self, what: str, f: str) -> dict[str, Any]:
        return dict(file=f, what=what)

    def lg(self, st: str) -> str:
        return f"run:checkpoints/{st}/ledger.json"

    def ensembles(self) -> list[dict[str, Any]]:
        s = (self.s1b or {}).get("summary", {})
        return list(s.get("vehicles", {}).values()) + list(s.get("links", {}).values())

    def assumed_perts(self) -> list[str]:
        return [k for k, e in self.perts.items() if e.get("kind") == "assumed" or "ASSUMED" in str(e.get("citation", ""))]


def _data_pedigree(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    L = f.have.get("ingest")
    if not L or not L["inputs"]:
        return 0, [], ["no ingest ledger naming the WRF/UMWM inputs" if not L else "the ingest ledger lists no inputs"]
    ev, miss, lvl = [f.ev(f"{len(L['inputs'])} input(s) named: {L['inputs'][0]['ref']}", f.lg("ingest"))], [], 1
    schemas = [f.root / "cafe" / "schemas" / n for n in ("wrfout.json", "umwmout.json")]
    bad = [c["name"] for c in L["checks"] if not c["ok"]]
    ust = next((c for c in L["checks"] if c["name"] == "coare_ustar_vs_umwm_ust"), None)             # absent in ledgers from before round 8's reading of it
    agree = None if ust is None else ust.get("value")
    if not bad and ust is not None and not (isinstance(agree, (int, float)) and agree >= pipeline.USTAR_AGREE_FRACTION):
        got = f"only {pipeline.ustar_percent(agree)} %" if isinstance(agree, (int, float)) else "no fraction recorded for"
        miss.append(f"BRIEF 2.1 finding: {got} of the sea points have COARE u* within {100 * pipeline.USTAR_AGREE_BAND:.0f} % of UMWM ust; "
                    f"the brief asks {pipeline.USTAR_AGREE_FRACTION:.0%}, so the forcing is not shown to be consistent and the level stays at 1")
    elif not bad and L["checks"] and all(s.is_file() for s in schemas):
        lvl = 2
        ev.append(f.ev(f"{len(L['checks'])} ingest self-checks passed; schemas present", "cafe/schemas/wrfout.json, cafe/schemas/umwmout.json"))
    else:
        miss.append(f"ingest self-checks failed or absent ({bad or 'none recorded'}) or a schema file is missing")
    name = (f.mission or {}).get("name", "")
    tao = f.run / "ingest" / "tao_compare.json"
    pooled = (_json(tao) or {}).get("ALL") if tao.is_file() else None
    if not (lvl == 2 and name and pooled):
        miss.append(f"no TAO/TRITON wind and SST comparison with pooled numbers stored (looked for {tao}); the WRF winds and frozen SST are not checked "
                    "against buoys")
        return lvl, ev, miss
    sp, dr = float(pooled["speed_rmse"]), float(pooled["dir_rmse_deg"])
    n = len([k for k in _json(tao) if k != "ALL"])
    ev.append(f.ev(f"WRF compared with {n} TAO/TRITON moorings: wind speed RMSE {sp:.2f} m/s (bias {float(pooled['speed_bias']):+.2f}), direction RMSE "
                   f"{dr:.1f} deg (bias {float(pooled['dir_bias_deg']):+.1f}), SST bias {float(pooled.get('sst_bias', math.nan)):+.2f} K; the same comparison "
                   "fits the Stage-1 wind priors", str(tao)))
    if sp <= WIND_RMSE_LIMIT[0] and dr <= WIND_RMSE_LIMIT[1]:                       # (a NaN fails both)
        lvl = 3
    else:
        miss.append(f"the pooled wind error ({sp:.2f} m/s, {dr:.1f} deg) is above {WIND_RMSE_LIMIT[0]:g} m/s or {WIND_RMSE_LIMIT[1]:g} deg, the brief's "
                    "prior sd: agreement with the moorings is not shown, so the level stays at 2")
    return lvl, ev, miss


def _verification(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    if not f.have:
        return 0, [], ["no stage ledger in the run directory"]
    ev, miss, lvl = [f.ev(f"{len(f.have)} of {len(STAGES)} stage ledgers present", "run:checkpoints/")], [], 1
    tests = sorted((f.root / "tests").glob("test_*.py"))
    if not f.problems and tests:
        lvl = 2
        ev.append(f.ev(f"ledger chain audits clean; {len(tests)} test files present (their results are not read here)", "cafe/pm/audit.py, tests/"))
    else:
        miss.append(f"ledger problems: {f.problems[:3]}" if f.problems else "no test files in tests/")
    if lvl == 2 and any(r["status"] == "run" and r["u_num"] is not None for r in f.vv):
        lvl = 3
        ev.append(f.ev("a two-grid GCI sets U_num of a V&V 20 row", "cafe/pm/vv.py, cafe/pm/dtmb5415.py"))
        fb = [r["id"] for r in f.vv if r["status"] == "run" and "Fs = 3, p = 2 assumed" in r["note"]]
        if fb:                                                                  # round 7, M-5: the evidence is the fallback, not the three-grid GCI
            miss.append(f"{len(fb)} V&V 20 row(s) rest on the Fs = 3, p = 2 fallback (the grid sequence is not monotone, "
                        f"so the three-grid GCI was not used): {fb}")
    else:
        miss.append("no grid-convergence (GCI) study stored under the data directory: numerical error of the CFD is not estimated")
    return lvl, ev, miss


def _validation(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    ran = [r for r in f.vv if r["status"] == "run"]
    full = [r for r in ran if r["u_val"] is not None]
    miss = [f"not run: {r['case']}" + (f" ({r['note'].removeprefix('not run: ')})" if " recipe " in r["note"] else "") for r in f.vv if r["status"] != "run"]
    if not ran:
        return 0, [], ["no validation comparison has been run"] + miss
    unj = [r["id"] for r in full if r.get("not_judged")]                                    # round 7, M-5: a finest grid that has not converged judges nothing
    ev = [f.ev(f"{len(ran)} comparison(s) ran, {len(full)} with all uncertainty terms, {sum(bool(r['validated']) for r in full)} with |E| <= U_val, "
               f"{sum(bool(r['informative']) for r in full)} with U_val below {UVAL_MAX_FRAC:.0%} of the reference"
               + (f", {len(unj)} not judged (finest grid not converged)" if unj else ""), "credibility.json: vv20")]
    if not full:
        return 1, ev, ["no comparison stored U_num, U_input and U_D, so |E| <= U_val cannot be assessed"] + miss
    wide = [r["id"] for r in full if not r["informative"]]
    judged = [r for r in full if not r.get("not_judged")]
    if len(judged) >= 4 and all(r["validated"] for r in judged) and not wide:
        return 3, ev, miss
    why = ["fewer than four complete comparisons, or one with |E| > U_val"]
    if unj:
        why.append(f"{len(unj)} comparison(s) not judged because the finest grid has not converged, so not counted toward level 3: {unj}")
    if wide:
        why.append(f"U_val is {UVAL_MAX_FRAC:.0%} of the reference or more in {wide}: an uncertainty that wide cannot validate it")
    return 2, ev, why + miss


def _input_pedigree(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    its = [i for i in f.items if i["key"] in f.used and (i["assumed"] or i["sourced"])]
    if not its:
        return 0, [], ["no platform file with provenance fields is used by this mission (or mission.yaml is missing)"]
    good = sum(1 for i in its if i["sourced"] and not i["assumed"] and not i["recalled"])
    frac = good / len(its)
    ap = f.assumed_perts()
    ev = [f.ev(f"{good} of {len(its)} platform inputs sourced and not recalled ({frac:.0%}); {sum(i['assumed'] for i in its)} assumed, "
               f"{sum(i['recalled'] for i in its)} recalled", ", ".join(sorted(f.used.values())))]
    miss = [f"{len(its) - good} platform inputs are assumed or cited from memory (listed in this report)"]
    if ap:
        miss.append(f"perturbation prior(s) of kind assumed: {ap}")
    lvl = 3 if frac >= 0.8 and not ap else 2 if frac >= 0.5 else 1
    return lvl, ev, miss


def _uncertainty(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    ens = f.ensembles()
    if not ens:
        return 0, [], ["no stage-1b summary: no verdict intervals"]
    ev, miss, lvl = [f.ev(f"{len(ens)} verdicts with {ens[0]['verdict']['method']} intervals", "run:stage1b/summary.json")], [], 1
    copied = any("copied" in str(n) for n in (f.have.get("stage1b") or {}).get("notes", []))             # stage 1b is stage 1 when nothing was refit
    st = "stage1" if copied else "stage1b"                                                                  # the stage that ran the verdicts' ensemble
    lhs = [c for c in (f.have.get(st) or {}).get("checks", []) if c["name"].startswith("lhs_stratified")]
    if lhs and all(c["ok"] for c in lhs):
        lvl = 2
        ev.append(f.ev(f"{len(lhs)} Latin-hypercube stratification checks passed", f.lg(st)))
    else:
        miss.append(f"no passed Latin-hypercube stratification check in the {st} ledger" + (" (stage 1b is a copy of it)" if copied else ""))
    if any(e.get("cls") == "usv" for e in f.ensembles()):                          # round 7, M-15
        ev.append(f.ev(f"USV {usv_speed_sampling()}: the width of usv_vpp_bias is the published spread of VPP over-prediction, not an uncertainty "
                       "of this model; the stage-1b case usv_vpp_bias_brief is the sensitivity", "config/perturbations.yaml usv_vpp_bias"))
    # round 5, M-11: an ensemble whose 95 % Wilson lower bound on P(fail) is already 5 % or more excludes P(fail) < 5 %; no n certifies it, so it is not "short"
    # round 9, DECISIONS 526: nor is a link with the verdict NOT EXERCISED: no member count decides it (DECISIONS 477)
    short = [e["n"] for e in ens if e["verdict"]["verdict"] != NOT_EXERCISED and e["n"] < e["verdict"]["n_certify"]
             and intervals.wilson(e["k_fail"], e["n"], 0.95)[0] < 0.05]
    if lvl == 2 and not short and not f.assumed_perts():
        lvl = 3
    else:
        miss.append(f"{len(short)} verdict(s) have n below n_certify: P(fail) < 5 % cannot be certified there" if short else "")
        miss.append(f"perturbation prior(s) of kind assumed: {f.assumed_perts()}" if f.assumed_perts() else "")
    return lvl, ev, [m for m in miss if m]


def _robustness(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    ens = f.ensembles()
    if not ens:
        return 0, [], ["no stage-1b summary"]
    ev, miss, lvl = [f.ev(f"{len(ens)} ensembles", "run:stage1b/summary.json")], [], 1
    s = (f.s1b or {})["summary"]
    allv = {**s["vehicles"], **s["links"]}
    sens = [k for k, e in allv.items() if e["sensitivity"]["param"]]
    tests = sum(e["sensitivity"].get("noise_floor") is not None for e in allv.values())            # a permutation test each, at the 5 % level (stage1._summary)
    luck = sum(math.comb(tests, i) * 0.05 ** i * 0.95 ** (tests - i) for i in range(len(sens), tests + 1))      # P(at least this many clear it by chance)
    clear = bool(sens) and tests >= len(sens) and luck < 0.05   # round 7, M-23: 1 of 3 tests clears by luck 14 % of the time; round 8, M-21: no floor, no test
    refit = [k for k, r in f.refit.items() if r.get("used")]
    if clear or refit:
        lvl = 2
        ev.append(f.ev(f"sensitivity indices for {sens}" + ("" if clear else " (none stands clearly above chance)") + f"; refit rerun for {refit}",
                       "run:stage1b/summary.json, run:refit/refit.json"))
    elif sens:
        ev.append(f.ev(f"sensitivity indices exist for {sens}; none stands clearly above chance ({len(sens)} of {tests} tests cleared the 95 % floor; "
                       f"{luck:.0%} chance of that many by luck)"
                       + ("; ranked parameters without a permutation floor are not counted" if tests < len(sens) else ""),
                       "run:stage1b/summary.json"))
        miss.append("the first-order sensitivities do not stand clearly above chance and no refit reran")
    else:
        miss.append("no first-order sensitivity (every ensemble is all-pass or all-fail, or n < 16) and no refit rerun")
    s1 = ((f.s1 or {}).get("summary") or {}).get("vehicles", {})
    changed = [k for k, e in s["vehicles"].items() if k in s1 and s1[k]["verdict"]["verdict"] != e["verdict"]["verdict"]]
    if lvl == 2 and refit and not changed:
        lvl = 3
        ev.append(f.ev("verdicts identical before and after the refit rerun", "run:stage1/summary.json, run:stage1b/summary.json"))
    else:
        if not refit:
            miss.append("no vehicle was refit, so verdict stability under refit was not tested")
        if changed:
            miss.append(f"verdicts changed by the refit: {changed}")
    return lvl, ev, miss


def _use_history(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    p = f.root / "docs" / "USE_HISTORY.md"
    if p.is_file():
        return 1, [f.ev("a use-history record exists (content is not machine-checked)", "docs/USE_HISTORY.md")], []
    return 0, [], ["no record of a prediction of this tool compared with a real campaign outcome (docs/USE_HISTORY.md does not exist)"]


def _ms_management(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    if not f.have:
        return 0, [], ["no stage ledger"]
    ev, miss, lvl = [f.ev(f"{len(f.have)} ledgers", "run:checkpoints/")], [], 1
    keys = all(d.get("git_sha") not in (None, "none") and d.get("config_hash") and d.get("versions") for d in f.have.values())
    seeds = bool((f.have.get("stage1") or {}).get("seeds"))
    if keys and seeds:
        lvl = 2
        ev.append(f.ev("git sha, config hash, versions in every ledger; stage-1 seeds recorded", "run:checkpoints/*/ledger.json"))
    else:
        miss.append("a ledger lacks a git sha (not run from a git checkout), config hash or versions, or the stage-1 seeds are not recorded")
    if lvl == 2 and not f.problems and (f.root / "docs" / "BUILDERS.md").is_file() and "[tool.ruff]" in (f.root / "pyproject.toml").read_text():
        lvl = 3
        ev.append(f.ev("ledger chain audits clean; house rules and ruff configured", "cafe/pm/audit.py, docs/BUILDERS.md, pyproject.toml"))
    else:
        miss.append(f"ledger audit problems: {f.problems[:3]}" if f.problems else "")
    return lvl, ev, [m for m in miss if m]


def _people(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    p = f.root / "docs" / "QUALIFICATIONS.md"
    if p.is_file():
        return 1, [f.ev("a qualifications record exists (content is not machine-checked)", "docs/QUALIFICATIONS.md")], []
    return 0, [], ["nothing records who ran or reviewed this (docs/QUALIFICATIONS.md does not exist)"]


SCORERS = dict(data_pedigree=_data_pedigree, verification=_verification, validation=_validation, input_pedigree=_input_pedigree, uncertainty=_uncertainty,
               robustness=_robustness, use_history=_use_history, ms_management=_ms_management, people=_people)


def factor_table(f: Facts) -> list[dict[str, Any]]:
    out = []
    for key, name in FACTORS:
        lvl, ev, miss = SCORERS[key](f)
        lim = [x["id"] for x in f.limitations if key in x["factors"]]
        capped = min(lvl, 2) if lim else lvl
        out.append(dict(factor=key, name=name, level=capped, evidence_level=lvl, capped_by=lim if capped < lvl else [], limitations=lim, rule=RULES[key],
                        level_text=LEVEL_TEXT.get(key, {}).get(capped, LEVELS[capped]), evidence=ev, missing=miss))
    return out


NOT_EXERCISED_DETAIL = "the link was required at no moment in any member, so the run says nothing about it (verdict NOT EXERCISED)"


def _far(e: dict[str, Any]) -> bool | None:
    """Whether a link's median distance to the ship is beyond ACOUSTIC_NEAR_KM: from the summary's `distance_km_median`, else from the share of the needed
    samples that are out of the modem's range (more than half of them: the median distance is beyond the range, which is longer than 3 km); None if neither."""
    d = e.get("distance_km_median")
    if d is not None:
        return bool(d > ACOUSTIC_NEAR_KM)
    out = e.get("frac_out_of_range")
    return True if out is not None and out > 0.5 else None


def sanity(f: Facts) -> dict[str, Any] | None:
    """The verdicts of the run against what BRIEF section 6 expects of the demo mission, or None for any other mission. A row with `distance` set
    (an acoustic link) agrees when the link is NO-GO beyond ACOUSTIC_NEAR_KM of the ship and GO within it; None only when the run holds no distance."""
    name = (f.mission or {}).get("name", "")
    exp = EXPECTED.get(name)
    if exp is None or not f.s1b:
        return None
    ens = {**f.s1b["summary"]["vehicles"], **f.s1b["summary"]["links"]}
    rows = []
    for k, x in exp.items():
        if k not in ens:
            continue
        e, v = ens[k], ens[k]["verdict"]["verdict"]
        far = _far(e) if x.get("distance") else None
        agrees = v in x["allowed"] if x["allowed"] is not None else None if far is None else v == ("NO-GO" if far else "GO")
        detail = ""
        if next((u.get("task", {}).get("mode") for u in (f.mission or {}).get("vehicles", []) if u["id"] == k), None) == "drift":
            agrees, detail = None, DRIFT_DETAIL                      # a drift glider swims a fixed heading: its GO is not agreement with the expectation
        if v == NOT_EXERCISED:                                    # no moment required the link: neither agreement nor disagreement
            agrees, detail = None, NOT_EXERCISED_DETAIL
        elif x.get("distance"):
            d = e.get("distance_km_median")
            detail = ("the run holds no ship distance for this link" if far is None else
                      f"median distance to the ship {d:.0f} km" if d is not None else "most needed samples are out of the modem's range"
                      ) + (f", beyond {ACOUSTIC_NEAR_KM:g} km" if far else f", within {ACOUSTIC_NEAR_KM:g} km" if far is False else "")
        if k == "usv" and (e.get("speed") or {}).get("ratio_median") is not None:
            sp = e["speed"]
            shown = (f"speed over ground / mean wind at the anemometer height along the track {sp['ratio_anem_median']:.3f} (median of the per-member ratios; "
                     f"{sp['ratio_median']:.3f} on the 10 m wind)" if sp.get("ratio_anem_median") is not None else
                     f"speed over ground / mean 10 m wind along the track {sp['ratio_median']:.3f} (median of the per-member ratios; no ratio at the "
                     "anemometer height in this summary, so part of the gap is the difference of the wind heights)")
            detail = (f"{shown} against Chiodi et al.'s {USV_CHIODI_RATIO} (at the anemometer height): the calibration scenario differs from the "
                      "mission (no current, uniform wind, sailing to a station); the westward current lowers the mission ratio and the calibration may "
                      "already include part of that effect, a possible double penalty that is not established")
        rows.append(dict(id=k, expected=x["text"], allowed=x["allowed"], observed=v, k_fail=e["k_fail"], n=e["n"], agrees=agrees, detail=detail))
    return dict(mission=name, note=SANITY_NOTE, rows=rows)


# ------------------------------------------------------------------------------------------------------ HTML

CSS = """
:root{--bg:#fbfbfa;--fg:#1b1f23;--muted:#5c6670;--card:#fff;--line:#d5d9de;--go:#1a7f37;--nogo:#c4262e;--marg:#9a6700;--accent:#0b5cad;
--warn:#fff4d6;--warnfg:#5c4200;
--c0:#0b5cad;--c1:#b3541e;--c2:#2a7f62;--c3:#8250df;--c4:#bf3989;--c5:#57606a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1317;--fg:#e6e9ec;--muted:#9aa4ae;--card:#171c22;--line:#2d343c;
--go:#3fb950;--nogo:#ff7b72;
--marg:#e3b341;--accent:#58a6ff;--warn:#3a2f10;--warnfg:#f2d98a;--c0:#58a6ff;--c1:#ff9b5e;--c2:#56d4a8;--c3:#c297ff;--c4:#ff8fc8;--c5:#9aa4ae}}
:root[data-theme=dark]{--bg:#0f1317;--fg:#e6e9ec;--muted:#9aa4ae;--card:#171c22;--line:#2d343c;--go:#3fb950;--nogo:#ff7b72;--marg:#e3b341;
--accent:#58a6ff;
--warn:#3a2f10;--warnfg:#f2d98a;--c0:#58a6ff;--c1:#ff9b5e;--c2:#56d4a8;--c3:#c297ff;--c4:#ff8fc8;--c5:#9aa4ae}
pre{white-space:pre-wrap;overflow-wrap:anywhere}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}
main{max-width:64rem;margin:0 auto;padding:1rem}h1{font-size:1.5rem}h2{font-size:1.25rem;margin-top:2rem;
border-bottom:1px solid var(--line)}h3{font-size:1.05rem;margin:.2rem 0}
a{color:var(--accent)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:.75rem 1rem;margin:.75rem 0}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{border-bottom:1px solid var(--line);
padding:.3rem .5rem;text-align:left;vertical-align:top}
.badge{display:inline-block;padding:0 .5rem;border-radius:4px;border:2px solid currentColor;font-weight:700}.go{color:var(--go)}
.nogo{color:var(--nogo)}.marginal{color:var(--marg)}.undecided,.notexercised{color:var(--muted)}
.warn{background:var(--warn);color:var(--warnfg);border-radius:6px;padding:.5rem .75rem;margin:.5rem 0}.big{font-size:1.1rem;font-weight:700}
.muted{color:var(--muted)}.lk{font-size:.7rem;vertical-align:super;margin-left:.15rem;text-decoration:none}code{word-break:break-all}
svg{width:100%;height:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}svg text{fill:var(--fg);font-size:11px}
.box{fill:none;stroke:var(--muted);stroke-dasharray:4 3}.trk{fill:none;stroke-width:2}.mem{fill:none;stroke-width:1;opacity:.55}
.memfail{stroke-dasharray:3 2}
.s0{stroke:var(--c0);fill:var(--c0)}.s1{stroke:var(--c1);fill:var(--c1)}.s2{stroke:var(--c2);fill:var(--c2)}.s3{stroke:var(--c3);
fill:var(--c3)}.s4{stroke:var(--c4);fill:var(--c4)}
.s5{stroke:var(--c5);fill:var(--c5)}.win{fill:none;stroke-width:2}.ship{fill:var(--fg);stroke:none}
@media (max-width:40rem){main{padding:.5rem}th,td{padding:.25rem}}
"""


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(title)}</title><style>{CSS}</style></head><body><main>{body}</main></body></html>')


def _g(x: Any) -> str:
    return "n/a" if x is None else f"{x:.4g}" if isinstance(x, float) else str(x)


def _render(c: dict[str, Any]) -> str:
    e = html.escape
    h = [f"<h1>Credibility report</h1><p class=muted>{e(c['note'])}</p><p><a href='index.html'>Back to the mission report</a></p>"]
    h.append("<h2 id=factors>NASA-STD-7009B credibility factors</h2><div class=scroll><table>"
             "<tr><th>Factor<th>Level<th>Evidence (file)<th>Missing<th>Rule</tr>")
    for r in c["factors"]:
        ev = "<br>".join(f"{e(x['what'])} <code>{e(x['file'])}</code>" for x in r["evidence"]) or "none"
        lim = f"<br>capped at 2 by {', '.join(r['capped_by'])}" if r["capped_by"] else ""
        h.append(f"<tr><td>{e(r['name'])}<td><b>{r['level']}</b> of 4{lim}<br><span class=muted>{e(r['level_text'])}</span><td>{ev}"
                 f"<td>{'<br>'.join(e(m) for m in r['missing']) or 'nothing recorded as missing'}<td>{e(r['rule'])}</tr>")
    h.append("</table></div><h2 id=vv20>ASME V&amp;V 20 comparisons</h2><p class=muted>E = S &minus; D; U_val = sqrt(U_num&sup2; + U_input&sup2; + U_D&sup2;); "
             "validation is reported, not pass/fail.</p><div class=scroll><table><tr><th>Comparison<th>Status<th>S<th>D<th>E<th>U_num<th>U_input<th>U_D"
             "<th>U_val<th>|E| &le; U_val<br><span class=muted>counts toward Validation 3 if U_val / D &lt; 0.5 (credibility); "
             "the DTMB receipts require &le; 0.10</span><th>Note</tr>")
    for r in c["vv20"]:
        ok = (r["not_judged"] if r.get("not_judged") else "not assessable (U_val not stored)" if r["validated"] is None else ("yes" if r["validated"] else "no")
              + ("" if r["informative"] else f" (U_val is {r['u_frac']:.0%} of the reference: too wide to validate it)"))
        cells = "".join(f"<td>{_g(r[k])}" for k in ("S", "D", "E", "u_num", "u_input", "u_D", "u_val"))
        h.append(f"<tr id='vv-{e(r['id'])}'><td>{e(r['case'])}<td>{e(r['status'])}" + cells
                 + f"<td>{ok if r['status'] == 'run' else 'n/a'}<td>{e(r['note'])}</tr>")
    h.append("</table></div><h2 id=limitations>Known limitations</h2><ul>")
    for x in c["limitations"]:
        h.append(f"<li id='{x['id']}'><b>{x['id']}</b> {e(x['text'])} <span class=muted>bears on: {e(', '.join(x['factors']))}; see "
                 f"{', '.join('<code>' + e(w) + '</code>' for w in x['where'])}</span>")
    h.append("</ul>")
    if c.get("sanity"):
        sn = c["sanity"]
        h.append(f"<h2 id=sanity>Sanity check against the brief ({e(sn['mission'])} only)</h2><p class=muted>{e(sn['note'])}</p><div class=scroll><table>"
                 "<tr><th>Vehicle or link<th>Brief expects<th>This run<th>Failed<th>Agrees</tr>")
        for r in sn["rows"]:
            ag = "cannot be checked from the verdict" if r["agrees"] is None else "yes" if r["agrees"] else "<b>NO</b>"
            h.append(f"<tr><td>{e(r['id'])}<td>{e(r['expected'])}<td>{e(r['observed'])}<td>{r['k_fail']} of {r['n']}<td>{ag}"
                     f"{'<br><span class=muted>' + e(r['detail']) + '</span>' if r['detail'] else ''}</tr>")
        h.append("</table></div>")
    h.append("<h2 id=assumed>Assumed inputs and priors</h2><p class=muted>Every assumptions.yaml key, every perturbation prior, "
             "every platform input marked assumed. "
             "A verdict that depends on one carries the assumed badge in the mission report.</p>")
    for file in sorted({i["file"] for i in c["assumed_inputs"]}):
        key = next((x["key"] for x in c["assumed_inputs"] if x["file"] == file and "key" in x), pathlib.Path(file).stem)
        h.append(f"<h3 id='{e(plat_anchor(key))}'>{e(file)}</h3><div class=scroll><table><tr><th>Input<th>Kind<th>Value<th>Why<th>Replace with</tr>")
        for i in (x for x in c["assumed_inputs"] if x["file"] == file):
            h.append(f"<tr id='{i['anchor']}'><td><code>{e(i['id'])}</code><td>{e(i['kind'])}<td>{e(i['value'])} {e(i['unit'])}"
                     f"<td>{e(i['why'])}<td>{e(i['replace_with'])}</tr>")
        h.append("</table></div>")
    return "".join(h)


# ------------------------------------------------------------------------------------------------------ entry point

def build(run_dir: str | pathlib.Path, root: pathlib.Path = ROOT, data: pathlib.Path | None = None) -> dict[str, Any]:
    f = Facts(pathlib.Path(run_dir), root, data or data_root())
    items = assumed_inputs(root, f.run, [r for r in f.refs if not platform_shipped(r, root)])
    labels = {p.stem: platform_label(p.stem, True) for p in (root / "platforms").glob("*.yaml")} | f.used          # key -> the `file` of its items
    return dict(schema="cafe.pm.credibility/1", run=f.run.name,
                note="Levels run 0-4 (BRIEF 5.4). The rule behind each level is this tool's reading of the factor, not the text of NASA-STD-7009B, "
                     "which was not re-read. Level 4 is never awarded automatically.",
                levels=LEVELS, factors=factor_table(f), vv20=f.vv, limitations=f.limitations, sanity=sanity(f), assumed_inputs=items,
                platform_assumed_counts={s: sum(1 for i in items if i["file"] == lab and i["kind"] == "assumed") for s, lab in sorted(labels.items())})


def _clean(x: Any) -> Any:
    """JSON without NaN or Infinity: non-finite floats become null."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def write(run_dir: str | pathlib.Path) -> list[pathlib.Path]:
    out = pathlib.Path(run_dir) / "report"
    out.mkdir(parents=True, exist_ok=True)
    c = build(run_dir)
    j, h = out / "credibility.json", out / "credibility.html"
    j.write_text(json.dumps(_clean(c), indent=1, allow_nan=False))
    h.write_text(page("Credibility report", _render(c)))
    return [h, j]
