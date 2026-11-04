# Round 8, batch E hand-back (environment readers and ingest checks)

Fixed: M-1 (ingest side), M-2, M-24, M-29, M-30, M-31, M-33, M-34. Not fixed: none.
Worktree `/Users/aaroh/Downloads/everything/cafe-r8e`, branch `r8-e`. The unfixed code for the before-runs was a detached worktree at eaf0e27 with only the five test files copied in.

## M-1 forcing plausibility gate (cafe/pm/pipeline.py, config/assumptions.yaml)
- `_forcing_range` (pipeline.py:559) and the new ledger check `forcing_in_physical_range` in `_ingest_checks` (:651): WRF 10 m wind speed (hypot of U10, V10, at most 100 m/s, every cell), WRF SST (271 to 315 K, at water cells by `Wstatic["LANDMASK"] < 0.5` when the cache has it, so land cells are not judged), UMWM swh (0 to 30 m) and ust (0 to 5 m/s) at sea nodes. "Outside" = not finite or out of bounds. value = number outside, limit 0, note names each field, the count and the worst value. The four bounds are `ingest.wind_speed_max_ms`, `ingest.swh_range_m`, `ingest.sst_range_k`, `ingest.ust_range_ms` in config/assumptions.yaml (each with unit, `why` "Gross-error bound, not a model of the weather ...", `replace_with`).
- u* finding (:666): `USTAR_AGREE_FRACTION = 0.90` (:582); when `coare_ustar_vs_umwm_ust`'s fraction within 20 % is below it the ledger gets "BRIEF 2.1 finding: only {x} % of the {n} sea points have COARE u* within 20 % of UMWM ust; the brief asks 90 %". The check itself stays unthresholded (row 168).
- Honest limit of the gate: winds x 3 (about 21 m/s) are inside 100 m/s and pass `forcing_in_physical_range`, exactly as merged.md says; what catches them is the u* fraction (0.0 %), which is the note above and K's Data pedigree rule.
- Tests (tests/test_pipeline.py, end): `test_r8_m1_the_forcing_check_passes_on_the_fixture_and_records_its_bounds`, `..._one_cell_outside_the_gross_error_bounds_fails_..._worst_value` (U10 = 500, swh = -3, SST = 0 at a water cell, ust = 9; 4 cases), `..._a_land_cell_of_wrf_sst_is_not_judged_and_a_nan_is_counted...`, `..._a_ustar_agreement_below_the_briefs_90_percent_is_a_finding...` (ust x 0.1: fraction below 0.1, check ok, note present; fraction 0.95: no note).
- Before (unfixed code): all 7 fail (no check, no note). After: pass. Existing test changed: `test_the_ingest_checks_all_pass_on_the_fixture_and_record_numbers` lists the exact check names in order; `forcing_in_physical_range` is now the 5th (after `no_nan_in_sea_cells`). Nothing was weakened.

## M-2 ocean time cadence (pipeline.py)
- `OCEAN_MAX_STEP_S = 86400.0` (:293), `_ocean_steps` (:296), `_ocean_cadence` (:303), `_ocean_time_problem(times, window, max_step_s)` (:309): drops non-finite times, sorts, empty -> "the store has no finite times", coverage message unchanged, else the largest step between the last time at or before the window start and the first at or after its end must not exceed the limit ("its largest step inside the window is {h} h (from A to B UTC), more than the {limit} h limit: the current would be a straight line across it; ingest a store with a shorter cadence"). `_ocean_cached` and the `short` text in `s_ingest` use it unchanged.
- Ledger check `ocean_time_cadence` in `s_ingest` (:450), always recorded (GOFS too): value = largest step in hours, limit 24, note "median {m} h, largest {x} h ...".
- Tests: `test_r8_m2_a_lab_store_with_a_step_over_a_day...` (6 d apart, 5.75-day hole, empty, all-NaN, NaN dropped, unsorted, 3 h / 6 h / daily pass, `max_step_s` override, `_ocean_cadence`), `test_r8_m2_a_stored_lab_ocean_with_a_36_hour_step_is_not_cached_and_a_daily_one_is` (`_ocean_cached`), `test_r8_m2_the_ingest_records_the_ocean_time_cadence_for_gofs_and_for_a_lab_store` (3 h and 6 h). Before: fail (None / ValueError / no check). After: pass. The existing 6-hourly test passes unchanged.
- Note for the lead: an unsorted or duplicated store written by the OLD `ingest_lab_hycom` still passes `_ocean_time_problem` (it sorts, as merged.md says) and is rejected later by `Ocean` (raw ValueError, as today). M-30 stops new ones at ingest; I did not add a sortedness test here.

