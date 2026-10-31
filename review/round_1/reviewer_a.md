# Round 1, reviewer A

Scope: all lanes. Read: BRIEF, DECISIONS, QUESTIONS_FOR_LAB, RUNBOOK, CHANGELOG (Known issues skipped), `cafe/pm/` (stats, stage1, pipeline, budget, ledger, audit, config, comms, usv, report, credibility, whatif, perturb), the `q1` run (report.json, index.html, credibility, 9 ledgers, plan, windows, stage3, emulator files). Reproductions marked "homebase" were run with `PMX=pm_rev_a PM_CPUS=1 PM_MEM=6g` on the CI synthetic environment or as pure-python snippets; the rest are arithmetic on the `q1` files or on code lines. Working tree at review time = `cc2d3f6` plus the uncommitted `cafe/pm/physics/*.py`, `stats/intervals.py`, `audit.py` edits (read as they stand on disk).

Not reported because the repo already states them: DTMB 5415 v3/v4 study, wall-model plate failure and the resulting `ok = False` of every stage-3 window, XLB sphere Cd, SITL return, UAS propulsion/60 Wh battery, GCI r = 2 values, per-batch draws, SPRT/subset simulation not called (DECISIONS 70, 73), native-sphere row names, no GPU, missing lab inputs.

---

### A-1. Stage 1 silently drops UAS sorties when `every_days` < 1
severity: major
lane: robustness / statistics
where: cafe/pm/stage1.py:98 (`launch_times`); schema allows it at cafe/schemas/mission.json (`every_days`: `exclusiveMinimum: 0`)
reproduction: homebase, `stage1.launch_times({"local_solar_time": "14:00", "every_days": ed}, -165.0, t0, T, 1920.0)` with the demo window (6 days, 03-01 12Z to 03-07 12Z): `every_days=1.0` gives 6 launches (correct); `0.5` gives 9 launches, last 03-05 13:00 (the window holds 12; the final 2 days have none); `0.25` gives 8 launches, last 03-03 07:00 (window holds 24). Cause: the count `np.arange(int((T - day0) / 86400.0) + 3)` is in days, then multiplied by `every_days`, so the schedule spans (days + 3) x every_days only. A mission run with `every_days: 0.001` flew (CI env) with a handful of sorties and returned a normal verdict.
why it matters: a UAS flying twice a day gets its second half of the window unflown, so P(fail), `no_sortie_flown` and the battery mode are understated with no warning; the same function feeds `_sortie_hours` (pipeline.py:346), so the 3-D wind cache has the wrong hours too.

### A-2. `verdict.go` / `verdict.nogo` in the mission file are validated for order and then ignored
severity: major
lane: robustness / documentation
where: cafe/pm/config.py:93 (only reads them to check `nogo < go`); cafe/pm/stats/intervals.py:25-26, 94-101 (hard-coded 0.10 / 0.40 / 0.75); missions/tepex_c_demo.yaml:51; QUESTIONS_FOR_LAB.md item 5 ("If different: edit the mission file")
reproduction: `grep -rn '\["verdict"\]\["go"\]\|"nogo"\]' cafe/pm` returns only config.py:93. On homebase/local: `config.load_mission` accepts `verdict: {go: 0.99, nogo: 0.98}` and also `{go: 5, nogo: -3}` (no range check); `stats.intervals.verdict(8, 32)` is the same for every mission. The PIs' own go/no-go thresholds (the thing Q5 asks for) cannot be set.
why it matters: the lab is told an answer to Q5 is a config change; it is a no-op, and verdicts silently keep the 0.9 / 0.6 / lo >= 0.75 rules.

### A-3. `environment.atmosphere.*` and `environment.waves.*` mission keys are accepted and never read
severity: major
lane: robustness / documentation
where: cafe/schemas/mission.json:26-27; cafe/pm/pipeline.py (the only `environment` keys read are `ocean` at 139/237/271 and `subgrid` via `subgrid.switch`); cafe/pm/env/orca.py:25 (`CAFE_ORCA` env var is the only way to repoint); QUESTIONS_FOR_LAB.md items 3 and 9
reproduction: `grep -rn "local_wrf\|local_umwm\|restart_spectra\|\['atmosphere'\]" cafe/pm` finds no consumer. Q3 says "point `environment.atmosphere.path` at it" (and Q9 "re-point `CAFE_ORCA`", the one working knob, an environment variable not a mission key); the mission's `restart_spectra` flag has no reader either. Setting `atmosphere: {source: local_wrf, path: /x}` or `waves.restart_spectra: false` changes nothing (orca.ingest is always called with `spectra=True`, pipeline.py:~232, and always reads `BASE`).
why it matters: three of the lab questions promise a one-line config answer that does nothing; a short window with no 00/06/12/18 Z hour (`orca.py:249`) cannot opt out of the spectra it cannot get.

