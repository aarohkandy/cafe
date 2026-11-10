# Round 14, reviewer D (commit b42ae10, whose code is that of 20537b1)

Scope read line by line: `cafe/hangar.py`, `cafe/pm/physics/__init__.py`, `cafe/pm/stage3/wallmodel.py`, `cafe/pm/env/tao.py`; then `config/*`, `platforms/*`, `missions/*`, `cafe/schemas/mission.json` against their readers; then `bin/*` by reading plus the argument checks that exit before anything is sent. Method for the tests: 81 hand-made mutants of the three pm files in a detached worktree on orca (2 CPUs, proot, `PMX=pm_rev14_d`), each run against the tests that name the file (`-x`), the logs and every script named below are in the session scratchpad `/private/tmp/claude-501/-Users-aaroh-Downloads-everything-cafe-main/3ffc3622-1caa-4fef-bc21-ff4bf3298226/scratchpad/d/` (`rev14_d_mut.log`, `rev14_d_mut2x.log`, `rev14_d_<n>.py`, `rev14_d_mut*.py`); on orca they were copied to `pmdata/` and run as `PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_rev14_d PM_CPUS=2 bin/pmx.sh python /data/rev14_d_<n>.py`, and are removed with my `pm_rev14_d*` directories at the end.

What I checked and found right (so nobody reads it again): `utau_loglaw` against a float64 root of the same law over 1,000 (u, nu) pairs (largest relative error 1.8e-7, no jump at y+ 11.06); the `_RULES` boundaries of `physics.check_params` except the gaps in D-5, D-6 and D-12; every key of `config/assumptions.yaml` against a reader (all `stage3.*`, `ingest.*`, `env.sigma.*`, `bathy.*`, `subgrid.*`, `reach.*`, `tao.air_gap_s`, `waves.*`, `dtmb5415.*` are read, none missing); every key of `perturbations.yaml` against `stage1`/`perturb`; the seaglider, slocum and saildrone arithmetic written in their `why` strings (volmax 51 270 cc, Cd1 10.48, T_roll 2.75 s, pump 7.6 kJ, hotel 0.1366 W, vpp_bias width 0.0285/sqrt 12 = 0.0082); the quad_uas arithmetic (hover throttle 48 %, 12.6 m/s tilt limit, 4.4 m/s2 drag, 56 deg phase margin, 0.6 V sag); `Re_L` of `PLATE_SLOW` 1.024e6 against `PLATE_RE_MIN`; 36 mission variants through `load_mission` (all `ConfigError`, none a traceback); the argument checks of `pm.sh`, `bin/pmx.sh`, `bin/orca_gate.sh` (all refused ones exit 2 before an ssh).

