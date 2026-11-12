#!/bin/zsh
# Remaining ANVIL-029 container runs, back to back, all inside one hold of the host test lock.
set -u
H=/private/tmp/claude-501/-Users-nirtuttnauer--claude-spares-spare-hO9v2b/16289924-d1d6-4d91-97ef-4c6c6397c323/scratchpad/anvil029/harness
WT=/Users/nirtuttnauer/Documents/Code/modelanvil/.claude/worktrees/anvil-029
REL=/Users/nirtuttnauer/.cache/modelanvil-selfhost/releases/0.1.0
echo "batch-start $(date -u +%FT%TZ)"
$H/run_m1.sh lora 4g 4g 4
$H/run_m2.sh 7.5g 7680m 4 $REL $WT/scripts
$H/run_m2.sh 4g 4g 4 $REL $WT/scripts
$H/run_m1.sh fullsft 7.5g 7680m 4
$H/run_m1.sh fullsft 4g 4g 4
$H/run_m1.sh lora 7.5g-rerun 7680m 4
echo "batch-end $(date -u +%FT%TZ)"
