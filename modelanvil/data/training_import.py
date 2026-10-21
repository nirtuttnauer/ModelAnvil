"""Ordinary training records become role-preserving, reproducible envelopes."""
import csv
import hashlib
import io
import json
import uuid
from itertools import islice

from modelanvil.data.source_import import SourceImportError, _object, _constant

VERSION = 'modelanvil.training-records.v1'
ROLES = {'system', 'user', 'assistant'}
ROLE_PREFIX_TEMPLATE = "{% for message in messages %}{{ message['role'] | capitalize }}: {{ message['content'] }}\n{% endfor %}{% if add_generation_prompt %}Assistant: {% endif %}"


def source_records(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16 * 1024**2:
        raise SourceImportError('Choose a nonempty training file of at most 16 MiB.')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeError:
        raise SourceImportError('Use a UTF-8 JSONL, JSON or CSV training file.') from None
    try:
        if text.lstrip().startswith('['):
            records = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
            if not isinstance(records, list):
                raise ValueError()
        elif text.lstrip().startswith('{'):
            records = [json.loads(line, object_pairs_hook=_object, parse_constant=_constant)
                       for line in islice((line for line in text.splitlines() if line.strip()), 1001)]
        else:
            reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
            headers = [h.strip().lower() for h in reader.fieldnames] if reader.fieldnames else []
            if not headers or any(not h for h in headers) or len(set(headers)) != len(headers):
                raise ValueError()
            reader.fieldnames = headers
            records = list(islice(reader, 1001))
    except (ValueError, TypeError, RecursionError, csv.Error):
        raise SourceImportError('The file is malformed. Use one JSON object per line, a JSON array, or a CSV with unique column names.') from None
    if not records or len(records) > 1000:
        raise SourceImportError('Use between 1 and 1,000 training examples.')
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict) or None in record:
            raise SourceImportError(f'Example {number}: expected an object with named columns.')
        if len(record) > 64 or any(not isinstance(key, str) or not key or len(key) > 128 for key in record):
            raise SourceImportError(f'Example {number}: use at most 64 columns with nonempty names of at most 128 characters.')
    return records


def training_mapping(value):
    if value is None or value == {} or value == {'mode': 'auto'}:
        return None
    if not isinstance(value, dict):
        raise SourceImportError('Column mapping must be an object.')
    mode = value.get('mode')
    required = {'prompt_response': ['prompt_field', 'response_field'], 'messages': ['messages_field'], 'text': ['text_field']}
    if not isinstance(mode, str) or mode not in required:
        raise SourceImportError('Choose prompt/response, messages, text, or automatic column mapping.')
    optional = ['group_field'] + (['system_field', 'context_field'] if mode == 'prompt_response' else [])
    if set(value) - {'mode', *required[mode], *optional}:
        raise SourceImportError('The column mapping contains unsupported fields.')
    result = {'mode': mode}
    for key in required[mode] + optional:
        field = value.get(key, '')
        if not isinstance(field, str) or len(field) > 128 or key in required[mode] and not field:
            raise SourceImportError(f'Select a valid {key.replace("_field", "")} column.')
        if field:
            result[key] = field
    fields = [field for key, field in result.items() if key != 'mode']
    if len(set(fields)) != len(fields):
        raise SourceImportError('Map each training field to a different source column.')
    return result


