# Round 22, merge step (code part and documents): hand-back (work in progress)

Worktree `/Users/aaroh/Downloads/everything/cafe-r22m`, branch `r22-merged`, from 83240d0. "Before" worktrees: `../cafe-r22m-base` (detached 83240d0; has `tests/test_round22_m.py` and `tests/test_usv.py` copied in, uncommitted there) and `../cafe-r22m-old` (detached 7a1aaa9, for the USV reproduction). Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nothing pushed. Orca = `cafe-orca` (ssh host), runs: `PM_TAKE=1 PM_HOST=cafe-orca PM_RUNTIME=proot PMX=<dir> PM_CPUS=2 TM=<name> bin/pmx.sh python -m pytest -q -q -p no:cacheprovider ...` from the worktree; log `~/cafe-worker/logs/<TM>.log` ends `rc=N`; count results from progress characters only. Max three 2-CPU jobs at a time.

## State at 2026-11-19 (commit 7fc2d4e plus this file)

### Part 1
| item | status |
|---|---|
| 1 hunks: `hangar.check` through `finite_real`, `bench/throughput.py` through `load_json`, allow-list counts of `tests/test_round21_e.py` corrected (json 18/11, math 33/17, numpy 145/33, dynamic 4/3), `live.py` in `APP_IMAGE`, D's siblings (`check_fleet` `max_m`/`need`, free-surface `resistance` in `vehicle.build`, `_vec3` bool/numeral item); D's OPEN `check_fleet` entry removed from `tests/test_round22_d.py` | DONE. Tests in `tests/test_round22_m.py`. Before (base 83240d0, job `r22m_b2`): 107 failed, 38 passed; after (`r22m_2`, `r22m_4`, `r22m_5`): all pass except the one grid test fixed afterwards (see item 2). `r22m_1` (test_round21_e on the merged tree before my edits) failed in the numpy group only (live.py, vehicle.py): that is what was corrected. |
| 2 `test_usv.py::test_table_equals_direct_coupled_solve` | DONE (product fix + tests), evidence below. After-fix run of the corrected grid test NOT yet re-run alone (it was in `r22m_5`, failed once on leeway sign of stalled states, then I restricted the assertion to moving states). Re-run `tests/test_round22_m.py` and `tests/test_usv.py` once. |
| 3 comms.py comment/docstring (lines 120-190) and UAS "flight levels could not be read" sentence | DONE. Pins moved (below). The three UAS-sentence pins and the comms pins ran green in `r22m_4`/`r22m_5` before the docstring re-wrap; re-run `test_round18_b/x/m`, `test_comms*`, `test_round21_b`, `test_round22_b`. |
| 4 records that disagree on `ran`: left, recorded | DONE (P-R22M5). |
| 5 cross-batch runs, ruff, mypy, `audit --code-only` | PARTLY. Running now (see jobs). ruff/mypy last run in `r22m_3` (before the line-length fixes: ruff had 16 E501/F811 which I then fixed; mypy rc 0 then). MUST RE-RUN ruff (`ruff check cafe/pm tests`), mypy (`mypy cafe/pm`) and `python -m cafe.pm audit --code-only` (expect ONE problem, missing `docs/mutation.json`) via script `sh /data/r22m_lint.sh` (exists in `~/cafe-worker/cafe/pmdata/`). Not yet run: group J4 (below). |

