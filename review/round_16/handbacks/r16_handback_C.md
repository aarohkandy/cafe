# Round 16, batch C: hand-back to the documents step

Branch `r16-c`, from `ed3141d`. Findings: M-18, M-20, M-21, M-23, M-24, M-26, and the two security items S1 and S2 (the review of the round 16 prefix). No document was edited; this file and the two rows of `review/orca/PROBLEMS.md` (P-R16C1, P-R16C2) are the only text outside code and tests. DECISIONS numbers below are "C1, C2 ..." for the documents step to number after 883; a row that amends an old one names it.

No printed number of the demo moves: the shipped `config/assumptions.yaml` still reads 70 elements (the tests compare the line reader with PyYAML on the file itself), the writers write the same arrays and text, the ingest only gains a lock, and `cfd` is not on the demo's path. No demo was run.

## What changed, by file

- `cafe/atomic.py`: `_replace_through(p, fill, follow_symlinks)` is the one temporary-and-replace; `write_text` and `write_with(p, writer, follow_symlinks=False)` both call it (S1).
- `cafe/ocean.py`: the slice child and the axes child write through `atomic.write_with`; the parent hands the slice child a `tmp_name` and removes it in a `finally` (S2).
- `cafe/fea.py` (M-20), `cafe/cfd.py` (M-23, M-26), `cafe/pm/stage3/pipeline_windows.py` (M-26, one line).
- `cafe/pm/env/remote.py` (`store_lock(..., wait=)`), `cafe/pm/pipeline.py` (`_shared_store`, `s_ingest`), `cafe/pm/env/hycom.py`, `bathy.py`, `orca.py` (M-24).
- Tests: `tests/lockprobe.py` (new, a probe for a held flock), `tests/test_cfd.py` (new), and additions to `test_remote.py`, `test_audit.py`, `test_surface.py`, `test_pipeline.py`, `test_hycom.py`, `test_bathy.py`, `test_orca.py`, `test_stage3.py`, `test_round16_pb.py`; `test_config.py` (three expected-count lines, see "needs from other batches").

## S1. `write_with` keeps the target's mode, refuses a symlink and writes through the descriptor

