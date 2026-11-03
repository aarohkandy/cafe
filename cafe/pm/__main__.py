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
    audit     [RUN ...] [--code-only]        the ledger/code/test audit (cafe.pm.audit)
    promote-calibration --run DIR            copy that run's stage3/subgrid_calibration.json into the tracked config/subgrid.json (a deliberate, committed act)
    report    --run DIR [--open]             re-render the report from a finished run; --open shows it in a browser when there is a display
    receipts  [--broken YAML] [--slow] [--only NAME,..] [--json OUT]   every receipt (app + pre-mission) as one table; see cafe/pm/receipts.py
    acceptance --mission M --gpus N --out DIR [--golden FILE] [--update-golden] [--skip-overnight]
                                             BRIEF 5.3: quick + overnight (+ 4h), golden diff, reproducibility, broken config; see cafe/pm/acceptance.py
                                             (verdicts identical where decided; P(fail) by Newcombe's difference interval, Bonferroni 95 %)
"""
from __future__ import annotations

import argparse, json, os, pathlib, sys, webbrowser
from typing import Any

from . import acceptance, audit, budget, ledger, pipeline, report, stage1, whatif
from .config import ConfigError, load_mission


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
    p = sub.add_parser("receipts")
    p.add_argument("--broken", default=None, help="overlay yaml to apply; the exit code is 0 only if it makes a receipt fail")
    p.add_argument("--slow", action="store_true", help="also run the slow receipts instead of reading their stored results")
    p.add_argument("--only", default=None, help="comma-separated parts of receipt-group names to run")
    p.add_argument("--json", default=None, help="where to write the table (default runs/receipts.json, runs/receipts_broken.json with --broken)")
    p = sub.add_parser("acceptance", description=(
        "BRIEF 5.3 gates. Two independent runs agree when every verdict that is decided in either (its 95 % P(fail) interval wholly inside GO or "
        "NO-GO) is identical, and Newcombe's interval for the P(fail) difference contains 0 at a family-wise 95 % (Bonferroni over the vehicles "
        "and links). A verdict that changes while undecided in both is allowed and named only while the two runs' 95 % P(fail) "
        "intervals overlap. The same-seed check is exact equality."))
    p.add_argument("--mission", required=True)
    p.add_argument("--gpus", type=int, default=0)
    p.add_argument("--out", required=True, help="where the runs, receipts and acceptance.json go (each run in its own subdirectory, removed first)")
    p.add_argument("--golden", default=str(acceptance.GOLDEN))
    p.add_argument("--update-golden", action="store_true", help="write the golden from the quick run; that check then fails until it is rerun without this")
    p.add_argument("--skip-overnight", action="store_true", help="rehearsal only: the overnight check fails ('not run')")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "acceptance":
            return acceptance.main(a)
        if a.cmd == "receipts":
            from . import receipts
            return receipts.run(a.slow, a.only.split(",") if a.only else None, a.broken, a.json)[1]
        if a.cmd == "audit":
            return audit.main(a.runs + (["--code-only"] if a.code_only else []))
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
            print(f"{a.mission}: valid ({len(m['vehicles'])} vehicles, {len(m['links'])} links)")
        elif a.cmd == "plan":
            m = load_mission(a.mission)
            if a.gpus > 0 and not a.assume_gpu and not pipeline.gpu_visible():
                print(f"no GPU found on this machine: the {a.gpus} GPU(s) below are projected from published benchmarks, not measured")
            print(budget.describe(budget.plan(a.budget, a.gpus, m, gpu_mem_gb=_gpu_mem(a), vehicle_classes=stage1._classes(m))))
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
    except (ConfigError, budget.PlanError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ledger.StageFailed as e:                                      # a stage's self-check failed: the message names it and the ledger has the detail
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def _gpu_mem(a: argparse.Namespace) -> float | None:
    """--gpu-mem-gb, else what nvidia-smi says when GPUs are asked for, else None (no memory to guard)."""
    given = getattr(a, "gpu_mem_gb", None)
    return given if given is not None else pipeline.gpu_memory_gb() if getattr(a, "gpus", 0) > 0 else None


def _report(run: pathlib.Path, open_it: bool) -> int:
    """Re-render a finished run's report; with the environment cache present the report also routes the reach map through its currents."""
    m = load_mission(run / "mission.yaml")
    plan = json.loads((run / "plan.json").read_text())
    ctx = pipeline.Context(run / "mission.yaml", plan["budget"], plan["gpus"], run)
    env = None
    if ctx.cache.is_dir():
        try:
            env = ctx.env
        except Exception as e:                                          # noqa: BLE001  a broken cache must not stop the report
            print(f"note: environment not loaded ({type(e).__name__}: {e}); no environment section or reach map", file=sys.stderr)
    paths = report.write(run, m, plan, env=env)
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
    from .config import load_platform
    from .physics import glider, uas, usv
    raw = load_platform(name)
    kind = str(raw.get("kind", "")).lower()
    cls, loader = ("uas", uas) if "kind" not in raw else ("usv", usv) if "sail" in kind or "usv" in kind else ("glider", glider)
    try:
        loader.load_platform(name)
    except ValueError as e:
        print(f"{name} ({cls}): provenance FAILED: {e}")
        return 1
    leaves: list[tuple[str, dict[str, Any]]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict) and "value" in node:
            leaves.append((path, node))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
    walk(raw, "")
    print(f"{name} ({cls}): provenance OK, {pipeline._assumed(raw)} of {len(leaves)} values assumed")
    for path, n in leaves:
        why = "ASSUMED: " + str(n.get("why", "")) if n.get("assumed") is True else "source: " + str(n.get("source", ""))
        print(f"  {path} = {n['value']} {n.get('unit', '')}  [{why[:110]}]")
    return 0


def _whatif(a: argparse.Namespace) -> int:
    m = load_mission(a.mission)
    if not (a.shift or a.move or a.drop):
        raise ConfigError("whatif needs at least one of --shift, --move, --drop")
    moves = [whatif.parse_move(x) for x in a.move]
    ops = dict(shift_h=sum(whatif.parse_shift(x) for x in a.shift), dlon=sum(d for d, _ in moves), dlat=sum(d for _, d in moves), drop=a.drop)
    run = pathlib.Path(a.run or f"runs/{m['name']}/{a.budget}")
    ctx = pipeline.Context(a.mission, a.budget, a.gpus, run)
    if not ctx.cache.is_dir():
        raise ConfigError(f"no environment cache at {ctx.cache}: run `python -m cafe.pm fetch --mission {a.mission}` first")
    base, tracks, scales, fitted = {}, {}, None, None
    if (run / "stage1b" / "summary.json").is_file():
        base = {k: v["verdict"] for k, v in json.loads((run / "stage1b" / "summary.json").read_text())["summary"]["vehicles"].items()}
        res, why = report._load_res(run, report.Trace(run))
        tracks = {k: whatif.track_points(r, m) for k, r in (res or {"vehicles": {}})["vehicles"].items() if r["class"] != "uas"}
        rf = run / "refit" / "refit.json"
        scales = {k: r for k, r in json.loads(rf.read_text()).items() if r["used"]} if rf.is_file() else None
        pf = run / "ingest" / "priors_fitted.json"
        fitted = json.loads(pf.read_text()) if pf.is_file() else None
        if res is None:
            print(f"note: {why}; every changed vehicle goes to Stage 1")
    else:
        print(f"note: no finished run at {run}: the baseline and every changed vehicle are run in Stage 1 at the {a.budget} budget")
    cls = set(stage1._classes(m).values())
    ems = whatif.train(pipeline.emulator_table(), cls)
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
    for vid, why in ans.get("unchanged", {}).items():
        print(f"{vid}: unchanged ({why})")
    if ans["dropped"]:
        print(f"dropped {', '.join(ans['dropped'])}; links removed: {', '.join(ans['links_removed']) or 'none'}. "
              "Other vehicles are unaffected: Stage-1 vehicles do not interact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
