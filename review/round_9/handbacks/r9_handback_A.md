# Round 9, batch A (first half) hand-back: M-2, M-13, M-20, M-33, M-1, M-14, M-12, M-11, M-18, M-9

Branch `r9-a`, from `91c9777`. Tests ran on cafe-burst (`PMX=pm_r9a`, image `cafe-pm`, 4 CPUs, 16 GB). Each regression test is named `test_r9_m<n>_...` (the four `load_mission` refusals are cases of
`test_validation_gaps_are_refused_with_the_field_and_the_fix`, ids `r9_m13_...`, `r9_m20_...`, `r9_m33_...`), so `-k r9` selects them all. Docs (DECISIONS, CHANGELOG, RUNBOOK, STATUS) are not touched.

## Result in one table

| finding | where the fix is | regression test(s) (all fail on `91c9777`, pass now) |
|---|---|---|
| M-2 alias shared between vehicles | `config._unshare`, last step of `load_mission` | `test_config.py::test_r9_m2_a_yaml_alias_is_unshared_at_load_and_the_mission_hash_does_not_move`; `test_whatif.py::test_r9_m2_a_shared_yaml_dict_is_not_edited_twice_and_a_move_gives_each_vehicle_its_own_position` |
| M-13 identical waypoints | `load_mission`, next to the "at least two waypoints" check | cases `r9_m13_two_identical_waypoints`, `r9_m13_a_repeated_last_waypoint`; control `test_r9_m13_a_section_may_return_to_an_earlier_waypoint_and_a_station_task_keeps_its_waypoints` (passes before and after, on purpose) |
| M-20 empty box | `load_mission`, after the latitude check; `budget.padded_area_deg2` simplified | case `r9_m20_equal_box_longitudes`; `test_r9_m20_a_box_across_the_dateline_...`; `test_budget.py::test_r9_m20_equal_box_longitudes_are_a_strip_with_no_width_in_the_budget_as_in_the_config` |
| M-33 gofs31 path suffix | `load_mission` | case `r9_m33_gofs_path_without_zarr`; control `test_r9_m33_a_gofs_path_ending_in_zarr_loads_and_so_does_no_path` |
| M-1 platform as a path | `config.platform_path` (used by `load_platform` and `s_hangar`) | `test_pipeline.py::test_r9_m1_a_platform_given_as_a_path_is_read_and_hashed_by_the_hangar_stage_whether_relative_or_absolute`; `test_config.py::test_r9_m1_a_platform_given_as_a_path_resolves_to_that_path_and_a_name_to_platforms` |
| M-14 raw dict in text | `config.fmt_box`, used by `config.load_mission` (two messages) and `whatif.apply` | `test_config.py::test_r9_m14_a_box_in_a_message_is_words_not_a_dict`; `test_whatif.py::test_r9_m14_a_move_out_of_the_box_names_the_box_in_words` |
| M-12 same-file copy | `pipeline.run` | `test_pipeline.py::test_r9_m12_running_from_the_runs_own_mission_copy_into_its_own_directory_is_not_a_same_file_error` |
| M-11 `--gpu-mem-gb` | `budget.plan` | `test_budget.py::test_r9_m11_...` (5 values x 2 GPU counts); `test_cli.py::test_r9_m11_...` (4 values, exit 2, `error:` line, no traceback) |
| M-18 `--drop` of every vehicle | `whatif.answer` | `test_whatif.py::test_r9_m18_dropping_every_vehicle_is_refused_and_dropping_some_is_not` |
| M-9 other-machine bench | `budget.machine_warning`, `budget.cpu_model`; printed by `plan` (`__main__`) and logged by `pipeline.run` | `test_budget.py::test_r9_m9_*` (4 tests); `test_cli.py::test_r9_m9_plan_prints_...`; `test_pipeline.py::test_r9_m9_the_run_logs_...` |

