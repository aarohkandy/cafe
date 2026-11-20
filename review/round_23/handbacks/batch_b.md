# Round 23, batch B hand-back: report, credibility, RF texts and their documents

Branch r23-b, base f62defd. The diff is net-negative in claims: no new printed number, constant, key or option. Every change is a deleted clause or a reworded one, plus one one-expression code change (`band_figures`, `-0.0`). OD-1 (a) and OD-2 (a) taken as written.

## 1. What changed, by finding

| finding | change (file) | evidence it holds |
|---|---|---|
| M-1 / S-1 | `IRIDIUM_NOTE` loses ", so a member needing hundreds of samples cannot miss the required fraction by chance" (report.py); PHYSICS 849 loses the parenthesis "(P(fail) below 1e-90 ...)" | `tests/test_round23_b.py::test_m1_*` (constant text, any `required_fraction`; no "cannot", "by chance", "never", "hundreds", "1e-90") |
| M-2 / S-3 / S-4 | `credibility.SAMPLING_NOTE` is now "These are figures of the 400 sampled ranges" (the worst-case and finer-sampling hedge is deleted); the card's tail loses "at a wave height of 1 to 3 m these figures are different (L23); " (the head names Hs 0); L23 cell regenerated; QUESTIONS 20a, PHYSICS 811/817 follow | `test_m2_no_rf_card_over_the_height_grid_*`: every pair of the 22 heights 0.1 to 1,000 m prints "400 sampled ranges" and none of "worst", "larger", "finer", "null", "different", "wave height of 1 to 3 m" |
| M-4 / S-26 / S-28 | "up to 7.6 dB", "within about 8 dB at a peak", "7.5 dB lower to 34.7 dB higher" and "no sample changed its sign" deleted from the `two_ray_curved_db` docstring, CREDIBILITY (limitation row), QUESTIONS 12a, PHYSICS 819; said instead "the margin differs from a Fresnel two-ray in either direction; the card and L23 print the median and the counts for the link's own pair of heights". The "7.4 dB lower to 23.6 dB higher at Hs 0.5 m" (and the Hs 1.5 pair beside it) stay, scoped "on that one grid". `two_ray_loss_db` docstring (S-28): the figures for a 5 cm sampling (1.0, 29, 34 dB) and for Hs 1 m (2.4 dB) are deleted (not re-measured); the 1 m-sampling figures (0.8, 26, 20 dB, Hs 3 m 0.3 dB) stay because `tests/test_comms.py::test_r8_m49` recomputes them (26 to 0.5 dB, 20 to 0.5 dB, the other two as bounds), and PHYSICS 12.1 carries them (pinned by `tests/test_config_docs.py`) | `test_m4_*` over the three documents and the docstring |
| M-5 | stability figures (S-20), "extremes keep growing" (S-21), the percentile and 5.2 / 54.1 dB figures (S-23) and the "nulls out of both curves" parenthesis (S-24) deleted from the comms docstring, PHYSICS 817, QUESTIONS 20a. L23: platform names gone for the ten generic pairs (S-8), "it does not stop at any height" gone (S-6), "the same Fresnel two-ray" now says "(with the Ament roughness factor in its reflection coefficient)" (S-25 words), the demo paragraph names its own heights ("the demo's USV whip (2.2 m) and ship mast (15 m) ... lowest (18.1 m) and highest (108.1 m) leg"). `LOW_ANTENNA_NAMES` deleted (no other user). `_end_heights` docstring and PHYSICS 817: the record holds the deck height as `alt`. `band_figures`: `round(med, 1) + 0.0` (no "-0.0") | `test_m5_*`, `test_m5_a_median_that_rounds_to_zero_*` (grid -30 to +30 dB step 0.01 plus the boundaries: equals the old format except where the old one printed "-0.0") |
| S-12 | `certify_statement` of an excluded P(fail): "... (lower 95 % bound 0.xx)." (the clause "no number of members certifies it" deleted); CREDIBILITY 66, PHYSICS 892 follow | `test_s12_*` |
| S-14 | `report._attitude_note`: "The controller clamps the commanded tilt at 35 deg, below the 42 deg attitude exceedance, so the UAS verdict rests on ..." (was "Attitude exceedance cannot fire in this controller model (the tilt clamp ...)"); PHYSICS 756 says what the code does and the 96 of 96 q2 sorties | `test_s14_*`: 7 (clamp, exceedance) pairs including equal and reversed, both tails: no "cannot"; equal or above prints the "can fire" sentence |
| S-15 | L17 text: "the UAS controller clamps the commanded tilt at 35 deg, below the 42 deg of attitude exceedance" (credibility.py, CREDIBILITY 143; the same text is in `tests/test_credibility.py`) | `test_s15_*` (the numbers are tied to `config.load_platform("quad_uas")`) |
| S-16 | ", so the ensemble is pure physics" deleted (report.py plan block) | `test_s16_s17_*` |
| S-17 | report.py prints the basis as given, without the prefix "the plan is a lower bound:" and the docstring of `_timing` says "an estimate". The basis itself ("... so it is a lower bound") comes from budget.py: see hunks below | `test_s16_s17_*` |
| S-33 / S-40 | CREDIBILITY 203 loses "the Uncertainty factor cannot reach 3 there"; CREDIBILITY 156 "in exactly those" to "in those"; **sibling found**: the Uncertainty rule (`credibility.RULES["uncertainty"]`, printed, and CREDIBILITY 50) lost ", no member count decides it" and CREDIBILITY 201 lost "no member count decides it, and counting it held the factor at level 2 for a link nothing could certify" | `test_s33_s40_*`, `test_the_rules_text_is_the_documents_text` |
| S-8 | see M-5 | |
| S-6 | see M-5 | |

