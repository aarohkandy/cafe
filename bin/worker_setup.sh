#!/bin/sh
# Ready a machine to run cafe jobs through bin/pmx.sh: docker, the cafe-pm image, SITL, Bellhop and the data the tests and the demo read.
#   sh bin/worker_setup.sh <user@host> [key, as a path on homebase]      default key ~/.ssh/burst_ed25519
# Everything is copied from homebase, so the worker must be reachable from homebase and accept that key. A fresh install needs 25 GB free (checked before anything is installed or copied; a worker that already holds the image and the data directories is not asked again, because the install used that space) and an account that can sudo for
# the docker install. On a machine where the login is not yet in the docker group the first run adds it and stops: log out of that login and run it again. Its host key must already be in homebase's known_hosts; WORKER_TOFU=1 trusts it on first contact instead and prints the fingerprint to compare with
# the provider's console. Re-running is safe. Then run jobs on it with:  export PM_HOST=<user@host>   (if only homebase reaches it, an ~/.ssh/config entry with ProxyJump and PM_HOST=<that name>)
set -eu
W="${1:?usage: sh bin/worker_setup.sh <user@host> [key, as a path on homebase]}"; KEY="${2:-\$HOME/.ssh/burst_ed25519}"
. "$(dirname "$0")/pm_checks.sh"          # W and KEY are pasted into the script homebase runs: a ';' or a space in it is a command there (round 11 M-18)
case $W in *@*) pm_user "the user of the worker" "${W%%@*}" ;; esac; pm_host "the host of the worker" "${W#*@}"; pm_key "the key path" "$KEY"
O="${WORKER_TOFU:+-o StrictHostKeyChecking=accept-new}"
H="${PM_HOME_HOST:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"
ssh -i "$K" "$H" sh -s <<EOF
set -eu
S="ssh $O -i $KEY"
[ -z "$O" ] || \$S $W true
[ -z "$O" ] || ssh-keygen -F ${W#*@} -l
\$S $W 'docker image inspect cafe-pm >/dev/null 2>&1 && for d in pmdata/bin pmdata/dtmb5415 pmdata/bathy pmdata/tao pmdata/cache pmdata/ocean; do [ -d work/cafe/\$d ] || exit 1; done && [ -d work/cafe/data ]' || {
kb=\$(\$S $W 'df -Pk . | tail -1 | tr -s " " | cut -d" " -f4')
[ "\${kb:-0}" -ge 26214400 ] || { echo "STOP: only \$((\${kb:-0} / 1048576)) GB free on $W, 25 GB needed" >&2; exit 1; }
}
\$S $W 'cloud-init status --wait >/dev/null 2>&1 || true; command -v docker >/dev/null && command -v rsync >/dev/null && command -v tmux >/dev/null' || \$S $W 'sudo apt-get update -qq && sudo apt-get install -y -qq docker.io rsync tmux'
\$S $W 'docker ps >/dev/null 2>&1' || { \$S $W 'sudo usermod -aG docker \$USER' && echo "STOP: docker did not answer for the login on $W, which is now in the docker group: that login does not have the group yet. Log out of it and run this again; if it stops here again, run docker ps on $W to see why" >&2; exit 1; }
\$S $W 'docker image inspect cafe-pm >/dev/null 2>&1' || docker save cafe-pm:latest | \$S $W docker load
\$S $W 'mkdir -p work/cafe/pmdata work/cafe/data logs'
cd \$HOME/work/cafe
rsync -a -e "\$S" pmdata/bin pmdata/dtmb5415 pmdata/bathy pmdata/tao pmdata/cache pmdata/ocean $W:work/cafe/pmdata/
rsync -a -e "\$S" data/ $W:work/cafe/data/
\$S $W 'docker run --rm --ulimit core=0 cafe-pm python -c "import cafe" 2>/dev/null || docker run --rm cafe-pm python --version; df -h / | tail -1; nproc; free -g | sed -n 2p'
EOF
