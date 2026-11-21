# Hand-back, work-order step 2: the sea-pressure-only hull FEA (branch wo-fea, base 8ecf0e7)

An earlier builder instance was cut off with this work uncommitted; I kept its diff (it matched the plan), re-ran its checks, found one pin its last run
still failed (`test_review_round_6_m14`), fixed the cause (item 5 below), and committed.

## What changed (file:function)

1. `cafe/pm/stage3/pipeline_windows.py`
   - `_glider_vehicle_for(ctx, vid, platform, a, clip)`: the dive lookup and `glider_vehicle` factored out of `_row`. `_row` calls it with `clip=False`
     (LES rows byte-identical, `_row` stays unclipped as ruled); the new path uses `clip=True` (`min(dive, rating_m)`, as the model flies it).
   - `_sea_pressure_fea(veh, a, timeout_s)`: `_fea` with a zero wall-pressure field; a run gets `load="sea pressure only"` and `depth_m`.
   - `_fea_submit(pool, ctx, vid, platform, a, st, sizes)`: queues it on the one-worker pool, before the free-surface submissions, counted in
     `st["queued"]`; gated on the plan's held seconds `st["fea_left"]` (from `sizes["fea"]["hold_s"]`), else the existing "not planned" reason; never raises.
   - `run()`: submits one FEA per glider the plan marks planned out (`budget.fea_planned_out`), then copies the result into every row of that
     glider whose LES part was planned out (`fea`, and `timing.fea_s`, `timing.fea_seconds`, so the hashed rows stay clock-free); one log line per glider.
     A stage with share 0.0 starts none (its rows keep "the window did not run", the M-8 pin).
   - `profile_stage3_s`: subtracts `les.fea_hold_s` (see item 5).
2. `cafe/pm/budget.py`
   - `fea_planned_out(classes, wins)`: gliders (FEA_CLASSES) with an LES part that does not run; plan inputs only.
   - `plan()`: `hold = n_planned_out * fea_min_s`, taken only if `s3 >= fs_need_total + hold`, else 0; `kept = max(kept, fs_s + hold)`; stored as
     `les.fea_hold_s`.
   - `stage3_plan()`: `fs_plan` is priced on `share - hold` (so `fs.fit` equals what the runtime gate runs); `fea.hold_s` reported.
3. `cafe/pm/report.py`: `_hull_fea(st3, vid, tr)` (first stage-3 row with a run sea-pressure FEA; each number a traced node of stage3/windows.json),
   `_vehicles(..., st3=...)` adds `hull_fea` (glider only, else None), `_notes_html` prints the one ruled line under the hull warning. The warning is
   unchanged and the verdict is not capped.
4. `tests/test_wo_fea.py` (new, T1 to T10), `tests/test_budget.py` (two moved pins), nothing else edited.
5. Found while finishing (consequence of the plan hold, not in the plan): `profile_stage3_s` feeds the free-surface refusal's "it would fit --budget X"
   clause. With the hold inside the stage-3 share it would offer a profile whose free-surface share is smaller than said by the FEA's seconds. It now
   subtracts the hold (rounded to 1e-6 s: the share is a fraction of the budget). Result: the existing m14 pin holds unchanged.

## Regression tests (before = base 8ecf0e7 with the new test file only; after = this tree)

