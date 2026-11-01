# Round 3, reviewer B

Scope: all lanes of BRIEF 5.6, at commit `73bf4c7` (branch `premission-step4`), against the q3 quick run (`/private/tmp/claude-501/.../scratchpad/q3`, binaries read from `~/work/cafe/pmdata/runs/q3/` on homebase).
Nothing in the repo was edited. Checks ran at 1 CPU through `pmx.sh` (`PMX=pm_rev3_b`): python snippets only, plus one targeted pytest run (`tests/test_config.py test_perturb.py test_stats.py test_budget.py test_conventions.py`, all passed).
Checked and found sound (so not reported): Wilson / Newcombe / `n_certify` arithmetic, EASI sensitivity and its permutation floor, LHS strata and antithetic pairs, the wind-error fit of DECISIONS 182/209 (recomputed 0.1131 m/s from `tao_compare.json`), the Thorp / Stojanovic / two-ray / Ament / radio-horizon formulas, Stokes drift, Okubo K and dK/dy, WRF destaggering, the GEBCO sign, the Celik GCI, Seaglider steady flight (0.20 m/s ground speed in still water, station lost above about 0.25 m/s of current), USV VPP calibration (SOG / wind 0.183 on a beam reach in 5.4 m/s, no current), UAS dynamics and battery.

Order: major, then minor.

---

### B-1. The emulator's training variants all reuse one hypercube, so its hold-out RMSE gate and conformal coverage are measured on correlated targets and its debiasing subtracts noise that is not there
severity: major
lane: statistics
where: cafe/pm/pipeline.py:1012 (`whatif.run_variant(mv, ctx.env, list(range(ctx.plan["batch"])), seed, ...)`); cafe/pm/stage1.py:288 (`sampling.lhs(M, marg, np.random.SeedSequence([seed, members[0]]), ...)`); cafe/pm/whatif.py:301 (`run_variant` -> `run_batch`) and :403-407 (`floor`, `deb`, `rmse_ok`); cafe/pm/emulator.py `fit` (calibration rows) and `holdout_report`
reproduction: Every variant v0..vK of `s_emulator` calls `run_batch` with members `0..batch-1` and the run's own seed. `U, X` come from `SeedSequence([seed, 0])` and every per-member stream (wind noise, current field, SDE, windage) from `member_rng(seed, m, ...)`, so U, X and all member noise are identical in every variant and equal to the first batch of the baseline. Check: `np.array_equal(stage1.run_batch(mv0, env, list(range(32)), seed, pri, marg)["U"], stage1.run_batch(mv1, env, list(range(32)), seed, pri, marg)["U"])` is True for any two variants. So the training rows' `p_fail` are fractions of the same 32 (quick) to 128 (overnight) members: their binomial errors are shared, not independent. `fit_class` then takes `floor = sqrt(mean(p(1-p)/n_members))` (0.08 at p = 0.3, n = 32) and reports `deb = sqrt(max(rmse^2 - floor^2, 0))`, and `rmse_ok = deb <= 0.05`. A GP that interpolates the shared sample has a small raw hold-out RMSE (it is fitting the same noise on both sides of the split), so `deb` goes to 0 and the gate passes, although the error against the true P(fail) cannot be below the 0.08 Monte-Carlo sd at n = 32. The conformal scores are likewise computed on held-out points whose targets carry the training points' noise, so the "90 % coverage" holds for rows of this one sample, not for the P(fail) of a new run with another seed. Not visible in q3 (the emulator did not train: 1 to 2 points per class), it appears at the first run that reaches 100 distinct points (overnight gives 49 per vehicle in one run).
why it matters: BRIEF 2.7's acceptance (RMSE <= 0.05 against P(fail), coverage within 5 % of nominal) can be passed by construction, and every EMULATED answer would carry an interval that under-covers for a new ensemble.

---

### B-2. Resume hash, config hash and the receipt ids in `report.json` depend on how the mission path is spelled
severity: minor
lane: reproducibility
where: cafe/pm/config.py:174 (`m["_path"] = str(path)`); cafe/pm/pipeline.py:110 (`self.hash = digest(dict(mission=self.mission, ...))`)
reproduction: `Context("missions/ci_fixture.yaml","ci",0,"/tmp/x").hash == Context("/app/missions/ci_fixture.yaml","ci",0,"/tmp/x").hash` is False (a68aa5ffdfb2 vs b491f00ef717), and the `./missions/../missions/...` spelling gives a third value. The hash is the ledger `config_hash`, so it appears in the report as `ingest:config:aef70c53c18e` and in every stage's resume test (`ledger.done`).
why it matters: RUNBOOK 5 promises "same seed + same machine bench = the same `report.json`" and "rerunning the same command skips every stage"; both fail when `fetch` and `run` (or two runs) name the mission with different spellings, silently recomputing and renaming every config receipt.

