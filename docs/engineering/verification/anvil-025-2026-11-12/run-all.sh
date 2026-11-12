#!/bin/zsh
# ANVIL-025 live run under one hold of the host test lock: phase 1 (host drill), off-host restore in a fresh dind engine, cleanup.
# usage: run-all.sh <worktree> <release-0.1.0> <release-0.1.1> <live-dir>
set -u
WT=$1; REL0=$2; REL1=$3; L=$4; TOOLS=${0:A:h}
echo "lock acquired $(date -u +%FT%TZ)"
"$TOOLS/phase1.sh" "$WT" "$REL0" "$REL1" "$L"
grep -q 'drill exit 0 ' "$L/phase1.txt" || { echo "drill did not pass; instances kept for inspection"; exit 1; }
/usr/bin/python3 "$TOOLS/offhost_restore.py" "$WT" "$REL0" "$L/backup" "$L/record/baseline.json" "$L/owner-private.json" "$L/seed.json" "$L/offhost"
echo "offhost exit $?"
"$TOOLS/cleanup.sh" "$L" 2>&1 | tee "$L/cleanup.txt"
echo "run-all end $(date -u +%FT%TZ)"
