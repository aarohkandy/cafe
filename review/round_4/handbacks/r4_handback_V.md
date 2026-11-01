# Round 4 hand-back, batch V (vehicles and stage 1)

Findings fixed: M-1 (physics, platform and stage-1 parts), M-5 (usv.py and stage-1 parts), M-7 part (1), M-8, M-10, M-11 (stage-1 part). None left unfixed.
Two of them need the lead's attention before they are accepted: **M-8** (the finding's sign is wrong once the divergence factor it asks for is included; details below) and **M-1** (the demo's UAS verdict will probably move).

Files changed (all on the list I own): `cafe/pm/physics/uas.py`, `cafe/pm/physics/usv.py`, `cafe/pm/physics/comms.py`, `platforms/quad_uas.yaml`, `cafe/pm/stage1.py`, `tests/test_uas.py`, `tests/test_usv.py`, `tests/test_comms.py`, `tests/test_stage1.py`. (`tests/test_comms_exact.py` needed no change.)

Not committed. Scratch files: `scratchpad/v_probe1.py`, `v_probe2.py`, `v_ids.txt`, `oldtree/` (a copy of the tree with HEAD's versions of the five source files, used to show the tests fail before).

---------------------------------------------------------------------------------------------------------------------------------

## M-1 UAS profile cut by the return-to-ship timer

What changed
- `cafe/pm/physics/uas.py:50` `FLAGS` gains `profile_incomplete` (so `fly_mission`, `stage1._run_uas` and the report's mode tables get it for free).
- `uas.py:521` `simulate` returns `wp_done` (`S.wpi` at the end, (M,) ints). `uas.py:557-558` `fly_sortie`: `short = wp_done / n_wp < sortie.min_profile_fraction`; the flag is set for flown (not scrubbed, the existing `& gate["ok"]` mask) sorties, `t_first` is the end of the sortie (`t_end`, float64). `uas.py:566, 569` the all-scrubbed branch returns `wp_done` zeros; `fly_sortie` returns `n_wp` (pattern length) in both branches.
- `platforms/quad_uas.yaml:115` `sortie.min_profile_fraction` 1.0, `assumed: true`, why as the finding words it, and a `replace_with` key ("the lab's minimum acceptable profile"). The credibility table has no replace_with column for platform leaves (`credibility.py` ignores the key), so the text is only in that key; batch G may want to show it. One more assumed input in the credibility table (two with M-10).
- `stage1.py:333, 327` `_run_uas` keeps `wp_done` in each `sorties[i]` and `n_wp` on the vehicle result (both only when the sortie result has them: older/stubbed results have neither). `merge` (`stage1.py:573-590`) concatenates `wp_done` with the other sortie arrays and carries `n_wp`. `summarize` (`stage1.py:678-681`) writes `vehicles[<uas id>].profile = {"wp_done_median", "n_wp", "complete_share"}` over the flown (member, sortie) pairs; absent when no wp_done is stored or nothing was flown. `profile_incomplete` is in `modes` like any other.
- `time_limit_factor` untouched.

Tests (fail before, pass after; "before" = HEAD source with these tests, run in `oldtree`):
- `tests/test_uas.py::test_the_fast_sortie_reaches_every_waypoint_and_reports_how_many` (KeyError n_wp before)
- `::test_a_sortie_cut_short_by_the_timer_is_profile_incomplete_and_the_minimum_fraction_sets_the_bar` (KeyError wp_done before; also pins the exact `>=` edge: fraction n/4 passes, (n+0.5)/4 fails)
- `::test_a_scrubbed_sortie_is_not_profile_incomplete_and_still_reports_its_pattern`
- `::test_the_demo_sortie_in_a_6_m_s_wind_returns_at_7_of_8_waypoints_and_in_still_air_flies_all_8` (real platform, 20 min sortie; 8 of 8 at 0 m/s, 7 of 8 at 6 m/s, flag only on the windy one, no battery flag, landed)
- `tests/test_stage1.py::test_the_profile_each_flown_sortie_delivered_is_kept_merged_and_summarised` (stub sorties flying 8/6 and 7/5 of 8 waypoints, second sortie scrubbed for member 1: profile = median 7, n_wp 8, complete share 2/6 over two merged batches; `modes.profile_incomplete` = 4)
- `::test_an_older_uas_result_without_wp_done_has_no_profile_block` (absence accepted; all-scrubbed gives no block). Passes before and after by design: it guards the "accept absence" rule.

Measurement asked for ("fraction of sorties that completes at the demo's median wind"). Probe `v_probe2.py` on homebase: real platform, 15 members each in its own uniform 10 m wind (AnalyticEnv's log profile, so the winds aloft are about 20 % higher), upwind legs, no turbulence:

| 10 m wind [m/s] | 2 .. 5.0 | 5.5 .. 6.5 | 7.0 | 7.5 .. 9.0 |
| waypoints flown of 8 | 8 | 7 | 6 | 5 |
| sortie ended at [s] | 1186 .. 1259 | 1269 .. 1408 | 1493 | 1281 .. 1440 |

So the sortie is complete up to about 5.2 m/s and cut at 7 of 8 above it. At the finding's 5.3 m/s median the answer is "just past the edge: 7 of 8"; with the demo's wind-bias spread (perturbations.yaml `wind_speed_bias` sigma 2.0 m/s) around 5.3, about 45 to 50 % of the sorties would complete (Phi((5.2 - 5.3) / 2.0)), if the ensemble's wind at the ship is N(5.3, 2.0). That second number is arithmetic on the prior, not a measurement of the demo ensemble. The lead has to re-run the demo to get the real share and the new UAS verdict: with `min_profile_fraction` 1.0 any member that fails to complete on any sortie is failed, and a member flies a sortie per day, so the verdict will almost certainly move to NO-GO. The finding says the DECISIONS row must state the new demo number: it is not available until the demo is re-run (`vehicles.uas.profile` and `modes.profile_incomplete` give it).

DECISIONS row: `| ? | UAS sorties are judged on the profile they deliver: new failure mode profile_incomplete, set for a flown sortie whose waypoints reached / waypoints in the pattern is below sortie.min_profile_fraction (1.0, assumed), first at the end of the sortie; fly_sortie returns wp_done and n_wp; Stage 1 summary vehicles[uas].profile = {wp_done_median, n_wp, complete_share}. time_limit_factor stays 1.0. In a uniform 10 m wind (log profile) the 20 min pattern is flown completely up to 5.0 m/s, 7 of 8 waypoints for 5.5 to 6.5, 6 at 7.0, 5 from 7.5 to 9 | Review round 4, M-1. The return-to-ship timer (1200 s) is a designed failsafe, but its truncation of the flux profile was invisible and counted as a pass; the demo's UAS GO described a profile that was not delivered. The demo's new UAS number: (lead: fill in after the re-run). |`

CHANGELOG (Fixed): `- A UAS sortie that the return-to-ship timer or the battery turns back before its last waypoint is now a failure (new mode profile_incomplete, sortie.min_profile_fraction 1.0, assumed); fly_sortie returns wp_done and n_wp and the Stage 1 summary has vehicles[uas].profile (median waypoints flown, pattern length, share of sorties complete). In a 5.5 to 6.5 m/s wind the demo's pattern ends at 7 of 8 waypoints. (M-1)`

PHYSICS.md (UAS sortie section, after the paragraph that describes the timer): `The sortie ends its pattern early when the airborne time exceeds duration_s x time_limit_factor (the return-to-ship failsafe, 1200 s) or the state of charge falls below the reserve. Every flown sortie reports the waypoints it reached (wp_done) of the pattern (n_wp = 2 x levels, 8 in the demo); below sortie.min_profile_fraction (1.0, assumed) the member records profile_incomplete at the end of the sortie. The nominal pattern takes 1127 s of flight, so a 1200 s timer leaves 6 % slack: in a uniform wind the pattern is complete up to about 5.2 m/s (10 m value, log profile) and ends at 7 of 8 waypoints from 5.5 to 6.5 m/s, 6 at 7 and 5 from 7.5 to 9 m/s (probe, one member per wind, no turbulence). The UAS verdict therefore rests on the battery and on finishing the profile inside the time limit.` Also the docs sentence at report.py:54 (`UAS_ATTITUDE_NOTE`) is batch R's.

QUESTIONS_FOR_LAB: `How long may a UAS sortie take, and what is the shortest acceptable flux profile (how many of the stacked levels must be flown)? They set sortie.time_limit_factor and sortie.min_profile_fraction, both assumed.`

---------------------------------------------------------------------------------------------------------------------------------

## M-5 non-finite current crashes the USV step

What changed
- `cafe/pm/physics/usv.py:91` `FAILS` gains `no_current_data`. `usv.py:527-529` in `USVSim.step`: `bw, bc = ~isfinite(wind).all(-1), ~isfinite(cur).all(-1)`; the non-finite vector (wind and current separately) is replaced by zero for the step and `no_current_data` is flagged (first time = the step time) for `bw | bc`. Module docstring updated. Hs NaN in the USV is not touched (see M-10 note below: the finding sends it to A-5's rule, which is stage 1's UAS/RF Hs only).
- Stage 1 needed no code: `fail`/`first` are built from `sim.fail`, so the mode appears in `modes` and `summarize`. `report.py` has no mode list for the USV (it prints whatever is in `modes`), so nothing is needed there.
- Wind and current both go through the same rule and the same mode name (the interface fixed `no_current_data`); a NaN wind vector is therefore also labelled `no_current_data`. The docstring says so.

Tests (all fail before with `IndexError: index -9223372036854775808`):
- `tests/test_usv.py::test_a_non_finite_current_is_a_labelled_failure_for_that_member_and_the_run_goes_on` (one member of four has a NaN current: only it fails, first at t = 0; the other three have the identical track and the identical other modes as a clean run; the holed member's track equals a zero-current run's)
- `::test_a_current_that_is_nan_everywhere_fails_every_member_the_way_the_gliders_no_flight_does` (the reviewer's edge9 case; same track and other modes as a zero-current run)
- `::test_a_non_finite_wind_vector_is_the_same_labelled_failure`
- `tests/test_stage1.py::test_a_nan_current_is_a_labelled_failure_through_run_batch_and_the_summary` (real USV through `run_batch` on `AnalyticEnv(current=(nan, 0))`; `summarize` gives `modes.no_current_data == 2`)

DECISIONS row: `| ? | USVSim.step replaces a non-finite wind or current vector by zero for that step and records the new failure mode no_current_data (first at the step time), so a land block or masked cell in the ocean store fails the member as the glider's no_flight does and no longer raises IndexError out of the table lookup | Review round 4, M-5. np.floor(NaN).astype(int) is the most negative int64; a cell with every corner NaN (the 0.08 degree land mask) killed Stage 1. Whether the GOFS store has such a cell inside the demo box was not checked. |`

CHANGELOG: `- A non-finite current (or wind) at a USV no longer raises IndexError and ends Stage 1: the member fails with the new mode no_current_data. (M-5)`

---------------------------------------------------------------------------------------------------------------------------------

## M-7 part (1): Stage 1 stores the speed through the water

- `stage1.py:133` `_run_usv` returns `stw_ms` = per-member mean of the simulator's recorded `h["stw"]` (NaN for a run too short for a step). `merge` carries it (`stage1.py:573`). `_speed` (`stage1.py:717`) adds `speed.stw_ms` (list) and `speed.stw_ms_median` beside `sog_ms_median`; both are left out when the result has no `stw_ms` (an older run). Parts (2) and (3) of the finding (reach map, glider band) are batch R's.
- Tests: `tests/test_stage1.py::test_usv_speed_over_ground_and_wind_along_the_track_are_stored_per_member_and_summarised` (extended: a fake history with a time-varying stw gives member means 0.7 and 1.3; `stw_ms_median` 1.0 differs from `sog_ms_median` 0.75; the same result without `stw_ms` summarises without the keys), `::test_stage1_keeps_the_speed_through_the_water_of_a_real_usv_run` (real USV, no current: stw_ms equals sog_ms within 8 %), and the existing short-run test now also asserts `stw_ms` is NaN. All fail before (KeyError `stw_ms`).
- `FakeSim.run` in tests/test_stage1.py now returns a `stw` array (the real simulator always does).

DECISIONS row: `| ? | Stage 1 stores stw_ms for each USV member (mean over the run of the recorded speed through the water) and the speed summary gets stw_ms_median beside sog_ms_median; speed over ground is unchanged and stays the speed block, ratio line and calibration number | Review round 4, M-7 (1). The reach map must hand the router the speed through the water (the router adds the current); the demo's 0.72 m/s through the water is not the 0.66 m/s over ground that was printed. The report side is batch R. |`

CHANGELOG: `- Stage 1 keeps each USV member's mean speed through the water (stw_ms) and the summary lists its median next to the speed over ground, for the reach map to use. (M-7)`

---------------------------------------------------------------------------------------------------------------------------------

## M-8 two-ray RF over a curved earth (status: partly; revised after the lead's decision)

The finding's direction was wrong: with the divergence factor D (which the fix asks for) the flat model was pessimistic beyond 10 km, not optimistic. Lead decision: keep D; where geometric optics fails, between a validity limit and the horizon, use the larger loss of the curved model with D and the flat model. Implemented as follows (`cafe/pm/physics/comms.py`):
- `A_EFF`, `FLAT_A` (1e12 m, a plane earth), `kerr_reflection` (Kerr cubic, trigonometric form), `divergence_factor` (two principal planes of the sphere, in (0, 1]).
- `two_ray_curved_db(d, ht, hr, hs, f, divergence=True, a_eff=A_EFF)`: the geometric-optics loss (tangent-plane heights, grazing angle, Ament x D). `divergence=False` is kept because tests use it (the reviewer's table).
- `psi_critical(lam, a)` = (lam / (pi a))^(1/3), 2.31 mrad at 915 MHz. **ASSUMED**: the end of the interference region, recalled from Kerr / Blake, not re-read; the docstring says so and names the replacement (re-read value, or ITU-R P.526 diffraction). No citation I can give.
- `two_ray_loss_db(d, ht, hr, hs, f, a_eff=A_EFF)`: inside the limit (grazing angle >= psi_critical) the curved loss with D; from the limit to the radio horizon `max(curved with D, flat)`; beyond the horizon the curved loss, unchanged. Carries the `# ponytail:` note (no smooth-earth diffraction, ITU-R P.526 is the upgrade path; flat stands in and is conservative by construction). The d^-4 receipt calls it with `a_eff=FLAT_A` (claim string unchanged).
- `stage1.py` method string for RF: "two-ray over a 4/3-radius earth with divergence (Kerr), <radio> (Ament sea roughness, modelled)" (unchanged by this decision; it does not mention the transition rule, batch R/G may add "flat loss near the horizon").

Numbers (15 m / 3 m masts, 915 MHz, Hs 0, horizon 23.09 km): the limit is at 6.94 km. Loss in dB, flat / curved D=1 (reviewer) / curved with D / new rule: 5 km 114.9 / 115.7 / 115.7 / 115.7; 10 km 126.9 / 130.2 / 127.7 / 127.7; 15 km 134.0 / 142.7 / 125.8 / 134.0; 20 km 139.0 / 161.9 / 122.4 / 139.0; 22 km 140.6 / 180.6 / 120.9 / 140.6. (Between 6.9 and ~11 km the curved loss can still be 0.8 dB above the flat one, so the rule keeps it; past about 11 km the flat loss is the larger.) **The reviewer's case `rf_margin(20e3, 15, 3, 0)`: 20 km is outside the validity limit (grazing angle 0.2 mrad against 2.3 mrad, limit at 6.9 km) and inside the horizon (23.09 km), so it gets the flat loss 139.0 dB and the margin is +13.0 dB** (+29.6 dB with the curved loss alone, never negative). No demo number changes: the only RF link, `usv-uas-rf`, is 89 % beyond the horizon; the UAS link is inside 2 km (0.12 dB).

One of the lead's test descriptions does not hold as worded: "the curved loss is between free space and flat inside the validity limit" is false in general (at 5 km curved is 0.8 dB above flat, and constructive maxima go below free space). I tested what is true: inside the limit the result equals the curved loss exactly; in the transition zone it equals max(curved, flat) and is >= both; it never goes below free space - 6.02 dB; beyond the horizon unchanged.

Tests (`tests/test_comms.py`; fail before, except the near-field guard)
- `test_the_kerr_specular_point_solves_the_cubic_and_obeys_the_law_of_reflection`, `test_the_two_ray_loss_without_divergence_is_the_kerr_curved_earth_table` (reviewer's six ranges to 0.5 dB with `two_ray_curved_db(divergence=False)`, flat table to 0.1 dB with `FLAT_A`), `test_the_divergence_factor_is_in_zero_one_and_falls_toward_the_horizon`, `test_within_2_km_the_curved_loss_is_the_flat_loss`
- `test_the_curved_loss_is_unchanged_above_the_critical_grazing_angle_and_the_larger_of_it_and_the_flat_loss_below_it` (the rule, on a 400-point grid, plus beyond-horizon and 2 km unchanged)
- `test_the_margin_never_rises_over_the_last_30_percent_of_the_horizon[...]` (5 mast pairs and sea states, 3000-point grid from 70 % to 99.99 % of the horizon, monotone non-increasing)
- `test_the_finding_case_20_km_is_in_the_transition_zone_and_gets_the_flat_loss` (asserts the +13.0 dB, with the reason)
- Existing tests: the two that I had loosened for the first version are back to their original form (`test_two_ray_beats_free_space_penalty_far_out_and_has_null`: +20 dB at 5 km holds again with the rule; `test_radio_horizon_and_rf_margin`: monotone for 1, 5, 14 km). Still changed: `test_loss_grows_with_range_past_last_null` (law asserted out to 40 % of the horizon, not 20 x the first range, which was beyond the horizon for tall masts), `test_the_two_ray_loss_gives_ament_the_grazing_angle_not_its_sine` (1e-9 -> 1e-3 dB at 20 m: the bulge), and the two receipt stand-ins accept the keyword.
- Runs (2 CPUs): `tests/test_comms.py tests/test_comms_exact.py` (includes the comms receipts and the tests that make each receipt fail) all passed, comms.py 100 % (220 statements); `ruff check` on both files clean; `mypy cafe/pm` has only the pipeline.py:663 error that is not mine.

DECISIONS row: `| ? | The two-ray RF loss is computed over a 4/3-radius earth (Kerr's specular point, tangent-plane heights for the path lengths and the grazing angle, the divergence factor D of the spherical surface on the reflected field, with the Ament factor). While the grazing angle at the specular point is above psi_c = (lambda / pi a)^(1/3) (2.3 mrad at 915 MHz, assumed: recalled, not re-read) that is the loss; from there to the 4/3-earth radio horizon the loss is the larger of it and the plane-earth loss; beyond the horizon the curved loss as before (no link). Inside 2 km it equals the plane-earth result to 0.15 dB; for 15 m / 3 m masts the limit is at 6.9 km of a 23.1 km horizon and rf_margin(20 km) is +13.0 dB | Review round 4, M-8, status partly. The finding's table (curved, D = 1: 9 to 40 dB more loss than flat) is reproduced to 0.1 dB, but with D, which its own fix requires, the sign reverses: the flat model was pessimistic beyond 10 km (curved with D falls toward free space, 120.9 dB at 22 km against 140.6 flat). Geometric optics fails just inside the horizon and diffraction (ITU-R P.526) is not modelled, so the flat loss stands in there: conservative by construction. No demo number changes. |`

CHANGELOG: `- The two-ray RF link model is now a 4/3-radius earth (Kerr's specular point, tangent-plane heights, divergence factor) up to a critical grazing angle (assumed) and the larger of that and the plane-earth loss from there to the radio horizon; no change within 2 km, so no demo number moves. (M-8, partly: the finding's direction was wrong)`

PHYSICS.md (RF section; replaces "two-ray + 4/3-earth horizon" wording): `Two-ray over a 4/3-radius earth (a = 8 495 km): the specular point is the root of the cubic 2x^3 - 3dx^2 + (d^2 - 2a(ht + hr))x + 2a ht d = 0 (Kerr 1951, trigonometric form), R1 = x from the ht antenna; the antennas' heights above the tangent plane there are h1 = ht - R1^2/2a and h2 = hr - R2^2/2a; the direct and reflected path lengths are hypot(d, h1 - h2) and hypot(d, h1 + h2); the reflected field carries the reflection coefficient -1, the Ament roughness factor and the divergence factor of the spherical surface D = [1 + 2 R1 R2/(a d sin psi)]^-1/2 [1 + 2 R1 R2 sin psi/(a d)]^-1/2 (Kerr 1951; Blake 1980 ch. 5). Within 2 km it is the plane-earth result (0.15 dB). D falls to 0 with the grazing angle psi, so toward the horizon the reflected ray fades out and the curved loss tends to free space. Geometric optics is not trusted below psi_c = (lambda / pi a)^(1/3) (2.3 mrad at 915 MHz; ASSUMED, recalled from Kerr / Blake, not re-read): from there to the radio horizon the loss is the larger of the curved loss and the plane-earth loss, which is conservative; beyond the horizon rf_margin reports no link. No smooth-earth diffraction (ITU-R P.526) is modelled in that zone. Limits as before: specular only, antenna motion only through the roughness factor. The d^-4 receipt is the plane-earth law (a_eff = 1e12 m).` References: `Kerr, D.E. (ed.), Propagation of Short Radio Waves, MIT Rad. Lab. Series 13, 1951, ch. 2; Blake, L.V., Radar Range-Performance Analysis, 1980, ch. 5; ITU-R P.526 (named as the upgrade path).` Credibility: psi_c is an assumed number in code (not in a yaml), so it is not in the assumed-inputs table; batch G may want to list it.

---------------------------------------------------------------------------------------------------------------------------------

## M-10 UAS lost_link latch and NaN Hs

Note on the finding: it says the latch is on "one 50 ms sample". The link hook is called once per record interval, `rec_dt` = 1 s (every 20 blocks), not per 50 ms block. The hold is therefore 5 consecutive 1 s samples. The fix and its numbers are otherwise as written.

What changed
- `uas.py:473-509` `simulate(..., link_hold_s)`: per member, the length of the current run of consecutive lost samples (seconds = samples x the record interval) and the time its first sample was taken; `f_link` is set when the run reaches `link_hold_s`, `t_link` is the start of the run; a gap resets it. `fly_sortie` passes `P["radio"]["link_loss_hold_s"]`. Default 0 in `simulate` keeps the old behaviour for the receipts.
- `platforms/quad_uas.yaml:131` `radio.link_loss_hold_s` 5.0 s, assumed, why as the finding words it (ArduCopter FS_GCS_TIMEOUT 5 s, recalled not re-read), `replace_with` key. (`_uas_radio` still finds the RF block: it looks for a dict with `tx_power_dbm`.)
- `stage1.py:212` `fill_hs(hs, lon, lat, what)`: non-finite Hs -> the same member's last finite value along time, else the next (forward then backward fill), returns the count; a member with none raises `OutsideData` naming member and position. Used in `_uas_links` (replaces `nan_to_num`, `stage1.py:255`) and in `evaluate_link` for RF links (replaces `nan_to_num`; positions that are unknown (non-finite lon/lat) are set to 0 first, as before, since no link is required there). Counts go into `vehicles[uas].hs_filled` and `links[<rf link>].hs_filled` (summed by `merge`), and `stage1.run` writes one ledger note: "<n> non-finite wave-height samples (UMWM sea mask) on the UAS and RF link tracks were replaced by the same member's last finite Hs (next one at the start); Hs 0 would be a glass-calm sea, the deepest two-ray null". `OutsideData` is imported from `env.environment`.

Tests (fail before)
- `tests/test_uas.py::test_a_one_sample_fade_is_ridden_through_and_a_long_one_sets_lost_link_at_the_start_of_the_run` (one lost sample: no flag; 4 s: none; 6 s: flag with `t_first` = 20.0 s, the start of the run; 3 s + break + 3 s: none; hold 0 gives the old behaviour), `::test_the_hold_counts_each_member_on_its_own_run` (before: `[True, True]` where `[True, False]` is right)
- `tests/test_stage1.py::test_fill_hs_takes_the_last_finite_value_of_the_member_then_the_next_and_counts`, `::test_the_uas_link_reads_the_neighbouring_hs_where_the_sea_mask_gave_nan_and_counts_the_samples` (the hook's Hs is 2.0 where it was 0 before; an all-NaN sea raises `OutsideData`), `::test_the_rf_link_fills_a_masked_hs_from_the_members_neighbouring_record_and_counts_them` (the margin equals that of a clear 2 m sea and differs from a calm one by more than 0.1 dB), `::test_run_writes_the_filled_hs_samples_into_the_ledger`.
- I did not run the reviewer's `edge4` probe (CI mission, 8 members, lost_link 5 of 8 at Hs 0.0). The cheap unit tests above show the latch and the fill; the Hs-0 case for the real two-ray null is not re-run.

DECISIONS row: `| ? | lost_link needs radio.link_loss_hold_s (5 s, assumed) of consecutive lost link samples (the link is judged once per second); the member's lost_link time is where that run began; a non-finite Hs on a UAS or RF link track is the same member's last finite Hs (then the next one), counted in the ledger, and a member with no finite Hs at all stops the run with OutsideData naming its position (was nan_to_num: Hs 0) | Review round 4, M-10. ArduCopter's GCS failsafe waits FS_GCS_TIMEOUT (5 s, recalled not re-read) before acting; one lost sample of a smooth-sea two-ray null (5 of 8 members at Hs 0, 2 at 0.2, none at 0.4 or more in the reviewer's probe) is a fade, not a lost link. A masked Hs is not a calm sea: 0 is the deepest null. |`

CHANGELOG: `- A UAS now loses its link only after 5 s of consecutive lost samples (radio.link_loss_hold_s, assumed), not at one sample of a two-ray null; a non-finite wave height on a UAS or RF link track takes the member's neighbouring Hs instead of 0 (counted in the ledger; none at all raises OutsideData). (M-10)`

QUESTIONS_FOR_LAB: `What is the radio failsafe timeout of the UAS (how long may the telemetry link be down before the aircraft returns)? radio.link_loss_hold_s is 5 s, assumed from ArduCopter's default.`

---------------------------------------------------------------------------------------------------------------------------------

## M-11 Iridium link to a glider (stage-1 part)

- `stage1.py:481` `_surfaced(out, a, b, t)` (the glider end's surfaced flag interpolated onto `t`; the old inline code, shared) and `evaluate_link`: an Iridium link with `when: surfacing` takes `need = live & surfaced(glider end)`; `always` is as before. Docstring says so.
- Tests: `tests/test_stage1.py::test_an_iridium_link_to_a_glider_is_required_only_while_the_glider_is_surfaced` (glider surfaced in 2 of 217 records: `need_count` [2, 2, 2] with `when: surfacing` (217 before), 0 and fraction 1.0 for a glider that never surfaces, 217 with `always`, either end order).
- Config refusal (rf or iridium link with a glider end unless `when: surfacing`, and accepting `surfacing` for Iridium) is batch C's.

DECISIONS row (to be merged with batch C's): `| ? | Stage 1 evaluates an Iridium link with when: surfacing as live and the glider end surfaced (amends 155: Iridium when was always only) | Review round 4, M-11. An Iridium (or RF) antenna on a glider works at the surface only; Iridium took every record as required, so a glider that never surfaced passed. |`

CHANGELOG: `- An Iridium link to a glider with when: surfacing is required only while the glider is on the surface. (M-11)`

---------------------------------------------------------------------------------------------------------------------------------

## Needs from other batches / cross-impact

- Batch R (report.py): read `res["vehicles"][uas].profile` and `modes["profile_incomplete"]` (keys absent in older runs), `speed.stw_ms_median` / `speed.stw_ms` (absent in older runs). The UAS result also carries `n_wp` and `hs_filled` (vehicle) and `hs_filled` (RF link results); the stage-1 `run()` ledger note is written by stage1. The mode name `no_current_data` is the USV's; the report prints whatever is in `modes`.
- Batch C (config): the refusal in M-11 as described in the common interface; nothing else from me.
- Batch G (docs): two more assumed inputs in `platforms/quad_uas.yaml` (`sortie.min_profile_fraction`, `radio.link_loss_hold_s`), counted automatically by `credibility.assumed_inputs`; update any hard-coded count in the docs. PHYSICS and QUESTIONS text above. docs/PHYSICS.md line 801 quotes the receipt claim "Two-ray far field: loss rise per decade of range": unchanged string.
- Stats batch (M-18, `cafe/pm/stats/intervals.py`): its new verdict note no longer contains "73 members" ("The report's certification count, 73, is for ..."), which two assertions in my `tests/test_stage1.py` (lines 844 and 927) expected. I changed them to `"73" in note`. If that wording is changed again those two lines are the only ones to look at.
- `mypy cafe/pm` currently reports one error that is not mine: `cafe/pm/pipeline.py:663: Call to untyped function (unknown) in typed context`. `ruff check cafe/pm tests` has 18 E501/B018 errors, all in files I do not own (credibility, emulator, pipeline, report and tests for pipeline, bench, budget, ledger, receipts, report); none in my files.
- One flaky test seen once, not related to my change: `tests/test_uas.py::test_an_autopilot_that_never_arms_is_reported_and_fails_the_sitl_receipts` failed in one run ("no MAVLink heartbeat ... Connection refused": a fake SITL listening on a localhost port) and passed in every later run.

## Commands run (all through pmx.sh on homebase, PMX=pm_r4v, 2 CPUs, 8 GB)

- Before/after: from `scratchpad/oldtree` (HEAD source for the five source files + the new tests), the 24 node ids in `scratchpad/v_ids.txt`: **22 failed, 2 passed** as intended (the two that pass are the guards `test_within_2_km_the_curved_loss_is_the_flat_loss` and `test_an_older_uas_result_without_wp_done_has_no_profile_block`; the extended existing `test_usv_speed_over_ground...` failed too, on `stw_ms`). Reasons seen: KeyError n_wp / wp_done / link_loss_hold_s / stw_ms / hs_filled, `IndexError: index -9223372036854775808 ...` in the three USV NaN tests and the run_batch one, `AttributeError: ... A_EFF / kerr_reflection / fill_hs`, `TypeError ... divergence`, `[217, 217, 217] == [2, 2, 2]` for Iridium, `[True, True] == [True, False]` for the per-member hold.
- After: `python -m pytest -q -p no:cacheprovider tests/test_comms.py tests/test_comms_exact.py tests/test_usv.py tests/test_uas.py tests/test_stage1.py` (+ coverage run below): all passed (the coverage run below executed the same files in two invocations: uas, usv, comms, comms_exact together; stage1 alone; both rc=0).
- Coverage (`--cov=cafe.pm.physics.uas --cov=cafe.pm.physics.usv --cov=cafe.pm.physics.comms`, those four test files): comms 100 % (210 statements), uas 100 % (685), usv 100 % (465). `--cov=cafe.pm.stage1` with `tests/test_stage1.py`: 100 % (561).
- `tests/test_credibility.py tests/test_config.py`: 153 passed (the new assumed inputs do not break them).
- `ruff check cafe/pm tests`: none of the errors are in the files I touched. `mypy cafe/pm`: clean for my files (1 error in pipeline.py, not mine).
- Not run: the full suite, the mutation tests, tests/test_report.py / test_pipeline.py (other batches' files, which read `stage1.summarize` output).