---

### B-3. UAS failure times are float32 epoch seconds: 128 s resolution, printed to the second
severity: minor
lane: numerics
where: cafe/pm/stage1.py:257 (`s["t_first"][k] + s["t_launch"]`); cafe/pm/physics/uas.py:512 and :569 (same sum); report line "First failure"
reproduction: In `stage1b/res.pkl` of q3, `vehicles["uas"]["first"]["battery_reserve"].dtype` is float32 (every glider and USV `first` array is float64). The JAX `t_batt` (seconds since launch, float32) plus a Python-float `t_launch` stays float32 under NumPy 2 promotion; at 1.68e9 s the spacing is 128 s. The three failing members read `[1677892992, 1678065664, 1677892992]`, all exact multiples of 128 (1677892992 = 13108539 x 128), which is why the report says "First failure: 2023-03-04 01:23:12Z; median failure: 2023-03-04 01:23:12Z" (two members tie because of the rounding). Every UAS `first_fail_t`, `median_fail_t` and the emulator's `t_fail_h` inherit it.
why it matters: the failure instant is wrong by up to 64 s and shown to the second; the first and the median failure are the same number only because of the quantisation. Fix: `np.float64(s["t_launch"]) + s["t_first"][k].astype(float)`.

---

### B-4. `--gpus N` is trusted with no GPU present: the plan, the stage-1 ensemble and the report label follow a GPU that does not exist
severity: minor
lane: robustness
where: cafe/pm/budget.py:72-78 (`lbm_rate`: with `gpus > 0` and no measured GPU entry it returns 0.95 x 20.8e9 cell-updates/s "projected from published benchmarks"), :132 (`runs = gpus > 0 or ...`), :217 (`label "GPU LES windows"`); cafe/pm/__main__.py `_gpu_mem` (no `nvidia-smi` gives `None`, silently); cafe/pm/stage3/lbm.py:71-80 (`pick_backend` falls back to "jax" without a word)
reproduction: on homebase (no `nvidia-smi`): `python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget quick --gpus 1` exits 0, prints "1 GPU(s)", shrinks stage 1 from 32 to 16 members ("ensemble capped at 16 members", because stage 3 now holds 30 % of the budget: `plan["shares"] = {stage1 .45, stage3 .30, stage1b .15, emulator .05}`), and `plan["les"]["label"]` is "GPU LES windows" with `runs: true, reachable: false` for every part (need 3e20 cell-updates for `usv/hull`, afford 8e11). The run would execute those windows on the CPU at 7.5e6 cell-updates/s and cut them.
why it matters: BRIEF 4.0 "Missing GPU -> CPU path with labels, refuse, never guess". RUNBOOK 6 tells the lab to add `--gpus all` to the `docker run` by hand; forgetting it gives a halved ensemble, 30 % of the budget burnt on cut windows and a report that says "GPU path" and "projected from published benchmarks".

---

### B-5. `validate` accepts platform / class mismatches and links that cannot exist, and the run then dies in stage 1 (after the ingest) with a non-actionable error
severity: minor
lane: robustness
where: cafe/pm/config.py:87-91 (`_klass`), :93-130 (`_check_links`), cafe/pm/stage1.py:40-45 (`_classes`)
reproduction: edit `missions/tepex_c_demo.yaml` and run `python -m cafe.pm validate`: (a) `vehicles[uas].platform: seaglider` (still has `base: ship`) is accepted; stage 1 then calls `uas.load_platform("seaglider")` -> `ValueError: platform numbers without a source or an assumed+why: ['kind']`. (b) `vehicles[glider_eq].platform: quad_uas` is accepted; `glider.load_platform("quad_uas")` -> `KeyError: 'params'`. (c) `links: {a: uas, b: ship, kind: acoustic, when: always}` is accepted (an aircraft with an underwater modem); `evaluate_link` computes a Thorp budget with depth 0 for the UAS. Class is decided by `base` alone (tests/test_stage1.py even pins `{"a": "uas", "b": "glider"}` for `quad_uas` with and without a base), and nothing checks that the platform file is of that class.
why it matters: BRIEF 4.0 asks for "a specific, actionable error naming the file, field and fix" for a vehicle yaml that does not fit; here the failure comes hours into a run, with a bare `KeyError`.

---

