"""Tests for dataset mixtures and weighted sampling (WP-05)."""
import uuid
from django.test import TestCase

from modelanvil.data.mixtures import MixtureComponent, build_mixture


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


class MixtureTests(TestCase):
    def test_build_mixture_proportional_and_deterministic(self):
        comp_a = MixtureComponent(
            revision_id="rev-a",
            weight=1.0,
            rows=[make_sample(f"A sample {i}", group=f"ga-{i}") for i in range(10)],
        )
        comp_b = MixtureComponent(
            revision_id="rev-b",
            weight=3.0,
            rows=[make_sample(f"B sample {i}", group=f"gb-{i}") for i in range(30)],
        )

        res1 = build_mixture([comp_a, comp_b], total_samples=20, seed="42")
        res2 = build_mixture([comp_a, comp_b], total_samples=20, seed="42")

        # Deterministic output
        self.assertEqual(res1.row_count, 20)
        self.assertEqual(res1.recipe_digest, res2.recipe_digest)
        self.assertEqual(res1.rows[0]["sample_id"], res2.rows[0]["sample_id"])

        # Proportions: A had weight 1 (25%), B had weight 3 (75%)
        # total 20 -> A: 5, B: 15
        self.assertEqual(res1.component_sample_counts["rev-a"], 5)
        self.assertEqual(res1.component_sample_counts["rev-b"], 15)

        # Split manifest is populated
        self.assertTrue(len(res1.split_manifest["train"]) > 0)
        self.assertEqual(
            len(res1.split_manifest["train"]) + len(res1.split_manifest["validation"]) + len(res1.split_manifest["test"]),
            20,
        )

    def test_build_mixture_validates_inputs(self):
        with self.assertRaises(ValueError):
            build_mixture([])

        comp = MixtureComponent(revision_id="rev-1", weight=-1.0, rows=[make_sample("test")])
        with self.assertRaises(ValueError):
            build_mixture([comp])
