# Review round 6, batch P hand-back (M-2, M-6, M-23)

Branch `r6-p`, worktree `/Users/aaroh/Downloads/everything/cafe-r6p`. All three findings are fixed.

## Incident (shared `git stash`), resolved

I ran `git stash push -- cafe/` / `git stash pop` to test the old code; the stash stack is shared by every worktree, so my pop and builder C's crossed and for a few
minutes each tree held the other's `cafe/` edits. My tree was restored from the diffs (C's edits removed from it). Checked afterwards: `git diff 77732a7 HEAD -- cafe/`
(the dangling stash of my work) shows only my later line-length/mypy edits in budget.py, emulator.py and stage3/freesurface.py; config.py, env/hycom.py, env/ocean.py,
env/orca.py, `__main__.py` and mission.json are identical to e9bf044 in `r6-p`; and C's branch `r6-c` holds only C's files. I did not edit C's worktree. No `git stash` since.
(The "before" results below were produced by that stash run: the new tests on the old `cafe/`.)

## M-2  memory model (budget.py, pipeline.py, par.py)

- `budget.py`: `ENV_GB_PER_DAY` is gone. `ENV_REF_GB, ENV_REF_DEG2_DAY = 9.0, 14*34*6` (the one measured point) and `ENV_GB_PER_DEG2_DAY` (0.0031). New
  `padded_area_deg2(mission)` (the box ingest downloads: `pipeline.padding` each side, longitude wrap, no box = the demo's 14 x 34), `env_model_gb`
  (linear in area and days; exactly 9.0 for the demo), `env_gb(mission, cache)` = max(model, every `*.zarr` below the cache (`rglob`, so `orca/*.zarr`) plus the
  mission's ocean store (`ocean.store_path`; a lab store without `path` is skipped)). `plan(env_gb=None)` uses `env_model_gb`.
- `pipeline.py`: `Context._make_plan()` (the old body of `__init__`, now run under `par.limit(None)` so a plan never inherits the worker cap of an
  earlier plan of the same run) and `Context.replan()`; `s_ingest` ends with `ctx.replan()`. A changed plan replaces `ctx.plan`, rewrites `plan.json`,
  is printed (`ingest: the plan changed now that the cache is on disk: environment A -> B, workers a -> b`, then `budget.describe`) and calls
  `par.resize(workers)`; a plan that no longer fits raises `PlanError` (which names the GB needed and available). Nothing happens for `fetch` (no plan).
- `par.py`: new `resize(n)` (sets the limit and the width of a pool that has not started its processes), `limit(None)` allowed.
- Existing test changed: `tests/test_pipeline.py::test_the_workers_of_a_run_are_the_cpus_cut_to_what_the_memory_holds...` asserted the old 1.5 GB/day model
  (a 4 GB container, `env_gb` 2.25 for the CI window). The CI fixture's box is 4 x 4 deg and 1.5 days, so the model now gives 0.0756 GB; the test now uses a
  1 GB container (same intent: memory holds exactly one worker) and `env_gb` approx 0.0756. Not weakened: the same four numbers `(8, 1, 1, 1)` are asserted.
  `test_the_environment_is_1_5_gb_a_day_or_the_stores_on_disk...` is unchanged and still passes (a mission without a box is the demo's box).
- Not measured: the area scaling (9 GB at one box). The 844 GB the test shows for a 360 x 124 deg box is the linear model, a floor, not a measurement.
- Tests (all new, end of file): `tests/test_budget.py::test_the_environment_grows_with_the_area_of_the_padded_box_and_the_demo_stays_9_gb`,
  `::test_every_zarr_store_below_the_cache_and_the_ocean_store_count_toward_the_floor`, `::test_a_mission_without_a_box_is_planned_on_the_demos_box`;
  `tests/test_par.py::test_resize_lowers_the_limit_and_the_width_of_a_pool_that_has_not_started`;
  `tests/test_pipeline.py::test_the_plan_is_made_again_at_the_end_of_the_ingest_with_the_stores_it_put_on_disk` (a real `s_ingest` on the CI fixture with a
  2 GB sparse `orca/big.zarr` added: env_gb 0.08 -> 2.0, workers 3 -> 1, plan.json rewritten, a second `replan()` is a no-op, a resume plans the same, a 5 GB store is
  refused naming "about 5 GB"), `::test_a_plan_made_again_without_a_memory_figure_prints_unknown`.
- Before/after: old code, `budget.env_gb` of the demo = 9.0 and of the 360 x 120 deg box = **9.0** (script on homebase); new code 9.0 and 844.1.
  Old code on the tests: `assert 9.0 == 12.0 +- 0.01` (orca store not counted), `AttributeError` for the new names, `'Context' object has no attribute 'replan'`.

## M-6  shared emulator table (emulator.py, whatif.py)

- `emulator.write_table`: unique temporary in the same directory (`<table>.<pid>.<8 hex>.tmp`, not `mkstemp`, whose 0600 would lock other users out of the
  shared table), `os.replace`, temporary removed if the write fails.
- `emulator.locked(path)` (new): `fcntl.flock(LOCK_EX)` on `<table>.lock`; no `fcntl` = no lock. `whatif.add_rows` and `Emulator.append` (the same
  read-modify-write) hold it around read, filter, concat, write.
- Tests: `tests/test_whatif.py::test_three_processes_adding_rows_to_one_table_lose_none_and_never_corrupt_it` (three real `python -c` processes, 12 `add_rows` calls
  each of a row with a 400 kB column, released together by a file; expects 36 rows, exit 0, no temporary left),
  `tests/test_emulator.py::test_write_table_uses_a_temporary_of_its_own_and_leaves_none_behind_when_it_fails`, `::test_the_table_lock_makes_a_second_holder_wait_and_is_skipped_without_fcntl`.
- Before/after: old code, the three-process test: `assert (31 == 36)` (5 of 36 rows lost; the other runs of the race are the reviewer's ConfigError/FileNotFoundError); new code: 36 of 36.

## M-23  CAFE_NPROC, CAFE_OFFLINE (par.py, stage3/freesurface.py, pipeline.py)

- `par.env_count(name)` (new): unset or empty -> None; else a whole number of at least 1 or `ConfigError("<name>=<v!r> is not a whole number of at least 1; set <name>=N or unset it")`.
  `par.workers` now uses it (message unchanged). `freesurface.nproc` = `par.env_count("CAFE_NPROC") or max(1, min(6, par.workers()))`.
- `pipeline._offline`: `1/true/yes/on` (any case) is offline; empty, `0/false/no/off` online; anything else `ConfigError("CAFE_OFFLINE='x' is not 0 or 1; set CAFE_OFFLINE=1 to download nothing, or 0 or unset it")`.
- Tests: `tests/test_par.py::test_env_count_is_a_whole_number_of_at_least_one_or_a_config_error_naming_the_variable`,
  `tests/test_stage3.py::test_a_bad_cafe_nproc_is_a_config_error_and_0_or_negative_is_not_accepted`,
  `tests/test_pipeline.py::test_cafe_offline_reads_1_true_yes_on_as_offline_and_0_false_no_off_as_online_and_nothing_else`.
- Before/after: old code: `ValueError: invalid literal for int() with base 10: 'abc'`, and `CAFE_OFFLINE=false` read as offline (`assert True is False`); new code: pass.

## Proposed doc text

DECISIONS rows (the lead numbers them from 308):
- `| ? | The stage-1 environment size is `ENV_GB_PER_DEG2_DAY` (9 GB / (14 x 34 deg x 6 days) = 0.0031) x the padded box's area (deg^2, `pipeline.padding` on each side, longitude wrap) x the window's days, set from the one measured point and linear in both; the demo stays 9.0 exactly. The floor from disk is every `*.zarr` below the cache (orca stores too) plus the mission's ocean store. `Context.replan()` makes the plan again at the end of `s_ingest`; a changed plan is written to plan.json, printed, and the pool/`par.workers()` follow it (`par.resize`); a plan that no longer fits is a `PlanError`. | Review round 6, M-2. The model ignored the area of the box and counted only `derived.zarr` (218 MB); the cold-cache plan had no floor. Calibrated at one box and window, so a floor beyond it, not a measurement. Amends row 281 ("1.5 GB per window day", "the larger of ... the cache's Zarr stores") and rows 267/270 in form only. |`
- `| ? | The emulator training table is written through a unique temporary and `os.replace` (`emulator.write_table`), and `whatif.add_rows` and `Emulator.append` hold `fcntl.flock` on `<table>.lock` around their read-modify-write (`emulator.locked`; none without `fcntl`). Concurrent runs share the table safely; `--emulator-table` still gives a private copy. | Review round 6, M-6. Three processes lost rows, met half-written files and renamed each other's one fixed temporary. Rows 174 and 261 (a repeat replaces its rows) unchanged. |`
- `| ? | `par.env_count(name)` is the one parse of a whole-number environment variable (`CAFE_WORKERS`, `CAFE_NPROC`; `ConfigError` naming it). `CAFE_OFFLINE` is 1/true/yes/on (offline) or ''/0/false/no/off (online), any case; anything else is a `ConfigError`. | Review round 6, M-23. `CAFE_NPROC=abc` was a traceback, 0 and -3 were accepted, `CAFE_OFFLINE=false` turned offline mode on. Extends rows 296 and 297; reverses neither. |`

CHANGELOG lines:
- `M-2: the stage-1 environment size follows the padded box's area (0.0031 GB per deg^2 day, one measured point; the demo is still 9.0 GB), the disk floor counts every Zarr store of the cache and the ocean store, and the plan is made again at the end of the ingest (plan.json and the worker count follow it).`
- `M-6: the emulator training table is written through a unique temporary and read-modify-writes hold a file lock, so concurrent runs share it safely.`
- `M-23: CAFE_NPROC is validated like CAFE_WORKERS (par.env_count); CAFE_OFFLINE accepts 1/true/yes/on and 0/false/no/off and rejects anything else.`

RUNBOOK (docs batch):
- line 43 (step 1), replace "needs the environment (about 1.5 GB per window day, so 9 GB for the demo, or the size of the cache on disk if that is larger)" with "needs the environment (0.0031 GB per square degree of the padded box per window day, so 9 GB for the demo; calibrated on that one box and window and a floor beyond it; or the size on disk of the cache's Zarr stores and the ocean store if that is larger; the plan is made again when the ingest ends)"; "a 30-day window needs about 45 GB" becomes "a 30-day window on the demo's box with the default pad needs more than 100 GB (reasoned, not measured)". `CAFE_WORKERS` and `CAFE_NPROC` "must be a whole number of at least 1, else `error: ...` and exit 2".
- line 17: "`CAFE_OFFLINE=1` makes that a rule ...; 0 or unset turns it off" (also true/yes/on and false/no/off; anything else is an error).
- the sentence about the emulator table (each run its own copy): concurrent runs now share the table safely (a lock file `train.parquet.lock` sits beside it); `--emulator-table` still gives a private copy.
- line 120: "`CAFE_NPROC` overrides (a whole number of at least 1)".
- line 211 table row unchanged.

## Needs from other batches

Nothing. (M-17 reads the `s_stage1b` note; I did not touch it. `pipeline.py` hunks of mine: `Context` (`__init__`, `_make_plan`, `replan`), `_gb`, `_offline`, one line at the end of `s_ingest`.)

## Commands run and results (homebase, `PMX=pm_r6p PM_CPUS=2 PM_MEM=8g`, image cafe-pm)

- New tests on the fixed code (`sh /data/r6p_new.sh`): all 13 selected tests PASSED (the 12 new ones and the changed workers test).
- The same tests on the old `cafe/` (the new tests kept): all 13 FAILED. Messages: `AttributeError: module 'cafe.pm.budget' has no attribute 'padded_area_deg2'`;
  `assert 9.0 == 12.0 +- 0.01`; `AttributeError ... 'env_count'` / `'resize'` / `'locked'`; `ValueError: invalid literal for int() with base 10: 'abc'`;
  `assert (31 == 36)` (three processes, 5 rows lost); `'Context' object has no attribute 'replan'`; `assert True is False` (`CAFE_OFFLINE=false` read as offline);
  the changed workers test: `PlanError ... 3 GB is available` / `1 GB is available` (the old model needs 2 GB for the CI window). Old `budget.env_gb`
  of the demo box and of a 360 x 120 deg box: 9.0 and 9.0.
- A bug the first run of the re-plan test found in my own first version: the second plan inherited the worker cap `par.resize` had set (and `fs_plan` priced the
  free-surface cores from `par.workers()`), so a plan made again differed from the first for no reason. `Context._make_plan` now runs under `par.limit(None)`;
  `test_the_plan_is_made_again_at_the_end_of_the_ingest...` asserts the second `replan()` is a no-op, which fails without it.
- `python -m coverage run ... pytest -q -q tests/test_budget.py tests/test_par.py tests/test_emulator.py tests/test_whatif.py tests/test_pipeline.py tests/test_stage3.py`:
  rc=0, no failures. Coverage of those files alone: budget.py 100 %, emulator.py 100 %, whatif.py 100 %, stage3/freesurface.py 100 %, par.py 99 % (line 110, `_mapped`,
  a worker-side line other test files cover), pipeline.py 98 % (lines 69-74, 79-80, 100, 275-276, 300, 307-308, 360-363, 1197-1198, 1280 are not mine and belong to
  other test files; line 125 is the `seed_override` line moved into `_make_plan`, covered by the seeded runs of test_cli/test_acceptance, not run here).
  I did not run the full suite or the whole-`cafe/pm` coverage (the lead does).
- `ruff check cafe/pm tests bench`: All checks passed. `mypy cafe/pm`: Success, no issues in 54 source files.
- No container of mine is left (`docker ps | grep r6p` empty).