DECISIONS row C1: `cafe.atomic.write_text` and `write_with` are one implementation, `_replace_through`. The temporary is made with `os.open(O_WRONLY|O_CREAT|O_EXCL)`, `0o600` when the target exists and `0o666` when it does not; the content goes through that descriptor (`write_text` as a `Path` whose `open` is the descriptor, `write_with`'s writer gets `open(fd, "wb", closefd=False)`), never through the name again; an existing file's permission bits are set with `os.fchmod` before `os.replace`; a symbolic link at the target is refused (`OSError`, ELOOP) unless `follow_symlinks=True`, which replaces the file the link names and keeps the link. `write_with` had `open(tmp, "xb")`: the umask's mode (a `0o600` `.npz` became `0o644`), no symlink check, and a second open by name. Amends 872 (its rules now hold for `write_with`) and 880 (the writer gets "a file object on the descriptor `os.open(O_EXCL)` returned", not "a file object opened `"xb"`").

CHANGELOG: "S1: `cafe.atomic.write_with` keeps the replaced file's mode, refuses a symbolic link at the target (`follow_symlinks` replaces the file it names) and writes through the descriptor of the temporary it created; it and `write_text` are one function."

Doc sentences: none beyond the docstrings (RUNBOOK does not describe the writer). If DECISIONS 872 is summarised anywhere in `docs/`, say "both writers".

Could break, and checked: the callers of `write_with` are `cafe/_site_data.py:282` (a cache file), `cafe/hangar.py:339` (`fea_<key>.npz`), `cafe/ocean.py` (3 writes), and, new in this batch, `bathy.fetch_gebco` and `orca._save`. None writes through a symbolic link (the check is on the last component of the target only; a link in the directory path is followed as before). The 17-character temporary name is unchanged, so the long-name case of M-6 holds. `cafe/atomic.py` still imports only `json, os, pathlib, stat, uuid` (+ `typing`), which `test_r15_config_write_text_is_the_atomic_writer...` pins. The cut-write fixtures of the earlier rounds (`cut_writes`, `cut_npz`) still cut: `write_text` goes through `Path.write_text`, `write_with` through `np.savez*` given a file object.

Tests: `tests/test_round16_pb.py`, `test_r16_s1_*` (each parametrized over `write_text` and `write_with`: mode kept / umask for a new file, the temporary never wider than 0o600, symlink refused and `follow_symlinks`, content through the descriptor when a link is swapped in at the temporary's name). Fails on the unfixed code for `write_with` in the first three; the fourth is a mutant test (below).

## S2. The part files of `cafe/ocean.py`

DECISIONS row C2: the part files of `cafe/ocean.py` are no longer predictable names opened by name. `_child_axes` writes `atomic.write_with(out, ...)`; `_child_slice` the same, to a name the parent chose with `atomic.tmp_name(<cache file>)` (`.<12 hex>.tmp`), and the parent removes it in a `finally`, whether the child worked or not. Before: `<out>.<pid>.part.npz` and `<stem>.<pid>.part.npz`, opened by `np.savez(name)`, so a link planted at the guessed pid name received the write (the review of the round 16 prefix). The sweep `test_p_r15a_3_every_npz_the_app_writes_goes_through_write_with_or_is_named_here` now allows only the pressure `.npy` of `cfd.py`, and a new sweep forbids a `.part` / `.tmp` suffix string and `getpid` in any `cafe/*.py` outside `atomic.py` (one allowed: `env.py`'s filter that leaves an old `.part` out of a WRF catalogue). Amends 880 (the two child writes were named there as exceptions).

CHANGELOG: "S2: the part files of `cafe/ocean.py` are written with `atomic.write_with` under `atomic.tmp_name` names (O_EXCL), not `<name>.<pid>.part.npz`; a sweep keeps pid-named and fixed-suffix files out of `cafe/*.py`."

Could break, and checked: `test_p_r15a_3 ... hycom_call` had a stand-in child that called `np.savez(args[4], ...)`, which adds `.npz` to the temporary's name; it now calls `atomic.write_with` as the real child does. `tests/test_config.py::test_r15_every_json_the_app_reads_back...` counted `ocean.py:os.replace: 1`; that entry went (no `os.replace` is left in ocean.py). The real children were run in-process with a fake `netCDF4` (`test_r16_s2_*`); a real `python -m cafe.ocean` child was not run (no network from the worker).

## M-18. Lock sites held by tests (tests only)

DECISIONS row C3 (amends 883): the list of sites that take `store_lock` is held by tests, asked through a descriptor of its own (`tests/lockprobe.held(lockfile)`, a `flock` of a second open file conflicts with the first): after a `with store_lock(p)` block the file is free and a second block holds it afresh (`held.discard`, also after a block that raised), and the lock is held at the write of `surface.build`, at `store_span`, at `SurfaceLayer`'s load, at `Context.env`'s span check and load, at `_derived_unchanged`'s hash and at `audit._tree`'s hash of `derived.zarr` (and not for any other store, nor when the file is absent). The sites of 883 are complete: pipeline.py `Context.env`, `_derived_record`, `_derived_current`, `_derived_unchanged`; surface.py `store_span`, `build`, `SurfaceLayer`; audit.py `_tree`; remote.py's release. Seven edits (a null context for each lock, `held.discard` as `pass`) were applied one at a time: see "Mutants" below.

CHANGELOG: "M-18: tests hold every site of the cache lock (the release, `Context.env`, `surface.build`, `store_span`, `SurfaceLayer`, `_derived_unchanged`, `audit._tree`)."

Doc sentences: none. No timing: the tests ask the lock, they do not wait for a thread (the finding allowed `wait(0.4)`; this avoids it).

Could break: nothing in production code changed for M-18.

## M-20. `fea.hull_elements_along` and the two layouts

DECISIONS row C4 (amends 874): the line reader refuses a line deeper than the `value:` line that follows it (`value: 70` then `    more` is '70 more' in YAML, with 3, 4 or 5 spaces of indent, also after a blank line), and its blanks are the space and the tab only (`str.strip()` and `\s` take U+00A0, which YAML keeps as text: `value: 70` + U+00A0 is '70\xa0'). A deeper comment line, and a deeper line under another child (`unit:`), are read as before. Other line-break characters (U+000B, U+000C, U+0085) are still not covered.

CHANGELOG: "M-20: `fea.hull_elements_along` refuses a continuation line under `value:` and a no-break space after the number; before, it returned 70 where PyYAML gives '70 more' or '70\xa0'."

Doc sentence for 874's text (or RUNBOOK 5 if it describes the reader): "a line under `value:` that is indented further, and a no-break space, are refused."

Could break, and checked: the only reader of the key besides PyYAML is this function (`pipeline_windows` uses PyYAML), called by `pipeline_windows._fea` and `hangar.fea_cases`; the shipped file reads 70 (the existing test compares both on the file). Tests: ten rows added to `test_r15_l0_4_the_hull_mesh_reading_never_returns_a_number_pyyaml_does_not` (seven "refuse", three controls that return 70 and equal PyYAML), and `test_r16_m20_...` which shows that PyYAML does not give 70 for each refused text.

## M-21. `"xb"` of `write_with` (tests only)

DECISIONS row C5 (amends 872, 880): `test_r16_m21_a_temporary_name_that_exists_is_an_error...` makes `tmp_name` return an existing file and requires `FileExistsError` with that file and the target untouched, for both writers (the check is now on `O_EXCL` in the shared function). The reviewer's items 2 and 3 (`fchmod`, `is_symlink`) were already killed by `test_round15_a.py` and `test_config.py` (the reviewer's `-k` filter deselected them); they are also killed by the S1 tests.

CHANGELOG: "M-21: a test holds the O_EXCL of the atomic writers."

## M-23. `cfd.cached` and the solver settings

DECISIONS row C6 (amends 815 and 817, which cover only the write path): `cafe.cfd.cached` hashes the mesh bytes, the call parameters and `cfd.recipe()`: the sha-1 of the JSON (sorted keys) of the module constants named in `cfd.SETTINGS`: `FOAM` (which holds the OpenFOAM version in its path, `openfoam2506`), `FLUIDS`, `DIRS`, `COMMON_SCHEMES`, `QUALITY`, `EXT_SNAPPY`, `EXT_FIELDS`, `SURF_FO`, `FS_FIELDS`, `FS_DOMAIN`, `FS_H0`, `FS_Z`, `FS_NZ`, `FS_GRADE`, `FS_BOXES`, `FS_ITERS`, `FS_LTS`. A comment, a docstring or another function changes nothing. `CAFE_NPROC` is not in the key (cores change the time, not the answer); the cached file is now `{"recipe", "nproc", "result"}` and `cached` returns `result`. A new module-level constant must be named in `SETTINGS` or `NOT_SETTINGS` (a test reads the module). Every cache file made before this change has another name and is never read again: the next CFD of every case runs once more.

CHANGELOG: "M-23: the CFD result cache is keyed on the solver settings (`cfd.SETTINGS`, with the OpenFOAM version) as well as the mesh and the call; the core count is recorded in the file, not keyed."

Doc sentences (RUNBOOK, where the app's CFD cache is described, if anywhere): "The CFD cache is keyed on the mesh, the case parameters and the solver settings of `cafe/cfd.py`; editing a setting makes the next run compute again. `python -m cafe._seed` seeds old validation runs: run it only for runs made with the present settings (it fills the new names, so after this change nothing seeded earlier is found)."

Limit, to state plainly (the lead decided "the constants"): the `fvSchemes`, `fvSolution`, `controlDict`, `transportProperties` and similar texts written inline in the bodies of `external()` and `free_surface()` are not module constants, so an edit of one of them is still not in the key. Moving them into named constants would put them in; not done (it changes the file that writes the case). Also: `hangar.py` passes call parameters only, so `level_offset`, `iters` and the like are in the key only when the caller puts them in its `key`.

Could break, and checked: callers `hangar.py:294, 300, 314` use the return value only; `_seed.py` calls `cached(k, stl, print, lambda: r)` and works as before, into the new names. Tests: `tests/test_cfd.py`: a changed value of each constant of `SETTINGS` (generic mutator per type) forces a recompute and the new recipe is cached in turn; NPROC is recorded and not keyed; the sweep over the module's upper-case names.

## M-24. Two ingests of one mission

DECISIONS row C7 (amends 883, which locks only `derived.zarr`): the ingest's shared stores are locked and written under unique names. `pipeline._shared_store(ctx, dir, name, what)` holds `surface.store_lock(dir, name)` while the GEBCO cut (`DATA/bathy/<cut>.npz.lock`) and, for a GOFS store, the ocean store (`DATA/ocean/<store>.zarr.lock`) are checked, fetched and checked again (`_need` runs under the hold, so the check after another run's fetch finds the store there and fetches nothing). The locks are beside the stores in DATA, not in the mission cache (`derived.lock`): both stores are shared across missions. A second ingest logs "ingest: another run is fetching <what> (<lock>); waiting for it" (`store_lock(..., wait=)`, called once and only when the lock is taken by someone else). A lab store is not locked (it is never fetched). Under `CAFE_OFFLINE` nothing is made (no directory, no lock file); a directory that cannot be made or written means no lock, as `store_lock` already did. Unique temporaries (`atomic.tmp_name`, `.<12 hex>.tmp`): `hycom.write_store` builds in a directory of its own and removes it on any exception (a kill -9 leaves it; `sync_filters` and `is_junk` ignore `*.tmp`; nothing deletes it); `hycom._fetch_part` (new, see "Changed by the finishing builder") gives each download child a name of its own and removes it whatever happened, `_child_ncss` / `_child_dods` write the name they are given (`O_EXCL` / `clobber=False`) and no longer rename; `bathy.fetch_gebco` and `orca._save` write through `atomic.write_with`. Not changed: `bathy`'s `window_check.npz` (the receipts' file) is still one name, but it is now replaced atomically.

CHANGELOG: "M-24: the ingest holds `<store>.lock` (DATA/ocean, DATA/bathy) over the check, fetch and check of the ocean store and the GEBCO cut and says when it waits; `write_store`, the download children, `fetch_gebco` and the orca `_save` write under temporaries of their own."

Doc sentences: RUNBOOK troubleshooting: "A second ingest of the same mission waits for the first and logs `another run is fetching ...`; `<store>.zarr.lock` and `<cut>.npz.lock` beside the stores are lock files, safe to leave." One line on the orphan: "A killed fetch can leave `.<12 hex>.tmp` beside the store; delete it by hand when disk is short."

Could break, and checked: `hycom.refuse_overlap` still refuses a source directory named `<store>.tmp` (that name is no longer the temporary; the refusal is harmless and its test, `tmp_sibling`, still passes; its docstring says "or its `.tmp` sibling" and is now historical). `bathy.cuts` filters the old `.part.npz` and lists only `gebco2026_*.npz`, so a lock file is not a cut. No other code lists `DATA/ocean` or `DATA/bathy`. Lock order: one lock at a time, never nested (GEBCO then ocean), and the fetch threads of `fetch_gofs` and `fetch_gebco` take none. The wait of a second ingest is as long as the first fetch (hours for the GOFS store): P-R16C2.

Tests: `test_r16_m24_*` in `test_remote.py`, `test_pipeline.py`, `test_hycom.py`, `test_bathy.py`, `test_orca.py`. The race itself is reproduced as a thread test (the first writer is held between its write and its rename while a second writer runs through), which fails on the unfixed code for `write_store`, `fetch_gebco` and `_save`.

## M-26. `cafe/cfd.py` hostile inputs

DECISIONS row C8 (amends 569 and 663; extends 330): (1) `cfd.external` and `cfd.free_surface` load the body with `cfd._body` before they delete the case directory: an empty mesh, or one with an extent of zero along any axis, is a `ValueError` naming the file ("flat or empty mesh"), with no relative threshold (a real foil is thin). (2) `external` calls `dvec` on every direction before the case is touched, so a mistyped label is found before the first `blockMesh`, not after the mesh. (3) `NPROC = par.env_count("CAFE_NPROC") or 6`: an empty or unset variable is 6, a bad one (`abc`, `0`, `-3`) is a `ConfigError` naming it (row 330), where the bare `int` was a `ValueError` at import for an empty one. Rows 569 and 663 say the bare `int` stays: that is reversed for CAFE_NPROC (not for CAFE_WORKERS, whose empty value is unset by design, 663). (4) `pipeline_windows.run` sets `CAFE_NPROC` to the planned ranks when it is unset or empty (it was `setdefault`, which left an empty one in place and made the ranks run differ from the ranks planned).

CHANGELOG: "M-26: `cafe.cfd` refuses a flat or empty mesh before it deletes the case directory, finds a mistyped direction before meshing, and reads `CAFE_NPROC` with `par.env_count` (empty is 6); stage 3 exports the planned ranks over an empty `CAFE_NPROC`."

Doc sentence for RUNBOOK 1 (where `CAFE_NPROC` is described): "An empty `CAFE_NPROC=` counts as unset, like `CAFE_WORKERS=`."

Could break, and checked: `cafe.cfd` now imports `cafe.pm.par` (numpy and the standard library only; no cycle: `par` imports nothing from `cafe.cfd`, and `cafe/pm/__init__.py` is light). In the live app image a bad `CAFE_NPROC` ends in `ModuleNotFoundError: yaml` (the `ConfigError` is in `config`, which imports pyyaml): P-R16C1, not fixed. `free_surface` got the same guard as `external` (the finding named `external` only): it deleted the case directory first too, and divided by an extent of zero. `characterize_external` calls `external` first, so a bad label in `dirs` fails in its coarse run before any work.

## Tests run

Fixed tree (orca, proot, 2 CPUs): Commands: `PM_TAKE=1 PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_r16c PM_CPUS=2 bin/pmx.sh ...` (2 CPUs, pinned). Logs on orca in `~/cafe-worker/logs/`.

- `ruff check cafe/pm tests`: All checks passed. `mypy cafe/pm`: no issues found in 55 source files (both on the final tree; a first ruff run flagged one 161-character line of my own edit in `tests/test_config.py`, fixed).
- `python -m cafe.pm audit --code-only` on the final tree: the banned-token scan and the commented-code scan report nothing (`tests/lockprobe.py` and the new tests included); the only problem is `mutation: no stored result at docs/mutation.json`, which this worktree does not have (not touched by this batch).
- Run 1 (`r16c_fixed`, `rc=0`, 1,583 passed, 0 failed, 0 skipped, about 80 min): `tests/test_cfd.py test_remote.py test_surface.py test_bathy.py test_orca.py test_hycom.py test_config.py test_round15_a.py test_round16_pb.py test_audit.py test_stage3.py test_pipeline.py`, every file whole. This ran on the inherited code before the finishing builder's change to `hycom.py` (below) and `tests/test_config.py`.
- Run 2 (`r16c_fixed2`, `rc=0`, 955 passed, 0 failed), on the final tree: `tests/test_hycom.py test_config.py test_ingest_fetch.py test_config_docs.py test_receipts.py test_round15_a.py test_bathy.py test_orca.py test_remote.py test_surface.py` with `--cov=cafe/pm/env`: `env/bathy.py`, `env/hycom.py`, `env/orca.py`, `env/remote.py`, `env/surface.py` at **100 %** (0 missed lines); the other `env` modules show their partial figures because their tests are not in this selection. `test_cfd.py`, `test_round16_pb.py`, `test_audit.py`, `test_stage3.py` and `test_pipeline.py` were not rerun on the final tree: nothing the change touched is read by them (`test_pipeline.py` replaces `hycom.fetch_gofs` by a stand-in).
- Not run: the whole suite (batch D / the lead's gate), a real `python -m cafe.ocean` child, two real ingests.

On the unfixed tree (a detached worktree at `ed3141d` with only the new test files copied in) the tests that name a fix fail: Run `r16c_base3` (`rc=1`, 51 passed, 45 failed), in a detached worktree at `ed3141d` with only the new and changed test files copied in (`tests/lockprobe.py`, `tests/test_cfd.py` and the edits of 10 test files), `-k "r16 or r15_l0_4 or p_r15a_3 or r15_every_json or bare"` over `test_cfd, test_remote, test_surface, test_bathy, test_orca, test_hycom, test_round16_pb, test_audit, test_stage3, test_pipeline, test_config`. Failed there, as they must:

- M-23, M-26 (`test_cfd.py`): all three `m23` tests (`AttributeError: recipe`/`SETTINGS`, `KeyError 'recipe'`), `NPROC` empty (`ValueError` at import), bad `NPROC` x3, flat mesh x2 and empty STL and thin body (`DID NOT RAISE ValueError` / no `_body`), mistyped direction x3 (`DID NOT RAISE`); `test_stage3.py::test_r16_m26_an_empty_cafe_nproc_...` (setdefault left the empty value).
- M-20 (`test_stage3.py`): the 7 new "refuse" rows of `test_r15_l0_4_...` (continuation at 3, 4, 5 spaces and after a blank line, three no-break-space rows); the three "returns 70" control rows pass on both trees by design.
- M-24: `test_remote.py::..._a_lock_of_another_name_...` (no `wait=`), `test_bathy.py` x2 (`FileNotFoundError` of the shared `.part.npz`; the planted link), `test_orca.py` x1 (`FileNotFoundError`), `test_hycom.py` x3 (`append_dim='time' does not match any existing dataset dimensions` in the first writer; the leftover `gofs_x.zarr.tmp`; `_fetch_part` missing), `test_pipeline.py::test_r16_m24_*` x3 (no lock held at the check; no `_shared_store`).
- S1/M-21 (`test_round16_pb.py`), `write_with` only: the four mode rows, the temporary-width test and the symlink test (the unfixed `write_with` made its temporary with the umask's mode and never looked at a link), and `test_r16_m21_...[write_with]`: on the unfixed code a temporary name that already exists makes `open(tmp, "xb")` fail, and then its `except BaseException: tmp.unlink()` deletes the file that was there (a real defect, found by this test, and gone with the shared function). The same tests for `write_text` pass on both trees (it already had these rules).
- S2: all four `test_r16_s2_*` and the changed sweep `test_p_r15a_3_...` (found `{ocean.py: 2, cfd.py: 1}`).
- `test_config.py::test_r15_every_json_the_app_reads_back_...` (the `ocean.py:os.replace` entry removed).

Passed on the unfixed tree, and why that is right: the five `m18` tests (M-18 is tests only: the production code was correct, the mutants below are the proof), `test_r16_s1_the_content_goes_through_the_descriptor_...` for both writers (neither unfixed writer opened its temporary twice by name; the test guards the shared function and is proven by two mutants, see below), `test_r16_m26_a_good_body_and_good_directions_go_on_to_the_case` (a control), and `test_r16_m20_the_layouts_..._pyyaml_does_not_give_70` (it asserts what PyYAML returns for the refused texts: a documentation test of the premise of the M-20 rows, not of cafe code). `test_config.py`'s `BARE_*` count test was not in the `-k` selection of this run; it is green in runs 1 and 2 on the fixed tree.. The tests that stay green there are the tests-only items (M-18, M-21 on `write_text`), the controls, and the S1 test that needs a mutant.

## Mutants

One edit at a time on a copy of the final tree (`cafe-r16c-mut` on `pm_r16c_m`, driver `mut_driver.py` kept out of the commit), the named tests run with `-x`, the file restored after each; logs `r16c_mut.log`, `r16c_mut2.log`. Every edit applied (each matched its text once). **All 21 killed, none survived.**

| Mutant (edit) | Killed by |
|---|---|
| M-18 `held.discard(path)` -> `pass` (remote.py) | `test_remote.py::test_r16_m18_a_lock_is_released_at_the_end_of_its_block_and_a_second_block_takes_it_afresh` (alone, `r16c_mut2`); also `test_surface.py::test_r16_m18_the_surface_layer_...` |
| M-18 null context for `Context.env` | `test_pipeline.py::test_r16_m18_context_env_checks_the_layer_and_loads_it_under_one_hold_of_the_caches_lock` |
| M-18 null context for `_derived_record` | `test_pipeline.py::test_r16_pa_two_runs_that_build_the_derived_layer_at_once_make_one_good_store` |
| M-18 null context for `_derived_current` | `test_pipeline.py::test_r16_pa_a_run_that_checks_the_layer_while_another_builds_it_waits_and_never_reads_half_a_store` |
| M-18 null context for `_derived_unchanged` | `test_pipeline.py::test_r16_m18_the_derived_unchanged_check_hashes_the_store_under_the_caches_lock` |
| M-18 null context for `surface.build` | `test_surface.py::test_r16_m18_the_surface_layer_is_written_read_and_measured_under_the_caches_lock` |
| M-18 null context for `store_span` | the same test |
| M-18 null context for `SurfaceLayer` | the same test |
| M-18 null context for `audit._tree` | `test_audit.py::test_r16_m18_the_audit_hashes_the_derived_layer_under_the_caches_lock_and_other_stores_without_one` |
| M-21 `O_EXCL` dropped | `test_round16_pb.py::test_r16_m21_a_temporary_name_that_exists_is_an_error_...[write_text]` (the `write_with` parameter is the same code) |
| S1 `write_with` writes by name (`open(tmp, "wb")`) | `test_r16_s1_the_content_goes_through_the_descriptor_...[write_with]` |
| S1 `write_text` writes by name (`_Created.open` -> `Path.open`) | `test_r16_s1_the_content_goes_through_the_descriptor_...[write_text]` |
| S1 `os.fchmod` -> `pass` | `test_r16_s1_an_existing_file_keeps_its_mode_...[436-63-436-write_text]` |
| S1 `elif p.is_symlink()` -> `elif False` | `test_r16_s1_a_symbolic_link_at_the_target_is_refused_...[write_text]` |
| S1 temporary mode `0o600` -> `0o666` | `test_r16_s1_a_temporary_is_never_readable_more_widely_...[write_text]` |
| M-24 lock removed from `_shared_store` | `test_pipeline.py::test_r16_m24_the_gebco_cut_and_the_ocean_store_are_checked_and_fetched_under_a_lock_beside_the_store` |
| M-24 `wait()` never called in `store_lock` | `test_remote.py::test_r16_m24_a_lock_of_another_name_...wait_is_called_only_when_someone_else_holds_it` |
| M-24 GEBCO cut not locked | the lock-beside-the-store test above |
| M-24 ocean store not locked | the same |
| M-24 `_fetch_part` leaves its temporary (`finally: pass`) | `test_hycom.py::test_r16_m24_a_part_is_fetched_into_a_temporary_of_its_own_that_never_outlives_the_call` |
| M-24 `write_store` does not remove its temporary on error | `test_hycom.py::test_r16_m24_a_store_write_that_fails_leaves_neither_a_store_nor_a_temporary_and_keeps_the_old_store` |

(The "seven edits" of the first draft of this section became nine for M-18: the four sites the finding named, its three siblings, `audit._tree` and the release; all nine are above, plus the `-remote-only` rerun of the release.)

## Changed by the finishing builder (after the inherited diff)

1. **Orphaned part files (a defect of the inherited M-24 change), `cafe/pm/env/hycom.py`.** The inherited `_child_ncss` / `_child_dods` wrote `<out>` through `atomic.tmp_name(out)` and renamed it themselves. A child killed at its deadline (`_child`: `subprocess.run(timeout=)`, the usual failure of a hung HYCOM server) cannot clean up, and with a name of its own per attempt every timeout, retry and server fallback left one half-downloaded `.<12 hex>.tmp` in `<store>.parts` (before: one fixed `<out>.part` that the retry overwrote, so the leak was bounded). `ncss` and the `.parts` directory are on a disk that is 97 % full. Now `hycom._fetch_part(args, path, deadline)` makes the name (`atomic.tmp_name`), runs `_child` into it, `os.replace`s it onto the part, and removes the name in a `finally` (so also after a kill or an error); the two children write the name they are given directly (`open(out, "xb")`, `netCDF4.Dataset(out, "w", clobber=False)`) and no longer rename. Callers changed: `fetch_gofs`' `one()` (both servers) and `check_node`. The inherited test of the children was replaced by `test_hycom.py::test_r16_m24_a_part_is_fetched_into_a_temporary_of_its_own_that_never_outlives_the_call` (real NCSS and DODS fetches, a planted link at the old `.part` name, a child that writes half a file and then fails or times out); killed by a mutant above and failing on the unfixed tree.
2. `tests/test_config.py`: `BARE_REPLACES["env/hycom.py"]` 3 -> 2 (one `os.replace` less after item 1), with its comment.
3. Reviewed and left as they were: `atomic._replace_through` (the descriptor is closed in the `finally` on every path; `O_EXCL` failure happens before the `try`, so a planted name is never unlinked; the file object over the descriptor uses `closefd=False`), `store_lock(wait=)` (the descriptor is closed in the outer `finally` if `wait()` or the second `flock` raises; `held` is added only after the lock is taken), `_shared_store` (locks are taken one after the other, never nested; `s_ingest` does not hold `derived.lock` at that point), `hycom.write_store` (temporary removed on any `BaseException`), `cfd.recipe()` and the `par.env_count` import (`cafe/pm/__init__.py` and `par.py` import numpy and the standard library only; no cycle).

## Incidents and side effects

- The first builder was cut off on 2026-11-12; the lead's coordinator message said a later turn of mine died on a network error (ENOTFOUND). Nothing was lost: the worktree and the logs were intact; the runs above were all repeated or completed after it.
- Orca: all jobs used `pm_r16c`, `pm_r16c_b`, `pm_r16c_m`, 2 CPUs, one at a time (another builder's jobs ran beside mine); logs `r16c_fixed`, `r16c_fixed2`, `r16c_base3`, `r16c_mut`, `r16c_mut2` (the first `r16c_base3` call died at once with `rc=4`: `bin/pmx.sh` splits arguments on spaces and the `-k` expression broke; it was rerun through a script). `pm_r16c_b`, `pm_r16c_m`, `pm_r16c_m2` were removed at the end, `pm_r16c` left.
- A ssh poll of mine timed out twice during the 80-minute run (exit 255/144); the job was unaffected (tmux).
- Not changed by me and noticed: `tests/test_receipts.py::test_r8_m31_...` still plants an old `gebco2026_*.npz.part.npz` (green; the name is no longer written by the code, the test only checks that a stray half file is not a cache).

## What I did not check

- A real `python -m cafe.ocean _slice` / `_axes` child, a real fetch from HYCOM, GEBCO or orca (no network from the worker), two real ingests racing: the race is reproduced with threads and held `flock`s only.
- The orphan the S2 change leaves when the `_slice` or `_axes` child is itself killed mid-write: `atomic.write_with` inside the child makes its own `.<12 hex>.tmp` that the parent cannot name (the parent removes only the name it handed over). Before the change the pid-named part file leaked the same way, so this is not a regression; the same holds for a `kill -9` of `write_store` (P-R16C2).
- The whole suite and the 100 % coverage gate of `physics`, `stats` and `env` in one run (the `env` figures above are for the five modules this batch changed, from a selection of test files); mypy/ruff only on `cafe/pm` and `tests` as the gate asks; `cafe/cfd.py`, `cafe/ocean.py`, `cafe/atomic.py`, `cafe/fea.py` are not under mypy (as before).
- The CFD cache key still omits the inline OpenFOAM texts (the limit stated under M-23) and `hangar.py`'s call parameters beyond what its `key` holds.

## Needs from other batches

- Batch D (documents): the DECISIONS rows C1 to C8, the amendments named above (817, 815, 872, 874, 880, 883, 569, 663, 330), the CHANGELOG lines, the RUNBOOK sentences (CAFE_NPROC empty; the lock files and the waiting line; the CFD cache key and `_seed`), STATUS if it lists the app's caches. `review/orca/PROBLEMS.md` has P-R16C1 and P-R16C2 (open); D should add their closing sentences.
- Batch A: no code. `tests/test_config.py` is edited by this batch in three places that batch A (M-28, `BARE_COPIES` for `physics/usv.py`) may also touch: the `env/bathy.py` and `env/orca.py` lines of `BARE_COPIES` (one comment each), the `BARE_REPLACES` line (`env/bathy.py` and `env/orca.py` removed, `env/hycom.py` now 2 (was 3: `write_store` and `_fetch_part`), `env/remote.py` kept), and the last line of `test_r15_every_json_the_app_reads_back...` (`"ocean.py:os.replace": 1` removed). They are neighbours of A's hunk: if git reports a conflict, keep both sides.
- Batch B: nothing.
- The lead (owner decisions): whether to move the inline OpenFOAM texts of `external()` and `free_surface()` into named constants so that the CFD key covers them (M-23 limit); whether `ConfigError` should live where the app image can import it (P-R16C1); whether to delete orphaned `.tmp` ocean stores (P-R16C2).
