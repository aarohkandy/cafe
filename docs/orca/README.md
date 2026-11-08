# Running cafe on Orca

Orca is the lab's Jupyter-style container, first reached through the VS Code tunnel `orca-guest-aaroh` and now over Tailscale and SSH as `cafe-orca`. It is the worker for cafe jobs; it replaced the Azure burst VM (`cafetest`, about $1.40/h), whose resource group was deleted on the owner's yes on 2026-11-06.

**Status (updated in review round 11): connected, and cafe jobs run there.** The go check (`bin/orca_ready.sh`) passed on the real machine, and the demo's quick runs (`q10`, `q10lb`, `q11`, `q11la`) and the whole-suite gates ran there. Where things stand is in [`docs/ORCA_RUNNER.md`](../ORCA_RUNNER.md) (how to run, what is not the same as docker, the gate) and `STATUS.md`; this page keeps what was measured about the machine and how to connect.

| Step | State |
|---|---|
| Orca's size, network and tools | Measured with `probe.sh` on 2026-11-04 (table below) |
| `proot` runs a Ubuntu 24.04 system without root | Passed on Orca with `proot_test.sh` |
| `bin/orca_setup.sh` | Run on Orca by the owner, who runs it again when the container restarts |
| Tailscale login and SSH in from outside | Works: the laptop reaches it as `cafe-orca` |
| The real `cafe-pm` image under proot | Runs the demo and the suite (`bin/pmx.sh` with `PM_RUNTIME=proot`) |
| OpenFOAM `interFoam` in parallel under proot | Part of the go check, which passed |
| A runner that works without docker | `PM_RUNTIME=proot` in `bin/pmx.sh` and `pm.sh`; see [`docs/ORCA_RUNNER.md`](../ORCA_RUNNER.md) |
| The whole suite on Orca | `bin/orca_gate.sh`: 3,352 tests at `e06879c`, 3,649 at `4c95c40`, 3,705 at `cacc0c2` (54.6 min with coverage at K=8); the numbers and the timings are in ORCA_RUNNER.md |

## What Orca is

Measured on 2026-11-04 by `probe.sh` and `proot_test.sh`, run by hand in the tunnel terminal.

| | Orca | Burst VM |
|---|---|---|
| CPUs | 32 (`nproc` says 64, `cpu.max` caps it at 32) | 32 |
| RAM | 256 GiB limit, about 200 GB available | 125 GB |
| GPU | None visible | Not used |
| Docker | None; no podman or apptainer either | Yes |
| `unshare -Ur` | Denied, so bubblewrap-style sandboxes are out | Denied |
| Space | 685 GB left on a lab-shared 201 T disk at 100 %; 13 GB on `/` | 41 GB free |
| `/dev/shm` | 64 MB | Set by `--shm-size` |
| Download speed | About 100 MB/s | About 150 MB/s |
| Cost to you | Not checked | About $1.40/h |

Other facts: Ubuntu 22.04, kernel 5.10, user `intern` (uid 5337), `HOME=/home/jovyan`. Installed: `mamba`, `curl`, `wget`. Missing: `tmux`, `rsync`, `sshd`, `make`, `gcc`. Outbound HTTPS reaches Tailscale, GitHub, conda-forge and PyPI.

### What that means for cafe

- **Do not size jobs from `nproc`.** It would start twice as many workers as there are CPUs. Pass 32 explicitly.
- **Keep temp files off `/`.** `/dev/shm` is below `par.py`'s 12 GB minimum, so the shared arrays go to the temp directory, and the demo's are about 9 GB. Point `TMPDIR` at the big disk.
- **Stay small on the shared disk.** It belongs to the lab and is at 100 %. A worker needs about 25 GB.
- **Conda alone is not enough.** The pipeline needs OpenFOAM's `interFoam` and the tested package versions, so a rebuilt environment would not match `cafe-pm`. Run the image itself.

### proot speed on Orca

One run of each, so treat these as rough.

| Work | Direct | Under proot | Cost |
|---|---|---|---|
| Starting 1,000 processes | 233 ms | 614 ms | about 2.6x |
| 2,000 file writes | 11 ms | 47 ms | about 4.3x |
| Pure CPU loop | 1,003 ms | 942 ms | none measurable |

