"""Tests for Software Bill of Materials (SBOM) and Model Provenance (SPDX 2.3)."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import tempfile

from django.conf import settings
from django.test import override_settings

from django.test import TestCase

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.releases.lifecycle import export_release_bundle
from modelanvil.runners.training.engine import CausalTextModel, pack_safetensors
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from rest_framework.test import APIClient
from modelanvil.releases.models import Release, ReleaseVersion
from modelanvil.releases.sbom import generate_model_sbom
from modelanvil.runners.models import Model, ModelVersion, TokenizerVersion


class ModelSBOMTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="sbom-org", name="SBOM Org")
        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="sbom-tok",
            vocabulary_size=32000,
        )
        self.model = Model.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="llama-governed",
            intended_tasks=["chat", "code"],
        )
        self.model_version = ModelVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="transformer",
            tokenizer=self.tokenizer,
            license_evidence="Apache-2.0",
            parameters_count=7000000000,
            state=ModelVersion.State.QUALIFIED,
        )
        self.release = Release.objects.create(
            tenant_id=self.tenant.tenant_id,
            name="Llama Governed Release",
        )
        self.release_version = ReleaseVersion.objects.create(
            tenant_id=self.tenant.tenant_id,
            release=self.release,
            revision_no=1,
            model_version=self.model_version,
            candidate_ref=str(self.model_version.model_version_id),
            status=ReleaseVersion.Status.QUALIFIED,
        )

    def test_generate_model_sbom_spdx_structure(self):
        report = generate_model_sbom(self.release_version)
        self.assertFalse(report.verified)
        self.assertNotIn("checksums", report.spdx_document["packages"][0])
        self.assertTrue(any("Metadata-only" in warning for warning in report.warnings))
        self.assertEqual(len(report.sbom_digest), 64)
        doc = report.spdx_document
        self.assertEqual(doc["spdxVersion"], "SPDX-2.3")
        self.assertEqual(doc["dataLicense"], "CC0-1.0")
        packages = doc["packages"]
        self.assertEqual(len(packages), 2)  # Model + Tokenizer
        model_pkg = next(p for p in packages if p["name"] == "llama-governed")
        self.assertEqual(model_pkg["licenseConcluded"], "Apache-2.0")
        self.assertEqual(model_pkg["versionInfo"], "r1")

    def test_tombstoned_component_blocks_sbom_generation(self):
        DeletionTombstone.objects.create(
            tenant_id=self.tenant.tenant_id,
            resource_type="model_version",
            resource_id=str(self.model_version.model_version_id),
            reason="GDPR right to be forgotten",
        )
        with self.assertRaises(PermissionError) as ctx:
            generate_model_sbom(self.release_version)
        self.assertIn("tombstoned", str(ctx.exception))

    def test_committed_numerical_bytes_back_export_and_deterministic_sbom(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': root}):
            tokens = ['<pad>', '<bos>', '<eos>', '<unk>', *list('abcdef')]
            raw, manifest = pack_safetensors(CausalTextModel(10, n_embd=4, lora_r=2, lora_alpha=4).export_tensors())
            bundle = {'config.json': {'vocab_size': 10, 'n_embd': 4, 'lora_r': 2, 'lora_alpha': 4},
                'weights_manifest.json': manifest, 'model.safetensors.b64': base64.b64encode(raw).decode(),
                'tokenizer_config.json': {'kind': 'character-v1', 'tokens': tokens, 'bos_id': 1, 'eos_id': 2, 'unk_id': 3}}
            payload = json.dumps(bundle).encode()
            artifact = Artifact.objects.create(tenant_id=self.tenant.pk, object_key='model.json', storage_location_id='local',
                sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json')
            backend = artifact_storage_backend()
            upload_staged_artifact(artifact, io.BytesIO(payload), backend=backend)
            self.tokenizer.vocabulary_size = 10; self.tokenizer.save()
            self.model_version.artifact_manifest_id = str(artifact.artifact_id)
            self.model_version.metadata = {'weights_sha256': hashlib.sha256(raw).hexdigest()}
            self.model_version.save()
            report = generate_model_sbom(self.release_version)
            self.assertTrue(report.verified)
            self.assertEqual(report.sbom_digest, generate_model_sbom(self.release_version).sbom_digest)
            checksum = report.spdx_document['packages'][0]['checksums'][0]['checksumValue']
            self.assertEqual(checksum, hashlib.sha256(raw).hexdigest())
            export = export_release_bundle(self.release_version)
            self.assertEqual(export['model_bundle'], bundle)
            self.assertEqual(export['model_artifact']['sha256'], artifact.sha256)
            self.assertFalse(export['loading_verification']['production_qualified'])
            self.assertFalse(export['independent_loading_evidence']['load_tested'])
            (backend.root / str(self.tenant.pk) / 'model.json').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                generate_model_sbom(self.release_version)
            with self.assertRaises(ValueError):
                export_release_bundle(self.release_version)

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_spdx_materialization_persists_once_and_requires_write_role(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MODELANVIL={**settings.MODELANVIL, 'artifact_backend': 'filesystem', 'artifact_root': root}):
            client = APIClient()
            viewer, hashed = generate_api_key()
            ApiKey.objects.create(tenant=self.tenant, name='viewer', role=Role.VIEWER, secret_hash=hashed)
            client.credentials(HTTP_AUTHORIZATION=f'Bearer {viewer}')
            path = f'/api/v1/release-versions/{self.release_version.release_version_id}/sbom/'
            self.assertEqual(client.get(path).status_code, 200)
            self.assertEqual(client.post(path, {}, format='json').status_code, 403)
            writer, hashed = generate_api_key()
            ApiKey.objects.create(tenant=self.tenant, name='writer', role=Role.ENGINEER, secret_hash=hashed)
            client.credentials(HTTP_AUTHORIZATION=f'Bearer {writer}')
            first = client.post(path, {}, format='json')
            self.assertEqual(first.status_code, 200, first.content)
            self.assertFalse(first.json()['verified'])
            second = client.post(path, {}, format='json')
            self.assertEqual(first.json()['sbom_artifact'], second.json()['sbom_artifact'])
            self.assertEqual(Artifact.objects.count(), 1)
            artifact = Artifact.objects.get()
            self.assertEqual(artifact.state, Artifact.State.COMMITTED)
            with artifact_storage_backend().open(self.tenant.pk, artifact.object_key) as stream:
                saved = stream.read()
            self.assertEqual(hashlib.sha256(saved).hexdigest(), artifact.sha256)
            self.assertEqual(json.loads(saved), first.json()['spdx_document'])
            download = client.get(first.json()['sbom_artifact']['download_endpoint'])
            self.assertEqual(download.status_code, 200)
            self.assertEqual(b''.join(download.streaming_content), saved)
            self.release_version.refresh_from_db()
            self.assertEqual(self.release_version.bundle_manifest['sbom']['artifact_id'], str(artifact.artifact_id))
