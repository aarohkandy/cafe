#!/bin/sh
# The whole test suite on orca as K separate proot jobs, because every system call of a job goes through ONE single-threaded proot (review/orca/PROBLEMS.md P-12, P-13):
# 12 pytest-xdist workers under one proot got 76,000 stat calls a second, 12 proots 293,000. Each job is a plain pytest process (no xdist) over its own share of the
# test files (cafe/pm/shares.py: balanced by the per-file time of the last run in the tag's folder), all at once; then the real-time tests (audit.SERIAL_TESTS) alone.
# Runs ON the worker, normally through bin/orca_gate.sh:    sh proot_suite.sh <dir under ~/cafe-worker/cafe, as for proot_run.sh> <K> <tag> [--cov]
#   K     1 to 16 jobs of 2 CPUs each (orca's cgroup holds 32: the sum over everything of ours must stay there; check /proc/loadavg first)
#   tag   names the logs ~/cafe-worker/logs/<tag>_s<i>.log (-vv, so a failure has its name while it runs; each ends rc=N), <tag>_serial.log and <tag>_audit.log, and the
#         folder pmdata/shards/<tag>/ (junit s<i>.xml, serial.xml, coverage). A run with the same tag takes its balance from that folder's junit files.
#   --cov coverage per job, then `coverage combine`, `coverage json` to /app/coverage.json, and `python -m cafe.pm.audit --pytest-done` (ruff, mypy, the scans and the
#         coverage gates; the receipt, coverage.receipt.json, is written first, only here, when every job passed, and holds the digest of the code that ran: --pytest-done
#         fails without it or when the code has changed since). Exit 0 only if every job and the audit passed; what failed is named.
# TERM, INT or HUP stops every job, in every step, the shares step and the audit included (proot_run.sh's own handler: TERM to the job's group, KILL after PM_STOP_GRACE s). Nothing is written outside ~/cafe-worker.
set -u
[ $# -eq 3 ] || { [ $# -eq 4 ] && [ "$4" = --cov ]; } || { echo "usage: sh proot_suite.sh <dir> <K> <tag> [--cov]" >&2; exit 2; }
D=$1; K=$2; TAG=$3; COV=${4:-}
case ${D#pm_} in "$D"|''|*[!A-Za-z0-9_-]*) echo "dir: pm_ and then letters, digits, _ or - only (not '$D')" >&2; exit 2 ;; esac
. "$(dirname "$0")/pm_checks.sh"; pm_tag "$TAG"                                   # the same rule bin/orca_gate.sh applies before it sends anything
pm_num K "$K"
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

# One job: its log (ending rc=N), the wrapper's TERM passed on to proot_run.sh. $1 = log name, the rest = the command run in the cafe-pm root filesystem. Every step, the shares and the audit too, goes through it (M-38).
job() {
    n=$1; shift
    ( sh "$R/bin/proot_run.sh" "$D" "$@" > "$LOGS/$n.log" 2>&1 &
      p=$!; trap 'kill -TERM $p 2>/dev/null' INT TERM HUP
      while :; do wait $p; r=$?; kill -0 $p 2>/dev/null || break; done          # a signal ends `wait` early: wait again until the job has really ended
      [ -z "$(tail -c 1 "$LOGS/$n.log")" ] || echo >> "$LOGS/$n.log"          # a stopped job leaves half a line: rc=N must be a line of its own (orca_watch reads it so)
      echo "rc=$r" >> "$LOGS/$n.log"; exit $r ) &
    PIDS="$PIDS $!"
}
export PM_CPUS=2 PM_THREADS=2          # PM_THREADS: BLAS and OpenMP pools of a job at its 2 CPUs, not orca's 64 (bin/proot_run.sh; P-20)
rm -f "$SH"/.coverage* "$SH"/serial.xml
# A smaller K than the last run under this tag: its logs <tag>_s<K+1>.log and up still end rc=0 and would end a reader's wait loop at once (P-30). Only this tag's: the part after
# "<tag>_s" must be all digits and above K (tag a must not touch the logs of tag a_s3, "a_s3_s1.log"). pm_tag refuses a tag that is itself such a log name (a_s2 beside a), and a TM of one under proot (bin/pm_checks.sh).
for x in "$LOGS/${TAG}"_s[0-9]*.log; do
    [ -f "$x" ] || continue; i=${x##*/"${TAG}"_s}; i=${i%.log}
    case $i in ''|*[!0-9]*) continue ;; esac
    [ "$i" -gt "$K" ] && rm -f "$x"
done
# A job passes only if its exit status AND its junit file say so: a pytest process was seen to end with rc=0 after "1 failed" (round 9, orca-go P-18). $1 name, $2 exit status, $3 junit file.
verdict() {
    if [ "$2" -ne 0 ]; then BAD="$BAD $1(rc=$2)"; return; fi
    [ "$3" -nt "$SH/.start" ] || { BAD="$BAD $1(rc=0, but no new junit file)"; return; }
    e=$(grep -o ' errors="[0-9]*"' "$3" | head -1 | tr -dc 0-9); f=$(grep -o ' failures="[0-9]*"' "$3" | head -1 | tr -dc 0-9)
    [ "$e$f" = 00 ] || BAD="$BAD $1(rc=0, but its junit file says ${f:-?} failed, ${e:-?} errors)"
}
[ -z "$COV" ] || rm -f "$R/coverage.json" "$R/coverage.receipt.json"           # an old one must not be read as this run's
touch "$SH/.start"
# 1. the shares: a small python step under proot, once (as a job, so that a signal acts at once). Junit to balance by: the first suite's (if kept here), then this tag's last run, oldest first.
J=; [ -f "$C/pmdata/junit_91c9777.xml" ] && J="/data/junit_91c9777.xml"
for x in $(ls -tr "$SH"/s[0-9]*.xml 2>/dev/null); do J="$J $DS/$(basename "$x")"; done
# A step is a job() like the others, waited for with `wait`, which a trapped signal ends at once: run in the foreground it would hold TERM, INT and HUP back until it returned (round 14 M-38).
# shellcheck disable=SC2086
job "${TAG}_shares" python -m cafe.pm.shares "$K" "$DS" $J
wait $PIDS; r=$?; PIDS=
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
    job "${TAG}_audit" sh -c 'coverage combine --keep --data-file="$1/.coverage" "$1" && coverage json --data-file="$1/.coverage" -o /app/coverage.json \
        && python -m cafe.pm.audit --pytest-receipt && python -m cafe.pm.audit --pytest-done' x "$DS"
    wait $PIDS; r=$?; PIDS=
    [ $r -eq 0 ] || BAD="$BAD audit(rc=$r)"
elif [ -n "$COV" ]; then
    echo "coverage and audit not run: a job failed"
fi
if [ -n "$BAD" ]; then echo "FAILED:$BAD (logs: $LOGS/${TAG}_*.log)"; exit 1; fi
echo "suite ok: $K shares and the serial tests${COV:+, coverage and audit}"
