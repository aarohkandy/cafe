(
echo "== who"; id; hostname; uname -r; head -2 /etc/os-release; uptime; echo "HOME=$HOME PWD=$PWD"
echo "== size"; nproc; free -g | sed -n 2p; cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max 2>/dev/null
ls /dev/nvidia* 2>/dev/null | head -3
echo "== disk"; df -h "$HOME" / /tmp /dev/shm 2>&1
touch "$HOME/.w" 2>&1 && rm -f "$HOME/.w" && echo home-writable
echo "== tools"; for t in curl wget sha256sum conda mamba python3 tmux screen rsync ssh sshd proot bwrap unshare apptainer singularity podman docker make gcc gfortran; do printf '%s: ' $t; command -v $t || echo -; done
python3 --version
echo "== userns"; unshare -Ur true 2>&1 && echo userns-ok; cat /proc/sys/user/max_user_namespaces 2>/dev/null
echo "== others"; ps -eo user= | sort | uniq -c | sort -rn | head -5
echo "== outbound"; for u in https://pkgs.tailscale.com https://login.tailscale.com https://github.com https://conda.anaconda.org https://pypi.org/simple/; do printf '%s ' "$u"; curl -sS -o /dev/null -m 10 -w '%{http_code}\n' "$u" 2>&1 | tail -1; done
echo "== speed"; curl -sS -o /dev/null -m 20 -w '%{speed_download} bytes/s\n' https://pkgs.tailscale.com/stable/tailscale_1.104.5_amd64.tgz 2>&1 | tail -1
echo "== done"
)
