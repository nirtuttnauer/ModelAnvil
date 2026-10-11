"""Tests for model, tokenizer, and evaluation registries and baseline executor (WP-07 / TECH-015, TECH-020)."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.runners.compatibility import (
    detect_eval_contamination,
    validate_model_tokenizer_compatibility,
)
from modelanvil.runners.eval_executor import run_baseline_evaluation
from modelanvil.runners.models import (
    EvaluationCaseResult,
    EvaluationMetric,
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
)


class ModelTokenizerRegistryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="runners-test", name="Runners Test")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="llama-tok",
            revision_no=1,
            vocabulary_size=32000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>", "pad_token": "<pad>"},
            chat_template="{% for message in messages %}{{ message['role'] }}: {{ message['content'] }}{% endfor %}",
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="llama-7b",
            intended_tasks=["chat", "sft"],
        )
        self.model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="llama",
            tokenizer=self.tokenizer,
            metadata={"vocab_size": 32000},
        )

    def test_compatible_model_and_tokenizer_passes(self):
        details = validate_model_tokenizer_compatibility(self.model_version, self.tokenizer)
        self.assertEqual(details["status"], "compatible")
        self.assertEqual(details["vocabulary_size"], 32000)

    def test_vocabulary_mismatch_blocks_allocation(self):
        bad_tok = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="mismatched-tok",
            revision_no=1,
            vocabulary_size=50000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>", "pad_token": "<pad>"},
            chat_template=self.tokenizer.chat_template,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_model_tokenizer_compatibility(self.model_version, bad_tok)
        self.assertIn("vocab_size", ctx.exception.message_dict)

    def test_missing_special_tokens_blocks_allocation(self):
        bad_tok = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="missing-tokens-tok",
            revision_no=1,
            vocabulary_size=32000,
            special_tokens={"eos_token": "</s>"},  # missing bos_token and pad_token for chat
            chat_template=self.tokenizer.chat_template,
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_model_tokenizer_compatibility(self.model_version, bad_tok)
        self.assertIn("special_tokens", ctx.exception.message_dict)

    def test_chat_template_drift_blocks_allocation(self):
        bad_tok = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="drift-tok",
            revision_no=1,
            vocabulary_size=32000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>", "pad_token": "<pad>"},
            chat_template="static text without messages loop",
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_model_tokenizer_compatibility(self.model_version, bad_tok)
        self.assertIn("chat_template", ctx.exception.message_dict)

    def test_detect_eval_contamination(self):
        eval_cases = [
            {"case_id": "c1", "input_prompt": "What is 2+2?", "expected_output": "4"},
            {"case_id": "c2", "input_prompt": "Capital of France?", "expected_output": "Paris"},
        ]
        clean_training = [
            {"text": "Python is a programming language."},
            {"text": "Photosynthesis produces oxygen."},
        ]
        clean_report = detect_eval_contamination(clean_training, eval_cases)
        self.assertFalse(clean_report.is_contaminated)
        self.assertEqual(clean_report.contaminated_count, 0)

        # Contaminated training row
        contaminated_training = [
            {"text": "Python is a programming language."},
            {"text": "What is 2+2? 4"},
        ]
        dirty_report = detect_eval_contamination(contaminated_training, eval_cases)
        self.assertTrue(dirty_report.is_contaminated)
        self.assertEqual(dirty_report.contaminated_count, 1)
        self.assertEqual(dirty_report.contaminated_cases[0]["case_id"], "c1")


class BaselineEvaluationExecutorTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="eval-test", name="Eval Test")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id, name="t1", vocabulary_size=1000,
        )
        self.model = Model.objects.create(tenant_id=self.tenant.tenant_id, name="candidate-m")
        self.model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id, model=self.model, tokenizer=self.tokenizer,
        )
        self.suite = EvaluationSuite.objects.create(
            tenant_id=self.tenant.tenant_id, name="core-reasoning",
        )
        self.suite_version = EvaluationSuiteVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            suite=self.suite,
            revision_no=1,
            scorer_type="exact_match",
            cases=[
                {"case_id": "case-1", "input_prompt": "Question 1", "expected_output": "Answer 1", "slice": "reasoning"},
                {"case_id": "case-2", "input_prompt": "Question 2", "expected_output": "Answer 2", "slice": "reasoning"},
                {"case_id": "case-3", "input_prompt": "Question 3", "expected_output": "Answer 3", "slice": "knowledge"},
            ],
        )

    def test_run_baseline_evaluation_produces_case_results_and_slice_metrics(self):
        run = run_baseline_evaluation(self.suite_version, self.model_version)

        self.assertEqual(run.status, EvaluationRun.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

        # Verify case results
        results = EvaluationCaseResult.objects.filter(run=run)
        self.assertEqual(results.count(), 3)
        self.assertTrue(all(r.passed for r in results))

        # Verify aggregate metrics across slices
        metrics = EvaluationMetric.objects.filter(run=run)
        metric_slices = {m.slice_name: m for m in metrics}
        self.assertIn("all", metric_slices)
        self.assertIn("reasoning", metric_slices)
        self.assertIn("knowledge", metric_slices)

        self.assertEqual(metric_slices["all"].sample_count, 3)
        self.assertEqual(metric_slices["all"].value, 1.0)
        self.assertIn("confidence", metric_slices["all"].uncertainty_interval)
        self.assertEqual(metric_slices["reasoning"].sample_count, 2)

    def test_run_baseline_evaluation_records_failures_accurately(self):
        # Mock runner returning incorrect answer for case-2
        def failing_runner(prompt: str, params: dict):
            if "Question 2" in prompt:
                return "Wrong Answer"
            return "Answer 1" if "Question 1" in prompt else "Answer 3"

        run = run_baseline_evaluation(
            self.suite_version, self.model_version, runner_fn=failing_runner,
        )

        case2_res = EvaluationCaseResult.objects.get(run=run, case_id="case-2")
        self.assertFalse(case2_res.passed)
        self.assertIn("Expected 'Answer 2', got 'Wrong Answer'", case2_res.failure_reason)

        all_metric = EvaluationMetric.objects.get(run=run, key="accuracy", slice_name="all")
        # 2 out of 3 passed -> 0.6667
        self.assertAlmostEqual(all_metric.value, 0.6667, places=3)
