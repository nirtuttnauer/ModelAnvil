"""Publish transactional job outbox events to durable RabbitMQ queues."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import pika
from django.core.management.base import BaseCommand

from modelanvil.jobs.models import publish_outbox_batch


class RabbitPublisher:
    """Small reconnecting publisher using RabbitMQ publisher confirms."""

    def __init__(self, url: str):
        self.url = url
        self.connection = None
        self.channel = None

    def _ensure_channel(self):
        if self.connection is None or self.connection.is_closed:
            parameters = pika.URLParameters(self.url)
            self.connection = pika.BlockingConnection(parameters)
            self.channel = self.connection.channel()
            self.channel.confirm_delivery()
        elif self.channel is None or self.channel.is_closed:
            self.channel = self.connection.channel()
            self.channel.confirm_delivery()
        return self.channel

    def __call__(self, message: dict[str, Any]) -> bool:
        try:
            channel = self._ensure_channel()
            queue = message["topic"]
            channel.queue_declare(queue=queue, durable=True)
            channel.basic_publish(
                exchange="",
                routing_key=queue,
                body=json.dumps(message, separators=(",", ":")),
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    message_id=message["event_id"],
                    headers={"tenant_id": message["tenant_id"]},
                ),
                mandatory=True,
            )
            # With confirm_delivery enabled, basic_publish raises on Nack or
            # unroutable messages. Reaching here means the broker confirmed it.
            return True
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        try:
            if self.connection is not None and self.connection.is_open:
                self.connection.close()
        finally:
            self.connection = None
            self.channel = None


class Command(BaseCommand):
    help = "Publish pending transactional outbox events to RabbitMQ."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--loop", action="store_true", help="Keep polling for new outbox events.")
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["interval"] <= 0:
            self.stderr.write("--limit and --interval must be positive")
            return
        publisher = RabbitPublisher(os.environ.get(
            "RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F"
        ))
        try:
            while True:
                count = publish_outbox_batch(publisher, limit=options["limit"])
                self.stdout.write(f"confirmed={count}")
                if not options["loop"]:
                    break
                time.sleep(options["interval"])
        except KeyboardInterrupt:
            self.stdout.write("outbox publisher stopped")
        finally:
            publisher.close()
