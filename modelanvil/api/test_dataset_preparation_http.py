"""Real HTTP acceptance using the exact frontend dataset client, not mocks."""
import hashlib
import base64
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import LiveServerTestCase, override_settings

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, LineageEdge
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key


@override_settings(ALLOWED_HOSTS=["127.0.0.1", "testserver"])
class DatasetPreparationHttpTests(LiveServerTestCase):
    host = "127.0.0.1"

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js 22.18+ is required for the actual frontend-client HTTP test.")
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        override = override_settings(MODELANVIL={**settings.MODELANVIL,
            "artifact_backend": "filesystem", "artifact_root": root.name})
        override.enable()
        self.addCleanup(override.disable)
        self.tenant = Tenant.objects.create(slug="dataset-http", name="Dataset HTTP")
        self.secret, digest = generate_api_key()
        ApiKey.objects.create(tenant=self.tenant, name="engineer", role=Role.ENGINEER, secret_hash=digest)
        self.documents = [{
            "schema_version": "1.0", "sample_id": f"00000000-0000-4000-8000-{number:012d}",
            "source_group_id": "shared-source", "blocks": [
                {"block_id": "text", "type": "text", "text": f"Original example {number} 日本語"}],
            "provenance": {"source_snapshot_ref": "uploaded-http-fixture",
                "source_record_key": str(number), "content_sha256": "a" * 64},
        } for number in range(1, 4)]

    def run_frontend(self, *, invalid=False):
        script = Path(settings.BASE_DIR) / "scripts" / "dataset_client_http.mjs"
        self.assertTrue(script.is_file(), "Missing actual dataset-client HTTP acceptance harness")
        raw = "".join(json.dumps(document, ensure_ascii=False) + "\n" for document in self.documents)
        if invalid:
            raw = "PRIVATE_MARKER\n"
        result = subprocess.run([shutil.which("node"), str(script)],
            cwd=settings.BASE_DIR, input=json.dumps({"base": self.live_server_url, "token": self.secret,
                "raw": raw, "invalid": invalid, "name": "HTTP prepared dataset"}),
            text=True, capture_output=True, timeout=30)
        # The harness prints only a client-owned sanitized status or summary.
        self.assertEqual(result.returncode, 0, "Frontend HTTP acceptance failed: " + result.stderr)
        return json.loads(result.stdout)

    def test_frontend_upload_prepare_list_and_verify_published_manifest_over_real_http(self):
        result = self.run_frontend()
        self.assertEqual(result["state"], "published")
        self.assertEqual(result["row_count"], len(self.documents))
        revision = DatasetRevision.all_objects.get(revision_id=result["revision_id"], tenant_id=self.tenant.pk)
        self.assertEqual(revision.state, DatasetRevision.State.PUBLISHED)
        self.assertEqual(revision.dataset.current_revision_id, revision.pk)
        artifact = revision.manifest_artifact
        self.assertEqual(artifact.state, Artifact.State.COMMITTED)
        with artifact_storage_backend().open(self.tenant.pk, artifact.object_key) as stream:
            raw = stream.read()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact.sha256)
        self.assertEqual(json.loads(raw)["rows"], self.documents)
        self.assertTrue(LineageEdge.all_objects.filter(child_artifact=artifact, tenant_id=self.tenant.pk).exists())
        self.assertEqual(result["request_count"], 8)

    def test_invalid_upload_stops_at_preparation_and_does_not_publish_or_delete_earlier_resources(self):
        result = self.run_frontend(invalid=True)
        self.assertEqual(result, {"state": "refused", "status": 400, "request_count": 4})
        self.assertFalse(DatasetRevision.all_objects.filter(tenant_id=self.tenant.pk).exists())
        self.assertEqual(Dataset.all_objects.filter(tenant_id=self.tenant.pk, current_revision=None).count(), 1)
        self.assertEqual(Artifact.all_objects.filter(tenant_id=self.tenant.pk, state=Artifact.State.COMMITTED).count(), 1)

    def test_actual_frontend_client_imports_csv_json_and_binary_docx_over_http(self):
        from modelanvil.data.test_source_import import docx
        text = "Actual source text 日本語"
        sources = [("csv", f'text\n{text}\n'.encode()),
                   ("json", json.dumps([{"text": text}], ensure_ascii=False).encode()),
                   ("docx", docx(f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>'))]
        for fmt, raw in sources:
            result = subprocess.run([shutil.which("node"), str(Path(settings.BASE_DIR) / "scripts/dataset_client_http.mjs")],
                cwd=settings.BASE_DIR, input=json.dumps({"base": self.live_server_url, "token": self.secret,
                    "raw_base64": base64.b64encode(raw).decode(), "source_format": fmt, "expected_texts": [text],
                    "name": f"HTTP {fmt} source"}), text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["state"], "published")
            self.assertEqual(report["row_count"], 1)
            self.assertEqual(report["request_count"], 8)

    def test_actual_frontend_client_imports_pdf_and_pins_parser_revision(self):
        from modelanvil.data.test_pdf_import import HAS_PDF, pdf
        if not HAS_PDF:
            self.skipTest("Install requirements.documents.txt for actual PDF HTTP checks")
        raw = pdf(["Real PDF page one", "Real PDF page two"], compressed=True)
        result = subprocess.run([shutil.which("node"), str(Path(settings.BASE_DIR) / "scripts/dataset_client_http.mjs")],
            cwd=settings.BASE_DIR, input=json.dumps({"base": self.live_server_url, "token": self.secret,
                "raw_base64": base64.b64encode(raw).decode(), "source_format": "pdf",
                "expected_texts": ["Real PDF page one", "Real PDF page two"], "name": "HTTP PDF source"}),
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["row_count"], 2)
        revision = DatasetRevision.all_objects.get(revision_id=report["revision_id"])
        self.assertEqual(revision.metadata["recipe"]["extraction"]["pdf_parser"], "pypdf==6.20.0")
