# Reviewer A, round 6: findings on commit 739fe5c

Method: read BRIEF 5.6, the q6 ledgers, `report.json`, `index.html`, `credibility.json`, the stats modules, config, stage1, USV, glider and UAS physics, RUNBOOK and
PHYSICS. Recomputed every Wilson interval in the report from k and n (all agree). Probed the simulators with hostile analytic environments and one synthetic
`ci_env` (1 CPU, container `cafe-pm`, private dir `pm_rev6_a`). Scripts: `.../scratchpad/rev6/a/t1.py` (config), `t3.py` (USV), `t4.py` (glider), `t5.py` (UAS), `t7.py` (UAS forcing at the end of the window).

### A-1. A USV whose wave height (or period, direction or Stokes drift) is NaN turns into a NaN position with no failure flag, and counts as a pass
severity: major
lane: robustness
where: cafe/pm/physics/usv.py:546-549 (only wind and current are checked for non-finite values), usv.py:557-566 (Hs, Tp, dir_to, stokes enter the speed and the position update), cafe/pm/stage1.py:449-456 (`_left_data` ignores non-finite positions), stage1.py:671-672 (`failed` is the OR of the flags only), cafe/pm/env/environment.py:84-86 (UMWM fields are NaN wherever `seamask` is 0)
reproduction: on homebase, `AnalyticEnv(hs=float('nan'))`, `usv.USVSim(P, 4, env, (-165,-1), 0.0, dict(mode='section', waypoints=[(-165,-1),(-165,1)]), perturb=dict(vpp_bias=np.full(4,-0.24))).run(6*3600, dt=60, record_s=60)`
  gives `lon = [nan nan ...]`, `lat = [nan ...]` at the last record and every entry of `fail` False (`no_current_data` False too). NaN wind is caught (`no_current_data` True, same script,
  case "wind nan"), NaN Hs is not. In the real environment `GriddedEnv.waves` returns NaN Hs on every UMWM non-sea cell, while the current comes from the separate HYCOM store, so a cell
  that is land in UMWM and ocean in HYCOM (any island or reef the 12 km mask drops, or the edge of the sea mask) gives exactly this. The round-5 fix for the UAS link (`fill_hs`, M-10) was not applied to the USV.
why it matters: the member is not failed, not flagged `left_data`, drops out of the sensitivity rows and reads as a success in P(fail), so a bad cell biases a verdict toward GO without a trace.

### A-2. A UAS launch inside the last hour of the window passes `validate` and then aborts Stage 1 with OutsideData
severity: major
lane: robustness
where: cafe/pm/stage1.py:219-221 (`hours = np.arange(floor(ts[0]/3600)*3600 - 3600, ts[-1] + 7200, 3600)` is passed to `env.rain_hourly`), cafe/pm/env/environment.py:142-152 and 150 (`_check` raises when the start of an hour is past the last ingested hour), cafe/pm/config.py:226-233 (`validate` only requires launch + 1.6 x duration <= window.end)
reproduction: `tests.fixtures.ci_env.make` into a temp dir, GriddedEnv as in `tests/conftest.py::ci_full`, mission `missions/ci_fixture.yaml` (window ends 2023-03-03T06:00Z) with `window.start` 2023-03-02T06:00Z, one UAS, `every_days: 3`, `duration_min: 20`, `local_solar_time` chosen so the launch is 05:05, 05:20 or 05:28 UTC on 3 March
  (`validate`/`load_mission` accept all three; 04:50 is fine). `stage1._uas_forcing(env, mm, origin, ts, P, 2, 1, [0, 1])` raises
  `OutsideData: WRF rain_hourly: (-165.000, 0.000) at 2023-03-03 07:00:00Z is outside the ingested data (... 2023-03-01 18:00:00Z..2023-03-03 06:00:00Z)`. Direct call: `env.rain_hourly([-165],[0],[end+3600])` raises the same. Any launch later than window.end - 1 h and no later than window.end - 32 min crashes (a 28 min band).
why it matters: a valid mission whose last daily sortie falls near the end of the window fails the whole run after ingest, with a message that tells the user to widen the box or window, not that the gust-front look-ahead is reading two hours past the launch.