Rows of my batch not touched, and why: S-25's cells (KEEP: `tests/test_round19_b.py` recomputes them to 0.1 dB); S-23 and S-20 in RUNBOOK 190 are batch G's.

## 2. Decision text for DECISIONS (batch G numbers them; none needs the owner)

1. Round 23, M-1: `IRIDIUM_NOTE` says what the verdict restates and that it is no evidence; it says nothing of a member missing the required fraction. The 10.5 % of members that miss one of 865 moments at 0.05^3 per sample (merge's run) are why.
2. Round 23, M-2 (OD-1 a): `SAMPLING_NOTE` is "These are figures of the 400 sampled ranges"; the card has no sentence about a finer sampling, the worst case or a wave height; the card's head names Hs 0 and L23 prints the three pairs measured at Hs 1 to 3 m.
3. Round 23, M-4 (OD-2 a): no document or docstring prints a limit of the model's error against Fresnel; the named one-grid figure 7.4 dB lower to 23.6 dB higher at Hs 0.5 m stays.
4. Round 23, M-5: L23 names no platform for the ten generic pairs; the median prints "+0.0", never "-0.0".
5. Round 23, S-12, S-14 to S-17, S-33, S-40: the clauses "no number of members certifies it", "no member count decides it", "cannot fire", "pure physics" and the "cannot reach 3" clause are deleted; the attitude statement says what the controller does (clamps the commanded tilt at the platform's limit).

## 3. Document sentences that must change (batch G; I did not edit these)

- docs/RUNBOOK.md 190: delete "It prints no extreme and no limit: the largest and smallest differences of a sampled grid are the sampling's" only if it is to be kept as a statement about the demo's pair: keep "(the demo's pair of 2.2 m with 108.1 m is -10.8 to +39.2 dB at 400 points and -14.9 to +70.9 at 40,000)"; delete ", the median moved by at most 0.59 dB and each count by at most 0.046 of 400 between 400 and 40,000 ranges (190 pairs of heights, two frequencies)"; change ", not of the worst case (review round 22" to ") (review round 22" (the card now says only "These are figures of the 400 sampled ranges").
- docs/RUNBOOK.md 146: "the estimate is a lower bound and q8 ran 2.2 times over it" to "the estimate ran 2.2 times under the measured time at q8" (or delete "is a lower bound and"); S-17.
- STATUS.md 21: "the margin is up to 7.6 dB optimistic at interference peaks and conservative at nulls" to "the margin differs from a Fresnel two-ray in either direction (optimistic at interference peaks, conservative at nulls)".
- STATUS.md 177: delete ", so `plan.json` says `sitl_members` 0 for every budget and the ensemble is pure physics" to ", so `plan.json` says `sitl_members` 0 for every budget".
- DECISIONS 1057 and 1069 quote the deleted sentence ("not of the worst case"): leave as history, add the round 23 row.
- docs/RUNBOOK.md 189 and the other rows of batch G are not mine.

## 4. Hunks for other batches

- cafe/pm/budget.py:57-58 (batch D's file, S-17): `STAGE1_S_BASIS = (... "and worker start-up are not in it, so it is a lower bound")` to `... "and worker start-up are not in it")`; budget.py:603 "(a lower bound, not a schedule: plan.json stage1_s_basis)" to "(an estimate, not a schedule: plan.json stage1_s_basis)"; cafe/pm/pipeline.py:1593 "the planned cost is a lower bound (plan.json stage1_s_basis)" to "the planned cost is an estimate (plan.json stage1_s_basis)"; tests/test_budget.py:592-594 pin "lower bound" and "(a lower bound, not a schedule" (they change with it). Until that lands the report still prints the basis with "so it is a lower bound" inside it: my report change removed only the report's own prefix.
- cafe/pm/physics/rfband.py:12-13 (docstring, not in my file list): "(a finer sampling finds interference nulls and, for most pairs, larger differences)" is the same hedge (false for the pairs without a null): delete the parenthesis.
- Batch E's claims lint: `report.py` "forcing, not the worst case for the glider" (line ~1965, a different statement about forcing that the sweep did not list) and `report._chance` ("misses it by chance", S-19, KEEP) will be hits of the word list; allow-list them with those reasons. Nobody read S-19's number against `whatif._chance_miss` this round.
- Batch A's S-9 (`NOT_EXERCISED_NOTE`) is the sibling of "no number of members certifies it" that I deleted in report.py; mine is a different string.

## 5. Pins moved (each because the product's answer is now the intended one)

tests/test_round17_b.py (L23 start and the names of a pair), tests/test_round18_a.py (CASE: card tail and the note), tests/test_round18_x.py (L23 regex without names; the demo paragraph words), tests/test_round19_b.py (the card no longer says "these figures are different"; the PE11 names test rewritten: the names are gone, the two demo heights are still tied to their platform files and the old names are asserted absent), tests/test_round20_b.py (the demo card text), tests/test_round18_b.py and tests/test_round21_b.py (L23 start and the pair regex without names), tests/test_round22_b.py (`NOTE`; `figs` prints +0.0 like the product; the L23 test; **one assertion deleted**: `s40k[3] > abs(s400[0])` held the deleted sentence "a finer sampling can find a larger one" and passed only because the low pairs exceed their median by 0.01 dB; the 400-versus-40,000 tolerance assertions stay), tests/test_report.py (attitude statement, certify statement, the basis prefix, "pure physics"), tests/test_comms.py (the docstring test asserts "7.6 dB" absent instead of present), tests/test_config_docs.py (the four 7.6, 34.7 and "no sample changed" parts removed from the document-equals-docstring check; 7.4 / 23.6 stays), tests/test_credibility.py (L17 text).

## 6. q25 against q24

Expected, in the report only: every RF card (sampling note, tail), L23 (names, the Ament words, no "does not stop at any height", the demo paragraph), the Iridium card's note, the attitude statement of the UAS block, L17, the Uncertainty rule text, the plan block ("pure physics" and the basis prefix gone), a certify statement of an excluded verdict. A median that rounds to zero would print "+0.0" (none in the demo's cards: -0.2, -1.9, +0.1, -1.4, ...). No verdict, count, interval or margin moves; the medians and counts the cards print equal `rfband.pair_band`'s (held by tests/test_round22_b.py, unchanged).

## 7. What I tried as a hostile reviewer

- `band_figures`: -0.04999, -0.05, +-0.0, NaN, inf, a numpy float, a bool: same as the old format except where it printed "-0.0" (the test compares the old format over 6,001 medians).
- the card at every pair of 22 heights (both orders, as glider-class ends): the hedge words are absent; an RF link with a UAS end (the demo's card) still has its legs sentence before the tail.
- `_attitude_note`: clamp equal to the exceedance (prints "can fire"), clamp above, clamp 0.1, exceedance 89.9, no-profile tail, NaN is not reachable (`angle90` refuses it).
- L23: the regenerated cell is the code's text character for character (`test_m5_the_l23_cell_*`, and `test_credibility_doc_limitation_table_is_the_code_s_list`).
- the doc lints search for the deleted words in the whole of CREDIBILITY, PHYSICS and QUESTIONS (not only the lines I edited): they found two siblings I had not edited (CREDIBILITY 201's "no member count decides it", the rule at CREDIBILITY 50) and my own history sentences quoting the deleted words (rewritten).

## 8. Remaining claims on my files and the test that holds each

- every pair's median and counts: tests/test_round22_b.py (independent Fresnel reference, 105 pairs, both frequencies).
- "These are figures of the 400 sampled ranges": `cr.SAMPLING_NOTE == ...` and the card grid.
- "at none of the 400 sampled ranges is the loss 3 dB off" (S-5), "for any heights from 0.1 m to 1000 m" (S-7), "Level 4 is never awarded" (S-30), "every number links to a receipt" (S-31): unchanged, their tests are those of the sweep's KEEP column.
- The attitude statement: a statement of the code path (the commanded force is clamped, uas.py:372), not of the achieved tilt; 96 of 96 q2 sorties at 35.00 deg is stated as a measurement in PHYSICS 756 and the CREDIBILITY L17 row.
- L23 Hs cells: tests/test_round19_b.py recomputes to 0.1 dB.

## 9. Not verified / leftovers

**Orca jobs** (all on cafe-orca, proot, 2 CPUs, dirs pm_r23b, pm_r23b2, pm_r23bbase; scratch worktree `../cafe-r23b-base` at f62defd, removed at the end):
- before (f62defd + the new test file), job `r23b_base1`, rc=1: tests/test_round23_b.py 26 failed, 7 passed (the 7 are the L23-cell-equals-text test and the six `_attitude_note` cases of the unchanged "can fire" branch: clamp equal to or above the exceedance).
- after, job `r23b_6` (final tree), rc=0, 610 passed: tests/test_round23_b.py, test_round18_b.py, test_round21_b.py, test_comms.py, test_config_docs.py.
- after, job `r23b_4` (tree before the last two fixes), 875 passed 5 failed; the five were pins of the deleted text (test_round18_b x2, test_round21_b, test_comms, test_config_docs: all fixed, and re-run green in `r23b_6`). It covered tests/test_round23_b.py, 17_b, 16_report, 18_m, 17_m, 18_a, 17_a, 18_x, 18_b, 19_b, 20_b, 21_b, 22_b, test_comms, test_config_docs (all of which pass except those five).
- after, job `r23b_5` (tree before one fix), rc=1: tests/test_report.py and tests/test_credibility.py, 428 passed, 1 failed (`test_l1_the_uas_attitude_statement_...`, a second pin of the attitude sentence at the end of the test; fixed); re-run with the other five changed report tests and tests/test_round23_b.py on the final tree in `r23b_7`: rc=0, 39 passed.
- `ruff check cafe/pm tests`: 4 E501 findings, all in files this batch does not touch and that fail identically at f62defd (tests/test_round21_e.py:217, tests/test_round22_m.py:140, 148, 172); none in my files. `mypy cafe/pm`: no issues in 57 source files.
- An earlier job on a tree without a final pin fix (`r23b_1`, `r23b_2`, `r23b_3`) was killed by exact tmux session name or finished; no process of mine is running at the end.

**Not verified**
- tests/test_round17_b.py, test_round18_a.py, test_round18_x.py, test_round19_b.py, test_round20_b.py, test_round22_b.py, test_round16_report.py, test_round17_m.py, test_round17_a.py, test_round18_m.py and test_credibility.py passed in jobs `r23b_3`/`r23b_4`/`r23b_5` on a tree that differed from the final one only in docstring rewraps and test edits in files named above; I did not rerun every file on the very last tree (about 90 minutes of orca at 2 CPUs); the full suite and the gate are the lead's.
- No demo run (q25) and no coverage run: every statement I added in cafe/pm (`band_figures`' `round(med, 1) + 0.0`, the new `_attitude_note` return, the string edits) is executed by tests/test_round23_b.py and tests/test_report.py.
- The 7.4 / 23.6 dB (and 2.8 / 6.9 dB at Hs 1.5 m) figures of the comms docstring and PHYSICS 819 are the reviewer's, kept as named measurements "on that one grid"; B reproduced 7.4 / 23.6 at 4,000 to 400,000 ranges, nobody reproduced the Hs 1.5 m pair; delete it if the skeptic objects.
- S-19 (the emulator-miss-by-chance number) was not read against `whatif._chance_miss`.
- The `how many members miss one of 865 moments` figure (10.5 %) is the merge's run, not mine.

**Leftovers**: laptop: worktree `../cafe-r23b-base` (removed) and scratch in the session scratchpad r23b; orca: ~/cafe-worker/cafe/pm_r23b, pm_r23b2, pm_r23bbase, pmdata/dump_l23_b.py and pmdata/l23_b.txt (mine; small), logs r23b_*.log in ~/cafe-worker/logs.

