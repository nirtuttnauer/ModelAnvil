"""Acceptance and unit tests for WP-12 RAG implementation, evaluation metrics, pipeline, and cluster explorer."""
import hashlib
import uuid
from django.test import TestCase

from modelanvil.artifacts.models import DeletionTombstone
from modelanvil.identity.models import Tenant
from modelanvil.rag.explorer import ClusterExplorer
from modelanvil.rag.metrics import (
    compute_all_retrieval_metrics,
    hit_at_k,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from modelanvil.rag.models import (
    DocumentChunk,
    EmbeddingSpace,
    IndexVersion,
    KnowledgeBase,
    ProjectionArtifact,
    QueryTrace,
    SourceDocument,
)
from modelanvil.rag.embedding_model import MODEL_ID, REVISION
from modelanvil.rag.pipeline import RAGPipeline
from modelanvil.rag.retrieval import RetrievalEngine


def fake_embed_query(query: str, dimension: int) -> list[float]:
    """Deterministic stand-in. Production retrieval does not call this."""
    digest = hashlib.sha256(query.encode("utf-8")).digest()
    vec = [(digest[i % len(digest)] / 255.0) * 2.0 - 1.0 for i in range(dimension)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm else vec


class RetrievalMetricsAcceptanceTests(TestCase):
    """PRD Section 17 & TECH-023: Hand-scored deterministic retrieval metrics."""

    def test_hand_scored_acceptance_fixtures(self):
        """Verify the exact official hand-scored acceptance fixtures from the specification:

        Relevant IDs: {A, B, C}. Retrieved: [B, X, A]. K = 3.
        Recall = 2/3, Precision = 2/3, Hit = 1.0, MRR = 1.0.
        """
        relevant = {"A", "B", "C"}
        retrieved = ["B", "X", "A"]

        r = recall_at_k(retrieved, relevant, k=3)
        p = precision_at_k(retrieved, relevant, k=3)
        h = hit_at_k(retrieved, relevant, k=3)
        m = mrr_at_k(retrieved, relevant, k=3)

        self.assertAlmostEqual(r, 2.0 / 3.0, places=3)
        self.assertAlmostEqual(p, 2.0 / 3.0, places=3)
        self.assertEqual(h, 1.0)
        self.assertEqual(m, 1.0)

        # Single result B at K = 3
        retrieved_single = ["B"]
        r_single = recall_at_k(retrieved_single, relevant, k=3)
        p_single = precision_at_k(retrieved_single, relevant, k=3)
        self.assertAlmostEqual(r_single, 1.0 / 3.0, places=3)
        self.assertAlmostEqual(p_single, 1.0 / 3.0, places=3)  # Denominator is strictly 3!

    def test_unjudged_queries_yield_na(self):
        """Unlabeled / unjudged queries must yield None (N/A) rather than a fabricated score."""
        r_na = recall_at_k(["A", "B"], relevant_ids=set(), k=3)
        self.assertIsNone(r_na)

        ndcg_na = ndcg_at_k(["A", "B"], graded_relevance={}, k=3)
        self.assertIsNone(ndcg_na)

    def test_ndcg_graded_relevance(self):
        """Graded relevance nDCG@K calculation."""
        grades = {"A": 3.0, "B": 2.0, "C": 1.0}
        # Perfect ordering
        score_perfect = ndcg_at_k(["A", "B", "C"], grades, k=3)
        self.assertEqual(score_perfect, 1.0)

        # Suboptimal ordering
        score_suboptimal = ndcg_at_k(["C", "B", "A"], grades, k=3)
        self.assertLess(score_suboptimal, 1.0)
        self.assertGreater(score_suboptimal, 0.5)


class RAGPipelineAndRetrievalTests(TestCase):
    """PRD Scenario 14: All retrieval modes, query serving, citations, abstention, and revocation/tombstone isolation."""

    def setUp(self):
        self.tenant = Tenant.objects.create(slug="rag-test-tenant", name="RAG Test Tenant")
        self.tenant_id = self.tenant.tenant_id

        self.kb = KnowledgeBase.objects.create(
            tenant_id=self.tenant_id,
            name="Quantum Computing Corpus",
            description="Reference corpus on quantum gates and hardware",
        )

        self.space = EmbeddingSpace.objects.create(
            tenant_id=self.tenant_id,
            name="bge-small-en-v1.5",
            model_name="bge-small-en-v1.5",
            dimension=4,  # 4-dimensional for simple testing
        )

        self.index = IndexVersion.objects.create(
            tenant_id=self.tenant_id,
            knowledge_base=self.kb,
            embedding_space=self.space,
            revision_no=1,
            adapter_type=IndexVersion.AdapterType.HYBRID,
        )

        # Create source documents and chunks
        self.doc1 = SourceDocument.objects.create(
            tenant_id=self.tenant_id,
            knowledge_base=self.kb,
            title="Qubit Superposition Guide",
            source_uri="s3://corpus/qubits.md",
            content="Qubits can exist in a superposition of states zero and one simultaneously.",
            content_hash=hashlib.sha256(b"qubits").hexdigest(),
        )
        self.chunk1 = DocumentChunk.objects.create(
            tenant_id=self.tenant_id,
            document=self.doc1,
            chunk_index=0,
            text="Qubits can exist in a superposition of states zero and one simultaneously.",
            content_hash=hashlib.sha256(b"qubits-chunk").hexdigest(),
            token_count=12,
            embedding=[0.9, 0.1, 0.0, 0.0],  # Close to query
        )

        self.doc2 = SourceDocument.objects.create(
            tenant_id=self.tenant_id,
            knowledge_base=self.kb,
            title="Quantum Entanglement Foundations",
            source_uri="s3://corpus/entanglement.md",
            content="Entangled pairs exhibit non-local correlations measuring Bell inequalities.",
            content_hash=hashlib.sha256(b"entanglement").hexdigest(),
        )
        self.chunk2 = DocumentChunk.objects.create(
            tenant_id=self.tenant_id,
            document=self.doc2,
            chunk_index=0,
            text="Entangled pairs exhibit non-local correlations measuring Bell inequalities.",
            content_hash=hashlib.sha256(b"entanglement-chunk").hexdigest(),
            token_count=10,
            embedding=[0.0, 0.8, 0.5, 0.1],
        )

        self.doc_secret = SourceDocument.objects.create(
            tenant_id=self.tenant_id,
            knowledge_base=self.kb,
            title="Confidential Quantum Hardware Lab",
            source_uri="s3://corpus/confidential.md",
            content="Proprietary dilution refrigerator temperature logs and microwave lines.",
            content_hash=hashlib.sha256(b"confidential").hexdigest(),
        )
        self.chunk_secret = DocumentChunk.objects.create(
            tenant_id=self.tenant_id,
            document=self.doc_secret,
            chunk_index=0,
            text="Proprietary dilution refrigerator temperature logs and microwave lines.",
            content_hash=hashlib.sha256(b"confidential-chunk").hexdigest(),
            token_count=10,
            embedding=[0.1, 0.1, 0.9, 0.1],
        )

    def test_all_retrieval_modes(self):
        """TECH-022: Lexical, dense, and hybrid (RRF) modes execute with valid scoring."""
        engine = RetrievalEngine(self.index)

        # 1. Lexical retrieval
        lex_results = engine.retrieve_lexical("superposition states", top_k=2)
        self.assertGreaterEqual(len(lex_results), 1)
        self.assertEqual(lex_results[0].chunk_id, str(self.chunk1.chunk_id))

        # 2. Dense retrieval
        dense_results = engine.retrieve_dense([0.9, 0.1, 0.0, 0.0], top_k=2)
        self.assertGreaterEqual(len(dense_results), 1)
        self.assertEqual(dense_results[0].chunk_id, str(self.chunk1.chunk_id))

        # 3. Hybrid retrieval (RRF)
        hybrid_results = engine.retrieve_hybrid("superposition", [0.9, 0.1, 0.0, 0.0], top_k=2)
        self.assertGreaterEqual(len(hybrid_results), 1)
        self.assertEqual(hybrid_results[0].chunk_id, str(self.chunk1.chunk_id))
        self.assertGreater(hybrid_results[0].score, 0.0)

    def test_incompatible_embedding_dimension_blocked(self):
        """TECH-022: Incompatible dimensions fail closed before query execution."""
        engine = RetrievalEngine(self.index)
        with self.assertRaises(ValueError):
            engine.retrieve_dense([0.1, 0.2], top_k=2)  # 2d instead of declared 4d

    def test_permission_revocation_and_tombstone_exclusion(self):
        """TECH-024 / PRD Scenario 14: Revoked access or DeletionTombstones immediately purge chunks from search."""
        engine = RetrievalEngine(self.index)

        # Initial search returns chunk_secret
        results_before = engine.retrieve_dense([0.1, 0.1, 0.9, 0.1], top_k=3)
        self.assertTrue(any(r.chunk_id == str(self.chunk_secret.chunk_id) for r in results_before))

        # Revoke doc_secret
        self.doc_secret.is_revoked = True
        self.doc_secret.save()

        # Immediate exclusion check
        results_after_revocation = engine.retrieve_dense([0.1, 0.1, 0.9, 0.1], top_k=3)
        self.assertFalse(any(r.chunk_id == str(self.chunk_secret.chunk_id) for r in results_after_revocation))

        # Re-enable doc_secret, then create DeletionTombstone
        self.doc_secret.is_revoked = False
        self.doc_secret.save()

        DeletionTombstone.objects.create(
            tenant_id=self.tenant_id,
            resource_type="document",
            resource_id=str(self.doc_secret.doc_id),
            reason="GDPR deletion",
        )

        results_after_tombstone = engine.retrieve_dense([0.1, 0.1, 0.9, 0.1], top_k=3)
        self.assertFalse(any(r.chunk_id == str(self.chunk_secret.chunk_id) for r in results_after_tombstone))

    def test_pipeline_query_serving_citations_and_abstention(self):
        """PRD Scenario 14: Citations preserved, explicit abstention on low relevance, and trace audit."""
        pipeline = RAGPipeline(self.index, abstention_threshold=0.01)

        # 1. Answer with citation
        trace = pipeline.answer_query("qubits superposition", mode="lexical")
        self.assertFalse(trace.abstained)
        self.assertIn("Qubit Superposition Guide", trace.answer)
        self.assertGreaterEqual(len(trace.citations), 1)
        self.assertEqual(trace.citations[0]["chunk_id"], str(self.chunk1.chunk_id))
        self.assertGreater(trace.latency_ms, 0.0)

        # 2. Irrelevant query -> Abstention
        pipeline_strict = RAGPipeline(self.index, abstention_threshold=0.99)
        trace_abstained = pipeline_strict.answer_query("cooking lasagna recipe", mode="lexical")
        self.assertTrue(trace_abstained.abstained)
        self.assertIn("I do not have sufficient authorized evidence", trace_abstained.answer)
        self.assertEqual(len(trace_abstained.citations), 0)

        # 3. Redact trace
        self.doc1.is_revoked = True
        self.doc1.save()
        pipeline.redact_trace(trace)
        self.assertTrue(trace.redacted)
        self.assertIn("REDACTED", trace.supplied_context)

    def test_fake_embed_query_stays_out_of_production(self):
        vec = fake_embed_query("qubits superposition", self.space.dimension)
        self.assertEqual(len(vec), self.space.dimension)
        self.assertAlmostEqual(sum(x * x for x in vec), 1.0, places=6)
        self.assertFalse(hasattr(RAGPipeline, "pseudo_embed_query"))
        pipeline = RAGPipeline(self.index)
        with self.assertRaises(ValueError):
            pipeline.answer_query("qubits superposition", mode="dense")
        with self.assertRaises(ValueError):
            pipeline.answer_query("qubits superposition", mode="hybrid")

    def test_embedding_model_revision_is_pinned(self):
        self.assertEqual(MODEL_ID, "sentence-transformers/all-MiniLM-L6-v2")
        self.assertEqual(len(REVISION), 40)
        int(REVISION, 16)


class ClusterExplorerTests(TestCase):
    """PRD Scenario 15 & TECH-025: Saved projections, original-space neighbors, table equivalent, and tenant isolation."""

    def setUp(self):
        self.tenant_a = Tenant.objects.create(slug="tenant-a", name="Tenant A")
        self.tenant_b = Tenant.objects.create(slug="tenant-b", name="Tenant B")

        self.kb_a = KnowledgeBase.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            name="Org A Corpus",
        )
        self.space_a = EmbeddingSpace.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            name="space-a",
            dimension=4,
        )
        self.index_a = IndexVersion.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            knowledge_base=self.kb_a,
            embedding_space=self.space_a,
            revision_no=1,
        )

        self.doc_a = SourceDocument.objects.create(
            tenant_id=self.tenant_a.tenant_id,
            knowledge_base=self.kb_a,
            title="Doc A1",
            source_uri="uri-a1",
            content="Content A1",
            content_hash="hash-a1",
        )
        self.chunks_a = []
        for i in range(5):
            c = DocumentChunk.objects.create(
                tenant_id=self.tenant_a.tenant_id,
                document=self.doc_a,
                chunk_index=i,
                text=f"Chunk A-{i}",
                content_hash=f"hash-chunk-a-{i}",
                token_count=10,
                embedding=[0.2 * i, 0.1, 0.5, 0.2],
            )
            self.chunks_a.append(c)

    def test_saved_projection_reopens_without_recomputing(self):
        """TECH-025: Saved projection coordinates persist and reopen identically."""
        explorer = ClusterExplorer(self.index_a)
        artifact = explorer.build_and_save_projection(method="umap", num_clusters=2)

        self.assertEqual(artifact.total_points, 5)
        self.assertEqual(len(artifact.coordinates), 5)

        # Reopen from DB
        reopened = ProjectionArtifact.objects.get(artifact_id=artifact.artifact_id)
        self.assertEqual(reopened.coordinates, artifact.coordinates)
        self.assertEqual(reopened.method, "umap")

    def test_original_space_neighbors(self):
        """TECH-025: Nearest neighbors use declared original embedding space, not 2D plot distance."""
        explorer = ClusterExplorer(self.index_a)
        target = self.chunks_a[0]

        neighbors = explorer.get_original_space_neighbors(str(target.chunk_id), k=2)
        self.assertEqual(len(neighbors), 2)
        self.assertIn("similarity", neighbors[0])
        # Neighbors are sorted by original cosine similarity descending
        self.assertGreaterEqual(neighbors[0]["similarity"], neighbors[1]["similarity"])

    def test_query_overlay_and_table_export(self):
        """PRD Scenario 15: Query overlay and accessible table equivalent."""
        explorer = ClusterExplorer(self.index_a)
        artifact = explorer.build_and_save_projection(method="pca", num_clusters=2)

        retrieved_ids = [str(self.chunks_a[0].chunk_id)]
        relevant_ids = [str(self.chunks_a[0].chunk_id), str(self.chunks_a[1].chunk_id)]

        overlay = explorer.overlay_query_and_relevance(
            artifact=artifact,
            query="test query",
            retrieved_ids=retrieved_ids,
            relevant_ids=relevant_ids,
        )

        self.assertIn("query_point", overlay)
        self.assertEqual(overlay["retrieved_count"], 1)
        self.assertEqual(overlay["relevant_count"], 2)

        # Accessible table equivalent
        table = explorer.export_accessible_table(artifact)
        self.assertEqual(len(table), 5)
        self.assertIn("document_title", table[0])
        self.assertIn("cluster_name", table[0])
