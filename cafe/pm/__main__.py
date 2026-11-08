"""python -m cafe.pm <command>  (bin/run_premission is `python -m cafe.pm run`)

    run       --mission M --budget {ci,quick,4h,overnight} --gpus N [--gpu-mem-gb G] [--assume-gpu] [--out DIR] [--fresh] [--seed S] [--emulator-table FILE]
                                             the whole pipeline, resumable; --gpus N > 0 is refused when no GPU is visible (unless --assume-gpu)
    fetch     --mission M                    ingest only (orca + ocean into the cache); plans nothing, so it takes no --budget and works for any mission
    ingest-ocean --mission M --path DIR [--temperature-kind {in_situ,potential}] [--grid STEM]
                                             the lab's HYCOM (netCDF or archv .a/.b) -> the mission's ocean store (environment.ocean.path)
    validate  --mission M                    schema and cross-checks, nothing run
    plan      --mission M --budget B --gpus N [--gpu-mem-gb G] [--assume-gpu]   what the budget buys on this machine (a GPU that is not here is said so)
    whatif    --mission M [--run DIR] [--budget B] (--shift 48h | --move "1deg W" | --drop ID)... [--vehicle ID]...
                                             what if: emulator-first, Stage 1 at the budget (default quick) when it cannot answer
    hangar    --platform NAME                provenance check and the Stage-1 coefficients the platform implies
    audit     [RUN ...] [--code-only] [--ledgers-only]  the ledger/code/test audit (cafe.pm.audit)
    promote-calibration --run DIR            copy that run's stage3/subgrid_calibration.json into the tracked config/subgrid.json (a deliberate, committed act)
    report    --run DIR [--open]             re-render the report from a finished run; --open shows it in a browser when there is a display
    receipts  [--broken YAML] [--slow] [--only NAME,..] [--json OUT]   every receipt (app + pre-mission) as one table; see cafe/pm/receipts.py
    acceptance --mission M --gpus N --out DIR [--golden FILE] [--update-golden [--golden-mission NAME]] [--skip-overnight]
                                             BRIEF 5.3: quick + overnight (+ 4h), golden diff, reproducibility, broken config; see cafe/pm/acceptance.py
                                             (verdicts identical where decided; P(fail) by Newcombe's difference interval, Bonferroni 95 %)
"""
from __future__ import annotations

import argparse, os, pathlib, sys, webbrowser
from typing import Any

from . import acceptance, audit, budget, ledger, par, pipeline, report, stage1, whatif
from .config import ConfigError, ResourceError, damaged_run_files as _run_files, json_object as _json_object, load_mission, os_error_text
from .env.environment import OutsideData
from .stats import intervals


