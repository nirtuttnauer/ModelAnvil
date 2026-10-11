"""Tests for LLM-as-a-Judge Calibration Engine (Inter-rater agreement & bias detection)."""
from __future__ import annotations

from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.runners.judge_calibration import (
    calibrate_llm_judge,
    compute_cohens_kappa,
    compute_position_bias,
    compute_verbosity_bias,
)
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion


class JudgeCalibrationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="judge-org", name="Judge Org")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="j-tok",
            vocabulary_size=32000,
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="judge-model-70b",
        )
        self.judge_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="llama-70b",
            tokenizer=self.tokenizer,
            state=ModelVersion.State.QUALIFIED,
        )

    def test_compute_cohens_kappa_perfect_and_chance(self):
        # Perfect agreement
        j = ["candidate_a", "candidate_b", "tie", "candidate_a"]
        h = ["candidate_a", "candidate_b", "tie", "candidate_a"]
        self.assertEqual(compute_cohens_kappa(j, h), 1.0)

        # Poor agreement (worse than chance)
        j2 = ["candidate_a", "candidate_b", "candidate_a", "candidate_b"]
        h2 = ["candidate_b", "candidate_a", "candidate_b", "candidate_a"]
        self.assertLess(compute_cohens_kappa(j2, h2), 0.0)

    def test_detect_position_bias(self):
        # Balanced
        choices = ["candidate_a", "candidate_b", "candidate_a", "candidate_b"]
        self.assertEqual(compute_position_bias(choices), 0.50)

        # Strong A-bias
        choices_biased = ["candidate_a", "candidate_a", "candidate_a", "candidate_b"]
        self.assertEqual(compute_position_bias(choices_biased), 0.75)

    def test_detect_verbosity_bias(self):
        # Systematic preference for whichever response is longer
        samples = [
            {"candidate_a_text": "Short", "candidate_b_text": "Much longer verbose answer that elaborates"},
            {"candidate_a_text": "A very long detailed paragraph with lots of words", "candidate_b_text": "Concise"},
        ]
        # Judge picked longer option in both cases
        judge_choices = ["candidate_b", "candidate_a"]
        corr = compute_verbosity_bias(samples, judge_choices)
        self.assertGreaterEqual(corr, 0.90)

    def test_calibrate_llm_judge_qualifies_good_judge(self):
        dataset = [
            {"human_choice": "candidate_a", "judge_choice": "candidate_a", "candidate_a_text": "A1", "candidate_b_text": "B1"},
            {"human_choice": "candidate_b", "judge_choice": "candidate_b", "candidate_a_text": "A2", "candidate_b_text": "B2"},
            {"human_choice": "candidate_a", "judge_choice": "candidate_a", "candidate_a_text": "A3", "candidate_b_text": "B3"},
            {"human_choice": "candidate_b", "judge_choice": "candidate_b", "candidate_a_text": "A4", "candidate_b_text": "B4"},
            {"human_choice": "tie", "judge_choice": "tie", "candidate_a_text": "A5", "candidate_b_text": "B5"},
        ]
        record, result = calibrate_llm_judge(self.judge_version, dataset, min_kappa_threshold=0.70)
        self.assertEqual(result.status, "qualified")
        self.assertEqual(record.status, "qualified")
        self.assertEqual(len(result.rejection_reasons), 0)
        self.assertGreaterEqual(result.agreement_score, 0.70)

    def test_calibrate_llm_judge_rejects_erratic_or_biased_judge(self):
        dataset = [
            {"human_choice": "candidate_a", "judge_choice": "candidate_b", "candidate_a_text": "A1", "candidate_b_text": "B1"},
            {"human_choice": "candidate_b", "judge_choice": "candidate_a", "candidate_a_text": "A2", "candidate_b_text": "B2"},
            {"human_choice": "candidate_a", "judge_choice": "candidate_b", "candidate_a_text": "A3", "candidate_b_text": "B3"},
        ]
        record, result = calibrate_llm_judge(self.judge_version, dataset, min_kappa_threshold=0.70)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(record.status, "rejected")
        self.assertTrue(any("below minimum threshold" in r for r in result.rejection_reasons))
