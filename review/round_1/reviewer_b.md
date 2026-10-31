# Round 1 findings, reviewer B

Run reviewed: `q1` (quick, gpus 0, git 62688c3 per the ledgers), repo at HEAD d7a618b plus the uncommitted tree. "run" below means the q1 files
(`report/report.json`, `report/index.html`, `checkpoints/*/ledger.json`, `plan.json`, `stage3/windows.json`, `emulator/*.json`).
Reproductions marked (homebase) were run with `PMX=pm_rev_b PM_CPUS=1 PM_MEM=6g pmx.sh python -c ...` from the repo root.

### B-1. The report's "receipts" are file hashes and one vacuous check; no verdict links to a model Receipt
severity: critical
lane: honesty
where: cafe/pm/report.py:74 (receipt resolution), cafe/pm/pipeline.py:271 (`ocean_source_covers_box`), cafe/pm/pipeline.py:552 (`emulator_variants_within_share`), docs/BRIEF.md section 0.2
reproduction: in `report.json` `receipts` has 18 rows: 9 `kind=output` (sha-256 of a stage output), 8 `kind=config` (the same config hash repeated per stage) and 1 `kind=check`. Walking every `{value, receipt}` leaf in report.json: 297 cite an output hash, 27 a config hash, 10 the single check `ingest:check:ocean_source_covers_box`. That check is `L.check("ocean_source_covers_box", oc is not None, ...)` (pipeline.py:271): it is true whenever `open_ocean` returned, so it cannot fail. The 10 numbers that cite it are the reach-map numbers (`reach.vehicles.*.max_range_km`, `.speed`, `.flow_max`, `reach.horizon`), including the assumed 0.23 and 1.4 m/s speeds. None of the 296 rows of `runs/receipts.json` (Thorp vs Bellhop, SPURS-2, Chiodi band, Wilson vs statsmodels, ...) is cited by any verdict. Similarly `emulator_variants_within_share` in the emulator ledger has value 0.0 against limit 240 (0 variants ran), so it passes trivially. The page nevertheless prints "Traceability check: every number links to a passing ledger receipt."
why it matters: BRIEF 0.2 requires each verdict to link to "the Receipt(s) that justify the model that produced it". Today the link proves only that a number came from a hashed file, and the sentence on the page reads as stronger than that.

### B-2. "What would fix it" says no single change among all N candidates reaches the target when 0 to 3 candidates were evaluated
severity: major
lane: honesty
where: cafe/pm/report.py:648-649, cafe/pm/whatif.py:436-486 (`flip_search`, `FALLBACK_K = 3` at whatif.py:50), cafe/pm/pipeline.py:569-571
reproduction: `report.json` -> `vehicles.usv.fix.tried` (16 rows) and `vehicles.uas.fix.tried` (18 rows): every row has method "not evaluated"; the reasons are "no emulator" or "Stage 1 not run: the emulator budget is spent". Yet index.html prints for the USV "no single change among the 16 candidates reaches GO or MARGINAL (P(fail) now 0.9688); ... only a few were run in Stage 1" and for the UAS "no single change among the 18 candidates reaches GO". For glider_eq only 3 of 18 ran (deploy +6 h, 0.5 deg E, 0.5 deg W). Cause: `flip_search` charges each Stage-1 fallback at the planned cost and iterates vehicles in mission order, so glider_eq spends the 240 s share (228.2 s) and usv/uas get nothing. The ledger log line `flip search usv: nothing in 16 candidates flips it` has the same wording. `found: false` is therefore "not searched", not "searched and absent".
why it matters: this is the line the PI acts on ("nothing helps"), and for two of three non-GO vehicles it is not backed by a single evaluation.