### A-4. The UAS "worst window" is chosen at a time the UAS is on deck
severity: major
lane: physics / honesty
where: cafe/pm/pipeline.py:405-440 (`s_windows`; `airborne` is never read in pipeline.py), cafe/pm/stage1.py:~227-245 (`_run_uas` leaves lon/lat at the ship while not airborne)
reproduction: q1 `windows/windows.json`: uas W1 `t = 1677772800` = 2023-03-02 16:00:00Z, lon -165.0, lat 0.0 (the ship). Sorties launch at 14:00 local solar = 01:00Z at 165W (`stage1.launch_times`; first UAS failure in the report is 2023-03-03 01:21Z, i.e. sortie 2). 16:00Z is 05:00 local, 15 h after a landing. The 10 m wind maximum is searched over all 865 ten-minute records of the ship position, not over `airborne` records. The report then prints "uas, 10 m wind speed at the worst windows: 2023-03-02 16:00:00Z: 8.219 m/s (failed members)".
why it matters: the LES window (and every UAS number derived from it, including the environment line in the report) describes a moment when no UAS is flying; the BRIEF 5.5 `windows` check ("chosen windows are the argmax of the stated criteria (assert it)") is only `every_vehicle_has_a_window` (see A-8), so nothing catches it.

### A-5. USV speed prior double-penalises: -30 to -35 % applied to a model that is already ~-24 % from the Chiodi target, on top of a current-coupled solve
severity: major
lane: physics / statistics
where: config/perturbations.yaml:69-76 (`usv_vpp_bias` uniform [-0.35, -0.30]); cafe/pm/stage1.py:87 (`fac = 1 + bias`); cafe/pm/physics/usv.py:456, 612-620; docs/PHYSICS.md:532, 650, 672; platforms/saildrone_explorer.yaml:86
reproduction: homebase, `usv.mean_sog(P, 5.4, bias=b) / 5.4` against Chiodi et al. 2021's 0.96 / 5.4 = 0.1778: b = 0 gives 0.2345 (model/observed = 1.319, so "over-predicts by 32 %" is already inside the 30-35 % band); b = -0.30 gives 0.1643 (-7.6 %); b = -0.325 (prior mean) 0.1584 (-10.9 %); b = -0.35 0.1525 (-14.2 %). The factor that reproduces the observation is 1/1.319 = 0.758 (b = -0.242). "Overpredicts by 30-35 %" means model = 1.30-1.35 x observed, i.e. a speed factor 0.74-0.77, not 0.65-0.70. Further, usv.py:17-20 and PHYSICS.md:620 state the Stage-1 solve already puts the current into the apparent wind (the Sun et al. correction); PHYSICS.md:672 records that superposition over-predicts by only 8-26 % in the model's own test, yet the full 30-35 % is applied on top. Every member is slower than the calibration target; none is at b = 0.
why it matters: the headline `usv NO-GO 31/32` (becalmed 15, swept_off_track 28 within 6.7 h of deploy) is produced by a speed prior that is a unit-conversion error and a double count; BRIEF 6's sanity expectation (USV GO outside 7-8 March) is missed and the report never mentions the disagreement.

