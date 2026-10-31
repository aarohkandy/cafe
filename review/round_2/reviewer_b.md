# Round 2, reviewer B

Commit 8ee5f50. The quick run q2 is in `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe/7a1f0993-224f-4f35-ab3f-f6f1853168a1/scratchpad/q2`. The probe scripts quoted below are in `.../scratchpad/repo_copy/_rb/` (a copy of the repo with my scripts added; nothing in the repo was edited). They were run with `PMX=pm_rev_b PM_CPUS=1 PM_MEM=6g .../scratchpad/pmx.sh python _rb/<script>` from that copy. I found no critical finding. Order: major, then minor.

### B-1. The credibility V&V 20 table is built from the discarded, recipe-less DTMB 5415 run files; they lift Validation from 1 to 2 and show "validated" at U_val about 100 % of C_T
severity: major
lane: honesty / data
where: cafe/pm/dtmb5415.py:512-528 (`tabulate`, no recipe check) against :470-473 (the only RECIPE refusal, in `run_case`); cafe/pm/credibility.py:221-232 (rows), :352-364 (`_validation`), :344-346 (Verification evidence level 3); CHANGELOG.md:182 ("the DTMB V&V 20 rows read 'not run' until it finishes")
reproduction: `ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121 'ls -l ~/work/cafe/pmdata/dtmb5415/run_*.json; python3 -c "import json;print(list(json.load(open(\"/home/azureuser/work/cafe/pmdata/dtmb5415/run_coarse.json\"))))"'` gives files dated Oct 29 11:41 and 13:07 with keys `['grid','iters','surf_level','S','speeds']` and no `recipe` key (the current recipe is `pout-lts01-parts-v4`, dtmb5415.py:270). q2 `report/credibility.json` `vv20` reads `/data/dtmb5415/run_coarse.json + run_fine.json` and has four rows with `status: run`: Fr 0.10 S = 4.726e-3, u_num = 4.885e-3 (103 % of S), `validated: true`; Fr 0.28 S = 4.060e-3, u_num = 3.658e-3 (90 % of S), `validated: true`; Fr 0.41 `validated: true`; Fr 0.20 `validated: false`. `_validation` returns level 2 only because these four rows have all uncertainty terms (the sphere and wall-model rows have none, so without them the level is 1). The report text says "9 comparison(s) ran, 4 with all uncertainty terms, 3 with |E| <= U_val". CHANGELOG.md:144 itself calls the Fr 0.10 and 0.28 "passes" at 90 to 103 % of C_T meaningless and the first grid pair discarded.
why it matters: DECISION 144 says files of another recipe are refused, and CHANGELOG says the rows read "not run"; the shipped credibility report instead shows three validated rows and a Validation level of 2 from files the repo itself discarded.

### B-2. The emulator cannot reach `MIN_ROWS = 100` distinct feature points in any budget, so it never trains and no EMULATED answer can ever appear
severity: major
lane: statistics / performance
where: cafe/pm/whatif.py:50 (`MIN_ROWS = 100`), cafe/pm/budget.py:33 (`EMULATOR_VARIANTS` 2/6/24/48), cafe/pm/whatif.py:339-340 (`fit_class`: rows whose `code_digest` differs are not trained on), cafe/pm/pipeline.py:s_emulator
reproduction: `_rb/t6.py` on the demo mission: variants asked = got = 48 at overnight; rows per vehicle including the base mission = 49, so USV and UAS reach at most 49 distinct points and the glider class (two gliders) at most 98, all below 100. At quick, 7 rows per vehicle. q2 report, Emulator section: "2 glider rows in the training table, 100 are needed". Rows keyed by mission, class, vehicle, variant and features replace their predecessor on a rerun, and rows with another `code_digest` are excluded, and `code_digest` covers `config/` and `platforms/`, so a new commit or `make bench` empties the usable table.
why it matters: BRIEF 2.7(b), 2.7 acceptance and the "EMULATED" badge are unreachable even under `--budget overnight`; the only evidence of the emulator is the synthetic-table receipt, which BRIEF 2.7 forbids as sole training data. The flip search is always the 0 to 3 candidate Stage-1 fallback.

