# Round 8 hand-back, batch C (command line and mission config): M-3, M-6, M-18, M-39, M-52 fixed; none left unfixed

Branch `r8-c` (worktree `/Users/aaroh/Downloads/everything/cafe-r8c`). Tested at `PM_CPUS=1 PM_MEM=6g` (container limit 6 GB: under the 9 GB the demo window needs, so the planner's refusal would fire if a test reached it unpatched).

## M-3 whatif checks `--mission` against the run's own copy
- cafe/pm/__main__.py `_whatif` (after `run = ...`): when `run/mission.yaml` exists it is loaded with `load_mission(..., set_verdict=False)`; every key except `seed` and `_path` is compared. A difference raises `ConfigError("--mission X is not the mission run R was made from (differs in: vehicles); ... Use `--mission R/mission.yaml`, or run the edited mission first")`. A seed difference alone prints `note: the run used seed S, this file says T; the what-if draws use T`. No copy: unchanged.
- Tests (tests/test_cli.py, end): `test_r8_m3_whatif_refuses_a_mission_that_is_not_the_one_the_run_was_made_from` (glider_eq `deploy.lat` -2.0: exit 2, stdout empty, `whatif.answer` never called, message names `vehicles`; the run's own mission then prints "->"), `test_r8_m3_a_seed_alone_is_a_note_and_a_run_without_its_mission_copy_is_as_before`.
- Before (unfixed code, new tests copied in): both FAILED. After: pass.
- DECISIONS: `| ? | whatif refuses a --mission that differs from the run's copy (run/mission.yaml) in any key but seed; a seed difference is a printed note and the draws use the file's seed | Review round 8, M-3. A what-if compares a change with the run's verdicts; a different mission pairs one mission's baseline with another's answer. |`
- CHANGELOG: `whatif refuses a --mission that differs from the one the run was made from (seed alone is a note) (round 8, M-3).`
- RUNBOOK, one sentence under "What if" (line 145): `The --mission must be the one the run was made from (it is compared with runs/quick/mission.yaml; only the seed may differ, and the file's seed is then used for the new draws); to try an edited mission, run it first.`

## M-6 report --run needs no stage-1 memory
- cafe/pm/__main__.py `_report`: `pipeline.Context(run / "mission.yaml", None, plan["gpus"], run, hash_budget=plan["budget"])` (no plan, so `budget.plan` and its memory refusal never run; `_report` uses only `ctx.cache` and `ctx.env`).
- tests/test_cli.py: new autouse fixture `roomy_machine` (placed after `calls`) patches `par.memory_gb` to 64 for every CLI test through its own `pytest.MonkeyPatch.context()` (so `test_whatif_with_the_real_engine...`, which calls `monkeypatch.undo()`, keeps it); the refusal tests (`test_plan_applies_the_memory_model_of_run`, `test_the_real_planner_refusal...`) patch `par.memory_gb` to their own values afterwards, unchanged. New `test_r8_m6_report_of_a_finished_run_needs_no_memory_for_stage_1` (`par.memory_gb` = 2.0: report returns 0; `plan` still refuses with "2 GB is available").
- Before: new test FAILED (exit 2, planner refusal). After: passes. Whole `tests/test_cli.py` + `tests/test_config.py` + `tests/test_config_docs.py` at `PM_MEM=6g`: 265 passed, rc 0. No assertion of an existing test changed.
- DECISIONS: `| ? | report --run builds its Context without a plan (hash_budget names the budget); the CLI tests that reach the planner run with par.memory_gb patched to 64, the refusal tests on explicit values | Review round 8, M-6. Re-rendering a finished run needs none of stage 1's memory; the plan is run/plan.json. |`
- CHANGELOG: `report --run no longer applies the stage-1 memory model; the CLI tests no longer depend on the machine's memory (round 8, M-6).`
- RUNBOOK (line 143, after the report sentence): `It needs no more memory than the report itself (no stage-1 memory model runs).`

## M-18 ship bounds
- cafe/schemas/mission.json `ship`: `antenna_height_m` 0.5 to 100, `transducer_depth_m` 0 to 100, each with a description.
- Tests (tests/test_config.py, end): `test_r8_m18_the_ship_antenna_and_transducer_are_bounded_on_both_sides_and_named` (1000, 100.5, 0, 0.1 / 20000, 100.5, -1, each naming its field), `test_r8_m18_the_edges_of_the_ship_bounds_and_the_shipped_missions_load` (0.5, 0, 100, 100 load; loosening or tightening a bound fails).
- Before: 6 of the 7 refusal cases FAILED (the -1 case was already refused by `minimum: 0`). After: pass.
- DECISIONS: `| ? | ship.antenna_height_m 0.5 to 100 m, ship.transducer_depth_m 0 to 100 m (schema bounds; choices, not measurements; the demo's 15 and 5 are inside) | Review round 8, M-18. Extends 316. A typo (15 written as 150) turned a NO-GO link into GO; the lower antenna bound is a deck rail, the transducer's upper bound an over-the-side cable. |` No QUESTIONS_FOR_LAB.
- CHANGELOG: `mission schema bounds ship.antenna_height_m (0.5..100 m) and ship.transducer_depth_m (0..100 m) (round 8, M-18).`
- RUNBOOK line 115, add to the list of bounded numbers: `` `ship.antenna_height_m` 0.5 to 100, `ship.transducer_depth_m` 0 to 100,``

## M-39 `_say` explains the three YAML slips
- cafe/pm/config.py `_say` (+ helper `_is_float`): `local_solar_time` with an int -> "YAML reads an unquoted HH:MM as a number (840 = 14:00 as minutes); put it in quotes, e.g. "14:00"" (a value of 1440 or more, i.e. `14:00:00`, gets the same advice without the conversion); a string field with a bool -> "YAML reads an unquoted no/yes/on/off as false; put it in quotes" (the original word is lost by the loader, so the message names the family); a number field with a string that parses as a finite float -> "the number is written in a form YAML reads as text ('5e0'); write 5". Any other string for a number keeps the schema text.
- Tests (tests/test_config.py, end): `test_r8_m39_an_unquoted_time_a_no_and_an_exponent_without_a_dot_say_why` (5 cases incl. `14:00:00`, `radius_km: five` keeps the schema text), `test_r8_m39_the_quoted_forms_load`.
- Before: 4 of 5 FAILED (the schema text). After: pass. `cafe/pm/config.py` coverage 100 % in this run of the three test files.
- DECISIONS: `| ? | _say names three more YAML slips: an unquoted HH:MM (read as minutes), an unquoted no/yes/on/off (read as a boolean) and an exponent without a dot such as 5e0 (read as text) | Review round 8, M-39. Extends 155 and _say. The refusal printed a number or boolean the user never typed. |`
- CHANGELOG: `mission errors explain an unquoted HH:MM, no/yes/on/off and 5e0 (round 8, M-39).`
- RUNBOOK line 115, the quoting sentence: after "A time must be in quotes (`start: "2023-03-01T12:00:00Z"`)" add `, and so must a time of day (`local_solar_time: "14:00"`) and an id such as `no` (YAML reads them as a number and false); write `5.0` or `5`, not `5e0``.

## M-52 `cafe.pm audit --ledgers-only`
- cafe/pm/__main__.py: `audit` subparser gains `--ledgers-only`, forwarded after `--code-only`; the module docstring usage line names it.
- Test: `test_r8_m52_audit_forwards_ledgers_only_like_code_only`. Before FAILED (unrecognized argument), after passes. The existing `test_audit_forwards_its_runs_and_flag_...` unchanged and green.
- DECISIONS: `| ? | python -m cafe.pm audit accepts --ledgers-only (forwarded like --code-only); --mutation-record stays on python -m cafe.pm.audit (it is make mutation's) | Review round 8, M-52. The RUNBOOK listed options the subcommand did not take. |`
- CHANGELOG: `cafe.pm audit takes --ledgers-only (round 8, M-52).`
- RUNBOOK line 178: replace "or an option it does not know (`--code-only`, `--ledgers-only`, `--mutation-record`)" with "or an option it does not know (`--code-only` and `--ledgers-only` for both `python -m cafe.pm audit` and `python -m cafe.pm.audit`; `--mutation-record` only for `python -m cafe.pm.audit`)".

## Needs from other batches
Nothing. Docs are for the lead's docs pass (text above). Note for the merge: tests/test_cli.py gained an autouse fixture near the top (`roomy_machine`) in addition to tests at the end; K's M-7 / M-22 tests that reach the planner in that file get the 64 GB machine for free.

## Commands run (homebase, from the worktree, `PMX=pm_r8c PM_CPUS=1 PM_MEM=6g`)
- Fail-first: detached worktree `/Users/aaroh/Downloads/everything/cafe-r8c-old` (eaf0e27) with the new test files copied in, `PMX=pm_r8c_old`: `pytest tests/test_config.py -k r8` -> 10 failed; `tests/test_cli.py -k r8` -> 4 failed (all listed above).
- Fixed: `pytest tests/test_cli.py tests/test_config.py tests/test_config_docs.py` (+ `--cov=cafe.pm.config --cov=cafe.pm.__main__`) -> 265 passed, rc 0; config.py 100 %, `__main__.py` 99 % (line 112, the `acceptance` branch, is covered by tests/test_acceptance.py, which I did not run).
- `python -m ruff check cafe/pm tests bench` -> All checks passed; `python -m mypy cafe/pm` -> Success, 54 files.
- No container of mine left running (`docker ps | grep r8c` empty).
