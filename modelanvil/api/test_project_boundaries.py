"""Regression and verification tests for project boundaries and resource relationships (TASK-2 / MA-PM-02).

Validates:
1. Two tenants (Tenant A, Tenant B) and two restricted projects per tenant (Proj A1, Proj A2; Proj B1, Proj B2).
2. Cross-tenant and unauthorized-project resource relationship rejections before mutation on POST, PUT, PATCH, and custom actions.
3. Cross-project resource referencing enabled via explicit ProjectGrant.
4. Non-leakage: denials return 400/404 without leaking existence of resources in other tenants or projects.
5. Role restrictions and audit evidence:
   - Budget policy, runner manifest, and adapter registry write restrictions.
   - Endpoint promotion and rollback: Role.MANAGER minimum, audit event recorded on denied and ok.
   - Policy exceptions: Role.MANAGER minimum, audit event recorded on denied and ok.
   - Worker administration and artifact grants: Role.ADMIN minimum, audit event recorded on denied and ok.
"""
from __future__ import annotations

import uuid
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.core.models import AuditEvent
from modelanvil.data.models import DataSource, SourceSnapshot
from modelanvil.identity.models import (
    ApiKey,
    Project,
    ProjectGrant,
    Role,
    Team,
    Tenant,
    generate_api_key,
)
from modelanvil.releases.models import (
    DeploymentRevision,
    GateResult,
    Release,
    ReleaseVersion,
    ServingEndpoint,
)
from modelanvil.runners.models import (
    EvaluationSuite,
    EvaluationSuiteVersion,
    EvaluationRun,
    Model,
    ModelVersion,
    TokenizerVersion,
)


class ProjectBoundariesAndAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # -------------------------------------------------------------------
        # Tenant A Setup
        # -------------------------------------------------------------------
        self.tenant_a = Tenant.objects.create(slug="tenant-a", name="Tenant A")
        self.team_a = Team.objects.create(tenant_id=self.tenant_a.tenant_id, slug="team-a", name="Team A")
        self.proj_a1 = Project.objects.create(
            tenant_id=self.tenant_a.tenant_id, team=self.team_a, slug="proj-a1", name="Project A1"
        )
        self.proj_a2 = Project.objects.create(
            tenant_id=self.tenant_a.tenant_id, team=self.team_a, slug="proj-a2", name="Project A2"
        )

        # Keys for Tenant A
        self.raw_key_a1, key_a1 = self._create_key(self.tenant_a, Role.ENGINEER, project=self.proj_a1)
        self.raw_key_a2, key_a2 = self._create_key(self.tenant_a, Role.ENGINEER, project=self.proj_a2)
        self.raw_key_a_mgr, key_a_mgr = self._create_key(self.tenant_a, Role.MANAGER, project=self.proj_a1)
        self.raw_key_a_admin, key_a_admin = self._create_key(self.tenant_a, Role.ADMIN)

        # -------------------------------------------------------------------
        # Tenant B Setup
        # -------------------------------------------------------------------
        self.tenant_b = Tenant.objects.create(slug="tenant-b", name="Tenant B")
        self.team_b = Team.objects.create(tenant_id=self.tenant_b.tenant_id, slug="team-b", name="Team B")
        self.proj_b1 = Project.objects.create(
            tenant_id=self.tenant_b.tenant_id, team=self.team_b, slug="proj-b1", name="Project B1"
        )
        self.proj_b2 = Project.objects.create(
            tenant_id=self.tenant_b.tenant_id, team=self.team_b, slug="proj-b2", name="Project B2"
        )

        # Keys for Tenant B
        self.raw_key_b1, key_b1 = self._create_key(self.tenant_b, Role.ENGINEER, project=self.proj_b1)
        self.raw_key_b_admin, key_b_admin = self._create_key(self.tenant_b, Role.ADMIN)

        # -------------------------------------------------------------------
        # Resources in Proj A1
        # -------------------------------------------------------------------
        self.source_a1 = DataSource.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Source A1",
            kind="s3",
        )
        self.model_a1 = Model.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Model A1",
        )
        self.tok_a1 = TokenizerVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Tokenizer A1",
            vocabulary_size=1000,
        )
        self.mv_a1 = ModelVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            model=self.model_a1,
            tokenizer=self.tok_a1,
            revision_no=1,
            state="ready",
        )
        self.suite_a1 = EvaluationSuite.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Suite A1",
        )
        self.suite_v_a1 = EvaluationSuiteVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            suite=self.suite_a1,
            revision_no=1,
        )
        self.release_a1 = Release.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Release A1",
        )
        self.rv_a1 = ReleaseVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            release=self.release_a1,
            model_version=self.mv_a1,
            revision_no=1,
            status=ReleaseVersion.Status.QUALIFIED,
        )
        self.endpoint_a1 = ServingEndpoint.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            endpoint_key="ep-a1",
            name="Endpoint A1",
        )
        self.artifact_a1 = Artifact.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            storage_location_id="loc-a1",
            object_key="art-a1",
            sha256="a" * 64,
            byte_size=100,
            media_type="application/octet-stream",
            state=Artifact.State.COMMITTED,
        )
        self.dataset_a1 = Dataset.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a1,
            name="Dataset A1",
        )

        # -------------------------------------------------------------------
        # Resources in Proj A2 (Restricted sibling project in same tenant)
        # -------------------------------------------------------------------
        self.source_a2 = DataSource.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            name="Source A2",
            kind="s3",
        )
        self.model_a2 = Model.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            name="Model A2",
        )
        self.tok_a2 = TokenizerVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            name="Tokenizer A2",
            vocabulary_size=1000,
        )
        self.mv_a2 = ModelVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            model=self.model_a2,
            tokenizer=self.tok_a2,
            revision_no=1,
            state="ready",
        )
        self.release_a2 = Release.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            name="Release A2",
        )
        self.rv_a2 = ReleaseVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            release=self.release_a2,
            model_version=self.mv_a2,
            revision_no=1,
            status=ReleaseVersion.Status.QUALIFIED,
        )
        self.artifact_a2 = Artifact.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            storage_location_id="loc-a2",
            object_key="art-a2",
            sha256="b" * 64,
            byte_size=200,
            media_type="application/octet-stream",
            state=Artifact.State.COMMITTED,
        )

        # -------------------------------------------------------------------
        # Resources in Tenant B (Different tenant)
        # -------------------------------------------------------------------
        self.source_b1 = DataSource.objects.create(
            tenant_id=self.tenant_b.tenant_id,
            project=self.proj_b1,
            name="Source B1",
            kind="s3",
        )
        self.model_b1 = Model.objects.create(
            tenant_id=self.tenant_b.tenant_id,
            project=self.proj_b1,
            name="Model B1",
        )
        self.tok_b1 = TokenizerVersion.objects.create(
            tenant_id=self.tenant_b.tenant_id,
            project=self.proj_b1,
            name="Tokenizer B1",
            vocabulary_size=1000,
        )
        self.mv_b1 = ModelVersion.objects.create(
            tenant_id=self.tenant_b.tenant_id,
            project=self.proj_b1,
            model=self.model_b1,
            tokenizer=self.tok_b1,
            revision_no=1,
            state="ready",
        )

    def _create_key(self, tenant: Tenant, role: str, project: Project | None = None) -> tuple[str, ApiKey]:
        raw, hashed = generate_api_key()
        key = ApiKey.objects.create(
            tenant_id=tenant.tenant_id,
            project=project,
            name=f"Key for {tenant.slug} {role}",
            role=role,
            secret_hash=hashed,
        )
        return raw, key

    # =======================================================================
    # 1. Cross-Tenant Rejection Tests (POST/PUT/PATCH must not leak existence)
    # =======================================================================
    def test_cross_tenant_source_snapshot_reference_rejected(self):
        """Proj A1 caller cannot snapshot a DataSource from Tenant B."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/source-snapshots/", {

            "source": self.source_b1.pk,
            "source_revision": "rev-1",
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))
        self.assertNotIn(b"tenant-b", res.content.lower())

    def test_cross_tenant_model_version_references_rejected(self):
        """Proj A1 caller cannot create a ModelVersion referencing Model or Tokenizer from Tenant B."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        # Foreign model
        res = self.client.post("/api/v1/model-versions/", {
            "model": self.model_b1.pk,
            "tokenizer": self.tok_a1.pk,
            "revision_no": 2,
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

        # Foreign tokenizer
        res = self.client.post("/api/v1/model-versions/", {
            "model": self.model_a1.pk,
            "tokenizer": self.tok_b1.pk,
            "revision_no": 2,
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    def test_cross_tenant_release_version_references_rejected(self):
        """Proj A1 caller cannot create a ReleaseVersion referencing ModelVersion from Tenant B."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/release-versions/", {
            "release": str(self.release_a1.release_id),
            "model_version": str(self.mv_b1.model_version_id),
            "revision_no": 2,
            "candidate_ref": "ref-1",
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    def test_cross_tenant_evaluation_run_references_rejected(self):
        """Proj A1 caller cannot run evals against candidate ModelVersion from Tenant B."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/evaluation-runs/", {
            "suite_version": str(self.suite_v_a1.suite_version_id),
            "candidate_model_version": str(self.mv_b1.model_version_id),
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    # =======================================================================
    # 2. Cross-Project Rejection Tests (Same tenant, without ProjectGrant)
    # =======================================================================
    def test_cross_project_source_snapshot_rejected_without_grant(self):
        """Proj A1 caller cannot reference Source from restricted Proj A2."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/source-snapshots/", {

            "source": self.source_a2.pk,
            "source_revision": "rev-1",
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    def test_cross_project_model_version_rejected_without_grant(self):
        """Proj A1 caller cannot create ModelVersion referencing Model from restricted Proj A2."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/model-versions/", {
            "model": self.model_a2.pk,
            "tokenizer": self.tok_a1.pk,
            "revision_no": 2,
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    def test_cross_project_release_version_rejected_without_grant(self):
        """Proj A1 caller cannot link ModelVersion from restricted Proj A2 into its Release."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/release-versions/", {
            "release": str(self.release_a1.release_id),
            "model_version": str(self.mv_a2.model_version_id),
            "revision_no": 2,
            "candidate_ref": "ref-1",
        })
        self.assertIn(res.status_code, (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND))

    def test_cross_project_dataset_preparation_rejected_without_grant(self):
        """Proj A1 caller cannot prepare Dataset using Artifact owned by restricted Proj A2."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post(f"/api/v1/datasets/{self.dataset_a1.dataset_id}/prepare/", {
            "input_artifact_id": str(self.artifact_a2.artifact_id),
        })
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # =======================================================================
    # 3. Cross-Project Access Allowed With Explicit ProjectGrant
    # =======================================================================
    def test_cross_project_model_version_allowed_with_project_grant(self):
        """When Proj A2 grants access to Proj A1, referencing is permitted."""
        # Grant Proj A1 access to Proj A2's model
        ProjectGrant.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            project=self.proj_a2,
            granted_to_project=self.proj_a1,
            resource_type="model",
            resource_id=self.model_a2.model_id,
        )

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/model-versions/", {
            "model": self.model_a2.pk,
            "tokenizer": self.tok_a1.pk,
            "revision_no": 2,
            "architecture_ref": "arch-1",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(res.data["project"]), str(self.proj_a1.id))

    def test_project_grants_api_crud(self):
        """Manager can manage ProjectGrants via REST API."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a_mgr}")
        res = self.client.post("/api/v1/project-grants/", {
            "project": str(self.proj_a2.id),
            "granted_to_project": str(self.proj_a1.id),
            "resource_type": "all",
            "role": Role.VIEWER,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        grant_id = res.data["id"]

        # View grant
        res = self.client.get(f"/api/v1/project-grants/{grant_id}/")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Self-grant rejected
        res = self.client.post("/api/v1/project-grants/", {
            "project": str(self.proj_a1.id),
            "granted_to_project": str(self.proj_a1.id),
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # =======================================================================
    # 4. Same-Scope Legitimate Writes
    # =======================================================================
    def test_legitimate_same_scope_writes_succeed(self):
        """All legitimate writes within same project succeed and inherit project scope."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        # Create Model
        res = self.client.post("/api/v1/models/", {
            "name": "New Model A1",
            "intended_tasks": ["chat"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        model_id = res.data["model_id"]

        # Create ModelVersion
        res = self.client.post("/api/v1/model-versions/", {
            "model": res.data["id"],
            "tokenizer": self.tok_a1.pk,
            "revision_no": 1,
            "architecture_ref": "llama-style",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(res.data["project"]), str(self.proj_a1.id))

        # Create SourceSnapshot
        res = self.client.post("/api/v1/source-snapshots/", {

            "source": self.source_a1.pk,
            "source_revision": "rev-1",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(res.data["project"]), str(self.proj_a1.id))

    # =======================================================================
    # 5. Role Restrictions & Audit Evidence
    # =======================================================================
    def test_registry_write_role_restrictions(self):
        """BudgetPolicy & RunnerManifest require ADMIN; AdapterRegistry requires MANAGER."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")  # ENGINEER

        # Engineer denied on BudgetPolicy
        res = self.client.post("/api/v1/budget-policies/", {
            "name": "Eng Policy",
            "period": "monthly",
            "unit": "dollars",
            "limit_amount": "500.00",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Engineer denied on RunnerManifest
        res = self.client.post("/api/v1/runner-manifests/", {
            "name": "Manifest 1",
            "version": "1.0",
            "digest": "abc",
            "manifest": {},
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Create AdapterRegistry entry directly
        from modelanvil.runners.models import AdapterRegistryEntry
        valid_manifest = {
            "schema_version": "1.0",
            "adapter_id": "test-adapter",
            "version": "1.0.0",
            "platform_api": "1.0",
            "image": "img@sha256:" + "a" * 64,
            "license": "Apache-2.0",
            "capabilities": [{"kind": "predict", "input_schema_refs": ["ref1"], "output_schema_refs": ["ref2"]}],
            "resources": {
                "cpu_cores": 1,
                "memory_bytes": 1024,
                "gpu_count": 0,
                "disk_bytes": 1024,
            },
            "permissions": {
                "network_hosts": [],
                "artifact_access": [],
                "secret_kinds": [],
            },
            "dependencies": [],
        }
        adapter_entry = AdapterRegistryEntry.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            name="adapter-1",
            version="1.0",
            manifest_digest="0" * 64,
            manifest=valid_manifest,
        )

        # Engineer denied on AdapterRegistry mutation
        res = self.client.patch(f"/api/v1/adapter-registry/{adapter_entry.entry_id}/", {
            "enabled": False,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

        # Manager allowed on AdapterRegistry mutation
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a_mgr}")
        res = self.client.patch(f"/api/v1/adapter-registry/{adapter_entry.entry_id}/", {
            "enabled": False,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Admin allowed on BudgetPolicy and RunnerManifest
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a_admin}")
        res = self.client.post("/api/v1/budget-policies/", {
            "name": "Admin Policy",
            "period": "monthly",
            "unit": "dollars",
            "limit_amount": "1000.00",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_serving_endpoint_promotion_authorization_and_audit(self):
        """Promotion requires MANAGER; unauthorized attempts are denied and audited."""
        # 1. Engineer denied
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post(f"/api/v1/serving-endpoints/{self.endpoint_a1.endpoint_id}/promote/", {
            "release_version_id": str(self.rv_a1.release_version_id),
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        audit_denied = AuditEvent.objects.filter(
            action="promote",
            resource_type="serving_endpoint",
            resource_id=self.endpoint_a1.endpoint_id,
            result="denied",
        ).first()
        self.assertIsNotNone(audit_denied)

        # 2. Manager attempting to promote release version from restricted Proj A2
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a_mgr}")
        res = self.client.post(f"/api/v1/serving-endpoints/{self.endpoint_a1.endpoint_id}/promote/", {
            "release_version_id": str(self.rv_a2.release_version_id),
        })
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        audit_cross_denied = AuditEvent.objects.filter(
            action="promote",
            resource_type="serving_endpoint",
            resource_id=self.endpoint_a1.endpoint_id,
            result="denied",
        ).count()
        self.assertGreaterEqual(audit_cross_denied, 2)

        # 3. Same-scope manager passes authorization, but fixture runtime cannot serve.
        res = self.client.post(f"/api/v1/serving-endpoints/{self.endpoint_a1.endpoint_id}/promote/", {
            "release_version_id": str(self.rv_a1.release_version_id),
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("unqualified", str(res.data))
        self.assertTrue(AuditEvent.objects.filter(action="promote", resource_id=self.endpoint_a1.endpoint_id,
                                                 result="denied", input_snapshot={"reason": "runtime_unqualified"}).exists())

    def test_policy_exception_authorization_and_audit(self):
        """Waiving gate results requires MANAGER; unauthorized attempts are denied and audited."""
        gate = GateResult.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            release_version=self.rv_a1,
            criterion_key="eval_accuracy",
            passed=False,
        )

        # 1. Engineer denied
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post(f"/api/v1/release-versions/{self.rv_a1.release_version_id}/exceptions/", {
            "gate_result_id": str(gate.gate_result_id),
            "reason": "Engineer emergency waiver",
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        audit_denied = AuditEvent.objects.filter(
            action="create_policy_exception",
            resource_type="release_version",
            result="denied",
        ).first()
        self.assertIsNotNone(audit_denied)

        # 2. Manager granted
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a_mgr}")
        res = self.client.post(f"/api/v1/release-versions/{self.rv_a1.release_version_id}/exceptions/", {
            "gate_result_id": str(gate.gate_result_id),
            "reason": "Authorized manager waiver for staging demo",
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        audit_ok = AuditEvent.objects.filter(
            action="create_policy_exception",
            resource_type="release_version",
            result="ok",
        ).first()
        self.assertIsNotNone(audit_ok)

    def test_worker_and_storage_admin_authorization_and_audit(self):
        """Worker administration & storage grants require ADMIN; denials record audit evidence."""
        # 1. Worker registration denial
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        res = self.client.post("/api/v1/workers/register/", {
            "pool": "pool-1",
            "hostname": "host-1",
            "platform": {"os": "linux"},
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        audit_worker_denied = AuditEvent.objects.filter(
            action="admin_denied",
            resource_type="worker_administration",
            result="denied",
        ).first()
        self.assertIsNotNone(audit_worker_denied)

        # 2. Worker artifact download grant issuance denial
        fake_attempt_id = uuid.uuid4()
        res = self.client.post("/api/v1/workers/artifact-grants/", {
            "worker_id": 1,
            "attempt_id": str(fake_attempt_id),
            "artifact_id": str(self.artifact_a1.artifact_id),
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        audit_grant_denied = AuditEvent.objects.filter(
            action="create",
            resource_type="worker_artifact_grant",
            result="denied",
        ).first()
        self.assertIsNotNone(audit_grant_denied)


class TrainingBoundaryRegressionTests(TestCase):
    setUp = ProjectBoundariesAndAuthorizationTests.setUp
    _create_key = ProjectBoundariesAndAuthorizationTests._create_key

    def payload(self):
        return {"execution_mode": "simulation", "recipe_type": "lora_adapter", "base_model_version": self.mv_a1.pk,
                "tokenizer_version": self.tok_a1.pk, "total_steps": 2}

    def test_training_relations_rejected_before_mutation_on_all_write_methods(self):
        from modelanvil.runners.models import TrainingRun
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        created = self.client.post('/api/v1/training-runs/', self.payload(), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        run_id = created.data['run_id']
        for method in ['post', 'put', 'patch']:
            for field, value in [('base_model_version', self.mv_a2.pk), ('tokenizer_version', self.tok_b1.pk), ('project', str(self.proj_a2.pk)), ('project', None)]:
                with self.subTest(method=method, field=field, value=value):
                    payload = {**self.payload(), field: value}
                    path = '/api/v1/training-runs/' if method == 'post' else f'/api/v1/training-runs/{run_id}/'
                    response = getattr(self.client, method)(path, payload, format='json')
                    self.assertEqual(response.status_code, 400, response.json())
        run = TrainingRun.all_objects.get(run_id=run_id)
        self.assertEqual(run.project_id, self.proj_a1.pk)
        self.assertEqual(run.base_model_version_id, self.mv_a1.pk)
        self.assertEqual(TrainingRun.all_objects.count(), 1)

    def test_restricted_training_read_and_actions_hide_other_projects(self):
        from modelanvil.runners.models import TrainingRun
        run = TrainingRun.all_objects.create(tenant_id=self.tenant_a.tenant_id, project=self.proj_a2,
            recipe_type='lora_adapter', base_model_version=self.mv_a2, tokenizer_version=self.tok_a2)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.raw_key_a1}")
        self.assertEqual(self.client.get(f'/api/v1/training-runs/{run.run_id}/').status_code, 404)
        page = self.client.get('/api/v1/training-runs/')
        self.assertEqual(len(page.data['results']), 0)
        for action in ['cancel', 'train-steps', 'export', 'infer']:
            self.assertEqual(self.client.post(f'/api/v1/training-runs/{run.run_id}/{action}/', {}, format='json').status_code, 404)
        self.assertEqual(self.client.get(f'/api/v1/training-runs/{uuid.uuid4()}/').status_code, 404)

    def test_viewer_cannot_create_or_execute_training(self):
        from modelanvil.runners.models import TrainingRun
        key, _ = self._create_key(self.tenant_a, Role.VIEWER, self.proj_a1)
        run = TrainingRun.all_objects.create(tenant_id=self.tenant_a.tenant_id, project=self.proj_a1,
            recipe_type='lora_adapter', base_model_version=self.mv_a1, tokenizer_version=self.tok_a1)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {key}')
        self.assertEqual(self.client.post('/api/v1/training-runs/', self.payload(), format='json').status_code, 403)
        for action in ['cancel', 'train-steps', 'export', 'infer']:
            self.assertEqual(self.client.post(f'/api/v1/training-runs/{run.run_id}/{action}/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.get(f'/api/v1/training-runs/{run.run_id}/').status_code, 200)

    def test_idempotency_cache_is_principal_scoped_and_rejects_changed_body(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a1}')
        path = '/api/v1/training-runs/'
        first = self.client.post(path, self.payload(), format='json', HTTP_IDEMPOTENCY_KEY='shared')
        replay = self.client.post(path, self.payload(), format='json', HTTP_IDEMPOTENCY_KEY='shared')
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(replay.data['run_id'], first.data['run_id'])
        changed = self.client.post(path, {**self.payload(), 'total_steps': 3}, format='json', HTTP_IDEMPOTENCY_KEY='shared')
        self.assertEqual(changed.status_code, 409)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a2}')
        other = self.client.post(path, {**self.payload(), 'base_model_version': self.mv_a2.pk, 'tokenizer_version': self.tok_a2.pk},
                                 format='json', HTTP_IDEMPOTENCY_KEY='shared')
        self.assertEqual(other.status_code, 201, other.data)
        self.assertNotEqual(other.data['run_id'], first.data['run_id'])

    def test_model_qualification_cannot_be_set_from_registry_metadata(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a1}')
        response = self.client.patch(f'/api/v1/model-versions/{self.mv_a1.model_version_id}/', {'state': 'qualified'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_dataset_and_pool_references_are_scoped_on_create(self):
        from modelanvil.jobs.models import WorkerPool
        dataset = Dataset.all_objects.create(tenant_id=self.tenant_a.tenant_id, project=self.proj_a2, name='Training data A2')
        revision = DatasetRevision.all_objects.create(tenant_id=self.tenant_a.tenant_id, project=self.proj_a2,
            dataset=dataset, revision_no=1, state='published', manifest_digest='a' * 64)
        pool = WorkerPool.all_objects.create(tenant_id=self.tenant_b.tenant_id, name='other-tenant')
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a1}')
        for field, value in [('dataset_revision', revision.pk), ('pool', pool.pk)]:
            response = self.client.post('/api/v1/training-runs/', {**self.payload(), field: value}, format='json')
            self.assertEqual(response.status_code, 400, response.json())
        from modelanvil.runners.models import TrainingRun
        self.assertEqual(TrainingRun.all_objects.count(), 0)

    def test_alignment_relationships_are_scoped_on_post_put_patch(self):
        from modelanvil.runners.models import AlignmentRun
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a1}')
        payload = {'algorithm': 'dpo', 'policy_model_version': self.mv_a1.pk, 'reference_model_version': self.mv_a1.pk,
                   'dataset_manifest_digest': 'a' * 64, 'held_out_validation_digest': 'b' * 64}
        created = self.client.post('/api/v1/alignment-runs/', payload, format='json')
        self.assertEqual(created.status_code, 201, created.json())
        run = AlignmentRun.all_objects.get(run_id=created.data['run_id'])
        for method in ['post', 'put', 'patch']:
            path = '/api/v1/alignment-runs/' if method == 'post' else f'/api/v1/alignment-runs/{run.pk}/'
            for field, value in [('policy_model_version', self.mv_b1.pk), ('reference_model_version', self.mv_a2.pk), ('reward_model_version', self.mv_a2.pk)]:
                response = getattr(self.client, method)(path, {**payload, field: value}, format='json')
                self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(AlignmentRun.all_objects.count(), 1)

    def test_release_gate_references_rejected_before_mutation(self):
        evaluation = EvaluationRun.all_objects.create(tenant_id=self.tenant_a.tenant_id, project=self.proj_a2,
            suite_version=self.suite_v_a1, candidate_model_version=self.mv_a2)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a1}')
        before = GateResult.all_objects.count()
        for reference in [str(evaluation.run_id), str(uuid.uuid4()), 'bad-id']:
            response = self.client.post(f'/api/v1/release-versions/{self.rv_a1.release_version_id}/evaluate-gates/',
                {'criteria': [{'key': 'min_accuracy', 'eval_run': reference}]}, format='json')
            self.assertEqual(response.status_code, 400, response.json())
        self.assertEqual(GateResult.all_objects.count(), before)

    def test_malformed_custom_action_references_never_surface_internal_errors(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.raw_key_a_mgr}')
        promotion = self.client.post(f'/api/v1/serving-endpoints/{self.endpoint_a1.endpoint_id}/promote/',
            {'release_version_id': 'malformed'}, format='json')
        self.assertEqual(promotion.status_code, 400)
        exception = self.client.post(f'/api/v1/release-versions/{self.rv_a1.release_version_id}/exceptions/',
            {'gate_result_id': 'malformed', 'reason': 'test'}, format='json')
        self.assertEqual(exception.status_code, 400)
