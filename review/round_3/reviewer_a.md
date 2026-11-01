# Round 3, reviewer A

Material read: BRIEF, DECISIONS, RUNBOOK, PHYSICS, CREDIBILITY, QUESTIONS, STATUS, the q3 report / report.json / credibility.json / every ledger, and `cafe/pm` (stage1, perturb, stats, budget, config, audit, comms, glider, usv, emulator, report, credibility, pipeline, tao, subgrid).
Reproductions below ran on homebase at 1 CPU (`pm_rev3_a`) or locally (pure-numpy modules). Where I say "q3 run" I mean the files under `scratchpad/q3` and `~/work/cafe/pmdata/runs/q3`.
A re-run of the q3 USV batch (members 0..31, same seed, same cached env) reproduced the report's USV failure counts exactly (becalmed 10, swept_off_track 27, wing_stall 21), so the instrumented numbers below are the report's own.

### A-1. A USV `task.mode: station` (or `drift`) passes `validate` and then crashes Stage 1 with a bare traceback
severity: major
lane: robustness
where: cafe/pm/stage1.py:89-95 (`_run_usv` passes the mission `task` straight to `USVSim`); cafe/pm/physics/usv.py:90, 445-446 (`MODES`, `md["station"]`); cafe/pm/config.py:165-167 (station needs `lon`, `lat`; no check of mode against vehicle class); cafe/schemas/mission.json:43-45 (`mode` enum is the same for every class)
reproduction: `_run_glider` turns `task.lon/lat` into `station=` (stage1.py:75-76); `_run_usv` does not. `USVSim` reads `md["station"]`. On homebase:
```
v = demo "usv" vehicle with task = {mode: station, lon: -165.0, lat: 0.0, radius_km: 5.0}
stage1._run_usv(v, usv.load_platform(v["platform"]), AnalyticEnv(), 4, {"usv_vpp_bias": np.full(4, -0.24)}, t0, t0 + 86400, 1.0)
-> KeyError: 'station'
same vehicle with task = {mode: drift}  -> ValueError: mode 'drift' not in ('section', 'station')
```
`load_mission` accepts both files (I loaded them: `usv_drift -> ACCEPTED`). The platform file even documents the station case (saildrone_explorer.yaml:95 "distance-from-station (station)"), and `usv.py` receipts exercise station mode directly. The crash happens after the 2.5 h ingest, in stage 1.
why it matters: a lab member who asks for a station-keeping USV (the SPURS-2 failure the brief names) gets a validated mission that dies hours into the run with no actionable message; BRIEF 4.0 says refuse early with a specific error.

### A-2. A glider task `mode: drift` is a hard-wired due-north swim that cannot fail from the environment, and the sanity table counts its GO as agreement
severity: major
lane: honesty / physics
where: cafe/pm/physics/glider.py:256 (`drift_dir` from `md.get("heading_to", 0.0)`), 352-353; cafe/pm/stage1.py:71-85 (`_run_glider` never passes `heading_to`); cafe/schemas/mission.json:43-50 (task has no `heading_to`, and no `additionalProperties: false`); missions/tepex_c_demo.yaml:29; docs/PHYSICS.md:557-585 (the mode is not described)
reproduction: `platforms/slocum.yaml` and `seaglider.yaml` have no `heading_to` in `mission_defaults`, so every drift glider swims on compass heading 0. In the q3 report.json the glider_2n median track (`map.vehicles.glider_2n.median.values`) goes from lat 2.000 to lat 3.666 in six days (+185 km) at lon -170.0 to -170.2, i.e. it flew north. In `GliderSim.step`, `station_lost` is only evaluated when `mode == "station"` and `waypoint_unreachable` only in `section`; so for `drift` the flags left are battery, seafloor, overdepth, no_flight and `left_data`. Result: 0 of 32 members failed in every mode, "GO", and the report's sanity row (`gliders GO for a drift section` -> yes) is true by construction. If the lab writes `heading_to: 270` in the task (the natural way to ask for a westward leg) the key is accepted and ignored (A-5).
why it matters: the report presents a GO for glider_2n as a result about the equatorial currents; it is a fixed heading with no pass/fail criterion tied to the mission, and nothing in the report or PHYSICS says so.

