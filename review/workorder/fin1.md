# fin1: the work order's final run

`missions/tepex_c_demo.yaml`, `--budget overnight --gpus 0 --fresh`, orca (proot, 6 CPUs, 48g), code `44c0b00` (code digest `be6174a4...`), started 2026-11-21 17:24 UTC beside the gate's third pass, **`rc=0`**. Read with `review/workorder/on2read.py` (pointed at fin1) and `review/workorder/fin1chk.sh` (job `fin1_chk`, `rc=0`): `audit --ledgers-only` 0 problems.

Walls: ingest 149 s, stage 1 432 s, stage 3 4,729 s, stage 1b 498 s (a real rerun), emulator 9,311 s, report 180 s; 14,978 s over hangar to emulator of the 36,000 s budget (0.42).

## Against the work order's section 3

| Item | Result |
|---|---|
| 1. CFD ran and stage 1b flew the refitted coefficients | **Gliders: yes.** One CPU RANS case each passed its four checks: glider_eq cd 0.3729 against 0.3014 (GCI 0.0861, scatter 0.0047), glider_2n cd 0.3539 against 0.2840 (GCI 0.0895, scatter 0.0019). The refit used both (`refit_iterations_performed` 1; glider_eq multiplier 1.237) and stage 1b reran all 512 members. **USV hull: no.** Its free-surface case ran and failed its checks (cd 0.098, spread 0.189, against 0.053): the USV keeps the analytic model (DECISIONS 1104). The UAS has no CFD part. |
| 2. FEA ran for the glider pressure hull at the ordered depth, utilisation beside the verdict | **Yes.** Sea pressure only: glider_eq 2.873 at 950 m (buckling; stress 0.580), glider_2n 0.764 at 500 m. The line prints under the hull warning; the verdict is not capped (awaiting the owner, QUESTIONS 22a, 22b). |
| 3. The emulator trained, passed its gate, one `whatif` EMULATED | **Yes, for the USV and the UAS.** All 119 planned variants ran (8,553 s; 120 points a scope). USV and UAS emulators passed RMSE and coverage and answered their fix candidates. `whatif --run /data/runs/fin1 --shift 30h` (`rc=0`): usv `[EMULATED, training-set distance 0.39 of limit 1.69]`, uas `[EMULATED, 0.72 of 2.36]`. The Seaglider emulator missed RMSE (0.063 against 0.054) and coverage; the Slocum has P(fail) 0 in all 120 rows (nothing to learn): Stage 1 answers both. |
| 4. One table on the first screen | **Yes**, after the Verdicts table and before the cards: |

| Vehicle or link | CFD | FEA | Emulator |
|---|---|---|---|
| glider_eq | yes | yes | no |
| glider_2n | yes | yes | no |
| usv | no | no | yes |
| uas | no | no | yes |
| usv-uas-rf | no | no | no |
| glider_eq-ship-acoustic | yes | no | no |
| glider_2n-ship-acoustic | yes | no | no |
| usv-shore-iridium | no | no | no |

with "The CFD geometry is a set of ellipsoids from a few yaml dimensions, not CAD." and "The UAS is out: its window is the frame without rotors."

## Verdicts (512 members)

| | fin1 | on1 (analytic drag, `8ecf0e7`) |
|---|---|---|
| glider_eq | MARGINAL, 172 failed | MARGINAL, 140 |
| glider_2n | GO, 0 | GO, 0 |
| usv | NO-GO, 467 | NO-GO, 467 |
| uas | NO-GO, 499 | NO-GO, 499 |

The equatorial glider fails more often with the CFD drag (1.24 times the analytic value): it is slower.

## Not done, stated

- USV hull CFD does not converge on CPU (DECISIONS 1104; `handbacks/fs.md` lists what to try). Done item 1 holds for the gliders only.
- No GPU: no LES window ran (15 parts not run).
- The Seaglider's modelled hull fails at 950 m (utilisation 2.87); the verdict does not use it.
- The run was not alone on the worker (the gate's third pass ran beside it for its first 75 minutes).
- The freeze steps of `HANDOFF.md` (mutation, receipts, golden re-mint, acceptance) are not started.