### B-3. The USV prior is described as calibrated to Chiodi's SOG/wind of 0.178, but in the demo mission the ensemble reaches 0.10 to 0.12
severity: major
lane: physics / honesty
where: DECISIONS.md:216 (row 163); config/perturbations.yaml:69-76 (citation text "reproduces Chiodi's mean SOG / wind = 0.1778"); cafe/pm/physics/usv.py:612-656 (`mean_sog`, the calibration scenario); cafe/pm/stage1.py:_run_usv
reproduction: `_rb/t7.py` reproduces the calibration: bias -0.2422 gives mean SOG 0.960 m/s at 5.4 m/s (ratio 0.1778) but only for 48 vehicles sailing to a station from 6 degrees away, uniform wind, no current, 12 h. In the q2 mission (`_rb/t2.py` on `/data/runs/q2/stage1/res.pkl`): mean path speed per member (sum of 10-min record displacements over 518400 s) is [0.62 0.49 0.65 0.53 0.72 0.62 0.63 0.64 0.53 0.47 0.66 0.59 0.55 0.94 0.98 0.41] m/s, mean 0.61. `report.json` environment: mean U10 along the USV median track 5.86 m/s (5.2 m/s after the fitted -0.62 m/s wind bias). Ratio 0.104 to 0.117, 35 to 41 % below 0.178. 13 of 16 members are `swept_off_track`, the first at 03-01 20:47Z, 8 h after deploy (westward drift of 25 to 85 km over the 20 km tolerance).
why it matters: the headline USV NO-GO (13/16, brief-bias case 31/32) rests on a speed model that, as used in the mission, is well below the observation it is said to be calibrated to; the report and the sanity block do not say so, and no bias-0 or mission-level SOG/wind row is shown.

### B-4. `cafe.pm fetch` (and `plan`, `run`) die with a raw PlanError traceback for a 30-day window or a large fleet; `fetch` plans a quick budget it never uses
severity: major
lane: robustness
where: cafe/pm/pipeline.py:84 (`Context.__init__` calls `budget.plan` for every command, including `fetch`); cafe/pm/budget.py:108-114 (`PlanError(ValueError)`); cafe/pm/__main__.py:118 (only `ConfigError` is caught); `fetch` has no `--budget` (line 31-37)
reproduction: `sed 's/end: "2023-03-07T12:00:00Z"/end: "2023-03-31T12:00:00Z"/' missions/tepex_c_demo.yaml > _rb/m30.yaml; pmx.sh env CAFE_OFFLINE=1 python -m cafe.pm fetch --mission _rb/m30.yaml` prints a Python traceback ending `cafe.pm.budget.PlanError: --budget quick: stage 1 needs 2546 s for even one batch of 4 members ... short by 2006 s`. Same for `plan --budget quick`, and for `plan --budget ci` on the demo. With 18 gliders + USV + UAS, `budget.plan('quick', ...)` raises likewise (`_rb/t4.py`: "20 veh quick PlanError", "30d quick PlanError"; overnight and 4h plan fine).
why it matters: the data download (the 2.5 h step of RUNBOOK 4) cannot be started for exactly the 30-day and 20-vehicle missions BRIEF 5.6 names, although those would run at `overnight`; the refusal is a traceback and exit 1, not "error: ..." and exit 2 as RUNBOOK's table promises.

