import hashlib
import csv
import io
import json
import zipfile

from django.test import SimpleTestCase
from contracts.validate import validate_envelope
from modelanvil.data.source_import import extract_source


def docx(xml):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


class SourceImportTests(SimpleTestCase):
    def test_csv_and_json_preserve_exact_text_locations_hashes_and_groups(self):
        fixtures = [("csv", b'body,group\n"First, sample",shared\n"Second\nline",shared\n', "record/1"),
                    ("json", json.dumps([{"body": "First, sample", "group": "shared", "other": None},
                                         {"body": "Second\nline", "group": "shared"}]).encode(), "/0")]
        for fmt, raw, location in fixtures:
            rows = extract_source(raw, source_format=fmt, text_field="body", group_field="group")
            self.assertEqual(rows, extract_source(raw, source_format=fmt, text_field="body", group_field="group"))
            self.assertEqual([r["blocks"][0]["text"] for r in rows], ["First, sample", "Second\nline"])
            self.assertEqual({r["source_group_id"] for r in rows}, {"shared"})
            self.assertEqual(rows[0]["blocks"][0]["location"]["source_path"], location)
            for row in rows:
                validate_envelope(row)
                self.assertEqual(row["provenance"]["source_snapshot_ref"], "sha256:" + hashlib.sha256(raw).hexdigest())
                self.assertEqual(row["provenance"]["content_sha256"], hashlib.sha256(row["blocks"][0]["text"].encode()).hexdigest())

    def test_default_group_protects_whole_source_and_docx_extracts_body_table_text(self):
        raw = docx('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   '<w:p><w:r><w:t>First</w:t><w:tab/><w:t>line</w:t><w:br/><w:t>next</w:t></w:r></w:p>'
                   '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Table cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
                   '</w:body></w:document>')
        rows = extract_source(raw, source_format="docx")
        self.assertEqual([r["blocks"][0]["text"] for r in rows], ["First\tline\nnext", "Table cell"])
        self.assertEqual(len({r["source_group_id"] for r in rows}), 1)
        self.assertEqual(rows[1]["provenance"]["source_record_key"], "word/document.xml/paragraph/2")
        for row in rows:
            validate_envelope(row)

    def test_malformed_or_ambiguous_records_never_produce_samples(self):
        cases = [("csv", b'text,text\na,b\n'), ("csv", b'text,group\na\n'), ("csv", b'text\na,b\n'),
                 ("csv", b'text\n"unclosed'), ("json", b'[{"text":"a","text":"b"}]'),
                 ("json", b'[{"text":"a","bad":NaN}]'), ("json", b'{"text":"a"}'),
                 ("json", b'[{"text":4}]'), ("json", b'[{"text":" "}]'), ("json", b'[]'),
                 ("docx", b'not a zip'), ("docx", docx('<!DOCTYPE doc [<!ENTITY e "EXPANDED">]><doc>&e;</doc>')),
                 ("docx", docx('<!DOCTYPE doc [<!ENTITY e "EXPANDED">]><doc>&e;</doc>'.encode('utf-16')))]
        for fmt, raw in cases:
            with self.subTest(format=fmt, raw=raw[:30]):
                with self.assertRaises((ValueError, zipfile.BadZipFile, csv.Error)):
                    extract_source(raw, source_format=fmt)

    def test_row_limit_and_missing_group_are_rejected(self):
        for raw, options in [(json.dumps([{"text": "a"}] * 10001).encode(), {}),
                             (b'[{"text":"a"}]', {"group_field": "missing"})]:
            with self.assertRaises(ValueError):
                extract_source(raw, source_format="json", **options)

    def test_docx_uncompressed_size_is_checked_before_xml_expansion(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", "x" * (16 * 1024 * 1024 + 1))
        self.assertLess(len(buffer.getvalue()), 100000)
        with self.assertRaisesRegex(ValueError, "archive exceeds"):
            extract_source(buffer.getvalue(), source_format="docx")
