# Round 5 hand-back, batch C (M-3, M-17, M-18, M-19)

All four fixed. Worktree `/Users/aaroh/Downloads/everything/cafe-r5c`, branch `r5-c`.

## M-3 non-finite numbers
- `cafe/pm/config.py`: new `_finite(node, path, where)`, called in `load_mission` after `_unread_keys`, before the schema. Message `<file>: vehicles/glider_eq/task/radius_km: nan is not a finite number; write a number (a missing value is a missing key, not .nan)`. List items that have an `id` (vehicles, links) are named by it. `every_days: .nan/.inf` is now a `ConfigError` (the `ValueError` out of `launch_times` is unreachable).
- Test: `test_r5_m3_a_non_finite_number_is_refused_naming_the_field` (13 fields x nan/inf = 26 cases: box/pad_deg, ship antenna_height_m and transducer_depth_m, glider radius_km, lost_after_h, dive_depth_m, heading_to, usv track_tolerance_km and becalmed_after_h, uas every_days, max_mean_wind_ms, altitudes_m[0], a link's required_fraction).
- Before: 26 failed of 26 (load_mission returned). After: 26 passed.

## M-17 station without lat
- `config.py`: the station check moved to the top of the vehicle loop (before the points loop that did `task["lat"]`) and tests `{"lon","lat"} <= set(task)`; skipped for a UAS (`base`) so "a UAS flies sorties and takes no task" still wins. Message: `... mode 'station' needs lon and lat of the station (radius_km, default 5, and lost_after_h, default 6, are optional)`.
- Test: `test_r5_m17_a_station_without_lon_or_lat_is_a_config_error[lat|lon]`. Before: both failed (KeyError 'lat' for lat; for lon the old message). After: pass.
- Existing test changed: `BAD` row `mutate_station_without_point` asserted the old message "needs lon, lat and radius_km" (the wrong sentence the finding names); now "needs lon and lat of the station". Failed before the fix by construction, passes after.

## M-18 duplicate key, leading-zero number
- `config.py`: `_Loader(yaml.SafeLoader)` with `construct_mapping` raising `line N: duplicate key 'k'; a later value would silently replace an earlier one` (merge keys `<<` are not counted), and an int constructor raising `line N: 010 is read as octal 8; write 8, or quote it for a string` (refused, not read as decimal). `_yaml` uses it and prefixes the file path. `load_platform`/`_registry`/`assumptions` go through `_yaml`, so config/platform files read by `config` get the same check; the physics modules' own `yaml.safe_load` are untouched (batch V). `08`/`09` are strings under YAML 1.1 and the schema refuses them already; plain `0` is fine.
- Tests: `test_r5_m18_a_duplicate_key_is_refused_with_its_line`, `test_r5_m18_a_leading_zero_number_is_refused_not_read_as_octal` (both failed before: loaded and ran on the second value / 8); `test_r5_m18_a_merge_key_is_not_a_duplicate_and_the_shipped_files_load` (passes before and after; pins that `missions/`, `platforms/`, `config/` YAML all load and that merge keys are not flagged).

## M-19 corrupt cache, run directory without plan.json
- `cafe/pm/env/environment.py` `GriddedEnv.__init__`: local `load(store)` wraps `xr.open_zarr(store).load()` for wrf, umwm, wrf3d, umwmspec: `ConfigError("environment cache file <store> cannot be read (<Type>: <msg>); delete <cache>/orca and run `python -m cafe.pm fetch --mission ...` again: only that part is downloaded again")`.
- `cafe/pm/env/hycom.py` `open_store`: the open (both `cache` branches) wrapped the same way, "delete <store's parent dir>" (the ocean part). `kind_of` still raises its own `ValueError`.
- `cafe/pm/__main__.py` `_report`: `ConfigError("<run>: no plan.json; this is not a finished run directory (run `python -m cafe.pm run` first)")` before reading it; `main` shows it as `error: ...`, exit 2.
- Tests: `test_r5_m19_a_truncated_chunk_...`, `test_r5_m19_a_corrupt_zarr_json_is_a_config_error_for_every_store` (tests/test_environment.py); `test_r5_m19_open_store_names_a_corrupt_or_missing_store_and_the_fix` (tests/test_hycom.py). All failed before (RuntimeError zstd / JSONDecodeError, no match), pass after.
- Existing test changed: tests/test_cli.py `test_report_of_a_directory_that_is_not_a_run_exits_2` asserted `pytest.raises(FileNotFoundError, match="plan.json")` (the traceback the finding names); now asserts exit 2 and "no plan.json; this is not a finished run directory" on stderr. Failed before.
- Judgment: the finding names the cache chunk and `zarr.json` of an orca/ocean store; I guarded all four orca stores because they share the one failure.

## Proposed docs
DECISIONS rows:
- `| ? | The mission loader refuses a NaN or infinite number anywhere in the file, naming the field by its slash path (vehicles and links by id); there is no legitimate non-finite mission value. | Review round 5, M-3. JSON Schema's number accepts both and every comparison with NaN is False, so a typo turned a failure criterion off and the verdict was GO. |`
- `| ? | A station task needs lon and lat (radius_km, default 5, and lost_after_h, default 6, are optional); checked before any point is read. | Review round 5, M-17. A missing lat was a KeyError traceback; the old message also named radius_km as required. |`
- `| ? | Mission and config YAML is read by a SafeLoader that refuses a repeated mapping key (naming key and line) and a leading-zero integer such as 010 (octal 8; refused, not read as decimal, naming the line). | Review round 5, M-18. Both were accepted silently; the verdict thresholds and the seed decide what the report says. Physics modules' own platform readers are unchanged (batch V). |`
- `| ? | An unreadable environment cache file (orca stores, ocean store) and a run directory without plan.json are ConfigErrors naming the file and the fix (delete that part and fetch again / run first); exit 2. | Review round 5, M-19. They were raw RuntimeError, JSONDecodeError and FileNotFoundError tracebacks. |`

CHANGELOG lines:
- `M-3: load_mission refuses NaN and infinite numbers, naming the field.`
- `M-17: a station task without lat (or lon) is a ConfigError, not a KeyError.`
- `M-18: YAML duplicate keys and leading-zero numbers are refused with the line.`
- `M-19: a corrupt environment cache file and a run without plan.json end in a named error, exit 2.`

RUNBOOK step 4 (docs batch): replace "names the station (`lon`, `lat`, `radius_km`)" by "names the station (`lon`, `lat`; `radius_km`, default 5, and `lost_after_h`, default 6, are optional)". Add to the troubleshooting table: "error: environment cache file ... cannot be read" -> delete the named orca/ocean directory and rerun `fetch`; "error: ... duplicate key" / "read as octal" -> fix the named line.

## Needs from other batches
- Batch V (M-4): platform loaders in physics modules still use plain `yaml.safe_load`; to share the check, `from ..config import _yaml` (no import cycle: config imports physics only inside functions).
- Docs batch: the RUNBOOK text above.

## Commands run (homebase, cafe-pm image, PM_CPUS=1, PMX=pm_r5c)
- Before (cafe/ stashed, new tests kept), `-k "r5 or station or not_a_run"` on test_config/hycom/cli/environment: 35 failed (26 non-finite, 2 station, 2 yaml, 1 hycom, 2 environment, 1 cli report, 1 old BAD row), 0 other.
- After: `ruff check cafe/pm tests bench` All checks passed; `mypy cafe/pm` Success, no issues in 54 files; tests/test_config.py, test_config_docs.py, test_hycom.py, test_cli.py, test_environment.py: 297 passed, 0 failed.
- Coverage on those four files + config: config.py 100 %, env/hycom.py 100 %; env/environment.py misses only lines outside `__init__` (rain/other functions, covered by test files I did not run); the guard lines are covered. No containers left (`docker ps | grep r5c` empty).
