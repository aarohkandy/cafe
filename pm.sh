#!/bin/sh
# Run a command for the pre-mission pipeline on homebase, in the cafe-pm image:  ./pm.sh make acceptance
# Syncs this checkout to ~/work/cafe/pm (never the live app's ~/work/cafe/src) without --delete, so outputs written
# on the server (report/, checkpoints/, config/throughput.json) survive; copy them back with ./pm.sh --pull.
H="azureuser@100.108.213.121"; K="$HOME/.ssh/homebase_ed25519"
if [ "$1" = "--pull" ]; then shift; for p in "$@"; do rsync -az -e "ssh -i $K" "$H:work/cafe/pm/$p" "./$(dirname "$p")/"; done; exit; fi
rsync -az --exclude .git --exclude __pycache__ --exclude site --exclude checkpoints --exclude cache -e "ssh -i $K" ./ "$H:work/cafe/pm/"
ssh -i "$K" "$H" "mkdir -p \$HOME/work/cafe/pmdata && docker run --rm --hostname \$(hostname) -u 1000:1000 --cpus ${PM_CPUS:-8} --memory ${PM_MEM:-28g} -e HOME=/tmp -e PYTHONPATH=/app -e CAFE_DATA=/data -v \$HOME/work/cafe/pm:/app -v \$HOME/work/cafe/pmdata:/data -v \$HOME/work/cafe/data:/work:ro -w /app cafe-pm $*"
