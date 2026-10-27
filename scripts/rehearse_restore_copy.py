#!/usr/bin/env python3
"""Copy a directory and print a rehearsal report. This does not claim a recovery time."""
import argparse
import json
import sys
from pathlib import Path

from modelanvil.core.restore_rehearsal import rehearse_copy


def main(argv=None):
    parser = argparse.ArgumentParser(description='Copy files and verify their bytes.')
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args(argv)
    try:
        report = rehearse_copy(args.source, args.destination)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
