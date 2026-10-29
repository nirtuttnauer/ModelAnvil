"""The CPU character reproduction rule is frozen before its repeat runs."""
import copy
import json
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, SimpleTestCase, override_settings

from modelanvil.runners.cpu_character_eval_envelope import (
    POLICY_ID,
    POLICY_PATH,
    check_run,
    load_policy,
    load_reference,
    measured_spread,
    reference_problems,
)
from modelanvil.runners.cpu_character_eval_repeat import run_once


def _report(score=0.0, output="same", seed=42):
    reference = load_reference()
    return {
        "policy_id": POLICY_ID,
        "contains_measurement": True,
        "protocol": copy.deepcopy(reference["protocol"]),
        "evidence_level": "integrated_execution",
        "candidate_weights_sha256": "a" * 64,
        "baseline_weights_sha256": "b" * 64,
        "cases": [{
            "case_id": "held-out",
            "input_prompt": "zz",
            "expected_output": "not-the-model-output",
            "slice": "held-out",
            "candidate_output": output,
            "baseline_output": "",
            "passed": False,
            "baseline_passed": False,
            "score": score,
            "baseline_score": 0.0,
        }],
        "metrics": [{
            "key": "accuracy", "slice_name": "all", "method": "wilson",
            "value": score, "sample_count": 1, "lower": 0.0, "upper": 0.5,
        }],
        "baseline_metrics": [{
            "key": "accuracy", "slice_name": "all", "method": "wilson",
            "value": 0.0, "sample_count": 1, "lower": 0.0, "upper": 0.5,
        }],
        "wall_seconds": 1.25,
        "hostname": "synthetic",
        "platform": "synthetic",
        "python": "3.12.3",
    }


class EnvelopeRuleTests(SimpleTestCase):
    def test_policy_and_reference_contain_no_measurement(self):
        policy = load_policy()
        reference = load_reference()
        self.assertEqual(reference_problems(policy, reference), [])
        self.assertTrue({"tolerance", "absolute_tolerance", "numeric_tolerance", "tolerances"}.isdisjoint(policy))
        self.assertIs(reference["contains_measurement"], False)
        raw = json.dumps(reference)
        for word in ("candidate_output", "weights_sha256", "accuracy", "spread"):
            self.assertNotIn(word, raw)

    def test_tolerance_is_the_unpadded_spread(self):
        runs = [_report(0.0), _report(0.0), _report(0.1)]
        spread = measured_spread(runs)
        self.assertEqual(spread["exact_disagreements"], [])
        self.assertEqual(spread["tolerances"]["cases[0].score"], 0.1)
        self.assertEqual(spread["tolerances"]["metrics[0].value"], 0.1)

    def test_failure_does_not_change_the_policy(self):
        policy = load_policy()
        reference = load_reference()
        before = POLICY_PATH.read_bytes()
        repeats = [_report(0.0), _report(0.0), _report(0.0)]
        candidate = _report(1.0)
        result = check_run(policy, reference, repeats, candidate)
        self.assertFalse(result["ok"])
        self.assertEqual(result["tolerances"]["cases[0].score"], 0.0)
        self.assertEqual(result["policy_id"], POLICY_ID)
        self.assertNotIn("tolerance", policy)
        self.assertEqual(POLICY_PATH.read_bytes(), before)

    def test_exact_text_is_not_given_a_tolerance(self):
        policy = load_policy()
        reference = load_reference()
        repeats = [_report(output="one"), _report(output="two"), _report(output="one")]
        result = check_run(policy, reference, repeats, _report(output="one"))
        self.assertFalse(result["ok"])
        self.assertIn("not widened", result["failures"][0]["reason"])

    def test_a_stored_tolerance_is_rejected(self):
        policy = load_policy()
        policy["tolerance"] = 1
        self.assertTrue(reference_problems(policy, load_reference()))

    def test_matching_run_passes_at_the_measured_spread(self):
        policy = load_policy()
        reference = load_reference()
        repeats = [_report(0.0), _report(0.0), _report(0.1)]
        self.assertTrue(check_run(policy, reference, repeats, _report(0.1))["ok"])
        self.assertFalse(check_run(policy, reference, repeats, _report(0.2))["ok"])


@override_settings(ALLOWED_HOSTS=["testserver"])
class CpuCharacterEvalRepeatTests(TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory()
        self.addCleanup(storage.cleanup)
        override = override_settings(MODELANVIL={
            **settings.MODELANVIL, "artifact_backend": "filesystem", "artifact_root": storage.name,
        })
        override.enable()
        self.addCleanup(override.disable)

    def test_two_runs_match_on_the_pinned_worker_path(self):
        reference = load_reference()
        first = run_once(reference, name="envelope-a")
        second = run_once(reference, name="envelope-b")
        self.assertEqual(first["evidence_level"], "integrated_execution")
        self.assertEqual(first["protocol"], reference["protocol"])
        self.assertEqual(second["protocol"], reference["protocol"])
        policy = load_policy()
        result = check_run(policy, reference, [first, first, second], second)
        self.assertTrue(result["ok"], result["failures"])
        for field, tolerance in result["tolerances"].items():
            self.assertEqual(tolerance, 0.0, field)
