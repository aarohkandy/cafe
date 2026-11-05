#!/bin/sh
# Run a command for the pre-mission pipeline on homebase, in the cafe-pm image:  ./pm.sh make acceptance
# Syncs this checkout to ~/work/cafe/pm (never the live app's ~/work/cafe/src) with --delete, so a file removed from the tree is gone on the server too. The outputs
# written on the server (runs/, checkpoints/, config/throughput.json, docs/mutation.json, ...) are listed in bin/sync_filters, shared with bin/pmx.sh, and survive; copy them back with ./pm.sh --pull.
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job under proot (bin/proot_run.sh), not docker, with ~/cafe-worker/cafe for ~/work/cafe; bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; S="ssh -i $K"
R=work/cafe; RP=; PRE=
if [ "${PM_RUNTIME:-docker}" = proot ]; then         # orca is shared: everything of ours stays inside ~/cafe-worker, and only where orca_setup.sh made that folder
  case ${PM_STOP_GRACE:-10} in *[!0-9]*) echo "PM_STOP_GRACE: whole seconds (default 10), not '$PM_STOP_GRACE'" >&2; exit 2 ;; esac    # it is pasted into the remote command line
  $S "$H" test -f cafe-worker/.cafe-worker-owned || { echo "STOP: no cafe-worker of ours on $H: run bin/orca_setup.sh there" >&2; exit 1; }
  R=cafe-worker/cafe; RP=--rsync-path=cafe-worker/env/bin/rsync; PRE='PATH=$HOME/cafe-worker/env/bin:$PATH; '
fi
if [ "$1" = "--pull" ]; then shift; for p in "$@"; do rsync -az $RP -e "$S" "$H:$R/pm/$p" "./$(dirname "$p")/"; done; exit; fi
rsync -az --delete --filter=". $(dirname "$0")/bin/sync_filters" $RP -e "$S" ./ "$H:$R/pm/" || exit 1
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata && CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-8} CAFE_MIN_FREE_GB=${CAFE_MIN_FREE_GB:-60} PM_STOP_GRACE=${PM_STOP_GRACE:-10} sh \$HOME/$R/pm/bin/proot_run.sh pm $*"
  exit
fi
$S "$H" "mkdir -p \$HOME/work/cafe/pmdata && docker run --rm --ulimit core=0 --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/pm:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
