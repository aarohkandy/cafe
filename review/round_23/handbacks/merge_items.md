# Merge-items hand-back (builder MI, branch r23-mi, base f71ad43)

## What changed
1. `cafe/pm/budget.py` `bench_sortie_rate`: the check on `sortie_min` / `mission_days` is now `_need(..., positive=False)` (finite and at least 0). 0 takes the pre-round-23 path (`sm and days` false -> None -> the "UAS stage-1 cost is not scaled" note); NaN, inf, -inf, negative, bool, str, list, 10**400 still give PlanError. `_need`'s docstring says so. One line of code, no new statement.
2. L17 (`credibility.LIMITATIONS`, docs/CREDIBILITY.md L17 cell): text now starts "in the shipped quad_uas.yaml the UAS controller clamps ..." (S-15 SCOPE; the one added clause is the scope). New test reads `platforms/quad_uas.yaml` (`limits.max_tilt_deg`, `limits.tilt_exceedance_deg`), builds the text from them, asserts equality with the code text and with the CREDIBILITY.md cell. The L23 cell was not touched.
3. New `tests/test_round23_m.py` (items 1 and 2).

## Pins moved (each because the product's answer is now the intended one)
- tests/test_credibility.py:464 (`LIMITS2` L17 text) and tests/test_round23_b.py:155 (`test_s15_*` text equality, rewrapped under 160): the L17 text carries the scope clause.
- tests/test_round23_d.py `test_m9_the_benchmarks_sortie_minutes_and_days_...`: parametrised over NOT_COSTS instead of NOT_RATES (0 and -0.0 are no longer errors for these two figures; renamed `..._at_least_0_or_absent`). The other checks of that test (NaN etc. refused, 1e-300 accepted, absent -> None) are unchanged. No assertion weakened elsewhere.
Nothing else in A to D broke in combination.

## Evidence (orca, proot, 2 CPUs; logs ~/cafe-worker/logs)
- Before (detached f71ad43 plus the new file, pm_r23mib): r23mi_b1 rc=1, 9 FAILED: 7 zero-figure cases (`sortie_min` 0, 0.0, -0.0 with days 6; `mission_days` 0, 0.0, -0.0; both 0), the plan case, the L17 case. The non-finite/negative cases pass before and after by design.
- After (pm_r23mi): r23mi_1 rc=0, 600 passed (test_round23_m, _b, _d, test_credibility).
- Cross-batch: r23mi_x1 rc=0 (tests/test_stage1.py, tests/test_report.py, `-n 2`; 432 progress characters, all dots); r23mi_y1 rc=0, 2438 passed (test_budget, comms, config, config_docs, round17_b, 18_a, 18_b, 18_x, 19_b, 20_b, 21_a, 21_b, 21_e, 22_a, 22_b, 22_c, 22_d, 22_m, 23_a, 23_b, 23_c, 23_d, `-n 2`). tests/test_app.py, test_live.py and test_vehicle.py do not exist (the app/live pins are in test_round21_e, 22_d, 22_m).
- r23mi_l2 (script /data/r23mi_lint.sh): `ruff check cafe/pm tests` clean (ruff_rc=0, after two E501 of mine rewrapped; r23mi_l1 had found them), `mypy cafe/pm` clean (57 files), `audit --code-only` exactly one problem: docs/mutation.json missing; pytest of the four changed files rc=0.

## Decision text for DECISIONS
Round 23, merge items: `bench_sortie_rate` refuses a NaN, infinite, negative or non-number `sortie_min` / `mission_days` and treats 0 as "not known" (None, UAS cost not scaled, with its note), as before round 23; L17 names the shipped quad_uas.yaml for its two figures, and a test reads them from the file. No owner decision.

## Remaining claims and holders
- L17's 35 and 42 equal the shipped file's: `test_l17_names_the_shipped_file_and_its_two_numbers_are_the_files` (also the CREDIBILITY cell). The "does not say cannot" and cell-measurement pins stay in test_round23_b.
- 0 -> None / bad -> PlanError: the first three tests of test_round23_m.

## Not verified
Coverage was not measured (the one changed code line is run by every `bench_sortie_rate` test). Full suite, gate and mutation not run. The 432-character progress of r23mi_x1 was not split between test_stage1 and test_report (rc=0 only).

## Leftovers
Orca: pm_r23mi, pm_r23mi2, pm_r23mib and pmdata/r23mi_lint.sh removed; logs r23mi_* stay. Laptop: ../cafe-r23mi-base removed.