## M-24 non-increasing cached time axis (cafe/pm/env/environment.py, pipeline.py)
- `GriddedEnv.__init__` builds its six WRF/UMWM axes through a local `axis()` (environment.py:74) that turns the `Axis` ValueError into the same `ConfigError` family as an unreadable file: "environment cache file {cache}/orca/{store}: axis time: must be strictly increasing (a repeated or reversed value); delete {cache}/orca and run `python -m cafe.pm fetch --mission ...` again ...".
- `_ingest_checks` (:633) catches that ConfigError from `ctx.env`, records `time_axes_hourly_gap_free` as failed with its text and returns False; `s_ingest` (:462) stops there (`_tao` would build the env again). `_ingest_checks` now returns bool.
- Where the surface layer still has to be built, `surface.build(ctx.env)` raises the ConfigError itself: exit 2 with an `error:` line naming the store (test below).
- Tests: tests/test_environment.py `test_r8_m24_a_repeated_or_reversed_axis_value_is_a_config_error...` (4 cases: wrf time, umwm time, wrf lat, umwm lon); tests/test_pipeline.py `test_r8_m24_a_repeated_time_stamp_in_the_cached_wrf_fails_the_hourly_check...` (warm ingest, then broken: StageFailed on the check, only that check failed) and `test_r8_m24_the_ingest_that_has_to_build_the_surface_layer_ends_in_a_config_error...`. Before: bare ValueError (all 6 fail). After: pass.

## M-29 coarse lab grids (cafe/pm/env/hycom.py)
- `_cut` (:669) and `_sub` (:690): the pad cut as before, plus the nearest point beyond an edge when the nearest kept one lies more than 0.1 deg inside it; when no point lies in the pad but the grid reaches both sides, both neighbours are kept (a grid coarser than the box); a grid that does not reach both sides keeps nothing and `_sub` still raises "no lab-HYCOM points inside the box". The longitude ranking uses the coordinate unwrapped around the box centre, so the dateline works whatever the file's convention.
- Tests (tests/test_hycom.py): `test_r8_m29_the_cut_of_a_coarse_lab_grid_always_brackets_the_box_to_the_ingest_checks_tolerance` (steps 0.25, 0.5, 1.0 deg, 8 offsets each, lon in 0..360 and in -180..180; asserts the exact `_ocean_cached` edge conditions, increasing axes, at most one extra point per edge) and `test_r8_m29_a_fine_grid_is_cut_as_before`. Before: all 6 parametrized cases fail; after: pass. The unthinned fixture's store is unchanged (the existing round-trip tests pass).
- Test deviates from merged.md's wording ("the fixture thinned by 4 and 5"): a thinned fixture file has no points beyond the box to keep, so no cut could bracket it; a synthetic wider coarse grid tests the cut itself.

## M-30 lab snapshots by time (cafe/pm/env/hycom.py)
- `_snapshot_times` (:703) reads the time steps of a netCDF (time coordinate of the temperature variable) or an archv stem (`.b` day) without the fields; `ingest_lab_hycom` (:735) sorts files by their first time (unreadable files keep name order, the reader then reports them) and raises "{a} and {b} are the same time ({t} UTC); remove one" (file names) before anything is written.
- Tests: `test_r8_m30_snapshots_go_into_the_store_by_time_not_by_file_name` (reversed names; snap_9 / snap_10), `..._the_same_snapshot_twice_is_refused_naming_both_files` (and a single snapshot still works), `..._a_file_whose_time_cannot_be_read_is_left_to_the_reader_to_name`. Before: store times reversed / no error / AttributeError; after: pass.

## M-31 receipts read a `.part.npz` (cafe/pm/env/bathy.py:175, cafe/pm/receipts.py:348)
- `bathy.cached_cuts(dir)` lists finished cuts only; `receipts.jobs` uses it. Test (tests/test_receipts.py) `test_r8_m31_a_part_file_left_by_an_interrupted_gebco_fetch_is_not_the_cache`: only a `.part.npz` gives the "GEBCO cache not found" context row. Before: fails; after: passes. (`bathy.choose` never globbed, so it needed no change.)

