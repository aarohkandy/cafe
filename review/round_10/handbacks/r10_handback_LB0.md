# Round 10, look-ahead hand-back LB0: eight confirmed look-ahead problems

Branch `r10-la` (worktree `../cafe-r10la`), on top of the P-32 commit `06c7452`. Tests ran on cafe-orca (`PM_HOST=cafe-orca PM_RUNTIME=proot`, 2 CPUs per job, `PMX=pm_r10la*`). DECISIONS, CHANGELOG, RUNBOOK and ORCA_RUNNER are not edited here (the lead's doc pass); the text for them follows each item. DECISIONS numbers 575 to 582 follow 574 of the P-32 hand-back; renumber if that changes. No stated number changes in any item: the demo's emulator scopes (`glider/seaglider/144h`, ...) are the strings they were, the 14 to 12 members of `wing_stall_angle` is batch C's and is not touched here.

Tests are named `*_lb0_*` (except the one assertion added to an existing report test, item 3). Each was run on a detached worktree of `06c7452` (`../cafe-r10la-mut`, tests copied over, removed at the end) and fails there, except the ones marked "guard", which pass before and after on purpose.

## 1. Report banner on every older run: the derived layer rebuilt in place (P-34, derived part)

Root cause, one place: `audit.ledger_problems` judged the shared `derived.zarr` by its bytes against the run's ledger, but the layer's key holds `code_digest`, so the first run after any code change rebuilds the one store in place and every earlier run in `$CAFE_DATA` reads "changed since the stage ran ... run `fetch` again" (the advice rebuilds with the new key and cannot clear it). The report turned that into "the numbers below may not be what the stages produced", which is false: the run's outputs hash on their own and each stage that read the layer checked it when it ran (`_derived_unchanged`).

Fix: `audit._rebuilt_by_a_later_run`. For an input named `derived.zarr`, when the run's own `ingest/derived.digest.json` has a `built_from` text and the store's `built_from` attribute is another text, the store was rebuilt from another key by a later run: not a problem of this run. Same key and other bytes (damage), a missing or unusable run record, a record without a text key: the old check stands. No extra disk, no layout change (`SurfaceLayer`, `Context.env`, `_derived_unchanged` and the tests of the cache layout are untouched).

Chosen over the finding's first option (a store per key, `derived-<key>.zarr`): that is P-34 (a), 218 MB for each code edit on a disk that is 97 % full on homebase, and it is the owner's call (PROBLEMS P-34, CLAUDE.md). It also changes the path every consumer reads. Not done for the orca stores and the ocean store (same defect, no key to tell a rebuild from damage; P-34 stays open for them). The finding's second line (an older-rule `<data>/tao/manifest.json` rewritten in place) is for runs made before P-32, which have no copy of the bytes; PROBLEMS P-36.

Callers checked: `_dir_problems` unchanged; `ledger_problems` is called by `audit.main`, `credibility.Facts.problems`, `report` (banner, `ledger_problems`), `__main__` (warning lines). All get the same list; nothing else compared the derived tree. `ledger.done` hashes the layer for resume (a later stage of a finished run re-runs when the store changed) and is not changed: a resume must not feed a rebuilt layer to a stage.

Tests: `test_audit.py::test_lb0_a_derived_layer_rebuilt_from_another_key_...` (fails before), `::test_lb0_a_derived_layer_edited_under_the_key_the_run_recorded_is_still_a_problem` (guard), `::test_lb0_without_the_runs_record_of_its_key_...` (4 cases, guard), `::test_lb0_only_the_derived_layer_gets_the_rebuild_pass` (guard); `test_ingest_fetch.py::test_lb0_a_derived_layer_rebuilt_on_other_code_...` runs two real ingests on the CI fixture with another `code_digest` and audits the first (fails before with the quoted line).

DECISIONS 575: The audit of a run does not blame the shared derived surface layer for being rebuilt by a later run: for an input `derived.zarr`, a `built_from` in the store that differs from the one in the run's `ingest/derived.digest.json` (both texts) means a rebuild from another key (any code edit changes it), and the layer's tree hash is not compared; the same key with other bytes, or a run without a usable record, is checked as before ("changed since the stage ran"). | Look-ahead LB0. The report banner "the numbers may not be what the stages produced" showed on every earlier run in a data directory after the first run on new code, and its advice could not clear it. The run's outputs and its stages' own `derived_unchanged` checks are what vouch for its numbers. A store per key (P-34 a) was not taken: 218 MB for each code edit, the disk is 97 % full, the owner's call. The orca and ocean stores are the same defect and stay open (P-34). Amends 571 and P-32's sweep. Tests: `tests/test_audit.py::test_lb0_*derived*` (4), `tests/test_ingest_fetch.py::test_lb0_a_derived_layer_rebuilt_on_other_code_...`.

CHANGELOG: The audit (and so the report's "ledgers do not match" banner and `warning:` lines) no longer blames an earlier run when a later run rebuilt the shared derived surface layer from another key; damage under the same key is still reported; DECISIONS 575, P-34.

RUNBOOK sentence (troubleshooting, the row for `input .../derived.zarr changed since the stage ran`): "For a run made before the latest code change this line no longer appears: the layer is rebuilt in place by every run on new code, and the audit compares the key the run recorded (`ingest/derived.digest.json`) with the store's. A line that still appears means the store has the run's own key and other bytes: delete `derived.zarr` and run `fetch` again."

## 2. `receipts` dropped the TAO integrity row with only the older cache

`tao.caches(data)` returns every TAO cache directory under `data` that has a `manifest.json` (the older `<data>/tao`, rounds 1-9, and the current `<data>/tao/s2`); `receipts.jobs` passes that list (or `None`), and `tao.receipts(out_dir)` verifies each and states the total ("of N") in the one row. Two changes beyond the finding's fallback, both on purpose: the older cache is checked even when `s2` exists (its files are what older runs' ledgers hash), and a directory without a manifest is no cache (`verify` would raise FileNotFoundError on it; the old `is_dir()` test passed such a directory). Callers: `receipts.jobs` only (`grep cache_dir`); `tao.receipts` still takes one path (str or Path).

Existing test changed to the new subject, not weakened: `test_receipts.py::test_stored_data_directories_are_passed_only_when_they_exist` now writes a `manifest.json` into the `s2` directory it makes and expects a list.

Tests: `test_receipts.py::test_lb0_the_tao_receipt_checks_every_cache_with_a_manifest_...`, `test_tao.py::test_lb0_the_hash_receipt_counts_the_files_of_every_cache_it_is_given_...` (fail before).

DECISIONS 576: The TAO integrity receipt (`pm.env.tao`, "TAO files whose SHA-256 differs from the manifest (of N)") verifies every cache that has a manifest, the older rule's `<data>/tao` and the current `<data>/tao/s<SELECTION>`, and counts the files of both; a directory with no `manifest.json` is not a cache. | Look-ahead LB0. After 571 moved the cache, `receipts.jobs` passed `out_dir` only for the new directory, so a machine with the rounds 1-9 download lost the row without a note, and those 15 files and their manifest are what the older runs' ledgers hash. Test: `tests/test_receipts.py::test_lb0_*`, `tests/test_tao.py::test_lb0_*`.

CHANGELOG: `receipts` checks the SHA-256 of the older TAO download as well as the current one (one row, both counted).

## 3. Report text: `wing_stall_angle` without the speed gate

`report._task_html` now ends the calm-weather paragraph "wing_stall_angle is the apparent wind inside the bow cone while the apparent wind speed is at or above <trim_min_aws> (below it only wing_stall_calm counts)", with `trim_min_aws` from the same node the paragraph already prints (1.5 m/s). Siblings: the sentence occurs once in `cafe/pm` (grep); `physics/usv.py` and DECISIONS 544 already state the gate; `docs/PHYSICS.md` line 679 lists the modes without defining this one.

Test: the assertion added to `test_report.py::test_the_usv_block_states_the_two_calm_clocks_when_either_calm_mode_occurred` (fails before; this test is not named lb0).

DECISIONS 577: The report's definition of `wing_stall_angle` includes the gate of 544: the apparent wind inside the bow cone while the apparent wind speed is at or above `trim_min_aws` (below it only `wing_stall_calm` counts). | Look-ahead LB0; the wording of the report did not follow 544. No number changes. Test: `tests/test_report.py::test_the_usv_block_states_the_two_calm_clocks_...`.

CHANGELOG: The report's explanation of the USV mode `wing_stall_angle` states the apparent-wind-speed gate of 544.

## 4. A stage's OSError exited 2 as `error:`

Root: `main` caught every OSError of the whole dispatch (M-5 meant a path the user named). Now `__main__._names_a_path_given(e, args)`: the error is the user's only when the file it names (`filename`, `filename2`) is one of the paths on the command line (every string or list value of the parsed arguments), lies under one, or lies under the default `runs/`; otherwise it is re-raised (traceback, exit 1) as before M-5. The emulator table's `.lock` is not under `--emulator-table X` (`X.lock` is a sibling, path components are compared), and `PermissionError` on the shared table directory is a traceback. One raise had no filename: `receipts --broken <missing>` now raises `FileNotFoundError(ENOENT, "broken configuration X: no such file", X)`; its message text is unchanged (the existing test `test_receipts.py` matches it, and the CLI test still sees "no such file").

Known cost (PROBLEMS P-37): `par.py` ("is full after N arrays") and `dtmb5415.py` ("only N GB free under") raise a bare `OSError(message)`; they are the program's own and now give a traceback again. The ENOSPC of a cache or run file whose name is under `--out` stays an `error:` line with exit 2 (the file is under a path the user named, and the message names it).

Callers checked: every command goes through `main`'s dispatch; the M-5 test (`--out` a file, below a file, `receipts --broken`) is unchanged and passes; `stage1.main` and `acceptance.main` have their own mains/handlers (not touched).

Tests: `test_cli.py::test_lb0_an_oserror_about_a_file_the_user_did_not_name_keeps_its_traceback` (fails before), `::test_lb0_an_oserror_about_a_path_that_was_given_is_still_an_error_line_and_exit_2` (the `--out`, a file under `--out`, `--emulator-table` and the default `runs/` pass before and after; its last assertion, the `X.lock` beside a named table raising, fails before).

DECISIONS 578: `main` turns an `OSError` into `error: ...` and exit 2 only when the file it names is a path given on the command line, below one, or below `runs/` (the default output); any other OSError (a stage's own: the emulator table's lock, a cache file, a network error) keeps its traceback and exit 1. A raise of an OSError about a path it was given sets `filename` (the `receipts --broken` check does). | Look-ahead LB0. 539 wrapped the whole dispatch, so `PermissionError` on the shared table's `.lock` read as bad input (exit 2, the RUNBOOK's "a path you named") and lost the traceback that locates a code bug. Amends 539. Open: two bare `OSError(message)` raises (`par.py`, `dtmb5415.py`) now give a traceback (PROBLEMS P-37). Tests: `tests/test_cli.py::test_lb0_an_oserror_*` (2).

