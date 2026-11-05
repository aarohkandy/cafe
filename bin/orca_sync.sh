#!/bin/sh
# Put what cafe jobs need on orca: proot, the cafe-pm root filesystem (the image, flattened) and the data. Streamed from homebase, where the image and data live, through
# pipes: nothing is written on homebase, whose disk is full, and nothing passes through this laptop.
#   sh bin/orca_sync.sh <orca tailnet IP> [proot] [root] [pmdata] [data]      about 18 GB; run bin/orca_setup.sh on orca first, it prints the IP
# No parts named: whatever is missing is copied (root also when the cafe-pm image has changed), so a cut stream is resumed by running it again; a part restarts from its start.
# Parts named: those are copied again. Orca's host key must already be in homebase's known_hosts; ORCA_TOFU=1 trusts it on first contact and prints the fingerprint.
# CAFE_MIN_FREE_GB (default 25) is the room orca must have. For a rehearsal without orca: ORCA_VIA=<ssh name of a host with docker and the image> ORCA_SRC='sh -c' ORCA_DST='docker exec -i <container> sh -c' (arguments split on spaces).
set -eu
IP="${1:?usage: sh bin/orca_sync.sh <orca tailnet IP> [proot] [root] [pmdata] [data]}"; shift
VIA="${ORCA_VIA:-azureuser@100.108.213.121}"; K="${PM_KEY:-$HOME/.ssh/homebase_ed25519}"
O="${ORCA_TOFU:+-o StrictHostKeyChecking=accept-new}"
DST="${ORCA_DST:-ssh $O -p 2222 -i .ssh/burst_ed25519 intern@$IP}"           # run on VIA: homebase's key for the burst VM is the one orca_setup.sh authorizes
q() { printf "'%s' " "$(printf %s "$1" | sed "s/'/'\\\\''/g")"; }                  # ssh joins its arguments into one line for the remote shell: quote each
ssh -i "$K" "$VIA" bash -s -- "$(q "${ORCA_SRC:-sh -c}")" "$(q "$DST")" "$(q "$*")" "$(q "${O:+tofu}")" "$(q "$IP")" "$(q "${CAFE_MIN_FREE_GB:-25}")" <<'EOF'
set -euo pipefail
S=$1; D=$2; PARTS=$3; TOFU=$4; IP=$5; MIN=$6
[ -z "$TOFU" ] || ssh-keyscan -p 2222 "$IP" 2>/dev/null | ssh-keygen -lf -     # compare with the fingerprint of ~/cafe-worker/ssh/host_ed25519.pub on orca
$D 'test -f cafe-worker/.cafe-worker-owned' </dev/null || { echo "STOP: cafe-worker is not set up on orca: run bin/orca_setup.sh there" >&2; exit 1; }
free=$($D 'df -Pk . | awk "NR==2{print int(\$4/1048576)}"' </dev/null); [ "$free" -ge "$MIN" ] || { echo "STOP: only $free GB free on orca's shared disk, 25 GB needed" >&2; exit 1; }
want() { case " $PARTS " in *" $1 "*) return 0 ;; esac; return 1; }          # named on the command line: copy again
todo() { want "$1" || { [ -z "$PARTS" ] && ! $D "$2" </dev/null; }; }          # none named: copy when $2 (run on orca) says it is not there
step() { echo "== $1 $(date +%T)"; }

if todo proot 'test -x cafe-worker/bin/proot'; then
  step proot                                       # the release binary, pinned: the same checksum as docs/orca/proot_test.sh
  $D 'mkdir -p cafe-worker/bin && cd cafe-worker/bin && curl -fsSL https://github.com/proot-me/proot/releases/download/v5.5.0/proot -o proot.new && echo "db185300a9daabbce86aca7632d8c7fdc4249f6f153171954013b70c5f491ec0  proot.new" | sha256sum -c - && chmod +x proot.new && mv proot.new proot' </dev/null
fi

id=$($S 'docker image inspect -f {{.Id}} cafe-pm:latest' </dev/null)
if todo root "test \"\$(cat cafe-worker/root.done 2>/dev/null)\" = $id"; then
  step "root $id"
  $D 'rm -rf cafe-worker/root.new && mkdir cafe-worker/root.new' </dev/null
  # dev/* is the container's own device nodes: proot binds the host's. Everything else extracts without root (--no-same-owner) and proot shows it owned by the user.
  $S 'c=$(docker create cafe-pm:latest true); trap "docker rm $c >/dev/null" EXIT; docker export $c | gzip -1' </dev/null | $D 'tar xzf - -C cafe-worker/root.new --no-same-owner --exclude="dev/*"'
  $D 'cd cafe-worker && test -x root.new/usr/bin/env && test -d root.new/venv/lib && rm -rf root && mv root.new root' </dev/null || { echo "STOP: the root filesystem did not extract completely" >&2; exit 1; }
  $D "printf %s $id > cafe-worker/root.done" </dev/null
fi

for p in pmdata data; do
  if todo $p "test -f cafe-worker/$p.done"; then
    step $p
    if [ $p = pmdata ]; then dirs="bin dtmb5415 bathy tao cache ocean"; else dirs=.; fi      # the same as bin/worker_setup.sh copies
    $S "cd work/cafe/$p && tar cf - $dirs | gzip -1" </dev/null | $D "mkdir -p work/cafe/$p && tar xzf - -C work/cafe/$p --no-same-owner"
    $D "touch cafe-worker/$p.done" </dev/null
  fi
done
step done
EOF
