"""Credibility report (BRIEF 5.4): NASA-STD-7009B factor table, ASME V&V 20 table, assumed inputs, known limitations.

    write(run_dir) -> [run_dir/report/credibility.html, run_dir/report/credibility.json]

Every level is computed from files that exist: the run directory (ledgers, summaries, plan) and the repo (platforms/, config/,
tests/, docs/). Where evidence is missing the level is 0 and the cell says what is missing. Level 4 is never awarded: it needs
independent review or field evidence, which no file in this tool can show. The 0-4 scale is BRIEF 5.4's; the rule behind each
level below is this tool's own reading of the factor, not the wording of NASA-STD-7009B (the standard was not re-read), so
the report prints the rule next to every level. A known limitation that bears on a factor caps it at 2.

ASME V&V 20 (E = S - D, U_val = sqrt(U_num^2 + U_input^2 + U_D^2), |E| <= U_val): rows come from cafe.pm.dtmb5415.tabulate
(all four uncertainty terms) and from the stored slow-run receipts under $CAFE_DATA/receipts (S and D only: the runs store no
uncertainty terms, so they are listed with E and "U_val not stored", never as validated). A comparison that was not run is
listed as "not run" with the file that would hold it.
"""
from __future__ import annotations

import html
import json
import math
import os
import pathlib
from typing import Any

import yaml

from . import config
from .audit import STAGES, ledger_problems

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
]

FACTORS = [("data_pedigree", "Data pedigree"), ("verification", "Verification"), ("validation", "Validation"), ("input_pedigree", "Input pedigree"),
           ("uncertainty", "Uncertainty characterization"), ("robustness", "Results robustness"), ("use_history", "Use history"),
           ("ms_management", "M&S management"), ("people", "People qualifications")]

RULES = {
    "data_pedigree": "1 ingest ledger names its inputs; 2 and every ingest self-check passed and the wrfout/umwmout schemas exist; "
                     "3 and a TAO/TRITON comparison is stored for this mission.",
    "verification": "1 a stage ledger exists; 2 every ledger is clean (ok, no failed check, chain intact, hashes reproduce) and tests exist; "
                    "3 and a grid-convergence (GCI) study backs a V&V 20 row.",
    "validation": "1 a comparison with a reference ran; 2 and one has all of U_num, U_input, U_D; 3 and at least four such rows all satisfy |E| <= U_val.",
    "input_pedigree": "1 platform inputs carry provenance; 2 and at least half are sourced (not assumed, not recalled); "
                      "3 and at least 80 % are, and no perturbation prior is of kind assumed.",
    "uncertainty": "1 verdict intervals exist; 2 and the Latin-hypercube stratification checks passed; "
                   "3 and every vehicle and link has n >= n_certify and no perturbation prior is of kind assumed.",
    "robustness": "1 one ensemble ran; 2 and first-order sensitivities exist for a vehicle or link with both outcomes; "
                  "3 and a stage-3 refit reran stage 1 and no verdict changed.",
    "use_history": "1 only if docs/USE_HISTORY.md records a past prediction compared with a real outcome; otherwise 0.",
    "ms_management": "1 ledgers exist; 2 and every ledger carries a git sha, config hash, versions, and the stage-1 seeds; "
                     "3 and the ledger chain audits clean, docs/BUILDERS.md exists and ruff is configured.",
    "people": "1 only if docs/QUALIFICATIONS.md records who ran and reviewed this; otherwise 0.",
}


def data_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("CAFE_DATA", "/data"))


def _json(p: pathlib.Path) -> Any:
    return json.loads(p.read_text()) if p.is_file() else None


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


def platform_items(root: pathlib.Path = ROOT) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted((root / "platforms").glob("*.yaml")):
        _prov(yaml.safe_load(f.read_text()), "", f"platforms/{f.name}", out)
    return out


def assumed_inputs(root: pathlib.Path = ROOT) -> list[dict[str, Any]]:
    """The full list: every assumptions.yaml key, every perturbation prior (kind prior or assumed), every platform leaf marked assumed."""
    items = []
    for k, e in (yaml.safe_load((root / "config" / "assumptions.yaml").read_text()) or {}).items():
        items.append(dict(id=f"assumptions.yaml:{k}", file="config/assumptions.yaml", kind="assumed", value=repr(e.get("value")), unit=str(e.get("unit", "")),
                          why=str(e.get("why", "")), replace_with=str(e.get("replace_with", ""))))
    for k, e in (yaml.safe_load((root / "config" / "perturbations.yaml").read_text()) or {}).items():
        assumed = e.get("kind") == "assumed" or "ASSUMED" in str(e.get("citation", ""))
        items.append(dict(id=f"perturbations.yaml:{k}", file="config/perturbations.yaml", kind="assumed" if assumed else "prior",
                          value=repr(e.get("value")), unit=str(e.get("unit", "")), why=str(e.get("citation", "")), replace_with=""))
    for it in platform_items(root):
        if it["assumed"]:
            items.append(dict(id=f"{it['file'].split('/')[-1]}:{it['path']}", file=it["file"], kind="assumed", value=it["value"], unit=it["unit"],
                              why=it["why"], replace_with=""))
    for i, it in enumerate(items):
        it["anchor"] = f"A{i}"
    return items