def mapped_record(record, mapping, number):
    if mapping is None:
        return record
    def field(key):
        name = mapping[key]
        if name not in record:
            raise SourceImportError(f'Example {number}: mapped column {name} is missing.')
        return record[name]
    mode = mapping['mode']
    if mode == 'prompt_response':
        prompt, response = field('prompt_field'), field('response_field')
        for key, text in [('prompt_field', prompt), ('response_field', response)]:
            if not isinstance(text, str) or not text.strip():
                raise SourceImportError(f'Example {number}: {mapping[key]} must contain nonempty text.')
        if 'context_field' in mapping:
            context = field('context_field')
            if not isinstance(context, str):
                raise SourceImportError(f'Example {number}: {mapping["context_field"]} must contain text.')
            if context: prompt += '\n' + context
        messages = [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': response}]
        if 'system_field' in mapping:
            system = field('system_field')
            if not isinstance(system, str):
                raise SourceImportError(f'Example {number}: {mapping["system_field"]} must contain text.')
            if system.strip(): messages.insert(0, {'role': 'system', 'content': system})
        result = {'messages': messages}
    elif mode == 'messages':
        messages = field('messages_field')
        if isinstance(messages, str):
            try: messages = json.loads(messages, object_pairs_hook=_object, parse_constant=_constant)
            except (ValueError, TypeError, RecursionError):
                raise SourceImportError(f'Example {number}: {mapping["messages_field"]} must contain a JSON messages array.') from None
        result = {'messages': messages}
    else:
        result = {'text': field('text_field')}
    if 'group_field' in mapping:
        group = field('group_field')
        if not isinstance(group, str) or not group.strip() or len(group) > 256:
            raise SourceImportError(f'Example {number}: {mapping["group_field"]} must contain nonempty group text of at most 256 characters.')
        result['group_id'] = group
    return result


def inspect_training_source(raw, source_mapping=None):
    records = source_records(raw)
    columns = list(dict.fromkeys(key for record in records for key in record))
    if len(columns) > 64:
        raise SourceImportError('Use at most 64 different source columns across the file.')
    mode = 'auto'
    recommended = {'mode': mode}
    if 'messages' in columns:
        recommended = {'mode': 'messages', 'messages_field': 'messages'}
    else:
        pair = next(((a, b) for a, b in [('prompt', 'response'), ('prompt', 'completion'), ('instruction', 'output'), ('question', 'answer')] if a in columns and b in columns), None)
        if pair:
            recommended = {'mode': 'prompt_response', 'prompt_field': pair[0], 'response_field': pair[1]}
            if pair[0] == 'instruction' and 'input' in columns: recommended['context_field'] = 'input'
        elif 'text' in columns:
            recommended = {'mode': 'text', 'text_field': 'text'}
    if recommended['mode'] != 'auto':
        group = next((name for name in ['source_group_id', 'group_id'] if name in columns), None)
        if group: recommended['group_field'] = group
    samples = []
    for record in records[:5]:
        cells = {}
        for key, value in record.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            cells[key] = text[:300] + ('…' if len(text) > 300 else '')
        samples.append(cells)
    return {'row_count': len(records), 'columns': columns, 'sample_rows': samples, 'recommended_mapping': recommended,
            'validation': validate_training_source(records, hashlib.sha256(raw).hexdigest(), recommended if source_mapping is None else source_mapping),
            'source_digest': hashlib.sha256(raw).hexdigest(), 'limits': 'First 5 source rows; cells longer than 300 characters are abbreviated. Full values are used for validation and training.'}


def validate_training_source(records, source, source_mapping=None):
    """Inspect every bounded source row using the same importer and envelope checks as publication."""
    from modelanvil.data.preparation import prepare_envelopes
    from modelanvil.data.detection import content_digest
    mapping = training_mapping(source_mapping)
    columns = list(dict.fromkeys(key for record in records for key in record))
    required = set(mapping[key] for key in mapping if key != 'mode') if mapping else set()
    missing = {column: [] for column in columns}
    missing_rows, invalid_rows, formatting, duplicates, whitespace = set(), set(), [], [], []
    seen, sample_ids = {}, set()
    for number, record in enumerate(records, 1):
        empty = {column for column in columns if record.get(column) is None or isinstance(record.get(column), str) and not record[column].strip()}
        messages_column = mapping.get('messages_field') if mapping else 'messages'
        messages = record.get(messages_column)
        if isinstance(messages, str):
            try: messages = json.loads(messages)
            except (ValueError, RecursionError): pass
        if isinstance(messages, list) and (not messages or any(isinstance(turn, dict) and (turn.get('content') is None or isinstance(turn.get('content'), str) and not turn['content'].strip()) for turn in messages)):
            empty.add(messages_column)
        # Selected context/system columns may be empty strings, but must exist and contain text.
        empty_required = empty & required
        if mapping and mapping['mode'] == 'prompt_response':
            for key in ('system_field', 'context_field'):
                if key in mapping and isinstance(record.get(mapping[key]), str):
                    empty_required.discard(mapping[key])
        for column in empty:
            missing[column].append(number)
        if empty: missing_rows.add(number)
        if any(isinstance(value, str) and value.strip() and value != value.strip() for value in record.values()):
            whitespace.append(number)
        try:
            row = _training_records([record], source, mapping, number)[0]
            prepare_envelopes([row])
            if row['sample_id'] in sample_ids:
                raise ValueError('Sample ID repeats another row. Give each canonical envelope a unique sample_id.')
            sample_ids.add(row['sample_id'])
        except ValueError as exc:
            invalid_rows.add(number)
            if not empty_required:
                formatting.append({'row': number, 'message': str(exc)})
            continue
        digest = content_digest(row)
        if digest in seen:
            duplicates.append({'row': number, 'duplicate_of': seen[digest]})
        else:
            seen[digest] = number
    issues = []
    for column, rows in missing.items():
        if rows:
            blocking = column in required and not (mapping and mapping['mode'] == 'prompt_response' and column in [mapping.get('system_field'), mapping.get('context_field')] and all(isinstance(records[n - 1].get(column), str) for n in rows))
            issues.append({'code': 'missing_values', 'severity': 'error' if blocking else 'warning', 'count': len(rows), 'rows': rows[:5],
                           'message': f'Column "{column}" has missing or blank values. ' + ('Fill every required value before previewing again.' if blocking else 'Check whether these blanks are intentional; unused columns do not affect training.')})
    if formatting:
        issues.append({'code': 'formatting', 'severity': 'error', 'count': len(formatting), 'rows': [item['row'] for item in formatting[:5]],
                       'message': 'Repair malformed training records before continuing. Check text types, message roles and conversation order.', 'examples': formatting[:5]})
    if duplicates:
        issues.append({'code': 'duplicate_rows', 'severity': 'warning', 'count': len(duplicates), 'rows': [item['row'] for item in duplicates[:5]],
                       'message': 'Repeated training content adds no new examples. Exact duplicates will be removed during guided preparation; the first occurrence is kept.', 'examples': duplicates[:5]})
    if whitespace:
        issues.append({'code': 'whitespace', 'severity': 'warning', 'count': len(whitespace), 'rows': whitespace[:5],
                       'message': 'Leading or trailing whitespace is present. Check formatting; text is preserved exactly as supplied.'})
    return {'checked_rows': len(records), 'invalid_rows': len(invalid_rows), 'missing_value_rows': len(missing_rows),
            'duplicate_rows': len(duplicates), 'formatting_error_rows': len(formatting), 'issues': issues,
            'mapping': mapping or {'mode': 'auto'}, 'can_prepare': not invalid_rows}


def training_records(raw, source_mapping=None):
    records = source_records(raw)
    mapping = training_mapping(source_mapping)
    source = hashlib.sha256(raw).hexdigest()
    return _training_records(records, source, mapping)


def _training_records(records, source, mapping, start=1):
    rows = []
    for number, record in enumerate(records, start):
        record = mapped_record(record, mapping, number)
        if record.get('schema_version') == '1.0':
            rows.append(record)
            continue
        messages = record.get('messages')
        if messages is None:
            pair = next(((a, b, record[a], record[b]) for a, b in
                         [('prompt', 'response'), ('prompt', 'completion'), ('instruction', 'output'), ('question', 'answer')]
                         if a in record and b in record), None)
            if pair is not None:
                field, response_field, prompt, response = pair
                for column, value in ((field, prompt), (response_field, response)):
                    if not isinstance(value, str) or not value.strip():
                        raise SourceImportError(f'Example {number}: {column} must contain nonempty text. Fill in this field before uploading again.')
                if field == 'instruction' and 'input' in record:
                    context = record['input']
                    if not isinstance(context, str) or not isinstance(prompt, str):
                        raise SourceImportError(f'Example {number}: instruction and input must be text.')
                    if context:
                        prompt += '\n' + context
                messages = [{'role': 'user', 'content': prompt}, {'role': 'assistant', 'content': response}]
            elif 'text' in record:
                messages = [{'content': record['text']}]
            else:
                raise SourceImportError(f'Example {number}: add messages, prompt and response columns, or a text field.')
        if not isinstance(messages, list) or not messages or len(messages) > 64:
            raise SourceImportError(f'Example {number}: messages must be a nonempty list of at most 64 turns.')
        blocks = []
        chat = any(isinstance(m, dict) and 'role' in m for m in messages)
        previous = None
        for index, message in enumerate(messages):
            if not isinstance(message, dict) or not isinstance(message.get('content'), str) or not message['content'].strip():
                raise SourceImportError(f'Example {number}, turn {index + 1}: content must be nonempty text.')
            role = message.get('role')
            if chat and (not isinstance(role, str) or role not in ROLES or (role == 'system' and index != 0)
                         or (role == 'assistant' and previous != 'user')
                         or (role == 'user' and previous not in (None, 'system', 'assistant'))):
                raise SourceImportError(f'Example {number}, turn {index + 1}: use an optional system message followed by alternating user and assistant turns.')
            blocks.append({'block_id': f'turn-{index + 1}', 'type': 'text', 'text': message['content'],
                           **({'role': role} if role else {})})
            previous = role
        if chat and previous != 'assistant':
            raise SourceImportError(f'Example {number}: finish the conversation with an assistant response to train on.')
        content = json.dumps(blocks, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        # Repeated prompts and alternate responses stay together across held-out splits.
        context = [b for b in blocks if b.get('role') != 'assistant'] if chat else blocks
        group = record.get('source_group_id', record.get('group_id'))
        if group is None:
            group = 'content:' + hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if not isinstance(group, str) or not group.strip() or len(group) > 256:
            raise SourceImportError(f'Example {number}: group_id must be nonempty text of at most 256 characters.')
        rows.append({'schema_version': '1.0',
                     'sample_id': str(uuid.uuid5(uuid.NAMESPACE_URL, f'{VERSION}:{source}:{number}')),
                     'source_group_id': group, 'blocks': blocks,
                     'provenance': {'source_snapshot_ref': f'sha256:{source}', 'source_record_key': f'example/{number}',
                                    'content_sha256': hashlib.sha256(content.encode()).hexdigest(),
                                    'transformation_revision_ref': VERSION},
                     'metadata': {'source_format': 'training'}})
    return rows


def allocate_training_splits(prepared, seed, validation_percent, test_percent):
    """Allocate whole groups proportionally; small datasets retain a training group."""
    groups = sorted({r['source_group_id'] for r in prepared['rows']},
                    key=lambda group: hashlib.sha256(f'{seed}:{group}'.encode()).hexdigest())
    count = len(groups)
    validation = max(1, count * validation_percent // 100) if validation_percent and count >= 3 else 0
    test = max(1, count * test_percent // 100) if test_percent and count >= 3 else 0
    validation = min(validation, max(0, count - test - 1))
    assignments = {group: 'validation' if i < validation else 'test' if i < validation + test else 'train'
                   for i, group in enumerate(groups)}
    prepared['split_manifest'] = {name: [r['sample_id'] for r in prepared['rows'] if assignments[r['source_group_id']] == name]
                                  for name in ('train', 'validation', 'test')}
    prepared['recipe']['algorithm'] = 'proportional_training_source_groups_v1'


def tokenize_blocks(blocks, tokenizer):
    """Plain text learns all tokens; conversations learn assistant content only."""
    if any(b['type'] != 'text' for b in blocks):
        raise ValueError('Use text-only examples for this model.')
    if not any(b.get('role') for b in blocks):
        text = '\n'.join(b['text'] for b in blocks)
        ids = tokenizer.encode(text, add_special_tokens=True)
        return text, ids, ids.copy()
    pieces, spans, cursor = [], [], 0
    previous = None
    for index, block in enumerate(blocks):
        role = block.get('role')
        if not isinstance(role, str) or role not in ROLES or (role == 'system' and index != 0) or (role == 'assistant' and previous != 'user') or (role == 'user' and previous not in (None, 'system', 'assistant')):
            raise ValueError('Use an optional system message followed by alternating user and assistant turns.')
        prefix = f'{role.capitalize()}: '
        body = block['text'] + '\n'
        if role == 'assistant':
            spans.append((cursor + len(prefix), cursor + len(prefix) + len(body)))
        pieces.append(prefix + body)
        cursor += len(prefix) + len(body)
        previous = role
    if previous != 'assistant':
        raise ValueError('Each conversation must end with a nonempty assistant response.')
    text = ''.join(pieces)
    if getattr(tokenizer, 'chat_template', None):
        messages = [{'role': b['role'], 'content': b['text']} for b in blocks]
        text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        spans = [(len(tokenizer.apply_chat_template(messages[:i], tokenize=False, add_generation_prompt=True)),
                  len(tokenizer.apply_chat_template(messages[:i + 1], tokenize=False, add_generation_prompt=False)))
                 for i, message in enumerate(messages) if message['role'] == 'assistant']
    encoded = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
    ids = encoded['input_ids']
    labels = [token if any(end > lo and start < hi for lo, hi in spans) else -100
              for token, (start, end) in zip(ids, encoded['offset_mapping'])]
    if not any(i != -100 for i in labels[1:]):
        raise ValueError('Each conversation needs assistant tokens to train on.')
    return text, ids, labels
