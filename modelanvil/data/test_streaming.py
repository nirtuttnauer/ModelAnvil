"""Tests for streaming envelope preparation (WP-05)."""
import uuid
from django.test import TestCase

from modelanvil.data.preparation import stream_prepare_envelopes


def make_sample(text: str, group: str = "g1") -> dict:
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.uuid4()),
        "source_group_id": group,
        "blocks": [{"block_id": "b1", "type": "text", "text": text}],
        "provenance": {
            "source_snapshot_ref": "snap-1",
            "source_record_key": "k1",
            "content_sha256": "0" * 64,
        },
    }


class StreamingPreparationTests(TestCase):
    def test_stream_prepare_envelopes_yields_kept_and_dropped(self):
        samples = [
            make_sample("Clean text sample 1"),
            make_sample("Contact me at user@example.com for info"),  # PII email
            make_sample("Clean text sample 2"),
        ]

        generator = stream_prepare_envelopes(samples, detect={"privacy": True, "quality": False})
        results = list(generator)

        self.assertEqual(len(results), 3)

        status0, row0, split0 = results[0]
        self.assertEqual(status0, "kept")
        self.assertIn(split0, ("train", "validation", "test"))

        status1, id1, reasons1 = results[1]
        self.assertEqual(status1, "dropped")
        self.assertIn("pii.email", reasons1)

        status2, row2, split2 = results[2]
        self.assertEqual(status2, "kept")
