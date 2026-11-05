# Round 9, batch C handback (vehicle physics): M-22, M-27, M-3, M-25, M-26, and the M-13 constructor part

Branch `r9-c` (worktree `/Users/aaroh/Downloads/everything/cafe-r9c`), cut from 91c9777. Files changed: `cafe/pm/physics/{__init__,uas,usv,glider,comms}.py`; tests `test_uas.py`, `test_usv.py`, `test_glider.py`, `test_comms.py`, `test_platform_required.py`. No docs edited. The `load_platform` suffix rule is untouched.

Every new test was run on the code at 91c9777 (a detached worktree with only the test files copied in) and fails there; all pass on r9-c. The three existing USV tests that pinned `first['no_current_data'] == 0.0` for an environment hole now pin `60.0` (see M-27); they fail on 91c9777 with the new value, which is the intended change of the rule, not a weakened assertion.

---

## M-22. Platform loaders require the `mission_defaults` keys the simulators index

What was built: `glider.MISSION_REQUIRED` (new: `dive_depth_m` pos, `station_tol_m`, `lost_hours`, `wp_radius_m`, `unreach_hours`, kind `any` = finite) is passed to `check_params` in `glider.load_platform` for both kinds; `usv.MISSION_REQUIRED` grows from `cap_cycles` to all eight keys the model indexes (`becalmed_after_h`, `calm_sustain_s`, `track_tolerance_km`, `corridor_km`, `wp_radius_m`, `roll_limit_deg`, `stall_sustain_s` kind `any`; `cap_cycles` stays `ge1`). A missing key is `ValueError: <file>:mission_defaults: missing ['<key>']; add them (see platforms/<kind>.yaml for the layout)`. It reaches the user as a `ConfigError` at mission load and a failed `provenance_<platform>` hangar check, as for `params`. Stage 3 (`pipeline_windows.py:524`), `report.py:448/:602` and `stage1.py:112` need no edit.

- All keys are required for every mode (the finding allowed this): a glider file with only the section keys, or a USV file without `corridor_km`, is now refused even for a mission that never reads the key. The shipped files all carry every key. I chose "all" because the report and stage 3 read the platform's own `dive_depth_m` and `calm_sustain_s`/`becalmed_after_h` whatever the mode, and a platform file describes a vehicle.
- Ranges: only presence is new. The new keys are kind `any` (finite, signed), exactly what `check_params` already enforced for unlisted keys, so no file that loaded before is refused for its value. `dive_depth_m` is `pos` because the `GliderSim` constructor already refuses a value of 0 or less (round 8, M-28) with its own message; a platform default of 0 now fails at load instead. Tightening the ranges of the other keys (a negative `corridor_km` is nonsense) is a separate question; I did not take it.
- Tests: `test_usv.py::test_r9_m22_*` (one case per key, plus the table equals the shipped file's key set), `test_glider.py::test_r9_m22_*` (5 keys x 2 kinds), `test_platform_required.py::test_r9_m22_every_mission_default_the_models_and_their_readers_index_is_in_a_loader_table` (scans `md["..."]` of glider.py and usv.py, and `["mission_defaults"]["..."]` / `("mission_defaults", "...")` of report.py, stage1.py and pipeline_windows.py; `station` and `waypoints` are the mission's own geometry, not platform defaults, and are excluded).
- The finding said fixtures with `mission_defaults: {}` in test_glider.py need updating. None did: the three that write that line (test_glider.py:78, :612; test_usv.py:965) are refused earlier (bad `params` leaf, missing `kind`/`params`), and still are.

**DECISIONS row (new).** Each platform loader also requires every mission default its model indexes: `glider.MISSION_REQUIRED` (`dive_depth_m` above 0, `station_tol_m`, `lost_hours`, `wp_radius_m`, `unreach_hours`; both kinds, every mode) and `usv.MISSION_REQUIRED` (all eight keys; `cap_cycles` 1 or above as before). A missing key is a `ValueError` naming `<file>:mission_defaults` and the key, so a `ConfigError` at load and a failed `provenance_<platform>`. Only presence is new; the values of the new keys must be finite and no more. A test reads the `md["..."]` and `["mission_defaults"]["..."]` literals of the two models, the report, stage 1 and the stage-3 windows and requires each in a table. | Review round 9, M-22 (C-2). `run` died in a bare `KeyError` at the first step that read a deleted key (`corridor_km`, `station_tol_m`, ...). **Amends 279** ("`mission_defaults` of a glider or USV must be finite but are not required"). A file that only a section mission used and that lacks a station key is now refused (the shipped files are not affected).

