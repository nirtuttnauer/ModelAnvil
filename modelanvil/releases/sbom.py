"""SPDX inventory with checksums from verified committed model bytes."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from modelanvil.releases.artifacts import release_model_bundle
from modelanvil.releases.models import ReleaseVersion


@dataclass(frozen=True)
class ModelSBOMReport:
    spdx_id: str
    sbom_digest: str
    spdx_document: dict[str, Any]
    verified: bool
    warnings: list[str]


def generate_model_sbom(release_version: ReleaseVersion, *, creator_org: str = "ModelAnvil",
                        environment_info: Optional[Mapping[str, str]] = None) -> ModelSBOMReport:
    model = release_version.model_version
    if model is None:
        raise ValueError("Cannot generate SBOM without an associated model version.")
    material = release_model_bundle(release_version)
    tokenizer = model.tokenizer
    spdx_id = f"SPDXRef-ModelAnvil-Model-{model.model_version_id}"
    tok_id = f"SPDXRef-Tokenizer-{tokenizer.tokenizer_id}"
    model_package = {
        "SPDXID": spdx_id, "name": model.model.name, "versionInfo": f"r{model.revision_no}",
        "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
        "licenseConcluded": model.license_evidence or "NOASSERTION",
        "licenseDeclared": model.license_evidence or "NOASSERTION",
    }
    tok_package = {
        "SPDXID": tok_id, "name": tokenizer.name, "versionInfo": f"r{tokenizer.revision_no}",
        "downloadLocation": "NOASSERTION", "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION",
    }
    warnings = ["Licenses and dataset lineage are recorded metadata, not independently attested.",
                "Checksum verification does not establish production or hardware qualification."]
    if material:
        model_package["checksums"] = [{"algorithm": "SHA256", "checksumValue": material["verification"]["weights_sha256"]}]
        model_package["packageFileName"] = "model.safetensors"
        config = material["bundle"].get("tokenizer_config.json")
        if config is not None:
            raw = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            tok_package["checksums"] = [{"algorithm": "SHA256", "checksumValue": hashlib.sha256(raw).hexdigest()}]
            tok_package["packageFileName"] = "tokenizer_config.json"
    else:
        warnings.append("Metadata-only inventory: no committed model weights are pinned; no byte checksums are asserted.")
    document = {
        "spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"ModelAnvil-SBOM-{model.model.name}",
        "documentNamespace": f"https://modelanvil.invalid/spdx/{release_version.release_version_id}/{material['artifact'].sha256 if material else 'metadata'}",
        "creationInfo": {"created": release_version.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "creators": [f"Organization: {creator_org}", "Tool: ModelAnvil-Release-Manager"]},
        "packages": [model_package, tok_package],
        "relationships": [
            {"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": spdx_id},
            {"spdxElementId": spdx_id, "relationshipType": "DEPENDS_ON", "relatedSpdxElement": tok_id},
        ],
    }
    canonical = json.dumps(document, sort_keys=True, indent=2).encode("utf-8")
    return ModelSBOMReport(spdx_id, hashlib.sha256(canonical).hexdigest(), document, bool(material), warnings)