### B-3. Mission keys the lab is told to edit are accepted by the schema and silently ignored (verdict thresholds, local_wrf/local_umwm/path, restart_spectra, pattern)
severity: major
lane: robustness
where: missions/tepex_c_demo.yaml:51 (`verdict: {go: 0.9, nogo: 0.6}`), cafe/pm/config.py:93, cafe/pm/stats/intervals.py:25-27, cafe/schemas/mission.json:26-27, cafe/pm/pipeline.py:230, cafe/pm/env/orca.py:25, QUESTIONS_FOR_LAB.md items 3 and 5
reproduction: `grep -rn '\["verdict"\]' cafe/pm` finds only the ordering check at config.py:93; the verdict code uses the constants `P_FAIL_GO = 0.10`, `P_FAIL_NOGO = 0.40`, `LO_SUCCESS_GO = 0.75`. A mission with `verdict: {go: 0.99, nogo: 0.9}` validates and yields the same verdicts. The schema offers `atmosphere.source: local_wrf`, `waves.source: local_umwm`, `atmosphere.path`, `waves.path`, but `grep -rn atmosphere cafe/pm` finds nothing that reads them and `s_ingest` always calls `orca.ingest(...)` against `BASE` (env `CAFE_ORCA`, else the orca URL). `waves.restart_spectra: false` is never read (`orca.ingest(..., spectra=True)` default is used). `sorties.pattern` is never read. `validate` prints "valid" for all of them. QUESTIONS_FOR_LAB.md says "every answer is a config change": Q5 (thresholds) and Q3 ("point `environment.atmosphere.path` at it") name keys that do nothing.
why it matters: refuse-never-guess (BRIEF 4.0): a lab user who sets their own go/no-go thresholds or a local WRF path gets the orca/default behaviour with no warning.

### B-4. Stage-3 UAS "worst window" is chosen at a time the UAS is not flying, and the LES runs a flight state beyond the airframe's limits
severity: major
lane: physics
where: cafe/pm/pipeline.py:405-437 (`s_windows`, UAS branch at 428-429), cafe/pm/stage3/pipeline_windows.py:250-270 (`uas_case`), platforms/quad_uas.yaml (limits.max_airspeed_ms 12, tilt_exceedance_deg 42)
reproduction (homebase): load `/data/runs/q1/stage1b/res.pkl`; UAS `airborne` is true in 12 of 865 records (1.4 % of the window); the chosen window t = 1677772800 = 2023-03-02 16:00:00Z = 05:00 local solar at 165W; the sorties launch at 01:00Z (`stage1.launch_times` gives 03-02 .. 03-07 01:00). Airborne members at the window record: 0 of 32. `s_windows` takes `np.nanmax` of 10 m wind over all records of the failed members and never reads `r["airborne"]`; a non-flying UAS sits at the ship so its record is finite. stage3/windows.json for uas: `heading_source: relative-flow direction (no stage-1 track)`, `kinematics.v_rel_ms = 16.2` (8.2 m/s wind + 8 m/s leg speed), `tilt_deg = 41.97`, i.e. above `max_airspeed_ms` 12 and at the 42 deg exceedance. The LES then diverges (mach_max 7.4, cd NaN).
why it matters: the window is meant to be the moment the vehicle meets the worst forcing in flight; for the UAS it is a ground-idle hour, and the case solved is one Stage 1 would call a failure before the LES starts.

### B-5. The 73-member certification size is a Wilson number but the interval the code applies for n > 40 is Agresti-Coull, which gives 6 % at n = 73 and jumps at n = 41
severity: major
lane: statistics
where: cafe/pm/stats/intervals.py:28 (`SWITCH_N = 40`), :64-75 (`interval`), :78-82 (`n_certify`), :111-114 (`interval_region`), cafe/pm/stats/sequential.py:`ensemble_stop`
reproduction (homebase, `intervals.interval(0, n, 0.95)` upper bound): n = 40 -> 0.0876 (wilson); n = 41 -> 0.1021 (agresti-coull); n = 73 -> 0.0599; n = 87 -> 0.0507; first n with upper < 5 % is 89. `n_certify()` returns 73 because it solves the Wilson zero-failure bound, which is exactly what `wilson(0, 73)` gives (0.0500). So (a) an all-pass ensemble of 41 has a wider reported 95 % interval than one of 40, and `interval_region` flips from "GO" (hi <= 0.10) at n = 40 to undecided at n = 41, which changes `ensemble_stop`; (b) at n = 73 with zero failures the module's own `interval()` says P(fail) up to 6 %, while the report's `certify_statement` logic (`n < n_certify`) treats 73 as enough.
why it matters: the headline "can certify P(fail) < 5 %" threshold and the displayed/decision interval are computed by two different formulas that disagree between n = 41 and 88.

