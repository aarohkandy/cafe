# Round 1 merged findings (BRIEF 5.6 step 2)

Inputs: reviewer_a.md (28 findings), reviewer_b.md (25 findings). Merged to 33 findings, M-1 .. M-33. Every source id appears in exactly one merged finding.
Each claim was checked by reading the cited code and, for run-based claims, the `q1` files (`plan.json`, `stage3/windows.json`, ledgers, `report.json`, `credibility.json`). Nothing was run on homebase. Two numeric claims were re-run locally with numpy only (noise floor, M-23).

Severity: 1 critical, 16 major, 16 minor. Status: 30 confirmed, 3 partly, 0 not confirmed.

Ranking inside a severity: what changes a verdict or a number printed in the report comes first.

Fix lane: "code" = the code can do better with the inputs and compute available. "wording" = the physics or data cannot be had here (no GPU, no lab data, no CAD), so only the claim can change. "code + wording" = both.

---

## Critical

### M-1. Receipts are file hashes and one vacuous check; failing numbers carry an "ok" receipt; the page says every number links to a passing receipt   (sources: B-1, A-9)
severity: critical / status: confirmed / lane: code + wording
where: cafe/pm/report.py:75-90 (`Trace.ref`), :130-150 (`check_traceability`), :872 (banner); cafe/pm/pipeline.py:271 (`ocean_source_covers_box`), :552; cafe/pm/stage3/pipeline_windows.py:634-641
claim: A number's receipt is the sha-256 of a stage output (297 of 334 leaves) or a config hash (27); the 10 that cite a check cite a check that cannot fail. An `output` receipt is always `ok=True` even when the output is `windows.json` in which 6 of 6 windows failed. No verdict cites a model receipt from `runs/receipts.json`. The banner reads as "passing".
check: `Trace.ref` sets `ok=True` for `output` and `config` rows (report.py:84-89) and `check_traceability` only tests `r["ok"]` (:148). `ocean_source_covers_box` is `oc is not None` (pipeline.py:271): it fails only if the store is missing and never compares the box with the waypoints. `grep receipts.json cafe/pm/report.py credibility.py audit.py` is empty. Banner text at report.py:872. q1 stage-3 ledger is `ok: true` with 4 bookkeeping checks while every window row is `ok: False` (windows.json).
fix: (1) make an `output` receipt carry the output's own quality bit (for `windows.json` ok only if some window passed; the others stay True) and reword the banner to "every number links to a hashed ledger output or check; a link is provenance, not a pass"; (2) make `ocean_source_covers_box` compare the store box with the box and waypoints; (3) add a receipts-table row per physics group (`runs/receipts.json` group ok/fail count) and have each vehicle verdict cite its class group. Files: cafe/pm/report.py (batch D), cafe/pm/pipeline.py (batch C, keep the check name `ocean_source_covers_box`).

---

## Major

### M-2. USV speed prior may be applied on top of a current-coupled model that is already below the calibration target   (sources: A-5)
severity: major / status: partly / lane: code (needs a DECISIONS row)
where: config/perturbations.yaml:69-76 (`usv_vpp_bias` uniform [-0.35, -0.30]); cafe/pm/stage1.py:87; cafe/pm/physics/usv.py:456, 606-620; docs/PHYSICS.md:650-672; platforms/saildrone_explorer.yaml:86; BRIEF 2.1 line 109
claim: Bias -0.30..-0.35 is applied as a multiplicative speed factor (0.65-0.70) to a model that already solves the current inside the VPP. The repo's own receipt (PHYSICS.md:650) puts the model at 0.164 vs Chiodi 0.178, -7.6 % at b = -0.30. The factor that reproduces Chiodi would be near 0.76. USV NO-GO 31/32 follows.
check: holds in part. The factor application and the receipt number are in the code and docs (usv.py:456 `fac = 1 + bias`; PHYSICS.md:650 "0.164 against Chiodi's 0.178, -7.6 %"). BRIEF line 109 says "solve ... current inside the VPP (Sun et al. ...: still-water VPPs overpredict SOG by 30-35 %)" and line 117 says "VPP bias -30 %", so the code follows the brief's literal text. Not established: that this is a "unit-conversion error", and that b = 0 or the calibrated b would change the verdict (no such run exists).
fix: Decide and record in DECISIONS: either calibrate the prior so the model reproduces the Chiodi SOG ratio (`mean_sog` receipt picks b, brief range kept as the spread of the observed overprediction applied to the still-water speed only) or keep the brief's value and add a sensitivity row to the report (USV verdict at b = 0 and at the calibrated b, same seed, 32 members, about 30 s on 1 CPU). Files: config/perturbations.yaml, cafe/pm/physics/usv.py, platforms/saildrone_explorer.yaml (batch B); the report row is in M-30 (batch D); PHYSICS.md text via batch A.

### M-3. Stage-3 UAS "worst window" is chosen at an hour when the UAS is on deck   (sources: A-4, B-4)
severity: major / status: confirmed / lane: code
where: cafe/pm/pipeline.py:405-440 (`s_windows`, UAS branch at 428-429); cafe/pm/stage3/pipeline_windows.py:250-270; cafe/pm/stage1.py:232 (`airborne` is in the result)
claim: The 10 m wind maximum is searched over all records, not over `airborne` ones. In q1 the UAS window is 2023-03-02 16:00Z (05:00 local, ship position), with v_rel 16.2 m/s and tilt 41.97 deg, and the LES diverges (mach_max 7.4).
check: `s_windows` never reads `r["airborne"]` (`grep airborne cafe/pm/pipeline.py` empty); `stress[ok] = hypot(u10)` for the UAS at :428-429. windows.json uas: `t = 1677772800`, `lon -165.0, lat 0.0`, `kinematics` as stated, `heading_source: relative-flow direction (no stage-1 track)`, mach_max 7.399.
fix: For class `uas`, set `ok &= airborne[:, sel]` before taking the max (fall back to all records with a stated reason if no member is airborne); clip the leg speed so v_rel stays within `limits.max_airspeed_ms`. Add the BRIEF 5.5 argmax assertion for the chosen windows (see M-12). Files: cafe/pm/pipeline.py (batch C); `uas_case` clip in cafe/pm/stage3/pipeline_windows.py (batch E).

