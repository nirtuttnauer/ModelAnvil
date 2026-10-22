"""Held-out comparison helpers for the guided decision loop."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from modelanvil.runners.eval_worker import evaluation_prompt_format
from modelanvil.runners.guided_comparison import cases_from_manifest, normalize_questions
from modelanvil.runners.training import hf_runtime


def chat_version(template='{{ messages }}'):
    return SimpleNamespace(architecture_ref=hf_runtime.RUNTIME_ID, tokenizer=SimpleNamespace(chat_template=template))


class GuidedComparisonTests(SimpleTestCase):
    def test_native_template_requires_both_snapshots_to_declare_a_chat_template(self):
        guided = chat_version()
        run = SimpleNamespace(candidate_model_version=guided, baseline_model_version_id=1, baseline_model_version=chat_version())
        self.assertEqual(evaluation_prompt_format(run), 'native_template')
        run.baseline_model_version = chat_version('')
        self.assertEqual(evaluation_prompt_format(run), 'plain')
        run.baseline_model_version = SimpleNamespace(architecture_ref='other', tokenizer=SimpleNamespace(chat_template='{{ messages }}'))
        self.assertEqual(evaluation_prompt_format(run), 'plain')

    def test_held_out_cases_prefer_the_test_split_and_annotation_rows(self):
        prepared = {'split_manifest': {'test': ['t1'], 'validation': ['v1']}, 'rows': [
            {'sample_id': 't1', 'blocks': [{'role': 'user', 'text': 'Ask'}, {'role': 'assistant', 'text': 'Answer'}], 'source_group_id': 'g'},
            {'sample_id': 'v1', 'blocks': [], 'metadata': {'input_text': 'Label me', 'label': 'yes'}},
        ]}
        cases = cases_from_manifest(prepared)
        self.assertEqual([case['case_id'] for case in cases], ['t1'])
        self.assertEqual(cases[0]['expected_output'], 'Answer')
        prepared['split_manifest']['test'] = []
        annotation = cases_from_manifest(prepared)
        self.assertEqual(annotation[0]['input_prompt'], 'Label me')
        self.assertEqual(annotation[0]['slice'], 'held_out')

    def test_confirmed_questions_reject_blank_answers(self):
        with self.assertRaises(ValueError):
            normalize_questions([{'input_prompt': 'Ask', 'expected_output': '   '}])
        cases = normalize_questions([{'input_prompt': ' Ask ', 'expected_output': ' Answer '}])
        self.assertEqual(cases[0]['case_id'], 'question-1')
        self.assertEqual(cases[0]['slice'], 'confirmed')
        self.assertEqual(cases[0]['input_prompt'], 'Ask')
