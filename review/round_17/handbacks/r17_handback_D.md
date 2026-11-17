# Round 17, batch D hand-back: RF link physics and validation (M-5, M-6, M-16, M-20)

Branch `r17-d`, worktree `/Users/aaroh/Downloads/everything/cafe-r17d`, base 433429e. Code and tests are commit c2e47f0; this file is the second commit.
No document other than this file was edited. No physics function changed (see "No demo number moves").

Files touched: `cafe/pm/physics/comms.py` (M-16 one line; M-5 docstring only), `cafe/pm/physics/glider.py`, `cafe/pm/physics/usv.py`, `cafe/pm/physics/uas.py`
(the `ship_antenna_height_m` kind only), `tests/test_round17_d.py` (new).
OUTSIDE MY LIST, one minimal hunk: `cafe/pm/physics/__init__.py` (the new kind `antenna`, the constant `ANTENNA_MIN_M = 0.1`, three `HINTS` entries, one docstring
line). It was needed because the refusal must name why, and `HINTS` and `_RULES` live there. No existing test file was edited: `test_platform_required.py`'s
row `rf_antenna_height_m ... "at most 50"` still matches, because the new kind's text is "0.1 m or above and at most 50".

## M-6: platform RF antenna heights

Change (OD-4, floor 0.1 m):
- `physics/__init__.py`: kind `antenna` (>= `ANTENNA_MIN_M` = 0.1); `HINTS` for `antenna_height_m`, `rf_antenna_height_m` (the sentence "below 0.1 m the two-ray
  link model has no meaning") and `ship_antenna_height_m`.
- `glider.py`: `antenna_height_m="antenna"` (was `nonneg`; no upper bound before, none added).
- `usv.py`: `rf_antenna_height_m="antenna<=50"` (was `nonneg<=50`); new `OPTIONAL_KINDS = dict(iridium_antenna_height_m="pos<=50")`, applied in `load_platform`
  only when the file carries the key (the key stays optional, nothing reads it).
- `uas.py`: `ship_antenna_height_m="range:0.5:100"` (was `nonneg`): the mission schema's own range for the ship's antenna (`cafe/schemas/mission.json:37`),
  because this value is the ship's antenna wherever the mission names none and reaches `rf_margin` as `hr` (`stage1.ship_antenna_m`).
- `rf_margin` and `two_ray_loss_db` are NOT guarded (round 16 M-27 contract kept).

DECISIONS row text (number after 916 by batch G): "Round 17, M-6 (OD-4): a platform's RF antenna height is 0.1 m or above (`physics.ANTENNA_MIN_M`): the glider files'
`antenna_height_m`, the USV's `rf_antenna_height_m` (and at most 50), with a refusal that names the key and says below 0.1 m the two-ray model has no meaning
(the margin of an antenna at 0 m was a finite -43 dB at 5 km, +1.4 dB at 1 km, neither 'no link' nor an error); the UAS file's `ship_antenna_height_m` is 0.5 to 100
like the mission's `ship.antenna_height_m`; the USV's `iridium_antenna_height_m`, which no code reads, is checked (above 0, at most 50) when the file has it. The
shipped values (0.5, 0.3, 2.2, 10) load. The floor is a choice: 0.1 m is where the two-ray model is 12 to 16 dB off (M-5), the Slocum's 0.3 m must stay valid;
the lab may prefer 0.5 with a warning below it (QUESTIONS_FOR_LAB)."
CHANGELOG line: "Platform files: an RF antenna height below 0.1 m is refused (glider `antenna_height_m`, USV `rf_antenna_height_m`); the UAS file's `ship_antenna_height_m` must
be 0.5 to 100; the USV's `iridium_antenna_height_m` is checked (round 17, M-6)."
Sentences for batch G: PHYSICS 12.1 and the platform `why` strings: "A platform's RF antenna height is 0.1 m or above; below it the two-ray model has no
meaning (a height of 0 gave a finite margin of -43 dB at 5 km)." QUESTIONS_FOR_LAB sub-item: "Lowest RF antenna height a platform may have. Default 0.1 m
(refused below); 0.5 m with a warning below it is the other reading."
What could break and was checked: every place an antenna height is read or validated (grep of `antenna`): `stage1.py:134` (glider `antenna_height_m`), `:156` (USV
`rf_antenna_height_m`), `:294-297` (`ship_antenna_m`: mission value, else the UAS file's `ship_antenna_height_m`, else 10 m: the mission schema already forces
0.5 to 100, the platform fallback now has the same range), `:324` and `:420` (the UAS whip is ADDED to the deck height and altitude, so 0 stays harmless; exempt in the
class test), `missions/*.yaml` (`ship.antenna_height_m` 15), `platforms/*.yaml` (0.5, 0.3, 2.2, 10; `iridium_antenna_height_m` 2.0). No mission or platform key overrides
a platform parameter (`grep override` in config.py and the schema finds none), so there is no second path to a platform height. The table-listing test
`test_every_parameter_the_models_read_is_in_a_table` still holds (OPTIONAL is unchanged). Tests in other files that set heights bypass the loader (monkeypatched
`P["radio"]`, 20.0 and 10.0 are in range).
Side effect to know: `usv.py`'s table cache key (`_digest`) hashes the bytes of `usv.py`, so the USV tables are rebuilt once on the first run after this merge (same
values; physics is unchanged). Any edit of `usv.py` does this.
Tests (all in `tests/test_round17_d.py`): `test_m6_an_rf_antenna_height_below_a_tenth_of_a_metre_is_refused_naming_the_key_and_why` (3 platforms x 6 values: 0, 0.0,
1e-9, 0.05, 0.0999, -0.3), `test_m6_the_floor_itself_and_the_shipped_heights_load` (0.1, 0.3, 0.5, 2.2), `test_m6_the_floor_is_a_tenth_of_a_metre`,
`test_m6_the_shipped_platforms_still_load_with_the_heights_the_demo_uses`, `test_m6_the_usv_rf_height_keeps_its_upper_bound`,
`test_m6_the_ship_antenna_of_the_uas_platform_is_the_mission_schemas_half_metre_to_a_hundred` (0, 0.2, 0.49, 0.5, 10, 100, 100.5),
`test_m6_the_iridium_antenna_height_nothing_reads_is_checked_when_the_file_has_it`, `test_m6_a_usv_file_without_the_iridium_antenna_still_loads`,
`test_m6_every_antenna_height_a_platform_table_lists_refuses_zero_except_the_one_added_to_the_body_height` (the class: a new `*antenna*` key with a lax kind fails it).

