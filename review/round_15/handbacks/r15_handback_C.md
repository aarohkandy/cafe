# Round 15, batch C hand-back (branch r15-c): M-2, M-32, M-33, M-34, M-35, M-36, M-39

Worktree `/Users/aaroh/Downloads/everything/cafe-r15c`, branch `r15-c` from 09f4ce4. Code and tests are in commit 9953b4e; this file is the second commit. No document outside this file was edited. All test runs were on cafe-orca (proot, 2 CPUs, `pm_r15c`); the laptop ran only numpy scratch measurements of the rigid-body solver and a differential check of the search (see M-32).

What changed, by file:
- `cafe/pm/dtmb5415.py`: `not_judged(root)` (new, M-2); `read_run` checks every speed entry of a file made by this RECIPE through `_speed_readable` and `_real` (new, M-36); `receipts()` and `main()` ask `not_judged`.
- `cafe/pm/vv.py`: `format_table(rows, fmt, not_judged=())` (M-2).
- `cafe/pm/credibility.py`: `_dtmb_rows` asks `dtmb5415.not_judged` (M-2).
- `cafe/reach.py`: `_dijkstra` rebuilt (all edge costs at once, scipy csgraph), `made_good` takes arrays, `_crosses_land` takes index arrays, `_inside` (new), `reach()` (M-32, M-34, M-35).
- `cafe/app.py`: `/api/reach` adds a sentence to `warning` when cells were outside the weather box (M-35). `cafe/static/app.js` needed no change: it already draws every non-land unreachable cell the same.
- `cafe/pm/physics/rigid.py`: `implicit_midpoint` is Newton with the analytic Jacobian (M-33). `cafe/dyn.py`: comment only.
- Tests: `tests/test_vv.py` (M-2, M-36; the DTMB tests live there), `tests/test_reach.py` (M-32, M-34, M-35, M-39 and `made_good` on arrays), `tests/test_dyn.py` (M-33).

Gates run: `ruff check cafe/pm tests` clean; `mypy cafe/pm` strict clean (55 files); whole files `tests/test_reach.py`, `test_vv.py`, `test_dyn.py`, `test_credibility.py`, `test_receipts.py` (and `tests/test_report.py -k reach`, `tests/test_cli.py::test_report_routes_the_reach_map_through_the_environment_when_the_cache_exists`) green before the last line-length edits; the final re-run of the five whole files, after the line-length edits, was green (rc 0).

## Each regression test failing on the unfixed code

Unfixed code = a detached worktree at 09f4ce4 with the three new test files copied in (removed afterwards). 36 tests failed there, all new: `test_r15_m32_*` (3), `test_r15_m34_*` (8), `test_r15_m35_*` (2), `test_made_good_takes_an_array...`, `test_r15_m2_*` (3), `test_r15_m36_a_damaged_speed_entry...` (all 14 parametrisations), `test_implicit_midpoint_reference_solves_its_own_equation...` (3). Tests that pass on both (by design, they guard what must not be tightened): `test_r15_m36_a_file_of_another_recipe...`, `test_r15_m36_what_run_grid_writes_stays_readable` (5), `test_r15_m32_a_cell_no_route_reaches_keeps_the_blocked_label...`, the refusal test of `implicit_midpoint` (a new case, see M-33), and the M-39 tests (they kill mutants, below).

Mutants of the fix, one at a time against `tests/test_reach.py -x`, in a detached worktree at 9953b4e (control unmutated: rc 0; every mutant rc 1):
- `blocked = land | ~inside` to `land` killed by `test_r15_m35_cells_beyond...`; `np.isinf(tb)` label removed, killed by `test_r15_m32_a_return_that_the_current_forbids...`; `if not T > 0` to `if T < 0`, killed by `test_r15_m34_no_budget_is_refused[kw0]`; reserve check removed, killed by `[kw3]`; the order of `np.isinf(t)` and `t > T_s` swapped, killed by `test_r15_m32_a_cell_that_is_only_too_far...`.

## M-2. The report table prints `not judged` for a row whose finest grid has not converged

