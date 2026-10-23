"""Saved, measured PCA of provided vectors with current-access checks."""
from __future__ import annotations
import hashlib
import json
from typing import Sequence
import numpy as np
from modelanvil.rag.models import IndexVersion, ProjectionArtifact
from modelanvil.rag.retrieval import RetrievalEngine, cosine_similarity

MAX_POINTS = 512
MAX_DIMENSION = 4096
METHOD_VERSION = 'pca-svd-v1'


class ClusterExplorer:
    def __init__(self, index_version: IndexVersion):
        self.index_version = index_version
        self.tenant_id = index_version.tenant_id

    def _chunks(self):
        return RetrievalEngine(self.index_version).get_eligible_chunks()

    def _checked_points(self, artifact):
        if (artifact.tenant_id != self.tenant_id or artifact.index_version_id != self.index_version.pk
                or artifact.settings.get('method_version') != METHOD_VERSION):
            raise ValueError('This projection has no qualified PCA provenance for the selected index. Rebuild it.')
        chunks = {str(c.chunk_id): c for c in self._chunks()}
        if any(point['chunk_id'] not in chunks for point in artifact.coordinates):
            raise ValueError('Projection inputs were revoked, deleted or removed from the index. Rebuild it before viewing or exporting.')
        digest = hashlib.sha256(json.dumps([(point['chunk_id'], chunks[point['chunk_id']].content_hash,
            chunks[point['chunk_id']].embedding) for point in artifact.coordinates], separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        if digest != artifact.settings.get('input_digest'):
            raise ValueError('Projection inputs changed. Rebuild it before viewing or exporting.')
        return chunks

    def build_and_save_projection(self, method='pca', num_clusters=None):
        if method != 'pca':
            raise ValueError('Only measured PCA is supported; UMAP is not implemented.')
        chunks = self._chunks()
        dimension = self.index_version.embedding_space.dimension
        if not chunks or len(chunks) > MAX_POINTS or not 1 <= dimension <= MAX_DIMENSION:
            raise ValueError(f'PCA requires1–{MAX_POINTS} authorized chunks and1–{MAX_DIMENSION} dimensions.')
        if any(len(c.embedding or []) != dimension for c in chunks):
            raise ValueError('Every projection input needs a compatible real embedding; lexical chunks have none.')
        num_clusters = min(3, len(chunks)) if num_clusters is None else num_clusters
        if type(num_clusters) is not int or not 1 <= num_clusters <= min(20, len(chunks)):
            raise ValueError('Choose1–20 clusters, no more than the input points.')
        matrix = np.asarray([c.embedding for c in chunks], dtype=np.float64)
        if not np.isfinite(matrix).all():
            raise ValueError('Embedding values must be finite.')
        mean = matrix.mean(axis=0)
        centered = matrix - mean
        _, singular, vectors = np.linalg.svd(centered, full_matrices=False)
        basis = np.zeros((2, dimension))
        for i in range(min(2, len(vectors))):
            if singular[i] > np.finfo(float).eps * max(matrix.shape) * max(float(singular[0]), 1):
                row = vectors[i]
                basis[i] = row if row[np.argmax(np.abs(row))] >= 0 else -row
        projected = centered @ basis.T
        # Farthest-first initialization and bounded Lloyd iterations use actual original vectors.
        centers = [matrix[0]]
        while len(centers) < num_clusters:
            distance = np.min(np.stack([np.sum((matrix-c)**2, axis=1) for c in centers]), axis=0)
            if float(distance.max()) <= 1e-15:
                break
            centers.append(matrix[int(distance.argmax())])
        centers = np.asarray(centers)
        for _ in range(20):
            distances = np.sum(matrix**2, axis=1)[:, None] + np.sum(centers**2, axis=1)[None, :] - 2*matrix @ centers.T
            labels = distances.argmin(axis=1)
            updated = np.asarray([matrix[labels == i].mean(axis=0) if np.any(labels == i) else centers[i] for i in range(len(centers))])
            if np.allclose(updated, centers, rtol=0, atol=1e-9):
                break
            centers = updated
        labels = (np.sum(matrix**2, axis=1)[:, None] + np.sum(centers**2, axis=1)[None, :] - 2*matrix @ centers.T).argmin(axis=1)
        total_variance = float(np.sum(singular**2))
        ratios = [(float(value**2) / total_variance if total_variance else 0) for value in singular[:2]]
        digest = hashlib.sha256(json.dumps([(str(c.chunk_id), c.content_hash, c.embedding) for c in chunks], separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        return ProjectionArtifact.objects.create(tenant_id=self.tenant_id, index_version=self.index_version,
            method='pca', coordinates=[{'chunk_id':str(c.chunk_id), 'title':c.document.title,
                'x':round(float(xy[0]),6), 'y':round(float(xy[1]),6), 'cluster_id':int(label)}
                for c,xy,label in zip(chunks,projected,labels)],
            clusters={str(i):f'Vector cluster {i+1}' for i in range(len(centers))},
            settings={'method_version':METHOD_VERSION, 'numpy_version':np.__version__, 'input_digest':digest,
                'mean':mean.tolist(), 'components':basis.tolist(), 'explained_variance_ratio':ratios,
                'clustering':'bounded-kmeans-original-vectors', 'num_clusters':len(centers),
                'max_points':MAX_POINTS, 'max_dimension':MAX_DIMENSION,
                'limits':'PCA preserves variance, not all neighbors or semantic meaning. Clusters describe provided vectors; no retrieval-quality qualification is inferred.'},
            total_points=len(chunks), displayed_points=len(chunks))

    def get_original_space_neighbors(self, target_chunk_id, k=5):
        chunks = self._chunks()
        target = next((c for c in chunks if str(c.chunk_id) == target_chunk_id), None)
        if target is None or not target.embedding:
            raise ValueError('Target is outside the authorized frozen index or has no embedding.')
        if type(k) is not int or not 1 <= k <= 100:
            raise ValueError('Choose1–100 neighbors.')
        rows = [{'chunk_id':str(c.chunk_id), 'title':c.document.title,
            'similarity':round(cosine_similarity(target.embedding,c.embedding),4), 'text_snippet':c.text[:80]}
            for c in chunks if c.pk != target.pk and c.embedding and len(c.embedding) == len(target.embedding)]
        return sorted(rows,key=lambda row:(-row['similarity'],row['chunk_id']))[:k]

    def overlay_query_and_relevance(self, artifact, query, retrieved_ids, relevant_ids, query_embedding: Sequence[float] | None=None):
        self._checked_points(artifact)
        known = {point['chunk_id'] for point in artifact.coordinates}
        retrieved, relevant = set(retrieved_ids)&known, set(relevant_ids)&known
        query_point = None
        if query_embedding is not None:
            vector = np.asarray(query_embedding,dtype=float)
            mean = np.asarray(artifact.settings['mean'])
            if vector.shape != mean.shape or not np.isfinite(vector).all():
                raise ValueError('The query vector must match the saved embedding space.')
            xy = (vector-mean) @ np.asarray(artifact.settings['components']).T
            query_point = {'x':float(xy[0]), 'y':float(xy[1]), 'label':query}
        return {'query_point':query_point, 'query_point_available':query_point is not None,
            'points':[{**point,'is_retrieved':point['chunk_id'] in retrieved,'is_relevant':point['chunk_id'] in relevant} for point in artifact.coordinates],
            'total_points':len(known), 'retrieved_count':len(retrieved), 'relevant_count':len(relevant)}

    def export_accessible_table(self, artifact):
        chunks = self._checked_points(artifact)
        return [{'chunk_id':point['chunk_id'], 'document_title':chunks[point['chunk_id']].document.title,
            'cluster_name':artifact.clusters[str(point['cluster_id'])], 'x':point['x'], 'y':point['y'],
            'token_count':chunks[point['chunk_id']].token_count, 'text_preview':chunks[point['chunk_id']].text[:100]}
            for point in artifact.coordinates]
