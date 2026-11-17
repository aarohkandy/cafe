# Round 18, batch B handback: M-3 (the low-antenna band by pair) and the A-1 tests of M-16

Branch `r18-b` (cut from d69be8f), worktree `cafe-r18b`, orca dirs `pm_r18b`, `pm_r18b_base` (fail-before, detached worktree at d69be8f, removed locally), `pm_r18b_lint`, `pm_r18b_fin`. OD-3 taken as the default: no physics change, no loader refusal (`config.py` untouched), the band stated by pair, "never too high" and "not affected" removed.

Files changed (code commit 9988da8): `cafe/pm/physics/comms.py` (docstring of `two_ray_curved_db` only; the diff has no code line), `cafe/pm/credibility.py` (L23 text only: id, factors and `where` unchanged), `tests/test_round18_b.py` (new), and two pins that moved: `tests/test_round17_b.py` (L23's start and one phrase) and `tests/test_round17_d.py` (the docstring pin "12 to 16 dB at 0.1 m" is "11 to 16 dB at 0.1 m": the measured minimum is +11.4, so "12" was wrong; and a comment that said "never too high"). No document is edited; `review/round_18/handbacks/r18_B_docs.patch` is the `docs/CREDIBILITY.md` L23 row and the `docs/PHYSICS.md` 12.1 "Low antennas" paragraph (`git apply --check` passes on this branch; `tests/test_config_docs.py::test_credibility_doc_limitation_table_is_the_code_s_list` compares the doc's L23 text to the code character for character, so it FAILS without the patch: r18b_nodoc, 1 failed, and passes with it). The measuring and mutant scripts are in `review/round_18/handbacks/r18_B_x/` (`pairs.py`, `mut.py`, `cred.py`, `neg2.py`).

## M-3: the band is of the pair of heights