Failing before, shown: the r9 tests copied onto a detached worktree of `91c9777` (`PMX=pm_r9a_mut`, `-k r9`, five test files): 34 FAILED, rc=1 (the r9 tests that pass there are the two positive controls named above). Some of them fail only for a missing new function
(`platform_path`, `fmt_box`, `machine_warning`, `cpu_model`); for those, a mutant of the fixed tree shows the test catches the behaviour and not just the name:
`s_hangar` back to `PLATFORMS / f"{ref}.yaml"` fails the M-1 pipeline test; `fmt_box` returning `str(b)` fails both M-14 tests; the warning appended to the plan's notes fails `test_r9_m9_the_warning_is_never_in_the_plan_...` and
`test_r9_m9_the_run_logs_...`; comparing with `par.workers()` instead of `os.cpu_count()` fails `test_r9_m9_a_cpu_limited_container_on_the_benchmarked_box_is_not_warned`. Worktree and its burst directories removed afterwards.

Whole files run on the final tree: see "Verified" at the end.

## Per finding

### M-2. A YAML alias between two vehicles
**Fixed** in the one shared place: `config._unshare(node)` rebuilds every dict and list of the loaded mission and `load_mission` returns that (before `_path` is set). `whatif.apply`, `solo`, the emulator variants (`pipeline.py` one `apply` per variant) and `flip_search` all
start from a mission that came through `load_mission` (`Context.mission`, `__main__._whatif`), so none can see a shared dict. I used a rebuild and not `json.loads(json.dumps(m))`: same effect, but it keeps Python types as they are (an int key stays an int, nothing goes through text).
Checked: no caller relies on identity with the validated document (`validate` returns the same object `doc` and `load_mission` was its only holder); the mission content hash does not move (`Context.hash` is `digest(mission without _path)`, a
`json.dumps(sort_keys=True)`, which writes an alias and a copy identically; the test compares the digest of an aliased mission with that of the same mission written without anchors); `run --seed` rewrites `mission.yaml` through `_yaml` + `safe_dump` and that file
reloads through `load_mission`, so it is unshared again. `report.py` and `credibility.py` read the run's `mission.yaml` with `read_yaml` (aliases kept) but only read it.
Not done: rejecting aliases in `_Loader` (the stricter alternative). An alias is legal YAML and was accepted before; refusing it would break a mission someone already wrote.

### M-13. Identical waypoints
**Fixed** in `load_mission`: a `section` whose consecutive waypoints are equal is a `ConfigError` naming `vehicles/<id>/task/waypoints/<i>` and `waypoints/<i-1>` and the fix (remove the repeat, or `mode: station`). `[A,A]` (so also "fewer than two distinct points") and a trailing `[A,B,B]` are both
caught by the one rule. `[A,B,A]` still loads (a section may come back; control test). Only `mode: section` is checked: `drift` and `station` ignore `waypoints` (`test_stage1.py:369` builds a drift task with them). The schema keeps longitude in [-180, 180), so there is
one spelling of a point and plain equality is the rule. Grep of `missions/`, `tests/`, `tests/fixtures/`: no deliberate repeat (loiter) in any mission that goes through `load_mission`.
Not done (named): with `repeat: true` the flown sequence wraps from the last waypoint to the first, so `[A,B,A]` + repeat has a zero-length wrap leg for one step. I did not refuse it: the step is harmless (the vehicle is already "reached" and moves on), the cross-track test is on for every other leg, and it is not the same defect (no track test silently off). Say if you want it.
The constructors (`USVSim`, `GliderSim`) still accept `[A,A]`: that is batch C's line (see "needs from other batches").

