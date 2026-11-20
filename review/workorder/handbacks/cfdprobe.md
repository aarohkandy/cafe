# Hand-back: cfdprobe (work order step 3, plan step 0 only)

## What changed
- New `review/workorder/rans_probe.py` (standalone script). No product code, no `cafe/cfd.py` edit, no test, no document edit, no printed sentence in the product.
- Steps: (1) `Context` on the demo mission and the run dir (default `/data/runs/q25`, read only), `PW.glider_vehicle` and `PW.glider_case` for the first glider (`glider_eq`, Seaglider) at its first window, with `PW.track_heading` from the run's `res.pkl`, as `_row` does; (2) union STL by `trimesh.boolean.union(engine="manifold")` of `W.vehicle_mesh` of each shape, watertight check, no shift, to `<out>/glider.stl`; (3) `vb = R @ (v - u_env)`, label `x[+-]z<angle .2f>`, `cfd.dvec` check (also the angle error of the rounded label); (4) `cfd.external` at `level_offset` -1 then 0, `dirs=(label,)`, `cfd._shrink` after each; (5) prints and writes `<out>/result.json` (per grid: level, cells, failed_checks, seconds, solve and mesh seconds, iterations, drag, force, force_std, scatter, cd; summary: `vv.refinement_ratio`, `cfd.gci`, cd on `veh.ref_area`, `cd_hangar`, cd/cd_hangar, total seconds). `result.json` is rewritten after each grid, `info.json` holds the case facts.
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
