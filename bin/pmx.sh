#!/bin/sh
# Like ./pm.sh but syncs (with --delete) to a private ~/work/cafe/$PMX so it never touches the shared ~/work/cafe/pm. Run from the cafe checkout.
# TM=<name>: run detached in tmux session <name>, output to ~/logs/<name>.log, exit code appended as "rc=N" (also after `tmux kill-session`: the HUP is passed to the job and its own status, 143, is written; P-26). After 3 s the session must exist (exact name) or the log must already end in rc=0, else exit 1.
# Defaults on this path: PM_CPUS=2 and PM_MEM=8g (docker's --cpus and --memory; under proot PM_CPUS only sets CAFE_WORKERS), PM_SHM=16g. The whole-box 8 CPUs and 28g are pm.sh's, the lead's path; ask for more here with PM_CPUS=<n> PM_MEM=<n>g.
# PM_THREADS=<n> (proot only) goes to bin/proot_run.sh, which caps the job's BLAS and OpenMP pools at n threads; unset, they size themselves to the worker's 64 CPUs, not to PM_CPUS (P-20).
# What the sync keeps on the server (outputs of jobs and gates): bin/sync_filters, shared with pm.sh.
# Worker: PM_HOST=<ssh host> (default homebase; an ~/.ssh/config name such as cafe-burst carries its own jump), PM_KEY=<ssh key>. bin/worker_setup.sh readies one.
# PM_ENTRY=proot_suite.sh (with PM_RUNTIME=proot): the worker script that runs, instead of proot_run.sh, with the dir name first as for it (bin/orca_gate.sh).
# PM_RUNTIME=proot: for a worker with no docker (orca): the same job in the cafe-pm root filesystem under proot (bin/proot_run.sh), with ~/cafe-worker/cafe for ~/work/cafe and ~/cafe-worker/logs for ~/logs; bin/orca_sync.sh readies one.
H="${PM_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; D=${PMX:-pm_x}; S="ssh -i $K"
R=work/cafe; L='$HOME/logs'; RP=; PRE=
# rsync --delete empties ~/$R/$D, and the variables below are pasted into the remote command line: bin/pm_checks.sh refuses (exit 2, nothing sent) a PMX, TM, PM_CPUS, PM_MEM, PM_SHM, PM_STOP_GRACE, CAFE_MIN_FREE_GB or PM_THREADS that is not plain
. "$(dirname "$0")/pm_checks.sh"; pm_names; pm_job
if [ "${PM_RUNTIME:-docker}" = proot ]; then         # orca is shared: everything of ours stays inside ~/cafe-worker, and only where orca_setup.sh made that folder
  case ${PM_ENTRY:-proot_run.sh} in proot_run.sh|proot_suite.sh) ;; *) echo "PM_ENTRY: proot_run.sh or proot_suite.sh, not '$PM_ENTRY'" >&2; exit 2 ;; esac
  $S "$H" test -f cafe-worker/.cafe-worker-owned || { echo "STOP: no cafe-worker of ours on $H: run bin/orca_setup.sh there" >&2; exit 1; }
  R=cafe-worker/cafe; L='$HOME/cafe-worker/logs'; RP=--rsync-path=cafe-worker/env/bin/rsync    # rsync and tmux come from orca_setup.sh
  PRE="PATH=\$HOME/cafe-worker/env/bin:\$PATH; export TMUX_TMPDIR=$L; "
fi
rsync -az --delete --filter=". $(dirname "$0")/sync_filters" $RP -e "$S" ./ "$H:$R/$D/" || exit 1
CMD="docker run --rm --ulimit core=0 --name ${TM:-pmx_$D} --hostname \$(hostname) -u \$(id -u):\$(id -g) --cpus ${PM_CPUS:-2} --memory ${PM_MEM:-8g} --shm-size ${PM_SHM:-16g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -e CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) -e CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) -v \$HOME/work/cafe/$D:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
if [ "${PM_RUNTIME:-docker}" = proot ]; then
  CMD="CAFE_GIT_SHA=$(git rev-parse HEAD 2>/dev/null) CAFE_GIT_DIRTY=$(if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo 1; else echo 0; fi) PM_CPUS=${PM_CPUS:-2} ${PM_THREADS:+PM_THREADS=$PM_THREADS }CAFE_MIN_FREE_GB=${CAFE_MIN_FREE_GB:-60} PM_STOP_GRACE=${PM_STOP_GRACE:-10} sh \$HOME/$R/$D/bin/${PM_ENTRY:-proot_run.sh} $D $*"
fi
if [ -n "$TM" ]; then
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata $L && tmux new-session -d -s $TM \"trap 'kill -HUP \\\$p 2>/dev/null; wait \\\$p; echo rc=\\\$? >> $L/$TM.log; exit' HUP; $CMD > $L/$TM.log 2>&1 & p=\\\$!; wait \\\$p; echo rc=\\\$? >> $L/$TM.log\" && sleep 3 && if tmux has-session -t =$TM 2>/dev/null; then tmux ls | grep \"^$TM:\" || :; else tail -n 1 $L/$TM.log | grep -qx rc=0 && echo \"$TM: finished, rc=0\" || { echo \"$TM ended: \$(tail -n 1 $L/$TM.log)\" >&2; exit 1; }; fi"
else
  $S "$H" "${PRE}mkdir -p \$HOME/$R/pmdata && $CMD"
fi