CHANGELOG: An OSError from a stage (the emulator table's lock, a cache file, the network) keeps its traceback and exit 1; only a file under a path given on the command line (or `runs/`) is `error:` with exit 2; DECISIONS 578.

RUNBOOK (troubleshooting row "exit code 2 and `error: ...`"): after "a path you named (`--out`, `--broken`) cannot be made or read" add "(an OSError about any other file, such as the emulator table's `.lock`, is a program failure: a traceback and exit 1)".

## 5. `orca_gate.sh` accepted a tag `pmx.sh` refused

`bin/pm_checks.sh`: one `pm_word <what> <name>` (2 or more of letters, digits, `_`, `-`, the first a letter or digit); `pm_tag` is `pm_word tag` then `pm_shape`; the TM check of `pm_names` is `pm_word TM`. `orca_gate.sh` (exports the tag as TM), `proot_suite.sh` and `pmx.sh` now refuse `a`, `9`, `-x`, `_x` with the same words before anything is sent. The message of `pm_tag` changed ("tag: 2 or more of letters, digits, _ and -, the first a letter or digit"); no test or doc quoted the old one (grep). Callers: `orca_gate.sh`, `proot_suite.sh`, `pmx.sh`, `orca_ready.sh` (via `pm_names`), `pm.sh` (`pm_job` only).

Tests: `test_proot_suite.py::test_lb0_the_gate_and_the_suite_refuse_the_tags_pmx_would_refuse_as_a_tm` (5 tags, fails before), `::test_lb0_a_tm_and_a_tag_go_through_one_rule` (guard).

DECISIONS 579: A gate's tag and `TM` go through one rule in `bin/pm_checks.sh` (`pm_word`): 2 or more of letters, digits, `_` and `-`, the first a letter or digit; `orca_gate.sh`, `proot_suite.sh` and `pmx.sh` refuse the same names, with nothing sent. A one-character tag is refused by all three (it was accepted by the first two and refused by `pmx.sh`). | Look-ahead LB0. Amends the tag rule of M-28. Test: `tests/test_proot_suite.py::test_lb0_*`.

CHANGELOG: `orca_gate.sh` and `proot_suite.sh` refuse a tag of one character or starting with `-` or `_`, as `pmx.sh` refuses it for `TM`.

ORCA_RUNNER: wherever a tag is described, "2 or more characters, the first a letter or digit" (an example tag of one letter, if any, becomes `g1`).

## 6. `ingest-ocean` on a folder of stores deleted the folder

Root: `hycom.write_store` replaces `out` after `looks_like_zarr`, which looked one level down for marks, so a folder holding a complete store counted as a damaged store; and the store's variable `c` (sound speed) looked like a chunk directory. `looks_like_zarr(d)` now means: a mark file in `d`, or a subdirectory that is an ARRAY (`.zarray`, a `zarr.json` whose `node_type` is `array`, or, when the metadata is lost, a chunk directory `c` that holds numbers only). A group (another store) is not an array, so a folder of stores is not a store. The damaged forms the RUNBOOK tells the user to repair with `ingest-ocean` (top `zarr.json` lost, all metadata lost; test r9_f) are still recognised.

Not done: the finding's second option (the `.zarr` suffix for `lab_hycom` in `load_mission`): the refusal is now by what the directory holds, which does not depend on the name, and a suffix check would reject lab missions that name a store otherwise. Swept: the other `shutil.rmtree` calls on a path from the user are `acceptance` (M-12, guarded), `app.py` (the app's own runs dir); every other is a temporary the code made.