### B-6. Stage-1 ensemble is capped at 32 (cannot certify) because the planner prices a batch at 3.4x its real cost from a measurement taken at load 33 on a different mission
severity: major
lane: performance
where: cafe/pm/budget.py:85-86, config/throughput.json (`stage1.*`: `load_1min 32.85`, `mission missions/ci_fixture.yaml`, `sizes [8, 32]`), docs/RUNBOOK.md troubleshooting row "ensemble capped at 32 members"
reproduction: `plan.json` predicts stage 1 at 6 days x (7.67 + 7.67 + 12.6 + 55.7) = 502 s per batch + 60 s for 32 members = 562 s, against a stage-1 share of 540 s. The same run's stage-1 ledger `wall_s` is 148.0 s. The costs were measured on `ci_fixture.yaml` with an 8-CPU box at 1-min load 32.85, so they include contention. Because `n_batches = int(540 // 562) = 0`, `max(n_batches, 1)` forces one batch of 32; the rest of the budget is unspent (the whole run took about 514 s of 1200 s) and the emulator stage gets 0 variants (variant cost estimated at 561.8 s against 0.7 x 240 s). At the measured 148 s, two or three batches (n = 64..96) would have fit and quick could have certified. The RUNBOOK row says the cap is "expected at quick on 8 CPUs".
why it matters: the quick budget cannot certify anything and the emulator never trains on the demo because of a stale, contended benchmark, and the runbook tells the user this is normal.

### B-7. The planner never refuses or shrinks below one 32-member batch, so `--budget` does not hold for a longer window or more vehicles
severity: major
lane: performance
where: cafe/pm/budget.py:85-86, docstring lines 9-10 ("A plan that would not fit is shrunk (members, then windows, then nest resolution) and says so")
reproduction (homebase, `budget.plan(...)` + `budget.wall_estimate` on the demo mission): 6-day demo, quick: predicted stage 1 = 562 s (share 540 s). Same mission with the window end moved to 2023-03-31: n_max 32, predicted 2809 s (share 540 s, whole budget 1200 s), notes say only "ensemble capped at 32 ... (2508 s per batch of 32 ...)". 20 UAS vehicles, quick: predicted 6681 s. Nothing refuses or warns that the plan exceeds the budget; windows and nest resolution are not shrunk either.
why it matters: BRIEF 0.1 makes the budget the contract; the 30-day and 20-vehicle robustness cases in BRIEF 5.6 silently run several times over it.

### B-8. Labels and text claim stage-3 coefficients are "blended with the published/Hangar values and their spread widened"; no code does either, and the refit spread is the within-window batch-means error
severity: major
lane: honesty
where: cafe/pm/budget.py:98-99 (label), cafe/pm/stage3/refit.py:56, cafe/pm/stage3/windows.py:163-181 (`cd_spread`), report index "Stage 3 and refit" header
reproduction: `grep -rn "blend\|widen" cafe/pm` finds only the label string. `refit.refit` pools `cd / cd_hangar` with DerSimonian-Laird; `cd_spread` is `blocks(D/q, 5)` standard error over 5 blocks of one run. In q1 `glider_eq` has cd 1.962 with cd_spread 0.000345 (0.02 %) at 0.6 cells per boundary-layer thickness (rule: 5-10) and cd is 6.5x cd_hangar; with a single window the pooled sigma would be cd_spread / cd_hangar = 0.0011, i.e. a drag multiplier of 6.5 +- 0.1 %. The sigma excludes discretisation error entirely and is narrower than the Hangar spread it replaces. Nothing was refit in q1 (all windows failed) so the verdicts were not affected, but the printed label describes behaviour that does not exist.
why it matters: the first time a window passes, Stage 1b would take a near-zero-variance multiplier from an under-resolved run, and the report text says the opposite.

### B-9. UAS refit multiplier divides frame-only LES drag by total drag including rotor momentum drag
severity: major
lane: physics
where: cafe/pm/stage3/pipeline_windows.py:263-270 (`cd_hangar` source string), cafe/pm/stage3/refit.py:56, cafe/pm/stage1.py:`refit_drag` (UAS takes the multiplier directly)
reproduction: stage3/windows.json uas: `cd_hangar = 5.04` with `cd_hangar_source` = "... includes the rotor momentum drag, which the window (no rotors) does not; the ratio therefore reads as 'frame drag / total drag'". `refit()` still forms `w["cd"] / w["cd_hangar"]` and `_multiplier` returns it as `drag`, and `stage1.refit_drag` applies it unchanged as the UAS drag multiplier (`sc = dict(drag=drag * ...)`). A plausible passing window with frame Cd near 1 gives a multiplier near 0.2 on the vehicle's total drag.
why it matters: latent defect: the first UAS window that passes its checks would cut the UAS drag by about 5x in Stage 1b (verdicts then change for the wrong reason). A coefficient of 5 on a quadrotor frame is also outside any bluff-body range, which the code comment acknowledges.

