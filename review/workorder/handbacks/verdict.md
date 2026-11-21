# Hand-back: work-order step 5, verdict-level fixes (items 1, 2, 4, 5, 6, 7)

Branch wo-verdict, base 8ecf0e7. Items 3 (already fixed), 8 and 9 (owner), 10 (procedure) not built. Orca jobs run as `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_wo_verdict[_b] PM_CPUS=2` (logs `~/cafe-worker/logs/wo_verdict_*.log`).

## What changed
- 6 `credibility.py` Facts: dropped `": no ledger" not in p and`, so a missing stage ledger is a problem (verification level 1, no "ledger chain audits clean", ms_management below 3).
- 7 `pipeline.py` `s_windows`: records outside the data (`env.inside`) are masked before the window is picked; the failed members are used when one has a record inside the data, else all members (basis and `failed_at` follow). No raise of `OutsideData`; a vehicle with every record outside gets `[]` and `every_vehicle_has_a_window` fails.
- 5 `env/surface.py`: source text only (fallback ruled by the lead); the number is unchanged, no 1.4826.
- 4 `report.py`: `Trace.run_file_ref(name, label)`; the seed uses `mission.yaml` and the plan values `plan.json` (receipt `report:input:<name>`, sha256 of the file; `stage` stays the label, so no stage cell moves; a missing file gives a `missing`/`not_run` row). Box, ship, deploy and `mref` values keep the ingest config hash (they are inside it).
- 1 `report.py`: "at least" before the member count in the certify statement and in the card.
- 2 `report.py` `USV_RATIO_NOTE`, `credibility.py` L18 and sanity detail, `docs/CREDIBILITY.md` L18 row: "westward" and the beam-reach/close-hauled sentence deleted; no sentence added.

## Regression tests (tests/test_wo_verdict.py, 11 cases) and before/after
| item | test | before (base 8ecf0e7) | after |
|---|---|---|---|
| 6 | test_a_missing_stage_ledger_is_a_problem_and_the_chain_is_not_called_clean | FAIL wo_verdict_b1, wo_verdict_b2 | pass wo_verdict_4 (rc=0) |
| 7 | test_windows_do_not_query_the_strict_environment_... [glider, usv, uas], ..._fall_back_to_all_members, test_a_vehicle_with_every_record_outside_the_data_has_no_window_... | FAIL (OutsideData) wo_verdict_b1 | pass wo_verdict_4 |
| 5 | test_the_stokes_drift_source_says_... | FAIL wo_verdict_b2 | pass wo_verdict_4 |
| 4 | test_the_seed_and_the_plan_values_carry_..., test_a_run_file_receipt_for_a_file_that_is_not_there_... | FAIL wo_verdict_6 | pass wo_verdict_4 |
| 1 | test_the_member_count_to_certify_is_a_least_number_... | FAIL wo_verdict_6 | pass wo_verdict_4 |
| 2 | test_the_usv_pages_do_not_say_the_current_is_westward_... | FAIL wo_verdict_6 | pass wo_verdict_4 |

wo_verdict_6: the same test file on a `git archive 8ecf0e7` copy in `pm_wo_verdict_b`, items 4, 1 and 2: 4 FAILED (receipt is `ingest:config:...`; no `run_file_ref`; card says "needs 73"; page holds "westward"), rc of the log 0 (the step rc=1).

wo_verdict_4 (final tree) steps, all rc=0: `ruff check cafe/pm tests`, `mypy cafe/pm`, tests/test_wo_verdict.py + tests/test_round23_claims.py, tests/test_report.py + test_credibility.py + test_surface.py, the whole tests/test_pipeline.py, tests/test_audit.py + test_reproducible.py + test_acceptance.py + test_cli.py + test_receipts.py. `audit --code-only` rc=1 with the one problem "mutation: no stored result at docs/mutation.json" (as at 8ecf0e7; no banned token, no other finding).

## Pins moved (existing tests edited, none weakened)
- tests/test_report.py `test_receipts_are_real_ledger_entries`: receipt kinds now `{"check","output","config","input"}` (the seed and plan rows are `input`).
- tests/test_report.py `test_not_certifiable_below_n_certify` (:137) and `...a_not_exercised_links_card...` (:2383): "needs 73 members" -> "needs at least 73 members".
- tests/test_report.py `test_r10_m4_...` (:2749): same.
- tests/test_credibility.py LIMITS2 (:465): L18 text without "westward".
- docs/CREDIBILITY.md L18 row mirrors the text (the claims lint reads it).

## Decision text and CHANGELOG lines (numbers left to the lead)
1. DECISIONS: The member count that certifies P(fail) < 5 % is a least number: each failure raises it (73 at none, 110 at one, 142 at two, 173 at three). The statement and the card say "at least N". The number and `credibility.py` `short` are unchanged. CHANGELOG: report prints "at least" before the certifying member count.
2. DECISIONS: The USV note and L18 no longer say the current is westward or describe the demo's tack change; they say a current may lower the ratio and that a double penalty is possible and not established. The demo-scenario measurements in the CREDIBILITY.md L18 row stay (labelled as the diagnosis scenario). CHANGELOG: USV ratio note and L18 no longer name the demo's current.
4. DECISIONS: The seed and the plan values carry the sha256 of `mission.yaml` / `plan.json` (report-stage ledger inputs), not the ingest config hash, which leaves the seed out and holds no plan. The printed stage stays "mission" / "plan". CHANGELOG: receipts of the seed and the plan values are the hashes of their own files.
5. DECISIONS: The Stokes-drift uncertainty stays the leave-one-out median absolute speed error times |v| (a median of per-triple medians); the source text says so and that it is not a standard deviation. No 1.4826 factor (a Gaussian assumption was not made). CHANGELOG: Stokes drift source text names the uncertainty as a median absolute error.
6. DECISIONS: A missing stage ledger is a problem of the ledger audit (the clause that dropped every "no ledger" line is removed): "ledger chain audits clean" and verification level 2 / ms_management level 3 need all nine ledgers. CHANGELOG: a run missing a stage ledger no longer reads "ledger chain audits clean".
7. DECISIONS: `s_windows` picks windows from records inside the data (`env.inside`); the failed members' records are used when one is inside, else all members. Reproduced first: a `left_data` member kept finite positions outside the box and the strict environment raised `OutsideData` (wo_verdict_b1). CHANGELOG: s_windows no longer queries the strict environment outside the data.

## Printed sentences or keys added
- "at least" (certify statement and card, item 1).
- Stokes source: "median absolute speed error ... , used as the uncertainty, not a standard deviation" (replaces "median speed error"; the work order names the fix, item 5).
- Two rows in the receipts table (`report:input:mission.yaml`, `report:input:plan.json`), item 4. No new key in report.json.
- Deleted: "westward", the beam-reach/close-hauled sentence.

## Not verified
- The full suite and coverage gate were not run (only the files above); mutation not run. Coverage of the new `run_file_ref` missing branch and the `inside is None` branch of `s_windows` is not measured (the former has a test; the latter, `getattr(ctx.env, "inside", None)`, only matters for an env without `inside`: check it under `--cov`, a test may be needed to keep 100 %).
- No demo run: no printed value in a real report was compared to q25.
- Other stages with a lenient edge (item 7's note) were not examined.

## Still wrong / for the lead
- Item 7 covers `s_windows` only; a left_data member's out-of-box tracks elsewhere are untouched.
- Item 5 leaves the uncertainty as a median error, not a sigma, so a consumer that treats it as 1 sigma still understates it by about 1.48.
- Item 4: the seed/plan rows add two `input` rows; `tests/test_report.py` pin on kinds moved.
