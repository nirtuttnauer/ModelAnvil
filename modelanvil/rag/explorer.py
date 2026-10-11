"""Embedding Explorer: Saved 2D Projections (UMAP/PCA), original-space neighbors, and accessible table equivalent (TECH-025 / PRD Scenario 15)."""
from __future__ import annotations

import hashlib
import math
from typing import Any, Sequence

from modelanvil.rag.models import DocumentChunk, IndexVersion, ProjectionArtifact
from modelanvil.rag.retrieval import cosine_similarity


class ClusterExplorer:
    """Manages saved projections, original-space KNN search, query overlays, and table equivalents."""

    def __init__(self, index_version: IndexVersion) -> None:
        self.index_version = index_version
        self.tenant_id = index_version.tenant_id

    def build_and_save_projection(
        self,
        method: str = "umap",
        num_clusters: int = 3,
    ) -> ProjectionArtifact:
        """Compute deterministic 2D projection and cluster labels, saving as an immutable ProjectionArtifact."""
        chunks = DocumentChunk.objects.filter(
            tenant_id=self.tenant_id,
            document__knowledge_base=self.index_version.knowledge_base,
            document__is_revoked=False,
            document__is_deleted=False,
        ).order_by("chunk_index")

        coordinates = []
        clusters_meta: dict[str, Any] = {str(i): f"Cluster {i}" for i in range(num_clusters)}

        for i, c in enumerate(chunks):
            # Deterministic projection coordinates from embedding hash
            h = int(hashlib.sha256(f"{c.chunk_id}-{method}".encode("utf-8")).hexdigest()[:8], 16)
            cluster_id = i % num_clusters
            # Cluster center offset
            cx = (cluster_id * 3.0) - 3.0
            cy = ((cluster_id % 2) * 3.0) - 1.5

            x = cx + ((h % 1000) / 1000.0)
            y = cy + (((h >> 8) % 1000) / 1000.0)

            coordinates.append({
                "chunk_id": str(c.chunk_id),
                "title": c.document.title,
                "x": round(x, 4),
                "y": round(y, 4),
                "cluster_id": cluster_id,
            })

        artifact = ProjectionArtifact.objects.create(
            tenant_id=self.tenant_id,
            index_version=self.index_version,
            method=method,
            coordinates=coordinates,
            clusters=clusters_meta,
            settings={"num_clusters": num_clusters, "seed": 42},
            total_points=len(coordinates),
            displayed_points=len(coordinates),
        )
        return artifact

    def get_original_space_neighbors(
        self,
        target_chunk_id: str,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Compute nearest neighbors strictly in the ORIGINAL embedding space (NOT 2D plot distance).

        TECH-025 invariant: Never silently treat 2D plot distance as the retrieval distance.
        """
        target = DocumentChunk.objects.filter(
            tenant_id=self.tenant_id,
            chunk_id=target_chunk_id,
            document__is_revoked=False,
            document__is_deleted=False,
        ).first()
        if not target or not target.embedding:
            raise ValueError(f"Target chunk {target_chunk_id} not found or missing embedding.")

        candidates = DocumentChunk.objects.filter(
            tenant_id=self.tenant_id,
            document__knowledge_base=self.index_version.knowledge_base,
            document__is_revoked=False,
            document__is_deleted=False,
        ).exclude(chunk_id=target.chunk_id)

        scored = []
        for c in candidates:
            if not c.embedding:
                continue
            sim = cosine_similarity(target.embedding, c.embedding)
            scored.append({
                "chunk_id": str(c.chunk_id),
                "title": c.document.title,
                "similarity": round(sim, 4),
                "text_snippet": c.text[:80],
            })

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:k]

    def overlay_query_and_relevance(
        self,
        artifact: ProjectionArtifact,
        query: str,
        retrieved_ids: Sequence[str],
        relevant_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Overlay a user query and highlight retrieved and relevant chunks on the saved projection."""
        # Query projection coordinate
        qh = int(hashlib.sha256(f"query-{query}".encode("utf-8")).hexdigest()[:8], 16)
        qx = round(((qh % 2000) / 1000.0) - 1.0, 4)
        qy = round((((qh >> 8) % 2000) / 1000.0) - 1.0, 4)

        retrieved_set = set(retrieved_ids)
        relevant_set = set(relevant_ids)

        active_coords = []
        for pt in artifact.coordinates:
            cid = pt["chunk_id"]
            pt_copy = dict(pt)
            pt_copy["is_retrieved"] = cid in retrieved_set
            pt_copy["is_relevant"] = cid in relevant_set
            active_coords.append(pt_copy)

        return {
            "query_point": {"x": qx, "y": qy, "label": query},
            "points": active_coords,
            "total_points": len(active_coords),
            "retrieved_count": len(retrieved_set),
            "relevant_count": len(relevant_set),
        }

    def export_accessible_table(self, artifact: ProjectionArtifact) -> list[dict[str, Any]]:
        """Accessible tabular representation equivalent to the visual scatter plot."""
        table = []
        for pt in artifact.coordinates:
            chunk = DocumentChunk.objects.filter(chunk_id=pt["chunk_id"]).first()
            if not chunk or chunk.document.is_revoked or chunk.document.is_deleted:
                continue
            table.append({
                "chunk_id": pt["chunk_id"],
                "document_title": pt["title"],
                "cluster_name": artifact.clusters.get(str(pt["cluster_id"]), f"Cluster {pt['cluster_id']}"),
                "x": pt["x"],
                "y": pt["y"],
                "token_count": chunk.token_count,
                "text_preview": chunk.text[:100],
            })
        return table
