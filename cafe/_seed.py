# seed the CFD cache with validation runs already computed for the built-in samples (same mesh, same case)
import json, pathlib, tempfile
import numpy as np
from cafe import geom, cfd
for key, run, what in (("quad", "q1", "external"), ("torpedo", "t1", "external"), ("wigley", "w1", "surface")):
    p = pathlib.Path(f"/work/runs/{run}/{key}.{what}.json")
    if not p.exists():
        continue
    s = geom.SAMPLES[key]; m = s["make"]()
    stl = pathlib.Path(tempfile.mkdtemp()) / "mesh.stl"; m.export(stl)
    if what == "external":
        k = ("external", "air", 10.0) if s["kind"] == "uav" else ("external", "water", round(1.5, 3))
    else:
        hs = geom.hydrostatics(m, s["spec"]["mass"])
        speeds = [float(fn * np.sqrt(9.81 * hs["lwl"])) for fn in (0.2, 0.3, 0.4)]
        k = ("surface", round(hs["draft"], 4), [round(x, 3) for x in speeds])
    r = json.loads(p.read_text())
    if what == "surface":   # json keys are strings; hangar expects the same shape cfd returns
        r["speeds"] = {float(u): v for u, v in r["speeds"].items()}
    cfd.cached(k, stl, print, lambda: r)
    print("seeded", key, k)
