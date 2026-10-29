"""`--budget {ci,quick,4h,overnight}` -> how big every stage is on THIS machine, from config/throughput.json (bench/).

The contract is wall-clock, not a fixed machine: the same mission and budget give a small plan on an 8-vCPU box with no
GPU and a large one on a GPU server, from that machine's measured rates. Every number the plan used is in the plan
(and so in the report), with where it came from.

Shares of the budget: ingest (measured bytes/s; zero once cached), stage 1 (members x vehicle-days x the measured
member cost), stage 3 (LES windows: cells x steps / measured LBM rate; FEA and interFoam on CPU in parallel), stage 1'
(the refit rerun), report. A plan that would not fit is shrunk (members, then windows, then nest resolution) and says so.
"""
from __future__ import annotations

import json, pathlib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
THROUGHPUT = ROOT / "config" / "throughput.json"

BUDGET_S = {"ci": 600, "quick": 1200, "4h": 4 * 3600, "overnight": 10 * 3600}
N_MAX = {"ci": 16, "quick": 64, "4h": 256, "overnight": 512}
N_MIN = {"ci": 8, "quick": 32, "4h": 73, "overnight": 73}            # 73: smallest n that can certify P(fail) < 5 % (stats.intervals)
BATCH = {"ci": 16, "quick": 32, "4h": 64, "overnight": 128}         # cost is per environment call, not per member: big batches
WINDOWS = {"ci": 1, "quick": 1, "4h": 3, "overnight": 3}             # worst windows per vehicle that get L3 LES + FEA
SITL = {"ci": 0, "quick": 0, "4h": 4, "overnight": 8}                # ArduCopter SITL members (serial, run as parallel -I instances)
SHARE = dict(stage1=0.45, stage3=0.30, stage1b=0.15, emulator=0.05)   # stage 1b is a copy (free) when no window passes: its share goes to the emulator
EMULATOR_VARIANTS = {"ci": 2, "quick": 6, "4h": 24, "overnight": 48}   # most mission variants (a batch of every vehicle each) the emulator stage adds per run
FALLBACK_COST = {"glider": (8.0, 0.1), "usv": (11.0, 0.1), "uas": (20.0, 0.3)}   # (s per batch, s per member) per mission day without bench
GPU_MEM_GUARD = 0.85


class PlanError(ValueError):
    pass


def throughput(path: str | pathlib.Path = THROUGHPUT) -> dict[str, Any]:
    return json.loads(pathlib.Path(path).read_text()) if pathlib.Path(path).exists() else {}


def member_cost(thr: dict[str, Any], cls: str) -> tuple[tuple[float, float], str]:
    """(s per batch, s per member) per mission day for a vehicle class, and where the numbers came from: bench/ or the
    labelled fallback (homebase, 2026-10-29, real TEPEX-C mission at load ~20)."""
    e = thr.get("stage1", {}).get(cls)
    if e:
        return (e["s_per_batch_day"], e["s_per_member_day"]), f"measured ({e['measured']}, {e['host']}, load {e.get('load_1min')})"
    return FALLBACK_COST[cls], "NOT MEASURED on this machine (run `make bench`): planner fallback"


def lbm_rate(thr: dict[str, Any], gpus: int) -> tuple[float, str, str]:
    """(cell-updates/s, backend name, source)."""
    if gpus > 0:
        e = thr.get("xlb-warp-gpu")
        if e:
            return e["per_device"] * gpus, "xlb-warp", f"measured ({e['measured']}, {e['device']})"
        return 0.95 * 20.8e9 * gpus, "xlb-warp", "projected from published benchmarks (FluidX3D RTX PRO 6000 20.8 GLUPS x 0.95 for XLB-Warp)"
    e = thr.get("xlb-jax-cpu") or thr.get("jax-lbm-d3q19-cpu")
    if e:
        return e["per_device"], "xlb-jax-cpu", f"measured ({e['measured']}, {e.get('device', 'cpu')})"
    return 5e6, "xlb-jax-cpu", "NOT MEASURED (run `make bench`): planner fallback"