### A-3. The "most sensitive to" line cannot name any parameter when the failure count is small, even for a perfectly known driver; the demo report names none
severity: major
lane: statistics
where: cafe/pm/stage1.py:537, 554 (`sensitivity.dominant(names, U, f.astype(float))` on the 0/1 failure indicator); cafe/pm/stats/sensitivity.py:23-53
reproduction: BRIEF 2.5 requires each verdict to name the parameter it is most sensitive to. EASI on a 0/1 vector with k ones saturates, and `noise_floor` (95 % quantile of the max over 10 columns) saturates at the same value. Local, numpy only:
```
x = rng.random((32, 10)); y = zeros(32); y[argsort(x[:, 0])[:k]] = 1      # failures are exactly the k lowest values of p0
detected = (first_order(x, y).argmax() == 0) and (first_order(x, y).max() > noise_floor(x, y))
n=32 k=1: 0/20 detected   k=2: 0/20   k=3: 13/20   k=6: 20/20      (n=64 k=3: 20/20)
```
In the q3 UAS ensemble (3 battery failures of 32) the three failing members have battery_capacity_scale ranks [5, 0, 1] (the three lowest, a known physical cause), S1 = 0.2644, floor = 0.2644, so the report prints "no parameter clears the noise floor". `glider_speed_scale`, which cannot affect a UAS, gets the identical S1 0.2644 from a tight rank cluster [26, 20, 24] (`res.pkl`, `summary.json` S1 dict). All three vehicles with mixed outcomes in the demo (glider_eq 6/32, usv 30/32, uas 3/32) and all links with all-or-none outcomes therefore name nothing. The irrelevant columns (`glider_speed_scale`, `usv_vpp_bias` for a UAS) also stay in the max that sets the floor. `stage1.summarize` already holds continuous margins that would carry the information (UAS `soc_end`, glider station distance), and the module docstring says EASI "works for continuous margins".
why it matters: an exit-condition deliverable (named dominant sensitivity per verdict) is structurally absent for any ensemble with at most 3 failures or 3 survivors, which is the budget-quick regime; the text "no parameter clears the noise floor" reads as "no parameter matters".

### A-4. A calendar-invalid time in a mission file ends in a Python traceback and exit 1, not `error: ...` and exit 2
severity: minor
lane: robustness
where: cafe/pm/config.py:47-48 (`utc` uses `strptime`), 133-151; cafe/schemas/mission.json:9 (`time` is only a regex); cafe/pm/__main__.py (`except (ConfigError, budget.PlanError)`)
reproduction: `sed 's/2023-03-07T12:00:00Z/2023-02-30T12:00:00Z/' missions/tepex_c_demo.yaml > bad.yaml; python -m cafe.pm validate --mission bad.yaml` -> `ValueError: day is out of range for month` (traceback). Same for `T24:00:00Z` and month 13: the regex `\d{2}` passes them. `ValueError` is the base class of `ConfigError`, but `main` only catches the subclass.
why it matters: BRIEF 4.0 "a specific, actionable error naming the file, field and fix"; `validate` is the first thing the RUNBOOK tells a lab member to run.

### A-5. Unknown keys in `task`, `sorties`, `launch_rules` and `shore` are silently ignored
severity: minor
lane: robustness
where: cafe/schemas/mission.json:35, 43-56 (these objects have no `additionalProperties: false`, unlike `box`, `deploy`, `ship`, `environment`, `links`, `verdict`)
reproduction: `load_mission` ACCEPTED all of: `task: {mode: station, ..., radius_kms: 3}` (typo, default 5 km used), `task: {mode: drift, heading_to: 270}` (ignored, A-2), `sorties: {every_day: 2}` (typo, default 1 d), `sorties` on a glider that has `deploy`/`task` (ignored). Round 1 M-11 fixed the same class of problem for `verdict`, `atmosphere`, `waves`, `pattern`.
why it matters: a mistyped tolerance or lost-after time changes a verdict with no warning; "refuse, never guess".