**CHANGELOG.** Platform loaders refuse a glider or USV file that lacks a mission default the model indexes (`corridor_km`, `station_tol_m`, ...), naming `<file>:mission_defaults` and the key, instead of a `KeyError` in the first step that reads it (round 9, M-22).

**Docs.** `docs/RUNBOOK.md`, wherever the platform-file check is described: "a glider or USV platform file must carry every key of its `mission_defaults` block (`platforms/seaglider.yaml`, `platforms/saildrone_explorer.yaml` show them); one that lacks a key is refused at load naming the file and the key." Any doc that says mission defaults "must be finite but are not required" (DECISIONS 279 only, as far as I found) is superseded.

**Could break, and how checked.** Anything that loads a platform file with a missing mission-default key: the shipped files (all keys present; `test_the_shipped_platform_files_satisfy_their_loaders`), test fixtures that write a platform (searched `mission_defaults` in tests/: none builds a partial block), the hangar and `config.load_mission` (go through `load_platform`; `test_platform_required.py`, `test_cli.py`, `test_config.py` run, below). `stage1._vehicle` builds the mission dict from `P.get("mission_defaults", {})` and the task, never from a bare platform: unchanged. Whole files run: see the end.

---

## M-27. USV `no_current_data` stamped at the start of the step, every other flag at its end

What was built: `USVSim._tf` (set to `t0` in `__init__`, to `t + dt` at the top of `step`), and `_flag` stamps `first[name]` with it, as `GliderSim._tf` does. A hole in wind, current, waves or insolation now all read `t + dt` of the step that met it (60 s at the stage-1 step). The start-position flag at construction stays `t0` (DECISIONS 356, `test_r7_m16_a_non_finite_start_position_is_flagged_at_t0_and_the_run_stays_finite` unchanged). Only `_flag` reads the stamp, and `_flag` is called only in `__init__` and `step`.

- Existing tests changed: `test_a_non_finite_current_is_a_labelled_failure_for_that_member_and_the_run_goes_on`, `test_a_current_that_is_nan_everywhere_fails_every_member_the_way_the_gliders_no_flight_does` and `test_a_wave_state_that_is_not_a_number_fails_every_member_from_the_first_step_and_the_run_goes_on` pinned `first == 0.0` for a hole met in the first step; they pin `60.0` (the dt of those runs) now.
- New test: `test_r9_m27_no_current_data_is_stamped_at_the_end_of_the_step_whatever_the_hole_and_the_start_flag_stays_t0` (wind, insolation and wave holes at dt = 60 all give 60.0; a NaN start stays 0.0 and a later step does not move it).
- No verdict or gate changes: `first` feeds `failed_at`, what-if and the report only.

