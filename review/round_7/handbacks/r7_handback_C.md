# Round 7 hand-back, batch C (mission config and CLI): M-1, M-32, M-33, M-34, M-47 (the five M-9 bounds)

Branch `r7-c`, worktree `/Users/aaroh/Downloads/everything/cafe-r7c`. All five fixed. M-47's emulator/whatif lock tests are not mine (batch of whatif/emulator).

## M-1 verdict cut-offs survive budget planning
- `cafe/pm/config.py` `load_mission(path, set_verdict=True)`: `intervals.set_thresholds` only when `set_verdict`. `cafe/pm/budget.py` `bench_sortie_rate`: `load_mission(..., set_verdict=False)`. `cafe/pm/stats/intervals.py` `set_thresholds` docstring: "set by the one mission a command runs; a mission loaded only to be read does not set it".
- Tests: `tests/test_config.py::test_r7_m1_a_mission_loaded_only_to_be_read_leaves_the_verdict_cut_offs_alone`, `tests/test_budget.py::test_r7_m1_planning_the_budget_does_not_replace_the_missions_verdict_cut_offs`, `tests/test_pipeline.py::test_r7_m1_a_context_keeps_the_missions_own_verdict_cut_offs_after_it_plans` (demo with `verdict: {go: 0.8, nogo: 0.5}`, `Context(..., "quick")`).
- Before (unfixed tree `cafe-r7c-old`): config test `TypeError: load_mission() got an unexpected keyword argument 'set_verdict'`; budget and pipeline tests `assert (0.1, 0.4) == (0.2 ± 2.0e-07, 0.5)` (the demo's cut-offs, as the finding reproduced). After: pass.
- DECISIONS: `| ? | The verdict cut-offs (stats.intervals module state) are set only by the one mission a command runs: load_mission(path, set_verdict=False) reads a mission without setting them, and budget.bench_sortie_rate (the benchmark's mission, read for its sortie-minutes) uses it. The demo and CI missions (0.9 / 0.6) are unchanged. | Review round 7, M-1. Extends row 153. Planning the budget loaded the benchmark's demo mission and replaced a UAS mission's own go/nogo with 0.9 / 0.6 for the stopper, the verdict and the report sentence. Not "save and restore": that keeps a hidden global write. |`
- CHANGELOG: `Fixed (round 7, M-1): a UAS mission's own verdict {go, nogo} is no longer replaced by the demo's 0.9 / 0.6 when the budget is planned (load_mission(..., set_verdict=False) for a mission read only for its sortie-minutes).`

## M-32 box across 0 deg E
- `cafe/pm/pipeline.py` `ocean_box` (about :205-218): runs `hycom.box360` on the padded box and raises `ConfigError("box (...): the box (with its pad of N deg) crosses 0 deg E; the GLBy ocean fetch cannot cross it: move the box east or west of 0 deg, or split the mission")`; other `box360` errors pass through. `cafe/pm/config.py` `load_mission` (after the lat_min < lat_max check) calls it (lazy import of pipeline, which imports config) and prefixes the path. So `validate`, `plan`, `fetch`, `run`, `whatif`, `ingest-ocean` all refuse with exit 2 and one `error:` line, and `ocean_box` itself refuses for a mission loaded without `load_mission`. The limit holds for every ocean source (GEBCO and lab HYCOM use `box360` too).
- Tests: `tests/test_config.py::test_r7_m32_a_box_across_0_deg_e_is_refused_at_validation_naming_the_box` (the reviewer's prime.yaml refused; a box 2..10 with pad 2, whose west edge is exactly 0, and the dateline demo still load); `tests/test_pipeline.py::test_r7_m32_ocean_box_across_0_deg_e_is_a_config_error_for_a_mission_loaded_without_validation`.
- Before: both `Failed: DID NOT RAISE ConfigError`. After: pass.
- DECISIONS: `| ? | A mission whose box, with its pad, crosses 0 deg E is refused at load (ConfigError naming the box and the fix) and by pipeline.ocean_box; the GLBy fetch (and GEBCO, TAO, lab HYCOM) take one box in 0..360 and the CLI cannot split a mission. A box east or west of 0 deg, or across 180 deg, is unchanged. | Review round 7, M-32. validate said "valid" and fetch died in a bare ValueError. Two fetches for a prime-meridian box is a feature, not this fix. |`
- CHANGELOG: `Fixed (round 7, M-32): a mission box that crosses 0 deg E is refused by validate/plan/fetch/run with an error line (it ended in a ValueError traceback at fetch).`
- RUNBOOK section 4 (text for the lead's documentation pass): "The mission box, with its pad (`pad_deg`, else the window length times 0.5 m/s rounded up to 0.5 deg), must not cross 0 deg E: the ocean fetch takes one box in 0..360. Move the box east or west of 0 deg, or run it as two missions. A box across 180 deg is fine."

## M-33 mission name length
- `cafe/schemas/mission.json` `name`: `"maxLength": 64`.
- Test: `tests/test_config.py::test_r7_m33_a_mission_name_is_at_most_64_characters_and_its_paths_can_be_made` (65 refused naming `name`; 64 loads and `mkdir` of the name and of `gofs_<name>.zarr` works under tmp_path). Before: `DID NOT RAISE`. After: pass.
- DECISIONS: `| ? | A mission name is at most 64 characters (schema maxLength). | Review round 7, M-33. The name is a directory and the stem of gofs_<name>.zarr; 300 characters passed validation and ended in OSError File name too long at ingest (limit 255 bytes per component). |`
- CHANGELOG: `Fixed (round 7, M-33): a mission name over 64 characters is refused at validation (it ended in OSError: File name too long at ingest).`
- RUNBOOK mission section: "`name`: lowercase letters, digits, `_` and `-`, at most 64 characters."

## M-34 corrupt mission/platform file and corrupt plan.json
- `cafe/pm/config.py` `_yaml` (:61-65): `UnicodeDecodeError` -> `ConfigError("<path>: not a UTF-8 text file (<reason> at byte <n>); the mission and platform files are UTF-8 YAML")`; `OSError` -> `ConfigError("<path>: cannot be read (<strerror>)")`. `cafe/pm/__main__.py` new `_json_object(p)` (:163): `ValueError`/`OSError` or a non-dict -> `ConfigError("<p>: not a JSON object (...); `run` writes it, so run it again (--fresh)")`; used for `plan.json` (`_report`) and for the other three run files the CLI reads (`stage1b/summary.json`, `refit/refit.json`, `ingest/priors_fitted.json`, in `_whatif`).
- Tests: `tests/test_config.py::test_r7_m34_a_mission_file_that_is_not_utf8_text_is_a_config_error` (mission, platform, directory); `tests/test_cli.py::test_r7_m34_a_mission_that_is_not_utf8_text_ends_in_an_error_line`, `::test_r7_m34_a_plan_json_that_is_not_a_json_object_ends_in_an_error_line[array|truncated|not utf-8]` (rc 2, `error:` line, no traceback).
- Before: rc 1 with `UnicodeDecodeError`, `TypeError: list indices must be integers or slices, not str`, `JSONDecodeError`, `UnicodeDecodeError` (as in the finding). After: pass.
- DECISIONS: `| ? | A mission or platform file that is not UTF-8, and a run file the CLI reads back (plan.json, summary.json, refit.json, priors_fitted.json) that is not a JSON object, is a ConfigError (an error: line, exit 2). | Review round 7, M-34. Same class as row 294 (the cache JSON) and round 6 M-8. BRIEF 5.6 lists "corrupt file" as a robustness input and the RUNBOOK promises error: with exit 2. |`
- CHANGELOG: `Fixed (round 7, M-34): a non-UTF-8 mission/platform file and a corrupt or non-object plan.json (and the other run files whatif reads) end in an error: line with exit 2, not a traceback.`

## M-47 (the five M-9 bounds)
- Tests only: `tests/test_config.py::test_r7_m47_the_other_bounds_of_r6_m9_are_each_refused_naming_their_field` (max wind 61, `lost_after_h` 721 and -5, `track_tolerance_km` 1001, gust-front window 1441, each naming its field).
- Each shown failing on the mutant it names (mutated `cafe/schemas/mission.json` in the throwaway tree, restored each time; the unmutated tree passes, rc 0):
  - M9a `max_mean_wind_ms` maximum 60 -> 6000: rc 1, fails `[max wind 61]`
  - M9d `lost_after_h` maximum 720 -> 7200: rc 1, fails `[lost after 721 h]`
  - M9f `track_tolerance_km` maximum removed: rc 1, fails `[track tolerance 1001 km]`
  - X9l `no_gust_front_within_min` maximum 1440 -> 144000: rc 1, fails `[gust-front window 1441 min]`
  - X9j `lost_after_h` exclusiveMinimum 0 -> minimum -5: rc 1, fails `[lost after -5 h]`
- The `Emulator.append` / `add_rows` lock tests (rest of M-47) are tests/test_emulator.py and tests/test_whatif.py: not in this batch.
- DECISIONS: none (tests only). CHANGELOG: `Tests (round 7, M-47): the five bounds of row 316 that no test refused (max wind 60, lost_after_h 720 and > 0, track_tolerance_km 1000, gust-front window 1440) are each refused by a test that fails when the bound is loosened.`

## Needs from other batches
- None. Note for the lead: `config.load_mission` now imports `pipeline` lazily (for `ocean_box`), so config -> pipeline at call time; no import cycle at load. If a later batch moves `padding`/`ocean_box` out of `pipeline.py`, update that one import.
- Docs for the documentation pass: the RUNBOOK sentences under M-32 and M-33 above; DECISIONS row 153 gets "set by the one mission a command runs; a mission loaded only to be read does not set it" (the lead's row for M-1 extends it).

## Commands and results
(see the end of this file)

All on homebase, from `/Users/aaroh/Downloads/everything/cafe-r7c`, `PMX=pm_r7c PM_CPUS=1`, `bin/pmx.sh` (rc is the container's exit code; the pytest summary line is suppressed by the repo config).
- Fail-first, on a throwaway `git worktree add --detach ../cafe-r7c-old premission-step4` with only the four test files copied in (`PMX=pm_r7c_old`): `test_config.py -k r7` rc 1 (4 failed: M-1, M-32, M-33, M-34), `test_budget.py -k r7` rc 1, `test_pipeline.py -k r7` rc 1 (M-1, M-32), `test_cli.py -k r7` rc 1 (4 failed: M-34 x4). The five M-47 tests pass on the unmutated old tree (rc 0, they are tests of a bound that already holds) and each fails on its mutant (see M-47).
- Fixed tree: `tests/test_config.py tests/test_budget.py` (PM_MEM=8g) rc 0; `tests/test_pipeline.py` (12g) rc 0; `tests/test_cli.py` (12g) rc 0 (whole files). After that, `ocean_box` was simplified (the `"crosses" not in str(e)` re-raise branch was removed: it could not be reached, since `load_mission` has already checked south < north, and an unreached branch costs coverage); re-run after it: whole `tests/test_config.py` rc 0, `tests/test_pipeline.py -k r7` rc 0, `tests/test_cli.py -k r7` rc 0. The full `test_pipeline.py` / `test_cli.py` were not re-run after that one-line removal.
- `ruff check cafe/pm tests bench`: all checks passed. `python -m mypy cafe/pm`: no issues in 54 source files.
- Coverage was not measured (the lead's full run does it). The new branches are each reached by a test: `_yaml` UnicodeDecodeError and OSError, `_json_object` ValueError and non-dict, `ocean_box` refusal, `set_verdict=False`.
- Commit trailer: the lead's common file names `Claude Opus 5.5`; this session's attribution reminder names `Claude Sonnet 5.5`, which is the model that wrote the commit, so the commit carries that one.
