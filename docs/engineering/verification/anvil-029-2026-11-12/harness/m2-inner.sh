#!/bin/sh
# Runs through docker exec inside the size-limited docker:dind container.
# usage: m2-inner.sh   (release at /release, qualify_selfhost.py at /qual, results to /out)
set -u
O=/out
cg=/sys/fs/cgroup
{ echo "memory.max $(cat $cg/memory.max)"; echo "memory.swap.max $(cat $cg/memory.swap.max)"; echo "cpu.max $(cat $cg/cpu.max)"; echo "nproc $(nproc)"; uname -a; echo "self cgroup: $(cat /proc/self/cgroup)"; ls $cg; } > $O/cgroup-limits.txt 2>&1
cat $cg/memory.peak > $O/memory.peak-after-engine-start.txt
echo "apk-start $(date -u +%FT%TZ)"
if ! apk add -q --no-progress python3 time > $O/apk.log 2>&1; then echo "apk add failed" >&2; exit 90; fi
{ python3 --version; /usr/bin/time --version; docker version --format 'client {{.Client.Version}} server {{.Server.Version}}'; docker compose version; } > $O/tool-versions.txt 2>&1
# Two-second sampler. T: whole container (epoch, memory.current, anon, file).
# C: one inner container (epoch, id, name, memory.peak, memory.current, anon). E: inner engine cgroup.
( while :; do
    now=$(date +%s)
    a=; f=
    while read -r k v; do case $k in anon) a=$v ;; file) f=$v ;; esac; done < $cg/memory.stat
    echo "T $now $(cat $cg/memory.current) $a $f"
    [ -f $cg/init/memory.peak ] && echo "E $now init $(cat $cg/init/memory.peak) $(cat $cg/init/memory.current)"
    for d in $cg/docker/*/; do
      [ -f "${d}memory.peak" ] || continue
      id=$(basename "$d")
      n=$(grep -o '"Name":"/[^"]*"' "/var/lib/docker/containers/$id/config.v2.json" 2>/dev/null | head -1 | cut -d'"' -f4)
      a2=
      while read -r k v; do [ "$k" = anon ] && a2=$v; done < "${d}memory.stat"
      echo "C $now $id ${n:-?} $(cat "${d}memory.peak") $(cat "${d}memory.current") $a2"
    done
    sleep 2
  done >> $O/cgroup-samples.txt ) &
sampler=$!
mkdir -p /work
cd /work
echo "measure-start $(date -u +%FT%T.%NZ)"
/usr/bin/time -v -o $O/time-v.txt python3 /qual/qualify_selfhost.py --release /release --output /work/qualification
code=$?
echo "measure-end $(date -u +%FT%T.%NZ) exit=$code"
echo $code > $O/exit-code.txt
cat $cg/memory.peak > $O/memory.peak.txt
cat $cg/memory.events > $O/memory.events.txt
cat $cg/memory.stat > $O/memory.stat-end.txt
[ -f $cg/init/memory.peak ] && cat $cg/init/memory.peak > $O/engine-init.memory.peak.txt
kill $sampler 2>/dev/null
ls -la /work/qualification > $O/qualification-files.txt 2>&1
cp /work/qualification/qualification.json $O/qualification.json 2>/dev/null
mkdir -p $O/private
for f in /work/qualification/*.json /work/qualification/*-private.log; do
  case $f in *credentials-private.json) continue ;; esac
  [ -f "$f" ] && cp "$f" $O/private/
done
{ docker ps -a --format '{{.Names}} {{.Status}}'; docker volume ls --format '{{.Name}}'; } > $O/inner-leftovers.txt 2>&1
exit $code
