"""Behavioral tests for the pure content-detection kernel (WP-05)."""
import hashlib
import uuid

from django.test import SimpleTestCase

from modelanvil.data.detection import (
    block_content_text,
    build_protected_set,
    content_digest,
    hamming_distance,
    privacy_flags,
    protected_overlap,
    quality_flags,
    sample_text,
    simhash,
)


def envelope(number=1, group="source-A", text="The quick brown fox jumps over the lazy dog."):
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.UUID(int=number)),
        "source_group_id": group,
        "blocks": [
            {"block_id": "text", "type": "text", "role": "user", "text": text},
        ],
        "provenance": {
            "source_snapshot_ref": "snapshot-1",
            "source_record_key": str(number),
            "content_sha256": "a" * 64,
        },
    }


class ContentExtractionTests(SimpleTestCase):
    def test_block_content_text_by_type(self):
        self.assertEqual(block_content_text({"type": "text", "text": " hi "}), " hi ")
        self.assertEqual(block_content_text({"type": "code", "text": "x = 1"}), "x = 1")
        self.assertEqual(block_content_text({"type": "json", "value": {"b": 1, "a": 2}}), '{"a":2,"b":1}')
        self.assertEqual(block_content_text({"type": "table", "value": [[1, 2]]}), '[[1,2]]')
        self.assertEqual(block_content_text({"type": "tool_call", "value": {"t": "f"}}), '{"t":"f"}')
        self.assertEqual(block_content_text({"type": "custom", "value": "raw"}), "raw")
        self.assertEqual(block_content_text({"type": "image", "asset_ref": "img:1"}), "")
        self.assertEqual(block_content_text({"type": "text"}), "")
        self.assertEqual(block_content_text({"type": "json", "value": None}), "")

    def test_sample_text_joins_in_order(self):
        row = {
            "blocks": [
                {"type": "text", "text": "first"},
                {"type": "image", "asset_ref": "img"},
                {"type": "json", "value": {"k": "second"}},
            ],
        }
        self.assertEqual(sample_text(row), "first\n{\"k\":\"second\"}")

    def test_content_digest_is_identity_free_and_order_sensitive(self):
        base = envelope(1)
        renamed = envelope(1)
        renamed["blocks"][0]["block_id"] = "other-id"
        renamed["provenance"]["source_record_key"] = "999"
        self.assertEqual(content_digest(base), content_digest(renamed))
        reordered = envelope(1)
        reordered["blocks"] = [
            {"type": "json", "value": {"z": 1}},
            {"type": "text", "text": "The quick brown fox jumps over the lazy dog."},
        ]
        self.assertNotEqual(content_digest(base), content_digest(reordered))
        changed = envelope(1)
        changed["blocks"][0]["text"] = "different content"
        self.assertNotEqual(content_digest(base), content_digest(changed))
        self.assertEqual(len(content_digest(base)), 64)


class PrivacyFlagTests(SimpleTestCase):
    def test_flags_each_signal(self):
        self.assertIn("pii.email", privacy_flags("contact me at alice@example.com today"))
        self.assertIn("pii.phone", privacy_flags("call 415-555-0132 or (415) 555-0132"))
        self.assertIn("pii.ssn", privacy_flags("my ssn is 123-45-6789 thanks"))
        self.assertIn("pii.ip_address", privacy_flags("server at 192.168.1.10 was slow"))
        self.assertIn("pii.credit_card", privacy_flags("card 4242 4242 4242 4242 on file"))

    def test_clean_text_has_no_flags(self):
        self.assertEqual(privacy_flags("The quick brown fox jumps over the lazy dog."), [])
        self.assertEqual(privacy_flags(""), [])

    def test_luhn_rejects_invalid_card(self):
        # 1234 5678 9012 3456 fails the Luhn check.
        self.assertNotIn("pii.credit_card", privacy_flags("number 1234 5678 9012 3456 end"))

    def test_flags_are_sorted_and_deduped(self):
        text = "a@b.co and a@b.co again"
        self.assertEqual(privacy_flags(text), ["pii.email"])


