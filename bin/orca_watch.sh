#!/bin/sh
# Flight recorder for orca: runs ON orca beside the jobs, so it keeps recording if the laptop sleeps or the connection drops.
# Read-only except for ~/cafe-worker/logs/watch: a line a minute in timeline.tsv, and the moment a job log gains a failed test, a traceback, an error line
# or an rc= it appends to problems.log and saves snap_*.txt (log tail, processes, memory, disk) while the evidence still exists.
# Start: TMUX_TMPDIR=$HOME/cafe-worker/logs cafe-worker/env/bin/tmux new-session -d -s watch 'sh cafe-worker/bin/orca_watch.sh'
# Stop:  TMUX_TMPDIR=$HOME/cafe-worker/logs cafe-worker/env/bin/tmux kill-session -t watch
cd || exit 1
L=cafe-worker/logs; W=$L/watch; G=/sys/fs/cgroup; FLOOR=${CAFE_MIN_FREE_GB:-60}
[ -f cafe-worker/.cafe-worker-owned ] || { echo "no cafe-worker of ours here" >&2; exit 1; }
mkdir -p "$W/state"
[ -s "$W/timeline.tsv" ] || printf 'utc\tcpus\tthrottled\tmem_gb\tavail_gb\tload1\tdisk_free_gb\tooms\ttmux\n' > "$W/timeline.tsv"

stat_of() { awk -v k="$1" '$1==k{print $2}' "$2"; }
snap() {                                                               # $1 = job name, $2 = why
    s="$W/snap_$(date -u +%Y%m%dT%H%M%SZ)_$1.txt"
    { echo "== $2"; date -u; cat /proc/loadavg; free -g; df -h . | tail -1; cat $G/memory.events
      echo "== log tail"; tail -c 6000 "$L/$1.log" 2>/dev/null; echo; echo "== processes"; ps -eo pid,ppid,etimes,pcpu,rss,args --sort=-rss | cut -c1-160 | head -25; } > "$s" 2>&1
}
note() { printf '%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$1" "$2" >> "$W/problems.log"; snap "$1" "$2"; }

u0=$(stat_of usage_usec $G/cpu.stat); low=
while :; do
    sleep 60
    u1=$(stat_of usage_usec $G/cpu.stat)
    free_gb=$(df -Pk . | awk 'NR==2{print int($4/1048576)}')
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$(awk -v a="$u0" -v b="$u1" 'BEGIN{printf "%.1f",(b-a)/6e7}')" \
        "$(stat_of nr_throttled $G/cpu.stat)" "$(awk '{printf "%.1f",$1/1073741824}' $G/memory.current)" \
        "$(awk '/MemAvailable/{printf "%.0f",$2/1048576}' /proc/meminfo)" "$(cut -d' ' -f1 /proc/loadavg)" "$free_gb" \
        "$(stat_of oom_kill $G/memory.events)" "$(TMUX_TMPDIR=$HOME/$L cafe-worker/env/bin/tmux ls 2>/dev/null | wc -l)" >> "$W/timeline.tsv"
    u0=$u1
    [ "$free_gb" -lt $((FLOOR + 40)) ] && [ -z "$low" ] && { low=1; note disk "only $free_gb GB free on the shared disk (jobs refuse under $FLOOR)"; }
    for f in "$L"/*.log; do
        [ -f "$f" ] || continue
        n=$(basename "$f" .log)
        fails=$(grep -aE '^[.sxFE]+ *(\[ *[0-9]+%\])?$' "$f" | tr -cd 'FE' | wc -c)
        errs=$(grep -acE '^(error:|Traceback )' "$f")
        rc=$(tail -c 120 "$f" | grep -ao 'rc=[0-9]*' | tail -1)
        now="$fails $errs $rc"; was=$(cat "$W/state/$n" 2>/dev/null)
        [ "$now" = "$was" ] && continue
        echo "$now" > "$W/state/$n"
        case "$now" in "0 0 "|"0 0 rc=0") ;; *) note "$n" "failed tests $fails, error lines $errs, ${rc:-still running}" ;; esac
    done
done
