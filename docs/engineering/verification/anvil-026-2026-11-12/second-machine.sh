#!/bin/zsh
# ANVIL-026: clean install on a second, never-used environment, then the golden path there.
# The "second machine" is a new docker:dind engine with an empty /var/lib/docker volume inside the
# Docker Desktop VM of Nir's Mac (Nir chose this reset environment on 2026-11-12).
# usage: second-machine.sh <release-dir> <repo-sha>
set -u
REL=$1; SHA=$2
DIND=docker:dind@sha256:08a98015fce594af7c382883bea080ea206de74402a95da9dc52b6428c8cd121
PY=python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
NAME=anvil026-second
SCRIPTS=$(cd "$(dirname "$0")/../../../.." && pwd)/scripts
rc=0
step() { echo; echo "== $1 $(date -u +%FT%TZ)"; }
docker rm -f $NAME > /dev/null 2>&1; docker volume rm anvil026-second-docker > /dev/null 2>&1
step "start fresh engine"
docker run -d --privileged --name $NAME --platform linux/arm64 \
  -v anvil026-second-docker:/var/lib/docker -v "$REL":/release:ro -v "$SCRIPTS":/scripts:ro $DIND > /dev/null || exit 3
for i in $(seq 1 60); do docker exec $NAME docker info > /dev/null 2>&1 && break; sleep 1; done
docker exec $NAME docker version --format 'inner engine {{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}'
echo "images before: $(docker exec $NAME docker images -q | wc -l | tr -d ' ')"
echo "volumes before: $(docker exec $NAME docker volume ls -q | wc -l | tr -d ' ')"
echo "containers before: $(docker exec $NAME docker ps -aq | wc -l | tr -d ' ')"
docker exec $NAME apk add -q --no-progress python3 curl > /dev/null 2>&1; echo "apk exit $?"
docker exec $NAME python3 --version

step "install release with scripts/install_selfhost.py"
docker exec $NAME sh -c 'python3 -c "import json,secrets;print(json.dumps({\"email\":\"owner@second-machine.test\",\"name\":\"Second machine check\",\"password\":secrets.token_urlsafe(24)}))" > /work-creds.json && chmod 600 /work-creds.json'
docker exec $NAME sh -c 'python3 /scripts/install_selfhost.py --directory /work/instance --release /release --http-port 18080 --https-port 18443 --credentials-stdin < /work-creds.json'
code=$?; echo "install exit $code"; [ $code -eq 0 ] || rc=1
step "health"
docker exec $NAME sh -c 'curl --fail --silent --show-error --cacert /work/instance/ca.crt https://localhost:18443/api/v1/health/; echo; echo "curl exit $?"'
docker exec $NAME sh -c 'python3 /work/instance/release/modelanvil.py status --directory /work/instance'
echo "status exit $?"
docker exec $NAME sh -c 'python3 /work/instance/release/modelanvil.py stop --directory /work/instance > /dev/null; echo "stop exit $?"; python3 /work/instance/release/modelanvil.py uninstall --directory /work/instance > /dev/null; echo "uninstall exit $?"; rm -f /work-creds.json'

step "release qualification on the installed package (train and infer)"
docker exec $NAME sh -c 'mkdir -p /work/q && cd /work/q && python3 /scripts/qualify_selfhost.py --release /release --output /work/q/qualification > /work/q/stdout.txt 2>&1; code=$?; tail -c 1500 /work/q/stdout.txt; exit $code'
code=$?; echo "qualify exit $code"; [ $code -eq 0 ] || rc=1
docker exec $NAME sh -c 'python3 - <<EOF
import json, pathlib
p = pathlib.Path("/work/q/qualification")
files = sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
print("qualification files:", len(files))
for f in files:
    if f.endswith(".json") and "private" not in f:
        try:
            d = json.loads((p / f).read_text())
        except Exception:
            continue
        if isinstance(d, dict):
            print(f, {k: d[k] for k in list(d)[:12] if not isinstance(d[k], (dict, list))})
EOF'

step "golden path from a clean clone at $SHA in a fresh python container on the second engine"
docker exec $NAME docker run --rm -e MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1 $PY sh -c "
  apt-get update -qq > /dev/null && apt-get install -y -qq --no-install-recommends git make ca-certificates > /dev/null &&
  git clone --quiet https://github.com/nirtuttnauer/ModelAnvil.git /src && cd /src && git checkout --quiet $SHA &&
  sh scripts/golden_path.sh $SHA --steps 3"
code=$?; echo "golden path exit $code"; [ $code -eq 0 ] || rc=1

step "cleanup"
docker rm -f $NAME > /dev/null 2>&1; docker volume rm anvil026-second-docker > /dev/null 2>&1
echo "left: containers $(docker ps -aq -f name=$NAME | wc -l | tr -d ' ') volumes $(docker volume ls -q -f name=anvil026-second-docker | wc -l | tr -d ' ')"
exit $rc
