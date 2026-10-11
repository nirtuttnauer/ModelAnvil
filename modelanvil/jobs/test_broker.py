"""Broker notification delivery into durable worker claims."""
import importlib
import importlib.util
import json
import os
import threading
import uuid
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.test import TransactionTestCase
import pika

from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerPool, dispatch_topic


def noop_executor(_descriptor, _context):
    return None


class FakeChannel:
    def __init__(self):
        self.acks = []
        self.published = []
        self.actions = []

    def basic_ack(self, delivery_tag):
        self.acks.append(delivery_tag)
        self.actions.append(("ack", delivery_tag))

    def basic_publish(self, **kwargs):
        self.published.append(kwargs)
        self.actions.append(("publish", kwargs["routing_key"]))
        return True


class BrokerConsumerTests(TransactionTestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="broker-consumer", name="Broker Consumer")
        self.pool = WorkerPool.objects.create(tenant_id=self.tenant.tenant_id, name="cpu")
        self.worker = Worker.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="broker-worker",
            slots=1,
            capabilities={"accelerator": "cpu"},
        )
        self.job = Job.objects.create(
            tenant_id=self.tenant.tenant_id,
            pool=self.pool,
            name="broker task",
            payload={"value": 9},
            requirements={"accelerator": "cpu"},
        )
        self.queue = dispatch_topic(self.tenant.tenant_id, self.pool.queue_name, self.pool.name)

    def test_consumer_claims_before_ack_and_executes_after_ack(self):
        spec = importlib.util.find_spec("modelanvil.jobs.broker")
        self.assertIsNotNone(spec, "RabbitMQ worker consumer is missing")
        consumer_class = importlib.import_module("modelanvil.jobs.broker").WorkerBrokerConsumer
        channel = FakeChannel()
        observed_ack = []
        envelope = {
            "schema_version": "1.0",
            "sample_id": str(uuid.uuid4()),
            "source_group_id": "broker-fixture",
            "blocks": [{"block_id": "b1", "type": "text", "text": "done"}],
            "provenance": {
                "source_snapshot_ref": "fixture-snapshot",
                "source_record_key": "fixture-record",
                "content_sha256": "0" * 64,
            },
        }

        def executor(descriptor, context):
            observed_ack.append(list(channel.acks))
            context.heartbeat(progress=0.5)
            return envelope

        consumer = consumer_class(self.worker, self.queue, executor)
        message = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": str(self.tenant.tenant_id),
            "topic": self.queue,
            "payload": {"event_type": "job.queued", "job_id": str(self.job.job_id)},
        }
        consumer.on_message(
            channel,
            SimpleNamespace(delivery_tag=17),
            None,
            json.dumps(message).encode("utf-8"),
        )
        consumer.wait_for_idle(timeout=5)

        self.job.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertEqual(channel.acks, [17])
        self.assertEqual(observed_ack, [[17]])
        self.assertEqual(self.job.status, Job.Status.SUCCEEDED)
        self.assertEqual(self.worker.slots, 1)
        self.assertEqual(JobAttempt.objects.filter(job=self.job).count(), 1)

    def test_incompatible_queued_job_is_delayed_for_another_worker(self):
        self.job.requirements = {"accelerator": "gpu"}
        self.job.save(update_fields=("requirements", "updated_at"))
        consumer_class = importlib.import_module("modelanvil.jobs.broker").WorkerBrokerConsumer
        channel = FakeChannel()
        consumer = consumer_class(self.worker, self.queue, lambda _descriptor, _context: None)
        message = {
            "event_id": str(uuid.uuid4()),
            "tenant_id": str(self.tenant.tenant_id),
            "topic": self.queue,
            "payload": {"event_type": "job.queued", "job_id": str(self.job.job_id)},
        }

        consumer.on_message(
            channel,
            SimpleNamespace(delivery_tag=18),
            None,
            json.dumps(message).encode("utf-8"),
        )

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, Job.Status.QUEUED)
        self.assertEqual(channel.actions, [("publish", f"{self.queue}.retry"), ("ack", 18)])

    def test_consume_worker_command_starts_broker_consumer(self):
        with patch("modelanvil.jobs.broker.WorkerBrokerConsumer.run") as run:
            call_command(
                "consume_worker",
                worker_id=self.worker.pk,
                executor="modelanvil.jobs.test_broker.noop_executor",
            )

        run.assert_called_once_with()


@skipUnless(os.environ.get("RABBITMQ_URL"), "requires a live RabbitMQ service")
class RabbitMQLoopIntegrationTests(TransactionTestCase):
    def test_consumer_loop_executes_a_dispatch_and_stops_cleanly(self):
        from modelanvil.jobs.broker import WorkerBrokerConsumer

        tenant = Tenant.objects.create(
            slug="broker-loop-" + uuid.uuid4().hex[:12],
            name="Broker loop integration",
        )
        pool = WorkerPool.objects.create(tenant_id=tenant.tenant_id, name="cpu")
        worker = Worker.objects.create(
            tenant_id=tenant.tenant_id,
            pool=pool,
            name="broker-loop-worker",
            slots=1,
            capabilities={"accelerator": "cpu"},
        )
        job = Job.objects.create(
            tenant_id=tenant.tenant_id,
            pool=pool,
            name="broker loop task",
            payload={"value": 9},
            requirements={"accelerator": "cpu"},
        )
        queue = dispatch_topic(tenant.tenant_id, pool.queue_name, pool.name)
        executed = threading.Event()
        failures = []

        def executor(_descriptor, _context):
            executed.set()
            return None

        consumer = WorkerBrokerConsumer(worker, queue, executor)
        ready_wait = getattr(consumer, "wait_until_ready", None)
        stop = getattr(consumer, "stop", None)
        if not callable(ready_wait):
            self.fail("consumer needs a readiness signal for integration use")
        if not callable(stop):
            self.fail("consumer needs a thread-safe stop operation")

        def run_consumer():
            try:
                consumer.run()
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=run_consumer, daemon=True)
        thread.start()
        connection = None
        channel = None
        try:
            self.assertTrue(ready_wait(timeout=10), "consumer did not enter its consume loop")
            connection = pika.BlockingConnection(pika.URLParameters(os.environ["RABBITMQ_URL"]))
            channel = connection.channel()
            channel.confirm_delivery()
            message = {
                "event_id": str(uuid.uuid4()),
                "tenant_id": str(tenant.tenant_id),
                "topic": queue,
                "payload": {"event_type": "job.queued", "job_id": str(job.job_id)},
            }
            confirmed = channel.basic_publish(
                exchange="",
                routing_key=queue,
                body=json.dumps(message).encode("utf-8"),
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                mandatory=True,
            )
            self.assertNotEqual(confirmed, False)
            self.assertTrue(executed.wait(10), "consumer did not run the executor")
            self.assertTrue(consumer.wait_for_idle(timeout=10))
            job.refresh_from_db()
            self.assertEqual(job.status, Job.Status.SUCCEEDED)
            self.assertEqual(JobAttempt.objects.filter(job=job).count(), 1)
        finally:
            stop()
            thread.join(timeout=10)
            if channel is not None and channel.is_open:
                for queue_to_delete in (queue, consumer.retry_queue, consumer.quarantine_queue):
                    channel.queue_delete(queue=queue_to_delete)
            if connection is not None and connection.is_open:
                connection.close()
        self.assertFalse(thread.is_alive(), "consumer did not stop")
        self.assertEqual(failures, [])