### B-5. Ledger check `common_random_numbers` cannot fail and tests streams the run does not use; the UAS turbulence, gust fronts and Iridium sessions are keyed by batch
severity: major
lane: statistics / honesty
where: cafe/pm/pipeline.py:570 (`L.check("common_random_numbers", ...)`); cafe/pm/stats/sampling.py:133-137 (`crn_check`); cafe/pm/stage1.py:143, 156, 382 (`member_seed(seed, members[0], ...)`)
reproduction: `crn_check` builds `draws[v]` for each "vehicle" by calling `member_rng(base_seed, m, s)` with no vehicle argument, so the vehicles are identical by construction and the check can fail only if numpy is non-deterministic. The other half of the check, `same`, regenerates batch 0's Latin hypercube from the seed, which tests determinism, not CRN. The streams it uses are `member_rng(seed, m, "uas/turb/0")` and `"uas/gust"`; the run draws `member_seed(seed, members[0], f"uas/turb/{i}")`, `"uas/gust"` and `"iridium/<id>"` from the batch's first member (stage1.py:143, 156, 382). docs/PHYSICS.md section 13.2 and docs/CREDIBILITY.md section 5 admit the batch keying; the ledger check (stage1 ledger q2: `common_random_numbers ok True`, note "every vehicle draws the same stream values per member") says the opposite. Batch size changes which turbulence box segment member j flies.
why it matters: BRIEF 5.5 requires CRN to be verified; the passing check is the same kind of can-never-fail check round 1 reported as M-1/M-12, and the property it names does not hold for three of the four stochastic streams.

### B-6. Round-1 M-17 was not fixed for STATUS.md: it still says the pipeline does not exist, and there is no gap statement
severity: major
lane: documentation
where: STATUS.md:1-3 (audit of 2026-10-28), :77 ("missing: `run_premission --mission --budget --gpus` entry point, stage checkpoints ..."), :18-20 (Saildrone "missing"), :102 ("6-11 not started"); docs/BRIEF.md section 0 ("gap is written at the top of STATUS.md"), section 8
reproduction: `git log -1 --format=%h -- STATUS.md` returns `ab376fd` (the pre-pipeline commit "Quad at 2.5 ms, TEOS-10 seawater density, spec audit"); `grep -n "run_premission\|not started" STATUS.md`. CHANGELOG.md:152 lists the M-17 fix as DECISIONS rows 21/68, CREDIBILITY.md, RUNBOOK 7 and QUESTIONS items, not STATUS.md. merged.md M-17 required "add the BRIEF 0 gap statement at the top of STATUS.md" and "record the blind RUNBOOK run once done"; no such record exists (`grep -ri "fresh subagent\|blind" CHANGELOG.md DECISIONS.md STATUS.md docs/RUNBOOK.md` is empty).
why it matters: the file a lab reader opens first states that the tool they are running is missing; BRIEF 0.5 (a fresh-eyes RUNBOOK test) has no record of ever being done.

### B-7. The golden's clean-tree requirement is bypassed on the supported homebase path
severity: major
lane: reproducibility
where: cafe/pm/acceptance.py:192-198 (`_dirty`), :201-215 (`provenance_problems`, "unknown is not dirty"); compare cafe/pm/ledger.py:38-49 (`git_dirty`, which falls back to `$CAFE_GIT_DIRTY`); pm.sh:8 (rsync `--exclude .git`, passes `CAFE_GIT_DIRTY`)
reproduction: through `./pm.sh` the checkout on homebase has no `.git`, so `git -C ROOT status` returns non-zero and `acceptance._dirty()` returns None; it never reads `$CAFE_GIT_DIRTY`, which pm.sh sets for exactly this case. `_golden_record` then stores `dirty: null`, and `provenance_problems` only rejects `dirty is True`. The ledger path handles it (`ledger.git_dirty` reads the env var). So `./pm.sh python -m cafe.pm acceptance ... --update-golden` (the RUNBOOK 7 command) from a tree with uncommitted edits writes a golden that passes the DECISIONS 178 provenance test. The q2 ledgers also show `git_dirty: null` (the scratch runner omits the variable).
why it matters: DECISIONS 178 says the golden must record "a clean tree"; on the only path used to mint it, the control accepts a dirty one.

