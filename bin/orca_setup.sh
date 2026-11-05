#!/bin/bash
# Joins a no-root, no-docker machine (the lab's orca container) to the owner's tailnet so agents can ssh in, using nothing but outbound HTTPS.
# The owner copies it to that machine and runs `bash orca_setup.sh` in its terminal, again after the container restarts. Never paste it raw: its `set -e` would close the terminal on any error.
# tailscale up prints a login URL for the owner to open. Needs conda-forge reachable and mamba on PATH.
# Others share this machine and possibly this account, so everything stays in ~/cafe-worker, marked as ours, and only processes running from it are ever stopped.
#   bash orca_setup.sh check   changes nothing; shows who else is here and says OK or STOP
#   bash orca_setup.sh         sets up or restarts      bash orca_setup.sh undo   stops ours and deletes ~/cafe-worker, nothing else
set -eu
W=$HOME/cafe-worker; M=$W/.cafe-worker-owned
case "$W" in /?*/cafe-worker) ;; *) echo "STOP: odd home folder '$W'"; exit 1 ;; esac
ours() { [ -f "$M" ]; }
stop_ours() {           # by pid file, and only a process whose program lives in our folder: never by name, the account may be shared
  for f in "$W/ssh/sshd.pid" "$W/ts/tailscaled.pid"; do
    [ -f "$f" ] || continue; p=$(cat "$f"); case "$(readlink "/proc/$p/exe" 2>/dev/null)" in "$W"/*) kill "$p" 2>/dev/null || true ;; esac
  done; sleep 1
}
problems() {
  if [ -e "$W" ] && ! ours && [ -n "$(ls -A "$W" 2>/dev/null)" ]; then echo "STOP: $W exists and is not ours"; fi
  if (exec 3<>/dev/tcp/127.0.0.1/2222) 2>/dev/null && ! ours; then echo "STOP: port 2222 is in use by something else"; fi
  a=$(df -Pk "$HOME" | awk 'NR==2{print int($4/1048576)}'); [ "$a" -ge "${CAFE_MIN_FREE_GB:-60}" ] || echo "STOP: only $a GB free on the shared disk"
}
case "${1:-}" in
  check)
    echo "== me"; id; echo "HOME=$HOME"; uptime
    echo "== who is logged in"; who 2>/dev/null || true
    echo "== processes by account"; ps -eo user= | sort | uniq -c | sort -rn | head
    echo "== busiest processes"; ps -eo user,pid,pcpu,pmem,etime,comm --sort=-pcpu | head -12
    echo "== home folder"; ls -la "$HOME" | head -40
    echo "== names we would use"; ls -ld "$W" "$HOME/work" "$HOME/logs" 2>&1 | cut -c1-100
    echo "== disk"; df -h "$HOME" / /tmp | cut -c1-80
    r=$(problems); [ -z "$r" ] && echo "check: OK, nothing changed" || { echo "$r"; echo "check: nothing changed"; exit 1; }
    exit 0 ;;
  undo)
    ours || { echo "STOP: $W is not ours, nothing touched"; exit 1; }
    stop_ours; "$W/bin/tailscale" --socket="$W/ts/sock" logout 2>/dev/null || true; rm -rf -- "$W"
    echo "removed $W; also remove device orca-cafe at https://login.tailscale.com/admin/machines"; exit 0 ;;
  "") ;;
  *) echo "usage: bash orca_setup.sh [check|undo]"; exit 2 ;;
esac
r=$(problems); [ -z "$r" ] || { echo "$r"; exit 1; }
V=1.104.5; SHA=720cbbccbfc03d8b55df72afc19e5a72e31b0f65934700aa6fa38074d4ad7bf7
mkdir -p $W/bin $W/ts $W/ssh $W/mh; touch $M; chmod 700 $W; cd $W    # the disk is shared with the lab: the host key and tailnet state stay private
if [ ! -x bin/tailscaled ]; then
  curl -fsSL https://pkgs.tailscale.com/stable/tailscale_${V}_amd64.tgz -o ts.tgz
  echo "$SHA  ts.tgz" | sha256sum -c -
  tar xzf ts.tgz --strip-components=1 -C bin tailscale_${V}_amd64/tailscale tailscale_${V}_amd64/tailscaled; rm ts.tgz
fi
[ -x env/bin/sshd ] || HOME=$W/mh XDG_CACHE_HOME=$W/mh/.cache CONDA_PKGS_DIRS=$W/pkgs mamba create -y -q -p $W/env --override-channels -c conda-forge openssh rsync tmux
rm -rf $W/pkgs $W/mh
[ -f ssh/host_ed25519 ] || env/bin/ssh-keygen -q -t ed25519 -N '' -f ssh/host_ed25519
cat > ssh/authorized_keys <<K
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDvAayxNiJTmhoucK4Iud5VzPW+HyxRYJ5v2Z/rMiLbJ cafe-laptop
ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOL1gtUF0WV3QidwT6ud63zHVi7kmop7LXhH9JMbQQ9Y cafe-homebase
K
chmod 700 ssh; chmod 600 ssh/authorized_keys
cat > ssh/sshd_config <<C
ListenAddress 127.0.0.1:2222
HostKey $W/ssh/host_ed25519
PidFile $W/ssh/sshd.pid
AuthorizedKeysFile $W/ssh/authorized_keys
PasswordAuthentication no
KbdInteractiveAuthentication no
StrictModes no
UsePAM no
Subsystem sftp internal-sftp
SetEnv PATH=$W/env/bin:$W/bin:/usr/local/bin:/usr/bin:/bin
C
stop_ours
$W/env/bin/sshd -f $W/ssh/sshd_config -E $W/ssh/sshd.log
TS_LOGS_DIR=$W/ts setsid nohup bin/tailscaled --no-logs-no-support --tun=userspace-networking --statedir=$W/ts --socket=$W/ts/sock --port=0 > ts/tailscaled.log 2>&1 &
echo $! > ts/tailscaled.pid
sleep 3
bin/tailscale --socket=$W/ts/sock up --hostname=orca-cafe --accept-dns=false
bin/tailscale --socket=$W/ts/sock ip -4
echo "ssh-home=$(getent passwd $(id -u) | cut -d: -f6) HOME=$HOME"    # ssh logs in to the first: relative paths from the runners land there
echo cafe-worker-ready