### B-6. A deploy time within one minute of the window end is valid for `validate` and crashes stage 1
severity: minor
lane: robustness
where: cafe/pm/config.py:151 (`t0 <= deploy < t1`); cafe/pm/stage1.py:64-68 (`_record_grid`, `h[k][n - 1::n]` on an empty history), :83 and :95 (`sim.run(T - t0, dt=60)`)
reproduction: `stage1._run_glider(v, SG, AnalyticEnv(...), 4, X, 0.0, 30.0)` and `stage1._run_usv(..., 0.0, 30.0)` (a deploy 30 s before the window end) raise `ValueError: all the input arrays must have same number of dimensions, but the array at index 0 has 2 dimension(s) and the array at index 1 has 1 dimension(s)`; `T = 59 s` runs (one step). A mission with `deploy.time: "2023-03-07T11:59:30Z"` passes `validate`.
why it matters: the schema/loader accept it, the run crashes after the ingest; a minimum run length (one step, or better one record) should be refused by `load_mission` naming the field.

---

### B-7. In dead calm with no current the USV is reported as `wing_stall`, never `becalmed`
severity: minor
lane: physics
where: cafe/pm/physics/usv.py:571-572 (`self.vmax < cv.speed(cur)`, strict), :576-578
reproduction: `stage1._run_usv(v, UP, AnalyticEnv(wind=(0,0), current=(0,0)), 4, X, 0.0, 86400.0)` -> failures `{'wing_stall': 4}` and no `becalmed` (0.0 < 0.0 is False). With a current of 0.01 m/s `becalmed` fires. The BRIEF's definition ("SOG < current") is read as through-water speed < current speed (DECISION in the module), which has no meaning when the current is zero: a boat that cannot move at all is not becalmed.
why it matters: the failure label that reaches the report ("wing stall", with its sensitivity and "what would fix it") is wrong in exactly the zero-wind edge case BRIEF 5.6 lists; the verdict (NO-GO) is right.

---

### B-8. Link requirements are applied to 6 to 12 samples per member, so "required_fraction 0.95" means "every sample"
severity: minor
lane: statistics
where: cafe/pm/stage1.py:419-422 and :434-438 (`need` on the 10-minute `REC_S` grid), `frac >= lk["required_fraction"]`; missions/tepex_c_demo.yaml links `usv-uas-rf` (0.95), `glider_*-ship-acoustic` (0.9)
reproduction: from q3 `stage1b/res.pkl`, `links["usv-uas-rf"]["need_count"]` is 6 to 12 per member (median 9; 291 airborne records for 32 members x 6 sorties of 20 to 32 min, so 1 to 2 records per sortie, the first at the launch instant when the UAS is on deck); `frac` can only take the values k/6 .. k/12, so one missed sample already puts a member below 0.95 (1/12 = 0.083 > 0.05). Acoustic links have 15 to 92 records per member.
why it matters: the member-level success of a link is decided by one or two records per sortie, and by where the launch falls on the 10-minute grid, not by the 0.95 / 0.9 fraction the mission asks for. In the demo the links fail by geometry anyway (89 % of the needed samples beyond the horizon; 555 and 630 km for the acoustic ones), so the verdicts are not changed; a real mission with a UAS leg inside the horizon would be.

---

### B-9. The "worst window" and the environment shown at it are taken from the unperturbed field, not from the field the failed members flew in
severity: minor
lane: honesty
where: cafe/pm/pipeline.py:848-856 (`ctx.env.current / ctx.env.waves / ctx.env.u10`, the base `GriddedEnv`); report lines "surface current speed at the worst windows ... (failed members)"
reproduction: `s_windows` selects the failed members and takes, over their records, the strongest forcing, but evaluates it with `ctx.env` and not with the member's `PerturbedEnv`. In q3 the UAS window "10 m wind speed 5.957 m/s (failed members)" is WRF's wind before the fitted -0.616 m/s bias and the member's AR(1) noise (sd 1.28 m/s, 22 deg); the USV's "Hs 2.272 m" is before each member's `hs_scale` (lognormal sd 0.15); and the three failed UAS members failed on 4 and 6 March, while the window is a record of 7 March 01:10Z.
why it matters: "the record where the failed members met the strongest forcing" (docstring, BRIEF 2.6) is not what is computed; the time-varying member wind error, which is where the ensemble's failures come from, is ignored when picking the moment that gets the LES.

---

