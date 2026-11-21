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
