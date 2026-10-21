"""UUIDv7 layout, runtime compatibility, and application default coverage."""
import uuid
from unittest.mock import patch

from django.apps import apps
from django.db import models
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import SeparateDatabaseAndState
from django.test import SimpleTestCase

from modelanvil.core import ids


class UUID7Tests(SimpleTestCase):
    def test_python_312_fallback_matches_rfc9562_uuid7_vector(self):
        timestamp = 0x017F22E279B0
        random = (0xCC3 << 62) | 0x18C4DC0C0C07398F
        with patch.object(ids.uuid, 'uuid7', None, create=True), patch.object(ids.time, 'time_ns', return_value=timestamp * 1_000_000), patch.object(ids.secrets, 'randbits', return_value=random) as entropy:
            value = ids.uuid7()
        self.assertEqual(str(value), '017f22e2-79b0-7cc3-98c4-dc0c0c07398f')
        self.assertEqual(value.version, 7)
        self.assertEqual(value.variant, uuid.RFC_4122)
        self.assertEqual(value.int >> 80, timestamp)
        entropy.assert_called_once_with(74)

    def test_same_millisecond_fallback_generates_distinct_identifiers(self):
        timestamp = 1_800_000_000_000
        with patch.object(ids.uuid, 'uuid7', None, create=True), patch.object(ids.time, 'time_ns', return_value=timestamp * 1_000_000):
            values = {ids.uuid7() for _ in range(1000)}
        self.assertEqual(len(values), 1000)
        self.assertTrue(all(value.version == 7 and value.variant == uuid.RFC_4122 and value.int >> 80 == timestamp for value in values))

    def test_native_uuid7_is_used_when_available(self):
        expected = uuid.UUID('017f22e2-79b0-7cc3-98c4-dc0c0c07398f')
        with patch.object(ids.uuid, 'uuid7', return_value=expected, create=True) as native, patch.object(ids.secrets, 'randbits') as entropy:
            self.assertEqual(ids.uuid7(), expected)
        native.assert_called_once_with()
        entropy.assert_not_called()

    def test_all_generated_model_uuid_fields_use_uuid7_and_keep_explicit_ids(self):
        checked = 0
        legacy = uuid.uuid4()
        for model in apps.get_models():
            for field in model._meta.local_fields:
                if not isinstance(field, models.UUIDField) or not field.has_default():
                    continue
                with self.subTest(model=model._meta.label, field=field.name):
                    self.assertIs(field.default, ids.uuid7)
                    self.assertEqual(field.get_default().version, 7)
                    self.assertEqual(getattr(model(**{field.name: legacy}), field.name), legacy)
                    checked += 1
        self.assertGreater(checked, 60)

    def test_default_migrations_update_state_without_rewriting_existing_rows(self):
        loader = MigrationLoader(None)
        checked = 0
        for (_, name), migration in loader.disk_migrations.items():
            if not name.endswith('_uuid7_identifiers'):
                continue
            for operation in migration.operations:
                self.assertIsInstance(operation, SeparateDatabaseAndState)
                self.assertEqual(operation.database_operations, [])
                for state_operation in operation.state_operations:
                    self.assertIs(state_operation.field.default, ids.uuid7)
                    checked += 1
        self.assertEqual(checked, 77)
