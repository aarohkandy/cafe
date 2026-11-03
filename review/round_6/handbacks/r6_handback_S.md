# Round 6, batch S hand-back (M-3, M-12, M-13, M-17, M-18)

Worktree `/Users/aaroh/Downloads/everything/cafe-r6s`, branch `r6-s`. All five findings are fixed.

## M-3 (SITL members)
- `cafe/pm/budget.py:36`: `SITL` is 0 for every budget.
- `cafe/pm/report.py` `_machine_html`: after "Plan: ..." the sentence "ArduCopter SITL is not part of the pipeline; it runs only as the slow receipts (UAS SITL vs our controller, UAS sortie), so the ensemble is pure physics."
- Tests: `tests/test_budget.py::test_the_plan_charges_no_sitl_member_because_no_stage_flies_one` (every budget has `sitl_members == 0`; neither `stage1.py` nor `pipeline.py` names `fly_sitl`); `tests/test_report.py::test_the_plan_block_says_sitl_is_not_in_the_pipeline_instead_of_a_member_count` (4h plan).
- Changed existing assertion: `tests/test_budget.py:31` asserted `sitl_members == 8` for overnight; that was the wrong behaviour the finding removes, now `== 0`.
- Before (old code): `assert 4 == 0` and the report test fails. After: pass.
- Doc text for the lead: STATUS.md section 3 ("Not done"): "ArduCopter SITL is not part of the pipeline: `uas.fly_sitl` runs only in the slow receipts, so `plan.json` says `sitl_members 0` for every budget." CHANGELOG "not called by any pipeline stage" list: add `fly_sitl`.
- DECISIONS row: `| ? | The plan states `sitl_members` 0 for every budget (4h and overnight were 4 and 8 before); the report's plan block says SITL runs only as the slow receipts. | Review round 6, M-3. No stage flies a SITL member, so the printed count was false. Amends row 85. |`
- CHANGELOG: "Plan: `sitl_members` is 0 for every budget; the report says ArduCopter SITL is only a slow receipt (M-3)."

## M-12 (receipts --only)
- `cafe/pm/receipts.py` `run`: `only` that matches no job name returns `([], 2)` after logging "no receipt group matches 'x'; the groups are: ..." and writes nothing. `--only` now writes `runs/receipts_partial.json` (plus its meta) unless `out`/`--json` is given. Module docstring says so.
- `cafe/pm/report.py` `Trace._stale`: a meta file with a non-empty `only` is stale ("was made with --only ...: it holds a part of the receipts"); an older meta without the key, or `only: null`, is unchanged.
- `cafe/pm/__main__.py` `--only` help text.
- Tests: `tests/test_receipts.py::test_only_that_matches_no_group_exits_2_and_writes_nothing_and_a_part_goes_to_its_own_file`; `tests/test_report.py::test_a_receipts_table_made_with_only_is_stale_even_when_its_digest_is_current`.
- Before: `([], 0) == ([], 2)` fails; report status `ok` instead of stale. After: pass.
- DECISIONS row: `| ? | `receipts --only` writes `runs/receipts_partial.json`, not `receipts.json`; a part matching no group exits 2 and writes nothing; the report treats a table whose meta has `only` as stale. | Review round 6, M-12. A one-group table replaced the full one and the report called it current (it compared only the code digest). |`
- CHANGELOG: "`receipts --only` no longer replaces the full table; an unmatched name exits 2 (M-12)."
- RUNBOOK (lead): where `receipts --only` is described, add "the table goes to runs/receipts_partial.json".

## M-13 (what-if candidates)
- `whatif.py` needed no change: `measure` and `emulate` already put `lo`/`hi` in every `tried` entry, and the report already carried them as `p_fail.uncertainty` (q6 `report.json` shows `{'kind': 'Wilson interval (Stage 1)', 'lo': 0.1716, 'hi': 0.4250}`). The finding's "uncertainty is None" is not what the q6 file holds; what was missing is the interval in the printed table.
- `cafe/pm/report.py` `_fix`: each tried entry gets `same_as_baseline` (the candidate interval contains the baseline's `p_fail`; None when there is no number). `_tried_html` prints the P(fail) with "(lo to hi)" and "not distinguishable from the baseline (its interval contains the baseline's P(fail))" in the note column; `_fix_html`'s best line adds the same words.
- Test: `tests/test_report.py::test_a_what_if_candidate_prints_its_interval_and_is_flagged_when_it_contains_the_baseline` (9 of 32 against 15 of 64 flagged; 0 of 32 not flagged).
- Before: `KeyError: 'same_as_baseline'`. After: pass.
- DECISIONS row: `| ? | The what-if table prints each candidate's interval and flags a candidate whose interval contains the baseline's P(fail) as not distinguishable from it; the candidates stay at the plan's sequential count. | Review round 6, M-13. 9 of 32 (0.17 to 0.43) beside 15 of 64 (0.157 to 0.334) was read as an evaluated change. |`
- CHANGELOG: "What-if table: candidate intervals and a not-distinguishable-from-baseline flag (M-13)."

