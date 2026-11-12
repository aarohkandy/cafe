# Round 16, reviewer C: output correctness of q16 (report/index.html, report.json, credibility.html) and three what-ifs

Run: q16 (commit 9328932). Recomputed independently from `q16_mission.json`, `stage1b/summary.json`, `ingest/*.json` and the report files with a script of my own (numpy and the standard library, no repo code): k_fail and n of all 8 rows, the Wilson 90 % and 95 % intervals, the failure-mode counts and shares, first and median failure times (and the 18, 62 and 61 failure times printed under "worst windows"), the link fractions, medians, p10, beyond-horizon share (0.88996), distances, the EASI first-order indices and noise floors of glider_eq, usv and uas (2,000 permutations, seed 0), the UAS sortie statistics (7 of 8 waypoints, 0.4882, 9.45 s, 1.784, 2.17, wind3d 0.6254), the USV speed ratios (0.1359, 0.1300, SOG 0.6924, u10 5.423), the speed prior's width, the LHS draws against the stated priors (every column matches to 1e-4, 32 strata hit once per batch), the fitted wind priors' means (-0.45997, +6.3797) and pooled TAO statistics from `tao_compare.json`, the hi95 bound by the stated formula (0.957), the V&V 20 rows (E, U_val, ratios), the input counts (287 catalogued, 272 used, per-file counts summing to 272), the plan and timing arithmetic (158.1, 582.1, 0.4851), the map's SVG coordinates and median tracks, the hull collapse depth (1.3225 x 500 x 0.5 = 330.6 m) and the candidate counts. Everything above agrees with what the report prints, apart from the findings below.

