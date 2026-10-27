#!/usr/bin/env python3
"""Fail when a saved decision report misses its declared regression gate."""
import argparse
import json
import sys
from pathlib import Path

from modelanvil.core.evaluation_gate import gate_status


def main(argv=None):
    parser = argparse.ArgumentParser(description='Replay a decision report against a regression threshold.')
    parser.add_argument('report', type=Path)
    parser.add_argument('--max-regression', type=float, default=0.0)
    parser.add_argument('--allow-inconclusive', action='store_true')
    args = parser.parse_args(argv)
    status = gate_status(json.loads(args.report.read_text()), max_regression=args.max_regression,
        require_decisive=not args.allow_inconclusive)
    if status == 2:
        print('Decision report is unusable.', file=sys.stderr)
    elif status == 1:
        print('Decision report missed the regression gate.', file=sys.stderr)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
