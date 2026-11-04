# Round 8, batch K hand-back (credibility, report, shared JSON reading)

Branch `r8-k` (worktree `/Users/aaroh/Downloads/everything/cafe-r8k`). Fixed: M-1 (Data pedigree part), M-7, M-10, M-16, M-19, M-20, M-21, M-22, M-42 (all but the emulator test, see "needs"), M-45, M-46, M-47.
The commit trailer is `Co-Authored-By: Claude Sonnet 5.5` (the model that did the work), not the Opus line in r8_common.md.

## Per finding

### M-1 (Data pedigree)
- `cafe/pm/credibility.py` `USTAR_AGREE_MIN = 0.90`, `_data_pedigree`: level 2 needs the ledger check `coare_ustar_vs_umwm_ust` to carry `value >= 0.90` when the check is there. A smaller value (or a check with no numeric value) keeps the factor at 1 and `missing` says "BRIEF 2.1 finding: only 50.0 % of the sea points have COARE u* within 20 % of UMWM ust; the brief asks 90%, ...". A mooring comparison cannot lift it. A ledger without the check (older runs, the `pm_run` fixture) is not held down. A failed `forcing_in_physical_range` (E's check) is already in `bad`, so it holds the level at 1 with no new code. `RULES["data_pedigree"]` and docs/CREDIBILITY.md row changed.
- Tests: `test_r8_m1_data_pedigree_two_needs_the_brief_ninety_percent_ustar_agreement`, `test_r8_m1_a_failed_physical_range_check_or_an_unrecorded_fraction_holds_data_pedigree_at_one`.
- Not done here (E's): the `forcing_in_physical_range` check and the u* note in `pipeline.py`.

### M-7
- `cafe/pm/__main__.py` `validate`: for a mission whose go is above 0.75 it prints (to stderr, so the existing exact-stdout test stays as it was) "note: verdict.go 0.99: GO needs the point estimate of P(success) >= 0.99 and the 90 % Wilson lower bound on success >= 0.75 (DECISIONS 68), so 9 members without a failure are GO; the stopper uses the 95 % bound against 0.01". n0 comes from `intervals.verdict(0, n)`.
- `cafe/pm/report.py` `_stat_html`: " (looser than 1 - go)" after the "at most 0.25" when `go_bound > go`.
- Tests: `test_r8_m7_validate_says_how_few_members...` (go 0.99 and the demo's 0.9, both n0 = 9), `test_r8_m7_validate_prints_no_note_...` (go 0.7), `test_r8_m7_the_rule_sentence_says_when_the_interval_term_is_looser_than_one_minus_go` (0.99, 0.9, 0.7).

### M-10
- `cafe/pm/dtmb5415.py`: `unsettled(iters, drift, parts, scatter)` holds the convergence rule once; `_converge` uses it (`ok = not unsettled(done, drift, parts, scatter)`); `not_converged_reasons(case)` (flag missing = "no convergence record"; flag False with no stored cause = "convergence limits not met (cause not stored)"); `row_notes` grids carry `reasons`.
- `cafe/pm/credibility.py` `_dtmb_rows`: a row with reasons is "finest grid not converged (<reasons>)" and not judged. A deleted `converged` is now not judged (was `validated: True`).
- Tests: `test_r8_m10_the_note_lists_the_cause_of_a_finest_grid_that_is_not_converged`, `test_r8_m10_unsettled_is_the_one_convergence_rule`, `test_r8_m10_not_converged_reasons_reads_a_missing_flag_as_not_converged`.
- Existing test changed: `test_an_unconverged_finest_grid_leaves_the_row_not_judged...` asserted the false inequality "iterative drift 0.0075 > 0.005"; it now asserts "iterative drift 0.0075 (limit 0.005)". Nothing else weakened.

### M-16
- `platforms/modems.yaml`: `defaults.anchor_margin_db` and `defaults.valid_range_factor` are `{value, unit, assumed: true, why}` leaves; `comms.py` reads `["value"]` (two reads: `implementation_loss_db`, `valid_range_m`); `config.table_provenance` accepts a `{value...}` leaf in a table (checks it as a leaf, not an entry `source`); `hangar --platform modems` now prints "2 of 2 values assumed"; `credibility.platform_items` already walks every `value` leaf, so `modems.yaml:defaults.anchor_margin_db` / `...valid_range_factor` join the assumed list with no code change.
- Tests: `test_r8_m16_hangar_modems_counts_the_two_assumed_defaults`, `test_r8_m16_a_modem_default_without_a_source_or_an_assumed_why_fails_naming_it` (cli), `test_r8_m16_a_defaults_leaf_needs_a_source_or_an_assumed_why_but_not_an_entry_source` (config), `test_r8_m16_the_two_modem_defaults_are_assumed_inputs_with_the_same_numbers` (listed; the margin at the vendor range is still 3.0 dB and `valid_range_m` still 40000.0).

### M-19
- `dtmb5415.receipts`: a row whose finest grid has reasons gets a `rc.context` line "C_T Fr x: |E| <= U_val is not judged: the finest grid has not converged (<reasons>; see the convergence rows)" instead of the bracket. Test: `test_r8_m19_a_row_whose_finest_grid_has_not_converged_is_a_context_row_in_the_receipts` (Fr 0.20 and 0.41 context, 0.10 and 0.28 brackets).

### M-20
- `credibility.usv_speed_sampling()` computes the sentence from `config/perturbations.yaml` `usv_vpp_bias` (shipped prior: "within +-1.4 % of the unbiased polar speed (range 2.9 %, sd 0.8 %; +-1.9 % of the speed flown)"); `report._usv_bias_html` and the Uncertainty evidence call it. The helper lives in credibility.py because perturb.py / stage1.py are not mine.
- Tests: `test_r8_m20_the_usv_speed_sampling_sentence_is_computed_from_the_prior` (prior monkeypatched to [-0.30, -0.20] gives +-5.0 % and +-6.7 %); the two existing tests that asserted the literal "sampled over 1.4 % only" now assert the computed sentence (`test_the_usv_speed_prior_width_is_not_an_uncertainty_of_the_model`, `test_the_usv_card_says_the_speed_factor_is_sampled_over_its_range_only_when_the_brief_case_is_stored`).

### M-21
- `_robustness`: `clear = bool(sens) and tests >= len(sens) and luck < 0.05`; the evidence adds "ranked parameters without a permutation floor are not counted". Test `test_r8_m21_ranked_parameters_without_any_permutation_floor_are_not_clearly_above_chance`.

### M-22
- `config.json_object` (moved from `__main__._json_object`, which is now an import alias); `credibility._json` and `report._jl` use it, so a truncated or non-object run file is a ConfigError (exit 2, one `error:` line). Also the `credibility.json` read in `report.build`.
- Tests: `test_r8_m22_report_of_a_run_with_a_damaged_json_file_ends_in_an_error_line` (cli, 8 files x truncated/array: summary, refit, priors_fitted, tao_compare, stage3 windows, windows, flip, ingest ledger), `test_r8_m22_a_truncated_run_file_is_a_config_error_naming_it` and `..._not_an_object_is_refused_too` (report), `test_r8_m22_a_truncated_run_json_is_a_config_error_naming_the_file` (credibility), `test_r8_m22_json_object_refuses_damage_and_other_json` (config).
- Not testable as merged.md says: a cut `report/credibility.json` is rewritten by `report.write` before `build` reads it, so it never reaches the reader (no test; the read still goes through `json_object`). Emulator `holdout.json` is covered through `report.write`.
- The ledger cut passes through `report.Trace._jl` here; M-23 (batch A) changes how `done` and the audit read ledgers, not this path.

### M-42 (tests)
- Robustness (a), (b), (c) and D-7 in tests/test_credibility.py; D-9(a) in tests/test_config.py. D-8 (emulator) is in "needs". Mutant results below.

### M-45, M-46
- `LEVEL_TEXT["verification"][2]` = "moderate: the ledger chain audits clean and test files exist; this report does not run or read the tests (`make audit` does)"; evidence "{n} test files present (their results are not read here)"; `RULES["verification"]` says so. `LEVEL_TEXT["ms_management"][3]` = "... house rules and ruff configured (`make audit` runs ruff; this report only checks that it is configured); no independent reviewer". docs/CREDIBILITY.md rows (Data pedigree, Verification, M&S management, the DTMB row note, the assumed-input count, receipts). Tests: `test_r8_m45_verification_two_says_it_does_not_run_or_read_the_tests`, `test_r8_m46_the_management_text_no_longer_says_the_audit_does_not_run_ruff`.

### M-47
- `report._txt` singularises `candidates`, `notches`, `members` when the value is exactly 1; "All {k} candidate(s)" in the flip summary. Existing test `test_what_would_fix_it_when_nothing_flips_the_verdict` pinned "1 candidates evaluated"; it now asserts "1 candidate evaluated" and that "1 candidates" is absent. New: `test_r8_m47_a_count_of_one_is_not_pluralised`.

## Before / after

Fixed code, `-k r8` over the five files: 56 passed (before the full-file runs below). On the unfixed `premission-step4` (`eaf0e27`) with the new test files copied in (throwaway worktree `cafe-r8k-old`): the new tests for M-1, M-7, M-10, M-16, M-19, M-20, M-21, M-22, M-45, M-46, M-47 and the four existing tests that I changed all FAILED (50 FAILED lines among the tests selected with `-k`; the M-42 tests and the `lost_after_h` test pass there, as they should: they pin code that was already right).

M-42 mutants, each applied to a copy of the fixed code (throwaway worktree `cafe-r8k-mut`) and run against the named tests; every one is killed:

| mutant | killed by |
|---|---|
| `luck < 0.15` | `test_r8_m42_the_robustness_rule...[14-percent-by-luck]` (2 != 1) |
| `0.1 ** i * 0.9 ** (tests - i)` | `...[2-of-5-is-2-percent]` (1 != 2) |
| `tests = len(allv)` | `...[10-entries-2-floors]` (1 != 2) |
| `judged = list(full)` | `test_r8_m42_validation_three_counts_four_judged_rows_beside_a_row_not_judged` (2 != 3) |
| `lost_after_h` `"minimum": 0` | `test_r8_m42_lost_after_h_of_zero_is_refused_naming_above_0` (DID NOT RAISE) |
| `drop_duplicates(self.features)` | the D-8 test below, in a scratch file (3 asks for one point; passes on the fixed code) |

## Existing tests changed (each pinned the old behaviour; no assertion was loosened)

- tests/test_credibility.py `test_an_unconverged_finest_grid_leaves_the_row_not_judged...`: "iterative drift 0.0075 > 0.005" (the false inequality, M-10) became "iterative drift 0.0075 (limit 0.005)".
- tests/test_credibility.py `write_dtmb` (fixture): the finest grid now stores `converged: True`, as every real `run_*.json` does; without it the rows are "not judged" by M-10 (this fixed `test_dtmb_rows_follow_asme_vv20`, `test_a_wrong_model_is_not_validated`, `test_all_four_dtmb_rows_validated_gives_level_three_capped_to_two`, `test_the_page_shows_vv_rows_with_and_without_uncertainty`).
- tests/test_credibility.py `test_ms_management_level_three_needs_the_process_files`: "ruff configured (not run by the audit)" (the false clause, M-46) became "`make audit` runs ruff; this report only checks that it is configured".
- tests/test_credibility.py `test_the_usv_speed_prior_width_is_not_an_uncertainty_of_the_model` and tests/test_report.py `test_the_usv_card_says_...`: "sampled over 1.4 % only" became the computed sentence (M-20).
- tests/test_report.py `test_what_would_fix_it_when_nothing_flips_the_verdict` ("1 candidates evaluated") and `test_what_would_fix_it_says_not_searched_when_no_candidate_was_evaluated` ("1 candidates that cannot"): singular (M-47).
- tests/test_report.py `test_the_page_labels_both_intervals_with_their_level` and `test_the_verdict_rule_is_stated_with_its_ties_and_the_wilson_bound_the_go_rule_also_needs`: the rule sentence now carries " (looser than 1 - go)" after "at most 0.25" (M-7).

## Interface with E (M-1)

`credibility.py` reads the ingest check `coare_ustar_vs_umwm_ust` (`value` = the agreeing fraction; level 2 needs at least `USTAR_AGREE_MIN = 0.90`, inclusive; the message starts "BRIEF 2.1 finding:") and E's `forcing_in_physical_range` (a failed one is in `bad` and holds the level at 1). Both are accepted as absent in an older ledger (the `pm_run` fixture has neither, and the synthetic run stays at 2). `USTAR_AGREE_MIN` is a second copy of E's `pipeline.USTAR_AGREE_FRACTION` (0.90): credibility.py does not import pipeline; the lead may point one at the other after the merge. Test: `test_r8_m1_both_ingest_checks_present_and_passing_keep_level_two_and_absent_ones_are_accepted` (0.90 passes, 0.8999 caps). Not covered by a K test: winds x 3 on the CI fixture (needs E's ingest change).

Checked against E's branch (`git show r8-e:cafe/pm/pipeline.py`): E writes `forcing_in_physical_range` (ok = no bad points, `value` = count) and `coare_ustar_vs_umwm_ust` with `ok = n > 0 and finite(median)` and `value = round(frac, 4)` (None when n = 0), so the check is `ok` even at 50 %: the fraction test in `_data_pedigree` is what holds the level, and n = 0 lands in `bad` through `ok=False`. Fail-first: the three M-1 tests (`..._two_needs_the_brief_ninety_percent_ustar_agreement`, `..._a_failed_physical_range_check_or_an_unrecorded_fraction_...`, `..._both_ingest_checks_present_and_passing_...`) FAIL on credibility.py from eaf0e27 (pre-K) with the new tests copied in (3 failed) and pass on this branch.
Exact one-line integration after the merge (optional, removes the second copy of 0.90): in `cafe/pm/credibility.py` replace the line `USTAR_AGREE_MIN = 0.90 ...` with `USTAR_AGREE_MIN = pipeline.USTAR_AGREE_FRACTION` plus `from . import pipeline` (only if credibility importing pipeline does not create an import cycle or pull stage code into the report; otherwise leave both at 0.90). Edge: E rounds the stored fraction to 4 decimals, so 0.89996 is stored as 0.9 and passes here while E's own note (on the unrounded value) fires; harmless, 4-decimal resolution.

## Proposed DECISIONS rows (the lead numbers them from 393)

| ? | Data pedigree level 2 needs the ingest check `coare_ustar_vs_umwm_ust` to record a fraction of at least 0.90 (BRIEF 2.1); below it the factor stays 1 and says the number; a ledger without the check is not held down | Review round 8, M-1. Amends 168: the u* agreement is still not a gate, but the finding the brief asks for now moves a credibility level. |
| ? | `validate` prints a note when verdict.go is above 0.75 (the interval term stays at 0.75, nine members without a failure are GO); the report rule sentence adds "(looser than 1 - go)" when 1 - 0.75 exceeds 1 - go | Review round 8, M-7. Keeps 68, 153, 287, 333: the rule is unchanged, the reader is told. |
| ? | A DTMB row is "not converged" unless the stored `converged` is True; the note lists the causes (resistance drift, pressure/viscous drift, scatter, fewer than 1000 iterations, no record) from `dtmb5415.unsettled`, which the run loop also uses | Review round 8, M-10. Amends 345. A missing flag was judged by the credibility report and failed by the receipts. |
| ? | The DTMB receipts do not bracket |E| <= U_val for a row whose finest grid has not converged; it is a context row "not judged" | Review round 8, M-19. Extends 345 to the receipts. |
| ? | `anchor_margin_db` (3 dB) and `valid_range_factor` (10) in platforms/modems.yaml `defaults` are `{value, unit, assumed: true, why}` leaves, counted by `hangar` ("2 of 2") and listed as assumed inputs | Review round 8, M-16. Amends 329 ("0 of 0"). Values unchanged. |
| ? | The USV speed-sampling sentence is computed from `usv_vpp_bias`: +-1.4 % of the unbiased polar speed, range 2.9 %, sd 0.8 %, +-1.9 % of the speed flown | Review round 8, M-20. Amends 355: "1.4 % only" read as the width; it is the half-width of the unbiased speed. |
| ? | Results robustness counts ranked parameters only where a permutation floor exists (`tests >= ranked`) | Review round 8, M-21. Amends 363. No floor, no test. |
| ? | `config.json_object` is the one reader of run JSON: a truncated or non-object file read by `report` is a ConfigError (exit 2) | Review round 8, M-22. Extends 374 to every reader of `report` (ledgers are M-23's). |
| ? | Verification 2 and its evidence say the report does not run or read the tests | Review round 8, M-45. Wording; no level moves. |
| ? | The M&S management text says `make audit` runs ruff and this report only checks it is configured | Review round 8, M-46. Amends 363. |
| ? | A count of exactly 1 uses the singular unit (candidate, notch, member) | Review round 8, M-47. Extends 381. |

## Proposed CHANGELOG lines

- M-1 (Data pedigree): level 2 needs 90 % of sea points with COARE u* within 20 % of UMWM ust (BRIEF 2.1), else 1 with the number.
- M-7: `validate` notes that a go above 0.75 leaves the interval term at 0.75 (nine members without a failure are GO); the report rule sentence says "looser than 1 - go".
- M-10: DTMB convergence rule in one function (`dtmb5415.unsettled`); a finest grid with no `converged` flag is not judged; the note names the causes.
- M-16: modems.yaml `anchor_margin_db` and `valid_range_factor` are assumed-input leaves (hangar says "2 of 2").
- M-19: DTMB receipts show |E| <= U_val as "not judged" for a row whose finest grid has not converged.
- M-20: the USV speed-sampling sentence is computed from the prior.
- M-21: Results robustness ignores ranked parameters that have no permutation floor.
- M-22: `report --run` ends in an `error:` line (exit 2) for a damaged run JSON file.
- M-42: tests that fail on five mutants of round 7's fixes (robustness rule x3, "not judged" filter, `lost_after_h` bound).
- M-45: Verification text says the tests are not run or read by the report.
- M-46: M&S management text says `make audit` runs ruff.
- M-47: "1 candidate", "1 notch", "1 member".

## Doc text

- QUESTIONS_FOR_LAB.md item 5 (M-7), add as a sub-item: "Should the 90 % lower-bound term of GO follow verdict.go (now it stays at 0.75 for any go above 0.75)? Default: no, as now (DECISIONS 68, 153)."
- docs/CREDIBILITY.md: already edited in this branch (Data pedigree, Verification, M&S management rows; the DTMB row note; the assumed-input count; receipts). Nothing else.

## Needs from other batches

1. tests/test_emulator.py (M-9's batch / whoever owns it), append at the end (D-8 of M-42; verified here to pass on the fixed code and fail on `drop_duplicates(self.features)`):

```python
def test_the_fresh_draws_are_asked_for_distinct_points_not_for_replicates_of_one(tmp_path):
    """Round 8 M-42 (D-8): `drop_duplicates(self.features)` in place of `point_cols` left the suite green; replicates sit next to each other here."""
    base = E.synthetic_table(40, 1)
    rng = np.random.default_rng(3)
    cols = ["deploy_shift_h", "lon_shift_deg", "duty_cycle", "battery_wh"]
    df = pd.concat([base.assign(wind_mean=base.wind_mean + 0.01 * rng.normal(size=len(base)), hs_max=base.hs_max + 0.01 * rng.normal(size=len(base)))
                    for _ in range(3)], ignore_index=True).sort_values(cols, kind="stable").reset_index(drop=True)
    em = E.Emulator(E.FEATURES, E.TARGETS, path=tmp_path / "t.parquet", seed=1, point_cols=cols)
    asked = []

    def fresh(row):
        asked.append(tuple(row[cols].round(9)))
        return 0.5, 10
    h = em.holdout_report(df, fresh=fresh)
    assert len(asked) == E.FRESH_POINTS == len(set(asked)) and h["fresh"]["points"] == E.FRESH_POINTS
```
2. E: nothing needed for my reader (it reads the existing check `coare_ustar_vs_umwm_ust` and its `value`); E's `forcing_in_physical_range` fails the level through the existing `bad` list.
3. After the merge, M-20's tests assume `report.py` imports `credibility` (it does) and `stats.sampling.PERTURBATIONS`.


## Final run (finish pass, homebase, PM_CPUS=2 PM_MEM=12g, detached)

`ruff check cafe/pm tests bench`: All checks passed. `mypy cafe/pm`: no issues in 54 source files. `pytest tests/test_credibility.py tests/test_vv.py tests/test_report.py`: pytest1_rc=0 (all dots, no F/E). `pytest tests/test_cli.py tests/test_config.py -k r8`: pytest2_rc=0. M-1 fail-first on pre-K credibility.py (eaf0e27): 3 failed. No container of K left running.
