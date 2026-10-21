import json
from unittest import TestCase

from modelanvil.data.publication import prepare_source, DatasetPreparationError
from modelanvil.data.training_import import training_records, tokenize_blocks


class TrainingImportTests(TestCase):
    def test_validation_checks_all_rows_and_matches_publication_duplicates(self):
        from modelanvil.data.training_import import inspect_training_source
        records = [{'prompt': f'Question {i}', 'response': f'Answer {i}'} for i in range(6)]
        records += [dict(records[0]), {'prompt': 'Missing response', 'response': '  '},
                    {'prompt': 'Wrong type', 'response': 42}, {'prompt': 'Edge whitespace ', 'response': 'Answer'}]
        raw = json.dumps(records).encode()
        report = inspect_training_source(raw)['validation']
        self.assertEqual(report['checked_rows'], 10)
        self.assertEqual(report['invalid_rows'], 2)
        self.assertEqual(report['missing_value_rows'], 1)
        self.assertEqual(report['formatting_error_rows'], 1)
        self.assertEqual(report['duplicate_rows'], 1)
        self.assertFalse(report['can_prepare'])
        issues = {issue['code']: issue for issue in report['issues']}
        self.assertEqual(issues['missing_values']['rows'], [8])
        self.assertEqual(issues['duplicate_rows']['examples'], [{'row': 7, 'duplicate_of': 1}])
        self.assertEqual(issues['formatting']['examples'][0]['row'], 9)
        self.assertIn('response must contain nonempty text', issues['formatting']['examples'][0]['message'])
        self.assertEqual(issues['whitespace']['rows'], [10])
        valid = json.dumps(records[:7]).encode()
        prepared, _ = prepare_source(valid, source_format='training', dedup={'exact': True, 'near': False})
        self.assertEqual(inspect_training_source(valid)['validation']['duplicate_rows'], len(prepared['dropped']))

    def test_validation_rechecks_mapping_and_treats_optional_blanks_as_warnings(self):
        from modelanvil.data.training_import import inspect_training_source
        raw = b'q,a,context,unused\nQuestion,Answer,,\nAnother,Second,,\n'
        mapping = {'mode': 'prompt_response', 'prompt_field': 'q', 'response_field': 'a', 'context_field': 'context'}
        report = inspect_training_source(raw, mapping)['validation']
        self.assertTrue(report['can_prepare'])
        self.assertEqual(report['missing_value_rows'], 2)
        self.assertTrue(all(issue['severity'] == 'warning' for issue in report['issues']))
        self.assertFalse(inspect_training_source(raw, {**mapping, 'response_field': 'unused'})['validation']['can_prepare'])
        self.assertTrue(inspect_training_source(raw, {'mode': 'text', 'text_field': 'a'})['validation']['can_prepare'])

    def test_validation_reports_all_bad_chats_with_bounded_details(self):
        from modelanvil.data.training_import import inspect_training_source
        raw = json.dumps([{'messages': [{'role': 'assistant', 'content': 'Out of order'}]} for _ in range(30)]).encode()
        report = inspect_training_source(raw)['validation']
        self.assertEqual(report['invalid_rows'], 30)
        self.assertEqual(report['formatting_error_rows'], 30)
        self.assertEqual(len(report['issues'][0]['examples']), 5)
        self.assertIn('alternating user and assistant', report['issues'][0]['examples'][0]['message'])
        raw = json.dumps([{'messages': [{'role': [], 'content': 'Wrong role'}]}, {'messages': [{'role': 'user', 'content': None}]}]).encode()
        report = inspect_training_source(raw)['validation']
        self.assertEqual(report['invalid_rows'], 2)
        self.assertEqual(report['missing_value_rows'], 1)
        self.assertEqual(report['formatting_error_rows'], 1)
        raw = b'prompt,response\nQuestion,Answer\nAnother\n'
        self.assertEqual(inspect_training_source(raw)['validation']['issues'][0]['rows'], [2])
        for malformed in [b'prompt,prompt\nOne,Two', b'{invalid json}', b'prompt,response\n"Unclosed,Answer']:
            with self.assertRaises(ValueError): inspect_training_source(malformed)

    def test_native_chat_template_masks_prompts_and_learns_assistant_end_token(self):
        class Tokenizer:
            chat_template = 'verified native template'
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                return ''.join(f"<{m['role']}>{m['content']}<end>" for m in messages) + ('<assistant>' if add_generation_prompt else '')
            def __call__(self, text, **options):
                return {'input_ids': list(text.encode()), 'offset_mapping': [(i, i + 1) for i in range(len(text))]}
        text, ids, labels = tokenize_blocks([{'type': 'text', 'role': 'user', 'text': 'Question'},
                                            {'type': 'text', 'role': 'assistant', 'text': 'Answer'}], Tokenizer())
        self.assertEqual(text, '<user>Question<end><assistant>Answer<end>')
        self.assertTrue(all(label == -100 for label in labels[:-len('Answer<end>')]))
        self.assertEqual(labels[-len('Answer<end>'):], ids[-len('Answer<end>'):])

    def test_chat_roles_and_duplicate_prompts_stay_together(self):
        raw = json.dumps([{'messages': [{'role': 'user', 'content': 'Same question'}, {'role': 'assistant', 'content': answer}]}
                          for answer in ['First response', 'Second response']]).encode()
        rows = training_records(raw)
        self.assertEqual([b['role'] for b in rows[0]['blocks']], ['user', 'assistant'])
        self.assertEqual(rows[0]['source_group_id'], rows[1]['source_group_id'])
        self.assertNotEqual(rows[0]['sample_id'], rows[1]['sample_id'])

    def test_json_csv_and_jsonl_pairs_have_usable_small_splits(self):
        records = [{'prompt': f'Question {i}', 'response': f'Response {i}'} for i in range(8)]
        sources = [json.dumps(records).encode(), '\n'.join(json.dumps(r) for r in records).encode(),
                   ('prompt,response\n' + '\n'.join(f'Question {i},Response {i}' for i in range(8))).encode()]
        for raw in sources:
            prepared, payload = prepare_source(raw, source_format='training', dedup={'exact': True, 'near': False})
            self.assertEqual(prepared['row_count'], 8)
            self.assertEqual([len(prepared['split_manifest'][k]) for k in ['train', 'validation', 'test']], [6, 1, 1])
            self.assertEqual(payload, prepare_source(raw, source_format='training', dedup={'exact': True, 'near': False})[1])

    def test_invalid_message_has_example_and_turn_repair_guidance(self):
        raw = b'{"messages":[{"role":"user","content":[]}]}'
        with self.assertRaisesRegex(DatasetPreparationError, 'Example 1, turn 1: content must be nonempty text'):
            prepare_source(raw, source_format='training')
        with self.assertRaisesRegex(DatasetPreparationError, 'finish the conversation'):
            prepare_source(b'{"messages":[{"role":"user","content":"Question"}]}', source_format='training')

    def test_invalid_pair_names_the_source_field_to_repair(self):
        for raw, field in [(b'Prompt,Response\nQuestion,\n', 'response'),
                           (b'{"question":null,"answer":"Answer"}', 'question'),
                           (b'{"instruction":"Question","output":"   "}', 'output')]:
            with self.assertRaisesRegex(DatasetPreparationError, f'Example 1: {field} must contain nonempty text'):
                prepare_source(raw, source_format='training')

    def test_never_split_a_source_group_and_keep_a_training_group(self):
        records = [{'prompt': f'Question {i}', 'response': 'Answer', 'group_id': f'group-{i % 3}'} for i in range(12)]
        prepared, _ = prepare_source(json.dumps(records).encode(), source_format='training')
        allocation = {id: split for split, ids in prepared['split_manifest'].items() for id in ids}
        groups = {}
        for row in prepared['rows']:
            groups.setdefault(row['source_group_id'], set()).add(allocation[row['sample_id']])
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))
        self.assertTrue(all(prepared['split_manifest'].values()))

    def test_prompt_tokens_are_masked_and_plain_text_behavior_is_preserved(self):
        class Tokenizer:
            def encode(self, text, **options): return list(text.encode())
            def __call__(self, text, **options): return {'input_ids': list(text.encode()), 'offset_mapping': [(i, i + 1) for i in range(len(text))]}
        _, ids, labels = tokenize_blocks([{'type': 'text', 'role': 'user', 'text': 'Question'},
                                         {'type': 'text', 'role': 'assistant', 'text': 'Answer'}], Tokenizer())
        self.assertTrue(all(i == -100 for i in labels[:len('User: Question\nAssistant: ')]))
        self.assertEqual(labels[-len('Answer\n'):], ids[-len('Answer\n'):])
        _, ids, labels = tokenize_blocks([{'type': 'text', 'text': 'Plain text'}], Tokenizer())
        self.assertEqual(labels, ids)


    def test_instruction_context_is_preserved_and_csv_headers_are_recognized(self):
        rows = training_records(b'{"instruction":"Summarize this","input":"Important context","output":"Summary"}')
        self.assertEqual(rows[0]['blocks'][0]['text'], 'Summarize this\nImportant context')
        rows = training_records(b' Prompt , Response \nQuestion,Answer\n')
        self.assertEqual([b['role'] for b in rows[0]['blocks']], ['user', 'assistant'])
        with self.assertRaisesRegex(DatasetPreparationError, 'instruction and input must be text'):
            prepare_source(b'{"instruction":"Summarize","input":{},"output":"Answer"}', source_format='training')

    def test_custom_columns_are_mapped_and_pinned_without_rewriting_source_bytes(self):
        import hashlib
        from modelanvil.data.training_import import inspect_training_source
        raw = b'customer query,agent reply,context,case\nReset?,Open settings.,Device settings,account-1\nRestart?,Press restart.,Device settings,account-2\n'
        inspected = inspect_training_source(raw)
        self.assertEqual(inspected['columns'], ['customer query', 'agent reply', 'context', 'case'])
        self.assertEqual(inspected['sample_rows'][0]['customer query'], 'Reset?')
        mapping = {'mode': 'prompt_response', 'prompt_field': 'customer query', 'response_field': 'agent reply', 'context_field': 'context', 'group_field': 'case'}
        first, payload = prepare_source(raw, source_format='training', source_mapping=mapping)
        self.assertEqual(first['rows'][0]['blocks'][0]['text'], 'Reset?\nDevice settings')
        self.assertEqual(first['rows'][0]['blocks'][1]['text'], 'Open settings.')
        self.assertEqual(first['rows'][0]['source_group_id'], 'account-1')
        self.assertEqual(first['recipe']['extraction']['source_mapping'], mapping)
        self.assertEqual(first['recipe']['extraction']['input_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(payload, prepare_source(raw, source_format='training', source_mapping=mapping)[1])
        swapped, _ = prepare_source(raw, source_format='training', source_mapping={**mapping, 'prompt_field': 'agent reply', 'response_field': 'customer query'})
        self.assertNotEqual(first['recipe_digest'], swapped['recipe_digest'])

    def test_messages_and_plain_text_columns_keep_the_correct_training_objective(self):
        messages = [{'role': 'user', 'content': 'Question'}, {'role': 'assistant', 'content': 'Answer'}]
        raw = json.dumps([{'turns': json.dumps(messages)}]).encode()
        rows = training_records(raw, {'mode': 'messages', 'messages_field': 'turns'})
        self.assertEqual([block['role'] for block in rows[0]['blocks']], ['user', 'assistant'])
        text = training_records(b'body\nTraining text\n', {'mode': 'text', 'text_field': 'body'})
        self.assertNotIn('role', text[0]['blocks'][0])
        self.assertEqual(training_records(b'{"text":"Plain"}', {'mode': 'text', 'text_field': 'text'})[0]['blocks'][0]['text'], 'Plain')

    def test_invalid_mapping_missing_values_and_duplicate_columns_are_rejected(self):
        from modelanvil.data.training_import import inspect_training_source
        raw = b'q,a\nQuestion,Answer\n'
        for mapping in [[], {'mode': []}, {'mode': 'other'}, {'mode': 'prompt_response', 'prompt_field': 'q', 'response_field': 'q'},
                        {'mode': 'prompt_response', 'prompt_field': 'q', 'response_field': 'missing'}, {'mode': 'text', 'text_field': 'q', 'unknown': 'a'}]:
            with self.assertRaises(DatasetPreparationError):
                prepare_source(raw, source_format='training', source_mapping=mapping)
        with self.assertRaisesRegex(ValueError, 'unique column names'):
            inspect_training_source(b'question,Question\nOne,Two\n')
        with self.assertRaisesRegex(DatasetPreparationError, 'a must contain nonempty text'):
            prepare_source(b'q,a\nQuestion,\n', source_format='training', source_mapping={'mode': 'prompt_response', 'prompt_field': 'q', 'response_field': 'a'})
        with self.assertRaisesRegex(DatasetPreparationError, 'training source format'):
            prepare_source(raw, source_format='csv', source_mapping={'mode': 'text', 'text_field': 'q'})

    def test_inspection_is_bounded_and_automatic_mapping_keeps_existing_recipe(self):
        from modelanvil.data.training_import import inspect_training_source
        records = [{'prompt': f'Question {i}', 'response': 'Answer ' + 'a' * 400} for i in range(8)]
        raw = json.dumps(records).encode()
        inspected = inspect_training_source(raw)
        self.assertEqual(inspected['row_count'], 8); self.assertEqual(len(inspected['sample_rows']), 5)
        self.assertEqual(len(inspected['sample_rows'][0]['response']), 301)
        self.assertEqual(inspected['recommended_mapping']['prompt_field'], 'prompt')
        self.assertEqual(prepare_source(raw, source_format='training')[1], prepare_source(raw, source_format='training', source_mapping={'mode': 'auto'})[1])