def _seed(text: str) -> int:
    """argparse type for --seed: a non-negative integer (numpy refuses a negative seed with a traceback)."""
    try:
        n = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if n < 0:
        raise argparse.ArgumentTypeError(f"{n} is negative: the seed must be 0 or more")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cafe.pm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "fetch", "validate", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--mission", required=True)
        if name in ("run", "plan"):
            p.add_argument("--budget", default="quick", choices=list(budget.BUDGET_S))
            p.add_argument("--gpus", type=int, default=0)
            p.add_argument("--gpu-mem-gb", type=float, default=None, help="device memory the planner sizes nests against (refuses over 85 %%); "
                           "default: nvidia-smi when --gpus > 0")
            p.add_argument("--assume-gpu", action="store_true", help="plan (or run) for --gpus N although no GPU is visible on this machine: the plan is a "
                           "projection from published benchmarks, and a run would execute its LES windows on the CPU")
        if name in ("run", "fetch"):
            p.add_argument("--out", default=None, help="run directory (default runs/<mission>/<budget>)")
            p.add_argument("--fresh", action="store_true", help="ignore existing checkpoints")
        if name == "run":
            p.add_argument("--seed", type=_seed, default=None, help="use this seed, not the mission's (kept in plan.json and mission.yaml; in the resume hash)")
            p.add_argument("--emulator-table", default=None, metavar="FILE",
                           help="the emulator's training table (default $CAFE_EMULATOR_TABLE, else $CAFE_DATA/emulator/train.parquet). The run trains on a "
                                "copy of it taken when the emulator stage starts (named in that stage's ledger with its sha256) and appends its own rows "
                                "afterwards, so a run's emulator depends only on the table it started from. To make runs comparable (acceptance, a "
                                "same-seed check), copy the table once and give every run its own copy of that file: runs that share a table "
                                "see each other's rows")
    p = sub.add_parser("ingest-ocean", help="the lab's HYCOM -> the ocean store the mission names (environment.ocean: {source: lab_hycom, path: ...})")
    p.add_argument("--mission", required=True)
    p.add_argument("--path", required=True, help="a per-snapshot .nc, a directory of them, an archv .a/.b file or stem, or a directory of archv files")
    p.add_argument("--temperature-kind", default=None, choices=["in_situ", "potential"],
                   help="what the files' temperature is; required unless the mission or every netCDF says it (never guessed)")
    p.add_argument("--grid", default=None, help="archv only: the regional.grid stem (default: next to the files)")
    p = sub.add_parser("promote-calibration", help="copy a run's sub-grid calibration into config/subgrid.json, "
                       "recording the run's path, the date and its ledger digest")
    p.add_argument("--run", required=True)
    p = sub.add_parser("report")
    p.add_argument("--run", required=True)
    p.add_argument("--open", action="store_true", help="open the report in a browser when there is a display, else just print its path")
    p = sub.add_parser("whatif")
    p.add_argument("--mission", required=True)
    p.add_argument("--run", default=None, help="a finished run of this mission: its stage-1b results are the baseline (default runs/<mission>/<budget>)")
    p.add_argument("--budget", default="quick", choices=list(budget.BUDGET_S), help="size of the Stage-1 fallback")
    p.add_argument("--gpus", type=int, default=0)
    p.add_argument("--shift", action="append", default=[], help="deploy later by e.g. 48h, 2d; earlier as --shift=-6h; a UAS: sorties later in the day")
    p.add_argument("--move", action="append", default=[], help="move by e.g. '1deg W', '0.5deg north' (a UAS moves with its ship)")
    p.add_argument("--drop", action="append", default=[], help="a vehicle id to leave out")
    p.add_argument("--vehicle", action="append", default=None, help="apply --shift and --move to this vehicle only (repeatable; default all)")
    p = sub.add_parser("hangar")
    p.add_argument("--platform", required=True)
    p = sub.add_parser("audit")
    p.add_argument("runs", nargs="*")
    p.add_argument("--code-only", action="store_true")
    p.add_argument("--ledgers-only", action="store_true")
    p = sub.add_parser("receipts")
    p.add_argument("--broken", default=None, help="overlay yaml to apply; the exit code is 0 only if it makes a receipt fail")
    p.add_argument("--slow", action="store_true", help="also run the slow receipts instead of reading their stored results")
    p.add_argument("--only", default=None, help="comma-separated parts of receipt-group names to run; the table goes to runs/receipts_partial.json "
                                         "(not receipts.json) unless --json says otherwise, and a part that matches no group exits 2")
    p.add_argument("--json", default=None, help="where to write the table (default runs/receipts.json, runs/receipts_broken.json with --broken)")
    p = sub.add_parser("acceptance", description=(
        "BRIEF 5.3 gates. Two independent runs agree when every verdict that is decided in either (its 95 % P(fail) interval wholly inside GO or "
        "NO-GO) is identical, and Newcombe's interval for the P(fail) difference contains 0 at a family-wise 95 % (Bonferroni over the vehicles "
        "and links). A verdict that changes while undecided in both is allowed and named only while the two runs' 95 % P(fail) "
        "intervals overlap. A link whose verdict changes to or from NOT EXERCISED (required at no moment in any member) is always a problem. "
        "The same-seed check is exact equality."))
    p.add_argument("--mission", required=True)
    p.add_argument("--gpus", type=int, default=0)
    p.add_argument("--out", required=True, help="where the runs, receipts and acceptance.json go (each run in its own subdirectory, removed first; "
                                                 "a directory that holds runs acceptance did not make is refused)")
    p.add_argument("--golden", default=str(acceptance.GOLDEN))
    p.add_argument("--update-golden", action="store_true", help="write the golden from the quick run; that check then fails until it is rerun without this. "
                   "A golden file of another mission (or a file that is no golden) is not overwritten unless --golden-mission NAME names this run's mission "
                   "(round 12, M-33)")
    p.add_argument("--golden-mission", default=None, metavar="NAME", help="with --update-golden: let this run's mission NAME replace a golden of another "
                   "mission, or a file that is not a golden (round 12, M-33)")
    p.add_argument("--skip-overnight", action="store_true", help="rehearsal only: the overnight check fails ('not run')")
    a = ap.parse_args(argv)
    try:
        pipeline._offline()                                              # round 12, M-22: a bad CAFE_OFFLINE is exit 2 now, not only when a download is due
        if a.cmd == "acceptance":
            return acceptance.main(a)
        if a.cmd == "receipts":
            from . import receipts
            return receipts.run(a.slow, a.only.split(",") if a.only else None, a.broken, a.json)[1]
        if a.cmd == "audit":
            return audit.main(a.runs + (["--code-only"] if a.code_only else []) + (["--ledgers-only"] if a.ledgers_only else []))
        if a.cmd == "hangar":
            return _hangar(a.platform)
        if a.cmd == "promote-calibration":
            from .env import subgrid
            try:
                cal = subgrid.promote_calibration(a.run)
            except ValueError as e:
                raise ConfigError(str(e)) from e
            print(f"config/subgrid.json calibration.source_run: {cal['source_run']}; review the diff and commit it")
            return 0
        if a.cmd == "ingest-ocean":
            return _ingest_ocean(a)
        if a.cmd == "whatif":
            return _whatif(a)
        if a.cmd == "validate":
            m = load_mission(a.mission)
            nv, nl = len(m["vehicles"]), len(m["links"])
            print(f"{a.mission}: valid ({nv} vehicle{'s' * (nv != 1)}, {nl} link{'s' * (nl != 1)})")
            go = round(1 - intervals.P_FAIL_GO, 12)
            if go > 0.75:                                                  # round 8, M-7: the interval term stays at 0.75, so it is looser than 1 - go
                n0 = next(n for n in range(1, 100_000) if intervals.verdict(0, n)["verdict"] == "GO")
                print(f"note: verdict.go {go:g}: GO needs the point estimate of P(success) >= {go:g} and the 90 % Wilson lower bound on success >= "
                      f"{intervals.LO_SUCCESS_GO:g} (DECISIONS 68), so {n0} members without a failure are GO; the stopper uses the 95 % bound against "
                      f"{1 - go:.3g}", file=sys.stderr)
        elif a.cmd == "plan":
            m = load_mission(a.mission)
            if a.gpus > 0 and not a.assume_gpu and not pipeline.gpu_visible():
                print(f"no GPU found on this machine: the {a.gpus} GPU(s) below are projected from published benchmarks, not measured")
            mem = par.memory_gb()                                                     # the memory model of `run` (round 5, M-6)
            print(budget.describe(budget.plan(a.budget, a.gpus, m, gpu_mem_gb=_gpu_mem(a), vehicle_classes=stage1._classes(m), mem_gb=mem,
                                              env_gb=None if mem is None else budget.env_gb(m, pipeline.DATA / "cache" / m["name"]))))
            if warn := budget.machine_warning():                                      # not in the plan: it differs between machines (budget.machine_warning)
                print(f"note: {warn}")
        elif a.cmd in ("run", "fetch"):
            m = load_mission(a.mission)
            if getattr(a, "gpus", 0) > 0 and not a.assume_gpu and not pipeline.gpu_visible():
                raise ConfigError(f"--gpus {a.gpus} but no GPU is visible (did the docker run get --gpus all?); use --gpus 0 or pass --assume-gpu "
                                  "to plan for one that will be there")
            bud = getattr(a, "budget", "quick")
            out = pathlib.Path(a.out or f"runs/{m['name']}/{bud}")
            ctx = pipeline.run(a.mission, bud, getattr(a, "gpus", 0), out, resume=not a.fresh, stop_after="ingest" if a.cmd == "fetch" else None,
                               seed=getattr(a, "seed", None), emulator_table=getattr(a, "emulator_table", None), gpu_mem_gb=_gpu_mem(a))
            if a.cmd == "run":
                print(f"report: {ctx.run_dir / 'report' / 'index.html'}")
        else:
            return _report(pathlib.Path(a.run), a.open)
    except (ConfigError, budget.PlanError, ResourceError, OutsideData) as e:       # the last: the data does not cover the mission
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ledger.StageFailed as e:                                      # a stage's self-check failed: the message names it and the ledger has the detail
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:                                                 # round 10, M-5: a named path (--out, --run, ...) that cannot be made or read
        if not _names_a_path_given(e, a):
            raise                                                        # the program's own file (the emulator table's lock, a cache): a traceback, exit 1
        print(f"error: {os_error_text(e)}", file=sys.stderr)
        return 2
    return 0