### test_usv diagnosis (evidence)
- Counterexample wind_from=180, speed=5, heading=0, cspeed=0, cdir=0 (a dead run). On 7a1aaa9 (`r22m_usv1.py`, run in `pm_r22m_old`): `gam` = -180.0; `_body` wy-cy = -1.2246e-15 so mirror sign m=+1; the table's side from `gam<0` is -1. Speeds equal to 1e-16 (0.6054188185528582 / ...81); direct leeway +2.8215 deg, table -2.8215 deg; tracks 2.8215 vs 357.1785: 5.6429 deg apart = 2 x leeway. One degree off the tie (h=1e-9 deg etc.) the two agree.
- Cause: two tie rules for the leeway side at a dead run. Not the tolerance, not a flake.
- Scan on 7a1aaa9 (`r22m_u3`, 37,500 axis-aligned states: wind dir and heading every 15 deg, speeds 0.5,1,5,10,14, currents 0,0.5,0.9 on 4 axes): 27,480 with |gam|>45, 16,506 moving (both stw>0.5); sign differed in 296 moving states, all at |gam|=180 within 1e-9 (378 moving dead runs, 78 % split), each with track diff >1.5 deg (max 5.727; leeway up to 2.86 deg); all other moving states: track diff <= 0.0149 deg, speed diff <= 0.038. 400,000 random continuous states (`r22m_u2`, old tree): sign never differed.
- Fix: `usv.through_water_table` now `side = _body(wind_en, current_en, heading_to)[4]` (the direct solve's sign). After (`r22m_u4`, this tree): max track diff over all moving states 0.01487 deg; zero > 1.5 deg including at ties.
- Printed numbers of the demo: none can carry it. `through_water_table` is used by `table_gap`/USV receipt (speed only) and the test; stage 1 `_eval` has its own side (unchanged); stage 3 `usv_case` calls the direct solve (unchanged). Open (P-R22M4): stage 3 `usv_case(heading=None)` sails with heading = wind direction = a dead run, so the direct solve's leeway side there is a rounding tie; mirror-symmetric hull should not care, not verified.
- Tests: `@example` added in `tests/test_usv.py`; `tests/test_round22_m.py::test_the_table_and_the_direct_solve_take_the_same_tack_on_a_dead_run` and `::test_the_table_equals_the_direct_solve_on_every_axis_aligned_state_with_the_test_usv_tolerances`. On base (`r22m_b2`) both and the `@example` test fail; on the fix tree `r22m_5` showed test_usv and the dead-run test pass (449 passed, 1 failed = the grid test before my assertion fix).

### Orca jobs (all mine; read = results already read)
| TM | PMX dir | runs | state |
|---|---|---|---|
| r22m_1 | pm_r22m | test_round21_e (merged tree, before fixes) | read: rc=1, numpy group only |
| r22m_2 | pm_r22m | test_round22_m, 21_e, 22_d | read: rc=0, 542 passed |
| r22m_3 | pm_r22m | `sh /data/r22m_lint.sh` | read; superseded, rerun needed |
| r22m_4 | pm_r22m | 12 files (18_b, 18_x, 18_m, 21_b, 22_b, 22_m, 21_e, 22_d, comms, 19_m, 20_b, comms_exact) | read: rc=0, 1,270 passed |
| r22m_5 | pm_r22m_b | 22_m, usv, 18_b, 18_x, 22_b | read: 449 passed, 1 failed (fixed) |
| r22m_b1, r22m_b2 | pm_r22m_base | test_round22_m on 83240d0 (first draft; final) | read: 79 failed/36 passed; 107 failed/38 passed |
| r22m_u2, r22m_u3, r22m_u4 | pm_r22m_old, pm_r22m_old, pm_r22m | USV scans (scripts `~/cafe-worker/cafe/pmdata/r22m_usv2.py`, `_usv3.py`; copies in scratchpad `r22m/`) | read |
| r22m_x1 | pm_r22m | `-n 2` test_pipeline, test_report, test_round16_report, test_round18_c | RUNNING at last look; NOT read |
| r22m_x2 | pm_r22m_c | `-n 2` test_stage1, test_stage3, test_whatif, test_acceptance, test_credibility | RUNNING; NOT read |
| r22m_x3 | pm_r22m_b | `-n 2` test_round14_survivors, 15_a, 16_a, 16_pb, all 17..22 round files | RUNNING; NOT read |
Do not sync into pm_r22m, pm_r22m_b, pm_r22m_c while those run (use a new PMX name). A background watcher on my side is harmless. Read results: `ssh cafe-orca 'tail -3 ~/cafe-worker/logs/r22m_x1.log'`, failures `grep -a ^FAILED`, counts from progress characters.

Still to launch (J4, others; after a slot frees): test_cli, test_runners, test_audit, test_config, test_config_docs, test_conventions, test_ledger, test_receipts, test_comms, test_comms_exact, test_stats, test_stats_exact, test_vv, test_cfd, test_cfd_main, test_usv, test_platform_required, test_emulator, test_uas, test_uas_exact, test_glider, test_dyn, test_reach, test_budget, test_bench, test_ci_env, test_nest, test_par, test_perturb, test_perturb_env, test_reproducible, test_q13cmp. Then the DOC READERS after docs are final: test_config_docs, test_round18_x, test_round18_m, test_config, test_conventions, test_audit, test_runners, test_round17_m, test_round19_m, test_round16_pb, test_round17_f, test_round18_e, test_round15_a, test_hycom, test_bathy, test_budget, test_receipts, test_credibility, test_stage3 (all read a document). Then `audit --code-only`.

### Pins moved by this step, with reasons
- `tests/test_round21_e.py`: allow-list counts (app.py math 4->3; bench entry deleted; hangar and live numpy entries deleted; vehicle.py numpy entry added) and `APP_IMAGE` + `live.py`: the tree changed as the hunks said.
- `tests/test_round22_d.py`: OPEN `check_fleet` entry of the `float(` enumeration removed: no `float(` left there after adopting D's hunk.
- `tests/test_round21_b.py` (2 asserts) and `tests/test_round22_b.py` (1): UAS unusable-height sentence is now the one existing sentence "no usable height (unreadable, or outside 0.1 to 1000 m): 18.1 and 108.1 m assumed" (the old one said "flight levels could not be read" for causes where that is false).
- `tests/test_round18_b.py` (200 m figures: "a 400-point grid from 200 m gave -5.0 dB at its minimum ...", "figures of that grid, not limits"; "never too high, for the pairs ...") and `tests/test_round18_x.py` ("at the sampled ranges the margin is too LOW, never too high, for the pairs ...", "the rows' 2.9 dB too high and 2.2 dB too low", "2.4 dB too high, 1.6 dB too low", "3.3 dB too high, 0.2 dB too low"): the comms docstring no longer says "up to" / "over this range" about 400-point row figures.
- `tests/test_usv.py`: `@example` only.
No assertion weakened.

### Part 2 documents
| document | status |
|---|---|
| DECISIONS.md rows 1057-1072 + in-place amendments (1037, 1041, 1045, 957, 991, 1000, 1018 rows, 1049, 1052, 1056) | DONE (written; text in the file). Numbers in rows came from hand-backs / merged.md / my scans. Re-read once for typos; row 1066 states allow-list counts 18/11, 33/17, 145/33, 4/3 (verified by script on the test file). |
| CHANGELOG.md 'Review round 22' | DONE (inserted before "### Known issues"); round 21 bullet marked history. |
| QUESTIONS_FOR_LAB.md item 20 (20a-20h), 19f and 12d amended | DONE. 20h text describes the USV fix as the default (matches what was done). |
| docs/RUNBOOK.md (52, 100, 189, 190) | DONE (no sentence states the hangar exit code except my new one in line 100). |
| docs/PHYSICS.md 12.1 (Low antennas paragraph, round 19/20/21 paragraphs marked, new round 22 paragraph), 12.2 (label, depth pair, ambiguous_db line 833) | DONE; verify with test_round18_x / 18_m / config_docs. |
| docs/CREDIBILITY.md L23 row (first cell from batch_b_l23.txt, other cells reworded) | DONE; verify `test_config_docs::test_credibility_doc_limitation_table_is_the_code_s_list`. |
| review/orca/PROBLEMS.md P-R22M1..M9 | DONE, but P-R22M1/M2 must be updated at the end with final leftovers and any further slips (mine so far: the stray Write under /private/tmp/private removed, first USV scan stopped by pid). P-R22M6 says "the merge step ran test_credibility and test_report, see STATUS": make that true or reword after x1/x2 results. |
| STATUS.md round 22 paragraph (with the single `**LEAD: fill in**` sentence) | DONE. STILL TO WRITE: a "Tests, round 22:" paragraph after the "Tests, round 21" paragraph (line ~87) with the runs and counts (batch hand-back counts: A r22a_12 199 passed, r22a_13 174, 92/99 failed before; B 440, 786, 741+2 expected red, 43/46 before; C 722, 1,038, 200, 44/58 before; D 214, 696, 530+1 (USV), 146/214 before; E 213; plus this step's jobs). |
| HANDOFF.md round 22 block (with single `**LEAD: fill in**` sentence) | DONE except three placeholders in the "What ran" bullet: `@@M_BEFORE@@` (107 failed on 83240d0 of 145), `@@M_AFTER@@` (final count of test_round22_m after the last run), `@@CROSS@@` (the cross-batch results: files, counts, failures with reasons). Replace them. |
| grep sweep ("39.2", "10.8 dB", "a bound", "up to 5.0", "0.01 m") | DONE: remaining occurrences are marked history or are my statements; PHYSICS 344/1014 are unrelated ("a bound, not a distribution", "not a bound of the total error"). |

### Remaining, in order
1. Read x1/x2/x3 results; fix only what the combination breaks (list pin + reason; never weaken). 2. Launch J4 and re-run lint/mypy/audit. 3. Re-run item 2 tests. 4. Run the doc readers (list above) and fix doc text if a pin fails. 5. Fill the three HANDOFF placeholders, write STATUS "Tests, round 22", finalize PROBLEMS P-R22M1/M2/M6. 6. Commit (logical commits), update this file's final "Report" with: commits; part 1 items before/after (job names, rc, counts); item 2; pins; DECISIONS rows 1057-1072 (awaiting the owner: 1057, 1058, 1059, 1065, 1070); doc test results; what q24 should show (only the usv-uas-rf card and L23 texts move; acoustic labels unchanged character for character); not verified; leftovers on orca and laptop.

### Leftovers (so far)
Orca (`~/cafe-worker/cafe/`): pm_r22m, pm_r22m_b, pm_r22m_c, pm_r22m_old, pm_r22m_base; pmdata files r22m_lint.sh, r22m_usv1.py, r22m_usv2.py, r22m_usv3.py; logs `~/cafe-worker/logs/r22m_*.log`. Laptop: worktrees cafe-r22m-base, cafe-r22m-old; scratch `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/e5175414-543a-42ed-83ef-98e3ca2ddc48/scratchpad/r22m/` (usv*.py, rows_*.py, amend.py, changelog/handoff/status/problems drafts).
