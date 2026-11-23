# Double-body RANS of the demo USV's underwater hull (branch scale-ladder)

Question: can a steady, fully submerged RANS case (`cafe.cfd.external`: snappyHexMesh, simpleFoam, k-omega SST) give the demo USV hull's drag on a CPU, where the free-surface case `hull_fs` never passes its checks?

Short answer. It runs, converges and passes all four checks of the glider part on level offsets 0 and 2 (65 min on 6 cores, 6.6 M cells), and fails the GCI check narrowly (0.109 against 0.10) on the glider's offsets 0 and 1 (15 min, 1.4 M cells). **But the drag it gives is 4.5 times `cd_hangar`** (cd 0.237 against 0.0528), 89 % of it pressure drag, and 2.3 times the free-surface case's unsteady mean (44.8 N against 19.7 N). The grid and the iterations are not the cause (three grids, drag settled, apparent order 2.5). I did not isolate the cause (see "What this leaves out" and "Not verified"); the one candidate I can name is the square-edged keel plate.

Script `review/workorder/usv_rans_probe.py` (tests in `tests/test_wo_ladder.py`, 9 pass; `ruff check cafe/pm tests review/workorder/usv_rans_probe.py` clean on orca). Every number below is from `result.json` / `info.json` and the logs in `cafe-orca:~/cafe-worker/cafe/pmdata/runs/usv_rans_a/` (job log `~/cafe-worker/logs/usvr_1.log`) and `usv_rans_b/` (`usvr_2.log`), or from the code lines named. First USV window of `/data/runs/fin1` (read only): vehicle `usv`, `saildrone_explorer`, window t 1678050000, heading 70.0 deg (stage-1 heading), speed 0.58986 m/s, Fr 0.0739.

## The body, and how its drag maps to cd

- Stage 3's `hull_fs` vehicle (`pipeline_windows.py:186-189`): ellipsoid of semi-axes (3.25, 0.6, 0.45) m centred on the waterline (`hull_draft_m` 0.45), keel plate 0.667 x 0.10 x 2.1 m hanging from its bottom (z -0.45 to -2.55), reference area `ref_area` = frontal = pi (beam/2) draft + keel thickness x span = 1.05823 m2 (`info.json`). `hull_fs` meshes the part below z = 0 (the half ellipsoid and the keel).
- The stage-3 `hull` part's shape is **not** this: it is the full ellipsoid and ONE keel below it, the same vehicle (`usv_vehicle` builds both parts alike), and its Hangar reference is the ellipsoid's own full surface plus the keel (`usv_case`, `pipeline_windows.py:272, 294-296`). It is a closed submerged body, but its drag is (half ellipsoid + keel) + the other half ellipsoid, which is not the underwater hull's. So I did not use it.
- Body run: the waterline plane is a symmetry plane of a double body, so the underwater hull is half of {full ellipsoid + keel below + the keel's mirror image above}. The mirror image of the keel is kept (a plate standing on top of the ellipsoid): without it the body is not symmetric about z = 0 and half its drag is not the hull's (the unmirrored body is what the `hull` part is). Both keels are pushed into the ellipsoid by `freesurface.KEEL_OVERLAP` = 0.25 of the vertical semi-axis, as `freesurface.write_stl` does, so the union is one solid. STL `usv_double.stl`: 1,332 triangles, watertight, extents 6.5 x 1.2 x 5.1 m, area 23.482 m2, volume 3.924 m3.
- Flow: along body +x at |R (v - u_env)| = 0.58986 m/s, as `hull_fs` runs it (`_fs_submit`, `pipeline_windows.py:798-799`). The window has a leeway of -7.86 deg and a heel of 4.21 deg (`info.json`: body velocity (0.5843, 0.0807, 0) m/s); `hull_fs` and this probe both ignore them, so both are an upright, straight-on hull.
- Mapping: `cd_hangar` is "the VPP's whole hull resistance plus the keel" (`pipeline_windows.py:31-32, 282, 288-289`: `_coef(r_hull + r_keel, rho_w, stw, veh.ref_area)`, with `_coef` = F / (rho/2 V^2 A), line 210), the whole underwater hull, not half of it. So the hull's drag is **half the double body's** and `cd = (drag / 2) / (0.5 rho_solver V^2 ref_area)`, with the solver's rho 1025 (the one its force carries; `rans.row_fields`, `rans.py:136-140`, is called on the halved drag and does exactly this); `cd_hangar` uses the case's own rho_water 1023 (ratio 1.0020). The same half is also what `freesurface.row_fields` divides for `hull_fs` (`R / q` on the whole-hull resistance).
- `info.json`: `s_wet_below_m2` = 11.618 m2, the underwater hull's wetted area (faces of the double body with z < 0; the same above, 11.618: symmetric); of that the half ellipsoid is 8.392 m2 (`freesurface.write_stl`'s `wetted_hull_m2`, what `cd_hangar`'s hull term is built on) and the keel with its junction 3.226 m2 (difference).

## Every run (job `usvr_1`: levels 0 1; job `usvr_2`: levels 0 2; 600 iterations each, 6 cores, one job at a time on a worker with load 2 to 7)

Drag columns are the **double body's**, last 20 % mean (120 iterations); the hull's are half. "Scatter" is the drag's own tail std / mean (what the product's `rans_iterative_scatter` reads).