### A-6. USV `wing_stall`: one angle is used for two different quantities, and a 30 min calm is a mission failure while `becalmed` needs 6 h
severity: minor
lane: physics
where: cafe/pm/physics/usv.py:169 (`wing_stall_deg` = 15 deg as the wing angle-of-attack stall), 576 (`e1["awa"] < P["wing_stall_deg"]` = 15 deg as a minimum boat-fixed apparent wind angle); platforms/saildrone_explorer.yaml:34, 41, 99; cafe/pm/physics/usv.py:574-578
reproduction: the platform file describes `wing_stall_deg` as the NACA 0015 static stall angle of attack (yaml:34). Line 576 compares it with `awa`, the angle of the apparent wind off the bow. The VPP polar itself gives positive speed there (TWS 6 m/s, TWA 15 deg: V = 0.55 m/s, awa = 13.1 deg), so the flag contradicts the polar. Instrumented rerun of the q3 USV batch (instrument `USVSim.step`, same seed, reproduces becalmed 10 / swept 27 / wing_stall 21): members with at least 1800 s continuous stall by `aws < 1.5 m/s` alone: 18 of 32; by `awa < 15 deg` alone: 9; by either: 21. So the second most common USV failure (66 % of members) is mostly "apparent wind under 1.5 m/s for 30 min", i.e. a calm, flagged as a failed mission after 0.5 h while `becalmed` (SOG below the current) needs `becalmed_after_h` = 6 h.
why it matters: the 30 min / 6 h inconsistency inflates P(fail) for any calmer mission and the stall label overstates what the wing does; here swept_off_track (27) decides the verdict anyway.

### A-7. The report of a resumed run prints the previous attempt's report-stage wall time and a git sha no stage of the run used
severity: minor
lane: honesty / reproducibility
where: cafe/pm/report.py:715-730 (`_machine` reads `tr.led`, the ledgers on disk when the report is being written); cafe/pm/pipeline.py:1064-1069 (`s_report`)
reproduction: q3 `report/report.json` -> `machine.wall_s.report.value` = 4.238 and `machine.git_sha` = [73bf4c7a..., eceb1762...]. q3 `checkpoints/report/ledger.json`: `wall_s` 1.441, `git_sha` 73bf4c7a, and every other ledger is 73bf4c7a. The values come from the old `report` ledger of an earlier attempt (eceb176) that is still on disk while the new report stage runs. The HTML prints "Code: git 73bf4c7a..., eceb1762..." and a Stage wall-time table whose last row is not this run's.
why it matters: the report's provenance line names a commit that produced nothing in the run; on a fresh run the row is missing instead, so identical inputs give different `report.json` (the keys are in `acceptance.VOLATILE`, which hides it).

### A-8. credibility.json says `nest_sphere_100.json is not stored` while `nest_sphere_100_d{8,12,16}.json` are stored
severity: minor
lane: honesty
where: cafe/pm/credibility.py:273-276 (`rec / f"{kind}_{tag}.json"`); cafe/pm/stage3/nest.py:427 (`nest_sphere_{tag}_d{d}.json`)
reproduction: q3 credibility.json `vv20`: `nest_sphere:Re100 -> "not run: nest_sphere_100.json is not stored"`. `ls ~/work/cafe/pmdata/receipts` on homebase: `nest_sphere_100_d8.json`, `nest_sphere_100_d12.json`, `nest_sphere_100_d16.json`. CHANGELOG lists the name mismatch as a known issue, but the report sentence is false, and Round 2 asked that every finding be fixed.
why it matters: the Validation factor and the V&V 20 table state an input is missing when it exists.

