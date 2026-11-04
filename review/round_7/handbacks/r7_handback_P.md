# Round 7 hand-back, batch P (emulator, planner, workers) -- branch r7-p

Fixed: M-6, M-7, M-14, M-22, M-25, M-37, M-38, M-46 (the `WORKER_GB` comment), M-47 (the `Emulator.append` lock, plus a matching `add_rows` test). Not fixed: none.
Commit message attribution uses the session's attribution line (Claude Sonnet 5.5), not the "Opus 5.5" in r7_common.md.

## Per finding

**M-6** (cafe/pm/whatif.py `_fits` ~l.346, new `is_base`, `run_variant` ~l.296-310, new `key_cols` ~l.402, `fit_class` ~l.420-433; cafe/pm/emulator.py `Emulator.__init__` `point_cols`, `holdout_report`)
- `_fits`: after the joint halving of shift and move fails, the move is dropped and the shift halved (duty kept); the all-zero change only when nothing is left. The existing `test_a_variant_that_does_not_fit_is_shrunk_and_finally_dropped` is unchanged and still passes.
- `design` keeps the all-zero entry in its output (so design.json still records it); `run_variant(..., mods=None)` (new last argument, pipeline passes `mods`) does not run a vehicle whose mod `is_base` and reports it in the existing skipped dict with "the variant equals the base mission". Deviation from the wording of the fix ("design omits"): design cannot omit, `apply(mission, mods)` has already made the mission; skipping happens in `run_variant`.
- `fit_class` counts points by `key_cols(cls)` = deploy_h, lon, lat + TASK[cls]; `Emulator(point_cols=...)` splits the hold-out and picks the fresh-draw points on the same key (default: all features, so every other caller is unchanged).
- Tests (tests/test_whatif.py end): `test_a_vehicle_at_the_box_edge_whose_move_is_invalid_keeps_its_shift_and_its_duty`, `test_no_variant_of_the_demo_is_the_base_mission_again_and_every_usv_variant_has_a_shift`, `test_a_vehicle_whose_change_is_empty_is_not_run_and_says_why`, `test_replicates_of_one_mission_are_one_feature_point_whatever_their_environment_medians`, `test_the_emulator_of_a_class_is_fitted_on_the_mission_columns_as_its_points`; tests/test_emulator.py: `test_the_holdout_splits_on_the_point_columns_so_replicates_with_other_noise_columns_stay_together`.
- Before (old code, new tests): all five whatif tests and the emulator test FAIL. After: pass.