### A-6. `--budget` does not hold: the plan exceeds its own stage share, is never refused, and its cost model is taken from a loaded box and a different mission
severity: major
lane: performance
where: cafe/pm/budget.py:85-86 (`n_batches = int(...)`, `max(n_batches, 1) * bs`), 91-92 note text; config/throughput.json `stage1.*` (`load_1min: 32.85`, `mission: missions/ci_fixture.yaml`, `sizes: [8, 32]`, usv/uas `s_per_member_day: 0.0`); cafe/pm/pipeline.py (no stage-1 wall check; only stage 3 has `stage_held_its_wall_clock_share`)
reproduction: (1) q1 plan: 502 s per batch + 32 x 1.88 s = 562 s planned for stage 1 against a share of 0.45 x 1200 = 540 s, so `n_batches` is 0 and the code forces 1; the note says "capped at 32 members by the stage-1 share", which hides that one batch does not fit. Measured stage 1: 148.0 s (ledger) = 3.8 x less than planned, because the rates were measured at load 32.85 on 8 CPUs on the CI fixture; the quick run used 512 s of 1200 s while 64 members (the quick N_MAX) would have fitted. (2) homebase, `budget.plan("quick", 0, mission_30d, vehicle_classes=...)`: planned stage 1 = 2809 s (note: "capped at 32 members"), against a 540 s share and a 1200 s budget. (3) Same with the demo window and 12 gliders + usv + uas: 1322 s; 16 gliders: 1627 s. No PlanError, no warning in `plan.json`/report; the BRIEF's 30-day and 20-vehicle robustness cases therefore break the 20-minute contract silently.
why it matters: BRIEF 0.1 says the contract is the budget; the planner's stated guarantee ("A plan that would not fit is shrunk ... and says so") is not met for stage 1, and a 3.8 x cost over-estimate shrinks the quick ensemble.

### A-7. "What would fix it" says no change reaches the target when none (usv, uas) or 15 of 18 (glider_eq) were evaluated
severity: major
lane: honesty
where: cafe/pm/report.py:648-649 (`_fix_html`); cafe/pm/pipeline.py emulator stage (variants/flip budget); cafe/pm/budget.py:EMULATOR_VARIANTS
reproduction: q1 index.html: usv "no single change among the 16 candidates reaches GO or MARGINAL (P(fail) now 0.9688)" with all 16 rows "n/a" (reasons: "no emulator; Stage 1 not run: the emulator budget is spent", or outside window/box). uas: same with 18 of 18 n/a. glider_eq: "no single change among the 18 candidates reaches GO" with 3 evaluated (deploy +6 h 0.3438, east 0.25, west 0.2812) and 15 n/a, including every candidate that is plausible (+12 h, +24 h, dive 25 % shallower). The suffix "so only a few were run in Stage 1" does not tell the reader the count is 0 for two vehicles. Six of the 18 glider candidates ("deploy 6 h/12 h/24 h/48 h earlier", etc.) can never be evaluated in this window and are counted in the 18.
why it matters: a reader of the NO-GO USV line is told no single mission change helps; nothing was tried.

### A-8. Stage ledgers do not carry the BRIEF 5.5 self-checks; several are never computed anywhere in the pipeline
severity: major
lane: honesty / data
where: cafe/pm/pipeline.py:172, 264-295 (ingest), 370 (hangar), 439 (windows), 479 (refit), 551-567 (emulator); cafe/pm/stage1.py:423 (stage 1 has only `lhs_stratified_batchN`); cafe/pm/stats/sampling.py:133 (`crn_check`, no caller); cafe/pm/env/environment.py:207 (`ustar_umwm` tagged, never compared)
reproduction: q1 ledgers. ingest checks: 7 (`*_present`, `orca_hours_cover_window`, `ocean_source_covers_box`, `tao_moorings_compared`); BRIEF 5.5 asks for schema parse, gap-free monotonic time axis, no NaN in sea cells, `swh` of the synthesized spectrum vs file within 1 %, COARE `u*` vs UMWM `ust` within 20 % at 90 % of sea points (BRIEF 2.1: "log the actual agreement"), GOFS flagged in-situ, direction round trip on three fields. `grep -rn ustar_umwm cafe/pm` has no consumer, so the COARE-vs-UMWM agreement is never computed on the mission data (PHYSICS.md:136 quotes two WRF `UST` numbers from a "lead's log"). hangar: 4 `provenance_*` checks in 0.073 s (no GCI, observed order, mesh quality, cache key; the stage is a count of `assumed` leaves, hangar.json 494 bytes). stage1: only the LHS check (no CRN, no energy/|H| drift, no failure-mode coverage, no Wilson-vs-statsmodels). windows: `every_vehicle_has_a_window` only (no argmax assertion). refit: one check, no convergence reason or coefficient change. stage1b: `checks: []`. emulator: 2 bookkeeping checks; RMSE/coverage/query-time checks exist only when trained (never at quick).
why it matters: "make audit asserts zero failed self-checks" is true because the checks that could fail are not there; BRIEF 0.2/5.5 are not met and the report cannot show that the reader's data matched the schema or the physics.

