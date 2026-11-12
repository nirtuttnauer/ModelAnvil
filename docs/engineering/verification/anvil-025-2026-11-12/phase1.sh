#!/bin/zsh
# ANVIL-025 phase 1 (host engine): install 0.1.0, seed data, run the drill (backup, upgrade to 0.1.1, rollback restore).
# usage: phase1.sh <worktree> <release-0.1.0> <release-0.1.1> <live-dir>
set -u
WT=$1; REL0=$2; REL1=$3; L=$4; PY=/usr/bin/python3; TOOLS=${0:A:h}
umask 077
mkdir -p "$L"
log() { echo "$(date -u +%FT%TZ) $*"; }
{
log "phase1 start; python $($PY -c 'import sys;print(sys.version.split()[0])')"
$PY - > "$L/owner-private.json" <<PYEOF
import json, secrets
print(json.dumps({"email": "owner@drill-anvil025.test", "name": "ANVIL-025 drill", "password": secrets.token_urlsafe(24)}))
PYEOF
log "credentials file mode $(stat -f %Lp "$L/owner-private.json")"
T0=$(date +%s)
$PY "$WT/scripts/install_selfhost.py" --directory "$L/instance" --release "$REL0" --http-port 41080 --https-port 41443 --credentials-stdin \
  < "$L/owner-private.json" > "$L/install.json" 2> "$L/install-private.log"
log "install exit $? seconds $(( $(date +%s) - T0 ))"
cat "$L/install.json"
curl --fail --silent --show-error --cacert "$L/instance/ca.crt" https://localhost:41443/api/v1/health/; echo " health curl exit $?"
T0=$(date +%s)
$PY "$TOOLS/seed.py" seed "$WT/scripts" "$L/instance" "$L/owner-private.json" > "$L/seed.json" 2> "$L/seed-private.log"
log "seed exit $? seconds $(( $(date +%s) - T0 ))"
cat "$L/seed.json"
T0=$(date +%s)
$PY "$WT/scripts/drill_selfhost.py" run --directory "$L/instance" --previous-release "$REL0" --release "$REL1" \
  --backup "$L/backup" --upgrade-backup "$L/upgrade-backup" --rollback-directory "$L/rollback" --record "$L/record" \
  --rollback-http-port 42080 --rollback-https-port 42443 > "$L/drill-stdout.json" 2> "$L/drill-stderr.txt"
log "drill exit $? seconds $(( $(date +%s) - T0 ))"
cat "$L/drill-stderr.txt"
for port dir in 41443 instance 42443 rollback; do
  curl --fail --silent --show-error --cacert "$L/$dir/ca.crt" https://localhost:$port/api/v1/health/; echo " $dir health curl exit $?"
  curl --fail --silent --show-error --cacert "$L/$dir/ca.crt" https://localhost:$port/api/v1/ready/; echo " $dir ready curl exit $?"
done
MODELS=($($PY -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["imported_model"],d["trained_model"])' "$L/seed.json"))
$PY "$TOOLS/seed.py" chat "$WT/scripts" "$L/rollback" "$L/owner-private.json" $MODELS > "$L/chat-rollback.json" 2> "$L/chat-rollback-private.log"
log "rollback chat exit $?"
cat "$L/chat-rollback.json"
$PY "$TOOLS/seed.py" chat "$WT/scripts" "$L/instance" "$L/owner-private.json" $MODELS > "$L/chat-upgraded.json" 2> "$L/chat-upgraded-private.log"
log "upgraded chat exit $?"
cat "$L/chat-upgraded.json"
log "phase1 end"
} 2>&1 | tee "$L/phase1.txt"
