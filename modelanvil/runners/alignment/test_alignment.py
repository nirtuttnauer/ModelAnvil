"""Unit and acceptance tests for WP-11 Alignment: DPO, Reward Model, RLHF, Verifier, and Release Gates."""
import uuid
from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.runners.models import (
    Model,
    ModelVersion,
    TokenizerVersion,
    EvaluationSuite,
    EvaluationSuiteVersion,
    EvaluationRun,
    EvaluationMetric,
    AlignmentRun,
    AlignmentCheckpoint,
)
from modelanvil.runners.alignment.preferences import (
    PreferencePair,
    PreferenceDataset,
    build_preference_dataset_from_records,
    score_distribution_summary,
)
from modelanvil.runners.alignment.dpo import DPOEngine
from modelanvil.runners.alignment.reward_model import RewardModelEngine
from modelanvil.runners.alignment.rlhf import RLHFOrchestrator
from modelanvil.runners.alignment.verifier import VerifierEngine
from modelanvil.runners.alignment.release_gate import (
    evaluate_alignment_release_gate,
    AlignmentReleaseGateResult,
)


class AlignmentTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="align-test-org", name="Align Test Org")
        self.tenant_id = self.tenant.tenant_id
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant_id,
            name="llama-align-tok",
            revision_no=1,
            vocabulary_size=32000,
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant_id,
            name="llama-8b-instruct",
            description="Base instruct model",
        )
        self.base_model = ModelVersion.objects.create(
            tenant_id=self.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="llama-8b",
            tokenizer=self.tokenizer,
            parameters_count=8_000_000_000,
            state=ModelVersion.State.QUALIFIED,
        )
        self.preference_raw_records = [
            {
                "prompt": "How to center a div in CSS?",
                "candidate_a": "Use display: flex; justify-content: center; align-items: center;",
                "candidate_b": "Use <center> tag.",
                "choice": "candidate_a",
            },
            {
                "prompt": "Explain photosynthesis.",
                "candidate_a": "Plants eat dirt and grow leaves.",
                "candidate_b": "Photosynthesis is the process by which green plants transform light energy into chemical energy.",
                "choice": "candidate_b",
            },
            {
                "prompt": "What is 2 + 2?",
                "candidate_a": "4",
                "candidate_b": "Four",
                "choice": "tie",
            },
            {
                "prompt": "Unclear query",
                "candidate_a": "Foo",
                "candidate_b": "Bar",
                "choice": "abstain",
            },
            {
                "prompt": "How to sort a list in Python?",
                "candidate_a": "Use sorted(lst) or lst.sort()",
                "candidate_b": "Write your own bubble sort from scratch",
                "choice": "candidate_a",
            },
            {
                "prompt": "What is the capital of France?",
                "candidate_a": "Paris",
                "candidate_b": "Berlin",
                "choice": "candidate_a",
            },
            {
                "prompt": "What is water made of?",
                "candidate_a": "Hydrogen and Oxygen",
                "candidate_b": "Nitrogen and Carbon",
                "choice": "candidate_a",
            },
        ]

    def test_preference_dataset_building_and_ties(self):
        """TECH-018: Validated human preference pair construction, tie/abstention separation, and digests."""
        train_ds, held_out_ds = build_preference_dataset_from_records(
            self.preference_raw_records, held_out_ratio=0.2, seed=42
        )

        self.assertEqual(train_ds.ties_count, 1)
        self.assertEqual(train_ds.abstentions_count, 1)
        self.assertEqual(len(train_ds) + len(held_out_ds), 5)
        self.assertIsNotNone(train_ds.digest)
        self.assertIsNotNone(held_out_ds.digest)
        self.assertNotEqual(train_ds.digest, held_out_ds.digest)

        # Check score distribution calculation
        dist = score_distribution_summary([2.5, 3.0, 1.8], [0.5, 1.0, 1.2])
        self.assertEqual(dist["count"], 3)
        self.assertGreater(dist["margin_mean"], 1.0)
        self.assertEqual(dist["accuracy"], 1.0)

    def test_dpo_engine_and_held_out_validation(self):
        """PRD Scenario 3: DPO training recipe, implicit reward tracking, held-out evaluation, and export."""
        train_ds, held_out_ds = build_preference_dataset_from_records(self.preference_raw_records)

        alignment_run = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.DPO,
            policy_model_version=self.base_model,
        )

        engine = DPOEngine(policy_model=self.base_model, reference_model=self.base_model, beta=0.1)
        run = engine.run_dpo(alignment_run, train_ds, held_out_ds, total_steps=4)

        self.assertEqual(run.status, AlignmentRun.Status.COMPLETED)
        self.assertEqual(run.current_step, 4)
        self.assertIsNotNone(run.output_model_version)
        self.assertEqual(run.output_model_version.state, ModelVersion.State.DRAFT)
        self.assertEqual(len(run.metrics_history), 4)
        self.assertGreater(run.latest_metrics["held_out_evaluation"]["accuracy"], 0.0)

        # Verify checkpoint
        self.assertGreaterEqual(run.checkpoints.count(), 1)

        # External loadable export bundle
        bundle = engine.export_bundle(run)
        self.assertEqual(bundle["algorithm"], "dpo")
        self.assertEqual(bundle["model_version_id"], str(run.output_model_version.model_version_id))
        self.assertNotEqual(bundle["state_digest"], "")

    def test_reward_model_training_and_score_distribution(self):
        """PRD Scenario 3: Bradley-Terry Reward Model training, score distributions, and draft candidate."""
        train_ds, held_out_ds = build_preference_dataset_from_records(self.preference_raw_records)

        alignment_run = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.REWARD_MODEL,
            policy_model_version=self.base_model,
        )

        engine = RewardModelEngine(base_model=self.base_model)
        run = engine.run_training(alignment_run, train_ds, held_out_ds, total_steps=4)

        self.assertEqual(run.status, AlignmentRun.Status.COMPLETED)
        self.assertEqual(run.output_model_version.metadata["model_type"], "reward_model")
        self.assertGreater(run.latest_metrics["score_distribution"]["margin_mean"], 0)
        self.assertGreater(run.latest_metrics["held_out_evaluation"]["accuracy"], 0)

        bundle = engine.export_bundle(run)
        self.assertEqual(bundle["model_type"], "reward_model")
        self.assertIn("score_distribution", bundle)

    def test_complete_rlhf_orchestration_and_recovery(self):
        """PRD Scenario 13 & 8: Complete learned-reward RLHF, rollouts, KL control, checkpoint recovery."""
        reward_model = ModelVersion.objects.create(
            tenant_id=self.tenant_id,
            model=self.base_model.model,
            revision_no=2,
            architecture_ref="llama-8b-rm",
            tokenizer=self.base_model.tokenizer,
            state=ModelVersion.State.QUALIFIED,
            metadata={"model_type": "reward_model"},
        )

        prompts = [
            "Write a summary of quantum physics.",
            "How do airplanes stay in the air?",
            "Explain gradient descent.",
        ]

        alignment_run = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )

        orchestrator = RLHFOrchestrator(
            policy_model=self.base_model,
            reference_model=self.base_model,
            reward_model=reward_model,
            beta_kl=0.05,
            budget_limit_dollars=50.0,
        )

        # Step 1: Run until step 2
        run = orchestrator.run_rlhf(alignment_run, prompts, total_steps=2)
        self.assertEqual(run.current_step, 2)
        self.assertTrue(run.checkpoints.filter(step=2).exists())

        # Step 2: Interrupt and resume from step 2 to step 4
        resumed_run = orchestrator.resume_from_checkpoint(
            alignment_run=run,
            prompts=prompts,
            checkpoint_step=2,
            target_steps=4,
        )

        self.assertEqual(resumed_run.status, AlignmentRun.Status.COMPLETED)
        self.assertEqual(resumed_run.current_step, 4)
        self.assertGreater(resumed_run.latest_metrics["net_reward_mean"], 0)
        self.assertGreater(resumed_run.latest_metrics["kl_divergence"], 0)
        self.assertFalse(resumed_run.latest_metrics["reward_hacking_detected"])

        export = orchestrator.export_bundle(resumed_run)
        self.assertEqual(export["algorithm"], "ppo_rlhf")
        self.assertIsNotNone(export["weights_manifest"])

    def test_rlhf_budget_and_divergence_limits(self):
        """TECH-019 / PRD Scenario 13: Stop limits on budget breach and KL divergence runaway."""
        reward_model = self.base_model
        prompts = ["Test prompt 1", "Test prompt 2"]

        # Test budget limit breach
        run_budget = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )
        orch_budget = RLHFOrchestrator(
            policy_model=self.base_model,
            reference_model=self.base_model,
            reward_model=reward_model,
            budget_limit_dollars=2.0,  # Strict budget
            cost_per_step_dollars=1.5,
        )
        stopped_run = orch_budget.run_rlhf(run_budget, prompts, total_steps=5)
        self.assertEqual(stopped_run.status, AlignmentRun.Status.FAILED)
        self.assertEqual(stopped_run.stop_reason, "budget_limit_exceeded")

        # Test KL divergence breach
        run_kl = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )
        orch_kl = RLHFOrchestrator(
            policy_model=self.base_model,
            reference_model=self.base_model,
            reward_model=reward_model,
            max_kl_divergence=0.1,  # Super tight limit
        )
        stopped_kl = orch_kl.run_rlhf(run_kl, prompts, total_steps=5)
        self.assertEqual(stopped_kl.status, AlignmentRun.Status.FAILED)
        self.assertEqual(stopped_kl.stop_reason, "kl_divergence_breach")

    def test_verifier_rl_recipe_and_exploit_detection(self):
        """PRD Scenario 4: Verifier-based RL in bounded environment, trajectory logs, and exploit penalty."""
        tasks = [
            {"prompt": "Calculate 15 * 12", "ground_truth": "180"},
            {"prompt": "Calculate 7 * 8", "ground_truth": "56"},
        ]

        engine = VerifierEngine(policy_model=self.base_model, domain_type="math_reasoning")

        # Clean run
        run_clean = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.VERIFIER_RL,
            policy_model_version=self.base_model,
        )
        res_clean = engine.run_verifier_rl(run_clean, tasks, total_steps=3, inject_exploit=False)
        self.assertEqual(res_clean.status, AlignmentRun.Status.COMPLETED)
        self.assertEqual(res_clean.latest_metrics["pass_rate"], 1.0)
        self.assertFalse(res_clean.latest_metrics["exploit_detected"])

        # Exploit run (reward hacking attempt via format padding and bypass)
        run_exploit = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.VERIFIER_RL,
            policy_model_version=self.base_model,
        )
        res_exploit = engine.run_verifier_rl(run_exploit, tasks, total_steps=2, inject_exploit=True)
        self.assertEqual(res_exploit.status, AlignmentRun.Status.COMPLETED)
        self.assertTrue(res_exploit.latest_metrics["exploit_detected"])
        self.assertEqual(res_exploit.latest_metrics["pass_rate"], 0.0)
        self.assertEqual(res_exploit.latest_metrics["average_reward"], -1.0)

    def test_release_gate_rejects_rising_learned_reward_alone(self):
        """TECH-019, TECH-021, PRD Scenario 13: Rising learned reward CANNOT satisfy release gate alone."""
        reward_model = self.base_model
        orch = RLHFOrchestrator(
            policy_model=self.base_model,
            reference_model=self.base_model,
            reward_model=reward_model,
        )
        alignment_run = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )
        run = orch.run_rlhf(alignment_run, ["Prompt 1"], total_steps=2)

        # Attempt release gate evaluation WITHOUT independent evaluation
        gate_res_no_eval = evaluate_alignment_release_gate(run, independent_eval_run=None)
        self.assertFalse(gate_res_no_eval.passed)
        self.assertFalse(gate_res_no_eval.promoted)
        self.assertTrue(any("Rising learned reward cannot satisfy release gates" in r for r in gate_res_no_eval.rejection_reasons))
        self.assertEqual(run.output_model_version.state, ModelVersion.State.REJECTED)

        # Inject reward hacking and test rejection
        run_hacked = AlignmentRun.objects.create(
            tenant_id=self.tenant_id,
            algorithm=AlignmentRun.Algorithm.PPO_RLHF,
            policy_model_version=self.base_model,
        )
        orch.run_rlhf(run_hacked, ["Prompt 1"], total_steps=2, inject_reward_hacking=True)

        suite = EvaluationSuite.objects.create(tenant_id=self.tenant_id, name="Independent Math Suite")
        suite_ver = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant_id, suite=suite, cases=[])
        eval_run = EvaluationRun.objects.create(
            tenant_id=self.tenant_id,
            suite_version=suite_ver,
            candidate_model_version=run_hacked.output_model_version,
            status=EvaluationRun.Status.COMPLETED,
        )
        EvaluationMetric.objects.create(
            tenant_id=self.tenant_id,
            run=eval_run,
            key="accuracy",
            value=0.95,
        )

        gate_res_hacked = evaluate_alignment_release_gate(run_hacked, independent_eval_run=eval_run)
        self.assertFalse(gate_res_hacked.passed)
        self.assertTrue(any("Reward hacking" in r for r in gate_res_hacked.rejection_reasons))

        # Valid independent evaluation passing gate
        gate_res_valid = evaluate_alignment_release_gate(run, independent_eval_run=eval_run)
        self.assertFalse(gate_res_valid.passed)
        self.assertFalse(gate_res_valid.promoted)
        run.output_model_version.refresh_from_db()
        self.assertEqual(run.output_model_version.state, ModelVersion.State.REJECTED)
