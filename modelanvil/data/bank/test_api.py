"""API tests for Dataset Bank endpoints (WP-06 / TASK-9 acquisition surface).

Upstream bytes are a local fixture served through an injected transport; no
test in this module reaches GitHub.
"""
from __future__ import annotations

import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from modelanvil.budgets.models import BudgetPolicy
from modelanvil.data.bank.acquisition import bank_acquisition_executor
from modelanvil.data.bank.test_acquisition import FakeUpstream
from modelanvil.identity.models import ApiKey, Project, Team, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Worker, WorkerPool, claim_job


def _api_key(tenant: Tenant, role: str = "owner") -> dict[str, str]:
    secret, digest = generate_api_key()
    ApiKey.objects.create(
        tenant=tenant, name=f"test-{role}", role=role, secret_hash=digest,
    )
    return {"HTTP_AUTHORIZATION": f"Bearer {secret}"}


@override_settings(ALLOWED_HOSTS=["testserver"])
class DatasetBankAPITests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="test-org", name="Test Org")
        self.auth_headers = _api_key(self.tenant, "owner")

    def test_list_sources(self):
        response = self.client.get("/api/v1/dataset-bank/sources/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("sources", data)
        self.assertGreater(data["count"], 0)
        self.assertEqual(data["qualified_count"], 11)

    def test_squad_requires_boolean_share_alike_opt_in(self):
        path = "/api/v1/dataset-bank/sources/text-squad/preflight/"
        for value in (False, "true", "false", 1):
            response = self.client.post(path, {"project_policy": {"allow_share_alike": value}},
                format="json", **self.auth_headers)
            self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(path, {"project_policy": {"allow_share_alike": True}},
            format="json", **self.auth_headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["access"]["share_alike_opt_in"])

    def test_http_subset_upstream_status_requires_requalification(self):
        with patch("modelanvil.data.bank.views.upstream_head_revision") as lookup:
            response = self.client.get("/api/v1/dataset-bank/sources/numeric-iris/upstream/", **self.auth_headers)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(response.json()["upstream_head_revision"])
        self.assertIsNone(response.json()["moved"])
        self.assertFalse(response.json()["automatic_update_check_supported"])
        lookup.assert_not_called()

    def test_list_sources_marks_unqualified_sources_unavailable(self):
        response = self.client.get("/api/v1/dataset-bank/sources/?q=tabler", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        source = response.json()["sources"][0]
        self.assertEqual(source["id"], "svg-tabler")
        self.assertTrue(source["download_enabled"])
        self.assertFalse(source["acquisition_available"])
        self.assertEqual(source["acquisition_status"], "unqualified")
        self.assertIn("No acquisition connector", source["acquisition_blocked_reason"])

    def test_search_sources_filter_by_query(self):
        response = self.client.get("/api/v1/dataset-bank/sources/?q=lucide", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sources = response.json()["sources"]
        self.assertTrue(any(s["id"] == "svg-lucide" for s in sources))

    def test_retrieve_source_card(self):
        response = self.client.get("/api/v1/dataset-bank/sources/svg-lucide/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        card = response.json()
        self.assertEqual(card["id"], "svg-lucide")
        self.assertEqual(card["license"], "ISC AND MIT")
        self.assertTrue(card["download_enabled"])
        self.assertIn("obligations", card)
        self.assertEqual(card["acquisition"]["status"], "qualified")
        self.assertEqual(len(card["acquisition"]["pinned_revision"]), 40)
        self.assertTrue(card["acquisition"]["verified_record_digests"])
        self.assertTrue(card["acquisition_available"])

    def test_retrieve_unqualified_source_card_publishes_its_blocked_reason(self):
        response = self.client.get("/api/v1/dataset-bank/sources/svg-feather/", **self.auth_headers)
        card = response.json()
        self.assertEqual(card["acquisition"]["status"], "unqualified")
        self.assertTrue(card["acquisition"]["blocked_reason"])
        self.assertFalse(card["acquisition_available"])

    def test_preview_of_an_unqualified_source_is_refused(self):
        response = self.client.get(
            "/api/v1/dataset-bank/sources/svg-feather/preview/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("not qualified for acquisition", response.json()["detail"])

    def test_preview_discloses_revision_access_scope_and_destination(self):
        with patch("modelanvil.data.bank.acquisition.https_transport", FakeUpstream()):
            response = self.client.get(
                "/api/v1/dataset-bank/sources/svg-lucide/preview/?limit=3", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["samples"]), 3)
        self.assertTrue(data["samples_are_real_upstream_records"])
        for sample in data["samples"]:
            self.assertTrue(sample["digest_verified"])
            self.assertTrue(sample["upstream_path"].startswith("icons/"))
            self.assertIn("<svg", sample["svg_raw"])
        disclosure = data["launch_disclosure"]
        self.assertEqual(len(disclosure["source_revision"]), 40)
        self.assertEqual(disclosure["access"]["gated"], False)
        self.assertEqual(disclosure["scope"]["record_limit"], 120)
        self.assertEqual(disclosure["scope"]["include_patterns"], ["icons/*.svg"])
        self.assertEqual(disclosure["destination"]["tenant_id"], str(self.tenant.pk))
        self.assertEqual(disclosure["destination"]["artifact_object_key_prefix"], "bank/svg-lucide/")
        self.assertIn("MIT", disclosure["obligations"]["evidence_urls"][0] + disclosure["license"])

    def test_preflight_source_approved(self):
        response = self.client.post(
            "/api/v1/dataset-bank/sources/svg-lucide/preflight/",
            data={"project_policy": {"max_storage_quota_bytes": 1000000000}},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["status"], "approved")
        self.assertEqual(data["source_id"], "svg-lucide")

    def test_preflight_source_rejects_share_alike_without_opt_in(self):
        response = self.client.post(
            "/api/v1/dataset-bank/sources/svg-openmoji/preflight/",
            data={"project_policy": {"allow_share_alike": False}},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("share-alike", response.json()["detail"])

    def test_preflight_refuses_an_unqualified_source(self):
        response = self.client.post(
            "/api/v1/dataset-bank/sources/svg-openmoji/preflight/",
            data={"project_policy": {"allow_share_alike": True}},
            format="json",
            **self.auth_headers,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not qualified for acquisition", response.json()["detail"])

    def test_list_presets(self):
        response = self.client.get("/api/v1/dataset-bank/presets/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("presets", data)
        preset = next(p for p in data["presets"] if p["id"] == "svg-starter-permissive")
        self.assertEqual(preset["qualified_source_ids"], ["svg-lucide"])

    def test_list_held_candidates(self):
        response = self.client.get("/api/v1/dataset-bank/held/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("held_candidates", data)
        self.assertTrue(any(h["name"] == "SVG Stack" for h in data["held_candidates"]))
        self.assertTrue(all(h["download_enabled"] is False for h in data["held_candidates"]))

    def test_upstream_revision_check_reports_a_moved_head(self):
        upstream = FakeUpstream(record_count=2)
        with patch("modelanvil.data.bank.acquisition.https_transport", upstream):
            response = self.client.get(
                "/api/v1/dataset-bank/sources/svg-lucide/upstream/", **self.auth_headers)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["moved"])
        self.assertNotEqual(data["upstream_head_revision"], data["pinned_revision"])
        self.assertEqual(data["acquirable_revisions"], [data["pinned_revision"]])
        self.assertEqual(data["acquirable_revisions"], [data["pinned_revision"]])

    def test_launch_is_refused_without_worker_capacity(self):
        with patch("modelanvil.data.bank.acquisition.https_transport", FakeUpstream()):
            response = self.client.post(
                "/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                data={"record_limit": 4}, format="json", **self.auth_headers,
            )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("acquisition worker", response.json()["detail"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class DatasetBankAcquisitionJourneyTests(APITestCase):
    """Launch from the API, execute on a registered worker, read the published version."""

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={
            **settings.MODELANVIL, "artifact_backend": "filesystem", "artifact_root": root.name,
        })
        override.enable()
        self.addCleanup(override.disable)

        self.tenant = Tenant.objects.create(slug="acquisition-org", name="Acquisition Org")
        self.other = Tenant.objects.create(slug="acquisition-other", name="Other Org")
        self.auth_headers = _api_key(self.tenant, "owner")
        self.other_headers = _api_key(self.other, "owner")
        self.pool = WorkerPool.objects.create(
            tenant_id=self.tenant.pk, name="dataset-acquisition", queue_name="bank")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.pk, pool=self.pool, name="bank-worker",
            slots=1, capabilities={"dataset_acquisition": True},
        )
        self.policy = BudgetPolicy.objects.create(
            tenant_id=self.tenant.pk, name="bank-records", period="monthly",
            unit="bank_acquisition_records", limit_amount=Decimal("1000"),
        )
        self.upstream = FakeUpstream(record_count=12)

    def launch(self, record_limit=6):
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            return self.client.post(
                "/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                data={
                    "record_limit": record_limit,
                    "budget_policy_id": str(self.policy.policy_id),
                    "estimated_amount": str(record_limit),
                    "split_seed": "bank-seed",
                },
                format="json", **self.auth_headers,
            )

    def run_worker(self):
        descriptor = claim_job(self.worker)
        self.assertIsNotNone(descriptor)
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            return execute_claim(self.worker, descriptor, bank_acquisition_executor)

    def state(self, snapshot_id, **headers):
        return self.client.get(
            f"/api/v1/dataset-bank/acquisitions/{snapshot_id}/", **headers or self.auth_headers)

    def test_launch_execute_publish_and_cancel_lifecycle(self):
        response = self.launch()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        launched = response.json()
        self.assertEqual(launched["state"], "ingesting")
        self.assertEqual(launched["planned_records"], 6)
        self.assertEqual(launched["job"]["status"], "queued")
        self.assertEqual(launched["budget_reservation"]["state"], "reserved")

        partial = self.state(launched["snapshot_id"])
        self.assertEqual(partial.status_code, status.HTTP_200_OK)
        self.assertEqual(partial.json()["verified_records"], 0)

        self.assertEqual(self.run_worker()["status"], "succeeded")

        published = self.state(launched["snapshot_id"]).json()
        self.assertEqual(published["state"], "ready")
        self.assertEqual(published["verified_records"], 6)
        self.assertEqual(published["row_count"], 6)
        self.assertEqual(published["revision_no"], 1)
        self.assertTrue(published["revision_id"])
        self.assertEqual(published["budget_reservation"]["state"], "settled")
        self.assertIn("dropped", published["rejection_report"])

        revisions = self.client.get("/api/v1/dataset-revisions/", **self.auth_headers).json()
        revision = next(item for item in revisions["results"] if item["revision_id"] == published["revision_id"])
        self.assertEqual(revision["state"], "published")
        self.assertEqual(revision["row_count"], 6)
        self.assertEqual(revision["manifest_digest"], published["rejection_report"] is not None and revision["manifest_digest"])
        datasets = self.client.get("/api/v1/datasets/", **self.auth_headers).json()["results"]
        dataset = next(item for item in datasets if item["dataset_id"] == published["dataset_id"])
        self.assertEqual(dataset["metadata"]["latest_attribution"]["source_revision"], published["source_revision"])
        self.assertTrue(dataset["metadata"]["transformations"])

    def test_cancel_before_execution_publishes_nothing(self):
        launched = self.launch().json()
        cancelled = self.client.post(
            f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/cancel/",
            format="json", **self.auth_headers,
        )
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK)
        self.assertEqual(cancelled.json()["state"], "cancelled")
        self.assertEqual(cancelled.json()["job"]["status"], "cancelled")
        self.assertEqual(cancelled.json()["budget_reservation"]["state"], "released")
        self.assertIsNone(claim_job(self.worker))
        self.assertEqual(
            self.client.get("/api/v1/datasets/", **self.auth_headers).json()["results"], [])

    def test_resume_after_a_cancelled_transfer_requeues_the_job(self):
        launched = self.launch(record_limit=8).json()
        self.client.post(
            f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/cancel/",
            format="json", **self.auth_headers,
        )
        resumed = self.client.post(
            f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/resume/",
            data={"budget_policy_id": str(self.policy.policy_id), "estimated_amount": "8"},
            format="json", **self.auth_headers,
        )
        self.assertEqual(resumed.status_code, status.HTTP_202_ACCEPTED, resumed.content)
        self.assertEqual(resumed.json()["state"], "ingesting")
        self.assertEqual(resumed.json()["job"]["status"], "queued")
        self.assertEqual(self.run_worker()["status"], "succeeded")
        self.assertEqual(self.state(launched["snapshot_id"]).json()["verified_records"], 8)

    def test_cross_tenant_transfer_state_is_forbidden(self):
        launched = self.launch().json()
        response = self.state(launched["snapshot_id"], **self.other_headers)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn("another organization", response.json()["detail"])
        cancel = self.client.post(
            f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/cancel/",
            format="json", **self.other_headers,
        )
        self.assertEqual(cancel.status_code, status.HTTP_403_FORBIDDEN)

    def test_viewer_role_cannot_launch_an_acquisition(self):
        viewer = _api_key(self.tenant, "viewer")
        response = self.client.post(
            "/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
            data={"record_limit": 4}, format="json", **viewer,
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_launch_requires_a_budget_policy_when_one_is_enabled(self):
        with patch("modelanvil.data.bank.acquisition.https_transport") as upstream:
            response = self.client.post(
                "/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                data={"record_limit": 4}, format="json", **self.auth_headers,
            )
        upstream.assert_not_called()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("budget_policy_id", response.json()["detail"])

    def test_invalid_launch_payloads_are_refused_before_network_or_side_effects(self):
        from modelanvil.data.models import SourceSnapshot
        from modelanvil.jobs.models import Job
        valid = {"budget_policy_id": str(self.policy.policy_id), "estimated_amount": "4"}
        for changed in ({"estimated_amount": "NaN"}, {"estimated_amount": "Infinity"},
                        {"estimated_amount": "0"}, {"estimated_amount": "0.0000001"},
                        {"estimated_amount": "1001"}, {"budget_policy_id": "bad-id"},
                        {"record_limit": "bad-limit"}, {"project_policy": []},
                        {"unknown_field": True}):
            with self.subTest(changed=changed), patch("modelanvil.data.bank.acquisition.https_transport") as upstream:
                response = self.client.post("/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                    data={**valid, **changed}, format="json", **self.auth_headers)
                self.assertEqual(response.status_code, 400, response.content)
                upstream.assert_not_called()
        self.assertFalse(SourceSnapshot.all_objects.filter(tenant_id=self.tenant.pk).exists())
        self.assertFalse(Job.all_objects.filter(tenant_id=self.tenant.pk).exists())

    def test_record_estimate_and_policy_unit_cannot_bypass_budget_admission(self):
        for estimate, unit in (("1", "bank_acquisition_records"), ("4", "USD")):
            self.policy.unit = unit
            self.policy.save(update_fields=["unit"])
            with patch("modelanvil.data.bank.acquisition.https_transport") as upstream:
                response = self.client.post("/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                    data={"record_limit": 4, "budget_policy_id": str(self.policy.policy_id), "estimated_amount": estimate},
                    format="json", **self.auth_headers)
            self.assertEqual(response.status_code, 400, response.content)
            upstream.assert_not_called()

    def test_publication_failure_is_resumable_without_refetching_or_double_billing(self):
        from modelanvil.budgets.models import UsageEvent
        launched = self.launch(record_limit=4).json()
        with patch("modelanvil.data.bank.acquisition._publish", side_effect=ValueError("invalid publication")):
            self.assertEqual(self.run_worker()["status"], "failed")
        failed = self.state(launched["snapshot_id"]).json()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["verified_records"], 4)
        self.assertIsNone(failed["revision_id"])
        before = len([url for url in self.upstream.fetches if url.endswith(".svg")])
        resumed = self.client.post(f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/resume/",
            data={"budget_policy_id": str(self.policy.policy_id), "estimated_amount": "1"},
            format="json", **self.auth_headers)
        self.assertEqual(resumed.status_code, 202, resumed.content)
        self.assertEqual(self.run_worker()["status"], "succeeded")
        ready = self.state(launched["snapshot_id"]).json()
        self.assertEqual(ready["state"], "ready")
        self.assertEqual(ready["budget_reservation"]["state"], "released")
        self.assertEqual(len([url for url in self.upstream.fetches if url.endswith(".svg")]), before)
        self.assertEqual(sum(UsageEvent.all_objects.filter(tenant_id=self.tenant.pk).values_list("quantity", flat=True)), Decimal("4"))

    def test_running_cancel_settles_transferred_records_and_resume_charges_only_remaining(self):
        from modelanvil.budgets.models import UsageEvent
        from modelanvil.data.bank.acquisition import fetch_record
        launched = self.launch(record_limit=4).json()
        count = 0
        def cancelling_fetch(source, record, **kwargs):
            nonlocal count
            payload = fetch_record(source, record, **kwargs)
            if record.path.endswith(".svg"):
                count += 1
                if count == 2:
                    cancelled = self.client.post(f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/cancel/",
                        {}, format="json", **self.auth_headers)
                    self.assertEqual(cancelled.status_code, 200)
                    self.assertEqual(cancelled.json()["budget_reservation"]["state"], "reserved")
            return payload
        with patch("modelanvil.data.bank.acquisition.fetch_record", side_effect=cancelling_fetch):
            self.assertEqual(self.run_worker()["status"], "interrupted")
        stopped = self.state(launched["snapshot_id"]).json()
        self.assertEqual(stopped["state"], "cancelled")
        self.assertEqual(stopped["budget_reservation"]["settled_amount"], "2.000000")
        resumed = self.client.post(f"/api/v1/dataset-bank/acquisitions/{launched['snapshot_id']}/resume/",
            data={"budget_policy_id": str(self.policy.policy_id), "estimated_amount": "2"},
            format="json", **self.auth_headers)
        self.assertEqual(resumed.status_code, 202, resumed.content)
        self.assertEqual(self.run_worker()["status"], "succeeded")
        self.assertEqual(self.state(launched["snapshot_id"]).json()["budget_reservation"]["settled_amount"], "2.000000")
        self.assertEqual(sum(UsageEvent.all_objects.filter(tenant_id=self.tenant.pk).values_list("quantity", flat=True)), Decimal("4"))

    def test_selected_project_is_preserved_through_publication_and_fences_status_actions(self):
        from modelanvil.artifacts.models import DatasetRevision
        from modelanvil.data.models import SourceSnapshot
        team = Team.objects.create(tenant_id=self.tenant.pk, name="Data team", slug="data-team")
        first = Project.objects.create(tenant_id=self.tenant.pk, team=team, name="First", slug="first")
        second = Project.objects.create(tenant_id=self.tenant.pk, team=team, name="Second", slug="second")
        first_headers = {**self.auth_headers, "HTTP_X_PROJECT_ID": str(first.pk)}
        second_headers = {**self.auth_headers, "HTTP_X_PROJECT_ID": str(second.pk)}
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            preview = self.client.get("/api/v1/dataset-bank/sources/svg-lucide/preview/", **first_headers)
            self.assertEqual(preview.status_code, 200, preview.content)
            self.assertEqual(preview.json()["launch_disclosure"]["destination"]["project_id"], str(first.pk))
            response = self.client.post("/api/v1/dataset-bank/sources/svg-lucide/acquisitions/",
                data={"record_limit": 4, "budget_policy_id": str(self.policy.policy_id), "estimated_amount": "4"},
                format="json", **first_headers)
        self.assertEqual(response.status_code, 201, response.content)
        sid = response.json()["snapshot_id"]
        snapshot = SourceSnapshot.all_objects.get(snapshot_id=sid)
        self.assertEqual(snapshot.project_id, first.pk)
        self.assertEqual(snapshot.source.project_id, first.pk)
        for suffix, method in (("", "get"), ("cancel/", "post"), ("resume/", "post")):
            self.assertEqual(getattr(self.client, method)(f"/api/v1/dataset-bank/acquisitions/{sid}/{suffix}",
                **second_headers).status_code, 403)
        self.run_worker()
        published = self.client.get(f"/api/v1/dataset-bank/acquisitions/{sid}/", **first_headers).json()
        self.assertEqual(published["state"], "ready")
        revision = DatasetRevision.all_objects.get(revision_id=published["revision_id"])
        self.assertEqual(revision.project_id, first.pk)
        self.assertEqual(revision.dataset.project_id, first.pk)
        self.assertEqual(revision.manifest_artifact.project_id, first.pk)
