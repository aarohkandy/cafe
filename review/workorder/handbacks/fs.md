# Hand-back: hull_fs convergence measurement (branch wo-fs)

Script: `review/workorder/fs_probe.py` (one grid per run; test `tests/test_wo_fs.py`). Case: first USV window of `/data/runs/on1` (speed 0.58986 m/s, L 6.5 m, Fr 0.0739, Re 4.46e6, draft with keel 2.55 m, keel 0.10 m thick, `cd_hangar` 0.05276 on ref area 1.0582 m2), production grid recipe (`cfd.free_surface`, snappy surface level 0, `FS_LTS`), no tank water, no y+ layer sizing. Numbers below are read from `result.json`, `history.csv` and the logs in `cafe-orca:~/cafe-worker/cafe/pmdata/runs/fs_probe_*/` (job logs `~/cafe-worker/logs/fs_*.log`). "R" is the full-hull resistance (half domain x 2), "scatter" is std/mean of the last 20 % of the history (what stage 3 checks against 0.02), "drift" is the relative change between the means of the last two 1,000-iteration blocks.

## Every run (appended after each run finishes)

| run | boxes | cells | iters | cores | mesh s | solve s | cell-updates/s | settled at | R mean N | scatter | drift (1000-blocks) | failed checks | Fz N |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fs_c1 | 1 | 70,585 | 8000 | 6 | 14 | 1,291 | 437,254 | never | 12.865 | 0.591 | 0.0016 | 1 | 18,205 |
| fs_f4 | 4 | 209,085 | 8000 | 6 | 27 | 3,115 | 537,014 | never | 19.725 | 0.253 | 0.0308 | 0 | 19,259 |
| fs_c3 | 3 | 143,605 | 8000 | 6 | 35 | 2,183 | 526,254 | never | 20.907 | 0.314 | 0.0153 | 1 | 18,715 |
| fs_c2 | 2 | 101,615 | 8000 | 6 | 17 | 1,576 | 515,661 | never | 18.408 | 0.404 | 0.0050 | 1 | 18,406 |
| fs_f4nk (no keel) | 4 | 209,236 | 5000 | 6 | 28 | 2,750 | 380,402 | never | 6.293 | 0.726 | 0.0154 | 0 | 18,192 |

Smoke runs before these (coarse grid, 2 cores, 300 and 500 iterations, `--settle` path included) only checked that the script and `dtmb5415._converge` run on this case; not counted.
| fs_f5 | 5 (probe's own 5th box) | 307,003 | 8000 | 6 | 41 | 5,318 | 461,806 | never | 19.855 | 0.161 | 0.0240 | 0 | 19,298 |

Six solver runs, all rc=0 (job logs `fs_c1`, `fs_f4`, `fs_c3`, `fs_f4nk`, `fs_c2`, `fs_f5`). Two ran at once, 6 cores each, on a shared worker (load average 9 to 20), so the seconds carry other people's load. "settled at" is `dtmb5415.unsettled` applied to the history every 250 iterations from 1,000 (the DTMB study's rule: drift, pressure/viscous drift, scatter <= 2 %); it was never met, in any run, because of the scatter. "failed checks" of the coarse grids 1, 2 and 3 are one skewness check (`log.checkMesh`: max skewness 5.68, 6.00 and 5.11 against 4, 8 to 10 faces); 4 and 5 boxes have none (3.63 and 2.16).

## What the histories show (`history.csv`, one row per iteration, from `force.dat`)

R in N, full hull. Means of iteration blocks:

| run | its 250-1000 | its 1000-2000 | its 2000-8000 | std of last 20 % (pressure part) | viscous part, mean (std) | period of the oscillation, iterations | SE of the mean it>2000 (blocks of 250) |
|---|---|---|---|---|---|---|---|
| c1 (1 box) | 12.81 | 12.69 | 12.62 | 7.58 | 3.97 (0.07) | 10 | 0.43 % |
| c2 (2) | 17.90 | 17.97 | 18.13 | 7.41 | 5.62 (0.08) | 11 | 0.96 % |
| c3 (3) | 20.70 | 20.71 | 20.90 | 6.54 | 6.09 (0.05) | 13 | 0.44 % |
| f4 (4) | 19.50 | 19.59 | 19.66 | 4.98 | 6.17 (0.04) | 28 | 0.46 % |
| f5 (5) | 20.02 | 19.86 | 19.94 | 3.20 | 5.28 (0.07) | 24 | 1.24 % |
| f4nk (4, no keel) | not computed | not computed | mean of last 20 % 6.29 | 4.56 | 4.87 (0.03) | 31 | not computed |

