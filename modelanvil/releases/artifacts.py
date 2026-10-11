"""Read the committed, accessible numerical bundle pinned by a release."""
import json

from modelanvil.artifacts.models import Artifact, DeletionTombstone
from modelanvil.core.tenancy import get_active_project
from modelanvil.runners.training.runtime import read_artifact
from modelanvil.runners.training.registry import verify_bundle


def release_model_bundle(version):
    model = version.model_version
    if model is None:
        return None
    if model.tenant_id != version.tenant_id or model.tokenizer.tenant_id != version.tenant_id:
        raise ValueError("Release components must belong to this tenant.")
    for component in (model.model_version_id, model.tokenizer.tokenizer_id):
        if DeletionTombstone.all_objects.filter(tenant_id=version.tenant_id, resource_id=str(component)).exists():
            raise PermissionError("A release component is tombstoned.")
    if not model.artifact_manifest_id:
        return None
    try:
        artifact = Artifact.all_objects.get(tenant_id=version.tenant_id, artifact_id=model.artifact_manifest_id)
    except (Artifact.DoesNotExist, ValueError):
        raise ValueError("The pinned model bundle artifact is unavailable.") from None
    raw = read_artifact(artifact, version.tenant_id, get_active_project() or version.project_id)
    try:
        bundle = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("The pinned model artifact is not a JSON bundle.") from None
    if not isinstance(bundle, dict):
        raise ValueError("The pinned model artifact must contain a bundle object.")
    # shortcut: bounded local CPU bundles; large external weight exports use their protected artifact download.
    verification = verify_bundle(bundle)
    if bundle.get("config.json", {}).get("vocab_size") != model.tokenizer.vocabulary_size:
        raise ValueError("Pinned weights do not match the release tokenizer vocabulary.")
    if model.metadata.get("weights_sha256") and model.metadata["weights_sha256"] != verification["weights_sha256"]:
        raise ValueError("Pinned weights do not match the model version checksum.")
    return {"artifact": artifact, "bundle": bundle, "verification": verification}