### A-9. Stage-3 physics failures are not ledger failures, so the ledger audit and the traceability banner pass over failing numbers
severity: major
lane: honesty
where: cafe/pm/stage3/pipeline_windows.py:634-641 (4 bookkeeping checks); cafe/pm/audit.py:ledger_problems (reads only `ledger["checks"]`); cafe/pm/report.py:75-90 (`Trace.ref`: an `output` row is always `ok=True`), 130-150 (`check_traceability`), index.html "Traceability check: every number links to a passing ledger receipt"
reproduction: q1 stage3 ledger `ok: true`, all 4 checks pass, while 6 of 6 window rows are `ok: False` and show mach_max 7.399 (limit 0.1), courant_max 4.272, yplus fraction 0 (uas W1), cd = nan; the glider windows report cd 1.962 and 3.291 against Hangar 0.301 and 0.284; usv hull cd 1.909 against 0.038; usv wing cl -2.237 against +0.842. Each of these numbers carries a receipt `stage3:output:windows.json`, status `ok`, and the page says every number links to a passing receipt.
why it matters: the receipts table reads "ok" for numbers the same page shows as FAIL; a reader or the audit cannot distinguish "ran and passed" from "ran and failed everything".

### A-10. Bellhop is never used by the pipeline; the acoustic range ignores depth
severity: major
lane: physics
where: cafe/pm/stage1.py:338 (`comms.acoustic_link(d, modem, band, wind)`: no `ssp`, no tx/rx depth, no water depth), 318-319 (`_pos` returns depth, never used); CHANGELOG.md ("Thorp/Stojanovic acoustics with Bellhop for ambiguous links"); docs/PHYSICS.md:748-762; DECISIONS 64
reproduction: `grep -n "ssp\|water_depth\|tx_depth" cafe/pm/stage1.py` is empty, so `acoustic_link` takes its `ssp is None` branch (comms.py:~258: method "thorp-only (no sound-speed profile)"). Any link whose Thorp margin is within +-6 dB takes that branch, in the lab's data too. `d = _dist(A, B)` is the great-circle ground range, so a glider submerged at 950 m is treated as at the surface for any `when: always` acoustic link.
why it matters: BRIEF 2.8 says Bellhop "runs automatically for every acoustic link whose Thorp-budget margin is within +-6 dB"; the code path exists and is receipted, but the pipeline cannot reach it. In the demo no link is ambiguous (margins -2011 dB / -2290 dB), so q1 does not show it.

### A-11. orca cache reuse ignores the box and the 3-D hours; the cache is keyed by mission name only
severity: major
lane: reproducibility / data
where: cafe/pm/pipeline.py:74 (`self.cache = DATA/cache/<name>`), 232-235 and 339-342 (`orca_covers` -> `_covers` compares only `d["t0"]`, `d["t1"]`); cafe/pm/env/orca.py:305 (manifest also holds `hours3d`, `wrf_index`, `umwm_index`, never compared)
reproduction: edit the demo mission to widen `box` (or `pad_deg`) or to change `sorties.local_solar_time`, keep `name: tepex_c_demo`: `_covers(manifest, t0, t1)` is True, nothing is refetched, the environment is built from the old box (later `OutsideData` at best) and the 3-D WRF hours of the old sortie times (a UAS at the new times falls back to the COARE profile from 10 m with no flag). The GOFS, TAO and GEBCO checks, by contrast, compare the box (`_ocean_cached`, `_tao_cached`).
why it matters: same-name missions with different box/sorties reuse a stale cache and the ledger's input hash (the manifest) still verifies.

### A-12. The resume/config hash does not cover `cafe/*.py`, which the pipeline imports
severity: major
lane: reproducibility
where: cafe/pm/pipeline.py:48-53 (`code_digest`: `cafe/pm/**/*.py`, `config/*`, `platforms/*.yaml`); imports of `cafe.cfd` (stage3/freesurface.py:78, 93, 147; stage3/windows.py:380; dtmb5415.py:47), `cafe.fea` (stage3/windows.py:313), `cafe.emulator` (physics/uas.py:678), `cafe.reach` (report.py:323), `cafe.receipts`
reproduction: `grep -rn "from cafe import" cafe/pm`. A change to `cafe/fea.py` or `cafe/cfd.py` (the free-surface limits maxCo/maxAlphaCo that DECISIONS 123 changed live there) leaves `ctx.hash` unchanged; `ledger.done()` then reuses the stage-3 result produced by the old code. Library versions are not in the hash either (`jax 0.12.0.1` runtime vs `jax 0.4.38` recorded in the LBM bench row of config/throughput.json).
why it matters: `--resume` can present stage-3 FEA/CFD numbers made by code that no longer exists.

