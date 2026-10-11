"""Tenant-scoped REST APIs for RAG Knowledge Bases, Index Versions, and Retrieval."""
from __future__ import annotations

import hashlib
import json
import math

from django.db import transaction

from rest_framework import serializers, status

from modelanvil.core.tenancy import get_active_tenant
from modelanvil.core.models import record_audit
from modelanvil.rag.ingestion import index_documents
from rest_framework.decorators import action
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.rag.models import (
    DocumentChunk,
    IndexVersion,
    KnowledgeBase,
)
from modelanvil.rag.retrieval import RetrievalEngine


class KnowledgeBaseSerializer(serializers.ModelSerializer):
    knowledge_base_id = serializers.UUIDField(source="kb_id", read_only=True)

    class Meta:
        model = KnowledgeBase
        fields = ("id", "knowledge_base_id", "kb_id", "name", "description", "created_at", "updated_at")
        read_only_fields = ("id", "knowledge_base_id", "kb_id", "created_at", "updated_at")


    def validate_name(self, value):
        existing = KnowledgeBase.objects.filter(tenant_id=get_active_tenant(), name=value)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError("A knowledge base with this name already exists.")
        return value


class DocumentInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=255)
    source_uri = serializers.CharField(max_length=512, required=False)
    content = serializers.CharField(max_length=500000, trim_whitespace=False)

    def validate_content(self, value):
        if not value.strip():
            raise serializers.ValidationError("Document content cannot be blank.")
        return value


class IndexInputSerializer(serializers.Serializer):
    documents = DocumentInputSerializer(many=True, allow_empty=False, max_length=50)
    chunk_size = serializers.IntegerField(default=1200, min_value=100, max_value=10000)
    chunk_overlap = serializers.IntegerField(default=100, min_value=0, max_value=1000)

    def validate(self, data):
        if data["chunk_overlap"] > data["chunk_size"] // 2:
            raise serializers.ValidationError({"chunk_overlap": "Overlap must be at most half the chunk size."})
        if sum(len(item["content"].encode("utf-8")) for item in data["documents"]) > 2000000:
            raise serializers.ValidationError({"documents": "Import at most 2 MB of UTF-8 text at once."})
        if sum(max(1, math.ceil(max(0, len(item["content"]) - data["chunk_overlap"]) / (data["chunk_size"] - data["chunk_overlap"]))) for item in data["documents"]) > 10000:
            raise serializers.ValidationError({"documents": "Import at most 10,000 chunks at once."})
        sources = [item["source_uri"] for item in data["documents"] if item.get("source_uri")]
        if len(sources) != len(set(sources)):
            raise serializers.ValidationError({"documents": "Source URIs must be unique within an import."})
        return data


class RetrievalQuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=10000, required=False, default="", allow_blank=True)
    top_k = serializers.IntegerField(default=5, min_value=1, max_value=100)
    mode = serializers.ChoiceField(choices=("lexical", "dense", "hybrid"), default="hybrid")
    query_embedding = serializers.ListField(child=serializers.FloatField(), required=False, max_length=4096, allow_empty=False)

    def validate(self, data):
        vector = data.get("query_embedding")
        if vector and not all(math.isfinite(value) for value in vector):
            raise serializers.ValidationError({"query_embedding": "Embedding values must be finite."})
        if data["mode"] == "dense" and not vector:
            raise serializers.ValidationError({"query_embedding": "Dense retrieval requires a query embedding."})
        if not vector and not data["query"].strip():
            raise serializers.ValidationError({"query": "Enter a query for lexical retrieval."})
        return data


class KnowledgeBaseViewSet(TenantScopedViewSet):
    queryset = KnowledgeBase.objects.all()
    serializer_class = KnowledgeBaseSerializer
    lookup_field = "kb_id"
    lookup_url_kwarg = "knowledge_base_id"
    http_method_names = ["get", "post", "patch", "head", "options"]

    @action(detail=True, methods=["post"], url_path="index")
    @transaction.atomic
    def build_index(self, request, knowledge_base_id=None):
        base = self.get_object()
        serializer = IndexInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        index = index_documents(base, **serializer.validated_data)
        record_audit("create", "knowledge_index", index.index_id,
                     actor_id=getattr(request, "modelanvil_actor_id", None), actor_kind=getattr(request, "modelanvil_actor_kind", "system"),
                     input_snapshot={"knowledge_base_id": str(base.kb_id), "manifest_digest": index.manifest_digest, "chunk_count": index.chunks_count})
        return Response(IndexVersionSerializer(index).data, status=status.HTTP_201_CREATED)


