"""Real optional rasterizer checks; core installations remain dependency-free."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from scripts.specialist_runtime import render_sources


@unittest.skipUnless(importlib.util.find_spec('PIL') and importlib.util.find_spec('pypdfium2'), 'Optional specialist image/PDF runtime is not installed')
class SpecialistRasterTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        Image.init()
        self.directory = tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def pdf(self, count=2, size=(400,200)):
        from PIL import Image, ImageDraw
        pages = []
        for n in range(count):
            image = Image.new('RGB',size,'white');ImageDraw.Draw(image).text((20,20),f'Page {n+1}',fill='black');pages.append(image)
        path = self.root/'source.pdf'
        pages[0].save(path,save_all=True,append_images=pages[1:],resolution=144)
        return path

    def test_image_only_pdf_renders_exact_page_count_dimensions_and_hashes(self):
        pages, metadata = render_sources(self.pdf())
        self.assertEqual(metadata['page_count'],2);self.assertEqual(metadata['renderer'],'pypdfium2==5.14.0')
        self.assertEqual([p['page'] for p in pages],[1,2])
        self.assertTrue(all(p['image_dimensions']==[400,200] and len(p['raster_sha256'])==64 for p in pages))
        self.assertNotEqual(pages[0]['raster_sha256'],pages[1]['raster_sha256'])
        self.assertTrue(all(Path(p['path']).is_file() for p in pages))

    def test_page_count_and_declared_canvas_limits_refuse_before_model_allocation(self):
        with self.assertRaisesRegex(ValueError,'1–5 pages'):render_sources(self.pdf(6))
        with self.assertRaisesRegex(ValueError,'dimensions'):render_sources(self.pdf(1,(4200,200)))

    def test_png_dimensions_animation_and_content_validation(self):
        from PIL import Image
        path = self.root/'image'
        from PIL import ImageDraw
        image=Image.new('RGB',(400,200),'white');ImageDraw.Draw(image).text((20,20),'Receipt',fill='black');image.save(path,format='PNG')
        pages, meta = render_sources(path)
        self.assertEqual(meta['normalization'],'exif_transpose_rgb');self.assertEqual(len(pages),1)
        Image.new('RGB',(20,20),'white').save(path,format='PNG')
        with self.assertRaisesRegex(ValueError,'single PNG/JPEG'):render_sources(path)
        Image.new('RGB',(400,200),'white').save(path,format='PNG',save_all=True,append_images=[Image.new('RGB',(400,200),'black')])
        with self.assertRaisesRegex(ValueError,'single PNG/JPEG'):render_sources(path)
        path.write_bytes(b'%PDF-broken')
        with self.assertRaises(Exception):render_sources(path)

    def test_uniform_image_and_blank_pdf_refuse_before_model_allocation(self):
        from PIL import Image
        image=Image.new('RGB',(400,200),'white');path=self.root/'blank.png';image.save(path)
        with self.assertRaisesRegex(ValueError,'Blank or nearly uniform'):render_sources(path)
        path=self.root/'blank.pdf';image.save(path,resolution=144)
        with self.assertRaisesRegex(ValueError,'Blank or nearly uniform'):render_sources(path)
