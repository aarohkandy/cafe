#!/bin/sh
# The whole suite (and with --cov the audit's coverage and the rest of it) on orca, detached in tmux, from the checkout:
#   PM_HOST=cafe-orca PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]
# It is bin/pmx.sh (same sync, names, owner check and tmux start as TM=; PMX is required, and from a checkout that does not own it PM_TAKE=1) with PM_ENTRY=proot_suite.sh: K jobs of 2 CPUs each under their own proot, then the real-time tests
# (docs/ORCA_RUNNER.md). The tmux session and its log are named <tag> (~/cafe-worker/logs/<tag>.log, ending rc=N); the jobs log to <tag>_s<i>.log. K at most 16 (orca has 32 CPUs).
. "$(dirname "$0")/pm_checks.sh"; pm_num K "${1-}"                                # the same rules proot_suite.sh applies on the worker (a K of 20 digits is refused by its length, not left to `[`)
[ "$1" -le 16 ] || { echo "K=$1 jobs of 2 CPUs is above orca's 32 CPUs (K at most 16)" >&2; exit 2; }
pm_tag "${2-}"
case ${3-} in ''|--cov) ;; *) echo "usage: PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]" >&2; exit 2 ;; esac
[ $# -le 3 ] || { echo "usage: PMX=pm_<you> bin/orca_gate.sh <K> <tag> [--cov]" >&2; exit 2; }
[ -n "${PMX-}" ] || { echo "PMX=pm_<you> is required: it is the directory on orca that this sync empties with --delete, and a name made from the tag would be the code tree of whatever run already uses that tag (round 14 M-33). Type: PM_TAKE=1 PM_HOST=cafe-orca PMX=pm_<you> bin/orca_gate.sh $* (PM_TAKE=1 the first time from a checkout that does not own that directory: a fresh worktree does not; bin/pmx.sh refuses a sync onto a directory another checkout owns, or one with a running job, without it)" >&2; exit 2; }
export PM_HOST="${PM_HOST:-cafe-orca}" PM_RUNTIME=proot PM_ENTRY=proot_suite.sh TM="$2"       # a directory another checkout owns is refused by bin/pmx.sh unless PM_TAKE=1 (a fresh worktree is another checkout)
exec sh "$(dirname "$0")/pmx.sh" "$@"