class QualityFlagTests(SimpleTestCase):
    def test_empty_sample(self):
        row = envelope(text="   \n\t  ")
        self.assertIn("quality.empty", quality_flags(row))

    def test_short_sample(self):
        row = envelope(text="hi")
        self.assertIn("quality.short", quality_flags(row, min_text_chars=8))
        self.assertNotIn("quality.short", quality_flags(row, min_text_chars=2))

    def test_repetitive_single_char(self):
        row = envelope(text="a" * 40)
        self.assertIn("quality.repetitive", quality_flags(row))

    def test_repetitive_unit(self):
        row = envelope(text="abcd" * 10)
        self.assertIn("quality.repetitive", quality_flags(row))

    def test_single_short_unit_and_two_copies_are_not_three_repetitions(self):
        for text in ('DOCUMENT', 'v=56789;', 'abcdefgh' * 2):
            self.assertNotIn('quality.repetitive', quality_flags(envelope(text=text)))
        self.assertIn('quality.repetitive', quality_flags(envelope(text='abcdefgh' * 3)))

    def test_normal_text_is_clean(self):
        row = envelope()
        self.assertEqual(quality_flags(row), [])

    def test_min_text_chars_validation(self):
        with self.assertRaises(ValueError):
            quality_flags(envelope(), min_text_chars=-1)
        with self.assertRaises(ValueError):
            quality_flags(envelope(), min_text_chars=True)


class SimhashTests(SimpleTestCase):
    def test_deterministic_and_stable(self):
        a = simhash("hello world, this is a test document")
        b = simhash("hello world, this is a test document")
        self.assertEqual(a, b)

    def test_whitespace_insensitive(self):
        self.assertEqual(simhash("hello   world"), simhash("hello world"))

    def test_empty_is_zero(self):
        self.assertEqual(simhash("   "), 0)

    def test_similar_texts_are_close(self):
        base = "The model anvil compiles the context workbench for evaluation runs."
        near = "The model anvil compiles the context workbench for evaluation runs!"
        far = "Completely unrelated content about gardening and tomato plants."
        self.assertLess(
            hamming_distance(simhash(base), simhash(near)),
            hamming_distance(simhash(base), simhash(far)),
        )

    def test_hamming_distance(self):
        self.assertEqual(hamming_distance(0b1010, 0b1010), 0)
        self.assertEqual(hamming_distance(0b1010, 0b0101), 4)
        with self.assertRaises(ValueError):
            hamming_distance(-1, 0)

    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            simhash("x", ngram=0)
        with self.assertRaises(ValueError):
            simhash("x", bits=7)


class ProtectedSetTests(SimpleTestCase):
    def test_build_and_exact_overlap(self):
        protected = envelope(100, text="Protected evaluation question text here.")
        probe = envelope(101, text="Protected evaluation question text here.")
        probe["blocks"][0]["block_id"] = "different"
        protected_set = build_protected_set([protected])
        self.assertEqual(len(protected_set["digests"]), 1)
        self.assertEqual(len(protected_set["simhashes"]), 1)
        self.assertIn("overlap.protected_exact", protected_overlap(probe, protected_set))

    def test_near_overlap(self):
        protected = envelope(100, text="The protected evaluation sentence is quite specific.")
        probe = envelope(101, text="The protected evaluation sentence is quite specific!")
        protected_set = build_protected_set([protected])
        flags = protected_overlap(probe, protected_set, near_threshold=8)
        self.assertIn("overlap.protected_near", flags)

    def test_disjoint_has_no_overlap(self):
        protected = envelope(100, text="Alpha beta gamma delta evaluation.")
        probe = envelope(101, text="Something entirely different and unrelated.")
        protected_set = build_protected_set([protected])
        self.assertEqual(protected_overlap(probe, protected_set, near_threshold=2), [])
