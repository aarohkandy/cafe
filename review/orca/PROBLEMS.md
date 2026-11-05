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