## M-5: low antennas under the -1 reflection (OD-3: documented, physics NOT changed)

Change: docstring of `comms.two_ray_curved_db` only (a paragraph "LOW ANTENNAS (round 17, M-5 ...)" with the measured band, the mechanism, the conservative
direction, why it is not changed, and the floor of M-6).
Measured here (not copied): flat-earth two-ray with the Fresnel coefficient of sea water (eps_c 72.8 - j118.9 at 915 MHz, vertical polarisation), other antenna 15 m,
Hs 0, d = 300 m to 12 km, 400 points, model (`two_ray_loss_db`) minus Fresnel, min / median / max, run on orca (job r17d_1): 2.2 m -3.3 / -0.4 / +0.2;
0.5 m -2.9 / +1.3 / +2.2; 0.3 m +1.2 / +5.1 / +6.0; 0.1 m +11.4 / +15.1 / +16.0. These equal the merge's figures. `rf_margin(5e3, ht, 10, 0.5)` for
ht = 0: -43.17 dB, 1e-9: -43.17, 0.1: +3.97, 0.3: +13.30 (and at 1 km +1.42 for 0, +31.95 for 0.1).
The independent reference is the Fresnel coefficient written in the test (`fresnel_loss_db`); only `C0` is taken from the code. Reviewer B's parabolic-equation figures
are quoted in the docstring as B's, and "a field of about 0.03 of free space" is B's estimate, marked "not re-measured".
DECISIONS row: "Round 17, M-5 (OD-3): the two-ray model's reflection coefficient of -1 is kept (917 to 920 stand); its error band for low antennas is stated in
`two_ray_curved_db`'s docstring: against the Fresnel coefficient of the assumed sea the loss is overstated by +1.2 to +6.0 dB (median 5.1) at 0.3 m (the Slocum's
antenna) and +11.4 to +16.0 dB at 0.1 m, -2.9 to +2.2 at 0.5 m, -3.3 to +0.2 at 2.2 m (flat earth, other antenna 15 m, 300 m to 12 km): the margin of an RF link to
a low antenna is too low (a GO can show as MARGINAL or NO-GO), never too high. `tests/test_round17_d.py` holds the figures (a change of the physics must update
them). The limitation row and the link-card note are batches B and A." (Use the 913 to 916 numbers as they stand in DECISIONS.)
CHANGELOG line: "Round 17, M-5: the error band of the two-ray model for antennas below 0.5 m is documented and tested (no physics change)."
Sentence for PHYSICS 12.1 and CREDIBILITY (batch G; batch B owns the L-row text "RF links to an antenna below 0.5 m: the loss is overstated, by 5 dB at the Slocum's
0.3 m"): the four rows of the table above.
What could break: nothing (a docstring). Sibling site: `two_ray_loss_db`'s plane-earth branch (`FLAT_A`) has the same -1, so the band applies to it too (the
test runs `two_ray_loss_db`, which includes it).
Tests: `test_m5_the_loss_of_a_low_antenna_is_overstated_by_the_documented_band` (4 heights; bounds = the measured range widened by 0.2 dB; for 0.3 m and 0.1 m also
"positive everywhere"), `test_m5_the_docstring_of_the_two_ray_model_states_the_low_antenna_band_and_the_floor`. HONEST NOTE: the band test PASSES on the unfixed
code (no physics change, so it must); it holds the documented figures against a later change. Only the docstring test fails before.

