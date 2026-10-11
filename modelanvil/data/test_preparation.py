"""Behavioral tests for the bounded, pure envelope preparation kernel."""
import copy
import hashlib
import importlib
import importlib.util
import json
import traceback
import uuid

from django.test import SimpleTestCase


def envelope(number=1, group="source-A"):
    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.UUID(int=number)),
        "source_group_id": group,
        "blocks": [
            {"block_id": "text", "type": "text", "text": "  Original\ntext  "},
            {"block_id": "json", "type": "json", "value": {"nested": [1, None, True]}},
        ],
        "provenance": {
            "source_snapshot_ref": "snapshot-1",
            "source_record_key": str(number),
            "content_sha256": "a" * 64,
        },
    }


class PreparationTests(SimpleTestCase):
    def prepare(self, documents, **kwargs):
        name = "modelanvil.data.preparation"
        self.assertIsNotNone(
            importlib.util.find_spec(name),
            "Missing feature: modelanvil.data.preparation.prepare_envelopes",
        )
        module = importlib.import_module(name)
        self.assertTrue(callable(getattr(module, "prepare_envelopes", None)),
                        "Missing feature: prepare_envelopes must be callable")
        return module.prepare_envelopes(documents, **kwargs)

    def test_prepares_exact_recipe_and_grouped_ordered_independent_rows(self):
        documents = [envelope(i + 1, f"source-{i % 40}-日本語") for i in range(80)]
        original = copy.deepcopy(documents)
        options = dict(split_seed="seed-λ", validation_percent=23, test_percent=17)
        result = self.prepare(iter(documents), **options)
        recipe = {"algorithm": "source_group_sha256_v1", "seed": "seed-λ",
                  "validation_percent": 23, "test_percent": 17}
        digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        expected = {"train": [], "validation": [], "test": []}
        for row in documents:
            payload = json.dumps(["seed-λ", row["source_group_id"]], ensure_ascii=False,
                                 separators=(",", ":"), allow_nan=False).encode("utf-8")
            bucket = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % 100
            split = "test" if bucket < 17 else "validation" if bucket < 40 else "train"
            expected[split].append(row["sample_id"])
        self.assertTrue(all(expected.values()))
        self.assertEqual(result, {
            "schema_version": "1.0", "recipe": recipe, "recipe_digest": digest,
            "rows": original, "split_manifest": expected,
            "row_count": 80, "source_group_count": 40,
        })
        self.assertEqual(result, self.prepare(documents, **options))
        reversed_result = self.prepare(reversed(documents), **options)
        self.assertEqual(reversed_result["rows"], list(reversed(original)))
        for split, ids in expected.items():
            self.assertEqual(reversed_result["split_manifest"][split], list(reversed(ids)))
        self.assertEqual(reversed_result["recipe_digest"], digest)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        documents[0]["blocks"][1]["value"]["nested"].append("input mutation")
        self.assertEqual(result["rows"], original)
        result["rows"][1]["blocks"][1]["value"]["nested"].append("result mutation")
        self.assertEqual(documents[1], original[1])
        self.assertEqual(result["rows"][0], original[0])

    def test_rejects_invalid_options_before_consuming_input(self):
        cases = [
            {"split_seed": value} for value in (None, 0, False, [], {})
        ] + [
            {name: value}
            for name in ("validation_percent", "test_percent")
            for value in (True, False, -1, 1.5, "10", None, 100)
        ] + [
            {"validation_percent": 50, "test_percent": 50},
            {"validation_percent": 90, "test_percent": 11},
        ] + [{"max_rows": value} for value in (True, False, 0, -1, 1.0, "1", None)]
        for options in cases:
            with self.subTest(options=options):
                consumed = []

                def documents():
                    consumed.append(True)
                    yield envelope()

                with self.assertRaises(ValueError):
                    self.prepare(documents(), **options)
                self.assertEqual(consumed, [])

    def test_rejects_empty_input(self):
        for documents in ([], iter(())):
            with self.subTest(documents=type(documents)):
                with self.assertRaises(ValueError):
                    self.prepare(documents)

    def test_accepts_exact_bound_and_stops_at_first_overflow_row(self):
        documents = [envelope(i + 1) for i in range(5)]
        self.assertEqual(self.prepare(iter(documents[:2]), max_rows=2)["row_count"], 2)
        consumed = []

        def bounded_probe():
            for document in documents:
                consumed.append(document["sample_id"])
                yield document

        with self.assertRaises(ValueError):
            self.prepare(bounded_probe(), max_rows=2)
        self.assertEqual(consumed, [row["sample_id"] for row in documents[:3]])
        # Overflow is rejected before trying to validate the sentinel row.
        with self.assertRaises(ValueError):
            self.prepare([envelope(), object()], max_rows=1)

    def assert_rejected_safely(self, documents, **options):
        try:
            self.prepare(documents, **options)
        except ValueError as exc:
            self.assertNotIn("PRIVATE_MARKER", str(exc))
            self.assertIsNone(exc.__cause__)
            self.assertNotIn("PRIVATE_MARKER", "".join(traceback.format_exception(exc)))
            return
        self.fail("Invalid envelopes must raise a sanitized ValueError")

    def test_rejects_schema_invalid_envelopes(self):
        mutations = [
            lambda row: row.pop("provenance"),
            lambda row: row.update(schema_version="PRIVATE_MARKER"),
            lambda row: row.update(source_group_id=""),
            lambda row: row.update(blocks=[]),
            lambda row: row.update(unexpected="PRIVATE_MARKER"),
            lambda row: row["blocks"][0].pop("text"),
            lambda row: row["provenance"].update(content_sha256="PRIVATE_MARKER"),
            lambda row: row["blocks"][0].update(location={"char_start": 0}),
            lambda row: row["blocks"][0].update(type="PRIVATE_MARKER"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                row = envelope()
                mutate(row)
                self.assert_rejected_safely([row])
        for value in (None, "PRIVATE_MARKER", [], 1):
            with self.subTest(root_type=type(value)):
                self.assert_rejected_safely([value])

    def test_requires_canonical_lowercase_uuid_sample_ids(self):
        canonical = "abcdefab-cdef-4abc-8def-abcdefabcdef"
        row = envelope()
        row["sample_id"] = canonical
        self.assertEqual(self.prepare([row])["rows"][0]["sample_id"], canonical)
        for value in (canonical.upper(), canonical.replace("-", ""), "{" + canonical + "}",
                      "urn:uuid:" + canonical, " " + canonical, canonical + " ",
                      "PRIVATE_MARKER", "", None, 7):
            with self.subTest(sample_id=value):
                invalid = envelope()
                invalid["sample_id"] = value
                self.assert_rejected_safely([invalid])

    def test_rejects_duplicate_ids_without_deduplicating_content(self):
        first = envelope(group="source-one")
        duplicate = envelope(group="source-two")
        self.assert_rejected_safely([first, duplicate])
        duplicate["sample_id"] = envelope(2)["sample_id"]
        duplicate["provenance"] = copy.deepcopy(first["provenance"])
        self.assertEqual(self.prepare([first, duplicate])["rows"], [first, duplicate])

    def test_rejects_non_json_and_nonfinite_nested_values(self):
        cyclic = []
        cyclic.append(cyclic)

        class PrivateObject:
            def __repr__(self):
                return "PRIVATE_MARKER"

        values = [float("nan"), float("inf"), -float("inf"), {1: "PRIVATE_MARKER"},
                  {None: "PRIVATE_MARKER"}, ("PRIVATE_MARKER",), {"PRIVATE_MARKER"},
                  b"PRIVATE_MARKER", PrivateObject(), cyclic]
        for value in values:
            for container in ("metadata", "value"):
                with self.subTest(value_type=type(value), container=container):
                    row = envelope()
                    if container == "metadata":
                        row["metadata"] = {"nested": [value]}
                    else:
                        row["blocks"][1]["value"] = {"nested": [value]}
                    self.assert_rejected_safely([row])
        row = envelope()
        row["blocks"][0]["location"] = {
            "coordinates": [1.0, float("inf")], "coordinate_system": "pixels"}
        self.assert_rejected_safely([row])

    def test_iteration_and_encoding_failures_are_sanitized(self):
        self.assert_rejected_safely(None)

        def broken_iterator():
            yield envelope()
            raise RuntimeError("PRIVATE_MARKER")

        self.assert_rejected_safely(broken_iterator())
        self.assert_rejected_safely([envelope()], split_seed="PRIVATE_MARKER\ud800")
        self.assert_rejected_safely([envelope(group="PRIVATE_MARKER\ud800")])

    def test_defaults_and_empty_seed_zero_percentages(self):
        default = self.prepare([envelope()])
        self.assertEqual(default["recipe"], {"algorithm": "source_group_sha256_v1",
                         "seed": "0", "validation_percent": 10, "test_percent": 10})
        result = self.prepare([envelope()], split_seed="", validation_percent=0, test_percent=0)
        self.assertEqual(result["recipe"]["seed"], "")
        self.assertEqual(result["split_manifest"], {
            "train": [envelope()["sample_id"]], "validation": [], "test": []})
        self.assertEqual(result["source_group_count"], 1)


def pii_envelope(number, group="source-pii"):
    row = envelope(number, group)
    row["blocks"] = [
        {"block_id": "text", "type": "text",
         "text": f"Record {number}: contact alice{number}@example.com, ssn 123-45-6789."},
    ]
    return row


class FeatureOptionTests(SimpleTestCase):
    def prepare(self, documents, **kwargs):
        from modelanvil.data.preparation import prepare_envelopes
        return prepare_envelopes(documents, **kwargs)

    def test_default_options_keep_historical_shape(self):
        result = self.prepare([envelope(1), envelope(2)])
        self.assertEqual(
            set(result),
            {"schema_version", "recipe", "recipe_digest", "rows",
             "split_manifest", "row_count", "source_group_count"})
        self.assertNotIn("dropped", result)
        self.assertNotIn("report", result)

    def test_invalid_feature_options_raise_before_consumption(self):
        cases = [
            {"detect": "yes"}, {"detect": {"privacy": "yes"}},
            {"detect": {"min_text_chars": -1}}, {"detect": {"min_text_chars": 1.5}},
            {"dedup": "yes"}, {"dedup": {"exact": 1}},
            {"protected": {"digests": "nope"}},
            {"protected": {"digests": ["x" * 63]}},
            {"protected": {"simhashes": [-1]}},
            {"near_threshold": -1}, {"near_threshold": 1.5},
            {"min_text_chars": -1},
        ]
        for options in cases:
            with self.subTest(options=options):
                consumed = []

                def documents():
                    consumed.append(True)
                    yield envelope()

                with self.assertRaises(ValueError):
                    self.prepare(documents(), **options)
                self.assertEqual(consumed, [])

    def test_detect_drops_privacy_and_quality_samples_with_reasons(self):
        clean = envelope(1)
        pii = pii_envelope(2)
        short = envelope(3, group="source-q")
        short["blocks"] = [{"block_id": "text", "type": "text", "text": "hi"}]
        repetitive = envelope(4, group="source-q")
        repetitive["blocks"] = [{"block_id": "text", "type": "text", "text": "xy" * 20}]
        result = self.prepare([clean, pii, short, repetitive], detect=True)
        self.assertEqual(result["row_count"], 1)
        self.assertEqual([row["sample_id"] for row in result["rows"]], [clean["sample_id"]])
        dropped = {entry["sample_id"]: entry["reasons"] for entry in result["dropped"]}
        self.assertEqual(dropped[pii["sample_id"]], ["pii.email", "pii.ssn"])
        self.assertEqual(dropped[short["sample_id"]], ["quality.short"])
        self.assertEqual(dropped[repetitive["sample_id"]], ["quality.repetitive"])
        self.assertEqual(result["report"], {
            "input_rows": 4, "kept": 1, "dropped": 3,
            "drop_reason_counts": {"pii.email": 1, "pii.ssn": 1,
                                   "quality.short": 1, "quality.repetitive": 1}})
        for split in result["split_manifest"].values():
            self.assertNotIn(pii["sample_id"], split)

    def test_detect_false_and_selective_detect(self):
        pii = pii_envelope(2)
        clean = envelope(1)
        result = self.prepare([pii, clean], detect=False)
        self.assertEqual(result["row_count"], 2)
        # An explicit opt-out is recorded in the recipe (and its digest),
        # unlike the historical default which omits the key entirely.
        self.assertEqual(result["recipe"]["detect"],
                         {"privacy": False, "quality": False, "min_text_chars": 8})
        self.assertNotEqual(result["recipe_digest"],
                            self.prepare([pii, clean])["recipe_digest"])
        result = self.prepare([pii, clean], detect={"privacy": True, "quality": False})
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["dropped"][0]["reasons"], ["pii.email", "pii.ssn"])
        result = self.prepare([pii, clean], detect={"privacy": False, "quality": True})
        self.assertEqual(result["row_count"], 2)

    def test_exact_dedup_keeps_first_occurrence(self):
        first = envelope(1, group="source-d")
        twin = envelope(2, group="source-d")
        twin["blocks"] = copy.deepcopy(first["blocks"])
        other = envelope(3, group="source-d")
        other["blocks"] = [{"block_id": "text", "type": "text", "text": "unique content here"}]
        result = self.prepare([first, twin, other], dedup=True)
        self.assertEqual([row["sample_id"] for row in result["rows"]],
                          [first["sample_id"], other["sample_id"]])
        self.assertEqual(result["dropped"][0], {
            "sample_id": twin["sample_id"], "reasons": ["duplicate.exact"]})
        self.assertEqual(result["report"]["drop_reason_counts"], {"duplicate.exact": 1})

    def test_near_dedup_groups_similar_content(self):
        base_text = "The anvil compiles the context workbench for the evaluation run."
        first = envelope(1, group="source-n")
        first["blocks"] = [{"block_id": "text", "type": "text", "text": base_text}]
        near = envelope(2, group="source-n")
        near["blocks"] = [{"block_id": "text", "type": "text", "text": base_text + "!"}]
        far = envelope(3, group="source-n")
        far["blocks"] = [{"block_id": "text", "type": "text",
                          "text": "Tomato gardening requires patience and regular watering."}]
        result = self.prepare([first, near, far], dedup={"exact": False, "near": True},
                              near_threshold=8)
        self.assertEqual([row["sample_id"] for row in result["rows"]],
                          [first["sample_id"], far["sample_id"]])
        self.assertEqual(result["dropped"][0]["reasons"], ["duplicate.near"])

    def test_dropped_rows_never_serve_as_duplicate_references(self):
        # A sample dropped for quality must not anchor a near-duplicate group:
        # its near twin (one character changed) is kept, not dropped as
        # duplicate.near. The twin is within the threshold of the dropped
        # anchor, so a reference set that included the anchor would drop it.
        anchor = envelope(1, group="source-x")
        anchor["blocks"] = [{"block_id": "text", "type": "text", "text": "abcd" * 40}]
        twin = envelope(2, group="source-x")
        twin["blocks"] = [{"block_id": "text", "type": "text",
                           "text": "abcd" * 39 + "abce"}]
        result = self.prepare([anchor, twin], detect=True, dedup=True, near_threshold=8)
        self.assertEqual(result["dropped"][0]["reasons"], ["quality.repetitive"])
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["rows"][0]["sample_id"], twin["sample_id"])

    def test_protected_overlap_drops_from_all_splits(self):
        protected = envelope(50, group="protected-set")
        protected["blocks"] = [{"block_id": "text", "type": "text",
                                "text": "Protected evaluation question number one."}]
        leak = envelope(1, group="source-l")
        leak["blocks"] = [{"block_id": "text", "type": "text",
                           "text": "Protected evaluation question number one."}]
        clean = envelope(2, group="source-l")
        clean["blocks"] = [{"block_id": "text", "type": "text", "text": "Ordinary training text."}]
        from modelanvil.data.detection import build_protected_set
        protected_set = build_protected_set([protected])
        result = self.prepare([leak, clean], protected=protected_set)
        self.assertEqual([row["sample_id"] for row in result["rows"]], [clean["sample_id"]])
        self.assertEqual(result["dropped"][0]["reasons"], ["overlap.protected_exact"])
        # Recipe records counts, never protected content.
        self.assertEqual(result["recipe"]["protected"]["exact_count"], 1)
        self.assertNotIn("Protected evaluation", json.dumps(result["recipe"]))

    def test_protected_accepts_envelope_iterable(self):
        protected = envelope(50)
        protected["blocks"] = [{"block_id": "text", "type": "text",
                                "text": "Protected evaluation question number one."}]
        leak = envelope(1)
        leak["blocks"] = copy.deepcopy(protected["blocks"])
        result = self.prepare([leak], protected=[protected])
        self.assertEqual(result["dropped"][0]["reasons"], ["overlap.protected_exact"])

    def test_all_dropped_input_is_not_an_error(self):
        result = self.prepare([pii_envelope(1), pii_envelope(2)], detect=True)
        self.assertEqual(result["row_count"], 0)
        self.assertEqual(len(result["dropped"]), 2)
        self.assertEqual(result["split_manifest"], {"train": [], "validation": [], "test": []})

    def test_recipe_digest_changes_with_features(self):
        base = self.prepare([envelope(1), envelope(2)])
        deduped = self.prepare([envelope(1), envelope(2)], dedup=True)
        self.assertNotEqual(base["recipe_digest"], deduped["recipe_digest"])
        self.assertNotIn("dedup", base["recipe"])
        self.assertEqual(deduped["recipe"]["dedup"],
                         {"exact": True, "near": True, "near_threshold": 3})
        same_again = self.prepare([envelope(1), envelope(2)], dedup=True)
        self.assertEqual(deduped["recipe_digest"], same_again["recipe_digest"])

    def test_max_rows_bounds_input_consumption_with_drops(self):
        documents = [pii_envelope(i + 1) for i in range(5)]
        with self.assertRaises(ValueError):
            self.prepare(iter(documents), detect=True, max_rows=2)
        # Dropped rows still count against the input bound.
        result = self.prepare([pii_envelope(1), pii_envelope(2)], detect=True, max_rows=2)
        self.assertEqual(result["report"]["input_rows"], 2)
