import copy
import hashlib

from django.test import SimpleTestCase
from contracts.validate import validate_envelope
from modelanvil.data.test_preparation import envelope
from modelanvil.data.text_chunks import chunk_envelopes


def text_row(text):
    row = envelope()
    row["blocks"] = [{"block_id": "text", "type": "text", "text": text, "location": {"page": 3, "source_path": "page/3"}}]
    row["provenance"]["content_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    return row


class TextChunkTests(SimpleTestCase):
    def test_chunks_reconstruct_exact_unicode_text_and_preserve_source_spans_and_groups(self):
        text = ("A line 日本語 🙂\n\t  " * 33) + "x"
        parent = text_row(text)
        original = copy.deepcopy(parent)
        chunks = list(chunk_envelopes([parent], 128))
        self.assertEqual(chunks, list(chunk_envelopes([parent], 128)))
        self.assertEqual(parent, original)
        self.assertEqual("".join(r["blocks"][0]["text"] for r in chunks), text)
        self.assertEqual(len({r["sample_id"] for r in chunks}), len(chunks))
        self.assertEqual({r["source_group_id"] for r in chunks}, {parent["source_group_id"]})
        for row in chunks:
            validate_envelope(row)
            block = row["blocks"][0]
            self.assertLessEqual(len(block["text"]), 128)
            self.assertGreater(len(block["text"]), 1)
            self.assertEqual(block["text"], text[block["location"]["char_start"]:block["location"]["char_end"]])
            self.assertEqual(block["location"]["page"], 3)
            self.assertEqual(row["provenance"]["parent_sample_refs"], [parent["sample_id"]])
            self.assertEqual(row["provenance"]["content_sha256"], hashlib.sha256(block["text"].encode()).hexdigest())

    def test_existing_character_offset_is_retained_and_invalid_span_refused(self):
        row = text_row("x" * 65)
        row["blocks"][0]["location"].update({"char_start": 200, "char_end": 265})
        chunks = list(chunk_envelopes([row], 32))
        self.assertEqual(chunks[0]["blocks"][0]["location"]["char_start"], 200)
        self.assertEqual(chunks[-1]["blocks"][0]["location"]["char_end"], 265)
        row["blocks"][0]["location"]["char_end"] = 300
        with self.assertRaises(ValueError): list(chunk_envelopes([row], 32))

    def test_invalid_limit_complex_blocks_and_output_amplification_are_refused(self):
        for limit in [True, "128", 31, 4097, 128.5]:
            with self.assertRaises(ValueError): list(chunk_envelopes([text_row("a")], limit))
        for blocks in [[{"type": "text", "role": "user", "text": "chat"}], [{"type": "code", "text": "code"}], text_row("a")["blocks"] * 2]:
            row = text_row("a"); row["blocks"] = blocks
            with self.assertRaises(ValueError): list(chunk_envelopes([row], 128))
        with self.assertRaisesRegex(ValueError, "sample limit"):
            list(chunk_envelopes([text_row("x" * 100)], 32, max_rows=2))
        row = text_row("x" * 10000); row["metadata"] = {"heavy": "y" * 1000000}
        with self.assertRaisesRegex(ValueError, "byte limit"):
            list(chunk_envelopes([row], 32))
