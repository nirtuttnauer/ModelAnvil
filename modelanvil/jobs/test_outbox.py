"""Transactional outbox delivery behavior."""
from django.test import TestCase

import modelanvil.jobs.models as jobs_models
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, WorkerPool


class OutboxDeliveryTests(TestCase):
    def test_delivery_requires_broker_confirmation_before_publishing_record(self):
        self.assertTrue(hasattr(jobs_models, "publish_outbox_batch"))
        tenant = Tenant.objects.create(slug="outbox-test", name="Outbox Test")
        event = jobs_models.OutboxEvent.objects.create(
            tenant_id=tenant.tenant_id, topic="jobs.cpu", payload={"job_id": "j-1"}
        )
        sent = []
        count = jobs_models.publish_outbox_batch(lambda message: sent.append(message) or True, limit=10)
        event.refresh_from_db()
        self.assertEqual(count, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["event_id"], str(event.event_id))
        self.assertIsNotNone(event.published_at)
        self.assertEqual(event.attempts, 1)
        self.assertEqual(jobs_models.publish_outbox_batch(lambda _message: self.fail("published event replayed")), 0)

    def test_failed_delivery_remains_pending_and_records_error(self):
        self.assertTrue(hasattr(jobs_models, "publish_outbox_batch"))
        tenant = Tenant.objects.create(slug="outbox-fail", name="Outbox Fail")
        event = jobs_models.OutboxEvent.objects.create(
            tenant_id=tenant.tenant_id, topic="jobs.cpu", payload={"job_id": "j-2"}
        )
        def fail(_message):
            raise ConnectionError("broker unavailable")
        count = jobs_models.publish_outbox_batch(fail, limit=10)
        event.refresh_from_db()
        self.assertEqual(count, 0)
        self.assertIsNone(event.published_at)
        self.assertEqual(event.attempts, 1)
        self.assertIn("broker unavailable", event.last_error)

    def test_job_notifications_use_tenant_scoped_pool_queues(self):
        first = Tenant.objects.create(slug="queue-tenant-one", name="Queue Tenant One")
        second = Tenant.objects.create(slug="queue-tenant-two", name="Queue Tenant Two")
        first_pool = WorkerPool.objects.create(tenant_id=first.tenant_id, name="cpu")
        second_pool = WorkerPool.objects.create(tenant_id=second.tenant_id, name="cpu")
        first_job = Job.objects.create(tenant_id=first.tenant_id, pool=first_pool, name="one")
        second_job = Job.objects.create(tenant_id=second.tenant_id, pool=second_pool, name="two")

        first_event = jobs_models.OutboxEvent.objects.get(payload__job_id=str(first_job.job_id))
        second_event = jobs_models.OutboxEvent.objects.get(payload__job_id=str(second_job.job_id))

        self.assertEqual(first_event.topic, f"tenant.{first.tenant_id}.cpu")
        self.assertEqual(second_event.topic, f"tenant.{second.tenant_id}.cpu")
        self.assertNotEqual(first_event.topic, second_event.topic)
