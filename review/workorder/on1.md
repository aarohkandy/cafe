# on1: the first `--budget overnight --gpus 0` run (work order step 1, a measurement)

`missions/tepex_c_demo.yaml`, `--budget overnight --gpus 0 --fresh`, orca (proot, 6 CPUs, 48g), code `8ecf0e7`, started 2026-11-20 07:26 UTC, `rc=0`. Read with `review/workorder/on1read.py` and `on1v.py` (run in `pm_on1`). Not strictly alone: from stage 3 on, up to five builder test jobs of 2 CPUs each ran beside it on other cores, so the walls below are upper figures.

## Time
10,003 s over hangar to emulator, of the 36,000 s budget (0.28). Stage walls: ingest 40 s, stage 1 393 s (planned 142 s), stage 3 1,496 s, stage 1b 138 s, emulator 7,972 s, report 58 s.

## Verdicts at 512 members against q25 at 64
No verdict changed.

| | on1 (k of 512) | q25 (k of 64) |
|---|---|---|
| glider_eq | MARGINAL, 140 | MARGINAL, 15 |
| glider_2n | GO, 0 | GO, 0 |
| usv | NO-GO, 467 | NO-GO, 61 |
| uas | NO-GO, 499 | NO-GO, 62 |
| usv-uas-rf, both acoustic links | NO-GO, 512 | NO-GO, 64 |
| usv-shore-iridium | GO, 0 | GO, 0 |

## CFD
- 15 LES window parts: none run (the lattice viscosity is 1.2e4 to 8.5e10 times out of reach of 7.5e6 cell-updates/s).
- Free-surface USV hull (`hull_fs`, interFoam, two grids, 6 cores): 1 of 3 cases ran (the other two "0.0 min left of the 118 min stage-3 share", though the first took 1,496 s of its planned 5,660 s). **It failed two of its three checks:** `fs_gci` 1.93 (limit 0.10), `fs_iterative_scatter` 0.487 (limit 0.02); `fs_refinement_ratio` 1.436 passed. cd 0.100 with spread 0.200 against `cd_hangar` 0.053.
- So `refit.json` has `used: false` for all four vehicles and `refit_iterations_performed` is 0: every verdict is still the analytic model's.

## FEA
None ran (it is called only inside a glider LES window). The Seaglider's hull warning prints (330.6 m against the 950 m order).

## Emulator
- 99 of the 119 planned variants ran before the 7,200 s share ended (planned 36 s a variant, measured 62 to 84 s); 106 points in each scope, 100 needed.
- `uas/quad_uas/144h`: trained and **passed its gate** (RMSE and coverage ok); five of the UAS's fix candidates were answered EMULATED.
- `usv/saildrone_explorer/144h`: trained, missed coverage (`t_fail_h` and one mode at 0.905 against the chance band); Stage 1 answers.
- `glider/seaglider/144h`: trained, missed RMSE (0.069 against 0.059) and coverage; Stage 1 answers.
- `glider/slocum/144h`: not trained: P(fail) is 0 in all 107 rows, nothing to learn.
- The plan's own note is wrong at this budget: it says 120 points and then "the emulator will not train from this run alone" in the same sentence (`plan.json` `emulator.note`, `trains: true`).

## What this run settles for the work order
- Done item 3 (an emulator that trains, passes its gate and answers) holds for the UAS, on this code digest. The command `whatif --run /data/runs/on1 --shift 30h` (job `on1_whatif`, `rc=0`, from the unchanged `8ecf0e7` tree) answered the UAS as `[EMULATED, training-set distance 0.72 of limit 2.49]`: NO-GO (P(fail) 0.961) to NO-GO (0.981, 0.939 to 0.994), not distinguishable from the baseline. The other three vehicles were answered by Stage 1, each with its emulator's reason.
- Done items 1 and 2 need code: the USV hull CFD exists but does not converge as configured; glider CFD and CPU FEA do not exist yet.
- The two idle `hull_fs` cases show the stage-3 gate counts the planned seconds of a case, not the measured ones.

# rans_g1: one CPU RANS case of the demo Seaglider (work order step 3, the probe)

`review/workorder/rans_probe.py --cores 6` on orca (job `rans_g1`, `rc=0`, 2026-11-20 20:05 UTC; `/data/runs/rans_probe/result.json`). The stage-3 glider geometry (ellipsoid hull and plate wing, 1.8 x 1.0 x 0.3 m), body-frame flow `x-z5.29` at 0.135 m/s, simpleFoam k-omega SST.

| grid | cells | failed mesh checks | iterations | seconds | drag (N) | cd |
|---|---|---|---|---|---|---|
| coarse (14 mm) | 108,837 | 0 | 146 (converged) | 31 | 0.2366 | 0.357 |
| fine (7 mm) | 316,218 | 0 | 1,500 (the cap) | 417 | 0.2582 | 0.390 |

Refinement ratio 1.427; GCI 0.243 (the free-surface part's limit is 0.10); norm of the force's std over the drag on the fine grid 0.084 (almost all of it in the lift component). `cd_hangar` 0.301, so cd / cd_hangar is 1.29: the CFD drag is above the analytic one, not below it. Total 448 s.

What it settles: a case costs minutes, not hours, and both meshes are valid; this pair of grids does not pass a 10 % GCI. A second experiment on finer grids is running (`handbacks/cfdprobe.md`).

# The two gliders' real RANS cases through the pipeline path (before the final run)

`review/workorder/rans_real.py --cores 6` on orca, the real child through `pipeline_windows._rans_work`, then the real `s_refit` on that row alone.

| | Seaglider (`wo_rans_real2`) | Slocum (`rans_slocum`, beside the gate `wog1`) |
|---|---|---|
| ok | true | true |
| cd / cd_hangar | 0.3718 / 0.3014 = 1.233 | 0.3536 / 0.2840 = 1.245 |
| cd_spread | 0.0352 | 0.0324 |
| rans_gci (limit 0.10) | 0.0944 | 0.0917 |
| rans_refinement_ratio (at least 1.3) | 1.596 | 1.590 |
| rans_iterative_scatter (limit 0.02) | 0.0070 | 0.0022 |
| failed mesh checks | 0 | 0 |
| seconds | 856 | 727 |
| refit | used, multiplier 1.233 | used |
