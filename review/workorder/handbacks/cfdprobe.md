# Hand-back: cfdprobe (work order step 3, plan step 0 only)

## What changed
- New `review/workorder/rans_probe.py` (standalone script). No product code, no `cafe/cfd.py` edit, no test, no document edit, no printed sentence in the product.
- Steps: (1) `Context` on the demo mission and the run dir (default `/data/runs/q25`, read only), `PW.glider_vehicle` and `PW.glider_case` for the first glider (`glider_eq`, Seaglider) at its first window, with `PW.track_heading` from the run's `res.pkl`, as `_row` does; (2) union STL by `trimesh.boolean.union(engine="manifold")` of `W.vehicle_mesh` of each shape, watertight check, no shift, to `<out>/glider.stl`; (3) `vb = R @ (v - u_env)`, label `x[+-]z<angle .2f>`, `cfd.dvec` check (also the angle error of the rounded label); (4) `cfd.external` at `level_offset` -1 then 0, `dirs=(label,)`, `cfd._shrink` after each; (5) prints and writes `<out>/result.json` (per grid: level, surface_cell_m, cells, failed_checks, seconds, solve and mesh seconds, iterations, drag, force, force_std, scatter, cd; summary: `vv.refinement_ratio`, `cfd.gci`, cd on `veh.ref_area`, `cd_hangar`, cd/cd_hangar, total seconds). `result.json` is rewritten after each grid, `info.json` holds the case facts.
- `--stop-after-stl` does 1 to 3 and prints one JSON line (label, speed, triangles, watertight). `--cores N` sets `CAFE_NPROC` before `cafe.cfd` is imported (`info.json` records `cfd.NPROC`).
- Guard: `--out` must be named `rans_probe*` and not under /tmp (cfd.external does `rmtree` of its case dir).

## Full run (lead, alone on the worker, after the overnight run ends)
    PM_HOST=cafe-orca PM_RUNTIME=proot PMX=pm_wo_cfdprobe PM_CPUS=6 PM_MEM=24g TM=rans_g1 bin/pmx.sh python review/workorder/rans_probe.py --cores 6
(`PM_CPUS` must equal `--cores`; `PM_TAKE=1` if the sync is refused.) Log `~/cafe-worker/logs/rans_g1.log` ends `rc=N`; results `/data/runs/rans_probe/result.json` (orca: `~/cafe-worker/cafe/pmdata/runs/rans_probe/`). Stop it only by exact session name `rans_g1`.

