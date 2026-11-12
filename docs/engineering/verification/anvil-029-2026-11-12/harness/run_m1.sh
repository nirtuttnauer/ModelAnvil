#!/bin/zsh
# Host side of measurement 1 (and the supplementary full_sft variant). Run it under testlock.sh.
# usage: run_m1.sh <lora|fullsft> <size-label> <memory> <cpus>
set -u
W=$1 L=$2 M=$3 C=$4
SHA=56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7
IMG=python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
WT=/Users/nirtuttnauer/Documents/Code/modelanvil/.claude/worktrees/anvil-029
BASE=/private/tmp/claude-501/-Users-nirtuttnauer--claude-spares-spare-hO9v2b/16289924-d1d6-4d91-97ef-4c6c6397c323/scratchpad/anvil029
O=$BASE/m1-$W-$L
mkdir -p $O
name=anvil029-$W-$L
watch='docker build|docker-buildx|buildx|build_selfhost_release|qualify_selfhost|manage.py test|npm test|npm run|vitest|storybook|premerge|golden_path'
snapshot() {
  echo "== $(date -u +%FT%TZ)"; uptime
  docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
  pgrep -fl "$watch" | grep -v pgrep | cut -c1-240
  ls -d /tmp/modelanvil-test.lock 2>/dev/null
}
echo "lock-acquired $(date -u +%FT%TZ)" > $O/run-times.txt
# Let a concurrent image build (not covered by the test lock) finish first, at most 20 minutes.
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
docker run -d --name $name --platform linux/arm64 --memory $M --memory-swap $M --cpus $C \
  -e MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 \
  -v $WT:/src:ro -v $BASE/harness:/harness:ro -v $O:/out \
  $IMG sh /harness/m1-inner.sh $W $SHA > $O/container-id.txt
docker inspect $name --format 'Memory={{.HostConfig.Memory}} MemorySwap={{.HostConfig.MemorySwap}} NanoCpus={{.HostConfig.NanoCpus}} Image={{.Image}} Platform={{.Platform}}' > $O/hostconfig.txt
docker stats --format '{{.MemUsage}}|{{.CPUPerc}}' $name > $O/docker-stats.raw 2>/dev/null &
statspid=$!
( while :; do snapshot; sleep 30; done ) > $O/host-samples.txt 2>&1 &
hostpid=$!
code=$(docker wait $name)
kill $statspid $hostpid 2>/dev/null
echo "container-exit $(date -u +%FT%TZ) code=$code" >> $O/run-times.txt
docker logs -t $name > $O/container.log 2>&1
docker inspect $name --format '{{json .State}}' > $O/state.json
docker rm $name > /dev/null
snapshot > $O/host-after.txt 2>&1
echo "$W $L exit=$code"
# Appended while batch.sh was running: its two run_m2.sh lines failed with "permission denied"
# (the file was not executable). Run the two stack measurements here, inside the same lock hold.
if [ "$W" = lora ] && [ "$L" = 7.5g-rerun ]; then
  $BASE/harness/run_m2.sh 7.5g 7680m 4 /Users/nirtuttnauer/.cache/modelanvil-selfhost/releases/0.1.0 $WT/scripts
  $BASE/harness/run_m2.sh 4g 4g 4 /Users/nirtuttnauer/.cache/modelanvil-selfhost/releases/0.1.0 $WT/scripts
fi