### B-8. A surfacing link written with the non-glider first is required at every record, not at surfacing
severity: major
lane: robustness / physics
where: cafe/pm/stage1.py:393 (`need = out[a]["surfaced"] if a in out else out[b]["surfaced"]`); validation accepts either order: cafe/pm/config.py:_check_links (`elif lk["when"] == "surfacing" and "glider" not in ends`, either end)
reproduction: `_rb/t5.py` builds one glider (surfaced at 1 record in 6) and one USV (surfaced always) and evaluates the same acoustic link `when: surfacing` in both orders over 433 records: `a=glider_eq, b=usv` gives `need_count` 73 per member; `a=usv, b=glider_eq` gives 433. `config.load_mission` accepts both (loaded `_rb/usv_glider.yaml` OK). The same line takes the first vehicle's flags when the first end is a UAS.
why it matters: a valid mission that names the pair the other way round silently counts about six times as many required moments; QUESTIONS_FOR_LAB 12 invites exactly this edit (it names `a: glider_eq, b: usv`, the safe order, but nothing says the order matters).

### B-9. RF and acoustic links to `shore` pass validation and then crash Stage 1 with KeyError
severity: minor
lane: robustness
where: cafe/pm/config.py:_check_links (nodes include the shore id, no kind restriction); cafe/pm/stage1.py:289-299 (`_pos`: the ship is special-cased, `shore` falls through to `out[node]`)
reproduction: `_rb/shore_rf.yaml` (demo with `usv-uas-rf` replaced by `{a: usv, b: shore, kind: rf, radio: rfd900x, when: always, required_fraction: 0.95}`) loads without error; `_rb/t5.py` last block: `stage1.evaluate_link` raises `KeyError: 'shore'`.
why it matters: this is the failure class M-27 set out to remove (validator accepts, deep KeyError after ingest); the shore has no position, so only Iridium is meaningful.

### B-10. Ingest check `swh_spectrum_vs_file` is an identity (5e-16), so it cannot fail
severity: minor
lane: honesty
where: cafe/pm/pipeline.py:332-348 (`_swh_error`), :410; cafe/pm/env/waves.py:95-127 (both components "renormalised ... so 4 sqrt(m0) = hs exactly")
reproduction: q2 ingest ledger: `swh_spectrum_vs_file ok True, value 5.08e-16, limit 0.01`. The synthesised E is built as `(hs^2 - w) A + w B` with A and B each normalised to unit Hs^2 and `w` clipped to [0, hs^2/2], so the Hs of the result equals the input Hs for any input. The check says nothing about Tp, direction or the mss fit (the clip means the mss does not always match; no ledger number reports that).
why it matters: BRIEF 2.1/5.5 intended the synthesised spectrum to be tested against the file; a 5e-16 pass is a statement about the normalisation line.

### B-11. UAS `max_tilt_deg` is 35.00 in all 96 sorties, so the attitude diagnostic carries no wind information
severity: minor
lane: physics
where: cafe/pm/physics/uas.py:303 (`k = jnp.minimum(1.0, fz * jnp.tan(tilt_lim) / fh)`), :338 (`flying & (tilt > tilt_exc)`); platforms/quad_uas.yaml:82-88 (limit 35 deg, exceedance 42 deg)
reproduction: `_rb/t3.py` on q2 `res.pkl`: over 6 sorties x 16 members `max_tilt_deg` has min 35.00, max 35.01, unique value 35.0, at launch winds from 2.2 to 7.96 m/s. `attitude_exceedance` fires in 0 members. With the commanded horizontal force clamped to g tan 35 deg, a 42 deg flag is reachable only through dynamic overshoot of 7 deg.
why it matters: the mode that should discriminate gust-front windows (BRIEF 6 expects UAS NO-GO there) saturates at the controller clamp every sortie; the demo UAS verdict is a battery verdict only, and the sanity row for the UAS is "cannot be checked".

