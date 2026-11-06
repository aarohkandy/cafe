#!/bin/sh
# The whole test suite on orca as K separate proot jobs, because every system call of a job goes through ONE single-threaded proot (review/orca/PROBLEMS.md P-12, P-13):
# 12 pytest-xdist workers under one proot got 76,000 stat calls a second, 12 proots 293,000. Each job is a plain pytest process (no xdist) over its own share of the
# test files (cafe/pm/shares.py: balanced by the per-file time of the last run in the tag's folder), all at once; then the real-time tests (audit.SERIAL_TESTS) alone.
# Runs ON the worker, normally through bin/orca_gate.sh:    sh proot_suite.sh <dir under ~/cafe-worker/cafe, as for proot_run.sh> <K> <tag> [--cov]
#   K     1 to 16 jobs of 2 CPUs each (orca's cgroup holds 32: the sum over everything of ours must stay there; check /proc/loadavg first)
#   tag   names the logs ~/cafe-worker/logs/<tag>_s<i>.log (-vv, so a failure has its name while it runs; each ends rc=N), <tag>_serial.log and <tag>_audit.log, and the
#         folder pmdata/shards/<tag>/ (junit s<i>.xml, serial.xml, coverage). A run with the same tag takes its balance from that folder's junit files.
#   --cov coverage per job, then `coverage combine`, `coverage json` to /app/coverage.json, and `python -m cafe.pm.audit --pytest-done` (ruff, mypy, the scans and the
#         coverage gates; it fails on a coverage.json older than the code). Exit 0 only if every job and the audit passed; what failed is named.
# TERM, INT or HUP stops every job (proot_run.sh's own handler: TERM to the job's group, KILL after PM_STOP_GRACE s). Nothing is written outside ~/cafe-worker.
set -u
[ $# -eq 3 ] || { [ $# -eq 4 ] && [ "$4" = --cov ]; } || { echo "usage: sh proot_suite.sh <dir> <K> <tag> [--cov]" >&2; exit 2; }
D=$1; K=$2; TAG=$3; COV=${4:-}
case ${D#pm_} in "$D"|''|*[!A-Za-z0-9_-]*) echo "dir: pm_ and then letters, digits, _ or - only (not '$D')" >&2; exit 2 ;; esac
case $TAG in ''|*[!A-Za-z0-9_-]*) echo "tag: letters, digits, _ and - only" >&2; exit 2 ;; esac
case $K in ''|0*|*[!0-9]*) echo "K: a whole number from 1 to 16, not '$K'" >&2; exit 2 ;; esac
[ "$K" -le 16 ] || { echo "K=$K jobs of 2 CPUs is above orca's 32 CPUs (K at most 16)" >&2; exit 2; }
W="$HOME/cafe-worker"; C="$W/cafe"; R="$C/$D"; LOGS="$W/logs"; SH="$C/pmdata/shards/$TAG"; DS="/data/shards/$TAG"      # DS: the same folder, as the job sees it
[ -f "$W/.cafe-worker-owned" ] && [ -d "$R" ] && [ -d "$C/pmdata" ] || { echo "no cafe-worker of ours here, or no $R: sync first (bin/orca_gate.sh)" >&2; exit 1; }
mkdir -p "$SH" "$LOGS" || exit 1
live() { st=$(sed 's/.*) //;s/ .*//' "/proc/$1/stat" 2>/dev/null) || :; [ -n "$st" ] && [ "$st" != Z ]; }
if [ -f "$SH/.pid" ] && live "$(cat "$SH/.pid")"; then echo "tag $TAG is running (pid $(cat "$SH/.pid")): take another tag" >&2; exit 1; fi
echo $$ > "$SH/.pid"
echo "load $(cut -d' ' -f1-3 /proc/loadavg); this run takes $((K * 2)) of orca's 32 CPUs: the load above is other jobs, ours included"
PIDS=
stop() { trap '' INT TERM HUP; for p in $PIDS; do kill -TERM "$p" 2>/dev/null || :; done; wait; rm -f "$SH/.pid"; exit 143; }
trap stop INT TERM HUP
trap 'rm -f "$SH/.pid"' EXIT

