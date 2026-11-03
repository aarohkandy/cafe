# Round 5 hand-back, batch W (what-if, free surface, CI workflow): M-14, M-16, M-22 (all fixed)

Branch `r5-w`, worktree `/Users/aaroh/Downloads/everything/cafe-r5w`. Only files listed in the prompt were touched, plus `cafe/pm/stage3/pipeline_windows.py`
(M-22, named in the finding) and tests/test_budget.py (one new test, named in the finding).

## M-14 `--shift 48h` on the demo
- `cafe/pm/whatif.py:92` `_whole_days(h)`, used by `apply` (:112, refusal kept) and by `answer` (:662-670): a UAS whose shift is whole days is taken out of `changed`
  and returned as `unchanged[vid]` = "launching +48 h later keeps the same launch time of day: nothing changes". If a move also applies to it, only the shift is
  dropped (the move still runs in Stage 1) and `unchanged` still names the shift, so the answer never raises. `answer` returns `unchanged` always (`{}` if none).
- `cafe/pm/__main__.py:269` `_whatif` prints `uas: unchanged (<why>)` after the answers; it accepts an `answer` without the key.
- Tests: tests/test_whatif.py `test_a_whole_day_shift_answers_the_vehicles_it_can_and_names_the_uas_as_unchanged` (glider answered, `unchanged["uas"]`, `apply` still raises,
  `only=["uas"]` gives no vehicles), `test_a_whole_day_shift_with_a_move_...`; tests/test_cli.py `test_whatif_prints_the_uas_that_a_whole_day_shift_leaves_unchanged`.
  Before (fixed code stashed): all three FAIL (`answer` raised `Invalid`; no key `unchanged`; no printed line). After: pass.
- Not done: the run on the real demo (`--shift 48h`) was not repeated; the tests use the CI fixture (UAS `every_days: 1`, the same refused case) with shift 24/48 h.
- DECISIONS row: `| ? | The what-if command line answers a UAS shifted by a whole number of days as "unchanged" (same launch time of day) and goes on to the other vehicles; a move still applies to it; `whatif.apply` keeps raising for direct callers | Review round 5, M-14. The RUNBOOK's first example (`--shift 48h`) aborted on the UAS before answering any vehicle. Amends row 195 for the command line only (the candidate generator still drops these). |`
- CHANGELOG: `whatif: a UAS shifted by whole days is reported "unchanged" and the other vehicles are answered (M-14).`
- RUNBOOK (docs/RUNBOOK.md:120-121, the paragraph after the example): replace the sentence that says the UAS refusal aborts with: "A UAS shifted by a whole number of days launches at the same time of day: the command prints `uas: unchanged (...)` next to the answers for the other vehicles."

## M-16 CI workflow
- `.github/workflows/premission.yml`: order is build, `make ci`, `make broken` (`if: always()`), `make audit` (`if: always()`, comment: red until `make mutation` has stored `docs/mutation.json`, STATUS.md); `timeout-minutes: 180`. Still serial (no xdist).
- Test: tests/test_config_docs.py `test_the_ci_workflow_can_reach_its_evidence_steps_and_finish` parses the workflow: ci < broken < audit, `if: always()` on the last two, timeout >= 150.
  Before: FAIL (audit came first, no `if`, timeout 60). After: pass.
- Not verified: no GitHub run. The audit is still red on the runner until `docs/mutation.json` exists; the point of the fix is that the other two steps now run and report.
- DECISIONS row: `| ? | CI workflow: `make ci` and `make broken` first, `make audit` last, each of the latter two `if: always()`, `timeout-minutes: 180`; the audit stays serial | Review round 5, M-16. The audit takes about 71 min serial and is red until `make mutation` stores docs/mutation.json; before, it ended the job at the 60-minute timeout or at its failure, so the broken-configuration step (exit condition 3's evidence) never ran. Amends the wording of row 97. |`
- CHANGELOG: `CI: make ci and make broken run before make audit and despite its failure; job timeout 180 min (M-16).`

## M-22 free-surface ranks
- `cafe/pm/stage3/freesurface.py:110` `nproc()`: `CAFE_NPROC` if set, else `max(1, min(6, par.workers()))`.
- `cafe/pm/stage3/pipeline_windows.py:698` (+ `import os`): `run` does `os.environ.setdefault("CAFE_NPROC", str(freesurface.nproc()))` first, so `cafe.cfd` (reads it at import) and the child use the planned number.
  `pipeline_windows.run` is the first place stage 3 runs; the plan (`budget.fs_plan`) already calls `nproc()`.
- Tests: tests/test_stage3.py `test_nproc_follows_the_machine_and_stage_3_runs_the_ranks_it_planned` (1 worker -> 1, 3 -> 3, explicit 4 -> 4, `run` exports 2); tests/test_budget.py
  `test_the_free_surface_price_follows_the_machines_cores` (1 worker: cores 1, need more than twice the 6-core need; 16 workers: 6; explicit 4). Before: both FAIL (`assert 6 == 1`). After: pass.
- Existing test changed: tests/test_stage3.py `test_nproc_follows_the_environment` asserted the default is 6 with no `CAFE_WORKERS`; the default now follows the machine, so it sets `CAFE_WORKERS=16` and still asserts 6 (the cap).
- Caveat: `run` sets `CAFE_NPROC` in the process environment for the rest of the process; a test calling `pw.run` without monkeypatching leaves it set (to the same value the default would give).
- DECISIONS row: `| ? | Free-surface MPI ranks: CAFE_NPROC if set, else min(6, par.workers()) (6 is the measured scaling knee: 8 cores reach efficiency 0.44); stage 3 exports it as CAFE_NPROC before cafe.cfd is imported, so the run uses what the plan priced | Review round 5, M-22. The plan and the run both used a fixed 6: 1 CPU was priced 6 times too low, a 32-core server used 6. |`
- CHANGELOG: `Free-surface case: ranks follow the machine (CAFE_NPROC, else min(6, workers)) in the plan and the run (M-22).`
- RUNBOOK/docs: if docs/RUNBOOK.md or PHYSICS say "6 ranks", add "(fewer on a machine with fewer CPUs; `CAFE_NPROC` overrides)".

## Needs from other batches
None.

## Commands
See the end of this file (results).

## Commands run (homebase, `PMX=pm_r5w PM_CPUS=1 PM_MEM=8g`, via sh scripts in pmdata)
- New tests, fixed code: `pytest -k "whole_day or nproc or machines_cores or ci_workflow or the_share_decides"` over test_config_docs, test_cli, test_whatif, test_budget, test_stage3: all passed.
- Same tests with `cafe/` and `.github/` stashed (tests kept): 6 FAILED (the 6 new tests; the `nproc` one `assert 6 == 1`).
- Whole files test_config_docs, test_cli, test_whatif, test_budget, test_stage3 with coverage: rc=0 (all passed, about 55 min on 1 CPU). stage3 coverage: freesurface 100 %, pipeline_windows 100 %, windows, wallmodel, refit, fluidx3d 100 % (lbm and nest are exercised by other test files, not run here).
  The whatif.py and __main__.py coverage rows were cut off by the script's `tail`; not re-measured. The new whatif branches (shift with move, no move) and the CLI line are each hit by a new test.
- `mypy cafe/pm`: no issues in 54 files. `ruff check cafe/pm tests bench`: the first run found one E501 (pipeline_windows.py:698, 165 > 160); shortened the comment; second run: all checks passed.
- No container of mine is left (`docker ps | grep r5w` empty).
