#!/bin/sh
# Run a command for the pre-mission pipeline on homebase, in the cafe-pm image:  ./pm.sh make acceptance
# Syncs this checkout to ~/work/cafe/pm (never the live app's ~/work/cafe/src) without --delete, so outputs written
# on the server (report/, checkpoints/, config/throughput.json) survive; copy them back with ./pm.sh --pull.
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job under proot (bin/proot_run.sh), not docker; bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; S="ssh -i $K"
RP=; PRE=; [ "${PM_RUNTIME:-docker}" = proot ] && { RP=--rsync-path=cafe-worker/env/bin/rsync; PRE='PATH=$HOME/cafe-worker/env/bin:$PATH; '; }
if [ "$1" = "--pull" ]; then shift; for p in "$@"; do rsync -az $RP -e "$S" "$H:work/cafe/pm/$p" "./$(dirname "$p")/"; done; exit; fi
rsync -az --exclude .git --exclude __pycache__ --exclude site --exclude checkpoints --exclude cache $RP -e "$S" ./ "$H:work/cafe/pm/"
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/work/cafe/pmdata && CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-8} sh \$HOME/work/cafe/pm/bin/proot_run.sh pm $*"
  exit
fi
$S "$H" "mkdir -p \$HOME/work/cafe/pmdata && docker run --rm --ulimit core=0 --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/pm:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