Tests: `test_hycom.py::test_lb0_a_directory_of_other_stores_is_not_a_store_to_replace_...` (2 cases: metadata kept, metadata lost; fails before), `::test_lb0_a_store_and_its_damaged_forms_are_still_recognised` (3 cases, guard).

DECISIONS 580: `hycom.looks_like_zarr` (the test `write_store` makes before it replaces a directory) is true for a directory that carries Zarr group or array metadata itself, or holds an array of a store (v2 `.zarray`, v3 `zarr.json` with `node_type` array, or a chunk directory `c` holding chunk keys only); a directory whose subdirectories are other stores (groups) is not a store and is refused ("holds no Zarr metadata or chunks"). | Look-ahead LB0, RC-10 sibling. `ingest-ocean` with `environment.ocean.path` a folder of other missions' stores replaced (deleted) the folder. The test is by what the code made, not by the name. A damaged store (a lost top `zarr.json`, or all metadata) is still replaced, as the `unreadable` advice needs (r9_f). Relates 546 (M-12, `acceptance`) and 535. Tests: `tests/test_hycom.py::test_lb0_*` (2).

CHANGELOG: `ingest-ocean` no longer deletes a folder that holds other Zarr stores when `environment.ocean.path` names it; a damaged store of its own is still replaced.

