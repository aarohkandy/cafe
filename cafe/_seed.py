"""python -m cafe._seed: seed the CFD cache with validation runs already computed for the built-in samples (same mesh, same case).

The runs are read from `$CAFE_WORK/runs/<run>/<sample>.<what>.json` (`/work` when CAFE_WORK is unset: the directory `cfd.CACHE` sits in), and written under
the key of the code that is here. Seed only runs made with the present settings of `cafe/cfd.py`: the cache cannot tell the settings an old file was made
with, and it will be reused as if they were these (round 17, M-12). Exit 1, with a line naming the directory, when none of the files is there.
Each sample prints what happened to it (round 18, M-12): `seeded` (the entry was written), `already there` (the cache held an identical earlier run: nothing
was written) or `NOT seeded` with the cache's warning (it could not be written; the exit is then 1). Every file is read and its shape checked first (round 19,
M-14): one that cannot be read, is not JSON or is not a result of its case is `NOT seeded <file> - <reason>`, exit 1, and nothing is written for any sample."""
import json, math, pathlib, sys, tempfile
import numpy as np
from cafe import geom, cfd

CASES = (("quad", "q1", "external"), ("torpedo", "t1", "external"), ("wigley", "w1", "surface"))


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _vec(v: object) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v)


def _checked(what: str, k: tuple, r: object) -> dict:
    """`r` as the result `cfd.cached` would hold under the key `k`, or a `ValueError` saying what is wrong with it (round 19, M-14). The fields the Hangar
    reads (`vehicle.py`): for `external` the fluid and speed of the key, `rho`, `nu`, `L`, and per direction the `force`, `moment` and `viscous` vectors; for
    `surface` the speeds of the key, each with its `resistance`. A file of another shape was cached under the real key and read as a result."""
    if not isinstance(r, dict):
        raise ValueError(f"the file holds {type(r).__name__}, not a result (a JSON object)")
    if what == "surface":
        sp = r.get("speeds")
        if not isinstance(sp, dict) or not sp:
            raise ValueError("no `speeds` (an object of the speeds of the case)")
        try:                                      # json keys are strings; hangar expects the same shape cfd returns
            got = {float(u): v for u, v in sp.items()}
        except ValueError:
            raise ValueError("a key of `speeds` is not a number") from None
        if not all(isinstance(v, dict) and _num(v.get("resistance")) for v in got.values()):
            raise ValueError("a speed has no numeric `resistance`")
        if sorted(round(u, 3) for u in got) != k[2]:
            raise ValueError(f"its speeds {sorted(got)} are not those of this case {k[2]}")
        return {**r, "speeds": got}
    if r.get("fluid") != k[1] or r.get("speed") != k[2]:
        raise ValueError(f"made for fluid {r.get('fluid')!r} at speed {r.get('speed')!r}, not {k[1]!r} at {k[2]!r}")
    bad = [f for f in ("rho", "nu", "L") if not _num(r.get(f))]
    if bad:
        raise ValueError(f"no number in {', '.join(bad)}")
    dirs = r.get("dirs")
    if not isinstance(dirs, dict) or not dirs or not set(dirs) <= set(cfd.DIRS):
        raise ValueError(f"`dirs` is not an object of directions among {', '.join(cfd.DIRS)}")
    for d, v in dirs.items():
        if not isinstance(v, dict) or not all(_vec(v.get(f)) for f in ("force", "moment", "viscous")):
            raise ValueError(f"direction {d} has no `force`, `moment` and `viscous` of three numbers each")
    return r


def main() -> int:
    runs = cfd.CACHE.parent / "runs"
    cases = []
    bad = 0
    for key, run, what in CASES:                  # every file is read and checked before the first is written
        p = runs / run / f"{key}.{what}.json"
        if not p.exists():
            continue
        s = geom.SAMPLES[key]; m = s["make"]()
        if what == "external":
            k = ("external", "air", 10.0) if s["kind"] == "uav" else ("external", "water", round(1.5, 3))
        else:
            hs = geom.hydrostatics(m, s["spec"]["mass"])
            speeds = [float(fn * np.sqrt(9.81 * hs["lwl"])) for fn in (0.2, 0.3, 0.4)]
            k = ("surface", round(hs["draft"], 4), [round(x, 3) for x in speeds])
        try:
            r = _checked(what, k, json.loads(p.read_text()))
        except (OSError, ValueError) as e:        # JSONDecodeError and UnicodeDecodeError are ValueErrors
            bad += 1
            print("NOT seeded", p, "-", e)
            continue
        cases.append((key, m, k, r))
    if bad:
        print(f"nothing was seeded: {bad} of the {len(cases) + bad} files cannot be used; fix or remove them and run it again", file=sys.stderr)
        return 1
    failed = 0
    for key, m, k, r in cases:
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
    if not cases:
        print(f"no old runs found under {runs} (q1/quad.external.json, t1/torpedo.external.json, w1/wigley.surface.json); "
              "set CAFE_WORK to the directory that holds runs/", file=sys.stderr)
    return 0 if cases and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