### M-20. A box with `lon_min == lon_max`
**Decision applied: refuse.** `load_mission` checks `(lon_max - lon_min) % 360 == 0` (the modulo `_in_box` uses) after the latitude check: "box.lon_min and box.lon_max are both X: the box has no width and nothing fits in it; give the west and east edges (a box across the dateline is lon_min 165, lon_max -165)". Grepped `missions/`, `tests/`, `bench/`, `cafe/` for equal longitudes
meaning a full circle: none (`tests/test_budget.py:575` uses -180 to 179.9, which is not equal). With the refusal in `load_mission` the `% 360.0 or 360.0` in `budget.padded_area_deg2` could only be reached by a hand-made mission dict, so it is now `% 360.0`: equal longitudes there are a strip with no width,
as in `_in_box`, and a test says so. `env/perturb.py:141` (`if width else 0.0`, "a full circle keeps 0") reads the *environment's* bounds, not the mission box, and `hycom.box360` keeps its `or 360.0` because a padded span can really be 360; neither is the mission-box rule, both left alone.
The schema's longitude is [-180, 180), so -180 and 180 cannot both occur and the modulo only ever triggers on an exact tie.

### M-33. gofs31 `ocean.path` not ending in `.zarr`
**Fixed** (variant a): `load_mission` refuses a `gofs31` `path` whose suffix is not `.zarr`, naming `environment/ocean/path`, the cause (the fetch writes `<name>.zarr`) and both fixes (`<path>.zarr`, or no path). `x.v2.zarr`, `my_gofs.zarr` and no path still load. `lab_hycom` is not checked: `hycom.ingest_lab_hycom` writes the store at exactly the path it is given
(read, no suffix assumption in it). The fetch path itself (`pipeline.py:428`, `store.parent` + `store.stem`) is unchanged.

### M-1. Platform as a path
**Fixed**: `config.platform_path(ref)` is the one rule (`.yaml`/`.yml` suffix = the path as given, else `PLATFORMS/<ref>.yaml`); `config.load_platform` and `pipeline.s_hangar` both call it. `s_hangar` now records the resolved file in `L.input` (so the ledger input has a sha256 and a lab-edited platform file invalidates a resume),
loads it, and writes it as the row's `file`. A relative path is read from where the command runs (the same as every loader). Goldens: `tests/golden/*.json` store the mission summary (platform *name*), not the file string; `hangar.json` `file` is a path and for the shipped missions it is unchanged.
Siblings that are NOT in this branch (yours at merge; exactly what each needs is in "needs from other batches"): glider/usv `load_platform` (`not path.suffix` rule), `physics/__init__.py:57` message, `report.py:451` source label, `credibility.py:365/474/481/740`.

### M-14. Raw Python in user-facing text
**Fixed**: `config.fmt_box(b)` -> `lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg` (`:g` numbers; `lon_min > lon_max` is the antimeridian case, as in `_in_box`). Used by the two `load_mission` messages (ship outside the box, point outside the box) and `whatif.apply`'s "moving ... puts ... outside the mission box (...)".
Swept for siblings: the only other mission-box f-strings are `pipeline.py:214` and `env/hycom.py:79,648,704` and they print a tuple of the *padded* box (south, north, west, east), not the mission's dict; left as they are. The `report.py:1197` "None" is batch B's, as decided.

### M-12. `run --mission <run dir>/mission.yaml --out <run dir>`
**Fixed** in `pipeline.run`: the byte copy happens unless the destination exists and `os.path.samefile` says it is the source. With `--seed` and the same file the file is rewritten with the new seed (the text is read before the file is opened for writing, so no crash; its comments are lost as already documented for `--seed`). Both cases tested, plus
a different directory still gets a byte-identical copy. `fetch` goes through the same `run()`.

### M-11. `--gpu-mem-gb`
**Fixed** in `budget.plan`, next to the `gpus < 0` check: `PlanError("--gpu-mem-gb X: the device memory must be a positive number of GB ...")` for nan, inf, -inf, negative and zero, whether or not GPUs are asked for (so `plan --gpu-mem-gb nan` without GPUs is also refused, instead of being silently ignored); and `if gpus > 0 and gpu_mem_gb is not None` (not truthiness). All three callers
(`__main__` plan, `Context._make_plan`, `pipeline_windows.py:627` which passes `les.get("gpu_mem_gb")`, absent or already positive) go through `plan()`. The CLI prints `error: ...` and exits 2 (PlanError is already caught in `main`). No argparse type added: one check, in the API.
One consequence to know: `_gpu_mem(a)` returns what nvidia-smi says, so a (never seen) `0` MB answer is now an error naming `--gpu-mem-gb` instead of a silent no-guard plan.