## 7. Wrong-shaped JSON in the audit's readers (RC-1 sibling)

Root: the readers accepted any JSON object and then indexed it. Fixed at each reader of a stored file the audit or a resume reads:
- `audit.ledger_problems`: the per-stage body is `_stage_problems`; a KeyError, TypeError or AttributeError becomes "stage X: ledger P is damaged or incomplete (KeyError: 'ok'); delete it and run the stage again", the chain restarts (as for a missing ledger).
- `audit.coverage_problems` (`_read_json`, a gate line "coverage: P is damaged or incomplete"), `audit.mutation_problems` (a cut or foreign `docs/mutation.json` is a line naming the command), `audit.mutation_record` / `--mutation-record` (mutmut's counts cut or missing a key: `error:` and exit 2).
- `subgrid.promote_calibration`: a file that is not a JSON object is a ValueError (the handler already makes it a ConfigError, exit 2).
- Sibling found by the sweep: `ledger.done` (resume) and `ledger.rerecord` (`report --run`) read the ledger with bare indexing. `done` treats a wrong-shaped ledger like a half-written one (a note, the stage runs again); `report --run` records inside `damaged_run_files`. PROBLEMS P-35.

Tests: `test_audit.py::test_lb0_a_ledger_that_is_json_of_the_wrong_shape_...` (6 shapes), `::test_lb0_the_other_readers_of_the_audit_say_a_damaged_file_is_a_problem`; `test_ledger.py::test_lb0_a_ledger_of_the_wrong_shape_...` (6); `test_cli.py::test_lb0_promote_calibration_...` (4 contents), `::test_lb0_report_of_a_run_whose_report_ledger_...` (all fail before).

DECISIONS 581: `audit` reports a stored file that is valid JSON of the wrong shape (a ledger, `coverage.json`, `docs/mutation.json`) as a problem line naming the file, as it does one that is not JSON, and `--mutation-record` on unusable counts is `error:` with exit 2; `ledger.done` runs a stage again when its ledger has the wrong shape (a note on stderr), and `report --run` reports a report ledger of the wrong shape as `error:` (exit 2); `promote-calibration` refuses a calibration file that is not a JSON object (exit 2). | Look-ahead LB0, RC-1 sibling. 539 wrapped only `report`, `whatif` and `stage1`; `audit --ledgers-only` is the command the report's new warning names and the reader most likely to meet a damaged ledger. Amends 539. Tests: `tests/test_audit.py::test_lb0_*` (2), `tests/test_ledger.py::test_lb0_*`, `tests/test_cli.py::test_lb0_*` (2).

CHANGELOG: `audit --ledgers-only`, `ledger.done` and `report --run` no longer end in a traceback on a ledger that is valid JSON of the wrong shape; `coverage.json` and `docs/mutation.json` that are cut short are audit problems, not tracebacks; `promote-calibration` refuses a calibration file that is not an object.

## 8. A platform given as a path is the emulator scope by its string

`budget.platform_label(ref)`, used by `budget.emulator_scope`: a platform file in the repo's `platforms/` is its file name (`seaglider` and `platforms/seaglider.yaml` are one scope; `pipeline.code_digest` hashes those files, so an edit starts new rows, as before), any other file is `<stem>@<first 12 hex digits of its sha-256>` (the lab's own file is hashed by nothing else), and a reference that names no file keeps its text (`load_platform` refuses it). The scope strings of the demo are what they were (`glider/seaglider/144h`), so rows already in a shared table keep their scope; rows whose scope holds a path (a mission that named its platform by path) are another scope now and are not pooled (they were made by whatever the file held at the time).

