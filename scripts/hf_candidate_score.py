"""Independent offline baseline/candidate loss scoring for explicit protected samples."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import torch
from transformers import AutoTokenizer
from hf_candidate_infer import load_candidate


def score(model, encoded):
    totals = {}
    with torch.inference_mode():
        for sample, ids in encoded:
            tensor = torch.tensor([ids], dtype=torch.long)
            loss = model(input_ids=tensor, attention_mask=torch.ones_like(tensor), labels=tensor, use_cache=False).loss.item()
            if not torch.isfinite(torch.tensor(loss)).item():
                raise ValueError('Independent loss scoring produced a non-finite value.')
            entry = totals.setdefault(sample['split'], {'negative_log_likelihood': 0.0, 'prediction_tokens': 0, 'samples': 0})
            pairs = len(ids) - 1
            entry['negative_log_likelihood'] += loss * pairs
            entry['prediction_tokens'] += pairs; entry['samples'] += 1
    return {name: {**value, 'loss': value['negative_log_likelihood'] / value['prediction_tokens']} for name, value in totals.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-dir', type=Path, required=True)
    parser.add_argument('--candidate-dir', type=Path, required=True)
    parser.add_argument('--samples', type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(4)
    raw = args.samples.read_bytes()
    if len(raw) > 1024**2:
        raise ValueError('Quality sample manifest exceeds 1 MiB.')
    data = json.loads(raw); samples = data['samples']
    if not 1 <= len(samples) <= 1000:
        raise ValueError('Supply 1–1000 explicitly split samples.')
    tokenizer = AutoTokenizer.from_pretrained(str(args.base_dir), local_files_only=True, trust_remote_code=False)
    encoded, groups, seen, content = [], {}, set(), set()
    for sample in samples:
        if sample['split'] not in {'train_consumed', 'validation', 'test'} or sample['sample_id'] in seen:
            raise ValueError('Quality samples require unique IDs and explicit protected splits.')
        seen.add(sample['sample_id'])
        text_sha = hashlib.sha256(sample['text'].encode()).hexdigest()
        if text_sha in content:
            raise ValueError('Duplicate quality text must be removed before protected publication.')
        content.add(text_sha)
        group = sample['source_group_id']
        if group in groups and groups[group] != sample['split']:
            raise ValueError('A source group appears in both training and protected samples.')
        groups[group] = sample['split']
        ids = tokenizer.encode(sample['text'], add_special_tokens=True)
        if not 2 <= len(ids) <= 128:
            raise ValueError('Quality text must encode to 2–128 tokens; no implicit truncation.')
        encoded.append((sample, ids))
    if {s['split'] for s in samples} != {'train_consumed', 'validation', 'test'}:
        raise ValueError('Include consumed train, validation and protected test samples.')
    baseline = score(load_candidate(args.base_dir).eval(), encoded)
    candidate = score(load_candidate(args.candidate_dir).eval(), encoded)
    checks = {'consumed_training_loss_decreased': candidate['train_consumed']['loss'] < baseline['train_consumed']['loss'],
        'validation_regression_within_five_percent': candidate['validation']['loss'] <= baseline['validation']['loss'] * 1.05,
        'test_regression_within_five_percent': candidate['test']['loss'] <= baseline['test']['loss'] * 1.05}
    print(json.dumps({'samples_sha256': hashlib.sha256(raw).hexdigest(), 'dataset_digest': data['dataset_digest'],
        'source_groups': groups, 'base': baseline, 'candidate': candidate, 'checks': checks, 'passed': all(checks.values()),
        'consumer_imported_modelanvil_or_django': any(m.split('.')[0] in {'modelanvil', 'django'} for m in sys.modules),
        'scope': 'Independent CPU FP32 token-weighted loss on explicit consumed train and file-group-held-out text. This bounded corpus/three-step pilot does not establish broader task quality or production qualification.'}))


if __name__ == '__main__':
    main()
