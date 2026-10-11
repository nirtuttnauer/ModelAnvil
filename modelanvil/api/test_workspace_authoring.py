"""Real text ingestion and saved context authoring through authenticated API boundaries."""
import hashlib

from django.test import TestCase
from rest_framework.test import APIClient

from modelanvil.context_lab.compiler import estimate_tokens
from modelanvil.context_lab.models import ContextBlockRevision, ContextRecipe, ContextRecipeVersion
from modelanvil.identity.models import ApiKey, Role, Tenant, generate_api_key
from modelanvil.rag.models import DocumentChunk, IndexVersion, KnowledgeBase, SourceDocument


class WorkspaceAuthoringTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(slug="authoring", name="Authoring")
        self.client = self.client_for(self.tenant)

    def client_for(self, tenant, role=Role.ENGINEER):
        secret, secret_hash = generate_api_key()
        ApiKey.objects.create(tenant=tenant, name="authoring-key", secret_hash=secret_hash, role=role)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {secret}")
        return client

    def make_base(self):
        response = self.client.post("/api/v1/knowledge-bases/", {"name": "Source notes"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["knowledge_base_id"]

    def index(self, base, text="Quantum qubits preserve superposition.", **extra):
        return self.client.post(f"/api/v1/knowledge-bases/{base}/index/", {
            "documents": [{"title": "Research note", "source_uri": "local:note", "content": text}], **extra,
        }, format="json")

    def query(self, index, **extra):
        return self.client.post(f"/api/v1/index-versions/{index}/query/", {"query": "qubits", "mode": "lexical", **extra}, format="json")

    def test_import_query_hashes_and_immutable_source_revisions(self):
        base = self.make_base()
        first = self.index(base)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["chunk_count"], 1)
        self.assertEqual(first.data["adapter_type"], "lexical")
        first_id = first.data["index_id"]
        result = self.query(first_id)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["mode"], "lexical")
        self.assertEqual(result.data["results"][0]["metadata"]["content_hash"], hashlib.sha256(b"Quantum qubits preserve superposition.").hexdigest())
        second = self.index(base, "Classical bits store binary states.")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["revision_no"], 2)
        self.assertEqual(self.query(second.data["index_id"]).data["results"], [])
        self.assertEqual(len(self.query(first_id).data["results"]), 1)
        self.assertEqual(SourceDocument.objects.count(), 2)
        self.assertEqual(DocumentChunk.objects.count(), 2)
        self.assertEqual(self.client.patch(f"/api/v1/index-versions/{first_id}/", {"revision_no": 5}, format="json").status_code, 405)
        document = SourceDocument.objects.order_by("revision_no").first()
        document.is_revoked = True
        document.save(update_fields=["is_revoked"])
        self.assertEqual(self.query(first_id).data["results"], [])

    def test_duplicate_content_reuses_document_and_spans_preserve_original_text(self):
        base = self.make_base()
        content = "word " * 100
        first = self.index(base, content, chunk_size=100, chunk_overlap=20)
        self.assertEqual(first.status_code, 201)
        second = self.index(base, content, chunk_size=100, chunk_overlap=20)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(SourceDocument.objects.count(), 1)
        for chunk in DocumentChunk.objects.all():
            self.assertEqual(chunk.text, content[chunk.span_start:chunk.span_end])
        self.assertEqual(first.data["manifest_digest"], second.data["manifest_digest"])

    def test_invalid_imports_are_atomic_and_queries_fail_as_client_errors(self):
        base = self.make_base()
        for payload in ({"documents": []}, {"documents": [{"title": "A", "content": " "}]},
                        {"documents": [{"title": "A", "content": "text"}], "chunk_size": 100, "chunk_overlap": 99}):
            response = self.client.post(f"/api/v1/knowledge-bases/{base}/index/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(SourceDocument.objects.count(), 0)
        index = self.index(base).data["index_id"]
        for payload in ({"top_k": "bad"}, {"top_k": -1}, {"mode": "unknown"}, {"mode": "dense"}, {"mode": "dense", "query_embedding": [1]}):
            self.assertEqual(self.query(index, **payload).status_code, 400)
        obj = IndexVersion.objects.get(index_id=index)
        obj.status = "revoked"
        obj.save(update_fields=["status"])
        self.assertEqual(self.query(index).status_code, 409)

    def test_foreign_tenants_and_viewers_cannot_write(self):
        base = self.make_base()
        foreign = Tenant.objects.create(slug="foreign", name="Foreign")
        other_client = self.client_for(foreign)
        self.assertEqual(other_client.post(f"/api/v1/knowledge-bases/{base}/index/", {"documents": []}, format="json").status_code, 404)
        viewer = self.client_for(self.tenant, Role.VIEWER)
        self.assertEqual(viewer.post(f"/api/v1/knowledge-bases/{base}/index/", {"documents": []}, format="json").status_code, 403)
        index = self.index(base).data["index_id"]
        self.assertEqual(viewer.post(f"/api/v1/index-versions/{index}/query/", {"query": "qubits", "mode": "lexical"}, format="json").status_code, 200)
        self.assertEqual(other_client.post(f"/api/v1/index-versions/{index}/query/", {"query": "qubits"}, format="json").status_code, 404)
        self.assertEqual(self.client.post("/api/v1/knowledge-bases/", {"name": "Source notes"}, format="json").status_code, 400)

    def recipe_payload(self):
        return {"name": "Grounded assistant", "initial_version": {
            "model_limit_tokens": 1000, "output_reserve_tokens": 100,
            "blocks": [{"block_key": "system", "block_type": "instruction", "role": "system", "priority": 1, "order": 0, "content_template": "Use the evidence."},
                       {"block_key": "evidence", "block_type": "evidence", "role": "system", "priority": 2, "order": 1, "max_tokens": 10, "content_template": "word " * 100}],
        }}

    def test_atomic_recipe_authoring_compile_and_immutable_versions(self):
        saved = self.client.post("/api/v1/context-recipes/", self.recipe_payload(), format="json")
        self.assertEqual(saved.status_code, 201, saved.data)
        version = saved.data["versions"][0]["recipe_version_id"]
        response = self.client.post(f"/api/v1/context-recipe-versions/{version}/compile/", {"variables": {}}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["token_count"], estimate_tokens(response.data["serialized_prompt"]))
        self.assertEqual(sum(block["token_count"] for block in response.data["block_token_counts"]), response.data["token_count"])
        self.assertEqual(response.data["truncated_blocks"][0]["block_key"], "evidence")
        self.assertLessEqual(response.data["truncated_blocks"][0]["tokens_retained"], 10)
        self.assertEqual(ContextBlockRevision.objects.count(), 2)
        self.assertEqual(self.client.patch(f"/api/v1/context-recipe-versions/{version}/", {"model_limit_tokens": 1}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"/api/v1/context-recipe-versions/{version}/").status_code, 405)
        malformed = self.client.post(f"/api/v1/context-recipe-versions/{version}/compile/", {"variables": {"evidence": ["bad"]}}, format="json")
        self.assertEqual(malformed.status_code, 400)

    def test_invalid_recipe_does_not_leave_partial_records(self):
        for mutation in ("duplicate", "reserve", "summarize"):
            payload = self.recipe_payload()
            if mutation == "duplicate":
                payload["initial_version"]["blocks"][1]["block_key"] = "system"
            elif mutation == "reserve":
                payload["initial_version"]["output_reserve_tokens"] = 1000
            else:
                payload["initial_version"]["budget_policy"] = "summarize"
            response = self.client.post("/api/v1/context-recipes/", payload, format="json")
            self.assertEqual(response.status_code, 400, response.content)
            self.assertEqual(ContextRecipe.objects.count(), 0)
            self.assertEqual(ContextRecipeVersion.objects.count(), 0)

    def test_version_authoring_rejects_foreign_recipe_relation(self):
        saved = self.client.post("/api/v1/context-recipes/", self.recipe_payload(), format="json")
        foreign = Tenant.objects.create(slug="other-recipe", name="Other")
        other = self.client_for(foreign)
        payload = {"recipe": saved.data["id"], "revision_no": 2, **self.recipe_payload()["initial_version"]}
        self.assertEqual(other.post("/api/v1/context-recipe-versions/", payload, format="json").status_code, 400)
        second = self.client.post("/api/v1/context-recipe-versions/", payload, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(self.client.post("/api/v1/context-recipe-versions/", payload, format="json").status_code, 400)
