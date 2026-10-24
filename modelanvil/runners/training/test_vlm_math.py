"""Image trust-boundary tests; synthetic pixel fixtures do not qualify model quality."""
import hashlib
import importlib.util
import io
from unittest import skipUnless

from django.test import SimpleTestCase

from .vlm_math import decode_image


@skipUnless(importlib.util.find_spec('PIL'), 'Optional pinned Pillow is not installed')
class VisionImageBoundsTests(SimpleTestCase):
    def encoded(self, format='PNG', size=(32, 32)):
        from PIL import Image
        stream = io.BytesIO(); Image.new('RGB', size, 'red').save(stream, format=format)
        return stream.getvalue()

    def test_real_decode_retains_raw_identity_and_bounds_before_processor(self):
        for format, media in [('PNG', 'image/png'), ('JPEG', 'image/jpeg')]:
            raw = self.encoded(format)
            image, pin = decode_image(raw, media)
            self.assertEqual(image.mode, 'RGB'); self.assertEqual(image.size, (32, 32))
            self.assertEqual(pin['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(pin['byte_size'], len(raw))
            self.assertEqual(image.getpixel((16, 16))[0], 255 if format == 'PNG' else 254)

    def test_corrupt_mislabeled_oversized_animated_or_unsupported_images_fail(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(stream, format='PNG', save_all=True,
            append_images=[Image.new('RGB', (32, 32), 'blue')])
        for raw, media in [(b'not an image', 'image/png'), (self.encoded(), 'image/jpeg'),
                (self.encoded(size=(1025, 32)), 'image/png'), (stream.getvalue(), 'image/png'),
                (self.encoded('GIF'), 'image/gif'), (b'x' * (2 * 1024**2 + 1), 'image/png'),
                (self.encoded()[:-20], 'image/png')]:
            with self.assertRaises(ValueError): decode_image(raw, media)