What-ifs (orca, `PMX=pm_rev16_c*`, 2 CPUs, `python -m cafe.pm whatif --mission /data/runs/q16/mission.yaml --run /data/runs/q16`): `--shift 6h`, `--move 0.5degW`, `--drop uas`; each checked by a stage-1 rerun of the same change made by editing a copy of the mission file (`c_s1.py`, the whole 4-vehicle mission, members 0..63 in two batches of 32, the run's fitted priors, the seed of the mission; UAS also under the 10 m wind as the what-if does). Scratch files only in my worktree and under `/data/runs/rev16_c_t` on orca (removed at the end).

### C-1. `whatif` draws its Stage-1 answers from other Latin-hypercube columns than the base run, so a changed vehicle is compared with the baseline on different draws and the answer is not what a rerun of the changed mission gives (the sign of the effect can flip)
severity: major
lane: statistics
where: cafe/pm/whatif.py:904-911 (`_stage1` calls `stage1.run` on `solo(...)`), cafe/pm/stage1.py:938 (`run` takes `priors_for(mission, fitted)` of the one-vehicle mission), cafe/pm/stage1.py:62-75 (`priors_for` lists only the columns of the classes present), cafe/pm/stats/sampling.py:193 (`lhs_unit` draws all d permutations and the d-column jitter in one call, so a different d changes every column, the forcing ones too), cafe/pm/whatif.py:223-227 (`solo` docstring: "its result is the same"), cafe/pm/whatif.py:728-731 (`measure` docstring: "common random numbers", true only because the flip search hands it the full mission's `pri, marg`)
reproduction: on orca, `--move 0.5degW` prints `glider_eq: MARGINAL (P(fail) 0.281) -> MARGINAL (P(fail) 0.344) (0.254 to 0.446)  [Stage 1, n = 64]`, i.e. 22 of 64. The same change made in the mission file and run as the whole mission with the base run's draws (members 0..63, 10 columns) gives glider_eq 12 of 64 (0.1875, 90 % Wilson 0.121 to 0.280) against the baseline's 18 of 64: the effect has the other sign. `c_s3.py` isolates the cause: the west05 glider_eq alone with its own 8 columns gives 22 of 64 (per batch 14, 8: the CLI's number), with the full mission's 10 columns 12 of 64 (7, 5). The unchanged mission shows it too (`c_s2.py`, members 0..31): glider_eq alone with its own columns 7 failures, with the full mission's columns 10 (the report's own first 32 members have 10), 11 of the 32 members differ; usv 32 against 31. Same pattern for `--shift 6h`: glider_eq CLI 12 of 64 against the rerun's 14 of 64 (0.146 to 0.314, which contains the baseline 0.281 where the CLI's 0.121 to 0.280 stops 0.001 short of it); usv CLI 30 of 32 (0.938) against the rerun's 31 of 32 in members 0..31, which is also what `flip.json` holds for the same change (31 of 32); uas CLI 32 of 32 (1.000) against 31 of 32 in both the rerun (2-D wind) and `flip.json`. So for one change the report's candidate table (`flip.json`, which hands `measure` the full mission's draws) and the `whatif` command disagree for usv and uas, and neither prints that the other exists. `--move` on the usv (CLI 29 of 32, 0.906; rerun 59 of 64, 0.92) and the uas (32 of 32 both) agree within noise.
why it matters: the command exists to compare a change with the baseline; the baseline is the report's 18 of 64 on the full-mission draws and the answer is on other draws, so the difference carries the draw noise of two unpaired samples (sd of a difference about 0.08 at p = 0.25) and not the effect. RUNBOOK 5 says to compare the verdict, but the printed P(fail) and interval are what a user acts on, and for glider_eq the move west reads as worse (0.344) when the paired rerun reads better (0.1875).
wrong data: yes (what-if P(fail) and interval of every Stage-1-answered vehicle whose class set differs from the mission's; the fix is to pass the mission's `pri, marg` to `run_batch` as `measure` already does)

### C-2. The base report's own numbers depend on which other classes are in the mission; `--drop` says "Other vehicles are unaffected" while a rerun of the same mission without the UAS gives other counts
severity: minor
lane: reproducibility
where: cafe/pm/__main__.py:356-357 (the drop message), cafe/pm/stage1.py:62-75, cafe/pm/stats/sampling.py:193, cafe/pm/stats/sampling.py:241-243 (`member_seed`: "No vehicle in the key: that is the common random numbers")
reproduction: `--drop uas` prints `dropped uas; links removed: usv-uas-rf. Other vehicles are unaffected: Stage-1 vehicles do not interact.` and no P(fail), so the user keeps the report's glider_eq 18 of 64 (0.281) and usv 62 of 64. The mission file without the UAS and its link, run on the same seed and the same 64 members (`c_s1.py dropuas 64`, 9 columns instead of 10): glider_eq 13 of 64 (per batch 8, 5; the q16 run had 10, 8), 0.203 (90 % Wilson 0.133 to 0.297), usv 60 of 64 (0.9375), glider_2n 0 of 64. The vehicles' physics do not interact, but their draws do, so "the same seed gives the same member" holds only for the same class set.
why it matters: a lab user who drops the UAS and reruns the pipeline gets another P(fail) and interval for the glider than the report and the what-if print, with the same seed; the message promises "unaffected". Sampling noise at this n, not a physics error, but it contradicts the `member_seed` comment and the message.
wrong data: no (the verdicts here are unchanged: MARGINAL, NO-GO, GO); the sentence is wrong as a statement about the numbers

### C-3. The UAS what-if line compares a 3-D-wind baseline with a 10 m-profile candidate, against RUNBOOK 5's "for the candidate and the baseline alike"
severity: minor
lane: honesty
where: cafe/pm/whatif.py:884-897 (`answer`: `b = base.get(vid)` is the stage-1b verdict, 61 of 64 under the WRF 3-D field for 62.5 % of the records; the candidate is run inside `wind_2d`), cafe/pm/__main__.py:337-350 (prints `r['base']['p_fail']` with no wind-model note), docs/RUNBOOK.md:175; only the flip search computes the same-model baseline (`base_2d`, whatif.py:797-804)
reproduction: `--shift 6h` prints `uas: NO-GO (P(fail) 0.953) -> NO-GO (P(fail) 1.000) (0.922 to 1.000)  [Stage 1, n = 32 ...]`; `--move 0.5degW` the same pair. `emulator/flip.json` uas `base_2d` says the baseline under the same 10 m model is 0.96875 (31 of 32, 0.871 to 0.993), and the report prints it ("The baseline under the same model: NO-GO P(fail) 0.9688"). The CLI shows +0.047 for a shift that, against its own same-model baseline, is +0.031 (one member).
why it matters: the user is told in the RUNBOOK that the two sides use one wind model; the CLI shows 3-D on one side and 2-D on the other without a word, so a model effect is read as an effect of the change. The verdict (NO-GO) does not move here.
wrong data: yes (the UAS baseline P(fail) and the difference)

### C-4. Credibility limitation L19 states the wind prior as a boundary estimate of 0.113 m/s; this run fitted 0.5689 m/s from 14 moorings
severity: minor
lane: documentation
where: cafe/pm/credibility.py:70 (L19, printed on credibility.html "Known limitations")
reproduction: L19 reads "the persistent wind-speed prior is a boundary moment estimate ... in the evidence run q5 11 moorings over 6 days gave 0.113 m/s, with a 95 % upper bound of about 0.5 m/s". The same page's inputs and `priors_fitted.json` give 0.5689 m/s (interior: between-mooring sd 0.677, sampling variance 0.168 subtracted, 0.0327 added) and a bound of 0.9572 m/s; `fit_wind_error`'s docstring itself records 0.110/0.461 for 11 moorings and 0.569/0.957 for 14. The text is true of q5 and not of the run the page describes.
why it matters: a reader of the limitations list takes the prior as nearly zero and the bound as 0.5, when this ensemble drew 0.57 and the bound is 0.96.
wrong data: no

### C-5. "USV speed factor is sampled within +-1.4 % of the unbiased polar speed" reads as a speed near the polar's
severity: minor
lane: honesty
where: cafe/pm/credibility.py:167-175 (`usv_speed_sampling`; printed on credibility.html, factor "Uncertainty characterization", and in the USV section of index.html)
reproduction: `usv_vpp_bias` is uniform on [-0.2565, -0.228] (realised range -0.2563 to -0.2283 in `q16_mission.json`, mean -0.2422): the USV flies 23 to 26 % below the unbiased polar. The sentence gives only the half-width 0.0143 as "+-1.4 % of the unbiased polar speed", and "+-1.9 % of the speed flown"; the centre appears only in the assumed-inputs list.
why it matters: the sentence is about the spread, but a reader of "within 1.4 % of the polar" takes the USV to fly at the polar speed; the NO-GO verdict rests on the 24 % cut.
wrong data: no (wording)

### C-6. A required-sample median of 18.5 is printed as 18
severity: minor
lane: statistics
where: cafe/pm/stage1.py:807 (`nc = int(np.median(...))`), cafe/pm/report.py:683-690
reproduction: `np.median(need_count)` of glider_eq-ship-acoustic is 18.5 (members need 15 to 22 samples); the page prints "decided on 18 samples (the median number of required samples per member); one missed sample is 0.05556 of them".
why it matters: negligible here (granularity holds either way) but the statement is not the median, and `granularity_ok` is judged on the truncated value.
wrong data: no

### C-7. The report never says how many UAS launches were scrubbed, and a scrubbed day is not a failure
severity: minor
lane: honesty
where: cafe/pm/stage1.py:402-416 (`scrubbed` is kept in res.pkl, `no_sortie_flown` fires only when every launch is scrubbed), cafe/pm/report.py (no mention)
reproduction: `q16_mission.json` uas `scrubbed`: 3 of 384 launches (member 22 sortie 2, member 28 sortie 5, member 60 sortie 2; all three members fail anyway). The UAS section prints "share of the flown sorties that reached every waypoint 0.4882" (381 flown) and no scrub count; `grep -c scrub index.txt` is 0.
why it matters: a UAS GO would read as six delivered profiles when a member could pass with five scrubbed days and one clean sortie; the reader cannot see the count that would tell them.
wrong data: no (nothing in q16 changes)

### C-8. The glider fix table offers dives of 712.5 m and 475 m, both below the hull's collapse depth of 330.6 m that the same page warns about
severity: minor
lane: honesty
where: cafe/pm/whatif.py (`candidates`, the "dive N % shallower" rows), cafe/pm/report.py (hull_warning only in the vehicle's header)
reproduction: index.html glider_eq: hull warning "ordered dive depth (950 m) is deeper than the collapse depth ... (330.6 m)"; the candidate rows "dive 25 % shallower (950 m to 712.5 m)" and "dive 50 % shallower (950 m to 475 m)" carry no note. None was evaluated in q16, but a candidate that reached GO would be offered as the fix for a hull the report says cannot fly it.
why it matters: the fix is advised for a vehicle that the model's own hull rule fails; the user could read "dive to 475 m" as safe.
wrong data: no (no candidate was answered in q16)

### C-9. The V&V 20 summary counts judged and not-judged rows on different bases
severity: minor
lane: documentation
where: cafe/pm/credibility.py:752-753
reproduction: credibility.html Validation: "4 comparison(s) ran, 4 with all uncertainty terms, 1 with |E| <= U_val, 3 with U_val below 50% of the reference, 3 not judged". In `credibility.json` all four rows have |E| <= U_val (E 0.000865, 0.000722, 0.000842, -0.00004 against U_val 0.00188, 0.00109, 0.00265, 0.00199); the "1" counts only the judged row (the other three have `validated` null), while the "3 with U_val below 50 %" counts Fr 0.10, 0.20 and 0.41, two of which are not judged.
why it matters: the two counts read as one population; "1 with |E| <= U_val" reads as three of four disagreeing.
wrong data: no

## Read and found right (no finding)

k_fail, P(fail), n and verdict of all eight rows; every Wilson interval (90 % and 95 %) to 5 digits; the verdict rule text; n_certify 73 and the rule-of-three text; mode counts and shares (a member can fail in several: 128 for usv, 79 for uas against 62 and 61); first and median failure times for all four vehicles; the failed-member time lists (18, 62, 61; the UAS list is truncated to the second, not rounded); the link fractions, medians, beyond-horizon 0.89, distances 555 and 633 km (5 deg of longitude is 556 km); the sensitivity indices and floors of glider_eq, usv and uas to 1e-8; the sample sizes of the three flip candidates and their intervals (8/32, 31/32, 32/32, 12/64, 30/32, 22/64 against Wilson); the TAO prior means, pooled bias, RMSE and SST sigma from the 14 per-mooring rows; the hi95 value by the stated formula; the assumed-input arithmetic (289 listed, 287 not fitted, 272 used + 15 unused); the emulator row partition (7 + 17 + 24 + 34 = 82, 7 + 3 + 10 = 20, 7 + 17 + 17 = 41); the plan and timing sums; the map (box, ship, deploy, windows, tracks within 0.02 deg of my medians, failed flags); the V&V 20 rows' E and U_val; the hull collapse depth.

## Not covered

The values that need the environment cache (the worst-window forcing at the stage-3 windows, the reach map's outline, the environment-along-tracks arrays, the hull depth from a fresh FEA), the wind noise sd and tau (needs the hourly residual series, only checked for consistency with the pooled statistics and the printed lag-1 correlation), `credibility.json` levels beyond the arithmetic above, the emulator/design.json variants, the report's receipts digests, and the `whatif` paths for `--vehicle`, `--drop` of a vehicle with links in both directions and a trained emulator (no emulator trains in q16). No full demo, gate or CFD was started. Per the prompt I did not edit `review/orca/PROBLEMS.md`; C-1 is the row I would add.

total: 9 findings (0 critical, 1 major, 8 minor)