DEFAULT_OUT = pathlib.Path("runs")                                       # where `run`, `whatif`, `report` and `receipts` write when no path is given


def _names_a_path_given(e: OSError, a: argparse.Namespace) -> bool:
    """True when the file `e` names is one of the paths on the command line (or lies under one, or under the default `runs/`): a bad input, exit 2. An
    OSError of a stage (the emulator table's `.lock`, a cache file) is not the user's to fix and keeps its traceback. A raise with no `filename` is
    not told apart, so the code that raises an OSError about a path it was given sets it."""
    values = [v for x in vars(a).values() for v in (x if isinstance(x, list) else [x])]
    given = [pathlib.Path(os.path.abspath(v)) for v in values if isinstance(v, (str, os.PathLike)) and str(v)] + [pathlib.Path(os.path.abspath(DEFAULT_OUT))]
    named = [pathlib.Path(os.path.abspath(f)) for f in (e.filename, e.filename2) if isinstance(f, (str, os.PathLike)) and str(f)]
    return any(g == n or g in n.parents for g in given for n in named)


def _gpu_mem(a: argparse.Namespace) -> float | None:
    """--gpu-mem-gb, else what nvidia-smi says when GPUs are asked for, else None (no memory to guard)."""
    given = getattr(a, "gpu_mem_gb", None)
    return given if given is not None else pipeline.gpu_memory_gb() if getattr(a, "gpus", 0) > 0 else None


