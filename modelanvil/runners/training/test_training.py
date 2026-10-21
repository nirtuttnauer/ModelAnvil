"""Comprehensive test suite for training vertical slices (WP-08 / TECH-016, TECH-017 / PRD Scenarios 1, 2, 8)."""
from __future__ import annotations

import math
import uuid
from django.core.exceptions import ValidationError
from django.test import TestCase

from modelanvil.identity.models import Tenant
from modelanvil.runners.models import (
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingCheckpoint,
    TrainingRun,
)
from modelanvil.runners.training.engine import TrainingEngine
from modelanvil.runners.training.preflight import (
    estimate_parameter_count,
    estimate_training_flops,
    preview_encoded_samples,
    validate_training_preflight,
)
from modelanvil.runners.training.sweeps import run_bounded_parameter_sweep


class TrainingPreflightTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="trn-test", name="Training Test")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="test-tok",
            vocabulary_size=32000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>", "pad_token": "<pad>"},
            chat_template="{% for message in messages %}{{ message['role'] }}: {{ message['content'] }}{% endfor %}",
        )
        self.base_model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="base-llama",
            intended_tasks=["chat"],
        )
        self.base_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.base_model,
            tokenizer=self.tokenizer,
            metadata={"vocab_size": 32000, "parameter_count": 125000000},
        )

    def test_preflight_blocks_unsupported_recipe_and_precision(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type="unsupported_quantum_ml",
                tokenizer_version=self.tokenizer,
            )
        self.assertIn("Unsupported recipe type", str(ctx.exception))

        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
                tokenizer_version=self.tokenizer,
                hardware_config={"precision": "int8_experimental"},
            )
        self.assertIn("Precision 'int8_experimental' is unsupported", str(ctx.exception))

    def test_preflight_scratch_blocks_base_model_and_vocab_mismatch(self):
        # Scratch cannot have base model
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
                tokenizer_version=self.tokenizer,
                base_model_version=self.base_version,
            )
        self.assertIn("base_model_version must be None", str(ctx.exception))

        # Architecture vocab mismatch
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
                tokenizer_version=self.tokenizer,
                hyperparameters={
                    "architecture": {"n_layer": 6, "n_embd": 384, "vocab_size": 16000}
                },
            )
        self.assertIn("vocab_size (16000) does not match tokenizer", str(ctx.exception))

    def test_preflight_lora_requires_base_model_and_valid_r(self):
        # Missing base model
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
                tokenizer_version=self.tokenizer,
            )
        self.assertIn("requires a registered base_model_version", str(ctx.exception))

        # Invalid rank r <= 0
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
                tokenizer_version=self.tokenizer,
                base_model_version=self.base_version,
                hyperparameters={"lora_config": {"r": 0, "lora_alpha": 16}},
            )
        self.assertIn("rank r and lora_alpha must be positive", str(ctx.exception))

    def test_preflight_budget_exceeded_blocks_launch(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_training_preflight(
                recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
                tokenizer_version=self.tokenizer,
                hyperparameters={
                    "architecture": {"n_layer": 24, "n_embd": 2048, "vocab_size": 32000},
                    "max_steps": 100000,
                    "batch_size": 32,
                    "max_seq_len": 2048,
                },
                hardware_config={"slots_required": 8, "slot_hourly_rate": 5.0},
                budget_limit_dollars=10.0,  # $10 budget limit
            )
        self.assertIn("exceeds authorized project budget limit", str(ctx.exception))

    def test_preflight_approved_computes_estimates(self):
        result = validate_training_preflight(
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 6, "n_embd": 384, "vocab_size": 32000},
                "max_steps": 50,
                "batch_size": 4,
                "max_seq_len": 128,
            },
            hardware_config={"precision": "bf16", "slots_required": 1},
            budget_limit_dollars=500.0,
        )
        self.assertEqual(result["status"], "approved")
        self.assertGreater(result["parameter_count"], 0)
        self.assertGreater(result["estimated_flops"], 0)
        self.assertGreater(result["estimated_cost_dollars"], 0)

    def test_preview_encoded_samples(self):
        records = [
            {"messages": [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi!"}]},
            {"text": "Plain language pretraining sample."},
        ]
        # A tokenizer without a pinned character encoding cannot produce real ids.
        unknown = preview_encoded_samples(records, self.tokenizer, limit=2)
        self.assertEqual(len(unknown), 2)
        self.assertEqual(unknown[0]["encoding"], "unavailable")
        self.assertIsNone(unknown[0]["token_count"])
        self.assertIsNone(unknown[0]["sample_tokens"])
        self.assertIn("reason", unknown[0])

        # A pinned character-v1 tokenizer produces actual, verifiable token ids.
        tokens = ["<pad>", "<bos>", "<eos>", "<unk>", *list("helo i!.")]
        char_tok = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id, name="char-tok", vocabulary_size=len(tokens),
            special_tokens={"bos_token": "<s>", "eos_token": "</s>"},
            compatibility={"character_v1": {"tokens": tokens}},
        )
        previews = preview_encoded_samples([{"text": "hi"}], char_tok, limit=1)
        self.assertEqual(previews[0]["encoding"], "pinned")
        self.assertEqual(previews[0]["sample_tokens"], [1, tokens.index("h"), tokens.index("i"), 2])
        self.assertEqual(previews[0]["token_count"], 4)


class ScratchAndFineTuningJourneyTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="journeys", name="Journeys Org")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="j-tok",
            vocabulary_size=1000,
            special_tokens={"bos_token": "<s>", "eos_token": "</s>"},
        )
        self.engine = TrainingEngine()

    def test_candidate_models_stay_distinct_for_uuid7_runs_with_the_same_time_prefix(self):
        identifiers = [uuid.UUID('019a3621-4d78-7bd0-8e43-9a091242336a'),
                       uuid.UUID('019a3621-4d78-7bd0-8e43-9a091242336b')]
        runs = [TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id, run_id=identifier,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING, tokenizer_version=self.tokenizer,
            hyperparameters={'architecture': {'n_layer': 1, 'n_embd': 4, 'vocab_size': 1000}},
            initialization_seed=42, total_steps=1,
        ) for identifier in identifiers]
        first, _ = self.engine.export_candidate_model(runs[0])
        second, _ = self.engine.export_candidate_model(runs[1])
        self.assertNotEqual(first.model_id, second.model_id)
        self.assertEqual(first.revision_no, 1)
        self.assertEqual(second.revision_no, 1)
        repeated, _ = self.engine.export_candidate_model(runs[0])
        self.assertEqual(repeated.model_id, first.model_id)
        self.assertEqual(repeated.revision_no, 2)

    def test_legacy_uuid4_run_exports_keep_the_existing_logical_model(self):
        identifier = uuid.UUID('12345678-1234-4234-8234-123456789abc')
        existing = Model.objects.create(tenant_id=self.tenant.tenant_id, name=f'scratch_pretraining-candidate-{identifier.hex[:8]}')
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id, run_id=identifier,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING, tokenizer_version=self.tokenizer,
            hyperparameters={'architecture': {'n_layer': 1, 'n_embd': 4, 'vocab_size': 1000}},
            initialization_seed=42, total_steps=1,
        )
        candidate, _ = self.engine.export_candidate_model(run)
        self.assertEqual(candidate.model_id, existing.pk)

    def test_prd_scenario_1_scratch_model_journey(self):
        # 1. Initialize scratch run with recorded random initialization seed
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 128, "vocab_size": 1000},
                "learning_rate": 5e-4,
                "batch_size": 2,
                "max_seq_len": 64,
            },
            initialization_seed=42,
            total_steps=20,
        )

        init_info = self.engine.initialize_run(run)
        self.assertEqual(init_info["initialization_seed"], 42)
        # Starting loss ~ ln(1000) = 6.9078
        self.assertAlmostEqual(init_info["initial_loss"], math.log(1000), places=1)

        # 2. Train steps and save checkpoints
        metrics = self.engine.train_steps(run, num_steps=20, checkpoint_interval=10)
        self.assertEqual(len(metrics), 20)
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

        # Loss decayed
        self.assertLess(run.latest_loss, init_info["initial_loss"])

        # Checkpoints exist and have digests
        checkpoints = TrainingCheckpoint.objects.filter(training_run=run).order_by("step")
        self.assertEqual(checkpoints.count(), 2)  # step 10 and step 20
        self.assertTrue(all(len(c.state_digest) == 64 for c in checkpoints))

        # Output model registered
        self.assertIsNotNone(run.output_model_version)
        output_model = run.output_model_version
        self.assertEqual(output_model.state, ModelVersion.State.DRAFT)

        # 3. Export bundle and verify external loadable outside platform
        _, bundle = self.engine.export_candidate_model(run)
        verify_result = TrainingEngine.verify_external_loadable(bundle)
        self.assertTrue(verify_result["is_loadable"])
        self.assertEqual(verify_result["vocab_size"], 1000)

    def test_prd_scenario_2_fine_tuning_lora_journey(self):
        # 1. Register base model
        base_model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="base-foundation",
            intended_tasks=["chat"],
        )
        base_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=base_model,
            tokenizer=self.tokenizer,
            metadata={"vocab_size": 1000, "parameter_count": 500000},
        )

        # 2. Run LoRA adapter recipe
        lora_run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=base_version,
            tokenizer_version=self.tokenizer,
            hyperparameters={
                "lora_config": {"r": 8, "lora_alpha": 16, "target_modules": ["q_proj", "v_proj"]},
                "learning_rate": 2e-4,
                "batch_size": 4,
            },
            total_steps=10,
            initialization_seed=123,
        )

        self.engine.train_steps(lora_run, num_steps=10, checkpoint_interval=5)
        self.assertEqual(lora_run.status, TrainingRun.Status.COMPLETED)

        # Output model retains base model lineage
        self.assertIsNotNone(lora_run.output_model_version)
        output_mv = lora_run.output_model_version
        self.assertEqual(output_mv.metadata["recipe_type"], "lora_adapter")


class InterruptionRecoveryAndSweepsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="rec-test", name="Recovery Test")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="r-tok",
            vocabulary_size=500,
        )
        self.engine = TrainingEngine()

    def test_interruption_and_checkpoint_restoration(self):
        # Step 1: Run 10 steps, checkpointing at step 5
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={"architecture": {"n_layer": 2, "n_embd": 64, "vocab_size": 500}},
            total_steps=20,
            initialization_seed=999,
        )
        self.engine.train_steps(run, num_steps=10, checkpoint_interval=5)
        self.assertEqual(run.current_step, 10)

        # Step 2: Grab checkpoint at step 5
        ckpt_step_5 = TrainingCheckpoint.objects.get(training_run=run, step=5)

        # Step 3: Simulate interruption and restore from step 5
        restored_run = self.engine.restore_from_checkpoint(ckpt_step_5)
        self.assertEqual(restored_run.current_step, 5)
        self.assertEqual(restored_run.latest_loss, ckpt_step_5.metrics["loss"])

        # Step 4: Continue from step 5 to 10
        continued_metrics = self.engine.train_steps(restored_run, num_steps=5, checkpoint_interval=5)
        self.assertEqual(restored_run.current_step, 10)
        self.assertEqual(len(continued_metrics), 5)

    def test_restore_rejects_corrupted_checkpoint(self):
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            hyperparameters={"architecture": {"n_layer": 2, "n_embd": 64, "vocab_size": 500}},
            total_steps=10,
        )
        self.engine.train_steps(run, num_steps=5, checkpoint_interval=5)
        ckpt = TrainingCheckpoint.objects.get(training_run=run, step=5)

        # Corrupt digest
        ckpt.state_digest = "0" * 64
        ckpt.save()

        with self.assertRaises(ValueError) as ctx:
            self.engine.restore_from_checkpoint(ckpt)
        self.assertIn("digest mismatch", str(ctx.exception))

    def test_bounded_parameter_sweep_within_budget(self):
        sweep_res = run_bounded_parameter_sweep(
            tenant_id=str(self.tenant.tenant_id),
            recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
            tokenizer_version=self.tokenizer,
            base_hyperparameters={
                "architecture": {"n_layer": 2, "n_embd": 64, "vocab_size": 500},
            },
            search_space={
                "learning_rate": [1e-4, 5e-4],
                "batch_size": [2, 4],
            },
            budget_limit_dollars=50.0,
            steps_per_trial=5,
        )
        self.assertEqual(sweep_res["status"], "completed")
        self.assertEqual(sweep_res["total_trials"], 4)
        self.assertIn("best_trial", sweep_res)
        self.assertIsNotNone(sweep_res["best_trial"]["final_loss"])

    def test_bounded_parameter_sweep_overbudget_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            run_bounded_parameter_sweep(
                tenant_id=str(self.tenant.tenant_id),
                recipe_type=TrainingRun.RecipeType.SCRATCH_PRETRAINING,
                tokenizer_version=self.tokenizer,
                base_hyperparameters={
                    "architecture": {"n_layer": 2, "n_embd": 64, "vocab_size": 500},
                },
                search_space={
                    "learning_rate": [1e-4, 5e-4],
                    "batch_size": [2, 4],
                },
                budget_limit_dollars=0.00000000001,  # Impossibly low budget limit
                steps_per_trial=10,
            )
        self.assertIn("exceeds authorized budget limit", str(ctx.exception))
