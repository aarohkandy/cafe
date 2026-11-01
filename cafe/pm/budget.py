"""`--budget {ci,quick,4h,overnight}` -> how big every stage is on THIS machine, from config/throughput.json (bench/).

The contract is wall-clock, not a fixed machine: the same mission and budget give a small plan on an 8-vCPU box with no
GPU and a large one on a GPU server, from that machine's measured rates. Every number the plan used is in the plan
(and so in the report), with where it came from.

Nothing here or in the stages is sized from elapsed time: every amount of work that affects a result (LES window cells and steps, the
free-surface go/no-go, the number of emulator variants) comes from this plan, so two runs with the same seed on the same machine bench make
the same report. `plan["stage3"]` and `plan["emulator"]` hold those sizes. The wall clock is only a safety kill that turns a late window
into a row that says it was killed.

Shares of the budget: stage 1 (members x vehicle-days x the measured member cost), stage 3 (LES windows: cells x steps / measured LBM
rate; FEA and interFoam on CPU in parallel), stage 1' (the refit rerun), the emulator (`SHARE`; they sum to 0.95, the rest is slack for the
report). The ingest is NOT in any share and `--budget` does not count it: a cold fetch is a network job whose length is the lab link's (RUNBOOK 4),
a warm cache costs seconds. A plan that would not fit is shrunk (members, then windows, then nest resolution) and says so. Stage 1 never
overruns its share: when a batch of the profile's size does not fit it is halved down to `MIN_BATCH` members, and when even that does not fit `plan` refuses
(`PlanError`) with the shortfall in seconds.

On `--gpus 0` a LES window whose physical lattice viscosity (stage3.nu_lat_floor) needs more than `stage3.skip_factor` times the cell-updates its
slice affords is not run (`les_windows`): it could only fail the viscosity_floor check, so its slice goes back to stage 1 at plan time.
"""
from __future__ import annotations

import json, math, pathlib
from collections import Counter
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
EMULATOR_VARIANTS = {"ci": 2, "quick": 6, "4h": 24, "overnight": 48}   # most mission variants (a batch of every vehicle each) per run ...
EMULATOR_REACH = ("4h", "overnight")                                   # ... except on these, where the cap is the count that reaches EMULATOR_MIN_POINTS
EMULATOR_MIN_POINTS = 100         # distinct feature points per vehicle class the emulator needs to train (whatif.MIN_ROWS reads this)
EMULATOR_POINTS_MARGIN = 1.2      # variants are sized for this many times the minimum (a skipped variant or a repeated point still leaves enough)
TRAIN_FRAC = 0.7                  # of the emulator share the variant runs may use; the rest is for the flip search's Stage-1 fallback
STAGE3_PARTS = {"glider": ("body",), "usv": ("hull", "wing"), "uas": ("body",)}     # the native-LBM parts of a window, one slice of the share each
FS_PARTS = {"usv": "hull_fs"}                                                        # the free-surface part: a child process with its own queue
FEA_CLASSES = ("glider",)                                                            # classes whose window carries an FEA of the pressure hull
FALLBACK_COST = {"glider": (8.0, 0.1), "usv": (11.0, 0.1), "uas": (20.0, 0.3)}   # (s per batch, s per member) per mission day without bench
GPU_MEM_GUARD = 0.85
LES_BYTES_PER_CELL = 55.0         # FP16S storage (Lehmann et al. 2022), the figure `les["max_cells"]` and the memory guard use
NOMINAL_WINDOW = {("glider", "body"): ("nominal.glider", "water"), ("usv", "hull"): ("nominal.usv_hull", "water"),   # (stage3.* key of [speed, length], fluid)
                  ("usv", "wing"): ("nominal.usv_wing", "air"), ("uas", "body"): ("nominal.uas", "air")}
MIN_BATCH = 4                     # members: the smallest stage-1 batch the planner will shrink to (below it an ensemble has no spread worth reporting)
LOAD_WARN_FRAC = 0.25             # x cpus: a rate measured with more 1-min load than this (2 on 8 CPUs) was contended by other work


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
        e = thr.get("jax-lbm-d3q19-gpu")                                   # the key `bench/throughput.py lbm gpu` saves under
        if e:
            return e["per_device"] * gpus, "native-jax-gpu", f"measured ({e['measured']}, {e['device']})"
        return 0.95 * 20.8e9 * gpus, "xlb-warp", "projected from published benchmarks (FluidX3D RTX PRO 6000 20.8 GLUPS x 0.95 for XLB-Warp)"
    e = thr.get("jax-lbm-d3q19-cpu")
    if e:
        return e["per_device"], "native-jax-cpu", f"measured ({e['measured']}, {e.get('device', 'cpu')})"
    return 5e6, "native-jax-cpu", "NOT MEASURED (run `make bench`): planner fallback"


