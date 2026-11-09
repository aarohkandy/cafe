# Round 13, reviewer D (stage-3 path, outside-cafe/pm modules, dtmb5415, whatif)

Read line by line: stage3/lbm.py, nest.py, freesurface.py, fluidx3d.py, refit.py, windows.py, pipeline_windows.py; cafe/planner.py (with `boundary_layer`), cafe/fea.py, cafe/reach.py, cafe/cfd.py (the parts the pipeline and dtmb5415 use), cafe/emulator.py (the SITL part uas.py uses), cafe/pm/emulator.py, cafe/pm/dtmb5415.py, cafe/pm/whatif.py. Ran on orca (proot, 2 CPUs): the first 42 tests of tests/test_stage3.py (stopped by me, see below), tests/test_emulator.py + test_reach.py + test_whatif.py (all passed, rc=0), one FEA computation and one whatif script. Numbers recomputed by hand and found right: Knud Thomsen ellipsoid area 17.03 m2, hull_fs displacement 1.98 m3, wetted ratio 1.29, 0.37 L Re^-1/5 boundary layer (30 mm at the BRIEF's 1.5 m hull), the demo's skipped-window dx / cells / cell-updates for the glider (1.9 mm, 6.5e9, 1.4e15), Bouzidi and Ladd terms, DerSimonian-Laird pool, Richardson solve, uas_leg_speed, Zermelo made_good.

### D-1. The printed "a calibrated emulator misses the coverage gate by chance with probability P" is about half the true figure at the planned hold-out size
severity: minor
lane: statistics, honesty
where: cafe/pm/whatif.py:450-457 (`_chance_miss`, Binomial(n_test, 0.9)) and :517-519 (`coverage_chance_fail`); cafe/pm/pipeline.py:1551 (the note); cafe/pm/emulator.py:34-38 (`_conformal_q`) and :189-194 (the calibration split); DECISIONS 263 ("0.255 at 20 points"); docs/PHYSICS.md 13.6
reproduction: the smallest trainable scope has `budget.EMULATOR_MIN_POINTS` = 100 distinct points. `holdout_report` takes round(0.2 x 100) = 20 as test, fits a sub-emulator on 80, and `fit` keeps round(0.2 x 80) = 16 as the conformal calibration set, so `_conformal_q` uses k = ceil(17 x 0.9) = 16. Split conformal then covers a new point with probability k/(n_cal+1) = 16/17 = 0.941, not 0.90, and for a fixed calibration set the coverage is Beta(16, 1). The gate band is 0.85 to 0.95 on 20 test points (17, 18 or 19 hits). `whatif._chance_miss(20, 0.9)` = 0.2545 (printed on orca, the figure the note gives). A Monte Carlo of exchangeable scores with n_cal 16, n_test 20 (200 000 draws, numpy, no repo code) gives mean coverage 0.941 and P(outside the band) = 0.526; Binomial(20, 16/17) alone gives 0.325. The all-20-hits outcome (coverage 1.0, above 0.95) is the main miss: probability 0.30 at 0.941 against 0.12 at 0.90. At 25 and 30 test points the same calculation gives 0.76 and 0.68 (Beta-binomial) against 0.51 and 0.36 printed.
why it matters: the note and holdout.json exist to tell the reader that a MISSED coverage gate is weak evidence of a bad emulator; they understate how weak (a well-calibrated, conservative split-conformal emulator fails the two-sided gate about one time in two at the minimum size), and the number is printed beside the word MISSED. tests/test_whatif.py:369 pins the binomial figure.

### D-2. The stage-3 FEA never runs the buckling step, so the stored "utilization" leaves out hull collapse (BRIEF 2.6 asks for it); for the default glider it reads 1.9 times too low
severity: minor
lane: physics, documentation
where: cafe/pm/stage3/pipeline_windows.py:399-404 (`_fea_child` calls `W.fea_window(veh, ..., h=...)` with `buckle` left False); cafe/pm/stage3/windows.py:345-366 (`fea_window`, `buckle: bool = False`); docs/BRIEF.md:129 ("check hull collapse (Bresse Receipt) ... Output a structural utilization ratio per window"); cafe/pm/pipeline.py:13 ("FEA utilization")
reproduction: on orca a script built the pipeline's default glider hull (ellipsoid radii 0.9 / 0.15 / 0.15 m, Al 6061, 8 mm wall, depth 500 m, h = L/20 as `stage3.fea_elements_along`) and called `W.fea_window(veh, zeros((1,3)), zeros(1), h=0.09, buckle=True)`. Output: `vm_p99` 101.3 MPa so utilization on von Mises alone = 101.3 / 276 = 0.367 (what the pipeline stores, buckle False); `buckling_factor` 1.455 (after the module's 0.75 follower factor), so `1/buckling_factor` = 0.687 and `utilization` = 0.687 (hydrostatic 5.03 MPa). The pipeline's value is 0.367, a factor 1.87 below what the same function returns with the step on. No document says the pipeline's utilization is stress only; tests/test_stage3.py:577 covers `buckle=True` but nothing calls it from the pipeline.
why it matters: the only structural number the stage produces omits the mode that governs a thin pressure hull, and the omission is not stated anywhere. (In the q13 demo no window runs, so no value reached the report.)

