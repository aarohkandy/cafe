# Round 2, reviewer A: findings

Scope: `cafe/pm/` at commit `8ee5f50` (branch `premission-step4`), the quick run `q2` of `missions/tepex_c_demo.yaml` (`--budget quick --gpus 0`), BRIEF section 5.6 lanes (all).
Method: read the code, the run's ledgers, `plan.json`, `windows.json`, `report.json`, `credibility.json`, `index.html`; local numpy checks; a few 1-CPU snippets on homebase (private dir `pm_rev_a`, synced to `8ee5f50`). Nothing in the repo was edited.
Run timeline used below (from the ledgers' `started` and `wall_s`): ingest 21:56:21Z, report finished 22:16:35Z.

---

### A-1. The quick run took 20 min 14 s; ingest (522 s) is in no budget share, and the planner overestimates stage 1 by 2.5x
severity: major
lane: performance
where: cafe/pm/budget.py:32 (`SHARE` sums to 0.95 and has no ingest term), cafe/pm/budget.py:26 (`BUDGET_S`), cafe/pm/acceptance.py:98-106 (wall limit is the whole process), docs/RUNBOOK.md:9
reproduction: q2 ledgers: ingest `wall_s` 522.039, hangar 0.134, stage1 211.047, windows 0.093, stage3 360.1, refit 0.008, stage1b 40.555, emulator 78.088, report 1.835. Sum 1213.9 s. First ledger `started` 2026-10-31T21:56:21.468Z, report ledger `started` 22:16:33.574 plus 1.835 s = 22:16:35.4, i.e. 1214 s wall against `BUDGET_S["quick"]` = 1200. `acceptance.check_run` compares the wall time of the whole `python -m cafe.pm run` with 1200 s, so `make acceptance` fails `run_quick` on this evidence ("took 20.2 min, over the 20 min limit"). The ingest was a cache rebuild, not a download: `pmdata/cache/tepex_c_demo/orca/hours/*.npz` and the `*.zarr` were rewritten 22:04 (the 3-D hour list changed with DECISION 164), so a warm cache still costs up to 8.7 min. `budget.py` docstring promises "ingest (measured bytes/s; zero once cached)" but no ingest term exists. Separately, plan.json `stage1_s` = 531.8 s, measured stage-1 wall = 211 s for the same 16 members: 330 s of the 540 s stage-1 share were never used while `n_max` was capped at 16 and the emulator got 0 variants (`plan.json` emulator.variants_* = 0).
why it matters: the headline contract ("quick finishes in at most 20 min") is missed on the one machine it is gated on, and the runbook states it as met.

### A-2. Verdicts cite a model-receipt table from two days earlier code, with no code digest
severity: major
lane: honesty / reproducibility
where: cafe/pm/report.py:46 (`RECEIPTS = credibility.ROOT / "runs/receipts.json"`), cafe/pm/report.py:78-85 (`Trace._table` reads the file and hashes it, nothing else), cafe/pm/receipts.py:418 (`out.write_text(json.dumps(rows ...))`: rows only, no sha or digest)
reproduction: `report.json` receipts `physics:pm.physics.glider|usv|comms|uas` all carry sha256 `0df5e5f6eb2d...`. On homebase `sha256sum ~/work/cafe/pm/runs/receipts.json` = 0df5e5f6eb2d847962f9...; `ls -l` mtime 2026-10-29 09:05 UTC. `git log --since='2026-10-29 09:05' -- cafe/pm/physics cafe/pm/stats` lists 62688c3, 3d03456, 8ee5f50 (the diff of `3d03456~3..HEAD` touches physics/comms.py, glider.py, uas.py, usv.py, stats/intervals.py, sensitivity.py, sequential.py). The run's code digest is `9f537b95...`. The stored slow receipt `pmdata/receipts/pm.physics.uas.slow.json` (Oct 29 08:57) is correctly refused as "not run on this code", which proves the digest moved, yet the same page prints "Model receipts (pm.physics.glider): 25 receipts pass, 0 fail" for the verdict of the current code.
why it matters: DECISION 172 made the receipt a statement about the model that produced the verdict; a pass count from older code is that same claim without its evidence. The table must carry the code digest and `Trace` must compare it.

### A-3. On `--gpus 0` stage 3 spends 30 % of the budget on windows that cannot pass at any CPU budget
severity: major
lane: numerics / performance / honesty
where: cafe/pm/budget.py:32 (`stage3=0.30`), config/assumptions.yaml `stage3.nu_lat_floor` (1e-4), cafe/pm/stage3/pipeline_windows.py:513-517 (`viscosity_floor` check always fails when floored), docs/BRIEF.md section 3 ("on a CPU-only box the LES windows are replaced by the Hangar RANS coefficients ... and the report says so")
reproduction: `stage3/windows.json` resolution blocks, all five LES windows: `nu_floored: true`; glider_eq `nu_lat` 1e-4 against `nu_lat_physical` 3.70e-6 at dx 0.0952 m; glider_2n 2.67e-6 at 0.0794 m; usv hull 1.01e-7 at 0.316 m; usv wing 3.68e-7; uas 3.43e-6. `nu_lat_physical` scales as 1/dx at fixed lattice speed, so glider_eq needs dx <= 0.0952 x 3.70e-6 / 1e-4 = 3.5 mm: 1.1e9 cells (54,777 x 27^3) and at least 9,600 steps (10 s physical, dt 1.04 ms), about 1e13 cell-updates, against 2.2e8 planned per window at quick and about 3.6e9 per part at overnight (plan: 0.30 x 36000 s / 15 parts x 7.5e6 / 1.5). That is 3,000x to 45,000x short for glider_eq, and the usv hull needs 1000x finer dx. No CPU budget can clear `viscosity_floor`, so no CPU window is ever `usable_for_refit`, and the refit and the sub-grid recalibration can never run. This is not stated anywhere (grep `viscosity.floor` in docs: only DECISIONS 77 and PHYSICS 921). The Hangar RANS substitute the brief asks for does not exist (DECISION 171), so the 6 min of quick (3 h of overnight) produce six failing rows and a "CPU fallback" label that implies coefficients are being produced.
why it matters: the planner gives this stage 30 % of every `--gpus 0` budget (6 of 20 min at quick, 3 of 10 h overnight) that stage 1 (n = 16 at quick) and the emulator could use; and the label "pooled window coefficient over the Hangar-model value" (`plan.json les.label`) suggests a result the CPU path cannot give. The honest options are to skip stage 3 on CPU with a stated reason, or to plan it only when `nu_lat_physical >= nu_lat_floor` is reachable in the share.

### A-4. The fitted wind prior treats the hourly mooring misfit as a constant bias held for six days
severity: major
lane: statistics / data
where: cafe/pm/pipeline.py:449-452 (`value = sqrt(rmse^2 - bias^2)` of the pooled hourly series), cafe/pm/env/perturb.py:116-131 (`wind_speed_bias` and `wind_direction_bias` are one number per member, applied at every time and place)
reproduction: `ingest/tao_compare.json`: per-mooring time-mean speed bias has mean 0.595 and standard deviation 0.375 m/s over the 11 moorings; per-mooring mean direction bias has standard deviation 8.7 deg. `ingest/priors_fitted.json` uses sd 1.328 m/s and 23.73 deg (the hourly RMSE with the pooled mean removed). The prior is sampled once per member and added to the whole 6-day record, so a persistent-error sd 3.5x (speed) and 2.7x (direction) the dispersion that the data show for a persistent error. Most of the hourly misfit is short-lived, and `bulk_stress`, `hs_scale` etc. carry their own error. Because the brief's 2.0 m/s and 15 deg priors were also constants, the "fit replaces the literature prior" step (BRIEF 5.2) did not add the temporal structure the data supports; the result is a larger constant rotation (24 deg 1-sigma for 6 days) than the literature default it replaced (15 deg).
why it matters: every wind-driven verdict (usv swept_off_track 13 of 16, uas battery_reserve, glider windage) is computed under a persistent forcing error the moorings do not support; the credibility page labels the draw "data" (kind: data) with no caveat.

### A-5. Windows cut by the wall-clock kill put machine-dependent numbers into the hashed outputs, so "same seed gives identical report.json" cannot hold
severity: major
lane: reproducibility
where: cafe/pm/stage3/pipeline_windows.py:508-523 (`run_steps`, `cut_reason`, the coefficients and check values of a killed run are written), cafe/pm/budget.py:5-7 (docstring: "nothing ... is sized from elapsed time"), cafe/pm/acceptance.py (same_seed = exact equality)
reproduction: q2 `stage3/windows.json` resolution blocks: all five LES windows have `run_steps` < `planned_steps` (glider_eq 3500/4300, glider_2n 3200/4300, usv hull 3400/4700, usv wing 4100/4700, uas 4000/4700) with `cut_reason` "killed after N of M steps: its wall-clock slice ... was spent". `cells_per_s_measured` was 3.46e6 to 4.25e6 against the planned 7.53e6 (1.8x to 2.2x slower). The cut is at a 100-step chunk boundary decided by the clock, and the reported `cd`, `cd_spread`, `cl`, `force_running_mean_dev`, `mach_max` and the other check values (all in the hashed `windows.json` and in `report.json` stage3.vehicles.*.checks and coefficients, e.g. cd 1.962) depend on how many chunks ran. Two runs of the same seed on a differently loaded box therefore differ in `report.json`. The `les_margin` of 1.5 covers a box slower than the bench by at most 1.5x; here the stored rate (measured 2026-10-28) was 1.8-2.2x too fast.
why it matters: BRIEF 5.3 asks for byte-identical reports for one seed; the design excuse (the kill only turns a late window into a row that says so) fails because the row's numbers are still written and hashed.

### A-6. The report never says a window was killed or under-resolved; a killed window that passes its checks reads "no check or error recorded"
severity: major
lane: honesty
where: cafe/pm/report.py:543-549 (`not_used_because` is built from failed checks and `error` only; `w["reasons"]` is never read), cafe/pm/stage3/pipeline_windows.py:520-521 (`ok = checks_ok and not killed`, killed reason goes to `reasons` only)
reproduction: `grep -c killed report/index.html` = 0 (and in `report.json`, only prose about the free-surface child). `windows.json` glider_eq[0].reasons includes "killed after 3500 of 4300 steps ..." and "resolution below the rule: 0.6 cells per boundary-layer thickness at dx = 0.0952 m (BRIEF 2.6: 5-10)"; for the other windows 0.3 to 0.6 cells per thickness (usv hull 0.3, usv wing 0.4, uas 0.6). The page shows only "failed self-checks: yplus_in_30_300_fraction, wall_model_receipt_error, viscosity_floor". A window that passes every check but is killed has `ok` False, `checks` all ok and no `error`: the code at report.py:549 then prints "no check or error recorded".
why it matters: the resolution shortfall (an order of magnitude under the brief's rule) and the kill are the first things a CFD reviewer asks; both are in the data and hidden by the renderer.

### A-7. One member that leaves the cached box aborts the whole base ensemble
severity: major
lane: robustness
where: cafe/pm/env/environment.py:92-100 (`_check` raises `OutsideData` when strict, the default), cafe/pm/stage1.py `run_batch` (no handler), cafe/pm/pipeline.py:534-545 (`_stage1` no handler), cafe/pm/physics/glider.py / usv.py (no domain guard)
reproduction: the repo's own test shows it: tests/test_pipeline.py:1250 `with pytest.raises(OutsideData): stage1.run_batch(mv, ...)`. Only the what-if and emulator-variant paths catch it (whatif.py:268-276, 435-457). The cache is box +- `pad_deg` (here lon 163E..163W, lat +-7). The base ensemble has no such catch: the 30-day window is accepted by `budget.plan` at overnight (`plan --budget overnight` with a 2023-03-31 end: stage 1 estimated 14,844 s inside a 16,200 s share), and a drifting glider (`glider_2n` mode drift, currents 0.2-1.0 m/s in this box) or a swept USV travels 500-2000 km (4.5 to 18 deg) in 30 days, past the 2 deg pad. The first member that crosses raises `OutsideData` out of the vectorised step, the stage ledger records the error, and the run ends after hours with no report. (Currents do not raise: `Ocean._at` clamps silently to the edge, so wind raises while the current is edge-held.)
why it matters: BRIEF 4.0 "degrade, never crash"; the brief's robustness lane names a 30-day window and a vehicle leaving the box. The right behaviour is a per-member `left_data` failure flag from the first position outside, not an exception.

### A-8. What-if and flip-search answers for the UAS switch wind model against the baseline they are compared with
severity: major
lane: data / statistics
where: cafe/pm/env/environment.py:151-156 (3-D WRF wind only where `_wind3d` has an ingested hour pair, else the COARE profile from U10), cafe/pm/whatif.py:98-104 (UAS shift edits `local_solar_time`), cafe/pm/whatif.py:127 (duty edits `every_days`), `ingest/cut.json` (`hours3d`: 01:00 and 02:00 UTC on 2-7 March only)
reproduction: homebase snippet (`whatif.apply` then `stage1.launch_times`, lon -165): base first launch 03-02 01:00Z; "launch 6 h later" 03-02 07:00Z; "12 h later" 03-01 13:00Z. The ingested 3-D hours are the 12 hours 01Z/02Z of 3-7 March. A shifted sortie therefore flies in hours without 3-D fields and gets the COARE 3.5 log profile from U10 at 18-100 m, while the baseline got WRF's own 3-D wind above the first mass level (a discontinuity of tens of percent at 30-100 m is normal). The candidate's P(fail) differs from the base partly because of the wind model, not the change. The emulator training variants (`s_emulator`) have the same mix, so the emulator also learns the switch.
why it matters: "the smallest change that flips the verdict" for the UAS is a compare of two different wind products; nothing in the report says so.

### A-9. Three ledger self-checks cannot fail
severity: major
lane: honesty
where: cafe/pm/pipeline.py:570 and cafe/pm/stats/sampling.py:133-137 (`common_random_numbers`), cafe/pm/pipeline.py:332-348 (`swh_spectrum_vs_file`), cafe/pm/pipeline.py:706 (`refit_iterations_within_cap`)
reproduction: (a) `crn_check` draws `member_rng(base_seed, m, s)` once per "vehicle" with identical arguments and compares them; it cannot fail whatever `run_batch` does (a per-vehicle `PerturbedEnv` with a vehicle-keyed seed would still pass), and the other half (`same`) only regenerates the first LHS batch. The check name and note claim "every vehicle draws the same stream values per member". (b) The ingest ledger value for `swh_spectrum_vs_file` is 5.08e-16 against a limit of 0.01: `spectrum_from_params` normalises to the file's `swh` on the same grid it is then integrated on, so the check is the identity to machine epsilon (waves.py:99-100 says so: each component is "renormalised on the discrete bins to its own Hs, so 4 sqrt(m0) = hs exactly"). (c) `refit_iterations_within_cap` compares the plan constant 2 with `refit.MAX_ITER` = 2 (ledger value 2, limit 2); the run performed zero refit iterations (stage 1b is a copy) and the pipeline never loops. BRIEF 0.3 and 5.5: every check must be able to fail.
why it matters: the credibility page counts "14 ingest self-checks passed" and the Verification factor leans on ledger checks; three of them carry no evidence.

### A-10. STATUS.md describes the repo as it was on 2026-10-28
severity: major
lane: documentation
where: STATUS.md:1-12, 80-118 (last commit ab376fd, 2026-10-28)
reproduction: `git log -1 --format=%ad -- STATUS.md` = 2026-10-28. It says "On track for step 4", lists as missing the `run_premission --mission --budget --gpus` entry point, stage checkpoints, per-mission HTML report, Saildrone vehicle and "6-11 not started". All exist at `8ee5f50` (`bin/run_premission`, `report/index.html`, `physics/usv.py`). BRIEF 0.1 and 8 require STATUS.md to carry, at the top, the missing inputs with the command that completes each; that content is only in QUESTIONS_FOR_LAB.md and the golden/mutation gaps are written nowhere in STATUS.md.
why it matters: STATUS.md is the first file a lab member opens and it contradicts the tool in front of them.

---

### A-11. UAS what-if candidates "24 h / 48 h later or earlier" are the baseline; fractional `every_days` drifts the launch time of day
severity: minor
lane: statistics
where: cafe/pm/whatif.py:102-104 (`tot = (hh*60 + mm + round(h*60)) % 1440`), cafe/pm/whatif.py:127, cafe/pm/stage1.py:101-108 (`launch_times`)
reproduction: homebase snippet `whatif.apply(m, {'uas': dict(shift_h=h)})` then `launch_times(..., lon=-165, window of the demo)`: for h = 24, 48, -24, -48 `local_solar_time` stays "14:00", 6 launches, first at 03-02 01:00Z, identical to h = 0. The report lists "launch the sorties 24 h later" (cost 4) and "48 h later" (cost 8), "24 h earlier", "48 h earlier" among the 16 UAS candidates; four are no-ops that would be evaluated and priced as real changes. With `every_days` = 1/0.75 (the "duty" candidate, "fly sorties every 1.33333 d") launches fall at 08:59Z, 16:59Z, 00:59Z, 08:59Z, i.e. not at the mission's `local_solar_time`.
why it matters: wasted Stage-1 budget and mislabelled fixes; the duty candidate changes time of day as well as frequency.

### A-12. `ingest/tao_compare.json` and `stage3/windows.json` are not valid JSON
severity: minor
lane: robustness / documentation
where: cafe/pm/pipeline.py `_dump` (`json.dumps(..., default=ledger._jsonable)` with the default `allow_nan=True`)
reproduction: `node -e "JSON.parse(require('fs').readFileSync('q2/stage3/windows.json','utf8'))"` fails at `"limit": Infinity`; `q2/ingest/tao_compare.json` fails at `"sst_bias": NaN`. `report.json` is clean (the report maps non-finite to null), but these two are listed as the report's inputs and hashed outputs and the RUNBOOK invites reading raw JSON; `jq` and JavaScript reject them.
why it matters: a lab member's tooling cannot open two of the evidence files.

### A-13. A diverged LES window keeps running until the wall-clock kill
severity: minor
lane: numerics / performance
where: cafe/pm/stage3/pipeline_windows.py:508-521, cafe/pm/stage3/lbm.py (no non-finite abort)
reproduction: `stage3/windows.json` uas[0]: `mach_max` 8.85, `courant_max` 5.11, `cd` NaN, `force_running_mean_dev` NaN, yet `run_steps` 4000 of 4700 and `cut_reason` "killed after 4000 of 4700 steps ... 70 s was spent". The window consumed its whole 70 s slice (19 % of the stage-3 share) on a field that was already NaN; the thin arms (0.015 x 0.01 m, 1 cell at dx 0.0146 m, below `stage3.min_cells_across` = 2) are the likely cause.
why it matters: a non-finite or Mach > 1 state should end the window at the first chunk and hand its time to the next one.

### A-14. `PlanError` and `--seed -5` end in a Python traceback, not an `error:` line
severity: minor
lane: robustness
where: cafe/pm/__main__.py:118 (`except ConfigError` only), cafe/pm/budget.py (`PlanError(ValueError)`)
reproduction: homebase `python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget ci`, `plan ... --gpus -1`, and `run ... --budget quick` on the demo with its window extended by one day (the brief's original 7-day window; `plan` says "short by 54 s") all raise `PlanError` out of `main`; `run --seed -5` raises `ValueError: expected non-negative integer` from numpy. Exit code 1 and a traceback, where a bad mission file gives exit 2 and "error: ...". The runbook (step 3) says the `ci` refusal is "by design".
why it matters: the refusals are the right behaviour with the right message, wrapped in a traceback a lab member will read as a crash.

### A-15. `validate` accepts duplicate link ids and a swapped latitude box with a misleading message
severity: minor
lane: robustness
where: cafe/pm/config.py:96-130 (`load_mission`, `_check_links`), cafe/pm/config.py:51-55 (`_in_box`)
reproduction: demo mission with `links[0]` copied to the end: `python -m cafe.pm validate` prints "valid (4 vehicles, 5 links)"; reports and results are keyed by link id (`out["links"][lk["id"]]`), so one of the two silently overwrites the other. Demo with `box.lat_min: 5, lat_max: -5`: the error is "ship (-165.0, 0.0) is outside the mission box ...; widen the box or move the ship", which sends the user to the wrong fix (the schema does not require lat_min < lat_max).
why it matters: BRIEF 4.0 asks for a specific, actionable error naming file, field and fix; one input is silently accepted and one is blamed on the wrong field.

### A-16. The refit loop of BRIEF 2.6 is a single rerun; `plan.json` says 2 iterations
severity: minor
lane: honesty / numerics
where: cafe/pm/pipeline.py:735-752 (`s_stage1b` reruns once, reports verdict changes, no convergence test or second pass), cafe/pm/budget.py `refit_iterations`
reproduction: `plan.json` `"refit_iterations": 2`; stage1b ledger note "no vehicle was refit: stage 1b is stage 1 (copied, not rerun)"; refit ledger note "it does not loop until the verdicts stop changing". The credibility page's Results-robustness row ("a stage-3 refit reran stage 1 and no verdict changed") can only be earned by one rerun.
why it matters: the brief asks for a loop with a convergence check capped at two; the plan field and the passing cap check read as if it exists, and the limitation is not in CREDIBILITY's known list.

### A-17. The "brief prior" sensitivity case is a different sample (n = 32) from the verdict it is printed beside (n = 16)
severity: minor
lane: statistics
where: cafe/pm/stage1.py:496-520 (`sensitivity_case`, `n=32`, docstring "every other input drawn from the run's own hypercube columns"), cafe/pm/pipeline.py:721 (`_sensitivity_cases`)
reproduction: the case calls `run_batch(..., list(range(32)))`, so `lhs(32, ..., SeedSequence([seed, 0]))`; the main run's first batch is `lhs(16, ..., SeedSequence([seed, 0]))`. The two permutation sets differ (`rng.permuted(tile(arange(n)...))` consumes a different stream), so the columns are not the run's own. The report prints "NO-GO 0.9688, 31 members of 32" next to "NO-GO 0.8125, 13 of 16" as "the same ensemble under another setting of one input" (report text); the change of prior and of sample are confounded.
why it matters: the point of the case is to isolate the effect of the brief's -30 to -35 % bias; both verdicts are NO-GO so the conclusion survives, but the sentence is wrong and the comparison cannot be read as an effect size.

### A-18. Docs that DECISIONS superseded still state the old numbers
severity: minor
lane: documentation
where: docs/RUNBOOK.md:146 ("`ensemble capped at 32 members` ... expected at quick"), docs/RUNBOOK.md:11 (orca cache 1.1 GB), docs/PHYSICS.md:845 ("first 6 harmonics"), docs/PHYSICS.md:657 ("the platform's own N(-0.30, 0.03) default"), docs/CREDIBILITY.md:14 and :71 ("twelve" limitations), CHANGELOG.md:30 ("1,370 test functions in 43 test files")
reproduction: q2 `plan.json` note: "ensemble capped at 16 members" (the runbook's troubleshooting row names 32); `du -sh pmdata/cache/tepex_c_demo/orca` = 2.1 GB plus `derived.zarr` 218 MB (runbook: 1.1 GB; the demo's data is about 7.7 GB, not 6.4); `sensitivity.default_harmonics` = min(6, max(2, n//16)) (DECISION 156), 2 harmonics at n = 16; `platforms/saildrone_explorer.yaml` `vpp_bias_mean` -0.2422, `vpp_bias_sd` 0.0082; `credibility.json` lists L01-L13 (DECISION 179 added L13); `ls tests/test_*.py | wc -l` = 47 and 1,622 `def test_`.
why it matters: the runbook is the blind-follow document of exit condition 5, and PHYSICS.md is the equation record.

### A-19. BRIEF 2.9 "the web UI replays and the static demo read report.json" is dropped without a decision
severity: minor
lane: documentation / honesty
where: README.md (0 mentions of `cafe.pm`, `run_premission` or the RUNBOOK), cafe/static/, site/ (no reader of `report.json`)
reproduction: `grep -rl "report.json" cafe site bin lab` returns only `cafe/pm/{audit,acceptance,pipeline,report}.py`; `grep -c -i "premission\|RUNBOOK" README.md` = 0; no DECISIONS or CHANGELOG row records the omission.
why it matters: "never silently narrow the scope" (BRIEF 0); the README a lab member opens first describes only the old app.

### A-20. Data-pedigree level 3 ("strong") needs only that a TAO comparison exists, not that the model agrees
severity: minor
lane: honesty
where: cafe/pm/credibility.py (Data pedigree rule: "3 and a TAO/TRITON comparison is stored for this mission")
reproduction: `credibility.json` factor "Data pedigree": level 3, "strong: checked against an independent reference". The stored comparison is `ingest/tao_compare.json` ALL: speed RMSE 1.46 m/s (bias +0.62), direction RMSE 24.8 deg, SST bias -0.11 K with T5S180W at -0.50 K; the rule would give level 3 for any numbers.
why it matters: the level reads as a verdict on the data's quality; it only records that a comparison ran.

---

total: 20 findings (0 critical, 10 major, 10 minor)