1. The mean is settled by iteration 250 to 1,000 on every grid (fine grid: 19.50, 19.59, 19.66). Two thousand iterations give the same R as 8,000 within 0.2 to 2 %; the DTMB study's 6,000 iterations do not carry over to Fr 0.074. The history after the first block is flat, with a fast oscillation on top.
2. The scatter is that oscillation: the pressure force swings by +-5 to 7 N (std) with a period of 10 to 31 iterations, the viscous force is steady (std < 0.1 N), the vertical force std is 0.1 to 0.6 % of its mean. It does not die with iterations (std of the last 20 %: 7.6, 7.4, 6.6, 5.0, 3.2 N for 1 to 5 boxes), it falls only slowly with the grid, and 5 boxes still give 16 % against the 2 % limit.
3. It is not the keel. Without the keel (f4nk) the pressure force has the same oscillation (std 4.56 N on a mean pressure force of 1.43 N), scatter 73 %. The keel carries 13.4 N of the 19.7 N (mean of the last 20 %: 19.725 with, 6.293 without), and the 4-box R is 3.1 times the no-keel R.
4. The mean R is not grid converged either: 12.9, 18.4, 20.9, 19.7, 19.9 N for 1 to 5 boxes (not monotone), while the iterative uncertainty of each mean is 0.4 to 1.2 % (SE over blocks). The disagreement between the coarse grids is discretisation, not noise.
5. y+ on the hull (yPlus function objects, last write): wet-area mean 2,603 (c1), 1,748 (c2), 1,055 (c3), 309 (f4), 196 (f5), 90 (f4nk); min 1.2 to 22.9, max 4,000 to 8,800, against the 30 to 300 the wall function is built for.
6. The LTS logs carry no "Courant Number" lines, only "Flow time scale min/max": f4 min 4.9e-4 s, max 1.0 s (the `maxDeltaT 1` clip), last write 8.0e-3 to 1.0 s; the other runs in `result.json` `courant`.
7. Measured rate: 4.4e5 (1 box), 5.2e5 (2, 3 boxes), 5.4e5 (4), 4.6e5 (5), 3.8e5 (4, no keel, shared box) cell-updates/s at 6 ranks, 2.9 to 3.5 times the 153,199/s that stage 3 prices. Not measured at other core counts.

## Pairs (`fs_probe.py --compare`, which calls `vv.refinement_ratio`, `cfd.gci` and `freesurface.row_fields` as `two_grid` and the row do; GCI on the last-20 % mean R, the value stage 3 uses)

| fine / coarse | r (cells) | R fine, R coarse (N) | relative difference | GCI | r >= 1.3 | GCI <= 0.10 |
|---|---|---|---|---|---|---|
| 4 / 1 (production's pair) | 1.436 | 19.725, 12.865 | 34.8 % | 0.982 | yes | no |
| 4 / 2 | 1.272 | 19.725, 18.408 | 6.7 % | 0.324 | no | no |
| 4 / 3 | 1.133 | 19.725, 20.907 | 6.0 % | 0.632 | no | no |
| 5 / 1 | 1.632 | 19.855, 12.865 | 35.2 % | 0.634 | yes | no |
| 5 / 2 | 1.446 | 19.855, 18.408 | 7.3 % | 0.201 | yes | no |
| 5 / 3 | 1.288 | 19.855, 20.907 | 5.3 % | 0.241 | no (just) | no |
| 5 / 4 | 1.137 | 19.855, 19.725 | 0.65 % | 0.067 | no | yes |
| 3 / 1 | 1.267 | 20.907, 12.865 | 38.5 % | 1.905 | no | no |
| 3 / 2 | 1.122 | 20.907, 18.408 | 12.0 % | 1.383 | no | no |
| 2 / 1 | 1.129 | 18.408, 12.865 | 30.1 % | 3.285 | no | no |

With production's formula (Fs = 3, p = 2) a GCI of 0.10 at r = 1.436 allows 3.5 % between the grids, at r = 1.446 about 3.6 %; at 4 boxes against any grid of at most 2 boxes the count-based ratio stays under 1.3 (a coarse grid of at most 95,170 cells, i.e. only the 1-box grid, which is 35 % off). No pair passes all three checks. The one pair that passes the GCI number, 5/4, fails the ratio and its fine member fails the scatter (a GCI at r = 1.14 is not meaningful by the check's own note). On the mean over iterations > 2,000 instead of the last 20 %, the same pairs give 5/4 0.143, 5/2 0.249, 4/1 1.011, 4/2 0.377 (the 5-box mean has an SE of 1.2 %, comparable to its 0.65 to 1.4 % difference from the 4-box).

