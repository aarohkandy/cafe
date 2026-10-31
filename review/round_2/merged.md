# Round 2 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (20 findings), reviewer_b.md (27 findings). Merged to 36 findings, M-1 .. M-36. Every source id appears in exactly one merged finding (47 ids: A-1..A-20, B-1..B-27).
Each claim was checked by reading the cited code and, for run-based claims, the `q2` files (`plan.json`, `stage3/windows.json`, ledgers, `report.json`, `credibility.json`, `ingest/*.json`, `emulator/*.json`, `stage1b/sensitivity_cases.json`). Read-only on homebase: file listings and mtimes, `sha256sum` of `runs/receipts.json`, and one low-priority python snippet that loads `runs/q2/stage1/res.pkl` (USV path speed, UAS `max_tilt_deg`). No container, no test suite. One local numpy check (per-mooring spread of the TAO bias, M-1).

Severity: 0 critical, 14 major, 22 minor. Status: 31 confirmed, 5 partly, 0 not confirmed.
Severity changes against the reviewers (each also says why in its finding): A-1 major to minor (M-25), B-7 major to minor (M-31). B-4 and A-14 are one major finding.

Ranking inside a severity: what changes a verdict or a number printed in the report comes first.

Fix lane: "code" = the code can do better with the inputs and compute available. "wording" = the physics or data cannot be had here (no GPU, quota 0; no lab data; no CAD), so only the claim changes. "code + wording" = both.

Cold fetch (context for M-25): the q2 ingest ledger says `wall_s` 522.0 s, started 21:56:21Z; the orca cache files in `pmdata/cache/tepex_c_demo/orca/` were all rewritten between 22:04:10 and 22:04:53Z, inside that window, so it was a refetch (cache key changed in round 1). Warm ingests on the same box: 5.5 s (q1, 2026-10-31), 6.3 s and 6.7 s (t_ci, t_quick). The other eight stages sum to 691.9 s. A warm quick run is therefore about 698 s, not 1214 s.

---

## Critical

None. Both reviewers found none and nothing here changes that.

---

## Major

