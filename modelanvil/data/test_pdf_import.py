import hashlib
import importlib.metadata
import io
import subprocess
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase
from contracts.validate import validate_envelope
from modelanvil.data.source_import import PDF_VERSION, SourceImportError, extract_source

try:
    HAS_PDF = importlib.metadata.version("pypdf") == PDF_VERSION
except importlib.metadata.PackageNotFoundError:
    HAS_PDF = False


def pdf(texts, *, encrypted=False, compressed=False):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text is not None:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 50 700 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream.flate_encode() if compressed else stream)
    if encrypted:
        writer.encrypt("fixture-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PdfRefusalTests(SimpleTestCase):
    def test_missing_pinned_dependency_has_an_actionable_safe_error(self):
        with patch("modelanvil.data.source_import.importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(SourceImportError, "requirements.documents.txt"):
                extract_source(b"%PDF-private", source_format="pdf")

    def test_process_timeout_does_not_expose_diagnostics_or_pass_credentials(self):
        def timeout(command, **kwargs):
            self.assertEqual(set(kwargs["env"]), {"PATH"})
            self.assertEqual(command[1], "-I")
            self.assertEqual(kwargs["timeout"], 15)
            raise subprocess.TimeoutExpired(command, 15, output=b"PRIVATE_MARKER", stderr=b"PRIVATE_MARKER")
        with patch("modelanvil.data.source_import.importlib.metadata.version", return_value=PDF_VERSION), patch("modelanvil.data.source_import.subprocess.run", side_effect=timeout):
            with self.assertRaisesRegex(SourceImportError, "time limit") as error:
                extract_source(b"%PDF-private", source_format="pdf")
            self.assertNotIn("PRIVATE_MARKER", str(error.exception))


@skipUnless(HAS_PDF, "Install requirements.documents.txt for actual PDF parser checks")
class PdfExtractionTests(SimpleTestCase):
    def test_real_pdf_pages_have_exact_text_hashes_locations_and_one_protected_group(self):
        raw = pdf(["First source page", "Second source page"], compressed=True)
        rows = extract_source(raw, source_format="pdf")
        self.assertEqual(rows, extract_source(raw, source_format="pdf"))
        self.assertEqual([r["blocks"][0]["text"] for r in rows], ["First source page", "Second source page"])
        self.assertEqual([r["blocks"][0]["location"] for r in rows], [{"source_path": "page/1", "page": 1}, {"source_path": "page/2", "page": 2}])
        self.assertEqual(len({r["source_group_id"] for r in rows}), 1)
        for row in rows:
            validate_envelope(row)
            self.assertIn(PDF_VERSION, row["provenance"]["transformation_revision_ref"])
            self.assertEqual(row["provenance"]["source_snapshot_ref"], "sha256:" + hashlib.sha256(raw).hexdigest())
            self.assertEqual(row["provenance"]["content_sha256"], hashlib.sha256(row["blocks"][0]["text"].encode()).hexdigest())

    def test_encrypted_blank_mixed_and_oversized_pdfs_refuse_whole_document(self):
        cases = [(pdf(["Private source text"], encrypted=True), "Encrypted"), (pdf([None]), "OCR"),
                 (pdf(["Readable", None]), "OCR"), (pdf(["text"] * 101), "page"),
                 (pdf(["x" * (1024 * 1024 + 1)], compressed=True), "failed|limits"),
                 (b"%PDF-1.7 PRIVATE_MARKER", "failed")]
        for raw, message in cases:
            with self.assertRaisesRegex(SourceImportError, message) as error:
                extract_source(raw, source_format="pdf")
            self.assertNotIn("PRIVATE_MARKER", str(error.exception))
