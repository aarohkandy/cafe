# Round 9, batch F handback (branch r9-f): environment stores

Commits on r9-f, in order: M-6 and M-38 (one commit, same function), M-5, M-35. Each regression test was run on the unfixed code (detached worktree at 91c9777 with only the new test files and, for M-35, `config/assumptions.yaml` copied in) and failed there; all pass on r9-f. DECISIONS numbers below are left as `N` for the lead to assign (last row at 91c9777 is 460).

## M-6. orca.assemble keeps every hourly part open

DECISIONS row: `orca.assemble` reads the hourly parts through one helper, `_stack`, which opens each `.npz` in a `with` block, copies the keys it needs and closes it; no part stays open while the next is read, so a 30-day window (about 1,440 parts) needs a handful of descriptors instead of one per part. `bytes_fetched` is summed from the `_bytes` of the same read (no retained handle). The container descriptor limit is not raised. Test: `tests/test_orca.py::test_r9_m6_assemble_closes_each_part_so_a_30_day_window_fits_a_descriptor_limit_of_256` (720 hours, RLIMIT_NOFILE 256).

Amends: 192 (it says a 30-day fetch should work; this is what made it true past about 500 hours). No row contradicts.

CHANGELOG: `orca.assemble` closes each hourly part as it reads it; a window of 21 days or more no longer ends in `OSError: Too many open files` (review round 9, M-6).

Doc sentences: none needed beyond the CHANGELOG line; if RUNBOOK or ORCA_RUNNER mention a window limit or a raised ulimit for orca, remove it.

Checked could break: callers of `assemble`: only `orca.ingest` (grep over cafe, tests, bin). The values written are the same arrays (`np.stack` of the same keys in the same order), so `test_ingest_end_to_end` (compares every variable to the fixtures, the manifest part hashes and `bytes_fetched`) is the guard; it passes. Peak memory is unchanged: one stacked array per variable plus the list of its slices, as before.

## M-38. assemble overwrites the stores before it replaces the old manifest

DECISIONS row: `orca.assemble` unlinks `out/manifest.json` (`missing_ok`) immediately before the first `to_zarr`, so while the stores are being rewritten there is no manifest; `read_json` returns None for it and `pipeline._orca_covers` is False, which is the "fetch again" path of 315. The hourly parts are kept, so the next `ingest` re-assembles without a fetch. The manifest written at the end is the only record that all four stores are from one window. Test: `tests/test_orca.py::test_r9_m38_a_failed_assemble_leaves_no_manifest_so_the_half_rewritten_cache_is_never_trusted` (`to_zarr` raises on `umwm.zarr` after `wrf.zarr` was rewritten: no manifest; the rerun logs `7 cached, fetching 0` and writes a manifest).

Amends: 315 (manifest written atomically; add that it is also removed before the stores are rewritten).

CHANGELOG: `orca.assemble` removes the old manifest before it rewrites the stores, so a failure part-way leaves no manifest that vouches for a half-new cache (review round 9, M-38).

Doc sentences: ORCA_RUNNER or RUNBOOK troubleshooting: "A cache with no `manifest.json` but with `hours/*.npz` is an assemble that was interrupted; run `fetch` again: it re-assembles from the parts without downloading."

Checked could break: (1) a failure while reading the parts (before the unlink, e.g. a missing wrf part) leaves the old manifest and the old stores untouched: unchanged and correct. A failure after the unlink (the first store write onward) costs the manifest; the price is a re-assembly, no fetch. (2) The ledger `tree_sha256` of the orca cache is taken at ingest after a successful assemble, so it sees the new manifest. (3) `pipeline.orca_covers` logs "unreadable" only when the manifest exists and is unreadable; with the manifest absent it stays silent and fetches, as for a first run. No change needed in pipeline.py.

## M-5. ingest_lab_hycom deletes the lab's source directory

DECISIONS row: two guards in `cafe/pm/env/hycom.py`, both before any read. (a) `refuse_overlap(out_zarr, source)`: with both paths `resolve()`d, a `ConfigError` naming both when the store, or its `.tmp` sibling (which `write_store` also rmtrees), is the source, holds it, or lies inside it (conservative: a store inside a source directory is refused although it would be safe). It is called at the top of `ingest_lab_hycom` (source = `path`) and of `assemble_gofs` (source = the parts directory, the only other `write_store` caller path with an input directory). (b) `write_store` itself refuses, before consuming any step, an existing `out_zarr` that is a non-empty directory with neither `zarr.json` nor `.zgroup`; an empty directory, a missing path and an existing Zarr store (v3 `zarr.json`, or v2 `.zgroup`) are replaced as before. `__main__._ingest_ocean` and config.py need no change. Tests: `tests/test_hycom.py::test_r9_m5_*` (five parametrised overlaps incl. a symlink and the `.tmp` sibling, the single-file source whose directory is the store, the GOFS parts, and the non-store directory plus the replace cases).