**DECISIONS row (new).** Every `USVSim` flag is stamped with the end of the step in which it first holds (`_tf`, as the glider's); the one exception is a start position that is not finite, stamped `t0`. `no_current_data` met in a wind, current or wave lookup was stamped at the start of the step. | Review round 9, M-27 (C-8). A wind hole gave `t` and an insolation hole in the same step `t + dt`, which row 356 had called "the end of the step ... as the glider". **Amends 356** (its flag-time sentence now holds for every hole, not only the shortwave one) **and 241** ("first at the step time" is the end of the first step). Row 406's glider rule is unchanged.

**CHANGELOG.** USV `no_current_data` from a wind, current or wave hole is stamped with the end of the step, like every other USV flag and the glider's; it was the start of the step (round 9, M-27).

**Docs.** `docs/PHYSICS.md` USV failure-flag paragraph: "All flags of a step carry the time at its end; a start position that is not finite carries t0." (The module docstring of `usv.py` already says so now.)

**Could break.** Anything that read `first['no_current_data']` for a USV as the step start: `failed_at` in stage 1, the what-if rows, the report's first-failure time. Those take `first` as a time to display or to order (`stage1.summarize`: earliest first time over modes, `first_fail_t`; `pipeline.py:1179`, `whatif.py:268`: earliest per member); none assumes 0.0 for a hole. One visible effect: `first_fail_t` of a member whose first failure is a hole in the first step is 60 s, not 0. The stage-1 and report test files ran green (below).

---

## M-3. UAS has no `no_current_data` path

What was built, and where it differs from the finding's suggestion:

1. `uas.FLAGS` gains `"no_current_data"` as the last entry (so `first_failure_mode` indices into `FLAGS` do not move).
2. **The check is in `uas.simulate`, not in `make_wind`.** `simulate` is the one place every wind function's output goes through (the env mean from `make_wind`, plus its turbulence and gust, plus any test or receipt function). For each record interval it takes the stacked `(blocks, 3, M)` wind, finds the member-blocks whose vector is not finite, replaces them by zero (so the state stays finite), and flags a member that is flying (`phase < DONE` at the start of the interval) from the end of the first such 50 ms block (`t_first` = `(k + 1) * 50 ms` after launch, like the other UAS flags). The flag is sticky: it is set once and kept, so the 1 s held mean ending does not clear it. A member that is down, or was scrubbed, is zeroed but not flagged. `make_wind` is unchanged; the SITL path (`fly_sitl`, which uses `make_wind` through `_Sim1`) still passes a NaN wind to the firmware, and returns no `no_current_data` flag (one member, never adopted by a stage, M-26).
3. The member keeps flying on zero wind (as the glider and USV do) and is a labelled failure (`failed` is any flag). Its `soc_end`, `max_tilt_deg` and track stay finite, so Stage 1's min over `soc_end` is not turned NaN.
4. **Sibling found by the sweep and fixed: `fly_sortie`'s air state at the ship.** `env.air(...)` at the ship feeds the air density of every member. A NaN density (finite wind, NaN pressure or temperature) gave a NaN vehicle for a member that was not scrubbed: NaN `soc_end`, `max_tilt_deg`, `profile_incomplete` and only by luck `no_current_data` (the NaN position propagating into the wind lookup). It is now a scrub, the same rule as no wind at the ship: `gate["ok"]` includes `isfinite(rho)`, and the density passed to `derive` for such a member is 1.0 (never read: it is not flown) so the batch stays finite. `launch["ok"]` shows it.
5. `FLAGS`-keyed code needs no edit: `fly_mission`, `stage1` (`fail`/`first` over `uas.FLAGS`) and the stage-1 test fixtures all build from `uas.FLAGS`. Every fixture that builds `{k: ... for k in uas.FLAGS}` was checked (test_stage1.py:253, :299, :1119 and :237/:238) and runs green. A hole beyond the sortie's reach does not flag: `test_r9_m3_a_hole_beyond_the_reach_of_the_sortie_does_not_flag_and_changes_nothing`.

Sweep of every lookup in the three vehicle classes, with what it does with a NaN:

| class | lookup | result |
|---|---|---|
| UAS | `make_wind` mean wind (in flight) | was silent; now `no_current_data` (this finding) |
| UAS | turbulence / gust arrays from the caller | same path through `simulate`; now `no_current_data` |
| UAS | `wind_ref` (launch gate) | NaN mean compares False: scrubbed (already) |
| UAS | `env.air` at the ship (`rho`) | was a NaN vehicle; now scrubbed (fixed here) |
| UAS | `fly_sitl` wind and air | not changed (see above) |
| USV | wind, current, waves, insolation, start position | already `no_current_data` (rounds 4, 6, 7) |
| USV | `sde_displacement` | depends on latitude and time only, no field lookup: cannot be a hole |
| glider | current (all members), wind (surfaced), start position | already `no_current_data` (round 8, M-14) |
| glider | `env.density` and `env.sst` in `_state` (in flight) | **found, not changed**: a NaN gives `no_flight` (the member fails, positions and energy stay finite; reproduced with a hole east of the start). Same mislabel round 8 M-14 removed for the current; `no_flight` says "flight model failed" for a hole in the input. |
| glider | `env.depth` (begin of dive) | **found, not changed**: a NaN floor gives `seafloor` (the member fails and stays finite). A NaN depth met only mid-dive (`step`'s seafloor test, `depth >= NaN` is False) is silent but the next dive start flags it. |

The two glider rows are the same class (a hole in the input labelled as a vehicle failure) but they are not silent and not NaN, so they are outside this finding's defect; relabelling them is about six lines in `GliderSim.step` and `_begin_dive` and changes the failure-mode counts of runs over real HYCOM stores (a density that is NaN below the store's own sea floor, where `no_flight` fires today, would become `no_current_data`). That is the lead's call; I did not take it.

Tests: `test_uas.py::test_r9_m3_*` (wind hole met in flight, flag only on the member that flew into it, flight identical to the clean one because the env's wind is 0; stickiness and stamp time (a one-lookup hole at t = 10 s gives `t_first` 10.05); a hole beyond the sortie's reach; a scrubbed member not flagged; the air-state scrub).

**DECISIONS row (new).** A UAS member met by a wind vector that is not finite (the mean from the store, or its turbulence and gust) is flagged `no_current_data`, the sixth UAS failure mode (`uas.FLAGS`, last), from the end of that 50 ms block, and is flown on a zero wind from then on, so its battery, tilt and track stay finite; the flag is kept for the rest of the sortie (the 1 s held mean does not clear it), and a member that is down or scrubbed is not flagged. A ship whose air state (pressure, temperature, humidity) is not finite scrubs the launch, as a ship with no finite wind does. | Review round 9, M-3 (C-1). A NaN wind met after launch left every UAS flag False but `profile_incomplete` with `soc_end`, `max_tilt_deg` and the position NaN. **Extends 241, 308, 356 and 406 to the third vehicle class**; the report text of row 406 (`MODE_TEXT["no_current_data"]`) serves it without change. Zero wind is a stand-in for the member's remaining flight; the labelled failure pushes toward NO-GO, never toward GO (as 308).

**CHANGELOG.** UAS: a wind vector that is not finite in flight is a labelled `no_current_data` failure (the member flies on zero wind), not a silent NaN vehicle; a ship with no finite air state scrubs the launch (round 9, M-3).

**Docs.** `docs/PHYSICS.md` line ~726 (UAS flags): add "`no_current_data` (the wind at a flying member was not finite: it flew on zero wind from that 50 ms block; a ship with no finite air state is scrubbed instead)". `docs/PHYSICS.md` line ~875 and any table that lists "the UAS failure modes" as five: six now. `docs/CREDIBILITY.md` needs nothing.

**Could break.** (a) Any code that iterates `uas.FLAGS` and indexes a dict it did not build from it: grepped all uses (stage1.py:386/388, fly_sortie/fly_mission, tests): all derive from `FLAGS` or from `fly_sortie`'s output, which now carries the key. `fly_sitl` returns only four flags and no `FLAGS`-keyed consumer reads it (test_budget.py forbids stage1/pipeline naming it). (b) A run whose store has a masked cell under a flight: it now reports `no_current_data` where it reported nothing or `profile_incomplete`; verdict direction is toward NO-GO only. (c) `first_failure_mode` index values: unchanged for the five old modes (the new one is appended). (d) `simulate` callers passing a wind function whose output has a NaN on purpose: only the new tests. Whole files run: see the end.

**Needs from batch B.** Nothing is required: `report.MODE_TEXT["no_current_data"]` exists already (shared by the glider and USV) and its wording covers a UAS ("no finite wind ... at the vehicle's position ... a hole in the input"); a hole at the ship scrubs rather than flags, so the text needs no "at the ship" clause. The finding's "batch B adds the `MODE_TEXT` entry" is therefore a no-op. I found nothing in `report.py` or `stage1.py` that enumerates the UAS modes as a fixed list (`stage1.py:756` picks the margin by the dominant mode's name and falls back to `margin`, which is finite now).