# ------------------------------------------------------------------------------------------------------ V&V 20 rows

def _row(rid: str, case: str, source: str, S: float | None, D: float | None, u: tuple[float, float, float] | None, note: str) -> dict[str, Any]:
    """One V&V 20 row. u = (u_num, u_input, u_D) or None when the run stored no uncertainty terms."""
    r: dict[str, Any] = dict(id=rid, case=case, source=source, status="run" if S is not None else "not run", S=S, D=D, E=None, u_num=None, u_input=None,
                             u_D=None, u_val=None, ratio=None, validated=None, note=note)
    if S is not None and D is not None:
        r["E"] = S - D
    if S is not None and u is not None:
        r["u_num"], r["u_input"], r["u_D"] = u
        r["u_val"] = math.sqrt(sum(x * x for x in u))
        r["ratio"] = abs(r["E"]) / r["u_val"] if r["u_val"] > 0 else (0.0 if r["E"] == 0 else math.inf)
        r["validated"] = r["ratio"] <= 1.0
    return r


def _dtmb_rows(data: pathlib.Path) -> list[dict[str, Any]]:
    try:
        from . import dtmb5415
    except ImportError as e:
        return [_row("dtmb5415", "DTMB 5415 C_T", "cafe/pm/dtmb5415.py", None, None, None, f"not run: cafe.pm.dtmb5415 cannot be imported ({e})")]
    root = data / "dtmb5415"
    rows = dtmb5415.tabulate(root)
    out = []
    for fr in dtmb5415.CT_REF:
        src = f"{root}/run_coarse.json + run_fine.json"
        if fr in rows:
            r = rows[fr]
            out.append(_row(f"dtmb5415:Fr{fr:.2f}", f"DTMB 5415 C_T at Fr {fr:.2f} (INSEAN 2340)", src, r.S, r.D, (r.u_num, r.u_input, r.u_D),
                            "U_D and U_input are assumed (config/assumptions.yaml dtmb5415.*); the free surface is held at the static draft"))
        else:
            out.append(_row(f"dtmb5415:Fr{fr:.2f}", f"DTMB 5415 C_T at Fr {fr:.2f} (INSEAN 2340)", src, None, None, None,
                            f"not run: no coarse+fine run for this speed under {root}"))
    return out


def _stored_rows(data: pathlib.Path) -> list[dict[str, Any]]:
    """Slow-run receipts stored by cafe.pm.stage3: S and D only."""
    rec = data / "receipts"
    out = []
    morrison = None
    for kind, label in (("nest_sphere", "native LBM sphere Cd"), ("lbm_sphere", "XLB sphere Cd")):
        for tag, re in (("100", 100.0), ("1000", 1000.0), ("1e4", 1e4)):
            f = rec / f"{kind}_{tag}.json"
            rid, case = f"{kind}:Re{tag}", f"{label} at Re = {re:g} vs Morrison 2013"
            d = _json(f)
            if d is None:
                out.append(_row(rid, case, f"{f}", None, None, None, f"not run: {f.name} is not stored"))
                continue
            if "ref" in d:
                ref = float(d["ref"])
            else:
                from .stage3 import lbm
                morrison = morrison or lbm.morrison
                ref = float(morrison(re))
            out.append(_row(rid, case, f"{f}", float(d["cd"]), ref, None, f"d = {d.get('d', '?')} cells; the run stores no U_num, U_input or U_D"))
    plates = (("wm_flat_plate", "wall-modelled flat plate C_f vs ITTC-57", "ittc"), ("wm_channel", "wall-modelled channel C_f vs Dean 1978", "cf_dean"))
    for name, case, dk in plates:
        f = rec / f"{name}.json"
        d = _json(f)
        if d is None:
            out.append(_row(f"wallmodel:{name}", case, f"{f}", None, None, None, f"not run: {f.name} is not stored"))
        else:
            out.append(_row(f"wallmodel:{name}", case, f"{f}", float(d["cf"]), float(d[dk]), None, "the run stores no U_num, U_input or U_D"))
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
        self.mission = yaml.safe_load((run / "mission.yaml").read_text()) if (run / "mission.yaml").is_file() else None
        self.s1b = _json(run / "stage1b" / "summary.json")
        self.s1 = _json(run / "stage1" / "summary.json")
        self.refit = _json(run / "refit" / "refit.json") or {}
        self.problems = [p for p in ledger_problems(run) if "stage report" not in p and ": no ledger" not in p]
        used = {v["platform"] for v in (self.mission or {}).get("vehicles", [])}
        links = {lk["kind"] for lk in (self.mission or {}).get("links", [])}
        self.used = used | ({"radios"} if "rf" in links else set()) | ({"modems"} if "acoustic" in links else set())
        self.items = platform_items(root)
        self.perts = yaml.safe_load((root / "config" / "perturbations.yaml").read_text()) or {}
        self.vv = vv20_rows(data)

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
    if not bad and L["checks"] and all(s.is_file() for s in schemas):
        lvl = 2
        ev.append(f.ev(f"{len(L['checks'])} ingest self-checks passed; schemas present", "cafe/schemas/wrfout.json, cafe/schemas/umwmout.json"))
    else:
        miss.append(f"ingest self-checks failed or absent ({bad or 'none recorded'}) or a schema file is missing")
    name = (f.mission or {}).get("name", "")
    tao = f.run / "ingest" / "tao_compare.json"
    if lvl == 2 and name and tao.is_file():
        lvl = 3
        ev.append(f.ev("WRF wind and SST compared with TAO/TRITON moorings; the fitted wind errors are the Stage-1 priors", str(tao)))
    else:
        miss.append(f"no TAO/TRITON wind and SST comparison stored (looked for {tao}); the WRF winds and frozen SST are not checked against buoys")
    return lvl, ev, miss


