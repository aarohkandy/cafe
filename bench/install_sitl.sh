#!/bin/sh
# Install the ArduCopter SITL binary and its two parameter files, the real autopilot the UAS receipts fly against (cafe/pm/physics/uas.py fly_sitl).
# They are ArduPilot's own stable-4.7.1 SITL build (git dbe79216) and default_params at that commit, fetched and checked against the sha-256 of the
# files homebase has run since 2026-10-10 (~/work/cafe/data/sitl): the same bytes, so a lab install and the CI runner fly the same autopilot.
#   sh bench/install_sitl.sh [DIR]     DIR defaults to ~/work/cafe/data/sitl (homebase, /work/sitl in the containers); the code reads
#                                      $CAFE_WORK/sitl, so mount DIR's parent at /work or pass -e CAFE_WORK=<it> (RUNBOOK 1). Re-running is safe.
set -eu
OUT="${1:-$HOME/work/cafe/data/sitl}"
BIN="https://firmware.ardupilot.org/Copter/stable-4.7.1/SITL_x86_64_linux_gnu/arducopter"
SRC="https://raw.githubusercontent.com/ArduPilot/ardupilot/dbe792162d06cab66c3475fd5556bf7a120f119e/Tools/autotest/default_params"
mkdir -p "$OUT"
get() {   # url, file, pinned sha-256
  curl -fsSL --retry 3 -o "$OUT/$2.part" "$1"
  got=$(sha256sum "$OUT/$2.part" | cut -d" " -f1)
  [ "$got" = "$3" ] || { rm -f "$OUT/$2.part"; echo "SHA256 MISMATCH for $1: got $got, pinned $3; nothing installed" >&2; exit 1; }
  mv "$OUT/$2.part" "$OUT/$2"
}
get "$BIN" arducopter 011627d41dd95640c3aca02d45283474be48721c8b1bb7a4b234d38b69063482
get "$SRC/copter.parm" copter.parm 5e01345b45d1c6190b28bece5638bbdd4cf1cce35e05bbbf480ab24d2b51aa0e
get "$SRC/copter-X.parm" copter-X.parm cf4ac873fb3472edad53ec6550a329cd704c02748b959bfbb2ce37cfe856e236
chmod 755 "$OUT/arducopter"
echo "ArduCopter 4.7.1 SITL installed in $OUT (arducopter, copter.parm, copter-X.parm; sha-256 checked)"
