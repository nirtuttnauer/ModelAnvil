"""Bounded local JSONL preparation and verified dataset publication.

This synchronous development slice is not the streaming WP-05 pipeline.
Database publication is transactional; filesystem writes are not a database
transaction and may leave an unreferenced unique output after a later failure.
"""
import hashlib
import csv
import io
import json
import uuid
import zipfile
from xml.etree.ElementTree import ParseError

from django.conf import settings
from django.db import transaction
from django.db.models import Max

from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, LineageEdge
from modelanvil.artifacts.storage import LocalArtifactStorage, artifact_storage_backend, upload_staged_artifact

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_ROWS = 10000


class DatasetPreparationError(ValueError):
    """A client-safe preparation refusal; never includes input values."""


def _reject_constant(value):
    raise DatasetPreparationError("Input must contain finite JSON values.")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DatasetPreparationError("Input contains duplicate JSON object keys.")
        result[key] = value
    return result


def _documents(raw):
    # splitlines() is bounded by the verified 16 MiB input cap, not the corpus.
    try:
        text = raw.decode("utf-8")
        for line in text.split("\n")[:-1] if text.endswith("\n") else text.split("\n"):
            if not line.strip():
                raise DatasetPreparationError("Input must contain one JSON envelope per nonempty line.")
            yield json.loads(line, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise DatasetPreparationError("Input must be valid UTF-8 canonical sample-envelope JSONL.") from None


def _read_verified_input(artifact, backend):
    if artifact.byte_size < 1 or artifact.byte_size > MAX_INPUT_BYTES:
        raise DatasetPreparationError("Input must contain 1 byte to 16 MiB of source data.")
    digest = hashlib.sha256()
    raw = bytearray()
    try:
        with backend.open(artifact.tenant_id, str(artifact.object_key)) as stream:
            while True:
                block = stream.read(min(65536, MAX_INPUT_BYTES + 1 - len(raw)))
                if not isinstance(block, bytes):
                    raise DatasetPreparationError("Input bytes are unavailable.")
                if not block:
                    break
                raw.extend(block)
                if len(raw) > MAX_INPUT_BYTES:
                    raise DatasetPreparationError("Input exceeds the 16 MiB preparation limit.")
                digest.update(block)
    except (OSError, ValueError, TypeError):
        raise DatasetPreparationError("Input bytes could not be verified.") from None
    if len(raw) != artifact.byte_size or digest.hexdigest() != artifact.sha256:
        raise DatasetPreparationError("Input bytes do not match the committed digest and size.")
    return bytes(raw)


@transaction.atomic
def publish_prepared_dataset(dataset, artifact, *, split_seed="0", validation_percent=10, test_percent=10,
                             detect=None, dedup=None, protected=None,
                             near_threshold=3, min_text_chars=None,
                             source_format="jsonl", text_field="text", group_field=None):
    # Serialize revision numbering/publication per dataset and pin input state
    # until publication. All callers acquire locks in this order.
    dataset = Dataset.all_objects.select_for_update().get(pk=dataset.pk, tenant_id=dataset.tenant_id)
    artifact = Artifact.all_objects.select_for_update().get(pk=artifact.pk, tenant_id=dataset.tenant_id)
    if artifact.state != Artifact.State.COMMITTED:
        raise DatasetPreparationError("Input must remain committed until publication.")
    backend = artifact_storage_backend()
    if artifact.storage_location_id != "local" or artifact.object_version is not None:
        raise DatasetPreparationError("Preparation currently supports only unversioned local storage artifacts.")
    from modelanvil.data.source_import import MEDIA_TYPES, VERSION, PDF_VERSION, SourceImportError, extract_source
    if artifact.media_type != {"jsonl": "application/x-ndjson", **MEDIA_TYPES}.get(source_format):
        raise DatasetPreparationError("Source format does not match the committed media type.")
    if source_format == "jsonl" and (text_field != "text" or group_field is not None):
        raise DatasetPreparationError("Canonical envelopes do not support field mappings.")
    raw = _read_verified_input(artifact, backend)
    # The independent, pure kernel is deliberately imported only at execution.
    from modelanvil.data.preparation import prepare_envelopes
    try:
        documents = _documents(raw) if source_format == "jsonl" else extract_source(raw,
            source_format=source_format, text_field=text_field, group_field=group_field)
        prepared = prepare_envelopes(documents, split_seed=split_seed,
            validation_percent=validation_percent, test_percent=test_percent, max_rows=MAX_ROWS,
            detect=detect, dedup=dedup, protected=protected,
            near_threshold=near_threshold, min_text_chars=min_text_chars)
        if source_format != "jsonl":
            prepared["recipe"]["extraction"] = {"version": VERSION, "source_format": source_format,
                "input_sha256": artifact.sha256, "text_field": text_field, "group_field": group_field}
            if source_format == "pdf":
                prepared["recipe"]["extraction"]["pdf_parser"] = f"pypdf=={PDF_VERSION}"
            prepared["recipe_digest"] = hashlib.sha256(json.dumps(prepared["recipe"], sort_keys=True,
                separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        payload = json.dumps(prepared, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except SourceImportError as exc:
        raise DatasetPreparationError(str(exc)) from None
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError, zipfile.BadZipFile, ParseError, RuntimeError, OSError, csv.Error):
        raise DatasetPreparationError("Input or split recipe is invalid for bounded source preparation.") from None
    manifest = Artifact.all_objects.create(
        tenant_id=dataset.tenant_id, project_id=dataset.project_id, storage_location_id="local",
        object_key=f"datasets/{dataset.dataset_id}/{uuid.uuid4()}.json",
        sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type="application/json",
        metadata={"kind": "prepared_dataset", "input_artifact_id": str(artifact.artifact_id)})
    upload_staged_artifact(manifest, io.BytesIO(payload), backend=backend)
    latest = DatasetRevision.all_objects.filter(dataset=dataset, tenant_id=dataset.tenant_id).aggregate(
        number=Max("revision_no"))["number"] or 0
    revision_metadata = {
        "preparation_kind": "bounded_local_jsonl_v1" if source_format == "jsonl" else VERSION,
        "input_artifact_id": str(artifact.artifact_id),
        "input_sha256": artifact.sha256,
        "recipe": prepared["recipe"],
        "source_group_count": prepared["source_group_count"],
        "split_counts": {key: len(values) for key, values in prepared["split_manifest"].items()},
    }
    if "report" in prepared:
        # Aggregate drop transparency on the revision row; per-sample drop
        # details live in the manifest artifact only, keeping the DB slim.
        revision_metadata["drop_report"] = prepared["report"]
    revision = DatasetRevision.all_objects.create(
        tenant_id=dataset.tenant_id, dataset=dataset, revision_no=latest + 1,
        schema_version=prepared["schema_version"], manifest_digest=manifest.sha256,
        manifest_artifact=manifest, recipe_digest=prepared["recipe_digest"],
        source_snapshots=[], row_count=prepared["row_count"],
        state=DatasetRevision.State.PUBLISHED,
        published_at=manifest.committed_at or manifest.created_at,
        metadata=revision_metadata)
    dataset.current_revision = revision
    dataset.save(update_fields=["current_revision", "updated_at"])
    LineageEdge.all_objects.create(
        tenant_id=dataset.tenant_id, parent_artifact=artifact, child_artifact=manifest,
        relation="derived_dataset", detail={"recipe_digest": prepared["recipe_digest"]})
    return revision
