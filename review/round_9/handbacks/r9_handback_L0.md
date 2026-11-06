# Round 9, batch L0 handback (branch r9-merged, worktree cafe-r9m)

Seven look-ahead problems, fixed at the shared place. Next free DECISIONS row at my base (2f5bf5e) is 470; the numbers below are suggestions for the lead to
renumber. Docs were not edited. The two "machine warning" problems are one defect and are one row.

## L0-1 The credibility page shows a wall-model plate receipt that stage 3 refuses (Re_L below 1e6)

DECISIONS row (suggested 470): the Re_L rule for a stored flat-plate receipt is one function, `config.plate_re_problem(name, d)` (with `config.PLATE_RE_MIN` =
1e6, which `wallmodel.PLATE_RE_MIN` now aliases): it returns the phrase "wm_flat_plate.json is at Re_L 9.8e+05, below the 1e+06 the comparison needs (rerun
it)" or None. `wallmodel._stored_receipts` (the stage-3 gate) and `credibility._stored_rows` (the page) both call it, so a refused plate is a "not run: ..." row
and no longer counts in `_validation`'s `ran` list. At exactly 1e6 it counts, as before. Amends 466 (its claim "the page never shows a row stage 3 refuses" held
for missing and non-numeric fields only), and 424. Not changed, and still different on purpose: the gate also refuses a receipt without `code_sha` or with
another one; the page does not look at `code_sha` (its existing tests store receipts without one). See "Still open" below.

CHANGELOG: the credibility page no longer draws a wall-model flat-plate row from a receipt run below Re_L 1e6, which stage 3 refuses; one rule
(`config.plate_re_problem`) for both; DECISIONS 470, round 9 M-23 sibling.

Test: `tests/test_credibility.py::test_l0_the_page_refuses_a_plate_receipt_below_the_minimum_re_as_stage_3_does` (fails on 2f5bf5e: the row is "run" and
Validation is 1 with the refused plate alone).
Callers checked: `wallmodel._stored_receipts` (used by `stale_wall_receipts`, `stored_wall_error`, so `windows.stage3_checks`) keeps its phrase byte for byte
(tests/test_stage3.py ran whole is in the end list); `wallmodel.receipts()` still compares `plate["re"] < PLATE_RE_MIN` with the same constant.

## L0-2 / L0-3 The report's machine warning describes the machine that renders, not the machine the run was on (two findings, one defect)

DECISIONS row (suggested 471): `ledger.machine()` records `warning` (`budget.machine_warning` on the throughput block it just read, judged on the host that
runs the stage) beside host, cpus, workers and bench_id; `report._machine` reads `first["machine"].get("warning")` from the ingest ledger (the same ledger
that gives the `cpus` the page prints) and no longer calls `machine_warning()` at render time. So `report --run` on another machine, and a run resumed across
machines, print what the run saw; a ledger written before this field has no key and the report says None (unknown, not a guess). `machine.machine` is still
volatile (`acceptance.VOLATILE`). Amends 468: the warning is still not in `plan.json`, the notes or `report.json` outside `machine.machine`, but it is in the
stage ledgers' `machine` block, which already differs between machines (host, cpus, workers), so no shared-between-machines file gains it. The `plan` printout
and the `run` log line still judge the machine they run on, which is correct there.

CHANGELOG: the report's other-machine warning is the one recorded where the run was made (ledger `machine.warning`), so `report --run` on another machine no
longer names the wrong one or loses it; DECISIONS 471, round 9 M-9 sibling.

