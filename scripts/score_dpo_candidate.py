"""Independent offline CPU preference/regression scoring; no Django/ModelAnvil imports."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import sys


def read_json(path):
    raw = path.read_bytes()
    if not 0 < len(raw) <= 1024**2:
        raise ValueError('Scoring input must fit within 1 MiB.')
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def verify_files(directory, expected):
    allowed = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json',
               'model.safetensors', 'adapter_config.json', 'adapter_model.safetensors'}
    if not isinstance(expected, dict) or not expected or set(expected) - allowed:
        raise ValueError('Unsupported scoring model files.')
    actual, total = {}, 0
    for name, wanted in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file(): raise ValueError('Scoring model file unavailable.')
        size = path.stat().st_size; total += size
        if size < 1 or total > 1024**3 or (not name.endswith('.safetensors') and size > 8 * 1024**2):
            raise ValueError('Scoring model exceeds its bounded profile.')
        sha = hashlib.sha256()
        with path.open('rb') as source:
            while block := source.read(1024 * 1024): sha.update(block)
        actual[name] = sha.hexdigest()
        if actual[name] != wanted: raise ValueError('Scoring model checksum changed.')
    config = json.loads((directory / 'config.json').read_text())
    expected_config = {'model_type': 'llama', 'hidden_size': 576, 'num_hidden_layers': 30,
        'vocab_size': 49152, 'intermediate_size': 1536, 'num_attention_heads': 9, 'num_key_value_heads': 3}
    if any(config.get(key) != value for key, value in expected_config.items()) or config.get('quantization_config'):
        raise ValueError('Independent DPO scoring supports dense SmolLM2-135M only.')
    return actual


def response_score(model, pair, field):
    """Independent CPU log-softmax/gather sum over response labels, including EOS."""
    import torch
    ids = torch.tensor([pair[field]], dtype=torch.long, device='cpu')
    logits = model(input_ids=ids[:, :-1], attention_mask=torch.ones_like(ids[:, :-1]), use_cache=False).logits
    logp = torch.nn.functional.log_softmax(logits[0, pair['prompt_tokens'] - 1:].float(), dim=-1)
    return logp.gather(-1, ids[0, pair['prompt_tokens']:, None]).sum().item()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base', 'candidate', 'preferences', 'regression', 'manifest'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    signal.alarm(120)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    from transformers import AutoTokenizer
    torch.set_num_threads(1)
    torch.set_default_device('cpu')
    root = Path(__file__).resolve().parents[1]
    consumer = load_source('independent_hf_consumer', root / 'scripts/hf_candidate_infer.py')
    math_impl = load_source('independent_dpo_objective', root / 'modelanvil/runners/alignment/torch_dpo.py')
    group_impl = load_source('independent_preference_groups', root / 'modelanvil/runners/alignment/preference_groups.py')
    manifest, manifest_sha = read_json(args.manifest)
    beta = manifest['beta']
    if type(beta) not in (int, float) or not math.isfinite(beta) or not .001 <= beta <= 1:
        raise ValueError('Invalid pinned DPO beta.')
    base_names = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'model.safetensors'}
    if (set(manifest['base_files']) != base_names or
            set(manifest['candidate_files']) != base_names | {'adapter_config.json', 'adapter_model.safetensors'}):
        raise ValueError('Independent scoring needs complete pinned base and adapter snapshots.')
    hashes = {'base': verify_files(args.base, manifest['base_files']),
              'candidate': verify_files(args.candidate, manifest['candidate_files'])}
    tokenizer = AutoTokenizer.from_pretrained(str(args.base), local_files_only=True, trust_remote_code=False)
    data, digests, groups, encoded = {}, {}, {}, {}
    for name in ('preferences', 'regression'):
        value, sha = read_json(getattr(args, name)); digests[name] = sha
        if sha != manifest[name + '_sha256'] or value.get('schema_version') != 'modelanvil.preference-pairs.v1':
            raise ValueError('Independent scoring data identity changed.')
        pairs = value.get('pairs')
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32:
            raise ValueError('Scoring requires 1–32 held-out pairs.')
        data[name], groups[name], encoded[name] = pairs, set(), []
        seen = set()
        for pair in pairs:
            if (not isinstance(pair, dict) or any(not isinstance(pair.get(k), str) or not pair[k].strip()
                    for k in ('prompt', 'chosen', 'rejected')) or pair['chosen'] == pair['rejected']):
                raise ValueError('Invalid held-out preference pair.')
            group = group_impl.source_group(pair, required=True)
            if pair['prompt'] in seen:
                raise ValueError('Held-out rows need source groups and unique prompts.')
            seen.add(pair['prompt']); groups[name].add(group.strip())
            encoded[name].append(math_impl.encode_pair(tokenizer, pair))
    if (groups['preferences'] & groups['regression'] or
            (groups['preferences'] | groups['regression']) & set(manifest['training_groups'])):
        raise ValueError('Protected scoring source groups overlap.')
    if {row['prompt'].strip() for row in data['preferences']} & {row['prompt'].strip() for row in data['regression']}:
        raise ValueError('Protected preference and regression prompts overlap.')

    def score(model):
        result = {'pairs': [], 'regression_negative_log_likelihood': 0., 'regression_tokens': 0}
        with torch.inference_mode():
            for pair in encoded['preferences']:
                values = [response_score(model, pair, key)
                          for key in ('chosen', 'rejected')]
                if not all(math.isfinite(value) for value in values): raise ValueError('Non-finite preference scores.')
                result['pairs'].append({'chosen_logp': values[0], 'rejected_logp': values[1],
                    'margin': values[0] - values[1], 'win': 1. if values[0] > values[1] else .5 if values[0] == values[1] else 0.})
            for pair in encoded['regression']:
                value = response_score(model, pair, 'chosen')
                if not math.isfinite(value): raise ValueError('Non-finite regression score.')
                result['regression_negative_log_likelihood'] -= value
                result['regression_tokens'] += len(pair['chosen']) - pair['prompt_tokens']
        result['preference_accuracy'] = sum(pair['win'] for pair in result['pairs']) / len(result['pairs'])
        result['regression_loss'] = result['regression_negative_log_likelihood'] / result['regression_tokens']
        return result
    baseline = score(consumer.load_candidate(args.base).eval())
    candidate = score(consumer.load_candidate(args.candidate).eval())
    losses = [-torch.nn.functional.logsigmoid(torch.tensor(beta * (c['margin'] - b['margin']))).item()
              for b, c in zip(baseline['pairs'], candidate['pairs'])]
    objective = sum(losses) / len(losses)
    checks = {'preference_accuracy_not_regressed': candidate['preference_accuracy'] >= baseline['preference_accuracy'],
              'reference_relative_preference_loss_not_regressed': objective <= math.log(2) + 1e-6,
              'separate_regression_loss_within_five_percent': candidate['regression_loss'] <= baseline['regression_loss'] * 1.05}
    print(json.dumps({'schema_version': 'modelanvil.independent-dpo-evaluation.v1', 'manifest_sha256': manifest_sha,
        'file_sha256': hashes, 'input_sha256': digests, 'source_groups': {k: sorted(v) for k, v in groups.items()},
        'baseline': baseline, 'candidate': candidate, 'dpo_loss': objective, 'beta': beta, 'checks': checks,
        'passed': all(checks.values()), 'production_qualified': False,
        'consumer_imported_modelanvil_or_django': any(n == 'django' or n.startswith('modelanvil') for n in sys.modules),
        'scope': 'Independent bounded CPU held-out preference and separate chosen-response regression scoring; no customer or production qualification.'}))


if __name__ == '__main__': main()
