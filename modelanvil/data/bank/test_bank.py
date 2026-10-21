"""Comprehensive test suite for Dataset Bank and SVG starter (WP-06 / TECH-010 / PRD Scenario 11)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from modelanvil.data.bank.catalog import DatasetBankCatalog
from modelanvil.data.bank.downloader import ResumablePresetDownloader
from modelanvil.data.bank.svg_starter import (
    normalize_icon_concept,
    prepare_svg_record,
    prepare_svg_starter_dataset,
)
from modelanvil.data.models import DataSource, SourceSnapshot
from modelanvil.identity.models import Tenant


def _two_revision_catalog(revisions) -> DatasetBankCatalog:
    path = Path(__file__).resolve().parents[3] / "catalog" / "dataset-presets.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for source in data["sources"]:
        if source["id"] == "svg-lucide":
            source["acquisition"]["qualified_revisions"] = list(revisions)
            source["acquisition"]["pinned_revision"] = revisions[-1]
    return DatasetBankCatalog.from_dict(data)


class DatasetBankCatalogTests(TestCase):
    def setUp(self):
        self.catalog = DatasetBankCatalog.load_from_file()

    def test_catalog_loads_all_candidate_manifests(self):
        sources = self.catalog.list_sources()
        self.assertEqual(len(sources), 33)
        self.assertTrue(self.catalog.schema_version in ("1.0", "0.1.0"))
        self.assertGreaterEqual(len(self.catalog.list_presets()), 3)
        self.assertGreaterEqual(len(self.catalog.held_candidates), 2)

    def test_catalog_references_are_unique_and_output_groups_are_consistent(self):
        path = Path(__file__).resolve().parents[3] / "catalog" / "dataset-presets.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        sources = {source["id"]: source for source in data["sources"]}
        self.assertEqual(len(sources), len(data["sources"]))
        groups = {group["id"]: group for group in data["output_groups"]}
        for group_id, group in groups.items():
            self.assertEqual(len(group["source_ids"]), len(set(group["source_ids"])))
            for source_id in group["source_ids"]:
                self.assertIn(source_id, sources)
                self.assertIn(group_id, sources[source_id]["output_group_ids"])
        for source in sources.values():
            for group_id in source["output_group_ids"]:
                self.assertIn(group_id, groups)
                self.assertIn(source["id"], groups[group_id]["source_ids"])
        for preset in data["presets"]:
            self.assertTrue(set(preset["source_ids"]) <= sources.keys())

    def test_expansion_preserves_subset_scope_and_share_alike_opt_in(self):
        smol = self.catalog.get_source("text-smol-magpie-ultra")
        self.assertEqual(smol.fetch["configuration"], "smol-magpie-ultra")
        for source_id in ("text-squad", "text-dolly15k"):
            with self.subTest(source=source_id):
                source = self.catalog.get_source(source_id)
                self.assertEqual(source.eligibility, "opt_in_required")
                for consent in (False, "true", 1):
                    with self.assertRaisesMessage(ValidationError, "share-alike"):
                        self.catalog.preflight_download(
                            source.id, tenant_id="tenant-1", project_policy={"allow_share_alike": consent},
                        )
                self.catalog.preflight_download(
                    source.id, tenant_id="tenant-1", project_policy={"allow_share_alike": True},
                )

    def test_search_svg_returns_curated_candidates(self):
        results = self.catalog.search("svg")
        source_ids = {s.id for s in results}
        self.assertIn("svg-lucide", source_ids)
        self.assertIn("svg-tabler", source_ids)
        self.assertIn("svg-heroicons", source_ids)
        self.assertIn("svg-feather", source_ids)

    def test_only_a_qualified_source_is_acquirable(self):
        qualified = {source.id for source in self.catalog.qualified_sources()}
        self.assertEqual(qualified, {"svg-lucide", "text-smol-magpie-ultra", "text-ultrachat-200k", "text-squad",
            "preference-ultrafeedback-binarized", "tools-glaive-v2", "image-clevr", "audio-vctk",
            "audio-libritts-r", "numeric-iris", "numeric-wine-quality", "math-gsm8k", "code-mbpp", "text-dolly15k"})
        for source in self.catalog.list_sources():
            if source.id in qualified:
                continue
            self.assertFalse(source.acquisition.qualified)
            self.assertFalse(source.acquisition_available)
            self.assertTrue(source.acquisition.blocked_reason)
            with self.assertRaises(ValidationError) as ctx:
                self.catalog.assert_acquirable(source.id)
            self.assertIn("not qualified for acquisition", str(ctx.exception))

    def test_license_eligibility_alone_never_enables_acquisition(self):
        card = self.catalog.get_source("svg-tabler")
        self.assertTrue(card.download_enabled)
        self.assertEqual(card.eligibility, "eligible")
        self.assertFalse(card.acquisition_available)

    def test_qualified_source_declares_pinned_revision_and_evidence(self):
        card = self.catalog.get_source("svg-lucide")
        self.assertTrue(card.acquisition.qualified)
        self.assertTrue(card.acquisition_available)
        self.assertEqual(len(card.acquisition.pinned_revision), 40)
        self.assertIn(card.acquisition.pinned_revision, card.acquisition.qualified_revisions)
        self.assertTrue(card.acquisition.verified_record_digests)
        self.assertGreater(card.acquisition.record_limit, 0)
        self.assertTrue(card.acquisition.evidence.get("checks"))

    def test_held_candidates_excluded_from_eligible_downloads(self):
        # SVG Stack is held due to lack of dataset license declaration
        results = self.catalog.search("svg stack", eligible_only=True)
        self.assertEqual(len(results), 0)

        # Ineligible sources have download_enabled = False
        held_names = [h.name.lower() for h in self.catalog.held_candidates]
        self.assertIn("svg stack", held_names)

    def test_preflight_blocks_held_candidates(self):
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download("svg-stack", tenant_id="tenant-1")
        self.assertIn("held from download", str(ctx.exception))

    def test_preflight_enforces_share_alike_policy(self):
        # OpenMoji is CC-BY-SA-4.0
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "svg-openmoji",
                tenant_id="tenant-1",
                project_policy={"allow_share_alike": False},
            )
        self.assertIn("share-alike", str(ctx.exception))

        # Share-alike opt-in clears the license gate but the source is still
        # unqualified, so acquisition stays refused.
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "svg-openmoji",
                tenant_id="tenant-1",
                project_policy={"allow_share_alike": True},
            )
        self.assertIn("not qualified for acquisition", str(ctx.exception))

    def test_preflight_enforces_gated_credentials(self):
        # xLAM requires credentials acceptance
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "tools-xlam",
                tenant_id="tenant-1",
                project_policy={"gated_credentials_accepted": False},
            )
        self.assertIn("credentials", str(ctx.exception))

        # Accepting credentials does not manufacture a qualification record.
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "tools-xlam",
                tenant_id="tenant-1",
                project_policy={"gated_credentials_accepted": True},
            )
        self.assertIn("not qualified for acquisition", str(ctx.exception))

    def test_preflight_discloses_revision_scope_and_destination_inputs(self):
        result = self.catalog.preflight_download("svg-lucide", tenant_id="tenant-1")
        self.assertEqual(result["status"], "approved")
        self.assertEqual(result["source_revision"], self.catalog.get_source("svg-lucide").acquisition.pinned_revision)
        self.assertEqual(result["scope"]["include_patterns"], ["icons/*.svg"])
        self.assertEqual(result["scope"]["record_limit"], 120)
        self.assertEqual(result["access"]["license_paths"], ["LICENSE"])
        self.assertTrue(result["qualification_evidence"]["verified_record_digests"])
        self.assertFalse(result["access"]["gated"])

    def test_preflight_refuses_an_unqualified_upstream_revision(self):
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "svg-lucide", tenant_id="tenant-1", source_revision="f" * 40,
            )
        self.assertIn("is not qualified", str(ctx.exception))

    def test_preflight_refuses_scope_beyond_the_qualified_bound(self):
        with self.assertRaises(ValidationError) as ctx:
            self.catalog.preflight_download(
                "svg-lucide", tenant_id="tenant-1",
                project_policy={"record_limit": 100000},
            )
        self.assertIn("exceeds the qualified bound", str(ctx.exception))


class SVGStarterPreparationTests(TestCase):
    def test_icon_concept_normalization(self):
        concept, variant = normalize_icon_concept("arrow-right-bold")
        self.assertEqual(concept, "arrow-right")
        self.assertEqual(variant, "bold")

        concept, variant = normalize_icon_concept("check-circle-filled")
        self.assertEqual(concept, "check-circle")
        self.assertEqual(variant, "filled")

        concept, variant = normalize_icon_concept("search-24")
        self.assertEqual(concept, "search")
        self.assertEqual(variant, "size_24")

    def test_svg_render_isolation_and_label_provenance(self):
        # Dangerous SVG with script and XXE
        dirty_svg = (
            '<!DOCTYPE svg SYSTEM "http://malicious.org/xxe.dtd">'
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">'
            '<script>alert("xss")</script>'
            '<path d="M5 12h14"/>'
            '</svg>'
        )
        record = prepare_svg_record(
            source_library="lucide",
            icon_name="arrow-right-outline",
            svg_content=dirty_svg,
        )
        # Raw is preserved
        self.assertEqual(record.svg_raw, dirty_svg)
        # Renderable SVG is sanitized: script and DOCTYPE stripped
        self.assertNotIn("<script", record.svg_clean)
        self.assertNotIn("DOCTYPE", record.svg_clean)
        self.assertIn("<path", record.svg_clean)

        # Label provenance
        self.assertEqual(record.label, "arrow right outline")
        self.assertEqual(record.label_provenance, "filename_derived")
        self.assertEqual(record.license, "ISC AND MIT")

    def test_variant_group_splits_prevent_leakage(self):
        # Prepare 10 concepts with distinct variant geometries
        records = []
        for i in range(10):
            concept = f"icon-{i}"
            for v_idx, variant in enumerate(["outline", "filled", "bold"]):
                records.append({
                    "source_library": "lucide",
                    "icon_name": f"{concept}-{variant}",
                    "svg_content": f'<svg><path d="M{i} {v_idx}" stroke="{variant}"/></svg>',
                })

        dataset = prepare_svg_starter_dataset(
            records, train_ratio=0.8, val_ratio=0.1, test_ratio=0.1
        )
        self.assertEqual(len(dataset.items), 30)

        # Verify that all variants of a concept reside in the EXACT SAME split
        train_concepts = {item.concept_group for item in dataset.splits["train"]}
        val_concepts = {item.concept_group for item in dataset.splits["val"]}
        test_concepts = {item.concept_group for item in dataset.splits["test"]}

        self.assertEqual(len(train_concepts.intersection(val_concepts)), 0)
        self.assertEqual(len(train_concepts.intersection(test_concepts)), 0)
        self.assertEqual(len(val_concepts.intersection(test_concepts)), 0)

    def test_cross_library_deduplication_and_attributions(self):
        identical_svg = '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>'
        records = [
            {"source_library": "feather", "icon_name": "check", "svg_content": identical_svg},
            {"source_library": "lucide", "icon_name": "check", "svg_content": identical_svg},
            {"source_library": "tabler", "icon_name": "unique-tabler", "svg_content": '<svg><path d="M1 1"/></svg>'},
        ]
        dataset = prepare_svg_starter_dataset(records, deduplicate_cross_source=True)

        # One duplicate dropped
        self.assertEqual(dataset.deduplication_summary["deduplicated_count"], 1)
        self.assertEqual(len(dataset.items), 2)

        # Attributions manifest present
        manifest = dataset.attribution_manifest
        self.assertIn("notices", manifest)
        notices = [n["spdx"] for n in manifest["notices"]]
        self.assertTrue(any("MIT" in spdx for spdx in notices))


class PRDScenario11DownloaderJourneyTests(TestCase):
    def setUp(self):
        self.tenant_a = Tenant.objects.create(slug="org-a", name="Organization A")
        self.tenant_b = Tenant.objects.create(slug="org-b", name="Organization B")
        self.downloader = ResumablePresetDownloader()

    def test_interrupted_and_resumed_download_journey(self):
        # Step 1: Initiate the qualified snapshot for Lucide
        snapshot = self.downloader.initiate_download(
            tenant_id=str(self.tenant_a.tenant_id),
            source_id="svg-lucide",
        )
        self.assertEqual(snapshot.state, SourceSnapshot.State.INGESTING)
        self.assertEqual(
            snapshot.source_revision,
            ResumablePresetDownloader().catalog.get_source("svg-lucide").acquisition.pinned_revision,
        )

        chunks = [b"chunk-data-1", b"chunk-data-2", b"chunk-data-3", b"chunk-data-4"]

        # Step 2: Inject interruption after chunk 2
        progress1 = self.downloader.execute_chunked_transfer(
            snapshot, chunks, interrupt_after_chunk=2
        )
        self.assertTrue(progress1.interrupted)
        self.assertFalse(progress1.completed)

        # Snapshot is NOT ready
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, SourceSnapshot.State.INGESTING)
        self.assertGreater(snapshot.detail["bytes_transferred"], 0)

        # Step 3: Resume transfer to completion
        progress2 = self.downloader.execute_chunked_transfer(snapshot, chunks)
        self.assertTrue(progress2.completed)
        self.assertFalse(progress2.interrupted)

        # Snapshot is now READY and immutable
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.state, SourceSnapshot.State.READY)
        self.assertIsNotNone(snapshot.completed_at)
        self.assertTrue(len(snapshot.manifest_digest) == 64)

    def test_unqualified_source_cannot_be_initiated(self):
        with self.assertRaises(ValidationError) as ctx:
            self.downloader.initiate_download(
                tenant_id=str(self.tenant_a.tenant_id), source_id="svg-tabler",
            )
        self.assertIn("not qualified for acquisition", str(ctx.exception))

    def test_unauthorized_cross_organization_cache_denied(self):
        snapshot = self.downloader.initiate_download(
            tenant_id=str(self.tenant_a.tenant_id),
            source_id="svg-lucide",
        )
        chunks = [b"data-1"]
        self.downloader.execute_chunked_transfer(snapshot, chunks)

        # Organization B attempts to access Organization A's snapshot/cache
        with self.assertRaises(PermissionDenied):
            self.downloader.access_snapshot(
                snapshot.snapshot_id,
                requesting_tenant_id=str(self.tenant_b.tenant_id),
            )

    def test_new_upstream_revision_creates_distinct_snapshot(self):
        first_revision, second_revision = "1" * 40, "2" * 40
        downloader = ResumablePresetDownloader(
            _two_revision_catalog([first_revision, second_revision])
        )
        snapshot_v1 = downloader.initiate_download(
            tenant_id=str(self.tenant_a.tenant_id),
            source_id="svg-lucide",
            revision=first_revision,
        )
        downloader.execute_chunked_transfer(snapshot_v1, [b"v1-bytes"])
        snapshot_v1.refresh_from_db()
        self.assertEqual(snapshot_v1.state, SourceSnapshot.State.READY)
        digest_v1 = snapshot_v1.manifest_digest

        # Upstream revision bump, both revisions carrying qualification evidence
        snapshot_v2 = downloader.initiate_download(
            tenant_id=str(self.tenant_a.tenant_id),
            source_id="svg-lucide",
            revision=second_revision,
        )
        downloader.execute_chunked_transfer(snapshot_v2, [b"v2-updated-bytes"])
        snapshot_v2.refresh_from_db()

        self.assertNotEqual(snapshot_v1.snapshot_id, snapshot_v2.snapshot_id)
        self.assertNotEqual(digest_v1, snapshot_v2.manifest_digest)
        # v1 remains unchanged
        snapshot_v1.refresh_from_db()
        self.assertEqual(snapshot_v1.manifest_digest, digest_v1)
