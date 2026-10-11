"""Tests for repository and Scrapling crawler connectors (WP-04)."""
import json
from unittest.mock import MagicMock
from django.test import TestCase

from modelanvil.data.connectors.base import ConnectorConfig
from modelanvil.data.connectors.repository import RepositoryConnector
from modelanvil.data.connectors.crawler import ScraplingCrawlerConnector


class ConnectorTests(TestCase):
    def test_repository_connector_acquires_and_validates_envelopes(self):
        sample_records = [
            {"id": "rec-1", "text": "This is sample document 1 from repo."},
            {"id": "rec-2", "text": "This is sample document 2 from repo."},
        ]

        def fake_transport(url: str, headers: dict[str, str]):
            self.assertIn("ref=v1.0.0", url)
            return 200, json.dumps(sample_records).encode("utf-8"), {}

        config = ConnectorConfig(
            target_uri="https://api.example.com/v1/dataset",
            allowed_domains=["example.com"],
            pin_revision="v1.0.0",
        )
        connector = RepositoryConnector(config, transport=fake_transport)
        result = connector.acquire()

        self.assertEqual(result.item_count, 2)
        self.assertEqual(result.failure_count, 0)
        self.assertTrue(len(result.manifest_digest) == 64)
        self.assertEqual(result.items[0].envelope["blocks"][0]["text"], "This is sample document 1 from repo.")

    def test_repository_connector_checkpoint_and_resume(self):
        config = ConnectorConfig(
            target_uri="https://api.example.com/v1/dataset",
            allowed_domains=["example.com"],
        )
        connector = RepositoryConnector(config)
        connector.processed_ids.add("rec-1")
        cp = connector.checkpoint()

        new_connector = RepositoryConnector(config)
        new_connector.resume(cp)
        self.assertIn("rec-1", new_connector.processed_ids)

    def test_crawler_enforces_domain_and_denies_forbidden_destinations(self):
        config = ConnectorConfig(
            target_uri="http://127.0.0.1/private",
            allowed_domains=["example.com"],
        )
        crawler = ScraplingCrawlerConnector(config)
        allowed, reason = crawler.is_url_allowed("http://127.0.0.1/private")
        self.assertFalse(allowed)
        self.assertIn("Denied destination", reason)

        allowed, reason = crawler.is_url_allowed("https://otherdomain.org/page")
        self.assertFalse(allowed)
        self.assertIn("not in allowed domains", reason)

        allowed, reason = crawler.is_url_allowed("https://sub.example.com/page")
        self.assertTrue(allowed)

    def test_crawler_discovers_links_and_produces_checkpoints(self):
        pages = {
            "https://example.com/index": (
                200,
                b'<html><body><h1>Home</h1><p>Welcome</p><a href="/about">About</a></body></html>',
                {},
            ),
            "https://example.com/about": (
                200,
                b'<html><body><h1>About</h1><p>Our mission</p></body></html>',
                {},
            ),
        }

        def fake_transport(url: str, headers: dict[str, str]):
            return pages.get(url, (404, b"Not Found", {}))

        config = ConnectorConfig(
            target_uri="https://example.com/index",
            allowed_domains=["example.com"],
            max_requests=10,
        )
        crawler = ScraplingCrawlerConnector(config, transport=fake_transport)
        result = crawler.acquire()

        self.assertEqual(result.item_count, 2)
        self.assertEqual(crawler.requests_made, 2)
        self.assertEqual(crawler.status, "completed")
        self.assertTrue(len(result.manifest_digest) == 64)

        cp = crawler.checkpoint()
        self.assertEqual(cp["status"], "completed")
        self.assertEqual(cp["requests_made"], 2)

    def test_crawler_cancellation(self):
        config = ConnectorConfig(
            target_uri="https://example.com/page",
            allowed_domains=["example.com"],
        )
        crawler = ScraplingCrawlerConnector(config)
        crawler.cancel()
        self.assertEqual(crawler.status, "cancelled")
        result = crawler.acquire()
        self.assertEqual(result.item_count, 0)
