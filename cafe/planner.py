"""Resolution planner: cell sizes per nest level from the wall-clock budget and the measured solver throughput.

    python -m cafe.planner [config/premission.json] [--devices N] [--backend gpu] [--check]

Cost of a uniform level, in cell-updates:  T * U * V / (CFL * dx^4)   (cells V/dx^3, steps T*U/(CFL*dx)).
So halving dx costs 16x, and 64x the compute buys only 64^(1/4) = 2.83x finer cells.

Levels per drone and medium: bridge levels from L1 down in 10x steps, L2a (~1 km box), L2b (close nest), and L3,
the drone-resolving box. L3 is graded: the hull boundary-layer shell at hull resolution, then bands of 10 cells
that double their spacing outward up to the L2b spacing, each band on its own CFL step. Adjacent levels never
differ by more than max_refinement_ratio: a finer level that would is coarsened to the limit (it stays in budget).
"""
import json, math, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "throughput.json"


def uniform_cost(T, U, V, cfl, dx):
    return T * U * V / (cfl * dx ** 4)


def solve(cost, budget, lo=1e-6, hi=1e5):
    """dx at which the (decreasing) cost function meets the budget, by bisection in log dx."""
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if cost(mid) > budget else (lo, mid)
    return hi


def boundary_layer(L, U, nu):
    """Turbulent flat-plate thickness at the trailing edge, 0.37 L Re^-1/5: the shell kept at hull resolution."""
    return 0.37 * L * (U * L / nu) ** -0.2


def hull_cost(T, h, nu, cfl, dx_h, dx_out):
    """Graded L3 box around a hull: area h["area"], length h["length"], box h["box_lengths"] lengths on a side."""
    A, L, U = h["area"], h["length"], h["U"]
    R = h["box_lengths"] * L / 2
    box = (2 * R) ** 3
    vol = lambda d: min(A * d + 4 / 3 * math.pi * d ** 3, box)     # region within distance d of the hull
    d, dx, cost, bands = 0.0, dx_h, 0.0, []
    while True:
        d1 = max(boundary_layer(L, U, nu), 10 * dx) if not bands else d + 10 * dx
        last = dx * 2 > dx_out or d1 >= R
        if last:
            d1 = math.sqrt(3) * R                                    # the rest of the box at this spacing
        cost += uniform_cost(T, U, vol(d1) - vol(d), cfl, dx)
        bands.append((dx, d1))
        if last:
            return cost, bands
        d, dx = d1, dx * 2


def throughput(cfg, devices):
    """(cell-updates/s on `devices`, where the number came from)."""
    b = json.loads(BENCH.read_text()).get(cfg["solver"]) if BENCH.exists() else None
    if not b or b.get("backend") != cfg["backend"]:
        return cfg["assumed_per_device"] * devices, f"assumed {cfg['assumed_per_device']:.3g}/device ({cfg['backend']}), not measured"
    measured = {int(k): v for k, v in (b.get("cell_updates_per_s") or {}).items()}
    if devices in measured:
        return measured[devices], f"measured on {devices} x {b['device']} ({b['host']}, {b['measured']})"
    eff = b.get("scaling_efficiency_1_to_8", 1.0)
    return b["per_device"] * devices * eff, f"{b['per_device']:.3g}/device measured, x{devices} at the measured {eff:.0%} efficiency (extrapolated)"