def _report(run: pathlib.Path, open_it: bool) -> int:
    """Re-render a finished run's report; with the environment cache present the report also routes the reach map through its currents."""
    m = load_mission(run / "mission.yaml")
    if not (run / "plan.json").is_file():
        raise ConfigError(f"{run}: no plan.json; this is not a finished run directory (run `python -m cafe.pm run` first)")
    plan = _json_object(run / "plan.json")
    with _run_files(run):
        ctx = pipeline.Context(run / "mission.yaml", None, plan["gpus"], run, hash_budget=plan["budget"])         # no plan: no stage-1 memory model
        env = None
        if ctx.cache.is_dir():
            try:
                env = ctx.env
            except Exception as e:                                      # noqa: BLE001  a broken cache must not stop the report
                print(f"note: environment not loaded ({type(e).__name__}: {e}); no environment section or reach map", file=sys.stderr)
        paths = report.write(run, m, plan, env=env)
    for problem in _json_object(run / "report" / "report.json").get("ledger_problems", []):       # round 10, M-7: a warning, not a failure (DECISIONS 515)
        print(f"warning: {problem}", file=sys.stderr)
    bad = {k: v for k, v in report.self_checks(run).items() if v}                    # the stage's own checks on the new files, before they are recorded
    if bad:
        for k, v in bad.items():
            print(f"error: re-rendered report fails {k}: {'; '.join(v[:5])}", file=sys.stderr)
        print(f"error: the new files are in {run / 'report'} but the report ledger still records the old ones, so `audit` will say they changed; "
              "fix the cause and run `report --run` again, or rerun the report stage", file=sys.stderr)
        return 1
    with _run_files(run):                                                # the report ledger can be valid JSON of the wrong shape
        ledger.rerecord(run, "report", paths, ctx.code_digest)
    for p in paths:
        print(p)
    if open_it:
        shown = _has_display() and webbrowser.open(paths[0].resolve().as_uri())
        print(f"opened {paths[0]}" if shown else f"no display to open it on: {paths[0]}")
    return 0


