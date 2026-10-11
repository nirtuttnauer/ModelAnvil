from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from modelanvil.jobs.management.commands.flush_outbox import RabbitPublisher


class RabbitPublisherTests(SimpleTestCase):
    @patch("modelanvil.jobs.management.commands.flush_outbox.pika.BlockingConnection")
    def test_publishes_persistent_message_with_confirm_and_event_id(self, connection_factory):
        connection = MagicMock()
        channel = connection.channel.return_value
        connection_factory.return_value = connection
        publisher = RabbitPublisher("amqp://guest:guest@localhost:5672/%2F")
        message = {"event_id": "evt-1", "tenant_id": "tenant-1", "topic": "cpu", "payload": {"job_id": "job-1"}}

        self.assertTrue(publisher(message))

        channel.confirm_delivery.assert_called_once_with()
        channel.queue_declare.assert_called_once_with(queue="cpu", durable=True)
        args = channel.basic_publish.call_args.kwargs
        self.assertEqual(args["routing_key"], "cpu")
        self.assertTrue(args["mandatory"])
        self.assertEqual(args["properties"].message_id, "evt-1")
        self.assertEqual(args["properties"].delivery_mode, 2)
        connection.close.assert_not_called()
        publisher.close()
        connection.close.assert_called_once_with()
