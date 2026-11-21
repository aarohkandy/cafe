# Hand-back: work order step 3, the glider's CPU RANS part `body_rans` (branch `wo-rans`, cut from `wo-fea` at 9cc9c60)

Builder: Claude Fable 5.2. Every run below is on cafe-orca (proot, `PMX=pm_wo_rans`, logs `~/cafe-worker/logs/<job>.log`, each ends `rc=N`). Nothing was run on the laptop. Nothing was pushed. DECISIONS.md, CHANGELOG.md, STATUS.md and HANDOFF.md are untouched: their text is at the end.

## What changed

| file | change |
|---|---|
| `cafe/pm/stage3/rans.py` (new) | `write_stl` (hull and wing unioned, body frame, no shift), `flow_label` (body-frame velocity -> `x+z<angle>` / `x-z<angle>` and the speed; refuses what the label cannot carry), `drag_history` (the probe's function ported: mean and std of the drag, the force projected on the flow direction, over the last 20 % of the iterations from `postProcessing/forces`; `cfd._shrink` keeps `postProcessing`, so it can be read before or after), `two_grid` (`cfd.external` at level offsets 0 and 1, 600 iterations, `dirs=(label,)`, each case shrunk after its solve, fine and coarse mesh checks both kept, GCI from `cfd.gci` at the cell-count ratio), `run_child`/`main` (child with `freesurface.arm_watchdog`), `row_fields` (cd, cd_spread, the four checks), `reasons` (one sentence per failing check). Constants carry the measured figures and the jobs `rans_g1` to `rans_g4`. |
| `cafe/pm/budget.py` | `RANS_PARTS = {"glider": "body_rans"}`, `rans_vehicles`, `rans_plan` (priced from `stage3.glider.rans.*`; `fit` allows a microsecond like `fs_plan`'s caller does); `plan()` prices RANS on `s3 - fs - FEA hold` and keeps `kept = fs + hold + rans.fit * rans.need_s` (clamped to `s3`); `stage3_plan` adds key `rans` (same arithmetic, so `plan` and `run` agree); label, note and `les.note` say only "sub-grid stays uncalibrated" where `rans.fit > 0`. |
| `cafe/pm/stage3/pipeline_windows.py` | `_rans_gate`, `_rans_work` (child, watchdog, job directory removed, never raises), `_rans_submit`, and the wiring in `run`: FEA, then RANS, then free surface in the one-worker pool; `st["rans_queued"]`; `want` counts the RANS rows. One case per glider vehicle at its first window; the other windows get no `body_rans` row. |
| `cafe/pm/pipeline.py` | `s_refit`: candidate list for the multiplier is `("hull_fs", "hull", "body", "body_rans")`: a passing LES `body` row wins, else a passing `body_rans`; never pooled. Reasons for the unused one in `refit.json` (`body_not_used`, `body_rans_not_used`). |
| `config/assumptions.yaml` | `stage3.glider.rans.est_s` 867 s and `stage3.glider.rans.margin` 1.25, each with value, unit, why, replace_with. Scoped to gliders by `credibility.config_scope` (test T16). |
| `cafe/pm/credibility.py`, `docs/CREDIBILITY.md` (L15), `docs/RUNBOOK.md` | L15 and one RUNBOOK sentence narrowed (below). |
| `review/workorder/rans_real.py` (new) | the one real run (below). Not product code, no test. |

The gate for a case is the plan's own seconds, not the clock: `_rans_gate` compares `est_s x margin` with `sizes["rans"]["share_s"]` (the share left after the FEA hold and the free-surface cases) less the RANS cases already queued. The queue runs RANS before the free-surface case, so a gate against the whole share would let both gliders' cases through and then refuse the free-surface one; T10 is that case.

## The real row (the one real run)

Job `wo_rans_real2`, rc=0, 6 CPUs, `PM_MEM=24g`, orca load about 5 to 9: `review/workorder/rans_real.py --cores 6`. The demo's Seaglider (`glider_eq`, first window t=1678006800, label `x-z5.29`, 0.13520 m/s, the case of the probe), the real child through `pipeline_windows._rans_work`, no stand-in. Plan at overnight (in memory): `rans` 2 cases, fit 2, need 1083.75 s, label ends "sub-grid stays uncalibrated". The row is in `~/cafe-worker/cafe/pmdata/runs/rans_real/row.json`.

| field | value |
|---|---|
| ok | **true**, reasons `[]` |
| cd (fine grid, solver rho, ref_area 0.070686 m2) | 0.37178 (drag 0.24617 N) |
| cd_hangar | 0.30142; cd / cd_hangar = **1.2334** |
| cd_spread | 0.035182 (= hypot(GCI x cd, std / q), 9.5 % of cd) |
| cl, cl_spread, cl_hangar | None, None, None |
| rans_gci | **0.094375** (limit 0.10) ok |
| rans_refinement_ratio | 1.5962 (limit 1.3) ok; cells 1,284,814 fine, 315,938 coarse |
| rans_iterative_scatter | 0.006971 (limit 0.02) ok |
| rans_mesh_checks | 0 (limit 0): 0 on both grids |
| seconds | 856.0 s in the child, 857.9 s for the row; the estimate is 867 s (the plan allows 1083.75 s) |

Then the real `pipeline.s_refit` on that row alone (fresh run directory `runs/rans_real/run`, budget overnight): `used: true`, `part: "body_rans"`, `drag.mean = 1.2334204660990837` = cd / cd_hangar exactly, `windows: 1`, `sigma` 0.1807 (statistical 0.1167, between-window floor 0.1233, discretisation floor 0.0617), no lift entry. The same is pinned in tests T17 to T21.

No limit was loosened. The GCI is the closest call: 0.0944 against 0.10 (the probe's runs gave 0.0849, 0.0903 and 0.0904; this one is the highest of four).

## Tests (new file `tests/test_wo_rans.py`, 35 tests)

"Before" is job `wo_rans_base`: the tree at 9cc9c60 plus the new `rans.py` only (no budget, wiring, refit or assumption change), this test file. 29 of 35 failed; the 6 that passed are the tests of the new module alone (T3, T4b, T22, T23, T24) and T25 (a hand-built row through the report, a guard). "After" is `wo_rans_2` (35 minus T26, all passed), `wo_rans_fin2` (pytest1 rc=0) and `wo_rans_fin4` (rc=0, with T26).

| test | behaviour | before |
|---|---|---|
| T1 | a glider whose LES part is planned out gets exactly one `body_rans` row for three windows, label, cd = drag / q, cd_spread, GCI, ratio, four named checks, no lift; the LES rows are as they were; `every_window_attempted` 4 of 4 | fails (no row) |
| T2 | the child gets a real closed STL, the window's flow label and speed (`x-z`, matches the row's body velocity to 0.01 deg), a watchdog | fails |
| T3 | `flow_label`: sign, 0.01 deg, refuses backward, pure-z, sideslip, zero, NaN | passes (new module) |
| T4 (8 cases) | each check fails alone (fine or coarse mesh checks, GCI 11 % and NaN, ratio 1.2 and no cell counts, scatter 3 % and no history), `ok` false, one sentence each | fail |
| T4b | all four failing: four sentences, spread formula | passes (new module) |
| T5 (2) | drag -1 N and NaN: a not-ok row with the reason | fail |
| T6 | a child that raises (exit 1 with the exception as its last stderr line), SIGKILL early, watchdog kill, timeout, OSError, exit 0 with no file: each a row with `error`; the stage does not raise | fails |
| T7 | a deadline already passed is "killed before it started"; the job directory is removed in both cases | fails |
| T8 | a case that does not fit: the gate sentence, `left_s`, no child; exactly margin x estimate fits; share 0 | fails |
| T9 | no wall-clock budget: runs with the 1e9 watchdog and no timeout; a failing `glider_case` is a row, not an exception | fails |
| T10 | two gliders and a USV on a share holding the free-surface case and one RANS case: order `rans` then `fs`; the first glider runs, the second is refused with the gate sentence, the free-surface row still runs and is ok | fails |
| T11 | a USV, a UAS and a plan with `cpu_fallback` false get no `body_rans` row | fails (no row for the glider to compare) |
| T12 | plan: RANS priced after the FEA hold and the free-surface cases; `kept` equals the three; shares sum to what they did (0.95: `SHARE` sums to 0.95) and stage 1 is not below its share; a share holding 1.5 cases gives fit 1 and more to stage 1 | fails (no `rans`) |
| T13 | 150 estimates from 600 s up: `plan()` and `stage3_plan` agree on `fit` through the `kept / B * B` round trip, the three never exceed the share | fails |
| T14 | `rans_plan`/`rans_vehicles`: GPU plan, LES window that runs, non-glider, negative share, a microsecond under the need | fails |
| T15 | label, note and `les.note` drop only "and refit" where `rans.fit > 0` (overnight, 4h), and are the old text at quick; "CPU fallback" prefix kept | fails |
| T16 | the two assumptions: values, fields, and `used_of` lists them for a glider mission, not for a USV-only or UAS-only one | fails |
| T17 | s_refit: a passing `body_rans` row alone sets the glider's multiplier (`part`, `drag.mean = cd / cd_hangar`, one window, the between-window floor applies, no lift) | fails (`used` false) |
| T18 | a passing LES `body` row wins and the two are not pooled | fails |
| T19 | a failing RANS row: not used, `failed_checks` names it, reasons for the unused part | fails |
| T20 | `s_stage1b` after that s_refit reruns stage 1 (`refit_iterations_performed` 1, scales name `body_rans`), not a copy | fails |
| T21 | the stage's own row through `refit.refit` and `s_refit`: drag / hangar, no lift (a row with a lift hangar value and no lift would raise `TypeError` in `refit.refit`) | fails |
| T22 | `drag_history` is the std of the projected drag, not the norm of `force_std` (a case where the norm is over 0.04 of the drag and the true figure under 0.01), survives `cfd._shrink`, None without a history or with a malformed one | passes (new module) |
| T23 | `two_grid` with a stand-in `cfd.external`: levels 0 and 1, 600 iterations, `dirs`, fluid, speed, coarse case shrunk, GCI against `cfd.gci`, both meshes' checks, a non-positive coarse drag refused | passes (new module) |
| T24 (slow) | the real OpenFOAM on the stage's own STL of the Seaglider at level offset -2, 30 iterations: a force and the mesh checks come back, `drag_history` reads the real `postProcessing` | passes (new module) |
| T25 | the report shows a `body_rans` row as "W1 body_rans" with its checks and traceability holds | passes (guard) |
| T26 | a hull and wing that do not union into a closed solid: a row that says so | fails |

Coverage (job `wo_rans_fin3`, `coverage run --source=cafe/pm` over `tests/test_wo_rans.py` and `tests/test_wo_fea.py`): `rans.py` 99 % (line 56, the non-closed union, which T26 now covers), every new line of `budget.py` and `pipeline_windows.py` covered (their misses in that run are older code the two files do not reach). The new lines of `pipeline.py` are in T17 to T21 (test_pipeline.py run below).

## Pins moved (each moves by exactly what this step adds)

- `tests/test_credibility.py`: the per-class assumption keys 32 -> 34 (the two new keys); the L15 text (`LIMITS2`).
- `tests/test_budget.py`: two plan shapes (`..._gives_the_slices_to_stage_1` at 4h, `..._free_surface_cases_keep_the_share...` at overnight) hold the glider's RANS seconds beside the FEA hold and the free-surface cases.
- `tests/test_wo_fea.py`: `out_ctx` sets `cpu_fallback` False so the FEA tests do not also queue a RANS case (T3 and T4b saw an extra child); T9 and T10 add the RANS seconds to the share and to the profile seconds (4h: 2 x 1083.75 s, not 0).
- `tests/test_config.py` (`BARE_WRITES`: `stage3/rans.py` 1 write, `pipeline_windows.py` 2 -> 3) and `tests/test_round21_e.py` (`RAW_ISFINITE`: `stage3/rans.py` 6), the two source-scan allow-lists. Each entry has its reason.
- Not moved: `tests/test_report.py:1337,1344` (a hand-built plan passed through the report, not computed), `tests/test_budget.py:245` (`ci` plans no case: the glider's smoke window runs).
- Docs and text: L15 (`credibility.py`, `docs/CREDIBILITY.md`, `tests/test_credibility.py`) and the one RUNBOOK sentence; DECISIONS 189's figures (stage 3 keeps 0.197 on overnight, stage 3 0 on 4h) were already stale after step 2 and are stale again (see "Plans" below).

## Evidence (jobs)

| job | what | result |
|---|---|---|
| `wo_rans_1` | first run of `tests/test_wo_rans.py` | 6 failed (my test errors: an `approx` compared with `>`, a hand-typed cell count, a patched helper left on, shares sum 0.95, the pipeline data fixture); fixed |
| `wo_rans_2` | the file and the credibility pin test | file all passed; the pin 32 -> 34 failed, moved |
| `wo_rans_lint`, `wo_rans_lint2` | ruff, mypy | 24 ruff errors (23 E501, one B905) and 12 mypy errors, fixed; `lint2` rc=0, ruff clean, mypy clean (58 files) |
| `wo_rans_fin` | pytest1 (wo_rans, wo_fea, budget, round23_claims, credibility): 6 pin failures (4 in test_wo_fea, 2 in test_budget), moved; pytest2 `tests/test_pipeline.py -k "refit or stage1b or stage3"` **rc=0**; pytest3 `tests/test_stage3.py -k "fs or free or fea or window"` **rc=0** | |
| `wo_rans_fin2` | ruff (one E501 in test_budget, fixed), mypy rc=0, pytest1 on the moved pins **rc=0**, pytest4 over the source-scan files (test_config_docs, test_config, test_round16_pb, 17_f, 18_m, 21_e, 22_c, 22_d, test_runners): 2 failed (the two allow-lists above), moved | |
| `wo_rans_fin3` | `tests/test_config.py`, `tests/test_round21_e.py`, `tests/test_budget.py` **rc=0**; coverage as above | ruff: one E501 in test_round21_e, fixed |
| `wo_rans_fin4` | final tree: mypy rc=0, `tests/test_wo_rans.py` + `tests/test_round21_e.py` + `tests/test_config.py` **rc=0** | ruff: one E501 in `rans_real.py` (the script, not in the project's `ruff check cafe/pm tests`), shortened after the run and checked by length only |
| `wo_rans_base` | the new tests on the old code (above) | 29 failed |
| `wo_rans_real2` | the real case and the refit on its row | rc=0 |
| `wo_rans_plan` | `plan` for the demo at 2 CPUs (below) | rc=0 |
| `wo_rans_real` | first try of the real script | rc=1: `_base` needs `ctx.plan["les"]`, the script read no plan; fixed in the script |

## Plans (demo mission, `--gpus 0`, planned on 2 CPUs, job `wo_rans_plan`)

| budget | stage 1 share | stage 3 share | FEA hold | RANS cases (cases / fit) | free-surface fit | n_max |
|---|---|---|---|---|---|---|
| quick | 0.75 | 0 | 0 | 2 / 0 | 0 | 64 |
| 4h | 0.5104 | 0.2396 | 1282.2 s | 2 / 2 | 0 | 256 |
| overnight | 0.6542 | 0.0958 | 1282.2 s | 2 / 2 | 0 (at 2 CPUs; 1 at 6, as T12 pins) | 512 |

The labels: quick still says "sub-grid and refit stay uncalibrated", 4h and overnight "sub-grid stays uncalibrated". The ensemble caps do not move; the stage-1 share at 4h falls from the 0.66 step 2 left it (0.75 before it) to 0.51.

## Printed text and keys added

- Row label (all `body_rans` rows): `RANS (OpenFOAM simpleFoam, k-omega SST), CPU, two-grid GCI`. `resolution.source`: `cafe.cfd.external: OpenFOAM simpleFoam, k-omega SST, snappyHexMesh`.
- Checks and notes: `rans_gci` (two-grid GCI of the drag, not a bound of the total error; fails when not finite or above 10 %), `rans_refinement_ratio`, `rans_iterative_scatter`, `rans_mesh_checks` (value = failed checks of both grids, limit 0).
- One reason per failing check: scatter ("the solver reported no force history" / "the drag still wanders by X over the last 20 % of iterations (limit 2%): not converged"), GCI ("grid-convergence index X is above 10%: ..." / "no grid-convergence index: ..."), mesh ("checkMesh failed N mesh check(s) (fine grid a, coarse grid b): ..."), ratio ("refinement ratio r = X (cells a / b) is below 1.3: ..." / "unknown (no cell counts)").
- Gate refusal: "RANS window not run: estimated N min x 1.25 margin = M min (two grids, 600 iterations) against X min left of the Y min stage-3 share after the FEA and the free-surface cases; <fitting_budget clause>".
- Child failures: "RANS window killed before it started: the stage-3 wall-clock share was spent before its turn came", "RANS run killed at its deadline after N s: it did not finish inside the share", "RANS run failed (rc): <killed by its watchdog at the deadline | killed by SIGKILL before its deadline (...) | last stderr line>", "RANS window failed: <error>". Row `fea`: "no structural model in this part: the hull's FEA is the body window's".
- Plan texts: label, note and `les.note` say "sub-grid stays uncalibrated" where `rans.fit > 0`, else the old text.
- `refit.json` reasons: "no LES body window passed its checks: the RANS window (body_rans) sets the multiplier", "a passing LES body window sets the multiplier; LES and RANS coefficients are not pooled", "no window of this part passed its checks".
- L15 (`credibility.py`, `docs/CREDIBILITY.md`): "no LES window can reach the lattice viscosity floor on a CPU, so none is run and the sub-grid layer stays uncalibrated; the drag refit comes only from a CPU RANS (glider) or free-surface (USV) case, where the budget holds one and it passes its checks; no GPU run exists". RUNBOOK: one parenthesis after "and the time goes back to stage 1".
- Keys: part `body_rans`; checks above; assumptions `stage3.glider.rans.est_s`, `stage3.glider.rans.margin`; plan key `stage3.rans` (`cases`, `vehicles`, `est_s`, `margin`, `need_s`, `share_s`, `fit`); row keys `gci`, `refinement_ratio`, `drag_n`, `ref_area`, `resolution.{flow_label, level_offsets, iterations, iterations_cap, estimated_s, cells_fine, cells_coarse}`; `refit.json` `body_not_used`, `body_rans_not_used`.

## Text for the documents (unnumbered)

DECISIONS row:

> A glider whose LES body window is not run on a CPU plan gets one stage-3 part `body_rans` (`stage3/rans.py`): the window's hull ellipsoid and wing plate, unioned, through `cafe.cfd.external` (snappyHexMesh, simpleFoam, k-omega SST) on two grids (level offsets 0 and 1, 600 iterations each; offsets -1 and 0 gave GCI 0.243, measured on orca 2026-11-20, jobs rans_g1 to rans_g4) at the first window's through-water speed and body-frame flow direction. One case per glider vehicle, not per window: the through-water state does not depend on the heading, and K identical rows pooled in the refit would shrink its sigma by about sqrt(K) and lose the between-window floor. cd is the fine grid's drag over the solver's own rho, speed squared and the vehicle's reference area; cd_spread = hypot(GCI x cd, the drag's std over its last 20 % of iterations / q); no lift (cl, cl_spread and cl_hangar are None, and stage 1 flies drag only). The row is ok only if rans_gci <= 10 %, rans_refinement_ratio >= 1.3, rans_iterative_scatter <= 2 % (the std over the mean of the force projected on the flow direction, not the norm of `force_std`, which is dominated by lift and fails a settled case) and rans_mesh_checks is 0 on both grids. The plan prices a case at `stage3.glider.rans.est_s` (867 s at 6 ranks) x `stage3.glider.rans.margin` (1.25) on the share left after the sea-pressure FEA hold and the free-surface cases (`budget.rans_plan`); the queue runs the FEA, then the RANS cases, then the free-surface cases, and `kept` is the three. A passing `body_rans` row feeds the refit when no LES body row passes (`s_refit`; never pooled with one). The plan label and notes say only that the sub-grid stays uncalibrated where a case fits; L15 is narrowed the same way. Measured once for real (job wo_rans_real2): ok, cd 0.3718 against cd_hangar 0.3014 (ratio 1.23), GCI 0.0944, scatter 0.0070, 0 failed mesh checks, 856 s. Open: the Hangar reference is the whole-vehicle force balance and the RANS geometry a bare ellipsoid and plate, so the multiplier compares different things (owner decision 3 of the plan).

CHANGELOG lines:

> - Glider CPU RANS part `body_rans` (work order step 3): one two-grid `cfd.external` case per glider whose LES body window is planned out, in a child process after the sea-pressure FEA and before the free-surface cases; checks `rans_gci`, `rans_refinement_ratio`, `rans_iterative_scatter`, `rans_mesh_checks`; no lift; a passing row feeds the refit when no LES body row passes.
> - Plan: `plan.json` `stage3.rans` (cases, vehicles, est_s, margin, need_s, share_s, fit); `kept` is the free-surface cases, the FEA hold and the RANS cases; the label, note and `les.note` say "sub-grid stays uncalibrated" where a case fits; assumptions `stage3.glider.rans.est_s` (867 s, 6 ranks, rans_g4) and `.margin` (1.25); L15 narrowed.
> - `refit.json` gains `body_not_used` / `body_rans_not_used` (the reason the part that did not set the multiplier did not).

## What is NOT verified

- The whole suite and the gate; the whole of `tests/test_stage3.py`, `tests/test_report.py` and `tests/test_pipeline.py` on this tree (only the `-k` selections above ran; `test_report.py` was last run whole by the FEA builder, `wo_fea_rep`). No mutation run.
- The Slocum: no real case (its hull, wing and Reynolds number differ; the 867 s is the Seaglider's), and the real run drove `_rans_work`, not `_rans_submit` and the pool; those are tested with a stand-in solver only.
- A whole pipeline run on this code (overnight, 6 CPUs): not run. The rows in a real `windows.json`, the report page with a real `body_rans` row and stage 1b's verdict from this refit are therefore not seen.
- Cores other than 6: `est_s` is a 6-rank figure and is not scaled by the core count (the ruling). `run` exports `CAFE_NPROC=min(6, workers)`; on 2 CPUs the case is slower than priced and, if it does not finish, is killed at the stage deadline and says so.
- The case under load: `wo_rans_real2` ran at load 5 to 9; the 16-core and 6-core probe times are from the probe.

## What still looks wrong

1. **The GCI margin is thin.** Four runs of the same setting gave 0.0849, 0.0903, 0.0904 and now 0.0944 against the 10 % limit (the drag is not monotone in the cell size, 0.2366, 0.2575, 0.2460 N at levels 5, 6, 7, so the two-grid GCI is a sensitivity, not an asymptotic error). A fifth run can exceed 0.10: the row is then not ok, `refit.json` says the glider keeps the analytic coefficients, and the plan's seconds were spent. This fails closed.
2. **The multiplier compares different things (plan section 8, item 3, still the owner's).** The reference `cd_hangar` is the whole-vehicle force balance (hull, tail, antenna, fairings); the RANS geometry is a bare ellipsoid and a flat plate. Measured cd / cd_hangar is 1.23, above 1, so `refit_drag` slows the glider (speed follows drag^-1/2, about x0.90): the pessimistic direction, the opposite of the plan's guess. Its sigma is 0.18, mostly the assumed floors (between-window 0.12 for a single window, discretisation 0.06), not the GCI.
3. **Advice sentence.** `_rans_gate` and `_fs_gate` pass `queued_s` (which includes the FEA hold) to `fitting_budget` while `profile_stage3_s` already subtracts the hold: the "it would fit --budget X" advice counts the FEA hold twice, so it is stricter than the plan (a true statement, but it can name overnight where 4h also fits). Written by step 2 for the free-surface gate; the RANS gate uses the RANS-only queue, so it is not affected.
4. **Stale texts.** `docs/RUNBOOK.md` line 159 still says "the glider hull's FEA belongs to its LES window, so it does not run when that window is skipped" (false since step 2); DECISIONS 189's "stage 3 keeps 0.197 on overnight, 0 on 4h" and `STATUS.md`'s `--gpus 0` row are stale since step 2 and again since this step.
5. **`profile_stage3_s`** is the stage-3 seconds less the FEA hold, so it now includes the RANS seconds; the free-surface advice is consistent with it, but a reader of `profile_stage3_s` alone would see the RANS seconds counted as free-surface ones. The docstring says what is held, not what is included.

## Open questions for the lead

- Owner decision 3 stays open (above): whether a bare-hull-and-plate RANS may set the glider's multiplier at all, now that the ratio is known to be 1.23.
- Whether the thin GCI margin should be answered by a third grid (the probe's note: a level-8 run needs a cell-cap change in `cafe/cfd.py`, which this step may not edit) or accepted as fail-closed.
- Whether the first-window-only rule should instead be "the window nearest the median through-water state", which this step does not compute.