### A-13. Stage 3's second job (recalibrate the sub-grid layer and write `config/subgrid.json`) is not implemented
severity: major
lane: physics / documentation
where: config/subgrid.json (`calibration.source_run: null`); cafe/pm/env/subgrid.py:9-10, 53-57; BRIEF 2.2 ("the L2 moving LES nest ... its job is to validate and recalibrate the synthetic layer (compare resolved spectra, sigma_u/u*, length scales, gust statistics ...; write the calibration back)"); docs/PHYSICS.md:306
reproduction: `grep -rn "calibration" cafe/pm` shows readers only; nothing writes `calibration` or sets `source_run`. No stage-3 check compares an LES spectrum, sigma_u/u* or gust statistic with the Mann/gust layer. STATUS.md, DECISIONS and QUESTIONS_FOR_LAB do not list it as open (only PHYSICS.md:306 says "meant to overwrite").
why it matters: the brief called this a decision, not an option; as shipped, Stage 3 can only refit the vehicle drag (and in q1 refits nothing), and the Mann/gust layer feeding every UAS number is uncalibrated by design with that not stated at the top level.

### A-14. Emulator "rows" are keyed by run directory, so reruns of one mission count as new training data
severity: major
lane: statistics
where: cafe/pm/whatif.py:242 (`key=f"{run_id}|{vid}|{variant}"`), 268-274 (`add_rows` replaces only identical keys), 46 and 324 (`MIN_ROWS = 100` counts rows); cafe/pm/pipeline.py:516 (`run_id = digest(str(run_dir.resolve()))[:12]`)
reproduction: q1 emulator ledger: the table held 16 rows before this run and 20 after; `usv` 5 rows, `uas` 5 rows, `glider` 10 rows: five runs of the one demo mission (one USV and one UAS row each), differing only in output directory. The features (`params`, `env_stats`) and targets are mission-determined, so these are exact duplicates. `acceptance` itself writes three runs (`quick`, `quick_same`, `quick_seed`). After ~25 runs of the same mission, `fit_class` passes the 100-row gate with a single design point, and `holdout=0.2` then scores coverage on rows that are copies of training rows.
why it matters: BRIEF 2.7's acceptance (RMSE <= 0.05, coverage within 5 %) can be "met" with one training point; the report would then show EMULATED verdicts with a coverage figure that is leakage.

### A-15. Report label "coefficients blended with the published/Hangar values and their spread widened" and backend "xlb-jax-cpu" are not what the code does
severity: major
lane: honesty
where: cafe/pm/budget.py:98 (label), 95 (`backend` "xlb-jax-cpu" with the rate of `jax-lbm-d3q19-cpu`); cafe/pm/stage3/refit.py (no blending or widening: DerSimonian-Laird pooling only); DECISIONS 76 (window engine is the native JAX kernel; XLB only for reference cases); q1 windows.json (`source: native-nest`)
reproduction: `grep -rn blended cafe/pm` returns only the label. The refit never mixes in the Hangar value or widens a spread. Windows report `source: native-nest`, the plan reports "Backend xlb-jax-cpu at 7.535e+06 ... (measured (2026-10-28, cpu))" whose rate is from the `jax-lbm-d3q19-cpu` bench entry (a BGK + Smagorinsky roll kernel, config/throughput.json), not XLB and not the regularised-BGK + Bouzidi + sponge kernel the windows run (measured 5.8-6.9e6 cells/s in the stage-3 note). RUNBOOK and BRIEF text repeat "XLB-JAX CPU path".
why it matters: the page header for Stage 3 makes three claims (engine, rate source, blending) that the repo's own DECISIONS and code contradict.

