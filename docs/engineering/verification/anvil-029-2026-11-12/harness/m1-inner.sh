#!/bin/sh
# Runs as the container command inside python:3.12-slim-bookworm with the size limits.
# usage: m1-inner.sh <lora|fullsft> <sha>
set -u
W=$1
SHA=$2
O=/out
cg=/sys/fs/cgroup
{ echo "memory.max $(cat $cg/memory.max)"; echo "memory.swap.max $(cat $cg/memory.swap.max)"; echo "cpu.max $(cat $cg/cpu.max)"; echo "nproc $(nproc)"; uname -a; } > $O/cgroup-limits.txt 2>&1
# One-second cgroup sampler: epoch, memory.current, anon, file (bytes).
( while :; do
    a=; f=
    while read -r k v; do
      case $k in anon) a=$v ;; file) f=$v ;; esac
    done < $cg/memory.stat
    echo "$(date +%s) $(cat $cg/memory.current) $a $f"
    sleep 1
  done >> $O/cgroup-samples.txt ) &
sampler=$!
export DEBIAN_FRONTEND=noninteractive
echo "apt-start $(date -u +%FT%T.%NZ)"
if ! { apt-get update -qq && apt-get install -y -qq --no-install-recommends git time make ca-certificates; } > $O/apt.log 2>&1; then
  echo "apt-get failed" >&2
  kill $sampler 2>/dev/null
  exit 90
fi
cat $cg/memory.peak > $O/memory.peak-after-apt.txt
/usr/bin/time --version > $O/gnu-time-version.txt 2>&1
git --version >> $O/gnu-time-version.txt 2>&1
echo "measure-start $(date -u +%FT%T.%NZ)"
cd /src
if [ "$W" = lora ]; then
  /usr/bin/time -v -o $O/time-v.txt sh scripts/golden_path.sh "$SHA" --steps 3
else
  /usr/bin/time -v -o $O/time-v.txt sh /harness/fullsft.sh "$SHA"
fi
code=$?
echo "measure-end $(date -u +%FT%T.%NZ) exit=$code"
echo $code > $O/exit-code.txt
cat $cg/memory.peak > $O/memory.peak.txt
cat $cg/memory.events > $O/memory.events.txt
cat $cg/memory.stat > $O/memory.stat-end.txt
kill $sampler 2>/dev/null
exit $code
