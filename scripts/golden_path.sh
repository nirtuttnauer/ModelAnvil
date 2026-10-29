#!/bin/sh
# Clone a pinned SHA, run the README CPU install, and train a few SmolLM2-135M steps.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
exec python3 "$root/scripts/golden_path.py" "$@"
