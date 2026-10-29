#!/usr/bin/env python3
"""Test fixture, not part of the product: stands in for a lab-built FluidX3D executable.

Honours the contract in cafe/pm/stage3/fluidx3d.py: reads --case, writes --out in the forces.dat format. The force is a
quadratic drag of coefficient CD on the case's velocity plus a small oscillation, so tests can check the plumbing
(parsing, units, coefficient extraction) against numbers they know.
"""
import json
import math
import sys

CD, AREA = 0.30, 0.02          # the tests read these back


def main(argv):
    case = json.load(open(argv[argv.index("--case") + 1]))
    out = argv[argv.index("--out") + 1]
    if case["name"] == "stub-crash":
        sys.stderr.write("stub: forced failure\n")
        return 3
    if case["name"] == "stub-nofile":
        return 0
    v = case["velocity"]
    sp = math.sqrt(sum(x * x for x in v))
    with open(out, "w") as f:
        f.write("# step time_s Fx_N Fy_N Fz_N (stub)\n")
        for k in range(1, 101):
            step = k * case["steps"] // 100
            t = step * case["dt"]
            d = 0.5 * case["rho"] * AREA * CD * sp * sp * (1 + 0.01 * math.sin(40 * t / (case["steps"] * case["dt"])))
            f.write(f"{step} {t:.9g} {-d * v[0] / sp:.9g} {-d * v[1] / sp:.9g} {-d * v[2] / sp:.9g}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
