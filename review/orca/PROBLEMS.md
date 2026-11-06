# Orca: problems as they appear

Written when each problem is seen, not after the job ends. A line is added at once, even with the cause unknown; it is closed later with what was found.

**Where the evidence is (all on orca, `~/cafe-worker`, except the code):**
- `logs/watch/problems.log` and `snap_*.txt`: written automatically by `bin/orca_watch.sh` the moment a job log gains a failed test, an error line or an `rc=`: log tail, processes, memory, disk.
- `logs/watch/timeline.tsv`: one line a minute: CPUs used, throttling, memory, load, free disk, OOM kills, sessions.
- `logs/<job>.log`: each job's whole output. `cafe/pmdata/junit_91c9777.xml`: the first suite's per-test results.
- `cafe/pmdata/runs/oq9`: the orca demo run. `cafe/pmdata/evidence/q9_burst_08f05d7`: burst's q9 run without the big binaries (same code digest), kept here so the comparison survives deleting the burst VM.

Comparison code: orca at 91c9777, burst at 08f05d7. Only documents differ between the two commits. Orca CPU: Intel Xeon Gold 6526Y (AVX-512). Burst CPU: AMD EPYC 7763 (no AVX-512).

## Open

| # | Seen (UTC) | Problem | Measured | Next check |
|---|---|---|---|---|
| P-1 | 11-05 16:55 | One test failed in the first orca suite, around 44 %. Not named yet: the log has dots only until the end. | `osuite.log` | Read its name from the junit file when the suite ends; rerun it alone; compare with burst. |
| P-11 | 11-05 18:30 | First suite on orca: 2,915 passed, 3 failed, 77.6 min (rehearsal 41 min for 2,598 tests). Failed: `test_orca.py::test_r7_m31_a_failed_part_stops_the_rest_and_keeps_the_finished_ones` (4 jobs ran, limit 3: timing), `test_ingest_fetch.py::test_a_tao_download_is_cached_only_if_it_covers_the_box_and_window_and_every_file_hashes` (a changed file not noticed), `test_glider.py::test_256_members_7_days_in_well_under_a_minute` (405.6 s, limit 45 s). | `logs/osuite.log`, `junit_91c9777.xml` | Rerun each alone. |
| P-12 | 11-05 18:30 | Suspected bottleneck: all 12 test workers share one `proot` process, and proot is single-threaded for every intercepted system call. Signs: only 1.3 to 1.8 CPUs used with 12 workers alive; that `proot` averaged 97 % of one CPU for 36 min; the glider test ran 9 times over its limit. The demo did not show it because its work is mostly computing, not system calls. | `ps` at 17:16, `timeline.tsv` | Measure one proot against several, and check seccomp mode on kernel 5.10. |
| P-13 | 11-05 18:40 | Measured P-12 (`stat` calls per second, orca, seccomp acceleration on): direct 1 process 389,000, 12 processes 1,525,000; one proot 1 process 44,000, 12 processes 76,000; 12 separate proots 293,000. So one proot is the cap: 12 workers get 1.7 times one worker, and 12 proots give 3.9 times one shared proot. The disk is not the main cause (xfs, 66 MB/s synced 4 kB writes, IO pressure 3 %). The rehearsal on kernel 7.0 did not show this. | `scratchpad` bench copied to `pmdata/sysbench.py` | One proot per worker for test runs. |
| P-14 | 11-06 00:24 | Reran P-11's three tests alone: the orca thread test and the glider test pass (load, not code), and the TAO cache test fails again, so that one is not load. Likely a test bug: it sets a file's last byte to 0, which changes nothing if that byte is already 0, and `next(glob)` gives another file on orca's xfs than on burst's ext4. Unconfirmed. | `logs/o3.log` | Confirm; flip the byte instead; sweep for unsorted file listings that could change a result on another file system (orca-go branch). |
| P-15 | 11-06 00:30 | The old-style reading of this log said the suite took 91 min. That was the wait loop's end. The junit file says 77.6 min, started 16:39:57, ended 17:57:33. | `junit_91c9777.xml` | Closed. Quote 77.6 min. |
| P-3 | 11-05 16:58 | Reach-map corners for `glider_eq` moved between burst and orca. No verdict changed. Everything else in the physics agrees to within 1e-7 relative or better. | vertex 8 lat -0.1911 vs -0.1434; vertex 9 lon -169.8566 vs -169.8089 | Find why a last-bit input change moves a corner by 0.048 deg: a tie in a hull or a grid step? If so, say so in the report or break the tie. |
| P-4 | 11-05 16:58 | The emulator did 6 variants on orca and 4 on burst, so row counts and what-if rows differ. The flip search tried different candidates (glider 1 vs 2). The cut depends on wall time by design (M-10). | `emulator/design/variants`, `/vehicles/glider_eq/fix/evaluated` | Confirm no verdict can depend on it; the report must say what ran (M-10 fix). |
| P-5 | 11-05 17:05 | The memory limit the code reads is above the real RAM: the cgroup says 256 GiB (274.9 GB), the machine has 251.6 GiB (270.2 GB). `plan.json` says `workers_by_memory` 295. | `/proc/meminfo`, `plan.json` | `par.memory_gb` should take the smaller of the cgroup limit and `MemTotal`. Matters only near the top. |
| P-6 | 11-05 17:10 | A suite's failures cannot be named while it runs, because `-q` is in `addopts` and xdist prints dots. | `pyproject.toml` | `-vv` in `bin/orca_suite.sh` (the one `-q` cancels one `-v`), and teach `orca_watch.sh` to count `FAILED` lines. |
| P-7 | 11-05 16:58 | The plan on orca uses homebase's `throughput.json`, so planned times are wrong here. | Stage 1 planned 52.7 s, ran 176 s; emulator share 240 s, ran 380 s | `make bench` on orca once it is the main machine. M-9 adds the warning. |
| P-8 | 11-05 16:33 | Free space on the shared disk keeps falling, and not from us: we hold 18 GB. | 685 GB, 568 GB, 459 GB, 458 GB | `timeline.tsv` tracks it. The recorder logs a problem under 100 GB; jobs refuse under 60 GB. Tell the owner if it drops fast. |

## Answered

| # | Seen (UTC) | What | Result |
|---|---|---|---|
| P-2 | 11-05 16:55 | `stage1/res.pkl` differs between burst and orca (332a18f6... vs cbc6a243...). Same code, seed and worker count. | Last-bit floating point differences between the two CPUs, not a bug: 1,389 of the 1,431 differing numbers in `report.json` are within 1e-9 relative, and all vehicle and link verdicts agree. So "same seed, identical report" holds on one machine, not across CPUs. RUNBOOK already limits it to the same machine; say so plainly in `docs/ORCA_RUNNER.md`. `derived.zarr` differs for the same reason (it is rebuilt on each machine). |
| P-9 | 11-05 16:58 | Does proot slow the work? | File-heavy work yes, compute no: ingest 245 s on orca vs 183 s on burst; stage 1 176 s vs 223 s. |
| P-10 | 11-05 16:39 | ORCA_RUNNER says it was not checked whether `par.memory_gb` reads orca's cgroup through proot. | It does: 274.88. See P-5. |