def plan(budget: str, gpus: int, mission: dict[str, Any], thr: dict[str, Any] | None = None, gpu_mem_gb: float | None = None,
         vehicle_classes: dict[str, str] | None = None) -> dict[str, Any]:
    if budget not in BUDGET_S:
        raise PlanError(f"--budget {budget!r}: choose one of {list(BUDGET_S)}")
    if gpus < 0:
        raise PlanError("--gpus must be >= 0")
    thr = throughput() if thr is None else thr
    B = BUDGET_S[budget]
    from .config import utc
    days = (utc(mission["window"]["end"]) - utc(mission["window"]["start"])).total_seconds() / 86400
    classes = vehicle_classes or {}
    costs = {vid: member_cost(thr, c) for vid, c in classes.items()}
    per_batch = sum(c[0] for c, _ in costs.values()) * days
    per_member = sum(c[1] for c, _ in costs.values()) * days
    bs = BATCH[budget]
    n_batches = int(SHARE["stage1"] * B // max(per_batch + bs * per_member, 1e-9))
    n_max = min(N_MAX[budget], max(n_batches, 1) * bs)
    notes = []
    if n_max < N_MAX[budget]:
        notes.append(f"ensemble capped at {n_max} members by the stage-1 share of the budget ({per_batch:.0f} s per batch of {bs} "
                     f"+ {per_member:.2f} s per member)")
    n_min = min(N_MIN[budget], n_max)
    rate, backend, rate_src = lbm_rate(thr, gpus)
    K = WINDOWS[budget]
    n_win = K * len(classes)
    cells_steps = SHARE["stage3"] * B * rate / max(n_win, 1)
    les = dict(backend=backend, rate=rate, rate_source=rate_src, windows_per_vehicle=K, cell_steps_per_window=cells_steps,
               cpu_fallback=gpus == 0,
               label=("CPU fallback: XLB-JAX at the resolution this budget affords on CPU; coefficients blended with the "
                      "published/Hangar values and their spread widened" if gpus == 0 else "GPU LES windows"))
    if gpus > 0 and gpu_mem_gb:
        les["gpu_mem_gb"] = gpu_mem_gb
        les["max_cells"] = int(GPU_MEM_GUARD * gpu_mem_gb * 1e9 / 55.0)    # 55 B/cell FP16S storage (Lehmann et al. 2022)
    return dict(budget=budget, budget_s=B, gpus=gpus, days=days, n_max=n_max, n_min=n_min, batch=min(BATCH[budget], n_max),
                sitl_members=SITL[budget], member_cost={k: dict(s_per_batch_day=c[0], s_per_member_day=c[1], source=s) for k, (c, s) in costs.items()},
                les=les, refit_iterations=0 if budget == "ci" else 2, notes=notes,
                certify_possible=n_max >= 73, shares=SHARE)


def emulator_share_s(plan: dict[str, Any], stage1b_free: bool = False) -> float:
    """Seconds the emulator stage may spend: its own share of the budget, plus stage 1b's when no vehicle was refit (the rerun was a copy)."""
    return float(plan["budget_s"] * (plan["shares"]["emulator"] + (plan["shares"]["stage1b"] if stage1b_free else 0.0)))


def batch_cost_s(plan: dict[str, Any], vids: Any = None, days: float | None = None) -> float:
    """Seconds one batch of plan["batch"] members costs for the named vehicles (default: all) over `days` (default: the mission length),
    from the per-vehicle costs in the plan: what stage 1 charges per environment call plus per member."""
    mc = plan["member_cost"]
    d = plan["days"] if days is None else days
    return float(sum(mc[v]["s_per_batch_day"] + plan["batch"] * mc[v]["s_per_member_day"] for v in (mc if vids is None else vids)) * d)


def memory_guard(cells: float, bytes_per_cell: float, gpu_mem_gb: float) -> float:
    """Refuse a nest that would exceed 85 % of device memory; say what to reduce."""
    need = cells * bytes_per_cell / 1e9
    if need > GPU_MEM_GUARD * gpu_mem_gb:
        f = (GPU_MEM_GUARD * gpu_mem_gb / need) ** (1 / 3)
        raise PlanError(f"nest needs {need:.1f} GB > {GPU_MEM_GUARD:.0%} of {gpu_mem_gb} GB: coarsen each axis by "
                        f"{1 / f:.2f}x (cell size x{1 / f:.2f}), or halve the box, or use FP16 storage (55 B/cell)")
    return need


def wall_estimate(p: dict[str, Any]) -> dict[str, float]:
    mc = p["member_cost"].values()
    return dict(stage1=(-(-p["n_max"] // p["batch"]) * sum(v["s_per_batch_day"] for v in mc) + p["n_max"] * sum(v["s_per_member_day"] for v in mc)) * p["days"],
                stage3=p["les"]["cell_steps_per_window"] * p["les"]["windows_per_vehicle"] * max(len(p["member_cost"]), 1) / p["les"]["rate"])


def describe(p: dict[str, Any]) -> str:
    lines = [f"budget {p['budget']} ({p['budget_s'] / 60:.0f} min), {p['gpus']} GPU(s), {p['days']:.2f} mission days",
             f"stage 1: {p['n_min']}..{p['n_max']} members in batches of {p['batch']} "
             f"({'can' if p['certify_possible'] else 'cannot'} certify P(fail) < 5 %)"]
    for k, v in p["member_cost"].items():
        lines.append(f"  {k}: {v['s_per_batch_day']:.3g} s/batch/day + {v['s_per_member_day']:.3g} s/member/day, {v['source']}")
    L = p["les"]
    lines.append(f"stage 3: {L['windows_per_vehicle']} window(s)/vehicle on {L['backend']} at {L['rate']:.3g} cell-updates/s "
                 f"({L['rate_source']}); {L['cell_steps_per_window']:.3g} cell-updates per window")
    lines += p["notes"]
    return "\n".join(lines)

