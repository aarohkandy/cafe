# Round 7, batch O (ocean and cache readers): hand-back

Branch `r7-o`, worktree `/Users/aaroh/Downloads/everything/cafe-r7o`. Fixed: M-2, M-3, M-12, M-17, M-24, M-30, M-31, M-36, M-46 (`GriddedEnv` docstring only). Not fixed: none.

## Per finding

### M-3 (hycom.py `fetch_gofs`, `assemble_gofs`)
- `fetch_gofs` (hycom.py ~299-330): new keyword `log` (default `print`). When the old manifest has parts and its `box` differs from the requested one, it logs "the ocean parts were cut to {old}, this fetch asks for {box}: all {n} parts are fetched again" and drops every recorded part. The manifest already carried `box`; it is now compared.
- `assemble_gofs` (~370-405): `xr.concat(..., join="exact")`; a `ValueError` becomes "the {d} parts in {pdir} were cut to different boxes (...); delete {pdir} and run fetch again". Each part's lat/lon is rounded to 4 decimals before the concat (the rounding used to come after it), so a float32 NCSS part and a float64 OPeNDAP part of the same box still align.
- Tests (tests/test_hycom.py, end): `test_r7_m3_a_changed_box_fetches_every_part_again_and_the_store_has_no_holes_of_the_old_box`, `test_r7_m3_a_grown_box_asks_the_server_again_and_the_same_box_still_asks_for_nothing`, `test_r7_m3_parts_cut_to_different_boxes_are_refused_not_joined_into_holes` (runs with FutureWarning as error). The whole hycom file also ran with `-W error::FutureWarning`.
- Before (unfixed tree): store step 0 has a NaN mask different from the truth in `water_temp`; grown box makes 0 requests (9 expected); the mixed-box assemble emits xarray's `FutureWarning` (join outer to exact). After: all pass.