## M-17 (stage 1b note, shares)
- `cafe/pm/pipeline.py` `_sensitivity_cases`: times the USV case and writes `sensitivity_wall_s` into the stage-1b ledger (outside any hashed output). `s_stage1b`: the copy note reads "no vehicle was refit: stage 1b is stage 1 (copied, not rerun); the sensitivity case reran the USV in N s, not charged to any share" (unchanged when no USV ran).
- `cafe/pm/report.py`: `_timing` adds `stage1b_sensitivity` (measured seconds, from the ledger) and `_machine_html` prints "Stage 1b sensitivity case ...: planned none, it is charged to no share; measured N s."; the emulator paragraph now says "(the share of stage 1b included, since no vehicle was refit)".
- Tests: `tests/test_pipeline.py::test_the_stage_1b_copy_note_and_ledger_say_how_long_the_sensitivity_case_ran`; `tests/test_report.py::test_the_machine_block_shows_the_stage_1b_sensitivity_case_seconds_it_charged_to_no_share`.
- Changed existing assertions, because they asserted the old wording: `tests/test_pipeline.py::test_stage1b_is_a_copy_of_stage1_when_no_vehicle_was_refit` (note 2 now `startswith`), `::test_no_passing_window_means_no_refit_and_stage1b_is_a_copy` (`startswith`/`endswith`), `tests/test_report.py` emulator test (`"including stage 1b"` became the new phrase).
- Before: `KeyError: 'sensitivity_wall_s'`, `KeyError: 'stage1b_sensitivity'`. After: pass.
- DECISIONS row: `| ? | Stage 1b's ledger records `sensitivity_wall_s`; its copy note names the sensitivity seconds and says no share is charged; the report's machine block shows them; no share is enforced differently. | Review round 6, M-17. Amends row 288's note text only. Stage 1b took 30 s and the emulator 291 s against a 240 s share. |`
- CHANGELOG: "Stage 1b ledger and machine block name the 30 s USV sensitivity case (M-17)."

## M-18 (UAS turbulence height)
- `cafe/pm/credibility.py`: limitation L20 (factors `validation`, where `cafe/pm/stage1.py`, `cafe/pm/env/subgrid.py`).
- `docs/CREDIBILITY.md`: L20 row in section 5 (the text matches the code character for character), the counts "L14 to L20", the Validation row (L20 added, "retire the twelve"). `docs/PHYSICS.md` section 5.1: one bullet on the single height (58 m; Lambda_1 40.6 m; 12.6 m at the 10 m leg; 42 m at 100 m).
- Test: `tests/test_credibility.py::test_the_single_height_uas_turbulence_is_a_listed_limitation_that_moves_no_level` (also reads the `z = deck + mean(levels)` line of stage1.py and the PHYSICS.md sentence). Existing `test_limitations_are_listed_verbatim_and_point_at_real_files` asserted the list ended at L19; it now ends at L20.
- Before: `StopIteration` (no L20). After: pass.
- DECISIONS row: `| ? | UAS turbulence stays one Mann box per sortie at deck height plus the mean altitude; recorded as limitation L20 and in PHYSICS 5.1. | Review round 6, M-18. The 10 m leg sees the 58 m length scale; sigma_u does not depend on height here; a box per leg is a feature. |`
- CHANGELOG: "Limitation L20: UAS turbulence at one height (M-18)."

## Needs from other batches
- The emulator's ledger note in `pipeline.s_emulator` (line ~1136, not in S's functions): change "incl. stage 1b, which was a copy" to "stage 1b's share included, since no vehicle was refit" (finding M-17). The report text already says it.
- Observation, not changed: the CREDIBILITY.md "What the current build can reach" table omits L19 (it bears on uncertainty and validation); the Validation row now lists L20 but still not L19.
- The cli and whatif tests need more than 8 GB: at `PM_MEM=8g` 13 `tests/test_cli.py` tests fail with the stage-1 memory guard ("needs about 9 GB ... 9 GB is available"). They pass at `PM_MEM=14g`. That is M-2's area (batch P), not this change.

## Commands and results (homebase, `PMX=pm_r6s PM_CPUS=2`, image cafe-pm)
- `pytest tests/test_budget.py tests/test_receipts.py tests/test_credibility.py tests/test_config_docs.py tests/test_cli.py` at 8g: all pass except the 13 memory-guard cases above; `tests/test_cli.py tests/test_whatif.py` at 14g: rc=0.
- The 8 new tests plus the 2 changed ones: green on the fixed tree (rc=0), red on the base `cafe/` and `docs/` (rc=1, 10 failures, messages above).
- `ruff check cafe/pm tests bench`: clean; `mypy cafe/pm`: clean.
- Final run of tests/test_budget.py test_receipts.py test_credibility.py test_config_docs.py test_cli.py test_whatif.py test_report.py test_pipeline.py test_audit.py at 14g: rc=0, no failures.
- No `git stash` was used. To get the red results I ran `git checkout premission-step4 -- cafe docs` in my own worktree (tests kept), ran the new tests, then `git checkout HEAD -- cafe docs`; `git diff --stat` shows only the files named above.
