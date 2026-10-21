"""Trust regressions: fixture metrics and metadata cannot become runtime evidence."""
import base64
import math
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from modelanvil.runners.training.engine import CausalTextModel, TrainingEngine, pack_safetensors
from modelanvil.runners.evidence import evaluation_evidence
from modelanvil.runners.eval_executor import run_baseline_evaluation
from modelanvil.runners.models import Model, ModelVersion, EvaluationSuite, EvaluationSuiteVersion, TokenizerVersion
from modelanvil.identity.models import Tenant
from modelanvil.releases.models import Release, ReleaseVersion, ServingEndpoint
from modelanvil.releases.lifecycle import evaluate_release_gates, record_policy_exception, promote_endpoint, ReleasePromotionBlockedError


class ExportEvidenceTests(SimpleTestCase):
    def bundle(self):
        raw, manifest = pack_safetensors(CausalTextModel(10, 4, 2).export_tensors())
        return {"model.safetensors.b64": base64.b64encode(raw).decode(), "weights_manifest.json": manifest,
                "config.json": {"vocab_size": 10, "n_embd": 4, "lora_r": 2}}

    def test_metadata_or_missing_weights_cannot_claim_loadability(self):
        with self.assertRaises(ValueError):
            TrainingEngine.verify_external_loadable({"config.json": {"vocab_size": 10}})
        bundle = self.bundle()
        del bundle["weights_manifest.json"]
        with self.assertRaises(ValueError):
            TrainingEngine.verify_external_loadable(bundle)

    def test_verified_export_requires_actual_forward_and_scopes_the_claim(self):
        with patch.object(CausalTextModel, "forward", autospec=True, side_effect=CausalTextModel.forward) as forward:
            result = TrainingEngine.verify_external_loadable(self.bundle())
        self.assertEqual(forward.call_count, 1)
        self.assertTrue(result["model_instantiated"])
        self.assertEqual(result["inference_steps"], 1)
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["independent_runtime_verified"])

    def test_corrupt_incomplete_wrong_shape_and_nonfinite_weights_rejected(self):
        for mutate in ("corrupt", "missing", "wrong_shape", "nan"):
            with self.subTest(mutate=mutate):
                tensors = CausalTextModel(10, 4, 2).export_tensors()
                if mutate == "missing": del tensors["lm_head.weight"]
                if mutate == "wrong_shape": tensors["lm_head.weight"] = ([5, 8], tensors["lm_head.weight"][1])
                if mutate == "nan": tensors["lm_head.weight"][1][0] = math.nan
                raw, manifest = pack_safetensors(tensors)
                bundle = self.bundle()
                if mutate == "corrupt": raw += b"changed"
                bundle.update({"model.safetensors.b64": base64.b64encode(raw).decode(), "weights_manifest.json": manifest})
                with self.assertRaises(ValueError): TrainingEngine.verify_external_loadable(bundle)

    def test_inference_limits_are_enforced(self):
        for count in (-1, 0, 33, True):
            with self.assertRaises(ValueError):
                TrainingEngine.generate_candidate_completion(self.bundle(), "hello", count)


class FixtureQualificationTests(TestCase):
    def setUp(self):
        tenant = Tenant.objects.create(slug="evidence", name="Evidence")
        self.tenant = tenant.tenant_id
        model = Model.objects.create(tenant_id=self.tenant, name="metadata")
        tokenizer = TokenizerVersion.objects.create(tenant_id=self.tenant, name="fixture", vocabulary_size=10)
        self.mv = ModelVersion.objects.create(tenant_id=self.tenant, model=model, tokenizer=tokenizer, license_evidence="mit",
                                             metadata={"execution_evidence": {"level": "hardware_qualified", "production_qualified": True}})
        suite = EvaluationSuite.objects.create(tenant_id=self.tenant, name="fixture")
        self.suite = EvaluationSuiteVersion.objects.create(tenant_id=self.tenant, suite=suite,
            cases=[{"input": "What?", "expected_output": "answer"}])
        release = Release.objects.create(tenant_id=self.tenant, name="fixture")
        self.rv = ReleaseVersion.objects.create(tenant_id=self.tenant, release=release, model_version=self.mv)

    def test_fallback_and_callback_origins_are_distinguished(self):
        fixture = run_baseline_evaluation(self.suite, self.mv, decoding_params={"execution_evidence": {"level": "hardware_qualified"}})
        self.assertEqual(evaluation_evidence(fixture)["level"], "simulation")
        callback = run_baseline_evaluation(self.suite, self.mv, runner_fn=lambda p, config: "answer")
        self.assertEqual(evaluation_evidence(callback)["level"], "integrated_execution")
        self.assertFalse(evaluation_evidence(callback)["hardware_qualified"])

    def test_empty_or_simulated_gates_and_waivers_never_qualify(self):
        self.assertFalse(evaluate_release_gates(self.rv, []))
        run = run_baseline_evaluation(self.suite, self.mv)
        self.assertFalse(evaluate_release_gates(self.rv, [{"key": "min_accuracy", "eval_run": run}, {"key": "license_compliance"}]))
        for gate in self.rv.gate_results.filter(passed=False):
            record_policy_exception(gate, "test-actor", "fixture", "Fixture waiver")
        self.rv.refresh_from_db()
        self.assertEqual(self.rv.status, ReleaseVersion.Status.REJECTED)
        self.rv.status = ReleaseVersion.Status.QUALIFIED
        self.rv.save()
        endpoint = ServingEndpoint.objects.create(tenant_id=self.tenant, endpoint_key="fixture", name="fixture")
        with self.assertRaises(ReleasePromotionBlockedError): promote_endpoint(endpoint, self.rv)

    def test_legacy_labels_remain_recorded_but_do_not_surface_as_verified(self):
        from modelanvil.api.views.models_evals import ModelVersionSerializer
        from modelanvil.api.views.release_views import ReleaseVersionSerializer, DeploymentRevisionSerializer
        from modelanvil.releases.models import DeploymentRevision
        self.mv.state = ModelVersion.State.QUALIFIED
        self.mv.save()
        model_data = ModelVersionSerializer(self.mv).data
        self.assertEqual(model_data['recorded_state'], 'qualified')
        self.assertEqual(model_data['state'], 'draft')
        self.rv.status = ReleaseVersion.Status.QUALIFIED
        self.rv.save()
        release_data = ReleaseVersionSerializer(self.rv).data
        self.assertEqual(release_data['recorded_status'], 'qualified')
        self.assertEqual(release_data['status'], 'draft')
        endpoint = ServingEndpoint.objects.create(tenant_id=self.tenant, endpoint_key='legacy', name='legacy')
        dep = DeploymentRevision.objects.create(tenant_id=self.tenant, endpoint=endpoint, release_version=self.rv, readiness_state='ready')
        deployment_data = DeploymentRevisionSerializer(dep).data
        self.assertEqual(deployment_data['recorded_readiness_state'], 'ready')
        self.assertEqual(deployment_data['readiness_state'], 'pending')
        self.assertFalse(deployment_data['execution_evidence']['production_qualified'])