---

## M-25. `comms.acoustic_link` with a scalar range and an ambiguous Bellhop link

Built: `m_t = np.asarray(acoustic_margin(...), float)` in `acoustic_link`, so `margin = m_t.copy()` is an ndarray for a 0-d input. Production callers (`stage1.py:532/:545`) pass n-d arrays and see no change. For a scalar `r` the results `thorp_margin` and `margin.value` are now 0-d arrays instead of `numpy.float64` (the finding anticipated this); `Tagged.value.shape == ()` still holds. Test: `test_comms.py::test_r9_m25_a_scalar_range_with_an_ambiguous_link_is_refined_like_an_array` (a 60 dB window makes 4.5 km ambiguous, `bellhop_tl` faked; fails with `TypeError` before; scalar and 1-element array agree). The existing scalar-in test (`ambiguous_db=0.1`) is unchanged and still passes.

**DECISIONS row.** None needed beyond the CHANGELOG line (no behaviour a user sees; no earlier row says anything about scalar inputs). If the lead keeps one per finding: `comms.acoustic_link` accepts a scalar range with an ambiguous Bellhop link; `thorp_margin` and `margin.value` are 0-d arrays for a scalar range. | Review round 9, M-25 (C-6). `numpy.float64` has no item assignment. Reverses no row.

