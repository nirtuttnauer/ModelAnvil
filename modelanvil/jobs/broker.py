"""RabbitMQ dispatch consumer with durable claim-before-ack semantics."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import pika
from pika.exceptions import ConnectionWrongStateError
from django.db import connections
from modelanvil.jobs.executor import ExecutionContext, Executor, execute_claim
from modelanvil.jobs.models import Job, Worker, claim_job, dispatch_topic

logger = logging.getLogger(__name__)


class WorkerBrokerConsumer:
    """Consume pool notifications and execute only durably claimed jobs.

    Incompatible or temporarily unclaimable queued work is sent to a delayed
    retry queue so another worker can receive it without a hot requeue loop.
    The database remains authoritative; duplicate/stale notifications are acked.
    """

    def __init__(
        self,
        worker: Worker,
        queue_name: str,
        executor: Executor,
        *,
        concurrency: int = 1,
        retry_delay_ms: int = 5000,
    ):
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if retry_delay_ms < 1:
            raise ValueError("retry_delay_ms must be positive")
        expected_queue = dispatch_topic(worker.tenant_id, worker.pool.queue_name, worker.pool.name)
        if queue_name != expected_queue:
            raise ValueError("queue_name does not match the worker's tenant and pool")
        self.worker = worker
        self.queue_name = queue_name
        self.executor = executor
        self.concurrency = concurrency
        self.retry_delay_ms = retry_delay_ms
        self.retry_queue = f"{queue_name}.retry"
        self.quarantine_queue = f"{queue_name}.quarantine"
        self._pool = ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="modelanvil-worker")
        self._condition = threading.Condition()
        self._active = 0
        self._ready = threading.Event()
        self._connection = None
        self._channel = None

    def configure_channel(self, channel) -> None:
        """Declare durable dispatch, delayed retry, and quarantine queues."""
        channel.queue_declare(queue=self.queue_name, durable=True)
        channel.queue_declare(
            queue=self.retry_queue,
            durable=True,
            arguments={
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.queue_name,
            },
        )
        channel.queue_declare(queue=self.quarantine_queue, durable=True)
        channel.basic_qos(prefetch_count=max(1, self.concurrency))

    def on_message(self, channel, method, properties, body: bytes) -> None:
        """Validate a notification, claim its job, ack, then execute async."""
        message = self._parse_message(body)
        if message is None:
            self._quarantine_and_ack(channel, method.delivery_tag, body, "invalid_json")
            return
        if (
            message.get("tenant_id") != str(self.worker.tenant_id)
            or message.get("topic") != self.queue_name
            or not isinstance(message.get("payload"), dict)
            or message["payload"].get("event_type") != "job.queued"
        ):
            self._quarantine_and_ack(channel, method.delivery_tag, body, "invalid_scope_or_event")
            return
        try:
            job_id = uuid.UUID(str(message["payload"].get("job_id", "")))
        except (ValueError, TypeError, AttributeError):
            self._quarantine_and_ack(channel, method.delivery_tag, body, "invalid_job_id")
            return

        job = Job.all_objects.filter(
            job_id=job_id,
            tenant_id=self.worker.tenant_id,
            pool_id=self.worker.pool_id,
        ).first()
        if job is None or job.status != Job.Status.QUEUED:
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        if not self._reserve_slot():
            self._delay_and_ack(channel, method.delivery_tag, body, message.get("event_id"))
            return
        descriptor = claim_job(self.worker, job)
        if descriptor is None:
            self._release_slot()
            job.refresh_from_db()
            if job.status == Job.Status.QUEUED:
                self._delay_and_ack(channel, method.delivery_tag, body, message.get("event_id"))
            else:
                channel.basic_ack(delivery_tag=method.delivery_tag)
            return

        # claim_job committed the attempt and slot reservation; execution must
        # not hold a broker delivery open for the duration of the task.
        channel.basic_ack(delivery_tag=method.delivery_tag)
        try:
            future = self._pool.submit(self._execute_claim, descriptor)
        except Exception:
            self._release_slot()
            logger.exception("could not start executor after durable claim")
            return
        future.add_done_callback(self._on_execution_done)

    def _execute_claim(self, descriptor: dict[str, Any]) -> dict[str, Any]:
        try:
            return execute_claim(self.worker, descriptor, self.executor)
        finally:
            # Django connections are thread-local; close the executor thread's
            # connection so the worker pool does not pin stale DB sessions.
            connections.close_all()

    @staticmethod
    def _parse_message(body: bytes) -> dict[str, Any] | None:
        try:
            message = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return None
        return message if isinstance(message, dict) else None

    def _reserve_slot(self) -> bool:
        with self._condition:
            if self._active >= self.concurrency:
                return False
            self._active += 1
            return True

    def _release_slot(self) -> None:
        with self._condition:
            self._active -= 1
            self._condition.notify_all()

    def _on_execution_done(self, future: Future) -> None:
        try:
            error = future.exception()
            if error is not None:
                logger.error(
                    "executor infrastructure failure",
                    exc_info=(type(error), error, error.__traceback__),
                )
        finally:
            self._release_slot()

    def _publish_confirmed(self, channel, queue: str, body: bytes, event_id: str | None, reason: str):
        confirmed = channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=body,
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
                message_id=event_id,
                headers={"retry_reason": reason},
            ),
            mandatory=True,
        )
        if confirmed is False:
            raise RuntimeError(f"RabbitMQ did not confirm routing to {queue}")

    def _delay_and_ack(self, channel, delivery_tag: int, body: bytes, event_id: str | None) -> None:
        self._publish_confirmed(channel, self.retry_queue, body, event_id, "not_claimable_yet")
        channel.basic_ack(delivery_tag=delivery_tag)

    def _quarantine_and_ack(self, channel, delivery_tag: int, body: bytes, reason: str) -> None:
        self._publish_confirmed(channel, self.quarantine_queue, body, None, reason)
        channel.basic_ack(delivery_tag=delivery_tag)

    def wait_for_idle(self, timeout: float = 30.0) -> bool:
        """Wait for submitted executors to finish; useful for controlled tests."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
        return True

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Wait until queues are declared and the consumer is registered."""
        return self._ready.wait(timeout)

    def stop(self) -> None:
        """Request a thread-safe graceful stop of the Pika consume loop."""
        connection = self._connection
        channel = self._channel
        if connection is None or channel is None or not connection.is_open:
            return
        try:
            connection.add_callback_threadsafe(channel.stop_consuming)
        except ConnectionWrongStateError:
            # The consume loop is already unwinding or its connection closed.
            return

    def run(self, rabbitmq_url: str | None = None) -> None:
        """Connect, declare topology, and consume with manual acknowledgements."""
        url = rabbitmq_url or os.environ.get("RABBITMQ_URL")
        if not url:
            raise ValueError("RABBITMQ_URL is required for broker consumption")
        connection = pika.BlockingConnection(pika.URLParameters(url))
        channel = connection.channel()
        self._connection = connection
        self._channel = channel
        try:
            channel.confirm_delivery()
            self.configure_channel(channel)
            channel.basic_consume(
                queue=self.queue_name,
                on_message_callback=self.on_message,
                auto_ack=False,
            )
            self._ready.set()
            channel.start_consuming()
        except KeyboardInterrupt:
            if channel.is_open:
                channel.stop_consuming()
        finally:
            self._ready.clear()
            self._channel = None
            self._connection = None
            self._pool.shutdown(wait=True, cancel_futures=False)
            if connection.is_open:
                connection.close()
            # The Pika callback thread also performs claims and needs its
            # thread-local Django connection released when consumption stops.
            connections.close_all()
