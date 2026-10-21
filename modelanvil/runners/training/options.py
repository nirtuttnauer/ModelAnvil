"""Supported CPU optimizer controls and separate validation forwards."""
import math


def cpu_options(values, defaults):
    values = values or {}
    if not isinstance(values, dict) or set(values) - {'learning_rate', 'validation_interval'}:
        raise ValueError('CPU recipes support learning_rate and validation_interval only; schedule and checkpoint cadence are fixed.')
    rate = values.get('learning_rate', defaults['learning_rate'])
    interval = values.get('validation_interval', 0)
    if type(rate) not in (int, float) or not math.isfinite(rate) or not 0.000001 <= rate <= 0.2:
        raise ValueError('Learning rate must be finite and between 0.000001 and 0.2.')
    if type(interval) is not int or not 0 <= interval <= 1000:
        raise ValueError('Validation interval is 0 (disabled) or 1–1000 optimizer steps.')
    return {**defaults, 'learning_rate': rate}, interval


def validation_sequences(prepared, encode, spec, train_samples, interval, context_limit):
    if not interval:
        return []
    ids = prepared.get('split_manifest', {}).get('validation', [])
    if not isinstance(ids, list) or not ids:
        raise ValueError('Validation requires a nonempty source-separated validation split.')
    groups = {sample['source_group_id'] for sample in prepared['rows'] if sample['sample_id'] in {item['sample_id'] for item in train_samples}}
    sequences = []
    for row in prepared['rows']:
        if row['sample_id'] not in ids: continue
        if row['source_group_id'] in groups or any(block.get('type') != 'text' or block.get('role') for block in row['blocks']):
            raise ValueError('Validation must use separate source groups and supported text blocks.')
        text = '\n'.join(block['text'] for block in row['blocks'])
        if spec['kind'] == 'character-v1' and any(char not in spec['tokens'] for char in text):
            raise ValueError('Validation text is outside the pinned character vocabulary.')
        tokens = encode(text, spec)
        if len(tokens) > context_limit: raise ValueError('Validation text exceeds the pinned model context; prepare shorter samples.')
        sequences.append(tokens)
    if len(sequences) != len(ids): raise ValueError('Validation samples do not resolve from the pinned manifest.')
    return sequences


def validation_metrics(sequences, interval, step, total_steps, loss):
    if not sequences or (step % interval and step != total_steps): return {}
    pairs = sum(len(sequence)-1 for sequence in sequences)
    value = sum(loss(sequence)*(len(sequence)-1) for sequence in sequences)/pairs
    if not math.isfinite(value): raise ValueError('Validation produced non-finite measurements.')
    return {'validation_loss': value, 'validation_pairs': pairs, 'validation_samples': len(sequences)}