**CHANGELOG.** `comms.acoustic_link` no longer raises `TypeError` for a scalar range with an ambiguous Bellhop link (round 9, M-25).

**Could break.** A caller that relies on `margin.value` being a `numpy.float64` for a scalar range (hashing it, JSON-dumping it). Searched: `acoustic_link` is called only at `stage1.py:532/:545` (arrays) and in tests; the scalar case is test-only. `test_comms.py`, `test_comms_exact.py` run green.

---

## M-26. `fly_sitl` docstring

Built: the docstring now lists what is returned (`flags` with the four keys, of which `wind_exceeds_airspeed` and `lost_link` are not modelled and always False; no `profile_incomplete`, no `no_current_data`; `t_end`, `energy_wh`, `soc_end`, `max_tilt_deg`, `landed`, `scrubbed`, `track` without `phase`, `sitl=dict(instance, messages, workdir, attitude)`) and names every `fly_sortie` key it lacks. No fields were added (DECISIONS 310: no stage adopts SITL members). Test: `test_uas.py::test_r9_m26_fly_sitl_documents_the_dict_it_returns_not_fly_sortie_s` runs `fly_sitl` against the existing fake firmware and checks that every returned key and flag is named in the docstring and every `fly_sortie` key it lacks is named as absent; it fails on the old docstring ("same fields as fly_sortie").

**DECISIONS row.** None (documentation only; row 310 already says no stage flies a SITL member). **CHANGELOG.** `uas.fly_sitl`'s docstring states the dict it returns instead of "same fields as fly_sortie" (round 9, M-26). **Docs.** None.

---

## M-13, constructor part

Built: `physics.drop_repeats(wps)` (new, in `physics/__init__.py`, shared) removes each waypoint equal to the one before it. `USVSim` calls it before the `len == 1` station collapse (so `[A, A]` is exactly the station A, `mode == "station"`), `GliderSim` calls it in section mode (so `[A, A]` is the single waypoint `[A]` and `[A, B, B]` is `[A, B]`; the glider has no station collapse and no track test, so the observable effect is the waypoint count and index, not a flag). Only a repeat next to its twin goes: `[A, B, A]` is kept (a return to A is a different section). A repeating USV section whose last point equals its first (the wrap `B -> A`) is not de-duplicated: no mission sets `repeat`, only tests do; noted, not built.

Tests: `test_usv.py::test_r9_m13_a_repeated_waypoint_is_one_waypoint_and_a_section_of_one_point_is_the_station` (`[A, A]` equals the station run in positions, flags and `xte_max`; `[A, B, B]` equals `[A, B]`), `test_glider.py::test_r9_m13_a_repeated_waypoint_is_one_waypoint`. I grepped missions/ and tests/ for deliberate repeated waypoints (loiter): none in missions; the tests that repeat a point use `repeat=True` with distinct points.

**DECISIONS row (new).** `USVSim` and `GliderSim` drop a waypoint that equals the one before it (`physics.drop_repeats`) before anything else reads the list, so a USV section of identical points is the station, with its distance test, and not a section with a zero-length leg whose cross-track error is 0. This is the second line of defence behind `load_mission`'s refusal (batch A). | Review round 9, M-13 (A-9). `[[-165,0],[-165,0]]` ran with the track test silently off (`becalmed` only, `xte_max` 0) where the same point as a station flags `swept_off_track`. **Amends 155** ("a `section` with fewer than two waypoints" is refused at load; the constructors now also tolerate what gets past). Needs the batch-A row for the load refusal.

**CHANGELOG.** `USVSim` and `GliderSim` drop a waypoint equal to its predecessor; a USV section of one distinct point is the station (round 9, M-13).

**Could break.** The glider's recorded `wp` index for a mission with a repeated waypoint (one fewer step); nothing outside the glider reads `.wps` or `wp` (grepped cafe/pm). A mission file with `[A, B, B]` now behaves as `[A, B]`, which is what its leg geometry already did.

---

## Needs from other batches

