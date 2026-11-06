#!/bin/sh
# What `docker run ... cafe-pm <cmd>` in bin/pmx.sh does, for a worker with no docker (orca): the cafe-pm root filesystem under proot, same mounts, same environment.
# Runs ON the worker, started by bin/pmx.sh or bin/pm.sh when PM_RUNTIME=proot:   sh proot_run.sh <dir under ~/cafe-worker/cafe that becomes /app> <command and arguments>
# The root filesystem and proot come from bin/orca_sync.sh. Not enforced here, unlike docker: PM_MEM and PM_SHM, and --cpus (PM_CPUS only sets CAFE_WORKERS), and /work being read-only.
set -eu
D="$1"; shift
GRACE="${PM_STOP_GRACE:-10}"; case "$GRACE" in ''|*[!0-9]*) echo "PM_STOP_GRACE: whole seconds (default 10), not '$GRACE'" >&2; exit 2 ;; esac       # seconds between TERM and KILL when the job is stopped
case "${PM_CPUS:-8}" in 0*|*[!0-9]*) echo "PM_CPUS: a whole number from 1, not '$PM_CPUS'" >&2; exit 2 ;; esac       # also checked on the laptop (bin/pm_checks.sh); this one is for a run by hand
W="$HOME/cafe-worker"; C="$W/cafe"          # nothing outside ~/cafe-worker: the home folder is shared
[ -x "$W/bin/proot" ] && [ -f "$W/root.done" ] && [ -x "$W/root/usr/bin/env" ] || { echo "no proot or root filesystem under $W: run bin/orca_sync.sh" >&2; exit 1; }
[ -d "$C/$D" ] && [ -d "$C/pmdata" ] && [ -d "$C/data" ] || { echo "missing $C/$D, $C/pmdata or $C/data: run bin/orca_sync.sh" >&2; exit 1; }
# PM_THREADS (default unset: the job's libraries size their thread pools to the 64 CPUs `nproc` shows, as under docker) caps BLAS and OpenMP pools at that many threads. proot_suite.sh sets it to its jobs' PM_CPUS:
# 8 jobs of "2 CPUs" were at 29 of orca's 32 CPUs in the first minutes (orca-go P-20). Pipeline runs leave it unset: thread counts can change the last bits of a sum.
THREADS=; case "${PM_THREADS:-}" in '') ;; 0*|*[!0-9]*) echo "PM_THREADS: a whole number of threads from 1, not '$PM_THREADS'" >&2; exit 2 ;; *) THREADS="OMP_NUM_THREADS=$PM_THREADS OPENBLAS_NUM_THREADS=$PM_THREADS MKL_NUM_THREADS=$PM_THREADS" ;; esac
[ "${PM_CPUS:-8}" -le 32 ] || echo "warning: PM_CPUS=${PM_CPUS} is above orca's 32 CPUs; the sum over all running jobs must stay at 32 or below, nothing here limits it" >&2
free=$(df -Pk "$W" | awk 'NR==2{print int($4/1048576)}'); [ "$free" -ge "${CAFE_MIN_FREE_GB:-60}" ] || { echo "STOP: only $free GB free on the shared disk" >&2; exit 1; }
mkdir -p "$C/tmp"
# A run that was SIGKILLed (or lost to a container restart) leaves its run.* directory: each holds .pids (this wrapper, then its proot); one with no live pid is stale. Not a stale one without .pids: that is a run just starting.
# Live = a /proc entry whose state is not Z: kill -0 is true for a zombie, which stays when the container's PID 1 does not reap orphans, and its directory would never be swept.
for d in "$C"/tmp/run.*; do
  [ -f "$d/.pids" ] || continue; live=
  for p in $(cat "$d/.pids"); do st=$(sed 's/.*) //;s/ .*//' "/proc/$p/stat" 2>/dev/null) || :; [ -n "$st" ] && [ "$st" != Z ] && live=1; done
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
  PMIX_MCA_gds=hash $THREADS /bin/sh -c '"$@"; r=$?; echo $r > /tmp/.rc; exit $r' sh "$@" <&3 3<&- &
P=$!; echo "$P" >> "$T/.pids"
# proot returns the exit status of the LAST process of the job to end, not of its first (rehearsed: `(sleep 3; exit 0) & exit 1` gives 0). A child that outlives the job, such as
# the resource tracker that multiprocessing starts for spawned workers, made a failed pytest or pipeline run read rc=0. So the job writes its own status to its /tmp (= $T) and that is the exit status here;
# A job that was killed, or a full disk, leaves none: a nonzero status from proot then stands, but its 0 proves nothing (see above), so that is a failure. The job could always exit 0 itself: this catches accidents, it is no sandbox.
r=0; wait "$P" || r=$?
c=; [ ! -f "$T/.rc" ] || read -r c < "$T/.rc" || :
case "$c" in
  ''|*[!0-9]*) [ "$r" -ne 0 ] || { echo "proot_run: the job left no exit status; counted as failed" >&2; r=1; } ;;
  *) r=$c ;;
esac
exit "$r"
