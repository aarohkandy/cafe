#!/bin/sh
# Run a command for the pre-mission pipeline on homebase, in the cafe-pm image:  ./pm.sh make acceptance
# Syncs this checkout to ~/work/cafe/pm (never the live app's ~/work/cafe/src) with --delete, so a file removed from the tree is gone on the server too. The outputs
# written on the server (runs/, checkpoints/, config/throughput.json, docs/mutation.json, ...) are listed in bin/sync_filters, shared with bin/pmx.sh, and survive; copy them back with ./pm.sh --pull.
# The shared pm/ has one owner at a time: the checkout that last synced it is recorded in ~/$R/pm.owner (host:path), and a sync from any other checkout is refused (it would --delete the
# owner's files under a running job). Another agent uses bin/pmx.sh with its own pm_<name>; PM_TAKE=1 makes this checkout the owner.
# Defaults on this path, the lead's whole-box one: PM_CPUS=8, PM_MEM=28g, PM_SHM=16g (bin/pmx.sh, the path of every other agent, defaults to PM_CPUS=2 and PM_MEM=12g). PM_THREADS=<n> (proot only) sets the job's BLAS, OpenMP and XLA pools to n threads instead of PM_CPUS (bin/proot_run.sh); docker gets them at PM_CPUS.
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job under proot (bin/proot_run.sh), not docker, with ~/cafe-worker/cafe for ~/work/cafe; bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; S="ssh -i $K"
R=work/cafe; RP=; PRE=
. "$(dirname "$0")/bin/pm_checks.sh"; pm_job           # PM_CPUS, PM_MEM, ... are pasted into the remote command line: exit 2, nothing sent, unless plain (bin/pm_checks.sh)
if [ "${PM_RUNTIME:-docker}" = proot ]; then         # orca is shared: everything of ours stays inside ~/cafe-worker, and only where orca_setup.sh made that folder
  $S "$H" test -f cafe-worker/.cafe-worker-owned || { echo "STOP: no cafe-worker of ours on $H: run bin/orca_setup.sh there" >&2; exit 1; }
  R=cafe-worker/cafe; RP=--rsync-path=cafe-worker/env/bin/rsync; PRE='PATH=$HOME/cafe-worker/env/bin:$PATH; '
fi
if [ "$1" = "--pull" ]; then shift; for p in "$@"; do rsync -az $RP -e "$S" "$H:$R/pm/$p" "./$(dirname "$p")/"; done; exit; fi
ME=$(printf %s "$(hostname):$(pwd -P)" | tr -c 'A-Za-z0-9_./:@+-' _)             # this checkout, in the characters that are safe in the command line below
OWNER=$($S "$H" "cat \$HOME/$R/pm.owner 2>/dev/null")
if [ -n "$OWNER" ] && [ "$OWNER" != "$ME" ] && [ "${PM_TAKE:-}" != 1 ]; then
  echo "STOP: the shared $R/pm on $H belongs to $OWNER, and a sync from here ($ME) would --delete its files under a running job. Use PMX=pm_<you> bin/pmx.sh, or PM_TAKE=1 to take it over." >&2; exit 1
fi
$S "$H" "printf '%s\\n' '$ME' > \$HOME/$R/pm.owner" || exit 1
rsync -az --delete --filter=". $(dirname "$0")/bin/sync_filters" $RP -e "$S" ./ "$H:$R/pm/" || exit 1
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata && CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-8} ${PM_THREADS:+PM_THREADS=$PM_THREADS }CAFE_MIN_FREE_GB=${CAFE_MIN_FREE_GB:-60} PM_STOP_GRACE=${PM_STOP_GRACE:-10} sh \$HOME/$R/pm/bin/proot_run.sh pm $*"
  exit
fi
$S "$H" "mkdir -p \$HOME/work/cafe/pmdata && docker run --rm --ulimit core=0 --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e OMP_NUM_THREADS=${PM_CPUS:-8} -e OPENBLAS_NUM_THREADS=${PM_CPUS:-8} -e MKL_NUM_THREADS=${PM_CPUS:-8} -e 'XLA_FLAGS=--xla_cpu_multi_thread_eigen=true intra_op_parallelism_threads=${PM_CPUS:-8}' -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/pm:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