**M-7** (cafe/pm/pipeline.py `s_emulator` ~l.1176, 1185-1187, 1220; whatif.py `DRAWS`)
- `first = ceil(len(res["U"]) / batch)` (res.pkl has `U`, not `n`); variant k runs `range((first + k) * batch, (first + k + 1) * batch)`, fresh block j = `first + len(variants) + len(n_fresh)`. `DRAWS` reworded (still contains "its own members").
- Tests (tests/test_pipeline.py end): `test_no_variant_and_no_fresh_draw_reuses_a_member_stage_1b_used` [48/16/3 variants, 96/32/1, 256/64/1 (4h-sized)]. The flip search's Stage 1 fallback runs the base members on purpose (common random numbers) and is excluded.
- Existing tests that asserted the old offsets and were changed to the new correct ones: `test_the_variant_runs_stay_inside_the_emulator_share` (variants `range(16*(k+1), ...)` -> `range(16*(3+k), ...)`, because the fixture's stage 1b has 48 members) and `test_the_hold_out_is_rechecked_on_members_no_training_row_used` (same, and the fresh-block threshold `16*(n_var+2)` -> `16*(3+n_var)`). Both fail on the old code with the new expectations.
- Before: 3 of 3 parametrisations FAIL; after: pass.

**M-14** (pipeline.py ~l.1169): `n_var = sizes["variants_no_refit" if free else "variants_refit"]`. Test `test_a_calibration_without_a_refit_sizes_the_variants_for_the_emulators_own_share` (calibration file, no refit: share 5 s, planned_variants 0 = variants_refit, was 3). Before FAIL, after pass.

**M-22** (pipeline.py `_stage1_checks` ~l.851-857): note names the profile and the share when `n_max == N_MAX[budget]`, the share when `n_max < N_MAX[budget]`; check logic unchanged. Test `test_the_ensemble_size_note_names_the_profile_that_caps_the_ensemble_and_the_share_when_it_is_the_share`. Before FAIL, after pass.

**M-25** (emulator.py `fit` ~l.187): leave-one-out distances on `np.unique(z.round(9), axis=0)`. Test `test_the_range_threshold_ignores_replicate_rows` (120 rows x5: same threshold as once, refused share equal within 0.02; was 0 / 1.0). Before FAIL, after pass. Note: a table with a single distinct point now has threshold inf (cKDTree k=2 on one point) instead of 0; such a table cannot be fitted by the pipeline (MIN_ROWS distinct points), so no special case was added.

**M-37** (par.py `_cgroup_cpus(root)` l.57, `workers()`): v2 `cpu.max`, else v1 `cpu/cpu.cfs_quota_us` / `cfs_period_us` (-1 = none). Test `test_the_cgroup_v1_cpu_quota_cuts_the_cpus_like_the_v2_one_does` (8 parametrisations on a tmp tree, 64 CPUs: 800000/100000 -> 8, 150000 -> 1, -1 -> 64, v2 wins over v1, garbage and zero period -> 64, empty tree -> 64). The older v2 tests still pass unchanged. On the old code with a stub `_cgroup_cpus` (the test patches that name) 7 of 8 FAIL (the 8th expects 1, which the container's real cpu.max gives); after: pass.

**M-38** (budget.py `plan` PlanError): message now ends "The 45 GB is the model's figure (linear from one measured 6-day point), not a measurement: measure the peak memory of a longer window before relying on it". `bench/mem.py`, which merged.md names, does not exist in the repository, so the text does not point to it. Test `test_the_refusal_of_a_long_window_says_its_memory_figure_is_the_models_and_not_a_measurement`. Before FAIL, after pass. RUNBOOK text: see below.

**M-46** (budget.py l.52-54): comment now "0.81 to 0.84 GB measured in round 5 by B's mem.py (the date is not recorded; the script and its output are not in the repository); re-measure the peak memory of a worker". Test `test_the_worker_memory_comment_carries_no_date_it_cannot_have_and_names_what_is_missing` is in tests/test_budget.py (not test_config_docs.py, which another batch owns). Before FAIL, after pass.

**M-47 (lock part)**: tests/test_emulator.py `test_append_holds_the_table_lock_once`, `test_threads_appending_to_one_table_lose_none` (4 threads x 5 rows of 300 kB; POSIX flock); tests/test_whatif.py `test_add_rows_holds_the_table_lock_once`. Mutants (`with locked(...)` replaced by `contextlib.nullcontext()` in `Emulator.append` and in `add_rows`): all three FAIL (threads test: 14 of 20 rows lost); with the lock: pass. The `R6_M9` part of M-47 is tests/test_config.py (not mine).

## Doc text (for the lead)

DECISIONS rows (`| ? | ... |`):
- M-6: `| ? | A variant keeps its shift and duty when only its move is invalid (the move is dropped, then the shift halved); the all-zero change only when nothing is valid, and that vehicle-variant is not run (skipped with "the variant equals the base mission"). A feature point is the mission columns (deploy_h, lon, lat, task), for the MIN_ROWS gate, the hold-out split and the fresh-draw points. | Review round 7, M-6. 3 of 6 UAS and 3 of 6 USV variants of q7 were the base mission again, and member-draw replicates counted as distinct points. Amends row 213. |`
- M-7: `| ? | Variant k runs the block of batch members number (first + k), first = ceil(members stage 1b used / batch); fresh-draw blocks follow the last variant. | Review round 7, M-7. Variant 0 reused stage 1's second batch. Amends row 213. |`
- M-14: `| ? | The number of variants is variants_no_refit when stage 1b was free (the share includes stage 1b's), else variants_refit. | Review round 7, M-14. The count and the share used different tests, so the clock decided the number of rows. Completes row 337. |`
- M-22: `| ? | The ensemble_size note names the budget profile (budget.N_MAX) when it caps the ensemble, the stage-1 share when that does. | Review round 7, M-22. q7 used 13 % of its share and the note blamed the budget. |`
- M-25: `| ? | The range threshold is the 99 % quantile of nearest-neighbour distances between distinct z-scored feature points. | Review round 7, M-25. Replicates counted at distance 0. |`
- M-37: `| ? | par.workers() also reads the cgroup v1 quota (cpu/cpu.cfs_quota_us over cfs_period_us). | Review round 7, M-37. Amends rows 266, 298. |`
- M-38: `| ? | The PlanError for a window that does not fit the memory says its environment figure is the model's. No number moves. | Review round 7, M-38. |`
- M-46: `| ? | WORKER_GB's comment carries no date; the measurement is of round 5, script and output not in the repository. Row 281's "2026-11-05" is corrected the same way. | Review round 7, M-46 (budget.py part). Amends row 281. |`
- M-47: tests only; no row needed.

CHANGELOG lines: one per finding, e.g. "Round 7 M-6: emulator variants keep shift and duty when only the move is invalid; empty variants are skipped; feature points count mission columns." (M-7: "variants and fresh draws use members after those stage 1b used"; M-14: "variant count follows the same free test as the share"; M-22: "ensemble_size note names profile or share"; M-25: "range threshold on distinct points"; M-37: "workers() reads the cgroup v1 CPU quota"; M-38: "memory refusal says the figure is the model's"; M-46: "WORKER_GB comment without an invented date"; M-47: "tests for the Emulator.append and add_rows lock".)

docs/RUNBOOK.md section 1 (M-38): "About 15 days of the demo box fit 32 GB; a longer window needs more memory or a smaller box (`pad_deg`). The memory figure is the model's (linear from one measured 6-day point), not a measurement." tests/test_config_docs.py should assert it (batch owning RUNBOOK).
docs/PHYSICS.md line 890 (DRAWS paragraph): replace "(variant k: members (k + 1) x batch up to (k + 2) x batch - 1; the baseline row keeps members 0 up to batch - 1)" with "(variant k: the block of batch members after the ones Stage 1b used, k blocks further on)".
DECISIONS row 213 and 281 texts need the same corrections (row 281: drop "2026-11-05").

## Needs from other batches
- RUNBOOK / PHYSICS / DECISIONS edits above (lead or the docs batch).
- test_config_docs.py assertion for the RUNBOOK sentence (M-38) if wanted.
- Nothing else in files I do not own.

## Commands and results (homebase, PMX=pm_r7p, PM_CPUS=1)
- Fixed code, whole files: `pytest tests/test_par.py tests/test_budget.py tests/test_emulator.py` rc=0 (128 tests); `tests/test_whatif.py tests/test_pipeline.py` (12g) rc=0; after the lint fixes the five files again under `coverage run`: rc=0.
- Coverage of those runs: budget.py 100 %, emulator.py 100 %, whatif.py 100 %; par.py misses l.120 (`_mapped`, used only in worker processes) and pipeline.py misses lines outside my changes (69-74, 79-80, 100, 125, 279-280, 304, 313-314, 369-372, 1223-1224, 1306: covered by other test files or not by these five); every line I changed is covered.
- `ruff check cafe/pm tests bench`: All checks passed. `mypy cafe/pm`: no issues in 54 source files.
- Fail-first: throwaway `git worktree add --detach ../cafe-r7p-old premission-step4` with my five test files copied in: `-k` on the new and changed tests: 24 FAIL, 4 pass (the four that pass on old code are the three lock tests, whose fix already exists, and par case `files1-1`: see mutants above); mutant/stub run: 7 par + 3 lock tests FAIL as quoted above. No `git stash` used. No container of mine is left running.