class IndexVersionSerializer(serializers.ModelSerializer):
    chunk_count = serializers.IntegerField(source="chunks_count", read_only=True)
    revision_no = serializers.IntegerField(default=1, min_value=1)

    @transaction.atomic
    def create(self, validated_data):
        base = KnowledgeBase.objects.select_for_update().get(pk=validated_data["knowledge_base"].pk)
        if IndexVersion.objects.filter(knowledge_base=base, revision_no=validated_data.get("revision_no", 1)).exists():
            raise serializers.ValidationError({"revision_no": "This index revision already exists."})
        chunks = list(DocumentChunk.objects.filter(document__knowledge_base=base, document__is_deleted=False, document__is_revoked=False).order_by("chunk_id").values_list("chunk_id", "content_hash"))
        if len(chunks) > 10000:
            raise serializers.ValidationError({"knowledge_base": "A local index supports at most 10,000 chunks."})
        manifest = [(str(key), digest) for key, digest in chunks]
        validated_data.update(chunks_count=len(chunks), configuration={"chunk_ids": [key for key, _ in manifest]},
                              manifest_digest=hashlib.sha256(json.dumps(manifest, separators=(",", ":")).encode()).hexdigest())
        return super().create(validated_data)

    class Meta:
        model = IndexVersion
        fields = ("index_id", "knowledge_base", "embedding_space", "revision_no", "status", "chunk_count", "adapter_type", "manifest_digest", "created_at")
        read_only_fields = ("index_id", "status", "chunk_count", "adapter_type", "manifest_digest", "created_at")


class IndexVersionViewSet(TenantScopedViewSet):
    queryset = IndexVersion.objects.select_related("knowledge_base")
    serializer_class = IndexVersionSerializer
    lookup_field = "index_id"
    http_method_names = ["get", "post", "head", "options"]

    def initial(self, request, *args, **kwargs):
        if self.action == "query":
            from modelanvil.identity.models import Role
            self.write_role = Role.VIEWER
        return super().initial(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="query")
    def query(self, request, index_id=None):
        """Execute hybrid/dense/lexical retrieval query across index chunks."""
        index_version = self.get_object()
        if index_version.status != IndexVersion.Status.READY:
            return Response({"detail": "Only ready index versions can be queried."}, status=409)
        serializer = RetrievalQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        query_text, query_embedding = data["query"], data.get("query_embedding")
        top_k, mode = data["top_k"], data["mode"]
        if query_embedding and mode != "lexical":
            if index_version.adapter_type == IndexVersion.AdapterType.LEXICAL:
                return Response({"detail": "This index supports lexical retrieval only."}, status=400)
            if len(query_embedding) != index_version.embedding_space.dimension:
                return Response({"query_embedding": "Embedding dimension does not match the index space."}, status=400)
        if not query_embedding:
            mode = "lexical"

        engine = RetrievalEngine(index_version)
        if mode == "hybrid" and query_embedding:
            results = engine.retrieve_hybrid(query_text, query_embedding, top_k=top_k)
        elif mode == "dense" and query_embedding:
            results = engine.retrieve_dense(query_embedding, top_k=top_k)
        else:
            results = engine.retrieve_lexical(query_text, top_k=top_k)

        data = [
            {
                "chunk_id": str(r.chunk_id),
                "text": r.chunk.text,
                "score": round(r.score, 4),
                "metadata": {
                    "document_title": r.chunk.document.title,
                    "source_uri": r.chunk.document.source_uri,
                    "document_revision": r.chunk.document.revision_no,
                    "content_hash": r.chunk.content_hash,
                    "span": f"{r.chunk.span_start}:{r.chunk.span_end}",
                    **r.chunk.metadata,
                },
            }
            for r in results
        ]
        return Response({"results": data, "mode": mode, "index_id": str(index_version.index_id), "manifest_digest": index_version.manifest_digest})
