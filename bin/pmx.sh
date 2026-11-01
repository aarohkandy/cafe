#!/bin/sh
# Like ./pm.sh but syncs (with --delete) to a private ~/work/cafe/$PMX so it never touches the shared ~/work/cafe/pm. Run from the cafe checkout.
# TM=<name>: run detached in tmux session <name>, output to ~/logs/<name>.log, exit code appended as "rc=N".
H="azureuser@100.108.213.121"; K="$HOME/.ssh/homebase_ed25519"; D=${PMX:-pm_x}
rsync -az --delete --exclude .git --exclude __pycache__ --exclude site --exclude checkpoints --exclude cache -e "ssh -i $K" ./ "$H:work/cafe/$D/"
CMD="docker run --rm --ulimit core=0 --name ${TM:-pmx_$D} --hostname \$(hostname) -u 1000:1000 --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -v \$HOME/work/cafe/$D:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
if [ -n "$TM" ]; then
  ssh -i "$K" "$H" "mkdir -p \$HOME/work/cafe/pmdata \$HOME/logs && tmux new-session -d -s $TM \"$CMD > \$HOME/logs/$TM.log 2>&1; echo rc=\\\$? >> \$HOME/logs/$TM.log\" && sleep 3 && tmux ls | grep $TM"
else
  ssh -i "$K" "$H" "mkdir -p \$HOME/work/cafe/pmdata && $CMD"
fi
