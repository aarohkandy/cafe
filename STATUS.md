# STATUS — cafe against the pre-mission multilevel spec

Audit of 2026-10-28. "done / partial / missing" per spec section, citing code. Decisions that keep an existing
choice over the spec are in `DECISIONS.md`.

**Hardware reality (read first).** The spec's hard requirement is "under 1 h on 8×H100". The compute here is
`homebase`: 8 vCPU, no GPU, and the Azure subscription has GPU quota 0 everywhere (a quota request is in
progress, see below). Everything below is built and measured on CPU, with the backend as a config switch.
Until a GPU node exists, any GPU number is a projection from the benchmark, labelled as one.

**Checkpoint (2026-10-28):** steps 1–3 of section 10 done (this audit, `bench/`, `cafe/planner.py`).
On track for step 4 (L1 ingestion fixes); see the bottom of this file.

## 1. What the system does

| | |
|---|---|
| **done** | Three drone kinds flying one mission on one clock: quad (`uav`), boat (`usv`), buoyancy glider (`uuv`, layout `glider`) — `mission.World`, `vehicle.default_actuators`. Failure probabilities with Wilson 90 % intervals over Monte Carlo runs: battery empty / under reserve, out of range, below rated depth, seafloor, aground, capsized, out of time — `mission._summary`, `mission._fleet`, `mission._rate`. |
| **partial** | Controller saturation is measured (`Drone.sat`, `mission.tick`) but not reported as a failure mode. Structural loads are checked once per design at characterization (`hangar`, `fea`), not over the mission. |
| **missing** | Saildrone (wind-propelled surface drone with a sail). Attitude-exceedance and structural-load-exceedance failure modes. High-fidelity loads at the worst moments (hull pressure, mast stress). HR: under 1 h on 8×H100 (no GPU, see above). |

## 2. Nested levels in space