| job | grid | level (offset) | cells | failed mesh checks | iterations | seconds (mesh + solve) | drag N (double) | pressure N | viscous N | scatter | hull drag N (half) | hull cd | cd / cd_hangar |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | coarse | 6 (0) | 350,461 | 0 | 600 | 183.8 (20.5 + 163.2) | 96.283 | 86.311 | 9.972 | 0.00139 | 48.141 | 0.2551 | 4.84 |
| 1 | fine | 7 (1) | 1,411,246 | 0 | 600 | 732.5 (60.1 + 672.4) | 91.223 | 81.189 | 10.035 | 0.00129 | 45.612 | 0.2417 | 4.58 |
| 2 | coarse | 6 (0) | 350,587 | 0 | 600 | 185.2 (20.5 + 164.8) | 96.537 | 86.619 | 9.917 | 0.00200 | 48.268 | 0.2558 | 4.85 |
| 2 | fine | 8 (2) | 6,623,908 | 0 | 600 | 3,742.2 (263.2 + 3,479.0) | 89.507 | 79.335 | 10.173 | 0.00019 | 44.754 | 0.2372 | 4.50 |

(cd / cd_hangar of the two coarse rows is 0.2551 / 0.05276 and 0.2558 / 0.05276; the fine rows' are the files' `cd_over_cd_hangar` 4.581 and 4.495.)

The level-6 grid was run twice (its meshes differ by 126 cells, 350,461 and 350,587) and its drag differs by 0.27 % (96.283, 96.537): the run-to-run noise at this level. Four grid solves were run in all, the limit.

