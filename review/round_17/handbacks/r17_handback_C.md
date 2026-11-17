# Round 17, batch C handback: M-8 and the tests of M-19 (A-3, A-5, A-6)

Branch `r17-c` (cut from 433429e), worktree `cafe-r17c`. Orca directories: `pm_r17c` (kept), `pm_r17c_demo` (kept, the demo's code tree), `pm_r17c_base` (fail-before and mutant runs; removed by exact name), run `/data/runs/r17c_demo` (kept), logs `~/cafe-worker/logs/r17c_*` (kept). Throwaway detached worktree `cafe-r17c-base` at 433429e (removed).
Code commit: ea87ea7 (`cafe/pm/stage1.py`, `tests/test_stage1.py`, `tests/test_round17_c.py`). Files outside my list: none (`tests/test_stage1.py` and `stage1.py` are in it).
Numbering of the DECISIONS rows: C1 here; batch G numbers it after 916.

## M-8 (and the acting-column part of A-6)

Change: `stage1.SENS_ACTS` (per class, the columns the class's simulator reads: glider = wind speed and direction, current speed and direction, glider_speed_scale, battery_capacity_scale; usv = all six forcing columns and usv_vpp_bias, NOT solar_yield_scale; uas = wind speed and direction, hs_scale, bulk_stress_scale, battery_capacity_scale) and `stage1.LINK_ACTS` (an RF link reads Hs at both ends: hs_scale). `summarize` passes `set(SENS_ACTS[class])` for a vehicle and the union of the ends' sets plus `LINK_ACTS[kind]` for a link, instead of `FORCING | ACTS[class]`. `ACTS` itself is unchanged: it is the list of priors a class reads, and `credibility.CLASS_PRIORS` and `tests/test_credibility.py:1547` are built from it (solar_yield_scale stays a used USV prior).
Deviation from the merged text, with the reason: the UAS keeps `hs_scale` (merged.md's four columns leave it out). `_uas_links` reads Hs at the ship (`env.waves(...)["Hs"]`) and the sortie ends on a lost link, so a wave-height error can act on the UAS's failures and margin. `tp_bias` is not read (`comms.rf_margin` takes Hs only), nor is any current. The test below derives the table from what the simulators really read, so this is checked, not argued. UAS floor is therefore 0.190, not the reviewer's 0.184 (4 columns).
Not changed: the failure-indicator fallback of `_sensitivity` (a margin that is not finite): for the USV and glider the margin is always finite, so solar_yield_scale could only act there for a UAS/USV-less case that does not exist; the UAS fallback keeps its own set.

DECISIONS row C1: "The first-order sensitivity of a vehicle or a link ranks only the columns the class's simulator reads (`stage1.SENS_ACTS`, read from `_run_glider`, `_run_usv`, `_run_uas`): glider the wind and the current and its own two priors, no wave column; USV all six forcing columns and the speed prior, not solar_yield_scale (it moves the state of charge and the battery flag, not the cross-track error the USV's margin is); UAS the wind, Hs (through the sortie's link at the ship), the stress scale and the battery scale, no current and no Tp; a link the union of its ends' columns, and hs_scale for an RF link. The noise floor is the permutation maximum over those columns, so an inert column no longer raises it or heads the list (round 17, M-8, OD-5: the per-class acting table taken now). Extends 211 and 892. In q17 the UAS's printed leader was current_direction_bias (S1 0.177, floor 0.214), a column its flight never reads; it is now wind_speed_bias (0.121, floor 0.190), still below the floor: nothing_above_floor in both."
CHANGELOG line: "stage1: the sensitivity ranks only the columns each class's simulator reads (SENS_ACTS), so the noise floors and the named leader of the glider, USV, UAS and link entries move (round 17, M-8)."
Document sentences for batch G: CREDIBILITY.md:198 (the "most sensitive to" entry) add: "over the columns that class's simulator reads (the glider no wave column, the UAS no current and no Tp, the USV not the solar yield; an RF link also Hs)"; the floors of the demo in CREDIBILITY (table below); `q17_vs_q16`-style note: verdicts and every k_fail unchanged, only sensitivity floors and the UAS leader move.
What could break and was checked: `credibility.CLASS_PRIORS` and the used-input counts (ACTS untouched; test_credibility pins pass); `tests/test_stage1.py:865` pinned the glider S1 key set as `FORCING | ACTS` (now `SENS_ACTS["glider"]`; the pins at 1601 to 1623 call `_sensitivity` directly or check subsets and pass unchanged); a link with no vehicle end (ship to shore iridium) has an empty set but cannot have a failing member, so `_sensitivity` returns all_pass before it ranks; old `summary.json` files are only read, never re-ranked; `report._sens_html` and the paragraph read stored fields (unchanged shape: `S1` has fewer keys); no golden pins a sensitivity (`tests/golden/tepex_c_demo_quick.json` has none).
Tests (`tests/test_round17_c.py`): `test_r17_m8_each_vehicle_and_link_ranks_only_the_columns_its_simulator_reads`, `..._an_rf_link_reads_hs_whatever_the_classes_at_its_ends`, `..._a_column_the_uas_cannot_feel_cannot_head_its_list` (a UAS margin that is a function of current_direction_bias alone must not name it), `..._the_acting_table_is_what_the_simulator_reads_of_the_forcing[glider|usv|uas]` (a recording environment under the real `_run_glider`, `_run_usv`, `_run_uas`: the fields read give the columns; the table must equal them, so it cannot drift from the simulators), `..._the_usv_margin_does_not_move_with_the_solar_yield_only_its_charge_does`.

## M-19 tests (tests only)

- A-3: `test_r17_a3_a_cut_write_of_the_usv_table_cache_leaves_no_file_at_its_name` (a `savez` that writes then raises leaves no `usv_tables_*.npz`).
- A-5: `test_r17_a5_fly_sitl_refuses_a_series_shorter_than_the_longest_flight_before_anything_else` (stub SITL directory with an empty non-executable `arducopter` and a stand-in `pymavlink` module, so the guard is reached with no binary; a nominal-length series and a caller's longer `max_s` both raise "turbulence series covers").
- A-6: `test_r17_a6_soc_min_is_the_lowest_state_of_charge_and_starts_at_the_platform_start_value` (soc0 0.8, sun at twice the hotel load: soc_min is exactly 0.8 at start and after the run, the final state is above 0.9). The `ACTS['usv']` mutant of A-6 is covered by M-8's tests (the column is out of the USV set, the demo shows it).
DECISIONS row C2: "Round 17, M-19 (A-3, A-5, A-6): three tests hold round 16's fixes that survived every test run against them (the atomic write of the USV table cache, the turbulence guard of `fly_sitl`, `soc_min` as the lowest state of charge from soc0); each was shown failing on its mutant." CHANGELOG: "tests: round 17 batch C (M-8, M-19)."

## Runs (orca, proot; real rc and counts)

| log | what | rc | result |
|---|---|---|---|
| `r17c_1` | `tests/test_round17_c.py`, fixed tree | 0 | 10 passed |
| `r17c_2` | `ruff check cafe/pm tests`, `mypy cafe/pm` (first tree; one E501 fixed, rerun) | 0, 1 then fixed | |
| `r17c_4` | ruff and mypy on the final code and tests | ruff_rc=0, mypy_rc=0 | "All checks passed", "no issues found in 55 source files" |
| `r17c_3` | `-n 2` of test_round17_c, test_stage1, test_credibility, test_config, test_stats_exact, test_config_docs, test_runners, test_report, test_pipeline (commit ea87ea7) | 0 | 1895 passed by the progress-line count (no F, s, x or E) |
| `r17c_demo` | quick demo, PM_CPUS=6, PM_MEM=16g, load about 4 at start | 0 | below |
Coverage: only `stage1.py` changed (not a gated package); every new line is run by the tests above (not measured separately). physics, stats, env untouched.

## Fail-before (detached worktree at 433429e, only `tests/test_round17_c.py` copied in, dir `pm_r17c_base`)

- `r17c_base_all`: rc 1, 7 failed (the three behavioural M-8 tests: S1 key sets include hs_scale, tp_bias, solar_yield_scale, the inert current_direction_bias is named with S1 0.986; the three table tests and the solar test: no `SENS_ACTS`), and the three M-19 tests pass (their code is correct, as merged.md says).
- Mutants of the M-19 tests, each run on the base code with one line changed (the unmutated control is `r17c_base_all`, which passes them): `r17c_mut_a3` (`np.savez(f, **tab)` for the `atomic.write_with`): rc 1, one file left at the name; `r17c_mut_a5` (`_turbulence_covers(turb, so["duration_s"])`): rc 1, the mutant passes the guard and fails with PermissionError at the fake binary; `r17c_mut_a6a` (`soc_min = soc_wh / battery_wh`, the last state): rc 1 (0.92 against 0.8); `r17c_mut_a6b` (`np.full(M, 1.0)` start): rc 1 (1.0 against 0.8). Mutants reverted with `git checkout`.

## The demo (`r17c_demo` against q17, `review/round_14/q14summary.py r17c_demo q17`, sensitivity entries of `stage1/summary.json` and `report.json`)

No verdict, k_fail, interval, mode count, prior, mooring count, design row or plan figure moves (the summary differs only in `git_sha` and timings: stage1 168.4 s against 157.9 s, variants 277.9 against 271.7). What moves (stage1 and stage1b summaries equal each other; `report.json` `vehicles.*.sensitivity.noise_floor` and the printed `index.html` text agree):

| entry | q17 | r17c_demo |
|---|---|---|
| glider_eq: floor, columns ranked, largest S1 | 0.1909 (0.191 printed), 8, wind_direction_bias 0.106 | 0.1766 (0.177), 6, wind_direction_bias 0.106 |
| uas: floor, columns, largest S1 | 0.2138 (0.214), 8, current_direction_bias 0.177 | 0.1903 (0.190), 5, wind_speed_bias 0.121 |
| usv: floor, columns, S1 of tp_bias (ranked) | 0.2022 (0.202), 8, 0.299 | 0.1985 (0.199), 7, 0.299 |
| printed sentences | "largest S1 0.106, wind_direction_bias; floor 0.191", "largest S1 0.177, current_direction_bias; floor 0.214", "tp_bias ... (S1 0.299) ... above the 0.202" | "... floor 0.177", "largest S1 0.121, wind_speed_bias; floor 0.190", "... above the 0.199" |
glider_2n, the four links and the Iridium link: all_fail or all_pass in both, no change. The USV's case (ranked, tp_bias) and the two others (nothing_above_floor) keep their case. The count "the report makes N such tests" is unchanged.

## Not checked

The full suite, the gate and coverage numbers (the lead's); `report.py` and `credibility.py` text that quotes the old acting rule beyond the grep of "columns that can act" (only CREDIBILITY.md:198 found); a sensitivity on a mission with a UAS and no other vehicle or with a RF link between a glider and the ship end to end (only by a synthetic summary test); the SITL test itself (no binary); the A-5 mutant's later flow beyond the PermissionError; the 18 unfinished reviewer-A mutants.