### B-12. The UAS stage-3 window still diverges after the M-3/DECISION 161 fix
severity: minor
lane: numerics
where: cafe/pm/stage3/pipeline_windows.py (UAS case, `leg_clipped`); DECISIONS.md:214 (row 161)
reproduction: q2 `stage3/windows.json` uas: `kinematics: v_rel_ms 12.0, tilt 33.6, leg_clipped True`; report checks `mach_max 8.849` (limit 0.1) and `courant_max 5.109` (limit 0.3), `cd: nan`. q1 had mach 7.4. The input is now inside the envelope (wind 5.96 m/s, leg 6.1 m/s) and the kernel still blows up; the fix changed the inputs, not the stability.
why it matters: no UAS LES window has ever run to completion; the report and CHANGELOG present the M-3 fix as done.

### B-13. `code_digest` leaves out `cafe/schemas/*.json`, which ingest and `load_mission` treat as the contract
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:51-62 (`rglob("*.py")`, `config/*.*`, `platforms/*.yaml`); cafe/pm/env/orca.py:34-58 (reads `cafe/schemas/wrfout.json`, `umwmout.json`, `umwmrst.json`); cafe/pm/config.py:SCHEMAS
reproduction: `find cafe -type f ! -name '*.py' ! -name '*.pyc'` lists `cafe/schemas/*.json`; none is hashed. Editing `wrfout.json` (units, a variable) does not change `Context.hash`, so `--resume` keeps the ingest ledger and every stored result as current.
why it matters: M-15 made the digest cover `cafe/**/*.py` so stale code is not reused; the data contract is outside it.

### B-14. The sensitivity case is not "the same ensemble under another setting of one input"
severity: minor
lane: statistics / honesty
where: cafe/pm/report.py:303, :808 (wording); cafe/pm/stage1.py:496-505 (`sensitivity_case`); cafe/pm/pipeline.py:SENSITIVITY_MEMBERS = 32
reproduction: the main USV ensemble is a 16-member Latin hypercube (`lhs(16, ...)`, plan batch 16); the case calls `run_batch(... range(32) ...)`, so `sampling.lhs(32, ...)` draws different strata for every parameter, and members 16 to 31 are new. q2 compares 31/32 (brief bias) with 13/16 (calibrated).
why it matters: the difference between the two verdicts mixes the prior change with a different design and twice the members; the header promises a one-input change.

### B-15. Credibility "Uncertainty characterization" is scored from the stage-1b ledger, so any run without a refit scores 1 though the stage-1 ledger has the passed LHS checks
severity: minor
lane: honesty
where: cafe/pm/credibility.py:383-400 (`_uncertainty`, line 388-393)
reproduction: q2 `credibility.json` factors: uncertainty level 1, missing "no passed Latin-hypercube stratification check in the stage-1b ledger (a copied stage 1b has none)", while `checkpoints/stage1/ledger.json` has `lhs_stratified_batch1 ok`. Stage 1b is a copy whenever no window passes, which is every CPU run.
why it matters: the score depends on whether a copy was made, not on the evidence; the factor is understated by one level.

### B-16. "First failure" and "median failure" are taken over the dominant mode's members only
severity: minor
lane: statistics
where: cafe/pm/stage1.py:470-473 (`first = r["first"][dom]`, `t_first`, `t_med`)
reproduction: for modes A with 3 members (first failures on day 4) and B with 2 other members (first failures on day 1), `dom = A`, so `first_fail_t` is day 4 and `median_fail_t` is the median over A's 3 members, while the earliest failure and the median over all failed members are day 1. In q2 the dominant mode covers every failed member (`_rb/t10.py` shows the same earliest and median), so the numbers shown are right here; the code is not.
why it matters: the report labels them "First failure" and "median failure" of the vehicle.

### B-17. Link moments before a vehicle's deploy time count as required (and, for position, as at the deploy point)
severity: minor
lane: data / statistics
where: cafe/pm/stage1.py:384 (Iridium `need = ones`), :399 (`when: always`), :393 (`np.interp` of `surfaced` clamps to the first value before `r["t"][0]`), :289-299 (`_pos` clamps likewise)
reproduction: record grids start at the vehicle's own deploy time (`_record_grid`); the link grid is the whole window (`t = arange(t0, T+1, REC_S)`). A vehicle deployed 48 h after the window start (the what-if "deploy 48 h later") has 48 h of a `when: always` or `surfacing` link counted as needed at its deploy point. The demo deploys at window start, so q2 is unaffected.
why it matters: link verdicts change with a deploy shift for reasons unrelated to the environment.

