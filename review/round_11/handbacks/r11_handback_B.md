# Round 11 batch B hand-back (branch r11-b)

Findings M-11, M-12, M-13, M-23, M-26, M-27, M-28. No DECISIONS, CHANGELOG, RUNBOOK or PHYSICS file was edited; the text for them is below.
The DECISIONS numbers are left blank (`NNN`): batch E numbers them after 592.

Everything ran on orca (proot, 2 CPUs, `pm_r11b*` directories). Fast receipts, all 350 rows, before (3ce8e09) and after: 0 values or verdicts moved (30 FAIL rows in both, the by-design ones).
Mutants: 27 hand-made mutants of the changed lines (the old code of M-11, M-12 and M-13 among them) plus the refuted lever-arm one, each run alone in a throwaway detached worktree (`cafe-r11b-mut`, removed afterwards): every one is killed (list at the end). The test run of each is only the new test(s) of its finding.

## M-11 curved-wall bounce-back, moving-wall term

DECISIONS row:
> NNN | `lbm.bounce_back` divides the moving-wall term by 2q on every link with q >= 1/2 (`wall = where(q >= 0.5, 1/(2q), 1)`), because Bouzidi, Firdaouss & Lallemand (2001) divide the whole q >= 1/2 expression by 2q: `f_qbar = [f_q+(x) - 6 w rho c.u_w]/(2q) + (2q-1)/(2q) f_qbar+(x)`. Before, the term of the halfway wall was subtracted unscaled, so on a uniform equilibrium whose velocity is the wall velocity a curved wall sent back `feq(-c)` only at q = 1/2. Links with q < 1/2 and the scalar halfway path (no `qdist`) are untouched: halfway results are bit-identical. A sphere carried by the stream (`nest.uniform_flow_force(bouzidi=True)`, 40x28x28, r 5, 400 steps): max |F|/(rho U^2 d^2) 7.78 before, 4.1e-6 after; mean of the norm over the last 100 steps 0.447 before (the reviewer's 0.389 is another average of the same run), 2.8e-6 after; the halfway wall's 8.6e-6 is unchanged. Tests: `tests/test_lbm.py::test_a_curved_wall_carried_by_the_fluid_leaves_a_uniform_equilibrium_unchanged_at_every_wall_distance`, `tests/test_nest.py::test_uniform_flow_gives_zero_force_on_a_curved_bouzidi_sphere_too`. | Review round 11, M-11 (C-1). Option of a `1/(2q)` factor only where `qdist` is an array, so no halfway or wall-model run changes.

Amends: 76 (it lists "Bouzidi curved walls, Ladd moving walls" with no word on their combination: add "the moving-wall term is scaled by 1/(2q) for q >= 1/2, row NNN"). PHYSICS 14.1 needs its sentence changed (below). Row 353 (300 B/cell) is unaffected.

CHANGELOG: `Fix: a curved (Bouzidi) wall moving with the fluid exerted a force (lbm.bounce_back kept the halfway wall's moving term for q >= 1/2); the term now takes the 1/(2q) too. Static-wall sphere Cd and every halfway or windowed result are unchanged (review round 11, M-11).`

Doc sentence, `docs/PHYSICS.md` 14.1 (line ~942), replace the moving/curved wall clause by: "moving wall (Ladd 1994): f_qbar = f_q+ - 6 w_q rho c_q . u_w; curved wall (Bouzidi, Firdaouss & Lallemand 2001): linear interpolation on the wall fraction q, exact sphere/ellipsoid distance; for q < 1/2 f_qbar = 2q f_q+(x) + (1-2q) f_q+(x - c_q) - 6 w_q rho c_q . u_w, for q >= 1/2 f_qbar = [f_q+(x) - 6 w_q rho c_q . u_w]/(2q) + (2q-1)/(2q) f_qbar+(x), so a body carried by the fluid feels no force at any q (review round 11, M-11)."

What I checked could break, and how:
- Callers of `bounce_back`: only `nest.step` (one call, nest.py:206), and `tests/test_lbm.py`, `tests/test_nest.py`. `wallmodel.wall_force` does not call it (it adjusts the post-collision populations before `nest.step` does); wallmodel.py:19 and :190 only mention it.
- The `qd` array reaches `nest.step` only from `nest.make_geom(qdist=...)`: `nest.sphere_drag` (static body, `u_wall` = 0, so the moving term is 0 and nothing changes) and `stack_geoms` (pads halfway bodies with q = 0.5, where the factor is 1/(2 x 0.5) = 1: identical). `windows.run_window` and `pipeline_windows` pass no `qdist`: scalar path, unchanged. Fast receipts: 0 of 350 moved (rec_base vs rec_after, id by id).
- Slow receipts (not rerun, hours): the stored `nest_sphere_*` grids are static-wall runs, so their Cd cannot change; they are stale only because `lbm.physics_sha()` (AST of lbm.py and the other PHYSICS_FILES) changed with this edit, as it already was for the earlier rounds. Whoever restores the slow receipts must rerun them, expecting the same Cd to float round-off.
- `lbm.specular` is an exact halfway wall with its own term and is not touched; `isinstance(qdist, float)` still treats an int scalar as an array (the reviewer's adjacent note): not changed, no caller passes one.
- The added `bouzidi` keyword of `uniform_flow_force` defaults to False, so `nest.receipts()` and its row (|F|/(rho U^2 d^2) < 1e-4) are unchanged. A second receipt row for the curved case was not added (it would add a row to the receipts table and move the receipt counts); the lead may want one.

## M-12 glider apogee overshoot

DECISIONS row:
> NNN | The glider's apogee overshoot adds `apogee_overshoot x w_last x min(dt, pump time left)` per apogee step (`glider.py`, `left`), evaluated before the timer is decremented, so it sums to `apogee_overshoot x w_last x pump_time_s` (0.5 w pump_time with the shipped 0.5) for any `dt` and any `pump_time_s`. Before, it added `apogee_overshoot x w_last x dt` on each of the `ceil(pump_time_s/dt)` apogee steps, i.e. 0.5 w dt ceil(pump/dt): too big by `ceil(pump/dt) dt / pump` (1.0 for 120/60 and 120/120, 1.2 for 150/60 and 100/60, 2.5 for 120/300). With the shipped pump_time_s 120 (both yamls) and the pipeline's constant `DT_VEHICLE` 60 the factor is 1 and the numbers are bit-identical. Tests: `tests/test_glider.py::test_r11_m12_the_apogee_overshoot_is_half_the_descent_speed_times_the_pump_time_for_any_step` (pump 90 .. 150 s, dt 45 .. 300 s) and `..._a_zero_overshoot_leaves_the_depth_and_a_slocum_follows_the_same_rule`. | Review round 11, M-12 (C-2). `platforms/seaglider.yaml` `apogee_overshoot` wording now says "apogee_overshoot * w * pump_time (0.5 * w * pump_time here), the same for any time step".

Amends: 50 and 550 quote the 120/60 case and stay true (550's "about 7.4 m" peak overshoot at the shipped pump time is unchanged); say in 550 "for a lab pump_time_s that is not a multiple of 60 the overshoot used to be larger, row NNN". Row 51 (pump energy) is not touched.

CHANGELOG: `Fix: the glider's apogee overshoot is 0.5 w pump_time_s whatever the time step (it was counted per step: 20 to 150 percent too deep for a pump_time_s that is not a multiple of dt, or a dt above it). Shipped platforms at dt 60 s are bit-identical (review round 11, M-12).`

Doc sentence (RUNBOOK or the glider platform note, wherever pump_time_s is described): "The depth overshoot while the pump runs is `apogee_overshoot` x the last descent speed x `pump_time_s`, for any pump time and any time step."

What I checked could break, and how:
- Before and after for the shipped case. Glider tests: the whole of `tests/test_glider.py` passes (see "Test runs"). A/B of full histories on the old and new tree, 5 days, M = 3, drift, section and station missions, Seaglider and Slocum, dt 60 s: see the table in "Before and after" below.
- The fast receipts include 26 `pm.physics.glider` rows: none moved.
- Callers: `GliderSim.run(seconds, dt)` (default 60), `stage1.py` uses the constant `DT_VEHICLE` = 60 (stage1.py:40, 123); `step` is called from nowhere else. Only a non-default `dt` or `pump_time_s` changes.
- `pump_time_s` = 0 (allowed, "nonneg"): one apogee step with `timer` 0, so the overshoot is 0 (it was one dt before); correct by the formula.
- Float residue: a timer left at +1e-15 after the sum of dts adds an extra step of 1e-15 s of overshoot: no visible effect.
- Not a sibling: the pump energy and the hotel energy are charged once per event or per step by design (R4 in merged.md); the `out_s`, `d_prev` resets are in M-28.

## M-13 `fly_sitl` frame

DECISIONS row:
> NNN | `uas.fly_sitl` aims, commands and records in the launch-relative frame of `_Sim1.p` (zero at the launch) and of the firmware's home: `_ship_rel(ship, t_launch, ship0, t)` = the ship's displacement since the launch is added to the waypoint for the target, the command to the firmware and the arrival test (`_reached`), and subtracted from `p` for the recorded track. Before, the ship's absolute position `ship(t_launch + t)` was added to the target and subtracted from the track while `p` and the firmware command were relative to `ship0`, so a ship not at the origin at the launch (`steaming(pos0=(1000, 0))`, or `t_launch > 0` at speed > 0) never met an arrival test and returned a normal dict with `landed` False and a track shifted by `ship0`. No stage flies SITL (310), so no run changed. There is no SITL binary on orca: the maths is tested as two extracted functions, not through the firmware. Test: `tests/test_uas.py::test_r11_m13_sitl_targets_and_the_track_are_in_the_launch_relative_frame_whatever_the_ship_and_the_launch_time`. | Review round 11, M-13 (C-3).

Amends: 310 is unchanged ("no stage flies a SITL member"); add the cross-reference. The `fly_sitl` docstring promised only "wp (W,3) ship-relative", which is true; I did not edit it.

CHANGELOG: `Fix: fly_sitl worked only with the ship at the origin at the launch (target, arrival test and track mixed the ship's absolute and launch-relative positions); now one launch-relative position serves the three. Latent: no stage flies SITL (review round 11, M-13).`

What I checked could break, and how:
- At the origin with `t_launch` 0 `_ship_rel` is `ship(t)[:2] - ship(0)[:2]` = `ship(t)[:2]` when `ship(0)` is the origin, exactly the old value: every existing caller (`steaming()` at the origin, t_launch 0, the SITL receipts and tests/test_uas.py's fake-SITL tests) sees the same numbers. The firmware command `lonlat(SITL_HOME, tgt - ship0)` is now `lonlat(SITL_HOME, tgt_rel)`: the same value.
- `fly_sortie`, `simulate`, `launch_check` use `_ship_at` consistently (reading): not touched.
- Not verified: the three call sites inside `fly_sitl` (goto target, arrival test, track) were rewired and read, and `fly_sitl` still runs against the fake-SITL tests (they stop before `goto`), but no test flies it with a real firmware; the slow SITL receipts (`make receipts --slow`, needs the binary, 20 min) must be run once on a host that has it, ship at the origin, to see the same result as before.

## M-23 `_val(x, what, n)`

Test only, no production change. Not done: dropping the `n is None` branch. The reviewer called it redundant; it is not: `a[:None]` on a 0-d array (the scalar density, SST, 2 m temperature and pressure reads at pipeline_windows.py:212, 213, 328) raises `IndexError: too many indices`. A mutant without the branch is killed by the new test, and the test says why.

DECISIONS row: none needed; a note appended to 549: "pinned by `tests/test_stage3.py::test_r11_m23_val_checks_the_first_n_components_only_and_the_whole_array_without_n` and `..._a_nan_in_a_vertical_component_does_not_refuse_a_uas_or_a_usv_case` (round 11, M-23); the `n is None` branch is needed for scalars."

CHANGELOG: `Test: _val's first-n-components rule (DECISIONS 549) is pinned, a NaN in an unread vertical component and in a read one (review round 11, M-23).`

Checked: test only; the end-to-end test uses a small `NanUp(AnalyticEnv)` whose wind and current have a third NaN component. It builds a UAS and a USV case, nothing else.

## M-26 UAS thresholds (partly refuted)

Tests only. Four of the five items are real and now pinned; the lever-arm item (uas.py:144) is refuted as the merge said: the mutant `arm = motor_radius_m` is killed by `tests/test_uas_exact.py::test_rate_gains_follow_the_mixer_authority_of_each_axis` (I ran it), so no test was added for it.

DECISIONS row: none contradicted. A one-line optional row: "the UAS battery, no-headway, launch-gate and link-hold thresholds each have a near-threshold test (round 11, M-26)". Tests (all in `tests/test_uas.py`):
- `test_r11_m26_the_battery_flag_fires_when_the_charge_crosses_the_reserve_not_half_of_it_and_the_return_starts_then_too` (also pins the failsafe RTL trigger at uas.py:314, which the finding listed as an unpinned neighbour);
- `test_r11_m26_the_no_headway_flag_waits_one_stuck_window_not_two_and_not_half_of_one` (a 14 m/s headwind pulse of 1.8 and 0.9 windows; `t_first` of this flag is the start of the run, so the window cannot be read from it);
- `test_r11_m26_the_launch_gate_averages_the_wind_at_the_start_the_middle_and_the_end_of_the_sortie` (three cases, one per sample time, and a gale between samples that must pass);
- `test_r11_m26_a_link_lost_for_exactly_the_hold_latches_and_one_sample_less_does_not`.
The assumed numbers are read from `P`, as the glider test does (reserve, stuck window, gate limit, hold). The pulse test also leans on the 2.9 s lag from the onset to the start of the no-headway run, measured on orca (63 s `t_first` for a pulse from 60 s).

CHANGELOG: `Test: the UAS battery reserve, no-headway window, launch-gate sample times and link hold are each pinned at their threshold (review round 11, M-26).`

Not done (listed by the finding as unpinned neighbours, not mutated, no test): `stuck_closing_ms` and `stuck_min_cmd_ms` (uas.py:366), the battery margin at stage1.py:398.

## M-27 stage-3 adapter

Tests only, plus one extraction with no behaviour change: the wall pressure formula of `windows.run_window` is now `windows.wall_pressure_pa(rho_lat, rho_f, dx, dt)` (the same expression, same operation order; the calling line is `pwall = wall_pressure_pa(np.mean(acc, 0), rho_f, dx, ns.dt)`).

DECISIONS row: none contradicted (81 and PHYSICS 960 are now held by tests). Tests (`tests/test_stage3.py`):
- the hangar test now also checks the flow relative to the body: angle `arctan2(-rel[2], rel[0])` = alpha and `rel[0]` = U cos(alpha) for the Seaglider, and the angle plus `rel[1]` ~ 0 for the Slocum (kills the negated vertical term);
- `test_r11_m27_fit_window_coarsens_by_the_fourth_root_...` (two budgets, rel 1e-6, with the preconditions that dx is coarsened and not capped by the body);
- `test_r11_m27_the_wall_pressure_is_cs2_times_the_density_excess_in_physical_units` (exact values);
- `test_r11_m27_the_wall_function_switches_to_the_viscous_law_below_y_plus_11_06` (y+ 9.5, 12.5, 40; written with the literal 0.41 and 5.2, so a changed KAPPA or B_LOG shows as well).

CHANGELOG: `Test: the stage-3 window sizing (fourth root), glider case flow direction, wall pressure and the viscous switch of the wall function are pinned; the wall pressure formula is the function windows.wall_pressure_pa (review round 11, M-27).`

Checked: the one production change is a pure extraction; the fast receipts (7 `pm.stage3.wallmodel`, 8 `lbm`, 8 `nest` rows) did not move; `tests/test_stage3.py` ran whole. Not done: the finding's sibling remarks (KAPPA, B_LOG, Y_MATCH, NU_MAX pinned only through the slow plate and channel gates; `uas_case`'s final assertion `(R @ (v-u_env))[0] != 0` is still weak).

## M-28 kernel and glider details

Tests only. Mutants of each of the four are killed by the test named. The overshoot value is held by the M-12 tests.

DECISIONS row: none contradicted. CHANGELOG: `Test: the nest sponge ramp is quadratic, the glider's apogee overshoot value, the stuck-clock reset by a good dive and the surfacing pump work are pinned (review round 11, M-28).`
- `tests/test_nest.py::test_r11_m28_the_sponge_ramp_is_quadratic_in_the_layer_index`;
- `tests/test_glider.py::test_r11_m28_a_good_dive_resets_the_stuck_clock_so_alternating_dives_never_flag_an_unreachable_waypoint` (calls `_begin_dive` on a stepped sim with set state: three consecutive calls; a mutant that keeps the old stuck time flags `waypoint_unreachable` falsely);
- `tests/test_glider.py::test_r11_m28_the_surfacing_charges_the_comms_and_the_pump_that_empties_the_bladder_at_the_surface` (the energy step across the first surfacing = hotel + comms + pump work, rel 1e-9).
Siblings not searched (as the finding says): other `np.where(cond, x + inc, 0.0)` resets in glider.py (`out_s` near :487), other E increments, other `P[...]` values validated only by bound tests.

## Before and after of a printed number

- Fast receipts, 350 rows: none moved (value and verdict, id by id). The 30 FAIL rows are the same 30.
- Glider histories at the shipped platform values and dt 60 s: identical on the old (3ce8e09) and the new tree, bit for bit. Six runs of 5 days, M = 3, dt 60 s (drift, section and station missions x Seaglider and Slocum): the hash of every history array is the same in all six, e.g. drift Seaglider max depth 502.6789651340148 m and total energy 1142540.5956821798 J before and after; drift Slocum 506.2439291187825 m and 2630049.537020242 J before and after. (Probe: `tests/test_glider.py`'s `sim` and `env` helpers; logs `r11b_ab_before` and `r11b_ab_after` on orca, removed.) At a pump_time_s that is not a multiple of dt the numbers do move, by the factor in the M-12 row: nothing in the shipped files or the missions sets one.
- Stage-3 / lbm: the demo's stage-3 numbers do not use a curved wall (no `qdist`), so none moves; the one number that changes is the new curved-wall uniform-flow force above (7.78 to 4.1e-6 max).
- Demo, q11 (stage 1 uses the glider at dt 60, pump 120): no printed number moves, by the identity above and the A/B; I did not rerun a demo.

## Needs from other batches

- Batch E (DECISIONS, CHANGELOG, PHYSICS 14.1, the 549/550/310/76 cross-references above): the rows and sentences in this file, numbered after 592.
- Batch E may want, and I did not add: a receipt row for the curved-wall uniform flow (`nest.uniform_flow_force(bouzidi=True)`), because it would change the receipt table's row count and the STATUS number of receipts.
- Batch A: none. No file of batch A was touched (the batch-B file list was kept: stage3/lbm.py, nest.py, windows.py, pipeline_windows.py untouched except as listed; physics/glider.py, physics/uas.py, platforms/seaglider.yaml; tests/test_lbm.py, test_nest.py, test_glider.py, test_uas.py, test_stage3.py). `cafe/pm/stage3/windows.py` gained the function `wall_pressure_pa`; `nest.py` the keyword `bouzidi`.
- Whoever runs the slow receipts next: `make receipts --slow` for the stage-3 groups and the UAS SITL group on a host with the binary (see M-11 and M-13).
- Nothing from batches A, C or D is needed to build or test these changes.

## Test runs (orca)

- The whole files `tests/test_lbm.py tests/test_nest.py tests/test_glider.py tests/test_uas.py tests/test_uas_exact.py tests/test_stage3.py` on commit 8f2f9d2 (`PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=2`, one pytest call): exit code 0, 494 passed on the progress lines, no F, E, s or x (counted as CLAUDE.md says). About 50 min.
- `ruff check cafe/pm tests`: clean. `mypy cafe/pm` (strict): no issues in 55 files. `audit.banned()`: 0 hits.
- Not run: the full suite, coverage, mutation testing (`make mutation`, hours), the slow receipts, `python -m cafe.pm audit`. The new production lines (`_ship_rel`, `_reached`, `left` in glider.step, `wall` in bounce_back, `wall_pressure_pa`) are each executed by a new test, so the 100 percent gate on physics should hold; it was not measured.
- The new tests' times: the M-26 flights are 300 s sorties (seconds each); the M-12 test steps a glider to 300 m six times; nothing new is slow.

## Mutants (each run alone in a detached worktree at the commit, file restored after)

- killed: M-11 drop the 1/(2q) wall factor (the old code)
- killed: M-11 factor 1/q instead of 1/(2q)
- killed: M-11 factor applied for q < 1/2 too
- killed: M-12 per-step overshoot (the old code)
- killed: M-12 / M-28 overshoot halved
- killed: M-12 timer read after the decrement (time left minus dt)
- killed: M-13 _ship_rel in the ship's absolute frame (the old frame)
- killed: M-13 _ship_rel at launch time 0 instead of t_launch + t
- killed: M-13 _reached ignores the height
- killed: M-23 whole array checked whatever n
- killed: M-23 the n is None branch dropped (a[:n] only)
- killed: M-26 battery flag at half the reserve
- killed: M-26 failsafe return at half the reserve (uas.py:314)
- killed: M-26 no-headway window doubled
- killed: M-26 no-headway window halved
- killed: M-26 launch gate sample times [0, 0.5, 0.5]
- killed: M-26 launch gate sample times [0, 0, 1]
- killed: M-26 launch gate sample times [0.5, 0.5, 1]
- killed: M-26 link hold strict
- killed: M-27 fit_window square root
- killed: M-27 wall pressure without /3
- killed: M-27 YPLUS_LAM 14
- killed: M-27 YPLUS_LAM 8
- killed: M-27 glider case vertical flow negated
- killed: M-28 sponge ramp linear
- killed: M-28 stuck reset keeps the old value
- killed: M-28 surfacing pump work dropped
- killed: M-26 lever arm without /sqrt(2) (uas.py:144, the refuted item): by `tests/test_uas_exact.py::test_rate_gains_follow_the_mixer_authority_of_each_axis`, a test that already existed
