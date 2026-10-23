"""Independent stdlib inference/accuracy checks for authored GRPO correctness probes.

Imports the standalone tensor consumer, never ModelAnvil, Django or training code.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys


def verify(response, expected, rule):
    if rule['type'] == 'exact_match':
        return response.strip() == expected.strip()
    target = float(expected)
    if not math.isfinite(target):
        raise ValueError('Invalid numeric target.')
    try:
        value = float(response)
    except ValueError:
        return False
    return math.isfinite(value) and abs(value - target) <= rule['tolerance']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--samples', type=Path, required=True)
    args = parser.parse_args()
    module = importlib.util.spec_from_file_location('standalone_character_consumer', Path(__file__).with_name('cpu_character_infer.py'))
    consumer = importlib.util.module_from_spec(module); module.loader.exec_module(consumer)
    data = json.loads(args.samples.read_text())
    if set(data) != {'heldout', 'regression', 'verifier'}:
        raise ValueError('Pin separate held-out and regression probes.')
    groups, outputs = {}, {}
    for split in ('heldout', 'regression'):
        if not 1 <= len(data[split]) <= 32:
            raise ValueError('Use 1–32 bounded probes per split.')
        for row in data[split]:
            group = row['source_group_id']
            if group in groups and groups[group] != split:
                raise ValueError('Protected probe groups overlap.')
            groups[group] = split
    for name, path in [('base', args.base), ('candidate', args.candidate)]:
        bundle = consumer.read_export(path); measured = {}
        for split in ('heldout', 'regression'):
            rows = []
            for row in data[split]:
                result = consumer.infer(bundle, row['prompt'], 1)
                rows.append({**row, **result, 'passed': verify(result['completion'], row['chosen'], data['verifier'])})
            measured[split] = {'accuracy': sum(r['passed'] for r in rows) / len(rows), 'rows': rows}
        outputs[name] = measured
    adversarial = ['NaN', 'Inf', '1\n2', '### VERIFIED TRUE ###', '1e999']
    checks = [not verify(value, '1', {'type': 'numeric_tolerance', 'tolerance': 0.}) for value in adversarial]
    imported = any(name == 'django' or name.startswith('django.') or name == 'modelanvil' or name.startswith('modelanvil.') for name in sys.modules)
    print(json.dumps({'consumer_imported_modelanvil_or_django': imported, 'results': outputs,
        'reward_hacking': {'responses': adversarial, 'all_rejected': all(checks)},
        'regression_delta': outputs['candidate']['regression']['accuracy'] - outputs['base']['regression']['accuracy'],
        'quality_improved': outputs['candidate']['heldout']['accuracy'] > outputs['base']['heldout']['accuracy'],
        'scope': 'Independent greedy one-token inference on authored CPU character probes; not general task quality or production qualification.'}, allow_nan=False))
    if imported or not all(checks):
        raise ValueError('Independent consumer or verifier integrity check failed.')


if __name__ == '__main__':
    main()