DECISIONS row: The not-judged rule of the DTMB V&V 20 rows (a row whose finest grid has not converged iteratively) is written once, in `dtmb5415.not_judged(root)` ({Fr: reasons} from `row_notes`, the finest grid's `not_converged_reasons`), and read by the three places that print or store a verdict: `python -m cafe.pm.dtmb5415 report` (the table's last column reads `not judged` in place of `yes`/`no`, through `vv.format_table(rows, not_judged=...)`), `dtmb5415.receipts()` (the context line, as before) and `credibility._dtmb_rows` (`validated: null`, as before). Before, the report table printed `yes` for Fr 0.20, 0.28 and 0.41 of the stored v4 study while the receipt lines under it said the row is not judged; `Vv20` and `vv20_row` do not depend on convergence (they also serve rows that have no grid), and a bare `vv.format_table(rows)` is unchanged. Test: `tests/test_vv.py::test_r15_m2_report_prints_not_judged_for_a_row_whose_finest_grid_has_not_converged`, `..._the_table_and_the_credibility_rows_agree_on_which_rows_are_not_judged`, `..._format_table_marks_only_the_rows_it_is_told_and_needs_one_flag_per_row`.

Amends: rows 345 and 402 (add "(round 15, M-2: the report table follows; one helper, `dtmb5415.not_judged`)"). Row 345 says the credibility table does not judge such a row; it now also says the report table.

CHANGELOG: `python -m cafe.pm.dtmb5415 report` printed `yes` in the |E|<=U_val column for rows whose finest grid had not converged (Fr 0.20, 0.28, 0.41 of the stored study); it prints `not judged`, from `dtmb5415.not_judged`, the one place of the rule that `receipts()` and the credibility table also use (round 15, M-2).

Doc sentences: `docs/RUNBOOK.md` and `docs/CREDIBILITY.md` where they describe the `dtmb5415 report` table: "The last column reads `not judged` for a speed whose finest grid has not converged; those rows are neither yes nor no, and the receipt line below the table gives the reasons."

Could break, checked: `format_table` has two callers, `dtmb5415.main` and `tests/test_vv.py` (default call unchanged; a new `not_judged` of the wrong length is a ValueError). `row_notes` is called by `receipts`, `credibility`, `not_judged`; its return is unchanged. `receipts()` no longer builds `notes` itself, it uses `not_judged(root)` (same reasons, same `rc.context` / `rc.bracket` calls: `tests/test_vv.py::test_receipts_*` green). `credibility._dtmb_rows` reads the same reasons and the `row["note"]` text is unchanged (`tests/test_credibility.py` green). No printed number of the demo moves: only the word in a column of a command that is not part of the demo report.

## M-36. A damaged speed entry makes the file unreadable