### B-10. Emulator training table takes replicate and stale-code rows, and the hold-out is a random row split, so "100 rows" and the coverage test can be met by rerunning one mission
severity: major
lane: statistics
where: cafe/pm/whatif.py:242 (`key = run_id|vid|variant`), :268-274 (`add_rows`), :46 (`MIN_ROWS = 100`), :351-357 (`train`), cafe/pm/emulator.py:208-214 (`holdout_report`)
reproduction (homebase): `/data/emulator/train.parquet` has 20 rows = 5 runs x 4 vehicles of one mission with identical features (mission params, track statistics) and different `run_id`; four of the five runs have `git_sha = none`, and the same vehicle gave different P(fail) on different code (usv 1.0, 0.969, 0.969, 0.875, 0.969; uas 0.125, 0.125, 0.125, 0.031, 0.125). `code_digest` and `git_sha` are stored on rows but `grep -n "code_digest\|git_sha" cafe/pm/whatif.py cafe/pm/emulator.py` shows nothing filters on them. The key contains `run_id`, so a rerun never replaces its predecessor. 25 reruns of the demo reach `MIN_ROWS` for every class; `holdout_report` then permutes rows at random, so replicates of the same point land on both sides of the 80/20 split and the held-out RMSE/coverage test is optimistic. BRIEF 2.7 asks for training on Stage-1 ensembles "the tool has already run", with a hold-out that means something.
why it matters: the receipt "fails if coverage drops" can be passed by memorisation, and answers mix results from superseded physics.

### B-11. Brief-required ledger self-checks are absent; the helper functions exist but are never called
severity: major
lane: reproducibility
where: cafe/pm/stage1.py:419-425, cafe/pm/stats/sampling.py:110 (`marginal_report`), :133 (`crn_check`), cafe/pm/pipeline.py:271-295 (ingest checks), cafe/pm/pipeline.py:360-372 (hangar), docs/BRIEF.md section 5.5
reproduction: q1 ledgers list their checks: ingest = 7 (`*_present`, `orca_hours_cover_window`, `ocean_source_covers_box`, `tao_moorings_compared`); hangar = 4 (`provenance_*`); stage1 = 1 (`lhs_stratified_batch1`); windows = 1; refit = 1; stage1b = 0. `grep -rn "crn_check\|marginal_report" cafe/pm` finds them only in sampling.py. Not present anywhere in the ledgers: swh-from-synthesised-spectrum vs file swh <= 1 %; COARE u* vs UMWM `ust` agreement (BRIEF 2.1, "log the actual agreement"); NaN-in-sea-cells; direction-convention round trip; waypoint-in-box +-2 deg; CRN verified; energy/|H| drift per member; failure modes exercised; Wilson vs statsmodels; GCI observed order p in [1.5, 3]. The credibility report nevertheless scores Data pedigree 3 of 4 on the rule "every ingest self-check passed", which here is seven presence checks.
why it matters: "every stage proves itself" (BRIEF 5.5) is met by files existing; the numerical self-checks live only in `make receipts`, which a run's audit does not consult.

### B-12. Orca cache reuse ignores the mission box
severity: major
lane: data
where: cafe/pm/pipeline.py:232-234 (`orca_covers`), :339-342 (`_covers`), manifest `~/work/cafe/pmdata/cache/tepex_c_demo/orca/manifest.json`
reproduction: the manifest keys are `base, t0, t1, hours, hours3d, wrf_index, umwm_index, wrf_attrs, parts`: no box. `_covers(d, t0, t1)` compares only time. The cache directory is `DATA/cache/<mission name>`. By code reading (not run, the box was busy): widen `box:` in a mission of the same name and window (e.g. `lon_min: 160`), rerun: ingest logs "orca cache ... covers the window", does not refetch, and the environment stays cut to the old 163E..163W domain. The TAO and ocean stores do check the box (`_tao_cached`, `_ocean_cached`); orca does not. Vehicles that then move outside the old cut fail later with an `OutsideData` error in stage 1 or the emulator, not at ingest.
why it matters: BRIEF 5.5 says ingest refuses when the box does not cover the waypoints; a stale cache turns that into a mid-run failure after minutes of work, or silently narrower data if it is not hit.

