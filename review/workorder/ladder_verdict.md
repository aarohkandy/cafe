# Scale ladder (work order, Addendum 1): the proof failed. The ladder is a diagnostic, not a source of coefficients

Lead, 2026-11-23. The addendum's item 4 asks for a proof run with a tolerance and a result, pass or fail, and says: if the proof fails, stop and tell the owner. This is that result. No ladder code is in the pipeline, and no reduced-Reynolds number is used anywhere in a run.

## The question

Can a drag coefficient measured at a reduced Reynolds number be scaled to the glider's own (Re_L 2.045e5 for the Seaglider window: 0.1352 m/s, 1.8 m, nu 1.19e-6) within a tolerance of 0.10? Two solvers were tried on the same shape (hull ellipsoid and plate wing).

## Result 1: turbulent steady RANS on orca, Re_L 1.0e4 to 8.0e4, checked against the same solver at 2.045e5

Source: `ladder_rans.md` (five runs, `rans_ladder_*` on orca). cd 0.6588, 0.5259, 0.4530, 0.3948 at Re_L 1.002e4, 2.005e4, 4.01e4, 8.02e4, and 0.3739 at the physical 2.045e5.

| rule, fitted on the four reduced rungs | predicted cd at 2.045e5 | against the measured 0.3739 | within 0.10 |
|---|---|---|---|
| one form factor on the ITTC-57 line, from the top rung | about 0.30 | 19 % low | no |
| one form factor on the Blasius line, from the top rung | about 0.25 | 34 % low | no |
| two terms, cd = a + b cf(Re), ITTC-57 | 0.348 | 7 % low | yes, by 3 points |
| two terms, cd = a + b cf(Re), Blasius | 0.338 | 10 % low | at the limit |

The form factor is not steady across the rungs (it moves 28.7 % on ITTC-57 and 65.1 % on Blasius). The pressure part of the drag is nearly constant and the viscous part is not, which is why two terms do better than one. The two-term rows are the lead's arithmetic on the table's numbers, one shape, one angle of attack.

## Result 2: laminar-resolved LBM on the laptop GPU (FluidX3D), Re_L 105 to 1,100

Source: `ladder_gpu_results.md` (the audit session's run, 2026-11-22 23:40 to 2026-11-23 07:08 PST, copied here as written). The solver is stable only to a cell Reynolds number of about 8, so on the grids the laptop holds the rungs stop near Re_L 1,100, about 190 times below the physical value.

- Seaglider, scaled to the physical Reynolds number: 0.170 +- 1.08 on the Blasius line and 0.110 +- 1.11 on ITTC-57, against 0.3729 (CPU RANS, run fin1) and 0.3014 (the analytic model). Of the three gates at 0.10, two fail on Blasius and all three on ITTC-57.
- Slocum: 0.174 +- 1.74 and 0.078 +- 1.79 against 0.3539 and 0.284; the same gates fail.
- The two-term fit gives a negative cd on the Blasius line (-0.38 and -1.04) and 3.87 and 5.44 on ITTC-57.
- The sphere check of the same solver is 5 to 8 % above the textbook value at Re 100 and 200, and refining from 24 to 32 cells moves it away from the reference.

The two solvers do not overlap in Reynolds number (1,100 against 10,000), so no rung could be paired between them.

## Verdict

- **Fail.** No rule tested reproduces the physical-Reynolds value within 0.10 from reduced-Reynolds rungs across both solvers. The only rows inside the tolerance are the two-term RANS rows, at 7 and 10 % low, and they use a solver that already runs at the physical Reynolds number in about 15 minutes per glider (`body_rans`), so they save nothing.
- The ladder stays a diagnostic: the tables above, and the scripts that made them (`rans_probe.py --speed-factor`, `ladder_table.py`). It does not enter the pipeline and sets no coefficient.
- The compute limit the addendum set out to remove is on the LES windows, not on the drag coefficients: the gliders' steady RANS cases at the physical Reynolds number fit the overnight budget on CPU and refit the drag (run fin1).

## The addendum's "Done" list

| item | state |
|---|---|
| orca's LBM rate in the plan | measured, not stored: 2.14e7 cell-updates/s on 6 CPUs, 3.13e7 on 16, 2.53e7 on 32 (the stored homebase figure is 7.53e6). Storing a host's rate changes which LES windows the plan affords on that host; it is left for the owner's yes because no LES window has been run to its end on CPU. |
| a proof run with its tolerance and result | this file: tolerance 0.10, fail |
| a demo run with a ladder of two passing rungs per glider and the report line | not done, by the addendum's own stop rule: the proof failed |
| a test that a reduced-Reynolds rung is never labelled or used as a physical row | the probe refuses an output directory that is not `rans_ladder_*` when a speed factor is set (`tests/test_wo_cfdprobe.py`); there is no pipeline row to guard, because nothing was built in |

## What would change the verdict

- A wall-resolved or wall-modelled LBM run at Re_L 1e4 to 1e5 (a workstation GPU with tens of GB, or the kernel critic's 10 h and 75 h CPU rungs in `LEAD_HANDOFF/plans/ladder_kernel_critic.md`), paired with the RANS rungs at the same Reynolds numbers.
- A second shape and a second angle of attack for the two-term rule.
