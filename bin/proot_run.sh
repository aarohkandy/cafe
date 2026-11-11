#!/bin/sh
# What `docker run ... cafe-pm <cmd>` in bin/pmx.sh does, for a worker with no docker (orca): the cafe-pm root filesystem under proot, same mounts, same environment.
# Runs ON the worker, started by bin/pmx.sh or bin/pm.sh when PM_RUNTIME=proot:   sh proot_run.sh <dir under ~/cafe-worker/cafe that becomes /app> <command and arguments>
# The root filesystem and proot come from bin/orca_sync.sh. Not enforced here, unlike docker: PM_MEM and PM_SHM, and /work being read-only. PM_CPUS is kept by pinning instead of --cpus (below, P-R14V5).
set -eu
D="$1"; shift
GRACE="${PM_STOP_GRACE:-10}"; case "$GRACE" in ''|*[!0-9]*) echo "PM_STOP_GRACE: whole seconds (default 10), not '$GRACE'" >&2; exit 2 ;; esac       # seconds between TERM and KILL when the job is stopped
. "$(dirname "$0")/pm_checks.sh"       # the rule of the laptop's scripts, for a run by hand: exit 2 before anything is read (round 14 M-19: a 20-digit number made `[` print 'Illegal number' and the check fell through)
[ -z "${PM_CPUS:-}" ] || pm_num PM_CPUS "$PM_CPUS"; pm_count CAFE_MIN_FREE_GB "${CAFE_MIN_FREE_GB:-60}"       # 0 is a value of CAFE_MIN_FREE_GB: the tests switch the disk check off with it
W="$HOME/cafe-worker"; C="$W/cafe"          # nothing outside ~/cafe-worker: the home folder is shared
[ -x "$W/bin/proot" ] && [ -f "$W/root.done" ] && [ -x "$W/root/usr/bin/env" ] || { echo "no proot or root filesystem under $W: run bin/orca_sync.sh" >&2; exit 1; }
[ -d "$C/$D" ] && [ -d "$C/pmdata" ] && [ -d "$C/data" ] || { echo "missing $C/$D, $C/pmdata or $C/data: run bin/orca_sync.sh" >&2; exit 1; }
# PM_THREADS is the size of the job's BLAS, OpenMP and XLA thread pools; unset, it is PM_CPUS. There is no cgroup under proot, so nothing but this kept a job to its PM_CPUS: its libraries sized their pools to the 64 CPUs
# `nproc` shows (orca-go P-20: 8 jobs of "2 CPUs" at 29 of orca's 32 CPUs; round 14 P-R14V5: a JAX matmul loop of a PM_CPUS=2 job at cpu/wall 32.1, the whole 32-CPU quota). DECISIONS 524 left the pools alone for pipeline runs
# ("a thread count can change the last bits of a sum"); that is amended: a job that takes the machine is the worse harm, and the same job under docker has the cgroup's quota and its host's pool size anyway.
N="${PM_CPUS:-8}"; TN="${PM_THREADS:-$N}"; [ -z "${PM_THREADS:-}" ] || pm_num PM_THREADS "$PM_THREADS"
THREADS="OMP_NUM_THREADS=$TN OPENBLAS_NUM_THREADS=$TN MKL_NUM_THREADS=$TN"
XLA="--xla_cpu_multi_thread_eigen=true intra_op_parallelism_threads=$TN"
[ "${PM_CPUS:-8}" -le 32 ] || echo "warning: PM_CPUS=${PM_CPUS} is above orca's 32 CPUs; the sum over all running jobs must stay at 32 or below, nothing here limits it" >&2
free=$(df -Pk "$W" | awk 'NR==2{print int($4/1048576)}'); [ "$free" -ge "${CAFE_MIN_FREE_GB:-60}" ] || { echo "STOP: only $free GB free on the shared disk" >&2; exit 1; }
mkdir -p "$C/tmp"
alive() { st=$(sed 's/.*) //;s/ .*//' "/proc/$1/stat" 2>/dev/null) || :; [ -n "$st" ] && [ "$st" != Z ]; }          # a /proc entry whose state is not Z (below)
# A run that was SIGKILLed (or lost to a container restart) leaves its run.* directory: each holds .pids (this wrapper, then its proot); one with no live pid is stale. Not a stale one without .pids: that is a run just starting.
# Live = a /proc entry whose state is not Z: kill -0 is true for a zombie, which stays when the container's PID 1 does not reap orphans, and its directory would never be swept.
for d in "$C"/tmp/run.*; do
  [ -f "$d/.pids" ] || continue; live=
  for p in $(cat "$d/.pids"); do ! alive "$p" || live=1; done
  [ -n "$live" ] || rm -rf "$d"
