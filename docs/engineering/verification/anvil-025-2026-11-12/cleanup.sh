#!/bin/zsh
# ANVIL-025 cleanup: stop and uninstall each host instance this run created, then remove its four data volumes.
# usage: cleanup.sh <live-dir>
set -u
L=$1; PY=/usr/bin/python3
for dir in instance rollback; do
  [ -f "$L/$dir/instance.json" ] || { echo "$dir: no instance.json"; continue; }
  P=$($PY -c 'import json,sys;print(json.load(open(sys.argv[1]))["compose_project"])' "$L/$dir/instance.json")
  case $P in modelanvil-local-*) ;; *) echo "refusing project $P"; exit 1;; esac
  $PY "$L/$dir/release/modelanvil.py" stop --directory "$L/$dir" > /dev/null; echo "$dir ($P) stop exit $?"
  $PY "$L/$dir/release/modelanvil.py" uninstall --directory "$L/$dir" > /dev/null; echo "$dir ($P) uninstall exit $?"
  docker volume rm ${P}_artifacts ${P}_caddy_config ${P}_certificates ${P}_database > /dev/null; echo "$dir ($P) volume rm exit $?"
  echo "$dir ($P) left: containers $(docker ps -aq --filter label=com.docker.compose.project=$P | wc -l | tr -d ' ') volumes $(docker volume ls -q --filter label=com.docker.compose.project=$P | wc -l | tr -d ' ') networks $(docker network ls -q --filter label=com.docker.compose.project=$P | wc -l | tr -d ' ')"
done
