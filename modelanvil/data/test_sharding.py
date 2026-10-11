"""Tests for tokenized and sharded dataset packaging (WP-05)."""
import uuid
from django.test import TestCase

from modelanvil.data.sharding import build_tokenized_shards


def make_sample(text: str) -> dict:
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.uuid4()),
        "source_group_id": "g1",
        "blocks": [{"block_id": "b1", "type": "text", "text": text}],
        "provenance": {
            "source_snapshot_ref": "snap-1",
            "source_record_key": "k1",
            "content_sha256": "0" * 64,
        },
    }


class ShardingTests(TestCase):
    def test_build_tokenized_shards_partitions_records_and_hashes(self):
        rows = [make_sample(f"Hello world document {i}") for i in range(25)]

        res = build_tokenized_shards(rows, shard_size_rows=10)

        # 25 rows with shard size 10 -> 3 shards (10, 10, 5)
        self.assertEqual(res.shard_count, 3)
        self.assertEqual(res.total_rows, 25)
        self.assertEqual(res.shards[0].row_count, 10)
        self.assertEqual(res.shards[1].row_count, 10)
        self.assertEqual(res.shards[2].row_count, 5)

        # Hashes and tokens are non-zero
        self.assertTrue(len(res.manifest_digest) == 64)
        for s in res.shards:
            self.assertTrue(len(s.sha256) == 64)
            self.assertTrue(s.token_count > 0)
            self.assertTrue(s.byte_size > 0)

    def test_build_tokenized_shards_empty_fails(self):
        with self.assertRaises(ValueError):
            build_tokenized_shards([])