### A-16. STATUS.md is the 2026-10-28 audit; BRIEF 0's top-of-file gap statement does not exist; the RUNBOOK has not been blind-tested
severity: major
lane: documentation
where: STATUS.md (last commit ab376fd, 2026-10-28: "`run_premission` ... missing", "Saildrone ... missing", "4 L1 ingestion fixes ... 6-11 not started"); docs/RUNBOOK.md; CHANGELOG.md ("`docs/RUNBOOK.md`, first draft (d7a618b)")
reproduction: `git log --format='%h %ad' -- STATUS.md` shows one 2026-10-28 commit. STATUS section 10 says steps 6-11 not started and lists the entry point, checkpoints, saildrone, worst-moment extraction and refit as missing; all exist in `cafe/pm`. BRIEF 0 requires, at the top of STATUS.md, for each missing input: which input, the one command that completes it, what the user gets meanwhile; STATUS.md has none (they are in QUESTIONS_FOR_LAB only). BRIEF 0.5 requires a fresh agent to follow the RUNBOOK blind and the stuck points to be fixed; the CHANGELOG calls the RUNBOOK a first draft and no such run is recorded.
why it matters: exit conditions 0.5 and the STATUS deliverable are open, and the file a lab member would read first describes a different project.

### A-17. Windows that are not run are shown as "failed its self-checks" with no reason, contradicting the RUNBOOK's troubleshooting row
severity: minor
lane: documentation / honesty
where: cafe/pm/report.py:770-780 (`_window_html`: shows `not_used_because` and checks only); stage3/windows.json `usv[2].error`; docs/RUNBOOK.md troubleshooting row 4
reproduction: `grep -c "free-surface window not run" report/index.html report/report.json` = 0 and 0. index.html: "W3 failed its self-checks; not used in the refit: failed self-checks: . Coefficients: cd_hangar 0.03887" (empty list). The reason ("estimated 94 min x 1.25 margin = 118 min ... against 6.0 min left ... it would fit --budget overnight") is only in `stage3/windows.json`. The RUNBOOK row says "the report says the hull refit was not used" and quotes that sentence as what you see. The ledger check `every_failed_window_states_a_reason` passes because the raw row has `error`.
why it matters: the reader sees a failure with no cause and cannot map it to the troubleshooting table.

### A-18. Refit spread collapses to ~0 with one window per vehicle (budgets ci and quick)
severity: minor
lane: statistics
where: cafe/pm/stage3/refit.py:25-37 (`pool`: `tau2 = 0` for k = 1), 41-45 (`sigma = sqrt(se^2 + tau^2)`); cafe/pm/stage3/windows.py:156-181 (`se` = std of 5 block means / sqrt(5)); budget.py:WINDOWS (`ci`: 1, `quick`: 1)
reproduction: local python on the q1 glider_eq W1 row (cd 1.9617, cd_spread 0.000345, cd_hangar 0.3014): `refit.refit([row])["drag"]` = mean 6.508, sigma 0.00114 (0.018 %). With two windows 10 % apart sigma = 0.56 (8 %). `stage1.refit_drag` then draws a lognormal with that sigma, i.e. effectively deterministic.
why it matters: when a window does pass (GPU or a fixed wall model) the "spread of a new window" the docstring promises is the autocorrelated temporal SE of one run, which is orders too small; budgets with one window per vehicle can never estimate between-window variance.

### A-19. `noise_floor` docstring says ~0.3 at 32 members; it is 0.55-0.60
severity: minor
lane: statistics / documentation
where: cafe/pm/stats/sensitivity.py:35
reproduction: local numpy, `noise_floor(x, y)` with x uniform (32, 10) and y a 0/1 indicator with 4, 8 or 16 ones, 10 seeds each: mean floor 0.599, 0.557, 0.545. q1 reports 0.572 (glider_eq) and 0.597 (uas). The CHANGELOG repeats "about 0.3" for the pre-fix S1 noise.
why it matters: the explanation of why no sensitivity is named at quick is off by 2 x; the true floor means nothing below S1 ~0.57 can ever be named at n = 32 (a deterministic driver, S1 ~0.9, is still detected).

### A-20. Credibility table prints the wrong value for three perturbation priors
severity: minor
lane: documentation / honesty
where: cafe/pm/credibility.py:113-116 (`value=repr(e.get("value"))`); config/perturbations.yaml:28-33, 69-76
reproduction: q1 credibility.json: `perturbations.yaml:current_correlation_length` value "0.0" m (the setting is `mean: 100000.0`); `usv_vpp_bias` "0.0" (the draw is uniform [-0.35, -0.30]); `wind_speed_bias` "2.0" m/s and `wind_direction_bias` "15.0" deg although the ensemble used the TAO-fitted N(-0.616, 1.328) m/s and N(7.21, 23.73) deg (summary.json `priors`).
why it matters: the list that must show every assumed input shows numbers the run did not use.

