from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from modelanvil.runners.training import test_cpu_runtime as cpu
from modelanvil.identity.models import ApiKey, Role, Team, Project
from modelanvil.jobs.models import Job, claim_job
from modelanvil.jobs.executor import execute_claim
from modelanvil.runners.training.executor import training_worker_executor
from modelanvil.budgets.models import UsageEvent, BudgetReservation
from modelanvil.core.models import AuditEvent, record_audit


class OperationsP1Tests(TestCase):
    setUp = cpu.CpuRuntimeTests.setUp
    artifact = cpu.CpuRuntimeTests.artifact
    envelope = cpu.CpuRuntimeTests.envelope
    payload = cpu.CpuRuntimeTests.payload
    launch = cpu.CpuRuntimeTests.launch

    def admin(self):
        key = ApiKey.objects.get(tenant=self.tenant); key.role = Role.ADMIN; key.save()

    def test_drain_acknowledges_claim_loop_and_preserves_active_execution_and_slots(self):
        self.admin(); self.worker.slots = 3; self.worker.last_heartbeat_at = timezone.now(); self.worker.save()
        run = self.launch(); descriptor = claim_job(self.worker)
        response = self.client.post(f'/api/v1/worker-inventory/{self.worker.pk}/drain/', {'draining':True}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['capacity']['configured_slots'], 3)
        self.assertEqual(response.data['capacity']['allocated_slots'], 1)
        self.assertIsNone(response.data['capacity']['free_slots'])
        self.assertIsNone(claim_job(self.worker)); self.worker.refresh_from_db(); self.assertIsNotNone(self.worker.drain_acknowledged_at)
        pool = self.client.post(f'/api/v1/worker-pools/{self.pool.pk}/drain/', {'draining':True}, format='json')
        self.assertEqual(pool.status_code, 200, pool.data)
        self.assertEqual(self.client.post(f'/api/v1/worker-pools/{self.pool.pk}/result-policy/', {'result_egress':'metadata_only'}, format='json').status_code, 400)
        result = execute_claim(self.worker, descriptor, training_worker_executor)
        self.assertTrue(result['committed'], result); self.assertEqual(result['status'], 'succeeded')
        run.refresh_from_db(); self.assertEqual(run.status, 'completed')
        self.worker.refresh_from_db(); self.assertEqual(self.worker.slots, 3)
        self.assertTrue(self.worker.drain_requested); self.assertIsNone(claim_job(self.worker))

    def test_missing_capabilities_and_stale_workers_have_explicit_queue_reasons(self):
        Job.objects.create(tenant_id=self.tenant.pk, pool=self.pool, name='Unmatched', requirements={'different_runtime':True})
        response = self.client.get('/api/v1/worker-inventory/queue-diagnosis/')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('No registered worker matches', response.data['rows'][0]['reason'])
        worker = self.client.get(f'/api/v1/worker-inventory/{self.worker.pk}/').data
        self.assertIsNone(worker['capacity']['free_slots'])
        self.assertEqual(self.client.post(f'/api/v1/worker-inventory/{self.worker.pk}/drain/', {}, format='json').status_code, 403)

    def test_filtered_ledger_summary_rows_and_export_reconcile_without_combining_units(self):
        UsageEvent.record(tenant_id=self.tenant.pk, provider_event_key='step-1', quantity=2, unit='training_steps')
        UsageEvent.record(tenant_id=self.tenant.pk, provider_event_key='case-1', quantity=3, unit='evaluation_cases')
        query = '?scope=tenant&unit=training_steps'
        summary = self.client.get('/api/v1/usage-events/summary/'+query)
        self.assertEqual(summary.status_code, 200, summary.data)
        self.assertEqual(summary.data['usage_by_unit'][0]['total_quantity'], '2.000000')
        self.assertEqual(len(summary.data['usage_by_unit']), 1)
        exported = self.client.get('/api/v1/usage-events/export/'+query)
        self.assertTrue(exported.data['complete']); self.assertEqual(exported.data['event_count'], 1)
        self.assertEqual(exported.data['events'][0]['quantity'], '2.000000')
        invalid = self.client.get('/api/v1/usage-events/summary/?date_from=2026-10-12&date_to=2026-10-01')
        self.assertEqual(invalid.status_code, 400)

    def test_audit_filters_search_beyond_first_page_and_export_snapshot_excludes_new_events(self):
        for i in range(505):
            AuditEvent.all_objects.create(tenant_id=self.tenant.pk, action='create' if i else 'training.resume', resource_type='training_run')
        filtered = self.client.get('/api/v1/audit/?scope=tenant&action=training.resume')
        self.assertEqual(filtered.status_code, 200, filtered.data); self.assertEqual(len(filtered.data['results']), 1)
        first = self.client.get('/api/v1/audit/export/?scope=tenant')
        self.assertEqual(len(first.data['results']), 500); self.assertFalse(first.data['metadata']['complete'])
        AuditEvent.all_objects.create(tenant_id=self.tenant.pk, action='new.after.snapshot', resource_type='training_run')
        second = self.client.get('/api/v1/audit/export/', {'cursor':first.data['next_cursor']})
        self.assertEqual(len(second.data['results']), 5); self.assertTrue(second.data['metadata']['complete'])
        self.assertEqual(second.data['metadata']['exported_count'], 505)
        self.assertEqual(self.client.get('/api/v1/audit/export/?cursor=invalid').status_code, 400)

    def test_audit_project_scope_and_historical_access_loss_are_explicit(self):
        team = Team.objects.create(tenant_id=self.tenant.pk, name='Team', slug='team')
        a = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='A', slug='a')
        b = Project.objects.create(tenant_id=self.tenant.pk, team=team, name='B', slug='b')
        self.base.project = b; self.base.save()
        event = AuditEvent.all_objects.create(tenant_id=self.tenant.pk, project_id=a.pk, action='create', resource_type='model_version', resource_id=self.base.model_version_id)
        state = self.client.get(f'/api/v1/audit/{event.event_id}/resource-state/', HTTP_X_PROJECT_ID=str(a.pk))
        self.assertEqual(state.status_code, 200, state.data); self.assertEqual(state.data['state'], 'access_lost')
        self.assertEqual(self.client.get(f'/api/v1/audit/{event.event_id}/', HTTP_X_PROJECT_ID=str(b.pk)).status_code, 404)