### A-3. PHYSICS.md section 5.2 and DECISIONS row 37 still say the pipeline omits theta_e; the code passes it
severity: minor
lane: documentation / honesty
where: docs/PHYSICS.md:340-341 ("The pipeline does not pass `theta_e` to `gust_fronts` ... f = 1 ... `theta_e_lo_K` and `theta_e_span_K` are not used by a run"), DECISIONS.md:60 (row 37, "The pipeline omits `theta_e` (f = 1)"); contradicted by cafe/pm/stage1.py:187 and 220-221 (`te = subgrid.theta_e(...)`, `subgrid.gust_fronts(..., theta_e_K=te, ...)`) and CHANGELOG.md:123 ("`7a359dd` passes theta_e")
reproduction: `grep -n "theta_e" docs/PHYSICS.md cafe/pm/stage1.py`.
why it matters: the gust-front rate is the quantity the UAS gust scrub depends on; the document a reviewer or lab user reads says it is the rain-only upper bound and that two assumed inputs are unused, which is false in both respects.

### A-4. PHYSICS.md says the UAS verdict is "decided by the battery alone below about 12 m/s"; the run says 55 of 55 failures are `profile_incomplete`
severity: minor
lane: documentation / honesty
where: docs/PHYSICS.md (paragraph "Control authority (review round 2, M-28)": "The UAS verdict is therefore decided by the battery alone below about 12 m/s of wind"), against the paragraph above it in the same file ("rests on the battery and on finishing the profile inside the time limit") and report.json `vehicles.uas` (modes: profile_incomplete 55, battery_reserve 6, wind_exceeds_airspeed 0, lost_link 0)
reproduction: `python3 -c "import json;print(json.load(open('q6/stage1b/summary.json'))['summary']['vehicles']['uas']['modes'])"`. My own sortie probe (t5.py, quad_uas, M=2, uniform 10 m wind): 0 m/s completes 8 of 8 waypoints, 5.3 m/s ends at 7 of 8 and sets `profile_incomplete` with a state of charge of 0.305 (above the 0.20 reserve), so no battery involvement.
why it matters: the sentence is the one a reader uses to interpret the NO-GO; it is also stale for the pre-round-4 model.

### A-5. `python -m cafe.pm audit <typo>` runs ruff, mypy and the whole pytest suite before saying anything about the run directory
severity: minor
lane: robustness / documentation
where: cafe/pm/audit.py:239-268 (`main`: `ledger_problems(r)` for a missing dir adds a problem but the code, mypy and pytest steps still run), cafe/pm/__main__.py (audit subcommand)
reproduction: `python -m cafe.pm audit /nonexistent` in the cafe-pm image: `ps` on homebase shows `python -m pytest -q -m "not network" --cov=cafe/pm ...` running at 96 % CPU two minutes later (I started it by accident and had to stop the container; the 71 min serial suite would have run at 1 CPU for hours). Only `--code-only` and `--ledgers-only` are recognised in `audit.main`; any other `--flag` is silently ignored (`runs = [a for a in argv if not a.startswith("--")]`).
why it matters: RUNBOOK step 7 and the troubleshooting table send a lab user to `audit`; a wrong path costs an hour of CPU on a shared box before the first message.

### A-6. `make acceptance` deletes the user's `runs/quick` and `runs/overnight`, and the RUNBOOK does not say so
severity: minor
lane: documentation
where: Makefile `acceptance` (`--out $(RUNS)`, RUNS defaults to `runs`), cafe/pm/acceptance.py:81 and 92 (`shutil.rmtree(d, ignore_errors=True)` of `out/<name>` and `out/<name>_fetch`), docs/RUNBOOK.md steps 5 and 7 (step 5 writes `runs/quick`; step 7 lists `make acceptance` with "~11 h" and nothing about removal; only the `--help` text of the CLI says "removed first")
reproduction: follow RUNBOOK 5 (`--out runs/quick`), read the report, then RUNBOOK 7 `pm make acceptance`: the first thing it does is remove `runs/quick`. Read the Makefile line and acceptance.py:81.
why it matters: a lab user who has reviewed a quick run (the golden must be minted from a reviewed run, RUNBOOK 7) loses it before the acceptance run produces its own.