def _verification(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    if not f.have:
        return 0, [], ["no stage ledger in the run directory"]
    ev, miss, lvl = [f.ev(f"{len(f.have)} of {len(STAGES)} stage ledgers present", "run:checkpoints/")], [], 1
    tests = sorted((f.root / "tests").glob("test_*.py"))
    if not f.problems and tests:
        lvl = 2
        ev.append(f.ev(f"ledger chain audits clean; {len(tests)} test files", "cafe/pm/audit.py, tests/"))
    else:
        miss.append(f"ledger problems: {f.problems[:3]}" if f.problems else "no test files in tests/")
    if lvl == 2 and any(r["status"] == "run" and r["u_num"] is not None for r in f.vv):
        lvl = 3
        ev.append(f.ev("a two-grid GCI sets U_num of a V&V 20 row", "cafe/pm/vv.py, cafe/pm/dtmb5415.py"))
    else:
        miss.append("no grid-convergence (GCI) study stored under the data directory: numerical error of the CFD is not estimated")
    return lvl, ev, miss


def _validation(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    ran = [r for r in f.vv if r["status"] == "run"]
    full = [r for r in ran if r["u_val"] is not None]
    miss = [f"not run: {r['case']}" for r in f.vv if r["status"] != "run"]
    if not ran:
        return 0, [], ["no validation comparison has been run"] + miss
    ev = [f.ev(f"{len(ran)} comparison(s) ran, {len(full)} with all uncertainty terms, {sum(bool(r['validated']) for r in full)} with |E| <= U_val",
               "credibility.json: vv20")]
    if not full:
        return 1, ev, ["no comparison stored U_num, U_input and U_D, so |E| <= U_val cannot be assessed"] + miss
    if len(full) >= 4 and all(r["validated"] for r in full):
        return 3, ev, miss
    return 2, ev, ["fewer than four complete comparisons, or one with |E| > U_val"] + miss


def _input_pedigree(f: Facts) -> tuple[int, list[dict[str, Any]], list[str]]:
    its = [i for i in f.items if pathlib.Path(i["file"]).stem in f.used and (i["assumed"] or i["sourced"])]
    if not its:
        return 0, [], ["no platform file with provenance fields is used by this mission (or mission.yaml is missing)"]
    good = sum(1 for i in its if i["sourced"] and not i["assumed"] and not i["recalled"])
    frac = good / len(its)
    ap = f.assumed_perts()
    ev = [f.ev(f"{good} of {len(its)} platform inputs sourced and not recalled ({frac:.0%}); {sum(i['assumed'] for i in its)} assumed, "
               f"{sum(i['recalled'] for i in its)} recalled", ", ".join(sorted(f"platforms/{u}.yaml" for u in f.used)))]
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
    lhs = [c for c in (f.have.get("stage1b") or {}).get("checks", []) if c["name"].startswith("lhs_stratified")]
    if lhs and all(c["ok"] for c in lhs):
        lvl = 2
        ev.append(f.ev(f"{len(lhs)} Latin-hypercube stratification checks passed", f.lg("stage1b")))
    else:
        miss.append("no passed Latin-hypercube stratification check in the stage-1b ledger (a copied stage 1b has none)")
    short = [e["n"] for e in ens if e["n"] < e["verdict"]["n_certify"]]
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
    sens = [k for k, e in {**s["vehicles"], **s["links"]}.items() if e["sensitivity"]["param"]]
    refit = [k for k, r in f.refit.items() if r.get("used")]
    if sens or refit:
        lvl = 2
        ev.append(f.ev(f"sensitivity indices for {sens}; refit rerun for {refit}", "run:stage1b/summary.json, run:refit/refit.json"))
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
        lim = [x["id"] for x in LIMITATIONS if key in x["factors"]]
        capped = min(lvl, 2) if lim else lvl
        out.append(dict(factor=key, name=name, level=capped, evidence_level=lvl, capped_by=lim if capped < lvl else [], limitations=lim, rule=RULES[key],
                        evidence=ev, missing=miss))
    return out


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
.nogo{color:var(--nogo)}.marginal{color:var(--marg)}.undecided{color:var(--muted)}
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
        h.append(f"<tr><td>{e(r['name'])}<td><b>{r['level']}</b> of 4{lim}<br><span class=muted>{e(LEVELS[r['level']])}</span><td>{ev}"
                 f"<td>{'<br>'.join(e(m) for m in r['missing']) or 'nothing recorded as missing'}<td>{e(r['rule'])}</tr>")
    h.append("</table></div><h2 id=vv20>ASME V&amp;V 20 comparisons</h2><p class=muted>E = S &minus; D; U_val = sqrt(U_num&sup2; + U_input&sup2; + U_D&sup2;); "
             "validation is reported, not pass/fail.</p><div class=scroll><table><tr><th>Comparison<th>Status<th>S<th>D<th>E<th>U_num<th>U_input<th>U_D"
             "<th>U_val<th>|E| &le; U_val<th>Note</tr>")
    for r in c["vv20"]:
        ok = "not assessable (U_val not stored)" if r["validated"] is None else "yes" if r["validated"] else "no"
        cells = "".join(f"<td>{_g(r[k])}" for k in ("S", "D", "E", "u_num", "u_input", "u_D", "u_val"))
        h.append(f"<tr id='vv-{e(r['id'])}'><td>{e(r['case'])}<td>{e(r['status'])}" + cells
                 + f"<td>{ok if r['status'] == 'run' else 'n/a'}<td>{e(r['note'])}</tr>")
    h.append("</table></div><h2 id=limitations>Known limitations</h2><ul>")
    for x in c["limitations"]:
        h.append(f"<li id='{x['id']}'><b>{x['id']}</b> {e(x['text'])} <span class=muted>bears on: {e(', '.join(x['factors']))}; see "
                 f"{', '.join('<code>' + e(w) + '</code>' for w in x['where'])}</span>")
    h.append("</ul><h2 id=assumed>Assumed inputs and priors</h2><p class=muted>Every assumptions.yaml key, every perturbation prior, "
             "every platform input marked assumed. "
             "A verdict that depends on one carries the assumed badge in the mission report.</p>")
    for file in sorted({i["file"] for i in c["assumed_inputs"]}):
        stem = pathlib.Path(file).stem
        h.append(f"<h3 id='plat-{e(stem)}'>{e(file)}</h3><div class=scroll><table><tr><th>Input<th>Kind<th>Value<th>Why<th>Replace with</tr>")
        for i in (x for x in c["assumed_inputs"] if x["file"] == file):
            h.append(f"<tr id='{i['anchor']}'><td><code>{e(i['id'])}</code><td>{e(i['kind'])}<td>{e(i['value'])} {e(i['unit'])}"
                     f"<td>{e(i['why'])}<td>{e(i['replace_with'])}</tr>")
        h.append("</table></div>")
    return "".join(h)


# ------------------------------------------------------------------------------------------------------ entry point

def build(run_dir: str | pathlib.Path, root: pathlib.Path = ROOT, data: pathlib.Path | None = None) -> dict[str, Any]:
    f = Facts(pathlib.Path(run_dir), root, data or data_root())
    items = assumed_inputs(root)
    return dict(schema="cafe.pm.credibility/1", run=f.run.name,
                note="Levels run 0-4 (BRIEF 5.4). The rule behind each level is this tool's reading of the factor, not the text of NASA-STD-7009B, "
                     "which was not re-read. Level 4 is never awarded automatically.",
                levels=LEVELS, factors=factor_table(f), vv20=f.vv, limitations=LIMITATIONS, assumed_inputs=items,
                platform_assumed_counts={s: sum(1 for i in items if i["file"] == f"platforms/{s}.yaml" and i["kind"] == "assumed")
                                         for s in sorted(p.stem for p in (root / "platforms").glob("*.yaml"))})


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
