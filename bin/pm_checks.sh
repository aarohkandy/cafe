# Sourced (`. bin/pm_checks.sh`) by pm.sh, bin/pmx.sh, bin/orca_ready.sh, bin/orca_gate.sh and bin/proot_suite.sh: the one place that decides what a name or a number pasted into a command line may be.
# They reach a shell on the worker (and docker's argument list), so a ';' or a space in one is a command there. Each function exits the calling script with status 2 before anything is sent.
pm_bad() { echo "$1" >&2; exit 2; }
pm_num() { case $2 in ''|0*|*[!0-9]*) pm_bad "$1: a whole number from 1, not '$2'" ;; esac; }                           # $1 name, $2 value
pm_size() { _pm_n=${2%[bB]}; case ${_pm_n%[kmgKMG]} in ''|0*|*[!0-9]*) pm_bad "$1: a whole number from 1, then k, m, g, kb, mb or gb if you like (8g), not '$2'" ;; esac; }       # docker's --memory, --shm-size
# A tag (or TM) T names a log T.log in the worker's one flat logs folder, and the suite's jobs write T_s<i>.log, T_serial.log, T_shares.log and T_audit.log beside it: a name that is itself
# one of those (a_s2 beside the tag a) would share its log with another tag's job, and the P-30 sweep of a's stale share logs would delete it (round 10 M-28).
pm_shape() {
  _pm_ok=1
  case $1 in *_serial|*_shares|*_audit) _pm_ok= ;; *_s*) case ${1##*_s} in ''|*[!0-9]*) ;; *) _pm_ok= ;; esac ;; esac       # ${1##*_s}: what follows the last _s
  [ -n "$_pm_ok" ] || pm_bad "$2: not a name ending _s<digits>, _serial, _shares or _audit, which are the suite's job logs (not '$1')"
}
pm_tag() { case $1 in ''|*[!A-Za-z0-9_-]*) pm_bad "tag: letters, digits, _ and - only (not '$1')" ;; esac; pm_shape "$1" tag; }
# PMX and TM name a directory that rsync --delete empties, a log file, a tmux session and a docker container. PMX: pm_ and a plain name (never pmdata, data, pm, tmp, .. or a path).
# TM: docker names start with a letter or digit and have 2 or more characters (a leading '-' is an option to tmux; a lone 'x' is no name for docker); under proot it is a gate's log name too (pm_shape).
pm_names() {
  _pm_d=${PMX:-pm_x}
  case ${_pm_d#pm_} in "$_pm_d"|''|*[!A-Za-z0-9_-]*) pm_bad "PMX: pm_ and then letters, digits, _ or - only (not '$_pm_d')" ;; esac
  case ${TM-} in '') ;; [!A-Za-z0-9]*|?|*[!A-Za-z0-9_-]*) pm_bad "TM: 2 or more of letters, digits, _ and -, the first a letter or digit (not '$TM')" ;; esac
  [ -z "${TM-}" ] || [ "${PM_RUNTIME:-docker}" != proot ] || pm_shape "$TM" TM
}
# What the job's command line carries; PM_RUNTIME decides which of them it does.
pm_job() {
  [ -z "${PM_CPUS-}" ] || pm_num PM_CPUS "$PM_CPUS"
  if [ "${PM_RUNTIME:-docker}" = proot ]; then
    case ${PM_STOP_GRACE:-10} in *[!0-9]*) pm_bad "PM_STOP_GRACE: whole seconds (default 10), not '$PM_STOP_GRACE'" ;; esac
    [ -z "${CAFE_MIN_FREE_GB-}" ] || pm_num CAFE_MIN_FREE_GB "$CAFE_MIN_FREE_GB"
    [ -z "${PM_THREADS-}" ] || pm_num PM_THREADS "$PM_THREADS"
  else
    [ -z "${PM_MEM-}" ] || pm_size PM_MEM "$PM_MEM"
    [ -z "${PM_SHM-}" ] || pm_size PM_SHM "$PM_SHM"
  fi
}
