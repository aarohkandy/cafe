# Round 19, batch B hand-back: the link card, the fix line, the credibility lines

Branch `r19-b` (cut from 51eb433). Files changed: `cafe/pm/report.py`, `cafe/pm/credibility.py`, `tests/test_round18_a.py` (two pins), `tests/test_round19_b.py` (new, 31 tests). `stage1.py`, `comms.py`, `DECISIONS.md`, `CHANGELOG.md`, `docs/*` untouched.

## OD-2 measurement (not made by the merge)

Model minus a flat-earth Fresnel two-ray (eps_c 72.8 - j118.9, 915 MHz, Hs 0, 300 m to the pair's radio horizon or 12 km, 400 points: the `tests/test_round18_x.py` `measured`), recomputed for the lower antenna moved up by the offset; the number is the largest move of any of the row's minimum, median and maximum [dB]. Orca, proot, 2 CPUs.

| row (low, partner) | +0.005 m | +0.01 m | +0.02 m | +0.05 m | -0.05 m |
|---|---|---|---|---|---|
| 0.1 / 15 | 0.45 | 0.88 | 1.69 | 3.77 | (below the platform floor) |
| 0.3 / 0.3 | 0.08 | 0.15 | 0.30 | 0.70 | 0.90 |
| 0.3 / 0.5 | 0.10 | 0.21 | 0.38 | 0.88 | 1.10 |
| 0.3 / 2.2 | 0.13 | 0.26 | 0.51 | 1.20 | 1.49 |
| 0.3 / 15 | 0.15 | 0.30 | 0.58 | 1.37 | 1.68 |
| 0.5 / 0.5 | 0.05 | 0.09 | 0.18 | 0.42 | 0.49 |
| 0.5 / 2.2 | 0.06 | 0.12 | 0.24 | 0.57 | 0.68 |
| 0.5 / 15 | 0.07 | 0.13 | 0.25 | 0.59 | 0.74 |
| 2.2 / 2.2 | 0.00 | 0.01 | 0.01 | 0.03 | 0.03 |
| 2.2 / 15 | 0.01 | 0.01 | 0.02 | 0.06 | 0.06 |

The partner end barely matters for a 15 m mast (0.01 dB over 0.05 m) and matters as much as the lower end where both are low (0.3 / 0.3: 0.90 dB for 0.05 m on the partner).

The merge's default for OD-2 (a row matched within 0.05 m "after the batch checks that every row moves by under 1 dB") fails its own condition: over 0.05 m the 0.1 m row moves by 3.8 dB, and the 0.3 m rows by 0.9 to 1.7 dB. No tolerance near 0.05 m keeps a printed band true to its printed 0.1 dB. What does: **0.001 m**. Over 0.001 m at either end (and both together) every figure of every row moves by under 0.1 dB (largest 0.093 dB, the 0.1 m row; the others 0.001 to 0.032 dB). The next round figure, 0.005 m, moves the 0.1 m row by 0.45 dB. So: a height within 0.001 m of a row is that row (float dust, a rounding, 0.5000001); a height further off is "not measured", printed with its actual heights, and (within 0.05 m of a row, or just above 0.5 m) the card says that the nearest measured pair's margin is biased and gives that pair's direction words, with no band for this pair. The per-0.01 m move (largest: 0.97 dB at 0.1 m, 0.31 at 0.3 m, 0.135 at 0.5 m, 0.012 at 2.2 m) is printed in L23 as upper bounds (1.0, 0.4, 0.2, under 0.1), a test holds each within 0.1 dB of the measured value.

Hs (M-3), the three pairs with a 15 m partner, same method with the model's `ament_rho` factor written independently on the Fresnel coefficient (min / median / max, dB): 0.1 m: Hs 0 +11.4 / +15.1 / +16.0, Hs 1 +10.9 / +15.2 / +16.0, Hs 2 +6.1 / +15.2 / +15.9, Hs 3 +2.7 / +15.2 / +15.6; 0.3 m: Hs 0 +1.2 / +5.1 / +6.0, Hs 1 +2.0 / +5.2 / +6.1, Hs 2 +2.5 / +5.2 / +6.1, Hs 3 +1.5 / +5.5 / +6.2; 0.5 m: Hs 0 -2.9 / +1.3 / +2.2, Hs 1 -2.0 / +1.3 / +2.3, Hs 2 -0.3 / +1.5 / +2.4, Hs 3 +0.3 / +1.9 / +2.5. These equal the merge's `p5.py` table to 0.1 dB. The other pairs were not measured above Hs 0 and L23 says so.

## Per finding

**M-2 (the card's pair lookup).** `report.py`: `_low_antenna_note` matches a pair to a row of `comms.LOW_ANTENNA_PAIR_BAND` within `credibility.LOW_ANTENNA_ROW_TOL_M` = 0.001 m at each end (`_nearest_row`); the trigger is an end at or below 0.5 + `RF_NEAR_ANTENNA_M` (0.05) m; the three pinned starts are kept (`startswith` of the old tests pass unchanged: "Both ends ... 0.5 m or lower", "An end ... below 0.5 m", "An end ... of 0.5 m", the last for an end within 0.001 m of 0.5) and a fourth start, "An end of this RF link has an antenna just above 0.5 m (up to 0.55 m): ...", covers 0.501 to 0.55 m. A height within the tolerance but not equal prints "(0.3004 m with 15 m, read as the measured 0.3 m with 15 m)". A pair off every row prints "not among those measured" with the heights as `:g` (0.30000000000000004 is a row now; 0.3004 is printed as 0.3004), and within 0.05 m of a row adds "the nearest measured pair, X m with Y m, has a biased margin (<`pair_effect`>), and this pair's figures are not that pair's (L23 says how far a height off a row moves them)". The ship's height is `stage1.ship_antenna_m` with the radio of the mission's UAS platform when the mission gives no `ship.antenna_height_m`, exactly the pick `evaluate_link` makes (`ship (10 m)` where it printed "no single height"). `credibility.py`: `LOW_ANTENNA_ROW_TOL_M`, and L23 states the tolerance and the per-0.01 m moves. Tests (`tests/test_round19_b.py`): `test_m2_a_height_a_rounding_off_a_row_is_that_row` (4 heights), `..._says_what_height_it_took...`, `..._the_tolerance_keeps_a_printed_figure_to_the_tables_0_1_db_...` (the measurement above, with a Fresnel reference), `..._the_stated_move_per_0_01_m...`, `..._a_height_just_above_0_5_m_or_off_a_row_is_not_silence...`, `..._a_ship_without_a_height...`, `..._the_names_l23_gives...` (PE11). Before (51eb433 plus the new test file, orca): the four rounding heights, the "read as" test, the L23 per-0.01 m test, the 0.51 m test and the ship test fail (0.5000001 printed None, 0.30000000000000004 and 0.4999999 "not among those measured", no tolerance text in L23, 0.51 m None, "no single height"); the PE11 test and the measurement test pass on the old code (they pin facts the old code already had). After: all pass.

**M-3 (Hs 0).** The card says "against a Fresnel two-ray at Hs 0 (a calm sea) from 300 m to the horizon ... at a wave height of 1 to 3 m these figures are different (L23); nearer than 300 m this is not stated". The merge's second sentence ("at a sea state of 2 m the minimum is nearer 0") is not true of every pair (0.3 m with 15 m: the minimum goes from +1.2 to +2.5), so the card says only that the figures differ. L23 carries the Hs 1, 2, 3 m figures of the three 15 m pairs (`credibility.LOW_ANTENNA_HS_BAND`, generated into `_l23_text`) and says the other pairs were not measured above Hs 0. Tests: `test_m3_the_card_says_the_figures_are_for_hs_0` (before: fails), `test_m3_l23_prints_the_hs_1_to_3_figures_of_the_15_m_pairs_to_0_1_db` (before: fails; recomputes all nine triples to 0.1 dB and the Hs 0 case equals the table). The table `LOW_ANTENNA_PAIR_BAND` is unchanged.

**M-4 (round-17 `flip.json`).** `_fix_html`: the left badge is the same-members verdict whenever the same-members baseline exists, with "(whole run: X)" when it differs, for an older file too (the `target_same is not None` condition is gone); when `target_same` is None the page adds "A Stage-1 row is judged against the whole run's target, GO or MARGINAL: this file, made by an older round, does not record the target of the rows' own members." `report.json` gains no key (`target_same` stays None). Tests: `test_m4_an_older_flip_json_whose_same_members_verdict_differs...` (before: "NO-GO to GO" beside 0.375; after: "MARGINAL (whole run: NO-GO) to GO"), `..._two_verdicts_agree_prints_one_badge`.

**M-13 (`measured`).** `report._fix`: `measured = {BASE_SAME_FLAGS: False, BASE_SAME_RUN: True}.get(source)`; `source` is stored only when a `str` (None for 5, a list, a dict); an unknown phrase is `measured` None, not False. `whatif.py` unchanged. Tests: `test_m13_measured_is_from_the_two_phrases_and_anything_else_is_not_known` (8 sources; before: six fail, the ledger check fails for 5), `..._a_baseline_that_was_not_run_is_not_measured...` (passes both sides).

**A-3 (fix-text edges; FH6, FH8, FH9, FH10, SM9).** Five tests, `test_a3_fh8_...`, `fh6`, `fh9`, `fh10` (a Stage-1 row against the same-members P(fail), an emulated row against the whole run's, both directions), `sm9`. They pass on the old code (the code was right) and each dies under the equivalent mutation of the fixed code (list below).

**A-4 (K4, K7b, K12a).** `test_a4_k4_...` (a not-judged row that carries `validated` True is not counted: "of the 3 judged, 3 with |E| <= U_val"), `test_a4_k7b_...` (four rows that pass plus a wide one: level 2 and the "an uncertainty that wide cannot validate it" line), `test_a4_k12a_...` (`used_counts`: a fitted value is counted neither used nor unused).

Mutants run on the fixed code (orca, one at a time, the selected tests only, each restored): FH8, FH6, FH9, FH10 (always the whole run's; and a same-members baseline for an emulated row), SM9, M-4 reverted, M-13 (`== BASE_SAME_RUN`; the `isinstance` dropped), ship read as 15 m, the radio route reversed, near distance 0, trigger `<`, tolerance 0.01 and 0, PE11 (names swapped), K4, K7b, K12a, "Hs 0" removed: 21 of 21 killed (rc 1, test failures, none a collection error). The reviewer's own mutants (written against the old lines) were not re-run; the old Q3 (`round(known[0], 1)`) has no equal in the new code, its hazard (a height 0.002 m off a row taken as the row) is held by the 0.302 m case.

## Decisions taken (text for DECISIONS; each "awaiting the owner")

- **OD-2 (M-2), taken as: (b) with a measured tolerance.** A row is matched within 0.001 m at each end (not 1e-6, not 0.05: see the measurement), the trigger is an end at or below 0.5 + 0.05 m, a height off a row prints the actual heights, says "not among those measured" with no band, and for a pair within 0.05 m of a row names that nearest row and its direction as biased; a height of 0.0005 m off prints "read as the measured ..." with both heights. The ship's height is `stage1.ship_antenna_m`'s (10 m without a height and without a UAS radio). Amends 944, 991. The cliff at 0.55 m remains and is stated: above it an end of 0.55 to 2.2 m prints no card (L23: a height between the listed ones is not measured); the schema's 0.5 m floor for the ship is unchanged.
- **OD-3 (M-3), taken as (a), narrowed.** The card says "at Hs 0 (a calm sea)" and that the figures are different at a wave height of 1 to 3 m (L23); L23 prints the Hs 1 to 3 m figures of the three 15 m pairs, measured here; the other seven pairs are stated as not measured above Hs 0. Not "the minimum is nearer 0": untrue for 0.3 m with 15 m. No figure of the table changed.
- **OD-4 (M-4), taken as (a).** An older `flip.json` with `base_same` and no `target_same`: the left badge is the same-members verdict with "(whole run: X)" beside it when the two differ, and the page says the target is the whole run's. Amends 952, 977.
- **M-13 (not an owner decision).** `measured` is True for the run phrase, False for the flags phrase, None for any other string, and None for a non-string `source` (which is not stored). Amends 993.

## Pins moved

- `tests/test_round18_a.py::test_m1_a_flip_json_without_target_same_renders_with_the_whole_runs_verdict_as_it_did` (renamed `..._renders_with_the_same_members_verdict_and_names_the_whole_runs`): it pinned "MARGINAL to GO" and "whole run:" absent for a `base_same` of NO-GO beside a whole run of MARGINAL, i.e. exactly the pair M-4 is about. (merged.md says "the two agree": they do not, the fixture's whole run is MARGINAL 0.18.) Now "NO-GO (whole run: MARGINAL) to GO".
- `tests/test_round18_a.py` `CASE` (the card's full sentence): "at Hs 0 (a calm sea)" and "at a wave height of 1 to 3 m these figures are different (L23)" added (M-3).
- Unchanged and passing: every `startswith` pin of the three card starts (`test_round17_a`, `test_round18_a`, `test_round18_x`, `test_round18_m`), `NOT_MEASURED`, L23's regex tests in `test_round18_x` and `test_round18_b`.

## Cross-batch needs

- **Batch G: `docs/CREDIBILITY.md` L23 row (line 149) must carry the new L23 text, character for character** (`tests/test_config_docs.py::test_credibility_doc_limitation_table_is_the_code_s_list` compares `| L23 | <text> |`). It fails on this branch until G replaces the text cell with: `python -c "from cafe.pm import credibility as c; print(next(x['text'] for x in c.LIMITATIONS if x['id']=='L23'))"` (run in the image). The new text adds, before "A pair of heights that is not listed", the Hs 1 to 3 m sentence and the tolerance sentence. `docs/PHYSICS.md` 12.1 should get the Hs 1 to 3 m figures above and the tolerance (0.001 m, with the table of moves per offset), and the card's new start ("just above 0.5 m"). DECISIONS: amends 944, 952, 977, 991, 993; new rows for OD-2, OD-3, OD-4 and M-13 from the text above.
- **Batch A: the M-5 hunk of `tests/test_round18_x.py`** (`test_x2_wind_direction_acts_on_the_uas_battery_reserve_and_not_on_its_profile_share`) is untouched here, as the lead said; merged.md's batch B note says B applies it, the lead's brief says A does. One of the two must, or that test fails when A lands M-5.

## Not verified

- The card was checked through `report._low_antenna_note` and through `report.write` of the synthetic run (fix line, `same_members`), not through a full pipeline run or a real mission with a 0.51 m Seaglider.
- The sensitivity numbers are for Hs 0, 915 MHz, 300 m to the horizon or 12 km, a flat-earth Fresnel bound (no surface wave); not at Hs above 0 and not nearer than 300 m.
- A tolerance on the partner end beyond 0.001 m (a 15 m mast moves the figures by 0.01 dB over 0.05 m) was not used: the rule is one tolerance for both ends.
- `docs/` and DECISIONS are not updated (G); `tests/test_config_docs.py` is expected to fail on the L23 row until they are.
- Not run: the full suite, the audit, mutation testing of physics/stats (nothing there changed), coverage (the changed lines are in `report.py` and `credibility.py`; their branches are all reached by the new tests, not measured).

## Test runs (orca, proot, 2 CPUS each)

| job | command (files) | rc |
|---|---|---|
| r19b_3 | `tests/test_round19_b.py` (31 tests, final tree) | 0 |
| r19b_old2 | the same file against 51eb433 (before) | 1: 17 failures, all M-2, M-3, M-4, M-13 as listed above |
| r19b_ex | `-n 2`: test_credibility, test_report, test_round16_report, test_round16_a, test_round17_a/b/d/m, test_round18_a/b/c/m/x, test_config_docs, test_receipts, test_comms (run on the tree before line wrapping only; the wrap changed no behaviour and test_round19_b was rerun after it) | 1: the one failure is `test_config_docs.py::test_credibility_doc_limitation_table_is_the_code_s_list` (docs/CREDIBILITY.md L23 row, batch G, see above); everything else passed |
| r19b_mut | 21 mutants, one at a time | 21 killed |
| r19b_ruff2 | `ruff check cafe/pm tests` | 0 |
| r19b_mypy | `mypy cafe/pm` | 0 |

Orca leftovers: scratch dirs `~/cafe-worker/cafe/pm_r19b`, `pm_r19b2`, `pm_r19b_old` (synced code and `.pmx.owner` markers) and the tmux/log files `~/cafe-worker/logs/r19b_*.log`; nothing else, nothing in `/tmp`, no shared store touched. Laptop: the throwaway worktree `../cafe-r19b-old` (detached at 51eb433).
