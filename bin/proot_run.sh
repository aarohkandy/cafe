#!/bin/sh
# What `docker run ... cafe-pm <cmd>` in bin/pmx.sh does, for a worker with no docker (orca): the cafe-pm root filesystem under proot, same mounts, same environment.
# Runs ON the worker, started by bin/pmx.sh or bin/pm.sh when PM_RUNTIME=proot:   sh proot_run.sh <dir under ~/work/cafe that becomes /app> <command and arguments>
# The root filesystem and proot come from bin/orca_sync.sh. Not enforced here, unlike docker: PM_MEM and PM_SHM, and --cpus (PM_CPUS only sets CAFE_WORKERS), and /work being read-only.
set -eu
D="$1"; shift
W="$HOME/cafe-worker"; C="$HOME/work/cafe"
[ -x "$W/bin/proot" ] && [ -x "$W/root/usr/bin/env" ] || { echo "no proot or root filesystem under $W: run bin/orca_sync.sh" >&2; exit 1; }
[ -d "$C/$D" ] && [ -d "$C/pmdata" ] && [ -d "$C/data" ] || { echo "missing $C/$D, $C/pmdata or $C/data: run bin/orca_sync.sh" >&2; exit 1; }
mkdir -p "$C/tmp"
T=$(mktemp -d "$C/tmp/run.XXXXXX")                 # the container's /tmp, on the big disk (/ has 13 GB on orca); gone after the run, as with --rm
trap 'rm -rf "$T"' EXIT; trap 'exit 143' INT TERM HUP
export PROOT_TMP_DIR="$T"
ulimit -c 0                                        # --ulimit core=0
B=; for f in /etc/resolv.conf /etc/hosts; do [ -e "$f" ] && B="$B -b $f"; done
# env -i: the image's own environment (docker inspect cafe-pm) plus the -e flags of the docker runner; nothing of the host's leaks in.
# LC_ALL: en_US.UTF-8 is missing in the image. PMIX_MCA_gds=hash: under proot Open MPI's PMIx shared-memory store fails at MPI_Init (PMIX_ERR_NOT_AVAILABLE in gds_shmem.c) and every
# mpirun, so OpenFOAM's meshing and solving in parallel, aborts; docker with the same 64 MB /dev/shm is fine, so it is proot, not the small shm. (Not needed: btl_vader_single_copy_mechanism.)
# shellcheck disable=SC2086
"$W/bin/proot" -r "$W/root" -i "$(id -u):$(id -g)" -w /app -b /dev -b /proc -b /sys $B \
  -b "$T:/tmp" -b "$C/$D:/app" -b "$C/pmdata:/data" -b "$C/data:/work" \
  /usr/bin/env -i PATH=/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONUNBUFFERED=1 HOME=/tmp TMPDIR=/tmp LC_ALL=C.UTF-8 \
  PYTHONPATH=/app CAFE_DATA=/data CAFE_GIT_SHA="${CAFE_GIT_SHA:-}" CAFE_GIT_DIRTY="${CAFE_GIT_DIRTY:-0}" CAFE_WORKERS="${PM_CPUS:-8}" \
  PMIX_MCA_gds=hash "$@"