Callers: `emulator_scope` is read by `budget.plan` (`vehicle_scopes`), `whatif.scope_of` / `scopes`, `pipeline.s_emulator` (row scope), `whatif.fit_class` (pooling), the tests. All route through it. The `plan.json` of an old run keeps its stored `vehicle_scopes`; a re-rendered report reads those, not the file.

Test: `test_budget.py::test_lb0_the_emulator_scope_names_a_platform_by_its_file_and_its_content` (fails before).

DECISIONS 582: `budget.emulator_scope` names a vehicle's platform by its file, not by the string the mission wrote: the file name for a file in the repo's `platforms/` (a name and `platforms/<name>.yaml` are one scope), and `<stem>@<12 hex digits of the sha-256 of the content>` for any other path, so an edited platform file of the lab's own is another function and its earlier rows are not trained on. A reference that names no file keeps its text. | Look-ahead LB0, RC-3 sibling. 535 (M-1) put the platform in the scope so as not to pool P(fail) functions that differ, but keyed on the string: `code_digest` hashes `platforms/*.yaml` only, so an edit of a platform given by path kept its old rows. The scopes of repo platforms are unchanged. Rows made under a path scope before this are another scope now. Test: `tests/test_budget.py::test_lb0_*`.

CHANGELOG: The emulator's scope names a platform by its file and, for a platform file outside `platforms/`, by a hash of its content, so editing the lab's own platform file no longer pools its old rows with the new ones.

## Verification

On orca, 2 CPUs per job, in the worktree's own directory: `ruff check cafe/pm tests` clean; `mypy cafe/pm` clean (55 files); the banned scan of `python -m cafe.pm.audit --code-only` has no hit (its one line is the absent `docs/mutation.json`, as on this tree before). Whole files, rc=0 each (the one failure of the first pass, `test_proot_suite.py::test_a_missing_marker_or_directory_or_a_tag_that_is_running_is_refused`, used the one-character tag `t`, which is refused now; its tags are `tg` and `ug`, nothing else changed): `test_audit`, `test_cli`, `test_ledger`, `test_hycom`, `test_budget`, `test_receipts`, `test_tao`, `test_proot_suite`, `test_runners`, `test_report`, `test_ingest_fetch`, `test_whatif`, `test_subgrid`, `test_config_docs`, `test_credibility`, `test_pipeline`, `test_stage1`, `test_surface`, `test_acceptance`, `test_emulator`. Coverage was not measured; every new statement in `cafe/pm/env` (`hycom._is_array` and its except branch, `tao.caches`, the `subgrid` raise) is reached by a test above. No full suite or gate ran on this branch.

Failing before: the `*_lb0_*` tests and the one report assertion were run on a detached worktree of `06c7452` with the new test files copied over (removed afterwards): 29 test cases of the lb0 tests failed there (parametrized cases counted singly) for the reasons stated in each item (the guards listed in each item passed); the report assertion failed there too.

## Not done

- P-34 for the orca stores and the ocean store (no key to tell a rebuild from damage; the owner's call).
- P-36: older runs' `<data>/tao/manifest.json` (no copy of the bytes exists).
- P-37: two bare `OSError(message)` raises now give a traceback.
