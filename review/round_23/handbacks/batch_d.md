# Batch D hand-back (M-8, M-9 per OD-4)

Branch r23-d, base f62defd. Files: cafe/app.py, cafe/live.py, cafe/pm/budget.py, tests/test_round23_d.py (new), this file. No other file touched.
(tests/test_app.py and tests/test_live.py named in merged.md do not exist; the app and live pins live in tests/test_round21_e.py, test_round22_d.py and test_round22_m.py, which ran green unchanged.)

## What changed and why

M-8 (OD-3: do it).
- `app._body_shape(body, need_t0=False)`: one guard, a 400 each, for `drones` (non-empty list of objects; the old message "add at least one drone"), `links` (absent, null or a list: "links must be a list"), `t0` (a string; absent only when `need_t0` is false: "t0 must be a date-time string"). `check_fleet` and `live_create` both call it first, so `live_create` no longer reads `x.get` of a str or int. The old per-link check ("each link joins two different drones") still handles a list entry that is no object.
- `check_fleet`: `samples` must be an int, not a bool (`2.5`, `24.0`, `64.5` were accepted); message now "max_hours must be in (0, 48] and samples a whole number in [1, 64]". `max_hours` uses `finite_real` (same answers as the old isinstance test on this domain).
- `live.create`: the same shape in ValueError form (the global handler turns it into a 400): drones and links lists of objects, `t0` a string; `links=body.get("links") or []` (a null `links` was a TypeError in `World`).
- `t0` is REQUIRED only for a live session. For `check_fleet` (missions, emulations) it is checked only when present: the worker reads it, a body without one is queued and fails there (not a 500), and every existing test body has none. Requiring it there moves 20+ pins for a case that is not a 500. Say if the lead wants it required; then the fixtures of test_round21_e, 22_d, 22_m get a `t0`.

M-9 (OD-4: `budget.throughput` only; D-3 and D-5 go to PROBLEMS).
- `budget._need(v, where, positive)` (reuses `jsonio.finite_real`): a PlanError naming the leaf. Called where the plan multiplies by the leaf, not in `throughput()`: the plan also takes a dict a caller passes (`thr=`), which `throughput()` never sees, and D-4 reproduced it that way. Leaves checked: `stage1.<cls>.s_per_batch_day` and `.s_per_member_day` (only for a class the mission flies), `jax-lbm-d3q19-{cpu,gpu}.per_device` (only the one the plan asks for), and a stage-1 entry's `sortie_min` and `mission_days` (sibling found here: a NaN `sortie_min` made the UAS scale factor NaN, `abs(nan - 1) > 1e-9` is False, so the cost was silently not scaled).
- DEVIATION FROM THE DEFAULT, loudly: the lead's note says "non-positive rate refused". For the two stage-1 COSTS that is unsafe: `bench/throughput.py` writes `s_per_member_day` 0.0 (and `s_per_batch_day` 0.0) on purpose when the slope is not resolved (`slope_resolved: false`; tests/test_bench.py:84-85, 125; tests/test_budget.py:153). Refusing 0 would make a plan error out of a table `make bench` writes. So costs: finite and at least 0 (NaN, inf, -inf, negative refused); rates (`per_device`) and the sortie figures: finite and above 0.

## Decision text for DECISIONS (none needs the owner)
Round 23, M-8: a fleet body's `drones`, `links`, `t0` and `samples` are shape-checked first (400, not 500); `samples` is a whole number; `t0` is required for a live session and checked when present for a mission. M-9 (D-4): the plan refuses a throughput leaf it multiplies by that is not finite (stage-1 costs at least 0, rates and sortie figures above 0) with a PlanError naming it; D-3 (subgrid promote) and D-5 (CAFE_PM_OVERLAY) to PROBLEMS.

## Pins moved
None. No existing test changed. Behaviour that moved with no pin: `links: false`, `0`, `""`, `{}` were read as "no links" and are now a 400; `links: null` stays accepted. A stored mission with `samples: 24.0` re-flown through `create_emulation` is now a 400 (the app page sends an int).

