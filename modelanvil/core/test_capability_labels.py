"""README capability Evidence column against docs/engineering/supported-capabilities.json (ANVIL-016)."""
import copy
import hashlib

from django.test import SimpleTestCase

from modelanvil.runners.evidence import LEVELS as CODE_LEVELS
from scripts.capability_labels import (
    END, LEVELS, NOTE, README, START, check, load_manifest, manifest_problems, readme_rows, render,
)


class CapabilityLabelTests(SimpleTestCase):
    def setUp(self):
        self.manifest = load_manifest()
        self.readme = README.read_text()

    def changed(self, area, **fields):
        manifest = copy.deepcopy(self.manifest)
        row = next(row for row in manifest['readme_rows'] if row['area'] == area)
        for key, value in fields.items():
            if value is None:
                row.pop(key, None)
            else:
                row[key] = value
        return manifest, row

    def test_repository_readme_and_manifest_agree(self):
        self.assertEqual(manifest_problems(self.manifest), [])
        check(self.readme, self.manifest)
        self.assertEqual(render(self.readme, self.manifest), self.readme)

    def test_levels_are_the_five_code_levels(self):
        self.assertEqual(LEVELS, CODE_LEVELS)
        self.assertEqual(len(LEVELS), 5)

    def test_every_readme_row_has_one_manifest_entry(self):
        areas = [row[0] for row in readme_rows(self.readme)]
        self.assertEqual(sorted(areas), sorted(row['area'] for row in self.manifest['readme_rows']))
        self.assertEqual(len(areas), len(set(areas)))

    def test_post_training_is_split_so_no_row_claims_more_than_its_evidence(self):
        levels = {row['area']: row['level'] for row in self.manifest['readme_rows']}
        self.assertNotIn('Post-training', levels)
        self.assertEqual(levels['Post-training on CPU'], 'integrated_execution')
        self.assertEqual(levels['Post-training on Apple GPU'], 'integrated_execution')
        self.assertEqual(levels['Post-training on CUDA, ROCm and XPU'], 'configuration_only')
        self.assertNotIn('hardware_qualified', levels.values())

    def test_readme_row_missing_from_the_manifest_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['readme_rows'] = [row for row in manifest['readme_rows'] if row['area'] != 'Team labeling']
        with self.assertRaisesRegex(ValueError, "README row 'Team labeling' is missing from the manifest"):
            check(self.readme, manifest)
        with self.assertRaisesRegex(ValueError, 'missing from the manifest'):
            render(self.readme, manifest)

    def test_manifest_row_without_a_readme_row_fails(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['readme_rows'].append({'area': 'Cluster training', 'level': 'configuration_only', 'evidence': []})
        with self.assertRaisesRegex(ValueError, "Manifest row 'Cluster training' is not in the README table"):
            check(self.readme, manifest)

    def test_missing_or_unsupported_level_fails(self):
        for level in (None, '', 'qualified', 'Integrated execution', 'production_qualified'):
            with self.subTest(level=level):
                manifest, _ = self.changed('Control plane', level=level)
                with self.assertRaisesRegex(ValueError, "Manifest row 'Control plane': level .* is not one of"):
                    check(self.readme, manifest)

    def test_level_above_simulation_without_evidence_fails(self):
        for level in ('integrated_execution', 'hardware_qualified'):
            with self.subTest(level=level):
                manifest, _ = self.changed('Control plane', level=level, evidence=[])
                with self.assertRaisesRegex(ValueError, 'needs at least one evidence file'):
                    check(self.readme, manifest)
        for level in ('configuration_only', 'simulation', 'unknown'):
            with self.subTest(level=level):
                manifest, _ = self.changed('Control plane', level=level, evidence=[])
                self.assertEqual(manifest_problems(manifest), [])

    def test_missing_evidence_file_fails(self):
        manifest, row = self.changed('Team labeling')
        row['evidence'][0]['path'] = 'verification/task10-labeling-2026-10-23/missing.json'
        with self.assertRaisesRegex(ValueError, 'missing.json does not exist'):
            check(self.readme, manifest)
        row['evidence'][0]['path'] = '../../../outside-the-repository.json'
        with self.assertRaisesRegex(ValueError, 'is outside the repository'):
            check(self.readme, manifest)

    def test_sha256_mismatch_fails_for_readme_rows_and_operations(self):
        stale = hashlib.sha256(b'stale evidence').hexdigest()
        manifest, row = self.changed('Post-training on Apple GPU')
        row['evidence'][0]['sha256'] = stale
        with self.assertRaisesRegex(ValueError, f'has sha256 [0-9a-f]{{64}}; the manifest records {stale}'):
            check(self.readme, manifest)
        manifest = copy.deepcopy(self.manifest)
        manifest['operations'][1]['evidence'][1]['sha256'] = stale
        problems = manifest_problems(manifest)
        self.assertEqual(len(problems), 1)
        self.assertIn('operations[1] training: evidence verification/task40-mps-pilot.json has sha256', problems[0])
        for bad in ('', stale.upper(), stale[:63], None):
            with self.subTest(sha256=bad):
                manifest, row = self.changed('Team labeling')
                row['evidence'][0]['sha256'] = bad
                with self.assertRaisesRegex(ValueError, '64-character lowercase sha256'):
                    check(self.readme, manifest)

    def test_readme_evidence_column_that_disagrees_with_the_manifest_fails(self):
        edited = self.readme.replace('| Configuration only |', '| Integrated execution |', 1)
        self.assertNotEqual(edited, self.readme)
        with self.assertRaisesRegex(ValueError, 'README Evidence column differs from the manifest'):
            check(edited, self.manifest)
        manifest, _ = self.changed('Control plane', level='simulation')
        with self.assertRaisesRegex(ValueError, 'README Evidence column differs from the manifest'):
            check(self.readme, manifest)
        manifest, row = self.changed('Control plane')
        row['evidence'] = row['evidence'][:1]
        with self.assertRaisesRegex(ValueError, 'README Evidence column differs from the manifest'):
            check(self.readme, manifest)

    def test_write_readme_adds_the_column_to_an_unmarked_three_column_table(self):
        begin, end = self.readme.index(START), self.readme.index(END) + len(END)
        rows = [line.rsplit(' | ', 1)[0] + ' |' for line in self.readme[begin:end].splitlines() if line.startswith('|')]
        rows[1] = '| --- | --- | --- |'
        plain = self.readme[:begin] + '\n'.join(rows) + self.readme[end:]
        self.assertNotIn(START, plain)
        self.assertNotIn(NOTE, plain)
        with self.assertRaisesRegex(ValueError, 'is not generated'):
            check(plain, self.manifest)
        self.assertEqual(render(plain, self.manifest), self.readme)