### B-18. A Tp perturbation changes Tp and Tm but not the Stokes drift
severity: minor
lane: physics
where: cafe/pm/env/perturb.py:147-170 (`PerturbedEnv.waves`: `stokes0` scaled by `hs ** 2` only)
reproduction: Stokes surface drift goes as Hs^2/T^3 for a narrow spectrum; with `tp_bias` sd 1 s on a mean Tp near 9 s, Tp = 8 s changes it by about 40 %. The code applies `hs_scale` to `stokes0` and ignores `tp_bias`.
why it matters: member wave states are internally inconsistent; the Stokes uncertainty that reaches the USV and glider drift is understated.

### B-19. The 3-D wind hours requested at ingest cover only [h, h+1] of a sortie launched in hour h
severity: minor
lane: data
where: cafe/pm/pipeline.py:493-500 (`_sortie_hours`: `out += [h, h + 1 h]`, duration not used); cafe/pm/env/environment.py:_wind3d (falls back to the log profile outside an ingested hour pair)
reproduction: `local_solar_time` 14:50 and `duration_min` 20 give a sortie that ends 70 min after the hour start, past h+1; the last 10 min fly on the 10 m scaled profile (source string changes mid-sortie), silently. The demo launches at :00, so q2 is unaffected.
why it matters: arbitrary launch minutes (a normal edit) change the wind model inside a sortie without a ledger note.

### B-20. Absurd or overlapping sortie schedules are accepted; non-daily schedules are anchored to the epoch day, not the first launch
severity: minor
lane: robustness
where: cafe/schemas/mission.json:54 (`every_days` exclusiveMinimum 0 only); cafe/pm/stage1.py:101-108 (`launch_times`)
reproduction: `_rb/t8.py`: `every_days: 1e-6` is ACCEPTED; `launch_times` then returns about 7.5 million launches for the 6-day window. `_rb/t1.py`: `every_days: 2.0` first launches on 03-03 01:00Z (the 03-02 slot is skipped), `1.5` gives launches at 13:00Z although `local_solar_time` is 14:00 local (02:00 local); the phase comes from `floor(t0/86400)`, so shifting the window start by a day changes which days fly. A period shorter than `duration_min * hard_stop_factor` makes sorties of one UAS overlap.
why it matters: no refusal for a schedule that cannot run; "every 2 days" does not mean "starting at the first slot".

### B-21. RUNBOOK troubleshooting row and a PHYSICS statement are stale after the planner change
severity: minor
lane: documentation
where: docs/RUNBOOK.md:146 (`ensemble capped at 32 members by the stage-1 share`); docs/PHYSICS.md:838 (quick `n_min / n_max` 32 / 64)
reproduction: q2 `plan.json` notes: "ensemble capped at 16 members by the stage-1 share ... (502 s per batch of 16 + 1.88 s per member)", `n_min = n_max = 16`; the demo at quick plans 16 members (`_rb/t4.py`: `demo quick n_max 16 batch 16`). The row a user greps for does not match and describes 32.
why it matters: the first thing a quick run prints does not match the table meant to explain it.

### B-22. docs/CREDIBILITY.md says "twelve" limitations and omits L13
severity: minor
lane: documentation
where: docs/CREDIBILITY.md:14, :71, section 5 table; cafe/pm/credibility.py:55 (`SUBGRID_LIMITATION`, id L13, caps validation and uncertainty); DECISIONS.md:232 (row 179)
reproduction: `grep -n "L13" docs/CREDIBILITY.md` is empty; q2 `credibility.json` lists L01 to L13 and the Uncertainty factor's `limitations` includes L13. The file says it is "copied from [the code] and must be kept the same" and was "checked against credibility.py on 2026-10-31".
why it matters: the "What the current build can reach" table (Validation caps, Uncertainty caps) is wrong for L13.

