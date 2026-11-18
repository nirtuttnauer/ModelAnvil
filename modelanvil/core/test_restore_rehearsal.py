"""Restore rehearsal copies regular files and does not follow a symlink outside the source."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from modelanvil.core.restore_rehearsal import rehearse_copy

SECRET = b'foreign-bytes-outside-the-source-tree'
SCOPE = 'Byte copy between directories. Not an off-host database restore or a recovery-time claim.'


def _regular_files(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    found = {}
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
        for name in filenames:
            path = current / name
            if path.is_symlink():
                continue
            found[path.as_posix()] = path.read_bytes()
    return found


def _symlink_targets(root: Path) -> list[Path]:
    if not root.exists():
        return []
    found = []
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in [*dirnames, *filenames]:
            path = current / name
            if path.is_symlink():
                found.append(path.resolve())
        dirnames[:] = [name for name in dirnames if not (current / name).is_symlink()]
    return found


class RestoreRehearsalTests(SimpleTestCase):
    def copy_or_refusal(self, source, destination):
        try:
            return rehearse_copy(source, destination)
        except ValueError:
            return None

    def assert_unqualified(self, report):
        self.assertIs(report['production_qualified'], False)
        self.assertIs(report['hardware_qualified'], False)
        self.assertEqual(report['scope'], SCOPE)
        self.assertEqual(
            set(report),
            {'files', 'inventory', 'production_qualified', 'hardware_qualified', 'scope'},
        )
        text = json.dumps(report)
        for claim in ('recovery_time', 'restore_time', 'rpo', 'rto', 'off_host'):
            self.assertNotIn(claim, text)

    def assert_secret_stays_outside(self, root, destination, outside, secret_paths):
        copies = sorted(path for path, data in _regular_files(root).items() if data == SECRET)
        self.assertEqual(copies, sorted(path.as_posix() for path in secret_paths))
        outside_root = outside.resolve()
        for target in _symlink_targets(destination):
            self.assertFalse(target == outside_root or target.is_relative_to(outside_root))
        report = getattr(self, '_report', None)
        if report is None:
            self.assertFalse(destination.exists())
            return
        self.assert_unqualified(report)
        digest = hashlib.sha256(SECRET).hexdigest()
        self.assertNotIn(digest, [item['sha256'] for item in report['inventory']])
        for item in report['inventory']:
            copied = destination / item['path']
            self.assertFalse(copied.is_symlink())
            self.assertTrue(copied.resolve().is_relative_to(destination.resolve()))

    def rehearse_escape(self, source, destination, outside, secret_paths):
        self._report = self.copy_or_refusal(source, destination)
        self.assert_secret_stays_outside(source.parent, destination, outside, secret_paths)

    def test_absolute_symlink_outside_the_source_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'weights.bin').write_bytes(b'kept')
            outside = root / 'outside'
            outside.mkdir()
            secret = outside / 'secret.bin'
            secret.write_bytes(SECRET)
            (source / 'escape.bin').symlink_to(secret)
            self.rehearse_escape(source, root / 'destination', outside, [secret])

    def test_relative_symlink_outside_the_source_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            nested = source / 'nested'
            nested.mkdir(parents=True)
            (source / 'weights.bin').write_bytes(b'kept')
            outside = root / 'outside'
            outside.mkdir()
            secret = outside / 'secret.bin'
            secret.write_bytes(SECRET)
            (nested / 'escape.bin').symlink_to(Path('..') / '..' / 'outside' / 'secret.bin')
            self.rehearse_escape(source, root / 'destination', outside, [secret])

    def test_directory_symlink_outside_the_source_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'weights.bin').write_bytes(b'kept')
            outside = root / 'outside-dir'
            outside.mkdir()
            secret = outside / 'nested-secret.bin'
            secret.write_bytes(SECRET)
            (source / 'escape-dir').symlink_to(outside, target_is_directory=True)
            self.rehearse_escape(source, root / 'destination', outside, [secret])

    def test_internal_symlink_is_not_materialized_as_a_second_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'weights.bin').write_bytes(b'kept')
            (source / 'alias.bin').symlink_to('weights.bin')
            destination = root / 'destination'
            report = self.copy_or_refusal(source, destination)
            self.assertIsNotNone(report)
            self.assertEqual(report['files'], 1)
            self.assertEqual(report['inventory'][0]['path'], 'weights.bin')
            self.assertEqual((destination / 'weights.bin').read_bytes(), b'kept')
            self.assertFalse((destination / 'alias.bin').exists())
            self.assert_unqualified(report)

    def test_existing_destination_is_rejected_and_a_copy_stays_under_the_new_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'models').mkdir(parents=True)
            (source / 'models' / 'weights.bin').write_bytes(b'weights')
            (source / 'empty').mkdir()
            marker = root / 'marker.bin'
            marker.write_bytes(b'marker')

            occupied = root / 'occupied'
            occupied.mkdir()
            (occupied / 'keep.bin').write_bytes(b'keep')
            with self.assertRaises(ValueError):
                rehearse_copy(source, occupied)
            self.assertEqual((occupied / 'keep.bin').read_bytes(), b'keep')
            self.assertFalse((occupied / 'models').exists())

            occupied_file = root / 'occupied-file'
            occupied_file.write_bytes(b'file-keep')
            with self.assertRaises(ValueError):
                rehearse_copy(source, occupied_file)
            self.assertEqual(occupied_file.read_bytes(), b'file-keep')

            dangling = root / 'dangling'
            dangling.symlink_to(root / 'missing')
            with self.assertRaises(ValueError):
                rehearse_copy(source, dangling)
            self.assertTrue(dangling.is_symlink())
            self.assertFalse(dangling.is_dir())

            destination = root / 'destination'
            report = rehearse_copy(source, destination)
            self.assertEqual((destination / 'models' / 'weights.bin').read_bytes(), b'weights')
            self.assertTrue((destination / 'empty').is_dir())
            self.assertFalse((destination / 'models' / 'weights.bin').is_symlink())
            self.assertFalse(destination.is_symlink())
            self.assertEqual(marker.read_bytes(), b'marker')
            files = sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob('*')
                if path.is_file() and not path.is_symlink()
            )
            self.assertEqual(files, [
                'destination/models/weights.bin',
                'marker.bin',
                'occupied-file',
                'occupied/keep.bin',
                'source/models/weights.bin',
            ])
            self.assertEqual(report['files'], 1)
            for item in report['inventory']:
                copied = destination / item['path']
                self.assertFalse(copied.is_symlink())
                self.assertEqual(copied.resolve().relative_to(destination.resolve()).as_posix(), item['path'])
                self.assertEqual(copied.read_bytes(), (source / item['path']).read_bytes())
            self.assert_unqualified(report)