### B-13. Bellhop is never used in the pipeline; the "ambiguous links get Bellhop" requirement is dead code
severity: major
lane: physics
where: cafe/pm/stage1.py:338 (`comms.acoustic_link(d, modem, band, wind)`), cafe/pm/physics/comms.py:`acoustic_link`
reproduction: `acoustic_link` refines a link with Bellhop only when `ssp is not None`; stage 1 never passes `ssp`, and nothing builds a sound-speed profile from the GOFS T/S column for a link. For any link with |Thorp margin| <= `ambiguous_db` the result is labelled "Thorp only, no sound-speed profile supplied". In q1 no link was ambiguous (margins -2011 and -2290 dB), so the report prints "Thorp budget decides every link" and the gap does not show. BRIEF 2.8: Bellhop "runs automatically for every acoustic link whose Thorp-budget margin is within +-6 dB".
why it matters: a glider-ship pair at the edge of range, the case the brief singles out, gets the crude budget.

### B-14. Links with a wrong endpoint, `when`, radio or modem pass `validate` and crash in stage 1 with a bare KeyError
severity: minor
lane: robustness
where: cafe/pm/config.py:84-92, cafe/pm/stage1.py:305-345
reproduction (homebase, `stage1.evaluate_link` with a stub env): `when: uas_airborne` between a glider and the ship -> `KeyError: 'ship'`; `kind: rf, when: surfacing` between ship and shore -> `KeyError: 'shore'`. Locally `config.load_mission` accepts both, a self-link (`a == b`), an unknown `radio: foo`/`modem: foo` (only presence of the key is checked), and a ship placed at 100E 50N far outside the box (the box check at config.py:70-79 covers only `deploy`, task waypoints and the station point; UAS vehicles and the ship are never checked). `sorties.local_solar_time: "25:99"` is also accepted and produces a launch hour of 26:39.
why it matters: BRIEF 4.0: every bad input should give an actionable error naming file, field and fix; these surface late, after the long ingest.

### B-15. Sentinel margins are printed as physical dB values
severity: minor
lane: honesty
where: cafe/pm/physics/comms.py:36 and :92 (`NO_LINK_DB = -200`), cafe/pm/stage1.py:316 (`margin = np.where(ok, 1.0, -1.0)`), cafe/pm/stage1.py:`summarize` (`margin_db_median`)
reproduction: index.html: "usv-uas-rf ... median margin -200 dB" (the beyond-horizon sentinel, since the USV is up to 111 km from the ship and the horizon for a 2.2 m antenna and a UAS at 8-100 m is about 24-49 km); "usv-shore-iridium ... median margin 1 dB" (the constant +1 for an Iridium session success, -1 for failure); "glider_eq-ship-acoustic ... median margin -2011 dB" (Thorp linearly extrapolated to 555 km; the demo places both gliders 555 and 598 km from the ship against a 4 km modem, so these two NO-GO verdicts cannot be anything else).
why it matters: the numbers look like link budgets and are not; the demo's acoustic links test nothing.

### B-16. CREDIBILITY.md and STATUS.md describe a different code base from the one under review
severity: minor
lane: documentation
where: docs/CREDIBILITY.md:140-145 and L09 row (line 127), STATUS.md:77 and the whole file (dated 2026-10-28), DECISIONS.md rows 80 vs 104
reproduction: CREDIBILITY.md section 5 says "the stage-3 wall-model check takes the better of the stored flat-plate and channel errors" (DECISIONS 104 and `wallmodel.stored_wall_error` take the worse), "Mission switches warm_layer, rain_lens and ocean_sde are not read; bulk_stress_scale is applied by nothing" (`subgrid.switch` is read in `pipeline.Context.env` and `stage1.run_batch`; `_uas_forcing` applies `bulk_stress_scale`), and is "Written against bb68642" (HEAD d7a618b). STATUS.md still lists as missing "stage 2/3, refit", "Saildrone", "`run_premission` entry point, stage checkpoints", all present now, and has no top-of-file gap statement with (a) input, (b) one command, (c) interim output that BRIEF 0 requires for the missing lab inputs.
why it matters: a lab reader checking the credibility limitations gets three wrong statements and a STATUS that says the tool does not exist.

