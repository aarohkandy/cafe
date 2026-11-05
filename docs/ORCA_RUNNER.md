# Running cafe jobs on orca (proot)

Orca has no docker, so `PM_RUNTIME=proot` makes `bin/pmx.sh` and `pm.sh` run the same job in the cafe-pm root filesystem under proot (`bin/proot_run.sh`). Without it nothing changes.
The worker setup is `bin/orca_setup.sh` (`docs/orca/README.md`). Nothing here contacts orca until the commands below are run.

Orca is shared, maybe on one account, so everything of ours stays inside `~/cafe-worker`: `~/cafe-worker/cafe` stands for `~/work/cafe`, `~/cafe-worker/logs` for `~/logs` (tmux's socket too). `bin/pmx.sh` and `pm.sh` refuse without the folder's owner marker and take plain `PMX` and `TM` names only, so `rsync --delete` cannot reach outside; a job refuses to start with under 60 GB free on the shared disk.

## Go (about a minute of the owner's part, then the copy)

1. Owner: run `bash orca_setup.sh` on orca, open the login link, add the `cafe-orca` entry to `~/.ssh/config` (`docs/orca/README.md`, "Connect").
2. `sh bin/orca_sync.sh <orca tailnet IP>` copies proot, the root filesystem (the cafe-pm image, flattened) and the data (about 18 GB) from homebase, through pipes. Run it again to resume a cut copy.
3. `PM_HOST=cafe-orca sh bin/orca_ready.sh` is the go check, on 2 CPUs, about 5 min: the worker is complete, a job runs, parallel OpenFOAM works, what the code sees of orca's CPUs and memory, how busy the machine is, and nothing changed outside `~/cafe-worker`. It ends `orca-ready`.
4. After the owner's go: `PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=<n> PMX=pm_<you> TM=<name> bin/pmx.sh <cmd>`, as on the burst VM. Choose `<n>` from the load the check printed.
5. The whole suite (arguments are split on spaces, so `-m "not network"` cannot be typed to `pmx.sh`; the script holds it): `PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=30 PMX=pm_<you> TM=<name> bin/pmx.sh sh bin/orca_suite.sh --junitxml=/data/junit.xml`. It is `python -m pytest -n 12 --dist loadfile -m "not network"` plus your arguments (a later `-n` wins); about 41 min in the rehearsal.

## Stopping a job

`ssh cafe-orca 'TMUX_TMPDIR=$HOME/cafe-worker/logs cafe-worker/env/bin/tmux kill-session -t <name>'` (or a TERM, INT or HUP to the `proot_run.sh` process) stops the job and removes its temp directory: TERM to the whole job, KILL after 10 s, as `docker stop` does. `kill -9` on the wrapper does not: the job keeps running under proot (find it with `ps -ef | grep cafe-worker/bin/proot`, stop it with `kill -TERM -<its pid>`, a process-group kill), and its `~/cafe-worker/cafe/tmp/run.*` directory stays until the next `proot_run.sh` start sweeps it, once the job has ended. The same goes for an orca restart. The sweep assumes one container at a time uses this home (it reads the pids in `run.*/.pids`).

## What is not the same as docker

- `PM_MEM` and `PM_SHM` are not enforced, and `PM_CPUS` only sets `CAFE_WORKERS` (there is no `--cpus`). `/work` is writable.
- Memory is unguarded. Under docker `CAFE_WORKERS` is unset and the planner cuts the workers to what the cgroup memory holds; here `CAFE_WORKERS` is set, which `cafe/pm/budget.py` reads as an explicit choice: no memory cut, only a note in the plan when memory is short. So `PM_CPUS` must keep the sum over all running jobs at 32 or below (orca's cgroup), and the memory of all jobs together under 256 GiB is yours to watch; `proot_run.sh` warns when `PM_CPUS` is above 32. Whether `par.memory_gb()` reads orca's cgroup through proot (`/sys` is the host's) was not checked.
- Kernel 5.10 and orca's cgroup (32 CPUs, 256 GiB, 64 MB `/dev/shm`) are the real limits; the temp directory is `~/cafe-worker/cafe/tmp/run.*` on the big disk, removed after the run.
- Open MPI runs with `PMIX_MCA_gds=hash`: without it every `mpirun` aborts at start under proot (rehearsed). If ranks later die with "Read -1, expected" add `OMPI_MCA_btl_vader_single_copy_mechanism=none`; the rehearsal did not need it.

## Rehearsal, 2026-11-05 (burst VM, no orca)

A container with orca's limits (ubuntu:22.04, `-u 5337:1000`, unnamed gid, `--shm-size 64m`, `--cpus 14`, `--cap-drop ALL`, default seccomp, no docker socket, `HOME=/home/jovyan` on a volume, no gcc, no `unshare`) got the root filesystem and data from `bin/orca_sync.sh`; jobs went through `bin/pmx.sh` with `PM_RUNTIME=proot`. Code: `premission-step4` at 0bcf88e plus this branch.

| | docker (burst VM) | proot (container) |
|---|---|---|
| whole suite, `-n 12 --dist loadfile -m "not network"`, 2,598 tests | 2,426 s, 2,597 pass | 2,475 s, 2,597 pass (+2 %; summed test time +23 %) |
| `run --budget ci` of the demo mission | 533 s | 665 s (+25 %; ingest 20 s vs 90 s) |
| interFoam, Wigley toy case, 6 ranks, 2 grids | 59 s | 88 s |

- Both suites fail the same one test: `tests/test_whatif.py::test_a_uas_flip_is_answered_without_a_median_track` (the suite and two single reruns under docker, the suite and one rerun under proot); it is not a proot matter.
- Stage-1 and stage-1b `res.pkl` have the same sha-256 under both (941c8a53...); `report.json` differs in 12 leaves, all host name and wall seconds; the verdicts are equal.
- Slowest under proot: tests that start many processes (`tests/test_cli.py`, up to 30x). Compute-bound work is within a few percent.
- Real Bellhop (`/data/bin`), the SITL tests of `tests/test_uas.py`, `test_par.py`, `test_ledger.py`, `test_stage3.py` (including both real-interFoam tests) pass under proot.
- Differs from orca: kernel 7.0 here, 5.10 there (proot's ptrace use was not tried on 5.10); cgroup v2 `--cpus 14` here, 32 CPUs and 256 GiB there; the disk here was shared with other jobs; rsync and tmux came from apt, not `~/cafe-worker/env/bin` (symlinked); the copy ran on one host, so it did not test the homebase to orca hop, `ssh`, or Tailscale.
