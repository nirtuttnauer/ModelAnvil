import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from scripts.beta_release_manifest import record


class BetaReleaseManifestTests(TestCase):
    def test_receipt_ignores_private_data_and_changes_with_source(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            for name in ('modelanvil/example.py', 'private-saas/secret.py', 'data/customer.json', 'deploy/.env', 'web/src/view.tsx'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('original')
            entries = b'modelanvil/example.py\0private-saas/secret.py\0data/customer.json\0deploy/.env\0web/src/view.tsx\0'
            with patch('scripts.beta_release_manifest.subprocess.check_output', return_value=entries), patch('scripts.beta_release_manifest.git', return_value='saved'):
                before = record(root)
                self.assertEqual(set(before['files']), {'modelanvil/example.py', 'web/src/view.tsx'})
                (root / 'modelanvil/example.py').write_text('changed')
                self.assertNotEqual(before['source_digest'], record(root)['source_digest'])
