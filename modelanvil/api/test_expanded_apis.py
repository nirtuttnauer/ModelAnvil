"""Tests for expanded REST API endpoints across Models, Training, RAG, Context Lab, and Releases."""
from __future__ import annotations

import json
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from modelanvil.identity.models import ApiKey, Membership, Role, Tenant, User, generate_api_key
from modelanvil.rag.models import (
    DocumentChunk,
    EmbeddingSpace,
    IndexVersion,
    KnowledgeBase,
    SourceDocument,
)
from modelanvil.releases.models import Release, ReleaseVersion, ServingEndpoint
from modelanvil.runners.models import (
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
    TrainingRun,
)


class ExpandedApiEndpointsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="api-test-org", name="API Test Org")
        self.user = User.objects.create_user(email="admin@api-test.org", password="testpassword123")
        Membership.objects.create(
            tenant=self.tenant,
            user=self.user,
            role=Role.ADMIN,
        )

        secret, secret_hash = generate_api_key()
        self.api_key = ApiKey.objects.create(
            tenant=self.tenant,
            name="test-key",
            secret_hash=secret_hash,
            role=Role.ADMIN,
        )

        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")

        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="api-tok",
            vocabulary_size=1000,
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="api-model",
            intended_tasks=["chat"],
        )
        self.model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="transformer",
            tokenizer=self.tokenizer,
            state=ModelVersion.State.QUALIFIED,
        )

    def test_models_and_versions_endpoints(self):
        # List models
        res = self.client.get("/api/v1/models/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        count = res.data["count"] if isinstance(res.data, dict) and "count" in res.data else len(res.data)
        self.assertGreaterEqual(count, 1)

        # List model versions
        res_v = self.client.get("/api/v1/model-versions/")
        self.assertEqual(res_v.status_code, status.HTTP_200_OK)
        count_v = res_v.data["count"] if isinstance(res_v.data, dict) and "count" in res_v.data else len(res_v.data)
        self.assertGreaterEqual(count_v, 1)

    def test_training_run_advance_and_export(self):
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
            total_steps=5,
        )
        # Advance training steps via REST API
        res = self.client.post(f"/api/v1/training-runs/{run.run_id}/train-steps/", {"steps": 5, "checkpoint_interval": 1})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "completed")

        # Export bundle via REST API
        res_export = self.client.post(f"/api/v1/training-runs/{run.run_id}/export/")
        self.assertEqual(res_export.status_code, status.HTTP_200_OK)
        self.assertTrue(res_export.data["verification"]["is_loadable"])

    def test_rag_knowledge_base_and_query(self):
        kb = KnowledgeBase.objects.create(tenant_id=self.tenant.tenant_id, name="Test KB")
        space = EmbeddingSpace.objects.create(tenant_id=self.tenant.tenant_id, name="Space", dimension=3)
        iv = IndexVersion.objects.create(tenant_id=self.tenant.tenant_id, knowledge_base=kb, embedding_space=space, revision_no=1)
        doc = SourceDocument.objects.create(tenant_id=self.tenant.tenant_id, knowledge_base=kb, title="Doc", content="Text", content_hash="h1")
        chunk = DocumentChunk.objects.create(
            tenant_id=self.tenant.tenant_id,
            document=doc,
            chunk_index=0,
            text="Antigravity high-speed AI engineering platform.",
            content_hash="c1",
            embedding=[1.0, 0.0, 0.0],
        )

        # Query endpoint
        res = self.client.post(f"/api/v1/index-versions/{iv.index_id}/query/", {
            "query": "Antigravity",
            "top_k": 3,
            "mode": "hybrid",
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["results"]), 1)
        self.assertIn("Antigravity", res.data["results"][0]["text"])

    def test_releases_sbom_and_promotion_endpoints(self):
        rel = Release.objects.create(tenant_id=self.tenant.tenant_id, name="Test Rel")
        rel_v = ReleaseVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            release=rel,
            revision_no=1,
            model_version=self.model_version,
            candidate_ref=str(self.model_version.model_version_id),
            status=ReleaseVersion.Status.QUALIFIED,
        )
        endpoint = ServingEndpoint.objects.create(
            tenant_id=self.tenant.tenant_id,
            endpoint_key="ep-test",
            name="Endpoint Test",
        )

        # SBOM endpoint
        res_sbom = self.client.get(f"/api/v1/release-versions/{rel_v.release_version_id}/sbom/")
        self.assertEqual(res_sbom.status_code, status.HTTP_200_OK)
        self.assertTrue(res_sbom.data["sbom_digest"])

        # Promote endpoint
        res_promote = self.client.post(f"/api/v1/serving-endpoints/{endpoint.endpoint_id}/promote/", {
            "release_version_id": str(rel_v.release_version_id),
        })
        self.assertEqual(res_promote.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unqualified", str(res_promote.json()))


    def test_training_registry_ids_create_a_pending_run_with_seed_zero(self):
        tokenizers = self.client.get("/api/v1/tokenizers/").data["results"]
        versions = self.client.get("/api/v1/model-versions/").data["results"]
        self.assertEqual(tokenizers[0]["id"], self.tokenizer.pk)
        self.assertEqual(versions[0]["id"], self.model_version.pk)
        response = self.client.post("/api/v1/training-runs/", {
            "execution_mode": "simulation",
            "recipe_type": "lora_adapter", "tokenizer_version": tokenizers[0]["id"],
            "base_model_version": versions[0]["id"], "initialization_seed": 0,
            "total_steps": 20,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["initialization_seed"], 0)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["total_steps"], 20)

    def test_training_refuses_foreign_tenant_registry_records(self):
        other = Tenant.objects.create(slug="other-training", name="Other")
        tokenizer = TokenizerVersion.all_objects.create(
            tenant_id=other.tenant_id, name="other-tokenizer", vocabulary_size=100)
        response = self.client.post("/api/v1/training-runs/", {
            "execution_mode": "simulation",
            "recipe_type": "scratch_pretraining", "tokenizer_version": tokenizer.pk,
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(TrainingRun.all_objects.count(), 0)

    def test_evaluation_listing_includes_recorded_metric_uncertainty(self):
        from modelanvil.runners.models import EvaluationMetric
        suite = EvaluationSuite.objects.create(tenant_id=self.tenant.tenant_id, name="Browser suite")
        version = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant.tenant_id, suite=suite)
        run = EvaluationRun.objects.create(tenant_id=self.tenant.tenant_id,
            suite_version=version, candidate_model_version=self.model_version, status="completed")
        EvaluationMetric.objects.create(tenant_id=self.tenant.tenant_id, run=run,
            key="accuracy", slice_name="all", value=0.8, sample_count=10,
            uncertainty_interval={"lower": 0.6, "upper": 0.9})
        response = self.client.get("/api/v1/evaluation-runs/")
        self.assertEqual(response.status_code, 200)
        result = response.data["results"][0]
        self.assertIn("started_at", result)
        self.assertIsNone(result["started_at"])
        self.assertEqual(result["metrics"][0]["uncertainty_interval"], {"lower": 0.6, "upper": 0.9})


    def test_context_version_and_compile_return_real_block_content_and_budget(self):
        from modelanvil.context_lab.models import ContextRecipe, ContextRecipeVersion, ContextBlockRevision
        recipe = ContextRecipe.objects.create(tenant_id=self.tenant.tenant_id, name="Browser context")
        version = ContextRecipeVersion.objects.create(tenant_id=self.tenant.tenant_id, recipe=recipe,
            model_limit_tokens=100, output_reserve_tokens=20)
        block = ContextBlockRevision.objects.create(tenant_id=self.tenant.tenant_id,
            recipe_version=version, block_key="evidence", block_type="evidence", role="user",
            content_template="Saved fact", priority=2)
        versions = self.client.get("/api/v1/context-recipe-versions/")
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(str(versions.data["results"][0]["blocks"][0]["block_revision_id"]), str(block.block_id))
        response = self.client.post(f"/api/v1/context-recipe-versions/{version.recipe_version_id}/compile/",
            {"variables": {"evidence": "Overridden fact"}}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Overridden fact", response.data["serialized_prompt"])
        self.assertEqual(response.data["included_blocks"], ["evidence"])
        self.assertGreater(response.data["token_count"], 0)
        self.assertFalse(response.data["budget_exhausted"])
        response = self.client.post(f"/api/v1/context-recipe-versions/{version.recipe_version_id}/compile/",
            {"variables": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_evaluation_creation_and_cases_use_tenant_scoped_relations(self):
        from modelanvil.runners.models import EvaluationCaseResult
        suite = EvaluationSuite.objects.create(tenant_id=self.tenant.tenant_id, name="browser-suite")
        version = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant.tenant_id, suite=suite, revision_no=1, cases=[{"id": "one"}])
        listed = self.client.get('/api/v1/evaluation-suite-versions/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data['results'][0]['id'], version.id)
        response = self.client.post('/api/v1/evaluation-runs/', {'suite_version': version.id, 'candidate_model_version': self.model_version.id}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        run = EvaluationRun.all_objects.get(run_id=response.data['run_id'])
        self.assertEqual(run.status, 'pending')
        EvaluationCaseResult.objects.create(tenant_id=self.tenant.tenant_id, run=run, case_id='one', score=0, passed=False, failure_reason='wrong answer')
        cases = self.client.get(f'/api/v1/evaluation-runs/{run.run_id}/cases/').data['results']
        self.assertEqual(cases[0]['score'], 0)
        self.assertEqual(cases[0]['failure_reason'], 'wrong answer')
        other = Tenant.objects.create(slug='eval-other', name='Other')
        foreign_suite = EvaluationSuite.objects.create(tenant_id=other.tenant_id, name='foreign')
        foreign_version = EvaluationSuiteVersion.objects.create(tenant_id=other.tenant_id, suite=foreign_suite, revision_no=1)
        response = self.client.post('/api/v1/evaluation-runs/', {'suite_version': foreign_version.id, 'candidate_model_version': self.model_version.id}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_alignment_creation_requires_pinned_inputs_and_separate_validation(self):
        payload = {'algorithm': 'dpo', 'policy_model_version': self.model_version.id, 'reference_model_version': self.model_version.id, 'dataset_manifest_digest': 'a' * 64, 'held_out_validation_digest': 'b' * 64, 'total_steps': 10, 'hyperparameters': {'beta': 0.1}}
        response = self.client.post('/api/v1/alignment-runs/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'pending')
        self.assertEqual(response.data['hyperparameters'], {'beta': 0.1})
        for changes in ({'reference_model_version': None}, {'held_out_validation_digest': 'a' * 64}, {'dataset_manifest_digest': 'invalid'}, {'total_steps': 0}, {'hyperparameters': []}, {'algorithm': 'ppo_rlhf', 'reward_model_version': None}, {'algorithm': 'verifier_rl', 'verifier_spec': {}}):
            response = self.client.post('/api/v1/alignment-runs/', {**payload, **changes}, format='json')
            self.assertEqual(response.status_code, 400, response.content.decode())
        other = Tenant.objects.create(slug='alignment-other', name='Other')
        tokenizer = TokenizerVersion.objects.create(tenant_id=other.tenant_id, name='foreign')
        model = Model.objects.create(tenant_id=other.tenant_id, name='foreign')
        version = ModelVersion.objects.create(tenant_id=other.tenant_id, model=model, tokenizer=tokenizer, revision_no=1)
        response = self.client.post('/api/v1/alignment-runs/', {**payload, 'policy_model_version': version.id}, format='json')
        self.assertEqual(response.status_code, 400)