### A-9. The receipts banner says "record a failed result" for four receipts that are only stale
severity: minor
lane: honesty
where: cafe/pm/report.py:1207-1213
reproduction: q3 index.html: "5 of 24 receipts below record a failed result and are marked FAILED OR MISSING: physics:pm.physics.comms; ...glider; ...uas; ...usv; stage3:output:windows.json". report.json `receipts[].got` for the four physics ids is "stale: made by other code" (no result was read); only `stage3:output:windows.json` ("0 of 6 windows passed") is a recorded failure. `failing = [... if not r["ok"]]` merges the two.
why it matters: "failed" and "not verified" are different statements for a reader deciding what to trust.

### A-10. BRIEF.md still says the synthesised mss "matches the file's to 0.0 %"; the run's ledger says 35 % at the 90th percentile and 31 % of points clipped
severity: minor
lane: documentation / honesty
where: docs/BRIEF.md:21 (correction row 2.3); docs/PHYSICS.md:222-223 (says "when w is not clipped")
reproduction: q3 `checkpoints/ingest/ledger.json` check `spectrum_mss_vs_file`: value 0.3455 (limit 0.5), note "the short-wave share is clipped (slope variance then off by more than 1 %) at 31.2% of the points". The BRIEF correction is the first thing a reader of the brief sees and has no condition.
why it matters: a claim in the document the lab reads contradicts the ledger the same run wrote; the limit of the check (0.5) is also looser than the sentence it backs.

### A-11. The resume digest covers only jax, numpy and scipy versions
severity: minor
lane: reproducibility
where: cafe/pm/pipeline.py:48 (`HASHED_LIBS`), 51-65 (`code_digest`)
reproduction: report.json `machine.versions` lists gsw 3.6.22, pycoare 0.4.3, mannrs 2.0.0, xarray, zarr, h5py, sklearn, smt, statsmodels, xlb, and the ledgers record them. `Context.hash` = digest(mission, budget, gpus, code_digest) hashes only `jax`, `numpy`, `scipy` besides the tree. Upgrading `gsw` (density, sound speed), `mannrs` (the UAS turbulence), `pycoare` or `smt` leaves every ledger "up to date" on `--resume` and the receipts table and emulator rows "made by the same code".
why it matters: RUNBOOK says "rerunning the same command skips every stage whose ledger and outputs are intact"; numbers from other library versions are mixed into one report.

### A-12. Stage 3 writes `config/subgrid.json`, a file `code_digest` hashes, so a run that calibrates invalidates its own checkpoints; `source_run` is only the directory's last name
severity: minor
lane: reproducibility
where: cafe/pm/env/subgrid.py:472-485 (`write_calibration` writes `config/subgrid.json`); cafe/pm/pipeline.py:58 (digest hashes `config/**/*`); cafe/pm/stage3/pipeline_windows.py:671-672 (`subgrid.write_calibration(cal, pathlib.Path(ctx.run_dir).name, path)`)
reproduction: by reading: after a stage-3 window passes (GPU, or the ci smoke window if it passes), the repo's `config/subgrid.json` changes; the next `run` (resume) computes a different `code_digest`, every stage's `config_hash` differs, nothing is "up to date", and stage 1 reruns with the new calibration, so a resume gives different numbers from the first completion. The repo tree is also left dirty by a run, and two runs in directories both called `quick` write the same `source_run`. Not exercised here (no GPU).
why it matters: the brief wants the write-back, but then the calibration should be a run output keyed into the hash, not a mutation of tracked config.

### A-13. `make audit` audits no run ledger in CI, and CI has no `--budget ci` acceptance
severity: minor
lane: reproducibility / documentation
where: Makefile:46-47 (`$(wildcard runs/quick runs/overnight runs/4h)`); .github/workflows/premission.yml:14-19 (audit before ci; `make ci` writes `runs/ci`); cafe/pm/audit.py:227-247 (`main`)
reproduction: with no run directory, `python -m cafe.pm.audit --code-only` loops over `runs = []`, prints `audit: 0 problem(s)` (given a mutation record) and exits 0; `ledger_problems` is called nowhere else (`grep ledger_problems cafe/pm/acceptance.py` finds nothing). The CI job runs `make audit` first, when no run exists, then `make ci`, whose `runs/ci` is not in the wildcard. BRIEF 5.3 asks CI to run "make audit + `--budget ci` acceptance"; CI runs `make ci`.
why it matters: the hash chain and the "every self-check passed" part of BRIEF 5.5 are never enforced by the required check; RUNBOOK 7 describes `make audit` as "ledgers re-hashed" without saying it needs a run directory.