Tests: `tests/test_report.py::test_l0_the_report_names_the_machine_the_run_was_on_not_the_one_that_renders_it` (fails on 2f5bf5e: the renderer's answer wins),
`tests/test_ledger.py::test_l0_machine_records_the_other_machine_warning_where_the_stage_ran`. The existing
`test_r9_m9_the_report_says_when_the_rates_are_another_machines_and_only_in_the_volatile_place` is rewritten to set the warning in the ingest ledger instead of
monkeypatching `budget.machine_warning`: it asserted the old route, and its other assertions (volatile path, HTML note, nothing in plan.json or the notes) are
all still there; the "no stage ledger carries it" assertion could not stay, because the ledger now carries it by design (it was trivially true before, the
ledgers having been written before the monkeypatch).
Also edited: `tests/test_pipeline.py::test_r9_m9_the_run_logs_the_other_machine_warning_after_the_plan_and_it_is_in_no_hashed_file` asserted "no stage ledger
carries the warning"; that is the part of row 468 this row amends. It now asserts plan.json is free of it, each ledger's `machine.warning` is the run's own,
and the ledgers' `config_hash` (what a resume compares) and the context hash are the same with and without a warning.
Callers checked: `ledger.machine()` is called by `Ledger.__init__` only (and tests); the extra key is read by nothing else (`grep "\"machine\"\]"`: report only).

## L0-4 M-4 sibling: DTMB 5415 run_<grid>.json readers crashed on a truncated or non-object file

DECISIONS row (suggested 472): `dtmb5415.read_run(f)` is the one reader of `run_<grid>.json`: `config.json_object`, and the file must hold a `speeds` mapping;
else None. `_runs` skips an unreadable file, `stale_files` names it (with the files of another recipe) and the new `stale_notes` gives each name its reason ("is
unreadable (rerun the grid)" or "was made by recipe R, not V"), which `credibility._dtmb_rows` prints as before. `run_grid` refuses to extend an unreadable
file (`ValueError ... move it aside`, like the recipe case) instead of a JSONDecodeError. The writers are atomic: `config.write_json` (a sibling temporary and
`os.replace`, the shape of `wallmodel._write_receipt`, which now calls it) is used by `run_grid`, `prepare` (hydro.json), `lbm.main slow` and `nest.main slow`.
The receipts status line says "of another recipe or unreadable" when any is unreadable. Amends 466 (its reader side) and 449 (M-32: wall-model write).

CHANGELOG: a cut-short or non-object `run_<grid>.json` is a named "not run" row and no longer stops the report stage; the DTMB run files, hydro.json and the
sphere receipts are written through a temporary; DECISIONS 472, round 9 M-4 sibling.

Tests: `tests/test_vv.py::test_l0_a_damaged_run_file_is_skipped_and_named_never_a_traceback_and_run_grid_will_not_extend_it` (4 damages),
`...::test_l0_run_grid_writes_through_a_temporary_so_a_kill_keeps_the_old_file`, `tests/test_credibility.py::test_l0_a_damaged_dtmb_run_file_is_a_not_run_row_that_names_it_not_a_traceback`
(3 damages), `tests/test_lbm.py::test_l0_a_slow_sphere_receipt_is_written_through_a_temporary_so_a_kill_keeps_the_old_one`,
`tests/test_nest.py::test_l0_a_nest_sphere_receipt_is_written_through_a_temporary_so_a_kill_keeps_the_old_one`,
`tests/test_config.py::test_l0_write_json_replaces_a_file_whole_or_not_at_all`.
Callers checked: `read_run`'s callers are the three listed; `stale_files` is used by `receipts` and (earlier) `credibility`; `tests/test_vv.py` ran whole.
Sibling not changed: `orca.write_json` and `hycom._write_json` are two more copies of the same atomic writer; moving them onto `config.write_json` is a
refactor outside this finding. `dtmb5415.receipts()` still does `json.loads(hydro.json)` bare (hydro.json is now atomic, so a cut-short file cannot appear
from `prepare`; a hand-edited one still raises in `receipts()`, which is the receipt command, not the report stage).

## L0-5 M-3 sibling: fly_sitl took the air density at the ship with no hole guard

DECISIONS row (suggested 473): the air at the ship is read by one function, `uas.air_at_ship(env, lon, lat, t) -> (rho, finite)`: where the air state is not
finite the density is the finite 1.0 and `finite` is False. `fly_sortie` (its M-3 guard moved into it) and `fly_sitl` both call it. A `fly_sitl` member whose
ship has no finite air state is scrubbed as in `fly_sortie`: it returns `scrubbed` True, nothing flown (`t_end` 0, `soc_end` 1, no flag), the firmware is
never started, and `sitl.messages` says why. With the default waypoints a non-finite wind at the ship (`wind_ref`) points the pattern as in still air and
sets `no_current_data` (the rule of an in-flight wind hole, which the existing test `test_r9_fly_sitl_labels_a_wind_that_is_not_finite...` fixes) instead of
making NaN waypoints. The docstring says both. Amends 469 (M-3 end to end) and 310.

CHANGELOG: `fly_sitl` scrubs a ship with no finite air state (as `fly_sortie` does) and no longer returns NaN energy and soc with no flag; NaN default
waypoints are gone; DECISIONS 473, round 9 M-3 sibling.

Tests: `tests/test_uas.py::test_l0_fly_sitl_scrubs_a_ship_with_no_air_state_as_fly_sortie_does_and_never_starts_the_firmware`,
`...::test_l0_fly_sitl_points_the_default_pattern_as_in_still_air_when_the_wind_at_the_ship_is_a_hole`.
Callers checked: `fly_sitl` has no stage caller (DECISIONS 310): receipts (`_sitl_receipts`) and tests. The scrub return has exactly the keys of the normal
return (the documentation test `test_r9_m26_...` pins them).

## L0-6 M-31 sibling: `_tao_cached` accepted a cache whose selected file lacks the QC variable

DECISIONS row (suggested 474): `tao.unusable_selected(dir)` reads every file the manifest selects through `_series` and lists those it refuses ("key: why");
`pipeline._tao_cached` returns False if the list is not empty, so `fetch` runs again (its `fetch_tao` marks such a file `unusable` and selects another
deployment) instead of `load_tao` raising a bare ValueError hours into the ingest. Cost: one read of each selected NetCDF file in the cache check.

CHANGELOG: the TAO cache check opens the selected files, so a cache with a file that lost its QC variable is fetched again, not a late ingest failure;
DECISIONS 474, round 9 M-31 sibling.

Test: `tests/test_pipeline.py::test_l0_a_tao_cache_whose_selected_file_lost_its_qc_variable_is_not_cached` (the file still hashes to its manifest; fails on
2f5bf5e at `_tao_cached`). Callers checked: `_tao_cached` is called by `_need` in the ingest only; `tests/test_pipeline.py::test_r6_m8_...tao_manifest` and
`tests/test_ingest_fetch.py::test_a_tao_download_is_cached_only_if...` ran whole.
Not fixed: if the offline cache has a file without its QC variable, the ingest now stops at the `tao_present` check with the fetch advice instead of at `load_tao`.

## L0-7 M-33 sibling: a damaged gofs31 store at a custom `.zarr` path got the lab-HYCOM advice

DECISIONS row (suggested 475): "the store is the lab's" is one rule, `ocean.is_lab(spec)` (source other than `gofs31`), used by `open_ocean` and by the ingest
stage, which passes `lab=` to every `hycom.open_store` of the mission's store; `_ocean_cached` takes it from its `window` argument (given for a lab store only).
The file-name guess in `hycom.unreadable` (`gofs*` prefix) remains only for a caller with no mission spec (`hycom.check_node`, `bathy.from_gofs`, which open a
store that has already opened once).

CHANGELOG: an unreadable ocean store gets the advice of its mission's source (a gofs31 store at any `.zarr` path: delete it and fetch; a lab store: restore it
from the lab), not of its file name; DECISIONS 475, round 9 M-33 sibling.

Test: `tests/test_ingest_fetch.py::test_l0_a_damaged_ocean_store_gets_the_advice_of_the_missions_source_not_of_its_file_name` (both directions: `mystore.zarr`
as gofs31, `gofs_lab.zarr` as a lab store).
Callers checked: 6 `open_store` calls in `pipeline` (all the mission's store); `ocean.open_ocean` already passed `lab`.

## L0-8 M-12 sibling: acceptance removed its run directory before reading a `--mission` inside it

DECISIONS row (suggested 476): `acceptance.refuse_wiped_mission(mission, out, names)` raises a ConfigError (exit 2) when the resolved mission is inside
`out/<name>` or `out/<name>_fetch` for a name in `names`. `run_one` asks for its own name before it removes anything; `run` asks for all of `RUN_NAMES` (quick,
quick_same, quick_seed, overnight, 4h) before the first run, so a mission in the last run's directory is refused before hours of work, not after. A mission
elsewhere, including `out/mission.yaml` and a directory whose name merely starts like a run's, is accepted. The message says to copy the mission out of `--out`
(a run's own copy is `<run dir>/mission.yaml`).

CHANGELOG: `acceptance` refuses a `--mission` that lies inside a directory it removes, with a message, instead of deleting it and failing with "file not
found"; DECISIONS 476, round 9 M-12 sibling.

Tests: `tests/test_acceptance.py::test_l0_a_mission_inside_a_run_directory_acceptance_removes_is_refused_before_anything_is_deleted`,
`...::test_l0_run_names_are_every_directory_run_makes` (RUN_NAMES equals the names `run` passes to `run_one`, so the list cannot drift).

## Still open (looked at, not changed)

- The page and the stage-3 gate still differ on `code_sha` for a stored wall-model receipt (the gate refuses a missing or stale one; the page draws the row).
  Same shape as L0-1, different rule; the page cannot call `lbm.physics_sha()` without the stage-3 import chain, and its tests store receipts with no sha.
  Owner's call whether the page should refuse it or label it.
- `ledger.machine()` calls `.get` on the throughput `machine` block; a hand-edited `"machine": "homebase"` string raises there, though `machine_warning`
  tolerates it. Not touched.
