# hr1: the demo run with the USV's bare-hull CFD case

`missions/tepex_c_demo.yaml`, `--budget overnight --gpus 0 --fresh`, orca (proot, 6 CPUs, cores 0,1,10,12,14,15), code `fe34859` (the code of `b0fd1cb`, which the gate `wog1` ran on: the commits between are documents only; code digest `97c13009009a...`), started 2026-11-24 02:27 UTC after the gate had ended, **`rc=0`**. Read with `review/workorder/hr1read.py` and `review/workorder/hr1chk.sh` (job `hr1_chk`, `rc=0`): `audit --ledgers-only` 0 problems, `whatif --shift 30h` `rc=0`, the contribution table before the cards.

Walls: ingest 236 s, stage 1 393 s, stage 3 2,975 s (its share 4,019.7 s), stage 1b 477 s (a real rerun, `refit_iterations_performed` 1), emulator 9,169 s, report 75 s; 13,019 s over hangar to emulator of the 36,000 s budget (0.36).

## The USV's hull case (the work order's one "no")

| | hr1 |
|---|---|
| Part | `hull_rans`, one case at the USV's first window (0.590 m/s through the water) |
| Checks | all four pass: GCI 0.0590 (limit 0.10), refinement ratio 1.875, iterative scatter 2.1e-5, mesh checks 0 |
| Grids | 1,888,790 and 286,535 cells; 245 iterations of the 600 cap |
| cd | 0.07670 against the model's hull term 0.08891: ratio 0.8626 |
| Share | the hull's viscous term is 0.2296 of the model's through-water resistance at the window's leeway and heel; residuary share 0.00095 (gate 0.01) |
| Refit | used, part `hull_rans`: multiplier 0.96846 (-3.15 %), sigma 0.02504 (statistical 0.01169, between-window 0.01981, discretisation 0.00990) |
| Speed | 0.96846^-0.5 = 1.0161 (computed from the mean; not read from stage 1b) |
| `hull`, `hull_fs` | not used, with the box-keel reason; `hull_fs` was not run in any of the three windows (refused at plan time: 118 min needed against 0.0 min left of the 67 min stage-3 share; plan `fs.fit` 0, `fs.share_s` 0) |

These are the numbers of the stand-alone case `hr_real1` (DECISIONS 1109) to four figures. The plan fitted three RANS cases (need 1,083.75 s for each glider and 570 s for the USV, 2,737.5 s held) after the FEA hold of 1,282.2 s.

## Verdicts (512 members)

| | hr1 | fin1 (`44c0b00`, no USV refit) |
|---|---|---|
| glider_eq | MARGINAL, 167 failed | MARGINAL, 172 |
| glider_2n | GO, 0 | GO, 0 |
| usv | NO-GO, 468 | NO-GO, 467 |
| uas | NO-GO, 499 | NO-GO, 499 |

**The USV's verdict does not move.** The boat is about 1.6 % faster under the refit and fails in one member more; why one more was not looked into.

Gliders: glider_eq cd 0.3718 against 0.3014 (GCI 0.0882, scatter 0.0075), multiplier 1.233; glider_2n cd 0.3536 against 0.2840 (GCI 0.0920, scatter 0.0023), multiplier 1.245. Hull FEA (sea pressure only): 2.87 and 0.764, as in fin1.

## The table on the first screen

| Vehicle or link | CFD | FEA | Emulator |
|---|---|---|---|
| glider_eq | yes | yes | no |
| glider_2n | yes | yes | no |
| usv | yes | no | no |
| uas | no | no | yes |
| usv-uas-rf | yes | no | no |
| glider_eq-ship-acoustic | yes | no | no |
| glider_2n-ship-acoustic | yes | no | no |
| usv-shore-iridium | yes | no | no |

with the three sentences: the geometry is ellipsoids, not CAD; "The USV's CFD is its bare hull as an ellipsoid with no keel, no waves, no leeway and no heel: it scales the hull's viscous term at one window's speed, and the rest of its drag stays the model's."; the UAS is out. Against fin1: the usv row's CFD went from no to yes and so did its two links'; **the usv row's Emulator went from yes to no** (next section).

## Emulator

All 119 planned variants ran, 120 points a scope. The UAS emulator passed and answered (`whatif --shift 30h`: `[EMULATED, training-set distance 0.72 of limit 2.36]`). **The USV's emulator trained but missed BRIEF 2.7 acceptance (coverage) in this run, so Stage 1 answered its whatif** (NO-GO, P(fail) 0.906 to 0.727 (0.658 to 0.786), n = 128); in fin1 it passed and answered. The cause was not looked into (the training table carries 176 rows marked stale for the USV's scope). The Seaglider's emulator missed acceptance (coverage) as before; the Slocum's has nothing to learn (P(fail) 0 in all rows).

## Not done, stated

- The `hull_rans` case's own wall time inside hr1 was not read (stand-alone it took 475 s against 456 priced and the 570 s cap).
- USV windows 2 and 3 (0.700 and 0.608 m/s) have no case: the product runs the first window only.
- The USV emulator's missed acceptance in hr1 was not looked into.
- No wall layers on the bare-hull grids (the 0.863 may be a few per cent low); the keel stays on the model's foil formula (PROBLEMS P-WO11, QUESTIONS 22i).
- The tests that read documents were not rerun on the documents-only commits after `b0fd1cb`.
- The freeze steps of `HANDOFF.md` (mutation, receipts, golden re-mint, acceptance) are not started.
