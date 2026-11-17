# Round 18, batch D (CFD, its seed and the count parser): hand-back

Branch `r18-d`, worktree `cafe-r18d`, base `d69be8f`. Code and tests in `ae0af39`, line-length fixes in `af342e6`, this file in the third commit. Findings M-2, M-11, M-12 and the A-3 tests of M-16 are done; nothing skipped. Owner decisions taken at the lead's defaults (OD-2: the unary sign of a literal only). No CFD case was run and nothing shared was written: every `cached` and `_seed` test is under a private `CACHE` and a private `tempfile.tempdir`.

Files changed: `cafe/cfd.py`, `cafe/_seed.py`, `cafe/pm/par.py`, `tests/test_round18_d.py` (new), `tests/test_round17_e.py` (one row added to the table of the M-4 test: the sign alone). `tests/test_cfd.py` needed no edit (no pin moved). No file outside the batch's list was touched.

## M-2 The CFD cache key and the sign of a literal

`cfd._text_and_numbers` (`cafe/cfd.py`) now yields a chain of unary signs over a constant as one item with its sign (`"-0.71"`, `"+1"`, `"~1"`, `"--1"`): a local helper `signed_literal` inside `_text_and_numbers`, so there is no new module constant and no new top-level name (`SETTINGS`, `NOT_SETTINGS` and `NOT_KEYED` are unchanged, and the pins on them pass untouched). Only the sign of a literal enters (OD-2): `-x`, `not y` and the binary operators stay outside the key as DECISIONS 929 says. The same function skips a `raise`, a `log(...)` or `print(...)` call and a docstring first, as before, so a sign under those still keeps the key.