| pair | refinement ratio r = (N_fine/N_coarse)^(1/3) | GCI (`cfd.gci`, Roache, Fs 3, p 2, on the double-body drag) | the four checks of `rans.row_fields` |
|---|---|---|---|
| job 1: levels 0, 1 (the glider's setting) | 1.591 | **0.1087** | GCI 0.1087 > 0.10 **fails**; r 1.591 >= 1.3 ok; scatter 0.00129 <= 0.02 ok; failed mesh checks 0 ok |
| job 2: levels 0, 2 | 2.663 | **0.0387** | all four pass (GCI 0.0387; r 2.663; scatter 0.00019; 0 failed) |

Three grids (levels 6, 7, 8; job 2's level 6, job 1's level 7, job 2's level 8), Celik et al. 2008 (`--three`, Fs 1.25): drags 89.507, 91.223, 96.537 N, r21 = 1.674, r32 = 1.591, **apparent order p = 2.55**, extrapolated drag 88.88 N (hull 44.44 N, cd 0.2355, 4.46 x cd_hangar), the level-8 drag is 0.71 % from the extrapolated value, GCI of the fine pair 0.0088. With job 1's level 6 (96.283 N, 350,461 cells) instead: p = 2.44, extrapolated 88.83 N, GCI 0.0095. The drag falls monotonically with refinement and its order is close to the second order the product's GCI assumes. The 7.3 % drop from level 6 to 8 (96.537 to 89.507 N) is behind the 0.109 of job 1: the product's Fs 3 and p 2 give a GCI of 0.109 for a drag whose level-7 error against the extrapolated value is (91.223 - 88.88) / 88.88 = 2.6 %.

Convergence of the drag with iterations (means of 100-iteration blocks, double body, N): level 7: 95.71, 91.35, 91.33, 91.25, 91.22, 91.22; level 8: 96.32, 89.16, 88.83, 89.50, 89.52, 89.51; level 6 (job 2): 99.19, 96.85, 96.38, 96.43, 96.47, 96.57. Settled by iteration 200 to 300 on every grid. The residuals do not reach `residualControl` (`solution_converged` false in all four; the last initial residuals, level 8: Ux 8.1e-6, Uy 1.5e-3, Uz 1.5e-3, p 7.6e-7, k and omega 1e-5 order; level 7: Uy 0.0136, Uz 0.0163): the iteration cap is the stop, as for the glider.

## y+ on the body

The expected y+ is from the mesh rule: surface cell h = (L/4)/2^level (L = 6.5 m), layers 3, expansion 1.2, final layer 0.5 h (`cfd.EXT_SNAPPY`, `relativeSizes true`), so the first layer is 0.5 h / 1.44 = 0.347 h and its centre 0.174 h up; u_tau = U sqrt(cf / 2) with cf = 0.003690 (ITTC-57 at Re 3.222e6 on L, solver nu 1.19e-6), u_tau 0.02534 m/s. Measured: `simpleFoam -postProcess -func yPlus` on the finished fields (the logs do not carry y+; the function reads the turbulence model, so it has to be run through the solver), patch `body`, and snappyHexMesh's layer tables.

| level | surface cell m | expected y+ of the first cell centre (layers all in) | expected y+ with no layers (cell centre) | measured y+ min / average / max | layers added (target 3; mean added, overall thickness %) | near-wall thickness measured (avg of first layer, m) vs 0.347 h |
|---|---|---|---|---|---|---|
| 6 | 0.02539 | 93.9 | 270.3 | 4.3 (job 2; 2.9 job 1) / 71.6 / 245.9 (256.3 job 1) | 2.84, 94 % | 0.00897 vs 0.00882 |
| 7 | 0.01270 | 46.9 | 135.2 | 1.6 / 38.9 / 112.5 | 2.92, 97 % | 0.00445 vs 0.00441 |
| 8 | 0.00635 | 23.5 | 67.6 | 0.94 / 20.3 / 69.3 | 2.96, 98.4 % | 0.00221 vs 0.00220 |

The mesh rule puts the first cell in 30 to 300 on average for levels 6 and 7 (71.6, 38.9; the minima, 1.6 to 4.3, are at the stagnation points and where the layers collapse). On level 8 the average is 20.3 and the bulk of the wall is below 30. The wall functions in `EXT_FIELDS` are `nutUSpaldingWallFunction` and `omegaWallFunction`, which blend the viscous and log layers and are defined down to y+ of order 1, so I take y+ 20 to 70 as not invalidating the level-8 case, but I did not test that (no run with a different wall treatment). The measured averages are 0.76, 0.83 and 0.87 of the expected centres of full layers.

## Reference numbers

- cd_hangar 0.05276 (`info.json`: 0.05275953, ref area 1.05823 m2); the same in newtons at the case's rho and speed: 9.936 N (`result.json` summary `hangar_drag_n`). Its source string (`info.json`): `usv.hull_resistance` (ITTC-57 friction x (1 + form_factor_k 0.20) + the residuary term) on the wetted area plus the keel's friction/profile drag at zero leeway, rudder and appendages excluded.
- CFD, finest grid: hull drag 44.754 N, cd 0.23716, **4.495 x cd_hangar** (added resistance +350 %); extrapolated (three grids) 44.44 N, cd 0.2355, 4.46 x. Job 1's pair (0, 1): cd 0.2417, 4.581 x.
- Free-surface case (`handbacks/fs.md`): unsteady mean 19.725 N for the 4-box grid (19.855 for 5 boxes), cd 0.10473 (1.985 x cd_hangar). The double body's 44.754 N is 2.27 x that. The fs case's own numbers have problems (scatter 16 to 25 %, GCI 0.2 to 1.0, y+ 90 to 2,600 on the hull); fs.md's keel-less run gave 6.293 N, i.e. 13.4 N for the keel there.
- Friction only, flat plate of the underwater hull's wetted area at the ITTC-57 line: cf at Re 3.222e6 (solver nu) = 0.003690, at Re 4.458e6 (the Hangar's nu_water 8.6e-7) = 0.003470; S_wet = 11.618 m2; cf S_wet / A_ref = **0.04052** (solver Re; 7.65 N at the solver's q 188.7 N, from hull drag / cd) and 0.03809 (Hangar Re). The CFD cd is 5.85 x the first (`form_factor_ittc57_re_solver` 5.854); `cd_hangar` is 1.385 x the second (0.05276 / 0.03809; the 1.2 form factor on the hull plus the keel's profile term and the residuary). The CFD's viscous part alone is 5.086 N for the hull (0.02695 in cd), 0.67 of the flat-plate friction at the same Re; I do not know why it is below it (the plate's local Re, the wall function, the short keel chord all go in different directions; not examined).
- So the CFD drag is almost all pressure: hull pressure part 39.67 N of 44.75 N (88.6 %) on level 8, 40.59 of 45.61 N (89.0 %) on level 7. The Hangar model has no term of that size: its form factor is 0.2 on the hull and 1.33 (1 + 2 t/c + 60 (t/c)^4, t/c 0.15) on the keel friction.

