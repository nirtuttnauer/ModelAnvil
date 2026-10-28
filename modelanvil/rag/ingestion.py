"""Bounded local text ingestion with immutable lexical index membership."""
from __future__ import annotations

import hashlib
import json
import re

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ValidationError

from modelanvil.core.ids import uuid7
from modelanvil.rag.models import DocumentChunk, EmbeddingSpace, IndexVersion, KnowledgeBase, SourceDocument

@transaction.atomic
def index_documents(knowledge_base: KnowledgeBase, documents: list[dict], chunk_size: int, chunk_overlap: int) -> IndexVersion:
    base = KnowledgeBase.objects.select_for_update().get(pk=knowledge_base.pk)
    for item in documents:
        source_uri = item.get("source_uri") or f"local:{uuid7()}"
        previous = SourceDocument.objects.filter(knowledge_base=base, source_uri=source_uri).order_by("-revision_no").first()
        digest = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
        if previous and previous.content_hash == digest and not previous.is_deleted and not previous.is_revoked:
            continue
        document = SourceDocument.objects.create(
            tenant_id=base.tenant_id, knowledge_base=base, title=item["title"], source_uri=source_uri,
            revision_no=previous.revision_no + 1 if previous else 1, content=item["content"], content_hash=digest,
        )
        chunks = []
        start = 0
        while start < len(document.content):
            end = min(start + chunk_size, len(document.content))
            content = document.content[start:end]
            chunks.append(DocumentChunk(
                tenant_id=base.tenant_id, document=document, chunk_index=len(chunks), text=content,
                span_start=start, span_end=end, token_count=len(re.findall(r"\w+", content)),
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            ))
            if end == len(document.content):
                break
            start = end - chunk_overlap
        DocumentChunk.objects.bulk_create(chunks)

    # Only the latest source revisions enter a new snapshot; older indexes keep their exact membership.
    latest = {}
    for document in SourceDocument.objects.filter(knowledge_base=base).order_by("source_uri", "revision_no"):
        latest[document.source_uri] = document
    document_ids = [document.pk for document in latest.values() if not document.is_deleted and not document.is_revoked]
    manifest = list(DocumentChunk.objects.filter(document_id__in=document_ids).order_by("chunk_id").values_list("chunk_id", "content_hash"))
    if len(manifest) > 10000:
        raise ValidationError({"documents": "A local lexical index supports at most 10,000 chunks."})
    chunk_ids = [str(chunk_id) for chunk_id, _ in manifest]
    manifest_digest = hashlib.sha256(json.dumps([(str(key), digest) for key, digest in manifest], separators=(",", ":")).encode()).hexdigest()
    space, _ = EmbeddingSpace.objects.get_or_create(
        tenant_id=base.tenant_id, name="Local lexical text",
        defaults={"model_name": "lexical-token-overlap-v1", "dimension": 1, "normalized": False,
                  "metadata": {"kind": "lexical", "embeddings_generated": False}},
    )
    revision = (IndexVersion.objects.filter(knowledge_base=base).aggregate(value=Max("revision_no"))["value"] or 0) + 1
    return IndexVersion.objects.create(
        tenant_id=base.tenant_id, knowledge_base=base, embedding_space=space, revision_no=revision,
        adapter_type=IndexVersion.AdapterType.LEXICAL, status=IndexVersion.Status.READY,
        chunks_count=len(chunk_ids), manifest_digest=manifest_digest,
        configuration={"chunk_ids": chunk_ids, "chunk_size": chunk_size, "chunk_overlap": chunk_overlap,
                       "retrieval": "lexical-token-overlap-v1", "embeddings_generated": False},
    )