## Verified (orca, `--stop-after-stl`, PM_CPUS=2, twice)
Printed: `{"label": "x-z5.29", "speed_ms": 0.13519521980268892, "stl_triangles": 1332, "stl_watertight": true}`.
`info.json`: vb = (0.13462, 0, -0.01247) m/s, label error 0.004 deg, glide -19.3 deg, alpha 5.3 deg, extents 1.8 x 1.0 x 0.3 m, ref_area 0.07069 m2, cd_hangar 0.3014 (cl_hangar 0.861), case density 1023.2, window t 1678006800 (-169.97, 0.008), dive 950 m. cfd sizes: L 1.8 m, h0 0.45 m, surface cell 9 mm (level 6, 7 mm cells; level 5 = 14 mm for the coarse grid).
Also checked, no solver: blockMesh, surfaceFeatureExtract, decomposePar, snappyHexMesh, checkMesh, simpleFoam and mpirun are on the PATH under proot, and `mpirun --oversubscribe -np 2 hostname` starts (uid 5337, TMPDIR /tmp = the worker's disk).

## Not verified
- No solver ran: snappy meshing of the 12 mm plate, GCI, seconds, memory at 6 ranks, `mpirun -np 6` with the solver.
- `ruff` is not installed on the laptop and the file lies outside cafe/pm and tests (not run). `py_compile` passes.
- Whether the q25 run's windows.json and res.pkl match HEAD's mission (q25 was made at 561cad0; the mission file is HEAD's).

## What would make the full run fail or write outside ~/cafe-worker
- Nothing found that writes outside: cases go to `--out`; `cfd.external` writes only its case dir; mpirun's session files go to the proot /tmp (`~/cafe-worker/cafe/tmp/run.*`); `cfd.CACHE` (/work, read only) is not used by `external`.
- The plan said ~0.25 m/s; the code gives 0.135 m/s (Re about 2e5). Code wins.
- The wing is 12 mm thick; the coarse grid's cell is 14 mm, the fine 7 mm (1.7 cells): snappy may drop or badly mesh the plate on the coarse grid (shows as failed_checks or a large GCI). Read `log.snappyHexMesh` and `log.checkMesh` in the kept case dirs.
- No wall-clock limit in `cfd.external` or the probe: a stuck run goes on until killed. `maxGlobalCells` 6 M caps the mesh silently.
- cd uses the solver's rho (1025); cd_hangar the case's (1023.2): the 0.2 % difference is recorded in `summary.note`, not corrected.
- `characterize_external` is not used (it would run a third grid above GCI 0.3 and drop the coarse mesh's checks).

## Decisions / CHANGELOG
None needed (a measurement script, no behaviour). Suggested CHANGELOG line for the merge: "review/workorder/rans_probe.py: one-case CPU RANS measurement of the demo Seaglider (two grids, GCI, cd against cd_hangar); no product change."

## Skeptic pass
New file `tests/test_wo_cfdprobe.py` (loads the script by path; the grid record moved into `rans_probe.grid_entry`). Jobs: `wo_cfdprobe_before` (old script, rc=1, both tests fail: no `grid_entry`), `wo_cfdprobe_after` (rc=0). Also on orca: `ruff check cafe/pm tests review/workorder/rans_probe.py` clean (rc=0); `tests/test_round23_claims.py` + the new file rc=0; `--stop-after-stl` smoke rc=0, same line as before. mypy not rerun: no file under cafe/pm changed.
1. surface_cell_m per grid (medium, real): `grid_entry` writes `L/4/2**level` (coarse 14 mm, fine 7 mm for L 1.8 m), not the requested 9 mm. `info.json.surface_cell_m` stays the requested size (cfd.external's `hs`). Test `test_surface_cell_is_the_one_the_level_gives`.
2. cd / cd_hangar rho (low, not real as a defect): cd is a dimensionless coefficient of the simulated flow; the solver's force carries rho 1025 (cfd.py FLUIDS), so `drag / (0.5*1025*U^2*A)` is the consistent cd. Rescaling by 1023.2 would put a 0.2 % error into the force instead. The ratio compares two coefficients; it is correct. The note in `summary.note` stays. Real part: `cd_on_ref_area` duplicated `cd`; removed (plan names only `cd`).
3. Three lines over 160 (low, real): wrapped; `awk length>160` empty, ruff clean on the file.
4. drag <= 0 (low, real): `grid_entry` raises ValueError (`grid <name>: the drag <x> N along <label> is not positive; the case in <dir> is kept for its logs`); the earlier grid stays in result.json. Test `test_a_grid_whose_drag_is_not_positive_is_refused`. Cores vs PM_CPUS check: not added (a new printed sentence the plan does not name); routed to the lead.
Printed sentences added: the one ValueError above; summary key `cd_on_ref_area` removed, per-grid `surface_cell_m` now means the real cell.
Hand-back "Not verified" update: ruff on the file was run (clean). The 12 mm plate versus 14 mm coarse / 7 mm fine remark stands.

## Convergence experiment

Goal: a two-grid setting for `cfd.external` on the demo Seaglider (label `x-z5.29`, 0.1352 m/s) with GCI <= 0.10, refinement ratio >= 1.3, 0 failed mesh checks, drag scatter <= 0.02, at most about 30 min a case on up to 16 cores. No product code was touched; `rans_probe.py` and its test changed (below). Everything below is read from `result.json`, `force.dat` and the OpenFOAM logs in `cafe-orca:~/cafe-worker/cafe/pmdata/runs/rans_probe{,2,3,4}/` (job logs `~/cafe-worker/logs/rans_g{1,2,3,4}.log`, all rc=0). Level offset 0 is level 6 (7.03 mm), 1 is level 7 (3.52 mm), -1 is level 5 (14.06 mm).

### Result: a setting passes
`--levels 0 1` (levels 6 and 7). With the default 1500 iterations on 16 cores: 1,283,035 cells fine, GCI 0.0904, ratio 1.596, both grids 0 failed checks, true drag std 0.5 %, 992 s (16.5 min). With 600 iterations: GCI 0.085 (16 cores) and 0.090 (6 cores), 405 s on 16 cores and 867 s (14.5 min) on 6 cores. The margin under 0.10 is thin (see "What is still wrong").

### Every run
Drag in N, cd on `ref_area` with the solver's rho. "std rel" is the true std of the drag over the last 20 % of iterations (`force.dat` projected on `dvec(label)`) over its mean; "bound" is sum_i |d_i| force_std_i / drag; "norm" is the old `scatter` (norm of force_std over drag, mostly lift). g1's std rel and bound were computed from its `force.dat` and `result.json` (the old script did not write them).

| job (out dir) | grid | level (offset) | iterations run / cap | cells | failed checks | seconds, cores | drag | cd | std rel | bound | norm |
|---|---|---|---|---|---|---|---|---|---|---|---|
| g1 (rans_probe) | coarse | 5 (-1) | 146 / 1500 | 108,837 | 0 | 30.9, 6 | 0.23655 | 0.3573 | 0.0000 | 0.0000044 | 0.000017 |
| g1 | fine | 6 (0) | 1500 / 1500 | 316,218 | 0 | 417.2, 6 | 0.25824 | 0.3900 | 0.0050 (0.00128 N) | 0.0123 | 0.0838 |
| g2 (rans_probe2) | coarse | 6 (0) | 1500 / 1500 | 315,595 | 0 | 203.6, 16 | 0.25746 | 0.3888 | 0.0051 | 0.0110 | 0.0772 |
| g2 | fine | 7 (1) | 1500 / 1500 | 1,283,035 | 0 | 788.4, 16 | 0.24600 | 0.3715 | 0.0050 | 0.0143 | 0.0949 |
| g3 (rans_probe3) | coarse | 6 (0) | 600 / 600 | 316,197 | 0 | 89.4, 16 | 0.25760 | 0.3891 | 0.0052 | 0.0115 | 0.0790 |
| g3 | fine | 7 (1) | 600 / 600 | 1,283,546 | 0 | 315.7, 16 | 0.24681 | 0.3728 | 0.0072 | 0.0237 | 0.1533 |
| g4 (rans_probe4) | coarse | 6 (0) | 600 / 600 | 316,022 | 0 | 166.8, 6 | 0.25817 | 0.3899 | 0.0051 | 0.0106 | 0.0721 |
| g4 | fine | 7 (1) | 600 / 600 | 1,283,595 | 0 | 700.5, 6 | 0.24669 | 0.3726 | 0.0077 | 0.0235 | 0.1597 |

| job | pair (levels) | refinement ratio | GCI | cd (fine) | cd / cd_hangar (0.3014) | total seconds, cores |
|---|---|---|---|---|---|---|
| g1 | 5 / 6 | 1.427 | 0.243 | 0.3900 | 1.294 | 448.2, 6 |
| g2 | 6 / 7, 1500 it | 1.596 | 0.0904 | 0.3715 | 1.233 | 992.0, 16 |
| g3 | 6 / 7, 600 it | 1.595 | 0.0849 | 0.3728 | 1.237 | 405.1, 16 |
| g4 | 6 / 7, 600 it | 1.596 | 0.0903 | 0.3726 | 1.236 | 867.3, 6 |

Step 4 (same setting on 6 cores): the 1500-iteration run on 16 cores took 16.5 min, not under 15, so only the 600-iteration setting was timed on 6 cores (g4). A 1500-iteration run on 6 cores was not run; by scaling g4 (level 7 solve 643 s for 600 iterations) it would be roughly 2,000 s or more, over the 30-minute line, and that is an extrapolation, not a measurement. Cores: 16 cores gave 2.2x fewer total seconds than 6 for level 7 at 600 iterations (315.7 s against 700.5 s), 2.2x on the 1500 level-6 case (179 s against 398 s solve).

### What the logs showed (step 1; g1 case dirs)
- Why the coarse grid stopped at 146 iterations: `log.simpleFoam.x-z5.29` ends "SIMPLE solution converged in 146 iterations". The `residualControl` in `cfd.external` is p 1e-5, U 1e-6, k and omega 1e-6; at iteration 146 the largest initial residual is Uy 6.1e-7 (Ux 1.5e-8, Uz 2.7e-8, p 1.0e-7, omega 8.7e-9, k 9.9e-9), so all five fields are under their limit. The drag is flat to 5 digits from about iteration 85 (0.23655).
- The fine grid (level 6) never meets those limits. Initial residuals at iterations 250 to 1500 stay at Ux 3e-5 to 5e-5, Uy 3e-3 to 1e-2, p 7e-6 to 1.2e-5, k 1.4e-5 to 2.7e-5, with no downward trend. It stops only at the 1500 cap.
- Fine-grid drag (level 6) is not drifting and not a clean oscillation. Per 150-iteration block the mean is 0.2577 to 0.2587 and the std 0.0011 to 0.0022 from iteration 151 on; over the last 300 iterations (what `tail_stats` uses) the slope is +0.00009 N per 100 iterations on a mean of 0.2582 and the std is 0.00128 N (0.5 %). A periodogram of the detrended tail has no dominant period (top peaks 43, 21 and 20 iterations at 16, 13 and 8 % of the spectrum); the drag changes direction at 31 of 298 steps. So: a small irregular unsteadiness, not a shedding cycle with an amplitude to average out. The old "scatter 0.084" was the lift std (0.0215 N on 0.806 N) entering the norm; the drag direction carries 0.0012 N std from x and 0.0215 x sin 5.29 deg from z.
- The same holds at levels 6 and 7 in g2: the mean of the last 20 % if the run had stopped at iteration 300, 500, 600, 800, 1000, 1500 is 0.2579, 0.2574, 0.2577, 0.2575, 0.2573, 0.2575 (level 6) and 0.2462, 0.2463, 0.2468, 0.2463, 0.2470, 0.2460 (level 7). The drag is settled by iteration 300 to within 0.3 %; the 1500 cap is mostly wasted time.
- The 12 mm plate, level 5 (14.06 mm cell, 0.85 cell across the plate): `snappyHexMesh` found 1234 non-manifold points at the first snap step (levels 6 and 7: 8 and 10), added the layers on 97.5 % of the 7,608 body faces (levels 6 and 7: 98.3 % of 30,656 and 99.99 % of 121,640 faces), with 2.78 of the 3 layers achieved on average (levels 6 and 7: 2.88 and 2.94) at 91.2 % of the target thickness (95.6 % and 97.6 %). Layer addition ran 6 iterations on level 5 against 1 on level 6 (level 7 not counted). `checkMesh` says "Mesh OK" on all three (max non-orthogonality 61.9, 61.0 and 62.1 deg; max skewness 1.59, 0.99, 0.99). So the 14 mm grid meshes the plate, but with sub-cell thickness it is a rougher geometry; level 6 has 1.7 cells across it and level 7 has 3.4.

### What the extra experiment shows about the result
- GCI 0.085 to 0.090 passes 0.10 on 3 of 3 runs, and the scatter, ratio and mesh-check conditions pass.
- It is a thin pass. The drag is not monotone in the cell size: 0.2366 (level 5), 0.2575 (level 6), 0.2460 (level 7). The two-grid GCI assumes order 2 and a monotone approach; the three levels show an oscillating one, so the 0.09 is not evidence of the asymptotic range. Between repeats of the same level-6 case the drag moved by 0.3 % (0.2582 in g1 and g4, 0.2575 and 0.2576 in g2 and g3, a different domain split each time), which moves the GCI by about 0.006 (the limit 0.10 corresponds to a level 6 to 7 drag difference of 0.0127 N; measured 0.0108 to 0.0115).
- cd / cd_hangar is 1.23 to 1.24 at levels 6 and 7 (1.29 at levels 5 and 6): the RANS drag stays about 23 % above the hangar model; that gap is not closed by refining.
- The bound (sum |d_i| force_std_i / drag) is a worst case that adds the x and z deviations as if perfectly correlated. It is 0.0143 at 1500 iterations on level 7 but 0.0235 to 0.0237 at 600, because the lift std on the shorter 120-iteration window is larger (z std 0.0376 and 0.0392 N against 0.0230 N); the true std of the drag over the same window is 0.0072 to 0.0077, far under 0.02.

### Recommendation for a product part
- `level_offset` pair (0, 1), the iteration count of the time budget below, and the true tail std of the projected drag (not the norm of `force_std`) as the scatter figure.
- 1500 iterations (the `cfd.external` default, no change): 992 s on 16 cores, both scatter figures pass (bound 0.0143, true 0.0050), GCI 0.0904. Not measured on 6 cores.
- 600 iterations: 405 s on 16 cores and 867 s on 6 cores, true scatter 0.0051 and 0.0072 to 0.0077 (passes 0.02); the bound figure fails (0.0235) so use the true std. GCI 0.085 to 0.090. This is the setting for the 6-core pipeline.
- Do not use level offset -1 as the coarse grid: GCI 0.243 at its pair, plate under one cell.

### What is still wrong, and what to try next
- The thin GCI margin and the non-monotone drag (above). To settle it: one level-8 run (cells would be about 8 M, over `maxGlobalCells` 6,000,000 in `cfd.py`, so a refinement box is needed first) or a Richardson study with three levels 5, 6, 7 using the finer pair for p. Not run: out of scope for four runs and it needs a cell cap change.
- The residuals do not converge, so the SIMPLE stop never fires above level 5; the iteration count is the only control. If a product part needs "converged" it needs a drag-stationarity stop (mean of two windows within a tolerance) instead of `residualControl`; that is a product decision.
- The 1500-iteration run on 6 cores was not measured.
- cd / cd_hangar 1.23 stays; this probe does not say which of the two is wrong.

### Script and test change
`rans_probe.py`: `--levels A B` (default -1 0; A < B or exit), `--iters N` (default 1500, passed as `iters=` to `cfd.external`; the cap is recorded per grid as `iterations_cap`, and in `info.json` with `levels`), per grid `scatter` (old norm, unchanged), `scatter_drag_bound`, and from `postProcessing/forces` `drag_tail_mean_n`, `drag_tail_std_n`, `drag_tail_std_rel`, `tail_iterations`, `history_iterations` (`drag_history`, empty when the case has no force file); `level_offset` per grid. New test `test_the_drag_bound_and_the_history_of_a_case` in `tests/test_wo_cfdprobe.py`. On orca: `ruff check cafe/pm tests review/workorder/rans_probe.py` clean; `tests/test_wo_cfdprobe.py` 3 passed. The new test fails on the old script (no `scatter_drag_bound`, no `drag_history`).
Directories created on orca, all mine: `runs/rans_probe2`, `rans_probe3`, `rans_probe4` (4 MB each after `_shrink`) and `~/cafe-worker/cafe/pm_wo_cfdprobe`; the temporary helper scripts I copied to `~/cafe-worker` were removed. No job of another builder was touched.