## M-16: `_run_bellhop` and `PATH`

Change: `if (bd := _bellhop_dir()) is not None and bd not in PATH.split(...)` (comms.py, one line).
DECISIONS row: "Round 17, M-16: `_run_bellhop` puts the Bellhop directory on PATH once (row 429) only when there is one; with no Bellhop it left PATH unchanged
only by accident of a RuntimeError, and wrote the text 'None' into it once per call before this fix." CHANGELOG: "`_run_bellhop` no longer puts 'None' on PATH when
there is no Bellhop (round 17, M-16)." Row 429 stays true for the found case. Unreachable from the pipeline (both callers test `bellhop_available()`).
Test: `test_m16_a_missing_bellhop_leaves_path_as_it_was_and_never_writes_none_into_it` (two calls, PATH equal to the start each time).

## M-20: the P.526 constants and the sea constants

Tests only (the code is not changed). Each reference is a closed form written in the test from the recommendation (F, G, K_V, beta, X, Y; `ref_f`, `ref_g`,
`ref_beyond`), compared at 1e-9 dB; the formulas are exact reproductions, so no "within the Fock tolerance" number is pinned:
- (a) `test_m20_the_distance_function_is_the_recommendations_in_both_branches` (X = 0.05, 0.5, 1.0, 1.5, 1.599, 1.6, 1.7, 3, 8) and
  `test_m20_the_two_branches_of_the_distance_function_meet_at_1_6` (the fits meet to 7e-6 dB at X = 1.6: that is the measured gap, so its tolerance is 1e-4);
- (b)+(e) `test_m20_the_diffraction_field_beyond_the_horizon_is_the_recommendations_over_the_sea` (6 cases: the demo's UAS and USV at 915 MHz, 0.1 m antennas where G is on
  its floor, 3 MHz where K is 2.3 and beta 0.44), `test_m20_fresh_water_at_5_ghz_goes_through_the_same_chain` (eps 80, sigma 0.01, by monkeypatching the module
  constants), `test_m20_the_sea_constants_are_the_assumed_sea_of_the_note`, `test_m20_the_floor_of_the_height_gain_binds_in_the_cases_that_say_so` (checks the premise:
  the 0.1 m case is 5 dB under the floor);
- (c) `test_m20_the_height_gain_switches_branch_above_b_of_2_and_floors_at_2_plus_20_log_k` (B = 1e-4 on the floor, 0.5, 1.9, 2.0, 2.0000001, 2.1, 2.9, 3.5, 10);
- (d) `test_m20_the_diffraction_loss_beyond_the_horizon_is_never_negative_even_where_the_formula_is`: at 915 MHz over the sea no sampled beyond-horizon point is negative, so
  the case that exercises `np.maximum(beyond, 0.0)` is 3 MHz, 20 m antennas, 1.01 times the horizon, where -(F+G+G) is -37 dB (asserted as the premise) and the function
  returns exactly 0.0. A 3 MHz sea path is outside the demo; the test is about the function's stated contract ("never negative"), not about HF.