### M-1. The fitted wind prior treats the hourly mooring misfit as a constant bias held for six days   (sources: A-4)
severity: major / status: partly / lane: code + wording
where: cafe/pm/pipeline.py:449-452 (`value = sqrt(rmse^2 - bias^2)` of the pooled hourly series); cafe/pm/env/perturb.py:116-131 (`wind_speed_bias`, `wind_direction_bias`: one number per member, added at every time and place); cafe/pm/env/perturb.py (no time-varying wind term)
claim: Every wind-driven verdict (usv 13 of 16, uas battery, glider windage) is computed under a persistent error with sd 1.33 m/s and 23.7 deg. The data support a persistent part about three times smaller; most of the hourly misfit is short-lived, and the credibility page labels the draw `kind: data` with no caveat.
check: holds in part. Confirmed: `priors_fitted.json` sd 1.328 m/s and 23.73 deg is the pooled hourly RMSE with the pooled mean removed; `PerturbedEnv.wind` applies one value per member to the whole record. Recomputed locally from `ingest/tao_compare.json`: the 11 per-mooring time-mean speed biases have mean 0.595 and sd 0.375 m/s, the direction biases sd 8.7 deg (reviewer's numbers hold). Not established: that the persistent sd is that small. The between-mooring spread is a spatial spread of time-mean errors over 6 days, and 6-day means of a synoptic WRF error are still correlated within the run; the hourly misfit is not all noise either. So "3.5x too large" is an estimate of the order, not a measurement. The comparison also uses the 15 deg literature prior, which was also constant (it replaced a constant by a larger constant).
fix: (1) Fit the persistent part from the between-mooring dispersion of the time-mean error, minus the mean sampling variance of those means (floor at 0); keep `wind_speed_bias` / `wind_direction_bias` for that part. (2) Fit the remainder (hourly residual about each mooring's own mean) as `wind_speed_noise` and `wind_direction_noise` in `priors_fitted.json`: an sd and an e-folding time from the lag-1 autocorrelation of the hourly residuals. (3) `PerturbedEnv.wind` adds that remainder as a per-member AR(1) series keyed like the other member streams. If it cannot be vectorised at the plan's batch cost, say so in DECISIONS, drop (3), and add the unmodelled short-lived error as a credibility limitation instead. (4) The credibility "assumed inputs" row for the two priors states which part is persistent and which is not modelled. Tests: a synthetic mooring set with known persistent and white parts recovers both within 20 %. Files: cafe/pm/pipeline.py (batch C, fit), cafe/pm/env/perturb.py and config/perturbations.yaml (batch B, apply); limitation text via batch A.

### M-2. The USV speed prior is calibrated to Chiodi's SOG/wind 0.178 in a toy scenario; in the demo mission the ensemble reaches 0.10 to 0.12, and the report does not say so   (sources: B-3)
severity: major / status: partly / lane: code (diagnosis) + wording
where: DECISIONS.md:216 (row 163); config/perturbations.yaml:69-76; platforms/saildrone_explorer.yaml:86-87; cafe/pm/physics/usv.py:612-656 (`mean_sog`); cafe/pm/stage1.py `_run_usv`; cafe/pm/credibility.py `EXPECTED["usv"]`
claim: The headline USV NO-GO (13/16; brief-prior case 31/32) rests on a speed model whose mission-level speed is 35 to 41 % below the observation it is said to be calibrated to.
check: holds in part. Reproduced from `runs/q2/stage1/res.pkl` on homebase: mean path speed (sum of 10-min record displacements / 6 d) per member 0.41 to 0.98, mean 0.627 m/s; `report.json` environment gives mean U10 along the USV track 5.86 m/s (5.2 m/s after the fitted -0.62 m/s wind bias); ratio 0.107 to 0.12 against 0.1778. 13 of 16 members `swept_off_track`, none of them by battery or capsize. Not established: that the model is wrong. The 0.178 calibration (`mean_sog`) is 48 vehicles sailing to a station from 6 degrees away, uniform wind, no current, 12 h; the mission has currents of 0.2 to 1.0 m/s, becalmed and stall time, and a track-holding task. The sanity table already lists the USV as "agrees: false" but gives no reason, and nothing shows the mission-level ratio.
fix: (1) Stage 1 summary stores, per USV member, mean speed over ground, mean U10 along the track and their ratio (also the median over members); the report USV block and the sanity row print it next to Chiodi's 0.178 with the words "the calibration scenario differs from the mission (no current, uniform wind, sailing to a station)". (2) Batch B explains the gap with `mean_sog`-style runs on 1 CPU in a test or a script under bench/: the calibration scenario, then with the mission wind field, then with the mission current, then with the track-holding task; the DECISIONS row names the factor that carries it. (3) If the factor is a model fault (for example current set double counted, or leeway), fix it and rerun the USV receipts; if it is the task and the current, keep the model and write that in CREDIBILITY next to L-list. No change of the prior unless (2) shows the calibration itself is wrong. Files: cafe/pm/stage1.py, cafe/pm/physics/usv.py, platforms/saildrone_explorer.yaml, config/perturbations.yaml (batch B); report and sanity rows (batch D); docs (batch A).

### M-3. The credibility V&V 20 table is built from the discarded, recipe-less DTMB 5415 run files; they lift Validation from 1 to 2 and show "validated" at U_val about 100 % of C_T   (sources: B-1)
severity: major / status: confirmed / lane: code
where: cafe/pm/dtmb5415.py:512-528 (`tabulate`: no recipe check) against :470-473 (`run_grid`, the only RECIPE refusal); cafe/pm/credibility.py:221-232 (`_dtmb_rows`), :352-364 (`_validation`), :344-346 (Verification level 3 from "a two-grid GCI sets U_num")
claim: DECISION 144 says files of another recipe are refused and CHANGELOG says the rows read "not run" until the v4 study finishes. The shipped credibility report instead shows four DTMB rows `status: run`, three of them validated, and Validation level 2.
check: `~/work/cafe/pmdata/dtmb5415/run_coarse.json` (Oct 29 11:41) and `run_fine.json` (Oct 29 13:07) have keys `grid, iters, surf_level, S, speeds`, no `recipe`; `dtmb5415.RECIPE` is `pout-lts01-parts-v4`. `tabulate` reads every `run_<grid>.json` with no stamp test. Without these four rows with all uncertainty terms `_validation` returns level 1 (the sphere and wall-model rows have none). The v4 data are in `~/work/cafe/pmdata/c/dtmb5415` and are not read.
fix: `tabulate` skips a file whose `recipe` is not `RECIPE` and `dtmb5415.stale_files(root)` lists them; `_dtmb_rows` writes "not run: run_coarse.json was made by recipe None, not pout-lts01-parts-v4" for every speed. Until the v4 files are copied to `/data/dtmb5415` the report therefore reads Validation 1 and Verification 2, which is the truth. Also count a V&V 20 row toward Validation level 3 only when `U_val` is below a stated fraction of the reference (set 50 %, a DECISIONS row), so an uncertainty as large as the quantity cannot "validate" it. After the study ends, copy the v4 files to `/data/dtmb5415`, move the v3 files to `dtmb5415/old_v3/`, and rerun the report. Files: cafe/pm/dtmb5415.py (batch E); cafe/pm/credibility.py (batch D, interface: `stale_files(root) -> list[str]`, `tabulate(root)` signature unchanged).

### M-4. Verdicts cite a model-receipt table from code two days older, with no code digest   (sources: A-2)
severity: major / status: confirmed / lane: code
where: cafe/pm/report.py:45-46 (`RECEIPTS`), :78-85 (`Trace._table`), :99-115 (`Trace.physics`); cafe/pm/receipts.py:416-418 (`out.write_text(json.dumps(rows ...))`)
claim: `report.json` receipts `physics:pm.physics.glider|usv|comms|uas` carry sha256 `0df5e5f6eb2d...` of a table made 2026-10-29 09:05 UTC; commits 62688c3, 3d03456 and 8ee5f50 since then change `physics/comms.py`, `glider.py`, `uas.py`, `usv.py` and `stats/*`; the run's code digest is `9f537b95...`. The page still prints "25 receipts pass, 0 fail" for the current code.
check: `ls -l` and `sha256sum` of `~/work/cafe/pm/runs/receipts.json` on homebase: mtime 2026-10-29 09:05:53, sha `0df5e5f6eb2d`; `git diff --stat 62688c3~1 HEAD -- cafe/pm/physics cafe/pm/stats` lists the seven files; the table rows hold id, module, name, value, reference, tolerance, unit, ok, kind, source, note and nothing about code. `Trace._table` returns the rows and the file hash only. The stored slow receipt is refused as "not run on this code", which shows the digest moved.
fix: `receipts.run` writes `runs/receipts.meta.json` next to the table (`code_digest` from `pipeline.code_digest()`, `made_at`, git sha), keeping `receipts.json` a plain list (cafe/app.py:573 reads it as one). `Trace` reads the meta file and compares the digest with the run's own; a mismatch or a missing meta file makes `physics()` return status "stale: made by other code" (not a pass, shown as such, the row not ok). Test: change one byte of a physics file, the status reads stale. `make receipts` is rerun at code freeze with the rest. Files: cafe/pm/receipts.py (added to batch C), cafe/pm/report.py (batch D).

### M-5. Windows cut by the wall-clock kill put machine-dependent numbers into hashed outputs, so "same seed, identical report.json" cannot hold on a loaded box   (sources: A-5)
severity: major / status: confirmed / lane: code
where: cafe/pm/stage3/pipeline_windows.py:508-523 (`run_steps`, `cut_reason`, coefficients and check values of a killed run still written); cafe/pm/budget.py:5-7 (docstring "nothing ... is sized from elapsed time"); DECISIONS 136; cafe/pm/acceptance.py (same-seed = exact equality)
claim: All five LES windows of q2 were cut: glider_eq 3500 of 4300 steps, glider_2n 3200 of 4300, usv hull 3400 of 4700, usv wing 4100 of 4700, uas 4000 of 4700 ("killed after N of M steps: its wall-clock slice ... was spent"). The cut falls at a 100-step chunk boundary decided by the clock; `cd` 1.962, `cd_spread`, `cl` and the check values depend on it and are in `windows.json` and `report.json`.
check: `stage3/windows.json` resolution blocks carry `planned_steps`, `run_steps`, `cut_reason` as quoted; implied rates cells x run_steps / slice: glider_eq 54,777 x 3500 / 54 s = 3.5e6 cell-updates/s against the planned 7.53e6 (the stored rate is 2026-10-28, measured on another load). Same seed on a differently loaded box gives different `run_steps` and so different numbers. Config says the kill only turns a late window into a row that says so; the row's numbers are still written.
fix: a cut window (`run_steps < planned_steps`) is written with `cut: true`, `ok: false`, and its measured values (`cd`, `cd_spread`, `cl`, `cl_spread`, check values, `run_steps`, `cells_per_s`) moved under a `machine_dependent` block that is excluded from the hash and not printed; the report prints "window cut at the time limit: its coefficients are withheld" in their place. The `cut_reason` text keeps only the planned number, not the step it stopped at. Re-measuring the rate at code freeze (bench) makes cuts rare, but this makes the property true. Add a test that two runs with different artificial cut points give equal `report.json`. Files: cafe/pm/stage3/pipeline_windows.py (batch E, writes), cafe/pm/pipeline.py `_dump` unchanged; cafe/pm/report.py (batch D, prints). Key names `run_steps`, `planned_steps`, `cut_reason` stay; new `cut`, `machine_dependent`.

### M-6. What-if and flip-search answers for the UAS switch between wind models, and 3-D hours cover only [h, h+1] of a sortie   (sources: A-8, B-19)
severity: major / status: confirmed / lane: code + wording
where: cafe/pm/env/environment.py:151-156 (3-D WRF wind only where `_wind3d` has an ingested hour pair, else the COARE log profile from U10); cafe/pm/whatif.py:98-104 (`shift_h` edits `local_solar_time`), :127 (`duty` edits `every_days`); cafe/pm/pipeline.py:493-499 (`_sortie_hours`: `out += [h, h + 1 h]`, duration not used); cafe/pm/stage1.py `launch_times`
claim: The baseline UAS flies in the 12 ingested hours (01Z and 02Z, 2 to 7 March). A shifted sortie ("launch 6 h later") flies in hours with no 3-D fields and gets the log profile from U10, so the candidate's P(fail) differs from the baseline partly because of the wind model, not the change. The emulator training variants (`s_emulator`) have the same mix. Separately a sortie launched at :50, or a longer one, ends after the hour h+1 and silently switches model for its last minutes.
check: `cut.json` `hours3d` has exactly 12 entries (01:00 and 02:00 on 2-7 March); `environment.wind` takes the 3-D value only where `_wind3d` is finite; `_sortie_hours` ignores `duration_min`; the `Tagged` source string is the same either way ("above 21 m in sortie hours: WRF 3-D U/V ...") so nothing in the report shows which model a sortie used. The "tens of percent" difference at 30 to 100 m is the reviewer's estimate; not measured here.
fix: (1) `_sortie_hours` covers launch to launch + `duration_min` x hard-stop factor, rounded out to whole hours. (2) `GriddedEnv.use_3d` (default True); the flip search and the emulator variants set it False for UAS candidates and for their base, so both sides use the same wind model, and the report says "UAS what-if answers use the 10 m scaled profile for the candidate and the baseline". (3) The wind `Tagged` source says per call whether the sortie used 3-D or not, and stage 1 records the fraction of sortie records that used 3-D in its summary; the report shows it. Test: shifted and unshifted candidates both report use_3d False and the same model. Files: cafe/pm/pipeline.py and cafe/pm/env/environment.py (batch C), cafe/pm/whatif.py and cafe/pm/report.py (batch D), cafe/pm/stage1.py summary field (batch B).

### M-7. The emulator cannot reach `MIN_ROWS = 100` distinct feature points in a single run at any budget, so no EMULATED answer can appear   (sources: B-2)
severity: major / status: confirmed / lane: code + wording
where: cafe/pm/whatif.py:50 (`MIN_ROWS`), :339-348 (`fit_class`: rows of another `code_digest` are not trained on), cafe/pm/budget.py:33 (`EMULATOR_VARIANTS` 2/6/24/48), cafe/pm/budget.py:191-202 (`emulator_plan`); cafe/pm/pipeline.py:829
claim: Rows per vehicle after one overnight run = 48 variants + the base = 49 distinct points. USV and UAS reach 49, the glider class (two vehicles) 98, all under 100. At quick: 7 rows per vehicle (and 0 variants at the current plan). The flip search is always the 0 to 3 candidate Stage-1 fallback; the BRIEF 2.7 acceptance and the badge are unreachable except by accumulating rows over several runs of identical code (the digest covers `config/` and `platforms/`, so any commit resets the table).
check: `emulator/holdout.json` of q2: glider 2 points, 10 stale rows left out, "100 are needed"; usv 1 point, 5 stale rows. `budget.EMULATOR_VARIANTS["overnight"] = 48`; `fit_class` counts distinct points of `BASE + TASK[cls]`; the plan note at quick reads "0 of 6 variants run".
fix: `budget.EMULATOR_MIN_POINTS = 100` (whatif's `MIN_ROWS` reads it). The planner sizes the variant count to reach `ceil(MIN_POINTS x 1.2 / largest number of vehicles of one class)` per class when the share allows, with each variant batch cut to the smallest member count whose P(fail) noise the emulator already corrects for (`noise_floor_rmse` is in `fit_class`), so a variant costs a fraction of a main batch; `emulator_plan` says in `plan.json` "this budget gives N points per class, 100 are needed: the emulator will not train" before the run, and the report's emulator section repeats it. If even `overnight` cannot reach 100 on CPU, the honest statement is the result: EMULATED answers need accumulated rows (document the command that adds a run's rows to a persistent table with the same code digest) or a bigger budget; do not lower `MIN_ROWS` to make it pass. Files: cafe/pm/budget.py (batch E), cafe/pm/whatif.py and cafe/pm/report.py (batch D); RUNBOOK sentence (batch A).

### M-8. On `--gpus 0` stage 3 spends 30 % of the budget on LES windows that cannot pass at any CPU budget   (sources: A-3)
severity: major / status: confirmed / lane: code + wording
where: cafe/pm/budget.py:32 (`SHARE` stage3 0.30), cafe/pm/budget.py `stage3_plan`; config/assumptions.yaml `stage3.nu_lat_floor` (1e-4); cafe/pm/stage3/pipeline_windows.py:513-517; docs/BRIEF.md section 3
claim: All five LES windows run with `nu_floored: true`: glider_eq lattice viscosity 1e-4 against physical 3.70e-6 at dx 0.0952 m; glider_2n 2.67e-6 at 0.0794 m; usv hull 1.01e-7 at 0.316 m; usv wing 3.68e-7; uas 3.43e-6. The lattice viscosity at fixed lattice speed goes as 1/dx, so glider_eq needs dx <= 0.0952 x 3.70e-6 / 1e-4 = 3.5 mm, about 27^3 x 54,777 = 1.1e9 cells and 27 x 4300 = 116,000 steps, 1e13 to 1e14 cell-updates (the reviewer, with 9,600 physical steps, gets 1e13). The plan allots 2.2e8 per window at quick and about 3.6e9 per part at overnight. At 7.5e6 cell-updates/s that is 15 to 190 days. The usv hull needs 1000x finer dx. So `viscosity_floor` fails in every CPU window, none is ever `usable_for_refit`, the refit and the sub-grid recalibration never run, and this is not written down anywhere.
check: `stage3/windows.json` resolution blocks as quoted (`nu_lat`, `nu_lat_physical`, `nu_floored`); `grep -i "viscosity floor\|nu_lat_floor"` in docs, DECISIONS, STATUS, QUESTIONS, CHANGELOG finds DECISIONS 77 (the floor value) and PHYSICS 921 (a window that needed the floor fails); neither says it cannot be reached. 6 of the 6 q2 windows fail. The plan.json label "pooled window coefficient over the Hangar-model value" suggests a result the CPU path cannot produce. A lower floor with a collision operator stable near tau = 1/2 (the assumptions file names entropic and cumulant) would move the numbers by 10x to 30x; that is kernel development, not a round-2 fix.
fix: the planner computes, per LES window, the cell-updates needed for `nu_lat_physical >= nu_lat_floor` and compares them with the window's share at the measured rate. When the need exceeds the share by more than a stated factor (100x) the window is "not run: would need X cell-updates, this machine does Y in the share", the row is written with that reason, and the LES slice is returned to stage 1 at plan time (n_max rises; the plan stays deterministic). FEA, the free-surface hull window and the GPU path are unchanged; `ci` keeps a one-window smoke path so the code is still exercised in CI. `plan.json` `les.label` says "no LES coefficients exist on this machine; sub-grid and refit stay uncalibrated". The same sentence goes into the report's stage-3 section, STATUS, CREDIBILITY (L13 text) and RUNBOOK. Do not fake a pass, and do not lower the floor to make a window pass. Files: cafe/pm/budget.py, cafe/pm/stage3/pipeline_windows.py, config/assumptions.yaml (stage3 and reach keys; added to batch E) (batch E); report line (batch D); docs (batch A). Reduces the impact of M-5, M-9 and M-26 on CPU, but their fixes are still needed for the GPU path.

### M-9. The report never says a window was killed or under-resolved; a killed window that passes its checks reads "no check or error recorded"   (sources: A-6)
severity: major / status: confirmed / lane: code
where: cafe/pm/report.py:543-549 (`not_used_because` from failed checks and `error` only), cafe/pm/stage3/pipeline_windows.py:520-521 (`ok = checks_ok and not killed`, the kill goes to `reasons` only)
claim: `windows.json` `reasons` carries the kill, the resolution shortfall (0.3 to 0.6 cells per boundary-layer thickness against the brief's 5 to 10), the raised viscosity and the y+ remark; the page shows only "failed self-checks: yplus_in_30_300_fraction, wall_model_receipt_error, viscosity_floor".
check: `grep -c killed report/index.html` = 0 (report.json: 2, free-surface prose); `grep -n "reasons" cafe/pm/report.py` empty; `windows.json` glider_eq[0].reasons has five entries including "killed after 3500 of 4300 steps" and "resolution below the rule: 0.6 cells per boundary-layer thickness". The page does print "cells per boundary-layer thickness" once (line 208927 of index.html) but that is not from the window block. A window with all checks ok and `cut` has `ok` False, no `failed`, no `error`, so report.py:549 prints "no check or error recorded".
fix: render `w["reasons"]` in full under each window and join them into `not_used_because`; when `ok` is False and nothing else explains it say "cut at the time limit" if `cut`. Show cells per boundary-layer thickness and "lattice viscosity raised: yes" as two cells in the window table. Tests: a killed window that passes every check; a window with only a resolution reason. Files: cafe/pm/report.py (batch D).

### M-10. A surfacing link written with the non-glider first is required at every record, not at surfacing   (sources: B-8)
severity: major / status: confirmed / lane: code
where: cafe/pm/stage1.py:~393 (`need = out[a]["surfaced"] ... if a in out else out[b]["surfaced"]`); cafe/pm/config.py `_check_links` (accepts either order, requires only that a glider is at one end)
claim: `a: usv, b: glider_eq, when: surfacing` counts all 433 records as needed (the USV is always surfaced); `a: glider_eq, b: usv` counts 73. Both load without error. Same for a UAS first.
check: read `evaluate_link`: `a in out` is true for any vehicle, so the first end decides; the second line then interpolates `out[a if a in out else b]["t"]`. B's probe numbers (73 vs 433 per member) follow from the surfaced flags (glider surfaced 1 record in 6). Not re-run here; the logic is plain in the code. QUESTIONS_FOR_LAB 12 names the safe order and says nothing about order.
fix: pick the glider end by class (`out[x]["class"] == "glider"`) for `when: surfacing`, and the UAS end by class for `uas_airborne` (already done at the next branch). Test with both orders giving equal `need_count`. File: cafe/pm/stage1.py (batch B); one sentence in QUESTIONS_FOR_LAB 12 is not needed once order no longer matters.

### M-11. One member that leaves the cached box aborts the whole base ensemble   (sources: A-7)
severity: major / status: confirmed / lane: code
where: cafe/pm/env/environment.py:92-100 (`_check` raises `OutsideData` when strict, the default); cafe/pm/stage1.py `run_batch` (no handler); cafe/pm/pipeline.py:534-545 (`_stage1`, no handler); cafe/pm/physics/glider.py, usv.py (no domain guard)
claim: A 30-day window is accepted by `budget.plan` at overnight (stage 1 is 2509 s per environment call and fits the 16,200 s share) and a drifting glider or a swept USV travels 500 to 2000 km in 30 days, past the 2 degree pad. The first member that crosses raises `OutsideData` out of the vectorised step; the stage ledger records the error and the run ends after hours with no report. Currents do not raise (`Ocean._at` clamps), only wind and waves do.
check: read the code: `strict=True` by default, `grep OutsideData cafe/pm` finds handlers only in whatif.py:268, :276, :435, :457; `tests/test_pipeline.py:1250` asserts `pytest.raises(OutsideData)` for `run_batch`. q2 itself stays inside (6 days, box 163E..163W, lat +-7). Not reproduced for 30 days (hours of compute); the path from `_check` to an unhandled exception is direct.
fix: BRIEF 4.0 says degrade, never crash. `run_batch` uses a non-strict environment (edge-held values) and records, per member, the first record outside the cached box as fail mode `left_data` (counts as a failed member in the verdict, with its time); the report names the mode in plain words ("N members left the downloaded data at about time T: widen `box` / `pad_deg` and rerun"). `_stage1` adds ledger check `members_inside_data` (value = fraction inside, limit 1.0) that can fail. At ingest, size `pad_deg` from window length x a stated drift speed when the mission does not set it, and say so in the ledger. Tests: a vehicle that leaves at record k gives `left_data` at k, no exception. Files: cafe/pm/stage1.py (batch B), cafe/pm/pipeline.py and cafe/pm/env/environment.py (batch C); mode label in the report (batch D, generic mode handling).

### M-12. Three ledger self-checks cannot fail, and the CRN check names a property that does not hold for three of four streams   (sources: A-9, B-5, B-10)
severity: major / status: confirmed / lane: code + wording
where: cafe/pm/pipeline.py:570 (`common_random_numbers`), cafe/pm/stats/sampling.py:133-137 (`crn_check`); cafe/pm/pipeline.py:332-348 and :410 (`swh_spectrum_vs_file`); cafe/pm/pipeline.py:706 (`refit_iterations_within_cap`); cafe/pm/stage1.py:143, 156, 382 (`member_seed(seed, members[0], ...)`)
claim: (a) `crn_check` calls `member_rng(base_seed, m, s)` with no vehicle argument once per "vehicle", so the vehicles are identical by construction; the other half regenerates the first LHS batch, which tests determinism. The check tests `uas/turb/0` and `uas/gust` streams, while the run draws `uas/turb/{i}`, `uas/gust` and `iridium/<id>` from the batch's first member, so member j's turbulence segment depends on the batch size. The note says "every vehicle draws the same stream values per member". (b) q2 `swh_spectrum_vs_file` value 5.08e-16, limit 0.01: the synthesised spectrum is renormalised to the file's Hs on the same grid it is integrated on. (c) `refit_iterations_within_cap` compares the plan constant 2 with `refit.MAX_ITER` = 2; the pipeline performed 0 refit iterations.
check: sampling.py:133-137 read: `draws` lists are the same expression in a loop; waves.py:99-100 says "renormalised on the discrete bins to its own Hs, so 4 sqrt(m0) = hs exactly"; pipeline.py:706 compares two constants (ledger value 2, limit 2). Batch keying is admitted in PHYSICS 13.2 and CREDIBILITY 5; the ledger note says the opposite. The ingest ledger's other checks (coare u* 0.9877, direction round trip) can fail; these three cannot.
fix: (a) `run_batch` returns the stream seeds it used per vehicle (`res["seeds"][vid][stream]`); the check compares them across vehicles and with `member_seed(seed, first_member, stream)` and can fail if a per-vehicle seed creeps in. Key the UAS turbulence, gust and Iridium streams per member where that is cheap (Iridium and gust draws per member); where it is not (Mann boxes are generated for the whole batch), keep batch keying and say so in the check note and CREDIBILITY, with the batch size in the stage-1 ledger. Delete the unused `crn_check` helper (batch A, and its tests). (b) Replace the identity with checks that compare what the synthesis does not enforce: Tp (spectral peak), mean wave direction and mss of the synthesised spectrum against the UMWM file values at the sampled sea nodes, and record the fraction where the clip on `w` bites; limits stated. (c) value = refit iterations performed (0 or 1 in this pipeline), limit = cap. Files: cafe/pm/pipeline.py (batch C), cafe/pm/stage1.py (batch B), cafe/pm/stats/sampling.py (batch A); credibility text (batch A).

### M-13. `cafe.pm fetch`, `plan` and `run` die with a Python traceback for a 30-day window or a large fleet; `fetch` plans a quick budget it never uses; `run --seed -5` also ends in a traceback   (sources: A-14, B-4)
severity: major / status: confirmed / lane: code
where: cafe/pm/pipeline.py:84 (`Context.__init__` calls `budget.plan` for every command, including `fetch`); cafe/pm/budget.py:108-114 (`PlanError(ValueError)`); cafe/pm/__main__.py:118 (`except ConfigError` only); `fetch` has no `--budget` (__main__.py:31-37); `--seed` has no range check
claim: `fetch --mission` with the window extended to 30 days prints a traceback ending `PlanError: --budget quick: stage 1 needs 2546 s for even one batch of 4 members ... short by 2006 s`, so the 2.5-hour download (RUNBOOK 4) cannot start for exactly the 30-day and 20-vehicle missions BRIEF 5.6 names, although they plan fine at `overnight`. `plan --budget ci` on the demo raises the same way; so does `run --seed -5` (numpy `ValueError`). Exit code 1 and a traceback, where a bad mission gives exit 2 and "error: ...".
check: arithmetic from the code and `plan.json` member costs: per environment call 83.6 s/day (7.67 + 7.67 + 12.6 + 55.7) x 30 d = 2509 s + 4 members > the quick share 540 s; on the demo (6 d) at `ci` 502 s > 0.45 x 600 s. `Context.__init__` runs `budget.plan(budget_name, ...)` before any command-specific work; `__main__` catches only `ConfigError`. The refusal text itself is right. Not run end to end (needs the full mission); the code path is direct.
fix: `__main__` catches `budget.PlanError` and prints `error: <message>` with exit 2; `--seed` gets an argparse type that rejects negatives with a message. `fetch` passes `budget_name=None`: `Context` skips the plan for `stop_after == "ingest"` (ingest needs only the mission and the window), so fetching never depends on a budget. RUNBOOK troubleshooting row names the `PlanError` text and exit 2. Tests: `fetch` of the 30-day mission reaches ingest; `plan --budget ci` exits 2 with the message. Files: cafe/pm/__main__.py, cafe/pm/pipeline.py (batch C); RUNBOOK (batch A).

### M-14. STATUS.md describes the repo as it was on 2026-10-28; round-1 M-17's STATUS part was not fixed   (sources: A-10, B-6)
severity: major / status: confirmed / lane: wording
where: STATUS.md:1-12, :20, :77, :102 (last commit ab376fd, 2026-10-28); docs/BRIEF.md section 0 (gap statement at the top of STATUS.md), section 8
claim: The file says "On track for step 4", lists as missing the `run_premission --mission --budget --gpus` entry point, stage checkpoints, the per-mission HTML report and the Saildrone vehicle, and "6-11 not started". All exist at 8ee5f50 (`bin/run_premission`, `report/index.html`, `physics/usv.py`). BRIEF 0 requires the missing inputs, each with the command that completes it and what the user gets meanwhile, at the top; that is only in QUESTIONS_FOR_LAB. The blind-RUNBOOK run round 1 asked for has no record (`grep -ri "fresh subagent\|blind"` in CHANGELOG, DECISIONS, STATUS, RUNBOOK is empty).
check: `git log -1 --format='%h %ad' -- STATUS.md` = `ab376fd 2026-10-28 18:10`; the quoted lines are there; `ls bin` shows `run_premission`; CHANGELOG lists M-17's fix as DECISIONS rows 21/68, CREDIBILITY, RUNBOOK 7 and QUESTIONS, not STATUS.
fix: rewrite STATUS from the code: what is done per stage with its evidence, what is not (no GPU; LES windows cannot pass on CPU, M-8; no DTMB v4 until the study ends; golden and mutation at code freeze; lab inputs), and put the BRIEF 0 gap statement at the top (input, one command, interim output, from QUESTIONS_FOR_LAB). The blind RUNBOOK run is a step for a fresh agent after code freeze; record its result, or write "not yet done" with the date. Files: STATUS.md, CHANGELOG.md, DECISIONS.md (batch A).

---

## Minor

### M-15. The "brief prior" sensitivity case is a different sample (n = 32) from the verdict it is printed beside (n = 16)   (sources: A-17, B-14)
severity: minor / status: confirmed / lane: code + wording
where: cafe/pm/stage1.py:496-520 (`sensitivity_case`, `n=32`, docstring "every other input drawn from the run's own hypercube columns"); cafe/pm/pipeline.py:718-727 (`SENSITIVITY_MEMBERS = 32`); cafe/pm/report.py:303, :808 ("the same ensemble under another setting of one input")
claim: The case calls `run_batch(..., range(32))`, so `lhs(32, ...)` draws different strata for every parameter and members 16 to 31 are new; the main run is `lhs(16, ...)`. q2 prints 31/32 beside 13/16; the change of prior and the change of design are confounded.
check: `sensitivity_cases.json` has `n: 32, k_fail: 31`; report.json usv `n` 16, `k_fail` 13; `lhs(n, ...)` permutes strata by n, so the first 16 of a 32 design are not the 16-design. Both verdicts are NO-GO, so the conclusion survives; the sentence and the docstring are wrong.
fix: `sensitivity_case` takes the run's own hypercube (`X=res["X"]`, same n, same members) and replaces only the `usv_vpp_bias` column, so the comparison is paired and an effect size can be read (members that flip). Keep a larger-n variant only as a second line labelled with its own n. Report wording: "same members and same other inputs; only `usv_vpp_bias` replaced". Files: cafe/pm/stage1.py (batch B, add the optional `X` argument, default None keeps the old call), cafe/pm/pipeline.py (batch C, pass `res["X"]`), cafe/pm/report.py (batch D, wording).

### M-16. Credibility "Uncertainty characterization" is scored from the stage-1b ledger, so any run without a refit scores 1 though the stage-1 ledger holds the passed Latin-hypercube checks   (sources: B-15)
severity: minor / status: confirmed / lane: code
where: cafe/pm/credibility.py:383-400 (`_uncertainty`)
claim: q2 `credibility.json` has uncertainty level 1 with "no passed Latin-hypercube stratification check in the stage-1b ledger (a copied stage 1b has none)", while `checkpoints/stage1/ledger.json` has `lhs_stratified_batch1 ok`. Stage 1b is a copy whenever no window passes, which is every CPU run.
check: read `_uncertainty` (lhs list taken from `f.have["stage1b"]` only) and the q2 stage-1 ledger.
fix: take the LHS checks from the stage that produced the verdict's ensemble: the stage-1 ledger when stage 1b is a copy (its ledger note says so), else stage 1b. Test both. File: cafe/pm/credibility.py (batch D).

### M-17. Data pedigree level 3 ("strong") needs only that a TAO comparison exists, not that the model agrees   (sources: A-20)
severity: minor / status: partly / lane: wording + code
where: cafe/pm/credibility.py:61-63 (`RULES["data_pedigree"]`), :312-331 (`_data_pedigree`)
claim: Level 3 reads "strong: checked against an independent reference" while the stored comparison is speed RMSE 1.46 m/s (bias +0.62), direction RMSE 24.8 deg, SST bias -0.11 K with T5S180W at -0.50 K; any numbers would score 3.
check: holds in part. `_data_pedigree` gives level 3 on `tao_compare.json` existing, as the code and RULES text say ("a TAO/TRITON comparison is stored"), so the rule is honest about what it tests; the level name and the word "independent" are not: the same comparison fits the Stage-1 wind priors, so it is not independent of the run.
fix: rename level 3 for this factor to "compared with moorings (the comparison also sets the wind priors)"; put the RMSE, bias and mooring count in the evidence line; cap at 2 when the pooled speed or direction RMSE exceeds a stated limit taken from the brief's prior sd (2.0 m/s, 15 deg) unless the limitation list names it. File: cafe/pm/credibility.py (batch D); wording of RULES in CREDIBILITY.md (batch A).

### M-18. The sanity row for the acoustic links says the distance "is not in the verdict", though the report holds it   (sources: B-27)
severity: minor / status: confirmed / lane: code
where: cafe/pm/credibility.py:89-90 (`EXPECTED`), :558; cafe/pm/report.py:1048
claim: `glider_eq-ship-acoustic` and `glider_2n-ship-acoustic` are NO-GO with "out of the acoustic model's range at 1 fraction of the needed samples"; the gliders are 555 and 598 km from the ship (QUESTIONS_FOR_LAB 12). The brief's expectation is "NO-GO at more than 3 km", which agrees. The table prints "cannot be checked from the verdict".
check: q2 `sanity.rows` has `agrees: null` for both; the stage-1 link summary carries `frac_out_of_range` and the positions are in `res.pkl`; credibility.py:89-90 text as quoted.
fix: the sanity row reads the link's median ship distance (or `frac_out_of_range` and the modem range) from the run and sets `agrees` true when the link is NO-GO and the median distance exceeds 3 km, false when it is GO beyond 3 km, null only when the distance is unavailable. Test with both. File: cafe/pm/credibility.py (batch D); the summary field comes from cafe/pm/stage1.py if it is not already stored (batch B).

### M-19. The reach map uses a USV speed that Stage 1 does not fly   (sources: B-24)
severity: minor / status: confirmed / lane: code
where: config/assumptions.yaml:328-336 (`reach.speed_ms.usv` 1.4); cafe/pm/report.py:439-441
claim: The map shows 155.9 km reachable in 24 h at 1.4 m/s (labelled "assumed"); the Stage-1 USV mean path speed is 0.63 m/s and the fastest member makes 85 km/day, so the outline is larger than anything the ensemble reaches.
check: q2 report reach block (assumed label present); my res.pkl numbers: mean path speed 0.627 m/s, per-member 0.41 to 0.98. The file's own `replace_with` says "the VPP speed at the forecast wind along the track".
fix: when the run has USV records, use the run's median mean path speed for the reach map and say so ("from the Stage-1 ensemble"); the assumed value stays only as the fallback and keeps its badge. Same for the glider if its Stage-1 speed through water differs from 0.23 m/s. File: cafe/pm/report.py (batch D). Depends on M-2 (if the USV speed model changes the number changes with it).

### M-20. Acoustic noise is computed from the unperturbed wind   (sources: B-25)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage1.py:~403 (`env.env.u10(...)`; every other forcing in `evaluate_link` uses the member's `env`)
claim: Stojanovic wind noise is 7.5 sqrt(w) dB; a member whose wind is 1.3 m/s lower (the fitted sd) is about 2 dB quieter, inside a Bellhop trigger band of +-6 dB. RF uses the member's own Hs.
check: read the line: `wind = np.hypot(*np.moveaxis(np.asarray(env.env.u10(lonA, latA, tt), float), -1, 0))` takes the underlying environment, bypassing `PerturbedEnv.wind`'s bias and rotation. Not exercised in q2 (links are 555 km out of range), so no number changes there.
fix: use the member's perturbed 10 m wind speed (`env.wind(lon, lat, 10.0, t)`, shaped as the Hs call is). Test: with a positive `wind_speed_bias` the noise term rises. File: cafe/pm/stage1.py (batch B).

### M-21. A Tp perturbation changes Tp and Tm but not the Stokes drift   (sources: B-18)
severity: minor / status: confirmed / lane: code
where: cafe/pm/env/perturb.py:147-170 (`PerturbedEnv.waves`: `stokes0` scaled by `hs ** 2` only)
claim: Surface Stokes drift of a narrow spectrum goes as Hs^2 / Tp^3 (u_s(0) = 16 pi^3/g integral f^3 E df, E scales with Hs^2 f_p^3 ...); a Tp of 8 s instead of 9 s changes it by about 40 %. The member's wave state is internally inconsistent and the Stokes uncertainty into USV and glider drift is understated.
check: read the code (hs only); the scaling follows from the formula in BRIEF 2.3 and PHYSICS (Breivik 2016).
fix: multiply `stokes0` by `(Tp_unperturbed / Tp_member)^3` where `tp_bias` is applied (guard Tp >= 1 s as the code already does). Test: `tp_bias = -1` s at Tp 9 s raises `stokes0` by (9/8)^3. File: cafe/pm/env/perturb.py (batch B, added to B).

### M-22. Link moments before a vehicle's deploy time count as required   (sources: B-17)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage1.py:~384 (Iridium `need = ones`), :~399 (`when: always`), :~393 (`np.interp` of `surfaced` clamps to the first value), :289-299 (`_pos` clamps likewise)
claim: Record grids start at the vehicle's own deploy time; the link grid is the whole window. A vehicle deployed 48 h after the window start has 48 h of a `when: always` or `surfacing` link counted as needed at its deploy point. The demo deploys at window start, so q2 is unaffected.
check: read `evaluate_link` (`t = np.arange(t0, T + 1, REC_S)` over the window; `need` has no deploy mask).
fix: mask `need` with `t >= deploy time` of each vehicle end (UAS: sortie times already come from `airborne`); `_pos` returns NaN before deploy so `need &= isfinite(d)` already drops them. Test: a what-if "deploy 48 h later" leaves the link's `need_count` equal to the in-window count. File: cafe/pm/stage1.py (batch B).

### M-23. "First failure" and "median failure" are taken over the dominant mode's members only   (sources: B-16)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage1.py:470-473 (`first = r["first"][dom]`, `t_first`, `t_med`)
claim: With mode A in 3 members (first failures on day 4) and mode B in 2 other members (day 1), the reported first failure is day 4 and the median is over A's 3, while the earliest failure and the median over all failed members are day 1. In q2 the dominant mode covers every failed USV member (mode share 1.0), so the printed numbers are right there.
check: read the lines; `mode_shares` in q2 report.json usv shows swept_off_track share 1.0 of failed members.
fix: `first` = elementwise minimum over `r["first"].values()` per failed member, then min and median over failed members; the dominant mode keeps its own `first_fail_mode`. Test with the A/B example. File: cafe/pm/stage1.py (batch B).

### M-24. UAS sortie schedule: 24 h and 48 h what-if shifts are the baseline, fractional `every_days` drifts the time of day, other periods are anchored to the epoch day, and absurd periods are accepted   (sources: A-11, B-20)
severity: minor / status: confirmed / lane: code
where: cafe/pm/whatif.py:102-104 (`tot = (hh*60 + mm + round(h*60)) % 1440`), :127 (`every_days / duty`); cafe/pm/stage1.py:101-108 (`launch_times`, `day0 = floor(t0/86400)*86400 - 86400`); cafe/schemas/mission.json:54
claim: Shifts of +-24 and +-48 h leave `local_solar_time` unchanged, so four of the 16 UAS candidates are the baseline, evaluated and priced as real changes. The duty candidate every 1.3333 d launches at 08:59Z, 16:59Z, 00:59Z, so not at the mission time of day. `every_days: 2` first launches on 03-03, skipping the 03-02 slot, because the phase comes from the epoch day; `every_days: 1e-6` is accepted (millions of launches); a period shorter than `duration_min x hard_stop_factor` makes sorties overlap.
check: read both functions: the modulo in `whatif.apply` removes whole days; `ts = day0 + off + every * arange(...)` with `day0` tied to the calendar, not to the first launch. Reviewers' probe values (first launch 03-02 01:00Z for h = 0, +-24, +-48) follow from that.
fix: `whatif.apply` rejects a UAS `shift_h` that is a whole number of days (`Invalid: the same launch time of day`) and the candidate generator drops them; the duty candidate rounds `every_days` up to a whole number of days when it is >= 1 and says so in its label. `launch_times` anchors the phase to the first slot at or after the window start. `load_mission` refuses `every_days * 1440 < duration_min x hard_stop_factor` with a message naming the file and fix; the schema sets a lower bound. Files: cafe/pm/stage1.py (batch B), cafe/pm/whatif.py (batch D), cafe/pm/config.py and cafe/schemas/mission.json (batch A).

### M-25. The quick run took 20 min 14 s only because the ingest was a cold fetch; the 20-minute limit counts the whole process, the budget docstring promises an ingest term that does not exist, and the planner overestimates stage 1 by 2.5x   (sources: A-1)
severity: minor / status: partly / lane: code + wording
where: cafe/pm/acceptance.py:79-90, :98-106 (`run_one` times the whole `run`; `check_run` compares it with 1200 s); cafe/pm/budget.py:5-7 and :32 (`SHARE` sums to 0.95, no ingest term; docstring "ingest (measured bytes/s; zero once cached)"); docs/RUNBOOK.md:9
claim: Ingest 522 s is in no budget share; the sum of ledger `wall_s` is 1213.9 s against `BUDGET_S["quick"]` = 1200, so `make acceptance` would fail `run_quick` on this evidence. The reviewer adds that a warm cache "still costs up to 8.7 min" and that plan.json `stage1_s` 531.8 s against 211 s measured wastes 330 s of the stage-1 share.
check: holds in part. Ledger arithmetic is right (522.0 + 0.13 + 211.0 + 0.09 + 360.1 + 0.01 + 40.6 + 78.1 + 1.8 = 1213.9; first start 21:56:21.5Z, report end 22:16:35.4Z). The warm-cache claim is not: the orca cache files were rewritten 22:04:10 to 22:04:53Z inside the ingest window (cache key changed in round 1, all 315 parts refetched), and warm ingests on the same box take 5.5 s (q1), 6.3 s, 6.7 s. Warm total is about 692 + 6 = 698 s, 58 % of the limit. The 2.5x stage-1 overestimate is the stale `config/throughput.json` (measured at load 32.9 on `ci_fixture`, plan notes say so); re-measured at code freeze, not a round-2 fix. Downgraded from major.
fix: decision: the 20-minute limit counts the compute stages with a warm cache; a network fetch is a separate, documented step (RUNBOOK 4) whose duration depends on the lab link, not on `--budget`. (1) `run_one` in acceptance runs `fetch` first (offline-safe, a few seconds when warm; fails with the fetch command if the cache is cold and `CAFE_OFFLINE=1`) and times only `run`; the row shows the wall of `run`, the ingest wall and "cold fetch: yes/no". (2) The ingest ledger notes `cold fetch: N parts, X s` when it fetched, and plan/report show "ingest X s (not counted against --budget)". (3) `budget.py` docstring and RUNBOOK 0 say what is counted. (4) The stage-1 estimate error needs no code change; the plan keeps its stale-measurement note until `make bench`. Files: cafe/pm/acceptance.py (batch D), cafe/pm/pipeline.py (batch C, ledger note), cafe/pm/budget.py docstring (batch E); RUNBOOK (batch A).

### M-26. The UAS stage-3 window still diverges after the round-1 fix, and a diverged window runs to the wall-clock kill   (sources: A-13, B-12)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage3/pipeline_windows.py (UAS case, `leg_clipped`, :508-521); cafe/pm/stage3/lbm.py (no non-finite abort); DECISIONS.md:214 (row 161)
claim: q2 UAS window: `kinematics` v_rel 12.0 m/s (limit 12), tilt 33.6 deg, `leg_clipped: True`; `mach_max` 8.85 (limit 0.1), `courant_max` 5.11, `cd`, `force_running_mean_dev`, `mass_drift_per_step` and `interpolation_residual` NaN; yet `run_steps` 4000 of 4700, so the NaN field consumed its whole 70 s slice (19 % of the stage-3 share). The fix changed the inputs, not the stability; no UAS window has ever completed.
check: `stage3/windows.json` uas[0] values as quoted; dx 0.0146 m, lattice `dt` 4.86e-5 s, so lattice speed is about 0.04 (the input is inside the envelope and the state still blows up). The likely cause named by A (arms 0.015 x 0.01 m, one cell, below `stage3.min_cells_across` = 2) is a guess; not established.
fix: (1) `run_steps` chunk loop ends at the first chunk where `mach_max` > 1 or any force is non-finite, records `diverged_at_step`, and the unused seconds go to the next window. (2) Reproduce the divergence at a coarse size on 1 CPU in a test, find the cause (thin parts, boundary, floor), and either fix it or mark the UAS window "not run: numerically unstable at this resolution" with the reason, so the slice is not wasted. Do not relax the Mach check. Files: cafe/pm/stage3/pipeline_windows.py, cafe/pm/stage3/lbm.py (batch E). Moot on CPU if M-8 skips the window, still needed for the GPU path.

### M-27. The refit loop of BRIEF 2.6 is a single rerun; `plan.json` says 2 iterations   (sources: A-16)
severity: minor / status: confirmed / lane: wording + code
where: cafe/pm/pipeline.py:735-752 (`s_stage1b`); cafe/pm/budget.py `refit_iterations`; cafe/pm/pipeline.py:706
claim: The brief asks for a loop with a convergence check capped at two; the pipeline reruns stage 1 once (zero times when no window passes) and never loops. The Results-robustness row "a stage-3 refit reran stage 1 and no verdict changed" can only be earned by one rerun. The limitation is not in the CREDIBILITY list.
check: `plan.json` `"refit_iterations": 2`; stage1b ledger note "no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"; refit ledger note "it does not loop until the verdicts stop changing". Related check fix is in M-12 (c).
fix: either implement the second pass (rerun stage 1 with the multipliers refitted on the first pass's window set only if a verdict changed, capped at `refit_iterations`) or state it: `plan.json` key `refit_iterations_max`, the stage-1b summary records `refit_iterations_performed`, and CREDIBILITY adds a limitation "single-pass refit". The second pass is a no-op on CPU (no usable windows), so the wording version is acceptable until a GPU run exists. Files: cafe/pm/pipeline.py (batch C); limitation text (batch A).

### M-28. UAS `max_tilt_deg` is 35.00 in all 96 sorties, so the attitude diagnostic carries no wind information   (sources: B-11)
severity: minor / status: confirmed / lane: code + wording
where: cafe/pm/physics/uas.py:303 (`k = jnp.minimum(1.0, fz * jnp.tan(tilt_lim) / fh)`), :338 (`flying & (tilt > tilt_exc)`); platforms/quad_uas.yaml:82-88 (limit 35 deg, exceedance 42 deg)
claim: With the commanded horizontal force clamped to g tan 35 deg, the 42 deg exceedance mode is reachable only through 7 deg of dynamic overshoot. The mode that should discriminate gust-front windows (BRIEF 6 expects UAS NO-GO there) saturates at the clamp in every sortie; the demo UAS verdict is a battery verdict only.
check: `res.pkl` of q2 on homebase: 6 sorties x 16 members, `max_tilt_deg` min 34.99996, max 35.0146, unique values {35.00, 35.01}; `fail["attitude_exceedance"]` fires in 0 members, `battery_reserve` in 2; launch winds 2.2 to 7.96 m/s.
fix: record, per sortie and member, the fraction of time at the clamp and the largest unclamped demand ratio (min over time of `k`), and add a mode "authority_saturated" (demand beyond the clamp for longer than a stated time) that is the real wind-driven failure; the threshold is a labelled assumption and a DECISIONS row. Until then the sanity row and the UAS block say "attitude exceedance cannot fire in this controller model (clamp 35 deg < 42 deg)". Tests with a gust series that demands more than the clamp. Files: cafe/pm/physics/uas.py, cafe/pm/stage1.py, platforms/quad_uas.yaml (batch B); wording (batch A, D).

### M-29. `validate` accepts duplicate link ids and a swapped latitude box with a misleading message, and RF or acoustic links to `shore` pass validation and then crash Stage 1 with KeyError   (sources: A-15, B-9)
severity: minor / status: confirmed / lane: code
where: cafe/pm/config.py:96-130 (`load_mission`, `_check_links`), :51-55 (`_in_box`); cafe/pm/stage1.py:289-299 (`_pos`)
claim: A mission with `links[0]` copied to the end validates as "5 links" and the results dict (keyed by link id) silently drops one. `box.lat_min: 5, lat_max: -5` gives "ship (-165.0, 0.0) is outside the mission box ...; widen the box or move the ship", which sends the user to the wrong fix. `{a: usv, b: shore, kind: rf}` loads, then `evaluate_link` raises `KeyError: 'shore'` (the ship is special-cased in `_pos`, the shore has no position).
check: read `_check_links`: `nodes` includes the shore id, `ends` classes only matter for `when`, there is no `ids` uniqueness test for links (vehicles have one, :124-127), the schema has no `lat_min < lat_max`; `_pos` falls through to `out[node]`.
fix: refuse duplicate link ids; refuse `lat_min >= lat_max` ("lat_min must be below lat_max") before the point-in-box checks; refuse an `rf` or `acoustic` link with the shore as an end ("the shore has no position; only iridium links can end at the shore"). Tests for the three. File: cafe/pm/config.py (batch A).

### M-30. `ingest/tao_compare.json`, `stage3/windows.json` and the ingest ledger are not valid JSON   (sources: A-12)
severity: minor / status: confirmed / lane: code
where: cafe/pm/pipeline.py:153-155 (`_dump`: `json.dumps(..., default=ledger._jsonable)`, `allow_nan=True`); cafe/pm/ledger.py (ledger writer)
claim: `windows.json` holds `"limit": Infinity` (15 occurrences), `tao_compare.json` `"sst_bias": NaN` (8), the ingest ledger 1. `jq` and `JSON.parse` reject them; `report.json` is clean because the report maps non-finite to null. The RUNBOOK invites reading raw JSON.
check: `grep -c "Infinity\|NaN"` over the q2 tree: stage3/windows.json 15, ingest/tao_compare.json 8, checkpoints/ingest/ledger.json 1, all other files 0. Other writers (acceptance, credibility, report, receipts) already use `allow_nan=False`.
fix: `_dump` and the ledger writer map non-finite floats to null (recursively, `_jsonable`) and use `allow_nan=False`; readers treat a null `limit` as "no limit" (the report's `num()` already does). Audit re-hash is unaffected (it hashes bytes). Test: every file written by a CI run parses with `json.loads(parse_constant=raise)`. Files: cafe/pm/pipeline.py, cafe/pm/ledger.py (batch C); null-limit handling in cafe/pm/report.py (batch D, check only).

### M-31. The golden's clean-tree requirement is bypassed on the supported homebase path   (sources: B-7)
severity: minor / status: confirmed / lane: code
where: cafe/pm/acceptance.py:192-198 (`_dirty`), :201-215 (`provenance_problems`, "unknown is not dirty"); compare cafe/pm/ledger.py:38-49 (`git_dirty`, falls back to `$CAFE_GIT_DIRTY`); pm.sh:8
claim: Through `./pm.sh` the checkout on homebase has no `.git`, so `acceptance._dirty()` returns None and never reads `$CAFE_GIT_DIRTY`, which pm.sh sets for exactly this case. `--update-golden` from a tree with uncommitted edits writes `dirty: null`, and `provenance_problems` only rejects `dirty is True`. The ledger path handles it (the q2 ledgers show `git_dirty: null` because the scratch runner omits the variable).
check: read both functions; `_dirty` has its own `git status` call and no env fallback; pm.sh passes `CAFE_GIT_DIRTY` (checked: line 9 of pm.sh). Downgraded from major: only the minting of the golden is affected, the fix is one line, and the golden is minted once by an operator who can see the tree.
fix: `_dirty = ledger.git_dirty`; `provenance_problems` treats `dirty` None as a problem ("cannot tell whether the checkout was clean"). Test: no `.git`, `CAFE_GIT_DIRTY=1` refuses; `=0` accepts; unset refuses. File: cafe/pm/acceptance.py (batch D).

### M-32. `code_digest` leaves out `cafe/schemas/*.json`, which ingest and `load_mission` treat as the contract   (sources: B-13)
severity: minor / status: confirmed / lane: code
where: cafe/pm/pipeline.py:51-62 (`rglob("*.py")`, `config/*.*`, `platforms/*.yaml`); cafe/pm/env/orca.py:34-58 (reads `wrfout.json`, `umwmout.json`, `umwmrst.json`); cafe/pm/config.py `SCHEMAS`
claim: Editing a schema (units, a variable) does not change `Context.hash`, so `--resume` keeps the ingest ledger and every stored result as current. Round-1 M-15 made the digest cover `cafe/**/*.py` for the same reason.
check: `ls cafe/schemas` = 6 JSON files; `code_digest` hashes none. `credibility._data_pedigree` also relies on the schema files being present.
fix: add `cafe/schemas/*.json` to the hashed files. Say in the CHANGELOG that stored resumes are invalidated once more. Test: touching a schema changes the digest. File: cafe/pm/pipeline.py (batch C).

### M-33. The planner's memory guard is dead code   (sources: B-26)
severity: minor / status: confirmed / lane: code
where: cafe/pm/budget.py:218 (`memory_guard`), :92 and :133-135 (`plan(..., gpu_mem_gb=None)` sets `les["max_cells"]` only when passed); cafe/pm/pipeline.py:84
claim: `Context` never passes `gpu_mem_gb`, so BRIEF 3's "the planner refuses a configuration over 85 % of GPU memory and says what to reduce" cannot happen; a too-large plan fails mid stage 3. The working guard is `lbm.check_memory` inside a window.
check: `grep -rn "memory_guard\|gpu_mem_gb" cafe/pm` finds only budget.py. Only matters with `--gpus > 0`, which cannot be run here (quota 0), so this is a unit-test-level fix.
fix: `run`/`plan` take `--gpu-mem-gb` (default: ask `nvidia-smi --query-gpu=memory.total` when `--gpus > 0`, else none); `Context` passes it to `plan`; `stage3_plan` calls `memory_guard` for each window's cells. Test with a fake memory size. Files: cafe/pm/__main__.py, cafe/pm/pipeline.py (batch C), cafe/pm/budget.py (batch E).

### M-34. `make audit` gates ruff, mypy, coverage and the banned-token scan on `cafe/pm` only; BRIEF 5.5 says `cafe/`   (sources: B-23)
severity: minor / status: partly / lane: wording + code
where: pyproject.toml:6-15 (`ruff include`, `mypy files = ["cafe/pm"]`, coverage `source`); cafe/pm/audit.py:27-29 (`SCAN`, `GATES`)
claim: About 7,156 lines under `cafe/` outside `cafe/pm` (cfd.py, fea.py, emulator.py, reach.py, receipts.py and others the pipeline imports) are outside every gate. "No DECISIONS row records the narrowing."
check: holds in part. The scope is real (pyproject and audit.py as quoted) and the pipeline imports `cafe.cfd`, `cafe.fea`, `cafe.emulator`, `cafe.reach` (pipeline.py `code_digest` docstring). It is recorded: DECISIONS 97 lists the scanned directories (`cafe/pm`, tests, bench, ...) and the coverage gates; what no row gives is the reason the older `cafe/` modules are excluded. `REVIEW.md` line 100 ("placeholder") is an old review document, not code.
fix: a DECISIONS row that names the modules outside the gates that the pipeline imports, says why they are excluded (pre-mission app code, tested through the pipeline and their own receipts), and states which gates they would need to join (ruff and the banned-token scan are cheap and should; mypy strict and 90 % coverage are not asked for them). Extend `SCAN` and ruff `include` to those imported modules. File: cafe/pm/audit.py, pyproject.toml (batch C); DECISIONS (batch A).

### M-35. Docs that DECISIONS superseded still state the old numbers   (sources: A-18, B-21, B-22)
severity: minor / status: confirmed / lane: wording
where: docs/RUNBOOK.md:146 (`ensemble capped at 32 members ...`), :11 (orca cache 1.1 GB), docs/PHYSICS.md:845 ("first 6 harmonics"), :838 (quick `n_min / n_max` 32 / 64), :657 ("the platform's own N(-0.30, 0.03) default"), docs/CREDIBILITY.md:14, :71 ("twelve" limitations, no L13 anywhere in the file, section 5 table), CHANGELOG.md:30 ("1,370 test functions in 43 test files")
claim: The first thing a quick run prints does not match the RUNBOOK table that explains it; PHYSICS and CREDIBILITY disagree with the code.
check: q2 `plan.json` note "ensemble capped at 16 members by the stage-1 share ... n_min = n_max = 16"; `du -sh` on homebase `cache/tepex_c_demo/orca` = 2.1 G (+ `derived.zarr` 218 M, not 1.1 GB); `sensitivity.default_harmonics` = `min(6, max(2, n // 16))` (docstring says 0.53 to 0.60 at six harmonics); `platforms/saildrone_explorer.yaml` `vpp_bias_mean` -0.2422, `vpp_bias_sd` 0.0082; `credibility.json` lists L01 to L13 and `grep -c L13 docs/CREDIBILITY.md` = 0; `ls tests/test_*.py | wc -l` = 47 and 1,622 `def test_`. The RUNBOOK 16-member figure itself depends on the stale bench (M-25), so the row should not name a number.
fix: RUNBOOK row: "ensemble capped at N members by the stage-1 share" with "N depends on the machine's measured stage-1 cost (`plan.json`)"; sizes from `du`; PHYSICS harmonics and quick `n_min/n_max` from `budget.py` (and say the planner may lower n_min); the platform default from the yaml; CREDIBILITY: thirteen limitations, L13 text and its row in the section 5 table (caps Validation and Uncertainty); CHANGELOG test count measured at code freeze. Add the new limitations from this round (M-1 persistent wind prior, M-8 CPU LES unreachable, M-27 single-pass refit, M-28 attitude clamp) as L14 and following, in `credibility.py`'s `LIMITATIONS` list too (the text must stay the same in both: credibility.py is batch D's). Files: docs/RUNBOOK.md, docs/PHYSICS.md, docs/CREDIBILITY.md, CHANGELOG.md (batch A); `LIMITATIONS` entries in cafe/pm/credibility.py (batch D, from batch A's text).

### M-36. BRIEF 2.9 "the web UI replays and the static demo read report.json" is dropped without a decision   (sources: A-19)
severity: minor / status: confirmed / lane: wording
where: docs/BRIEF.md:150; README.md (0 mentions of `cafe.pm`, `run_premission` or the RUNBOOK); cafe/static/, site/
claim: Nothing but the audit, acceptance, pipeline and report modules reads `report.json`; the README a lab member opens first describes only the old app; no DECISIONS or CHANGELOG row records the omission.
check: `grep -rl "report.json" cafe site bin lab` hits only `cafe/pm/{audit,acceptance,pipeline,report}.py`; `grep -c -i "premission\|RUNBOOK\|cafe.pm" README.md` = 0; DECISIONS and CHANGELOG hits for `report.json` are about the report schema, not the UI.
fix: README gets a short section for the pre-mission tool (what it is, the two commands, link to RUNBOOK and STATUS); a DECISIONS row says the web UI and static demo do not read `report.json` in this build, why (not built, no lab requirement beyond the brief's sentence) and what it would take; STATUS lists it under "not done". Building a reader is not proposed in this round. Files: README.md, DECISIONS.md, STATUS.md (batch A).

---

## Fix batches

Same five batches and file ownership as round 1, with the additions marked "(added)". Rules for all builders:
- Edit only the files your batch owns, plus the tests for those modules (new test files are fine; an existing test file is edited by the batch that owns the module under test).
- Do not edit any `*.md` unless you are batch A. Everyone else lists the DECISIONS, CHANGELOG, PHYSICS, CREDIBILITY, RUNBOOK or QUESTIONS lines that their change needs in the final message, and batch A applies them.
- Do not change a public signature that another batch calls (`flip_search`, `budget.plan` return keys, `Ledger.check`, `intervals.interval`, `stage1.run_batch`, `launch_times`, `dtmb5415.tabulate`). New arguments are optional with the old behaviour as default.
- Nothing runs on homebase except short 1-CPU checks while the DTMB study is running. `make bench`, `make mutation`, the golden and the final acceptance run at code freeze, when the box is idle; no builder starts them.
- Every fix gets a test that fails without it (a regression test per finding, as in round 1).

### Batch A: config, statistics, all documents
Findings: M-24 (config part), M-29, plus the document edits listed by the other batches: M-1, M-2, M-7, M-8, M-12, M-14, M-25, M-27, M-28, M-34, M-35, M-36 (and the wording sides of M-3, M-4, M-9).
Specific work: M-14 STATUS rewrite with the BRIEF 0 gap statement at the top; M-35 stale numbers; M-36 README and DECISIONS row; M-12 remove `sampling.crn_check` if batch C no longer calls it (coverage gate for `stats` is 100 %); new DECISIONS rows for round 2 (numbering continues after 181); CREDIBILITY limitations from this round with the same text that batch D puts in `credibility.py`.
Files owned:
- cafe/pm/config.py
- cafe/schemas/mission.json
- cafe/pm/stats/intervals.py, cafe/pm/stats/sequential.py, cafe/pm/stats/sensitivity.py, cafe/pm/stats/sampling.py, cafe/pm/stats/rare.py
- missions/*.yaml
- STATUS.md, DECISIONS.md, CHANGELOG.md, QUESTIONS_FOR_LAB.md, README.md, REVIEW.md, PLAN.md
- docs/BRIEF.md (read-only unless a finding says otherwise), docs/RUNBOOK.md, docs/PHYSICS.md, docs/CREDIBILITY.md
- tests for config and stats (tests/test_config*.py, tests/test_stats*.py, tests/test_intervals*.py, tests/test_sensitivity*.py)

### Batch B: Stage 1 engine and vehicle physics
Findings: M-1 (apply side), M-2 (diagnosis, summary fields), M-6 (summary field for 3-D use), M-10, M-11 (`left_data`), M-12 (stream seeds returned), M-15 (`X` argument), M-18 (distance field if missing), M-20, M-21, M-22, M-23, M-24 (`launch_times`), M-28.
Files owned:
- cafe/pm/stage1.py
- cafe/pm/physics/*.py (comms.py, glider.py, usv.py, uas.py, rigid.py)
- cafe/pm/env/perturb.py (added), cafe/pm/env/waves.py (added, only if M-12 (b) needs the spectrum accessor; the check itself is in pipeline.py)
- config/perturbations.yaml
- platforms/*.yaml
- tests for stage 1, perturbation and the physics modules (tests/test_stage1*.py, tests/test_comms*.py, tests/test_usv*.py, tests/test_uas*.py, tests/test_glider*.py, tests/test_perturb*.py)

### Batch C: pipeline, ledger, audit, ingest cache, receipts
Findings: M-1 (fit side), M-4 (receipts meta), M-6 (hours, `use_3d`), M-11 (ledger check, strict flag), M-12 (the three checks), M-13, M-15 (pass `X`), M-25 (ledger note), M-27, M-30, M-32, M-33, M-34.
Files owned:
- cafe/pm/pipeline.py
- cafe/pm/ledger.py
- cafe/pm/audit.py
- cafe/pm/receipts.py (added)
- cafe/pm/env/orca.py, cafe/pm/env/environment.py (added: `use_3d` attribute, strict flag use)
- cafe/pm/__main__.py
- pm.sh, Makefile, pyproject.toml
- tests for these (tests/test_pipeline*.py, tests/test_ledger*.py, tests/test_audit.py, tests/test_orca*.py, tests/test_receipts*.py, tests/test_main*.py)

### Batch D: report, credibility, what-if, emulator, acceptance
Findings: M-3 (credibility side), M-4 (Trace), M-5 (print withheld), M-6 (what-if side), M-7 (what-if/report side), M-8 (report line), M-9, M-15 (wording), M-16, M-17, M-18, M-19, M-24 (`whatif.apply`), M-25 (acceptance), M-31, M-35 (`LIMITATIONS` text).
Files owned:
- cafe/pm/report.py
- cafe/pm/credibility.py
- cafe/pm/whatif.py
- cafe/pm/emulator.py
- cafe/pm/acceptance.py
- tests/golden/*
- tests for these (tests/test_report*.py, tests/test_credibility*.py, tests/test_whatif*.py, tests/test_emulator*.py, tests/test_acceptance*.py)

### Batch E: budget, throughput, stage 3, sub-grid, DTMB
Findings: M-3 (recipe check), M-5 (cut handling in the window writer), M-7 (planner), M-8 (CPU LES skip), M-25 (docstring), M-26, M-33 (planner side).
Files owned:
- cafe/pm/budget.py
- config/throughput.json, config/subgrid.json, bench/*
- config/assumptions.yaml (added: `stage3.*` keys only; `reach.*` stays untouched, batch D handles M-19 in code)
- cafe/pm/stage3/*.py (refit.py, windows.py, pipeline_windows.py, nest.py, lbm.py, wallmodel.py, freesurface.py, fluidx3d.py)
- cafe/pm/env/subgrid.py
- cafe/pm/dtmb5415.py, cafe/pm/vv.py
- tests for these (tests/test_budget*.py, tests/test_stage3*.py, tests/test_refit*.py, tests/test_subgrid*.py, tests/test_dtmb*.py, tests/test_vv*.py)
- `make bench` on homebase is a separate step for when the box is idle; the builder must not start it now. After the DTMB v4 study finishes, copying its results to `/data/dtmb5415` and moving the v3 files aside is a manual step by the lead, not a builder task.

Cross-batch interfaces to respect:
- M-1: C writes `wind_speed_bias` / `wind_direction_bias` (persistent part) and, new, `wind_speed_noise` / `wind_direction_noise` (`value` sd, `tau_h`) into `ingest/priors_fitted.json`; B reads the noise keys only if present.
- M-3: E keeps `dtmb5415.tabulate(root)` unchanged and adds `stale_files(root) -> list[str]`; D's `_dtmb_rows` calls it for the "not run" reason.
- M-4: C writes `runs/receipts.meta.json` (`code_digest`, `git_sha`, `made_at`) and keeps `runs/receipts.json` a list; D's `Trace` reads the meta file and compares the digest with the run's.
- M-5: E writes `cut: true`, `ok: false` and a `machine_dependent` block (measured values) for a cut window and keeps `run_steps`, `planned_steps`, `cut_reason`; D prints "withheld" and does not read `machine_dependent`; C's `_dump` is unchanged.
- M-6: C adds `GriddedEnv.use_3d` (default True) and widens `_sortie_hours`; D sets `use_3d = False` for UAS candidates and their base inside `flip_search` and the emulator variants; B stores the 3-D-use fraction in the stage-1 summary; D prints it.
- M-7: E defines `budget.EMULATOR_MIN_POINTS = 100`; D's `whatif.MIN_ROWS` reads it.
- M-8: E adds `plan["stage3"]["les"]["reachable"]` and `skip_reason` per window; D's report prints them; C's `stage_held_its_wall_clock_share` check stays valid for the windows that run.
- M-11: B records fail mode `left_data` per member (first record outside); C adds the `members_inside_data` ledger check; D's report treats any mode name generically and gives `left_data` a sentence.
- M-12: B returns `res["seeds"]` from `run_batch`; C's `common_random_numbers` check compares them; A deletes `sampling.crn_check` only after C stops calling it.
- M-13: C's `Context(..., budget_name=None)` for `fetch`; no other batch calls `Context` with a plan for fetch.
- M-15: B adds the optional `X` argument to `sensitivity_case`; C passes `res["X"]` and the run's own n.
- M-24: B's `launch_times` signature does not change; D's `whatif.apply` and A's `config.py` refuse the same bad inputs with the same wording.
- M-25: D's acceptance runs `fetch` then times `run`; C adds the cold-fetch note to the ingest ledger (`cold fetch: N parts, X s`).
- M-30: C maps non-finite values to null in `_dump` and `ledger.py`; D's report treats a null `limit` as "no limit".
- M-35: A writes the limitation texts; D copies them into `credibility.py` unchanged.