## What this model leaves out

- Waves and the free surface's effect on the pressure field: the waterline is a rigid symmetry plane. At Fr 0.074 the wave resistance is small (the Hangar's residuary term `cr0 (Fr/0.35)^4`), but a free surface also changes the pressure field near the top of the hull and the keel root compared with a rigid lid; not quantified here.
- The keel's mirror image: it is needed for the symmetry, but the real keel has no image; by symmetry the flow on the waterline plane has no normal velocity, which is what the rigid lid is, so the half below sees a rigid lid, if the steady solution stays symmetric (job 1's force on the double body: z component 0.095 N coarse and 0.25 N fine against drags of 96.3 and 91.2 N, y component -0.85 and -0.73 N, from `force_n`: no sign that it does not). It was not tested against a lid-free run or a half-domain symmetry-plane run (cfd.external has no symmetry-plane option, so I cannot run the half body in the same code path).
- Leeway (-7.86 deg) and heel (4.21 deg) of the window, sinkage and trim: ignored, as in `hull_fs`. The keel at leeway carries side force and induced drag; the Hangar's keel term is at zero leeway.
- Displacement: `hull_fs`'s hull displaces 1.98 m3 (2,023 kg) against the platform's 0.73 m3 (750 kg), 2.7 x (`info.json` `wetted_area_note`; `config/assumptions.yaml` `stage3.usv.hull_draft_m`). The double body is the same geometry, so the 2.7 x mismatch is in the CFD, not in the Hangar side; `cd_hangar` is built on the window's own wetted area (8.39 m2 against the platform's 6.5), not on that displacement. The wetted area of the keel in the CFD (3.226 m2 with the junction) and the Hangar's keel area are not the same quantity; I did not compare them.
- A square-edged keel: `vehicle_mesh` makes the keel a box 0.667 x 0.10 x 2.1 m, with blunt leading and trailing edges and a flat tip; the Hangar's keel term is a foil's friction and profile drag (t/c 0.15). A blunt plate's pressure drag at this Re would be the first thing I would look at for the 89 % pressure share (the fs case, which has the same box, also found the keel carrying 13.4 of 19.7 N). I did not run a keel-less or foil-shaped keel here, so this is a candidate, not a finding.
- A steady RANS of a blunt body: the wake of the flat keel tip and trailing edge sheds in reality; the steady solution is one state of it (drag tail scatter 0.02 to 0.2 %, no sign of unsteadiness in the steady solver).

