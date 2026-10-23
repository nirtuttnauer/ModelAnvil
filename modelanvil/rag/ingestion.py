"""Bounded local text ingestion with immutable lexical index membership."""
from __future__ import annotations

import hashlib
import json

from django.db import transaction
from django.db.models import Max
from rest_framework.exceptions import ValidationError

from modelanvil.rag.chunking import token_chunks, PINS, RECIPE
from modelanvil.core.ids import uuid7
from modelanvil.core.tenancy import get_active_project
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
        SourceDocument.objects.create(
            tenant_id=base.tenant_id, knowledge_base=base, title=item["title"], source_uri=source_uri,
            revision_no=previous.revision_no + 1 if previous else 1, content=item["content"], content_hash=digest,
        )

    # Only the latest source revisions enter a new snapshot; older indexes keep their exact membership.
    latest = {}
    for document in SourceDocument.objects.filter(knowledge_base=base).order_by("source_uri", "revision_no"):
        latest[document.source_uri] = document
    recipe = {'tokenizer': PINS, 'chunk_size': chunk_size, 'chunk_overlap': chunk_overlap, 'recipe': RECIPE}
    recipe_digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    active = [d for d in latest.values() if not d.is_deleted and not d.is_revoked]
    if sum(len(d.content.encode('utf-8')) for d in active) > 2000000:
        raise ValidationError({'documents': 'A local token index supports at most 2 MB of active source text.'})
    total = 0
    try:
        for document in active:
            existing = DocumentChunk.objects.filter(document=document, recipe_digest=recipe_digest).count()
            if existing:
                total += existing
            else:
                chunks = []
                for item in token_chunks(document.content, chunk_size, chunk_overlap):
                    if total + len(chunks) >= 10000:
                        raise ValueError('A local token index supports at most 10,000 chunks.')
                    chunks.append(DocumentChunk(tenant_id=base.tenant_id, document=document, chunk_index=len(chunks),
                        recipe_digest=recipe_digest, content_hash=hashlib.sha256(item['text'].encode()).hexdigest(), **item))
                total += len(chunks)
                DocumentChunk.objects.bulk_create(chunks)
            if total > 10000:
                raise ValueError('A local token index supports at most 10,000 chunks.')
    except ValueError as exc:
        raise ValidationError({'documents': str(exc)}) from None
    document_ids = {document.pk for document in latest.values() if not document.is_deleted and not document.is_revoked}
    manifest = list(DocumentChunk.objects.filter(document_id__in=document_ids, recipe_digest=recipe_digest).order_by("chunk_id").values_list("chunk_id", "content_hash"))
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
                       "retrieval": "lexical-token-overlap-v1", "embeddings_generated": False,
                       "source_scope": {"tenant_id":str(base.tenant_id), "project_id":str(base.project_id) if base.project_id else None,
                                        "knowledge_base_id":str(base.kb_id), "build_project_id":str(get_active_project()) if get_active_project() else None, "current_permissions_required":True},
                       "source_revisions":[{"document_id":str(d.doc_id),"revision":d.revision_no,"content_hash":d.content_hash} for d in latest.values() if d.pk in document_ids],
                       "chunk_recipe":RECIPE, "chunk_units":"tokens", "tokenizer":PINS, "chunk_recipe_digest":recipe_digest,
                       "boundary_preference":"paragraph_then_sentence", "overlap_semantics":"at_most_requested_actual_tokens"},
    )
