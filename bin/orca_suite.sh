#!/bin/sh
# The whole suite as the orca rehearsal ran it (docs/ORCA_RUNNER.md). pmx.sh splits its arguments on spaces, so -m "not network" cannot be passed to it; this script holds it:
#   PM_HOST=cafe-orca PM_RUNTIME=proot PM_CPUS=30 PMX=pm_<you> TM=<name> bin/pmx.sh sh bin/orca_suite.sh --junitxml=/data/junit.xml
# Arguments after the script name go to pytest; a later -n wins over the 12 here.
exec python -m pytest -n 12 --dist loadfile -m "not network" "$@"