### A-7. Mission numbers that cannot be right are accepted by `validate`, and one of them is reported as the wrong failure
severity: minor
lane: robustness
where: cafe/schemas/mission.json (`launch_rules.max_mean_wind_ms`, `no_gust_front_within_min` have no minimum; `task.dive_depth_m`, `radius_km`, `lost_after_h`, `track_tolerance_km` have only exclusiveMinimum 0 and no maximum; `altitudes_m` accepts duplicates and any order), cafe/pm/physics/glider.py:367-369 (`dd >= min_dive_m` else flag `seafloor`)
reproduction: t1.py on homebase: `launch_rules: {max_mean_wind_ms: -5}` -> OK; `dive_depth_m: 1e6` -> OK; `dive_depth_m: 0.001` -> OK; `radius_km: 1e-9` -> OK; `radius_km: 1e308` -> OK; `altitudes_m: [2,2,2]` and `[100,10]` -> OK. t4.py: a Seaglider in 4000 m of water with `dive_depth_m` 20 (or 0.001) fails with `seafloor` at once (below `min_dive_m` 30 m), though the sea is 4000 m deep. A non-positive `max_mean_wind_ms` scrubs every sortie, so the UAS is NO-GO `no_sortie_flown` from a file `validate` called valid.
why it matters: a typo in a lab-edited file becomes a confident verdict with the wrong cause.

### A-8. `hangar --platform radios` / `modems` say "(uas): provenance FAILED" and list the whole file
severity: minor
lane: documentation / robustness
where: cafe/pm/__main__.py:166-175 (`_hangar`: any file without `kind` is treated as the UAS file), platforms/radios.yaml, platforms/modems.yaml; the RUNBOOK lists the platform directory as the thing to edit and `nonexist`'s error message lists `modems` and `radios` as "available" platforms (cafe/pm/config.py:244-248)
reproduction: `python -m cafe.pm hangar --platform modems` -> `modems (uas): provenance FAILED: platform numbers without a source or an assumed+why: ['defaults.ref_wind_ms', ...` (exit 1); `hangar --platform nonexist` -> `available: ['modems', 'quad_uas', 'radios', ...]`.
why it matters: the lab is told to fill the modem and radio files and to check them with `hangar`; the check calls them a UAS and fails them.

### A-9. Runs started with `bin/pmx.sh` record no clean-tree flag, so no run made with the parallel-agent runner can back the golden or a provenance claim; q6 is one
severity: minor
lane: reproducibility
where: bin/pmx.sh:6 (passes `CAFE_GIT_SHA` but not `CAFE_GIT_DIRTY`; `pm.sh` passes both), cafe/pm/ledger.py:46-53 (`git_dirty` returns None without `.git` and without the variable); q6 ledgers: every `checkpoints/*/ledger.json` has `"git_dirty": null`; report.json `machine.git_sha` prints the sha with no dirty flag
reproduction: `grep git_dirty q6/checkpoints/*/ledger.json`; compare bin/pmx.sh with pm.sh.
why it matters: CLAUDE.md sends every parallel agent to pmx.sh, and the evidence runs (q4 to q6) have an unknown tree state; the report names a commit that may not describe the code that ran.

### A-10. The UAS turbulence is generated at one height for all four flight levels
severity: minor
lane: physics
where: cafe/pm/stage1.py:189-198 (`z = deck_height_m + mean(levels_m)` = 58 m for the demo; `max(U, 1.0)`, `u*` and `L` from the ship's surface layer, one Mann box per sortie), docs/PHYSICS.md section 5.1 (does not say the box is at one height)
reproduction: `Lambda_1 = min(0.7 z, 42 m)` (PHYSICS 5.1) is 12.6 m at the 10 m leg (deck 8 m + 10 m = 18 m) and 42 m at the 58 m of the box (z = 8 + mean(10, 30, 60, 100) = 58 m); the series flown on the 10 m leg has the length scale of 58 m. The mission's `altitudes_m` [10, 30, 60, 100] change `z` only through their mean.
why it matters: turbulence scale and intensity are what the attitude and lean-angle flags respond to; the single-height simplification is unstated and untested against the per-level case.

### A-11. What-if candidates are compared at n = 32 against a baseline at n = 64 with no interval
severity: minor
lane: statistics / honesty
where: report.html "What would fix it" tables (e.g. glider_eq "deploy 6 h later ... Stage 1, n = 32 members 0.2812 MARGINAL" beside the baseline 0.2344 at n = 64; uas "launch the sorties 6 h later ... 0.9062" beside the baseline "0.875" under the 10 m model), cafe/pm/whatif.py:_stage1 (returns `lo`, `hi` but the report prints only p_fail and the verdict)
reproduction: 9 of 32 has a 90 % Wilson interval 0.16 to 0.43, 15 of 64 has 0.16 to 0.33: the candidate is indistinguishable from the baseline, but is listed as an evaluated change with its own verdict.
why it matters: the lab reads the table as "this change does/doesn't help"; a 4.7-point difference at n = 32 is noise.

total: 11 findings (0 critical, 2 major, 9 minor)