done
T=$(mktemp -d "$C/tmp/run.XXXXXX"); echo $$ > "$T/.pids"      # the container's /tmp, on the big disk (/ has 13 GB on orca); gone after the run, as with --rm
# The job runs in the background, in its own process group (setsid), so that a signal to this wrapper stops it at once: proot itself ignores SIGTERM and dies of SIGKILL
# without its tracees. The handler sends TERM to the group and KILL after PM_STOP_GRACE (10) s, as docker stop does. A SIGKILLed wrapper cannot do this: its job runs on, and the sweep above removes its directory once it ends.
P=; G=; command -v setsid >/dev/null 2>&1 && G=setsid
CLAIMED=; trap 'rm -rf "$T"; for d in $CLAIMED; do rm -rf "$d"; done' EXIT
stop() { [ -z "$P" ] || { kill -TERM "${G:+-}$P" 2>/dev/null || :; ( sleep "$GRACE"; kill -KILL "${G:+-}$P" 2>/dev/null ) & K=$!; wait "$P" 2>/dev/null || :; kill "$K" 2>/dev/null || :; }; exit 143; }
trap stop INT TERM HUP
# Pin the job to PM_CPUS cores (taskset on the host side of proot: the affinity is inherited by every tracee). The cores are the least busy ones over half a second of /proc/stat (other people's load counts, ours too), and each is claimed with
# an atomic mkdir of $C/tmp/cpu.<n> (the wrapper's pid in it) so that the K jobs of a gate, started at the same moment, do not all pick the same two; a claim of a dead wrapper is taken over. Fewer free cores than PM_CPUS: the rest is shared with
# the least busy claimed ones, with a warning. Not pinned: PM_CPUS at or above the CPUs this shell may use, or no taskset or /proc/stat (a warning). A race left: a claim whose wrapper died between mkdir and writing its pid stays.
PIN=
if command -v taskset >/dev/null 2>&1 && [ -r /proc/stat ]; then
  allowed=$(taskset -pc $$ | sed 's/.*: //')
  a=$(grep '^cpu[0-9]' /proc/stat); sleep 0.5; b=$(grep '^cpu[0-9]' /proc/stat)
  order=$(printf '%s\n--\n%s\n' "$a" "$b" | awk -v allowed="$allowed" '
    BEGIN { n = split(allowed, part, ","); for (i = 1; i <= n; i++) { m = split(part[i], r, "-"); for (c = r[1]; c <= r[m]; c++) ok[c] = 1 } }
    $1 == "--" { second = 1; next }
    { c = substr($1, 4) + 0; busy = $2 + $3 + $4 + $7 + $8 + $9; all = busy + $5 + $6
      if (!second) { b0[c] = busy; t0[c] = all } else if ((c in ok) && (c in b0)) { d = all - t0[c]; printf "%.4f %d\n", (d > 0 ? (busy - b0[c]) / d : 1), c } }' | sort -n | awk '{ print $2 }')
  have=$(printf '%s\n' "$order" | grep -c . || :)
  if [ "$have" -eq 0 ]; then
    echo "warning: could not read the CPUs this shell may use: the job is not pinned to PM_CPUS=$N cores" >&2
  elif [ "$have" -gt "$N" ]; then
    CORES=; got=0; rest=
    for c in $order; do
      if [ "$got" -lt "$N" ]; then
        d="$C/tmp/cpu.$c"
        if ! mkdir "$d" 2>/dev/null; then
          o=; [ ! -f "$d/pid" ] || read -r o < "$d/pid" || :
          if [ -n "$o" ] && ! alive "$o"; then rm -rf "$d"; mkdir "$d" 2>/dev/null || d=; else d=; fi
        fi
        if [ -n "$d" ]; then echo $$ > "$d/pid"; CLAIMED="$CLAIMED $d"; CORES="$CORES,$c"; got=$((got + 1)); continue; fi
      fi
      rest="$rest $c"
    done
    for c in $rest; do [ "$got" -lt "$N" ] || break; CORES="$CORES,$c"; got=$((got + 1)); echo "warning: no free core for PM_CPUS=$N, sharing core $c with another job of ours" >&2; done
    CORES=${CORES#,}; PIN="taskset -c $CORES"; echo "proot_run: pinned to cores $CORES (PM_CPUS=$N), pools of $TN threads" >&2
  fi
else
  echo "warning: no taskset or /proc/stat here: the job is not pinned to PM_CPUS=$N cores" >&2
fi
exec 3<&0                                          # a background job gets /dev/null for stdin unless told otherwise
export PROOT_TMP_DIR="$T"
ulimit -c 0                                        # --ulimit core=0
B=; for f in /etc/resolv.conf /etc/hosts; do [ -e "$f" ] && B="$B -b $f"; done
# env -i: the image's own environment (docker inspect cafe-pm) plus the -e flags of the docker runner; nothing of the host's leaks in.
# LC_ALL: en_US.UTF-8 is missing in the image. PMIX_MCA_gds=hash: under proot Open MPI's PMIx shared-memory store fails at MPI_Init (PMIX_ERR_NOT_AVAILABLE in gds_shmem.c) and every
# mpirun, so OpenFOAM's meshing and solving in parallel, aborts; docker with the same 64 MB /dev/shm is fine, so it is proot, not the small shm. (Not needed: btl_vader_single_copy_mechanism.)
# shellcheck disable=SC2086
$PIN $G "$W/bin/proot" -r "$W/root" -i "$(id -u):$(id -g)" -w /app -b /dev -b /proc -b /sys $B \
  -b "$T:/tmp" -b "$C/$D:/app" -b "$C/pmdata:/data" -b "$C/data:/work" \
  /usr/bin/env -i PATH=/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PYTHONUNBUFFERED=1 HOME=/tmp TMPDIR=/tmp LC_ALL=C.UTF-8 \
  PYTHONPATH=/app CAFE_DATA=/data CAFE_GIT_SHA="${CAFE_GIT_SHA:-}" CAFE_GIT_DIRTY="${CAFE_GIT_DIRTY:-0}" CAFE_WORKERS="${PM_CPUS:-8}" \
  PMIX_MCA_gds=hash $THREADS XLA_FLAGS="$XLA" /bin/sh -c '"$@"; r=$?; echo $r > /tmp/.rc; exit $r' sh "$@" <&3 3<&- &
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