def _has_display() -> bool:
    return sys.platform in ("darwin", "win32") or bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ingest_ocean(a: argparse.Namespace) -> int:
    """Write the lab's HYCOM into the store the mission names, cut to the mission's padded box."""
    from .env import hycom
    m = load_mission(a.mission)
    spec = m["environment"]["ocean"]
    if spec["source"] != "lab_hycom" or not spec.get("path"):
        raise ConfigError(f"{a.mission}: environment.ocean is {spec}; set it to {{source: lab_hycom, path: <where the store goes, e.g. "
                          f"/data/ocean/lab_{m['name']}.zarr>}} first")
    out = hycom.ingest_lab_hycom(a.path, pipeline.ocean_box(m), spec["path"], a.temperature_kind or spec.get("temperature_kind"), a.grid)
    print(f"ocean store: {out}")
    return 0


def _hangar(name: str) -> int:
    """Provenance check of one platform file and the numbers Stage 1 takes from it (what the pipeline's hangar stage records)."""
    from .config import TABLES, load_platform, table_provenance
    from .physics import glider, uas, usv
    raw = load_platform(name)
    kind = str(raw.get("kind", "")).lower()
    table = next((t for t in TABLES if t in raw and "kind" not in raw), None)             # radios.yaml / modems.yaml: a table of parts, not a vehicle
    cls: str = TABLES[table] if table else "uas" if "kind" not in raw else "usv" if "sail" in kind or "usv" in kind else "glider"
    loader: Any = None if table else {"uas": uas, "usv": usv, "glider": glider}[cls]
    try:
        if loader is not None:
            loader.load_platform(name)
        elif bad := table_provenance(raw):
            raise ValueError(f"table numbers without a source or an assumed+why: {bad}")
    except (ValueError, KeyError, TypeError, AttributeError) as e:  # as config._check_platform: a file of the wrong shape fails the check
        print(f"{name} ({cls}): provenance FAILED: {e if isinstance(e, ValueError) else f'{type(e).__name__}: {e}'}")
        return 1
    items = pipeline.provenance(raw, name)                                       # the items credibility.json counts (round 10, M-32)
    print(f"{name} ({cls}): provenance OK, {sum(i['assumed'] for i in items)} of {len(items)} items assumed")
    for i in items:
        why = "ASSUMED: " + i["why"] if i["assumed"] else "source: " + i["source"]
        print(f"  {i['path']} = {i['value']} {i['unit']}  [{why[:110]}]")
    return 0


def _model_note(finished: bool, fitted: bool, refit_file: bool) -> str | None:
    """Why a what-if baseline can differ from the P(fail) in the run's report: that is made with the TAO-fitted priors and the refit multipliers, and a
    what-if with no finished run, or with a run that lacks either file, uses perturbations.yaml as it stands (round 11, M-3). None when both were read.
    A run with no moorings legitimately has no priors_fitted.json."""
    files = ([] if fitted else ["priors_fitted.json"]) + ([] if refit_file else ["refit.json"])
    if not files:
        return None
    made = ([] if fitted else ["the TAO-fitted priors (the perturbations.yaml defaults stand)"]) + ([] if refit_file else ["the refit multipliers"])
    why = f"the run has no {' and no '.join(files)}" if finished else "there is no finished run"
    return f"note: this what-if is made without {' and '.join(made)} that the report's P(fail) uses ({why}), so a baseline can differ from it"