### M-4. Stage 1 drops UAS sorties when `every_days` < 1   (sources: A-1)
severity: major / status: confirmed / lane: code
where: cafe/pm/stage1.py:~94-100 (`launch_times`); cafe/schemas/mission.json:54 (`every_days` exclusiveMinimum 0); feeds cafe/pm/pipeline.py:346 (`_sortie_hours`)
claim: The count of schedule slots is in days but is multiplied by `every_days`, so the schedule spans only (days + 3) x every_days.
check: `ts = day0 + off + 86400.0 * every_days * np.arange(int((T - day0) / 86400.0) + 3)`: for every_days = 0.5 over 6 days, 9 slots x 0.5 d = 4.5 d. A's counts (9 launches, last 03-05 13:00) follow.
fix: `np.arange(int((T - day0) / (86400.0 * every_days)) + 3)`. One test with every_days 0.5 and 0.25 asserting the last launch is within one period of the window end. File: cafe/pm/stage1.py (batch B).

### M-5. n = 73 certifies with the Wilson bound but the interval applied above n = 40 is Agresti-Coull   (sources: B-5)
severity: major / status: confirmed / lane: code
where: cafe/pm/stats/intervals.py:28 (`SWITCH_N = 40`), :64-75 (`interval`), :78-82 (`n_certify`), :111-114 (`interval_region`); cafe/pm/stats/sequential.py `ensemble_stop`
claim: With zero failures the upper bound is 0.0876 at n = 40, 0.1021 at n = 41 and 0.0599 at n = 73 (Agresti-Coull), against 0.0500 for Wilson at 73. The "decided GO" region flips at n = 41 and the certify statement disagrees with the printed interval between n = 41 and 88.
check: arithmetic from `agresti_coull`: z^2 = 3.84, pt = 1.92/76.84 = 0.0250, half-width 1.96 x sqrt(0.025 x 0.975 / 76.84) = 0.0349, upper 0.0599. `n_certify` is the Wilson zero-failure solve (73).
fix: Use Wilson at every n in `interval` (remove the switch; Brown-Cai-DasGupta's own coverage plot has Wilson fine at n > 40) so the interval, `interval_region`, `ensemble_stop` and `n_certify` agree and BRIEF's 73 holds. Update the Agresti-Coull coverage receipt, which stays valid as a function. File: cafe/pm/stats/intervals.py and its tests (batch A).

### M-6. "What would fix it" says no single change reaches the target when 0 to 3 candidates were evaluated   (sources: B-2, A-7)
severity: major / status: confirmed / lane: code
where: cafe/pm/whatif.py:436-486 (`flip_search`, `FALLBACK_K = 3`); cafe/pm/report.py:648-649; cafe/pm/pipeline.py:569-571
claim: usv and uas get no Stage-1 fallback because glider_eq (first in mission order) spends the whole share; the report still prints "no single change among the 16 (18) candidates reaches ...".
check: `spent` is shared across vehicles (whatif.py:446, :470-476) and vehicles iterate in mission order; the report text at :648-649 uses `len(f['tried'])` without counting evaluated ones. q1 index.html shows the text for usv (16), uas (18), glider_eq (18, 3 evaluated); design.json `flip_spent_s` 228.19 of share 240.
fix: split `budget_s` equally over the non-GO vehicles inside `flip_search` (signature unchanged); store `evaluated` count per vehicle in `flip.json`; in the report say "none of N candidates could be evaluated" when evaluated = 0 and "none of the M evaluated (of N) reaches" otherwise, and do not count candidates that are structurally invalid in N. Files: cafe/pm/whatif.py, cafe/pm/report.py (batch D).

### M-7. `--budget` does not hold: the planner never shrinks or refuses below one 32-member batch, and its cost model is a contended, different-mission measurement   (sources: A-6, B-6, B-7)
severity: major / status: confirmed / lane: code (re-measure needs homebase idle)
where: cafe/pm/budget.py:85-86 (`n_batches = int(...)`, `max(n_batches, 1)`), docstring lines 9-10; config/throughput.json `stage1.*` (load_1min 32.85, mission ci_fixture.yaml, sizes [8, 32])
claim: q1 plans stage 1 at 562 s against a 540 s share, forces one batch, measured stage 1 is 148 s. A 30-day window plans 2809 s with no refusal; 12 gliders plus usv and uas plan 1322 s. The emulator then gets 0 variants.
check: plan.json: n_max 32, note "502 s per batch of 32 + 1.88 s per member"; stage1 ledger wall_s 148.012; design.json variant_s 561.8 and no variants. throughput.json stage1 entries carry `load_1min: 32.85`, `mission: missions/ci_fixture.yaml`. Code at :85-86 as quoted. No stage-1 wall check in pipeline.py (only `stage_held_its_wall_clock_share` for stage 3).
fix: (1) planner: when one batch does not fit, shrink the batch (16, 8), then set `plan["over_budget_s"]` and a `notes` line "predicted X s against a share of Y s", and raise `PlanError` only for `ci`; (2) planner warns when the throughput entry's `load_1min` exceeds `cpus` and `bench` refuses to write a stage-1 entry above that load; (3) re-run `make bench` on the demo mission when homebase is idle, otherwise keep the stale rates and say so in the plan. Files: cafe/pm/budget.py, config/throughput.json, bench/ (batch E). RUNBOOK troubleshooting row via batch A.

### M-8. Emulator training rows are keyed by run directory and stale-code rows are never filtered; the hold-out is a random row split   (sources: B-10, A-14)
severity: major / status: confirmed / lane: code
where: cafe/pm/whatif.py:242 (`key=f"{run_id}|{vid}|{variant}"`), :268-274 (`add_rows`), :46, :324 (`MIN_ROWS = 100`), :351-357; cafe/pm/emulator.py:208-214 (`holdout_report`); cafe/pm/pipeline.py:516
claim: Reruns of one mission count as new data (identical features), rows made by superseded code stay, and the 80/20 permutation puts copies of one point on both sides, so RMSE and coverage are optimistic and the 100-row gate can be reached with one design point.
check: key contains `run_id` (derived from the run directory path); `grep code_digest\|git_sha cafe/pm/whatif.py cafe/pm/emulator.py` hits only the docstring at whatif.py:11; `holdout_report` permutes row indices at random (emulator.py:210).
fix: key rows by a hash of (vehicle, variant, features, targets' mission digest) so a rerun replaces its predecessor; drop rows whose `code_digest` differs from the current one when training (keep them in the file); count `MIN_ROWS` on distinct feature points; make `holdout_report` split by distinct feature point (group split). Files: cafe/pm/whatif.py, cafe/pm/emulator.py (batch D). The `meta` fed by pipeline.py already holds run_id, git_sha and code_digest, so pipeline.py is not touched.

### M-9. Stage-3 label says coefficients are "blended with the Hangar values and their spread widened", and the backend is named XLB; the refit does neither and its spread collapses to ~0   (sources: A-15, B-8, A-18)
severity: major / status: confirmed / lane: code + wording
where: cafe/pm/budget.py:95-99 (`backend` "xlb-jax-cpu", `label`); cafe/pm/stage3/refit.py:25-45, 56; cafe/pm/stage3/windows.py:156-181 (`coefficients`, `cd_spread`); DECISIONS 76
claim: `grep blend cafe/pm` hits only the label. `refit` pools `cd / cd_hangar` with DerSimonian-Laird; with one window per vehicle (ci, quick) tau^2 = 0 and sigma is the batch-means SE of one run: glider_eq cd 1.962, spread 0.000345, sigma 0.00114 (0.02 %). The rate comes from the `jax-lbm-d3q19-cpu` bench entry (BGK + Smagorinsky), not XLB, and windows report `source: native-nest`.
check: budget.py:98-99 label text and :95 backend name as quoted; throughput.json `jax-lbm-d3q19-cpu` note "BGK + Smagorinsky, periodic streaming by roll"; windows.json every row `source: native-nest`; refit.py `_multiplier` returns `sqrt(se^2 + tau2)`; `blocks` + `/ sqrt(nb)` in windows.py:179-181 is a within-run SE over 5 blocks.
fix: wording: label becomes what the code does ("CPU fallback: native JAX lattice kernel at the resolution this budget affords; coefficients are the pooled window coefficient over the vehicle's Hangar-model value"); backend name `native-jax-cpu`. Code: with fewer than 2 windows, floor the refit sigma at a stated between-window fraction (a labelled-assumed default in `budget.stage3_assumptions()`, not a new key in config/assumptions.yaml, which no batch owns) and add the discretisation term from the sphere/DTMB GCI. Files: cafe/pm/budget.py, cafe/pm/stage3/refit.py, cafe/pm/stage3/windows.py (batch E); docs via batch A.

### M-10. UAS refit multiplier divides frame-only LES drag by total drag including rotor momentum drag   (sources: B-9)
severity: major / status: confirmed / lane: code
where: cafe/pm/stage3/pipeline_windows.py:263-270; cafe/pm/stage3/refit.py:56; cafe/pm/stage1.py `refit_drag`
claim: A passing UAS window would yield drag multiplier ~0.2 and `refit_drag` applies it unchanged to the UAS total drag.
check: `cd_hangar_source` says "includes the rotor momentum drag, which the window (no rotors) does not; the ratio therefore reads as 'frame drag / total drag'"; cd_hangar 5.04 in windows.json. `refit_drag` for UAS returns `r["mean"]` times a lognormal factor, no frame/rotor split. Latent in q1 (the UAS window failed).
fix: give `uas_case` a frame-only reference (d_x split into frame and rotor parts in the platform file, or the frame share set to the assumed fraction) so `cd_hangar` is comparable; until then mark UAS windows `usable_for_refit: False` with that reason. Files: cafe/pm/stage3/pipeline_windows.py, cafe/pm/stage3/refit.py (batch E). `refit_drag` in stage1.py needs no change if the multiplier is then frame/frame; if the builder wants a change there, route it to batch B.

### M-11. Mission keys the lab is told to edit are accepted and ignored: `verdict.go/nogo`, `atmosphere.*`, `waves.*`, `restart_spectra`, `sorties.pattern`   (sources: A-2, A-3, B-3)
severity: major / status: confirmed / lane: code (thresholds) + wording (paths for data the build cannot read)
where: cafe/pm/config.py:93; cafe/pm/stats/intervals.py:25-27, 94-101; cafe/schemas/mission.json:26-27, :54; cafe/pm/pipeline.py:230-234; cafe/pm/env/orca.py:25; missions/tepex_c_demo.yaml:51; QUESTIONS_FOR_LAB.md items 3, 5, 9
claim: `validate` says valid, results do not change.
check: `grep` of `local_wrf|local_umwm|restart_spectra|"pattern"|"atmosphere"|"waves"|"verdict"` in cafe/pm finds only config.py:93 (order check). Thresholds are the constants `P_FAIL_GO = 0.10`, `P_FAIL_NOGO = 0.40`, `LO_SUCCESS_GO = 0.75` (intervals.py:25-27). Only `ocean` and `subgrid` mission keys are read.
fix: Thresholds: derive `P_FAIL_GO = 1 - go`, `P_FAIL_NOGO = 1 - nogo` from the mission through one setter called by `config.load_mission` (mutation-safe: the demo must still give 0.10/0.40); add range checks (0 < nogo < go <= 1). Keys with no reader in this build (`local_wrf`, `local_umwm`, `path` on atmosphere/waves, `restart_spectra`, `pattern` other than `flux_profile`): `load_mission` raises `ConfigError` naming file, key and the one working route (`CAFE_ORCA`). QUESTIONS_FOR_LAB items 3, 5 and 9 reworded to match. Files: cafe/pm/config.py, cafe/schemas/mission.json, cafe/pm/stats/intervals.py (batch A); QUESTIONS_FOR_LAB.md (batch A).

### M-12. Brief-required ledger self-checks are absent; helper functions exist and are never called   (sources: A-8, B-11)
severity: major / status: confirmed / lane: code
where: cafe/pm/pipeline.py:172, 264-295 (ingest), 360-372 (hangar), 439 (windows), 479 (refit), 551-567 (emulator); cafe/pm/stage1.py:419-425; cafe/pm/stats/sampling.py:110 (`marginal_report`), :133 (`crn_check`); cafe/pm/env/environment.py:207 (`ustar_umwm`); docs/BRIEF.md 5.5
claim: ingest has 7 presence-type checks, stage 1 one (LHS), windows one, refit one, stage1b none. Missing: swh of the synthesised spectrum vs file, COARE u* vs UMWM `ust` agreement, NaN in sea cells, direction round trip, CRN, energy/|H| drift, failure-mode coverage, Wilson vs statsmodels, window argmax assertion.
check: q1 ledgers: ingest `['orca_present','tao_present','gebco_present','ocean_store_present','orca_hours_cover_window','ocean_source_covers_box','tao_moorings_compared']`, stage1 `['lhs_stratified_batch1']`, stage1b `[]`. `grep crn_check|marginal_report|ustar_umwm cafe tests` shows no caller outside tests and the definition.
fix: add the checks in pipeline.py using results the stages already write (call `crn_check`/`marginal_report` from `_stage1` on the merged batch; compute u*-vs-`ust` over the cached grid at ingest; assert window argmax in `s_windows`; record the actual agreement as `value`). Checks that need a physics number stay honest: where the build cannot compute one (GOFS in-situ flag from file attributes only) record `value=None` and `note`. Files: cafe/pm/pipeline.py (batch C); sampling.py unchanged (batch A owns it if it must change).

### M-13. Bellhop is never used by the pipeline, and the acoustic range ignores depth   (sources: A-10, B-13)
severity: major / status: confirmed / lane: code
where: cafe/pm/stage1.py:318-319, 338 (`comms.acoustic_link(d, modem, band, wind)`); cafe/pm/physics/comms.py:236-270
claim: `ssp` is never passed, so every ambiguous link (|margin| <= `ambiguous_db`) gets "Thorp only, no sound-speed profile supplied". Ground range is used for a submerged glider.
check: comms.py:257-267 branch `ssp is not None`; stage1.py:338 passes no `ssp`, tx/rx depth or water depth; `_pos` returns depth (:296) but it is unused. In q1 no link is ambiguous (margins -2011 and -2290 dB), so the gap is invisible.
fix: build `(z, c)` from the GOFS T/S column at the link midpoint (the environment already holds ocean T/S), pass `tx_depth`/`rx_depth` from `_pos` and the GEBCO depth, and use slant range. Add a test with a link engineered to be ambiguous. Files: cafe/pm/stage1.py, cafe/pm/physics/comms.py (batch B).

### M-14. orca cache reuse ignores the box and the 3-D hours   (sources: A-11, B-12)
severity: major / status: confirmed / lane: code
where: cafe/pm/pipeline.py:74, 232-235 (`orca_covers`), 339-342 (`_covers`); cafe/pm/env/orca.py:~305 (manifest)
claim: Cache directory is `DATA/cache/<mission name>`; `_covers` compares only `t0`/`t1`. A widened box or changed sortie time reuses the old orca cut.
check: `_covers(d, t0, t1)` returns `f(d["t0"]) <= t0 and f(d["t1"]) >= t1` and nothing else (:339-342). The TAO and ocean stores do compare the box. Not run (reading is enough).
fix: write `box` and the sorted `hours3d` into the orca manifest, compare them in `orca_covers` (box must contain the requested padded box; hours3d must be a superset), refetch otherwise. Files: cafe/pm/pipeline.py, cafe/pm/env/orca.py (batch C).

### M-15. The resume/config hash does not cover `cafe/*.py`, which the pipeline imports   (sources: A-12)
severity: major / status: confirmed / lane: code
where: cafe/pm/pipeline.py:47-54 (`code_digest`); imports in stage3/freesurface.py, stage3/windows.py, dtmb5415.py, physics/uas.py, report.py
claim: A change in `cafe/cfd.py`, `cafe/fea.py`, `cafe/emulator.py`, `cafe/reach.py` or `cafe/receipts.py` leaves the hash unchanged, so `--resume` reuses stage-3 output made by older code.
check: `code_digest` hashes `cafe/pm/**/*.py`, `config/*`, `platforms/*.yaml` only (:50-51).
fix: hash `cafe/**/*.py` (excluding `__pycache__`, `site`) and the installed versions of jax, numpy, scipy (`ledger.versions()`). Files: cafe/pm/pipeline.py (batch C). Note this invalidates every stored resume once; say so in the changelog.

### M-16. Stage 3's second job (recalibrate the sub-grid layer and write `config/subgrid.json`) is not implemented   (sources: A-13)
severity: major / status: confirmed / lane: code + wording
where: config/subgrid.json (`calibration.source_run: null`); cafe/pm/env/subgrid.py:9-10, 53-57; docs/BRIEF.md 2.2; docs/PHYSICS.md:306
claim: Nothing writes `calibration`; no stage-3 check compares an LES spectrum, sigma_u/u* or gust statistic with the Mann/gust layer. Not listed as open in STATUS, DECISIONS or QUESTIONS_FOR_LAB.
check: `grep subgrid.json\|source_run cafe/pm` shows readers only (subgrid.py:8-10, :39, :55). subgrid.json's note says "what Stage-3 LES overwrites".
fix: code: add `subgrid.recalibrate(series_by_window)` that fits sigma_u/u* and the length-scale factor from resolved nest series and writes the calibration block with `source_run`; test it on a synthetic series. It cannot produce a real calibration here (every CPU window fails its checks), so also wording: the report prints "sub-grid layer uncalibrated: no LES window passed" and the open item goes into STATUS and DECISIONS. Files: cafe/pm/env/subgrid.py, config/subgrid.json (batch E); wording via batch A and the report line via batch D.

### M-17. STATUS.md and CREDIBILITY.md describe a different code base; BRIEF 0's gap statement and the blind-RUNBOOK run are missing   (sources: A-16, B-16)
severity: major / status: confirmed / lane: wording (docs)
where: STATUS.md (dated 2026-10-28; line 77 "missing: `run_premission` ... entry point", line 20 "Saildrone ... missing", line 102 "6-11 not started"); docs/CREDIBILITY.md:3, 140, 142; DECISIONS.md rows 80 vs 104; CHANGELOG ("RUNBOOK, first draft")
claim: STATUS says the tool does not exist; CREDIBILITY says the wall-model check takes the better error (code takes the worse), that `warm_layer`/`rain_lens`/`ocean_sde` are not read and `bulk_stress_scale` is applied by nothing, and is "written against bb68642". DECISIONS 80 says "smaller", 104 says "worse".
check: `wallmodel.stored_wall_error` returns `max(...)` (wallmodel.py:348); `subgrid.switch(e, "warm_layer"/"rain_lens")` at pipeline.py:94, `ocean_sde` at stage1.py:257, `bulk_stress_scale` applied at stage1.py:59, 205; STATUS lines as quoted; no top-of-file gap statement.
fix: rewrite the stale rows from the code; add the BRIEF 0 gap statement at the top of STATUS.md (input, one command, interim output per missing lab input, from QUESTIONS_FOR_LAB); fix DECISIONS 80; record the blind RUNBOOK run once done (needs a fresh agent, not this review). Files: STATUS.md, docs/CREDIBILITY.md, DECISIONS.md, CHANGELOG.md (batch A).

---

## Minor

### M-18. Two confidence levels in one sentence, and numbers in decision text are untraced   (sources: B-19, A-23)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stats/intervals.py:94 (`verdict(conf=0.90)`); cafe/pm/stats/sequential.py `STOP_CONF = 0.95`; cafe/pm/report.py:152-173 (`_undecided`, `_stat`, `certify_statement`), :889-892 (`check_rendered`)
claim: The printed interval is the 90 % Wilson (glider_eq 0.147 to 0.392) next to a sentence about the 95 % interval (0.133 to 0.421) that "spans the NO-GO threshold of 0.40". The thresholds, 95 % bounds, "3/n" and "73 members" exist only inside strings with no ledger node; `check_rendered` is a substring test.
check: `_stat` builds `unc` from `v["conf"]` (0.90) while `_undecided` calls `intervals.interval(k, n, STOP_CONF)` (0.95). `_walk` yields only numeric JSON values, so numbers inside strings are invisible to both checks.
fix: print one stated interval per sentence (state the level in the label for both) and make the 95 % interval a traced node (`p_fail.interval_95` with receipt) while the strings only restate it; make `check_rendered` match whole numeric tokens. Files: cafe/pm/report.py (batch D).

### M-19. Sentinel link margins are printed as physical dB   (sources: A-24, B-15)
severity: minor / status: confirmed / lane: code + wording
where: cafe/pm/physics/comms.py:36, 92-97 (`NO_LINK_DB = -200`); cafe/pm/stage1.py:316 (`np.where(ok, 1.0, -1.0)`), :402 (`margin_db_median`)
claim: "usv-uas-rf median margin -200 dB" (beyond horizon), "usv-shore-iridium 1 dB" (success flag), acoustic "-2011 dB" (Thorp extrapolated to 555 km). The RF NO-GO is a consequence of ship geometry and is not explained.
check: the three expressions are as quoted; `rf_margin` returns `NO_LINK_DB` where `d > horizon` (and for NaN `d`, the comparison is False, so NaN also scores as -200).
fix: stage1 summary reports the median only over physically valid samples, plus `frac_beyond_horizon`/`frac_out_of_range` and a `margin_kind`; Iridium reports success fraction, no margin; NaN positions are excluded from `need`. Wording: the demo mission places both gliders 555 and 598 km from the ship against a 4 km modem, so the acoustic NO-GOs are by construction (Q12 already covers it; add the RF case). Files: cafe/pm/stage1.py, cafe/pm/physics/comms.py (batch B); report display is unchanged if the field is `None`; QUESTIONS_FOR_LAB text via batch A.

### M-20. y+ check passes at 97 % in a row whose y+ estimate is 1370, because it is evaluated with the inflated lattice viscosity   (sources: B-18)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage3/windows.py:188-205 (`stage3_checks`, `yplus_in_30_300_fraction`)
claim: The pass reads as a validated wall model while the physical viscosity is 27 to 300 times lower.
check: windows.json glider_eq: `y_plus_estimate 1369.66`, `nu_lat 1e-4`, `nu_lat_physical 3.698e-6`, `yplus_in_30_300_fraction 0.968 ok`; `viscosity_floor` fails separately in the same table. Same for glider_2n (0.973), usv hull (0.949).
fix: when `viscosity_floor` is raised, report the y+ fraction row with `note="evaluated at the raised lattice viscosity, not the physical one"` and set its `ok` False (the window is not at the physical Reynolds number); do not count it as a wall-model pass. File: cafe/pm/stage3/windows.py (batch E).

### M-21. Windows that were not run show "failed its self-checks:" with an empty reason   (sources: A-17)
severity: minor / status: confirmed / lane: code
where: cafe/pm/report.py:436-453 (`why = "failed self-checks: " + ", ".join(failed)`), :770-780 (`_window_html`); docs/RUNBOOK.md troubleshooting row 4
claim: The USV `hull_fs` row has `checks == []` and an `error` string; the page prints an empty list.
check: windows.json usv hull_fs: `ok: False`, `checks` absent/empty, `error: "free-surface window not run: estimated 94 min x 1.25 ..."`; report.py builds `failed` from `checks` only.
fix: use `w.get("error")` as the reason when set and append it to `why`; render it in `_window_html`. File: cafe/pm/report.py (batch D).

### M-22. "The flip search ran 228.2 s of Stage 1" is a planned charge; the emulator never trains at quick   (sources: B-20, A-25)
severity: minor / status: confirmed / lane: wording + code
where: cafe/pm/report.py:826; cafe/pm/pipeline.py:570-571; cafe/pm/whatif.py:476-481; cafe/pm/budget.py `emulator_plan`, `TRAIN_FRAC`, `EMULATOR_VARIANTS`
claim: The emulator stage's measured wall time is 65.4 s; 228.2 s is `batch_cost_s` charged for 3 fallbacks. At quick the variant cost (561.8 s) exceeds 0.7 x 240 s, so 0 of the advertised 6 variants run.
check: report.py:826 text as quoted; emulator ledger wall_s 65.4; design.json variant_s 561.8, share_s 240, variants `[]`, flip_spent_s 228.19.
fix: wording: "was charged 228 s of planned Stage-1 cost (the stage itself took 65 s)". Code: with M-7's re-measured costs a variant costs about 148 s and one variant fits; also state in the quick plan and report that the emulator cannot train at this budget (the "EMULATED" badge only when trained). Files: cafe/pm/report.py (batch D); planner side is inside M-7 (batch E, budget.py).

### M-23. `noise_floor` docstring says ~0.3 at 32 members; it is 0.53-0.60, so no first-order index can be named at quick   (sources: A-19, B-21)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stats/sensitivity.py:15-39 (`harmonics = 6`, docstring at :35); callers cafe/pm/stage1.py:392, 399
claim: With M = 6 harmonics and N = 32, lam = 0.375 and the null 95 % quantile of max S1 is about 0.55-0.60.
check: re-run locally (numpy only): mean noise floor over 5 seeds, x uniform (32, 10), y with 4, 8, 16 ones: 0.595, 0.556, 0.535. With `harmonics=2` the floor is 0.30, `harmonics=3` 0.39.
fix: default `harmonics = min(6, max(2, n // 16))` inside `first_order`/`noise_floor`/`dominant` (callers unchanged) and correct the docstring with the measured floor. File: cafe/pm/stats/sensitivity.py (batch A).

### M-24. Credibility table prints the wrong value for three or more perturbation priors   (sources: A-20)
severity: minor / status: confirmed / lane: code
where: cafe/pm/credibility.py:113-116 (`value=repr(e.get("value"))`); config/perturbations.yaml:28-33, 69-76
claim: `current_correlation_length` shows "0.0" (setting is `mean: 100000.0`), `usv_vpp_bias` "0.0" (draw is uniform [-0.35, -0.30]), `wind_speed_bias` 2.0 and `wind_direction_bias` 15.0 although the run used TAO-fitted values.
check: q1 credibility.json `assumed_inputs`: `current_correlation_length 0.0`, `usv_vpp_bias 0.0`, `wind_speed_bias 2.0`, `wind_direction_bias 15.0`. YAML header says `value` is the spread and unused for uniform.
fix: print the distribution (`dist`, `mean`/`median`, `value` as sigma, `lo`/`hi`) instead of `value`, and add the TAO-fitted override from the run's `summary.json priors` when present. File: cafe/pm/credibility.py (batch D).

### M-25. Ledger gaps: versions "?" for pycoare and mannrs, missing outputs dropped, no dirty-tree flag   (sources: A-21, B-23)
severity: minor / status: confirmed / lane: code
where: cafe/pm/ledger.py:28-40 (`git_sha`, `versions`), :89 (`... if pathlib.Path(p).is_file()`); pm.sh:8 (`CAFE_GIT_SHA=$(git rev-parse HEAD)`)
claim: q1 ledgers hold `pycoare: "?"`, `mannrs: "?"`; an `output()` for a file never written is silently dropped; the SHA is HEAD whether or not the tree is dirty, so q1's `62688c3` does not identify the code (the reviewed tree has uncommitted edits).
check: stage-1 ledger of q1: versions pycoare `?`, mannrs `?`; ledger.py:89 filter as quoted; no dirty field in `Ledger.d`.
fix: `importlib.metadata.version(name)` as fallback to `__version__`; raise in `__exit__` when a registered output is missing; add `git_dirty` (from `git status --porcelain`, or `CAFE_GIT_DIRTY` passed by pm.sh) and `code_digest` to every ledger. Files: cafe/pm/ledger.py, pm.sh (batch C).

### M-26. `audit` does not re-hash directory inputs and only verifies a run where it was made   (sources: A-22)
severity: minor / status: confirmed / lane: code
where: cafe/pm/audit.py:39-68 (`ledger_problems`)
claim: Inputs that are directories (the 5.1 GB ocean `.zarr`, orca per-hour npz) are skipped by `f.is_file()`; output paths and chain refs are absolute strings, so a moved run reports every output missing and the chain broken.
check: `if i.get("sha256") and f.is_file() and sha256(f) != i["sha256"]` (:57); `str(prev) not in {i["ref"] ...}` (:65).
fix: resolve ledger paths relative to the audited run directory when the absolute path does not exist; hash directories by the same manifest rule the ledger used (or accept the recorded `manifest_sha256` and compare to the store attribute). Files: cafe/pm/audit.py (batch C).

### M-27. Mission validation gaps surface as deep crashes or silent acceptance   (sources: A-26, B-14)
severity: minor / status: confirmed / lane: code
where: cafe/pm/config.py:60-95 (`load_mission`); cafe/schemas/mission.json:52-61; cafe/pm/stage1.py:305-345
claim: Accepted: ship or UAS base outside the box; `radio`/`modem` names not in the registries; a self-link (`a == b`); `when: uas_airborne` without a UAS end or `surfacing` without a glider end (KeyError `'ship'`/`'shore'` in stage 1); `local_solar_time: "25:99"`; `altitudes_m: []` (NaN crash at subgrid.py:144); `required_fraction: 0`; one-point USV section.
check: config.py box check covers only `deploy`, task waypoints and the station point (:70-79); links check only that the endpoints exist and the key is present (:86-92); schema pattern is `^\d{2}:\d{2}$` (mission.json:53), `altitudes_m` has no `minItems`, no `a != b`.
fix: add the checks in `load_mission`, each raising `ConfigError` with file, field and fix: ship in box; radio and modem names against `platforms/radios.yaml` and `modems.yaml`; `a != b`; `when` fits the endpoint classes; hour 0-23 and minute 0-59; `minItems: 1` for `altitudes_m`; `required_fraction > 0`. Files: cafe/pm/config.py, cafe/schemas/mission.json (batch A). stage1.py needs no edit.

### M-28. Record grid is offset by one step for gliders and the USV, not the UAS   (sources: B-22)
severity: minor / status: confirmed / lane: code
where: cafe/pm/stage1.py:76-79 (`keep = slice(None, None, 10)`), :211, :308 (`t = np.arange(t0, T + 1, REC_S)`)
claim: Glider and USV records are the state after each 60 s step (t0 + 60 + 600 k), so the deploy state is missing and links interpolate between differently aligned grids.
check: windows.json times mod 600 s: glider 1678039260 -> 60, usv 1678046460 -> 60, uas 1677772800 -> 0.
fix: prepend the initial state in `_run_glider`/`_run_usv` (take `h["t"]` including t0) or slice from the step that lands on t0 + 600 k. File: cafe/pm/stage1.py (batch B).

### M-29. "Stage 1 keeps the Hangar coefficients": the hangar stage does no CFD, GCI or caching   (sources: B-24)
severity: minor / status: confirmed / lane: wording
where: cafe/pm/pipeline.py:354-372 (`s_hangar`), :469; docs/BRIEF.md 2.9, line 162, 168
claim: `hangar.json` is platform file names and counts of assumed leaves (wall 0.073 s). The "Hangar coefficient" in refit/stage-3 rows is an analytic model value; the report uses the brief's term for a RANS-with-GCI result the tool does not compute.
check: `s_hangar` runs only the platform loaders and writes counts (:354-372); `cd_hangar_source` strings in windows.json are analytic (Seaglider force balance, `usv.hull_resistance`, `uas d_x`).
fix: wording, because no vehicle CAD exists here (QUESTIONS_FOR_LAB) and the DTMB study is the only RANS case: rename in the report and ledger text to "baseline model coefficient (analytic; no Hangar CFD run)" and state it in the credibility limitations. File: cafe/pm/pipeline.py (batch C); the report text comes from the same strings, docs via batch A.

### M-30. USV result is far from the brief's sanity expectation and the report does not say so   (sources: B-25)
severity: minor / status: confirmed / lane: code
where: cafe/pm/report.py (vehicle block), cafe/pm/credibility.py; docs/BRIEF.md line 249
claim: 31 of 32 USV members fail (swept_off_track 28, becalmed 15, wing_stall 9) mostly before 7-8 March; the brief expects MARGINAL then and GO otherwise. No credibility row compares the outcome with the expectation or shows what drives it.
check: q1 report.json usv: NO-GO, p_fail 0.96875, k_fail 31 of 32, modes as quoted; `grep expected|sanity` in index.html and credibility.json: 0 hits. Not established: whether this is model bias; see M-2.
fix: add a "sanity check against the brief" block for the demo mission (a hard-coded expectation table in the credibility report, flagged "does not apply to other missions") and, per vehicle, the first-failure time, mode shares and which constraint (speed, current, 20 km tolerance) was active at first failure. Files: cafe/pm/report.py, cafe/pm/credibility.py (batch D).

### M-31. RUNBOOK step 7 has no path to exit 0 on a clean machine; the `pm()` wrapper omits `--ulimit core=0`   (sources: B-17)
severity: minor / status: partly / lane: wording (docs)
where: docs/RUNBOOK.md:32, :99; runs/receipts.json; Makefile:39; pm.sh:8
claim: `make receipts` is documented as "exit 0 only if none failed" while the shipped table has failing rows, and the stored slow results it reads are absent on a clean machine.
check: `runs/receipts.json` has 296 rows of which 42 have `ok == false` (not 11 as B counted): `app.fea:not_run`, `pm.emulator:not_run`, `pm.physics.uas.slow:not_run`, XLB sphere rows, native sphere rows, flat plate, DTMB rows, COARE rows and others. The file is not tracked by git (`git ls-files runs` empty). `make receipts` itself was not run here. RUNBOOK:32 has no `--ulimit core=0`; pm.sh:8 does.
fix: wording: in section 7 list which receipt failures are the known open limitations (L01-L12 in CREDIBILITY) and which mean a broken install, and say the slow receipts need `receipts --slow` (hours). Add `--ulimit core=0` to the `pm()` wrapper. File: docs/RUNBOOK.md (batch A).

### M-32. DECISIONS row 21 contradicts the code and the CHANGELOG   (sources: A-27)
severity: minor / status: confirmed / lane: wording
where: DECISIONS.md row 21; CHANGELOG.md; cafe/pm/pipeline.py:215-255
claim: Row 21 says `fetch` does not download the ocean or TAO data; the code and CHANGELOG say it downloads all four inputs.
check: DECISIONS row 21 text "`make fetch` therefore does not download ..." against pipeline.py `fetch_ocean`/`_tao` calls in the ingest stage.
fix: rewrite row 21 from the code. File: DECISIONS.md (batch A).

### M-33. The golden gate is a snapshot of the tool's own output with no provenance, and lets undecided verdicts move   (sources: A-28)
severity: minor / status: partly / lane: code + wording
where: cafe/pm/acceptance.py:1-40, :140-175 (`compare`); tests/golden/tepex_c_demo_quick.json (`git_sha: "none"`)
claim: A verdict may change when it is undecided in both runs (q1 has glider_eq, glider_2n, uas and the iridium link undecided); the golden came from `--update-golden`, so it records what the tool said.
check: holds in part. `compare` allows an undecided-in-both verdict change and records a note (acceptance.py:154-159), as the docstring says. It is not blind to movement: P(fail) is judged by Newcombe's interval at a Bonferroni level, so a large shift fails, but a shift of a few members at n = 32 passes. The golden's `git_sha` is `"none"`.
fix: regenerate the golden through `pm.sh` so it carries the real SHA and code digest (needs about 9 min on homebase, so after the box is free); in `compare`, require equal verdict whenever the P(fail) intervals of the two runs do not overlap; say in the docstring and RUNBOOK that the golden is a regression snapshot, not an independent expectation. Files: cafe/pm/acceptance.py, tests/golden/tepex_c_demo_quick.json (batch D); RUNBOOK sentence via batch A.

---

## Fix batches

Five batches with disjoint file sets. Rules for all builders:
- Edit only the files your batch owns, plus the tests for those modules (new test files are fine; an existing test file is edited by the batch that owns the module under test).
- Do not edit any `*.md` unless you are batch A. Everyone else lists the DECISIONS, CHANGELOG, PHYSICS or QUESTIONS lines that their change needs in the final message, and batch A applies them.
- Do not change a public signature that another batch calls (`flip_search`, `budget.plan` return keys, `Ledger.check`, `intervals.interval`, `stage1.run_batch`).

### Batch A: config, statistics, all documents
Findings: M-5, M-11, M-17, M-23, M-27, M-31, M-32, plus the document edits listed by the other batches (M-2, M-7, M-9, M-16, M-19, M-29, M-33).
Files owned:
- cafe/pm/config.py
- cafe/schemas/mission.json
- cafe/pm/stats/intervals.py, cafe/pm/stats/sequential.py, cafe/pm/stats/sensitivity.py, cafe/pm/stats/sampling.py, cafe/pm/stats/rare.py
- missions/*.yaml
- STATUS.md, DECISIONS.md, CHANGELOG.md, QUESTIONS_FOR_LAB.md, README.md, REVIEW.md, PLAN.md
- docs/BRIEF.md (read-only unless a finding says otherwise), docs/RUNBOOK.md, docs/PHYSICS.md, docs/CREDIBILITY.md
- tests for config and stats (tests/test_config*.py, tests/test_stats*.py, tests/test_intervals*.py, tests/test_sensitivity*.py)

### Batch B: Stage 1 engine and vehicle physics
Findings: M-2, M-4, M-13, M-19 (stage side), M-28.
Files owned:
- cafe/pm/stage1.py
- cafe/pm/physics/*.py (comms.py, glider.py, usv.py, uas.py, rigid.py)
- config/perturbations.yaml
- platforms/*.yaml
- tests for stage 1 and the physics modules (tests/test_stage1*.py, tests/test_comms*.py, tests/test_usv*.py, tests/test_uas*.py, tests/test_glider*.py)

### Batch C: pipeline, ledger, audit, ingest cache
Findings: M-3 (windows side), M-12, M-14, M-15, M-25, M-26, M-29; M-1 pipeline side (a real `ocean_source_covers_box`, keep the check name).
Files owned:
- cafe/pm/pipeline.py
- cafe/pm/ledger.py
- cafe/pm/audit.py
- cafe/pm/env/orca.py (and cafe/pm/env/environment.py only if the u* vs `ust` check needs an accessor)
- cafe/pm/__main__.py
- pm.sh, Makefile, pyproject.toml
- tests for these (tests/test_pipeline*.py, tests/test_ledger*.py, tests/test_audit.py, tests/test_orca*.py)

### Batch D: report, credibility, what-if, emulator, acceptance
Findings: M-1 (report side), M-6, M-8, M-18, M-21, M-22 (report side), M-24, M-30, M-33.
Files owned:
- cafe/pm/report.py
- cafe/pm/credibility.py
- cafe/pm/whatif.py
- cafe/pm/emulator.py
- cafe/pm/acceptance.py
- tests/golden/*
- tests for these (tests/test_report*.py, tests/test_credibility*.py, tests/test_whatif*.py, tests/test_emulator*.py, tests/test_acceptance*.py)

### Batch E: budget, throughput, stage 3, sub-grid
Findings: M-3 (`uas_case` clip), M-7, M-9, M-10, M-16, M-20, M-22 (planner side).
Files owned:
- cafe/pm/budget.py
- config/throughput.json, config/subgrid.json, bench/*
- cafe/pm/stage3/*.py (refit.py, windows.py, pipeline_windows.py, nest.py, lbm.py, wallmodel.py, freesurface.py, fluidx3d.py)
- cafe/pm/env/subgrid.py
- cafe/pm/dtmb5415.py, cafe/pm/vv.py (read-only unless needed)
- tests for these (tests/test_budget*.py, tests/test_stage3*.py, tests/test_refit*.py, tests/test_subgrid*.py)
- `make bench` on homebase is a separate step for when the box is idle; the builder must not start it now.

Cross-batch interfaces to respect:
- M-1: C keeps the check name `ocean_source_covers_box`; D matches ledger checks by name prefix.
- M-3: C masks by `airborne` in `s_windows`; E clips the leg speed in `uas_case`.
- M-6: D keeps the `flip_search(..., budget_s, log)` signature; C's call at pipeline.py:569-571 stays valid.
- M-8: D uses the `meta` that pipeline.py already passes (run_id, git_sha, code_digest).
- M-19: B emits `None` or a new field for sentinel margins; D's report prints `None` as "n/a" already.
