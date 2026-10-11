"""Actual frontend API client against isolated HTTP acquisition and labeling workflows."""
import json
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import LiveServerTestCase, override_settings

from modelanvil.artifacts.models import DatasetRevision
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.data.bank.acquisition import bank_acquisition_executor
from modelanvil.data.bank.test_acquisition import FakeUpstream
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.jobs.executor import execute_claim
from modelanvil.jobs.models import Worker, WorkerPool, claim_job


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"])
class DataWorkflowHttpTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js22.18+ is required for frontend-client HTTP acceptance.")
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL,
            "artifact_backend": "filesystem", "artifact_root": root.name})
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug="data-http", name="Data HTTP")
        self.secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="engineer", role=Role.ENGINEER, secret_hash=digest)
        pool = WorkerPool.objects.create(tenant_id=self.tenant.pk, name="bank-http")
        self.worker = Worker.objects.create(tenant_id=self.tenant.pk, pool=pool, name="bank-http",
            slots=1, capabilities={"dataset_acquisition": True})
        self.policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name="records",
            period="monthly", unit="bank_acquisition_records", limit_amount=Decimal("100"))
        self.upstream = FakeUpstream(record_count=12)

    def frontend(self, **options):
        script = Path(settings.BASE_DIR) / "scripts" / "data_workflows_http.mjs"
        result = subprocess.run([shutil.which("node"), str(script)], cwd=settings.BASE_DIR,
            input=json.dumps({"base": self.live_server_url, "token": self.secret, "mode": "bank",
                "policy": str(self.policy.policy_id), "records": 4, **options}),
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_budget_refusal_over_http_never_requests_upstream(self):
        with patch("modelanvil.data.bank.acquisition.https_transport") as upstream:
            self.assertEqual(self.frontend(refused=True), {"state": "refused"})
        upstream.assert_not_called()

    def test_acquire_cancel_resume_execute_and_inspect_publication_over_http(self):
        with patch("modelanvil.data.bank.acquisition.https_transport", self.upstream):
            queued = self.frontend()
            descriptor = claim_job(self.worker)
            self.assertIsNotNone(descriptor)
            self.assertEqual(execute_claim(self.worker, descriptor, bank_acquisition_executor)["status"], "succeeded")
            published = self.frontend(snapshot=queued["snapshot_id"])
        revision = DatasetRevision.all_objects.get(revision_id=published["revision_id"], tenant_id=self.tenant.pk)
        self.assertEqual(revision.row_count, 4)
        self.assertEqual(revision.dataset.current_revision_id, revision.pk)

    def test_human_review_conflict_history_snapshot_export_over_http(self):
        result = self.frontend(mode="annotation")
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["item_count"], 1)
