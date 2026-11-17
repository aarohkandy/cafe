# Round 18, batch C handback: M-4 and the A-2 tests of M-16

Branch `r18-c` (cut from d69be8f), worktree `cafe-r18c`.
Commits (each ends with the `Co-Authored-By: Claude Fable 5.2` line): 64f9de7 (stage1.py, the three test files), a lint commit (line length, one unused loop variable), a draft of this hand-back, and the final hand-back commit.
Files touched, all in the batch's list: `cafe/pm/stage1.py`, `tests/test_stage1.py`, `tests/test_round17_c.py`, `tests/test_round18_c.py` (new). `physics/usv.py`, `physics/uas.py`, `credibility.py`, `report.py` are untouched.
Numbering of the DECISIONS rows: C1 and C2 here; batch G numbers them after 951.

## M-4 (OD-4 default): what changed

`cafe/pm/stage1.py`:
- `RANKED[(class, dominant mode)]` names the result key of the quantity that failed: `station_lost` and `swept_off_track` keep `margin` (distance from the station / cross-track error); a USV's `battery` is `energy_margin` (lowest state of charge); a glider's `battery` is `battery_margin` (new, see below); a UAS's `battery_reserve` is `margin`, `profile_incomplete` is `profile_margin`. Any other mode (becalmed, the wing stalls, capsize, a lost link, `left_data`, `no_current_data`, ...) ranks the 0/1 failure indicator, which is moved by whatever moves any quantity of the class (`SENS_ACTS[class]`, now the union of the rows of `ACTING`). With no failure the entry keeps the `margin` label as before (an all-pass entry's `quantity` is unchanged).
- `ACTING[(class, key)]` is the one table of the columns that move each quantity (below, how it is held). `_ranked(r, dom)` picks (acting set, quantity, name) for `summarize`; a result that lacks the quantity (an older `res.pkl`) or holds fewer than 16 finite values of it falls to the indicator and the class's columns (so a station glider's distance is never ranked under a battery failure).
- `_run_glider` stores `battery_margin` (+ `battery_margin_name`) for every task; a station glider's `margin` stays its distance, a drift glider's `margin` is the same array as before. The key is `battery_margin`, not `energy_margin`, on purpose: `summarize` builds a USV "energy" block (and the report reads it) from `energy_margin`, which a glider must not get. `_run_usv` adds `energy_margin_name`; `merge` copies the new key and both names; `QUANTITY` holds the two names for results made before they were stored.
- `link_acts(lk, classes)` replaces `ACTS`-union for links: an RF or acoustic link feels the columns that move the track of its end vehicles (`TRACK_ACTS`: glider wind and current and its speed prior; USV the six forcing columns and its speed prior; UAS the wind and the stress scale), not their battery or insolation, plus `LINK_ACTS` (RF: `hs_scale`); an Iridium link feels only the columns that move which moments are required (`PATTERN_ACTS`: a glider's speed prior for `when: surfacing`, the UAS's wind speed), and one `when: always` none. `_sensitivity` with an empty acting set returns the new case `no_acting_input` (no index, `S1 {}`, `noise_floor None`, so it is not counted among the permutation tests and `credibility` does not count it; the report prints its `text`).
- Data keys the report reads are unchanged (`param`, `S1`, `noise_floor`, `case`, `quantity`, `text`); the only new value is `case == "no_acting_input"`. `ACTS` is untouched, so `credibility.CLASS_PRIORS` and the "used by" counts do not move (a test pins the dict).

How `ACTING` is held (`test_r18_m4_the_acting_table_is_the_set_of_columns_that_move_each_quantity[glider_eq|glider_1n|usv|uas]`): for each vehicle alone, `run_batch` on the CI environment (`ci_full`, the gridded one), two members, every one of the 11 sampled columns alone at its 5 % (member 0) and 95 % (member 1) quantile against all-median draws; the quantities that changed are compared with the row of `ACTING` less `UNSEEN`. Table as found:

| (class, quantity) | columns that moved it |
|---|---|
| glider, `margin` (station distance) | wind_speed_bias, wind_direction_bias, current_speed_scale, current_direction_bias, glider_speed_scale |
| glider, `battery_margin` (station and drift) | glider_speed_scale, battery_capacity_scale |
| usv, `margin` (cross-track error) | the six forcing columns, usv_vpp_bias |
| usv, `energy_margin` | the same seven and solar_yield_scale |
| uas, `margin` (battery reserve) | wind_speed_bias, wind_direction_bias, bulk_stress_scale, battery_capacity_scale (+ UNSEEN hs_scale) |
| uas, `profile_margin` | wind_speed_bias (+ UNSEEN bulk_stress_scale, battery_capacity_scale, hs_scale) |

`test_r18_m4_every_column_that_moves_a_link_is_one_the_link_table_lists` does the same on the analytic environment for the three CI links and three more (Iridium on a surfacing glider, RF glider to ship, acoustic USV to ship): every column that moves a link's fraction, required moments or summed margin is in `link_acts`, and the Iridium link `when: always` is moved by none.

### Decisions the lead should look at (I took the more conservative reading in both)

1. **The steering and wave columns are NOT removed from the USV's charge.** OD-4 expected `energy_margin` to be moved by `solar_yield_scale` and not by the steering and wave columns. In the analytic environment that is true (my probe with `swdown` at break-even: only `solar_yield_scale` moves `energy_margin`; reviewer B's too). In the gridded CI environment the insolation varies in space and time, a column that moves the track moves what is harvested, and every one of the seven moves `energy_margin` (log `r18c_probe3`: wind, current, Hs, Tp and the speed prior all moved `usv.energy_margin`). The real runs are gridded, so the table follows the gridded probe: excluding them would make a real driver unnameable. Consequence: the USV's battery ranking is over eight columns, not one; `solar_yield_scale` still heads it when it dominates (the regression test). The one-column alternative needs the analytic environment as the probe and is a one-line change of the row plus the probe's environment.
2. **`UNSEEN` (columns kept that no probe of mine moved).** `hs_scale` on the UAS: with the shipped RFD900x the link has 35 dB or more of margin at any range a 20 min sortie reaches (computed, log `r18c_hs`: lost only beyond the 30.9 km horizon at 5 m, never at 30 or 100 m), so Hs never ends a sortie in the probe; with a radio 35 dB weaker the lost-link hook does flip with Hs (a test shows both). The lead may drop `hs_scale` from the UAS rows (it is practically inert for the shipped radio). `bulk_stress_scale` and `battery_capacity_scale` on the UAS `profile_margin`: the profile share is a count of waypoints and did not change at two quantiles, but a sortie that is stopped by turbulence or by its reserve delivers less of the pattern; a quantity of that kind cannot show inertness at two quantiles, so they stay (this keeps round 17's behaviour for the profile ranking and its existing test). `wind_direction_bias` is not on the profile row (the upwind pattern rotates with the wind: invariant, and the probe agrees).
3. Reviewer B's drift-glider set is three columns incl. `current_direction_bias`; mine is two (`glider_speed_scale`, `battery_capacity_scale`) in both the gridded and the analytic environment. Not reproduced with current_direction_bias; B's environment is not in the repository. Caveat of the table (comment in `stage1.py`): over a sea floor above the dive depth the track would move a glider's pumping energy; no probe of ours reaches that.

## Regression tests (`tests/test_round18_c.py`; names)

M-4:
- `test_r18_m4_a_usv_that_runs_out_of_charge_ranks_its_charge_and_the_solar_yield_not_the_cross_track_error`
- `test_r18_m4_a_mode_with_no_quantity_of_its_own_ranks_the_failure_indicator_over_every_column_of_the_class` (also pins `RANKED`)
- `test_r18_m4_a_glider_that_runs_out_of_battery_ranks_its_energy_over_the_two_columns_that_move_it`
- `test_r18_m4_a_result_that_does_not_hold_the_quantity_ranks_the_failure_indicator` (an older `res.pkl`)
- `test_r18_m4_without_a_failure_the_entry_keeps_the_margin_label_and_a_station_glider_keeps_its_battery_beside_the_distance` (real `_run_glider` and `merge`)
- `test_r18_m4_an_iridium_link_that_no_column_acts_on_is_not_ranked_and_is_not_counted_as_a_test`
- `test_r18_m4_a_link_feels_the_track_of_its_ends_and_its_own_columns_only` (includes two gliders on an RF link)
- `test_r18_m4_the_used_by_counts_of_the_credibility_page_still_read_acts_not_the_sensitivity_table`
- `test_r18_m4_hs_can_end_a_uas_sortie_through_its_link_which_is_why_it_is_listed_beside_what_the_probe_moved`
- `test_r18_m4_the_acting_table_is_the_set_of_columns_that_move_each_quantity[glider_eq|glider_1n|usv|uas]`
- `test_r18_m4_every_column_that_moves_a_link_is_one_the_link_table_lists`

M-16, A-2 (code is right; tests only):
- `test_r18_a2_a_launch_whose_hard_stop_does_not_fit_before_the_end_of_the_window_is_dropped` (stage1.py `_uas_setup` -> `launch_times`, also through `_run_uas`)
- `test_r18_a2_the_wave_height_at_the_ship_is_read_over_the_whole_flight_to_the_hard_stop_and_its_margin` (`_uas_links` grid; a recording environment)
- `test_r18_a2_the_fine_grid_of_a_flown_sortie_runs_to_the_hard_stop` (`_run_uas`, the :412 site)
- `test_r18_a2_a_flight_that_is_not_home_at_the_nominal_duration_flies_on_to_the_hard_stop` (`fly_sortie` -> `simulate`, a platform with `duration_s` 100 s)

Existing pins moved (each for the reason M-4 gives):
- `tests/test_round17_c.py`: `USV` set gains `solar_yield_scale` (the indicator of a USV is moved by its solar yield: the battery flag); the link rows are the track columns (RF: forcing, vpp, bulk stress; acoustic: the glider's five; Iridium `when: always`: none, `S1 == {}`); the RF glider-ship row is five glider columns plus `hs_scale`; the "UAS cannot feel current_direction_bias" test names its failing mode `battery_reserve` (a margin is ranked only when its mode failed); the solar-yield test now says `solar_yield_scale` is not in the USV's `margin` row and is in its `energy_margin` row.
- `tests/test_stage1.py::test_the_summary_ranks_the_margin_the_simulator_stored_and_only_the_columns_of_the_class`: the synthetic vehicles fail by `station_lost` and `swept_off_track` (their margin is ranked only for that mode), and the RF link no longer has `battery_capacity_scale`.

## Fail-before and mutants

Unfixed tree: throwaway detached worktree `../cafe-r18c-base` at d69be8f with only `tests/test_round18_c.py` copied in, orca dir `pm_r18c_base`, log `r18c_base1` (`-n 2`): rc 1, 18 tests, **13 failed, 5 passed**. The five that pass on the old code are the four A-2 tests (the code is right: they are held by mutants below) and the guard of `CLASS_PRIORS`. Of the 13 failures, 6 are behavioural on the old code: the USV ranks `usv_vpp_bias` where `solar_yield_scale` is asked; a glider's battery failure ranks the wind (`wind_speed_bias`) not `battery_capacity_scale`; a mode with no quantity prints "maximum cross-track error", not "failure indicator"; an older result ranks "maximum distance from the station" under a battery failure; `KeyError: 'battery_margin_name'`; the Iridium link is `ranked`, not `no_acting_input`. The other 7 (the four probe rows, the link probe, the `link_acts` test, the `hs` test) fail on the absence of `stage1.ACTING` / `stage1.link_acts`: they hold the new tables and cannot fail otherwise.

A-2 mutants (each a one-line `sed` on a copy in `pm_r18c_mut`, the file put back; control first; logs `r18c_mut1`, `r18c_mut2`): control rc 0; `_uas_links` grid with `so["duration_s"] + 61.0` rc 1 (killed by the wave-height test only); `launch_times(..., so["duration_s"])` rc 1 (the launch test only); the `_run_uas` fine grid with `so["duration_s"] + 1.0` rc 1 (the fine-grid test only); `simulate(t_max=so["duration_s"])` in `physics/uas.py` rc 1 (the flight test only).

## Runs (orca, proot; real rc and counts)

| log | what | rc | result |
|---|---|---|---|
| `r18c_pre2` | `test_stage1`, `test_round17_c` after the first code edit | 1 | 6 expected pin failures (listed above), then edited |
| `r18c_2` | `test_round18_c` (without the two probe tests) + `test_round17_c` | 1 -> fixed | 22 passed, 1 failed (the `hs` test: the shipped radio never flips; test rewritten with a weaker radio) |
| `r18c_4` | the four vehicle probes | 0 | 4 passed |
| `r18c_5` | the link probe and the `hs` test | 0 | 2 passed |
| `r18c_lint1` | `ruff check cafe/pm tests`, `mypy cafe/pm` | ruff 1 (10 E501 and one B007, all in my files), mypy 0 | fixed in the lint commit; `r18c_lint2` below |
| `r18c_wide1` | `-n 3` of `test_stage1`, `test_stats_exact`, `test_stats`, `test_pipeline`, `test_report`, `test_credibility`, `test_cli`, `test_reproducible`, `test_round15_a`, `test_round16_a`, `test_round16_report`, `test_round17_a`, `test_round17_b`, `test_round17_c`, `test_round17_m`, `test_round18_c`, `test_whatif`, `test_usv`, `test_perturb_env` (commit 64f9de7: every file that imports or pins `stage1`, the sensitivity, the summary, `merge` or the USV/glider result keys) | 0 | 1,968 passed by the progress-line count (no F, s, x or E) |
| `r18c_fin1` | `-n 3` of `test_round18_c`, `test_round17_c`, `test_stage1` on the final tree (the three files the lint commit touched; the wide run was on 64f9de7) | 0 | 202 passed by the progress-line count |
| `r18c_codeonly` | `python -m cafe.pm audit --code-only` | 1 | no banned token and no commented-out code found; the one problem is "mutation: no stored result at docs/mutation.json": that file is server-written, untracked and protected in `bin/sync_filters`, so no `pm_*` copy on orca has it (not mine; the same for any builder's tree) |
| `r18c_demo2` | quick demo on this tree (PM_CPUS=6, PM_MEM=16g; the first start `r18c_demo` was stopped after a minute by its own tmux session name because the tree had an untracked scratch dir, and rerun clean) | 0 | below |
| `r18c_lint2` | `ruff check cafe/pm tests`, `mypy cafe/pm` on the final tree | ruff_rc=0, mypy_rc=0 | "All checks passed!", "no issues found in 55 source files" |

## The demo against q18 (`review/round_14/q14summary.py r18c_demo q18`, plus the sensitivity entries of `stage1/summary.json`, `stage1b/summary.json`, `report/report.json`)

Verdicts, k_fail, n, p_fail and intervals of every vehicle and link, stage 1 and stage 1b: identical to q18 (glider_eq MARGINAL 15/64, uas NO-GO 62/64, usv NO-GO 61/64, glider_2n GO 0/64; links usv-uas-rf, glider_eq-ship-acoustic, glider_2n-ship-acoustic NO-GO 64/64, usv-shore-iridium GO 0/64), priors, env_sigmas, mooring count 15, plan figures: identical. The dominant mode, the ranked quantity and the case of every entry are the same.

What moved (sensitivity only):

| entry | q18 | r18c_demo |
|---|---|---|
| glider_eq (station_lost, distance) | floor 0.1766, 6 columns, largest S1 0.106 wind_direction_bias, `nothing_above_floor` | floor 0.1720, 5 columns (battery_capacity_scale out), same largest S1 and leader, same case |
| uas (profile_incomplete) | floor 0.1903, 5 columns, largest S1 0.121 wind_speed_bias, `nothing_above_floor` | floor 0.1818, 4 columns (wind_direction_bias out), same leader, same case |
| usv (swept_off_track, cross-track error) | floor 0.1985, 7 columns, tp_bias S1 0.299, `ranked` | unchanged |
| glider_2n, usv-uas-rf, the two acoustic links, usv-shore-iridium | all_pass / all_fail | unchanged |

Printed sentences: glider_eq "... floor 0.177" -> "floor 0.172"; uas "... floor 0.190" -> "floor 0.182"; the others identical. The merged text's expected "glider_2n floor 0.194 to 0.172" and "the Iridium link's ranking disappears" do not occur in q18: glider_2n is all-pass and the Iridium link is all-pass there (those numbers were the reviewer's random-outcome probe).

Other things that differ in `q14summary` and are not from this change: `git_sha`; stage1 wall 184 s against 157 s and the other timings (orca load average was 15 to 18 during the run); `variants_run` 5 against 6 and `design.rows_added` 24 against 28: `emulator/design.json` of r18c_demo records `killed: the variant runs spent the emulator stage's whole wall-clock share (240 s) before variant v5 of 6`; variants v0 to v4 are identical to q18's (same mods). A wall-clock cut on a loaded machine, not a draw or a code change. The run appended its rows to the shared emulator table (the pipeline does that for any run); `/data/runs/q18` was only read.

## Proposed DECISIONS rows

**C1** (amends 211 and 923; for batch G to number): "The first-order sensitivity of a vehicle ranks the quantity of its dominant failure mode, over the columns that move that quantity (`stage1.RANKED`, `stage1.ACTING`). `swept_off_track` and `station_lost` rank the cross-track error or the distance from the station (a USV: the six forcing columns and the speed prior; a station glider: wind, current and its speed prior, not its battery); `battery` ranks a USV's lowest state of charge (the same seven columns, because the insolation it harvests varies in the environment, and `solar_yield_scale`) and a glider's battery energy margin (its speed prior and its battery prior only; stored for every task as `battery_margin`, a station glider's `margin` stays its distance); `battery_reserve` and `profile_incomplete` the UAS's battery reserve margin and profile share; any other mode (becalmed, the wing stalls, a lost link, ...) ranks the 0/1 failure indicator over every column of the class (`SENS_ACTS`, now with the USV's `solar_yield_scale`). A result without the quantity (a `res.pkl` from before) ranks the indicator. The table is held by `tests/test_round18_c.py`, which perturbs every sampled column alone over its 5 to 95 % quantiles through the real simulators on the CI environment and asserts the table is the set that moved, less `UNSEEN` (columns that can act but that no probe moves: the UAS's `hs_scale`, and the stress and battery scales on its profile share). A link feels the track of its end vehicles (`link_acts`) and its own columns (RF: Hs); an Iridium link `when: always` has none and is not ranked (case `no_acting_input`: no noise floor, not counted among the report's permutation tests). `ACTS`, and with it the credibility page's 'used by' counts, is unchanged. In the demo no verdict, count or interval moves; glider_eq's floor goes 0.177 to 0.172 and the UAS's 0.190 to 0.182 (round 18, M-4, OD-4: a USV that runs out of charge no longer names `usv_vpp_bias` for its cross-track error, S1 0.997 in reviewer B's probe)."

**C2**: "Round 18, M-16 (A-2): four tests hold round 16's sortie length (`uas.sortie_t_max`, DECISIONS 899) at the sites no test held: the launch schedule, the wave-height grid of the UAS link, the 30 s grid, and `fly_sortie`'s hard stop; each was shown failing on its mutant."

CHANGELOG lines: "stage1: the sensitivity ranks the quantity of the dominant failure mode over the columns that move it (ACTING, RANKED), a glider keeps `battery_margin`, an Iridium link nothing acts on is not ranked (round 18, M-4)." and "tests: round 18 batch C (M-4, M-16 A-2)."

## Document text for batch G

- `docs/CREDIBILITY.md:199`: replace "over the columns the class's simulator reads (the glider no wave column, the UAS no current and no Tp, the USV not the solar yield; an RF link also Hs; review round 17, M-8; ...)" by "of the dominant failure mode (a USV that runs out of charge ranks its lowest state of charge, a glider its battery energy margin, a mode with no quantity of its own the 0/1 failure indicator), over the columns that move that quantity, found by moving each column alone through the simulators (review round 18, M-4; round 17, M-8); a link over the columns that move its ends' tracks and, for RF, Hs; an Iridium link that is decided by its own draw is not ranked; the demo's noise floors went to 0.172 (glider_eq) and 0.182 (the UAS), and no leader changed", and "five cases" -> "six cases (... and no input acts)".
- `docs/PHYSICS.md:910`: the same replacement for "Only the columns that the class's simulator reads are ranked ... (`stage1.SENS_ACTS`, `LINK_ACTS`)", the list of the one outcome per class (a USV's lowest state of charge and a glider's battery margin when the battery is what failed), "five cases" -> six; the sentence "a UAS ranks its battery reserve margin unless `profile_incomplete` is its dominant failure mode" generalises to the table.
- DECISIONS 211 and 923: "(amended by 277, 923, C1)"; 923's text on the acting set is superseded by C1.
- `q18_vs_q17`-style note: the table "What moved" above (two floors), nothing else.
- RUNBOOK: nothing found that names the acting columns.

## Edits needed in a file of another batch

- `cafe/pm/report.py` (batch A), optional: `_top3_html` (about line 1376) prints "Top sensitivities: none above the noise floor (or all-pass, all-fail, or fewer than 16 members)" when no column is listed; for a `no_acting_input` entry the `Most sensitive to:` line already carries the right sentence (the report prints `text`), and this line could add ", or no input acts on it". No data key moved, so nothing breaks without it. I could not render a page with a failing Iridium link (the demo has none).

## Not verified

- The full suite, the gate, coverage numbers (the lead's). No gated package (`physics`, `stats`, `env`) changed; every new line of `stage1.py` is exercised by the tests above (not measured separately).
- The probe uses two members at the 5 and 95 % quantiles with all other columns at their medians: a column that acts only in the tails, only by an interaction, or only in a flight at its limit shows as inert (the reason for `UNSEEN`, and a one-directional risk: excluded real drivers cannot be named). A different quantile pair or more members were not tried.
- The link probe runs on the analytic environment (the gridded one takes about 45 s a run for the whole mission); the vehicle probes on the gridded CI environment. A mission with a failing Iridium link or a real USV battery failure was not run end to end; the USV battery case is a synthetic summary plus the real `_run_usv` probe.
- Time of the probe tests: about 2 s a run for a glider, 3 s for the USV, 7 s for the UAS (20 s to start) in the probe logs: roughly 4 minutes in all, serially; I did not time the file.
- `report.py` rendering of the new case (see above); `whatif` and `pipeline` read the new keys only through `merge` (the wide run covers their tests).
- Reviewer B's own probes (`usvbat.py`, `sens.py`) were not re-run; their cases are rebuilt here as the tests above.

## Found outside my batch

- The UAS's `hs_scale` cannot flip the lost-link flag with the shipped radio (35 dB margin at 5 km, never lost within the horizon at 30 m or more): in practice an inert column for the UAS today (see decision 2); round 17 and the merge listed it as acting by reading the code.
- `bin/pmx.sh` records `CAFE_GIT_DIRTY` from `git status --porcelain`, which counts untracked files: a scratch directory in the worktree makes the demo's ledger say dirty. I stopped my first demo for that and reran it clean (the tmux session `r18c_demo`, exact name).

## Left on orca

Directories `pm_r18c`, `pm_r18c2`, `pm_r18c_base`, `pm_r18c_mut`, `pm_r18c_demo`, `pm_r18c_cmp` (code trees; `pm_r18c_base` has the unfixed code and my test file, `pm_r18c_mut` a `mut.out`), run `/data/runs/r18c_demo` (kept: the demo above; `r18c_demo` was started and stopped once before it and `--fresh` replaced it), logs `~/cafe-worker/logs/r18c_*`, job markers `.pmx.job.pm_r18c*`. Nothing in `/tmp` on orca, nothing outside `~/cafe-worker`, no kill by name (one tmux session killed by its exact name, `r18c_demo`). On the laptop: the throwaway worktree `../cafe-r18c-base` (detached at d69be8f, with my test file untracked in it; to remove with `git worktree remove --force ../cafe-r18c-base` from the lead's checkout) and scratch scripts in the session scratchpad `x_c18/` (probe, mutant driver, comparison).
