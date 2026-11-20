# Round 23, batch G hand-back (documents)

Branch r23-g (worktree /Users/aaroh/Downloads/everything/cafe-r23g), base f71ad43 (round 22 closed c7ca35e + review material + batches A to D). Documents only; no file under cafe/ or tests/, no docs/CREDIBILITY.md.

## What changed
- DECISIONS.md: rows 1073 to 1084 (1073 the lead's rulings and the three owner questions marked; 1074 the RF card, L23 and the sampling note; 1075 Iridium; 1076 the Bellhop label and the NOT EXERCISED note; 1077 the 7.6 dB; 1078 the S-12/S-14 to S-17/S-33/S-40 clauses and batch B's skeptic pass; 1079 YAML and `_vec3`; 1080 app, live, plan; 1081 builder M's and E's items and the claims lint; 1082 recorded and not coded; 1083 deviations of the builders from merged.md; 1084 pins moved). Amended in place with "(amended by NNNN: ...)": 286, 477, 652, 891, 1039, 1057, 1066 ('through any alias'), 1069.
- CHANGELOG.md: 'Review round 23' before 'Known issues'.
- review/orca/PROBLEMS.md: P-R23M1 (D-3, D-5 unguarded, with reachability) to P-R23M7 (leftovers by exact name).
- STATUS.md: Round 23 paragraph (section 2), 'Tests, round 23'; lines 18 (S-41), 21 (7.6 dB), 144 ('the plan is a lower bound'), 179 ('pure physics').
- HANDOFF.md: a round 23 block at the top of section 00, header updated.
- docs/RUNBOOK.md: 58 and 189 (632 km), 146 (S-17: 'the estimate is not a schedule and q8 ran 2.2 times over it'; the pin of tests/test_config_docs.py needs 'q8 ran 2.2 times over it (52.7 s ...'), 189 (S-36: 'conservative for the transmitter depth' deleted), 190 (S-20, S-21 and 'not of the worst case' deleted; the demo pair's -10.8 to +39.2 / -14.9 to +70.9 kept as figures of those two samplings of that pair). Line 100 needed no edit: it is true after batch C and tests/test_round23_c.py holds it (named in DECISIONS 1079).
- docs/PHYSICS.md: 757 loses 'The UAS verdict therefore rests on the battery and on finishing the profile inside the time limit.'; 762's 'therefore rests' clause is now 'In q6, 55 of 64 members were `profile_incomplete` and 6 `battery_reserve` (...)' (the lead's ruling after batch B's skeptic pass). Every other PHYSICS sentence shared with batch B's changes (817, 819, 849, 892, 756) was read and is consistent with the code text; none needed another edit.
- QUESTIONS_FOR_LAB.md: 12 (S-41: the demo's '555 and 598 km' and '111 km' deleted; the RF NO-GO follows from the radio horizon, 88.85 % in q12), new item 21 (21a to 21e). 12a and 20a are batch B's and were not touched.

## Honest-number sources
Every figure comes from a hand-back, merged.md or a run named in the row: 10.5 % / 10.25 % (merge), 26 of 33 and 610 (batch B), 71 of 110 and 1,215 (C), 378 and 1,120 (D), 480 `info` combinations (A), 632.45 km and 554.7 km (merge, q23), 88.85 % and 0.88848 (PHYSICS 819, q12), -10.77 / -14.88 dB (merge's run). Nothing is measured by this step.

## Runs (this step; orca, proot, 2 CPUs per job, PMX pm_r23g*)
- r23g_1 and r23g_2 (first draft of the documents): stopped by exact tmux session name (rc=143, no result). r23g_3 (test_config_docs, test_round23_b, pm_r23g3): ONE failure, test_the_runbook_does_not_say_the_planner_never_overruns_stage_1 (it pins 'q8 ran 2.2 times over it (52.7 s planned, 117 s measured, of a 900 s share)' in RUNBOOK 146; I had written '...over the estimate': text changed to 'the estimate is not a schedule and q8 ran 2.2 times over it', test untouched). Before that, a lint in tests/test_round23_b.py (M-4: no '7.6 dB', 'up to 7.6', '34.7', 'within about 8 dB' in CREDIBILITY, PHYSICS, QUESTIONS) would have failed on my first QUESTIONS 21b; found by reading, fixed before it ran.
- r23g_4 (pm_r23g4, -n 2): test_config_docs, test_round18_m, test_round18_x, test_runners, test_audit, test_conventions, test_round16_pb, test_round17_m, test_round19_m, test_round23_b, test_credibility, test_config, test_coare: rc=0, 1,237 passed, 0 failed.
- r23g_5 (pm_r23g5, -n 2): test_budget, test_report, test_round16_report, test_round21_b, test_round18_a, test_stage3: rc=0, 1,058 passed, 0 failed.
- r23g_6 (pm_r23g6, -n 2, on the committed tree after the last text edit but the hand-back): test_config_docs, test_round18_m, test_round18_x, test_runners, test_audit, test_conventions, test_round16_pb, test_round17_m, test_round19_m, test_round23_b, test_credibility, test_config: rc=0, 1,191 passed, 0 failed.
- Counts are the result characters of the progress lines (CLAUDE.md). ruff and mypy not run (no code touched). The audit's banned-token scan was run by hand over RUNBOOK.md (the only document it scans): no hit.
- Not run: the whole suite, the gate, a demo, mutation; test_pipeline, test_cli, test_par, test_stage1, test_whatif (they mention a document only in a docstring or an error message); builder M's and E's tests.

## Things I could not do or decide
- Builder M's and E's code was not available (parallel worktrees): DECISIONS 1081 records what they were asked to do, not what they did. If their hand-backs differ (the lint's allow-list, the symmetry test, `bench_sortie_rate`, L17), amend row 1081.
- S-42 (CREDIBILITY 171) and S-19's number: nobody's; recorded in P-R23M4. CREDIBILITY.md is not my file.
- Budget hunk of batch B (budget.py:57-58, 603; pipeline.py:1593; tests/test_budget.py:592-594) and the rfband.py docstring hedge (rfband.py:12-13): not mine, not known to be taken; P-R23M4.
- The plan basis printed by the report still says 'so it is a lower bound' until that hunk lands.
- PHYSICS 704's 'cannot fire' is the USV becalmed mode, not a claim of the sweep, and is unchanged. I amended no row of DECISIONS for 199, 237, 301, 332, 511 ('UAS verdict rests on ...') or 457/538 (dated history; named in row 1078).
- The lint-phrase hazard: tests/test_round23_b.py's M-4 lint scans CREDIBILITY, PHYSICS and QUESTIONS for '7.6 dB', 'up to 7.6', '34.7', 'within about 8 dB'. My first draft of QUESTIONS 21b quoted them; fixed. Builder E's lint over the documents (up to N, at most N, by chance, no number of members, within about) will see the new text of STATUS, QUESTIONS, RUNBOOK and PHYSICS: I added no such phrase to those four (STATUS 5 lines with a hit, QUESTIONS 6, as before or fewer); HANDOFF, CHANGELOG, DECISIONS and PROBLEMS (logs) do quote the deleted sentences.

## Hostile attempts on my own text
Read every new sentence of STATUS, HANDOFF, CHANGELOG, DECISIONS and QUESTIONS for a number or a claim not in a hand-back or merged.md; grepped the four user documents for the deleted words ('worst case', '7.6 dB', 'cannot fire', 'pure physics', 'no number of members', 'by chance', 'lower bound', 'rests on', 'ship's mast', 'at most 0.59', '0.046', 'through any alias'): the remaining hits are history rows or dated measurements, listed in row 1078 and P-R23M4; checked every table row's cell count; the first pin failure (RUNBOOK 146) was found by the tests and fixed in the text, not the test.

## Skeptic pass
Two minor findings, both real, both fixed in my files (documents only; no code, so no new regression test; the document-reading tests are re-run below).
1. STATUS.md round 23 paragraph said the claims lint's 'allow-list is the complete set of absolutes a user can see'. Real: DECISIONS 1081 says the code was not read by the documents step and the lint only proves no new absolute lands unreviewed; HANDOFF 'Not covered' and merged.md list uncovered sentences. Replaced with: the allow-list is the set of constant strings in the four files that match the lint's word list and were reviewed; sentences outside that list and those files (the stage-3 and emulator report text, PHYSICS outside the grep) are not covered.
2. '88.85 % in q12' (QUESTIONS_FOR_LAB 12, STATUS 'missing physical inputs' row at line 18) was a q12 figure next to q23 figures. Real: review/round_17/q17_vs_q16.md and round_20 reviewer_c record 0.8878 (0.8900 at q16), so the quantity moved. This step measures nothing and no q23 report.json is in the worktree, so both places now say 'about 89 %' with no run name (QUESTIONS 12's later sentence already said 89 %). Not changed: DECISIONS 652's '88.85 %', which is a dated round 12 record of what was read then, not a current claim.
Run: r23g_7 (pm_r23g7, -n 2, orca, proot): the r23g_6 files plus test_report and test_round16_report, on the tree with both edits: rc=0, 1,459 passed, 0 failed.

## Leftovers
Orca (inside ~/cafe-worker): cafe/pm_r23g, pm_r23g2, pm_r23g3, pm_r23g4, pm_r23g5, pm_r23g6, pm_r23g7 and their .pmx.job markers; logs r23g_1 to r23g_7. No tmux session of mine is alive. Laptop: worktree ../cafe-r23g (branch r23-g). Nothing is pushed. Scratch: the session scratchpad r23g/decisions.py (the script that wrote DECISIONS rows 1073 to 1084).

## Commits
df12104 (the documents), then the STATUS repair and this hand-back (see git log r23-g).
