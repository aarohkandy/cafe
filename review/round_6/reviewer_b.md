# Reviewer B, round 6: commit 739fe5c (premission-step4)

Method: read the brief, the repo and the q6 evidence in `scratchpad/q6`; recomputed printed numbers from the ledgers; ran hostile inputs on homebase in `pm_rev6_b` at 1 CPU (scripts in `scratchpad/rev6/b/t*.py`, each is self-contained and run through `scratchpad/rev6/b/run.sh`); ran a 33-mutant sweep over the stats, comms, usv, perturb, stage-1, pipeline and glider code against the tests that cover them (`t20.py`, `t23.py`). Nothing in the repo was edited.

Recomputed and found sound (no finding): Wilson 90 % and 95 % intervals for the q6 verdicts, `n_certify` 73 and 59, the TAO "ALL" row from the per-mooring rows (bias, rmse, direction, SST to 1e-15), the V&V 20 rows (E, U_val, ratios), the planner arithmetic for the emulator share (240 s, 168 s, 6 variants), the acoustic and RF sample granularity (1/18, 1/244), the UAS member P(fail) from the per-sortie rate (1 - 0.7192^6 = 0.862 against 55/64 = 0.859). Of 33 hand-made mutants, 29 were killed by the tests that cover them and 4 survived (see the finding that names mutants).

Findings are ordered by severity.

