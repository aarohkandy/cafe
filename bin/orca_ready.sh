#!/bin/sh
# The go check for orca, from the checkout: PM_HOST=cafe-orca sh bin/orca_ready.sh       (2 CPUs, about 5 min; stops at the first thing wrong)
# The worker is complete, a job runs, parallel OpenFOAM works (the biggest risk under proot), and nothing of ours landed outside ~/cafe-worker.
set -eu
H="${PM_HOST:-cafe-orca}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"; S="ssh -i $K"
export PM_HOST="$H" PM_RUNTIME=proot PM_CPUS=2 PMX=pm_ready
$S "$H" sh -s "${CAFE_MIN_FREE_GB:-60}" <<'EOF'
set -eu
cd; W=cafe-worker; echo "ssh-home=$HOME"
[ -f $W/.cafe-worker-owned ] || { echo "STOP: no cafe-worker of ours here" >&2; exit 1; }
for f in bin/proot root.done pmdata.done data.done env/bin/rsync env/bin/tmux; do [ -e $W/$f ] || { echo "STOP: $W/$f is missing: run bin/orca_sync.sh" >&2; exit 1; }; done
free=$(df -Pk . | awk 'NR==2{print int($4/1048576)}'); [ "$free" -ge "$1" ] || { echo "STOP: only $free GB free on the shared disk" >&2; exit 1; }
echo "free=${free}GB ours=$(du -sh $W 2>/dev/null | cut -f1) load=$(cut -d' ' -f1-3 /proc/loadavg)"
ps -eo user:12,pcpu,comm --sort=-pcpu | head -6
touch $W/.ready_start
EOF
bin/pmx.sh python -c "'from cafe.pm import par; print(\"workers\", par.workers(), \"memory_gb\", par.memory_gb())'"
bin/pmx.sh python -m pytest tests/test_par.py tests/test_stage3.py::test_free_surface_window_with_the_real_interfoam_at_toy_size -p no:cacheprovider -q -q
$S "$H" sh -s <<'EOF'
set -eu
cd
o=$(find . -maxdepth 2 -path ./cafe-worker -prune -o -newer cafe-worker/.ready_start -print 2>/dev/null | grep -v '^\.$' || :)
[ -z "$o" ] || { printf 'STOP: changed outside cafe-worker during this check (ours, or someone else on the account?):\n%s\n' "$o" >&2; exit 1; }
EOF
echo orca-ready
