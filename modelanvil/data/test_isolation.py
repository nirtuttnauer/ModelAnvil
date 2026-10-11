"""Tests for document rendering and media decoding isolation (WP-04)."""
from django.test import TestCase

from modelanvil.data.isolation import isolate_decode_media, isolate_render_document


class IsolationTests(TestCase):
    def test_isolate_render_document_sanitizes_scripts_and_events(self):
        dangerous_html = """
        <html>
            <head><script>alert('xss');</script></head>
            <body>
                <h1 onclick="malicious()">Title</h1>
                <p>Safe paragraph text.</p>
                <a href="javascript:doEvil()">Bad link</a>
                <iframe src="http://evil.com"></iframe>
            </body>
        </html>
        """
        res = isolate_render_document(dangerous_html)
        self.assertTrue(res.is_safe)
        self.assertNotIn("alert('xss')", res.clean_text)
        self.assertNotIn("onclick", res.clean_text)
        self.assertNotIn("javascript:", res.clean_text)
        self.assertIn("Safe paragraph text", res.clean_text)
        self.assertTrue(len(res.warnings) > 0)
        self.assertTrue(len(res.elements) > 0)

    def test_isolate_render_document_neutralizes_xxe_entities(self):
        xxe_svg = """<?xml version="1.0"?>
        <!DOCTYPE foo [
          <!ENTITY xxe SYSTEM "file:///etc/passwd">
        ]>
        <svg><text>&xxe;</text></svg>
        """
        res = isolate_render_document(xxe_svg, media_type="image/svg+xml")
        self.assertTrue(res.is_safe)
        self.assertIn("Detected potential XXE", "; ".join(res.warnings))

    def test_isolate_decode_media_png(self):
        # 1x1 valid PNG bytes
        png_1x1 = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        res = isolate_decode_media(png_1x1, "image/png")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.width, 1)
        self.assertEqual(res.height, 1)

    def test_isolate_decode_media_rejects_huge_dimensions(self):
        # Header with 20000x20000 dimensions (bomb)
        fake_huge_png = (
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x4e\x20\x00\x00\x4e\x20\x08\x06\x00\x00\x00"
        )
        res = isolate_decode_media(fake_huge_png, "image/png", max_dimension=16384)
        self.assertFalse(res.is_valid)
        self.assertIn("dimensions 20000x20000 exceed limit", res.error)