| | |
|---|---|
| **done** | L1 read-only and one-way: WRF wind (`env.Env`), HYCOM 3-D currents + seafloor (`ocean.currents`), in-situ seawater density by TEOS-10 (`gsw`) from HYCOM temperature and salinity (`ocean.temp_salt`, `env.Env._density`; one HYCOM snapshot nearest the start, held for the mission, fetched on the first underwater lookup so charts and quad-only missions don't wait for it), used for buoyancy per Monte Carlo run (`dyn.Dynamics.step`); gliders are ballasted neutral for the water at their launch point (`mission.World`). Falls back to 1025 kg/m³, labelled in the run's sources, when HYCOM is down. At TEPEX (2023-03-07) the column runs 1021.8 kg/m³ at the surface to 1026.5 at 100 m. WW3 waves (`ocean.waves`). Grid-relative winds rotated with COSALPHA/SINALPHA (`env.Env.__init__`). Lat/lon → local north-east metres (`mission.Frame`). Log wind profile below 10 m with Charnock z₀ = 0.011 u*²/g (+ smooth-flow term) (`env.Env.at`). Linear time interpolation between L1 outputs (`env.Env.surface`). |
| **partial** | Waves: random-phase linear superposition of 40 JONSWAP components seeded from WW3 Hs/Tp/direction (`env.Waves`) — not phase-resolved HOS. Vertical coordinates: only WRF surface fields are read (no 3-D atmosphere yet), HYCOM is already on z-levels; nothing needs sigma/hybrid conversion today, but nothing handles it either. |
| **missing** | L2a/L2b moving LES nests, synthetic inflow turbulence, sponge zones, whole-cell nest shifts, refinement-ratio enforcement, free surface across levels, subcycling L3/L2/L1. Staggered-grid handling (not needed for U10/V10; needed once 3-D WRF U/V are read). |

## 3. Zooming in time

| | |
|---|---|
| **done** | Stage 1 ensemble, in effect: `mission.run` flies 16–64 batched Monte Carlo runs of a Fossen 6-DOF (`dyn.Dynamics`, `M ν̇ + C ν + D ν + g = τ` about the CoG) with relative velocity throughout (`dyn.Dynamics.step`, `v_r`). Varies weather error, CFD uncertainty, propulsion and battery spread. Dryden gusts (`env.Gusts`). |
| **partial** | Gust intensity comes from U10 (MIL-HDBK-1797 low-altitude form), not calibrated from L2. One L1 start state per mission, perturbed — not several L1 starting states. |
| **missing** | Worst-moment extraction, stage 2 (L2 full mission), stage 3 (L3 + FEA windows), refitting coefficients from window forces, configurable event triggers, the "probabilities and conditions, not a timeline" report wording for gusts. |

## 4. Drone models

| | |
|---|---|
| **done** | 6-DOF rigid body, semi-implicit Euler (velocities then pose) for every vehicle (`dyn.Dynamics.step`) — satisfies the HR for the glider and submerged hulls. Quadratic drag on relative velocity from CFD tables (`dyn.Dynamics.drag`), BEM added mass (`hangar.bem`), panel buoyancy/gravity + Froude–Krylov wave forces (`dyn.Dynamics.panel_forces`), thrust maps, never blades (`vehicle.prop_perf`). Real firmware in lockstep: ArduCopter / ArduRover / ArduSub SITL over the JSON backend, the sim answers each servo packet (`emulator.Sim`). |
| **partial** | Multirate: per-vehicle step (`mission.PHYS_DT`): quad 2.5 ms (ArduCopter's 400 Hz rate loop, HR met), boat/sub 20 ms, glider 60 ms; one shared 20 ms clock. Air/water blending: panel hydrostatics integrate only the wetted panels, windage is separate; no single submerged-fraction blend. Sensor model: SITL gets truth (`emulator.Sim.reply`), no IMU noise/bias, GPS, depth, airspeed models; no actuator lag beyond motor τ (`vehicle.TAU_MOTOR`). Structure: CalculiX static/buckling/modal at characterization (`fea`, `hangar`), quad-frame modes reported. Glider firmware: ArduSub has no fin/buoyancy control, so gliders and finned AUVs use the built-in controller (`ctrl.Autopilot._glider`) — a stub in the spec's sense. |
| **missing** | Craig–Bampton reduced modal model every step. FEA from L3 pressures in event windows. Sail FSI flag. Actuator-disk/BEM propeller in L3. Saildrone vehicle + ArduRover sailboat firmware. |

## 5. Resolution planner — **done (CPU-measured)**

`cafe/planner.py`: cost = T·U·V/(CFL·Δx⁴) per level, solved for Δx from budget × share × throughput × devices,
clamped to ≤10× between adjacent levels. Reads `bench/throughput.json`. `python -m cafe.planner --check` asserts the
invariants and the spec's air/ocean reference rows at 10⁹ cell-updates/s/GPU (they are one L2a-sized nest per medium with
20 % of the budget: 1.7 m / 0.5 m on 8 GPUs, 0.6 m / 0.18 m on 512). The spec's hull rows (5 mm, 1 cm, 2 mm) are **not**
reproduced: the graded L3 here gives 9.3 mm, 6.3 mm, 3 mm, and the spec's L3 cost model isn't on disk to compare.
(Earlier versions of this file said the whole table was reproduced; the check only printed it.) Output on homebase: bottom of this file.

## 6. Throughput benchmark — **done (CPU)**

`bench/throughput.py`, run on homebase 2026-10-28 with the box otherwise idle (an earlier pass overlapped other
load and read 10–15 % low at 4–8 cores). Results in `bench/throughput.json`:

| Solver | 1 core | 2 | 4 | 8 |
|---|---|---|---|---|
| OpenFOAM v2506 `pimpleFoam` LES, 100³ | 4.64e4 | 8.64e4 | 1.42e5 | 1.65e5 cell-updates/s (44 % efficiency 1→8) |
| JAX D3Q19 LBM + Smagorinsky, 128³, one process | | | | 7.53e6 (whole CPU) |

The 4→8 step gains only 16 %: the 8 vCPUs are 4 physical cores with SMT. LBM vs OpenFOAM is **not** 46× per simulated
second: an LBM step is acoustically limited (lattice velocity 0.05 here), so it needs ~20× more steps than a CFL-1
step for the same physical time, so ~2× better. The planner's `cfl` is one number for every solver, so it must be set to
~0.05 before planning with the LBM entry. The LBM kernel never ran before this date (a jit bug in the
roll shifts); earlier versions of this file called it measured. No GPU measurement exists; 1→8 GPU scaling is still missing.

## 7. Config and run interface

| | |
|---|---|
| **done** | A run is restartable at the design level (characterization cached by mesh bytes, `cfd.cached`). |
| **partial** | Missions are files (`mission.json`) and run through the worker queue (`worker.py`); `lab/check.py` runs a fleet file end to end. Many thresholds still live in code (`mission.SIG`, `PHYS_DT`, verdict cut-offs in `mission._verdict`). |
| **missing** | `run_premission --mission --budget --gpus` entry point, stage checkpoints, per-stage wall-clock logging against budget, shrinking event windows on overrun. |

## 8. Report

| | |
|---|---|
| **done** | Per-drone and per-link probabilities with intervals, reasons and "what would pass" advice (`mission._advice`, `Link.advice`); interactive replay in the web UI; validation report from receipts (`report/build.py`). |
| **missing** | Single per-mission HTML/Markdown report with risk timeline, event-window details, resolution and budget used, calibrated-vs-assumed caveats. |

## 9. Validation

| | |
|---|---|
| **done** | `cafe/receipts.py` (each can fail): REMUS area/drag vs Prestero, Wigley resistance vs Kajitani, SUBOFF side force/yaw moment vs Roddy 1990, Wigley free-roll period vs linear hydrostatics, Lamb spheroid and strip-theory added mass, Bresse long-tube collapse, beam-theory stresses, Dryden σu/σw ratio, Hs reproduction, Zermelo reach, link geometry, HYCOM node match, WRF time interpolation. Planner self-check (air/ocean rows asserted). Quad time-step convergence, 2.5 vs 1.25 ms (receipt "Time step"). |
| **missing** | Unit tests for grid rotation / vertical interpolation as standalone tests (TEOS-10 has receipts: EOS-80 check values, a HYCOM grid node); nest conservation; wave through an L2/L3 boundary; sphere drag over Re; sphere added mass (½ρV) as a separate receipt; −5/3 slope of L2 spectra; field telemetry comparison (no telemetry yet); timed end-to-end on 8 GPUs. |

## 10. Progress against the order of work

| Step | State |
|---|---|
| 1 Audit | done (this file, `DECISIONS.md`) |
| 2 Throughput benchmark | done on CPU; GPU pending hardware |
| 3 Resolution planner | done |
| 4 L1 ingestion fixes | quad step 2.5 ms and TEOS-10 density done; next: standalone unit tests (grid rotation, vertical interpolation) |
| 5 Reduced models + multirate + ensemble | mostly exists (`mission`, `dyn`); needs saildrone, worst-moment extraction, attitude/saturation/load failure modes |
| 6–11 | not started |

## Planner output on homebase (measured OpenFOAM rate, `python -m cafe.planner`)

```
8 x cpu, openfoam-pimpleFoam-les: 1.65e+05 cell-updates/s (measured on 8 x cpu core, 2026-10-28)
budget 60 min, mission 3.0 h, shares {'L2a': 0.1, 'L2b': 0.2, 'L3': 0.3}
  air   L1 1.2e+04 m -> bridges 1.2e+03 m -> L2a 120 m -> L2b 12 m  (coarsened to 10x L2a)
  ocean L1 9e+03 m -> bridges 900 m -> 90 m -> L2a 18 m -> L2b 3.67 m
  L3 aerial    full mission 50 cm | event windows 8.8 cm, 6.0 min, 2 bands, BL shell 1.4 cm
  L3 saildrone full mission 1.68 m | event windows 6.9 cm, 6.0 min, 5 bands, BL shell 9.7 cm
  L3 glider    full mission 34 cm | event windows 1.9 cm, 6.0 min, 5 bands, BL shell 4.8 cm
  planned CFD wall time 33.9 min of 60
```

So in one hour this box can't resolve a hull: the event-window cells (2–9 cm) are coarser than each hull's boundary layer
(1.4–9.7 cm). The spec's 8×H100 assumption is 8e9 cell-updates/s, ~48,000× this box, which is ~15× finer cells.
