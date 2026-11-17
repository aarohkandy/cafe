# Round 17, reviewer C (output correctness)

Scope: every verdict, number, interval, warning, map element and table in q17's `report/index.html`, `report.json` and `credibility.html`, recomputed from the run's arrays (`q17_mission.json`) and ledgers, with the round 16 texts in particular (scrubbed launches, the USV lowest state of charge, the glider surfaced share, the Iridium sentence, the hull notes, L19 to L22), and `whatif` after M-1 checked on orca against real Stage-1 reruns with the base draws.

## What was recomputed and agrees (no finding)

- All 8 verdict rows: k_fail from the per-member `fail` arrays (15, 0, 61, 62; links 64, 64, 64, 0), every mode count (glider_eq 15; USV becalmed 18, swept 50, wing_stall_calm 40, wing_stall_angle 15; UAS battery_reserve 13, profile_incomplete 62), both Wilson intervals (90 % and the 95 % stopping interval) to 10 digits, `n_certify` 73 and the rule-of-three 0.04688, first and median failure times (from `first` arrays) and every `failed_at` list of the stage-3 windows (15, 0, 61, 62 entries, equal to the sorted per-member first failures), the mode shares, `decided`/`region` of glider_eq (0.1475 to 0.3513 sits inside 0.1 to 0.4).
- The USV minimum state of charge (median 0.7356, p10 0.7307, lowest 0.7254, 0 empty) from `energy_margin`; the USV speed sentence (sog 0.6867, 10 m wind 5.41, ratios 0.1339 / 0.1408, stw 0.7571, Chiodi 0.1778); the UAS scrub sentence (384 launches, 3 scrubbed, members 22, 28, 60, 0 with all scrubbed, from the `sorties[].scrubbed` arrays); the UAS profile and authority numbers (complete share 0.52756, wp median 8 of 8, clamp 9.65 s / 21.8 s, demand ratio 1.785 / 2.087, wind3d 0.6281 from [353421, 562720]); the link numbers (need counts 249.5 / 18.5 / 71 / 865, one missed sample 0.004008 / 0.05405 / 0.01408 / 0.001156, fractions beyond horizon 0.8878 pooled, medians, distances 80.14 / 554.70 / 632.45 km, margin median 15.16 dB).
- The USV `tp_bias` S1 0.299 against the floor 0.2022 and the glider_eq (0.1061, 0.1909) and UAS (0.177, 0.2138) cases, with `cafe/pm/stats/sensitivity.py` on `X` and the margins (identical to 4 digits); "1 of 3 tests, 14 % chance" is 1 - 0.95^3.
- The fix tables: every candidate count (18 / 14 + 4, 16 / 10 + 6, 12 / 10 + 2), the Wilson intervals of the evaluated rows, the "flies 5.75 d" texts, the move-outside-box refusals (the box edge is at 165 W).
- The TAO comparison (14 moorings: pooled speed RMSE 1.669, bias 0.469, direction bias -6.24, RMSE 27.06; the prior mean -0.45997 is minus the unweighted mean; value 0.5689 and hi95 0.9572 reproduce from `fit_wind_error`'s formulas with 13 dof), the V&V 20 table (E = S - D, U_val, the U_val / D ratios 0.468, 0.27, 0.63, 0.30), the credibility counts (274 used of 289; 100 + 13 + 3 + 43 + 9 + 59 + 21 + 26; 69 + 165 = 234 platform inputs; 60 test files; 8 of 9 ledgers; 21 ingest checks), the stage wall times (sum 596.2 s, 0.4969 of the budget), the 6 x 26.34 s planned emulator cost, the SVG map's scale (23.783 px/deg both ways) and every deploy, ship and window mark, and the map member tracks against the arrays (fail flags of the five shown members per vehicle agree).
- The glider surfaced share at full resolution on orca (`res.pkl`, 865 records): 0.021460 and 0.082623, as printed (the 30-min extract gives 0.0245 and 0.0837 only because it keeps every third record).
- M-1 on orca (`PMX=pm_rev17_c PM_CPUS=2`, script `/data/rev17_c_wi3.py` and two earlier ones, all removed at the end): `run_batch` of the solo mission with the full mission's priors for members 0 to 31 reproduces `res.pkl` exactly for glider_eq (5), usv (29) and uas (31): the fix holds at the base. A move or shift through `whatif.measure` reproduces the fix table's n = 32 rows (glider_eq deploy 6 h later 4 of 32, as printed).

## Findings

### C-1. The what-if and the fix table compare a 32-member candidate with the 64-member baseline, so the printed change is not the change on the shared members
severity: minor
lane: statistics, honesty
where: cafe/pm/whatif.py:733-747 (`measure`, one batch of 32), :914-922 (`_stage1`); cafe/pm/__main__.py:344-346 (prints `r['base']['p_fail']` -> `r['p_fail']`); cafe/pm/report.py:1348 (`SAME_AS_BASELINE`) and the fix table; docs/RUNBOOK.md:175 ("draws the members of the full run, so it is the answer of a rerun of the changed mission")
reproduction: q17 `emulator/flip.json` has the candidates at n = 32: glider_eq "deploy 6 h later" 0.125 (4 of 32), usv "deploy 6 h later" 0.90625 (29 of 32), uas 31 of 32 for two candidates. The baseline printed beside them is the 64-member 0.234375, 0.953125, 0.96875. M-1 makes the candidate's members 0 to 31 the base run's members 0 to 31, and the base's own failures in those 32 are (from `q17_mission.json` `fail`, and confirmed by `run_batch` against `res.pkl` on orca) glider_eq 5 of 32 (0.156), usv 29 of 32 (0.906), uas 31 of 32 (0.969). So on the shared members "deploy 6 h later" is -1 member for glider_eq (printed change 0.2344 -> 0.125 = -0.109; same-member change -0.031) and exactly 0 for the USV (printed 0.9531 -> 0.9062 = -0.047; same-member 0.000). Row 885 (M-2) did this for the UAS ("the unchanged mission measured as the candidate is, same members", `answer()` :893-896) and said why; the other classes were left with the 64-member base. The only guard is the sentence "not distinguishable from the baseline (its interval contains the baseline's P(fail))", which is right but hides that the candidate and the baseline share their draws and so differ by one member or none.
why it matters: a reader of the fix table reads a 4 to 11 point improvement for a change that moves one member or none; with a larger effect the sign and size of the printed difference still carry the sample-size gap.
wrong data: yes, the "P(fail) now X -> Y" lines of `cafe pm whatif` and the P(fail) / baseline pair of every n = 32 row of the fix table (glider_eq, usv) overstate the effect of the change by the gap between the 64-member and the first-32-member baseline.