### M-18. `whatif --drop` of every vehicle
**Fixed** in `whatif.answer` (the command-line entry), before anything runs: `Invalid("--drop a, b would leave no vehicles; a mission needs at least one (it has [...])")`. `apply()` still returns an empty list (`run_variant` relies on it; tested). `Invalid` is a `ConfigError`, so the CLI prints `error:` and exits 2.
Not done (named, the "milder variant"): `--vehicle X --drop X` still gives an answer with no vehicle rows. The output is true (the vehicle is dropped, its links listed), no number is wrong, and you did not ask for it.

### M-9. The planner uses another machine's `throughput.json` with no warning
**Fixed**, but not as a plan note. Trace: `plan["notes"]` is read by `budget.describe` (the `plan` command, the run log, the replan log) and by `report._machine`, which writes both `describe` and `notes` into **report.json `machine`**; acceptance's `same_seed` normalises only `acceptance.VOLATILE` and `machine.notes` and
`machine.describe` are not in it. A host-dependent sentence there would make the same seed on burst and on orca give two different `report.json` (DECISIONS 290). (The plan notes are not in any stage ledger hash: `stage_hash` digests `plan["emulator"]` and `plan["workers"]`; the finding's "hashed by the emulator and report stage ledgers" is true of the report, not of the ledger hash. Either way the answer is the same.)
So: `budget.machine_warning(thr=None, host=None) -> str | None` compares `thr["machine"]` (`cpus`, `cpu`: what `bench/throughput.py` writes) with the host: **`os.cpu_count()`** and **`budget.cpu_model()`** (the same two reads the bench makes, `/proc/cpuinfo` "model name", else `platform.processor()`). A key the host does not give is not compared. Text:
"throughput.json was measured on homebase (8 CPUs, AMD EPYC 9V45 96-Core Processor, 2026-11-01); here it is 32 CPUs, not 8; CPU model AMD EPYC 7763 64-Core Processor, not AMD EPYC 9V45 96-Core Processor. The stage-1 costs and LES rates in the plan are that machine's: run `make bench` here to measure this one". It is printed by
`plan` as the last line, `note: ...` (`__main__.py`), and logged by `pipeline.run` right after the plan (`log`), and appears in no plan, no plan.json, no ledger and no report field. `plan["notes"]`, `describe()` and `measurement_warnings` are unchanged, so no golden or acceptance fixture needs regenerating.
**No false warning on a cgroup-limited box** - how I checked: (1) by reading what the bench records (`bench/throughput.py:197,202`: `os.cpu_count()` and the `/proc/cpuinfo` model), which is what `machine_warning` compares, and not `par.workers()`, which is the number a docker `--cpus` quota, the affinity mask, `CAFE_WORKERS` and the memory cap lower;
(2) by running it in the burst container with `--cpus 2` (the runner's `PM_CPUS=2`): `os.cpu_count() 32, par.workers() 2, _cgroup_cpus() 2`; with a `throughput.json` whose machine block is this box the warning is `None`, and against the shipped homebase block it is the true warning above;
(3) `test_r9_m9_a_cpu_limited_container_on_the_benchmarked_box_is_not_warned` (patches `par.workers`, `_cgroup_cpus` and `CAFE_WORKERS` to 1) and the mutant that used `par.workers()` fails it.
The warning is a note, not a refusal (the finding's choice). Today it fires on cafe-burst (32 CPUs, EPYC 7763) and will on orca for the homebase block in `config/throughput.json`: that is the true state, and it goes away once `make bench` is run there (which rewrites the machine block).

**The one call the report machine block should make** (batch B, `report._machine`, the `machine=` dict at the end; `first["machine"]["cpus"]` is the ledger's `os.cpu_count()`, recorded when the stage ran, so a later re-render on another machine reports the run's machine and not the laptop's):

```python
machine=None if first is None else dict(host=first["machine"]["host"], bench_id=first["machine"]["bench_id"], cpus=cpus,
                                        bench_warning=budget.machine_warning(budget.throughput(), host=dict(cpus=first["machine"]["cpus"])))
```

It must sit inside that `machine` sub-dict: `acceptance.VOLATILE` drops `machine.machine` as a whole, so `same_seed` stays exact. The CPU model is not in the ledger, so the report compares the count only (pass `host=dict(cpus=...)`; `machine_warning` skips the model then). Not in `notes` or `describe`. The HTML line at `report.py:1444`
("host, cpus, bench id") can print it after the bench id when it is not None.

## Second pass (adversary's finding on M-9, and the bench copy)

- **`machine_warning` on a malformed `machine` block.** Fixed in `budget.machine_warning` (the one place `plan`, `pipeline.run` and, at merge, `report._machine` all call): `machine` that is not a non-empty mapping is nothing to compare (None); `cpus` is compared only when it is a positive int (not bool, not `"8"`, not `8.0`), `cpu` only when it is a string. A good field is still compared beside a bad one. Before: `AttributeError: 'list' object has no attribute 'get'` out of `plan` and `run`, and `{"cpus": "8"}` printed "here it is 8 CPUs, not 8". Tests: `test_budget.py::test_r9_m9_a_machine_block_that_is_not_a_mapping_...`, `..._a_cpu_count_or_model_of_the_wrong_type_...`, `..._a_good_field_is_still_compared_beside_a_bad_one`; `test_cli.py::test_r9_m9_a_throughput_file_with_a_malformed_machine_block_still_plans`. Shown failing on `5965bd7` (15 of 21 cases fail; the 6 that pass there are inputs the old code already answered None for), passing now. Not made a refusal: a malformed machine block does not make the rates wrong, and `throughput()` validates no other block either.
- **`bench/throughput.py:_cpu`** now calls `budget.cpu_model()` (one rule for what the bench writes and what `machine_warning` compares). `test_bench.py::test_cpu_name_falls_back_to_the_platform_without_proc_cpuinfo` is replaced by `test_cpu_name_is_the_one_the_planner_compares_with` (delegation; the /proc/cpuinfo and `platform.processor()` cases are the same reader's and are tested in `test_budget.py::test_r9_m9_the_cpu_model_is_the_first_model_name_...`). Fails on `5965bd7`, passes now.
- **Not touched, still for the merge (other batches' files, `merged.md` says no file is shared):** the glider/usv/uas `load_platform` suffix rule and `physics/__init__.py:57` (batch C); `report.py:451`, `credibility.py:365/474/481/740` and the credibility decision for a platform outside `platforms/` (batch B); `report.py` `None` rendering and the machine-block call (batch B); consecutive-duplicate waypoints in the `USVSim`/`GliderSim` constructors (batch C). Editing them here would conflict textually with those branches. The two choices named above (`[A,B,A]` + `repeat`, `--vehicle X --drop X`) stay as decided.

## DECISIONS rows (text; the lead numbers them, last row is 460)

1. **M-2.** `config.load_mission` returns the mission with every mapping and list rebuilt (`config._unshare`), so a YAML anchor and alias (`deploy: &d {...}` ... `deploy: *d`) give each vehicle its own copy; the mission hash is unchanged. | Review round 9, M-2. `whatif.apply` and the emulator variants edit `deploy` and `task` in place: two vehicles sharing one mapping both moved (two `dlon: -1.0` gave -172.0 for both, not -171.0 each), and the what-if, the "what would fix it" line and the emulator's training rows described a mission that was not the one stated. Aliases stay legal.
   *Amends:* none (adds to the list of what `load_mission` guarantees, row 155).
2. **M-13.** `load_mission` refuses a `section` task whose consecutive waypoints are equal, naming `waypoints/<i>`; `[A, B, A]` is allowed. | Review round 9, M-13. `[A, A]` flew with no leg: cross-track error 0, `swept_off_track` never raised, the verdict `becalmed` (the same point as a station gave `swept_off_track`). *Amends 155* (which refused only fewer than two waypoints).
3. **M-20.** `load_mission` refuses a box with `lon_min == lon_max`: it is a strip with no width, never a full circle. `budget.padded_area_deg2` reads it the same way. | Review round 9, M-20. The error was "point (...) is outside the mission box", which never said the box is empty, and the budget read the same box as 360 deg wide. *Amends:* none (rows 24, 309, 372 are about the wrap, which is unchanged; 309's area now has one reading).
4. **M-33.** `load_mission` refuses `environment.ocean.path` that does not end in `.zarr` for `source: gofs31`; `lab_hycom` keeps any path. | Review round 9, M-33. The GOFS fetch writes `<stem>.zarr`, so `path: /data/ocean/my_gofs` was fetched to `my_gofs.zarr` and then the check on `my_gofs` failed after every download. *Amends 318* (adds a rule to its gofs31 side).
5. **M-1.** `config.platform_path(ref)` is the one rule for a vehicle's `platform`: a value ending in `.yaml` or `.yml` is a path as given, anything else is `platforms/<ref>.yaml`; `config.load_platform` and the hangar stage use it and the hangar stage records that file as a hashed ledger input. | Review round 9, M-1. `platform: platforms/seaglider.yaml` passed `validate`, then `run` stopped in the hangar stage looking for `platforms/platforms/seaglider.yaml.yaml`, and a patch in place would have left the file unhashed. The class loaders, the report's source label and the credibility keys follow at merge (see this hand-back).
6. **M-14.** A mission box in a message is `config.fmt_box(box)` ("lon 165 E to 165 W (across the antimeridian), lat -5 to 5, pad 2 deg"), never the dict. | Review round 9, M-14. A what-if row read `{'lon_min': 165.0, 'lon_max': -165.0, ...}` and the antimeridian wrap was unexplained. (The report's `None` for a vehicle with no failing member is batch B's.)
7. **M-12.** `run` does not copy `mission.yaml` over itself: with `--mission <run dir>/mission.yaml --out <run dir>` the file is left as it is, and with `--seed` it is rewritten with the new seed. | Review round 9, M-12. RUNBOOK invites that path and it ended in a `shutil.SameFileError` traceback with no `error:` line.
8. **M-11.** `budget.plan` refuses a `gpu_mem_gb` that is not a positive finite number (`PlanError` naming `--gpu-mem-gb`), whether or not GPUs are asked for; a memory of 0 no longer switches the guard off. | Review round 9, M-11. nan and inf were tracebacks, -5 stored a negative `max_cells`, 0 silently disabled the 85 % guard. *Amends 204.*
9. **M-18.** `whatif.answer` refuses a `--drop` that would leave no vehicle (`Invalid`, exit 2); `whatif.apply` still may return an empty mission (the emulator's `run_variant` relies on it). | Review round 9, M-18. `vehicles: []` is refused by `validate`, yet dropping all four was answered with exit 0.
10. **M-9.** The planner compares the `machine` block of `config/throughput.json` (CPU count, CPU model) with the host (`os.cpu_count()` and the `/proc/cpuinfo` model, as `bench/` records them, never `par.workers()`) and `plan` prints, and `run` logs, "throughput.json was measured on <id> (...); here it is ...: run `make bench`". It is not a plan note and is in no plan.json, ledger or report field outside `report.json` `machine.machine` (`acceptance.VOLATILE`), so one seed on two machines still gives one `report.json`. | Review round 9, M-9. q9 ran on a 32-CPU box with homebase's 8-CPU rates and no line said so. A `machine` block that is not a mapping, or a `cpus` that is not a positive integer or a `cpu` that is not a string, is not compared (no warning, no crash). *Amends 157* (whose warning covered load and another mission only) and *refers to 290* (why it is outside the plan notes). RUNBOOK 4's "once per machine" now has this line to point at.

## CHANGELOG lines (one each)

- `load_mission` unshares YAML aliases (a `whatif` or emulator variant moved both vehicles that shared a `deploy`/`task`); DECISIONS (M-2 row).
- `load_mission` refuses a section with two equal consecutive waypoints, a box with `lon_min == lon_max`, and a gofs31 `ocean.path` that does not end in `.zarr`; the empty-box message says so (M-13, M-20, M-33 rows).
- `platform: <path>` works through `run` (the hangar stage resolved only names): `config.platform_path`, and the platform file is a hashed ledger input (M-1 row).
- Messages name the mission box in words (`config.fmt_box`), not as a Python dict (M-14 row).
- `run --mission <run dir>/mission.yaml --out <run dir>` no longer ends in `SameFileError` (M-12 row).
- `--gpu-mem-gb` must be a positive number (nan, inf, negative and zero were a traceback or a silent no-guard plan); `whatif --drop` of every vehicle is refused (M-11, M-18 rows).
- `plan` and `run` say when `config/throughput.json` was measured on another CPU count or model (M-9 row).

## Doc sentences needed (RUNBOOK unless said)

- Where the mission is validated (what `validate` refuses): add "a `section` whose consecutive waypoints are equal; a box whose `lon_min` equals `lon_max`; a `gofs31` `ocean.path` that does not end in `.zarr`". And: "YAML anchors and aliases are allowed; each use is its own copy."
- Step 4, "once per machine" (and the troubleshooting table): "`plan` and `run` print `note: throughput.json was measured on <machine> (...); here it is ...` when the file was written on a machine with another CPU count or CPU model; the planned stage-1 times are that machine's. Run `make bench` here. The line is not in `plan.json` or `report.json`."
- The `--mission <run dir>/mission.yaml` sentence near line 167: "...a run can be resumed with `--mission <run dir>/mission.yaml --out <run dir>`; with `--seed S` the copy is rewritten with S."
- `--gpu-mem-gb`: "a positive number of GB".
- `whatif`: "`--drop` cannot name every vehicle."
- The mission `platform` key (docs where the mission file is described; the schema description is already updated): "a name in `platforms/`, or a path ending in `.yaml`/`.yml`, relative to where the command runs."

## What I checked could break, and how

- `load_mission` is called by `Context`, `__main__` (validate, plan, whatif, run, fetch, report), `bench/throughput.py` (`set_verdict=False`), `budget.bench_sortie_rate` and many tests. The new refusals only fire on inputs the code would have mishandled (zero-length leg, empty box, a store the check can never find); the shipped missions and `ci_fixture` load (tests, `Context` in every pipeline test). The unshare changes no value.
- `config.load_platform`: same branch as before (`platform_path` is the old expression moved), checked by `test_load_platform_by_name_by_path_and_errors` and the monkeypatched `config.PLATFORMS` in `test_hangar_fails_on_a_platform_number_without_provenance` (the helper reads the module global at call time).
- `budget.padded_area_deg2`: callers `env_model_gb`, `env_gb`, plan; the only input whose result changed is equal longitudes, which `load_mission` no longer lets in. `DEMO_BOX` (165 to -165) and the -180..179.9 box give the same area (tests).
- `budget.plan`: the new check runs before the existing ones' costs; every existing `gpu_mem_gb` in tests (24, 48, 96, 0.5, 16, 40) is positive. `gpus > 0 and gpu_mem_gb is not None` differs from truthiness only for 0.0, now refused.
- `pipeline.run`: `ctx.path("mission.yaml")` is called once where it was called once; the plan/log order is unchanged except the added `note:` line after `describe` (`log[0]` is still `describe(plan)`; `test_a_fresh_run_writes_the_plan...` passes). `fetch` calls it too.
- `whatif.answer` guard: callers `__main__._whatif` and tests; ids not in the mission fall through to `apply`'s "no vehicle" error as before.
- Hashes: `Context.hash`, `stage_hash`, `plan.json`, the ledgers and `report.json` receive no new field; `code_digest` changes (code and `cafe/schemas/mission.json` descriptions changed), which is expected on any commit.
- Schema: only `description` strings of `box`, `ocean.path` and `platform` changed.

## Needs from other batches (for the merge)

- **Batch C / the merge, `config.platform_path` in the physics loaders.** `physics/glider.py:86-88` and `physics/usv.py:128-130` decide "path" by `not path.suffix` (a dotted name `foo.v2` is treated as a path `foo.v2` and not found; `platforms/x.yml` is treated as a path only by luck); `physics/uas.py:99-100` uses `.yaml/.yml` like config. All three should do `path = config.platform_path(name)` (importing `config` is already done by `read_yaml`). `physics/__init__.py:57` ("see platforms/{ref}.yaml for the layout") should print `config.platform_path(ref)`. Tests monkeypatch `glider.PLATFORMS`, `usv.PLATFORMS` and `uas.PLATFORM` (`test_hangar_fails_on_...`): once the loaders call `config.platform_path` that test also needs `config.PLATFORMS` patched (it already patches `config` in the same loop; `uas.PLATFORM` keeps its own `parent`, so uas can keep its line).
- **Batch B / the merge, report and credibility keys.** `report.py:451` (`src = f"platforms/{platform}.yaml"`): use the display form of `config.platform_path(platform)` (repo-relative when inside the repo, as given otherwise). `credibility.py:365` builds `used` from the raw `v["platform"]`, `:474` matches it against `Path(i["file"]).stem` of the `platforms/*.yaml` items and `:481`/`:740` print/key `platforms/{u}.yaml`: with a path reference nothing matches, so the "no platform file ... is used" message appears and the file's provenance is not counted. Key by `config.platform_path(ref).stem` for a file under `platforms/`; a platform file outside `platforms/` is not in `platform_items(root)` at all, so decide whether to add its items (`_prov(read_yaml(path), ...)`) or to say it is not scored. This is the decision the finding left open ("by stem or by path").
- **Batch B, M-9:** the one call above, in `report._machine`; the HTML line may print it.
- **Batch B, M-14:** `report.py:1197` renders `None` as "none (no member failed)" in HTML only.
- **Batch C, M-13 (defence in depth):** drop consecutive duplicate waypoints in `USVSim.__init__` (`usv.py:~483`) and `GliderSim.__init__` (`glider.py:~274`) before the `len == 1` station collapse, so a caller that does not go through `load_mission` gets the station result, not a zero-length leg.
- **`bench/throughput.py:_cpu`**: done in the second pass (calls `budget.cpu_model()`).
- **Textual conflicts to expect:** `__main__.py` (the `plan` branch gets two lines; M-16/M-19 in the other half of batch A touch `_report`), `pipeline.py` (`run()` top: mission copy and the `note:` log line; `s_hangar`).

## Not done / open

- The three named choices above: the cyclic zero leg of `[A,B,A]` + `repeat`, `--vehicle X --drop X`, and aliases kept legal.
- `ruff`/`mypy` and the whole test files: see "Verified" below.

## Verified

- On the final tree (burst, 4 CPUs, 16 GB): `tests/test_config.py tests/test_budget.py tests/test_whatif.py tests/test_cli.py tests/test_pipeline.py tests/test_config_docs.py tests/test_platform_required.py` whole files, rc=0 (log `r9a_final`; an earlier identical run before the schema-description edit also rc=0). The same five files on the untouched `91c9777`: rc=0 (baseline), so no failure is inherited or hidden.
- `ruff check cafe/pm tests`: clean. `mypy cafe/pm` (strict): no issues in 54 source files.
- `python -m cafe.pm audit --code-only`: the banned-token and commented-out-code scans pass; the one problem is the known one, "mutation: no stored result at docs/mutation.json".
- Not run: the full 75-minute suite, coverage gates (the new lines in `config.py`, `budget.py`, `whatif.py` each have a test that executes them; `physics`, `stats`, `env` are untouched), `make mutation`, a real `run` on demo data, anything on orca.
- Cleaned up: the throwaway mutant worktree and its burst directories, my base/mut/audit directories; `pm_r9a` and the logs `r9a_full`, `r9a_final` are removed last.
