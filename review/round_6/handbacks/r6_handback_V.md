# Round 6, batch V hand-back (M-1, M-4, M-5, M-10, M-15, M-16, M-26)

All seven findings fixed. Worktree `/Users/aaroh/Downloads/everything/cafe-r6v`, branch `r6-v`. Two existing assertions in `tests/test_report.py` (not my file) assert the old wording and fail until the lead changes them (see "needs from other batches").

## Per finding

### M-1 (USV wave state not a number)
- `cafe/pm/physics/usv.py` `step` (~l.551-556): `bv = ~(isfinite(Hs) & isfinite(Tp) & isfinite(dir_to) & isfinite(stokes).all(-1))`; for those members Hs 0, Tp = `self.wt.tp[0]`, direction 0, Stokes 0; `no_current_data` is flagged for `bw | bc | bv`. Docstring (l.69-71) updated. `cafe/pm/report.py` `MODE_TEXT["no_current_data"]` rewritten ("there was no finite wind, current or wave state at the vehicle's position (a land block, a masked cell or a hole in the sea mask), so its motion could not be computed"). Mode key unchanged.
- Tests: `tests/test_usv.py::test_a_wave_state_that_is_not_a_number_fails_every_member_from_the_first_step_and_the_run_goes_on` (hs, tp, hs+tp, direction), `test_a_stokes_drift_that_is_not_a_number_is_the_same_failure`; `tests/test_stage1.py::test_a_usv_in_a_hole_of_the_sea_mask_is_a_no_go_labelled_no_current_data_not_a_crash` (GriddedEnv `ci_full` wrapped so every wave variable is NaN, through `stage1.run_batch` and `summarize`: k_fail = M, NO-GO, mode counted).
- Before (baseline code + new tests): hs-only: silent pass (`assert np.False_`, no flag); tp, hs+tp, direction, and the run_batch case: `IndexError: index -9223372036854775808 is out of bounds` from `_lin`. After: pass.
- Deviation: the finding's GriddedEnv test says "seamask zero under the start"; I wrapped `ci_full.waves` instead of editing the session fixture's arrays (same NaN-together state the sea mask produces).

### M-4 (UAS launch in the first/last hour of the window)
- `cafe/pm/stage1.py`: new `_uas_hours(env, ts)` (l.180) returns the gust-front hours inside `env.bounds[4:6]` and the number dropped; `_uas_forcing` uses it (l.225); `_run_uas` adds `hours_dropped` (only when > 0) to its result; `merge` carries it (same in every batch); `run` writes a ledger note.
- Deviation from the finding's fix text: I kept the old hour set (look-back hour to `ts[-1] + 7200`) and drop the hours outside the data, instead of shortening the look-ahead to the sortie's end. Shortening changes the length of the hourly array and so every Poisson draw of every UAS run (q6 and the golden would move), against the finding's own aim that they do not. Hours outside the data get no events either way; `rain_hourly` stays strict.
- Tests (`tests/test_stage1.py`): `test_a_launch_in_the_last_or_first_hour_of_the_window_builds_the_gust_forcing_on_the_hours_the_data_has` (05:05, 05:20, 05:28Z last day; 18:10, 18:50Z first day), `test_a_launch_well_inside_the_window_keeps_the_hours_it_always_had` (hours identical to the old formula), `test_the_uas_result_counts_the_dropped_hours_and_the_stage_note_says_so`.
- Before: the five launches raise `OutsideData: WRF rain_hourly ... 2023-03-03 07:00:00Z` / `2023-03-01 17:00:00Z`. The other two tests fail on baseline with AttributeError (`_uas_hours` does not exist). After: pass.

### M-5 (null wind-direction prior)
- `cafe/pm/pipeline.py` `_tao` (l.621-626): an entry whose `mean` or `value` is not finite is not written; ledger note "no usable wind direction at the moorings (dir_n N): wind_direction_bias/noise stay the perturbations.yaml priors". `cafe/pm/stats/sampling.py:59`: `to_marginals` checks `isinstance(value, (int, float, np.number))` first, so `None`/str/list is the ValueError naming the key.
- Tests: `tests/test_pipeline.py::test_a_comparison_without_a_usable_wind_direction_writes_no_direction_prior_and_stage1_accepts_the_fit` (both a NaN mean+rmse and a NaN mean only; `priors_for` accepts the fit), `tests/test_stats.py::test_a_prior_without_a_numeric_sd_is_a_value_error_naming_the_key` (the finding names tests/test_sampling.py, which does not exist; sampling is tested in test_stats.py).
- Before: `wind_direction_bias` written with null mean/value; `to_marginals(value=None)` raises `TypeError: ufunc 'isfinite' not supported`. After: pass.