| Test | Before | After |
|---|---|---|
| T1 sea-pressure FEA for a planned-out glider, no window run | wo_fea_base1 fails (10 failed, 1 passed: the one that passed is T6) | wo_fea_t1 rc=0 (11 passed) |
| T2 depth = min(order, rating), pressure array all zeros | wo_fea_base1 fail | wo_fea_t1 pass |
| T3 one FEA, both windows | wo_fea_base1 fail | wo_fea_t1 pass |
| T4 FEA first in the queue, counted against the free-surface `left` | wo_fea_base1 fail | wo_fea_t1 pass |
| T4b hold below `fea_min_s` gives the "not planned" template, no child | wo_fea_base1 fail | wo_fea_t1 pass |
| T4c no wall-clock budget runs it; share 0.0 keeps "the window did not run" | wo_fea_base1 fail | wo_fea_t1 pass |
| T5 failed child / OSError gives "FEA failed: ...", no raise | wo_fea_base1 fail | wo_fea_t1 pass |
| T6 guard (passes before too): LES-loaded rows have no `load`; USV keeps "no structural model" | pass | pass |
| T7 `fea_s`, `fea_seconds` in timing, not in the hashed rows | wo_fea_base1 fail | wo_fea_t1 pass |
| T8 report: `hull_fea` with source/receipt/ledger, the line, None elsewhere and with no stage-3 file | wo_fea_base1 fail | wo_fea_t1 pass |
| T9 plan holds the FEA seconds, `fs.fit` equals the gate's, too-small share holds 0, 2 cores | wo_fea_base1 fail | wo_fea_t1 pass |
| T10 `profile_stage3_s` is the free-surface seconds less the hold | `test_review_round_6_m14` failed with the hold inside the share (wo_fea_t3: 4h read 1282.2, pinned 0.0) | wo_fea_f2 rc=0 (final tree); T10 itself was not run against the unfixed `profile_stage3_s` (m14 is the before evidence) |

## Pins moved (tests/test_budget.py, both because the plan now holds the FEA seconds at 4h and overnight)

- `test_a_cpu_plan_skips_every_les_window_that_cannot_reach_the_physical_viscosity_and_gives_the_slices_to_stage_1`: stage-3 share was 0.0 and stage 1
  the whole of it; now `fea_min_s / B` (0.0 at quick, which has less than 641 s). The "went to stage 1" skip reasons are unchanged.
- `test_the_free_surface_cases_keep_the_share_they_fit_when_the_les_slices_go_to_stage_1`: share is `fs.need_s + fea_min_s` (was `fs.need_s`).
No assertion weakened; each is the old claim plus the held seconds.

## Measured (orca, 2 CPUs, shared box; wo_fea_real, wo_fea_plans)

- ccx 2.21 at /usr/bin/ccx, gmsh 4.15.2 import fine in the image (plan 6d).
- One real sea-pressure FEA, Seaglider 1.8 x 0.30 m at its 950 m demo depth: 622.3 s (stored `fea_min_s` 641.1, so the floor is about 3 % conservative);
  utilisation 2.873 = buckling 2.873 (factor 0.696, 2 lobes, follower 0.75), stress 0.580 (safety factor 1.72, p99 von Mises 160 MPa); 5,546 elements,
  11,094 nodes, min element quality 0.404. The plan predicted buckling about 2.87 and stress about 0.58: agrees.
- Plans (wo_fea_plans), glider_eq and glider_2n both planned out: quick holds 0 (stage 3 stays 0.0, as before); 4h holds 1,282.2 s (stage 3 share 0.089,
  `fs.fit` 0 at 2 and 6 cores); overnight holds 1,282.2 s at 2 cores (the whole stage-3 share, `fs.fit` 0) and at 6 cores 8,357.2 s = 1 free-surface case
  (7,075 s) + 1,282.2 s, `fs.fit` 1 as before. Stage 1 gives up the held seconds (overnight at 6 cores: stage-3 share 0.2321, stage 1 0.5179).

## Decision text for DECISIONS (one paragraph per decision)