Amends: 376 and 422 (both describe `ingest_lab_hycom`'s refusals before anything is written); 21 (`ingest-ocean` writes the lab store; add that it refuses a store path that overlaps its source). No row contradicts.

CHANGELOG: `ingest-ocean` / `ingest_lab_hycom` refuse a store path that is, holds or lies inside the lab source directory (resolved, so symlinks count), and `write_store` refuses to replace a non-empty directory that is not a Zarr store; before, the success message came after the snapshots were deleted (review round 9, M-5).

Doc sentences: RUNBOOK step for `ingest-ocean`: "The store path (`environment.ocean.path`) must be outside the directory you pass as `--path`, and not its parent; the command refuses it, because replacing the store deletes the old directory at that path." And: "A path that exists, is not empty and is not a Zarr store is refused: move it away first."

Checked could break: other `rmtree` sites (grep over cafe, bin): `pipeline.py:463` removes `derived.zarr` of its own cache (no source); `cafe/app.py`, `cfd.py`, `fea.py`, `acceptance.py`, `par.py`, `dtmb5415.py`, `pipeline_windows.py` remove their own scratch or case directories, not a caller-named input; bathy has none. `write_store` callers: `fetch_gofs` -> `assemble_gofs` (out_dir/name.zarr beside a parts dir, never overlapping), `ingest_lab_hycom`, `tests/fixtures/ci_env/make.py`, and two tests in `test_pipeline.py` that write to fresh paths; all pass. A hazard I accepted: an old store written by zarr v2 code has `.zgroup` and is still replaced; a directory made by something else that happens to be empty is replaced. Not covered: a store path that is a file (rmtree ignores it and `os.replace` then fails with its own error, as before).

## M-35. bathy.from_gofs sigma 0 at the last level and no half-spacing term

DECISIONS row: `bathy.from_gofs` takes the floor of a node wet at level k and not at k+1 to be uniform in [z_k, z_k+1): depth = z_k + spacing/2, sigma = spacing/sqrt(12) (both computed). A node wet at the store's last level (5000 m for GOFS) has an unbounded floor: depth is that level, stated as a lower bound, and sigma is `bathy.gofs_open_level_sigma_m` (new key in `config/assumptions.yaml`, 1000 m, with a `why`: abyssal plains mostly 4000-6500 m, trenches to 11000 m; replace_with: not needed once GEBCO is cached). Land stays depth 0, sigma 0. The source string is "HYCOM GOFS 3.1 deepest valid level plus half a level spacing (a lower bound where the last level is wet)". Tests: `tests/test_bathy.py::test_gofs_floor_is_the_level_plus_half_a_spacing_with_the_uniform_sigma_and_the_last_level_is_a_lower_bound` (replaces `test_gofs_floor_is_the_deepest_valid_level_with_its_quantization`, which pinned sigma 0 and the unshifted depth) and the amended `tests/test_ocean.py::test_open_ocean_falls_back_to_the_gofs_floor_when_no_gebco_cache_matches` (1000 / 0 / 110 and sigma 1000 / 0 / 20/sqrt(12)).

Amends: 27 (the order is unchanged; its text "the deepest valid GOFS level" becomes "the deepest valid level plus half a spacing, a lower bound at the last level"). 99 only names the four inputs and needs no change.

CHANGELOG: `bathy.from_gofs` (GEBCO-missing fallback) reports the floor at the deepest valid level plus half a level spacing with sigma spacing/sqrt(12), and a node wet to the last level (5000 m) as a lower bound with the assumed sigma `bathy.gofs_open_level_sigma_m` = 1000 m; before, it reported the level itself and sigma 0 at 5000 m (review round 9, M-35). Seafloor-contact numbers from the GOFS fallback move by up to half a level spacing deeper.

Doc sentences: PHYSICS.md:439 table row 2 becomes: "floor between the deepest valid level and the next: level + spacing/2 (GOFS levels are 5-1000 m apart); where the last level (5000 m) is wet the depth is a lower bound | 0.08 x 0.04 deg | spacing/sqrt(12), computed; the open last level has the assumed `bathy.gofs_open_level_sigma_m` = 1000 m". Also bathy.py's module docstring was updated by this batch.

Checked could break (trace of everything that reads the depth and sigma): `Bathymetry` is built only by `from_gofs`/`from_gebco`/`from_umwm`; `choose` picks the first that works; `ocean.open_ocean` passes only the GOFS store, so the GOFS answer reaches `Ocean.bathymetry` -> `GriddedEnv.depth`. Readers of `.value`: `glider.py:373` and `:474` (dive depth and the `seafloor` flag), `stage1.py:525` (water depth), `report.py:662` (land mask `value <= 0`). Nobody in cafe/pm reads `.uncertainty` of the depth except tests; the source string reaches the report through the Tagged. Effects: (1) glider floor is deeper by up to half a level spacing, so fewer `seafloor` flags from the fallback (GEBCO runs are unaffected); (2) a node wet only at the surface level was depth 0 (read as land by the report mask) and is now half the first spacing; that is the correct reading of "wet at the surface"; (3) the open-level sigma is a constant, so for a lab store whose last level is shallow (the 1500 m test fixture, the 1000 m CI store) the same 1000 m applies: it is a deliberately large number, stated in the `why`, not a fit. `test_credibility` and `test_report` iterate every `assumptions.yaml` key and need no edit for the new key (both pass). `ASSUMED` in bathy.py now has three keys; no other module imports it.

## needs from other batches

None. M-5's guard sits in hycom.py, so `__main__.py` and `config.py` (batch A) need no edit; M-38 reads `pipeline.orca_covers` and needs no change there. One cross-batch file note: `tests/test_ocean.py` is outside the batch's file list but its GOFS-fallback test pinned the old depth (1000/0/100) and was amended in the M-35 commit; no other batch should be editing that test.

## Not done / not verified

- The full 75-minute suite and the mutation run were not run; only the touched test files and the callers' files named in the final report.
- No real 30-day orca fetch (the finding's own check did not run one either): the test uses 720 synthetic hours under a 256-descriptor limit.
- A truncated store after a kill mid-write (M-38) was not reproduced, as in the finding.