### A-14. The Ament roughness factor takes the sine of a sine
severity: minor
lane: physics
where: cafe/pm/physics/comms.py:62-64 (`ament_rho(hs, grazing, wavelength)` computes `np.sin(grazing)`), 77 (`ament_rho(hs, (ht + hr) / r2, lam)`)
reproduction: `(ht + hr) / r2` is already sin(psi) (r2 is the reflected path length). `ament_rho` is documented to take the grazing angle and applies `np.sin` again. For ht + hr = 20 m at d = 100 m: sin psi = 0.196, sin(0.196) = 0.1948 (exponent 1.4 % low); at d = 20 m: 0.707 vs 0.650 (exponent 16 % low). Negligible at the km ranges of the demo, wrong near the ship.
why it matters: a formula error in a function with a "recalled" receipt tolerance; the RF margin near the ship (where `usv-uas-rf` could pass) is slightly off.

### A-15. The report prints two different USV speeds and a ratio that is not the quotient of the two numbers beside it
severity: minor
lane: honesty
where: cafe/pm/report.py:932-934 and 520; cafe/pm/physics/usv.py:550-552 (`path_m += sog * dt` excludes the SDE displacement); cafe/pm/report.py:482-496 (`path_speed` sums the stored records, which include it)
reproduction: q3 index.html, USV block: "0.1233 (median over members; 0.6331 m/s over 5.294 m/s)", 0.6331 / 5.294 = 0.1196; two lines below, the reach map: "usv: ... at 0.6613 m/s ... median mean path speed over ground of the Stage-1 ensemble". Same ensemble, two "speed over ground" medians (0.6331 from `path_m`, 0.6613 from the records, +4.5 % from the ocean SDE's 29 m per minute random step), and a median of ratios printed as numerator and denominator medians.
why it matters: the calibration comparison (0.123 against Chiodi's 0.178) is the report's main USV caveat, and it is built from the smaller of two inconsistent speeds.

### A-16. The mission schema says `pad_deg` defaults to 2.0; the code's default depends on the window
severity: minor
lane: documentation
where: cafe/schemas/mission.json:23 (`"default": 2.0`); cafe/pm/pipeline.py:149-157 (`padding`); docs/RUNBOOK.md (describes the window rule)
reproduction: remove `pad_deg` from the demo mission: `padding()` returns `ceil(6 d x 86400 x 0.5 / 111e3 x 2) / 2` = 2.5 deg, 10 deg at 26 days. jsonschema does not apply defaults, so the schema's 2.0 (and the BRIEF's +/-2 deg) is never used.
why it matters: the schema is the file a lab member reads to learn the keys; the number in it is not what the code does.

### A-17. A vehicle deployed in the last 30 s of the window crashes Stage 1
severity: minor
lane: robustness
where: cafe/pm/config.py:151 (accepts any `deploy.time < window.end`); cafe/pm/stage1.py:64-68 (`_record_grid`)
reproduction: demo mission with `glider_eq.deploy.time = 2023-03-07T11:59:59Z` is ACCEPTED by `load_mission`. `stage1._run_glider(..., t0, t0 + 30, ...)` on homebase -> `ValueError: all the input arrays must have same number of dimensions, but the array at index 0 has 2 dimension(s) and the array at index 1 has 1 dimension(s)` (no step ran, so the history arrays are empty 1-D). The USV path shares `_record_grid`.
why it matters: tiny, but it is the form of input BRIEF 5.6 lists under robustness ("a vehicle ... a 30-day window"): an edge deploy time passes validation and dies after the ingest.

total: 17 findings (0 critical, 3 major, 14 minor)