### M-10 (platform range gaps)
- `cafe/pm/physics/__init__.py`: `check_params` kinds extended: `nonzero`, `ge1`, `<kind><=max`, `range:lo:hi` (`_rule`). `usv.py` `REQUIRED`: `rudder_x_m` nonzero, `rudder_area_m2`/`rudder_span_m`/`rudder_t_c` pos (moved from OPTIONAL: `_foil` reads them by f-string), `stw_cap_ms` `pos<=50`; new `MISSION_REQUIRED = {cap_cycles: ge1}` checked on `mission_defaults` (`cap_cycles` lives there, not in `params`; `ge1` rather than the finding's `positive`, because sqrt(2 ln N) is NaN for 0 < N < 1). `glider.py` `_COMMON`/seaglider: `gravity` `pos<=20`, `t_deep_c` `range:-5:50`, `apogee_overshoot` `nonneg<=5`, `hd_s` `range:-0.9:0` (the model divides by 1 + hd_s), `abs_compress` `pos<=1e-3`, `therm_expan` `pos<=1e-2`, `temp_ref` `range:-5:50`. The maxima other than the finding's 50 and 20 are my choices, stated in the loader message.
- Tests: `tests/test_usv.py::test_the_usv_loader_refuses_a_leaf_...` (11 triples), `tests/test_glider.py::test_the_glider_loader_refuses_a_leaf_...` (17 triples), `..._names_the_limit_...`, and two table-staleness tests (`any` leaves are a fixed list).
- Before: the out-of-range triples load (rest already refused). After: all refused; shipped files load (`test_platform_required.py` passes).
- Not done: I did not extend round 5's literal-vs-REQUIRED test; the two `any`-leaf tests replace it (a new `any` leaf fails them).

### M-15 (certify wording)
- `cafe/pm/stats/intervals.py` `verdict` note for 60 <= n < 73 now reads "the one-sided rule of three gives P(fail) < 3/n = 0.047 at 95% confidence (n = 64), below 5%; that is a weaker statement than the report's certification, which needs the two-sided 95% Wilson upper bound below 5%: 73 members." The n < 60 sentence is unchanged (test_stats_exact pins it).
- Tests: `tests/test_stats.py::test_the_rule_of_three_note_says_it_is_a_weaker_statement_than_the_certification`; the existing `test_the_zero_failure_note_asks_for_60_members_only_below_60` changed its 60..72 assertions to the new wording (it asserted the old wording; rule and numbers are unchanged).
- Before: note contained "already below 5%". After: passes.

### M-16 (sensitivity sentence)
- `cafe/pm/stage1.py` `_sensitivity` (l.717-724): S1 and floor to three places in both texts; " by 0.006" appended when they agree to two places.
- Test: `tests/test_stage1.py::test_the_sensitivity_sentence_prints_the_index_and_its_floor_to_three_places_and_the_gap_when_they_agree_to_two`. Before: "(S1 0.12) ... above the 0.12". After: pass.

### M-26 (tests that cannot fail)
- Tests: `tests/test_usv.py` `test_met_scales_east_west_metres_by_the_cosine_of_the_mean_latitude_and_leaves_a_meridian_alone`, `test_a_section_leg_east_west_at_60_north_has_...`, `test_becalmed_is_a_best_speed_below_the_current_not_below_half_of_it` (wind 3 m/s, current 2.0 and 0.8, no VPP bias: best speed 0.62 and 1.15 of the current); `tests/test_stage1.py::test_the_speed_over_ground_of_a_track_along_60_north_is_half_the_equatorial_one`; `tests/test_stats.py::test_the_go_lower_bound_is_the_smaller_of_075_and_the_missions_go`.
- Mutant runs (scratch copy synced to my homebase dir, only the named test files, each mutant applied alone): `_met` without cos(lat): both USV geometry tests FAIL (killed); `path_speed` without cos: its test FAILS (killed); `vmax <= 0.5 * speed(cur)`: the becalmed test FAILS (killed); `min(0.5, go)`: the go-bound test FAILS (killed). All four pass on the unmutated code.
- `tests/test_glider.py` line 413 (`... or True`) deleted. `audit.BANNED` gains `|\bassert\b.*\bor True\s*$` (`cafe/pm/audit.py:32-33`); `tests/test_audit.py::test_an_assert_that_ends_in_or_True_is_a_banned_pattern_and_other_uses_of_it_are_not` (fixture tree: the assert line is flagged, `lambda url: log.append(url) or True` is not). Before (baseline `audit.py`): `banned()` returns `[]` for that tree. The repo itself has no other match.

## Needs from other batches
1. `tests/test_report.py:1667` (batch owning test_report): `"the ocean current was not a number at the vehicle's position" in t` -> `"there was no finite wind, current or wave state at the vehicle's position" in t`. Fails until changed (my MODE_TEXT rewrite, M-1).
2. `tests/test_report.py:1745`: `"already below 5%" in d["note"]` -> `"weaker statement" in d["note"] and "already below" not in d["note"]` (M-15).
3. Docs (lead): `docs/PHYSICS.md:672`, replace "a non-finite wind or current vector, e.g. a land block of the ocean store, is replaced by zero for that step" with "a non-finite wind, current or wave state (Hs, Tp, direction or Stokes drift; the UMWM sea-mask holes), e.g. a land block of the ocean store, is replaced by zero for that step (Hs 0, Tp the wave table's first period, direction 0, Stokes 0)"; `docs/PHYSICS.md:841`, replace the "already below 5 %" clause with "from 60 to 72 the note says the one-sided rule of three is a weaker statement than the report's certification (round 6, M-15)"; add to PHYSICS.md's platform section: "Platform leaves carry ranges: `check_params` kinds `nonzero`, `ge1`, `<kind><=max` and `range:lo:hi` (round 6, M-10)".

## Proposed DECISIONS rows
- `| ? | A USV whose wave state (Hs, Tp, direction or Stokes drift) is not finite at its position is flagged `no_current_data` from that step (step runs on Hs 0, Tp = first table period, direction 0, Stokes 0); the key is unchanged and MODE_TEXT names the wave state. | Review round 6, M-1. A masked UMWM node is NaN in all wave variables together; the step needs all of them, so holding values would invent a sea state. |`
- `| ? | The UAS gust-front hours that lie outside the ingested time span (a launch within an hour of window start or end) are dropped, not read; the hour set is otherwise unchanged (look-back hour to last launch + 2 h), a dropped-hour count is stored (`hours_dropped`) and noted in the stage-1 ledger. | Review round 6, M-4. Amends row 284's hour set. The look-ahead is not shortened: that would change every Poisson draw and move q6 and the golden. |`
- `| ? | `_tao` writes a fitted wind prior only when its mean and value are finite; otherwise the perturbations.yaml prior stands and the ledger says so. `to_marginals` raises a ValueError naming the key for a non-numeric sd. | Review round 6, M-5. Zero wind has no direction; a null prior crashed stage 1 with a TypeError. |`
- `| ? | Platform leaves the models divide by, take a log of or exponentiate have ranges checked at load: stw_cap_ms <= 50, gravity <= 20, cap_cycles >= 1, rudder area/span/t_c > 0, rudder_x_m != 0, hd_s in [-0.9, 0], abs_compress <= 1e-3, therm_expan <= 1e-2, temp_ref and t_deep_c in [-5, 50] degC, apogee_overshoot <= 5. | Review round 6, M-10. Maxima other than 50 and 20 are chosen limits, named in the loader message; they reverse no row (amends 303's tables). |`
- `| ? | The zero-failure note for 60 <= n < 73 says the rule of three is a weaker statement than the 73-member two-sided Wilson certification, and no longer says "already below 5 %". | Review round 6, M-15. Amends row 286's quoted text only; rule and numbers unchanged. |`
- `| ? | The sensitivity sentence prints S1 and the noise floor to three places and, when they agree to two, their difference. | Review round 6, M-16. "0.12 above 0.12" read as a tie. |`
- `| ? | `audit.BANNED` has a pattern for an assert ending in `or True`; the four mutants that survived (USV east-west metres, `path_speed` east-west, the becalmed rule, the 0.75 go-bound) have tests, each shown failing on its mutant. | Review round 6, M-26. A vacuous assertion passed the token audit. |`

## CHANGELOG lines
- M-1: a USV with a non-finite wave state (UMWM sea-mask hole) is flagged `no_current_data` instead of a NaN position or an IndexError.
- M-4: a UAS launch in the first or last hour of the window no longer aborts stage 1 with `OutsideData`; hours outside the data carry no gust events and are counted in the ledger.
- M-5: no usable mooring wind direction leaves the direction priors at their configured values; a non-numeric prior sd is a ValueError naming the key.
- M-10: platform loaders refuse the 17 out-of-range leaf values (new `check_params` kinds).
- M-15: the rule-of-three note no longer says "already below 5 %".
- M-16: the sensitivity sentence prints three places for S1 and its floor.
- M-26: tests for `_met`, `path_speed`, the becalmed rule and the 0.75 go-bound; the vacuous glider assertion is gone; `BANNED` catches `assert ... or True`.

## Commands and results (homebase, `PMX=pm_r6v`, `PM_CPUS=2`)
- `ruff check cafe/pm tests bench`: clean (after wrapping long lines). `mypy cafe/pm`: Success, no issues in 54 files.
- New tests on baseline code + my test files (worktree `cafe-r6v-old`): all new behavioural tests fail for the reasons quoted above (listing in the log of this session).
- `pytest tests/test_usv.py test_glider.py test_platform_required.py test_stats.py test_stats_exact.py test_audit.py test_stage1.py test_uas.py test_uas_exact.py test_config.py test_cli.py test_comms.py test_comms_exact.py test_report.py` with `--cov` on physics, stats, stage1 (PM_MEM=8g): coverage physics `__init__`/glider/usv/uas/comms 100 %, stats 100 %; stage1 one missed line (885, `par.adopt`, not mine). Failures: the two test_report tests above, and 13 test_cli tests that hit the round-5 memory guard ("stage 1 needs about 9 GB ... 9 GB is available") because I limited the container to 8 GB.
- `pytest tests/test_cli.py test_tao.py test_whatif.py test_budget.py` at PM_MEM=16g: rc=0. `pytest tests/test_pipeline.py -k "tao or fitted or priors or ingest"`: rc=0. Not run: the whole of tests/test_pipeline.py and test_report.py's other tests beyond the run above.
- No container of mine is left running (`docker ps | grep r6v` empty).
