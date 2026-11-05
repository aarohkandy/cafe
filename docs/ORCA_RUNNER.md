# Running cafe jobs on orca (proot)

Orca has no docker, so `PM_RUNTIME=proot` makes `bin/pmx.sh` and `pm.sh` run the same job in the cafe-pm root filesystem under proot (`bin/proot_run.sh`). Without it nothing changes.
The worker setup (`bin/orca_setup.sh`, `docs/orca/README.md`) is a separate piece of work. Nothing here contacts orca until the commands below are run.

## Go (about a minute of the owner's part, then the copy)

1. Owner: run `bash orca_setup.sh` on orca, open the login link, add the `cafe-orca` entry to `~/.ssh/config` (`docs/orca/README.md`, "Connect").
2. `sh bin/orca_sync.sh <orca tailnet IP>` copies proot, the root filesystem (the cafe-pm image, flattened) and the data (about 18 GB) from homebase, through pipes. Run it again to resume a cut copy.
3. `PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=30 PMX=pm_<you> bin/pmx.sh python -c "import cafe.pm; print('ok')"` proves the path. `TM=<name>` runs detached in tmux, as on the burst VM.

## What is not the same as docker

- `PM_MEM` and `PM_SHM` are not enforced, and `PM_CPUS` only sets `CAFE_WORKERS` (there is no `--cpus`). `/work` is writable.
- Kernel 5.10 and orca's cgroup (32 CPUs, 256 GiB, 64 MB `/dev/shm`) are the real limits; the temp directory is `~/work/cafe/tmp/run.*` on the big disk, removed after the run.
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