def plan(cfg, devices=None):
    devices = devices or cfg["devices"]
    rate, rate_src = throughput(cfg, devices)
    T, cfl, rmax, B = cfg["mission_s"], cfg["cfl"], cfg["max_refinement_ratio"], cfg["budget_s"]
    drones, media = cfg["drones"], cfg["media"]
    nests = sum(len(d["media"]) for d in drones.values())      # each level's share is split over every nest
    out = dict(devices=devices, backend=cfg["backend"], solver=cfg["solver"], rate=rate, rate_source=rate_src, media={}, drones={})
    for m, md in media.items():
        users = sum(m in d["media"] for d in drones.values())
        if not users:
            continue
        U, L1 = md["U"], cfg["L1"][f"{m}_dx"]

        def with_bridges(dx_a):
            """L2a at dx_a plus the bridge levels L1 needs to reach it in steps of at most rmax; each bridge box is
            the next box in plus a 20-cell buffer (sponge) on every side."""
            chain, dx = [], L1
            while dx > rmax * dx_a * 1.0001:
                dx /= rmax
                chain.append(dx)
            levels, box = [dict(dx=dx_a, box=list(md["L2a_box"]))], list(md["L2a_box"])
            for dx in reversed(chain):
                box = [b + 40 * dx for b in box]
                levels.insert(0, dict(dx=dx, box=box, bridge=True))
            for x in levels:
                x["cost"] = uniform_cost(T, U, math.prod(x["box"]), cfl, x["dx"])
            return levels

        lv = {}
        dx_a = solve(lambda dx: sum(x["cost"] for x in with_bridges(dx)), B * cfg["shares"]["L2a"] * rate / nests)
        *bridges, lv["L2a"] = with_bridges(dx_a)
        if bridges:
            lv["bridges"] = bridges
        b = math.prod(md["L2b_box"])
        lv["L2b"] = dict(dx=solve(lambda dx: uniform_cost(T, U, b, cfl, dx), B * cfg["shares"]["L2b"] * rate / nests), box=md["L2b_box"])
        if lv["L2b"]["dx"] > lv["L2a"]["dx"]:
            lv["L2b"]["dx"], lv["L2b"]["note"] = lv["L2a"]["dx"], "budget allowed no refinement over L2a"
        if lv["L2a"]["dx"] / lv["L2b"]["dx"] > rmax:
            lv["L2b"]["dx"], lv["L2b"]["note"] = lv["L2a"]["dx"] / rmax, f"coarsened to {rmax}x L2a"
        lv["L2b"]["cost"] = uniform_cost(T, U, b, cfl, lv["L2b"]["dx"])
        for x in [*bridges, lv["L2a"], lv["L2b"]]:
            x["wall_s"] = x["cost"] * users / rate                    # every drone in this medium has its own nest
        out["media"][m] = lv
    for name, d in drones.items():
        h, m = d["hull"], d["hull"]["medium"]
        nu, dx_out = media[m]["nu"], out["media"][m]["L2b"]["dx"]
        res = {}
        for what, Th in (("mission", T), ("windows", cfg["events"]["windows_per_drone"] * (cfg["events"]["window_s"] + cfg["events"]["lead_s"]))):
            budget = B * cfg["shares"]["L3"] * rate / len(drones)
            dx = max(solve(lambda x: hull_cost(Th, h, nu, cfl, x, dx_out)[0], budget), cfg["wall_dx_min"])
            cost, bands = hull_cost(Th, h, nu, cfl, dx, dx_out)
            res[what] = dict(dx=dx, cost=cost, wall_s=cost / rate, bands=len(bands), floored=dx == cfg["wall_dx_min"],
                             shell_m=boundary_layer(h["length"], h["U"], nu))
        out["drones"][name] = res
    out["wall_s"] = sum(x["wall_s"] for lv in out["media"].values() for x in [*lv.get("bridges", []), lv["L2a"], lv["L2b"]]) \
        + sum(r["windows"]["wall_s"] for r in out["drones"].values())
    return out


def fmt(dx):
    return f"{dx * 1e3:.2g} mm" if dx < 0.01 else f"{dx * 100:.2g} cm" if dx < 1 else f"{dx:.3g} m"


def show(p, cfg):
    print(f"{p['devices']} x {p['backend']}, {p['solver']}: {p['rate']:.3g} cell-updates/s ({p['rate_source']})")
    print(f"budget {cfg['budget_s'] / 60:.0f} min, mission {cfg['mission_s'] / 3600:.1f} h, shares {cfg['shares']}")
    for m, lv in p["media"].items():
        chain = " -> ".join(fmt(x["dx"]) for x in lv.get("bridges", []))
        print(f"  {m:5s} L1 {fmt(cfg['L1'][m + '_dx'])}" + (f" -> bridges {chain}" if chain else "") +
              f" -> L2a {fmt(lv['L2a']['dx'])} -> L2b {fmt(lv['L2b']['dx'])}" + (f"  ({lv['L2b']['note']})" if "note" in lv["L2b"] else ""))
    for n, r in p["drones"].items():
        w = r["windows"]
        print(f"  L3 {n:9s} full mission {fmt(r['mission']['dx'])} | event windows {fmt(w['dx'])}{' (wall-model floor)' if w['floored'] else ''}"
              f", {w['wall_s'] / 60:.1f} min, {w['bands']} bands, BL shell {fmt(w['shell_m'])}")
    print(f"  planned CFD wall time {p['wall_s'] / 60:.1f} min of {cfg['budget_s'] / 60:.0f}")


