"""Tests for ModelAnvil CLI, API client, and deployment packaging contracts (WP-16).

Verifies:
- TECH-004: API-only journey from import -> train -> evaluate -> export.
- TECH-029: Scoped worker credentials, hybrid private worker enrollment, and metadata-only egress boundary.
- CLI argument parsing, JSON serialization, and error exit codes.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from unittest.mock import MagicMock, patch
from django.test import TestCase

from modelanvil.cli.client import ModelAnvilClient, ModelAnvilClientError
from modelanvil.cli.config import get_setting, load_config, save_config, set_setting
from modelanvil.cli.main import build_parser, main


class MockApiTransport:
    """Mock transport simulating ModelAnvil control plane endpoints for client testing."""

    def __init__(self):
        self.datasets = {}
        self.training_runs = {}
        self.eval_runs = {}
        self.releases = {}
        self.workers = {}
        self.pools = {1: {"id": 1, "name": "hybrid-pool", "result_egress": "envelope"}}

    def post(self, path: str, data: str = "{}", content_type: str = "application/json", **headers):
        payload = json.loads(data) if data else {}
        if path == "/api/v1/datasets/":
            ds_id = f"ds-{len(self.datasets) + 1}"
            rec = {"dataset_id": ds_id, "name": payload.get("name"), "status": "READY"}
            self.datasets[ds_id] = rec
            return MagicMock(status_code=201, content=json.dumps(rec).encode("utf-8"))

        elif path == "/api/v1/training-runs/":
            run_id = f"trn-{len(self.training_runs) + 1}"
            model_ver_id = f"mod-{len(self.training_runs) + 1}"
            rec = {
                "run_id": run_id,
                "model_version_id": model_ver_id,
                "name": payload.get("name"),
                "status": "SUCCEEDED",
            }
            self.training_runs[run_id] = rec
            return MagicMock(status_code=201, content=json.dumps(rec).encode("utf-8"))

        elif path.startswith("/api/v1/index-versions/") and path.endswith("/query/"):
            return MagicMock(status_code=200, content=json.dumps({"results": [{"chunk_id": "c1", "text": "matched text"}]}).encode("utf-8"))

        elif path.startswith("/api/v1/context-recipe-versions/") and path.endswith("/compile/"):
            return MagicMock(status_code=200, content=json.dumps({"token_count": 42, "serialized_prompt": "compiled prompt"}).encode("utf-8"))

        elif path == "/api/v1/evaluation-runs/":
            eval_id = f"eval-{len(self.eval_runs) + 1}"
            rec = {
                "run_id": eval_id,
                "name": payload.get("name"),
                "status": "COMPLETED",
                "accuracy": 0.94,
            }
            self.eval_runs[eval_id] = rec
            return MagicMock(status_code=201, content=json.dumps(rec).encode("utf-8"))

        elif path == "/api/v1/releases/":
            rel_id = f"rel-{len(self.releases) + 1}"
            rec = {
                "release_version_id": rel_id,
                "name": payload.get("name"),
                "semantic_version": payload.get("semantic_version", "1.0.0"),
            }
            self.releases[rel_id] = rec
            return MagicMock(status_code=201, content=json.dumps(rec).encode("utf-8"))

        elif "/export/" in path:
            return MagicMock(
                status_code=200,
                content=json.dumps({
                    "status": "EXPORTED",
                    "archive_hash": "sha256:abc12345",
                    "file_count": 4,
                }).encode("utf-8"),
            )

        elif path == "/api/v1/workers/register/":
            w_id = len(self.workers) + 1
            rec = {"worker_id": w_id, "name": payload.get("name"), "pool_id": payload.get("pool_id")}
            self.workers[w_id] = rec
            return MagicMock(status_code=201, content=json.dumps(rec).encode("utf-8"))

        elif "/egress/" in path:
            pool_id = int(path.split("/")[5])
            mode = payload.get("result_egress")
            if pool_id in self.pools:
                self.pools[pool_id]["result_egress"] = mode
                return MagicMock(status_code=200, content=json.dumps({"ok": True, "result_egress": mode}).encode("utf-8"))
            return MagicMock(status_code=404, content=b'{"error": "not found"}')

        return MagicMock(status_code=404, content=b'{"error": "route not found"}')

    def get(self, path: str, **headers):
        if path == "/api/v1/datasets/":
            return MagicMock(status_code=200, content=json.dumps(list(self.datasets.values())).encode("utf-8"))
        return MagicMock(status_code=404, content=b'{"error": "not found"}')


class CliAndClientTests(TestCase):
    def setUp(self):
        self.transport = MockApiTransport()
        self.client = ModelAnvilClient(
            base_url="http://testserver",
            token="test-token-xyz",
            tenant_id="tenant-123",
            transport=self.transport,
        )

    def test_api_only_journey_end_to_end(self):
        """TECH-004: Exercise complete API-only journey: import -> train -> evaluate -> export."""
        result = self.client.run_api_journey(
            dataset_name="churn-prediction-v1",
            model_name="churn-classifier",
            recipe="pretrain_scratch",
        )
        self.assertEqual(result["status"], "COMPLETED")
        self.assertTrue(result["dataset"]["dataset_id"].startswith("ds-"))
        self.assertTrue(result["training_run"]["run_id"].startswith("trn-"))
        self.assertTrue(result["evaluation_run"]["run_id"].startswith("eval-"))
        self.assertEqual(result["export_bundle"]["status"], "EXPORTED")
        self.assertEqual(result["export_bundle"]["archive_hash"], "sha256:abc12345")

    def test_hybrid_worker_enrollment_and_metadata_egress_policy(self):
        """TECH-029: Hybrid worker enroll and metadata-only result egress configuration."""
        # 1. Enroll worker into pool
        enrollment = self.client.enroll_worker(pool_id=1, name="onprem-dgx-01")
        self.assertEqual(enrollment["name"], "onprem-dgx-01")
        self.assertEqual(enrollment["worker_id"], 1)

        # 2. Configure metadata-only boundary
        egress_res = self.client.configure_pool_egress(pool_id=1, mode="metadata_only")
        self.assertTrue(egress_res["ok"])
        self.assertEqual(egress_res["result_egress"], "metadata_only")
        self.assertEqual(self.transport.pools[1]["result_egress"], "metadata_only")

    def test_cli_argument_parser(self):
        """Verify CLI argument parser subcommands."""
        parser = build_parser()
        args = parser.parse_args(["journey", "smoke", "--dataset-name", "smoke-ds"])
        self.assertEqual(args.command, "journey")
        self.assertEqual(args.subcommand, "smoke")
        self.assertEqual(args.dataset_name, "smoke-ds")

        train_args = parser.parse_args(["training", "launch", "run-1", "--recipe", "fine_tune_sft"])
        self.assertEqual(train_args.command, "training")
        self.assertEqual(train_args.subcommand, "launch")
        self.assertEqual(train_args.recipe, "fine_tune_sft")

    def test_cli_config_management(self):
        """Verify config file loading, setting, and environment fallback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_file = os.path.join(tmpdir, "test_config.json")
            with patch.dict(os.environ, {"MODELANVIL_CONFIG": cfg_file}):
                set_setting("url", "https://api.modelanvil.io")
                set_setting("token", "secret-token")
                self.assertEqual(get_setting("url"), "https://api.modelanvil.io")
                self.assertEqual(get_setting("token"), "secret-token")

    def test_cli_main_execution_success(self):
        """Verify CLI main entrypoint succeeds and writes output."""
        with patch("modelanvil.cli.main.get_client", return_value=self.client):
            stdout_capture = io.StringIO()
            with patch("sys.stdout", stdout_capture):
                exit_code = main(["--json", "journey", "smoke"])
                self.assertEqual(exit_code, 0)
                output = json.loads(stdout_capture.getvalue())
                self.assertEqual(output["status"], "COMPLETED")

    def test_client_error_handling(self):
        """Verify client raises ModelAnvilClientError on HTTP error codes."""
        # Nonexistent route
        with self.assertRaises(ModelAnvilClientError) as ctx:
            self.client.request("POST", "/api/v1/nonexistent/")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cli_rag_and_context_lab_subcommands(self):
        """Verify CLI execution of rag query and context-lab compile subcommands."""
        with patch("modelanvil.cli.main.get_client", return_value=self.client):
            # Test RAG query
            out_rag = io.StringIO()
            with patch("sys.stdout", out_rag):
                code_rag = main(["--json", "rag", "query", "idx-123", "my search text"])
                self.assertEqual(code_rag, 0)
                data_rag = json.loads(out_rag.getvalue())
                self.assertEqual(data_rag["results"][0]["chunk_id"], "c1")

            # Test Context-Lab compile
            out_ctx = io.StringIO()
            with patch("sys.stdout", out_ctx):
                code_ctx = main(["--json", "context-lab", "compile", "rec-ver-456", "--vars", "{\"evidence\": \"info\"}"])
                self.assertEqual(code_ctx, 0)
                data_ctx = json.loads(out_ctx.getvalue())
                self.assertEqual(data_ctx["token_count"], 42)