### M-30 (hycom.py `assemble_gofs`)
- All parts are opened first; any that cannot be opened, or has no time step, is deleted with its manifest entry (manifest rewritten) and a `FetchError` is raised: "the part {fn} was unusable ({reason}); it has been removed: rerun fetch to download it again" (several: "...; they have been removed: ... download them again"). All bad parts go in one pass so the rerun is one fetch, not one per attempt.
- Tests: `test_r7_m30_an_unusable_part_is_removed_with_its_entry_and_the_rerun_downloads_it_again` (stand-in server `Ncss.empty`, new attribute; the reviewer's `OSError: NetCDF: Unknown file format`; rerun asks only for `uv3z`), `test_r7_m30_a_part_with_no_time_step_is_unusable_too` (valid NetCDF with empty unlimited time; one and two bad parts).
- Before: the first run fails with a raw OSError and the rerun makes 0 requests. After: pass.

### M-24 (hycom.py `gofs_steps`, ocean.py, environment.py)
- `gofs_steps` (hycom.py:86): floor(t0) to ceil(t1) on the 3 h grid. An aligned window gives the same list, so q7's cache and the golden do not move. `fetch_gofs` docstring updated.
- `Ocean.inside(lon, lat, t=None)` and `Ocean.bounds()` (ocean.py:64, :72). `GriddedEnv.inside` ANDs the ocean's `inside` when the ocean has one (environment.py:161); `_check` takes optional `bounds`; new `_ocean_check` is called by `current`, `density`, `sound_speed`, so a strict environment raises `OutsideData` ("ocean current: ... is outside the ingested data") and a lenient one holds the edge while `inside` says False.
- Tests: `test_r7_m24_the_steps_cover_the_window_and_an_aligned_window_gets_its_own` (hycom), `test_r7_m24_ocean_inside_tests_the_stores_lat_lon_and_time_axes_and_bounds_names_them` (ocean), `test_r7_m24_inside_is_false_where_the_ocean_store_ends_and_a_strict_env_raises_there` (environment).
- Existing tests whose expectation changed, because they asserted the old behaviour: `test_steps_and_epoch` (a 13:00-14:00 window had no step, now [12:00, 15:00]) and `test_fetch_refuses_an_empty_window` (a window between two steps used to be empty and would now start a real fetch; it now uses an end a day before the start, which still gives no step).
- Before: `Ocean` has no `inside`; `GriddedEnv.inside` stays True 1 h past the store's end. After: pass.
- Note for the lead: `pipeline._ustar_agreement` and `_round_trip_errors` filter their sample points with `env.inside`; they now also drop points outside the ocean store (at most the 0.1 deg grid snap at the edge). Their tests and the CI fixture pass unchanged; atmosphere-only callers that want the old meaning would need an argument.

### M-36 (hycom.py `read_lab_netcdf`, `ingest_lab_hycom`)
- z-level files are sorted by depth ascending before use (hycom.py:513). `ingest_lab_hycom` refuses, with a `ConfigError` naming the file, any of water_temp/salinity/water_u/water_v that is entirely NaN at a time step: "{file}: every value of water_temp is NaN after reading (time ...; check the depth axis and the variable names)".
- Tests: `test_r7_m36_a_z_level_file_listing_depth_deepest_first_reads_like_the_ordered_one`, `test_r7_m36_a_lab_file_whose_field_is_all_nan_is_refused_with_the_file_named`.
- Before: depth stays descending (and the values are NaN), no error. After: pass.

### M-17 (orca.py `hours`, pipeline.py comment)
- `hours(t0, t1)` returns floor(t0) to ceil(t1) on the hour, `[]` if t1 < t0. Comment (docstring of `fetch_orca`) says the ingest holds the whole hours that cover the window.
- Tests: `test_r7_m17_hours_are_the_whole_hours_that_cover_the_window`, `test_r7_m17_a_half_hour_window_builds_a_time_axis_equal_to_the_file_stamps`. Changed existing assertion in `test_stamp_hours_urls`: 119 minutes from t(0) gave `[t0, t1]`, now `[t0, t1, t2]`, since 119 minutes reach into the third hour's file.
- Before: axis labelled 00:30...; 6 hours instead of 7. After: pass.

### M-31 (orca.py `ingest`)
- On the first exception, `ex.shutdown(wait=True, cancel_futures=True)`, every finished, uncancelled, successful future not yet saved is saved, then re-raise.
- Test: `test_r7_m31_a_failed_part_stops_the_rest_and_keeps_the_finished_ones` (7 wrf + 7 umwm jobs, 2 threads, hour 1 raises; at most 3 wrf jobs complete, finished ones are on disk).
- Before: 6 wrf jobs ran after the failure. After: at most 3.

### M-2 (pipeline.py `_derived_unchanged`, surface.py `SurfaceLayer.__init__`)
- `_derived_unchanged`: a `GriddedEnv` whose `subgrid` is None records a failed `derived_unchanged` ("{store} is missing or has another layout: ingest recorded it as an input of this run; rerun `python -m cafe.pm fetch --mission ...` and the run"); analytic environments still record nothing. I did not move the hash before `ctx.env`: with the `SurfaceLayer` fix a damaged store raises the `ConfigError` from `ctx.env` (exit 2 through the CLI's `ConfigError` handler), so the order no longer matters.
- `SurfaceLayer.__init__` wraps open and `.load()`: `ConfigError("derived surface layer {store} cannot be read ({type}: {msg}); delete {store} and run `python -m cafe.pm fetch --mission ...` again: only it is rebuilt")`.
- Tests: tests/test_surface.py `test_r7_m2_a_truncated_chunk_of_the_derived_layer_is_a_config_error_naming_it`; tests/test_pipeline.py `test_r7_m2_a_missing_or_old_layout_derived_layer_fails_derived_unchanged_instead_of_running_on_the_neutral_profile` (old layout, missing, stage fails, analytic env records nothing), `test_r7_m2_a_truncated_chunk_of_the_derived_layer_stops_the_context_with_a_config_error`.
- Before: no check recorded; RuntimeError (zstd) from zarr. After: pass.

### M-12 (pipeline.py `_ocean_cached`, plus its call in `s_ingest`)
- New `_ocean_time_problem(times, window)` (pipeline.py:286). `_ocean_cached(path, box, steps, window=None)`: with a `window` (lab store) the time test is coverage (first time <= start, last >= end), otherwise GOFS step membership as before.
- Call site in `s_ingest` (the finding names it, lines 383-386 of the old file): `window` is None for gofs31 and the mission window for a lab source; the `ocean_store` `_need` call passes it, and its `what` text gets " (its times span A to B UTC, the window is C to D UTC: the store ends 24.0 h before the window end)" when a lab store exists but does not cover the window. This shows in both the offline note and the "fetching ... failed" note. `fetch_ocean`'s own message is unchanged. These are the only lines of `s_ingest` I touched (plus the M-17 comment in `fetch_orca`), please keep them in the merge with C's `ocean_box` message.
- Tests (tests/test_pipeline.py): `test_r7_m12_a_six_hourly_lab_store_covers_the_window_and_is_cached_while_gofs_still_wants_every_step`, `test_r7_m12_ingest_accepts_a_six_hourly_lab_store_and_a_store_that_ends_early_fails_naming_the_edge`. tests/test_ingest_fetch.py (the existing `_ocean_cached` test) passes unchanged.
- Before: `_ocean_cached` takes no window; the 6-hourly store fails `ocean_store_present`. After: pass.

### M-46 (environment.py docstring)
- Docstring now: "the WRF fields alone are 6 days x 130 x 313 x 16 x 8 bytes = 0.76 GB in float64; with UMWM and the ocean the demo's environment is about 9 GB in memory, DECISIONS 267/270, measured". Test: `test_r7_m46_the_docstring_sizes_the_wrf_fields_in_float64_and_gives_the_measured_total` in tests/test_environment.py (tests/test_config_docs.py is not in my file list; the lead may move it there). Before: fails on the old docstring. After: pass. `WORKER_GB` is batch P's.

## Fail-first proof
Throwaway detached worktree of `premission-step4` with only my six test files copied in (removed afterwards), on homebase (`pm_r7o_old`): every new `r7_` test and the three changed existing tests failed (19 failures across hycom, orca, ocean, environment, surface, pipeline in the first run; the M-3 tests re-run without the new `log` keyword showed the NaN-mask mismatch, 0 requests, and the xarray FutureWarning; the M-46 test failed on the old docstring). On the fixed tree they pass.

## Docs and records (for the lead)

DECISIONS rows (number from 341):
- `| ? | The manifest of GOFS parts pins the box: a fetch for another box fetches every part again and logs it; parts are joined with join="exact" and a store of two boxes' parts is refused. | Review round 7, M-3. Amends row 22. Part names and hashes alone made a changed box reuse parts cut to the old one, and xarray's outer join turned them into NaN holes (0.468 against 0.024 NaN share in the demo). |`
- `| ? | An unusable GOFS part (unreadable, or no time step) is deleted with its manifest entry by assemble_gofs and raises FetchError telling the user to rerun fetch. | Review round 7, M-30. The part was recorded by hash and never fetched again. |`
- `| ? | gofs_steps returns the 3-hourly steps that cover the window (last at or before the start, first at or after the end), Ocean.inside tests the store's lat, lon and time axes, GriddedEnv.inside includes it and a strict environment raises OutsideData for an ocean query outside the store. | Review round 7, M-24. Amends row 22 ("the 3-hourly steps inside"). Ocean returned the edge value with no flag; an aligned window has the same steps as before, so q7 and the golden do not move. |`
- `| ? | A lab HYCOM store is cached when its time axis covers the window (first time <= start, last >= end); the failed check names the short edge. GOFS keeps the step-membership test. | Review round 7, M-12. Amends the check of row 22 for lab stores. A 6-hourly lab store could never contain the 3-hourly steps and the documented route looped. |`
- `| ? | read_lab_netcdf sorts a z-level file by depth ascending and ingest_lab_hycom refuses a field that is entirely NaN at a time step, naming the file. | Review round 7, M-36. A deepest-first file ingested as an all-NaN ocean. |`
- `| ? | orca.hours is the whole hours that cover the window (floor of the start to ceil of the end); the ingest of a failed part cancels the queued parts and saves the finished ones. | Review round 7, M-17 and M-31. A 12:30 start read the 12:00 file labelled 12:30; the pool ran every remaining part to completion and discarded them. |`
- `| ? | A missing or old-layout derived.zarr fails the derived_unchanged check of a gridded environment; an unreadable one is a ConfigError. | Review round 7, M-2. Completes row 238. |`
- M-46: row 281's date correction and the `WORKER_GB` comment are batch P's; the `GriddedEnv` docstring needs no row.

CHANGELOG lines: one per finding, same wording as the row (M-3, M-30, M-24, M-12, M-36, M-17, M-31, M-2, M-46 "GriddedEnv docstring sizes the WRF fields at 0.76 GB in float64").

RUNBOOK (docs/RUNBOOK.md, quoted exactly):
- Ocean section: "Changing `box` or `pad_deg` downloads the ocean again (the parts are reused only for the box they were cut to)."
- Step 4 (lab ocean): "The files must span the window; any regular cadence works (the ocean is interpolated linearly in time); GOFS is 3-hourly."
- Ingest/window section: "The ingest holds the whole hours that cover the window (a start at 12:30 reads the 12:00 file)."
- Troubleshooting row for `derived.zarr`: "derived surface layer ... cannot be read, or `derived_unchanged` says the layer is missing or has another layout: delete `cache/<mission>/derived.zarr` and run `python -m cafe.pm fetch --mission M`; only it is rebuilt (about a minute)."

## Needs from other batches
- `tests/test_config_docs.py`: optional, my M-46 docstring test lives in tests/test_environment.py instead.
- Nothing else. No change to `fetch_ocean`'s message was needed.

## Commands run (homebase, `PMX=pm_r7o PM_CPUS=1`, 8g or 12g)
- `pytest -W error::FutureWarning tests/test_hycom.py tests/test_orca.py tests/test_ocean.py tests/test_environment.py tests/test_surface.py`: exit 0 (final run after the last edit).
- `pytest tests/test_pipeline.py tests/test_ingest_fetch.py` (whole files, 12g): exit 0 (before the last comment-length and docstring-test edits); after them `pytest -k r7_ tests/test_pipeline.py`: exit 0.
- `ruff check cafe/pm tests bench`: All checks passed. `mypy cafe/pm`: no issues in 54 source files.
- Coverage (`--cov=cafe.pm.env --cov=cafe.pm.pipeline` over hycom, orca, ocean, environment, surface, ci_env, perturb_env, ingest_fetch, pipeline tests): environment.py, hycom.py, ocean.py, orca.py, surface.py 100 %; pipeline.py misses lines 69-74, 79-80, 100, 125, 1240-1241, 1323, none of them in code I changed.
- Banned-token scan of the diff: no hits. No container or tmux session of mine is left on homebase; `~/work/cafe/pm_r7o_old` removed.
