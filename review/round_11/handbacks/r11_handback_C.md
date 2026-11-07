# Round 11, batch C handback (branch r11-c, finding M-22)

Files changed: `cafe/pm/env/hycom.py` (one regex and its docstring), `tests/test_hycom.py` (10 test cases in 6 functions), `review/orca/PROBLEMS.md` (row P-R11C). No doc file edited.

## M-22. `looks_like_zarr` and Zarr 2 stores

**What was done.** The finding said "tests only". Writing the Zarr 2 test found a sibling in the same helper: a folder that holds a Zarr 2 ocean store which has lost every `.z*` file was reported as a damaged store (`looks_like_zarr(folder)` True, probe on orca), so `write_store` would delete the folder. Cause: `_chunks_dir` accepted names matching `[0-9.]+`, and Zarr 2 chunk files are named `0.0.0.0`. Zarr 3 chunk keys under `c/` are whole numbers (`c/0`, `c/0/0`); the code writes no dotted keys. Fix: `[0-9]+`, one place (`_chunks_dir`; its only caller is `_is_array`, whose only caller is `looks_like_zarr`, whose only callers are `write_store` and tests). Logged at once as P-R11C.

**Printed numbers.** None move (no number of the demo reads this helper).

**DECISIONS row text (new row, after the last):**
`hycom._chunks_dir` takes a directory `c` for the chunk directory of a Zarr 3 array only when it holds whole-number names (`[0-9]+`) and nothing else. Zarr 2 chunk files (`0.0.0.0`) and the metadata files (`.zarray`, `zarr.json`) are not chunk keys, so a variable named `c` in a Zarr 2 store, with or without its metadata, is a variable and a folder holding such a store is not a store to replace. | Round 11 M-22. A real Zarr 2 ocean store (variable `c`) in a folder: with its metadata the mutant `all` to `any` in `_chunks_dir` survived, and with every `.z*` file gone the folder was taken for a damaged store and `write_store` would have deleted it (probe: `looks_like_zarr(folder)` True). Tests: `tests/test_hycom.py::test_m22_*` (6 functions, 10 cases); the foreign-store layouts are built by zarr itself from the store the code writes (`zarr_format=2`).

**Amends:** row 581 (its "a chunk directory `c` holding chunk keys only" now says keys are whole numbers; the rule is otherwise unchanged and its two `test_lb0_*` tests pass unchanged).

**CHANGELOG line:** `hycom.looks_like_zarr`: a folder holding a Zarr 2 store whose metadata is lost is no longer taken for a damaged store (chunk keys are whole numbers, not `0.0.0.0`); tests for the Zarr 2 layout, each of `ZARR_MARKS` and the `.zarray` branch (M-22, DECISIONS <new>).

**Doc sentences needed:** none required. If RUNBOOK or PHYSICS describes `ingest-ocean`'s refusal ("holds no Zarr metadata or chunks"), it can add: "A folder of Zarr 2 stores is refused like a folder of Zarr 3 stores."

**What could break, and how it was checked.**
- Callers: `_chunks_dir` <- `_is_array` <- `looks_like_zarr` <- `write_store` (hycom.py:219) and tests (grep over `cafe` and `tests`; nothing else calls them).
- A real Zarr 3 store with lost metadata must still be recognised: `test_lb0_a_store_and_its_damaged_forms_are_still_recognised` (4 forms) and `test_r9_f_a_lab_store_that_lost_its_metadata_is_repaired_*` pass. Chunk keys written by zarr 3.4.2 are `c/0/0/0/0` (whole numbers); a Zarr 3 array with the `.` separator stores `c.0.0` in the array directory, not under `c/`, so the regex change does not affect it. The dotted v3 encoding is now run: `test_m22_a_zarr_3_store_with_the_dot_chunk_key_separator_...` builds the code's own store with zarr 3.4.2 and `chunk_key_encoding` separator `.` (chunk files `c.0.0.0.0` in the array directory, none under `c/`). With its `zarr.json` it is a store and its folder is not; with every `zarr.json` gone neither is recognised (no variable has a `c/` chunk directory), so nothing is deleted, as for any foreign store. This is a pin, not a fix: the test passes on the unfixed code too, because the regex change does not touch it. Its mutant: widening the regex to `[0-9.c]+` (as a change that tried to recognise the dotted names would) makes the variable `c` of the dotted store look like a chunk directory, the folder is taken for a damaged store, and the test fails (killed; run in a detached worktree on orca, removed after).
- A Zarr 2 array with a metadata-less `c/` holding `0.0.0.0` is now correctly not a Zarr 3 chunk directory. Not recognised either way, and not changed: a *metadata-less Zarr 2 store itself* (as `write_store`'s target) is not seen as a store (probe: `looks_like_zarr(store)` False). `write_store` code writes only Zarr 3, so such a target is foreign; it is refused with "holds no Zarr metadata or chunks" rather than replaced, which errs on the side of not deleting.
- Coverage gate for `cafe/pm/env` (100 %): the change adds no branch. Measured: `tests/test_hycom.py` alone with `--cov=cafe.pm.env.hycom --cov-branch`: 598 statements, 0 missed (100 % of lines); 2 partial branches at hycom.py:610->606 and 713->715, far from the change (line 192) and not counted by the gate (the gate's `[tool.coverage.run]` sets no `branch`); other test files may cover them. The full gate is the lead's step and was not run.

**Mutants (detached worktree, removed after; tests copied onto the unfixed HEAD or the fix):**
- `all` to `any` on the unfixed code (the finding's mutant): the real-store test and both hand-built cases fail (3 of 3 fail).
- `all` to `any` on the fixed code: killed by `test_m22_a_hand_built_..._store_with_c_is_not_a_store[0/0/0/0]` (Zarr 2 with the `/` separator, where `c/0` is a number).
- Regex back to `[0-9.]+`: killed by `test_m22_a_folder_of_a_zarr_2_store_that_lost_all_its_metadata_is_still_not_a_store`.
- `.zarray` check removed from `_is_array`: killed by `test_m22_a_zarray_in_a_variable_directory_makes_the_folder_a_store`.
- Each entry removed from `ZARR_MARKS` (`zarr.json`, `.zgroup`, `.zarray`, `.zattrs`): each killed by `test_m22_each_zarr_mark_alone_makes_the_directory_a_store` (it asserts the tuple and that each mark alone makes a store; the parameters are written out because the tuple itself is what a mutant changes).

**Gates run (orca, pm_r11c):** `tests/test_hycom.py` whole file with the dotted-separator test added (rc=0, with coverage as above), `ruff check cafe/pm tests` clean, `mypy cafe/pm` clean.

## Needs from other batches

None. Row numbering: the DECISIONS row above takes whatever number follows the last row once the batches' rows are merged.

## Round-2 items (follow-up to this handback)

- Dotted Zarr 3 separator: tested now (see above).
- Metadata-less Zarr 2 store as the `write_store` target: not changed, and not a problem. The code writes only Zarr 3; a foreign store of any kind that has lost its metadata is refused (nothing deleted), which is the safe side. Only the message ("holds no Zarr metadata or chunks") is loose for it. Left as is.
- Full gate: the lead's step; not run here. Coverage of `hycom.py` measured (above).
- Stray laptop files `/tmp/null` and `/tmp/hycom.py`: checked, neither exists. Orca: only `~/cafe-worker` was written; the `pm_r11c` and `pm_r11c_mut` directories and the logs `r11c_cov.log` are removed at the end.
