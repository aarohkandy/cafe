# Round 7 hand-back, batch V (vehicles): M-4, M-16, M-18, M-19, M-20, M-27, M-35, M-42, M-43

Branch `r7-v` (worktree `../cafe-r7v`). All nine findings are fixed; nothing is left unfixed. One part of M-27 (the row's `heading_source` text) needs a change in S's function, given under "needs from other batches".

Fail-first method: a detached worktree of `premission-step4` (`../cafe-r7v-old`, no stash) with only the eight test files copied in, run with `-k r7_` on homebase (`PMX=pm_r7v`), then the same on the fixed branch. Result: **fixed branch 21 passed; unfixed code 20 failed, 1 passed** (the one that passes on both is M-19's number pin, a wording finding: it pins numbers that do not change).

## Per finding

### M-35  loaders check the top-level blocks (glider.py:~89, usv.py:~137)
Both loaders: `missing = [k for k in ("kind", "params", "mission_defaults") if k not in raw]` -> `ValueError("<file>: missing [...]; add them (see platforms/<seaglider|saildrone_explorer>.yaml for the layout)")`, before `flat`.
Tests: `test_glider.py::test_r7_m35_the_glider_loader_names_the_file_and_the_missing_blocks`, `test_usv.py::test_r7_m35_the_usv_loader_names_...`, `test_cli.py::test_r7_m35_hangar_on_a_file_without_params_prints_provenance_failed_and_exits_1[seaglider|saildrone_usv]`.
Before: `KeyError: 'params'` at glider.py:103 / usv.py:140 (all four fail). After: pass; `hangar` prints `boat.yaml: missing ['params', 'mission_defaults']` after `provenance FAILED` and exits 1.

### M-16  non-finite shortwave and start position (usv.py `step`, `__init__`)
`step`: `bs = ~isfinite(sw)`; the energy update uses 0 W for those members; `no_current_data` is flagged for them. `__init__`: a non-finite start lon/lat is replaced by 0 (finite, so the step stays finite) and flagged at t = 0. `report.MODE_TEXT["no_current_data"]` gains "..., or no finite insolation there, so its motion or its battery could not be computed" (the round-4 prefix "there was no finite wind, current or wave state at the vehicle's position" is kept, so `test_report.py:1667` still holds). The flag time for the shortwave case is the end of the step in which the NaN was read (`_flag` uses `self.t`, already advanced), like the glider's "end of the first step".
Tests: `test_usv.py::test_r7_m16_a_non_finite_shortwave_...`, `test_r7_m16_a_non_finite_start_position_...`, `test_report.py::test_r7_m16_m20_the_page_names_...`.
Before: `assert np.isfinite(s.soc_wh).all()` False (soc NaN, battery never fires); start `[False, False, False] == [False, True, True]`. After: soc finite, `no_current_data` on all 3 members at 1.0 to 1.3 h, `battery` fires at the same hour as the clean run (to 1e-9).

### M-20  wind above the polar fails the member (usv.py `step`; `report.MODE_TEXT["capsize_proxy"]`)
Recommended variant (the flag): `acc["wind_out"]` accumulates `dt` while the wind relative to the water exceeds `pol.tws[-1]` (30 m/s); `capsize_proxy` is flagged when it reaches `stall_sustain_s` (1800 s, the existing clock; no new key). No new mode, so the mode set and the golden do not change. `MODE_TEXT["capsize_proxy"]` (new entry): "the roll peak passed the limit, or the wind relative to the water was above the polar's top (30 m/s: outside the model, counted as a failure, not a pass)".
Test: `test_usv.py::test_r7_m20_a_wind_above_the_polar_fails_every_member_...` (40 m/s at 10 m, i.e. ~37 m/s at the anemometer, 1 h, 3 members: every member fails `capsize_proxy`, first between 0.5 and 0.6 h; 25 m/s: none, `wind_out` stays 0). Before: `capsize_proxy` not fired (assert False). After: passes. Also `test_report.py::test_r7_m16_m20_...` (KeyError `capsize_proxy` before).

### M-18  `N_IT` 24 -> 48 (usv.py:91), `_digest` includes `N_IT`
Numbers (homebase, 31 x 73 polar, `usv._build_polar`; reference N_IT = 200; script `r7v_m18.py`):

| N_IT | build s | max abs dV vs 200 (m/s) | cells > 0.01 m/s | cells > 0.03 | cells rel > 2 % | TWS of the cells > 0.01 |
|---|---|---|---|---|---|---|
| 12 | 0.35 | 1.714 | 180 | 129 | 112 | 21 to 30 |
| 24 (was) | 0.64 | **1.549** (TWS 30, TWA 47.5: 1.573 vs 0.024) | **58** | 35 | 25 | 27 to 30 |
| 48 (now) | 1.24 | 0.025 | 9 | 0 | 1 | 30 |
| 96 | 2.45 | 0.0008 | 0 | 0 | 0 | none |
| 200 | 5.05 | reference | | | | |

At the worst cell (TWS 30, TWA 47.5) V / heel / K by N_IT: 12: 1.738 m/s, 27.85 deg, 386; 24: 1.573, 25.32, 408; 48: 0.0263, 25.00, 36.4; 96 and 200: 0.0241, 25.00, 36.4. The sway residual the receipt checks there is 0.0113 (N=12) and 0.0012 (N=24): small while V is wrong by 1.5 m/s, so the receipt could not see it. The converged state at that cell is a stall: V 0.024 m/s with sway residual 0.998 (no positive-X root, the `i0 = 0` fallback); that is existing behaviour, not changed here.
48 is converged to 0.025 m/s (the finding's choice); 96 would be converged to 1e-3 m/s for another 1.2 s of table build, if the lead prefers.
`_digest` now hashes `{**nums, "N_IT": N_IT}` (it did not include `N_IT`, so an on-disk `usv_tables_<digest>.npz` built with 24 would have been reused).
Tests: `test_r7_m18_the_polar_at_the_shipped_iteration_count_is_converged_everywhere_...` (the shipped-N_IT polar vs the 200 one < 0.03 m/s; it also builds N_IT = 24 and asserts it is > 1 m/s off and > 50 cells above 0.01, so the test can see the defect), `test_r7_m18_the_table_cache_key_follows_the_iteration_count`. Before: `1.549 < 0.03` False and equal digests. After: pass.

### M-4  two 12 m/s receipt rows, labels, yaml and header text (usv.py `receipts`, platforms/saildrone_explorer.yaml)
Receipt rows (usv.py ~701-711): "mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias; CALIBRATED: vpp_bias_mean)"; "best-heading still-water speed at 12 m/s, polar without the VPP bias (CALIBRATED: appendage_cda_m2; not what Stage 1 flies)" (value 2.923, 10 %, unchanged); new "best-heading speed at 12 m/s as Stage 1 flies it (polar x (1 + vpp_bias_mean))" = 2.2150 against 2.9, tolerance `chiodi_band` (0.25): passes (23.6 %), source text "... passes only because chiodi_band is wide; no single bias meets this and the 5.4 m/s mean: the polar is capped at 3.3 m/s".
yaml: header paragraph rewritten (what is fitted to what; "closure"; 2.2 m/s, 24 % under; the 3.3 x 0.7578 = 2.50 < 2.9 argument); `appendage_cda_m2` `why` and `vpp_bias_mean` `source` say what they are fitted to. No number in the yaml changed.
Existing tests changed: `tests/test_usv.py` used the two old row labels as dictionary keys (lines 683-714 of the old file); they now use module constants `MEAN_ROW`, `POLAR_ROW` holding the new labels. No assertion was weakened; only the key text.
Tests: `test_r7_m4_the_12_ms_receipt_has_a_row_for_...` (flown value == polar max x (1 + bias) to 1e-9, tol == `chiodi_band`, ok, > 20 % under 2.9), `test_r7_m4_the_flown_row_follows_the_bias` (bias -0.40: row fails; a mutant that drops the bias from the row fails the first test), `test_r7_m4_the_platform_header_says_what_is_fitted_to_what`. Before: KeyError on the new labels; header test fails. After: pass.

### M-19  wording; the numbers are pinned (test only)
`test_usv.py::test_r7_m19_in_short_steep_head_seas_the_first_order_speed_is_credited_with_what_the_boat_cannot_make`: at TWS 6, TWA 90 the still-water polar gives V = 1.554 m/s, K = 131.8 N s/m; `added_resistance(Hs 2, Tp 6, head seas)` at speeds [0, 0.5, 1.0, 1.554] = 312.6, 207.9, 155.6, 129.3 N (strictly decreasing); `USVSim._eval` returns 1.554 - 129.3 / 131.8 = 0.573 m/s. Passes on the unfixed code too (nothing in the model changed). The PHYSICS / CREDIBILITY text is below.

### M-27  heading record (stage1.py, glider.py, usv.py unchanged, pipeline_windows.py `track_heading`)
- `GliderSim` records `heading` (compass degrees of the horizontal swim direction, NaN before its first dive) every step; `USVSim` already recorded `heading` (`hd`).
- `stage1._run_glider` / `_run_usv` put `heading` on the 10-minute grid (NaN at the deploy record) via `_no_heading(h, M)`, which adds the entry only when the history holds one (the stand-in simulators in the tests have none); `merge` joins it along the members. UAS results have none.
- `track_heading(res, vid, t)`: the circular median over members (median of the offsets from the circular mean) of the recorded heading at the record nearest t; none finite or no heading in `res.pkl` -> the old course over ground. New `track_heading_source(res, vid, t)` returns "stage-1 heading (circular median)" or "course over ground (no heading in res.pkl)". Module docstring paragraph about heading reworded.
- `res.pkl` gets a `heading` array per glider and USV: its hash changes; the lead re-bases the golden hashes (the stage-1 numbers do not change).
Tests: `test_stage1.py::test_r7_m27_the_usv_and_glider_records_hold_the_bow_heading_...` (real runs with an eastward current across a northbound section: heading shape (13, 2), NaN first record, equals `sim.hd` / the glider's compass at the last record, and differs from the course by more than 5 deg), `test_r7_m27_merge_joins_the_heading_...`; `test_stage3.py::test_r7_m27_track_heading_is_the_recorded_bow_heading_...` (course 45, recorded 90 -> 90; without it 45), `test_r7_m27_the_heading_median_is_circular_...` ([350, 355, 5, 10] -> 0, a plain median gives 180; NaN members skipped). Before: KeyError 'heading' / 44.99999 == 90. After: pass.

### M-42  `battery_swap` removed (platforms/quad_uas.yaml, uas.py `REQUIRED`, `fly_mission` docstring)
Leaf and `REQUIRED` entry removed; docstring: "each starts on a full pack: the ship crew swaps it". A file that still carries the key loads (extra leaves are not refused). Tests (`test_uas.py`): `test_r7_m42_battery_swap_is_not_a_platform_input_and_an_old_file_...`, `test_r7_m42_every_required_key_of_the_uas_platform_is_named_in_the_code_that_reads_it` (every key of `uas.REQUIRED` appears quoted in the `cafe/pm` code; `[('sortie', 'battery_swap')]` before, `[]` after, for all the other keys too).

### M-43  `_Sim1` takes `t_launch` (uas.py)
`_Sim1.__init__(..., t_launch=0.0)`; `step` calls `wind_fn(k, t_launch + t, pos)`; `fly_sitl` passes `t_launch`. `t_launch = 0` is unchanged (the existing `[0.0, 0.05, 0.10]` test still passes untouched). Test `test_uas_exact.py::test_r7_m43_...`: with `t_launch = 1.7e9` the wind function sees 1.7e9, +0.05, +0.10; the sortie clock `s.t` still starts at 0. The test helper `air()` gained a `t_launch=0.0` argument. Before: `TypeError` (no such argument; the old behaviour is the pinned `[0.0, 0.05, 0.10]` of the existing test). Not tested: the one-line call-site wiring in `fly_sitl` (`_Sim1(P, prm, wfn, ship0, motor_map, t_launch)`), which needs the SITL binary.

## Proposed DECISIONS rows (the lead numbers them from 341)

| ? | The USV 12 m/s receipt is two rows: the unbiased polar the `appendage_cda_m2` fit was made on (2.923 m/s against 2.9, 10 %, labelled "not what Stage 1 flies") and the model Stage 1 flies, polar x (1 + `vpp_bias_mean`) = 2.215 m/s against 2.9 with tolerance `chiodi_band` (0.25; 23.6 %, a pass by 1.4 points). The 5.4 m/s row is labelled CALIBRATED: `vpp_bias_mean`. No number of the model changes. | Review round 7, M-4. One bias cannot meet both targets (the polar is capped at 3.3 m/s, 3.3 x 0.7578 = 2.50 < 2.9), so the statement changes, not the model. Amends 163: "reproduces" is a closure for the 5.4 m/s mean. |
| ? | A USV whose shortwave value is not finite uses 0 W for that step and is flagged `no_current_data`; a member whose start position is not finite is flagged at t = 0 and starts at (0, 0). | Review round 7, M-16. NaN through `np.clip` made the battery state NaN for good and `NaN <= 0` is False, so `battery` never fired. Extends 308. |
| ? | `usv.N_IT` is 48 (was 24); the table digest includes it. The polar changes only above 27 m/s (58 cells moved by more than 0.01 m/s, the worst by 1.55 m/s); 48 against 200 iterations agrees to 0.025 m/s. | Review round 7, M-18. 24 iterations had not converged in storm winds and no test varied it. |
| ? | Added resistance is linearised about the calm speed (R_aw/K), unchanged; where R_aw(0) exceeds the thrust X(0) the true speed is zero and the model reports a small positive one (Hs 2 m, Tp 6 s, TWS 6 m/s, TWA 90: 0.573 m/s). The numbers are pinned in tests/test_usv.py. | Review round 7, M-19. A root find per table cell would be a model change; the limitation is stated. |
| ? | A USV member whose wind relative to the water stays above the polar's top (30 m/s) for `stall_sustain_s` (1800 s) fails `capsize_proxy`. No new mode. | Review round 7, M-20. The polar clamps at 30 m/s, so a 60 m/s wind was a pass; for a go/no-go tool the out-of-range member must fail. |
| ? | The window heading is the stage-1 bow heading (`res.pkl` vehicles[vid]["heading"], circular median over members at the nearest 10-minute record); a run without it, and a UAS, use the course over ground. | Review round 7, M-27. The course includes current, leeway and Stokes drift; the polar and the glider case take the heading as the bow direction. |
| ? | `sortie.battery_swap` is removed from `quad_uas.yaml` and `uas.REQUIRED`; every sortie starts on a full pack. A file that still carries the key loads. | Review round 7, M-42. A required input read by no code. |
| ? | `uas._Sim1` takes `t_launch`; the environment is read at `t_launch + t`. | Review round 7, M-43. `fly_sitl` read the environment at seconds since boot. |
| ? | `glider.load_platform` and `usv.load_platform` refuse a file without `kind`, `params` or `mission_defaults` with a `ValueError` naming the file and the blocks. | Review round 7, M-35. `hangar` ended in `KeyError: 'params'`. |

## Proposed CHANGELOG lines
- M-4: USV receipts: the 12 m/s row split into the unbiased polar (the fit) and the model Stage 1 flies (2.215 vs 2.9 m/s, `chiodi_band`); calibration labels and the platform-file header state what is fitted to what.
- M-16: USV: a non-finite shortwave value is 0 W and flags `no_current_data`; a non-finite start position is flagged at t = 0.
- M-18: USV polar: `N_IT` 24 -> 48 (storm-wind cells were off by up to 1.5 m/s); the table digest includes `N_IT`.
- M-19: USV added resistance: the first-order numbers in short steep seas are pinned in tests (statement of the regime in PHYSICS and CREDIBILITY).
- M-20: USV: a wind above the polar's 30 m/s for 30 min fails `capsize_proxy`.
- M-27: stage 1 records each glider's and USV's heading in `res.pkl`; the stage-3 window heading is its circular median, the course over ground only without it.
- M-35: the glider and USV loaders name the file and the missing top-level blocks.
- M-42: `sortie.battery_swap` removed (read by no code).
- M-43: `fly_sitl` reads the environment at launch time plus the time since launch.

## Doc text for the lead (quoted exactly, with where it goes)

**docs/PHYSICS.md 10.1, the `balance` line (about line 650)**: replace "by 24 damped fixed-point iterations" with "by 48 damped fixed-point iterations (review round 7, M-18: 24 left 58 cells at 27 to 30 m/s of wind off by up to 1.5 m/s; 48 agrees with 200 to 0.025 m/s)".

**docs/PHYSICS.md 10.1, the "Fit." bullet (about line 655)**: replace with: "**Fits.** Two numbers are fitted, each to one target and neither checked against the other (review round 7, M-4). `appendage_cda_m2` was raised from 0.02 to 0.04 so that the best-heading speed at 12 m/s on the polar *without* the VPP bias matches Chiodi et al. 2021 (2.9 m/s). `vpp_bias_mean` is solved so that `usv.mean_sog` gives exactly the 5.4 m/s mean SOG / wind of 0.96 / 5.4: a closure, not a reproduction. Stage 1 flies the polar times (1 + `vpp_bias_mean`), which is 2.215 m/s at 12 m/s, 24 % under 2.9; no single bias meets both targets because the polar is capped at 3.3 m/s (3.3 x 0.7578 = 2.50 m/s < 2.9). Both receipts are labelled `CALIBRATED` and are calibrations, not validations (limitation L02)."

**docs/PHYSICS.md 10.1, after "Stage 1 lowers the speed by R_aw/K ... (first order)" (M-19)**: add: "Regime of validity (review round 7, M-19): added resistance is linearised about the calm speed, where it is smallest (it is largest at rest and falls with speed). Where R_aw(0) exceeds the thrust X(0) (short steep head seas: Hs 2 m, Tp 6 s, TWS 6 m/s, TWA 90 deg gives R_aw = 312.6, 207.9, 155.6, 129.3 N at 0, 0.5, 1.0, 1.554 m/s against X(0) = 105.5 N), the model's own equation X(V) = R_aw(V) has no positive root, the true speed is zero, and the model reports 1.554 - 129.3 / 131.8 = 0.573 m/s. Within modest seas the first-order speed is within 3 % (Hs 1 m, Tp 8 s: 1.475 against 1.470 m/s; reviewer's figure, not re-run). A root find per table cell would be a model change and is not made."

**docs/PHYSICS.md 10.1 / 10.2 (M-20)**, where the polar is described and in the flag list after `capsize_proxy`: "`capsize_proxy` (also fired when the wind relative to the water stays above the polar's top, 30 m/s, for `stall_sustain_s`: outside the model, so a failure, not a pass; review round 7, M-20; the polar clamps at 30 m/s)".

**docs/PHYSICS.md 10.2 flags list, `no_current_data` (M-16)**: append "... and, since review round 7, M-16, a non-finite shortwave value (0 W of sun for that step) or a non-finite start position (flagged at t = 0)"; and for `battery`: "(solar gain `eff x area x SWDOWN`, 0 W where SWDOWN is not finite, minus hotel load)".

**docs/PHYSICS.md 10.2 receipts table**: replace the two rows by
| `mean SOG / U at 5.4 m/s (VMG routing, all bearings, prior bias; CALIBRATED: vpp_bias_mean)` | 25 % band (assumed) | 0.1778 against Chiodi's 0.1778: a closure (vpp_bias_mean is solved to give it); bias 0 gives 0.2345 (+31.9 %), -0.30 gives 0.1643 (-7.6 %), -0.325 gives 0.1584 (-10.9 %), -0.35 gives 0.1525 (-14.2 %) |
| `best-heading still-water speed at 12 m/s, polar without the VPP bias (CALIBRATED: appendage_cda_m2; not what Stage 1 flies)` | 10 % | **fit**; 2.92 against 2.9 m/s |
| `best-heading speed at 12 m/s as Stage 1 flies it (polar x (1 + vpp_bias_mean))` | 25 % (`chiodi_band`) | 2.215 against 2.9 m/s (23.6 %); passes only because the band is wide; no single bias meets this and the 5.4 m/s mean (the polar is capped at 3.3 m/s) |

**docs/CREDIBILITY.md limitations** (M-4, M-19, M-20), three new lines in the table's format (ids to be assigned by the lead):
- "USV speed at moderate and strong wind is 24 % under the maximum the calibration was meant to hit (best-heading 2.215 m/s at 12 m/s as flown against Chiodi's 2.9; the 5.4 m/s mean is met by construction)"; also change L02's "holds: `appendage_cda_m2` 0.02 to 0.04; the receipt is labelled CALIBRATED" to end "...; the receipt is labelled CALIBRATED and a second row shows the model as flown".
- "USV added resistance is linearised about the calm speed: in short steep seas (Hs 2 m, Tp 6 s) the boat is credited 0.57 m/s it cannot make, so becalmed and swept_off_track are under-reported in exactly those sea states".
- "USV winds above 30 m/s are outside the polar; members that stay there fail `capsize_proxy` (a flag, not a physical capsize)".

**RUNBOOK / QUESTIONS / STATUS**: nothing from this batch (RUNBOOK line 115's claim about `hangar` is now true).

## Needs from other batches

1. **S (stage-3 `pipeline_windows.py`), M-27 row text.** I only touched `track_heading` and added `track_heading_source` next to it. For the row to say what the heading is, in `_describe` replace `heading_source="stage-1 median track" if heading is not None else "relative-flow direction (no stage-1 track)"` by `heading_source=source if heading is not None else "relative-flow direction (no stage-1 track)"`, give `_describe` a `source: str` parameter after `heading`, and pass `track_heading_source(res, vid, w["t"])` at its two call sites (`_row`, line ~487, and the hull_fs path, line ~643). Then the existing assertion `tests/test_stage3.py:1092` (`r["heading_source"] == "stage-1 median track"`, a res with no heading) becomes `== "course over ground (no heading in res.pkl)"`, and the one at 1049 (`startswith("relative-flow")`) is unchanged. I did not make this change (shared function, not mine); my branch leaves that assertion as is and it passes.
2. **Lead**: re-base the golden hashes of `res.pkl` (new `heading` array per glider and USV); the stage-1 values do not move. A merge of `tests/test_usv.py` with batch R's report tests is not needed: my report tests are appended to the end of `tests/test_report.py`.
3. **R (report.py)**: nothing; my `MODE_TEXT` edits are the `no_current_data` reword and a new `capsize_proxy` entry only.

## Commands run and results

All on homebase from `/Users/aaroh/Downloads/everything/cafe-r7v`, `PMX=pm_r7v PM_CPUS=2`, `PM_MEM=8g` (12g for the whole-file run):

- Unfixed code (`../cafe-r7v-old`, detached at `premission-step4` with only the eight test files copied in; removed afterwards): `python -m pytest -q -p no:cacheprovider tests/test_usv.py tests/test_glider.py tests/test_uas.py tests/test_uas_exact.py tests/test_stage1.py tests/test_stage3.py tests/test_cli.py tests/test_report.py -k r7_` -> 20 failed, 1 passed (M-19's pin).
- Fixed branch, same command -> 21 passed in 21 s.
- Fixed branch, whole files with coverage: `python -m pytest -q -q -p no:cacheprovider --cov=cafe.pm.physics --cov=cafe.pm.stage1 --cov=cafe.pm.stage3.pipeline_windows --cov-report=term-missing:skip-covered tests/test_usv.py tests/test_glider.py tests/test_uas.py tests/test_uas_exact.py tests/test_platform_required.py tests/test_stage1.py tests/test_stage3.py tests/test_cli.py tests/test_report.py` -> rc=0, every test passed (738 collected; about 45 min on 2 CPUs). Coverage: `physics/usv.py`, `glider.py`, `uas.py` and `stage3/pipeline_windows.py` at 100 % (not listed as missing). Listed as missing: `physics/comms.py` and `rigid.py` (their tests are other files; I did not touch them) and `stage1.py:890` (the `par.width() > 1` branch of `run`, untouched by me, covered by test_pipeline). The SITL tests in test_uas.py passed in this run (the flaky one did not flake).
- `python -m ruff check cafe/pm tests bench` -> All checks passed. `python -m mypy cafe/pm` -> Success: no issues found in 54 source files.
- `r7v_m18.py` / `r7v_m18b.py` (numerics, the table and the worst-cell line in M-18) were run with the image's python in the same container; scratch scripts removed from `pmdata` afterwards. No container or tmux session of mine is left (`docker ps | grep r7v`, `tmux ls | grep r7v` empty).

## Anything that still looks wrong

- At the worst storm cell (TWS 30, TWA 47.5) the converged polar has V = 0.024 m/s and a sway residual of 0.998: the root search has no positive-X root and falls back to the bottom of the grid. That is the model's answer (a stalled boat), but the sway-residual receipt is only run at TWS <= 14, so nothing looks at these cells. Not changed.
- `fly_sitl`'s `_Sim1(..., t_launch)` wiring is not exercised by any test (needs the SITL binary).
- `USVSim` flags `no_current_data` for a missing shortwave at the end of the step in which it is read (so `first` is one step later than the NaN); the wording of the flag in `first[name]` ("epoch seconds of the first occurrence") is therefore one step late for that cause, as for the glider's "end of the first step".
