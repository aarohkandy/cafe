# Hand-back: work order step 4, the emulator's share on a reach budget (`wo-emu2`, cut from 40f04c5)

Builder: Claude Fable 5.2. Runs are on cafe-orca (proot, `PMX=pm_wo_emu2`, logs `~/cafe-worker/logs/<job>.log`, each ends `rc=N`). Nothing was run on the laptop; nothing was pushed.

## What changed

| File | Change |
|---|---|
| `cafe/pm/budget.py` | `STAGE1_PRICED = 5.0`, `emulator_own_share_s`; `emulator_share_s` on `EMULATOR_REACH` budgets (`4h`, `overnight`) is the own share or, if larger, `budget_s` x (emulator + stage 1 + stage 1b shares) less `STAGE1_PRICED` x `stage1_s` (twice with a refit, once when stage 1b was a copy). `ci`, `quick` and other budgets return the own share as before. `emulator_plan`'s note says "will not train" only when `trains` is false. |
| `cafe/pm/pipeline.py` | the ledger note on the share and `design.json` key `stage1_unpriced`. |
| `cafe/pm/report.py` | the report's sentence on the share follows `stage1_unpriced`. |
| `docs/RUNBOOK.md`, `DECISIONS.md` (1106), `CHANGELOG.md` | one sentence, one row, one line. |
| `tests/test_wo_emu2.py` | new tests (below). |

## Tests (before = tree at 40f04c5 with the new test file)

`tests/test_wo_emu2.py`: reach share at overnight gives at least 100 points; the share formula and its floor; `ci` and `quick` keep the old share; the four planned stage seconds add up to the sum of the four shares (0.95 of the budget); the plan's note; the ledger note and `design.json` of a refit run on a reach budget; the report sentence. Before: these fail on 40f04c5 (no `emulator_own_share_s`, no `stage1_unpriced`). After: job `wo_emu2_k3` (see Skeptic pass).

## Printed text changed

The emulator ledger note "emulator share N s (...)" and the report sentence on the share, on a reach budget only: "(its own share and the seconds of stages 1 and 1b the plan does not price)". The plan's emulator note no longer says "will not train" when it trains.

## Pins moved

None. (The first commit moved the stage-3 pin of `tests/test_reproducible.py` for the RANS row; the skeptic pass took it out: see below.)

## Not verified

A 4h or overnight run with the new share (the plan says about 3 h longer than on1, not measured). The real-twin test `test_two_runs_with_the_same_seed_make_the_same_report_json_with_the_real_stage_3` was not made to pass here (below).

## Skeptic pass

| Issue | Result |
|---|---|
| `test_the_four_planned_stage_seconds_fit_the_budget` asserted the sum is the budget; SHARE sums to 0.95 | fixed: the test asserts `sum(shares) x B` (both refit and copy) and `< B`; the `emulator_share_s` docstring and DECISIONS 1106 say 0.95 of the budget, 5 % slack |
| ruff E501 on report.py, pipeline.py, test_wo_emu2.py | fixed: wrapped (`own` local in report.py, `stage1_unpriced` on its own line, docstring and test lines). Also an F811 in the new test (`run` fixture), marked `# noqa: F811` as the neighbouring tests do |
| `tests/test_reproducible.py` probe print and weak pin | fixed by removal: the file is back at 40f04c5. The 7-row pin is the RANS change's (1105), not this one; routed to the lead |
| budget.py:617 share cannot exceed the budget | not a defect (skeptic found it sound); no change |
| found while re-running: `test_a_refit_run_on_a_reach_budget_says_what_its_share_is_made_of` expected 60 s and got 90 s | fixed (test): `synthetic_ctx` makes a `quick` plan, whose shares moved stage 3's share to stage 1 (0.75 + 0.15); the test sets `shares=dict(budget.SHARE)` |

Routed to the lead, `tests/test_reproducible.py::test_two_runs_with_the_same_seed_make_the_same_report_json_with_the_real_stage_3` (not caused by this change: the `ci` share is unchanged): at 40f04c5 it pins 6 stage-3 rows and the RANS change (1105) adds a `body_rans` row (7). A run of it on orca (job `wo_emu2_1`, tree 40f04c5 plus the emu2 change, orca load about 10) failed earlier, at the twins' equality: 88 differences, the first `emulator.run_note: ... 0 poin != ... 3 poin`, so two runs of the same seed differ when the box is loaded (the body_rans case and the stage-3 clocks are the likely cause; not checked). The RANS change should move the pin and decide what `body_rans` must be on the `ci` plan.