### A-21. Ledger gaps: versions "?" for pycoare and mannrs; outputs that are missing are dropped; no dirty-tree flag
severity: minor
lane: reproducibility
where: cafe/pm/ledger.py:36-40 (`getattr(__import__(m), "__version__", "?")`), 89 (`... if pathlib.Path(p).is_file()`), 31-37 (`git_sha`); pm.sh / pmx.sh (`CAFE_GIT_SHA=$(git rev-parse HEAD)` of the laptop)
reproduction: every q1 ledger has `"pycoare": "?", "mannrs": "?"` (the two libraries that produce u*/z0 and the turbulence box). homebase: `with Ledger(d, "demo", "h") as L: L.output(d / "never_written.json")` gives `ok: true, outputs: []` (a promised output that was never written is not an error and not audited). q1 ledgers say git `62688c3`; the checkout reviewed is `cc2d3f6` plus uncommitted edits to 10 files, and `CAFE_GIT_SHA` is the laptop HEAD whether or not the tree is dirty, so a run from a dirty tree is stamped with a clean SHA.
why it matters: BRIEF 5.5 requires library versions and the code SHA in every ledger; two of the physics libraries are unversioned and a missing output cannot fail an audit.

### A-22. `audit` does not re-hash directory inputs and only verifies a run in the place it was made
severity: minor
lane: reproducibility
where: cafe/pm/audit.py:ledger_problems (`f.is_file()` guard on inputs; `str(prev)` string comparison for the chain; absolute `outputs[].path`)
reproduction: q1 ledgers record `/data/runs/q1/...` for all 19 outputs and the chain refs; on a copy of the run (the review copy) all 19 outputs are "missing" and 8 of 8 chain links "broken" (checked by running the audit's logic over q1). The ocean store input is a `.zarr` directory with a sha256 of its parts manifest; `ledger_problems` skips anything that is not a file, so the biggest input (5.1 GB) and the orca per-hour npz are never re-hashed. `python -m cafe.pm audit /abs/path` also fails the chain against a ledger written with relative `runs/quick` refs.
why it matters: BRIEF 5.5 says `make audit` re-hashes every input and output; a moved run cannot be audited and a modified store passes.

### A-23. Traceability and HTML-match checks cannot see numbers in text
severity: minor
lane: honesty
where: cafe/pm/report.py:115-150 (`_walk` visits only numeric JSON values), 889-892 (`check_rendered`: `html.escape(_txt(o)) in html_text`, a substring test); report.py:~171-195 (`_undecided`, `certify_statement`)
reproduction: the 95 % intervals ("0.133 to 0.421", "0 to 0.107", "0.0497 to 0.281"), "3/n = 0.094", the thresholds 0.10 / 0.40 and "73 members" appear only inside strings in `undecided_statement`, `certify_statement`, `note`, `region`; none is a node with a ledger. Two different confidence levels sit side by side for the same ensemble: the node `p_fail.uncertainty` is the 90 % Wilson interval (0.147-0.392 for glider_eq) and the sentence below it is the 95 % interval (0.133-0.421). `check_rendered` accepts any node whose text is a substring anywhere in the page, so "0 members" matches every zero mode.
why it matters: BRIEF 0.2 says every number is traceable; numbers carrying the decision text are not, and the check cannot fail on a wrong or swapped value.

### A-24. Sentinel link margins are printed as measurements; the RF link NO-GO is by construction and unexplained
severity: minor
lane: honesty / documentation
where: cafe/pm/physics/comms.py:36, 92 (`NO_LINK_DB = -200.0`); cafe/pm/stage1.py:305-345; QUESTIONS_FOR_LAB.md item 12 (covers acoustic only)
reproduction: q1 report: usv-uas-rf "median margin -200 dB" (the horizon sentinel; the horizon of the USV 2.2 m / ship 15 m pair is 4.12 (sqrt 2.2 + sqrt 15) = 22 km while the USV section spans +-111 km, so the link works ~11 % of the time, median fraction 0.1131); glider acoustic "median margin -2011 dB" and "-2290 dB" (Thorp 3.6 dB/km x 555 km, far outside any valid use of the formula). BRIEF 6 expects links GO except the glider acoustic; usv-uas-rf is NO-GO with P(fail) = 1 and the report gives no mission-geometry explanation (Q12 explains only the acoustic link). With `rf_margin(d=nan)` returning -200 (`np.where(nan <= horizon)` is False) a vehicle whose track is NaN is scored as a link failure.
why it matters: a number that is a clip value is displayed with a ledger link as if measured, and a reader is not told the RF verdict is a consequence of where the demo puts the ship.

### A-25. The emulator can never train at `--budget quick`, and "ran 228.2 s" is a planned cost
severity: minor
lane: performance / honesty
where: cafe/pm/budget.py:EMULATOR_VARIANTS, TRAIN_FRAC, emulator_plan (variant cost = `batch_cost_s(plan)`); cafe/pm/report.py (emulator section text "the flip search ran 228.2 s of Stage 1")
reproduction: q1 design.json: `variant_s` 561.8 s, emulator share 240 s x TRAIN_FRAC 0.7 = 168 s, so `planned_variants` is 0 although `EMULATOR_VARIANTS["quick"] = 6`; only 4 rows are added per run (A-14), so training is unreachable at quick. The emulator wall time in the ledger is 65.4 s while the report says the flip search "ran 228.2 s" (design.json `flip_spent_s` is the planner's charge, noted as "(planned cost)" only in the ledger).
why it matters: the quick budget advertises emulator verdicts ("EMULATED" badges, BRIEF 2.7b) that its own plan makes impossible, and a planned figure is worded as a measurement.

### A-26. Mission validation: gaps that surface as deep crashes or silent acceptance
severity: minor
lane: robustness
where: cafe/pm/config.py:load_mission (box check only for `deploy`/task points; link `radio`/`modem` names unchecked); cafe/schemas/mission.json (`altitudes_m` has no `minItems`; `required_fraction` may be 0; `links` a == b; `waypoints` minItems 1)
reproduction: local `config.load_mission` on edited copies of the demo: ship at 100E, 60N accepted (the ship is not box-checked, though the UAS flies from it); `radio: nonexistent` or `modem: foo` accepted, then `KeyError: 'nonexistent'` / `KeyError: 'foo'` from `comms` (homebase) in stage 1 after ingest and hangar; `sorties.altitudes_m: []` accepted and, on the CI environment (homebase), crashes in stage 1 with `ValueError: cannot convert float NaN to integer` at cafe/pm/env/subgrid.py:144 after ~30 s (np.mean of an empty list); `required_fraction: 0` makes a link always GO; a link from a vehicle to itself is accepted; a USV with a one-point section is accepted.
why it matters: BRIEF 4.0 asks for "a specific, actionable error naming the file, field and fix".

### A-27. Stale DECISIONS row 21 contradicts the code and the CHANGELOG
severity: minor
lane: documentation
where: DECISIONS.md row 21 ("`make fetch` therefore does not download the ocean or TAO data"); CHANGELOG.md ("`fetch` and the ingest stage of `run` download all four inputs"); cafe/pm/pipeline.py:215-255
reproduction: read the three. The RUNBOOK step 4 follows the code (fetch downloads GOFS); the decision table says the opposite.
why it matters: DECISIONS is the audit trail the brief asks to keep current.

### A-28. Golden gate is a snapshot of the tool's own output and passes while 3 of 4 vehicle verdicts are undecided
severity: minor
lane: honesty / reproducibility
where: cafe/pm/acceptance.py:1-40 (verdicts must match "wherever either run has it decided"); tests/golden/tepex_c_demo_quick.json (`git_sha: "none"`, a code digest `b2bfb26a...` that is not the code of q1)
reproduction: q1 has glider_eq MARGINAL, glider_2n GO and uas MARGINAL, all "undecided at n = 32" (plus the iridium link), so a verdict flip on any of them still passes `golden_diff`; the golden was made with `--update-golden` from this tool, so it records what the tool said, not an independent expectation (BRIEF 5.3: "diffs report.json against a golden file"). The q1 numbers (8/32, 0/32, 31/32, 4/32) equal the golden exactly, which supports reproducibility across the code change but says nothing about correctness. The golden's `git_sha: "none"` records no provenance.
why it matters: the quick gate cannot catch a change that moves undecided vehicles between GO, MARGINAL and NO-GO.

---
total: 28 findings (0 critical, 16 major, 12 minor)