## Recommendation for a product part `hull_rans`

- It works as a part: the same child-process structure as `body_rans`, one STL from `double_body_shapes` (hull, keel pushed in, mirrored keel; watertight), flow `+x` at the window's through-water speed, `rans.row_fields` on the **half** of the fine grid's drag (and std), `cd_hangar` from `usv_case(.., "hull_fs", wetted)` as the fs part, ref area `usv_vehicle`'s `ref_area`. All four checks are the glider part's, unchanged.
- Setting: 600 iterations (the drag is settled by 200 to 300). Level offsets **0 and 2** pass all four checks (GCI 0.039, r 2.66, scatter 0.0002, 0 failed) at 3,927 s on 6 cores and 6.6 M cells (castellation stopped at 5.83 M cells, under `maxGlobalCells` 6 M but not far; `maxLocalCells` 2 M is per rank; memory not measured). Offsets 0 and 1 (the glider's) take 916 s and fail the GCI at 0.109 only. Offsets 1 and 2 would give r 1.67 and, with the drags here (91.22 and 89.51 N), a product-formula GCI I did not compute (the Celik GCI of that pair at p 2.55 is 0.0088); they cost about 4,400 s (672 + 3,479 s of solving plus meshing) and were not run (the four-run limit).
- Whether to ship it is not a question of the numbers converging, which they do, but of cd = 4.5 x cd_hangar. A `hull_rans` row would hand the refit a multiplier of 4.5 on the hull's hangar drag, 89 % of it pressure drag from a geometry whose keel is a flat plate with square edges. If that is the real hull (a box keel), the Hangar underestimates the drag by 35 N at this speed; if the keel is a foil, this row measures the wrong body. The product decision needs the keel's real shape, or one run with a foil-shaped keel (and one without) to see how much of the 44.75 N is the keel; neither was run.

## Not verified

- The cause of the 4.5 x: not isolated (no run without the keel, with a rounded keel, at a different speed, or with a different turbulence model or wall treatment). The keel-edge explanation is a candidate only.
- That the double body is the same as the underwater hull with a free surface: no check against a lid or a symmetry-plane half domain, and the fs case is not a reference (it does not converge).
- Run-to-run noise beyond the one repeat of level 6 (0.27 %); no repeat of level 7 or 8.
- Wall treatment: y+ 20 to 70 average on level 8 with the blending wall functions; not compared with another treatment.
- Memory of the level-8 case: not measured (the job ran under `PM_MEM=24g` and finished).
- The Hangar's own parts (hull friction, form, residuary, keel): `cd_hangar` is one number from `usv_case`; I did not split it.
- Only one window, one speed (0.59 m/s), one heading; the code was not run through `pipeline_windows` itself (the probe builds the vehicle, speed and heading with the same functions, as `fs_probe.py` does).
- mypy not run (no `cafe/pm` file changed). Smoke runs (coarse levels, 20 to 30 iterations, 2 cores) checked the script only and are not counted; their directories are deleted.

## Where things are (orca, under `~/cafe-worker`)

`cafe/pmdata/runs/usv_rans_a/` and `usv_rans_b/` (`result.json`, `info.json`, `usv_double.stl`, `hull_fs_reference.stl`, `coarse/` and `fine/` logs and `postProcessing`, 15 and 46 MB), job logs `logs/usvr_1.log`, `logs/usvr_2.log`; source `cafe/pm_sl_usv`.
