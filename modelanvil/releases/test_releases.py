"""Acceptance tests for WP-15: Release gates, exceptions, exports, quantization, promotion, and rollback (PRD Scenario 10 / TECH-020-021, TECH-024)."""
import uuid
from django.test import TestCase

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.identity.models import Tenant
from modelanvil.releases.lifecycle import (
    ReleasePromotionBlockedError,
    TombstoneAccessDeniedError,
    evaluate_release_gates,
    export_release_bundle,
    promote_endpoint,
    quantize_and_evaluate,
    record_policy_exception,
    rollback_endpoint,
)
from modelanvil.releases.models import (
    DeploymentRevision,
    GateResult,
    Release,
    ReleaseException,
    ReleaseVersion,
    ServingEndpoint,
)
from modelanvil.runners.models import (
    EvaluationMetric,
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
)


class ReleaseLifecycleTests(TestCase):
    """PRD Scenario 10: Complete Release & Rollback journey."""

    def setUp(self):
        self.tenant = Tenant.objects.create(slug="release-test-tenant", name="Release Test Tenant")
        self.tenant_id = self.tenant.tenant_id

        self.tokenizer = TokenizerVersion.objects.create(
            tenant_id=self.tenant_id,
            name="rel-tok",
            revision_no=1,
            vocabulary_size=32000,
        )

        self.model = Model.objects.create(
            tenant_id=self.tenant_id,
            name="release-candidate-model",
        )
        self.mv1 = ModelVersion.objects.create(
            tenant_id=self.tenant_id,
            model=self.model,
            revision_no=1,
            architecture_ref="arch-llama",
            tokenizer=self.tokenizer,
            state=ModelVersion.State.QUALIFIED,
            license_evidence="apache-2.0",
        )
        self.mv2 = ModelVersion.objects.create(
            tenant_id=self.tenant_id,
            model=self.model,
            revision_no=2,
            architecture_ref="arch-llama",
            tokenizer=self.tokenizer,
            state=ModelVersion.State.QUALIFIED,
            license_evidence="apache-2.0",
        )

        self.suite = EvaluationSuite.objects.create(tenant_id=self.tenant_id, name="Release Eval Suite")
        self.suite_v = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant_id, suite=self.suite, cases=[])

        self.eval_run_pass = EvaluationRun.objects.create(
            tenant_id=self.tenant_id,
            suite_version=self.suite_v,
            candidate_model_version=self.mv1,
            status=EvaluationRun.Status.COMPLETED,
        )
        EvaluationMetric.objects.create(
            tenant_id=self.tenant_id,
            run=self.eval_run_pass,
            key="accuracy",
            value=0.92,
        )

        self.eval_run_fail = EvaluationRun.objects.create(
            tenant_id=self.tenant_id,
            suite_version=self.suite_v,
            candidate_model_version=self.mv2,
            status=EvaluationRun.Status.COMPLETED,
        )
        EvaluationMetric.objects.create(
            tenant_id=self.tenant_id,
            run=self.eval_run_fail,
            key="accuracy",
            value=0.68,  # Below threshold
        )

        self.release = Release.objects.create(
            tenant_id=self.tenant_id,
            name="Production Chat Release",
        )
        self.endpoint = ServingEndpoint.objects.create(
            tenant_id=self.tenant_id,
            endpoint_key="prod-chat-v1",
            name="Production Chat Serving Endpoint",
        )

    def test_failing_gate_criterion_blocks_promotion(self):
        """TECH-021: Failing evaluation check marks version rejected and blocks endpoint promotion."""
        rv = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=1,
            candidate_ref=str(self.mv2.model_version_id),
            model_version=self.mv2,
        )

        criteria = [
            {"key": "min_accuracy", "required_value": 0.85, "eval_run": self.eval_run_fail},
            {"key": "license_compliance"},
        ]

        passed = evaluate_release_gates(rv, criteria)
        self.assertFalse(passed)
        self.assertEqual(rv.status, ReleaseVersion.Status.REJECTED)

        # Attempting promotion fails closed
        with self.assertRaises(ReleasePromotionBlockedError):
            promote_endpoint(self.endpoint, rv)

    def test_policy_exception_cannot_waive_runtime_evidence(self):
        """PRD Scenario 10 / TECH-021: Record a permitted exception, waiving failure and enabling promotion."""
        rv = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=2,
            candidate_ref=str(self.mv2.model_version_id),
            model_version=self.mv2,
        )
        criteria = [{"key": "min_accuracy", "required_value": 0.85, "eval_run": self.eval_run_fail}]
        evaluate_release_gates(rv, criteria)
        self.assertEqual(rv.status, ReleaseVersion.Status.REJECTED)

        gate_res = rv.gate_results.get(criterion_key="min_accuracy")
        self.assertFalse(gate_res.passed)

        # Record audited exception
        exc = record_policy_exception(
            gate_result=gate_res,
            actor_id="ml-platform-lead",
            permitted_policy_id="emergency-minor-regression-policy-2026",
            reason="Approved hotfix with temporary accuracy waiver during upstream incident.",
        )
        self.assertTrue(exc.is_valid)

        # Release version now qualifies under exception
        rv.refresh_from_db()
        self.assertEqual(rv.status, ReleaseVersion.Status.REJECTED)

        # Can now promote endpoint
        with self.assertRaises(ReleasePromotionBlockedError):
            promote_endpoint(self.endpoint, rv)
        dep = promote_endpoint(self.endpoint, rv, simulation=True)
        self.assertEqual(dep.readiness_state, DeploymentRevision.ReadinessState.PENDING)
        self.assertEqual(self.endpoint.active_deployment, dep)

    def test_export_complete_candidate_and_tombstone_fail_closed(self):
        """PRD Scenario 10 & TECH-024: Export complete candidate bundle and fail closed on tombstoned assets."""
        rv = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=3,
            candidate_ref=str(self.mv1.model_version_id),
            model_version=self.mv1,
            status=ReleaseVersion.Status.QUALIFIED,
        )

        # 1. Clean export
        bundle = export_release_bundle(rv)
        self.assertEqual(bundle["release_name"], "Production Chat Release")
        self.assertFalse(bundle["independent_loading_evidence"]["load_tested"])
        self.assertIsNone(bundle["model_card"]["hashes"]["weights_sha256"])
        self.assertEqual(bundle["model_card"]["license"], "apache-2.0")

        # 2. Base model is tombstoned -> Export fails closed
        DeletionTombstone.objects.create(
            tenant_id=self.tenant_id,
            resource_type="model_version",
            resource_id=str(self.mv1.model_version_id),
            reason="Compliance revocation",
        )
        with self.assertRaises(TombstoneAccessDeniedError):
            export_release_bundle(rv)

    def test_quantization_evaluation(self):
        """PRD Scenario 10: Supported quantization evaluation, size reduction, and post-conversion score."""
        rv = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=4,
            candidate_ref=str(self.mv1.model_version_id),
            model_version=self.mv1,
            status=ReleaseVersion.Status.QUALIFIED,
        )

        spec = quantize_and_evaluate(
            rv, quantization_type="int8", baseline_accuracy=0.92, allowed_accuracy_drop=0.03
        )

        self.assertEqual(spec["quantization_type"], "int8")
        self.assertEqual(spec["compression_ratio"], 0.5)
        self.assertFalse(spec["evaluation_passed"])
        self.assertTrue(spec["simulated_evaluation_passed"])
        self.assertEqual(spec["execution_evidence"]["level"], "simulation")
        self.assertLessEqual(spec["accuracy_drop"], 0.03)

    def test_endpoint_promotion_and_rollback(self):
        """Fixture-only pointer promotion and rollback never mark serving ready."""
        rv1 = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=5,
            candidate_ref=str(self.mv1.model_version_id),
            model_version=self.mv1,
            status=ReleaseVersion.Status.QUALIFIED,
        )
        rv2 = ReleaseVersion.objects.create(
            tenant_id=self.tenant_id,
            release=self.release,
            revision_no=6,
            candidate_ref=str(self.mv2.model_version_id),
            model_version=self.mv2,
            status=ReleaseVersion.Status.QUALIFIED,
        )

        # Step 1: Promote rv1
        dep1 = promote_endpoint(self.endpoint, rv1, simulation=True)
        self.assertEqual(self.endpoint.active_deployment, dep1)

        # Step 2: Promote rv2
        dep2 = promote_endpoint(self.endpoint, rv2, simulation=True)
        self.assertEqual(self.endpoint.active_deployment, dep2)
        self.assertEqual(dep2.previous_deployment, dep1)

        # Step 3: Rollback to dep1
        rolled_back_dep = rollback_endpoint(self.endpoint)
        self.assertEqual(rolled_back_dep, dep1)
        self.assertEqual(self.endpoint.active_deployment, dep1)
        dep2.refresh_from_db()
        self.assertEqual(dep2.readiness_state, DeploymentRevision.ReadinessState.ROLLED_BACK)
