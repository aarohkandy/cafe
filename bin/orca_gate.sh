#!/bin/sh
# The whole suite (and with --cov the audit's coverage and the rest of it) on orca, detached in tmux, from the checkout:
#   PM_HOST=cafe-orca PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]
# It is bin/pmx.sh (same sync, names, marker check and tmux start as TM=) with PM_ENTRY=proot_suite.sh: K jobs of 2 CPUs each under their own proot, then the real-time tests
# (docs/ORCA_RUNNER.md). The tmux session and its log are named <tag> (~/cafe-worker/logs/<tag>.log, ending rc=N); the jobs log to <tag>_s<i>.log. K at most 16 (orca has 32 CPUs).
case $1 in ''|0*|*[!0-9]*) echo "usage: PMX=pm_<you> bin/orca_gate.sh <K, 1 to 16> <tag> [--cov]" >&2; exit 2 ;; esac
[ "$1" -le 16 ] || { echo "K=$1 jobs of 2 CPUs is above orca's 32 CPUs (K at most 16)" >&2; exit 2; }
. "$(dirname "$0")/pm_checks.sh"; pm_tag "${2-}"                                  # the same rule proot_suite.sh applies on the worker
case ${3-} in ''|--cov) ;; *) echo "usage: PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]" >&2; exit 2 ;; esac
[ $# -le 3 ] || { echo "usage: PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]" >&2; exit 2; }
export PM_HOST="${PM_HOST:-cafe-orca}" PM_RUNTIME=proot PM_ENTRY=proot_suite.sh PMX="${PMX:-pm_$2}" TM="$2"
exec sh "$(dirname "$0")/pmx.sh" "$@"
