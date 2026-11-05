#!/bin/sh
# Like ./pm.sh but syncs (with --delete) to a private ~/work/cafe/$PMX so it never touches the shared ~/work/cafe/pm. Run from the cafe checkout.
# TM=<name>: run detached in tmux session <name>, output to ~/logs/<name>.log, exit code appended as "rc=N".
# Worker: PM_HOST=<ssh host> (default homebase; an ~/.ssh/config name such as cafe-burst carries its own jump), PM_KEY=<ssh key>. bin/worker_setup.sh readies one.
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job in the cafe-pm root filesystem under proot (bin/proot_run.sh), with ~/cafe-worker/cafe for ~/work/cafe and ~/cafe-worker/logs for ~/logs; bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; D=${PMX:-pm_x}; S="ssh -i $K"
R=work/cafe; L='$HOME/logs'; RP=; PRE=
if [ "${PM_RUNTIME:-docker}" = proot ]; then         # orca is shared: everything of ours stays inside ~/cafe-worker, so a plain name only, and only where orca_setup.sh made that folder
  case "$D$TM" in *[!A-Za-z0-9_-]*) echo "PMX and TM: letters, digits, _ and - only" >&2; exit 2 ;; esac
  $S "$H" test -f cafe-worker/.cafe-worker-owned || { echo "STOP: no cafe-worker of ours on $H: run bin/orca_setup.sh there" >&2; exit 1; }
  R=cafe-worker/cafe; L='$HOME/cafe-worker/logs'; RP=--rsync-path=cafe-worker/env/bin/rsync    # rsync and tmux come from orca_setup.sh
  PRE="PATH=\$HOME/cafe-worker/env/bin:\$PATH; export TMUX_TMPDIR=$L; "
fi
rsync -az --delete --exclude .git --exclude __pycache__ --exclude site --exclude checkpoints --exclude cache $RP -e "$S" ./ "$H:$R/$D/" || exit 1
CMD="docker run --rm --ulimit core=0 --name ${TM:-pmx_$D} --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/$D:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  CMD="CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-8} CAFE_MIN_FREE_GB=${CAFE_MIN_FREE_GB:-60} sh \$HOME/$R/$D/bin/proot_run.sh $D $*"
fi
if [ -n "$TM" ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata $L && tmux new-session -d -s $TM \"$CMD > $L/$TM.log 2>&1; echo rc=\\\$? >> $L/$TM.log\" && sleep 3 && tmux ls | grep $TM"
else
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata && $CMD"
fi