### D-1. `fea_window` stores the stress-only utilization (0.367) with no flag when the buckling step returns no factor
severity: major
lane: honesty
where: cafe/pm/stage3/windows.py:362-366 (`buckling = ... if lam else None`, `utilization = max(stress, buckling or 0.0)`); cafe/fea.py:309-317 (block parsed by regex; `buckling_factor = ... if pos else None`); cafe/pm/stage3/pipeline_windows.py:403 (no check on the row)
reproduction: `rev14_d_10.py` (fea.solve replaced by one that returns what the wrapper returns when CalculiX's buckling block is missing or has no positive eigenvalue, hull = the default Seaglider at 500 m): `fea_window(veh, pts, p, buckle=True)` gives `{'utilization': 0.3671, 'stress_utilization': 0.3671, 'buckling_utilization': None, 'knockdown': None, 'buckling_factor': None}`; with a factor of 1.4552 the same call gives `utilization` 1.3744. Nothing in `windows.py`, `pipeline_windows.py` or the checks of the row turns the first case into a failure, a note or a `not run`. `fea.py` lines 309-311 parse a text block (`B U C K L I N G ...`) by regex and give `[]` when it is absent or printed differently, so a CalculiX output format that changed takes this path.
why it matters: the row then carries the very number that DECISIONS 730 (M-38) removed as 3.7 times too optimistic, under a field called `utilization`, and BRIEF 2.6 / STATUS present that field as the hull-collapse check; the absence of the check is not visible in the row, in the ledger or in the report.

### D-2. Nothing tests, and no receipt covers, the wall stress on a non-axis-aligned wall: the face-area factor and the post-kick wall velocity can be removed with every wall-model test green
severity: major
lane: tests
where: cafe/pm/stage3/wallmodel.py:160 (`area = 1.0 / jnp.maximum(jnp.abs(n).sum(0), 1e-6)`), 164 (`u_slip=uw + u1_t - fw`, the comment above it: "with the pre-kick velocity the bounce-back would hand back ~60 % of the stress"); module docstring lines 12-13, 23-24; docs/PHYSICS.md 14.3 ("times the voxel face area"); DECISIONS 79
reproduction: `rev14_d_mut.py`, mutants W11 (`area` -> 1.0) and W12 (`u_slip=uw + u1_t`): both SURVIVE the 12 wall-model tests of `tests/test_stage3.py` (`-k loglaw or wall_set or wall_state or wall_force or near_wall ...`, 82 s and 79 s) and then the same set plus `test_channel_receipts_at_ci_size` and `test_flat_plate_ci_size_regression` (`rev14_d_mut4.py`, 343 s and 339 s, log `rev14_d_mut2x.log`). Why (reasoning, not a run): the channel walls and the plate's force region are axis-aligned flats, where sum|n| = 1 and the factor is 1; the wall-velocity kick is the stress itself, 1.6e-6 against a cell speed of 0.02 to 0.04 (`rev14_d_2.py`), far below the CI tolerances (1 % on stress, 10 % on C_f).
why it matters: the vehicle windows are ellipsoids, plates and arms, i.e. curved or diagonal voxel walls, where the factor runs from 1 down to 0.58 (the mean of sum|n| over the unit sphere is 1.5): dropping it overstates the modelled wall shear on a hull by tens of percent (about 50 % in the mean over a sphere), and no test, no stored receipt (`wm_channel.json`, `wm_flat_plate.json`, both axis-aligned) and no CREDIBILITY row would show it. The 60 % leakage the second comment names is likewise unguarded. The wall model is presented as validated by the channel and the plate; for the part of it that acts on the vehicles it is not.

### D-3. `bin/orca_gate.sh` turns any tag into a directory that `rsync --delete` empties; `pmx.sh` has no "is this directory in use" guard
severity: minor
lane: robustness
where: bin/orca_gate.sh:11 (`PMX="${PMX:-pm_$2}"`); bin/pmx.sh (`rsync -az --delete ... "$H:$R/$D/"`, no owner file as `pm.sh` has for `pm/`); docs/ORCA_RUNNER.md:21 (states the default)
reproduction: `ls ~/cafe-worker/cafe` on orca lists `pm_gate pm_osuite pm_q13 pm_q14 pm_ready pm_rev14_*`. `PM_HOST=cafe-orca bin/orca_gate.sh 8 q14` (no PMX) passes `pm_tag` and `pm_names` (reproduced with `PM_HOST=nohost sh bin/orca_gate.sh 8 q14`, also `gate` and `ready`: rc 1 at the first ssh, not rc 2 from the checks) and syncs the caller's checkout with `--delete` onto `pm_q14`, the code tree of the q14 demo run; with tag `gate` it is `pm_gate`, with `ready` the go check's. The same holds for a second `bin/pmx.sh` with the PMX of a job that is running (I avoided it by using a second PMX for my ad-hoc runs while the mutation job ran in `pm_rev14_d`): the files under the running job are replaced.
why it matters: the tag is meant to name a log; as a default for a directory it collides with any agent's earlier directory. Only server-written outputs are protected (`sync_filters`); the code a finished run's audit digests is not.

### D-4. A real wall cell whose smoothed-solid gradient is exactly 0 gets a shear force about 1e6 times the log-law stress
severity: minor
lane: numerics
where: cafe/pm/stage3/wallmodel.py:87-90 (`nrm /= np.maximum(norm, 1e-12)` leaves n = 0), 160-161 (`area = 1/max(sum|n|, 1e-6)` = 1e6; `valid` is True)
reproduction: `rev14_d_2.py`: solid mask 8x11x8 with fluid layer y=5 between two 5-cell walls (symmetric about it) and a uniform u = 0.02: `wall_set` gives `|n|` = 0.0 for all 64 wall cells; `wall_state` gives `fw` max 1.59 against `utau`^2 = 1.59e-6 (u_tau 1.26e-3). The ordinary half-space wall in the same script has `fw` max 1.59 as well, because `lbm.links` wraps by `jnp.roll` and the cells of the opposite domain face (where the reflected Gaussian gradient is 0) become wall cells of the wall too.
why it matters: the comment says only padded entries have n = 0; a body that touches a domain face, or a one-cell slot symmetric in the smoothing window, gets a force 6 orders too large in the cell and the run diverges or reports a nonsense drag. The nest places bodies away from the faces today, so this is a latent hazard, not a seen failure. Fix: `valid &= |n| > 0` in `wall_set`.

### D-5. `physics.check_params` raises a bare `OverflowError` for an integer too large for a float
severity: minor
lane: robustness
where: cafe/pm/physics/__init__.py:44-47 (`_numeric` catches `TypeError`, `ValueError` only; `np.asarray(v, float)`)
reproduction: `rev14_d_1.py`: `battery_J: {value: 1<400 zeros>, ...}` in a copy of `seaglider.yaml` (YAML reads it as an int): `glider.load_platform(path)` raises `OverflowError: int too large to convert to float`, not the `ValueError` naming file and field. `sampling._num` (look-ahead L1 of round 13) and `config.finite_real` already catch it; the same class of input.
why it matters: the loader's contract (docstring, RUNBOOK) is a `ValueError` naming the field; `validate`, stage 1 and `hangar` end in a traceback for this input, as they did for the other shapes round 11 M-25 fixed.

### D-6. A list-valued platform parameter accepts strings and booleans as numbers; the scalar rule refuses both
severity: minor
lane: data
where: cafe/pm/physics/__init__.py:40-47, 59-67 (`np.asarray(["0.0025"], float)` converts; `isinstance(v, (str, bool))` is tested on the whole value only)
reproduction: `rev14_d_3.py` on a copy of `quad_uas.yaml`: `inertia_kgm2: ["0.0025","0.0021","0.0043"]` LOADED -> `['0.0025', '0.0021', '0.0043']`; `ocv_soc` as strings LOADED; `levels_m: [True, 25.0, 50.0, 80.0]` LOADED (level 1 m, below the schema's 2 m minimum for a mission); `mass_kg: "0.772"` is REFUSED.
why it matters: the quoted numbers reach the model as strings and fail at the first arithmetic in stage 1 (a traceback hours in), or as `True` fly a 1 m level; the check was meant to catch exactly this at load time.

### D-7. `subgrid.write_calibration` writes the tracked `config/subgrid.json` in place, not through `config.write_text`
severity: minor
lane: robustness
where: cafe/pm/env/subgrid.py:503 (`f.write_text(head + ...)`); DECISIONS.md row 739 (the sweep list and the "five writers by hand" list: this one is in neither)
reproduction: `rev14_d_7.py` (a copy of `config/subgrid.json`, `RLIMIT_FSIZE` 700 bytes, which is what a full disk or a kill part-way leaves): `write_calibration(cal, copy)` raises `OSError [Errno 27]`; the file is then 700 bytes of 3,712 and `json.loads` fails (`Unterminated string ... char 600`).
why it matters: every run reads this file (`_load`); row 739 says `config.write_text` is the one writer of a file "a later stage reads back". `promote-calibration` is deliberate and committed, so `git checkout` recovers, but the claim of the row does not hold and the failure is a hard stop for every later run.

### D-8. `bin/proot_suite.sh` does not act on TERM/INT/HUP during the shares step or the final audit step until that foreground step ends
severity: minor
lane: robustness
where: bin/proot_suite.sh:29 (`trap stop INT TERM HUP`), the foreground `sh "$R/bin/proot_run.sh" ... python -m cafe.pm.shares` and the step-4 `sh "$R/bin/proot_run.sh" ... sh -c 'coverage combine ... audit'`; header line 12 ("TERM, INT or HUP stops every job")
reproduction: a toy with the same shape (`trap_toy.sh` in the same scratchpad folder: `trap stop TERM`, foreground `sh -c 'sleep 6'`, `kill -TERM` after 1 s): "stop ran at 6s". POSIX defers a trap while a foreground command runs. In `proot_suite.sh` the foreground step 4 is ruff, mypy, the scans and the coverage gates (minutes); a `kill -TERM <suite pid>` (not `tmux kill-session`, which also reaches `proot_run.sh` in the process group) leaves the audit running and `.pid` in place until it ends.
why it matters: the stop path of the gate is documented as immediate; in steps 1 and 4 it is not.

### D-9. The 2.4 GHz link of the UAS exists three times with two powers, and no code reads any; a stale comment says stage 1 does not read `quad_uas.radio.rfd900x`
severity: minor
lane: data
where: platforms/quad_uas.yaml (`radio.link_2g4` tx 27 dBm, rx -100 dBm), platforms/radios.yaml (`xbee_pro_24` tx 18 dBm, rx -100 dBm), platforms/saildrone_explorer.yaml (`radio_2g4: xbee_pro_24`, `OPTIONAL`/`STRINGS` "read by no code", usv.py:103,130); cafe/pm/physics/uas.py:76-77 (comment "`radio.rfd900x` and `link_2g4` are not read here (stage 1 takes radios from platforms/radios.yaml)"); cafe/pm/stage1.py:284-285 (`_uas_radio` takes `freq_mhz`, `tx_power_dbm`, `rx_sensitivity_dbm` from the quad_uas file and overrides radios.yaml's `center_mhz`, `tx_dbm`, `rx_sens_dbm`); stage1.py:643 (the mission's `rf` link reads radios.yaml directly)
reproduction: `grep -rn "link_2g4\|radio_2g4\|xbee_pro_24" cafe`: no reader (only the `STRINGS` tuple and tests). `stage1._uas_radio` returns `dict(base, center_mhz=mean(r["freq_mhz"]), tx_dbm=r["tx_power_dbm"], rx_sens_dbm=r["rx_sensitivity_dbm"])`. So the same RFD900x numbers (30 dBm, -121 dBm, 915 MHz) are two copies: the UAS lost-link hook uses the quad_uas copy, the `usv-uas-rf` link verdict the radios.yaml copy; editing one (the RUNBOOK sends the lab to `radios.yaml` for the radio) changes one of the two evaluations.
why it matters: today the copies agree, so no number is wrong; the comment is wrong, the 27 dBm "500 mW" 2.4 GHz radio and the 18 dBm XBee describe the same link and neither can be used, and a lab edit of one copy diverges silently.

### D-10. Five keys of `config/subgrid.json` are read by nothing, among them the gust-front detection threshold
severity: minor
lane: data
where: config/subgrid.json:2 (`version`), 5 (`turbulence.model`), 14 (`stability.scaling`), 18 (`gust_front.detection` = `{dT_K: -1.5, within_s: 600}`); cafe/pm/env/subgrid.py (reads `turbulence.*` numbers, `gust_front.*` through assumptions, `calibration`, `rain_lens`, `ocean`)
reproduction: `grep -rn "within_s\|\bdT_K\b" cafe --include=*.py` finds only `assumption("subgrid.rain_lens.dT_K")`; no reader of `detection`, `model`, `scaling` or `version`. The event's own drop comes from `calibration.gust_stats.dT` (-1.5), and the detection threshold appears only in prose (subgrid.py:264, 689).
why it matters: the file's note says "the code uses it"; a lab that edits `detection.dT_K` or `stability.scaling` (the latter reads like a switch, `"mixing_length"`) changes nothing and is not told. Label them as documentation or read them.

### D-11. `tests/test_tao.py` does not pin the roughness-law constants, the 1 m/s direction floor or the fixed-point iterations (mutants that survive)
severity: minor
lane: tests
where: cafe/pm/env/tao.py:67 (`CH2`, `UMAX`), 313-315 (`_z0`'s `1e-4` floor), 333 (`for _ in range(20)`), 322 (`range(30)`), 407 (`fast = (ws >= min_speed) & (ts >= min_speed)`)
reproduction: `rev14_d_mut.py`, log lines: `T3 CH2 -0.0050 -> -0.0040` SURVIVED; `T3b UMAX 19 -> 25` SURVIVED; `T12 fast & -> |` SURVIVED; `T17 ust floor 1e-4 -> 1e-3` SURVIVED; `T23 range(20) -> range(2)` in `wind_to_10m` SURVIVED; `T24 range(30) -> range(2)` in `cd10n` SURVIVED. (`T10`, a fallback `1.0 -> 0.0` for zero speed, and `T14`, the longitude wrap that no TAO mooring needs, are equivalent mutants.) The receipt gate on the Charnock law is 5 % on Cd, the law agrees with COARE to 0.6 % (`rev14_d_9.py`: shipped max 0.0062, with CH2 = -0.004 it is 0.0153 and still passes); the only test of the slope uses `CH1 = 0` (`test_a_wrong_charnock_slope_fails_the_drag_receipts`).
why it matters: a 20 % change of the intercept, a switch of the 1 m/s direction floor from "both" to "either" (noisy directions of a near-calm sample enter the direction bias and rmse, and the fitted `wind_direction_bias`), and a collapse of the fixed point to 2 iterations all pass. The pipeline repeats the floor on its own (`_wind_residuals`: `ws >= 1.0` and `ts >= 1.0`), so the fit would stay right while `compare()` would not.

### D-12. Other mutants that survive the tests that name the file
severity: minor
lane: tests
where: cafe/pm/physics/__init__.py (`ge1` at 1, nested lists, `drop_repeats(cyclic)`), cafe/pm/stage3/wallmodel.py (`plate_mask` nose profile, `receipts()` y+ share gate)
reproduction: `rev14_d_mut.py` / `rev14_d_mut3.py` / `rev14_d_mut5.py`. After rerunning each survivor against the wider files that exercise it (`test_glider.py`, `test_usv.py`, `test_uas.py`, `test_stage3.py`, `test_nest.py`): P4 `ge1`: `a >= 1` -> `a > 1` SURVIVES (usv `cap_cycles` = 1.0, the boundary the message "1 or above" and the comment "N >= 1" name, is not tried); P11 `list3:pos` without the `ndim == 1` test SURVIVES (a nested list `[[1,2,3]]` would load); P21 `drop_repeats(..., cyclic)` without the wrap-leg removal SURVIVES `-k r9_m13 or waypoint` of glider and usv; W29 `plate_mask` nose `sqrt` profile -> linear SURVIVES the heavy set (330 s); W31 `receipts()` y+ share gate 0.9 -> 0.5 SURVIVES `test_wall_model_receipts_pass_and_fail`. P1 (`frac` upper bound 1: no shipped table uses `frac` without a maximum) and P23, T10, T14, W8 are equivalent mutants. 81 mutants in all: 55 killed on the first pass, 25 survived it; 6 of the 25 were killed by the wider files (P6, P12, P19, P20, P22, W4); W16 is an invalid mutant (a TypeError), W18 matched twice and was not run.
why it matters: each is a documented rule (a kind's boundary, the dedupe of a closed route, the nose of the validation plate, the 90 % share of cells in the log layer that BRIEF 5.5 names) that a later edit could change unseen.

### D-13. PHYSICS.md section 7 gives the range of the other 13 moorings' speed bias as +0.07 to +1.14; the ledger has -0.032
severity: minor
lane: documentation
where: docs/PHYSICS.md (section 7, paragraph "The persistent sd is 5 times the 11-mooring one ...")
reproduction: `q14/ingest/tao_compare.json`: `T2N170W.speed_bias` = -0.0321 (n 145, WIND file `OS_T2N170W_DM408B-20221014_D_WIND_10min.nc`, in the 14 of the manifest); the other twelve run +0.073 (T2S165E) to +1.142 (T5N165E); T5S165E is -1.482 as written. The document's cache is that of 6 Nov; q14's manifest lists the same 14 moorings.
why it matters: the sentence is the argument that one mooring decides the persistent sd; the low end of the "others" is -0.03, not +0.07. (I could not recompute the quoted 0.155 sd of the 13 without the residual series; the unweighted sd of the 13 per-mooring means is 0.398 against sampling variance about 0.15 to 0.17, so the value sits near the floor sqrt(between/13) = 0.110 to 0.16; worth rerunning `fit_wind_error` without T5S165E.)

### D-14. The fitted wind-bias mean is the sample-pooled mean, but it is cited as "the 14-mooring mean error" and its uncertainty is that of the unweighted mean
severity: minor
lane: statistics
where: cafe/pm/pipeline.py:945 (`mean = -a["speed_bias"]`, `a = cmp["ALL"]`), 957 (the citation text), 898-900 (`between`, `between / len(kept)`); cafe/pm/env/tao.py:446 (ALL pooled over samples); docs/PHYSICS.md section 7
reproduction: `q14/ingest/tao_compare.json`: the 14 per-mooring `speed_bias` have unweighted mean 0.4600 m/s and sd 0.6771; `ALL.speed_bias` is 0.4692 (n 1927; T0N170W has n 43, the others 144 to 145); `priors_fitted.json` has `mean -0.46922` and its citation says "minus the 14-mooring mean error". Direction: unweighted -6.380 deg, ALL -6.239 deg, fitted +6.2387.
why it matters: the difference is 0.009 m/s and 0.14 deg, immaterial for a verdict; but the centre of the random-effects prediction (sample-weighted) and its variance term (`between/k`, for the unweighted mean) are two estimators, and the citation names the other one. Either use the mooring mean or say "pooled over samples".

### D-15. Two docstrings of `wallmodel.py` give different, wrong ratios of Smagorinsky's length to the mixing length
severity: minor
lane: documentation
where: cafe/pm/stage3/wallmodel.py:14-17 ("6x too short at y = 1 cell and 15x at 2.5"), 168-172 ("6x too short at y = 1 cell and 6x at 2.5")
reproduction: arithmetic: the log law needs l = kappa y; the Smagorinsky length is C_s dx = 0.17 cells. kappa y / 0.17 = 0.41/0.17 = 2.4 at y = 1 and 1.025/0.17 = 6.0 at y = 2.5. "6x" at y = 1 and "15x" at 2.5 are y/0.17 (5.9 and 14.7), i.e. without kappa; the second docstring then repeats 6x for both.
why it matters: the argument for `near_wall_tau` is quantitative; the printed ratios are wrong in both places and disagree with each other. (The mechanism is right: the ratio is above 1 at the matching point.)

total: 15 findings (0 critical, 2 major, 13 minor)