D-A. A glider whose LES part is planned out (CPU run: no window reaches the physical viscosity) gets its pressure-hull FEA from the sea pressure alone:
`pipeline_windows._sea_pressure_fea` calls the existing `_fea` with a zero wall-pressure field, at `min(the ordered dive depth, the platform's rating_m)`
(the model flies that; `_row` keeps the depth as ordered). The result is in every row of that glider's planned-out part, labelled `load` "sea pressure
only" with `depth_m`; one FEA serves all K windows (sea pressure does not depend on time). Rows that have an LES wall pressure are unchanged and carry no
`load`. Other glider rows with no load (a thin-part fail, an LES error, a cut or killed window, quick's `runs` False) keep their own reasons. This amends
730 (no consumer: the report now reads `fea`) and leaves 842 (a warning, no cap) as it was.

D-B. The FEA runs serial in the one-worker pool the free-surface cases use, before them (they share the CPUs), and counts against the free-surface queue.
`budget.plan` holds `fea_min_s` per planned-out glider inside the stage-3 share, only when the share also holds all the free-surface cases that fit
(`les.fea_hold_s`, else 0: quick and ci hold 0 and the row says "not planned ... stage3.fea_min_s"); `stage3_plan` prices `fs` on the share less the hold and
reports `fea.hold_s`, so the plan's `fs.fit` is the runtime gate's (the gate allows the same microsecond: see Skeptic pass, 1). `profile_stage3_s` is likewise net of the hold. The hold is from plan inputs only (plan.json
stays deterministic); it changes `plan.json` and so the plan hash at 4h and overnight for a CPU run (q24 and q25 plan hashes no longer match).

D-C. The report prints beside the hull warning, for a glider with such a row, `vehicles.<vid>.hull_fea` (load, depth_m, utilization, stress_utilization,
buckling_utilization, each traced to stage3/windows.json) and one HTML line. The warning stays and the verdict is not capped on it. Measured at the
Seaglider's 950 m: utilisation 2.873 (stress 0.580, buckling 2.873) in 622 s on 2 CPUs.

CHANGELOG lines:
- D-A: Stage 3: a glider whose LES part is planned out gets a sea-pressure-only hull FEA (`_sea_pressure_fea`), at min(order, rating).
- D-B: Plan: stage 3 holds `fea_min_s` per planned-out glider (`les.fea_hold_s`, `fea.hold_s`) ahead of the free-surface cases; the FEA runs first in their queue; `profile_stage3_s` net of it.
- D-C: Report: `vehicles.<vid>.hull_fea` and one line beside the hull warning.

## Printed sentences and keys added

- HTML line (as ruled): "Hull FEA (sea pressure only) at {depth} m: utilisation {u} (stress {s}, buckling {b}); above 1 the hull yields or buckles." (`_n` of a `m` node adds the unit, so the test reads "at 950 m").
- Log line (the plan names it): "stage3 {vid} hull FEA (sea pressure only): run={bool} utilisation={u:.3g} | <reason> [{s:.1f} s]".
- Gate-failure reason: the existing template, "not planned: the FEA reserve is {x} s of a {slice} s slice, below stage3.fea_min_s ({m} s): use a larger --budget", with x = the held seconds left. No new sentence form. Deviation from the plan's wording ("stage share left in place of the reserve"): I print the held seconds left as the reserve.
- Existing reason "FEA failed: {e}" reused for a failure.
- Row keys: `fea.load` = "sea pressure only", `fea.depth_m`; `timing.fea_s`, `timing.fea_seconds`. plan keys: `les.fea_hold_s`, `fea.hold_s`.
- report.json: `vehicles.<vid>.hull_fea` (load, depth_m, utilization, stress_utilization, buckling_utilization). SCHEMA unchanged.

## Final-tree checks (orca, 2 CPUs)

- wo_fea_f2 rc=0: tests/test_wo_fea.py (12 at that run's tree: T1 to T10 with T4b and T4c), tests/test_budget.py, tests/test_round23_claims.py (no new hit), and the five tests of tests/test_stage3.py that
  read `profile_stage3_s` / the free-surface refusal clause (m14, r10_m33, the named-budgets, share-decides, smallest-profile tests).
- wo_fea_lint2 rc=0: `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean (57 files).
- wo_fea_t3 (tree before the `profile_stage3_s` fix, 02:40 PST): tests/test_stage3.py, test_report.py, test_wo_fea.py ran with exactly one failure, m14, which
  the fix removes. A re-run of the whole of those files on the final tree (wo_fea_f1) was killed by me at 11 % after 50 min (box loaded; exact pid of my own
  pytest): the whole of test_stage3.py and test_report.py on the final tree is therefore NOT re-run; the only change since wo_fea_t3 is `profile_stage3_s` and T10.

## Not verified

- No full overnight run or stage 3 on a copied run with the new code: the serial order and the free-surface wall-clock margin are tested only with fakes (T4). The lead's fact (on1: free-surface hull 1,496 s of stage 3 against 5,660 s planned) says the share has room, but this FEA-first order costs the free-surface case about 2 x 622 s of delay at 2 CPUs.
- One-thread ccx reproducibility across machines is unconfirmed (rows are hashed).
- The Slocum (1.5 x 0.22 m) FEA was not measured through `_fea`; plan 6b for it is open.
- Mutation testing not run. Whole suite not run (single files only, as ordered).

## Still wrong / open for the lead

- The model Seaglider hull (8 mm Al 6061, assumed) reads utilisation 2.87 at 950 m: the hull yields or buckles in the model; the owner's option A or B (plan section 8) is unanswered. I changed no hull number.
- QUESTIONS_FOR_LAB 4a cites `platforms/seaglider.yaml` for a wall it does not hold (it is `assumptions.yaml:203-237`); the lead may fix that sentence.
- `_row` unclipped vs the new path clipped: the two differ only above the 1000 m rating.

## Skeptic pass

1. Plan `fs.fit` against the run's gate in a 1e-6 s band (budget.py:518, pipeline_windows.py:713). **Real, fixed.** `_fs_gate` now allows the same microsecond
   `stage3_plan` adds (`need_s <= left_s + 1e-6`), so a case the plan says fits is run when the share is `(kept / budget_s) * budget_s` a few 1e-13 s below
   `kept`. The band also existed before this change for `kept = fit * need_s` (no hold); the fix covers both. Regression test T11
   (`test_t11_the_run_gate_runs_the_free_surface_case_the_plan_says_fits_...`): sweeps 2,000 estimates at the overnight budget with a hold of one or two FEAs,
   builds the run's `left` as the run does, asserts the sweep reaches the band (`left < need_s`) and the gate runs every case. Before (the gate line reverted,
   job wo_fea_t11b): fails, 129 of the 2,000 estimates in the band and refused (rc=1). After: wo_fea_sk2 rc=0 (see below). Pins moved: none. Printed sentences: none
   (the refusal text is unchanged; it only fires less often).
2. Report line wording (report.py:1728). **Routed to the lead.** The sentence is the plan's draft, which the plan says the lead approves; the work order names
   only the label. Skeptic's suggestion ("in the model") is a wording change I did not make without that approval. Same for the log line.
3. Gate-failure reason prints the held seconds left as "the FEA reserve" (pipeline_windows.py:436). **Routed to the lead** (accept as disclosed, or name the held
   seconds). Not changed: any other sentence needs approval under section 5.
4. Hand-back accuracy. **Fixed in this file:** "(11)" is 12 tests at the wo_fea_f2 tree (T1 to T10 plus T4b and T4c); T11 is the thirteenth. The rest is as the skeptic
   says and as disclosed above: the before/after table for T1 to T9 uses wo_fea_t1 / wo_fea_base1; T10 was not run against the unfixed `profile_stage3_s`
   (m14 is its before evidence); DECISIONS, CHANGELOG, STATUS, HANDOFF rows are the lead's (drafted above, per the order); no `assumptions.yaml` `fea_min_s` note and no
   QUESTIONS 4a fix (documents, the lead's). Whole `tests/test_stage3.py`: see "Final-tree checks, second pass".
5. `profile_stage3_s` rounds every profile to 6 decimals and floors at 0. **Not a defect, left as is.** The only callers are `freesurface.fitting_budget` (a
   sentence in minutes) and the tests at tests/test_stage3.py:2627-2639; the rounding is what keeps the m14 pin at 0.0 when the hold takes the whole share
   (-2e-13 otherwise). Rounding only when a hold exists would add a branch for no reader.

## Final-tree checks, second pass (after fda6af7; orca, 2 CPUs)

- wo_fea_sk2 rc=0: tests/test_wo_fea.py (13 with T11), tests/test_budget.py, tests/test_round23_claims.py all pass; `ruff check cafe/pm tests` clean; `mypy cafe/pm` clean (57 files).
  (wo_fea_sk, the first run, found a 164-character comment line in the edit and failed ruff: shortened, the tests had passed.)
- wo_fea_rep rc=0: the whole of tests/test_report.py on the final tree (199 tests).
- wo_fea_stg: the whole of tests/test_stage3.py was started and stopped by me (exact tmux session, rc=143) after 55 of 194 tests in 32 min (box load average 17):
  **NOT run whole on the final tree**. What did run on it: the five `profile_stage3_s` / free-surface refusal tests (wo_fea_f2, before the one-line gate change;
  the gate change only widens `need_s <= left_s` by 1e-6 s, and no stage-3 pin sits within a microsecond of a gate boundary that I know of). The lead's whole-file run is still due.