proot adds cost on each operating-system call, so number crunching is unaffected and work that starts many processes or touches many files is slower. Inside proot, set `LC_ALL=C.UTF-8`: `en_US.UTF-8` is missing.

## Connect

Others share this machine, and possibly this account. `orca_setup.sh` keeps everything in `~/cafe-worker`, refuses to start if that folder is not ours or port 2222 is taken, and only ever stops processes whose program lives in that folder. A rehearsal with decoy processes and a planted home folder left every file outside `~/cafe-worker` byte-identical through setup, restart and undo.

Run these in a terminal on Orca. Do not paste the script itself: run it with `bash`.

```bash
curl -fsSL https://raw.githubusercontent.com/aarohkandy/cafe/premission-step4/bin/orca_setup.sh -o /tmp/cafe_orca_setup.sh
```

```bash
bash /tmp/cafe_orca_setup.sh check
```

If it ends with `check: OK`, run the setup, open the login link it prints and approve `orca-cafe`:

```bash
bash /tmp/cafe_orca_setup.sh
```

Run it again after the container restarts; it restarts only our own `sshd` and `tailscaled`.

## How it was brought up (history; every step passed)

1. The image and the data were copied onto Orca, streamed from homebase, whose disk has too little room for a temporary copy (about 18 GB in all: the image is 5 GB, `pmdata` 7.7 GB, `data` 5.4 GB), with `bin/orca_sync.sh`; then the go check `PMX=pm_<you> PM_HOST=cafe-orca sh bin/orca_ready.sh` (default `pm_ready`; use your own `PMX` when another agent may run the check; the last step lists, as a warning, anything else that changed under `~` while it ran, because the account is shared) ([`docs/ORCA_RUNNER.md`](../ORCA_RUNNER.md)).
2. `interFoam` in parallel under proot (the go check runs it). If MPI's fast shared-memory transport fails there, this is where it shows; Open MPI runs with `PMIX_MCA_gds=hash` (ORCA_RUNNER.md).
3. The full suite on Orca: the first run (12 workers under one proot, `bin/orca_suite.sh`) took 77.6 min for 2,918 tests; the one-proot-per-job gate that followed is in ORCA_RUNNER.md.
4. The owner was then asked about deleting `burst-cafetest-rg`, and said yes on 2026-11-06 (`~/az_serv/docs/MONEY.md`).

### Estimated time (made before the setup; for history)

Estimates, not measurements.

| Step | Time |
|---|---|
| Connect (owner's part, including the login link) | About 5 min |
| Runner change | 30 to 60 min |
| Copy 18 GB | 10 min direct, up to about 2.5 h through a Tailscale relay |
| `interFoam` test | About 30 min |
| Full suite | 1 to 2 h; 75 min on 6 CPUs under docker today, with more CPUs but proot's cost here |

**About 3 to 6 hours in all**, most of it waiting. The copy speed is the biggest unknown, and a failure in the `interFoam` test could stop it early.

## Undo

On Orca, `bash /tmp/cafe_orca_setup.sh undo` refuses while a job of ours runs from `~/cafe-worker` (stop it first; sshd's own connection handlers do not count), logs out of Tailscale while tailscaled still runs (a failed logout is printed, not hidden), stops our two processes, waits until both are gone and deletes `~/cafe-worker`, and refuses if that folder is not marked as ours. Then remove the device `orca-cafe` at https://login.tailscale.com/admin/machines.

## The test scripts

Both are safe to repeat. Paste them into the Orca terminal; each runs in a subshell, so errors cannot close it.

- [`probe.sh`](probe.sh): read-only. Shows size, disk, tools and network.
- [`proot_test.sh`](proot_test.sh): downloads `proot` v5.5.0 and a Ubuntu 24.04 base system, stops unless both match their published checksums, times them, and deletes everything.

The checksum for `proot` comes from the project's `SHA256SUMS` on the v5.5.0 GitHub release, and the Ubuntu one from `SHA256SUMS` on cdimage.ubuntu.com.