### C-2. The credibility page lists platform defaults as the assumed inputs "used by this mission" for five inputs the mission overrides
severity: minor
lane: documentation, honesty
where: cafe/pm/credibility.py:642-651 (`item_used`: "a vehicle's platform file is read whole"), :1093-1094; platforms/quad_uas.yaml (`sortie.levels_m`, `launch_rule.gust_lookahead_min`, `radio.ship_antenna_height_m`), platforms/seaglider.yaml (`mission_defaults.lost_hours`, `mission_defaults.dive_depth_m`); missions/tepex_c_demo.yaml
reproduction: `credibility.json` of q17 `assumed_inputs`: `quad_uas.yaml:sortie.levels_m` value `[10.0, 25.0, 50.0, 80.0]`, `used: true`; the mission flies `altitudes_m: [10, 30, 60, 100]` (the report's own sentence says 10, 30, 60, 100, and `stage1._uas_setup` :338 applies it). `quad_uas.yaml:launch_rule.gust_lookahead_min` 15 min, used: true; the mission's `launch_rules.no_gust_front_within_min: 30` replaces it (:337 `rename`). `quad_uas.yaml:radio.ship_antenna_height_m` 10 m, used: true; the mission's `ship.antenna_height_m: 15.0` is what the RF link uses (`stage1.py:295-297`, "the mission's, else the platform's"). `seaglider.yaml:mission_defaults.lost_hours` 6 h, used: true; the mission orders `lost_after_h: 12.0` (`stage1.py:117`). `mission_defaults.dive_depth_m` 500 m; the mission orders 950 (this one's own `why` says the mission overrides it, the others say nothing). The page counts all of them in "Depends on 43 inputs" (UAS) and "21 inputs" (glider_eq) and in the 274 "used by this mission, verdicts depend on them".
why it matters: the lab is told which numbers to replace (`replace_with`) and what value the verdicts rest on; for these five the value shown is not the one in the run, and replacing it changes nothing.
wrong data: yes, the "All assumed inputs" table rows (value and "used") for those five inputs, and the per-vehicle "Depends on N inputs" and 274 / 289 counts.

### C-3. "of the window": the glider surfaced share is a mean over the whole 6-day run, printed as a share of the stage-3 window
severity: minor
lane: documentation
where: cafe/pm/report.py:1677-1678 (text) against :915-922 and DECISIONS 890 ("the mean `surfaced` of the run")
reproduction: the paragraph sits under "surface current speed at the worst windows" (a window is one record of the strongest forcing, e.g. glider_eq 2023-03-05 09:00Z) and says "A glider sees this surface current only while it is at the surface, 0.02146 of the window (mean over members)". The number is `np.mean` over all 865 records and all 64 members (`source`: "mean over records and members"): 0.021460 = about 18.5 surfacings of one 10-min record each over 865 (checked on orca from `res.pkl`).
why it matters: the sentence means to say how little of the time the surface current is seen; "of the window" reads as the share of the window instant, which is a different quantity (the share at a given hour can be 0 or 1 for a given member).
wrong data: yes, a misleading label on the printed share (0.02146, 0.08262): it is of the run, not of the window.

