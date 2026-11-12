"""Direct status checks for gate_status."""
from django.test import SimpleTestCase

from modelanvil.core.evaluation_gate import gate_status


def _report(**changes):
    report = {
        'candidate_accuracy': 0.9,
        'baseline_accuracy': 0.8,
        'decisive': True,
        'production_qualified': False,
    }
    report.update(changes)
    return report


class EvaluationGateTests(SimpleTestCase):
    def test_non_dict_returns_2(self):
        for report in (None, [], 'report', 0, 0.9, True):
            with self.subTest(report=report):
                self.assertEqual(gate_status(report), 2)

    def test_missing_numeric_accuracies_return_2(self):
        missing_candidate = _report()
        del missing_candidate['candidate_accuracy']
        missing_baseline = _report()
        del missing_baseline['baseline_accuracy']
        for report in (
            missing_candidate,
            missing_baseline,
            _report(candidate_accuracy=None),
            _report(baseline_accuracy=None),
            _report(candidate_accuracy='0.9'),
            _report(baseline_accuracy='0.8'),
            _report(candidate_accuracy=True),
            _report(baseline_accuracy=False),
            {},
        ):
            with self.subTest(report=report):
                self.assertEqual(gate_status(report), 2)

    def test_negative_max_regression_returns_2(self):
        report = _report()
        before = dict(report)
        for max_regression in (-0.01, -1, -0.1):
            with self.subTest(max_regression=max_regression):
                self.assertEqual(gate_status(report, max_regression=max_regression), 2)
        self.assertEqual(report, before)
        self.assertEqual(gate_status(report, max_regression='-0.01'), 2)
        self.assertEqual(gate_status(report, max_regression=None), 2)

    def test_flag_true_or_omitted_returns_2(self):
        omitted = _report()
        del omitted['production_qualified']
        for report in (
            _report(production_qualified=True),
            omitted,
            _report(production_qualified=None),
            _report(production_qualified=0),
            _report(production_qualified=1),
            _report(production_qualified='false'),
        ):
            with self.subTest(flag=report.get('production_qualified', '<omitted>')):
                before = dict(report)
                self.assertEqual(gate_status(report), 2)
                self.assertNotEqual(gate_status(report), 0)
                self.assertEqual(report, before)

    def test_true_flag_stays_2_when_the_numbers_would_otherwise_miss(self):
        report = _report(candidate_accuracy=0.1, production_qualified=True, decisive=False)
        self.assertEqual(gate_status(report), 2)
        self.assertNotEqual(gate_status(report), 0)

    def test_missed_regression_returns_1(self):
        report = _report(candidate_accuracy=0.5, baseline_accuracy=0.75)
        before = dict(report)
        self.assertEqual(gate_status(report, max_regression=0.125), 1)
        self.assertEqual(gate_status(report, max_regression=0), 1)
        self.assertEqual(gate_status(report, max_regression=0.0), 1)
        self.assertEqual(gate_status(_report(candidate_accuracy=1, baseline_accuracy=2), max_regression=0), 1)
        self.assertEqual(report, before)
        self.assertIs(report['production_qualified'], False)

    def test_regression_at_the_allowance_returns_0(self):
        report = _report(candidate_accuracy=0.5, baseline_accuracy=0.75)
        self.assertEqual(gate_status(report, max_regression=0.25), 0)
        self.assertEqual(gate_status(_report(candidate_accuracy=7, baseline_accuracy=8), max_regression=1), 0)
        self.assertIs(report['production_qualified'], False)

    def test_indecisive_report_returns_1_when_required_and_can_pass_when_not(self):
        passing = _report()
        omitted = _report()
        del omitted['decisive']
        for report in (
            _report(decisive=False),
            _report(decisive=None),
            _report(decisive='true'),
            _report(decisive=1),
            omitted,
        ):
            with self.subTest(decisive=report.get('decisive', '<omitted>')):
                before = dict(report)
                self.assertEqual(gate_status(report, require_decisive=True), 1)
                self.assertEqual(gate_status(report, require_decisive=False), 0)
                self.assertEqual(report, before)
                self.assertIs(report.get('production_qualified'), False)
        missed = _report(candidate_accuracy=0.5, decisive=False)
        self.assertEqual(gate_status(missed, require_decisive=True), 1)
        self.assertEqual(gate_status(missed, require_decisive=False), 1)
        self.assertEqual(gate_status(passing), 0)

    def test_passing_report_returns_0_and_does_not_set_the_flag(self):
        report = _report()
        before = dict(report)
        self.assertEqual(gate_status(report), 0)
        self.assertEqual(gate_status(report, max_regression=0.0, require_decisive=True), 0)
        self.assertEqual(report, before)
        self.assertIs(report['production_qualified'], False)
        self.assertEqual(before['production_qualified'], False)
