#!/bin/zsh
# Host side of measurement 2: the self-host qualification inside a size-limited docker:dind.
# Run it under testlock.sh.
# usage: run_m2.sh <size-label> <memory> <cpus> <release-dir> <dir-holding-qualify_selfhost.py>
set -u
L=$1 M=$2 C=$3 REL=$4 QS=$5
IMG=docker:dind@sha256:08a98015fce594af7c382883bea080ea206de74402a95da9dc52b6428c8cd121
BASE=/private/tmp/claude-501/-Users-nirtuttnauer--claude-spares-spare-hO9v2b/16289924-d1d6-4d91-97ef-4c6c6397c323/scratchpad/anvil029
O=$BASE/m2-$L
mkdir -p $O
name=anvil029-stack-$L
vol=anvil029-dind-$L
watch='docker build|docker-buildx|buildx|build_selfhost_release|qualify_selfhost|manage.py test|npm test|npm run|vitest|storybook|premerge|golden_path'
snapshot() {
  echo "== $(date -u +%FT%TZ)"; uptime
  docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
  pgrep -fl "$watch" | grep -v pgrep | cut -c1-240
}
echo "lock-acquired $(date -u +%FT%TZ)" > $O/run-times.txt
for i in {1..240}; do
  busy=no
  pgrep -f 'build_selfhost_release|docker build|docker-buildx' > /dev/null && busy=yes
  docker ps --format '{{.Names}}' | grep -q '^modelanvil-local-' && busy=yes
  [ $busy = no ] && break
  sleep 5
done
echo "build-wait-end $(date -u +%FT%TZ) polls=$i" >> $O/run-times.txt
snapshot > $O/host-before.txt 2>&1
docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}' >> $O/host-before.txt 2>&1
docker volume create --label anvil029=1 $vol > /dev/null
echo "dind-start $(date -u +%FT%TZ)" >> $O/run-times.txt
docker run -d --privileged --name $name --platform linux/arm64 --memory $M --memory-swap $M --cpus $C \
  -v $vol:/var/lib/docker -v $REL:/release:ro -v $QS:/qual:ro -v $BASE/harness:/harness:ro -v $O:/out \
  $IMG > $O/container-id.txt
docker inspect $name --format 'Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}} NanoCpus={{.HostConfig.NanoCpus}} Privileged={{.HostConfig.Privileged}} Image={{.Image}} Platform={{.Platform}}' > $O/hostconfig.txt
docker stats --format '{{.MemUsage}}|{{.CPUPerc}}' $name > $O/docker-stats.raw 2>/dev/null &
statspid=$!
( while :; do snapshot; sleep 30; done ) > $O/host-samples.txt 2>&1 &
hostpid=$!
ready=no
for i in {1..90}; do
  if docker exec $name docker info > /dev/null 2>&1; then ready=yes; break; fi
  sleep 2
done
echo "engine-ready=$ready $(date -u +%FT%TZ)" >> $O/run-times.txt
code=99
if [ $ready = yes ]; then
  docker exec $name sh /harness/m2-inner.sh 2>&1 | while IFS= read -r line; do print -r -- "$(date -u +%FT%TZ) $line"; done > $O/exec.log
  code=${pipestatus[1]}
fi
echo "exec-exit $(date -u +%FT%TZ) code=$code" >> $O/run-times.txt
kill $statspid $hostpid 2>/dev/null
docker logs -t $name > $O/dind.log 2>&1
docker inspect $name --format '{{json .State}}' > $O/state.json
docker stop -t 30 $name > /dev/null
docker rm -v $name > /dev/null
docker volume rm $vol > /dev/null
snapshot > $O/host-after.txt 2>&1
echo "stack $L exit=$code"
