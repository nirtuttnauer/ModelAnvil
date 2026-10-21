"""Bounded, queued, resumable Dataset Bank acquisition with verified publication.

Acquisition is only offered for catalog sources that carry a qualification
record: an implemented connector, a pinned immutable upstream revision, and
measured evidence that bytes were really fetched and digest-verified. Every
other source stays explicitly unavailable.

The flow reuses the existing foundations: :class:`ResumablePresetDownloader`
for tenant-scoped snapshot lifecycle and cache isolation,
``prepare_svg_record`` for SVG preparation and label provenance, the durable
``Job``/``Worker``/fencing protocol for execution capacity, the budget
reservation ledger for admission, and ``publish_prepared_dataset`` for the
immutable, digest-verified publication.

Resumption is record-granular: every verified upstream record is checkpointed
on the source snapshot, so an interrupted, cancelled or fenced-out transfer
restarts at the first unverified record without re-fetching verified bytes.
"""
from __future__ import annotations

import fnmatch
import hashlib
import io
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from modelanvil.core.ids import uuid7
from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, LineageEdge
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation, UsageEvent
from modelanvil.data.bank.catalog import DatasetBankCatalog, SourceCard
from modelanvil.data.bank.downloader import ResumablePresetDownloader
from modelanvil.data.bank.svg_starter import prepare_svg_record
from modelanvil.data.bank.http_snapshot import (
    CONNECTOR as HTTP_SUBSET_CONNECTOR, MAX_TRANSFER_BYTES, SnapshotError,
    cached_transport, fetch_qualified_record, load_manifest, record_url, validate_sample,
)
from modelanvil.data.models import SourceSnapshot
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.jobs.models import Job, Worker, WorkerPool
from modelanvil.identity.models import check_resource_access

JOB_TYPE = "dataset_acquisition"
ACQUISITION_CAPABILITY = "dataset_acquisition"
DEFAULT_POOL_NAME = "dataset-acquisition"
UPSTREAM_TIMEOUT_SECONDS = 20
MAX_RECORD_BYTES = 1 * 1024 * 1024
USER_AGENT = "modelanvil-dataset-bank"
#: Deterministic envelope identity namespace for acquired bank records.
ENVELOPE_NAMESPACE = uuid.UUID("6f2c1f8e-4b0a-5f52-9f4f-6a1d1c9d7b31")

Transport = Callable[[str, dict[str, str]], "tuple[int, bytes, dict[str, str]]"]


class AcquisitionRefused(ValidationError):
    """A client-safe acquisition refusal; never includes upstream response bodies."""


class AcquisitionCapacityError(ValidationError):
    """No worker capacity is registered for acquisition."""


class UpstreamError(RuntimeError):
    """A sanitized upstream transport or integrity failure."""


class AcquisitionCancelled(RuntimeError):
    """The operator or the tenant cancelled this transfer."""


class RecordStore:
    """Durable per-snapshot store for verified upstream record bytes.

    Verified bytes are appended and flushed before the snapshot checkpoint is
    written, so an interrupted transfer resumes from exactly the records whose
    bytes are already on disk. Each line is re-digest-verified on load; an
    unverifiable or foreign line is dropped and re-fetched.
    """

    def __init__(self, tenant_id: Any, snapshot_id: Any) -> None:
        root = Path(settings.MODELANVIL["artifact_root"]) / "bank-transfers" / str(tenant_id)
        self.path = root / f"{snapshot_id}.jsonl"
        self._tenant_id = str(tenant_id)

    def load(self, expected: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        recovered: dict[str, dict[str, Any]] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.endswith("\n"):
                        break
                    try:
                        entry = json.loads(line)
                        payload = bytes.fromhex(entry["payload_hex"])
                    except (ValueError, KeyError, TypeError):
                        break
                    if entry.get("snapshot_ref") != self._tenant_id + "/" + self.path.stem:
                        break
                    if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
                        break
                    record = expected.get(entry.get("path"))
                    if record is None or entry.get("blob_sha1") != record.get("blob_sha1"):
                        break
                    recovered[entry["path"]] = entry
        except OSError:
            return {}
        return recovered

    def append(self, snapshot_ref: str, path: str, payload: bytes, *, sha256: str, blob_sha1: str) -> None:
        line = json.dumps({
            "snapshot_ref": snapshot_ref, "path": path, "sha256": sha256,
            "blob_sha1": blob_sha1, "size": len(payload), "payload_hex": payload.hex(),
        }, sort_keys=True, separators=(",", ":")) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())

    def discard(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


class AcquisitionLeaseLost(RuntimeError):
    """A stale worker leaves its checkpoint for the reconciled job to resume."""

    pass


def https_transport(url: str, headers: dict[str, str]) -> "tuple[int, bytes, dict[str, str]]":
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_TRANSFER_BYTES + 1)
            if len(body) > MAX_TRANSFER_BYTES:
                raise UpstreamError("Upstream response exceeds the bounded transfer size.")
            return response.status, body, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raise UpstreamError(f"Upstream returned HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise UpstreamError("Upstream is unreachable.") from None


@dataclass(frozen=True)
class UpstreamRecord:
    """One immutable upstream blob selected for acquisition."""

    path: str
    blob_sha1: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "blob_sha1": self.blob_sha1, "size": self.size}


def git_blob_digest(payload: bytes) -> str:
    """Recompute the Git blob object id from raw bytes for integrity verification."""
    return hashlib.sha1(b"blob %d\0" % len(payload) + payload).hexdigest()


def _repository_api_base(repository: str) -> str:
    if not repository.startswith("https://"):
        raise UpstreamError("Upstream repository must use HTTPS.")
    remainder = repository[len("https://"):]
    if "/" not in remainder:
        raise UpstreamError("Upstream repository URL is malformed.")
    host, path = remainder.split("/", 1)
    if host != "github.com" or not path.endswith(".git"):
        raise UpstreamError("Upstream repository host is not a supported qualified connector.")
    return "https://api.github.com/repos/" + path[:-len(".git")]


def _raw_base(repository: str, revision: str) -> str:
    if not repository.startswith("https://github.com/"):
        raise UpstreamError("Upstream repository host is not a supported qualified connector.")
    remainder = repository[len("https://github.com/"):]
    if not remainder.endswith(".git"):
        raise UpstreamError("Upstream repository URL is malformed.")
    return f"https://raw.githubusercontent.com/{remainder[:-len('.git')]}/{revision}/"


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def select_records(inventory: list[UpstreamRecord], limit: int) -> list[UpstreamRecord]:
    """Deterministic evenly spaced slice of the sorted upstream inventory."""
    if limit <= 0 or limit >= len(inventory):
        return list(inventory)
    step = len(inventory) / limit
    return [inventory[int(index * step)] for index in range(limit)]


