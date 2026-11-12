#!/bin/zsh
# ANVIL-024 fresh-engine install: run scripts/install_selfhost.py inside a new docker:dind engine
# that has never seen ModelAnvil, then curl the health endpoint with the instance CA.
# usage: fresh_install.sh <worktree> <release-dir> <outdir>
set -u
WT=$1; REL=$2; OUT=$3
IMG=docker:dind@sha256:08a98015fce594af7c382883bea080ea206de74402a95da9dc52b6428c8cd121
NAME=anvil024-fresh
mkdir -p "$OUT"
docker rm -f $NAME > /dev/null 2>&1; docker volume rm anvil024-fresh-docker > /dev/null 2>&1
{
echo "start $(date -u +%FT%TZ)"
docker run -d --privileged --name $NAME --platform linux/arm64 \
  -v anvil024-fresh-docker:/var/lib/docker -v "$REL":/release:ro -v "$WT/scripts":/scripts:ro $IMG > /dev/null
for i in $(seq 1 60); do docker exec $NAME docker info > /dev/null 2>&1 && break; sleep 1; done
echo "inner engine images before install: $(docker exec $NAME docker images -q | wc -l | tr -d ' ')"
echo "inner engine volumes before install: $(docker exec $NAME docker volume ls -q | wc -l | tr -d ' ')"
docker exec $NAME apk add -q --no-progress python3 curl > /dev/null 2>&1; echo "apk exit $?"
docker exec $NAME python3 --version
docker exec $NAME sh -c 'python3 - > /work-creds.json <<EOF
import json, secrets
print(json.dumps({"email": "owner@fresh-install.test", "name": "Fresh install check", "password": secrets.token_urlsafe(24)}))
EOF
chmod 600 /work-creds.json'
T0=$(date +%s)
docker exec $NAME sh -c 'python3 /scripts/install_selfhost.py --directory /work/instance --release /release --http-port 18080 --https-port 18443 --credentials-stdin < /work-creds.json'
echo "install exit $? seconds $(( $(date +%s) - T0 ))"
echo "inner engine images after install: $(docker exec $NAME docker images --format '{{.Repository}}:{{.Tag}}' | sort | tr '\n' ' ')"
docker exec $NAME sh -c 'curl --fail --silent --show-error --cacert /work/instance/ca.crt https://localhost:18443/api/v1/health/; echo; echo "curl exit $?"'
docker exec $NAME sh -c 'python3 /work/instance/release/modelanvil.py stop --directory /work/instance > /dev/null; echo "stop exit $?"; python3 /work/instance/release/modelanvil.py uninstall --directory /work/instance > /dev/null; echo "uninstall exit $?"; rm -f /work-creds.json'
echo "end $(date -u +%FT%TZ)"
} > "$OUT/fresh-install.txt" 2>&1
docker rm -f $NAME > /dev/null 2>&1; docker volume rm anvil024-fresh-docker > /dev/null 2>&1
echo "cleanup: container $(docker ps -a -q -f name=$NAME | wc -l | tr -d ' ') volume $(docker volume ls -q -f name=anvil024-fresh-docker | wc -l | tr -d ' ')" >> "$OUT/fresh-install.txt"
cat "$OUT/fresh-install.txt"
