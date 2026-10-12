"""Runpod REST v2. Fixed origin, bounded bodies, no redirects or implicit retries."""
import json
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

from modelanvil.compute.plugins import ProviderError

SPEC_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["gpu_id", "gpu_count", "disk_gb", "cloud", "data_center_ids"],
    "properties": {
        "gpu_id": {"type": "string", "minLength": 1, "maxLength": 120},
        "gpu_count": {"type": "integer", "minimum": 1, "maximum": 8},
        "disk_gb": {"type": "integer", "minimum": 1, "maximum": 1000},
        "cloud": {"enum": ["SECURE", "COMMUNITY"]},
        "data_center_ids": {"type": "array", "minItems": 1, "maxItems": 16, "uniqueItems": True,
                            "items": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}},
    },
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RunpodProvider:
    def __init__(self, api_key):
        if not isinstance(api_key, str) or not api_key or any(ord(c) < 33 or ord(c) > 126 for c in api_key):
            raise ValueError("Invalid provider credential.")
        self._api_key = api_key
        self._opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def _request(self, method, path, payload=None):
        request = Request("https://api.runpod.io/v2/" + path,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json"},
                          method=method)
        try:
            with self._opener.open(request, timeout=30) as response:
                status = response.status
                raw = response.read(1024 * 1024 + 1)
            if status == 204:
                return None
            if status not in (200, 201) or len(raw) > 1024 * 1024:
                raise ProviderError("provider_invalid_response")
            return json.loads(raw)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 404 and method in ("GET", "DELETE"):
                return None
            codes = {401: "provider_auth_failed", 403: "provider_forbidden", 402: "provider_balance_required",
                     400: "provider_request_rejected", 422: "provider_request_rejected", 429: "provider_rate_limited"}
            raise ProviderError(codes.get(status, "provider_unavailable"), uncertain=status >= 500 or 300 <= status < 400) from None
        except (URLError, OSError, ValueError):
            raise ProviderError("provider_transport_uncertain") from None

    def catalog(self):
        data = self._request("GET", "catalog/gpus")
        if not isinstance(data, dict) or not isinstance(data.get("gpus"), list):
            raise ProviderError("provider_invalid_response")
        return [{key: row[key] for key in ("id", "name", "memory", "availability", "price", "maxCount", "dataCenters") if key in row}
                for row in data["gpus"] if isinstance(row, dict)]

    @staticmethod
    def _resource(row):
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", row["id"])
                or not isinstance(row.get("name"), str)
                or row.get("status") not in {"PROVISIONING", "RUNNING", "EXITED", "TERMINATED"}):
            raise ProviderError("provider_invalid_response")
        return {"id": row["id"], "name": row["name"], "status": row["status"]}

    def create(self, name, spec, bootstrap):
        return self._resource(self._request("POST", "pods", {
            "name": name, "image": bootstrap["image"], "entrypoint": ["python", "-m", "modelanvil.compute.worker"],
            "cmd": [], "env": bootstrap["env"], "ports": [], "disk": spec["disk_gb"],
            "gpu": {"id": spec["gpu_id"], "count": spec["gpu_count"]},
            "cloud": spec["cloud"], "dataCenterIds": spec["data_center_ids"],
        }))

    def inspect(self, resource_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resource_id):
            raise ProviderError("provider_invalid_identity")
        row = self._request("GET", "pods/" + resource_id)
        return None if row is None else self._resource(row)

    def find(self, name):
        cursor, seen, matches = None, set(), []
        for _ in range(100):
            data = self._request("GET", "pods?" + urlencode({"limit": 100, **({"cursor": cursor} if cursor else {})}))
            if not isinstance(data, dict) or not isinstance(data.get("pods"), list) or not isinstance(data.get("pagination"), dict):
                raise ProviderError("provider_invalid_response")
            matches.extend(self._resource(row) for row in data["pods"] if isinstance(row, dict) and row.get("name") == name)
            page = data["pagination"]
            if page.get("hasNextPage") is False:
                return matches
            cursor = page.get("nextCursor")
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in seen:
                raise ProviderError("provider_invalid_pagination")
            seen.add(cursor)
        raise ProviderError("provider_catalog_too_large")

    def release(self, resource_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", resource_id):
            raise ProviderError("provider_invalid_identity")
        self._request("DELETE", "pods/" + resource_id)