## Hunks / items for other batches
- PROBLEMS.md (batch G): D-3 `subgrid.promote_calibration` / `recalibrate` take a NaN, inf or negative leaf (a real window's ustar is positive; `--gpus 0` writes no inflow; only the GPU path or a hand edit reaches it); D-5 `CAFE_PM_OVERLAY` is read lazily mid-run and a non-mapping overlay is an AttributeError. Reachability as D wrote it; I did not run either.
- Siblings left, not in my files or not named: `cafe/pm/stage3/freesurface.py:rate` reads `config/throughput.json[openfoam-pimpleFoam-les].cell_updates_per_s` straight from the file with no finite test (a NaN there gives a NaN free-surface solve time in `fs_plan`); `cafe/planner.py:throughput` the same for the older planner; `budget.measurement_warnings` compares `load_1min > ...` (a NaN is only a missing warning). `live.create`'s `seed` and the mission's `seed`, `reserve` are not shape-checked (`seed: "a"` is a TypeError in `World`, a 500 in a live session). None is in merged.md's list; say if the lead wants any in.

## q25 against q24
No change in any verdict, count, interval or printed number: the shipped config/throughput.json passes every new check (test `test_m9_the_shipped_table_is_a_plan`, gpus 0 and 1, demo mission), and the demo never goes through the app.

## Remaining claims and the test that holds each
- "a 400 for a body whose drones/links/t0/samples has the wrong shape", every handler: `test_m8_*` (4 handlers x the shape table, 378 test cases in the file in all).
- the edges: samples 1 and 64 accepted, 0, 65, 2.5, 24.0, True refused; costs 0 accepted and -1e-300 refused; rates 1e-300 accepted and 0 / -0.0 refused: `test_m8_samples_that_were_accepted_still...`, `test_m9_a_stage_1_cost_of_0_or_more...`, `test_m9_a_rate_above_0...`.
- the PlanError names the leaf: `test_m9_a_stage_1_cost_that_is_not...`, `..._rate_that_is_not...`, `..._sortie_minutes_and_days...`.
- a leaf the mission or backend does not use is not read: `test_m9_the_leaves_the_plan_uses...`, `test_m9_a_rate_the_other_backend...`.

## Evidence (orca, proot, 2 CPUs per job; logs in ~/cafe-worker/logs)
- Before (detached worktree at f62defd with the new test file copied in, `pm_r23db`): r23d_b4 rc=1, FAILED lists the guarded cases: drones 8 of 52, links 32, t0 24 + 1 + 5, samples 60, `live.create` drones 7 / links 7, sortie 28 + 1, rates 15, costs 72, "reaches nothing" 1. Tests of behaviour that was already right (valid bodies, the link entries that are no object, max_hours, "still a plan" cases) pass before and after, by design.
- After (`pm_r23d`): r23d_4 rc=0, 378 passed.
- Existing files that import what I touched: r23d_ex1 rc=0, 1120 passed (test_budget, test_bench, test_round21_e, test_round22_d, test_round22_m, test_round17_a, test_round18_a, test_round19_c, test_round20_c, test_round21_c, test_whatif, test_par), `-n 2`.
- r23d_lint2: `ruff check cafe/pm tests/test_round23_d.py` clean, `mypy cafe/pm` clean (57 files).

## Hostile attempts
NaN, +-inf, -0.0, 10**400 and -10**400, bool, str, None, a list, the boundary and the value just past it (1e-300, -1e-300, 0, 0.0, -0.0) for every leaf; the three handlers with every drones/links/t0/samples shape including `[[]]`, `[None]`, `{}`, `""`, `0`, `False`; t0 absent against null against a number; the CPU rate bad in a GPU plan and the reverse; a class that is not flown with a bad leaf; a UAS `sortie_min` bad through a real plan of the demo; the shipped table. Not tried: a real HTTP client (httpx absent), the app in a browser, a real `live.create` through `World` (the environment is stubbed; `live_create` is stubbed at `live.create`).

## Not verified
Coverage of the added `budget.py` statements was not measured (no `--cov` run); every added line is run by a test in the file by reading (member_cost loop and raise, both `lbm_rate` branches, both `bench_sortie_rate` checks). The full suite, the gate and mutation were not run. No mutant was run: the bounds are covered by the edge rows above.

## Leftovers
Orca: ~/cafe-worker/cafe/pm_r23d, pm_r23d2, pm_r23db and pmdata/r23d_lint.sh removed at the end; logs r23d_* stay in ~/cafe-worker/logs. Laptop: the detached worktree ../cafe-r23d-base removed.