DECISIONS row: `dtmb5415.read_run` is the one reader of `run_<grid>.json` and now also checks every speed entry of a file made by this RECIPE (`_speed_readable`): a dict, `ct` a real number (NaN and infinity stay readable: a diverged solver's value, round 13 M-27), `cells` a finite number above 0, `ct_std` a real number when present (a missing one stays readable), and `iters`, `y_plus`, `drift`, `drift_parts`, `scatter` None or real (a bool or a string is not). Anything else returns None, so the file is "unreadable (rerun the grid)" through `stale_notes`, and `tabulate`, `row_notes`, `receipts` and `credibility._dtmb_rows` never see it: they raised KeyError, TypeError or ValueError on a hand-edited entry (an int, a missing `ct` or `cells`, `ct` null or text, `ct_std` null, `cells` 0, `drift` text). A file of another recipe is not checked (its entries are never read, and `run_grid` names it by its recipe). Tests: `tests/test_vv.py::test_r15_m36_*`.

Amends: the DECISIONS row of the round 9 L0 reader (the row that introduced `read_run`; its number was not looked up here). Add "(round 15, M-36: the entries too)".

CHANGELOG: A `run_<grid>.json` with a damaged speed entry (an int, no `ct` or `cells`, a null or text number) is read as an unreadable file and named in the report, instead of ending `receipts()`, `tabulate` and the credibility table in a KeyError, TypeError or ValueError (round 15, M-36).

Doc sentences: `docs/RUNBOOK.md` troubleshooting line for "run_fine.json is unreadable (rerun the grid)": "also printed when a speed entry in it is not a record (a missing C_T or cell count, a text where a number belongs); move the file aside and run the grid again."

Could break, checked: `read_run` callers are `run_grid` (a None is the existing ValueError "cannot be read as a run"; a file `run_grid` itself wrote always passes, entries come from `_case`: int cells, float ct/ct_std, None or float optionals), `_runs`, `_stale`. The old test that a file of the first study (no recipe, `speeds: {"0.20": {}}`) is named "made by recipe None" failed with a first draft that checked every file, so entries are checked only when `recipe == RECIPE`.

Checked on the stored v4 study (`~/cafe-worker/cafe/pmdata/dtmb5415`, read only, through `python -m cafe.pm.dtmb5415 report`): all three run files are readable, `stale_notes` is empty, and the table now ends `yes` for Fr 0.10 and `not judged` for 0.20, 0.28 and 0.41 (ratios 0.4596, 0.6647, 0.3171, 0.02024, unchanged); the receipt lines below it are as before.

## M-32. `why` classification of the reach map

DECISIONS row: `cafe.reach.reach` classifies a cell that is not feasible, in this order, from searches that have no time limit (so "no route" is told from "too far"): `land`; `outside weather data` (M-35); `currents/winds too strong or blocked` (no route exists from the launch point, however long it takes); `beyond endurance or time` (a route exists but takes longer than the horizon); `no way back: currents/winds too strong to return against` (round trip only; the way out fits, no route returns); `beyond endurance or time` (out and back together exceed the horizon). Before, the test was `np.isinf(t)` of a search that stopped at the horizon: in still water 3364 cells read "too strong or blocked", and with a 1.5 m/s current against V = 1 m/s the round trip said "beyond endurance or time" for cells that no horizon makes returnable. `_dijkstra` is rebuilt to make the unlimited search cheap: the cost of every edge is built at once (`made_good` takes an array of velocities, `_crosses_land` an array of indices) and scipy's csgraph solves it; the heap loop is gone. At n = 241 an unlimited search takes 0.1 s on the worker (the loop took 0.63 s at n = 81 and 1.4 s at n = 121, which would have made the receipts' n = 241 round trip about 12 s each). `hours`, `hold` and `radius_km` are unchanged in meaning; `flow_max` is now the largest flow inside the weather box. The pipeline's `report._reach_one` calls the same `_dijkstra` with its horizon as `T_s` and reads `tt <= horizon`: unchanged.

Amends: row 113 (it says "Dijkstra (`cafe.reach._dijkstra`)"; add that the search is csgraph over edge costs built at once, round 15, M-32) and row 216/243 not at all.

CHANGELOG: `/api/reach` told a cell that is merely too far from one that no route reaches, and a cell whose way back the current forbids from one that is beyond the battery: the `why` grid has `currents/winds too strong or blocked` only where no route exists, `no way back: ...` for a round trip with no route home, and `beyond endurance or time` otherwise (round 15, M-32). `cafe.reach._dijkstra` builds its edges at once and uses scipy's csgraph.

Doc sentences: `docs/PHYSICS.md` reach section (if there is one) and `README.md` line 181 need nothing; if a document lists the `why` strings, add the two new ones (`outside weather data`, `no way back: ...`).

Could break, checked:
- Differential check of the new `_dijkstra` against the old heap version (copied from 09f4ce4), 60 random fields (21, 31, 41 cells; flow up to 1.5 V; random land with walls; with and without `back`; limits from none to 0.3 of the span): 122,680 cells, the sets of cells within the limit are identical (0 mismatches), the largest relative difference of a settled time is 0 on the laptop and 6.3e-15 on the worker (the dot product `c @ d` became `c0*d0 + c1*d1`). A printed number of the demo could move only if a cell's time lay within about 1e-14 of the horizon. `report._reach_one` prints the radius of the farthest reachable cell per bearing; I did not rerun the demo report, so I state the number as unchanged by argument, not by measurement: the lead's next demo run should confirm `reach` is unchanged against q15.
- The analytic tests of `tests/test_reach.py` (uniform current, shear, rotation, back, one-cell walls, diagonal walls) are green on the new `_dijkstra`; `tests/test_report.py -k reach`, `tests/test_cli.py` reach test and `tests/test_receipts.py` (the fleet receipts run `reach.reach` at n = 121 and 241) are green.
- `receipts.py:559-560` and `app.py` are the only other callers of `reach.reach`; both read keys that still exist. `reach.py` is not in the mutation or coverage gates (row 205).

## M-33. `implicit_midpoint`