def measurement_warnings(thr: dict[str, Any], classes: dict[str, str], mission: dict[str, Any]) -> list[str]:
    """Why the stage-1 costs in `thr` may not describe this run: measured with other work on the machine (1-min load above
    LOAD_WARN_FRAC x cpus) or on another mission. The costs are still used; the plan says so."""
    out: set[str] = set()
    for cls in set(classes.values()):
        e = thr.get("stage1", {}).get(cls)
        if not e:
            continue
        load, cpus = e.get("load_1min"), e.get("cpus")
        if load is not None and cpus and load > LOAD_WARN_FRAC * cpus:
            out.add(f"stage-1 costs were measured at load {load:.1f} on {cpus} CPUs (above {LOAD_WARN_FRAC * cpus:g}): contended, so the plan is "
                    "pessimistic; re-run `python bench/throughput.py stage1` on a quiet machine")
        on = e.get("mission_name") or pathlib.Path(e.get("mission", "")).stem
        if on and mission.get("name") and on != mission["name"]:
            out.add(f"stage-1 costs were measured on mission {on!r}, not {mission['name']!r}: re-run `python bench/throughput.py stage1 <mission>`")
    return sorted(out)


def les_need(speed: float, length: float, fluid: str, a: dict[str, Any]) -> dict[str, float]:
    """The smallest LES window that reaches the physical lattice viscosity: lattice viscosity at fixed lattice speed is nu U_LAT / (U dx), so
    `stage3.nu_lat_floor` needs dx <= nu U_LAT / (U floor); the box of `stage3.box_bodies` body lengths at that dx, run for the shortest
    acceptable time (`stage3.min_flow_throughs` box transits). -> dx, cells, steps, cell_steps (cells x steps)."""
    from .stage3 import lbm, windows
    dx = windows.NU[fluid] * lbm.U_LAT / (speed * a["nu_lat_floor"])
    cells = math.prod(max(8, math.ceil(b * length / dx)) for b in a["box_bodies"])
    steps = math.ceil(a["min_flow_throughs"] * max(8, math.ceil(a["box_bodies"][0] * length / dx)) / lbm.U_LAT)
    return dict(dx=dx, cells=float(cells), steps=float(steps), cell_steps=float(cells) * steps)


def part_cell_steps(rate: float, slice_s: float, cls: str, a: dict[str, Any]) -> float:
    """Cell-updates a LES part of class `cls` is planned for in a wall-clock slice: the slice less the XLA compile guess and (glider) the FEA
    reserve, over `stage3.les_margin`, at the LBM rate."""
    return float(rate * max(slice_s - (a["fea_reserve_frac"] * slice_s if cls in FEA_CLASSES else 0.0) - a["compile_s_guess"], 0.0) / a["les_margin"])


