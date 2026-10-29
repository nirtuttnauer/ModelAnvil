#!/usr/bin/env python3
"""One pinned CPU character evaluation. The policy and reference are not modified."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "modelanvil.settings")

from modelanvil.runners.cpu_character_eval_repeat import main

if __name__ == "__main__":
    raise SystemExit(main())
