(
T=$(mktemp -d /tmp/proot_test.XXXXXX); trap 'cd /; rm -rf "$T"; echo "== cleaned $T"' EXIT; cd "$T" || exit 1
B=https://github.com/proot-me/proot/releases/download/v5.5.0/proot
U=https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.3-base-amd64.tar.gz
echo "== fetch"; curl -fsSL "$B" -o proot && curl -fsSL "$U" -o base.tgz || { echo FETCH-FAILED; exit 1; }
printf '%s  proot\n%s  base.tgz\n' db185300a9daabbce86aca7632d8c7fdc4249f6f153171954013b70c5f491ec0 6bc2cde3930ad088b3bb46fa45279e96d25bc3810f209850ecbe4722711874f9 | sha256sum -c - || { echo CHECKSUM-FAILED; exit 1; }
chmod +x proot; mkdir r; tar xzf base.tgz -C r --exclude='dev/*' 2>/dev/null; du -sh r | cut -f1
export PROOT_TMP_DIR="$T" PROOT_VERBOSE=-1
P_="./proot -r r -0 -w / -b /proc -b /dev -b /sys -b $T:/scratch"
echo "== host"; grep -h PRETTY /etc/os-release; ldd --version 2>&1 | head -1
echo "== inside"; $P_ /bin/sh -c 'grep -h PRETTY /etc/os-release; ldd --version 2>&1 | head -1; id -un; echo inside-ok' 2>&1 | tail -5
echo "== no-seccomp mode"; PROOT_NO_SECCOMP=1 $P_ /bin/sh -c 'echo noseccomp-ok' 2>&1 | tail -2
L='i=0; while [ $i -lt 1000 ]; do /bin/true; i=$((i+1)); done'
C='i=0; while [ $i -lt 1000000 ]; do i=$((i+1)); done'
F='i=0; while [ $i -lt 2000 ]; do : > /scratch/x$((i%50)); i=$((i+1)); done'
ms() { a=$(date +%s%N); "$@" >/dev/null 2>&1; r=$?; b=$(date +%s%N); echo "$(( (b-a)/1000000 )) ms (rc=$r)"; }
mkdir -p n; FN=$(printf '%s' "$F" | sed "s#/scratch#$T/n#")
echo "== speed: host then proot"
echo "spawn host  $(ms /bin/sh -c "$L")"; echo "spawn proot $(ms $P_ /bin/sh -c "$L")"
echo "cpu   host  $(ms /bin/sh -c "$C")"; echo "cpu   proot $(ms $P_ /bin/sh -c "$C")"
echo "files host  $(ms /bin/sh -c "$FN")"; echo "files proot $(ms $P_ /bin/sh -c "$F")"
echo "== done"
)