### B-10. docs/PHYSICS.md and the credibility table still describe the pre-round-2 sigma handling
severity: minor
lane: documentation
where: docs/PHYSICS.md:487-488 (`N(-0.62, 1.33) m/s`, `N(+7.2, 23.7) deg` shown as the fitted priors) and :499-500 ("`env.sigma.sst_k` and `env.sigma.t2_k` stay at their assumed values (0.5 K, 1.0 K) although ..."); config/assumptions.yaml `env.sigma.*`; credibility `assumed_inputs`
reproduction: the q3 ingest ledger note says "env sigmas fitted from the moorings: {'sst_k': 0.2592, 't2_k': 1.1908}" and `Context.env` (pipeline.py:123) reads `ingest/env_sigmas_fitted.json`, so the sigmas the environment values are tagged with are the fitted ones; PHYSICS says they are not. The same credibility report lists `assumptions.yaml:env.sigma.sst_k (assumed) 0.5 K` and `env.sigma.t2_k (assumed) 1.0 K` as inputs of this run (the wind priors beside them correctly read "this run drew ... (fitted)"). The first PHYSICS block also still gives the pre-182 prior `N(-0.62, 1.33)` that the code no longer uses (the real one is `N(-0.616, 0.113)`), with the correction only in the paragraph below it.
why it matters: a reader of PHYSICS gets the wrong numbers for the wind prior's width and the wrong source for two tagged uncertainties; the credibility table counts two fitted values as assumed.

---

### B-11. The README quick start does not run
severity: minor
lane: documentation
where: README.md:20-22; Makefile header ("Every target runs where it is invoked (inside the cafe-pm image ...)"); docs/RUNBOOK.md section 1
reproduction: the three README lines are `make install`, `make fetch`, `bin/run_premission --mission ...`. `make install` only builds the docker images; `make fetch` and `bin/run_premission` then run `python -m cafe.pm` on the host, where numpy / jax / xlb / gsw / smt are not installed (on this laptop, Python 3.9: `python3 -m cafe.pm validate --mission missions/tepex_c_demo.yaml` ends in `TypeError: unsupported operand type(s) for |` at `physics/comms.py:39`). RUNBOOK 1 defines the `pm()` wrapper and prefixes every command with it.
why it matters: the README is the file a lab member opens first; its three-command path fails at the second command.

---

### B-12. The report headline says four stale receipts "record a failed result"
severity: minor
lane: honesty
where: cafe/pm/report.py:1212; cafe/pm/report.py:119-121 (`n > 0, f"{n} of {len(ws)} windows passed their self-checks"`)
reproduction: the q3 page says "5 of 24 receipts below record a failed result and are marked FAILED OR MISSING: physics:pm.physics.comms; ...glider; ...uas; ...usv; stage3:output:windows.json". The four physics rows read "stale: made by other code" (the receipts table was not rerun; no result was recorded), and the fifth is "0 of 6 windows passed" where five of the six windows were never run (planned skips, stage-3 ledger 'every_failed_window_states_a_reason' ok).
why it matters: a stale table and a deliberate skip are shown as failed results; the page cannot tell a reader which of the five is a failure.

---

### B-13. The banned-token scan of `make audit` is narrower than BRIEF 5.5 and a literal grep of the repo hits
severity: minor
lane: documentation
where: cafe/pm/audit.py:25-31 (`SCAN`, `IMPORTED`, `EXEMPT`)
reproduction: `grep -rnE "TODO|FIXME|XXX|NotImplementedError|placeholder|xfail" cafe/static cafe/*.py REVIEW.md docs/BUILDERS.md` gives `cafe/static/index.html:151,153,159,163,164,165`, `cafe/static/app.js:540`, `cafe/static/vendor/OrbitControls.js:1189`, `REVIEW.md:100`, `docs/BUILDERS.md:18`. The audit regex also leaves out `skip\(` (BRIEF 5.5 lists it). `SCAN` covers `cafe/pm`, 15 older modules, tests, bench, platforms, missions, config, RUNBOOK and the Makefile, so these never fail the audit.
why it matters: BRIEF 0.7 / 5.5 say the repo contains zero of these tokens and the audit "greps the repo"; DECISIONS 205 records the narrowing for the older modules but not for the static app, `lab/`, `report/` and the other docs.

---

### B-14. STATUS.md test statistics predate DECISIONS 208 and 209
severity: minor
lane: documentation
where: STATUS.md section 1 ("1,757 `def test_` in 47 files, 2,040 collected cases; all 2,040 passed on the integrated round-2 tree ... coverage 100 % of 11,920 statements")
reproduction: `grep -rn "def test_" tests | wc -l` at `73bf4c7` gives 1,760 (1,759 in `tests/test_*.py`); DECISIONS 208 and 209 and the stage-3 skip-reason commit added tests after the run that the sentence reports, and no run on the current tree is recorded.
why it matters: the file says what was verified; the figures and "all passed" describe a tree that is three commits behind (the targeted run above passed, but the full-suite and coverage claim is not re-measured).

---

total: 14 findings (0 critical, 1 major, 13 minor)