## cd against cd_hangar (production's formula, `freesurface.row_fields`)

cd_hangar = 0.05276 (ref area 1.0582 m2, density of the case). Fine-grid cd: 4 boxes 0.10473 (1.985 x cd_hangar, added resistance +98.5 %), 5 boxes 0.10542 (1.998 x, +99.8 %); the pair 5/2 (best pair with r >= 1.3 and the lowest GCI, 0.20) gives cd 0.1054; the production pair 4/1 gives 0.1047. The CFD resistance is twice the hangar number on every fine grid and stable (4 to 5 boxes differ by 0.65 %), so this is a model difference, not iteration noise; the keel alone is 13.4 N in the CFD. The no-keel run's cd (0.0334, 0.63 x) is not comparable with cd_hangar. Why the hangar number is half was not investigated.

## Recommendation

Nothing passes: fs_iterative_scatter fails by 8 to 36 times its limit (16 % at best, 5 boxes; 25 % at the 4-box production fine grid; limit 2 %) and fs_gci by 2 to 10 times (best pair with r >= 1.3: 5/2 at 0.20; production's 4/1 at 0.98; limit 0.10). Neither is cured by more iterations or a longer run. What the numbers do support:

- Iterations: 2,000 are enough for the mean here (4-box R 19.66 N over its 1000-2000 and over 2000-8000; the first 250 are a start-up transient, 24 N). The `--settle` loop would run to its cap on every grid (the scatter never meets 2 %) so it saves nothing; it ran correctly on the 1-box grid for two chunks (500 iterations, `converged` False, scatter 0.367, drift 0.0007) and was not run further.
- Cost at the measured rate (computed from the measured cell-updates/s, not run): 1 box about 320 s and 4 boxes about 775 s at 2,000 iterations on 6 ranks; at 8,000 iterations the runs took 1,305 s (1 box), 1,593 s (2), 2,218 s (3), 3,142 s (4), 5,359 s (5) including 14 to 41 s of meshing. The pair 4/1 run one after the other (as `two_grid` does) is 4,447 s at 8,000 iterations; 5/2 is 6,952 s.
- If the scatter check is kept as written, no iteration or grid change within what was run can pass it. Next, in this order (none run, six runs were the limit):
  1. Find what makes the pressure force oscillate: it is in the pressure part only, with or without the keel, on all grids, with a period of 10 to 31 iterations, so it belongs to the pseudo-time march or the free surface at the hull, not to the keel. Cheapest test: the 1-box grid (320 s per 2,000 iterations) with `FS_LTS` changed in the probe process only (smaller maxCo and maxAlphaCo, larger rDeltaTSmoothingCoeff; DECISIONS comment at `cfd.py:561-570` says 0.25 scattered by +-40 % and 0.05 was too slow, so 0.1 is already the compromise), then a final stretch with a fixed small deltaT.
  2. Hull wall treatment as in the DTMB study (`dtmb5415.case_recipe`, y+ about 100 layers): production's y+ is 90 to 2,600 on the hull, which may be part of the 12.9 to 20.9 N spread between grids.
  3. If the oscillation stays, the check measures the wrong thing for a quantity whose mean is determined to 0.4 to 1.2 % (SE of the 250-iteration block means over iterations > 2,000, measured above); a check on that standard error, or on the scatter of 250-iteration block means (2.1 to 6.1 % measured, for iterations > 2,000), is a product decision I did not make.
  4. The GCI check needs the mean to move by less than about 3.5 % between grids at r = 1.4; 4 to 5 boxes differ by 0.65 %, 3 to 4 boxes by 6 %. A 5-box fine grid is feasible (307,003 cells, 5,359 s at 6 ranks, 41 s meshing, no failed mesh check) and meshes with the probe's own 5th box (not a product box), but its pair partners are 2 boxes (r 1.446, GCI 0.20) or 1 box (GCI 0.63): the count-based ratio and the 1.3 limit cannot both be met with the 4-box member and a GCI near 0.1.

## Against the diagnosis (`LEAD_HANDOFF/plans/hull_fs_diagnosis.md`)

- Cause 1 (too few iterations): not supported for the mean. R is flat from iteration 250 to 1,000 on all five grids; the DTMB 6,000-iteration need does not transfer to Fr 0.074. The 1,000-iteration last-quarter drift of the DTMB rule never fails on a trend but on the scatter.
- Cause 2 (the GCI is structural): confirmed. 1-box R is 12.9 N against 19.7 N; the 1-box grid also fails a skewness check; the count-based r is 1.436 and 0.35 of difference gives GCI 0.98.
- Cause 3 (the blunt keel causes the scatter): refuted by f4nk (same oscillation without the keel).
- Cause 4 (no y+ sizing): the y+ is out of range everywhere on the hull (above); whether it drives the grid sensitivity is untested.
- File:line: `cfd.py` domain is at 555-561 (not 355-361), `FS_LTS` at 570 (not 545), the snappy layer dictionary at 651-652 (not 601-603); `GRIDS` at `freesurface.py:108`, `ITERS` at `dtmb5415.py:273`, `tail_stats` at `cfd.py:190`, `_control`'s `deltaT 1` at `cfd.py:309`, the keel at `pipeline_windows.py:184` are right. The 4.3e5 cell-updates/s the diagnosis measured is right (4.4 to 5.4e5 here).
- Not reproduced: on1's fine grid had std 9.2 N on 18.92 N (49 %); the same fine grid at 2,000 iterations here gives 19.66 N with scatter 26.7 % (last 20 % of the first 2,000 rows), 1,000 iterations 20.05 N and 32.8 %. I do not know why on1 was worse (the run's code version and the number of ranks differ from this probe's, which uses HEAD).

## What was not verified

- Nothing was run at other core counts (the diagnosis's 12 and 16 rank question is open); two cases at 6 ranks each ran at the same time on a loaded worker.
- The `--settle` path ran for two 250-iteration chunks on the 1-box grid only.
- The 5th box is the probe's own (`EXTRA_BOX`, inside box 4); it is not in `cfd.FS_BOXES`, so production cannot run 5 boxes without a product change. The estimate `freesurface.refined_cells(5)` with that box is 344,562 against 307,003 measured (the 4-box estimate 214,341 against 209,085 measured).
- The vertical force (19,259 N at 4 boxes, 19,298 at 5) was only read, not compared with the displacement.
- Why the oscillation exists (candidates: the pseudo-time march or the interface at the hull's waterline edge) and why the hangar resistance is half of the CFD's.
- No run of the on1 mission through `pipeline_windows` itself; the probe builds the vehicle, STL, draft, speed and heading by the same functions (0.58986 m/s, draft 2.55 m, Fr 0.0739, Re 4.46e6, `info.json`).
- Only one speed, one window, one heading.
- `ruff check cafe/pm tests review/workorder/fs_probe.py`: clean on orca. The test file (5 tests, `tests/test_wo_fs.py`) passes on orca. mypy not run (no `cafe/pm` file changed).

## Where things are (orca, all under `~/cafe-worker`)

`cafe/pmdata/runs/fs_probe_{c1,c2,c3,f4,f5,f4nk}/` (`result.json`, `info.json`, `history.csv`, `case/` logs and `postProcessing`, 16 to 50 MB each), `fs_probe_pair_*/pair.json`; sources `cafe/pm_wo_fs`, `cafe/pm_wo_fs2`; logs `logs/fs_*.log`.