### C-4. The UAS levels note says the turbulence box is taken at the leg heights; L20 and the code say one height for all legs
severity: minor
lane: documentation
where: cafe/pm/report.py:519-520 (`_uas_levels_note`: "the wind, the radio antenna height and the turbulence box are taken there"); cafe/pm/stage1.py:213 (`z = deck_height + mean(levels_m)`), credibility L20
reproduction: q17 report, UAS card: "the legs are flown at 18, 38, 68, 108 m above the sea; the wind, the radio antenna height and the turbulence box are taken there." `_uas_forcing` builds one Mann box per sortie at 8 + mean(10, 30, 60, 100) = 58 m for every leg, which L20 on the credibility page of the same run says.
why it matters: two pages of one report disagree about whether the turbulence follows the leg altitude.
wrong data: no (text contradiction; the box height is stated correctly in L20).

### C-5. The UAS sensitivity names an inert column as the largest index and inflates the floor with it
severity: minor
lane: statistics
where: cafe/pm/stage1.py:45-46 and :738-770 (`acting` = FORCING + the class's columns)
reproduction: for the UAS, `current_speed_scale` and `current_direction_bias` are in the acting set, but the UAS vehicle reads no current (its flight reads the wind and, through its link, Hs: `stage1._run_uas`, `physics/uas.py` has no ocean read). On `profile_margin` (q17 arrays, the report's own estimator): with the 8 columns the floor is 0.2138 and the largest index is `current_direction_bias` 0.177 (printed: "largest S1 0.177, current_direction_bias; floor 0.214"); with the 4 columns that can act (wind speed and direction, bulk stress, battery) the floor is 0.1842 and the largest is `wind_speed_bias` 0.121. The finding "nothing clears the floor" is the same either way.
why it matters: the card names a parameter the aircraft cannot feel as the leading candidate and the floor is set by eight columns when four could act; the next mission whose live columns do clear a floor that is too high will read "cannot rank".
wrong data: no (the text says the sample cannot rank them), but the named parameter is inert.

### C-6. `review/round_17/q17_vs_q16.md` says 15 moorings; the fit used 14
severity: minor
lane: documentation
where: review/round_17/q17_vs_q16.md ("wind speed bias mean -0.45997, sd 0.56886, hi95 0.95721; 15 moorings")
reproduction: `ingest/tao_compare.json` has 15 keys, one of which is `ALL` (the pooled row); `priors_fitted.json` citation: "minus the unweighted mean of the 14 moorings' time-mean errors" and the report's L19 and Data-pedigree texts say 14.
why it matters: the note counts the pooled row as a mooring; the report is right.
wrong data: no (a review document, not an output of the run).

## Not checked, or checked only in part

- The environment series, Hs and current values along the tracks, the reach polygons and the "farthest reachable cell" distances (they need the environment zarr stores, which are not in the local copy); only their internal consistency was read (24 values per series; reach speed 0.7571 equals the median `stw_ms`).
- The 3-D-wind share and the emulator, holdout and flip numbers beyond the arithmetic above (the emulator is not trained in this run).
- `whatif --drop` and `--vehicle` after M-1: `answer()` with `--drop usv` correctly returns no vehicle row and names the two links removed (`usv-uas-rf`, `usv-shore-iridium`); `--move 0.5deg W --vehicle glider_eq` returns 0.34375 (22 of 64, 0.254 to 0.446, MARGINAL, n = 64) against base 0.2344. Real reruns on orca of the changed mission with the base draws: the solo path equals the full-mission path for members 0 to 31 (see the line at the end of this file; the 64-member rerun was not made). The USV and UAS moves were not rerun beyond the base (the base reproduces exactly), the USV "deploy 6 h later" count (29 of 32) was the only USV change run.
- ITU-R P.526 diffraction and the RF margins (reviewer B's); the 12 m/s USV figures; the stage-3 estimates (94 min) beyond the arithmetic 279,060 cells x 2000 / 153e3 x 1.5 + mesh = 94 min, x 1.25 = 118 min.
- `credibility.html` rendering at other widths (P-R14V3 is known).

## Real rerun, final line

`stage1.run_batch` of the whole changed mission (all four vehicles, links, `--move 0.5deg W` of glider_eq, the full mission's priors, members 0 to 31): glider_eq 14 of 32 failed; `whatif.measure` (solo mission, full priors) gave 14 of 32; the CLI's `answer()` over the plan's 64 members gave 22 of 64 (0.34375). The solo and the full-mission answers agree member for member in count; M-1 holds on this path in q17. Two other moves through `measure`: north 0.5 deg 26 of 32 (base first 32: 5), deploy 6 h later for the USV 29 of 32 (base first 32: 29).

total: 6 findings (0 critical, 0 major, 6 minor)
