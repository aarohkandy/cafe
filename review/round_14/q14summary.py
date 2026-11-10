"""Print the figures of demo runs side by side (read only): verdicts, fitted priors, mooring count, plan, stage-3 and timing.

usage: python q14summary.py RUN [RUN ...]   (run names under /data/runs; run it through bin/pmx.sh on orca)
"""
import json
import sys
from pathlib import Path

R = Path("/data/runs")


def get(o, *path):
    for k in path:
        o = o.get(k) if isinstance(o, dict) else None
    return o


def one(run):
    d = R / run
    j = lambda f: json.loads((d / f).read_text())  # noqa: E731
    s1, s1b = j("stage1/summary.json")["summary"], j("stage1b/summary.json")["summary"]
    rows = {}
    for tag, s in (("stage1", s1), ("stage1b", s1b)):
        for kind in ("vehicles", "links"):
            for k, v in s.get(kind, {}).items():
                vd = v["verdict"]
                rows[f"{tag}/{kind}/{k}"] = (vd["verdict"], vd["k_fail"], vd["n"], vd["p_fail"], vd["fail_lo"], vd["fail_hi"], vd.get("n_certify"))
    pri = j("ingest/priors_fitted.json")
    rows["priors"] = {k: (v.get("mean"), v.get("value"), v.get("value_hi95"), v.get("tau_h")) for k, v in pri.items() if isinstance(v, dict)}
    rows["env_sigmas"] = j("ingest/env_sigmas_fitted.json")
    rows["moorings"] = len(j("ingest/tao_compare.json"))
    rows["design"] = {k: j("emulator/design.json").get(k) for k in ("rows_added", "train_input_rows", "table_rows", "planned_variants")}
    rows["variants_run"] = len(j("emulator/design.json")["variants"])
    pl = j("plan.json")
    rows["plan.stage3.fea.min_s"] = get(pl, "stage3", "fea", "min_s")
    rows["plan.stage3.fea.runs"] = get(pl, "stage3", "fea", "runs")
    rows["plan.stage3.share_s"] = get(pl, "stage3", "share_s")
    m = j("report/report.json")
    t = get(m, "machine", "timing") or {}
    rows["timing_s"] = {k: get(v, "measured", "value") for k, v in t.items() if isinstance(v, dict)}
    rows["wall_s"] = get(m, "machine", "wall_s")
    rows["git_sha"] = get(m, "machine", "git_sha")
    return rows


if __name__ == "__main__":
    out = {r: one(r) for r in sys.argv[1:]}
    keys = sorted({k for o in out.values() for k in o})
    for k in keys:
        vals = [out[r].get(k) for r in out]
        flag = "" if all(v == vals[0] for v in vals) else "   <-- DIFFERS"
        print(f"## {k}{flag}")
        for r, v in zip(out, vals):
            print(f"   {r}: {json.dumps(v, default=str)}")