What the sweep found: the file has 27 `UnaryOp` signs over a number (the review's count). 10 are in keyed functions (`sh`, `symmetric_y`, `external`, `characterize_external`, `_keep_surface`, `free_surface` (4: the three `locationInMesh` fractions and `-1`), `characterize_free_surface`); the other 17 are in the module constants `DIRS`, `FS_DOMAIN`, `FS_Z` and `FS_BOXES`, which were already in the key through `json.dumps` of `SETTINGS` (which writes the sign). So the open hole was the 10, and a test now holds that the other 17 are in `SETTINGS`.

**For the RUNBOOK (batch G): every cached CFD result is renamed once more.** The item list of `_code_literals()` has `-1`, `-0.71` and so on where it had `1`, `0.71`, so `recipe()` changes and every cache file made before this commit has another name and is never read again: the next CFD of every case runs once more (as in round 17, DECISIONS 929). I did not compute the two recipes and compare names (no run of the real module on both trees); it follows from the item lists, and `test_r18_m2_the_sign_changes_the_recipe_and_so_the_cache_file` shows the file follows the digest.

Tests (`tests/test_round18_d.py`):
- `test_r18_m2_the_minus_of_a_negative_literal_is_in_the_cfd_key` (the `loc=(-0.71 * L, ...)` site turned to plus, and one sign alone).
- `test_r18_m2_turning_any_signed_literal_of_the_keyed_code_to_the_other_sign_moves_the_key` (the sweep: each of the 10 signed sites of the keyed functions turned to the other sign one at a time; the digest moves unless the site is under a `raise` or a log call).
- `test_r18_m2_the_other_signed_literals_of_the_file_are_module_constants_that_the_recipe_hashes_with_their_signs` (the 17; passes before and after: it pins the other half of the 27).
- `test_r18_m2_a_sign_is_one_item_with_its_number_and_only_a_literal_has_one` (six spellings give six digests; `-x`, `not x` and a binary operator keep the key; a sign under `raise` and `print` keeps it; a signed default moves it).
- `test_r18_m2_the_sign_changes_the_recipe_and_so_the_cache_file`.
- `tests/test_round17_e.py`: one more row in `test_r17_m4_an_edit_of_a_number_or_an_inline_text_in_the_code_changes_the_key` (`loc=(-0.71 * L,` to `loc=(0.71 * L,`). I put the sweep of signs in my new file and not into round 17's sweep (which raises each number by one): same effect, no second file to keep in step.

Proposed DECISIONS row (amends 929): `cfd._text_and_numbers` yields a chain of unary signs over a constant as one item with its sign, so the key sees `-0.71` and not `0.71`: 10 signed literals of the keyed functions (the free-surface `locationInMesh` fractions among them) were outside it; the 17 of the module constants were already in it through `SETTINGS`. Only the sign of a literal: the logic of the code (`-x`, `not y`, a binary operator) stays outside the key, as 929 says. Every cache file made before has another name and is never read again: the next CFD of every case runs once more. Why: round 18, M-2 (D-1): `_literals(src)` was equal for a source with `loc=(-0.71 * L, -0.83 * L, -0.37 * L)` and one with the three signs removed, so a `cfdcache` file made with the opposite corner would be reused as an identical earlier run; round 17's sweep raised each number by one and never turned a minus into a plus.

CHANGELOG line: the CFD cache key holds the sign of a literal (round 18, M-2); every cached CFD result is renamed and computed once more.

RUNBOOK:298 (the CFD-cache row): "every number and text written in its functions" becomes "every number (with its sign) and text written in its functions"; "every result cached before round 17 has another name" becomes "every result cached before round 18 has another name (round 17 and round 18, M-2, each renamed them)"; add DECISIONS 929 to the row's list (it is there) and round 18, M-2 to the finding list.

## M-11 `env_count` and `dvec`

- `par.env_count` (`cafe/pm/par.py`): a value that is plain ASCII digits and longer than 9 characters is a `ConfigError` naming the variable ("`CAFE_X='...'` has more than 9 digits, which is not a count of workers or cores; set CAFE_X=N or unset it"), before `int` is called; the value is shown in full up to 40 characters and cut to 20 plus `...` beyond that (a message of 5,000 digits was not an improvement). No semantic cap beyond 9 digits (the finding's default). The count is of characters, so `0000000004` (10) is refused too; `000000009` (9) still reads 9. The `ConfigError` import stays lazy, on the error path only (the comment at `par.py:214` relies on it). The existing message for the other bad values is unchanged byte for byte for values of up to 40 characters, so `tests/test_par.py` and round 17's `..._take_ascii_digits_only` rows pass untouched. `par.workers()` is the same parse (`CAFE_WORKERS`), `cfd.NPROC` too at import: all three are covered by a test.
- `cfd.dvec`: a label that is not a `str` is a `ValueError("bad direction ...")` first (None, a list, a set, bytes, a number, an object); one raise site, the same message as before. Reached through `external`'s `for d in dirs: dvec(d)` before the case is touched (a test).

Tests: `test_r18_m11_a_count_longer_than_nine_digits_is_a_config_error_that_names_the_variable` (10, 11, 4,300 and 5,000 digits, for `env_count("CAFE_X")`, `env_count("CAFE_NPROC")` and `par.workers()`; the message is under 300 characters), `test_r18_m11_a_count_of_up_to_nine_digits_is_still_a_count`, `test_r18_m11_importing_cfd_with_a_huge_cafe_nproc_names_the_variable` (subprocess, `import cafe.cfd` with 5,000 digits), `test_r18_m11_a_direction_label_that_is_not_a_string_is_a_bad_direction_not_a_type_error` (8 labels), `test_r18_m11_external_refuses_a_label_that_is_not_a_string_before_the_case_is_touched`, `test_r18_m11_the_labels_that_were_directions_still_are`. I added the `"9"*5000` and `"9"*10` rows here, not to round 17's parametrized list: that test matches the old wording "is not a whole number of at least 1" for every row.

Proposed DECISIONS row (extends 931, 330, 912, 951): `par.env_count` refuses a value of more than 9 digits as a `ConfigError` naming the variable and showing at most 40 characters of it (a count of workers or cores has at most 9 digits: a parser's bound, not the planner's; the plan can still ask 290 workers); it applies to `CAFE_WORKERS` and `CAFE_NPROC` together (`NPROC` at import). `cfd.dvec` raises `ValueError("bad direction ...")` for a label that is not a string, where row 931 promised a `ValueError` and `d in DIRS` raised `TypeError`. Why: round 18, M-11 (A-7, A-8): `CAFE_X="9"*5000` was `ValueError: Exceeds the limit (4300 digits)` from `int`, and `CAFE_NPROC=99999999999` reached `mpirun -np`.

CHANGELOG line: `CAFE_WORKERS` and `CAFE_NPROC` of more than 9 digits are a `ConfigError` naming the variable; `cfd.dvec` of a label that is not a string is a `ValueError` (round 18, M-11).

RUNBOOK:311 (the `CAFE_WORKERS=... is not a whole number of at least 1` row; also `CAFE_NPROC`): add "or more than 9 digits (`error: CAFE_WORKERS='...' has more than 9 digits, which is not a count of workers or cores`)" to the cause. RUNBOOK:159 ("a whole number of at least 1 in plain digits"): "and at most 9 digits".

## M-12 `_seed`

`cafe/_seed.py`: `cached` is called with a `log` that records and echoes each line, and the lambda records that the compute ran. Per sample it prints: `already there <key> <k>` when the compute did not run (the cache held an identical earlier run: nothing written; the cache's own "CFD: reusing ..." line precedes it); `NOT seeded <key> <k> - <the warning>` when it ran and a line starting `warning:` was logged (the write failed); `seeded <key> <k>` when it ran and wrote (also after "the cache file ... cannot be read; computing again": removed and rewritten). Exit 1 when any sample is `NOT seeded` (and as before when no old run is there). The temporary directory is a `tempfile.TemporaryDirectory()` per sample, removed on exit (`mkdtemp` left one per call). The `lambda` is bound to its loop variables (`r=r, c=computed`) and `log` to its list by default arguments (ruff B023). The detection of a failed write is by the text prefix `warning:` that `cached` writes (`cafe/cfd.py`, the write guard): the two are held together by the `NOT seeded` test, which uses a real unwritable cache.

Tests: `test_r18_m12_seed_a_second_time_says_already_there_not_seeded`, `test_r18_m12_seed_into_a_cache_that_cannot_be_written_says_not_seeded_and_exits_1` (a regular file where the cache directory should be), `test_r18_m12_seed_a_cache_file_that_cannot_be_read_is_replaced_and_counts_as_seeded` (passes before and after: pins the third word), `test_r18_m12_seed_leaves_no_temporary_directory_behind` (`tempfile.tempdir` patched to a private directory; two calls leave it empty). Round 17's two `_seed` tests pass unchanged (the first run still prints `seeded quad ('external', 'air', 10.0)`).

Proposed DECISIONS row (amends 932, the `_seed` row of round 17, M-12): `python -m cafe._seed` prints, per sample, `seeded` (an entry was written), `already there` (the cache held an identical earlier run: nothing written) or `NOT seeded` with the cache's warning (the write failed), and exits 1 when any sample is `NOT seeded` or none is found; its temporary directories are removed. Why: round 18, M-12 (D-4): it printed `seeded` after a hit and after a failed write, so the lab user's remedy of round 17's M-12 could read `seeded` for a seed that did not happen.

CHANGELOG line: `python -m cafe._seed` says `seeded`, `already there` or `NOT seeded` per sample, exits 1 for a failed write and removes its temporary directories (round 18, M-12).

RUNBOOK:298 (same row), the `_seed` sentence: add "it prints `seeded`, `already there` (the cache held an identical earlier run: nothing was written) or `NOT seeded: <warning>` (the cache could not be written: set `CAFE_WORK` to a writable directory), and exits 1 for a `NOT seeded`".

## M-16, A-3 tests

- `test_r18_a3_the_command_texts_of_the_openfoam_calls_are_in_the_key`: each of the 30 text constants of the 15 `sh(...)` calls of the keyed functions, edited one at a time, moves the digest; plus the named edit `decomposePar -force` to `decomposePar`.
- `test_r18_a3_a_result_that_json_refuses_with_a_value_error_is_returned_with_a_warning`: a circular list (`ValueError: Circular reference detected` from `json.dumps`) is returned with the one warning that names `ValueError`, and no file is left. I used the circular list only: the review's "a NaN" is written as `NaN` by `json.dumps` (its default `allow_nan`), so it is not a refusal here.

Mutants (detached worktrees `cafe-r18d-mut1` and `cafe-r18d-mut2` at `ae0af39`, one line each, run on orca with `tests/test_round18_d.py` and `tests/test_round17_e.py`; the round 17 file passes both mutants, as the review found, and only the new test fails):
- `("log", "print")` as `("log", "print", "sh")` in `_text_and_numbers`: `r18d_mut1.log`, 1 failed (`test_r18_a3_the_command_texts_...`), 115 passed, rc=1.
- `except (OSError, TypeError, ValueError)` as `except (OSError, TypeError)` in `cached`'s write guard: `r18d_mut2.log`, 1 failed (`test_r18_a3_a_result_that_json_refuses_...`), 115 passed, rc=1.

## Fail before

Detached worktree `cafe-r18d-base` at `d69be8f` with only `tests/test_round18_d.py` and the edited `tests/test_round17_e.py` copied in (`PMX=pm_r18d_base`), `r18d_base2.log`: **22 failed, 94 passed**, rc=1 (counted from the progress lines as CLAUDE.md says; the two `E` the loose count would add are traceback lines).
- Failed at base (22): M-2, 5 (the four tests of M-2 that change the key, and round 17's new row); M-11, 14 (the four lengths, the import, eight labels, `external` and a non-string label); M-12, 3 (the second run, the unwritable cache, the temporary directory).
- Passed at base (94 of 116, the pins that hold before and after or kill a mutant on correct code): the 17-constants test, the up-to-nine-digits test, the "were directions still are" test, the unreadable-file `_seed` test, both A-3 tests (they pass on correct code and fail on their mutants, shown above), and all of round 17's file but the new row.
- A first attempt used `-k` with a space-separated expression, which the runner split (`r18d_base1.log`, rc=4, nothing ran); not counted.

## Final runs (orca, `PM_CPUS=2`, logs in `~/cafe-worker/logs/`)

- `r18d_3.log`, rc=0, **916 passed**, no F or E, on the final tree `af342e6`: `tests/test_round18_d.py`, `test_round17_e.py`, `test_cfd.py`, `test_cfd_main.py`, `test_par.py`, `test_config.py`, `test_config_docs.py`, `test_runners.py`, `test_round16_pb.py`. These import or pin `cfd.SETTINGS`, `recipe`, `NOT_KEYED`, `dvec`, `env_count`, `CAFE_NPROC` and `CAFE_WORKERS`.
- `r18d_2.log`, rc=0, **2,161 passed**, no F or E, on `ae0af39` (the code commit; `af342e6` after it changes comments, line lengths and a test constant only, and `r18d_3` above re-ran 916 of these on `af342e6`): `tests/test_round18_d.py`, `test_round17_e.py`, `test_cfd.py`, `test_cfd_main.py`, `test_par.py`, `test_config.py`, `test_config_docs.py`, `test_runners.py`, `test_round16_pb.py`, `test_budget.py`, `test_environment.py`, `test_nest.py`, `test_ledger.py`, `test_receipts.py`, `test_vv.py`, `test_stage3.py`, `test_pipeline.py` (the files that import or pin the CFD key, `env_count` / `CAFE_NPROC` / `CAFE_WORKERS`, `dvec`, `_seed`, and the consumers of `cfd` and `par`). The test count per file (`r18d_col.log`, collect only): 27, 89, 17, 11, 55, 260, 57, 367, 33, 95, 118, 90, 66, 110, 158, 264, 344. It took about 1 h 55 min on a loaded box (`test_stage3` runs CalculiX).
- `r18d_1.log` (first run of the new file, before the test count fix: 1 failed, the sweep's lower bound written as 20 where the keyed functions hold 10; fixed, passes in the runs above).
- Coverage of `cafe/pm/par.py` (the only gated-class module I touched is none: `physics`, `stats` and `env` are not edited): `r18d_covb.log` (base tree, `tests/test_par.py`): 203 statements, 0 missed, 100 %; `r18d_cov.log` (my tree, `tests/test_par.py` with `test_round18_d.py` and `test_round17_e.py`): 206 statements, 0 missed, 100 %. Line coverage, `--cov=cafe.pm.par` (the audit's `--cov=cafe/pm` is not run per module here).
- `ruff check cafe/pm tests cafe/cfd.py cafe/_seed.py`: `r18d_ruff3.log`, "All checks passed!" on `af342e6` (the two `cafe/` files are outside the gate, checked anyway; earlier runs found four E501 of mine, fixed).
- `mypy cafe/pm`: `r18d_mypy2.log`, rc=0 on `af342e6`.
- `python -m cafe.pm audit --code-only`: `r18d_scan.log`, **1 problem**: "mutation: no stored result at docs/mutation.json". That file is not in the repository (`bin/sync_filters` keeps it on the server: it is made by `make mutation`), so a fresh `pm_r18d_*` directory has none; no banned token, ledger or scan problem. It ran on `ae0af39`; `af342e6` only edits comments, line lengths and a test constant.

## Not verified

- No real CFD case, no OpenFOAM, no `hangar.run`: the key is shown on the module text and `cached` with stand-in computes.
- That every old cache file is renamed was not measured (I did not compute `recipe()` on both trees and compare); it follows from the changed item list, and `test_r18_m2_the_sign_changes_the_recipe_and_so_the_cache_file` shows the file name follows the recipe.
- The second-user and read-only-mount cases of `_seed` are by a regular file standing for the cache directory; no real read-only mount (the runners' `/work:ro`) was used.
- `_seed` on the `wigley.surface.json` path was not tested (it needs `geom.hydrostatics`), as in round 17; only `quad` is. The `NOT seeded` / `already there` logic is the same code for all three.
- The full suite, the full audit and mutation testing were not run (the lead's gate). Python 3.12 only (orca); the laptop's 3.9 was used only to count `ast` nodes, which I report as measured there.
- Cache and recipe numbers (10 keyed signed sites, 17 in module constants, 30 text constants in 15 `sh` calls) were counted with `ast` on the laptop's Python 3.9 on this tree, the tests assert lower bounds that held on orca's 3.12.

## Found outside my batch, and left alone

- `cafe/cfd.py` imports `par` (`from cafe.pm import par`) and later defines a function named `par` (the mpirun wrapper). `NPROC = par.env_count(...)` runs before the `def`, so it works, but any later `par.env_count` or `par.workers` in this file would hit the function. Not changed (not in a finding); worth a rename (`mpi`) in a later round.
- `docs/RUNBOOK.md:298` and `:311` and DECISIONS 929, 931, 932 say what is above; the documents batch needs the rows and sentences in this file. No test of mine reads a document, so no `.patch` is needed.
- The `_seed` check of `warning:` text is a coupling to `cached`'s message (a prefix); if a later batch rewords that warning, the `NOT seeded` test fails, which is the intended alarm.

## Left on orca and on the laptop

Orca, inside `~/cafe-worker` only: directories `cafe/pm_r18d`, `pm_r18d_base`, `pm_r18d_mut1`, `pm_r18d_mut2`, `pm_r18d_lint`, `pm_r18d_lint2`, `pm_r18d_lint3`, `pm_r18d_cov`, `pm_r18d_covb`, `pm_r18d_fin`, `pm_r18d_pipe`; job markers `cafe/.pmx.job.pm_r18d*`; logs `logs/r18d_1`, `r18d_2`, `r18d_3`, `r18d_base1`, `r18d_base2`, `r18d_mut1`, `r18d_mut2`, `r18d_ruff`, `r18d_ruff2`, `r18d_ruff3`, `r18d_mypy`, `r18d_mypy2`, `r18d_scan`, `r18d_cov`, `r18d_covb`, `r18d_col` (collect only), `r18d_4` (a duplicate run of `test_pipeline.py` that I stopped with `tmux kill-session -t =r18d_4` when `r18d_2` reached the file: rc=143, not counted anywhere). No shared store, no `/data/runs`, no `cfdcache` was written, nothing in `/tmp`. Nothing killed.
Laptop: my scratch worktrees `../cafe-r18d-base`, `../cafe-r18d-mut1` and `../cafe-r18d-mut2` were removed with `git worktree remove --force` after their runs (the evidence is in the logs named above), and my wait script `../cafe-r18d-waitjobs.sh` is removed at the end; only `../cafe-r18d` (this branch) remains.