### B-23. `make audit` gates ruff, mypy, coverage and the banned-token scan on `cafe/pm` only; BRIEF 5.5 says `cafe/`
severity: minor
lane: honesty / documentation
where: pyproject.toml:6-15 (`ruff include`, `mypy files = ["cafe/pm"]`, coverage `source = ["cafe/pm"]`); cafe/pm/audit.py:27 (`SCAN`), :29 (`GATES`)
reproduction: `find cafe -name '*.py' -not -path 'cafe/pm/*' | xargs wc -l | tail -1` is 7156 lines (cafe/cfd.py, fea.py, emulator.py, reach.py, receipts.py and others the pipeline imports, see pipeline.py:code_digest docstring) outside every gate. `grep -n placeholder REVIEW.md` (line 100) is in the repo but outside `SCAN`. No DECISIONS row records the narrowing.
why it matters: the audit reports "0 problems" for a narrower tree than BRIEF 0.7 and 5.5 describe.

### B-24. The reach map uses speeds Stage 1 does not fly
severity: minor
lane: honesty
where: config/assumptions.yaml:328-336 (`reach.speed_ms.usv` 1.4); cafe/pm/report.py:439-441; cafe/pm/physics/usv.py (calibrated polar)
reproduction: q2 report: USV "farthest reachable cell 155.9 km ... at 1.4 m/s through the water (assumed)" in 24 h. From `res.pkl` (`_rb/t2.py`) the fastest USV member covers 509 km in 6 days (85 km/day) and the mean is 0.61 m/s.
why it matters: the map and the member tracks sit in one figure, and the outline is larger than anything the ensemble reaches.

### B-25. Acoustic noise is computed from the unperturbed wind
severity: minor
lane: statistics
where: cafe/pm/stage1.py:403 (`env.env.u10(...)`; every other forcing in the same function uses the member's perturbed `env`)
reproduction: `evaluate_link` takes `env` = PerturbedEnv, then calls `env.env.u10`, i.e. the underlying WRF wind without `wind_speed_bias` / `wind_direction_bias`. Stojanovic wind noise is 7.5 sqrt(w) dB; a member whose wind is 1.3 m/s (the fitted sd) lower is about 2 dB quieter, in a Bellhop trigger band of +-6 dB. RF uses the member's own Hs (CHANGELOG.md:127).
why it matters: breaks the one-environment-per-member rule for the acoustic margin.

### B-26. The planner's memory guard is dead code
severity: minor
lane: performance
where: cafe/pm/budget.py:218 (`memory_guard`), `plan(..., gpu_mem_gb=None)` sets `les["max_cells"]` only when `gpu_mem_gb` is passed; cafe/pm/pipeline.py:84 (`budget.plan(... )` never passes `gpu_mem_gb`)
reproduction: `grep -rn "memory_guard\|gpu_mem_gb" cafe/pm` shows no caller outside budget.py; the working guard is `lbm.check_memory` at cafe/pm/stage3/windows.py:254, inside a window.
why it matters: BRIEF 3 says the planner refuses a configuration over 85 % of GPU memory and says what to reduce; a too-large plan is accepted and fails mid stage 3.

### B-27. The sanity row for the acoustic links says the distance "is not in the verdict", though the report holds it
severity: minor
lane: honesty
where: cafe/pm/credibility.py:89-90, :558; cafe/pm/report.py:1048
reproduction: q2 report: glider_eq-ship-acoustic and glider_2n-ship-acoustic "out of the acoustic model's range at 1 fraction of the needed samples", gliders 555 and 598 km from the ship (QUESTIONS_FOR_LAB 12), yet the sanity table prints "cannot be checked from the verdict". The data show the brief's "NO-GO at more than 3 km" is met (agrees), and QUESTIONS_FOR_LAB 12 already says the geometry decides.
why it matters: a table that exists to compare with BRIEF 6 leaves a checkable row unanswered.

total: 27 findings (0 critical, 8 major, 19 minor)
