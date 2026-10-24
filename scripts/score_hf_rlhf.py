"""Independent offline CPU reward/policy scoring; no Django or ModelAnvil imports."""
import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys
import time


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def read_json(path):
    with path.open('rb') as stream: raw = stream.read(1024**2 + 1)
    if not 0 < len(raw) <= 1024**2: raise ValueError('Scoring JSON must fit within 1 MiB.')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def reward_scores(model, head, pair):
    import torch
    scores = []
    for key in ('chosen', 'rejected'):
        ids = torch.tensor([pair[key]], dtype=torch.long, device='cpu')
        hidden = model.model(input_ids=ids, use_cache=False).last_hidden_state[0]
        # Independent consumer pooling and dot product, including every actual response token and EOS.
        scores.append(float(torch.dot(hidden[pair['prompt_tokens']:].mean(0).float(), head)))
    if not all(math.isfinite(s) for s in scores): raise ValueError('Non-finite reward scores.')
    return scores


def ranking(rows):
    losses, predictions, inspection = [], [], []
    for chosen, rejected in rows:
        margin = chosen - rejected
        probability = 1 / (1 + math.exp(-max(-80., min(80., margin))))
        losses.append(max(-margin, 0.) + math.log1p(math.exp(-abs(margin))))
        # Both orientations avoid a meaningless all-positive reliability diagram; pairs remain the independent sample count.
        predictions.extend([(probability, 1), (1 - probability, 0)])
        inspection.append({'chosen_score': chosen, 'rejected_score': rejected, 'preferred_probability': probability})
    bins = []
    for index in range(5):
        values = [(p, y) for p, y in predictions if min(4, int(p * 5)) == index]
        if values: bins.append({'lower': index / 5, 'upper': (index + 1) / 5, 'orientation_count': len(values),
            'mean_probability': sum(p for p, y in values) / len(values), 'observed_fraction': sum(y for p, y in values) / len(values)})
    return {'pair_count': len(rows), 'accuracy': sum(1. if a > b else .5 if a == b else 0. for a, b in rows) / len(rows),
        'pair_log_loss': sum(losses) / len(losses), 'brier_score': sum((p - y)**2 for p, y in predictions) / len(predictions),
        'calibration_bins': bins, 'scores': inspection}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'candidate', 'preferences', 'regression', 'manifest'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120)); signal.alarm(125)
    if sys.platform.startswith('linux'): resource.setrlimit(resource.RLIMIT_AS, (8 * 1024**3, 8 * 1024**3))
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    from transformers import AutoTokenizer
    from safetensors.torch import load_file
    torch.set_num_threads(1); torch.set_default_device('cpu')
    started, cpu = time.monotonic(), time.process_time()
    root = Path(__file__).resolve().parents[1]
    helpers = load_source('independent_score_helpers', root / 'scripts/score_dpo_candidate.py')
    consumer = load_source('independent_hf_consumer', root / 'scripts/hf_candidate_infer.py')
    encoding = load_source('independent_token_boundaries', root / 'modelanvil/runners/alignment/torch_dpo.py')
    grouping = load_source('independent_source_groups', root / 'modelanvil/runners/alignment/preference_groups.py')
    manifest, manifest_sha = read_json(args.manifest)
    role = manifest['role']
    names = {'model.safetensors', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'}
    if role not in ('reward', 'policy') or set(manifest['base_files']) != names:
        raise ValueError('Independent RLHF requires its complete pinned base and explicit model role.')
    candidate_names = names if role == 'reward' else names | {'adapter_model.safetensors', 'adapter_config.json'}
    if set(manifest['candidate_files']) != candidate_names: raise ValueError('Incomplete RLHF candidate manifest.')
    hashes = {'base': helpers.verify_files(args.base, manifest['base_files']),
        'candidate': helpers.verify_files(args.candidate, manifest['candidate_files'])}
    if any(hashes['base'][n] != hashes['candidate'][n] for n in names):
        raise ValueError('RLOO and reward-head candidates must preserve the exact frozen base.')
    tokenizer = AutoTokenizer.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    data, groups, prompts, digests = {}, {}, {}, {}
    for name in ('preferences', 'regression'):
        value, sha = read_json(getattr(args, name)); digests[name] = sha
        if sha != manifest[name + '_sha256'] or value.get('schema_version') != 'modelanvil.preference-pairs.v1':
            raise ValueError('Independent RLHF dataset identity differs.')
        pairs = value.get('pairs')
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32: raise ValueError('Scoring requires 1–32 pairs.')
        groups[name], prompts[name], data[name] = set(), set(), []
        for pair in pairs:
            if any(not isinstance(pair.get(k), str) or not pair[k].strip() for k in ('prompt', 'chosen', 'rejected')):
                raise ValueError('Invalid protected preference row.')
            prompt = pair['prompt'].strip()
            if prompt in prompts[name]: raise ValueError('Protected prompts must be unique.')
            prompts[name].add(prompt); groups[name].add(grouping.source_group(pair, required=True))
            data[name].append(encoding.encode_pair(tokenizer, pair))
    if (groups['preferences'] & groups['regression'] or prompts['preferences'] & prompts['regression']
            or (groups['preferences'] | groups['regression']) & set(manifest['training_groups'])
            or (prompts['preferences'] | prompts['regression']) & set(manifest['training_prompts'])):
        raise ValueError('Independent protected groups or prompts overlap training data.')
    with torch.inference_mode():
        base = consumer.load_candidate(args.base).eval()
        if role == 'reward':
            path = args.candidate / 'reward_head.safetensors'
            if path.is_symlink() or not 1 <= path.stat().st_size <= 8192:
                raise ValueError('Reward head exceeds its fixed scalar-head shape.')
            hashes['reward_head'] = hashlib.sha256(path.read_bytes()).hexdigest()
            if hashes['reward_head'] != manifest['reward_head_sha256']: raise ValueError('Reward head checksum differs.')
            saved = load_file(str(path), device='cpu')
            if set(saved) != {'weight'} or saved['weight'].shape != (1, 576) or saved['weight'].dtype != torch.float32:
                raise ValueError('Reward head must be one CPU FP32 scalar projection over 576 features.')
            head = saved['weight'][0]
            if not torch.isfinite(head).all().item() or not torch.count_nonzero(head): raise ValueError('Reward head has no finite learned weights.')
            candidate = ranking([reward_scores(base, head, p) for p in data['preferences']])
            regression = ranking([reward_scores(base, head, p) for p in data['regression']])
            baseline = ranking([[0., 0.] for _ in data['preferences']])
            checks = {'ranking_above_chance': candidate['accuracy'] >= .5,
                'heldout_log_loss_not_regressed': candidate['pair_log_loss'] <= math.log(2) + 1e-6,
                'separate_regression_ranking_above_chance': regression['accuracy'] >= .5}
        else:
            def score(model):
                rows = [[helpers.response_score(model, p, k) for k in ('chosen', 'rejected')] for p in data['preferences']]
                result = ranking(rows)
                nll = -sum(helpers.response_score(model, p, 'chosen') for p in data['regression'])
                result['regression_loss'] = nll / sum(len(p['chosen']) - p['prompt_tokens'] for p in data['regression'])
                return result
            baseline = score(base); base = None; gc.collect()
            candidate = score(consumer.load_candidate(args.candidate).eval()); regression = None
            checks = {'preference_accuracy_not_regressed': candidate['accuracy'] >= baseline['accuracy'],
                'preference_log_loss_not_regressed': candidate['pair_log_loss'] <= baseline['pair_log_loss'] + 1e-6,
                'separate_regression_loss_within_five_percent': candidate['regression_loss'] <= baseline['regression_loss'] * 1.05}
    report = {'schema_version': 'modelanvil.independent-cpu-rlhf-evaluation.v1', 'role': role,
        'manifest_sha256': manifest_sha, 'file_sha256': hashes, 'input_sha256': digests,
        'baseline': baseline, 'candidate': candidate, 'regression': regression, 'checks': checks,
        'passed': all(checks.values()), 'production_qualified': False,
        'actual_units': {'training_steps': 0, 'generated_tokens': 0,
            'alignment_scores': (2 if role == 'reward' else 4) * len(data['preferences']) + 2 * len(data['regression'])},
        'cpu_seconds': time.process_time() - cpu, 'wall_seconds': time.monotonic() - started,
        'consumer_imported_modelanvil_or_django': any(n.split('.')[0] in {'django', 'modelanvil'} for n in sys.modules),
        'scope': 'Bounded independent CPU held-out ranking/calibration and separate regression gate; small authored fixtures cannot establish customer quality or production qualification.'}
    print(json.dumps(report, allow_nan=False))


if __name__ == '__main__': main()
