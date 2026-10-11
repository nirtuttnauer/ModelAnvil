"""Programmatic Python API client for ModelAnvil.

Allows direct integration with the ModelAnvil control plane for the complete
API-only developer journey: import -> train -> evaluate -> export (TECH-004),
as well as worker administration and hybrid credential configuration (TECH-029).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union


class ModelAnvilClientError(Exception):
    """Exception raised for API client errors with status code and payload."""

    def __init__(self, message: str, status_code: Optional[int] = None, payload: Optional[Any] = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ModelAnvilClient:
    """Client for the ModelAnvil REST API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        tenant_id: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[Any] = None,  # Custom transport (e.g. Django test client) for testing
    ):
        self.base_url = (base_url or os.environ.get("MODELANVIL_URL", "http://localhost:8000")).rstrip("/")
        self.token = token or os.environ.get("MODELANVIL_TOKEN", "")
        self.tenant_id = tenant_id or os.environ.get("MODELANVIL_TENANT", "")
        self.timeout = timeout
        self.transport = transport

    def _headers(self, custom: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.tenant_id:
            headers["X-Tenant-ID"] = self.tenant_id
        if custom:
            headers.update(custom)
        return headers

    def request(
        self,
        method: str,
        path: str,
        data: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Execute an HTTP request against the API."""
        norm_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{norm_path}"
        req_headers = self._headers(headers)

        if self.transport is not None:
            # Custom transport (e.g. test client)
            method_fn = getattr(self.transport, method.lower())
            kwargs: Dict[str, Any] = {}
            if data is not None:
                if isinstance(data, (dict, list)):
                    kwargs["data"] = json.dumps(data)
                    kwargs["content_type"] = "application/json"
                else:
                    kwargs["data"] = data
            for k, v in req_headers.items():
                if k.lower() == "authorization":
                    kwargs["HTTP_AUTHORIZATION"] = v
                elif k.lower() == "x-tenant-id":
                    kwargs["HTTP_X_TENANT_ID"] = v
            response = method_fn(norm_path, **kwargs)
            status_code = getattr(response, "status_code", 200)
            content = getattr(response, "content", b"")
            if status_code >= 400:
                try:
                    payload = json.loads(content.decode("utf-8"))
                except Exception:
                    payload = content.decode("utf-8")
                raise ModelAnvilClientError(
                    f"HTTP {status_code}: {payload}", status_code=status_code, payload=payload
                )
            if not content:
                return {}
            try:
                return json.loads(content.decode("utf-8"))
            except Exception:
                return {"raw": content.decode("utf-8")}

        # Standard library urllib request
        body_bytes = None
        if data is not None:
            if isinstance(data, (dict, list)):
                body_bytes = json.dumps(data).encode("utf-8")
            elif isinstance(data, str):
                body_bytes = data.encode("utf-8")
            elif isinstance(data, bytes):
                body_bytes = data

        req = urllib.request.Request(url, data=body_bytes, headers=req_headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(err_body)
            except Exception:
                payload = err_body
            raise ModelAnvilClientError(
                f"HTTP {err.code}: {payload}", status_code=err.code, payload=payload
            ) from err
        except urllib.error.URLError as err:
            raise ModelAnvilClientError(f"Network error: {err.reason}") from err

    # -------------------------------------------------------------------------
    # Datasets API
    # -------------------------------------------------------------------------
    def create_dataset(self, name: str, description: str = "") -> Dict[str, Any]:
        return self.request("POST", "/api/v1/datasets/", {"name": name, "description": description})

    def list_datasets(self) -> List[Dict[str, Any]]:
        res = self.request("GET", "/api/v1/datasets/")
        return res.get("results", res) if isinstance(res, dict) else res

    def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/api/v1/datasets/{dataset_id}/")

    # -------------------------------------------------------------------------
    # Training API
    # -------------------------------------------------------------------------
    def launch_training_run(
        self,
        name: str,
        recipe: str,
        hyperparameters: Optional[Dict[str, Any]] = None,
        dataset_version_id: Optional[str] = None,
        model_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "name": name,
            "recipe": recipe,
            "hyperparameters": hyperparameters or {},
            "dataset_version_id": dataset_version_id,
            "model_version_id": model_version_id,
        }
        return self.request("POST", "/api/v1/training-runs/", payload)

    def get_training_run(self, run_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/api/v1/training-runs/{run_id}/")

    # -------------------------------------------------------------------------
    # Evaluation API
    # -------------------------------------------------------------------------
    def launch_evaluation_run(
        self,
        name: str,
        model_version_id: str,
        evaluation_suite_id: str,
    ) -> Dict[str, Any]:
        payload = {
            "name": name,
            "model_version_id": model_version_id,
            "evaluation_suite_id": evaluation_suite_id,
        }
        return self.request("POST", "/api/v1/evaluation-runs/", payload)

    def get_evaluation_run(self, run_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/api/v1/evaluation-runs/{run_id}/")

    # -------------------------------------------------------------------------
    # Releases & Exports API
    # -------------------------------------------------------------------------
    def create_release(
        self,
        name: str,
        model_version_id: str,
        semantic_version: str = "1.0.0",
    ) -> Dict[str, Any]:
        payload = {
            "name": name,
            "model_version_id": model_version_id,
            "semantic_version": semantic_version,
        }
        return self.request("POST", "/api/v1/releases/", payload)

    def export_release(self, release_version_id: str) -> Dict[str, Any]:
        return self.request("POST", f"/api/v1/release-versions/{release_version_id}/export/")

    # -------------------------------------------------------------------------
    # Hybrid Workers API (TECH-029)
    # -------------------------------------------------------------------------
    def enroll_worker(self, pool_id: int, name: str) -> Dict[str, Any]:
        return self.request("POST", "/api/v1/workers/register/", {"pool_id": pool_id, "name": name})

    def configure_pool_egress(self, pool_id: int, mode: str) -> Dict[str, Any]:
        return self.request("POST", f"/api/v1/workers/pools/{pool_id}/egress/", {"result_egress": mode})

    # -------------------------------------------------------------------------
    # High-level API-only Journey (TECH-004)
    # -------------------------------------------------------------------------
    def run_api_journey(
        self,
        dataset_name: str,
        model_name: str,
        recipe: str = "pretrain_scratch",
    ) -> Dict[str, Any]:
        """Executes the complete API-only journey:
        Import Dataset -> Launch Training -> Launch Evaluation -> Export Release Bundle.
        """
        # 1. Dataset import/create
        dataset = self.create_dataset(name=dataset_name)
        dataset_id = dataset.get("dataset_id") or dataset.get("id")

        # 2. Training launch
        train_run = self.launch_training_run(
            name=f"run-{dataset_name}",
            recipe=recipe,
            dataset_version_id=dataset_id,
        )
        train_id = train_run.get("run_id") or train_run.get("id")

        # 3. Evaluation launch
        eval_run = self.launch_evaluation_run(
            name=f"eval-{dataset_name}",
            model_version_id=train_run.get("model_version_id", str(train_id)),
            evaluation_suite_id="default-suite",
        )
        eval_id = eval_run.get("run_id") or eval_run.get("id")

        # 4. Release export
        release = self.create_release(
            name=f"rel-{dataset_name}",
            model_version_id=train_run.get("model_version_id", str(train_id)),
        )
        rel_ver_id = release.get("release_version_id") or release.get("id")
        export_bundle = self.export_release(str(rel_ver_id))

        return {
            "status": "COMPLETED",
            "dataset": dataset,
            "training_run": train_run,
            "evaluation_run": eval_run,
            "release": release,
            "export_bundle": export_bundle,
        }

    # -------------------------------------------------------------------------
    # RAG & Context Lab APIs
    # -------------------------------------------------------------------------
    def query_rag(
        self,
        index_id: str,
        query: str,
        mode: str = "hybrid",
        top_k: int = 5,
    ) -> Dict[str, Any]:
        return self.request(
            "POST",
            f"/api/v1/index-versions/{index_id}/query/",
            {"query": query, "mode": mode, "top_k": top_k},
        )

    def compile_context(
        self,
        recipe_version_id: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.request(
            "POST",
            f"/api/v1/context-recipe-versions/{recipe_version_id}/compile/",
            {"variables": variables or {}},
        )

    def search_dataset_bank(self, query: str = "") -> Dict[str, Any]:
        return self.request("GET", f"/api/v1/dataset-bank/?search={query}")

    def get_release_sbom(self, release_version_id: str) -> Dict[str, Any]:
        return self.request("GET", f"/api/v1/release-versions/{release_version_id}/sbom/")
