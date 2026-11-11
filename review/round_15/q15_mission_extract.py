"""Write a run's per-member mission arrays (read only) from stage1b/res.pkl as one json, for a reviewer who has no GPU, no image and no pickle.

usage (orca, through bin/pmx.sh): python review/round_15/q15_mission_extract.py RUN OUT.json      (RUN under /data/runs; OUT under /data)

Per vehicle: t, lon, lat, depth and surfaced every 30 min (every 3rd sample of the 10 min grid), heading where the vehicle has one, `alt` and `airborne`
for the UAS plus its `fine` series and sorties; margin, margin_name, the `fail` and `first` dicts, the class and the antenna height. Per link: t, margin_db
and success at full resolution, frac, dist_m and the rest. X is the 64 draws of every sampled input; U is the unit hypercube. Each array is a list of lists
[time][member] (or [member]); lon and lat at 1e-5 deg, depth, heading and alt at 0.1, margin_db at 0.01; NaN and inf are null; surfaced is 0 or 1.
"""
import json
import pickle
import sys

import numpy as np

STEP = 3                                                     # the grid is 10 min; every 30 min
ROUND = dict(lon=5, lat=5, depth=1, heading=1, alt=1, margin_db=2)


def arr(a, name=""):
    a = np.asarray(a)
    if a.dtype == bool:
        a = a.astype(int)
    if a.dtype.kind == "f":
        a = np.round(a.astype("f8"), ROUND.get(name, 6))
        return np.where(np.isfinite(a), a, None).tolist() if not np.isfinite(a).all() else a.tolist()
    return a.tolist()


def val(o, name=""):
    if isinstance(o, dict):
        return {k: val(v, k) for k, v in o.items()}
    a = np.asarray(o)
    return a.item() if a.ndim == 0 else arr(a, name)


def vehicle(v):
    out = {}
    for k, o in v.items():
        if k in ("lon", "lat", "depth", "surfaced", "heading", "alt", "airborne", "t") and np.asarray(o).shape[:1] == (865,):
            out[k] = arr(np.asarray(o)[::STEP], k)
        elif k == "sorties":
            out[k] = {i: val(s) for i, s in o.items()} if isinstance(o, dict) else [val(s) for s in o]
        else:
            out[k] = val(o, k)
    return out


if __name__ == "__main__":
    r = pickle.load(open(f"/data/runs/{sys.argv[1]}/stage1b/res.pkl", "rb"))
    doc = dict(run=sys.argv[1], grid_s=float(r["vehicles"]["usv"]["t"][1] - r["vehicles"]["usv"]["t"][0]) * STEP, layout="[time][member] or [member]",
               X=val(r["X"]), U=arr(r["U"]), vehicles={k: vehicle(v) for k, v in r["vehicles"].items()},
               links={k: val(v) for k, v in r["links"].items()})
    with open(sys.argv[2], "w") as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    print(sys.argv[2], "written")