- Batch A (M-13): `config.load_mission` should refuse a section with fewer than two distinct points and consecutive duplicates, naming the index. My constructors work with or without it. If A also adds a test that a mission with `[A, A]` raises, nothing in my tests conflicts.
- Batch A (M-1): nothing; the suffix rule in `glider/usv/uas.load_platform` is untouched, as asked. The lines to change at merge are `if not path.suffix:` in each of the three.
- Batch B: nothing required (see M-3). `report.py:448/:602` read `mission_defaults` keys that the loaders now require, so a re-check of the report's own `KeyError` guard is not needed.
- Lead (decision): the glider density/sst/depth relabel described in M-3's sweep table.

## Verification

Run on cafe-burst (`pm_r9c`), exit codes read from the log:
- the five touched test files, whole: `test_comms.py`, `test_comms_exact.py`, `test_platform_required.py` (rc 0); `test_usv.py`, `test_glider.py`, `test_uas.py` (rc 0).
- the files that read what changed, whole (rc 0, one run): `test_stage1.py`, `test_report.py`, `test_cli.py`, `test_config.py`, `test_config_docs.py`, `test_whatif.py`, `test_credibility.py`, `test_uas_exact.py`, `test_receipts.py`, `test_vv.py`, `test_reproducible.py`, `test_budget.py`, `test_pipeline.py`, `test_bench.py`, `test_acceptance.py`, `test_ledger.py`. The last edits after that run were line wraps and comments only; the five touched files plus `test_comms_exact.py` and `test_uas_exact.py` were run again afterwards (rc 0).
- `python -m cafe.pm audit --code-only`: the banned-token and commented-code scans pass; its only problem is the missing stored mutation result (`docs/mutation.json`), as on any checkout without `make mutation`. **Not run: `make mutation`** (hours). The changed physics code (`uas.simulate` hole path, `usv._tf`, `drop_repeats`, `acoustic_link`) is in the mutation scope of physics, so the stored score needs a rerun at merge; the new tests were written to kill the obvious mutants (the stamp time, the argmax block index, the sticky flag, the phase mask, the `isfinite(rho)` term, the neighbour comparison).
- `python -m ruff check` and `python -m mypy` (strict, 54 source files) clean.
- mutants: the same new tests on a detached worktree at 91c9777: all new tests except the one "hole beyond the reach does not flag" negative control fail (`KeyError: 'no_current_data'`, `TypeError`, no `MISSION_REQUIRED`, wrong stamp time, `mode == 'section'`), pass on r9-c.


---

# Leftovers pass (second commit on r9-c)

The seven items the first pass listed as left. Tests: `test_glider.py::test_r9_a_*` and `test_r9_an_*`, `test_usv.py::test_r9_a_*`, `test_uas.py::test_r9_fly_sitl_labels_*` (and `test_r9_m26_*` now pins five flags). Each new test fails on 90d27d6 (a detached worktree with only the test files copied in) and passes on r9-c; the one negative control (`test_r9_an_sst_hole_under_a_slocum...`) passes on both by design.

## 1. Glider: a hole in the density, SST or depth is `no_current_data` (decided: done, not left to the lead)

