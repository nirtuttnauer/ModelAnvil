"""Integration tests for persistent labeling, immutable closure, and tenant boundaries."""
import hashlib
import json
from django.test import TestCase
from rest_framework.test import APIClient
from modelanvil.annotation.models import AnnotationRecord, AnnotationTask, LabelingCampaign
from modelanvil.identity.models import ApiKey, Project, Role, Team, Tenant, generate_api_key
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion
from modelanvil.jobs.models import Worker, WorkerPool


class LabelingApiTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="labels-test", name="Labels test")
        self.other = Tenant.objects.create(slug="labels-other", name="Other")
        self.client = self.auth_client(self.tenant)
        self.foreign = self.auth_client(self.other)

    def auth_client(self, tenant, role=Role.ADMIN):
        secret, hashed = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name="test", role=role, secret_hash=hashed)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
        return client

    def campaign(self, **changes):
        response = self.client.post("/api/v1/labeling-campaigns/", {
            "name": "Sentiment", "kind": "classification", "classes": ["positive", "negative"],
            "guidelines": "Review source text", "audit_sample_refs": ["audit-1"], **changes,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def batch(self, campaign, samples):
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {"samples": samples}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        batch = response.data
        tasks = self.client.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/').data["results"]
        return batch, tasks

    def review(self, task, label="positive", decision="corrected", revision=1):
        return self.client.post(f'/api/v1/annotation-tasks/{task["task_id"]}/review/', {
            "decision": decision, "human_label": {"label": label}, "expected_revision": revision,
        }, format="json")

    def close(self, batch):
        return self.client.post(f'/api/v1/labeling-batches/{batch["batch_id"]}/close/', {}, format="json")

    def test_manual_journey_cumulative_snapshot_and_immutable_history(self):
        campaign = self.campaign(max_cycles=2)
        batch, tasks = self.batch(campaign, [{"id": "one", "text": "Excellent"}, {"id": "two", "text": "Poor"}, {"id": "three", "text": "Unreadable"}])
        self.assertEqual(self.close(batch).status_code, 409)
        for task in tasks:
            self.assertEqual(self.review(task, decision="skipped" if task["sample_ref"] == "three" else "corrected").status_code, 201)
        closed = self.close(batch)
        self.assertEqual(closed.status_code, 200, closed.data)
        self.assertEqual(closed.data["item_count"], 2)
        self.assertEqual(self.close(batch).data["snapshot_id"], closed.data["snapshot_id"])
        self.assertEqual(self.review(tasks[0], revision=2).status_code, 409)
        exported = self.client.get(f'/api/v1/annotation-snapshots/{closed.data["snapshot_id"]}/export/').data
        payload = json.dumps(sorted(exported["items"], key=lambda x: str(x["sample_ref"])), sort_keys=True)
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), exported["manifest_digest"])
        self.assertEqual(self.client.delete(f'/api/v1/annotation-snapshots/{closed.data["snapshot_id"]}/').status_code, 405)
        second, tasks2 = self.batch(campaign, [{"id": "four", "text": "Another input"}])
        self.assertEqual(self.review(tasks2[0]).status_code, 201)
        self.assertEqual(self.close(second).data["item_count"], 3)
        campaign = self.client.get(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/').data
        self.assertEqual(campaign["status"], "completed")
        self.assertEqual(campaign["current_cycle"], 2)
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {"samples": [{"id": "five", "text": "x"}]}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_schema_validation_and_stale_review_never_overwrite(self):
        campaign = self.campaign()
        _, tasks = self.batch(campaign, [{"id": "one", "text": "Great"}])
        task = tasks[0]
        response = self.review(task, revision=2)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")
        self.assertIn("Another reviewer", response.json()["error"]["message"])
        self.assertEqual(self.review(task, label="not-a-class").status_code, 400)
        self.assertEqual(self.review(task, decision="accepted_without_edit").status_code, 400)
        self.assertEqual(self.review(task).status_code, 201)
        self.assertEqual(self.review(task, label="negative").status_code, 409)
        self.assertEqual(self.review(task, label="negative", revision=2).status_code, 201)
        history = self.client.get(f'/api/v1/annotation-tasks/{task["task_id"]}/history/').data["results"]
        self.assertEqual(len(history), 2)
        self.assertEqual({r["human_label"]["label"] for r in history}, {"positive", "negative"})
        self.assertTrue(all(r["reviewer_id"].startswith("api_key:") for r in history))

    def test_protected_duplicate_inputs_and_parallel_batches_are_rejected_atomically(self):
        campaign = self.campaign()
        path = f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/'
        for samples in ([{"id": "audit-1", "text": "protected"}], [{"id": "x", "text": "test", "split": "test"}], [{"id": "x", "text": "same"}, {"id": "y", "text": "same"}], [{"id": "x", "text": "first"}, {"id": "x", "text": "different"}]):
            self.assertEqual(self.client.post(path, {"samples": samples}, format="json").status_code, 400)
        self.assertEqual(AnnotationTask.all_objects.count(), 0)
        batch, tasks = self.batch(campaign, [{"id": "one", "text": "unique"}])
        self.assertEqual(self.client.post(path, {"samples": [{"id": "two", "text": "second"}]}, format="json").status_code, 409)
        self.review(tasks[0]); self.close(batch)
        self.assertEqual(self.client.post(path, {"samples": [{"id": "different-id", "text": "unique"}]}, format="json").status_code, 400)

    def test_paused_campaign_blocks_review_and_batch_closure(self):
        campaign = self.campaign()
        batch, tasks = self.batch(campaign, [{"id": "one", "text": "x"}])
        path = f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/lifecycle/'
        self.assertEqual(self.client.post(path, {"transition": "pause"}, format="json").status_code, 200)
        self.assertEqual(self.review(tasks[0]).status_code, 409)
        self.assertEqual(self.close(batch).status_code, 409)
        self.assertEqual(self.client.post(path, {"transition": "resume"}, format="json").status_code, 200)
        self.assertEqual(self.review(tasks[0]).status_code, 201)

    def test_cross_tenant_and_viewer_permissions(self):
        campaign = self.campaign()
        batch, tasks = self.batch(campaign, [{"id": "one", "text": "x"}])
        self.assertEqual(self.foreign.get(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/').status_code, 404)
        self.assertEqual(self.foreign.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/').status_code, 404)
        self.assertEqual(self.foreign.post(f'/api/v1/annotation-tasks/{tasks[0]["task_id"]}/review/', {}, format="json").status_code, 404)
        viewer = self.auth_client(self.tenant, Role.VIEWER)
        self.assertEqual(viewer.get(f'/api/v1/labeling-batches/{batch["batch_id"]}/tasks/').status_code, 200)
        self.assertEqual(viewer.post(f'/api/v1/annotation-tasks/{tasks[0]["task_id"]}/review/', {}, format="json").status_code, 403)
        self.assertEqual(viewer.post('/api/v1/labeling-campaigns/', {}, format="json").status_code, 403)

    def test_imported_draft_requires_pinned_origin_and_preserves_prediction(self):
        tok = TokenizerVersion.objects.create(tenant_id=self.tenant.tenant_id, name="tok")
        model = Model.objects.create(tenant_id=self.tenant.tenant_id, name="model")
        version = ModelVersion.objects.create(tenant_id=self.tenant.tenant_id, model=model, tokenizer=tok, revision_no=1)
        campaign = self.campaign(seed_mode="existing_model", drafting_model_id=str(version.model_version_id))
        prediction = {"model_version_id": str(version.model_version_id), "predicted_label": "positive", "confidence": .8}
        batch, tasks = self.batch(campaign, [{"id": "one", "text": "Excellent", "draft_prediction": prediction}])
        self.assertEqual(batch["drafting_model_id"], str(version.model_version_id))
        self.assertEqual(tasks[0]["status"], "drafted")
        self.assertEqual(self.review(tasks[0], decision="accepted_without_edit").status_code, 201)
        self.assertEqual(self.review(tasks[0], label="negative", revision=2).status_code, 201)
        records = AnnotationRecord.all_objects.all()
        self.assertTrue(all(r.original_prediction == prediction for r in records))

    def test_seed_model_must_be_accessible_in_the_active_project(self):
        team = Team.objects.create(tenant_id=self.tenant.pk, name="Review", slug="review")
        first = Project.objects.create(tenant_id=self.tenant.pk, team=team, name="First", slug="first")
        second = Project.objects.create(tenant_id=self.tenant.pk, team=team, name="Second", slug="second")
        tok = TokenizerVersion.objects.create(tenant_id=self.tenant.pk, name="scoped-tok")
        model = Model.objects.create(tenant_id=self.tenant.pk, project=first, name="scoped-model")
        version = ModelVersion.objects.create(tenant_id=self.tenant.pk, model=model, tokenizer=tok, revision_no=1)
        response = self.client.post('/api/v1/labeling-campaigns/', {
            "name": "Inaccessible seed", "kind": "classification", "classes": ["yes"],
            "seed_mode": "existing_model", "drafting_model_id": str(version.model_version_id),
        }, format="json", HTTP_X_PROJECT_ID=str(second.pk))
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(LabelingCampaign.all_objects.filter(name="Inaccessible seed").exists())

    def test_foreign_seed_model_and_bad_prediction_are_rejected(self):
        model = Model.objects.create(tenant_id=self.other.tenant_id, name="foreign")
        tok = TokenizerVersion.objects.create(tenant_id=self.other.tenant_id, name="foreign-tok")
        version = ModelVersion.objects.create(tenant_id=self.other.tenant_id, model=model, tokenizer=tok, revision_no=1)
        response = self.client.post('/api/v1/labeling-campaigns/', {"name": "Foreign", "kind": "classification", "classes": ["yes"], "seed_mode": "existing_model", "drafting_model_id": str(version.model_version_id)}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(LabelingCampaign.all_objects.count(), 0)
        campaign = self.campaign()
        response = self.client.post(f'/api/v1/labeling-campaigns/{campaign["campaign_id"]}/batches/', {"samples": [{"id": "one", "text": "x", "draft_prediction": {"predicted_label": "positive"}}]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_rejected_samples_are_excluded_from_snapshot(self):
        campaign = self.campaign(kind="preference_ranking", classes=[])
        batch, tasks = self.batch(campaign, [{"id": "one", "prompt": "question", "candidate_a": "a", "candidate_b": "b"}, {"id": "two", "text": "bad"}])
        for task in tasks:
            self.assertEqual(self.review(task, label="tie", decision="corrected" if task["sample_ref"] == "one" else "rejected").status_code, 201)
        self.assertEqual(self.close(batch).data["item_count"], 1)

    def test_worker_inventory_is_read_only_and_tenant_scoped(self):
        pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        Worker.objects.create(tenant_id=self.tenant.tenant_id, name="worker", pool=pool)
        self.assertEqual(len(self.client.get('/api/v1/worker-pools/').data['results']), 1)
        inventory = self.client.get('/api/v1/worker-inventory/').data['results']
        self.assertEqual(inventory[0]['pool_name'], 'cpu')
        self.assertNotIn('worker_token', inventory[0])
        self.assertEqual(self.foreign.get('/api/v1/worker-inventory/').data['results'], [])
        self.assertEqual(self.client.post('/api/v1/worker-pools/', {}, format='json').status_code, 405)
