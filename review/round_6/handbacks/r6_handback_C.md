# Round 6, batch C hand-back (M-7, M-8, M-9, M-11, M-22, M-24)

Branch `r6-c`, worktree `/Users/aaroh/Downloads/everything/cafe-r6c`. All six fixed. One part of M-8 needs another batch (below).

## Before/after of the new tests
`pytest tests/test_config.py tests/test_cli.py tests/test_hycom.py tests/test_ocean.py tests/test_orca.py tests/test_pipeline.py -k r6` on homebase (PM_CPUS=1, PM_MEM=8g):
- on the unfixed code (`cafe/` of e9bf044, new tests kept): **28 failed, 2 passed** (the 2 are the "edges of the ranges still load" test, a test that must pass before and after);
- on the fixed code: **30 passed**.
Old tests changed: none. No assertion weakened.

## Per finding
**M-9** (cafe/schemas/mission.json; cafe/pm/config.py `load_mission`). Schema: `max_mean_wind_ms` >0 and <=60; `no_gust_front_within_min` 0..1440; `radius_km` 0.01..1000; `lost_after_h` >0, <=720; `dive_depth_m` 1..2000; `track_tolerance_km` >0, <=1000; `altitudes_m` `uniqueItems`. `load_mission`: a glider `dive_depth_m` outside the platform's `min_dive_m`..`rating_m` is refused naming vehicle, number and limits; `altitudes_m` must rise. Note: the finding gave no lower bound for `radius_km`, but its list includes `radius_km: 1e-9`; I chose 0.01 km (10 m). Tests: `test_r6_m9_*` (11 refusals, edges and shipped missions load).
**M-11** (config.py `load_mission`): `lab_hycom` without `path` and `gofs31` with `temperature_kind` are `ConfigError`s naming `environment/ocean`. `ocean.store_path` keeps its ValueError. Test `test_r6_m11_*`.
**M-24** (config.py `_say`, used by `validate`): unquoted timestamp and empty value get the new texts. Test `test_r6_m24_*`.
**M-22** (`__main__.py` `_hangar`; config.py `TABLES`, `table_provenance`, `load_platform`'s `available:` list marks "(table)"): `hangar --platform radios|modems` prints "(radio table)" / "(modem table)", checks that each entry has a `source` and each `{value,..}` leaf has a source or assumed+why; exit 1 names the leaf. The table check is new (the comms loader has no provenance check of its own). Modems carry no value-leaves, so it prints "0 of 0 values assumed". Tests `test_r6_m22_*`.
**M-7** (env/hycom.py `unreadable`, `open_store(lab=)`; env/ocean.py `Ocean(lab=)`, `_field`, `open_ocean`): the message names the store, never its parent; a lab store (explicit `lab` from `source`, else a name not starting `gofs`) gets "restore ... the pipeline cannot download it"; `Ocean._field` wraps the lazy chunk read in the same `ConfigError`. Tests `test_r6_m7_*` (test_hycom.py, test_ocean.py). I did not add a `cli.main(["fetch"])` exit-2 test: exit 2 for any `ConfigError` is the existing handler in `__main__.main`.
**M-8** (env/orca.py `read_json`, `write_json`, `_drop_stale_parts`, manifest write; pipeline.py `orca_covers` (nested in `s_ingest`), `_umwm_depth`, `_tao_cached`): the orca `manifest.json` and `cut.json` are written through a temporary and `os.replace`; an unreadable manifest/cut record is "no record" (orca: fetch again, with a log line; TAO: not cached); `_umwm_depth` raises the cache `ConfigError` naming `umwm.zarr` and `delete <cache>/orca`. Tests `test_r6_m8_*` (test_orca.py, test_pipeline.py), including a write interrupted by a failing `os.replace` leaving the old file, and the offline case failing the `orca_present` check naming the command.

## Doc text for the lead
DECISIONS rows (number from 308):
- `| ? | `mission.json` ranges: max_mean_wind_ms (0,60], no_gust_front_within_min 0..1440, radius_km 0.01..1000, lost_after_h (0,720], dive_depth_m 1..2000, track_tolerance_km (0,1000], altitudes_m unique and rising; a glider dive_depth_m must lie between its platform's min_dive_m and rating_m. | Review round 6, M-9. Typos in a lab-edited file became a verdict with the wrong cause (`seafloor`, `no_sortie_flown`). The numbers are bounds of the model. |`
- `| ? | `environment.ocean` `lab_hycom` needs `path`; `temperature_kind` is refused for `gofs31`. | Review round 6, M-11. validate said valid, fetch and run ended in a bare ValueError. |`
- `| ? | The unquoted timestamp and the empty value of a mission file have their own messages. | Review round 6, M-24. |`
- `| ? | `hangar` knows `radios` and `modems` as tables: each entry needs a `source`, each value leaf a source or assumed+why. | Review round 6, M-22. They were treated as the UAS file. |`
- `| ? | An unreadable ocean store or chunk is a `ConfigError` naming the store itself (never its parent); the remedy is "delete" for a store the pipeline fetched and "restore" for the lab's. Amends row 294's remedy text. | Review round 6, M-7. The old text told the user to delete the whole `ocean` directory. |`
- `| ? | The orca manifest and cut record are written atomically; an unreadable one is no record (refetch), an unreadable TAO manifest is not cached, an unreadable `umwm.zarr` is a `ConfigError`. Extends row 294. | Review round 6, M-8. |`

CHANGELOG lines: one per finding, same wording as the rows.
RUNBOOK (troubleshooting row "`error: environment cache file ... cannot be read`", remedy column), replace with: "delete the store or directory the message names (the single `gofs_<mission>.zarr`, or `<cache>/orca`), never the whole `ocean` directory, and run `fetch` again; for a lab store the message says to restore it from the lab's source: the pipeline cannot download it". Also in the RUNBOOK step 4 (lab HYCOM): "`path` is required with `source: lab_hycom`".

## Needs from other batches
- `cafe/pm/env/tao.py` line 128 (`fetch_tao`): `old = json.loads(mpath.read_text())["files"] if mpath.exists() else {}` raises on an empty/truncated TAO manifest, so the refetch my `_tao_cached` now asks for still dies there. Change to `old = (orca.read_json(mpath) or {}).get("files", {})` (import `from .orca import read_json`), plus a test with an empty manifest. The TAO manifest writer is already atomic.
- `cafe/pm/pipeline.py` lines ~252, 344, 347 call `hycom.open_store(store)` without `lab`; they get the name rule (`gofs*` = downloaded), which is right for the default store. Passing `lab=spec["source"] != "gofs31"` there would make it exact.

## Incident (read this)
`git stash` is shared by all worktrees. I ran `git stash push -- cafe/` for the before/after check; builder P stashed ten seconds earlier, and the two `pop`s crossed: my worktree got P's `cafe/` edits and P's worktree got mine. I restored my tree (reverse-applied P's patch, then `git stash apply 6006e884` of my own dangling stash commit; verified byte-identical to my diff). I was refused permission to touch `/Users/aaroh/Downloads/everything/cafe-r6p`, so **that worktree still has my `cafe/` changes in place of P's**. Its own edits are the dangling commit `77732a7` (`git -C cafe-r6p checkout -- cafe/ && git -C cafe-r6p stash apply 77732a7`, after checking that `git -C cafe-r6p diff -- cafe/` is exactly my 336-line patch). `tests/` of P were not touched. Nobody should use `git stash` in these worktrees.

## Commands and results (homebase, `PMX=pm_r6c PM_CPUS=1`)
- Lint script: `ruff check cafe/pm tests bench` -> All checks passed; `mypy cafe/pm` -> no issues in 54 source files.
- `pytest tests/test_config.py test_cli.py test_hycom.py test_ocean.py test_orca.py test_environment.py test_bathy.py test_ingest_fetch.py test_pipeline.py --cov=cafe.pm.env --cov=cafe.pm.config` (PM_MEM=8g): coverage config.py, env/hycom.py, env/ocean.py, env/orca.py all 100 %; the only failures were 13 tests in test_cli.py (report and whatif) that stop at the stage-1 memory guard ("needs about 9 GB ... 9 GB is available") because of the 8 GB cap this batch's rules set; `tests/test_cli.py` alone at PM_MEM=12g: 64 passed. Everything else in those files passed. Not run: the full suite, coverage of all of `cafe/pm`, mutation testing.
- No container of mine is left (`docker ps | grep r6c` empty).
