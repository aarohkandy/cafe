"""Round 14, M-43: leave-one-out of fit_wind_error on the demo's hourly residuals (read only: q14la's inputs, a scratch run directory under /data/m43_run).

Rebuilds what pipeline._tao feeds fit_wind_error (the hourly model-minus-mooring series) from the cache and the run's own TAO manifest copy, checks that the
all-mooring fit reproduces the priors_fitted.json of the run, then prints the fit without each mooring (and without T5S165E)."""
import json
import pathlib
import sys

import numpy as np

from cafe.pm import pipeline
from cafe.pm.config import utc
from cafe.pm.env import tao

RUN = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/data/runs/q14la")
SCRATCH = pathlib.Path("/data/m43_run")
SCRATCH.mkdir(exist_ok=True)
ctx = pipeline.Context(RUN / "mission.yaml", None, 0, SCRATCH)
sig = RUN / "ingest" / "env_sigmas_fitted.json"
if sig.is_file():
    (SCRATCH / "ingest").mkdir(exist_ok=True)
    (SCRATCH / "ingest" / "env_sigmas_fitted.json").write_text(sig.read_text())
t0, t1 = utc(ctx.mission["window"]["start"]).timestamp(), utc(ctx.mission["window"]["end"]).timestamp()
tman = json.loads((RUN / "ingest" / "tao_manifest.json").read_text())
moor = tao.load_tao(tao.cache_dir(pipeline.DATA), t0, t1, man=tman)
hours = np.arange(t0, t1 + 1, 3600.0)
wrf = {}
for name, m in moor.items():
    if ctx.env.inside(m["lon"], m["lat"]):
        lo, la = np.full(hours.size, float(m["lon"])), np.full(hours.size, float(m["lat"]))
        wrf[name] = dict(t=hours, wind10=ctx.env.u10(lo, la, hours), sst=ctx.env.sst(lo, la, hours).value)
res = pipeline._wind_residuals(wrf, moor)
stored = json.loads((RUN / "ingest" / "priors_fitted.json").read_text())
print("moorings with a series:", len(res), "stored priors:", {k: (v["mean"] if "mean" in v else None, v["value"]) for k, v in stored.items()})


def fit(names, j):
    return pipeline.fit_wind_error({k: res[k][:, j] for k in names})


names = sorted(res)
for j, label in ((0, "speed m/s"), (1, "direction deg")):
    print(f"\n=== {label}: per-mooring time-mean error (model minus mooring), n")
    for k in names:
        x = res[k][:, j]
        print(f"  {k:8s} mean {np.nanmean(x):+8.4f}  n {int(np.isfinite(x).sum())}")
    all_ = fit(names, j)
    print(f"all {len(names)}: persistent {all_['persistent']:.4f}  hi95 {all_['persistent_hi95']:.4f}  mean {all_['mean']:+.5f}  noise {all_['noise']:.4f}  rho {all_['rho']:.3f}")
    key = "wind_speed_bias" if j == 0 else "wind_direction_bias"
    print(f"stored {key}: value {stored[key]['value']:.4f}  hi95 {stored[key]['value_hi95']:.4f}  mean {stored[key]['mean']:+.5f}")
    print("leave one out:")
    for k in names:
        f = fit([n for n in names if n != k], j)
        print(f"  without {k:8s}: persistent {f['persistent']:.4f}  hi95 {f['persistent_hi95']:.4f}  mean {f['mean']:+.5f}  noise {f['noise']:.4f}  moorings {int(f['moorings'])}")
    # the parts of the 13-mooring persistent sd
    rest = [n for n in names if n != "T5S165E"]
    means = np.array([np.nanmean(res[k][:, j]) for k in rest])
    print(f"without T5S165E: sd of the {len(rest)} time-mean errors {np.std(means, ddof=1):.4f}, range {means.min():+.4f} to {means.max():+.4f}")