Measured first (laptop, numpy only, `rigid.py` loaded by path): 1000 random diagonal inertias per cell of the table, dt = 0.1, fixed point failed for dt|w| = 0.3 at ratio 10, 50, 1000: 2, 129, 457 (the reviewer's 4, 113, 467 are the same order); at dt|w| = 1 it failed 162, 433, 757 at ratios 10, 50, 1000, so the claim "converges for dt|w| < 1" was wrong at every ratio but 1. The contraction constant is about dt/2 ||d omega_dot/dw||, which carries the inertia ratios. I fixed the solver rather than only the sentence: Newton from the Euler step with the analytic Jacobian I^-1([I w]x - [w]x I). Newton: 0 failures of 1000 at dt|w| = 0.3 for every ratio (residual below 2e-14); at dt|w| = 1: 0, 0, 2, 22 at ratios 1, 10, 50, 1000; at dt|w| = 3: 0, 14, 28, 105 at ratios 1, 10, 50, 1000. It converges at diag(2, 3, 5), dt = 50, which the old test used as its refusal case, so that test now has a new refusal case (diag(14.8, 3.9, 15.9), w = (1.6, -1, 0.5), dt = 6.3, dt|w| = 12, found by search; it fails for 30 of 30 draws within 0.1 % of those values), and the old case is a converging case.

DECISIONS row: `rigid.implicit_midpoint` (the reference integrator that grades `cafe.dyn`) solves the midpoint equation with Newton's method, not a fixed-point iteration whose documented bound (dt|w| < 1) the inertia ratios break. Convergence is stated as measured (the table above); outside it the function raises RuntimeError. `cafe.dyn` keeps 3 fixed-point sweeps and no check, as before; its comment now says the contraction depends on |w| and the inertia ratio and points to `rigid.implicit_midpoint`; `tests/test_dyn.py` holds `dyn` to the reference within 1e-8 at dt = 1 ms for |w| = 3.7. Tests: `tests/test_dyn.py::test_implicit_midpoint_reference_solves_its_own_equation_where_the_fixed_point_did_not` (3 cases: the reviewer's I = diag(3.734, 0.013, 1.545), dt = 0.1; diag(1, 20, 400); and the old dt = 50), `..._refuses_a_step_it_cannot_solve`.

Amends: none by number (no DECISIONS row names the solver); CHANGELOG.md line 98 (the dyn.py midpoint entry) can be left.

CHANGELOG: `rigid.implicit_midpoint` (test reference) uses Newton's method; the fixed-point version raised for dt|w| = 0.3 with an inertia ratio of 50 and its "converges for dt|w| < 1" was wrong (round 15, M-33). The `dyn.py` comment on its 3 sweeps no longer claims the correction is small per step by itself.

Could break, checked: `implicit_midpoint` has one caller, `tests/test_dyn.py` (dt 1e-3 body-rate test to 1e-8: green; Newton and the fixed point reach the same root to rounding). No pipeline code calls it. `cafe/dyn.py` changed in a comment only.

## M-34. A zero or negative time budget is refused

DECISIONS row: `reach.reach` raises ValueError "no time or energy budget: nothing is reachable" when `min(hours, endurance)` is not above 0 (hours 0, negative or NaN; battery 0), and refuses a reserve outside [0, 1) ("the battery reserve must be in [0, 1)"); `app.py` already maps ValueError to a 400. Before, `reach(veh, env, 10, -95, hours=0.0, n=9)` returned radius 0 and all 81 cells reachable in 0 h. Tests: `tests/test_reach.py::test_r15_m34_*`.

Amends: rows 113 and 216 do not mention T = 0; no amendment, a clause can be added to 113: "a zero budget is refused".

CHANGELOG: `reach.reach` refuses a time or energy budget of 0 (or less, or NaN) and a battery reserve outside [0, 1) with a ValueError, instead of a map where every cell is reachable in 0 h (round 15, M-34).

Could break, checked: callers (`app.py` already checks `0 < hours <= 240`; `receipts.py` uses 12 h and a battery of 1e9 Wh; `hangar.check` refuses `battery_wh <= 0`) cannot reach the new error with their inputs; the default reserve is 0.15.

## M-35. The reach search is limited to the loaded weather box

