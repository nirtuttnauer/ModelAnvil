#!/bin/sh
# Supplementary run: the same clone, README install block and README train command as
# scripts/golden_path.sh, with the one training recipe argument in the cloned
# scripts/golden_path.py switched from lora_adapter to full_sft before training.
# usage: fullsft.sh <sha>
set -eu
SHA=$1
REMOTE=https://github.com/nirtuttnauer/ModelAnvil.git
export GIT_TERMINAL_PROMPT=0
d=$(mktemp -d /tmp/modelanvil-fullsft-XXXXXX)
echo "cloning $SHA into $d"
git init -q "$d"
git -C "$d" remote add origin "$REMOTE"
git -C "$d" fetch -q --depth 1 origin "$SHA"
git -C "$d" checkout -q --detach FETCH_HEAD
[ "$(git -C "$d" rev-parse HEAD)" = "$SHA" ]
cd "$d"
python3 -I -c 'import sys; sys.path.insert(0, "scripts"); import golden_path as g; t = open("README.md", encoding="utf-8").read(); print("\n".join(g.install_commands(t)))' > /tmp/fullsft-install.txt
python3 -I -c 'import sys; sys.path.insert(0, "scripts"); import golden_path as g; t = open("README.md", encoding="utf-8").read(); print(g.train_command(t, 3))' > /tmp/fullsft-train.txt
while IFS= read -r cmd; do
  echo "+ $cmd"
  bash -o pipefail -c "$cmd" < /dev/null
done < /tmp/fullsft-install.txt
[ "$(grep -c 'recipe="lora_adapter"' scripts/golden_path.py)" = 1 ]
sed -i 's/recipe="lora_adapter"/recipe="full_sft"/' scripts/golden_path.py
grep -n 'recipe="full_sft"' scripts/golden_path.py
train=$(cat /tmp/fullsft-train.txt)
echo "+ $train"
bash -o pipefail -c "$train" < /dev/null
cd /
rm -rf "$d"
echo "full_sft variant completed 3 SmolLM2-135M CPU steps and independent inference at $SHA"