def _read_json(url: str, transport: Transport) -> dict[str, Any]:
    status, body, _headers = transport(url, {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    if status != 200:
        raise UpstreamError(f"Upstream returned HTTP {status}.")
    try:
        parsed = json.loads(body)
    except (UnicodeError, ValueError):
        raise UpstreamError("Upstream listing was not valid JSON.") from None
    if not isinstance(parsed, dict):
        raise UpstreamError("Upstream listing was not a JSON object.")
    return parsed


def upstream_head_revision(source: SourceCard, *, transport: Optional[Transport] = None) -> str:
    """Resolve the current upstream branch head without changing the pinned revision."""
    transport = transport or https_transport
    base = _repository_api_base(source.acquisition.upstream_repository)
    payload = _read_json(f"{base}/git/ref/heads/{source.fetch.get('ref_hint') or 'main'}", transport)
    target = payload.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit" or not isinstance(target.get("sha"), str):
        raise UpstreamError("Upstream reference did not resolve to a commit.")
    return target["sha"]


def list_inventory(
    source: SourceCard, *, transport: Optional[Transport] = None
) -> tuple[list[UpstreamRecord], list[UpstreamRecord]]:
    """Return (selected-pattern records, license-path records) at the pinned revision."""
    transport = transport or https_transport
    card = source.acquisition
    if card.connector == HTTP_SUBSET_CONNECTOR:
        manifest = load_manifest(source)
        records = [UpstreamRecord(entry["path"], entry["blob_sha1"], entry["size"]) for entry in manifest["records"]]
        notices = [UpstreamRecord(entry["path"], entry["blob_sha1"], entry["size"]) for entry in manifest["licenses"]]
        return sorted(records, key=lambda record: record.path), notices
    base = _repository_api_base(card.upstream_repository)
    try:
        payload = _read_json(f"{base}/git/trees/{card.pinned_revision}?recursive=1", transport)
    except UpstreamError as exc:
        # Public GitHub API quotas must not prevent downloading pinned raw files.
        inventory_path = card.evidence.get("inventory_path")
        if str(exc) not in ("Upstream returned HTTP 403.", "Upstream returned HTTP 429.") or not inventory_path:
            raise
        root = Path(__file__).resolve().parents[3] / "catalog" / "qualified-datasets"
        path = (root.parent.parent / inventory_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise UpstreamError("Pinned upstream inventory is unavailable.") from None
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != card.evidence.get("inventory_sha256"):
            raise UpstreamError("Pinned upstream inventory failed digest verification.") from None
        payload = json.loads(raw)
        if payload.get("revision") != card.pinned_revision:
            raise UpstreamError("Pinned upstream inventory does not match the qualified revision.")
    if payload.get("truncated"):
        raise UpstreamError("Upstream tree listing was truncated; the scope cannot be bounded.")
    entries = payload.get("tree")
    if not isinstance(entries, list):
        raise UpstreamError("Upstream tree listing is malformed.")

    records: list[UpstreamRecord] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("type") != "blob":
            continue
        path, sha, size = entry.get("path"), entry.get("sha"), entry.get("size")
        if not isinstance(path, str) or not isinstance(sha, str) or not isinstance(size, int) or size < 0:
            continue
        if _matches_any(path, card.include_patterns):
            records.append(UpstreamRecord(path, sha, size))
    if not records:
        raise UpstreamError("No upstream record matched the qualified include patterns.")
    records.sort(key=lambda record: record.path)

    licenses: list[UpstreamRecord] = []
    for path in card.license_paths:
        match = next((entry for entry in records if entry.path == path), None)
        if match is None:
            for entry in entries:
                if isinstance(entry, dict) and entry.get("path") == path and entry.get("type") == "blob":
                    match = UpstreamRecord(path, str(entry.get("sha")), int(entry.get("size") or 0))
                    break
        if match is None:
            raise UpstreamError(f"Declared license path {path!r} is absent at the pinned revision.")
        licenses.append(match)
    return records, licenses


def fetch_record(
    source: SourceCard, record: UpstreamRecord, *, transport: Optional[Transport] = None
) -> bytes:
    """Fetch one blob at the pinned revision and verify its Git object id."""
    transport = transport or https_transport
    if source.acquisition.connector == HTTP_SUBSET_CONNECTOR:
        try:
            body = fetch_qualified_record(source, record, transport)
            if not record.path.startswith("notice/"):
                validate_sample(source.id, body)
            return body
        except SnapshotError as exc:
            raise UpstreamError(str(exc)) from None
    raw_base = _raw_base(source.acquisition.upstream_repository, source.acquisition.pinned_revision)
    url = raw_base + quote(record.path)
    status, body, _headers = transport(url, {"User-Agent": USER_AGENT})
    if status != 200:
        raise UpstreamError(f"Upstream returned HTTP {status} for {record.path!r}.")
    if len(body) != record.size:
        raise UpstreamError(f"Upstream record {record.path!r} changed size at the pinned revision.")
    if len(body) > MAX_RECORD_BYTES:
        raise UpstreamError(f"Upstream record {record.path!r} exceeds the bounded record size.")
    if git_blob_digest(body) != record.blob_sha1:
        raise UpstreamError(f"Upstream record {record.path!r} failed digest verification.")
    return body


def preview_samples(
    source: SourceCard,
    *,
    limit: Optional[int] = None,
    transport: Optional[Transport] = None,
    inventory: Optional[tuple[list[UpstreamRecord], list[UpstreamRecord]]] = None,
) -> list[dict[str, Any]]:
    """Fetch real bounded records from the pinned upstream revision."""
    transport = cached_transport(transport or https_transport)
    card = source.acquisition
    inventory = inventory or list_inventory(source, transport=transport)
    count = limit or card.preview_limit or 5
    selected = select_records(inventory[0], max(1, min(int(count), card.record_limit or count)))
    samples: list[dict[str, Any]] = []
    for record in selected:
        payload = fetch_record(source, record, transport=transport)
        if card.connector == HTTP_SUBSET_CONNECTOR:
            content = json.loads(payload)
            for field in ("image_hex", "audio_hex"):
                if field in content:
                    media = bytes.fromhex(content.pop(field))
                    content[field.removesuffix("_hex")] = {"byte_size": len(media), "sha256": hashlib.sha256(media).hexdigest()}
            samples.append({"upstream_path": record.path, "upstream_url": _record_url(source, record.path),
                "byte_size": record.size, "content_sha256": hashlib.sha256(payload).hexdigest(),
                "digest_verified": True, "license": source.license_expression, "content": content})
            continue
        item = prepare_svg_record(
            source_library=source.id.split("-", 1)[-1],
            icon_name=record.path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            svg_content=payload.decode("utf-8"),
        )
        samples.append({
            "upstream_path": record.path,
            "upstream_url": _raw_base(card.upstream_repository, card.pinned_revision) + quote(record.path),
            "upstream_blob_sha1": record.blob_sha1,
            "byte_size": record.size,
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "digest_verified": True,
            "icon_name": item.icon_name,
            "concept_group": item.concept_group,
            "variant_type": item.variant_type,
            "label": item.label,
            "label_provenance": item.label_provenance,
            "license": item.license,
            "attribution_notice": item.attribution_notice,
            "svg_raw": item.svg_raw,
            "svg_render_isolated": item.svg_clean,
        })
    return samples


@dataclass
class AcquisitionLaunch:
    snapshot: SourceSnapshot
    job: Job
    reservation: Optional[BudgetReservation]
    plan: dict[str, Any]
    created: bool


def _acquisition_pool(tenant_id: Any, pool_name: Optional[str] = None) -> WorkerPool:
    from modelanvil.jobs.setup import local_capacity_available
    pools = WorkerPool.all_objects.filter(tenant_id=tenant_id, status="active")
    if pool_name:
        pools = pools.filter(name=pool_name)
    for pool in pools.order_by("name"):
        workers = Worker.all_objects.filter(
            tenant_id=tenant_id, pool=pool, slots__gte=1,
        ).exclude(status__in=(Worker.Status.OFFLINE, Worker.Status.DRAINING)).order_by("-slots", "id")
        for worker in workers:
            if worker.capabilities.get(ACQUISITION_CAPABILITY) is True and local_capacity_available(worker):
                return pool
    raise AcquisitionCapacityError(
        "No registered acquisition worker is available for this tenant. An operator must "
        f"register a worker in an active pool with the {ACQUISITION_CAPABILITY!r} capability."
    )


def _validate_budget(tenant_id: Any, budget_policy_id: Any, estimated_amount: Any, minimum_records: int = 0) -> Optional[BudgetPolicy]:
    """Refuse invalid admission before fetching upstream bytes; reserve under lock later."""
    enabled = BudgetPolicy.all_objects.filter(tenant_id=tenant_id, enabled=True)
    if not enabled.exists():
        if budget_policy_id:
            raise AcquisitionRefused("The supplied budget policy is not enabled for this tenant.")
        return None
    if budget_policy_id is None or estimated_amount is None:
        raise AcquisitionRefused(
            "This tenant has an enabled budget policy; budget_policy_id and estimated_amount "
            "are required to launch an acquisition."
        )
    policy = enabled.filter(policy_id=budget_policy_id).first()
    if policy is None:
        raise AcquisitionRefused("No enabled budget policy matches budget_policy_id in this tenant.")
    if policy.unit != "bank_acquisition_records":
        raise AcquisitionRefused("Acquisition requires a policy measured in bank_acquisition_records.")
    try:
        amount = Decimal(str(estimated_amount))
    except (InvalidOperation, ValueError, TypeError):
        raise AcquisitionRefused("estimated_amount must be a positive decimal.") from None
    if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18") or amount.as_tuple().exponent < -6:
        raise AcquisitionRefused("estimated_amount must be positive with at most 18 integer and 6 decimal digits.")
    if amount < minimum_records:
        raise AcquisitionRefused(f"estimated_amount must cover at least {minimum_records} planned records.")
    _, committed = BudgetReservation.current_commitment(policy)
    if committed + amount > policy.limit_amount:
        raise AcquisitionRefused("Budget limit exceeded.")
    return policy


def _reserve_budget(
    tenant_id: Any, job_id: Any, budget_policy_id: Any, estimated_amount: Any
) -> Optional[BudgetReservation]:
    policy = _validate_budget(tenant_id, budget_policy_id, estimated_amount)
    if policy is None:
        return None
    try:
        return BudgetReservation.reserve(
            tenant_id=tenant_id, policy=policy, job_id=job_id,
            estimated_amount=estimated_amount,
        )
    except ValueError as exc:
        raise AcquisitionRefused(str(exc)) from exc


def _existing_job(snapshot: SourceSnapshot) -> Optional[Job]:
    return Job.all_objects.filter(
        tenant_id=snapshot.tenant_id,
        payload__type=JOB_TYPE,
        payload__snapshot_id=str(snapshot.snapshot_id),
        status__in=(Job.Status.QUEUED, Job.Status.RUNNING),
    ).order_by("-created_at").first()


def launch_acquisition(
    *,
    tenant_id: Any,
    source_id: str,
    project_id: Any = None,
    catalog: Optional[DatasetBankCatalog] = None,
    project_policy: Optional[dict[str, Any]] = None,
    source_revision: Optional[str] = None,
    record_limit: Optional[int] = None,
    download_scope: str = "sample",
    split_seed: str = "0",
    budget_policy_id: Any = None,
    estimated_amount: Any = None,
    pool_name: Optional[str] = None,
    transport: Optional[Transport] = None,
) -> AcquisitionLaunch:
    """Preflight, plan, and queue a qualified sample or complete release."""
    catalog = catalog or DatasetBankCatalog.load_from_file()
    transport = transport or https_transport
    policy = dict(project_policy or {})
    if record_limit is not None:
        policy["record_limit"] = int(record_limit)
    preflight = catalog.preflight_download(
        source_id, tenant_id=str(tenant_id), project_policy=policy, source_revision=source_revision,
        download_scope=download_scope,
    )
    source = catalog.source_for_full_download(source_id) if download_scope == "full" else catalog.get_source(source_id)
    limit = int(preflight["scope"]["record_limit"])
    _validate_budget(tenant_id, budget_policy_id, estimated_amount, limit)
    pool = _acquisition_pool(tenant_id, pool_name)
    if download_scope == "full":
        from modelanvil.data.bank.full_download import load_manifest as load_full_manifest
        full_manifest = load_full_manifest(source)
        selected = [{"path": f["path"], "size": f["size"], "sha256": f["sha256"]} for f in full_manifest["files"]]
        licenses = []
    else:
        inventory, licenses = list_inventory(source, transport=transport)
        selected = select_records(inventory, limit)

    with transaction.atomic():
        downloader = ResumablePresetDownloader(catalog)
        snapshot = downloader.initiate_download(
            tenant_id=tenant_id, source_id=source_id,
            project_id=project_id,
            revision=preflight["source_revision"], project_policy=policy, download_scope=download_scope,
        )
        snapshot = SourceSnapshot.all_objects.select_for_update().get(pk=snapshot.pk, tenant_id=tenant_id)
        saved_plan = snapshot.detail.get("acquisition") or {}
        if saved_plan and (saved_plan.get("record_limit") != len(selected)
                           or saved_plan.get("split_seed", "0") != split_seed):
            raise AcquisitionRefused(
                "This source revision already has a frozen acquisition scope in this project. "
                "Restore or resume that acquisition; use another project to acquire a different subset."
            )
        if snapshot.state == SourceSnapshot.State.READY:
            job = _existing_job(snapshot) or Job.all_objects.filter(
                tenant_id=snapshot.tenant_id, payload__snapshot_id=str(snapshot.snapshot_id),
                payload__type=JOB_TYPE,
            ).order_by("-created_at").first()
            return AcquisitionLaunch(snapshot, job, None, snapshot.detail.get("acquisition", {}), created=False)

        active = _existing_job(snapshot)
        if active is not None:
            return AcquisitionLaunch(snapshot, active, None, snapshot.detail.get("acquisition", {}), created=False)
        detail = dict(snapshot.detail or {})
        plan = dict(detail.get("acquisition") or {})
        plan.setdefault("source_id", source_id)
        plan["source_revision"] = preflight["source_revision"]
        plan["download_scope"] = download_scope
        plan["connector"] = source.acquisition.connector
        plan["record_selection"] = source.acquisition.record_selection
        plan["record_limit"] = len(selected)
        plan["records"] = selected if download_scope == "full" else [record.as_dict() for record in selected]
        plan["license_records"] = [record.as_dict() for record in licenses]
        plan.setdefault("verified", {})
        plan.setdefault("failures", [])
        plan["planned_at"] = plan.get("planned_at") or timezone.now().isoformat()
        plan["preflight"] = preflight
        plan["split_seed"] = split_seed
        detail["acquisition"] = plan
        detail["source_id"] = source_id
        detail["preflight"] = preflight
        detail["bytes_transferred"] = sum(
            int(entry.get("size", 0)) for entry in plan["verified"].values()
        )
        snapshot.detail = detail
        snapshot.state = SourceSnapshot.State.INGESTING
        snapshot.save(update_fields=["detail", "state", "updated_at"])

        job_id = uuid7()
        reservation = _reserve_budget(tenant_id, job_id, budget_policy_id, estimated_amount)
        job = Job.all_objects.create(
            tenant_id=tenant_id,
            name=f"bank-acquisition {source_id} {preflight['source_revision'][:12]}",
            pool=pool, status=Job.Status.QUEUED,
            requirements={ACQUISITION_CAPABILITY: True, "slots": 1},
            payload={
                "type": JOB_TYPE,
                "project_id": str(snapshot.project_id) if snapshot.project_id else None,
                "snapshot_id": str(snapshot.snapshot_id),
                "source_id": source_id,
                "download_scope": download_scope,
                "source_revision": preflight["source_revision"],
                "record_limit": len(selected),
                "split_seed": split_seed,
            },
            job_id=job_id,
        )
        return AcquisitionLaunch(snapshot, job, reservation, plan, created=True)


def cancel_acquisition(snapshot: SourceSnapshot) -> dict[str, Any]:
    """Request cancellation; a queued job stops immediately, a running one is fenced."""
    with transaction.atomic():
        snapshot = SourceSnapshot.all_objects.select_for_update().get(
            pk=snapshot.pk, tenant_id=snapshot.tenant_id
        )
        if snapshot.state == SourceSnapshot.State.READY:
            raise AcquisitionRefused("This acquisition has already published; it cannot be cancelled.")
        job = _existing_job(snapshot)
        if job is None:
            raise AcquisitionRefused("This acquisition has no queued or running job to cancel.")
        job = Job.all_objects.select_for_update().get(pk=job.pk)
        if job.status == Job.Status.QUEUED:
            job.status = Job.Status.CANCELLED
            job.desired_action = Job.DesiredAction.CANCEL
            job.save(update_fields=["status", "desired_action", "updated_at"])
        else:
            job.desired_action = Job.DesiredAction.CANCEL
            job.save(update_fields=["desired_action", "updated_at"])
        if snapshot.state == SourceSnapshot.State.INGESTING:
            snapshot.state = SourceSnapshot.State.CANCELLED
            snapshot.save(update_fields=["state", "updated_at"])
        if job.status == Job.Status.CANCELLED:
            BudgetReservation.all_objects.filter(
                tenant_id=snapshot.tenant_id, job_id=job.job_id, state=BudgetReservation.State.RESERVED,
            ).update(state=BudgetReservation.State.RELEASED)
    return {"snapshot_state": snapshot.state, "job_status": job.status, "desired_action": job.desired_action}


@transaction.atomic
def resume_acquisition(
    snapshot: SourceSnapshot, *, pool_name: Optional[str] = None,
    budget_policy_id: Any = None, estimated_amount: Any = None,
) -> AcquisitionLaunch:
    """Re-queue an interrupted transfer from its persisted per-record state."""
    snapshot = SourceSnapshot.all_objects.select_for_update().get(pk=snapshot.pk, tenant_id=snapshot.tenant_id)
    if snapshot.state == SourceSnapshot.State.READY:
        raise AcquisitionRefused("This snapshot is already complete and immutable; nothing to resume.")
    if _existing_job(snapshot) is not None:
        raise AcquisitionRefused("This acquisition already has a queued or running job.")
    plan = (snapshot.detail or {}).get("acquisition") or {}
    if not plan.get("records"):
        raise AcquisitionRefused("This acquisition has no persisted transfer plan to resume.")
    remaining = len(plan["records"]) - len(plan.get("verified") or {})
    _validate_budget(snapshot.tenant_id, budget_policy_id, estimated_amount, max(0, remaining))
    pool = _acquisition_pool(snapshot.tenant_id, pool_name)
    with transaction.atomic():
        job_id = uuid7()
        reservation = _reserve_budget(snapshot.tenant_id, job_id, budget_policy_id, estimated_amount)
        job = Job.all_objects.create(
            tenant_id=snapshot.tenant_id,
            name=f"bank-acquisition {plan.get('source_id')} resume {str(snapshot.snapshot_id)[:8]}",
            pool=pool, status=Job.Status.QUEUED,
            requirements={ACQUISITION_CAPABILITY: True, "slots": 1},
            payload={
                "type": JOB_TYPE,
                "project_id": str(snapshot.project_id) if snapshot.project_id else None,
                "snapshot_id": str(snapshot.snapshot_id),
                "source_id": plan.get("source_id"),
                "download_scope": plan.get("download_scope", "sample"),
                "source_revision": plan.get("source_revision"),
                "record_limit": plan.get("record_limit"),
                "split_seed": plan.get("split_seed", "0"),
                "resumed_from_records": len(plan.get("verified") or {}),
            },
            job_id=job_id,
        )
        snapshot.state = SourceSnapshot.State.INGESTING
        snapshot.save(update_fields=["state", "updated_at"])
    return AcquisitionLaunch(snapshot, job, reservation, plan, created=True)


def access_acquisition(snapshot_id: Any, *, requesting_tenant_id: Any, project_id: Any = None) -> SourceSnapshot:
    """Tenant-isolated acquisition read; another tenant's transfer cache is refused."""
    tenant_id = uuid.UUID(str(requesting_tenant_id))
    snapshot = SourceSnapshot.all_objects.filter(snapshot_id=snapshot_id, tenant_id=tenant_id).first()
    if snapshot is None:
        foreign = SourceSnapshot.all_objects.filter(snapshot_id=snapshot_id).exists()
        if foreign:
            raise PermissionDenied(
                "Access denied: cannot access source snapshots or caches belonging to another organization."
            )
        raise AcquisitionRefused("Acquisition not found.")
    if not check_resource_access(snapshot, project_id, tenant_id):
        raise PermissionDenied("Acquisition is not accessible in this project.")
    return snapshot


def acquisition_state(snapshot: SourceSnapshot) -> dict[str, Any]:
    """Public transfer state; never exposes upstream credentials or response bodies."""
    detail = snapshot.detail or {}
    plan = detail.get("acquisition") or {}
    verified = plan.get("verified") or {}
    records = plan.get("records") or []
    job = Job.all_objects.filter(
        tenant_id=snapshot.tenant_id, payload__type=JOB_TYPE,
        payload__snapshot_id=str(snapshot.snapshot_id),
    ).order_by("-created_at").first()
    reservation = None
    if job is not None:
        reservation = BudgetReservation.all_objects.filter(
            tenant_id=snapshot.tenant_id, job_id=job.job_id,
        ).order_by("-reserved_at").first()
    published_revision = plan.get("published_revision") or None
    total_bytes = sum(int(record.get("size", 0)) for record in records)
    transferred_bytes = sum(int(entry.get("size", 0)) for entry in verified.values()) + int(plan.get("partial_bytes") or 0)
    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "download_scope": plan.get("download_scope", "sample"),
        "source_files": [{"path": path, **entry} for path, entry in verified.items()] if plan.get("download_scope") == "full" and snapshot.state == SourceSnapshot.State.READY else [],
        "source_id": plan.get("source_id") or detail.get("source_id"),
        "source_revision": plan.get("source_revision") or snapshot.source_revision,
        "state": snapshot.state,
        "connector": plan.get("connector"),
        "record_selection": plan.get("record_selection"),
        "planned_records": len(records),
        "verified_records": len(verified),
        "remaining_records": max(0, len(records) - len(verified)),
        "planned_bytes": total_bytes,
        "transferred_bytes": transferred_bytes,
        "progress": round(transferred_bytes / total_bytes, 4) if total_bytes else 0.0,
        "manifest_digest": snapshot.manifest_digest or "",
        "failures": plan.get("failures") or [],
        "job": None if job is None else {
            "job_id": str(job.job_id), "status": job.status,
            "desired_action": job.desired_action, "attempt_count": job.attempt_count,
            "pool": job.pool.name if job.pool_id else None,
        },
        "budget_reservation": None if reservation is None else {
            "reservation_id": str(reservation.reservation_id), "state": reservation.state,
            "unit": reservation.policy.unit, "estimated_amount": str(reservation.estimated_amount),
            "settled_amount": None if reservation.settled_amount is None else str(reservation.settled_amount),
        },
        "dataset_id": plan.get("dataset_id"),
        "revision_id": published_revision.get("revision_id") if isinstance(published_revision, dict) else None,
        "revision_no": published_revision.get("revision_no") if isinstance(published_revision, dict) else None,
        "manifest_artifact_id": published_revision.get("manifest_artifact_id") if isinstance(published_revision, dict) else plan.get("manifest_artifact_id"),
        "row_count": published_revision.get("row_count") if isinstance(published_revision, dict) else None,
        "recipe_digest": published_revision.get("recipe_digest") if isinstance(published_revision, dict) else None,
        "rejection_report": published_revision.get("rejection_report") if isinstance(published_revision, dict) else None,
        "updated_at": snapshot.updated_at.isoformat(),
    }


def _settle_budget(job_id: Any, tenant_id: Any, verified_records: int, *, download_scope: str = "sample") -> None:
    """Settle a reservation with the verified record count, or release it when nothing moved."""
    if not job_id:
        return
    reservation = BudgetReservation.all_objects.filter(
        tenant_id=tenant_id, job_id=job_id, state=BudgetReservation.State.RESERVED,
    ).first()
    if reservation is None:
        return
    if verified_records <= 0:
        reservation.release()
        return
    amount = Decimal(str(verified_records))
    reservation.settle(amount)
    UsageEvent.record(
        tenant_id=tenant_id,
        provider_event_key=f"bank-acquisition-{job_id}",
        quantity=amount, unit=reservation.policy.unit, reservation=reservation,
        detail={
            "unit_kind": "bank_acquisition_verified_files" if download_scope == "full" else "bank_acquisition_verified_records",
            "snapshot_ref": reservation.job_id and str(reservation.job_id),
            "quantity_basis": "verified complete source files" if download_scope == "full" else "verified upstream records at the pinned revision",
        },
    )


def _checkpoint(snapshot: SourceSnapshot, detail: dict[str, Any]) -> None:
    snapshot.detail = detail
    snapshot.save(update_fields=["detail", "updated_at"])


def _fail(snapshot: SourceSnapshot, detail: dict[str, Any], plan: dict[str, Any], reason: str) -> None:
    plan.setdefault("failures", []).append({"at": timezone.now().isoformat(), "reason": reason})
    detail["acquisition"] = plan
    snapshot.state = SourceSnapshot.State.FAILED
    snapshot.detail = detail
    snapshot.save(update_fields=["state", "detail", "updated_at"])


def _record_url(source: SourceCard, path: str) -> str:
    if source.acquisition.connector == HTTP_SUBSET_CONNECTOR:
        manifest = load_manifest(source)
        entry = next(item for item in manifest["records"] + manifest["licenses"] if item["path"] == path)
        return record_url(manifest, entry)
    return _raw_base(source.acquisition.upstream_repository, source.acquisition.pinned_revision) + quote(path)


def _http_envelopes(source, snapshot, records, verified, stored):
    manifest = load_manifest(source)
    expected = {record["path"]: record for record in manifest["records"]}
    envelopes = []
    for record in records:
        entry = expected[record["path"]]
        raw = bytes.fromhex(stored[record["path"]]["payload_hex"])
        if hashlib.sha256(raw).hexdigest() != entry["sha256"] or verified[record["path"]]["sha256"] != entry["sha256"]:
            raise UpstreamError("Checkpoint bytes differ from the qualified sample.")
        value = validate_sample(source.id, raw)
        blocks = []
        for field, kind, media_type in (("image_hex", "image", "image/png"), ("audio_hex", "audio", "audio/flac" if source.id == "audio-vctk" else "audio/wav")):
            if field not in value:
                continue
            media = bytes.fromhex(value.pop(field))
            media_sha256 = hashlib.sha256(media).hexdigest()
            artifact, _ = Artifact.all_objects.get_or_create(
                tenant_id=snapshot.tenant_id, storage_location_id="local",
                object_key=f"bank/{source.id}/{snapshot.snapshot_id}/media/{media_sha256}",
                defaults={"project_id": snapshot.project_id, "sha256": media_sha256,
                    "byte_size": len(media), "media_type": media_type, "state": Artifact.State.STAGING,
                    "metadata": {"kind": "dataset_bank_media", "source_id": source.id,
                        "source_revision": source.acquisition.pinned_revision, "snapshot_ref": str(snapshot.snapshot_id)}},
            )
            if artifact.project_id != snapshot.project_id or artifact.sha256 != media_sha256 or artifact.byte_size != len(media):
                raise UpstreamError("Media artifact differs from the authorized verified sample.")
            if artifact.state != Artifact.State.COMMITTED:
                upload_staged_artifact(artifact, io.BytesIO(media), backend=artifact_storage_backend())
            blocks.append({"block_id": kind, "type": kind, "asset_ref": f"sha256:{media_sha256}",
                "media_type": media_type, "metadata": {"artifact_ref": str(artifact.artifact_id), "byte_size": len(media), "sha256": media_sha256}})
        blocks.append({"block_id": "upstream-record", "type": "table" if source.category == "numeric" else "json", "value": value})
        envelopes.append({"schema_version": "1.0",
            "sample_id": str(uuid.uuid5(ENVELOPE_NAMESPACE, f"{snapshot.snapshot_id}:{record['path']}")),
            "source_group_id": entry["source_group_id"], "blocks": blocks,
            "provenance": {"source_snapshot_ref": str(snapshot.snapshot_id),
                "source_record_key": record["path"], "content_sha256": entry["sha256"],
                "transformation_revision_ref": HTTP_SUBSET_CONNECTOR},
            "metadata": {**entry["metadata"], "license": source.license_expression,
                "upstream_url": record_url(manifest, entry), "source_revision": source.acquisition.pinned_revision,
                "source_id": source.id, "training_recipe_qualified": False},
        })
    return envelopes


def _build_envelopes(
    source: SourceCard, snapshot: SourceSnapshot, records: list[dict[str, Any]],
    verified: dict[str, dict[str, Any]], stored: dict[str, dict[str, Any]], *, raw_base: str,
) -> list[dict[str, Any]]:
    """Map verified upstream records to canonical sample envelopes with real provenance."""
    if source.acquisition.connector == HTTP_SUBSET_CONNECTOR:
        return _http_envelopes(source, snapshot, records, verified, stored)
    library = source.id.split("-", 1)[-1]
    envelopes: list[dict[str, Any]] = []
    for record in records:
        entry = verified.get(record["path"])
        payload = stored.get(record["path"], {}).get("payload_hex")
        if entry is None or payload is None:
            raise UpstreamError(f"Record {record['path']!r} was not verified before publication.")
        item = prepare_svg_record(
            source_library=library,
            icon_name=record["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0],
            svg_content=bytes.fromhex(payload).decode("utf-8"),
        )
        envelopes.append({
            "schema_version": "1.0",
            "sample_id": str(uuid.uuid5(ENVELOPE_NAMESPACE, f"{snapshot.snapshot_id}:{record['path']}")),
            "source_group_id": f"{source.id}:{item.concept_group}",
            "language": "svg",
            "blocks": [{
                "block_id": record["path"], "type": "svg", "asset_ref": record["path"],
                "text": item.svg_clean, "media_type": "image/svg+xml",
            }],
            "provenance": {
                "source_snapshot_ref": str(snapshot.snapshot_id),
                "source_record_key": record["path"],
                "content_sha256": entry["sha256"],
                "transformation_revision_ref": item.content_hash,
            },
            "metadata": {
                "icon_name": item.icon_name,
                "concept_group": item.concept_group,
                "variant_type": item.variant_type,
                "label": item.label,
                "label_provenance": item.label_provenance,
                "license": item.license,
                "attribution_notice": item.attribution_notice,
                "upstream_blob_sha1": record["blob_sha1"],
                "upstream_repository": source.acquisition.upstream_repository,
                "upstream_url": raw_base + record["path"],
                "source_revision": source.acquisition.pinned_revision,
            },
        })
    return envelopes


def _protected_envelopes(dataset: Dataset) -> Optional[list[dict[str, Any]]]:
    """Rows held out by the current published version, so a new revision cannot leak them."""
    revision = dataset.current_revision
    if revision is None or revision.manifest_artifact_id is None:
        return None
    try:
        with artifact_storage_backend().open(dataset.tenant_id, str(revision.manifest_artifact.object_key)) as stream:
            manifest = json.loads(stream.read())
    except (OSError, ValueError, AttributeError):
        return None
    held = set(manifest.get("split_manifest", {}).get("validation", []))
    held |= set(manifest.get("split_manifest", {}).get("test", []))
    if not held:
        return None
    return [row for row in manifest.get("rows", []) if row.get("sample_id") in held]


def _dataset_for(source: SourceCard, tenant_id: Any, project_id: Any) -> Dataset:
    name = f"{source.name} (Dataset Bank)"
    if project_id:
        name = f"{name[:160]} · {project_id}"
    dataset = Dataset.all_objects.filter(tenant_id=tenant_id, project_id=project_id, name=name).first()
    if dataset is None:
        dataset = Dataset.all_objects.create(
            tenant_id=tenant_id, project_id=project_id, name=name,
            description=source.description,
            metadata={"bank_source_id": source.id, "acquisition": []},
        )
    return dataset


def _publish(
    dataset: Dataset, artifact: Artifact, *, protected: Optional[list[dict[str, Any]]], split_seed: str
) -> DatasetRevision:
    """Publish one immutable, digest-verified revision of the acquired dataset."""
    return publish_prepared_dataset(
        dataset, artifact, split_seed=split_seed, validation_percent=10, test_percent=10,
        detect={"privacy": False, "quality": False}, dedup={"exact": True, "near": False},
        protected=protected,
    )


def _execution_snapshot(descriptor):
    payload = descriptor.get("payload") or {}
    query = SourceSnapshot.all_objects.filter(snapshot_id=payload.get("snapshot_id"))
    if payload.get("download_scope") == "full":
        job = Job.all_objects.filter(job_id=descriptor.get("job_id")).first()
        if job is None or job.payload.get("snapshot_id") != payload.get("snapshot_id"):
            return None
        query = query.filter(tenant_id=job.tenant_id, project_id=job.payload.get("project_id"))
    return query.first()


def _execute_acquisition(descriptor: dict[str, Any], context: Any) -> dict[str, Any]:
    """Transfer, verify, prepare and publish one queued bank acquisition."""
    payload = descriptor.get("payload") or {}
    if payload.get("type") != JOB_TYPE:
        raise ValueError("Unsupported job type for the bank acquisition executor.")
    snapshot = _execution_snapshot(descriptor)
    if snapshot is None:
        raise UpstreamError("The queued source snapshot no longer exists.")
    tenant_id = snapshot.tenant_id
    previously_billed = int(payload.get("resumed_from_records") or 0)
    def settle(count):
        _settle_budget(descriptor.get("job_id"), tenant_id, max(0, count - previously_billed))
    if snapshot.state != SourceSnapshot.State.INGESTING:
        raise UpstreamError(f"Snapshot is {snapshot.state}; only ingesting snapshots transfer bytes.")

    catalog = DatasetBankCatalog.load_from_file()
    source = catalog.get_source(payload.get("source_id") or "")
    if source is None:
        raise UpstreamError("The queued source is no longer in the catalog.")
    if payload.get("download_scope") == "full":
        from modelanvil.data.bank.full_download import execute
        source = catalog.source_for_full_download(source.id)
        if payload.get("source_revision") != source.acquisition.pinned_revision or snapshot.source_revision != source.acquisition.pinned_revision:
            raise UpstreamError("Full-download revision differs from its qualification.")
        return execute(descriptor, context, source, snapshot)
    catalog.assert_acquirable(source.id, source_revision=payload.get("source_revision"))

    detail = dict(snapshot.detail or {})
    plan = dict(detail.get("acquisition") or {})
    records = list(plan.get("records") or [])
    verified: dict[str, Any] = dict(plan.get("verified") or {})
    store = RecordStore(tenant_id, snapshot.snapshot_id)
    snapshot_ref = f"{tenant_id}/{snapshot.snapshot_id}"
    stored = store.load({record["path"]: record for record in records})
    verified = {
        path: entry for path, entry in verified.items()
        if stored.get(path, {}).get("sha256") == entry.get("sha256")
    }
    raw_base = "" if source.acquisition.connector == HTTP_SUBSET_CONNECTOR else _raw_base(source.acquisition.upstream_repository, source.acquisition.pinned_revision)
    transport = cached_transport(https_transport)
    total_bytes = sum(int(record.get("size", 0)) for record in records) or 1
    transferred = sum(int(entry.get("size", 0)) for entry in verified.values())

    try:
        for record in records:
            if record["path"] in verified:
                continue
            if not context.heartbeat(min(0.99, transferred / total_bytes)):
                if getattr(context, "lease_lost", False):
                    raise AcquisitionLeaseLost("Worker lease lost before transfer.")
                plan["cancelled_at"] = timezone.now().isoformat()
                plan["verified"] = verified
                detail["acquisition"] = plan
                snapshot.state = SourceSnapshot.State.CANCELLED
                _checkpoint(snapshot, detail)
                snapshot.save(update_fields=["state", "updated_at"])
                settle(len(verified))
                raise AcquisitionCancelled("Transfer cancelled before completion.")
            record_bytes = fetch_record(source, UpstreamRecord(**record), transport=transport)
            content_sha256 = hashlib.sha256(record_bytes).hexdigest()
            store.append(
                snapshot_ref, record["path"], record_bytes,
                sha256=content_sha256, blob_sha1=record["blob_sha1"],
            )
            verified[record["path"]] = {
                "size": len(record_bytes), "sha256": content_sha256,
                "blob_sha1": record["blob_sha1"], "verified_at": timezone.now().isoformat(),
            }
            stored[record["path"]] = {"payload_hex": record_bytes.hex(), "sha256": content_sha256}
            transferred += len(record_bytes)
            plan["verified"] = verified
            detail["acquisition"] = plan
            detail["bytes_transferred"] = transferred
            _checkpoint(snapshot, detail)
    except AcquisitionCancelled:
        raise
    except UpstreamError as exc:
        _fail(snapshot, detail, plan, str(exc))
        settle(len(verified))
        raise

    if len(verified) != len(records):
        _fail(snapshot, detail, plan, "not every planned record was verified")
        settle(len(verified))
        raise UpstreamError("Not every planned record was verified; refusing to publish.")

    notices = []
    for record in plan.get("license_records") or []:
        notice = fetch_record(source, UpstreamRecord(**record), transport=transport)
        notices.append({
            "path": record["path"],
            "upstream_url": _record_url(source, record["path"]),
            "upstream_blob_sha1": record["blob_sha1"],
            "content_sha256": hashlib.sha256(notice).hexdigest(),
            "byte_size": len(notice),
            "digest_verified": True,
            "text": notice.decode("utf-8"),
        })

    envelopes = _build_envelopes(source, snapshot, records, verified, stored, raw_base=raw_base)
    body = "".join(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        for envelope in envelopes
    ).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    backend = artifact_storage_backend()
    staged, _ = Artifact.all_objects.get_or_create(
        tenant_id=tenant_id, storage_location_id="local",
        object_key=f"bank/{source.id}/{snapshot.snapshot_id}.jsonl",
        defaults={"project_id": snapshot.project_id,
        "sha256": digest, "byte_size": len(body), "media_type": "application/x-ndjson",
        "state": Artifact.State.STAGING,
        "metadata": {
            "kind": "dataset_bank_acquisition",
            "source_id": source.id,
            "source_revision": source.acquisition.pinned_revision,
            "snapshot_ref": str(snapshot.snapshot_id),
            "records": len(records),
        }},
    )
    if staged.project_id != snapshot.project_id or staged.sha256 != digest or staged.byte_size != len(body):
        raise UpstreamError("Cached acquisition artifact differs from the verified records or project.")
    if staged.state != Artifact.State.COMMITTED:
        upload_staged_artifact(staged, io.BytesIO(body), backend=backend)
    staged.refresh_from_db()
    if staged.state != Artifact.State.COMMITTED or staged.sha256 != digest:
        raise UpstreamError("Acquired artifact bytes were not committed with the verified digest.")

    for envelope in envelopes:
        for block in envelope["blocks"]:
            media_ref = block.get("metadata", {}).get("artifact_ref")
            if media_ref:
                media = Artifact.all_objects.get(artifact_id=media_ref, tenant_id=tenant_id, project_id=snapshot.project_id, state=Artifact.State.COMMITTED)
                LineageEdge.all_objects.get_or_create(tenant_id=tenant_id, parent_artifact=media, child_artifact=staged,
                    relation="bank_media", defaults={"detail": {"source_revision": source.acquisition.pinned_revision}})

    manifest_hasher = hashlib.sha256()
    for record in records:
        manifest_hasher.update(verified[record["path"]]["sha256"].encode("ascii"))
    with transaction.atomic():
        snapshot = SourceSnapshot.all_objects.select_for_update().get(pk=snapshot.pk, tenant_id=tenant_id)
        if snapshot.state != SourceSnapshot.State.INGESTING or not context.heartbeat(0.99):
            if getattr(context, "lease_lost", False):
                raise AcquisitionLeaseLost("Worker lease lost before publication.")
            raise AcquisitionCancelled("Acquisition cancelled before publication.")
        dataset = _dataset_for(source, tenant_id, snapshot.project_id)
        protected = _protected_envelopes(dataset)
        try:
            revision = _publish(dataset, staged, protected=protected, split_seed=plan.get("split_seed") or "0")
        except Exception as exc:
            _fail(snapshot, detail, plan, "Dataset preparation/publication failed; resume to retry verified records.")
            settle(len(verified))
            raise UpstreamError("Dataset preparation/publication failed; resume to retry verified records.") from exc

        attribution = {
            "source_id": source.id,
            "source_name": source.name,
            "source_url": source.source_url,
            "upstream_repository": source.acquisition.upstream_repository,
            "source_revision": source.acquisition.pinned_revision,
            "license": source.license_expression,
            "obligations": vars(source.obligations),
            "license_evidence_urls": source.obligations.evidence_urls,
            "license_notices": notices,
            "snapshot_ref": str(snapshot.snapshot_id),
            "artifact_ref": str(staged.artifact_id),
            "artifact_sha256": staged.sha256,
            "records_verified": len(verified),
            "verified_on": timezone.now().isoformat(),
        }
        transformations = [
            {"step": "git_blob_digest_verification",
             "detail": "Every acquired record matched its Git object id at the pinned revision."},
            {"step": "render_isolation",
             "detail": "Scripts, DOCTYPE and external references are stripped from the renderable SVG; the raw SVG is preserved."},
            {"step": "weak_label_extraction",
             "detail": "Labels are derived from filenames and are published as filename_derived, not human-reviewed."},
            {"step": "exact_duplicate_removal",
             "detail": "Byte-identical prepared records are dropped once and counted in the rejection report."},
            {"step": "protected_split_enforcement",
             "detail": "Each concept group maps to exactly one split, so icon variants cannot straddle splits."},
            {"step": "published_version_protection",
             "detail": ("Rows held out by the previous published version were dropped from this version."
                        if protected else "No earlier published version required protection.")},
        ]
        if source.acquisition.connector == HTTP_SUBSET_CONNECTOR:
            transformations = [
                {"step": "qualified_sha256_verification", "detail": "Every downloaded range, decoded sample, and archived notice matched the content-pinned subset manifest."},
                {"step": "canonical_source_record_import", "detail": "Source fields are retained as JSON/table blocks. Paired image/audio bytes are committed as tenant/project-scoped artifacts with content-addressed asset references. Training adapters are not qualified."},
                {"step": "source_group_split_enforcement", "detail": "Qualified prompt, passage, image, speaker, or feature groups stay within one local split. Only the qualified upstream split/configuration is admitted."},
            ]
        history = list(dataset.metadata.get("acquisition") or [])
        history.append({
            "revision_no": revision.revision_no, "revision_id": str(revision.revision_id),
            "snapshot_ref": str(snapshot.snapshot_id),
            "source_revision": source.acquisition.pinned_revision,
            "manifest_digest": revision.manifest_digest, "row_count": revision.row_count,
            "artifact_sha256": staged.sha256,
            "published_at": revision.published_at.isoformat() if revision.published_at else None,
        })
        dataset.metadata = {
            **dataset.metadata,
            "bank_source_id": source.id,
            "license": source.license_expression,
            "source_url": source.source_url,
            "modalities": source.modalities,
            "acquisition": history[-20:],
            "latest_attribution": attribution,
            "transformations": transformations,
        }
        dataset.save(update_fields=["metadata", "updated_at"])

        plan["published_revision"] = {
            "revision_id": str(revision.revision_id), "revision_no": revision.revision_no,
            "manifest_artifact_id": str(revision.manifest_artifact_id),
            "row_count": revision.row_count, "recipe_digest": revision.recipe_digest,
            "manifest_digest": revision.manifest_digest,
            "rejection_report": (revision.metadata or {}).get("drop_report"),
        }
        plan["dataset_id"] = str(dataset.dataset_id)
        plan["published_at"] = timezone.now().isoformat()
        plan["attribution"] = attribution
        plan["transformations"] = transformations
        detail["acquisition"] = plan
        _checkpoint(snapshot, detail)
        snapshot.mark_ready(manifest_digest=manifest_hasher.hexdigest(), item_count=len(records), failure_count=0)
        settle(len(verified))
    store.discard()

    return {
        "schema_version": "1.0",
        "sample_id": str(uuid.uuid5(ENVELOPE_NAMESPACE, f"publication:{revision.revision_id}")),
        "source_group_id": f"{source.id}:publication",
        "blocks": [{
            "block_id": "acquisition-result", "type": "json",
            "value": {
                "status": "published",
                "snapshot_ref": str(snapshot.snapshot_id),
                "source_id": source.id,
                "source_revision": source.acquisition.pinned_revision,
                "dataset_id": str(dataset.dataset_id),
                "revision_id": str(revision.revision_id),
                "revision_no": revision.revision_no,
                "manifest_digest": revision.manifest_digest,
                "artifact_sha256": staged.sha256,
                "records_verified": len(verified),
                "row_count": revision.row_count,
            },
        }],
        "provenance": {
            "source_snapshot_ref": str(snapshot.snapshot_id),
            "source_record_key": f"{source.id}@{source.acquisition.pinned_revision}",
            "content_sha256": staged.sha256,
        },
    }


def bank_acquisition_executor(descriptor: dict[str, Any], context: Any) -> dict[str, Any]:
    """Operator-installed executor entry point for ``manage.py run_worker``."""
    return execute_acquisition(descriptor, context)


def execute_acquisition(descriptor: dict[str, Any], context: Any) -> dict[str, Any]:
    """Persist failures outside publication transactions so verified records remain resumable."""
    try:
        return _execute_acquisition(descriptor, context)
    except AcquisitionCancelled:
        payload = descriptor.get("payload") or {}
        snapshot = _execution_snapshot(descriptor)
        if snapshot is not None and snapshot.state != SourceSnapshot.State.READY:
            snapshot.state = SourceSnapshot.State.CANCELLED
            snapshot.save(update_fields=["state", "updated_at"])
            plan = (snapshot.detail or {}).get("acquisition") or {}
            count = max(0, len(plan.get("verified") or {}) - int(payload.get("resumed_from_records") or 0))
            _settle_budget(descriptor.get("job_id"), snapshot.tenant_id, count, download_scope=payload.get("download_scope", "sample"))
        raise
    except (UpstreamError, ValueError, OSError):
        payload = descriptor.get("payload") or {}
        snapshot = _execution_snapshot(descriptor)
        if snapshot is not None and snapshot.state == SourceSnapshot.State.INGESTING:
            detail = dict(snapshot.detail or {})
            plan = dict(detail.get("acquisition") or {})
            _fail(snapshot, detail, plan, "Acquisition failed before publication; resume verified records to retry.")
            count = max(0, len(plan.get("verified") or {}) - int(payload.get("resumed_from_records") or 0))
            _settle_budget(descriptor.get("job_id"), snapshot.tenant_id, count, download_scope=payload.get("download_scope", "sample"))
        raise
