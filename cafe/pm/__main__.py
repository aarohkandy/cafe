"""python -m cafe.pm <command>  (bin/run_premission is `python -m cafe.pm run`)

    run       --mission M --budget {ci,quick,4h,overnight} --gpus N [--out DIR] [--fresh]   the whole pipeline, resumable
    fetch     --mission M                    ingest only (orca + ocean into the cache)
    validate  --mission M                    schema and cross-checks, nothing run
    plan      --mission M --budget B --gpus N   what the budget buys on this machine
    report    --run DIR                      re-render the report from a finished run
    receipts  [--broken YAML] [--slow] [--only NAME,..] [--json OUT]   every receipt (app + pre-mission) as one table; see cafe/pm/receipts.py
"""
import argparse, pathlib, sys

from . import budget, pipeline, stage1
from .config import ConfigError, load_mission


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m cafe.pm", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "fetch", "validate", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--mission", required=True)
        if name in ("run", "plan"):
            p.add_argument("--budget", default="quick", choices=list(budget.BUDGET_S))
            p.add_argument("--gpus", type=int, default=0)
        if name in ("run", "fetch"):
            p.add_argument("--out", default=None, help="run directory (default runs/<mission>/<budget>)")
            p.add_argument("--fresh", action="store_true", help="ignore existing checkpoints")
    p = sub.add_parser("report")
    p.add_argument("--run", required=True)
    p = sub.add_parser("receipts")
    p.add_argument("--broken", default=None, help="overlay yaml to apply; the exit code is 0 only if it makes a receipt fail")
    p.add_argument("--slow", action="store_true", help="also run the slow receipts instead of reading their stored results")
    p.add_argument("--only", default=None, help="comma-separated parts of receipt-group names to run")
    p.add_argument("--json", default=None, help="where to write the table (default runs/receipts.json, runs/receipts_broken.json with --broken)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "receipts":
            from . import receipts
            return receipts.run(a.slow, a.only.split(",") if a.only else None, a.broken, a.json)[1]
        if a.cmd == "validate":
            m = load_mission(a.mission)
            print(f"{a.mission}: valid ({len(m['vehicles'])} vehicles, {len(m['links'])} links)")
        elif a.cmd == "plan":
            m = load_mission(a.mission)
            print(budget.describe(budget.plan(a.budget, a.gpus, m, vehicle_classes=stage1._classes(m))))
        elif a.cmd in ("run", "fetch"):
            m = load_mission(a.mission)
            bud = getattr(a, "budget", "quick")
            out = pathlib.Path(a.out or f"runs/{m['name']}/{bud}")
            ctx = pipeline.run(a.mission, bud, getattr(a, "gpus", 0), out, resume=not a.fresh, stop_after="ingest" if a.cmd == "fetch" else None)
            if a.cmd == "run":
                print(f"report: {ctx.run_dir / 'report' / 'index.html'}")
        else:
            from . import report
            run = pathlib.Path(a.run)
            for p in report.write(run, load_mission(run / "mission.yaml"), __import__("json").loads((run / "plan.json").read_text())):
                print(p)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