# One job: its log (ending rc=N), the wrapper's TERM passed on to proot_run.sh. $1 = log name, the rest = the command run in the cafe-pm root filesystem.
job() {
    n=$1; shift
    ( sh "$R/bin/proot_run.sh" "$D" "$@" > "$LOGS/$n.log" 2>&1 &
      p=$!; trap 'kill -TERM $p 2>/dev/null' INT TERM HUP
      while :; do wait $p; r=$?; kill -0 $p 2>/dev/null || break; done          # a signal ends `wait` early: wait again until the job has really ended
      echo "rc=$r" >> "$LOGS/$n.log"; exit $r ) &
    PIDS="$PIDS $!"
}
export PM_CPUS=2
rm -f "$SH"/.coverage* "$SH"/serial.xml
# A job passes only if its exit status AND its junit file say so: a pytest process was seen to end with rc=0 after "1 failed" (round 9, orca-go P-18). $1 name, $2 exit status, $3 junit file.
verdict() {
    if [ "$2" -ne 0 ]; then BAD="$BAD $1(rc=$2)"; return; fi
    [ "$3" -nt "$SH/.start" ] || { BAD="$BAD $1(rc=0, but no new junit file)"; return; }
    e=$(grep -o ' errors="[0-9]*"' "$3" | head -1 | tr -dc 0-9); f=$(grep -o ' failures="[0-9]*"' "$3" | head -1 | tr -dc 0-9)
    [ "$e$f" = 00 ] || BAD="$BAD $1(rc=0, but its junit file says ${f:-?} failed, ${e:-?} errors)"
}
[ -z "$COV" ] || rm -f "$R/coverage.json"                                       # an old one must not be read as this run's
touch "$SH/.start"
# 1. the shares: a small python step under proot, once. Junit to balance by: the first suite's (if kept here), then this tag's last run, oldest first.
J=; [ -f "$C/pmdata/junit_91c9777.xml" ] && J="/data/junit_91c9777.xml"
for x in $(ls -tr "$SH"/s[0-9]*.xml 2>/dev/null); do J="$J $DS/$(basename "$x")"; done
# shellcheck disable=SC2086
sh "$R/bin/proot_run.sh" "$D" python -m cafe.pm.shares "$K" "$DS" $J > "$LOGS/${TAG}_shares.log" 2>&1; r=$?
echo "rc=$r" >> "$LOGS/${TAG}_shares.log"
[ $r -eq 0 ] || { echo "STOP: the shares step failed (rc=$r), see $LOGS/${TAG}_shares.log" >&2; exit 1; }
for x in "$SH"/s[0-9]*.xml; do [ -f "$x" ] || continue; i=${x##*/s}; i=${i%.xml}; [ -f "$SH/s$i.args" ] || rm -f "$x"; done       # a smaller K than last time: its extra junit files go
grep -v '^rc=' "$LOGS/${TAG}_shares.log"                                   # not its rc= line: the last line of this log is the job's own, for whoever polls it

# 2. the K jobs at once
i=1
while [ $i -le "$K" ]; do
    if [ -z "$COV" ]; then
        job "${TAG}_s$i" python -m pytest -p no:cacheprovider -vv -m "not network" --junitxml="$DS/s$i.xml" "@$DS/s$i.args"
    else
        job "${TAG}_s$i" env "COVERAGE_FILE=$DS/.coverage.s$i" python -m pytest -p no:cacheprovider -vv -m "not network" --cov=cafe/pm --cov-report= \
            --junitxml="$DS/s$i.xml" "@$DS/s$i.args"
    fi
    i=$((i + 1))
done
i=1; BAD=
for p in $PIDS; do wait "$p"; verdict "s$i" $? "$SH/s$i.xml"; i=$((i + 1)); done
PIDS=

# 3. the real-time tests alone
if [ -z "$COV" ]; then
    job "${TAG}_serial" python -m pytest -p no:cacheprovider -vv -m "not network" --junitxml="$DS/serial.xml" "@$DS/serial.args"
else
    job "${TAG}_serial" env "COVERAGE_FILE=$DS/.coverage.serial" python -m pytest -p no:cacheprovider -vv -m "not network" --cov=cafe/pm --cov-report= \
        --junitxml="$DS/serial.xml" "@$DS/serial.args"
fi
wait $PIDS; verdict serial $? "$SH/serial.xml"
PIDS=

# 4. coverage and the rest of the audit
if [ -n "$COV" ] && [ -z "$BAD" ]; then
    sh "$R/bin/proot_run.sh" "$D" sh -c 'coverage combine --keep --data-file="$1/.coverage" "$1" && coverage json --data-file="$1/.coverage" -o /app/coverage.json \
        && python -m cafe.pm.audit --pytest-done' x "$DS" > "$LOGS/${TAG}_audit.log" 2>&1; r=$?
    echo "rc=$r" >> "$LOGS/${TAG}_audit.log"
    [ $r -eq 0 ] || BAD="$BAD audit(rc=$r)"
elif [ -n "$COV" ]; then
    echo "coverage and audit not run: a job failed"
fi
if [ -n "$BAD" ]; then echo "FAILED:$BAD (logs: $LOGS/${TAG}_*.log)"; exit 1; fi
echo "suite ok: $K shares and the serial tests${COV:+, coverage and audit}"
