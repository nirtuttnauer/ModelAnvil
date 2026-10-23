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

    @action(detail=True,methods=['post'],url_path='revoke-document')
    @transaction.atomic
    def revoke_document(self,request,knowledge_base_id=None):
        from modelanvil.core.tenancy import get_active_project
        from modelanvil.identity.models import role_at_least,Role
        from modelanvil.rag.models import SourceDocument
        base=self.get_object()
        if ((base.project_id and str(base.project_id)!=str(get_active_project()))
                and not role_at_least(request.modelanvil_role,Role.ADMIN)):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('Revoke documents from their owning project or use an organization administrator.')
        if set(request.data)!={'document_id'}:
            raise serializers.ValidationError('Submit only the source document ID to revoke.')
        key=serializers.UUIDField().run_validation(request.data['document_id'])
        document=SourceDocument.objects.select_for_update().filter(knowledge_base=base,doc_id=key).first()
        if document is None:
            from rest_framework.exceptions import NotFound
            raise NotFound()
        document.is_revoked=True;document.save(update_fields=['is_revoked','updated_at'])
        record_audit('update','rag_source',document.doc_id,actor_id=request.modelanvil_actor_id,
            actor_kind=request.modelanvil_actor_kind,input_snapshot={'revoked':True})
        return Response({'document_id':str(document.doc_id),'revoked':True})


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

    def get_queryset(self):
        from modelanvil.identity.models import get_accessible_queryset
        return super().get_queryset().filter(knowledge_base__in=get_accessible_queryset(KnowledgeBase))

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

        from modelanvil.rag.workflow import trace_query
        try:
            trace, rows = trace_query(index_version,query_text,mode,top_k,query_embedding)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return Response({'results':rows,'mode':mode,'index_id':str(index_version.index_id),
            'manifest_digest':index_version.manifest_digest,'trace_id':str(trace.trace_id),
            'reranker':'none','generation':'not_executed','context_chunk_ids':[row['chunk_id'] for row in rows]})

    @action(detail=True,methods=['get'],url_path='judgment-pool')
    def judgment_pool(self,request,index_id=None):
        index=self.get_object()
        offset=serializers.IntegerField(min_value=0,max_value=10000).run_validation(request.query_params.get('offset',0))
        chunks=RetrievalEngine(index).get_eligible_chunks()
        return Response({'results':[{'chunk_id':str(c.chunk_id),'title':c.document.title,
            'span':f'{c.span_start}:{c.span_end}','text':c.text,'document_id':str(c.document.doc_id)} for c in chunks[offset:offset+50]],
            'total':len(chunks),'next_offset':offset+50 if offset+50<len(chunks) else None})

    @action(detail=True,methods=['get'])
    def traces(self,request,index_id=None):
        from modelanvil.rag.workflow import visible_traces
        index=self.get_object()
        return Response({'results':visible_traces(index),'limit':50,'generation':'not_executed'})

    @action(detail=True,methods=['get','post'])
    @transaction.atomic
    def comparisons(self,request,index_id=None):
        from modelanvil.rag.models import RetrievalRun
        from modelanvil.rag.workflow import compare,report
        index=self.get_object()
        if request.method=='GET':
            runs=list(RetrievalRun.objects.filter(index_version=index,tenant_id=index.tenant_id).exclude(qrels_digest='').order_by('-created_at')[:20])
            seen={run.pk for run in runs}
            for run in list(runs):
                group=run.protocol_ref.get('comparison_id')
                if group:
                    for peer in RetrievalRun.objects.filter(tenant_id=index.tenant_id,index_version__knowledge_base=index.knowledge_base,
                            protocol_ref__comparison_id=group).select_related('index_version'):
                        if peer.pk not in seen:
                            runs.append(peer);seen.add(peer.pk)
            return Response({'results':[report(run) for run in runs],'limit':20})
        form=RetrievalComparisonInput(data=request.data);form.is_valid(raise_exception=True)
        data=dict(form.validated_data)
        baseline_id=data.pop('baseline_index_id',None)
        baseline=self.get_queryset().filter(index_id=baseline_id,knowledge_base=index.knowledge_base,status='ready').first() if baseline_id else None
        if baseline_id and (baseline is None or baseline.pk==index.pk):
            raise serializers.ValidationError('Select a different accessible frozen index from the same knowledge base.')
        from modelanvil.core.ids import uuid7
        group=str(uuid7())
        try:
            rows=compare(index,**data,comparison_id=group)
            if baseline is not None:
                rows+=compare(baseline,**data,comparison_id=group)
        except ValueError as exc: raise serializers.ValidationError(str(exc)) from exc
        return Response({'results':rows},status=201)

    @action(detail=True,methods=['get','post'])
    def projection(self,request,index_id=None):
        from modelanvil.rag.explorer import ClusterExplorer
        index=self.get_object();explorer=ClusterExplorer(index)
        try:
            if request.method=='POST':
                if set(request.data)-{'num_clusters'}:
                    raise serializers.ValidationError('Submit only an optional cluster count; only measured PCA is supported.')
                count=serializers.IntegerField(min_value=1,max_value=20).run_validation(request.data['num_clusters']) if 'num_clusters' in request.data else None
                artifact=explorer.build_and_save_projection(num_clusters=count)
            else:
                artifact=index.projections.order_by('-created_at').first()
                if artifact is None:
                    return Response({'available':False,'reason':'No measured projection exists. Lexical indexes have no generated embeddings.'})
            table=explorer.export_accessible_table(artifact)
            settings={key:value for key,value in artifact.settings.items() if key not in ('mean','components')}
            return Response({'available':True,'artifact_id':str(artifact.artifact_id),'method':artifact.method,
                'settings':settings,'points':artifact.coordinates,'table':table,
                'total_points':artifact.total_points,'displayed_points':artifact.displayed_points})
        except ValueError as exc:
            return Response({'available':False,'reason':str(exc)},status=409)


class RetrievalComparisonCase(serializers.Serializer):
    query_id = serializers.CharField(max_length=128)
    query = serializers.CharField(max_length=2048)
    qrels = serializers.DictField(child=serializers.FloatField(min_value=0,max_value=10),default=dict)
    query_embedding = serializers.ListField(child=serializers.FloatField(),max_length=4096,allow_empty=False,required=False)

    def validate_qrels(self,value):
        if len(value)>1000:
            raise serializers.ValidationError('Judge at most1000 chunks per query.')
        result={}
        for key,grade in value.items():
            canonical=str(serializers.UUIDField().run_validation(key))
            if canonical in result or not math.isfinite(grade):
                raise serializers.ValidationError('Judgments require distinct chunk IDs and finite grades.')
            result[canonical]=grade
        return result

    def validate_query_embedding(self,value):
        if not all(math.isfinite(v) for v in value):
            raise serializers.ValidationError('Embedding values must be finite.')
        return value


class RetrievalComparisonInput(serializers.Serializer):
    qrels_version = serializers.CharField(max_length=128)
    cases = RetrievalComparisonCase(many=True,allow_empty=False,max_length=64)
    baseline_index_id = serializers.UUIDField(required=False)
    modes = serializers.ListField(child=serializers.ChoiceField(choices=['lexical','dense','hybrid']),min_length=1,max_length=3,default=['lexical'])
    top_k = serializers.IntegerField(min_value=1,max_value=100,default=5)

    def validate(self,data):
        if len({c['query_id'] for c in data['cases']})!=len(data['cases']) or len(set(data['modes']))!=len(data['modes']):
            raise serializers.ValidationError('Query IDs and retrieval modes must be distinct.')
        return data
