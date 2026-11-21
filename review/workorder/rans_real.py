"""The real child of the glider RANS part (work order step 3), once, for the demo's Seaglider. Not product code, and no test.

It builds the vehicle and the case exactly as stage 3's `_rans_submit` does for the first window of a finished demo run (the same vehicle and window the
probe review/workorder/rans_probe.py used), then drives the real child through `pipeline_windows._rans_work` (a real subprocess `python -m
cafe.pm.stage3.rans`: two cfd.external grids, no stand-in) and prints the row: ok, cd, cd_spread, each check's value and limit, seconds. Then it puts
that row alone in a stage-3 file of a fresh run directory and runs the real `pipeline.s_refit` on it: the glider is marked used with part `body_rans` and
drag.mean = cd / cd_hangar.

Run on orca, alone on the worker, PM_CPUS equal to --cores:
  PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_<you> PM_CPUS=6 PM_MEM=24g TM=<name> bin/pmx.sh python review/workorder/rans_real.py --cores 6
Writes only under --out (default /data/runs/rans_real); the run dir (default /data/runs/on1) is only read. TMPDIR is set under --out so the case
directories (the child's temporary directory) are made there and go away with the child.
"""
import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CAFE_OFFLINE", "1")                       # the environment is read from the cache; nothing is fetched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cores", type=int, default=6, help="MPI ranks of OpenFOAM (CAFE_NPROC); keep it equal to PM_CPUS")
    ap.add_argument("--out", default="/data/runs/rans_real", help="work directory (everything written is under it)")
    ap.add_argument("--run", default="/data/runs/on1", help="finished demo run: windows.json, stage1/res.pkl and ingest/ the case is built from (read only)")
    ap.add_argument("--mission", default=str(ROOT / "missions" / "tepex_c_demo.yaml"))
    args = ap.parse_args()
    out = pathlib.Path(args.out).resolve()
    if not out.name.startswith("rans_real") or str(out).startswith("/tmp"):
        sys.exit(f"--out {out}: the directory must be named rans_real* and not under /tmp")
    (out / "tmp").mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(out / "tmp")
    tempfile.tempdir = None
    os.environ["CAFE_NPROC"] = str(args.cores)                    # cafe.cfd reads it at import, in the child too
    from cafe.pm import ledger, pipeline
    from cafe.pm.stage3 import pipeline_windows as PW, rans

    ctx = pipeline.Context(args.mission, None, 0, args.run)
    vid = next(v["id"] for v in ctx.mission["vehicles"] if ctx.classes[v["id"]] == "glider" and v["platform"] == "seaglider")
    platform = next(v["platform"] for v in ctx.mission["vehicles"] if v["id"] == vid)
    w = json.loads((pathlib.Path(args.run) / "windows" / "windows.json").read_text())[vid][0]
    a = PW.assumptions()
    res = PW._load_res(ctx)
    P, veh = PW._glider_vehicle_for(ctx, vid, platform, a, clip=False)
    heading, hsrc = PW.track_heading(res, vid, w["t"]), PW.track_heading_source(res, vid, w["t"])
    case = PW.glider_case(ctx, w, P, veh, a, heading)
    vb = case["R"] @ (case["v"] - case["u_env"])
    label, speed = rans.flow_label(vb)
    base = PW._base(ctx, w, "body_rans")
    base["label"] = rans.LABEL
    PW._describe(base, veh, case, vb, heading, hsrc)
    base.update(cl_hangar=None, ref_area=veh.ref_area)
    print(json.dumps(dict(vehicle=vid, platform=platform, window=w, label=label, speed_ms=speed, cd_hangar=case["cd_h"], cores=args.cores,
                          est_s=PW.need(a, "glider.rans.est_s")), default=float), flush=True)
    t0 = time.perf_counter()
    row = PW._rans_work(base, veh, case, speed, label, PW.need(a, "glider.rans.est_s"), None, t0)
    (out / "row.json").write_text(json.dumps(row, indent=1, default=float))
    print(json.dumps({k: row.get(k) for k in ("ok", "part", "label", "error", "reasons", "cd", "cd_spread", "cd_hangar", "cl", "cl_hangar", "gci",
                                                "refinement_ratio", "drag_n", "ref_area", "resolution", "timing")}, indent=1, default=float), flush=True)
    for c in row["checks"]:
        print(f"check {c['name']}: value {c['value']:.6g} limit {c['limit']:.6g} ok {c['ok']}")
    if row.get("cd") is None:
        return 1
    # the refit on that row alone: a fresh run directory, the real s_refit
    ctx2 = pipeline.Context(args.mission, "overnight", 0, out / "run")
    ctx2.path("stage3", "windows.json").write_text(json.dumps({vid: [{k: x for k, x in row.items() if k != "timing"}]}, default=float))
    with ledger.Ledger(ctx2.run_dir, "refit", ctx2.hash) as L:
        pipeline.s_refit(ctx2, L)
    ref = json.loads(ctx2.path("refit", "refit.json").read_text())[vid]
    print(json.dumps(dict(refit=ref, cd_over_cd_hangar=row["cd"] / row["cd_hangar"]), indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