def _whatif(a: argparse.Namespace) -> int:
    m = load_mission(a.mission)
    if not (a.shift or a.move or a.drop):
        raise ConfigError("whatif needs at least one of --shift, --move, --drop")
    moves = [whatif.parse_move(x) for x in a.move]
    ops = dict(shift_h=sum(whatif.parse_shift(x) for x in a.shift), dlon=sum(d for d, _ in moves), dlat=sum(d for _, d in moves), drop=a.drop)
    run = pathlib.Path(a.run or f"runs/{m['name']}/{a.budget}")
    if (copy := run / "mission.yaml").is_file():                          # the mission the run was made from: a what-if compares a change with its verdicts
        old = load_mission(copy, set_verdict=False)
        diff = sorted(k for k in m.keys() | old.keys() if k not in ("seed", "_path") and m.get(k) != old.get(k))
        if diff:
            raise ConfigError(f"--mission {a.mission} is not the mission run {run} was made from (differs in: {', '.join(diff)}); what-if compares a change "
                              f"with that run's verdicts. Use `--mission {copy}`, or run the edited mission first")
        if m.get("seed") != old.get("seed"):
            print(f"note: the run used seed {old.get('seed')}, this file says {m.get('seed')}; the what-if draws use {m.get('seed')}")
    ctx = pipeline.Context(a.mission, a.budget, a.gpus, run)
    if not ctx.cache.is_dir():
        raise ConfigError(f"no environment cache at {ctx.cache}: run `python -m cafe.pm fetch --mission {a.mission}` first")
    base, tracks, scales, fitted = {}, {}, None, None
    with _run_files(run):
        if (run / "stage1b" / "summary.json").is_file():
            base = {k: v["verdict"] for k, v in _json_object(run / "stage1b" / "summary.json")["summary"]["vehicles"].items()}
            res, why = report._load_res(run, report.Trace(run))
            tracks = {k: whatif.track_points(r, m) for k, r in (res or {"vehicles": {}})["vehicles"].items() if r["class"] != "uas"}
            rf = run / "refit" / "refit.json"
            scales = {k: r for k, r in _json_object(rf).items() if r["used"]} if rf.is_file() else None
            pf = run / "ingest" / "priors_fitted.json"
            fitted = _json_object(pf) if pf.is_file() else None
            if res is None:
                print(f"note: {why}; every changed vehicle goes to Stage 1")
            if line := _model_note(True, pf.is_file(), rf.is_file()):
                print(line, file=sys.stderr)                 # stderr: the lines on stdout are the answer, which scripts read by position
        else:
            print(f"note: no finished run at {run}: the baseline and every changed vehicle are run in Stage 1 at the {a.budget} budget")
            print(_model_note(False, False, False), file=sys.stderr)
    ems = whatif.train(pipeline.emulator_table(), whatif.scopes(m))
    ans = whatif.answer(m, ops, base, tracks, ctx.env, ems, ctx.plan, fitted, scales, only=a.vehicle)
    what = [f"{ops['shift_h']:+g} h" if a.shift else "", f"{ops['dlon']:+g} deg lon, {ops['dlat']:+g} deg lat" if a.move else "",
            f"drop {', '.join(a.drop)}" if a.drop else ""]
    print(f"whatif {m['name']}: " + "; ".join(x for x in what if x))
    for vid, r in ans["vehicles"].items():
        if r["method"] == "EMULATED":
            how = f"EMULATED, training-set distance {r['distance']:.2f} of limit {r['threshold']:.2f}"
        elif r["method"] == "Stage 1":
            how = f"Stage 1, n = {r['n']} ({r['why']})"
        else:
            how = "unchanged"
        iv = f" ({r['lo']:.3f} to {r['hi']:.3f})" if "lo" in r else ""
        print(f"{vid}: {r['base']['verdict']} (P(fail) {r['base']['p_fail']:.3f}) -> {r['verdict']} (P(fail) {r['p_fail']:.3f}){iv}  [{how}]")
        if r.get("flight"):
            print(f"  note: {vid} {r['flight']}")
    for vid, why in ans.get("unchanged", {}).items():
        print(f"{vid}: unchanged ({why})")
    if ans["dropped"]:
        print(f"dropped {', '.join(ans['dropped'])}; links removed: {', '.join(ans['links_removed']) or 'none'}. "
              "Other vehicles are unaffected: Stage-1 vehicles do not interact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