SPEC = {8: dict(air=1.7, ocean=0.5, saildrone=5e-3, aerial=1e-2, glider=2e-3),
        512: dict(air=0.6, ocean=0.2, saildrone=2e-3, aerial=3.5e-3, glider=0.7e-3)}


def check(cfg):
    """Invariants that must hold, then the spec's reference table (10^9/GPU) side by side for comparison."""
    assert abs(uniform_cost(1, 1, 1, 1, 0.5) / uniform_cost(1, 1, 1, 1, 1.0) - 16) < 1e-9          # 2x finer = 16x cost
    g = dict(cfg, backend="gpu", solver="-", max_refinement_ratio=1e9)                             # unclamped, assumed rate
    p8, p512 = plan(g, 8), plan(g, 512)
    r = p8["media"]["air"]["L2a"]["dx"] / p512["media"]["air"]["L2a"]["dx"]
    assert abs(r - 64 ** 0.25) < 1e-3, r                                                          # 64x compute -> 2.83x
    for p in (plan(cfg, 8), plan(dict(cfg, devices=1), 1)):
        for m, lv in p["media"].items():
            chain = [cfg["L1"][f"{m}_dx"]] + [x["dx"] for x in [*lv.get("bridges", []), lv["L2a"], lv["L2b"]]]
            assert all(a / b <= cfg["max_refinement_ratio"] * 1.0001 for a, b in zip(chain, chain[1:])), chain
        for r_ in p["drones"].values():
            assert r_["windows"]["dx"] >= cfg["wall_dx_min"]
    print("invariants hold: 2x finer = 16x cost; 64x compute = 2.83x finer; adjacent levels <= "
          f"{cfg['max_refinement_ratio']}x; hull cells >= {fmt(cfg['wall_dx_min'])}\n")
    # The spec's air/ocean rows are one L2a-sized nest per medium with the L2b share (0.2) of the budget, not split
    # over drones: that reproduces all four to the digits the spec quotes, and is asserted. Its hull rows came from
    # an L3 cost model the spec didn't state; this planner's graded L3 differs, so they are shown, not asserted.
    print("spec reference (10^9 cell-updates/s/GPU, 1 h, 3 h mission) vs this planner with the same assumption:")
    print(f"  {'level':10s} {'8 GPU spec':>11s} {'planner':>9s} {'512 spec':>9s} {'planner':>9s}")
    g2 = dict(g, max_refinement_ratio=cfg["max_refinement_ratio"])
    for k in SPEC[8]:
        row = []
        for n in (8, 512):
            if k in ("air", "ocean"):
                md = cfg["media"][k]
                dx = solve(lambda d: uniform_cost(cfg["mission_s"], md["U"], math.prod(md["L2a_box"]), cfg["cfl"], d),
                           cfg["budget_s"] * cfg["shares"]["L2b"] * cfg["assumed_per_device"] * n)
                s = SPEC[n][k]
                sf = len(repr(s).replace(".", "").strip("0"))                     # digits the spec quotes
                assert abs(dx - s) <= 0.5 * 10 ** (math.floor(math.log10(s)) - sf + 1), (k, n, dx, s)
            else:
                dx = plan(g2, n)["drones"][k]["mission"]["dx"]
            row += [fmt(SPEC[n][k]), fmt(dx)]
        tag = "reproduced" if k in ("air", "ocean") else "not reproduced (graded L3 vs unstated spec model)"
        print(f"  {k:10s} {row[0]:>11s} {row[1]:>9s} {row[2]:>9s} {row[3]:>9s}  {tag}")


if __name__ == "__main__":
    args = sys.argv[1:]
    path = next((a for a in args if a.endswith(".json")), ROOT / "config" / "premission.json")
    cfg = json.loads(pathlib.Path(path).read_text())
    for flag, key, typ in (("--devices", "devices", int), ("--backend", "backend", str)):
        if flag in args:
            cfg[key] = typ(args[args.index(flag) + 1])
    if "--check" in args:
        check(cfg)
    else:
        p = plan(cfg)
        show(p, cfg)
        if "--json" in args:
            print(json.dumps(p, indent=1))