Lead decision: limit the search to the box, no silent edge hold. `Env.at` clips to the nearest edge of the box (`self.lat`, `self.lon`, lon in 0..360); `reach._inside(E, lat, lon)` tests a point against exactly those arrays (an environment without `lat`/`lon`, a test stub, is taken to cover everything). A cell outside is blocked for the search like land, its `why` is `outside weather data`, its `hours` is NaN and its `hold` False; a launch point outside raises "launch point is outside the loaded weather data". `reach()` returns `outside_cells` and `weather_box` ([lat min, lat max, lon min, lon max], None when everything is inside); `/api/reach` adds to `warning`: "the loaded weather covers a to b N and c to d E; the N grid cells beyond it are shown as out of reach ('outside weather data'), not guessed from the edge". The grid and `radius_km` are unchanged. The `adverse = 0.25` call goes through the same function.

DECISIONS row: as above, "Reach search stays inside the loaded weather box" (round 15, M-35). Amends row 113: "Water outside the ingested data counts as unknown" was true of the report (`_reach_one` masks with `env.inside`) and not of the legacy `/api/reach`; it is now true of both.

CHANGELOG: `/api/reach` no longer holds the weather box's edge value for cells beyond it (a fast vehicle at high latitude searched up to 400 km in a box of +-4 degrees); those cells are blocked, marked `outside weather data`, and the answer carries a warning that names the box (round 15, M-35).

Doc sentence for the user manual / RUNBOOK if it describes the reach layer: "Cells beyond the weather files' area are drawn as out of reach, not extrapolated."

Could break, checked: tests that pin `radius_km` or grid size: none changed (they use stubs without a box). `flow_max` over all cells became over the cells inside the box; for an environment without a box it is the same. No test of the `/api/reach` endpoint exists (no `TestClient` in `tests/`); `app.py` compiles and the only new reads are `outside_cells` and `weather_box`, which every `reach()` result carries. Not run: a real WRF box (needs the wrfout files).

## M-39. Tests for the reach rules

One assertion per surviving mutant, all six killed (the control passes): `np.linspace(top, bottom, 6)` to `(top, top, 6)` killed by `test_r15_m39_a_glider_is_routed_through_the_mean_current_over_its_dive_band[limits0-35.0]`; `battery_wh * (1 - reserve)` to `battery_wh` and `hotel_w + 1.0` to `+ 100.0` both killed by `test_r15_m39_endurance_is_the_battery_less_the_reserve_over_the_power`; `0.8 * V` to `1.0 * V` by `test_r15_m39_a_vehicle_holds_station_in_flow_up_to_80_percent_of_its_speed[0.9-False]`; the diagonal `and` to `or` (now `&` to `|`) by `test_r15_m39_a_diagonal_with_one_land_corner_is_allowed_and_with_two_is_not`; the default `glide_band (5, 100)` to `(5, 5)` by `...dive_band[limits1-52.5]`.

DECISIONS row: The reach rules that no test pinned are pinned in `tests/test_reach.py::test_r15_m39_*`: the glider's flow is the mean over 6 depths from top to bottom of its `glide_band` (default 5 to 100 m); endurance is `battery_wh * (1 - reserve) / P` with P from `ctrl._level_power` (a glider: `hotel_w + 1.0` W, an assumed pump power) and the horizon is the lesser of that and the hours asked; a vehicle holds station where the flow is below 0.8 of its speed (an assumed margin, the tests use 0.79 and 0.81); a diagonal step is blocked only when both corner cells are land. Amends row 205 not at all (`reach.py` stays outside the mutation and coverage gates); REVIEW.md rows 7 and 8 can cite the tests.

CHANGELOG: Six hand-made single-edit mutants of `cafe/reach.py` (glider band, reserve, hold factor, diagonal rule, pump power, default band) survived `tests/test_reach.py`; each is now killed (round 15, M-39).

Could break: nothing in the code; tests only. The two assumed values pinned (1.0 W pump, 0.8 hold margin) are assumptions already in the code, not new ones.

## What I noticed and did not fix (outside the findings or the batch)

