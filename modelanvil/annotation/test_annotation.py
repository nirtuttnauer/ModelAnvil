"""Comprehensive tests for annotation, ranking, synthetic data, and iterative labeling campaigns (WP-09, WP-10 / TECH-011-014 / PRD Scenario 17)."""
from __future__ import annotations

import hashlib
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.annotation.campaign_engine import CampaignEngine
from modelanvil.annotation.models import (
    AnnotationRecord,
    AnnotationTask,
    CampaignBatch,
    CumulativeSnapshot,
    LabelSchema,
    LabelingCampaign,
    RubricRevision,
)
from modelanvil.annotation.synthetic import generate_synthetic_records
from modelanvil.identity.models import Tenant
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion


class AnnotationCoreAndSyntheticTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="ann-test", name="Annotation Test")
        self.schema = LabelSchema.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="sentiment-v1",
            kind=LabelSchema.Kind.CLASSIFICATION,
            classes=["positive", "negative", "neutral"],
        )
        self.rubric = RubricRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="sentiment-guidelines",
            revision_no=1,
            guidelines_text="Label based on explicit tone.",
        )
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="ann-tok",
            vocabulary_size=1000,
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="drafter-v1",
        )
        self.model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            tokenizer=self.tokenizer,
        )
        self.engine = CampaignEngine()

    def test_submit_review_preserves_prediction_and_detects_concurrency_conflict(self):
        campaign = self.engine.create_campaign(
            name="c-conflict",
            tenant_id=self.tenant.tenant_id,
            label_schema=self.schema,
            seed_mode=LabelingCampaign.SeedMode.MANUAL,
        )
        batch = self.engine.start_batch(campaign, [{"id": "s-1", "text": "Great service!"}])
        task = AnnotationTask.objects.get(batch=batch)

        # Attach original model prediction
        task.content["draft_prediction"] = {"predicted_label": "positive", "confidence": 0.85}
        task.save()

        # Reviewer 1 submits review
        rec1 = self.engine.submit_review(
            task=task,
            reviewer_id="reviewer-alice",
            human_label={"label": "positive"},
            decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
            expected_revision=1,
            time_spent_seconds=12.5,
        )
        self.assertEqual(rec1.revision_no, 1)
        self.assertEqual(rec1.original_prediction["predicted_label"], "positive")
        self.assertEqual(task.status, AnnotationTask.Status.COMPLETED)

        # Reviewer 2 attempts concurrent edit with stale expected_revision=1
        with self.assertRaises(ValidationError) as ctx:
            self.engine.submit_review(
                task=task,
                reviewer_id="reviewer-bob",
                human_label={"label": "neutral"},
                decision=AnnotationRecord.Decision.CORRECTED,
                expected_revision=1,  # Stale!
            )
        self.assertIn("Concurrent edit conflict", str(ctx.exception))

    def test_blind_preference_with_ties_and_abstention(self):
        pref_schema = LabelSchema.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="pair-pref",
            kind=LabelSchema.Kind.PREFERENCE_RANKING,
        )
        campaign = self.engine.create_campaign(
            name="c-pref",
            tenant_id=self.tenant.tenant_id,
            label_schema=pref_schema,
            seed_mode=LabelingCampaign.SeedMode.MANUAL,
        )
        batch = self.engine.start_batch(
            campaign, [{"id": "pair-1", "cand_a": "Answer A", "cand_b": "Answer B"}]
        )
        task = AnnotationTask.objects.get(batch=batch)

        rec = self.engine.submit_review(
            task=task,
            reviewer_id="judge-1",
            human_label={"winner": "tie"},
            decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
            is_blind_preference=True,
            preference_choice="tie",
        )
        self.assertTrue(rec.is_blind_preference)
        self.assertEqual(rec.preference_choice, "tie")

    def test_synthetic_generation_preserves_provenance_and_denies_protected_cases(self):
        protected_prompt = "What is the capital of France?"
        protected_hash = hashlib.sha256(protected_prompt.encode("utf-8")).hexdigest()

        # Seed with clean prompts
        clean_inputs = [{"text": "Summarize the story of Cinderella."}]
        syn_records = generate_synthetic_records(
            prompt_template="Instruction: {input}",
            prompt_revision=1,
            seed_inputs=clean_inputs,
            model_version=self.model_version,
            decoding_params={"temperature": 0.8},
            protected_eval_hashes={protected_hash},
        )
        self.assertEqual(len(syn_records), 1)
        self.assertEqual(syn_records[0].provenance["origin"], "synthetic")
        self.assertEqual(syn_records[0].provenance["prompt_revision"], 1)

        # Attempt to use protected benchmark prompt as synthetic seed (TECH-014)
        dirty_inputs = [{"text": protected_prompt}]
        with self.assertRaises(ValidationError) as ctx:
            generate_synthetic_records(
                prompt_template="Instruction: {input}",
                prompt_revision=1,
                seed_inputs=dirty_inputs,
                model_version=self.model_version,
                protected_eval_hashes={protected_hash},
            )
        self.assertIn("matches a protected evaluation benchmark case", str(ctx.exception))


class IterativeLabelingJourneyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="iter-org", name="Iterative Org")
        self.schema = LabelSchema.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="topic-class",
            kind=LabelSchema.Kind.CLASSIFICATION,
            classes=["sports", "tech", "politics"],
        )
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="it-tok",
            vocabulary_size=1000,
        )
        self.engine = CampaignEngine()

    def test_prd_scenario_17_iterative_labeling_two_cycles(self):
        # 1. Setup campaign with reserved audit set (TECH-012, TECH-013)
        audit_samples = [
            {"id": "audit-1", "text": "Football championship results.", "expected": "sports"},
            {"id": "audit-2", "text": "New GPU release benchmarks.", "expected": "tech"},
        ]
        campaign = self.engine.create_campaign(
            name="topic-campaign",
            tenant_id=self.tenant.tenant_id,
            label_schema=self.schema,
            seed_mode=LabelingCampaign.SeedMode.MANUAL,
            audit_samples=audit_samples,
            max_cycles=3,
        )
        self.assertEqual(campaign.current_cycle, 0)
        self.assertNotEqual(campaign.held_out_audit_digest, "")

        # --- CYCLE 1: Seed Batch (Manual) ---
        seed_samples = [
            {"id": "s-1", "text": "Basketball playoff scores."},
            {"id": "s-2", "text": "AI model training throughput."},
        ]
        batch_1 = self.engine.start_batch(campaign, seed_samples)
        self.assertEqual(batch_1.cycle_no, 1)
        self.assertIsNone(batch_1.assigned_drafting_model)

        # Review seed items
        tasks_b1 = list(AnnotationTask.objects.filter(batch=batch_1))
        self.engine.submit_review(
            task=tasks_b1[0],
            reviewer_id="human-1",
            human_label={"label": "sports"},
            decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
        )
        self.engine.submit_review(
            task=tasks_b1[1],
            reviewer_id="human-1",
            human_label={"label": "tech"},
            decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
        )

        # Close batch 1 -> creates CumulativeSnapshot 1
        snap_1 = self.engine.close_batch(batch_1)
        self.assertEqual(snap_1.cycle_no, 1)
        self.assertEqual(snap_1.item_count, 2)
        self.assertEqual(campaign.current_cycle, 1)

        # Train labeling model version 1 from Snapshot 1
        cand_model_1 = self.engine.train_candidate_model(campaign, batch_1)
        self.assertIsNotNone(cand_model_1)

        # Qualify candidate model 1 against audit set -> passes gate (0.85 >= 0.70)
        advance_res_1 = self.engine.qualify_and_advance(
            campaign, cand_model_1, eval_score_fn=lambda m: 0.85, min_score_threshold=0.70
        )
        self.assertEqual(advance_res_1["decision"], "promoted")
        self.assertEqual(campaign.active_drafting_model, cand_model_1)

        # --- CYCLE 2: Model-Assisted Batch 2 ---
        batch_2_samples = [
            {"id": "s-3", "text": "Soccer tournament update."},
            {"id": "s-4", "text": "Election polling trends."},
        ]
        batch_2 = self.engine.start_batch(campaign, batch_2_samples)
        self.assertEqual(batch_2.cycle_no, 2)
        # Assigned model is pinned to cand_model_1
        self.assertEqual(batch_2.assigned_drafting_model, cand_model_1)

        # Generate model drafts using pinned model
        def mock_drafter(content):
            txt = content.get("text", "")
            return {
                "predicted_label": "sports" if "soccer" in txt.lower() else "politics",
                "confidence": 0.92,
            }

        draft_count = self.engine.generate_drafts(batch_2, drafter_fn=mock_drafter)
        self.assertEqual(draft_count, 2)

        # Human reviews drafts: accept one, correct one
        tasks_b2 = list(AnnotationTask.objects.filter(batch=batch_2))
        rec_accept = self.engine.submit_review(
            task=tasks_b2[0],
            reviewer_id="human-2",
            human_label={"label": "sports"},
            decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT,
        )
        self.assertEqual(rec_accept.original_prediction["predicted_label"], "sports")

        rec_correct = self.engine.submit_review(
            task=tasks_b2[1],
            reviewer_id="human-2",
            human_label={"label": "politics"},
            decision=AnnotationRecord.Decision.CORRECTED,
        )
        self.assertEqual(rec_correct.decision, AnnotationRecord.Decision.CORRECTED)

        # Close batch 2 -> creates CumulativeSnapshot 2 (2 from b1 + 2 from b2 = 4 total, no double counting)
        snap_2 = self.engine.close_batch(batch_2)
        self.assertEqual(snap_2.cycle_no, 2)
        self.assertEqual(snap_2.item_count, 4)
        self.assertEqual(campaign.current_cycle, 2)

        # Train candidate model 2 from accumulated 4 approved examples
        cand_model_2 = self.engine.train_candidate_model(campaign, batch_2)
        self.assertIsNotNone(cand_model_2)

        # Advance candidate model 2 -> promoted
        advance_res_2 = self.engine.qualify_and_advance(
            campaign, cand_model_2, eval_score_fn=lambda m: 0.90, min_score_threshold=0.70
        )
        self.assertEqual(advance_res_2["decision"], "promoted")
        self.assertEqual(campaign.active_drafting_model, cand_model_2)

    def test_failed_candidate_preserves_prior_model_and_labels(self):
        # Create base model
        base_m = Model.objects.create(tenant_id=self.tenant.tenant_id, name="base-clf")
        base_mv = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id, model=base_m, tokenizer=self.tokenizer
        )

        campaign = self.engine.create_campaign(
            name="fail-test-camp",
            tenant_id=self.tenant.tenant_id,
            label_schema=self.schema,
            seed_mode=LabelingCampaign.SeedMode.EXISTING_MODEL,
            active_drafting_model=base_mv,
        )
        batch = self.engine.start_batch(campaign, [{"id": "t-1", "text": "Sample 1"}, {"id": "t-2", "text": "Sample 2"}])
        tasks = list(AnnotationTask.objects.filter(batch=batch))
        for t in tasks:
            self.engine.submit_review(
                task=t, reviewer_id="user", human_label={"label": "sports"}, decision=AnnotationRecord.Decision.ACCEPTED_WITHOUT_EDIT
            )
        self.engine.close_batch(batch)

        cand_model = self.engine.train_candidate_model(campaign, batch)

        # Evaluation score is poor (0.45 < 0.70 threshold)
        advance_res = self.engine.qualify_and_advance(
            campaign, cand_model, eval_score_fn=lambda m: 0.45, min_score_threshold=0.70
        )
        self.assertEqual(advance_res["decision"], "rejected")
        # Prior active drafting model is preserved!
        self.assertEqual(campaign.active_drafting_model, base_mv)

    def test_campaign_pause_resume_and_rollback(self):
        campaign = self.engine.create_campaign(
            name="lifecycle-camp",
            tenant_id=self.tenant.tenant_id,
            label_schema=self.schema,
            seed_mode=LabelingCampaign.SeedMode.MANUAL,
        )
        # Pause
        self.engine.pause_campaign(campaign)
        self.assertEqual(campaign.status, LabelingCampaign.Status.PAUSED)

        # Starting batch on paused campaign is blocked
        with self.assertRaises(ValidationError) as ctx:
            self.engine.start_batch(campaign, [{"id": "s-1"}])
        self.assertIn("campaign is paused", str(ctx.exception))

        # Resume
        self.engine.resume_campaign(campaign)
        self.assertEqual(campaign.status, LabelingCampaign.Status.ACTIVE)

        batch = self.engine.start_batch(campaign, [{"id": "s-1"}])
        self.assertEqual(batch.status, CampaignBatch.Status.OPEN)

        # Rollback model
        self.engine.rollback_model(campaign, target_model=None)
        self.assertIsNone(campaign.active_drafting_model)