### B-1. A truncated or corrupt JSON in the orca cache crashes `fetch`/`run` with a raw traceback, every time, and the files are written non-atomically
severity: major
lane: robustness
where: cafe/pm/env/orca.py:328 (`manifest.json` written with `write_text`), cafe/pm/env/orca.py:281 (`cut.json`, same), cafe/pm/pipeline.py:315 (`orca_covers` reads `manifest.json`), cafe/pm/env/orca.py:272 (`cut.json` read), cafe/pm/pipeline.py:197 (`_umwm_depth` opens `umwm.zarr` outside the cache-read wrapper), cafe/pm/pipeline.py:266 (`_tao_cached` reads `tao/manifest.json`)
reproduction: `scratchpad/rev6/b/t5.py` builds the CI environment (`tests/fixtures/ci_env`) and then (a) writes `{garbage` to `cache/ci_fixture/orca/umwm.zarr/zarr.json`, (b) writes an empty file to `cache/ci_fixture/orca/manifest.json`; `cli.main(["fetch","--mission","missions/ci_fixture.yaml","--out",...])` raises `json.decoder.JSONDecodeError` from `pipeline.py:197` (a) and `pipeline.py:315` (b), exit code 1 with a traceback. `t22.py` shows a damaged `tao/manifest.json` does the same from `pipeline.py:266`. A truncated zarr chunk of the orca cache, by contrast, gives the promised `error: environment cache file ... cannot be read ... delete ...` (exit 2), so the wrapper at env/environment.py:70 exists and these paths bypass it. The orca manifest is rewritten in place by `write_text`, so an ingest killed mid-write (and homebase's disk is 98 % full: `df -h /` 7.4 GB free) leaves a zero-byte or partial file that no rerun repairs: `orca_covers()` reads it before anything else, and `--fresh` ignores checkpoints, not the cache.
why it matters: RUNBOOK's troubleshooting row promises an `error:` line and a remedy for a corrupt cache file; here the lab user gets a traceback and no remedy, permanently.

### B-2. A corrupt chunk in the ocean store gives a raw `RuntimeError` traceback, not the "cannot be read" error
severity: major
lane: robustness
where: cafe/pm/env/hycom.py:189-198 (`open_store` converts only open-time failures; chunks are read lazily), cafe/pm/env/ocean.py:56 (`_field` does `.values` with no handler), cafe/pm/pipeline.py:481 and :522 (`_round_trip_errors` in the ingest self-checks is the first reader)
reproduction: `t22.py`: on the CI environment overwrite one chunk of `ocean/gofs_ci_fixture.zarr/water_u` with `b"x"` (an interrupted download) and run `cli.main(["fetch","--mission","missions/ci_fixture.yaml", ...])`: `RuntimeError: Zstd decompression error: invalid input data` from `ocean.py:56` via `pipeline.py:481/522/357`, exit 1, traceback. The same damage in `orca/wrf.zarr` (same script) gives the friendly error, exit 2, so the two cache halves behave differently.
why it matters: the ocean store is the 5.1 GB, longest download of the RUNBOOK (about 2.5 h); a truncated part is the likeliest corruption and is the one that gets no guidance.

### B-3. The "cannot be read" remedy for an unreadable ocean store says to delete the whole `ocean` directory
severity: major
lane: robustness / documentation
where: cafe/pm/env/hycom.py:197 (`delete {pathlib.Path(path).parent}`); docs/RUNBOOK.md troubleshooting row "environment cache file ... cannot be read" ("delete the directory the message names (the orca or ocean part of the cache)")
reproduction: `t15.py`: put `{bad` into `ocean/gofs_ci_fixture.zarr/zarr.json` with a second store `ocean/gofs_other_mission.zarr` beside it; `fetch` exits 2 with "... cannot be read (JSONDecodeError ...); delete /tmp/cid/ocean and run `python -m cafe.pm fetch --mission ...` again: only that part is downloaded again". The parent of a store is `$CAFE_DATA/ocean`, which holds every mission's GOFS store and any lab HYCOM store. For `environment.ocean: {source: lab_hycom, path: ...}` the pipeline cannot download the store (`pipeline.py` `fetch_ocean` raises "this is the lab's HYCOM, which this pipeline cannot download"), so following the advice destroys the only copy. With `path: /etc/hostname` the message says "delete /etc".
why it matters: the message instructs data loss; the correct target is the single store path.

### B-4. No usable wind direction at the moorings (all-calm WRF, or a box whose moorings lack direction) writes a null prior and stage 1 dies with a `TypeError`
severity: major
lane: robustness (BRIEF 5.6 names "zero wind")
where: cafe/pm/pipeline.py:604-625 (the fit is written without checking it is finite; `clean()` in ledger.py turns NaN into null), cafe/pm/stage1.py:75 (`priors_for` merges the fit), cafe/pm/stats/sampling.py:59 (`np.isfinite(e["value"])` on `None`)
reproduction: `t11.py`: CI environment with U10/V10/U/V/UST and UMWM wspd/uc/vc set to 0, derived layer deleted, then `pipeline.run(ci_fixture, 'ci', stop_after='stage1')`. Ingest completes; `ingest/priors_fitted.json` holds `"wind_direction_bias": {"mean": null, "value": null, ... "fewer than 2 moorings, so the whole hourly misfit (nan deg) is held as one persistent error"}`, `tao_compare.json` has `dir_n: 0`, `dir_bias_deg: null`; stage 1 then raises `TypeError: ufunc 'isfinite' not supported for the input types` at `sampling.py:59` (no `error:` line, traceback).
why it matters: a calm or direction-less comparison (a small box with one mooring whose direction channel failed gives the same null) should refuse with a message at ingest, not crash a run after the ingest and hangar stages; and a fitted prior should never be accepted when it is NaN.

### B-5. The stage-1 memory model ignores the area of the box, so the guard is wrong for every box but the demo's and for a 30-day window
severity: major
lane: performance
where: cafe/pm/budget.py:53 (`ENV_GB_PER_DAY = 1.5`), :172-176 (`env_gb`: window days, or the cache's size on disk once it exists), :246-251 (the `workers_by_memory` and the refusal)
reproduction: `t17.py`: the demo (box 10 deg x 30 deg, pad 2) and the same mission with `box: {lon_min: -180, lon_max: 179.9, lat_min: -60, lat_max: 60}` (120 x 360 deg, about 90 times the area) both give `budget.env_gb(m) == 9.0`. For the BRIEF's 30-day case the pad rule (`pipeline.padding`, 0.5 m/s for 30 days, capped at 10 deg) makes the downloaded box 30 x 50 deg against the demo's 14 x 34, 3.2 times the area, so the environment needs about 5 x 3.2 = 16 times the demo's 9 GB (about 140 GB) while the model says 45 GB (`plan` on a 64 GB host passes: `t7.py`, "30d quick n_max 64 ... stage1_s 131.7"). The disk floor only applies after a first ingest; the plan in `Context.__init__` is made before it on a cold cache and never remade after the ingest.
why it matters: M-6 (round 5) added the guard so a run is refused rather than OOM-killed; it holds only for the one box it was calibrated on, which is the case "a 30-day window" in BRIEF 5.6 would exercise.

### B-6. `plan.sitl_members` (4 at `--budget 4h`, 8 at `overnight`) is printed in the report but no stage ever flies a SITL member
severity: major
lane: honesty
where: cafe/pm/budget.py:36 and :318 (`SITL = {... "4h": 4, "overnight": 8}`, `sitl_members=SITL[budget]`), cafe/pm/report.py:868 (printed as "sitl_members N members"); no caller of `physics/uas.py:fly_sitl` exists outside the slow receipts (`grep -rn "fly_sitl\|sitl" cafe/pm --include='*.py'` finds only `uas.py`, `receipts.py`, `budget.py`, `report.py`, `credibility.py`)
reproduction: `budget.plan('overnight', 0, demo)['sitl_members'] == 8`; the q6 report's plan line reads "sitl_members 0 members" (quick), and `report.py:868` prints the plan's value for the 4h and overnight budgets (4 and 8). `stage1.py` and `pipeline.py` contain no SITL path. BRIEF 2.5 requires the report to "state ... how many SITL members were run versus the pure-physics ensemble"; CHANGELOG:317 lists what is "not called by any pipeline stage" (SPRT, subset simulation, Realization, ...) and does not list the SITL members.
why it matters: a number in the report's plan block says members ran that did not; STATUS section 3 ("Not done") does not mention it.

### B-7. Concurrent runs corrupt the shared emulator training table: it is a read-modify-write with no lock and one fixed temporary name
severity: major
lane: reproducibility / robustness
where: cafe/pm/whatif.py:329-333 (`add_rows`: read, filter, concat, write), cafe/pm/emulator.py:75-79 (`write_table` always writes `<name>.tmp`, then `replace`), cafe/pm/pipeline.py:1238-1241 (a corrupt shared table stops the next run)
reproduction: `t21.py` starts three processes, each calling `whatif.add_rows(path, [one row])` 30 times with distinct keys on one parquet table (expected 91 rows). 83 of the 90 calls failed, with `ConfigError: training table ... cannot be read (ArrowInvalid)` (a reader met the half-written file) and `FileNotFoundError: ... train.parquet.tmp -> train.parquet` (two writers shared the `.tmp` name), and the table was left unreadable (`ArrowInvalid: Parquet file size is 2527 bytes, smaller than the size reported by footer's (827474256bytes)`). `$CAFE_DATA/emulator/train.parquet` is the default table of `pm.sh`, `pmx.sh` and the RUNBOOK wrapper, and homebase is shared (CLAUDE.md: several agents and the lead use it at once); RUNBOOK tells the user to give "each run its own copy" only for the acceptance and same-seed checks.
why it matters: the emulator needs 100 distinct points that accumulate across runs; two overlapping runs lose rows or leave a file whose repair is "move it aside (rows in it are lost)", and the next run of every user is then refused.

### B-8. `receipts --only <name>` replaces the whole receipts table with the selected rows, and a name that matches nothing exits 0 with an empty table
severity: minor
lane: robustness / honesty
where: cafe/pm/receipts.py:438-441 (the table and its meta are written to `runs/receipts.json` whatever `only` is), :369 (a typo selects nothing), cafe/pm/report.py:93-120 (`_stale` compares only `code_digest`, never the `only` field the meta records)
reproduction: `t6.py`: `python -m cafe.pm receipts --only nonexistent_group` prints "0 pass, 0 fail, 0 context (0 rows)", "table: /app/runs/receipts.json", exit 0, and has written `[]` over `runs/receipts.json` with a meta file holding the current code digest and `only: ["nonexistent_group"]`. A real `--only comms` leaves a one-group table that the report treats as current.
why it matters: the verdicts then cite receipt groups the table no longer holds, from a table the report considers current.

### B-9. The report's free-surface message "it would fit no --budget profile (the largest gives 0 min of stage 3)" is wrong, and contradicts the RUNBOOK
severity: minor
lane: honesty / documentation
where: cafe/pm/stage3/pipeline_windows.py:569-574 (`share = plan["shares"]["stage3"]`, the share after the slices of the unrunnable LES windows went to stage 1), cafe/pm/stage3/freesurface.py:137-142 (`fitting_budget(need, share, profiles)` multiplies that share by each profile), docs/RUNBOOK.md troubleshooting row ("free-surface window not run: estimated ... it would fit --budget overnight")
reproduction: `t8.py` with `CAFE_NPROC=6` (the q6 machine): `budget.plan('quick'...)['shares']['stage3'] == 0.0` and `plan('overnight')` gives a stage-3 share of 117.9 min, i.e. one free-surface case of the 118 min (94 min x 1.25) the q6 report calls impossible fits (`budget.fs_plan`: `fit = min(cases, share // need_s)` = 1 of 3); `freesurface.fitting_budget(118*60.0, 0.0, BUDGET_S)` returns "no --budget profile (the largest gives 0 min of stage 3)", `fitting_budget(118*60.0, budget.SHARE['stage3'], BUDGET_S)` returns "--budget overnight (180 min of stage 3)". The q6 report (index.html, USV W3 row) prints the first.
why it matters: the lab is told that no budget can run the hull window, which is not so, and the RUNBOOK says the opposite.

### B-10. `bin/pmx.sh` does not pass `CAFE_GIT_DIRTY`, so every run made through it has `git_dirty: null` in its ledgers and cannot mint or pass the golden
severity: minor
lane: reproducibility
where: bin/pmx.sh:5 (the `docker run` line passes `CAFE_GIT_SHA` only; `pm.sh` and the RUNBOOK wrapper pass both), cafe/pm/ledger.py:55-64
reproduction: every ledger in `scratchpad/q6/checkpoints/*/ledger.json` has `"git_dirty": null`, so the wrapper that made the q6 run did not pass the variable; `pmx.sh` is such a wrapper (diff its line 5 against `pm.sh` line 6). RUNBOOK says a run without it "cannot tell whether the checkout was clean" and `golden_diff` fails; CLAUDE.md tells agents to use `pmx.sh` when another agent is working.
why it matters: the golden's provenance rule (DECISIONS 260) is defeated by the tool the project's instructions tell agents to use.

### B-11. `environment.ocean: {source: lab_hycom}` with no `path` validates, then crashes with a bare `ValueError`
severity: minor
lane: robustness
where: cafe/pm/config.py:load_mission (no cross-check; schema allows `path` to be absent), cafe/pm/env/ocean.py:31 (`ValueError`), cafe/pm/__main__.py:153 (only `ConfigError`/`PlanError` are caught)
reproduction: `t14.py`: `validate` says valid; `fetch` raises `ValueError: ocean source 'lab_hycom' needs a `path` (run `hycom.ingest_lab_hycom` first)` as a traceback. `temperature_kind` on a `gofs31` source is also accepted and ignored.
why it matters: RUNBOOK step 4 tells the lab to write exactly this block; leaving out the path is the obvious slip and `validate` is documented to catch it.

### B-12. `CAFE_NPROC` is not validated (a letter is a traceback in `plan`; 0 is accepted)
severity: minor
lane: robustness
where: cafe/pm/stage3/freesurface.py:114 (`int(os.environ["CAFE_NPROC"])`)
reproduction: `t12.py`: `CAFE_NPROC=abc python -m cafe.pm plan --mission missions/tepex_c_demo.yaml --budget quick` raises `ValueError: invalid literal for int()` (traceback); `CAFE_NPROC=0` and negative values are accepted and priced at the 1-core rate (`rate()` clamps in `np.interp`). `CAFE_WORKERS` got its whole-number check in round 5; the sibling variable that RUNBOOK also mentions did not.
why it matters: round 5 validated `CAFE_WORKERS`; its twin that the RUNBOOK also names was not.

### B-13. Platform range checks leave gaps: several leaves load and then crash or give NaN inside the simulator
severity: minor
lane: robustness
where: cafe/pm/physics/usv.py (`REQUIRED` ranges), cafe/pm/physics/glider.py (`check_params`)
reproduction: `t16.py` sets each numeric leaf of the Seaglider, Slocum and Saildrone files to 0, -1 and 1e12 and flies 4 h under `warnings.simplefilter('error')`. 17 (file, leaf, value) triples load and then fail: saildrone `cap_cycles` 0 or -1 (`log` of a non-positive number in `usv.py` capsize proxy, NaN peak roll), `rudder_area_m2` 0 (`ZeroDivisionError`) and -1, `rudder_span_m` 0 (`ZeroDivisionError`) and -1, `rudder_x_m` 0, `stw_cap_ms` 1e12 (`MemoryError: Unable to allocate 146. TiB`), seaglider `hd_s` -1 (`ZeroDivisionError`), `abs_compress`, `temp_ref`, `therm_expan`, `t_deep_c`, `gravity`, `apogee_overshoot` at 1e12 (overflow or NaN). Most other leaves are refused at load, so the rule exists; these are the ones it misses.
why it matters: `hangar --platform` and `validate` are documented to find a bad file before a run.

### B-14. Two sentences in the same verdict block contradict each other
severity: minor
lane: documentation / honesty
where: cafe/pm/report.py:278 ("cannot be certified at n = ...") and cafe/pm/stats/intervals.py:119-123 (`verdict` note, ": already below 5%"); q6 `report/index.html`, glider_2n and usv-shore-iridium
reproduction: the q6 report for a 0-of-64 vehicle prints, one line apart, "P(fail) < 5 % cannot be certified at n = 64: 73 members ... are needed" and "P(fail) < 3/n = 0.047 at 95% confidence, one-sided (n = 64): already below 5%." Both are correct for their own interval (two-sided Wilson 95 % upper bound 0.0566; one-sided 0.0469) but a reader sees "cannot be certified" and "already below 5 %".
why it matters: the credibility report keys level 3 of Uncertainty on the first reading; the second says the opposite in plain words.

### B-15. The sensitivity sentence prints a driver and its floor as the same number
severity: minor
lane: documentation
where: cafe/pm/stage1.py:705-706 (`_sensitivity`: `(S1 {s1[param]:.2f}) ... above the {floor:.2f}`)
reproduction: q6 glider_eq: "current_speed_scale has the largest first-order index (S1 0.12) ... above the 0.12 that unrelated outcomes reach" (exact 0.1239 against 0.118).
why it matters: "0.12 above 0.12" reads as a tie; print three places or the difference.

### B-16. "Stage 1b was a copy" and the emulator share: stage 1b took 30.0 s, the emulator 291 s, the share they were charged to is 240 s
severity: minor
lane: honesty / performance
where: cafe/pm/budget.py:403 (`stage1b_free`), `scratchpad/q6/checkpoints/emulator/ledger.json` note ("emulator share 240 s (incl. stage 1b, which was a copy)"), `checkpoints/stage1b/ledger.json` wall_s 30.014
reproduction: stage1b reran the USV brief-prior sensitivity case (64 members), so it is not a copy; emulator 291.1 s + stage 1b 30.0 s = 321 s against the 240 s the plan gives both. Only the sum of all stages (about 495 s of 1200 s) is inside the budget, which is the contract; the per-stage shares printed as "planned" are not held and the note describes one stage as free that cost 30 s.
why it matters: small, but the machine block presents the shares as the plan; the 21 % overrun of the emulator share is only in the ledger.

### B-17. A comment names code that does not exist
severity: minor
lane: documentation
where: requirements-pm.txt:2-3 ("its uvmet10 rotation is done in cafe/pm/env/wrf.py and tested against a hand-rotated case"; there is no `cafe/pm/env/wrf.py`, the rotation is `conventions.rotate_grid_to_earth`)
reproduction: `ls cafe/pm/env/`; `grep -rn "env/wrf.py" .` finds only this comment.
why it matters: stale pointer in a file the lab reads when the image build fails.

### B-18. Mutants survive the tests of the mutation selection: the east-west metres-per-degree of the USV and of `path_speed` have no test away from the equator, and the USV `becalmed` rule can be changed by a factor of two
severity: minor
lane: physics / statistics (tests)
where: cafe/pm/physics/usv.py:506 (`_met`: `np.radians(dlon) * np.cos(np.radians(0.5 * (lat + tlat))) * R_E`), cafe/pm/stage1.py:97 (`path_speed`: `* np.cos(np.radians(0.5 * (lat[1:] + lat[:-1])))`), cafe/pm/physics/usv.py:597 (`self.acc["becalmed"] = np.where(self.vmax <= cv.speed(cur), ...)`), cafe/pm/stats/intervals.py:40 (`set_thresholds`: `min(0.75, go)`)
reproduction: `t20.py` / `t23.py` apply one source change at a time inside `pm_rev6_b` and run the tests that cover it (`-x`); of 33 mutants run, 4 survive: (1) `_met` without the cos(lat) factor survives all of `tests/test_usv.py` (every `_met` test is at latitude 0, `test_usv.py:437-462`); this function gives the waypoint distance, the cross-track error behind `swept_off_track` (54 of 64 q6 USV members) and the VMG choice, so away from the equator an east-west leg is measured too long by 1/cos(lat) with no test failing; (2) `path_speed` without cos(lat) survives all of `tests/test_stage1.py`, and `tests/test_report.py:1354-1364` also moves only along a meridian or at latitude 0 (`track()` has `lat0=0.0` and a constant longitude), so the "one definition of speed over ground" is unpinned for east-west motion off the equator; (3) `vmax <= cv.speed(cur)` -> `vmax <= 0.5 * cv.speed(cur)` (becalmed: "unable to stem the current") survives `test_usv.py`, yet `becalmed` is 22 of the 60 q6 USV failures; (4) `min(0.75, go)` -> `min(0.5, go)` survives `test_stats.py` and `test_stats_exact.py` (only `test_config.py:220` and `test_report.py:1752` pin it, and they are not in `pyproject.toml` `pytest_add_cli_args_test_selection`, so `docs/mutation.json` will count it as a survivor). The other 29 mutants (Wilson centre and Agresti-Coull centre, `n_certify`, the Newcombe bound, the NO-GO region, the SPRT bound, the antithetic mirror, the EASI bias correction, harmonics and floor quantile, the horizon constant, Ament roughness, Thorp, the Stojanovic noise terms, SBD segmenting, `stage1._dist` cos(lat), the glider drag exponent, the glider metres-per-degree, the launch-time longitude sign, the pad rounding, the Stokes period exponent, the current-field and wind-rotation terms, the wind clip at zero, roll sigma, the speed cap and the swept-off-track tolerance) were killed. The glider battery, seafloor, overdepth and station mutants of `t20.py` (28 to 31) were not run: `test_glider.py` takes over 2 min.
why it matters: 100 % line coverage on `physics` is met while a unit conversion that is exact at the demo's latitudes is untested; the demo cannot reveal it, any other mission can.

### B-19. A vacuous assertion in a test
severity: minor
lane: documentation / tests
where: tests/test_glider.py:413 (`assert (h["lon"] < 0).any() or (s.lon < 0).all() or True`)
reproduction: the line cannot fail; `audit.BANNED` has no pattern for `or True`. The next line asserts the real dateline condition, so coverage of behaviour is intact.
why it matters: BRIEF 5.1 "every one must be able to fail"; the audit's token list does not catch this form.

### B-20. `CAFE_OFFLINE=false` (or `no`, or any non-empty word other than `0`) turns offline mode on
severity: minor
lane: documentation
where: cafe/pm/pipeline.py:186-188 (`_offline`: "not in ('', '0')")
reproduction: `t12.py`: with `CAFE_OFFLINE=false` the run behaves as offline and fails `ocean_store_present`/`orca_present` with "CAFE_OFFLINE is set, so nothing is downloaded". RUNBOOK says only `CAFE_OFFLINE=1`.
why it matters: the error message is clear, but the variable name suggests a boolean and "false" means the opposite.

### B-21. YAML's unquoted timestamp gives an error that does not say to quote it
severity: minor
lane: documentation
where: cafe/pm/config.py:validate (`jsonschema` message passed through)
reproduction: `t13.py`: `window: {start: 2023-03-01T12:00:00Z ...}` unquoted gives "window/start: datetime.datetime(2023, 3, 1, 12, 0, tzinfo=datetime.timezone.utc) is not of type 'string'". The same applies to an empty `description:` ("None is not of type 'string'").
why it matters: the lab user's most likely first slip in a mission file; the message names Python types, not the fix.

total: 21 findings (0 critical, 7 major, 14 minor)
