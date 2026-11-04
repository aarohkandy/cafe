#!/bin/sh
# Ready a machine to run cafe jobs through bin/pmx.sh: docker, the cafe-pm image, SITL, Bellhop and the data the tests and the demo read.
#   sh bin/worker_setup.sh <user@host> [key, as a path on homebase]      default key ~/.ssh/burst_ed25519
# Everything is copied from homebase, so the worker must be reachable from homebase and accept that key. It needs 25 GB free and an account that can sudo for
# the docker install. Re-running is safe. Then run jobs on it with:  export PM_HOST=<user@host>   (if only homebase reaches it, an ~/.ssh/config entry with ProxyJump and PM_HOST=<that name>)
set -eu
W="$1"; KEY="${2:-\$HOME/.ssh/burst_ed25519}"
H="${PM_HOME_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"
ssh -i "$K" "$H" sh -s <<EOF
set -eu
S="ssh -o StrictHostKeyChecking=accept-new -i $KEY"
\$S $W 'cloud-init status --wait >/dev/null 2>&1 || true; command -v docker >/dev/null && command -v rsync >/dev/null && command -v tmux >/dev/null' || \$S $W 'sudo apt-get update -qq && sudo apt-get install -y -qq docker.io rsync tmux'
\$S $W 'docker ps >/dev/null 2>&1' || \$S $W 'sudo usermod -aG docker \$USER'
\$S $W 'docker image inspect cafe-pm >/dev/null 2>&1' || docker save cafe-pm:latest | \$S $W docker load
\$S $W 'mkdir -p work/cafe/pmdata work/cafe/data logs'
cd \$HOME/work/cafe
rsync -a -e "\$S" pmdata/bin pmdata/dtmb5415 pmdata/bathy pmdata/tao pmdata/cache pmdata/ocean $W:work/cafe/pmdata/
rsync -a -e "\$S" data/ $W:work/cafe/data/
\$S $W 'docker run --rm --ulimit core=0 cafe-pm python -c "import cafe" 2>/dev/null || docker run --rm cafe-pm python --version; df -h / | tail -1; nproc; free -g | sed -n 2p'
EOF