### D-3. `whatif.apply` raises a bare ValueError ("year 116102 is out of range"), not `Invalid`, for a very large deploy shift
severity: minor
lane: robustness
where: cafe/pm/whatif.py:138 (`apply`: the `Invalid` message calls `_iso(t)`), :172 (`_iso`, `datetime.fromtimestamp`); :710 (`parse_shift` accepts any run of digits; cafe/pm/__main__.py:173 catches `ConfigError` (the CLI path by reading, not run)
reproduction: on orca, `whatif.apply(config.load_mission("missions/tepex_c_demo.yaml"), {"glider_eq": {"shift_h": 1e9}})` raises `ValueError: year 116102 is out of range`; the same for `usv` and `glider_2n`. `shift_h` 6 and 24 return the mission; the UAS with 1e9 is accepted (a different branch). `apply`'s docstring says it makes the changed mission or raises Invalid. `parse_shift("1000000000h")` returns 1e9, so `python -m cafe.pm whatif ... --shift 1000000000h` reaches it; the CLI handler names `ConfigError`, so a bare ValueError would be a traceback instead of an `error:` line.
why it matters: an odd but valid argument crashes with a traceback where every other out-of-window shift gets a sentence; the flip search and `design` rely on `Invalid` to skip candidates.

### D-4. `whatif.apply` applies a move to a shared ship once, so the second UAS's own move is silently dropped (training variants and answers disagree with what was asked)
severity: minor
lane: correctness, robustness
where: cafe/pm/whatif.py:123 and :142-144 (`ship_moved` flag), :380 and :398 (`_fits`, `design` gives each vehicle its own Latin-hypercube move and `_fits` validates it)
reproduction: on orca, the demo mission with its UAS copied as `uas_b` (same ship) and `whatif.apply(m3, {"uas": {"dlon": -0.5}, "uas_b": {"dlon": -0.2}})`: the ship ends at lon -165.5 (base -165.0), i.e. only the first vehicle's -0.5 was applied; nothing says `uas_b`'s -0.2 was ignored. `is_base` / `_fits` / `describe` treat the second as a real change.
why it matters: with two UAS on one ship the training design (DECISIONS: "each vehicle its own") is not what it says, and a per-vehicle what-if move for the second is ignored without a message; both rows carry the first vehicle's ship position.

### D-5. The flip search's two UAS duty candidates are the same mission at costs of 1 and 2 notches
severity: minor
lane: honesty, statistics
where: cafe/pm/whatif.py:61 (`DUTIES = (0.75, 0.5)`), :569 (`candidates`, cost `(1 - f)/0.25`), :165 (`_duty_days` rounds a period of a day or more up to whole days)
reproduction: on orca, `whatif.apply(m, {"uas": {"duty": 0.75}}) == whatif.apply(m, {"uas": {"duty": 0.5}})` is True (both give `every_days` 2.0 from 1), and `candidates(m, "uas")` lists `duty 0.75` at cost 1.0 ("fly sorties every 2 d instead of 1 (rounded up to whole days)") and `duty 0.5` at cost 2.0 ("fly sorties every 2 d instead of 1"). The q13 flip.json carries both.
why it matters: the cost is "one notch = 25 % of duty" but the cheaper candidate halves the sorties, and the search ranks "cheapest change" by that number; the second candidate is a duplicate that can only waste a Stage-1 fallback.

### D-6. A killed FEA window leaves its ccx process running (only the python child is killed)
severity: minor
lane: robustness, performance
where: cafe/pm/stage3/pipeline_windows.py:408-427 (`_fea`: `_spawn([...], timeout=timeout_s)` with no `start_new_session` and no group kill); cafe/fea.py:278 (`subprocess.run(["ccx", ...])`, no timeout); compare freesurface.arm_watchdog (:182) and `_fs_work` (`start_new_session=True`), which do kill the group
reproduction: a child that runs `subprocess.run(["sleep", "8"], capture_output=True)`, run under `subprocess.run([python, "-c", child], capture_output=True, timeout=1)`: TimeoutExpired after 1 s, and `pgrep -f "^sleep 8$"` still finds the grandchild (laptop, pid killed by hand afterwards). `fea.solve` runs ccx exactly so.
why it matters: a window whose FEA is cut at its deadline keeps one CPU busy for as long as ccx runs, inside a stage-3 wall-clock share the code calls not negotiable, while its temporary directory is deleted under it.

### D-7. `fluidx3d.available` treats any truthy `enabled` as on, including the JSON string "false"
severity: minor
lane: robustness
where: cafe/pm/stage3/fluidx3d.py:34-35 (`settings`), :43 (`if not s["enabled"]`)
reproduction: on orca, `fluidx3d.available({"fluidx3d": {"enabled": "false", "binary": "/bin/ls"}})` returned `(True, 'using /bin/ls')`.
why it matters: the plugin is licence-restricted (commercial and military use forbidden, docs/LICENSES.md) and is meant to need one deliberate config line; an odd but valid value switches it on, and `budget.fs_plan` then drops the interFoam plan.

### D-8. The draft that "would give the platform's displacement" ignores the keel the same sentence counts
severity: minor
lane: documentation
where: DECISIONS 407 ("a draft of about 0.18 m, c = 3 V / (2 pi a b)"); config/assumptions.yaml `stage3.usv.hull_draft_m` `replace_with`; docs/PHYSICS.md 14.4 (USV windows)
reproduction: the same row says the mesh displaces 1.98 m3 = half ellipsoid (1.838 m3 at c = 0.45) + keel box 0.140 m3, against the platform's 750 kg / 1023 = 0.733 m3. c = 3V/(2 pi a b) with V = 0.733, a = 3.25, b = 0.6 is 0.179 m, which matches the ellipsoid alone. With the keel kept, c = (0.733 - 0.140) / (2 pi/3 x 3.25 x 0.6) = 0.145 m. At 0.18 m the mesh would displace 0.18 x 4.084 + 0.14 = 0.875 m3 (895 kg), 19 % over the platform's.
why it matters: the stated remedy for the 2.7 x displacement overshoot is itself 24 % off, in a figure a lab user would type into the yaml.

### D-9. "6 is the measured scaling knee" is not a measured point
severity: minor
lane: documentation, honesty
where: cafe/pm/stage3/freesurface.py:110-115 (`nproc`), DECISIONS 297; config/throughput.json `openfoam-pimpleFoam-les`
reproduction: the file holds measurements at 1, 2, 4 and 8 cores only: 46.4k, 86.4k, 141.9k, 164.5k cell-updates/s, i.e. efficiency 1.00, 0.93, 0.76, 0.44. Six cores is interpolated (`freesurface.rate` uses `np.interp`: 153k, efficiency 0.55). The curve has already bent at 4 (the step 4 to 8 buys 16 % for twice the cores); no measurement places a knee at 6.
why it matters: the cap that sizes the free-surface price is called measured; it is a choice between two measured points.

total: 9 findings (0 critical, 0 major, 9 minor)

## Not covered
- The stage-3 test file: only the first 42 of 155 tests in tests/test_stage3.py ran before I stopped them (orca at load 10 to 40, a 2-CPU run was 35 min for 42); no failure among them. tests/test_lbm.py and tests/test_nest.py (XLB and the native kernel) were not run.
- No LES window, no free-surface case and no real FEA of a pipeline window ran (the demo skips all of them on CPU); the physics of `nest.make_step`, the moving-wall terms and the specular wall were read and checked against their formulas, not run beyond what the test files do. wallmodel.py was outside my list and not read.
- cafe/cfd.py: `free_surface` (lines 448-640) and `characterize_free_surface` read; the external-flow half (lines 219-380) and the OpenFOAM dictionary text were skimmed, not read line by line. dtmb5415.py read, not fuzzed; no mutation runs on any of these files.
- cafe/emulator.py (SITL): read, not run; cafe/planner.py `plan` and `check` read, not run (only `boundary_layer` reaches the pipeline); cafe/reach.py read and checked through the `report._reach_one` path only.
- whatif.answer and the flip search were read and exercised through the test suite and q13's flip.json; `apply`, `candidates` were run on the demo mission on orca. No 30-day window, no NaN or zero-wind mission.
- Incidents: the first test bundle (test_stage3, test_emulator, test_reach, test_whatif in one command) was stopped by me with `tmux kill-session -t =rev13_d_stage3` (my own session; rc=143 in its log), then the pieces were rerun. Nothing wrong with orca itself, so no row in review/orca/PROBLEMS.md. My orca directory pm_rev13_d and my log files rev13_d_*.log were removed; the detached worktree ../cafe-rev13-d was removed. Nothing was written under pmdata/runs.