The figures (every one computed on orca by `r18_B_x/pairs.py`, logs `r18b_pairs`, `r18b_pairs2`, and held by the new tests; my own flat-earth Fresnel two-ray with the vertical-polarisation coefficient, eps_c 72.8 - j118.9, 915 MHz, Hs 0, 400 points from d0 to the pair's radio horizon, model = `two_ray_loss_db`, the loss `rf_margin` uses), model minus Fresnel, min / median / max dB:

| pair (m) | range | min / median / max |
|---|---|---|
| 15 with 2.2 | 300 m to 12 km | -3.3 / -0.4 / +0.2 |
| 15 with 0.5 | 300 m to 12 km | -2.9 / +1.3 / +2.2 (from 200 m the minimum is -5.0) |
| 15 with 0.3 | 300 m to 12 km | +1.2 / +5.1 / +6.0 |
| 15 with 0.1 | 300 m to 12 km | +11.4 / +15.1 / +16.0 |
| 0.5 with 0.3 (Seaglider, Slocum) | 200 m to horizon (5.2 km) | +9.0 / +9.3 / +9.3 |
| 0.3 with 0.3 (two Slocums) | 200 m to horizon (4.5 km) | +11.1 / +11.4 / +11.4 |
| 0.5 with 0.5 (two Seagliders) | 200 m to horizon (5.8 km) | +6.3 / +6.7 / +6.7 |
| 2.2 with 0.3 | 200 m to horizon (8.4 km) | +5.1 / +6.2 / +6.2 |
| 2.2 with 0.5 | 200 m to horizon (9.0 km) | +1.4 / +2.6 / +2.7 |
| 2.2 with 2.2 | 200 m to 12 km | -3.0 / -1.2 / +1.6 |

The first four rows are round 17's (unchanged to 0.1 dB); the 0.5 m minimum from 200 m, and the 2.2 m-partner rows, are new. The both-low rows equal reviewer B's (+9.0 / +9.3 / +9.3, +11.1 / +11.4 / +11.4, +6.3 / +6.7 / +6.7) and the merge's. 0.1 with 0.1, 0.1 with 2.2 and 0.3 with 15 from 200 m were computed too and not printed (a 0.1 m pair is outside what ships). Reviewer B's parabolic equation figures (15 m partner: -3.9 / -1.5 / -0.8 at 2.2 m, -3.1 / +0.3 / +1.2 at 0.5 m, +0.5 / +4.1 / +5.1 at 0.3 m, +10.6 / +14.2 / +15.1 at 0.1 m; Slocum with a 2.2 m end -0.1 / +3.7 / +4.7) are quoted as "reviewer's, not re-run".

What changed:
- L23 (`credibility.py`): now starts "RF links to a low antenna, an antenna below 0.5 m or the USV's 2.2 m whip:", says the error is of the pair of heights and gives the by-pair figures (about 5 dB at the Slocum's 0.3 m with a partner of 2.2 m or more, 6 to 11 dB when both ends are 0.5 m or lower with 7 / 9 / 11 dB for two Seagliders / Seaglider with Slocum / two Slocums, 11 to 16 dB at 0.1 m), says the loss is overstated and the margin too low for an antenna below 0.5 m (a GO can show as MARGINAL or NO-GO), and that at 0.5 m and 2.2 m with a 2.2 m or 15 m partner the model is within 3.3 dB and at worst understates the loss, so the margin there, the USV whip's included, can be too high. "never too high", "not affected", "conservative" are gone.
- Docstring of `two_ray_curved_db`: the LOW ANTENNAS paragraph is rewritten with the same table, the sign statement, the "Not run" list (a PE for two low ends, d below 200 m, Hs above 0) and a sentence saying round 17's reading held only for the Slocum's 0.3 m with a 15 m partner. The figures the old text carried that other tests pin (`+1.2 / +5.1 / +6.0 at 0.3 m`, `+11.4 / +15.1 / +16.0`, `about 5 dB for an RF link to the Slocum's 0.3 m`) are kept.

Tests (`tests/test_round18_b.py`):
- `test_r18_m3_the_docstring_figures_of_every_pair_are_the_measured_ones[pair0..pair9]`: recomputes each row above to 0.1 dB with `two_ray_loss_db` and the Fresnel two-ray of `tests/test_round17_d.py`, and asserts the printed "min / median / max" string is in the docstring.
- `test_r18_m3_l23_states_the_band_by_pair_and_drops_never_too_high_and_not_affected`, `test_r18_m3_l23_medians_are_those_of_the_pairs_it_names`, `test_r18_m3_the_docstring_has_no_conservative_for_all_and_no_unaffected_shipped_antenna`.
- `test_r18_m3_both_ends_low_is_overstated_everywhere_and_the_sign_flips_at_0_5_to_2_2_m` (the sign statement from the numbers), `test_r18_m3_the_shipped_antennas_are_the_ones_the_pairs_name` (0.3 / 0.5 / 2.2 m read from the platform files), `test_r18_m3_the_loader_accepts_an_rf_link_whose_two_ends_are_gliders` (the premise of the 6 to 11 dB).

## M-16 (A-1): five mutants of `smooth_earth_diffraction_db`

Tests, against a scalar P.452 interpolation written in the test (`ref_inside`, with `ref_beyond` of round 17's file; no number pinned that is only "within the Fock tolerance": equality to 1e-9 dB with the formulas):
- `test_r18_m16_a1_inside_the_horizon_the_loss_is_the_p452_interpolation_to_1e_9_db` (5 pairs x fractions 0.3, 0.6, 0.9, 0.998 of the horizon),
- `test_r18_m16_a1_just_beyond_the_horizon_is_the_diffraction_field_and_the_horizon_is_sqrt_2a_times_the_heights` (fractions 1.002, 1.004, 1.02, 1.3),
- `test_r18_m16_a1_the_switch_is_at_the_horizon_and_the_two_sides_differ_by_what_the_formulas_say` (0.9995 and 1.0005),
- `test_r18_m16_a1_a_diffraction_gain_inside_the_horizon_gives_a_loss_of_zero_not_a_negative_one` (two 0.3 m antennas 8, 10 and 14 m apart: the a_em diffraction is a gain of 3 to 8 dB, the factor 1 - h_se/h_req is above 0.2, so without the clip the loss was negative; found by a grid scan, `neg2.py`: 26 of the 134 negative a_em values in the grid have the factor positive, and the ones I looked at are for low antennas at distances below 20 m),
- `test_r18_m16_a1_the_inside_branch_is_not_all_zero_for_the_pairs_pinned` (guards the pins from the zero of `h_se > h_req`).

Mutant check (`r18_B_x/mut.py`, log `r18b_mut1`: each mutation is applied by an exact-string replace on the orca copy of `comms.py`, the m16 tests run with `-x`, the file restored; the control first): control rc=0; C23 (`250.0` as `249.0`) KILLED; C24 (`17.456` as `17.5`) KILLED; C28 (the `np.maximum(..., 0.0)` around the a_em diffraction removed) KILLED by the negative-case test; C30 (`np.sqrt(2.01 * a_km)`) KILLED; C32 (`hr * 1.01` in `d_los`) KILLED. I did not re-run the five against the files named in the finding (`tests/test_round17_d.py tests/test_round16_a.py`) to see them survive; the merge did that for other mutants and the reviewer for these.

## Fail-before and the runs (orca, proot, 2 CPUs; logs in `~/cafe-worker/logs/` on cafe-orca)

- `r18b_base1`: `tests/test_round18_b.py` on the unfixed tree (detached worktree at d69be8f, dir `pm_r18b_base`): 9 failed, 56 passed, rc=1. The 9: six `the_docstring_figures..` rows (the six pairs the old docstring does not carry), `l23_states_the_band..`, `l23_medians..`, `the_docstring_has_no_conservative..`. The rest pass on the unfixed code on purpose: the four 15 m rows were already measured (the pair test also checks they are in the docstring: they were), the premise tests (platform heights, loader), the sign test (a statement about the model, unchanged), and all M-16 tests (tests of unchanged code, whose proof is the mutant run).
- `r18b_1` (fixed tree, new file only): 65 passed, rc=0.
- `r18b_fin1` (final tree, docs patch applied for the run, then reverted in the worktree): `tests/test_round18_b.py test_round17_b.py test_round17_d.py test_round17_m.py test_round17_a.py test_credibility.py test_config_docs.py test_comms.py test_comms_exact.py test_round16_a.py`: 529 passed, 0 failed, rc=0 (the code, tests and docs patch of the final commit 9988da8; counted on the progress lines only).
- `r18b_2` (wider set on the code of 9988da8 minus the ruff-only edits: `tests/test_round18_b.py test_round17_b.py test_round17_d.py test_round17_m.py test_round17_a.py test_credibility.py test_config_docs.py test_comms.py test_comms_exact.py test_round16_a.py test_report.py test_round16_report.py`, docs patch applied): 797 passed, 0 failed, rc=0 (a run on the tree before the two ruff-only edits to my test files, which `r18b_fin1` covers).
- `ruff check cafe/pm tests`: `r18b_ruff3` rc=0, "All checks passed!" (two earlier runs found a 166-column line and a `zip` without `strict=`, both in my files, fixed). `mypy cafe/pm`: `r18b_mypy2` rc=0, "Success: no issues found in 55 source files". `audit.banned()` (`r18_B_x`-style script, `r18b_ban`): 0 hits. `python -m cafe.pm audit --code-only` (`r18b_audit1`): its one problem is "mutation: no stored result at docs/mutation.json" (the record is not in a clean checkout; it is not a scan hit).
- Coverage: no `physics`, `stats` or `env` line changed (docstring only in `comms.py`); not re-measured.

Test files that import or pin what I changed, all run above: `test_round18_b.py`, `test_round17_b.py`, `test_round17_d.py`, `test_round17_m.py` (the link card names L23), `test_round17_a.py` (`_low_antenna_note` `startswith`), `test_credibility.py` (the L-id list), `test_config_docs.py`, `test_comms.py`, `test_comms_exact.py`, `test_round16_a.py` (the Fock tests of `smooth_earth_diffraction_db`), `test_report.py`, `test_round16_report.py`.

## What moves on the credibility page against q18

Read-only `credibility.build` on a copy of q18 (`cp -r` of `/data/runs/q18` into `pm_r18b_lint/runs/q18copy`, `r18_B_x/cred.py`, log `r18b_cred`; nothing written in `/data/runs/q18`), compared with q18's stored `credibility.json`: no factor level and no count moves. Differences, six: L23's text (the one change of mine; "not affected" is gone from the page, no "never too high" on it), and five that are not from this change: the evidence path (`/data/runs/q18/...` against `runs/q18copy/...`), the run name, "8 of 9 stage ledgers present" becomes "9 of 9" and "8 ledgers" becomes "9" (the stored file was written before the report stage's own ledger existed), "67 test files present" becomes "68" (my new test file). The count of limitations stays (L23 is rewritten, not added); `DEMO_DIGEST` and every number are untouched.

## Proposed DECISIONS row (the documents batch numbers it after 951; amends 922 and 926, and the "never too high" of 926)

"The error of the two-ray -1 reflection for a low antenna is stated by PAIR of antenna heights, not as a property of one antenna (round 18, M-3, owner decision OD-3 default: no physics change, no loader refusal; rows 913 to 916 and 944 stand). Against a flat-earth Fresnel two-ray with the assumed sea (eps_c 72.8 - j118.9, 915 MHz, Hs 0; a bound: no surface wave), the model's loss minus the Fresnel loss, min / median / max in dB, is: 15 m partner (300 m to 12 km) -3.3 / -0.4 / +0.2 at 2.2 m, -2.9 / +1.3 / +2.2 at 0.5 m, +1.2 / +5.1 / +6.0 at 0.3 m, +11.4 / +15.1 / +16.0 at 0.1 m; both ends low (200 m to the pair's radio horizon) Seaglider 0.5 m with Slocum 0.3 m +9.0 / +9.3 / +9.3, two Slocums +11.1 / +11.4 / +11.4, two Seagliders +6.3 / +6.7 / +6.7; 2.2 m partner +5.1 / +6.2 / +6.2 at 0.3 m, +1.4 / +2.6 / +2.7 at 0.5 m, and -3.0 / -1.2 / +1.6 for two 2.2 m ends (tests/test_round18_b.py recomputes every row to 0.1 dB). The loss is overstated, and a GO can show as MARGINAL or NO-GO, for an antenna below 0.5 m: about 5 dB for the Slocum with the USV (1 to 6), 6 to 11 dB when both ends are 0.5 m or lower, 11 to 16 dB at 0.1 m; at 0.5 m and 2.2 m with a 2.2 m or 15 m partner the model is within 3.3 dB and at worst understates the loss, so a margin there, the USV whip's included, can be too high. Row 926's 'too low, never too high' and the L23 text 'the shipped UAS and USV antennas are not affected' were wrong for those pairs and are replaced. Not measured: a parabolic equation for two low ends, d below 200 m, Hs above 0 (reviewer B's PE for a 15 m partner agrees with the Fresnel rows to about 1 dB and is not re-run). The A-1 mutants of `smooth_earth_diffraction_db` (the constants 250 and 17.456, the clip of the a_em diffraction, the horizon constant and its `hr` term) are held by a scalar P.452 reference to 1e-9 dB."

CHANGELOG line: "Credibility and comms: the error band of the two-ray -1 reflection is stated by pair of antenna heights (L23, `two_ray_curved_db`): 6 to 11 dB overstated when both ends are 0.5 m or lower, about 5 dB at the Slocum with the USV, up to 3.3 dB understated at 0.5 m and 2.2 m; 'never too high' and 'not affected' removed; five surviving mutants of the P.452 interpolation held (round 18, M-3 and M-16)."

Document text: the patch above (`docs/CREDIBILITY.md` L23 row, both columns; `docs/PHYSICS.md` 12.1 "Low antennas" paragraph). Also for the documents batch: DECISIONS row 926 (line 979) says "too low, never too high": amend by pointer to the new row; QUESTIONS_FOR_LAB: a sub-item under OD-3 with its default ("no loader refusal of an RF link whose two ends are both 0.5 m or lower; the page states the 6 to 11 dB").

## Needed from other batches (not edited here)

1. Batch A, `report._low_antenna_note` (cafe/pm/report.py:724-745): its sentence still says the overstatement is "by about 1 to 6 dB at 0.3 m and 11 to 16 dB at 0.1 m" and "this margin is conservative", true only for a 2.2 m or higher partner. With the by-pair figures it should (a) count the ends, and (b) use the threshold "0.5 m or lower" for the both-ends case: with `RF_LOW_ANTENNA_M = 0.5` and a strict "below", a Seaglider (0.5 m) with a Slocum (0.3 m) is "one low end" and two Seagliders (0.5 m, 6.7 dB median overstated) get no note at all; a USV (2.2 m) with a Seaglider is +1.4 to +2.7 dB and needs no "6 to 11". Suggested wording for both ends 0.5 m or lower: "... Both ends are 0.5 m or lower: the two-ray model overstates the loss by 6 to 11 dB against a Fresnel two-ray (a Seaglider with a Slocum about 9 dB, two Slocums about 11, two Seagliders about 7): this margin is conservative and a GO can show as MARGINAL or NO-GO (CREDIBILITY, limitation L23)", and for one low end with a 2.2 m or higher partner "by about 5 dB at 0.3 m (1 to 6) and 11 to 16 dB at 0.1 m". The start "An end of this RF link has an antenna below 0.5 m:" can stay as the tests pin it.
2. `cafe/pm/physics/__init__.py:8` (`ANTENNA_MIN_M`'s comment): "12 to 16 dB too much loss at 0.1 m" should read "11 to 16 dB" (the measured minimum is +11.4). A comment, not my file; not edited.
3. Test of M-3's last foresight line ("add one link with both ends gliders to the test" through stage 1): not done here; the batch list gives me `comms`/`credibility` only. The loader premise is tested (`test_r18_m3_the_loader_accepts_an_rf_link_whose_two_ends_are_gliders`); a stage-1 run of such a link is not.

## Not verified

- No PE was run (reviewer B's PE figures are quoted as the reviewer's); the Fresnel two-ray has no surface wave, so every figure is a bound (stated in L23, the docstring and the patch). Distances below 200 m and Hs above 0 are not measured.
- The five A-1 mutants were not run against the existing files named in the finding; only against my tests (killed) with the control (green).
- Coverage and the full suite were not run (the lead's gate); the mutation score of `comms.py` was not re-measured.
- The new tests recompute the Fresnel pairs at 400 points; they depend on `two_ray_loss_db` and on the helper `fresnel_loss_db` of `tests/test_round17_d.py` (imported, so a change of that helper moves both files together).

## Left on orca (all inside `~/cafe-worker`, mine)

Directories `cafe/pm_r18b`, `cafe/pm_r18b_base`, `cafe/pm_r18b_lint` (holding `runs/q18copy`, 22 MB, removed at the end of this task, see below), `cafe/pm_r18b_fin`; job markers `cafe/.pmx.job.pm_r18b*`; logs `logs/r18b_*.log` (pairs, pairs2, neg, neg2, neg3, 1, base1, mut1, 2, fin1, nodoc, ruff, ruff2, ruff3, mypy, mypy2, audit1, ban, cred). Nothing in `/tmp` on orca, no shared store, no `/data/runs/q18` write, no stash, no push. Locally: the scratch worktree `cafe-r18b-base` was removed.