### B-17. RUNBOOK step 7 cannot exit 0 as shipped and the troubleshooting table does not say so
severity: minor
lane: documentation
where: docs/RUNBOOK.md section 7 ("`pm make receipts` ... exit 0 only if none failed"), runs/receipts.json (tracked in git)
reproduction: `runs/receipts.json` has 11 rows with `ok == false`: `app.fea:not_run` ("no stored result at /data/receipts/app.fea.json", about 60 min), `pm.emulator:not_run` (about 35 min), `pm.physics.uas.slow:not_run`, the three XLB sphere Cd rows (errors 0.30, 0.59, 0.73), native sphere Re 100 (0.124) and the Re 1e3/1e4 rows (NaN), the flat-plate row (0.1647) and the wall-cell y+ share row. On a clean machine the "slow ones are read from their stored result" are absent, so the step fails until `receipts --slow` has been run for hours, which the RUNBOOK does not mention; a blind follower cannot tell expected failures from a broken install. Also the `pm()` wrapper in RUNBOOK section 1 omits `--ulimit core=0`, which the Makefile (`mutation` target comment) and `pm.sh` say is needed to stop a crashed jax worker from writing a core file of 1 GB or more.
why it matters: BRIEF 0.5 (blind runbook) and 0.3 (`make receipts` zero failures): the document's own check step has no path to green.

### B-18. A y+ check passes at 97 % in a row whose own y+ estimate is 1370
severity: minor
lane: numerics
where: cafe/pm/stage3/windows.py:188-205 (`yplus_in_30_300_fraction`), stage3/windows.json `glider_eq[0].resolution`
reproduction: glider_eq window: `resolution.y_plus_estimate = 1369.66`, `nu_lat = 1e-4` vs `nu_lat_physical = 3.698e-6` (floor, ratio 27.04), and `yplus_in_30_300_fraction = 0.968` (pass). 1369.66 / 27.04 = 50.7, inside 30-300: the check is evaluated with the inflated lattice viscosity. The same pattern holds for glider_2n (1836.9 vs 0.973) and the USV hull (32837 vs 0.949). `viscosity_floor` fails these rows separately, but the y+ pass is shown in the table as a passed wall-model gate.
why it matters: the pass reads as "the wall model is at its matching point", while at the physical Reynolds number it is 27 to 300x too far out.

### B-19. Two confidence levels in one sentence: the printed interval does not span the threshold the next line says it spans
severity: minor
lane: statistics
where: cafe/pm/stats/intervals.py:94 (`verdict(conf=0.90)`), cafe/pm/stats/sequential.py:`STOP_CONF = 0.95`, cafe/pm/report.py (verdict block)
reproduction: index.html glider_eq: "P(fail) = 0.25, 90% wilson interval 0.147 to 0.392" then "The 95% interval on P(fail), 0.133 to 0.421, spans the NO-GO threshold of 0.40". The printed interval's upper end is 0.392 < 0.40, so the reader sees an interval below the cut and a statement that it straddles it. Likewise glider_2n "90 % ... 0 to 0.078" followed by "95 % ... 0 to 0.107, spans the GO threshold of 0.10".
why it matters: two undeclared levels (the GO rule uses the 90 % lower bound on success, the "decided" flag the 95 %) make the headline unreadable.

### B-20. The flip-search "ran 228.2 s of Stage 1" is a planned-cost charge, not a measurement
severity: minor
lane: honesty
where: cafe/pm/report.py:826, cafe/pm/pipeline.py:569-571, cafe/pm/whatif.py:476-481
reproduction: index.html Emulator section: "the flip search ran 228.2 s of Stage 1". The emulator ledger `wall_s` for the whole stage is 65.4 s. 228.2 is `spent += budget.batch_cost_s(plan, [vid])` for 3 candidates (about 76 s each from the contended costs of B-6).
why it matters: a reader takes it as measured time; it is the inflated estimate.

