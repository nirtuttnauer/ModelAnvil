"""Compatibility tests for contract schema versions.

Covers ``parse_version``, ``is_compatible``, and ``supported_versions``.
"""

from __future__ import annotations

import unittest

from contracts.versioning import (
    CONTRACTS,
    ContractId,
    ContractVersion,
    is_compatible,
    parse_version,
    supported_versions,
)


class ParseVersionTests(unittest.TestCase):
    def test_major_minor_normalizes_a_missing_patch_to_zero(self):
        parsed = parse_version("1.2")
        self.assertEqual(parsed, ContractVersion(1, 2, 0))
        self.assertEqual(parsed.patch, 0)
        self.assertEqual(parsed, parse_version("1.2.0"))
        self.assertEqual(str(parsed), "1.2.0")

    def test_major_minor_patch_keeps_each_component(self):
        parsed = parse_version("2.3.4")
        self.assertEqual(parsed, ContractVersion(2, 3, 4))
        self.assertEqual((parsed.major, parsed.minor, parsed.patch), (2, 3, 4))

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(parse_version("  1.2  "), ContractVersion(1, 2, 0))
        self.assertEqual(parse_version("\t3.4.5\n"), ContractVersion(3, 4, 5))

    def test_zero_components_are_accepted(self):
        self.assertEqual(parse_version("0.0"), ContractVersion(0, 0, 0))
        self.assertEqual(parse_version("0.0.0"), ContractVersion(0, 0, 0))

    def test_non_strings_raise_value_error(self):
        for value in (None, 1, 1.2, b"1.2", True, False, ["1", "2"], {"version": "1.2"}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    parse_version(value)
                self.assertIn("string", str(caught.exception))

    def test_wrong_arity_raises_value_error(self):
        for value in ("1", "1.2.3.4", "", "1.2.3.4.5", "1.2.3.4.5.6"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    parse_version(value)
                self.assertIn("MAJOR.MINOR", str(caught.exception))

    def test_negative_components_raise_value_error(self):
        for value in ("-1.0", "1.-2", "1.2.-3", "-1.-2.-3", "-1.0.0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    parse_version(value)
                self.assertIn("non-negative", str(caught.exception))

    def test_non_integers_raise_value_error(self):
        for value in ("a.b", "1.two", "1.2.x", "v1.2", "1.2.3rc1", "1.2.", "1..2", ".", ".."):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as caught:
                    parse_version(value)
                self.assertIn("integer", str(caught.exception).lower())


class IsCompatibleTests(unittest.TestCase):
    def test_different_majors_are_incompatible(self):
        pairs = (
            ("2.0", "1.0"),
            ("1.4.1", "2.0.0"),
            (ContractVersion(3, 0, 0), ContractVersion(1, 9, 9)),
            ("1.0", ContractVersion(0, 9, 0)),
        )
        for producer, consumer in pairs:
            with self.subTest(producer=producer, consumer=consumer):
                self.assertFalse(is_compatible(producer, consumer))
                self.assertFalse(is_compatible(producer, consumer, allow_additive=True))
                self.assertFalse(is_compatible(producer, consumer, allow_additive=False))

    def test_same_major_allows_different_minors_when_additive(self):
        pairs = (
            ("1.0", "1.4"),
            ("1.4.2", "1.0.0"),
            (ContractVersion(1, 0, 1), ContractVersion(1, 7, 0)),
            ("1.2.3", "1.2.9"),
        )
        for producer, consumer in pairs:
            with self.subTest(producer=producer, consumer=consumer):
                self.assertTrue(is_compatible(producer, consumer))
                self.assertTrue(is_compatible(producer, consumer, allow_additive=True))

    def test_strict_mode_requires_matching_minors(self):
        self.assertFalse(is_compatible("1.0", "1.1", allow_additive=False))
        self.assertFalse(is_compatible("1.3.0", "1.2.0", allow_additive=False))
        self.assertFalse(
            is_compatible(ContractVersion(2, 1, 0), ContractVersion(2, 0, 0), allow_additive=False)
        )
        self.assertTrue(is_compatible("1.2", "1.2.0", allow_additive=False))
        self.assertTrue(is_compatible("1.2.0", "1.2.9", allow_additive=False))
        self.assertTrue(
            is_compatible(ContractVersion(4, 5, 1), "4.5.8", allow_additive=False)
        )

    def test_malformed_version_raises_value_error(self):
        with self.assertRaises(ValueError):
            is_compatible("nope", "1.0")
        with self.assertRaises(ValueError):
            is_compatible("1.0", None)


class SupportedVersionsTests(unittest.TestCase):
    def test_every_contract_id_returns_its_inclusive_window(self):
        self.assertGreater(len(ContractId.ALL), 0)
        for contract_id in ContractId.ALL:
            with self.subTest(contract_id=contract_id):
                low, high = supported_versions(contract_id)
                window = CONTRACTS[contract_id]
                self.assertEqual(set(window), {"min", "max"})
                self.assertEqual(low, parse_version(window["min"]))
                self.assertEqual(high, parse_version(window["max"]))
                self.assertIsInstance(low, ContractVersion)
                self.assertIsInstance(high, ContractVersion)
                self.assertLessEqual(low, high)
                self.assertEqual(low.patch, parse_version(window["min"]).patch)
                self.assertEqual(high.patch, parse_version(window["max"]).patch)

    def test_unknown_contract_raises_key_error(self):
        for contract_id in ("not-a-contract", "", "sample_envelope", "SAMPLE_ENVELOPE"):
            with self.subTest(contract_id=contract_id):
                with self.assertRaises(KeyError) as caught:
                    supported_versions(contract_id)
                self.assertIn(contract_id, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
