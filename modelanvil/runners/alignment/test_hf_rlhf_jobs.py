"""CPU stage accounting/fencing control fixtures; numerical qualification is opt-in."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.jobs.models import JobAttempt, commit_result, reconcile_expired_leases
from modelanvil.runners.models import AlignmentStageAttempt
from . import hf_rlhf as runtime
from . import test_mps_dpo_jobs as fixtures


class CPUStageControlsTests(TestCase):
    def setUp(self):
        fixtures.DPOJobControlsTests.setUp(self)
        self.run.algorithm = 'rloo'
        self.job.payload = {'type': 'qualified_rlhf', 'run_id': str(self.run.run_id)}; self.job.save()
        self.reservation.estimated_amount = 9; self.reservation.save()
        reservations = {'training_steps': self.reservation}
        for unit in ('generated_tokens', 'alignment_scores'):
            policy = BudgetPolicy.objects.create(tenant_id=self.tenant.pk, name=unit, period='lifetime', unit=unit, limit_amount=100)
            reservations[unit] = BudgetReservation.reserve(tenant_id=self.tenant.pk, policy=policy, job_id=self.job.job_id, estimated_amount=50)
        self.run.execution_pins = {'runtime': runtime.RUNTIME_ID,
            'reservations': {u: str(r.reservation_id) for u, r in reservations.items()},
            'budget_specs': {u: {'policy_id': str(r.policy.policy_id), 'estimated_amount': int(r.estimated_amount)} for u, r in reservations.items()},
            'hyperparameters': {'rollout_group_size': 2, 'max_new_tokens': 3}, 'evaluation_score_calls': 6}
        self.run.save()

    def claim(self):
        return fixtures.DPOJobControlsTests.claim(self)

    def test_queued_cancel_settles_three_distinct_units_idempotently(self):
        for _ in range(2): runtime.cancel(self.run)
        self.assertEqual(list(BudgetReservation.all_objects.values_list('state', flat=True)), ['settled'] * 3)
        self.assertEqual(UsageEvent.all_objects.count(), 3)
        self.assertEqual(set(UsageEvent.all_objects.values_list('unit', flat=True)), set(runtime.UNITS))
        self.assertTrue(all(row.quantity == 0 for row in UsageEvent.all_objects.all()))

    def test_lost_stage_is_charged_as_unknown_upper_bound_and_stale_commit_refused(self):
        attempt, token = self.claim()
        self.run.status = 'running'; self.run.save()
        receipt = AlignmentStageAttempt.all_objects.create(tenant_id=self.tenant.pk, alignment_run=self.run,
            job_attempt=attempt, sequence=1, phase='rollout', input_digest='a' * 64,
            upper_units={'training_steps': 0, 'generated_tokens': 6, 'alignment_scores': 0})
        JobAttempt.all_objects.filter(pk=attempt.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(reconcile_expired_leases(job_ids=[self.job.job_id]), 1)
        receipt.refresh_from_db(); self.run.refresh_from_db()
        self.assertEqual(receipt.status, 'uncertain'); self.assertIsNone(receipt.actual_units)
        self.assertEqual(runtime.usage(self.run)['uncertain_upper_units']['generated_tokens'], 6)
        self.assertFalse(commit_result(attempt, token, 'succeeded'))
        self.assertEqual(UsageEvent.all_objects.count(), 0)
        runtime.cancel(self.run)
        event = UsageEvent.all_objects.get(unit='generated_tokens')
        self.assertEqual(event.quantity, 6); self.assertEqual(event.detail['measured'], 0)
        self.assertEqual(event.detail['uncertain_upper_bound'], 6)
        self.assertFalse(event.detail['uncertain_is_measurement'])

    def test_worker_success_without_final_durable_state_cannot_publish(self):
        attempt, token = self.claim()
        self.run.status = 'running'; self.run.current_step = self.run.total_steps; self.run.save()
        with patch.object(runtime, '_current_inputs', return_value={}):
            self.assertTrue(commit_result(attempt, token, 'succeeded'))
        self.run.refresh_from_db(); self.job.refresh_from_db()
        self.assertEqual((self.run.status, self.job.status), ('failed', 'failed'))
        self.assertIsNone(self.run.output_model_version_id)
        self.assertEqual(UsageEvent.all_objects.count(), 3)

    def test_budget_change_and_unsupported_hyperparameters_refuse_admission(self):
        self.assertEqual(set(runtime.authorized_budgets(self.run)), set(runtime.UNITS))
        policy = BudgetPolicy.all_objects.get(unit='generated_tokens'); policy.enabled = False; policy.save()
        with self.assertRaisesRegex(ValueError, 'authorized'): runtime.authorized_budgets(self.run)
        for changes in ({'rollout_group_size': 1}, {'max_new_tokens': 9}, {'max_kl_divergence': float('nan')}, {'ppo_epochs': 2}):
            with self.assertRaises(ValueError): runtime.hyperparameters(changes, 'rloo')

    def test_divergence_stop_keeps_measured_work_and_specific_reason(self):
        attempt, token = self.claim()
        self.run.status = 'running'; self.run.save()
        AlignmentStageAttempt.all_objects.create(tenant_id=self.tenant.pk, alignment_run=self.run,
            job_attempt=attempt, sequence=1, phase='policy_update', input_digest='a' * 64,
            upper_units={'training_steps': 1, 'generated_tokens': 0, 'alignment_scores': 0},
            actual_units={'training_steps': 1, 'generated_tokens': 0, 'alignment_scores': 0},
            status='measured_aborted', observations={'stop_reason': 'categorical_kl_stop'})
        self.assertTrue(commit_result(attempt, token, 'succeeded'))
        self.run.refresh_from_db()
        self.assertEqual(self.run.stop_reason, 'categorical_kl_stop')
        self.assertEqual(self.run.latest_metrics['stage_usage']['measured_units']['training_steps'], 1)
        self.assertEqual(self.run.latest_metrics['stage_usage']['uncertain_upper_units']['training_steps'], 0)

    def test_missing_optional_runtime_package_has_actionable_admission_error(self):
        import importlib.metadata
        def version(name):
            if name == 'accelerate': raise importlib.metadata.PackageNotFoundError(name)
            return runtime.CONTRACT['packages'][name]
        with patch.object(runtime.hf, 'require_packages'), patch.object(runtime.hf, 'require_adapter_package'), \
                patch('importlib.metadata.version', side_effect=version):
            with self.assertRaisesRegex(ValueError, 'accelerate==1.15.0'): runtime.environment()
