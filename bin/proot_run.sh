#!/bin/sh
# What `docker run ... cafe-pm <cmd>` in bin/pmx.sh does, for a worker with no docker (orca): the cafe-pm root filesystem under proot, same mounts, same environment.
# Runs ON the worker, started by bin/pmx.sh or bin/pm.sh when PM_RUNTIME=proot:   sh proot_run.sh <dir under ~/cafe-worker/cafe that becomes /app> <command and arguments>
# The root filesystem and proot come from bin/orca_sync.sh. Not enforced here, unlike docker: PM_MEM and PM_SHM, and --cpus (PM_CPUS only sets CAFE_WORKERS), and /work being read-only.
set -eu
D="$1"; shift
GRACE="${PM_STOP_GRACE:-10}"; case "$GRACE" in ''|*[!0-9]*) echo "PM_STOP_GRACE: whole seconds (default 10), not '$GRACE'" >&2; exit 2 ;; esac       # seconds between TERM and KILL when the job is stopped
W="$HOME/cafe-worker"; C="$W/cafe"          # nothing outside ~/cafe-worker: the home folder is shared
[ -x "$W/bin/proot" ] && [ -f "$W/root.done" ] && [ -x "$W/root/usr/bin/env" ] || { echo "no proot or root filesystem under $W: run bin/orca_sync.sh" >&2; exit 1; }
[ -d "$C/$D" ] && [ -d "$C/pmdata" ] && [ -d "$C/data" ] || { echo "missing $C/$D, $C/pmdata or $C/data: run bin/orca_sync.sh" >&2; exit 1; }
[ "${PM_CPUS:-8}" -le 32 ] || echo "warning: PM_CPUS=${PM_CPUS} is above orca's 32 CPUs; the sum over all running jobs must stay at 32 or below, nothing here limits it" >&2
free=$(df -Pk "$W" | awk 'NR==2{print int($4/1048576)}'); [ "$free" -ge "${CAFE_MIN_FREE_GB:-60}" ] || { echo "STOP: only $free GB free on the shared disk" >&2; exit 1; }
mkdir -p "$C/tmp"
# A run that was SIGKILLed (or lost to a container restart) leaves its run.* directory: each holds .pids (this wrapper, then its proot); one with no live pid is stale. Not a stale one without .pids: that is a run just starting.
for d in "$C"/tmp/run.*; do
  [ -f "$d/.pids" ] || continue; live=
  for p in $(cat "$d/.pids"); do kill -0 "$p" 2>/dev/null && live=1; done
  [ -n "$live" ] || rm -rf "$d"
done
T=$(mktemp -d "$C/tmp/run.XXXXXX"); echo $$ > "$T/.pids"      # the container's /tmp, on the big disk (/ has 13 GB on orca); gone after the run, as with --rm
# The job runs in the background, in its own process group (setsid), so that a signal to this wrapper stops it at once: proot itself ignores SIGTERM and dies of SIGKILL
# without its tracees. The handler sends TERM to the group and KILL after PM_STOP_GRACE (10) s, as docker stop does. A SIGKILLed wrapper cannot do this: its job runs on, and the sweep above removes its directory once it ends.
P=; G=; command -v setsid >/dev/null 2>&1 && G=setsid
trap 'rm -rf "$T"' EXIT
stop() { [ -z "$P" ] || { kill -TERM "${G:+-}$P" 2>/dev/null || :; ( sleep "$GRACE"; kill -KILL "${G:+-}$P" 2>/dev/null ) & K=$!; wait "$P" 2>/dev/null || :; kill "$K" 2>/dev/null || :; }; exit 143; }
trap stop INT TERM HUP
exec 3<&0                                          # a background job gets /dev/null for stdin unless told otherwise
export PROOT_TMP_DIR="$T"
ulimit -c 0                                        # --ulimit core=0
B=; for f in /etc/resolv.conf /etc/hosts; do [ -e "$f" ] && B="$B -b $f"; done
# env -i: the image's own environment (docker inspect cafe-pm) plus the -e flags of the docker runner; nothing of the host's leaks in.
# LC_ALL: en_US.UTF-8 is missing in the image. PMIX_MCA_gds=hash: under proot Open MPI's PMIx shared-memory store fails at MPI_Init (PMIX_ERR_NOT_AVAILABLE in gds_shmem.c) and every
# mpirun, so OpenFOAM's meshing and solving in parallel, aborts; docker with the same 64 MB /dev/shm is fine, so it is proot, not the small shm. (Not needed: btl_vader_single_copy_mechanism.)
# shellcheck disable=SC2086
$G "$W/bin/proot" -r "$W/root" -i "$(id -u):$(id -g)" -w /app -b /dev -b /proc -b /sys $B \
  -b "$T:/tmp" -b "$C/$D:/app" -b "$C/pmdata:/data" -b "$C/data:/work" \
  /usr/bin/env -i PATH=/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONUNBUFFERED=1 HOME=/tmp TMPDIR=/tmp LC_ALL=C.UTF-8 \
  PYTHONPATH=/app CAFE_DATA=/data CAFE_GIT_SHA="${CAFE_GIT_SHA:-}" CAFE_GIT_DIRTY="${CAFE_GIT_DIRTY:-0}" CAFE_WORKERS="${PM_CPUS:-8}" \
  PMIX_MCA_gds=hash "$@" <&3 3<&- &
P=$!; echo "$P" >> "$T/.pids"
wait "$P"