### B-21. Sensitivity noise floor at quick is 0.57-0.60, contradicting the docstring and leaving the "top 3 sensitivities" empty for every vehicle
severity: minor
lane: statistics
where: cafe/pm/stats/sensitivity.py:35 (docstring "With 32 members it is ~0.3"), :20-39, harmonics = 6
reproduction: run values at n = 32: glider_eq 0.572, uas 0.597 (usv 0.019 with 31 of 32 failing). With M = 6 harmonics, lam = 2M/N = 0.375 and the bias correction S - lam/(1-lam)(1-S) pushes the 95 % null quantile to about 0.6, so no first-order index can clear it. Every verdict reads "no parameter clears the noise floor". The docstring figure is wrong by 2x, and the 6 harmonics are too many for N = 32.
why it matters: BRIEF 2.5 asks each verdict to name its most sensitive parameter; at the quick budget the estimator cannot, and the docs promise otherwise.

### B-22. Record grid is offset by one step for gliders and the USV (and not for the UAS)
severity: minor
lane: numerics
where: cafe/pm/stage1.py:78-79 (`keep = slice(None, None, 10)`), :245-246 (`t = np.arange(t0, T + 1, REC_S)` for the UAS), `evaluate_link` (`t = np.arange(t0, ...)`)
reproduction: windows.json times are 18:01:00, 09:01:00, 20:01:00 (glider/USV) but 16:00:00 (UAS): 1678039260 - 1677672000 = 367260 = 612 x 600 + 60. Glider records are the state after each 60 s step (t0 + 60 + 600k); the UAS and link grids start at t0. The initial deploy state is never recorded, and links interpolate between differently aligned grids.
why it matters: small, but window times and link samples are inconsistent between classes and the deploy position is missing from every track.

### B-23. Working tree is dirty and the ledger cannot say so
severity: minor
lane: reproducibility
where: cafe/pm/ledger.py:28-34 (`git_sha`), cafe/pm/pipeline.py:48-56 (`code_digest` is only folded into `config_hash`), `git status`
reproduction: ledgers record `git_sha: 62688c3...` (HEAD at run time); the checkout under review is d7a618b with uncommitted changes to `cafe/pm/audit.py`, `physics/comms.py`, `glider.py`, `uas.py`, `usv.py`, `stats/intervals.py`. The ledger has no dirty flag or code digest field; `config_hash` mixes the mission, budget, gpus and code digest, so it cannot be compared with a checkout. The uncommitted diff also adds `# pragma: no mutate block` to the UAS SITL driver and four receipt generators in the two directories the mutation gate (>= 85 % killed) is measured on.
why it matters: the sha in the report does not identify the code that produced it, and the mutation denominator is being narrowed in the same tree.

### B-24. "Stage 1 keeps the Hangar coefficients": the hangar stage does no CFD, GCI or caching
severity: minor
lane: honesty
where: cafe/pm/pipeline.py:360-372 (`s_hangar`), refit.json reasons, docs/BRIEF.md 2.9 and 3 ("Hangar results cached by (CAD hash, mesh params, solver version)")
reproduction: q1 hangar ledger `wall_s = 0.073`, checks `provenance_<platform>` only, output `hangar.json` = platform file names and counts of assumed leaves. The "Hangar coefficient" in refit.json/stage3 rows (`cd_hangar_source`) is an analytic model value (Seaglider flight balance, USV `hull_resistance`, UAS `d_x`). No CAD hash, mesh or GCI is involved.
why it matters: the report text uses the brief's term for a RANS-with-GCI result the tool does not compute.

### B-25. USV result is far from the brief's sanity expectation and the report never says so
severity: minor
lane: physics
where: report vehicles.usv, docs/BRIEF.md section 6 ("USV MARGINAL in the low-wind/high-current window on 7-8 March, GO otherwise")
reproduction: usv: 31 of 32 members fail (modes: swept_off_track 28, becalmed 15, wing_stall 9), first failure 2023-03-01 18:42Z (6.7 h after deploy), median 2023-03-02 00:38Z, i.e. almost all failures precede 7-8 March. Platform `chiodi_band` and the 12 m/s point are flagged calibrated/assumed elsewhere, but the credibility report has no row comparing this outcome with the brief's expectation, and the same-window reach map (155.9 km in 24 h at an assumed 1.4 m/s) is consistent with a boat that can hold a 20 km corridor. No diagnostic (which of speed, current or the 20 km tolerance drives it) is printed.
why it matters: the brief marks this as the sanity check; a 97 % NO-GO could be a model bias or a tolerance choice, and the lab cannot tell which.

total: 25 findings (1 critical, 12 major, 12 minor)