- `cafe/dyn.py` solves the Coriolis midpoint with exactly 3 fixed-point sweeps and no residual check (the reviewer's note under M-33). Only the comment was fixed. A check or Newton there would change every vehicle's dynamics and the demo's numbers; it is a decision for the lead.
- `reach.reach` takes `hours` up to anything when called directly (the endpoint caps at 240). Not changed.
- `Env.lon` for a box that straddles longitude 0 would break `_inside` (and `Env` itself: `lo, hi = sorted(lon360(...))`); not new, not covered by a test, no such box in use.

## Needs from other batches

- Batch D (documents): the DECISIONS rows above, in this order for numbering: M-2, M-36, M-32, M-33, M-34, M-35, M-39. Amendments: rows 113 (M-32 csgraph, M-34 zero budget clause, M-35 "outside the ingested data" now true of `/api/reach`), 345 and 402 (M-2), the round 9 L0 `read_run` row (M-36). CHANGELOG lines as written. Note for the row on M-33: the measured table is in this file and in the `rigid.implicit_midpoint` docstring.
- Batch A and B: none. No file of theirs was touched (`cafe/pm/vv.py`, `credibility.py` and `dtmb5415.py` are in C's list; `app.py` and `dyn.py` have no other batch's finding). If a batch changes `credibility._dtmb_rows` or `dtmb5415.row_notes`, M-2's helper reads `row_notes(root)[fr]["grids"]` finest first.
- The lead: a demo report rerun to confirm the `reach` block of the report is bit-for-bit q15 (see M-32), and `tests/test_config_docs.py` after batch D if a document it reads changes.

## Adversary pass (after commit 1a4dac2): M-33, M-36, M-34 follow-ups

- **M-33 (Newton raised at large |w|, short step).** Cause: `implicit_midpoint` stopped on an absolute `max|step| < 1e-14`, below the rounding of w1 itself (about 1e-16 |w1|) once |w| is above roughly 100. Fixed in the one place, `rigid.implicit_midpoint`: the stop is `max|step| < tol * max(1, max|w1|)`; the docstring and the error text no longer blame step length alone. Callers: only `tests/test_dyn.py` (`cafe/dyn.py` has its own 3 sweeps and does not call it); for |w| below 1 the test is unchanged, so every earlier case (the 1e-3 s body-rate test, the three M-33 cases, the dt = 6.3 refusal) behaves as before. Test: `tests/test_dyn.py::test_implicit_midpoint_reference_settles_at_a_large_angular_velocity_and_a_short_step` (|w| = 300 and 1000, ratios 3 and 10, 100 draws each, dt|w| = 0.01, residual below 1e-12 |w|; plus the reviewer's diag(1,2,3) case against the old fixed-point answer). Failed on the unfixed code (4 of 4), passes after.
- **M-36 (damaged `surf_level`).** `discretization` puts `surf_level` in a set; a list or dict made `tabulate`, `row_notes`, `not_judged`, `receipts` raise TypeError once three grids were present. Fixed in `_speed_readable` (the one validator behind `read_run`): `surf_level` must be absent, None, an int or a string (what `_case` writes). Siblings swept: the other keys the readers index or hash are `ct`, `cells`, `ct_std`, the five optional numbers (all already checked); `converged` is only tested with `is True` / `is None`. Two cases added to the `DAMAGE` table of the parametrised test (`surf_level list`, `surf_level dict`): failed on the unfixed code, pass after. The stored v4 study still reads (`python -m cafe.pm.dtmb5415 report` on orca: 4 Froude rows, 12 cases). Other stored runs under `pmdata/runs` were not looked at (not mine to touch).
- **M-34 (surviving mutants).** Tests only: `test_r15_m34_a_reserve_of_zero_is_inside_the_documented_range` and `test_r15_m35_a_point_exactly_on_the_edge_of_the_weather_box_is_inside` (all four edges inclusive, a hair outside excluded). Mutants in a detached worktree, one at a time, `tests/test_reach.py -x`: control rc 0; `0 <= reserve` to `0 < reserve`, and each of the four `_inside` comparisons made strict, all rc 1 (killed).
- **Not problems / left as stated:** the demo-report rerun and a real WRF box are for the lead (no demo number moves: `reach`, `rigid` and `dtmb5415` changes here do not touch a printed demo value; `implicit_midpoint` is a test reference only). No `/api/reach` endpoint test: the repo has no endpoint tests (`TestClient`), out of scope. `cafe/dyn.py` keeps its 3 sweeps: the lead's decision, as above. The dt = 6.3 refusal case is still delicate near the boundary; unchanged by this fix (it fails by non-convergence, not by the tolerance), and it passes on orca. Docs and DECISIONS/CHANGELOG text stay with the docs step: add to the M-33 row "the stop test is relative to |w1| (round 15 adversary pass)" and to the M-36 row "`surf_level` is checked too".
