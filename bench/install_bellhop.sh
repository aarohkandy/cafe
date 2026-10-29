#!/bin/sh
# Build Bellhop (Acoustics Toolbox, Michael Porter / HLS Research) into ~/work/cafe/pmdata/bin on homebase.
# Run on homebase:   sh ~/work/cafe/pm/bench/install_bellhop.sh        (after ./pm.sh has synced the checkout)
# or from the laptop: ssh -i ~/.ssh/homebase_ed25519 azureuser@100.108.213.121 'sh -s' < bench/install_bellhop.sh
# Fetches the official source zip, verifies its sha256 against the pinned value (prints it either way), installs
# gfortran/make in a throwaway root container (nothing is committed to any image), and leaves bellhop.exe in
# /data/bin inside cafe-pm (= ~/work/cafe/pmdata/bin on the host). Re-running is safe.
set -eu
URL="http://oalib.hlsresearch.com/AcousticsToolbox/at_2026_10_27.zip"
SHA256="00b100a87d267a23517b96bb14eee40be8886f8a1ebbad265a63ca5aa1a8a853"   # measured 2026-10-29
OUT="$HOME/work/cafe/pmdata/bin"
mkdir -p "$OUT"
docker run --rm -e URL="$URL" -e SHA256="$SHA256" -v "$OUT:/out" cafe-pm sh -ec '
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends gfortran make unzip ca-certificates >/dev/null
  cd /tmp && wget -q -T 120 -O at.zip "$URL"
  got=$(sha256sum at.zip | cut -d" " -f1)
  echo "downloaded $URL"; echo "sha256 $got"
  [ "$got" = "$SHA256" ] || { echo "SHA256 MISMATCH (pinned $SHA256): refusing to build" >&2; exit 1; }
  unzip -q at.zip "at/*" && cd at
  F="-O2 -std=gnu -ffree-line-length-none -I../misc -I../tslib"                 # portable: no -march=native, no -ffast-math
  make -C misc FC=gfortran FFLAGS="$F" all >/dev/null
  make -C Bellhop FC=gfortran FFLAGS="$F" bellhop.exe >/dev/null
  cp Bellhop/bellhop.exe /out/bellhop.exe && chmod 755 /out/bellhop.exe && chown 1000:1000 /out/bellhop.exe
  echo "$got  at_2026_10_27.zip" > /out/bellhop.source.sha256 && chown 1000:1000 /out/bellhop.source.sha256
'
sha256sum "$OUT/bellhop.exe"
echo "bellhop.exe installed in $OUT (visible as /data/bin/bellhop.exe in ./pm.sh)"