Mutants (driver `mut.py` run in a detached worktree `cafe-r17d-mut` synced to `pm_r17dm`, the new test file alone, each mutant one edit of the final `comms.py`,
`__pycache__` of the physics directory removed before each run, mtime refreshed): control rc=0, 0 failed. Killed (rc=1, tests failed): A-7a `** 1.425` -> `** 1.4` (10
tests), A-7b `k = 0.36 *` -> `0.30 *` (9), B-3 `0.36` -> `0.5` (8), A-7c remove `np.maximum(beyond, 0.0)` (1: the never-negative test only), B-3a sea constants `72.8, 6.05` ->
`20.0, 0.01` (10), B-3b `b > 2.0` -> `b > 3.0` (4), B-3c floor `2 + 20 log K` -> `-60` (9). All seven mutants of the finding's list are killed, the control green.
DECISIONS row: "Round 17, M-20: the P.526 distance function (both branches, the exponent 1.425), the height-gain function (the branch at B = 2, the floor 2 + 20 log K), K, beta, X, Y and the sea constants are pinned by closed forms written from the recommendation in `tests/test_round17_d.py` (1e-9 dB), and the never-negative contract of `smooth_earth_diffraction_db` beyond the horizon by a 3 MHz case where the formula alone is -37 dB; six mutants that survived round 16's tests are killed (tests only; the five-pairs Fock check of DECISIONS 913 stays the check of the whole chain)." CHANGELOG: "Tests pin the P.526 and sea constants of the smooth-earth diffraction loss (round 17, M-20)."

## Fail-before

M-6, M-16, the docstring test of M-5: `tests/test_round17_d.py` copied into a detached worktree at the base commit 433429e (`cafe-r17d-base`, synced to `pm_r17dbase`, log
`r17dbase_1`): rc=1, 83 tests, 53 passed and 30 failed. The 30 are: M-16 (1), M-6 refusal rows (18: 0, 0.0, 1e-9, 0.05, 0.0999, -0.3 for three platforms; the -0.3 rows fail
on the message, the old kind refused it too), `test_m6_the_floor_is_a_tenth_of_a_metre`, the USV upper-bound test (message), the UAS ship rows 0, 0.2, 0.49, 100.5 (4), the Iridium
rows 0, -1.0, 51 (3), the class test, the docstring test. The 53 passing on base are the loads (the floor itself and the shipped values), M-20 and the band test of M-5
(they hold the unchanged code; M-20 fails on its mutants instead). On the fixed tree: log `r17d_9`, rc=0, 83 passed.

## Runs on the final tree (orca, host cafe-orca, proot, 2 CPUs each; the code tree is commit c2e47f0)

| job log | files | rc | passed |
|---|---|---|---|
| r17d_9 | tests/test_round17_d.py | 0 | 83 |
| r17d_10 | tests/test_comms.py, test_comms_exact.py, test_round16_a.py, test_round17_d.py, test_glider.py, test_platform_required.py, test_audit.py | 0 | 618 |
| r17d2_1 | tests/test_usv.py, test_uas.py | 0 | 254 |
| r17d3_1 | tests/test_config.py, test_credibility.py, test_stats_exact.py, test_config_docs.py, test_runners.py, test_stage1.py | 0 | 1283 |
| r17d_8 | `python -m ruff check cafe/pm tests` | 0 | All checks passed |
| r17d_11 | `python -m mypy cafe/pm` | 0 | no issues in 55 source files |

(No failures, no skips; the counts are the result characters of the progress lines only. `test_audit.py` runs the banned-token and commented-code scan over the tree
including my files.)

## No demo number moves

No physics function changed: `comms.py` has one condition changed (the PATH branch of `_run_bellhop`, which only runs with a Bellhop and is not in the demo) and a docstring;
`glider.py`, `usv.py`, `uas.py` and `physics/__init__.py` changed only the validation tables. The shipped values the demo reads (Slocum 0.3 m, Seaglider 0.5 m, USV 2.2 m,
ship 15 m by the mission, 10 m platform fallback) all pass the new floors, tested in `test_m6_the_shipped_platforms_still_load_with_the_heights_the_demo_uses`; the pin files
that hold demo numbers (test_stage1, test_credibility, test_config, test_stats_exact) pass. No demo or gate was run (not allowed). Only the USV table cache key changes (see M-6).

## Not verified

- Coverage: no coverage run (a gate). The new physics lines are executed by the new tests (the `antenna` rule and its message, the HINTS, `OPTIONAL_KINDS`, both outcomes of the
  PATH condition), but 100 % on physics was not measured.
- The full suite and the demo were not run. Test files other than the ones listed (for example test_pipeline, test_hangar, test_whatif, test_report) were not run on this tree;
  none loads a platform with a height under 0.1 m (grep), but that is a grep, not a run.
- B's parabolic-equation figures and the 0.03 field floor are B's and were not re-run; my check is the flat-earth Fresnel two-ray (a bound without a surface wave).
- Whether the lab prefers a floor of 0.5 m with a warning (OD-4 alternative) is open; it is in the QUESTIONS_FOR_LAB sentence above.
- The upper bound of the glider antenna height is still none (a finite number); only the floor was added.

