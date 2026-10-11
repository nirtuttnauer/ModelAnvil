"""Legacy synthetic training fixture regression tests. CPU qualification lives in test_cpu_runtime."""
from __future__ import annotations

import base64
import json
import uuid
from decimal import Decimal
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation
from modelanvil.core.tenancy import set_active_tenant
from modelanvil.identity.models import ApiKey, Membership, Role, Tenant, User, generate_api_key
from modelanvil.jobs.executor import ExecutionContext
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, claim_job
from modelanvil.runners.models import (
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingCheckpoint,
    TrainingRun,
)
from modelanvil.runners.training.engine import (
    TrainingEngine,
    pack_safetensors,
    unpack_safetensors,
)
from modelanvil.runners.training.executor import training_worker_executor


class SyntheticTrainingFixtureTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="ft-journey", name="Fine-Tuning Journey Org")
        set_active_tenant(self.tenant.tenant_id)

        self.user = User.objects.create_user(email="admin@ft-journey.org", password="testpassword123")
        Membership.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=Role.ADMIN,
        )

        secret, secret_hash = generate_api_key()
        self.api_key = ApiKey.objects.create(
            tenant=self.tenant,
            name="Test Runner Key",
            secret_hash=secret_hash,
            role=Role.ADMIN,
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")

        # 2. Tokenizer Version
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="synthetic-tok",
            vocabulary_size=1000,
            special_tokens={"bos_token": "<|begin_of_text|>", "eos_token": "<|end_of_text|>"},
            chat_template="{% for m in messages %}{{ m.role }}: {{ m.content }}\n{% endfor %}",
        )

        # 3. Base Model & Qualified Version
        self.base_model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="Synthetic-base",
            intended_tasks=["text_generation", "reasoning"],
        )
        self.base_model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.base_model,
            revision_no=1,
            tokenizer=self.tokenizer,
            architecture_ref="modelanvil/llama-3-8b",
            state="qualified",
            metadata={"vocab_size": 1000, "parameter_count": 8030000000},
        )

        # 4. Prepared Immutable Dataset
        self.dataset = Dataset.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="alpaca-cleaned-instruct",
        )
        self.manifest_artifact = Artifact.objects.create(
            tenant_id=self.tenant.tenant_id,
            storage_location_id="default",
            object_key="datasets/alpaca/manifest.json",
            sha256="a" * 64,
            byte_size=1024,
            media_type="application/json",
            state=Artifact.State.COMMITTED,
        )
        self.dataset_revision = DatasetRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            dataset=self.dataset,
            revision_no=1,
            manifest_digest="a" * 64,
            manifest_artifact=self.manifest_artifact,
            row_count=50000,
            state=DatasetRevision.State.PUBLISHED,
        )

        # 5. Worker Pool & Registered Worker
        self.pool = WorkerPool.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="fixture-pool",
            queue_name="fixture-jobs",
            status="active",
        )
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="synthetic-worker",
            capabilities={"accelerator": "h100", "slots": 4},
            slots=4,
            status=Worker.Status.AVAILABLE,
        )

        # 6. Budget Policy
        self.budget_policy = BudgetPolicy.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="monthly-gpu-spend",
            unit="gpu_seconds",
            limit_amount=Decimal("10000.00"),
            enabled=True,
        )

    def tearDown(self):
        set_active_tenant(None)

    def test_safetensors_pack_unpack_and_tensor_checksums(self):
        """Verify Safetensors binary serialization, little-endian floats, and SHA-256 checksums."""
        tensors = {
            "transformer.wte.weight": ([4, 2], [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]),
            "lm_head.weight": ([4, 2], [1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]),
        }
        safetensors_bytes, manifest = pack_safetensors(tensors)
        self.assertGreater(len(safetensors_bytes), 8)
        self.assertEqual(manifest["format"], "safetensors")
        self.assertIn("weights_sha256", manifest)
        self.assertEqual(len(manifest["weights_sha256"]), 64)

        # Unpack and verify float values match
        unpacked = unpack_safetensors(safetensors_bytes)
        self.assertEqual(set(unpacked.keys()), {"transformer.wte.weight", "lm_head.weight"})
        shape, values = unpacked["transformer.wte.weight"]
        self.assertEqual(shape, [4, 2])
        self.assertAlmostEqual(values[0], 0.1, places=5)
        self.assertAlmostEqual(values[7], 0.8, places=5)

    def test_configuration_requires_published_dataset_and_valid_manifest(self):
        """Unsupported or draft datasets are rejected before dispatch."""
        # 1. Draft revision fails
        draft_revision = DatasetRevision.objects.create(
            tenant_id=self.tenant.tenant_id,
            dataset=self.dataset,
            revision_no=2,
            manifest_digest="b" * 64,
            state=DatasetRevision.State.DRAFT,
        )
        res = self.client.post("/api/v1/training-runs/", {
            "execution_mode": "simulation",
            "recipe_type": "lora_adapter",
            "base_model_version": self.base_model_version.id,
            "tokenizer_version": self.tokenizer.id,
            "dataset_revision": draft_revision.id,
            "pool": self.pool.id,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        content_1 = res.content.decode()
        self.assertIn("published", content_1)

        # 2. Incompatible tokenizer vocabulary fails
        bad_tok = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="mismatched-tok",
            vocabulary_size=50000,  # model metadata specifies 1000
        )
        res = self.client.post("/api/v1/training-runs/", {
            "execution_mode": "simulation",
            "recipe_type": "lora_adapter",
            "base_model_version": self.base_model_version.id,
            "tokenizer_version": bad_tok.id,
            "dataset_revision": self.dataset_revision.id,
            "pool": self.pool.id,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        content_2 = res.content.decode()
        self.assertIn("Vocabulary size mismatch", content_2)

    def test_simulation_never_allocates_worker_or_budget(self):
        response = self.client.post('/api/v1/training-runs/', {
            'execution_mode': 'simulation', 'recipe_type': 'lora_adapter',
            'base_model_version': self.base_model_version.pk, 'tokenizer_version': self.tokenizer.pk,
            'pool': self.pool.pk, 'budget_policy_id': str(self.budget_policy.policy_id),
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Job.objects.count(), 0)
        self.assertEqual(BudgetReservation.objects.count(), 0)

    def test_synthetic_worker_fixture_loss_and_checkpoint_digests(self):
        """Worker executes claimed job, updates weights, and saves checkpoints with valid SHA-256 digests."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=self.base_model_version,
            tokenizer_version=self.tokenizer,
            dataset_revision=self.dataset_revision,
            dataset_manifest_digest=self.dataset_revision.manifest_digest,
            pool=self.pool,
            hyperparameters={"checkpoint_interval": 5, "learning_rate": 0.08},
            initialization_seed=101,
            total_steps=10,
        )
        job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="test-training-job",
            payload={"type": "training", "run_id": str(run.run_id)},
        )
        run.job = job
        run.save(update_fields=["job"])

        # Claim job with registered worker
        descriptor = claim_job(self.worker)
        self.assertIsNotNone(descriptor)
        self.assertEqual(descriptor["job_id"], str(job.job_id))

        attempt = JobAttempt.objects.get(attempt_id=descriptor["attempt_id"])
        context = ExecutionContext(attempt, descriptor["fencing_token"])

        # Execute training through real worker executor
        training_worker_executor(descriptor, context)

        # Reload run
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.Status.COMPLETED)
        self.assertEqual(run.current_step, 10)
        self.assertIsNotNone(run.latest_loss)

        # Verify loss genuinely decreased
        first_step_loss = run.metrics_log[0]["loss"]
        final_step_loss = run.metrics_log[-1]["loss"]
        self.assertLess(final_step_loss, first_step_loss)

        # Verify checkpoints created at steps 5 and 10 with SHA-256 digests
        checkpoints = list(TrainingCheckpoint.objects.filter(training_run=run).order_by("step"))
        self.assertEqual(len(checkpoints), 2)
        for ckpt in checkpoints:
            self.assertTrue(ckpt.is_valid)
            self.assertEqual(len(ckpt.state_digest), 64)
            wm = ckpt.weights_manifest
            self.assertEqual(wm["format"], "safetensors")
            self.assertIn("weights_sha256", wm)
            self.assertEqual(len(wm["weights_sha256"]), 64)
            self.assertIn("transformer.layers.0.lora_A.weight", wm["tensors"])

        # Output model version registered and ready
        self.assertIsNotNone(run.output_model_version)
        self.assertEqual(run.output_model_version.state, ModelVersion.State.DRAFT)

    def test_checkpoint_restoration_and_corruption_rejection(self):
        """Restoring from valid checkpoint restores exact weights; corrupted digest is rejected."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=self.base_model_version,
            tokenizer_version=self.tokenizer,
            hyperparameters={"checkpoint_interval": 5, "learning_rate": 0.05},
            initialization_seed=303,
            total_steps=15,
        )
        engine = TrainingEngine()
        engine.train_steps(run, num_steps=5, checkpoint_interval=5)
        self.assertEqual(run.current_step, 5)

        ckpt_5 = TrainingCheckpoint.objects.get(training_run=run, step=5)

        # Restore from step 5
        restored = engine.restore_from_checkpoint(ckpt_5)
        self.assertEqual(restored.current_step, 5)

        # Continue from step 5 to 10
        engine.train_steps(restored, num_steps=5, checkpoint_interval=5)
        self.assertEqual(restored.current_step, 10)

        # Corrupt digest must be rejected
        ckpt_10 = TrainingCheckpoint.objects.get(training_run=run, step=10)
        ckpt_10.state_digest = "e" * 64
        ckpt_10.save()
        with self.assertRaises(ValueError) as ctx:
            engine.restore_from_checkpoint(ckpt_10)
        self.assertIn("digest mismatch", str(ctx.exception))

    def test_cancellation_fences_commits_and_releases_budget(self):
        """Cancelling an active run halts execution, sets status CANCELLED, and releases reservation."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=self.base_model_version,
            tokenizer_version=self.tokenizer,
            pool=self.pool,
            total_steps=50,
        )
        reservation = BudgetReservation.reserve(
            tenant_id=self.tenant.tenant_id,
            policy=self.budget_policy,
            job_id=run.run_id,
            estimated_amount=Decimal("150.00"),
        )
        run.resource_reservation_id = reservation.reservation_id
        job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="cancellable-job",
            payload={"type": "training", "run_id": str(run.run_id)},
        )
        run.job = job
        run.save()

        # Cancel through API
        cancel_res = self.client.post(f"/api/v1/training-runs/{run.run_id}/cancel/")
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.json()["status"], "cancelled")

        # Job marked CANCELLED
        job.refresh_from_db()
        self.assertEqual(job.desired_action, Job.DesiredAction.CANCEL)

        # Reservation released
        reservation.refresh_from_db()
        self.assertEqual(reservation.state, BudgetReservation.State.RELEASED)

    def test_synthetic_candidate_local_numerical_inference(self):
        """Synthetic candidate local smoke check emits placeholder IDs."""
        run = TrainingRun.objects.create(
            tenant_id=self.tenant.tenant_id,
            recipe_type=TrainingRun.RecipeType.LORA_ADAPTER,
            base_model_version=self.base_model_version,
            tokenizer_version=self.tokenizer,
            initialization_seed=404,
            total_steps=10,
        )
        engine = TrainingEngine()
        engine.train_steps(run, num_steps=10, checkpoint_interval=5)

        mv, bundle = engine.export_candidate_model(run)

        # Verify external loading
        verify_result = TrainingEngine.verify_external_loadable(bundle)
        self.assertTrue(verify_result["is_loadable"])
        self.assertIn("weights_sha256", verify_result)

        # Execute candidate model text generation
        completion = TrainingEngine.generate_candidate_completion(
            bundle, prompt="ModelAnvil fine-tuning experiment", max_new_tokens=5
        )
        self.assertTrue(completion["is_verified"])
        self.assertEqual(len(completion["generated_tokens"]), 5)
        self.assertIn("tok_", completion["completion"])

        # Test inference via API endpoint
        infer_res = self.client.post(f"/api/v1/training-runs/{run.run_id}/infer/", {
            "prompt": "Test generation prompt",
            "max_tokens": 4,
        }, format="json")
        self.assertEqual(infer_res.status_code, status.HTTP_200_OK)
        infer_json = infer_res.json()
        self.assertTrue(infer_json["verification"]["is_loadable"])
        self.assertTrue(infer_json["inference"]["is_verified"])
        self.assertEqual(len(infer_json["inference"]["generated_tokens"]), 4)
