#!/bin/sh
# Like ./pm.sh but syncs (with --delete) to a private ~/work/cafe/$PMX so it never touches the shared ~/work/cafe/pm. Run from the cafe checkout.
# TM=<name>: run detached in tmux session <name>, output to ~/logs/<name>.log, exit code appended as "rc=N".
# Worker: PM_HOST=<ssh host> (default homebase; an ~/.ssh/config name such as cafe-burst carries its own jump), PM_KEY=<ssh key>. bin/worker_setup.sh readies one.
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job in the cafe-pm root filesystem under proot (bin/proot_run.sh); bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; D=${PMX:-pm_x}; S="ssh -i $K"
RP=; PRE=; [ "${PM_RUNTIME:-docker}" = proot ] && { RP=--rsync-path=cafe-worker/env/bin/rsync; PRE='PATH=$HOME/cafe-worker/env/bin:$PATH; '; }   # rsync and tmux come from orca_setup.sh
rsync -az --delete --exclude .git --exclude __pycache__ --exclude site --exclude checkpoints --exclude cache $RP -e "$S" ./ "$H:work/cafe/$D/"
CMD="docker run --rm --ulimit core=0 --name ${TM:-pmx_$D} --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/$D:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  CMD="CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-8} sh \$HOME/work/cafe/$D/bin/proot_run.sh $D $*"
fi
if [ -n "$TM" ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/work/cafe/pmdata \$HOME/logs && tmux new-session -d -s $TM \"$CMD > \$HOME/logs/$TM.log 2>&1; echo rc=\\\$? >> \$HOME/logs/$TM.log\" && sleep 3 && tmux ls | grep $TM"
else
  $S "$H" "${PRE}mkdir -p \$HOME/work/cafe/pmdata && $CMD"
fi