## M-33 old orca cache labelling (cafe/pm/env/orca.py:77, 357; pipeline.py:500, 506)
- Manifest records `layout_version = orca.LAYOUT_VERSION` (2). `_old_orca_layout(d, t0)` = no current version and the window start is not on the hour; `_orca_covers` refuses it, and `s_ingest`'s `orca_covers` logs "orca manifest ... was made by older code (its hour labels are shifted for a window that starts at :30): fetching again". An old manifest for an on-the-hour window is accepted (identical labels): the demo and q8 are unchanged. The CI fixture's manifest is written by the current code, so it carries the version.
- Tests: `test_r8_m33_an_orca_cache_of_the_old_hour_labelling_is_reused_only_for_a_window_that_starts_on_the_hour` (4 cases), `test_r8_m33_ingest_says_why_it_fetches_an_old_cache_for_a_window_that_starts_at_30`, tests/test_orca.py `test_r8_m33_the_manifest_records_the_layout_version_of_the_hour_labelling`. Before: the 12:30 / no-version case and the other two fail; after: pass.

## M-34 `run --seed` copy (pipeline.py:1418)
- With a seed override the saved `mission.yaml` is `yaml.safe_dump(dict(config._yaml(mission_path), seed=seed), sort_keys=False)` (comments lost; the original stays at `plan.json`'s `mission_path`); without one it is `shutil.copy` as before. `re` is still used elsewhere in the module.
- Test `test_r8_m34_run_seed_rewrites_the_saved_mission_whatever_the_spelling_of_seed` (`seed : 5`, `"seed": 5`, `'seed': 5`, `seed: 5   # the draw`; with no override the copy is byte-identical). Before: 3 of 4 keep seed 5; after: all give 9.

## Proposed DECISIONS rows (the lead numbers them from 393)
- `| ? | New ingest check forcing_in_physical_range: WRF 10 m wind speed at most 100 m/s, WRF SST 271 to 315 K at water cells, UMWM swh 0 to 30 m and ust 0 to 5 m/s at sea nodes; value = number outside, limit 0; bounds in assumptions.yaml ingest.*. The u* agreement stays unthresholded as a gate but a fraction below 0.90 puts the BRIEF 2.1 finding in the ledger (pipeline.USTAR_AGREE_FRACTION) | Review round 8, M-1. Amends 168 (the finding is now made; K's Data pedigree reads it). A x3 wind is inside the bounds and is caught by the u* fraction, not by this check. |`
- `| ? | A lab ocean store must cover the window with no step over 24 h between the last time at or before its start and the first at or after its end (pipeline.OCEAN_MAX_STEP_S); non-finite times are dropped, an empty axis is a problem; ledger check ocean_time_cadence records the median and largest step for GOFS and lab stores | Review round 8, M-2. Amends 352 (coverage plus the step bound); the 24 h is an assumption, QUESTIONS_FOR_LAB. |`
- `| ? | A cached WRF or UMWM axis that is not strictly increasing is a ConfigError naming the store and the fix (GriddedEnv); the ingest records time_axes_hourly_gap_free as failed with that text and stops | Review round 8, M-24. Extends 294. |`
- `| ? | The lab ocean cut keeps, besides the points within 0.1 deg of the box, the nearest point beyond an edge when the nearest kept one is more than 0.1 deg inside it (both neighbours when none is kept and the grid reaches both sides) | Review round 8, M-29. Amends 21/318/376 in the cut only; a grid of any spacing works if the file covers the box. |`
- `| ? | ingest_lab_hycom orders snapshots by their time, not by file name, and refuses two snapshots of the same time naming both files, before writing | Review round 8, M-30. Extends 376. |`
- `| ? | The GEBCO cache glob of the receipts ignores .part.npz (bathy.cached_cuts) | Review round 8, M-31. |`
- `| ? | The orca manifest records layout_version 2; a manifest without it is refused for a window that does not start on the hour (fetched again, noted in the ingest) and accepted for one that does | Review round 8, M-33. Completes round 7 M-17. |`
- `| ? | run --seed writes mission.yaml from the loaded mission with the seed replaced (yaml.safe_dump), not by a regex; comments are lost in that copy | Review round 8, M-34. |`

## CHANGELOG lines
- M-1: Ingest check `forcing_in_physical_range` (gross-error bounds in assumptions.yaml `ingest.*`); a COARE/UMWM u* agreement below 90 % is a ledger finding.
- M-2: A lab ocean store with a step over 24 h inside the window is refused; empty or NaN time axes give a message; ledger check `ocean_time_cadence`.
- M-24: A non-increasing cached WRF/UMWM axis is a ConfigError naming the store; the ingest records the failed hourly check and stops.
- M-29: The lab ocean cut keeps the points that bracket the box, whatever the grid spacing.
- M-30: Lab snapshots are ingested in time order; a repeated snapshot is refused naming both files.
- M-31: The receipts job for bathymetry ignores the `.part.npz` of an interrupted GEBCO fetch.
- M-33: The orca manifest records `layout_version`; an old cache for a window that starts at :30 is fetched again.
- M-34: `run --seed` writes the saved mission.yaml with the seed replaced whatever its spelling.

## Other doc text
- docs/RUNBOOK.md line 107 (ocean store): replace "any regular cadence works" with "any cadence with no step longer than 24 h inside the window works, and a grid of any spacing works if the file covers the box"; also add to troubleshooting: "environment cache file ...wrf.zarr: axis time: must be strictly increasing" -> delete `<cache>/orca` and run `fetch` again.
- docs/CREDIBILITY.md (M-1, K's part): Data pedigree level 2 needs `forcing_in_physical_range` ok and the u* fraction at least 0.90.
- QUESTIONS_FOR_LAB.md sub-item: "Longest step of a lab ocean store inside the window (default 24 h, `pipeline.OCEAN_MAX_STEP_S`): the daily mean of a reanalysis is accepted, a longer step is refused because the current would be a straight line across it. Is 24 h right for your model?"

## Needs from other batches
- K (Data pedigree, M-1 part 3): read the ingest ledger check `forcing_in_physical_range` (a missing or failed check caps the level) and `coare_ustar_vs_umwm_ust`'s `value` (fraction within 20 %; level 2 needs at least 0.90). The threshold is `pipeline.USTAR_AGREE_FRACTION`; K may import it or repeat 0.90. The ledger note text for the finding begins "BRIEF 2.1 finding:".
- A: no change needed. `_ingest_checks` now returns a bool and `s_ingest` has one new check (`ocean_time_cadence`); A's `L.input` / `ocean_store_nan_mask` edits are in other functions.
- config/assumptions.yaml gained four `ingest.*` entries: they are listed assumed inputs (credibility/report count them automatically); the tests that count assumptions relative to a base still pass.

## Commands and results (all on homebase, `PMX=pm_r8e PM_CPUS=1`)
- Fail-first, unfixed code (detached worktree at eaf0e27 + the five new test files, `PMX=pm_r8e_old`): `pytest -k r8` on tests/test_hycom.py test_receipts.py test_orca.py test_environment.py: 15 failed (M-29 x6, M-30 x3, M-31, M-33, M-24 x4); on tests/test_pipeline.py: 17 failed (M-24 x2, M-1 x7, M-2 x3, M-33 x2 [the 12:30 no-version case and the ingest-note test], M-34 x3); the on-the-hour and versioned M-33 cases pass on old code, as intended.
- Fixed code: `pytest -k r8` on all five files: all pass.
- Whole files, fixed code: tests/test_pipeline.py + tests/test_ingest_fetch.py (PM_MEM=12g): rc 0. tests/test_hycom.py, test_environment.py, test_orca.py, test_bathy.py, test_receipts.py with coverage: rc 0; hycom.py, orca.py, bathy.py 100 %; environment.py 98 % in this subset, the six missing lines (210, 218, 291, 326-327, 332) are existing subgrid/ocean lines covered by other test files, none are lines this batch added (`axis()` is covered). tests/test_config.py, test_ocean.py, `-k "assum or sigma or fitted"` in test_credibility.py and test_report.py, `-k "seed or ingest"` in test_cli.py: 187 passed, 0 failed.
- `ruff check cafe/pm tests bench`: All checks passed. `mypy cafe/pm`: Success, no issues in 54 source files.
- No container of mine is left running (`docker ps | grep r8e` empty). The commit message ends with the Sonnet 5.5 Co-Authored-By line (the lead's later correction to r8_common.md).
