"""python -m cafe._seed: seed the CFD cache with validation runs already computed for the built-in samples (same mesh, same case).

The runs are read from `$CAFE_WORK/runs/<run>/<sample>.<what>.json` (`/work` when CAFE_WORK is unset: the directory `cfd.CACHE` sits in), and written under
the key of the code that is here. Seed only runs made with the present settings of `cafe/cfd.py`: the cache cannot tell the settings an old file was made
with, and it will be reused as if they were these (round 17, M-12). Exit 1, with a line naming the directory, when none of the files is there.
Each sample prints what happened to it (round 18, M-12): `seeded` (the entry was written), `already there` (the cache held an identical earlier run: nothing
was written) or `NOT seeded` with the cache's warning (it could not be written; the exit is then 1)."""
import json, pathlib, sys, tempfile
import numpy as np
from cafe import geom, cfd


def main() -> int:
    runs = cfd.CACHE.parent / "runs"
    found = failed = 0
    for key, run, what in (("quad", "q1", "external"), ("torpedo", "t1", "external"), ("wigley", "w1", "surface")):
        p = runs / run / f"{key}.{what}.json"
        if not p.exists():
            continue
        found += 1
        s = geom.SAMPLES[key]; m = s["make"]()
        if what == "external":
            k = ("external", "air", 10.0) if s["kind"] == "uav" else ("external", "water", round(1.5, 3))
        else:
            hs = geom.hydrostatics(m, s["spec"]["mass"])
            speeds = [float(fn * np.sqrt(9.81 * hs["lwl"])) for fn in (0.2, 0.3, 0.4)]
            k = ("surface", round(hs["draft"], 4), [round(x, 3) for x in speeds])
        r = json.loads(p.read_text())
        if what == "surface":   # json keys are strings; hangar expects the same shape cfd returns
            r["speeds"] = {float(u): v for u, v in r["speeds"].items()}
        lines: list[str] = []
        computed: list[int] = []

        def log(line: str, lines: list[str] = lines) -> None:
            lines.append(line)
            print(line)

        with tempfile.TemporaryDirectory() as d:
            stl = pathlib.Path(d) / "mesh.stl"; m.export(stl)
            cfd.cached(k, stl, log, lambda r=r, c=computed: c.append(1) or r)
        warned = [x for x in lines if x.startswith("warning:")]
        if not computed:
            print("already there", key, k)
        elif warned:
            failed += 1
            print("NOT seeded", key, k, "-", warned[-1])
        else:
            print("seeded", key, k)
    if not found:
        print(f"no old runs found under {runs} (q1/quad.external.json, t1/torpedo.external.json, w1/wigley.surface.json); "
              "set CAFE_WORK to the directory that holds runs/", file=sys.stderr)
    return 0 if found and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