- `step`: a member in flight whose flight model failed (`~st.ok`) while the density or the temperature it was given is not finite is `no_current_data`; `no_flight` is only a flight that failed on finite inputs. The test is on the inputs the model got, so a Slocum (which does not read the SST) over an SST hole still flies and is not flagged, as before.
- `_begin_dive`: a floor that is not finite is `no_current_data`; `seafloor` is the floor being too shallow (a depth of 0 on land is still the sea floor, per `protocol.depth`).
- Sibling found by the sweep: the end-of-step `seafloor` test (`depth >= NaN` is False) was blind over a depth hole while under water, and said nothing until the next dive start, hours later or never. A member below the surface over a depth that is not finite is now `no_current_data`; a surfaced one is left to its next dive start.
- Effect on real stores: a density that is NaN where `no_flight` fired before (below a store's own floor) is `no_current_data` now, so failure-mode counts move from `no_flight` to `no_current_data`, member by member; no member that passed fails (except the new mid-dive depth hole, which passed silently before) and none that failed passes.
- `report.MODE_TEXT["no_current_data"]` (batch B's file, not edited here) lists "wind, current or wave state ... or insolation"; it should add "density, sea-surface temperature or water depth". The sentence ends "a hole in the input", which already holds.
- **DECISIONS row (new).** A glider member whose flight model fails while the density or the temperature it was given is not finite, whose floor at the start of a dive is not finite, or that is under water over a floor that is not finite, is `no_current_data` (the glider's input hole, as the current and the wind of row 406); `no_flight` is only a failure on finite inputs and `seafloor` only a floor too shallow. | Review round 9, batch C leftover. **Extends 406** (current and wind) to the density, the SST and the depth. Counts of `no_flight` and `seafloor` on a store with holes become `no_current_data`.
- **CHANGELOG.** Glider: a hole in the density, SST or water depth is `no_current_data`, not `no_flight` or `seafloor`; a depth hole met under water is flagged where it was silent (round 9).

## 2. `fly_sitl` and a wind that is not finite

Fixed in `_Sim1.step`, the one place the SITL physics reads the wind: a vector that is not finite is replaced by zero (as `simulate` does) and `_Sim1.hole` is set; `fly_sitl` returns it as `flags["no_current_data"]` (an array of one). The firmware no longer receives NaN. The docstring and `test_r9_m26_*` name the fifth flag. Nothing else reads a SITL result (`fly_sitl` is called only by `_sitl_receipts`, which reads `landed`, `track`, the energy and the attitude). DECISIONS 310 (no stage flies a SITL member) is unchanged. **CHANGELOG.** `fly_sitl` gives the firmware a zero wind for a wind lookup that is not finite and reports `no_current_data` (round 9).

## 3. A repeating USV section whose last point equals its first

`physics.drop_repeats(wps, cyclic=False)`: with `cyclic` a last point equal to the first goes too (its wrap leg has length zero and its capture is at once). `USVSim` passes `repeat` (read first now). `[A, B, A]` with `repeat` flies as `[A, B]` round and round (same positions, `test_r9_a_repeating_section...`); without `repeat` it is unchanged (the return to A is the last leg). Glider sections never repeat. **Amends the M-13 row**: "...and a repeating section's last point equal to its first".

## 4. Ranges of the new mission-default keys

USV: `becalmed_after_h` above 0 (the mission schema's `exclusiveMinimum`), `calm_sustain_s` and `stall_sustain_s` 0 or above (0: at once), `track_tolerance_km` above 0 and at most 1000 (the schema's maximum), `corridor_km` and `wp_radius_m` above 0, `roll_limit_deg` above 0 and at most 180. Glider: `station_tol_m` and `wp_radius_m` above 0 (a radius of 0 is never reached), `lost_hours` and `unreach_hours` 0 or above. Every shipped file passes (`test_the_shipped_platform_files_satisfy_their_loaders`); a file with a value outside is refused as `<file>:mission_defaults.<key>: ... must be a finite number <rule>`. **Amends the M-22 row** ("only presence is new; the values must be finite and no more" now reads: and in the stated range). The ranges are choices; each is in the refusal text.

## 5. Not done

- `make mutation` (hours): the stored physics score needs a rerun at merge (`uas.simulate`, `usv._tf`, `drop_repeats`, `acoustic_link`, `_Sim1.step`, the glider hole labels changed).
- The full 75-minute suite. The touched files and the files that read them ran whole (below).
- Batch A's `load_mission` duplicate-waypoint refusal and the `load_platform` suffix rule: the lead's, as asked.

## Verification of the leftovers pass

On cafe-burst (`pm_r9c`), exit codes from the logs: whole files `test_glider.py`, `test_usv.py`, `test_uas.py`, `test_uas_exact.py`, `test_comms.py`, `test_comms_exact.py`, `test_platform_required.py` (rc 0); the readers whole in one run (rc 0): `test_stage1.py`, `test_report.py`, `test_cli.py`, `test_config.py`, `test_config_docs.py`, `test_whatif.py`, `test_credibility.py`, `test_receipts.py`, `test_vv.py`, `test_reproducible.py`, `test_budget.py`, `test_pipeline.py`, `test_bench.py`, `test_acceptance.py`, `test_ledger.py`. After those runs only comments and a docstring wrap changed; the touched files (glider, usv, uas, uas_exact, platform_required, comms) ran again (rc 0). `ruff check cafe/pm tests` and `mypy cafe/pm` (strict, 54 files) clean. `audit --code-only`: the banned and commented-code scans pass; the one problem is the missing `docs/mutation.json`.