def les_windows(budget: str, gpus: int, classes: dict[str, str], rate: float, share_s: float, K: int, a: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per LES part `<vehicle id>/<part>`: what its window needs for the physical lattice viscosity (`les_need` at the nominal speed and length of
    `stage3.nominal.*`), what its slice affords at `rate`, `reachable` (need <= afford) and `runs`. With `gpus` 0 a window needing more than
    `stage3.skip_factor` x its affordance is not run (`skip_reason` says what it needed and what the machine does); `ci` keeps its first
    window as a smoke path (`smoke`) so the code is still exercised. A GPU plan never skips. Deterministic: plan inputs only."""
    parts = [(vid, c, part) for vid, c in classes.items() for part in STAGE3_PARTS[c]]
    slice_s = share_s / max(K * len(parts), 1)
    out: dict[str, dict[str, Any]] = {}
    for vid, c, part in parts:
        key, fluid = NOMINAL_WINDOW[(c, part)]
        speed, length = a[key]
        n, afford = les_need(speed, length, fluid, a), part_cell_steps(rate, slice_s, c, a)
        runs = gpus > 0 or n["cell_steps"] <= a["skip_factor"] * afford
        out[f"{vid}/{part}"] = dict(reachable=bool(n["cell_steps"] <= afford), runs=bool(runs), smoke=False, need_cell_updates=n["cell_steps"],
                                    afford_cell_updates=afford, cells_physical=n["cells"], dx_physical_m=n["dx"],
                                    nominal_speed_ms=speed, nominal_length_m=length,
                                    skip_reason=None if runs else (
                                        f"not run: the physical lattice viscosity (stage3.nu_lat_floor {a['nu_lat_floor']:g}) needs dx {n['dx'] * 1e3:.2g} mm, "
                                        f"{n['cells']:.2g} cells and {n['cell_steps']:.2g} cell-updates; this machine does {afford:.2g} in the window's "
                                        f"slice at {rate:.2g} cell-updates/s ({n['cell_steps'] / max(afford, 1.0):.2g}x short, skipped beyond "
                                        f"{a['skip_factor']:g}x); "
                                        "the window could only fail viscosity_floor, so its share went to stage 1"))
    if budget == "ci" and out and not any(w["runs"] for w in out.values()):         # one window stays so CI exercises the stage
        first = next(iter(out.values()))
        first.update(runs=True, smoke=True, skip_reason=None)
    return out


def fs_plan(classes: dict[str, str], K: int, a: dict[str, Any], share: float | None) -> dict[str, Any] | None:
    """The free-surface cases (`K` per USV): priced once, `fit` of them fit `share` (all, with no wall-clock budget). None without any case, or
    when the FluidX3D plugin replaces interFoam."""
    cases = K * sum(1 for c in classes.values() if c in FS_PARTS)
    if not cases:
        return None
    from .stage3 import fluidx3d, freesurface
    if fluidx3d.available(freesurface.fluidx3d_config())[0]:
        return None
    est = freesurface.estimate(freesurface.nproc(), a["fs.snappy_cell_factor"], a["fs.cost_factor"], a["fs.mesh_s_per_cell"])
    need = float(est["total_s"] * a["fs.margin"])
    return dict(cases=cases, estimate=est, margin=a["fs.margin"], need_s=need, share_s=share, fit=cases if share is None else int(min(cases, share // need)))


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
    rate, backend, rate_src = lbm_rate(thr, gpus)
    K = WINDOWS[budget]
    a = stage3_assumptions()
    wins = les_windows(budget, gpus, classes, rate, SHARE["stage3"] * B, K, a)
    shares, skipped_s = dict(SHARE), 0.0
    if wins and not all(w["runs"] for w in wins.values()):                      # the slices of the windows that do not run go back to stage 1 ...
        s3 = SHARE["stage3"] * B
        kept = s3 * sum(w["runs"] for w in wins.values()) / len(wins)
        fs = fs_plan(classes, K, a, s3)                                         # ... but the free-surface cases keep what they fit in the whole share
        kept = max(kept, 0.0 if fs is None else fs["fit"] * fs["need_s"])
        skipped_s = s3 - kept
        shares.update(stage3=kept / B, stage1=SHARE["stage1"] + skipped_s / B)
    share1 = shares["stage1"] * B
    bs = BATCH[budget]
    while bs >= MIN_BATCH and per_batch + bs * per_member > share1:       # the batch must fit the share: halve it until it does
        bs //= 2
    if bs < MIN_BATCH:
        need = per_batch + MIN_BATCH * per_member
        raise PlanError(f"--budget {budget}: stage 1 needs {need:.0f} s for even one batch of {MIN_BATCH} members ({per_batch:.0f} s per environment "
                        f"call over {days:.2f} mission days + {per_member:.2f} s per member) but its share of the {B} s budget is {share1:.0f} s: "
                        f"short by {need - share1:.0f} s. Use a longer --budget, a shorter mission window or fewer vehicles")
    n_batches = int(share1 // max(per_batch + bs * per_member, 1e-9))
    n_max = min(N_MAX[budget], n_batches * bs)
    notes = measurement_warnings(thr, classes, mission)
    if bs < BATCH[budget]:
        notes.append(f"stage-1 batch shrunk from {BATCH[budget]} to {bs} members: a batch of {BATCH[budget]} costs "
                     f"{per_batch + BATCH[budget] * per_member:.0f} s against a stage-1 share of {share1:.0f} s")
    if n_max < N_MAX[budget]:
        notes.append(f"ensemble capped at {n_max} members by the stage-1 share of the budget ({per_batch:.0f} s per batch of {bs} "
                     f"+ {per_member:.2f} s per member)")
    n_min = min(N_MIN[budget], n_max)
    reachable = any(w["reachable"] for w in wins.values())
    nowhere = gpus == 0 and bool(wins) and not reachable
    if nowhere:
        notes.append(f"stage 3: no LES coefficients exist on this machine: {sum(not w['runs'] for w in wins.values())} of {len(wins)} window part(s) are not "
                     f"run (their physical lattice viscosity is out of reach of {rate:.2g} cell-updates/s) and {skipped_s:.0f} s of the budget went "
                     "to stage 1; "
                     "the sub-grid layer and the refit stay uncalibrated")
    les = dict(backend=backend, rate=rate, rate_source=rate_src, windows_per_vehicle=K,
               cell_steps_per_window=SHARE["stage3"] * B * rate / max(K * len(classes), 1),
               cpu_fallback=gpus == 0, windows=wins,
               label=("GPU LES windows" if gpus > 0 else
                      "CPU fallback: no LES coefficients exist on this machine (no window reaches the physical lattice viscosity with this "
                      "budget's cell-updates); "
                      "sub-grid and refit stay uncalibrated" if nowhere else
                      "CPU fallback: native JAX lattice kernel at the resolution this budget affords on CPU; coefficients are the pooled "
                      "window coefficient over the vehicle's Hangar-model value"))
    if gpus > 0 and gpu_mem_gb:
        les["gpu_mem_gb"] = gpu_mem_gb
        les["max_cells"] = int(GPU_MEM_GUARD * gpu_mem_gb * 1e9 / LES_BYTES_PER_CELL)
    p: dict[str, Any] = dict(budget=budget, budget_s=B, gpus=gpus, days=days, n_max=n_max, n_min=n_min, batch=min(bs, n_max),
             stage1_s=-(-n_max // min(bs, n_max)) * per_batch + n_max * per_member, stage1_share_s=share1,
             sitl_members=SITL[budget], member_cost={k: dict(s_per_batch_day=c[0], s_per_member_day=c[1], source=s) for k, (c, s) in costs.items()},
             les=les, refit_iterations=0 if budget == "ci" else 2, notes=notes, certify_possible=n_max >= 73, shares=shares, vehicle_classes=dict(classes))
    em = emulator_plan(p)
    if not em["trains"]:
        p["notes"].append(em["note"])
    return p


def stage3_assumptions() -> dict[str, Any]:
    """config/assumptions.yaml keys `stage3.*` -> {short key: value}."""
    from .config import assumptions
    return {k[len("stage3."):]: v["value"] for k, v in assumptions().items() if k.startswith("stage3.")}


def stage3_plan(p: dict[str, Any], classes: dict[str, str], a: dict[str, Any]) -> dict[str, Any]:
    """The sizes of stage 3, from the plan and the assumptions only (never from elapsed time).

    The stage's share of the budget is split evenly over its LES parts that run (`STAGE3_PARTS` of each class, `windows_per_vehicle` windows
    each; `les_windows` marks the CPU windows that cannot reach the physical lattice viscosity as not run, and `plan` has already given their
    slices to stage 1). A part's run gets its slice less the FEA reserve (classes in FEA_CLASSES) and the XLA compile guess, divided by
    `stage3.les_margin`, at the plan's LBM rate: `cell_steps_per_part[class]`, which `pipeline_windows.fit_window` turns into dx and steps.
    `runs` says whether the slice reaches `stage3.min_window_s`; `fea.runs` whether the reserve reaches `stage3.fea_min_s`. `fs` prices the
    free-surface cases (None without any, or when the FluidX3D plugin replaces interFoam): the first `fit` of `cases` fit the share, in queue
    order. `les` is `reachable` (any window reaches the physical viscosity), its `windows` and a `note`; a plan with `max_cells` (GPU memory
    known) is refused (`memory_guard`) when a window's planned nest is over 85 % of it. A plan with no wall-clock budget (`shares`/`budget_s`
    absent) uses `les.cell_steps_per_window` shared between the parts."""
    les = p["les"]
    K = les["windows_per_vehicle"]
    cls = set(classes.values())
    wins = les.get("windows") or {}
    n_les = K * sum(1 for vid, c in classes.items() for part in STAGE3_PARTS[c] if wins.get(f"{vid}/{part}", dict(runs=True))["runs"])
    share = float(p["shares"]["stage3"] * p["budget_s"]) if "shares" in p and "budget_s" in p else None
    slice_s = None if share is None else share / max(n_les, 1)
    fea_s = 0.0 if slice_s is None else a["fea_reserve_frac"] * slice_s
    per_part: dict[str, float] = {}
    for c in sorted(cls):
        per_part[c] = float(les["cell_steps_per_window"] / len(STAGE3_PARTS[c])) if slice_s is None else part_cell_steps(les["rate"], slice_s, c, a)
    if les.get("gpu_mem_gb"):
        for w in wins.values():
            if w["runs"]:
                memory_guard(w["cells_physical"] * min(1.0, w["afford_cell_updates"] / w["need_cell_updates"]) ** 0.75, LES_BYTES_PER_CELL, les["gpu_mem_gb"])
    fs = fs_plan(classes, K, a, share)
    reachable = any(w["reachable"] for w in wins.values())
    return dict(share_s=share, windows_per_vehicle=K, les_parts=n_les, slice_s=slice_s, min_window_s=a["min_window_s"],
                runs=n_les == 0 or slice_s is None or slice_s >= a["min_window_s"], compile_s=a["compile_s_guess"], les_margin=a["les_margin"],
                fea=dict(reserve_frac=a["fea_reserve_frac"], reserve_s=fea_s, min_s=a["fea_min_s"], runs=slice_s is None or fea_s >= a["fea_min_s"]),
                cell_steps_per_part=per_part, fs=fs,
                les=dict(reachable=reachable, windows=wins,
                         note=("no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated"
                               if wins and not reachable and les["cpu_fallback"] else None)))


def emulator_plan(p: dict[str, Any]) -> dict[str, Any]:
    """How many variant runs the emulator stage makes, from the plan only: a variant costs `batch_cost_s(plan)` (the planner's estimate from
    the measured per-vehicle costs), the variants may use `TRAIN_FRAC` of the stage's share, and at most EMULATOR_VARIANTS[budget] (on
    `EMULATOR_REACH` budgets: the count that gives the smallest class `EMULATOR_MIN_POINTS` x `EMULATOR_POINTS_MARGIN` points). Two answers
    because the share is bigger by stage 1b's when no vehicle was refit (the rerun was a copy): `variants_refit`, `variants_no_refit`.
    A variant adds one feature point per vehicle, so a class of n vehicles has (variants + 1) n points after one run (`points_per_class`, best
    case); `trains` is False, with the numbers in `note`, when that is under `EMULATOR_MIN_POINTS` for any class: the run alone cannot train an
    emulator, rows must accumulate over runs of one code digest (whatif.add_rows) or the budget must be bigger."""
    est = batch_cost_s(p)
    per_class = Counter(p.get("vehicle_classes", {}).values())
    smallest = min(per_class.values(), default=1)
    cap = max(math.ceil(EMULATOR_MIN_POINTS * EMULATOR_POINTS_MARGIN / smallest) - 1, 0) if p["budget"] in EMULATOR_REACH else EMULATOR_VARIANTS[p["budget"]]

    def n(free: bool) -> int:
        return int(min(cap, TRAIN_FRAC * emulator_share_s(p, free) // est)) if est > 0 else 0       # (a denormal est: // is inf)
    refit, no_refit = n(False), n(True)
    best = max(refit, no_refit)
    points = {c: (best + 1) * k for c, k in sorted(per_class.items())} or {"": best + 1}
    short = {c: v for c, v in points.items() if v < EMULATOR_MIN_POINTS}
    avail = f"{TRAIN_FRAC:.0%} of a {emulator_share_s(p, True):.0f} s emulator share"
    note = (f"the emulator cannot train at this budget: one mission variant costs {est:.0f} s of stage 1 and the variants may use {avail}, so "
            f"{best} of {cap} variants run" if best == 0 else
            f"this budget gives {min(points.values())} distinct points per vehicle class in one run ({best} variants of {est:.0f} s + the base mission, "
            f"{avail}), {EMULATOR_MIN_POINTS} are needed: the emulator will not train from this run alone; rows accumulate in the training table "
            "across runs of the same code digest")
    return dict(variant_s=est, variant_s_source="the planner's estimate from the measured per-vehicle costs (plan.json member_cost)",
                share_s=dict(refit=emulator_share_s(p, False), no_refit=emulator_share_s(p, True)), train_fraction=TRAIN_FRAC,
                max_variants=cap, variants_refit=refit, variants_no_refit=no_refit, min_points=EMULATOR_MIN_POINTS, points_per_class=points,
                trains=not short, note=note)


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

