"""Explicit administrator-issued input access; no upload or presigned URLs."""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from modelanvil.artifacts.models import Artifact, WorkerArtifactGrant
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.identity.models import Tenant
from modelanvil.jobs.models import Job, JobAttempt, Worker, WorkerCredential, WorkerPool


def require_feedback_artifact(artifact):
    from modelanvil.annotation.feedback import artifact_live
    try:artifact_live(artifact)
    except ValueError as exc:raise PermissionDenied('Feedback artifact is unavailable.') from exc


_SNAPSHOT_FIELDS = ("storage_location_id", "object_key", "object_version", "sha256", "byte_size", "media_type")


def artifact_snapshot(artifact):
    return {field: getattr(artifact, field) for field in _SNAPSHOT_FIELDS}


def storage_fingerprint():
    """Pin the single local backend, without retaining storage credentials."""
    config = settings.MODELANVIL
    if config.get("artifact_backend", "filesystem") != "filesystem":
        raise PermissionDenied("Worker artifact downloads require the qualified local backend.")
    root = str(Path(config["artifact_root"]).resolve())
    return hashlib.sha256(root.encode("utf-8")).hexdigest()


def _locked_execution(tenant_id, attempt_id, worker_id, fencing_token=None):
    # Commit/reconciliation already lock attempt before job. Avoid reversing
    # that order or locking through nullable joined worker relations.
    attempt = JobAttempt.all_objects.select_for_update().filter(
        tenant_id=tenant_id, attempt_id=attempt_id, worker_id=worker_id,
    ).first()
    if attempt is None:
        raise NotFound()
    job = Job.all_objects.select_for_update().filter(pk=attempt.job_id, tenant_id=tenant_id).first()
    worker = Worker.all_objects.select_for_update().filter(pk=worker_id, tenant_id=tenant_id).first()
    now = timezone.now()
    if (job is None or worker is None or worker.pool_id != job.pool_id
            or worker.status not in (Worker.Status.AVAILABLE, Worker.Status.BUSY, Worker.Status.DRAINING)
            or attempt.status != JobAttempt.Status.RUNNING
            or job.status != Job.Status.RUNNING or job.desired_action != Job.DesiredAction.RUN
            or job.claimed_by_id != worker_id or job.fencing_token != attempt.fencing_token
            or (fencing_token is not None and attempt.fencing_token != fencing_token)
            or attempt.lease_expires_at is None or attempt.lease_expires_at <= now
            or job.lease_expires_at is None or job.lease_expires_at <= now):
        raise PermissionDenied("Artifact access requires a current running execution.")
    if not WorkerPool.all_objects.select_for_update().filter(pk=job.pool_id, tenant_id=tenant_id).exists():
        raise PermissionDenied("Worker pool scope is no longer valid.")
    return attempt


@transaction.atomic
def issue_download_grant(*, tenant_id, attempt_id, worker_id, artifact_id, ttl_seconds):
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
        raise ValidationError({"ttl_seconds": "Provide an integer from 1 to 300."})
    attempt = _locked_execution(tenant_id, attempt_id, worker_id)
    artifact = Artifact.all_objects.select_for_update().filter(tenant_id=tenant_id, artifact_id=artifact_id).first()
    if artifact is None:
        raise NotFound()
    if (artifact.state != Artifact.State.COMMITTED or artifact.object_version
            or artifact.storage_location_id != "local"):
        raise PermissionDenied("Only committed unversioned local artifacts can be granted.")
    require_feedback_artifact(artifact)
    return WorkerArtifactGrant.all_objects.create(
        tenant_id=tenant_id, attempt=attempt, worker_id=worker_id, artifact=artifact,
        fencing_token=attempt.fencing_token, artifact_snapshot=artifact_snapshot(artifact),
        storage_fingerprint=storage_fingerprint(),
        expires_at=min(timezone.now() + timedelta(seconds=ttl_seconds), attempt.lease_expires_at),
    )


@contextmanager
def authorized_download(*, tenant_id, grant_id, worker_id, credential_id):
    """Keep revocation, attempt state and artifact tombstones locked for a read."""
    with transaction.atomic():
        reference = WorkerArtifactGrant.all_objects.filter(
            tenant_id=tenant_id, grant_id=grant_id, worker_id=worker_id,
        ).first()
        if reference is None:
            raise NotFound()
        _locked_execution(tenant_id, reference.attempt.attempt_id, worker_id, reference.fencing_token)
        grant = WorkerArtifactGrant.all_objects.select_for_update().get(pk=reference.pk)
        credential = WorkerCredential.all_objects.select_for_update().filter(
            pk=credential_id, tenant_id=tenant_id, worker_id=worker_id,
            revoked_at__isnull=True, expires_at__gt=timezone.now(),
        ).first()
        if credential is None:
            raise PermissionDenied("Worker credential is no longer valid.")
        tenant = Tenant.objects.select_for_update().filter(pk=tenant_id, status="active").first()
        if tenant is None:
            raise PermissionDenied("Tenant is no longer active.")
        artifact = Artifact.all_objects.select_for_update().filter(pk=grant.artifact_id, tenant_id=tenant_id).first()
        if (grant.revoked_at is not None or grant.expires_at <= timezone.now()
                or artifact is None or artifact.state != Artifact.State.COMMITTED
                or artifact_snapshot(artifact) != grant.artifact_snapshot
                or storage_fingerprint() != grant.storage_fingerprint):
            raise PermissionDenied("Artifact grant is no longer valid.")
        require_feedback_artifact(artifact)
        yield grant, artifact


@transaction.atomic
def discover_download_grants(*, tenant_id, attempt_id, worker_id, fencing_token, credential_id, cursor=None):
    """Disclose explicit input grants, never tenant storage metadata or bytes."""
    attempt = _locked_execution(tenant_id, attempt_id, worker_id, fencing_token)
    query = WorkerArtifactGrant.all_objects.select_for_update().filter(
        tenant_id=tenant_id, attempt=attempt, worker_id=worker_id,
        revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).order_by("grant_id")
    if cursor is not None:
        query = query.filter(grant_id__gt=cursor)
    candidates = list(query[:33])
    if not WorkerCredential.all_objects.select_for_update().filter(
            pk=credential_id, tenant_id=tenant_id, worker_id=worker_id,
            revoked_at__isnull=True, expires_at__gt=timezone.now()).exists():
        raise PermissionDenied("Worker credential is no longer valid.")
    if not Tenant.objects.select_for_update().filter(pk=tenant_id, status="active").exists():
        raise PermissionDenied("Tenant is no longer active.")
    grants = []
    for reference in candidates[:32]:
        try:
            with authorized_download(tenant_id=tenant_id, grant_id=reference.grant_id,
                                     worker_id=worker_id, credential_id=credential_id) as (grant, artifact):
                grants.append(({"grant_id": str(grant.grant_id), "artifact_id": str(artifact.artifact_id),
                               "sha256": artifact.sha256, "byte_size": artifact.byte_size,
                               "expires_at": grant.expires_at.isoformat()}, grant.expires_at))
        except (PermissionDenied, NotFound):
            continue
    # Row locks prevent ownership mutations, not wall-clock lease expiry.
    _locked_execution(tenant_id, attempt_id, worker_id, fencing_token)
    if not WorkerCredential.all_objects.select_for_update().filter(
            pk=credential_id, tenant_id=tenant_id, worker_id=worker_id,
            revoked_at__isnull=True, expires_at__gt=timezone.now()).exists():
        raise PermissionDenied("Worker credential is no longer valid.")
    now = timezone.now()
    return {"attempt_id": str(attempt.attempt_id),
            "grants": [reference for reference, expires_at in grants if expires_at > now],
            "next_cursor": str(candidates[31].grant_id) if len(candidates) > 32 else None}


class GrantDownload:
    """Bounded stream whose authority is checked before each local file read."""
    chunk_size = 64 * 1024

    def __init__(self, *, tenant_id, grant_id, worker_id, credential_id):
        self.scope = {"tenant_id": tenant_id, "grant_id": grant_id, "worker_id": worker_id,
                      "credential_id": credential_id}
        with authorized_download(**self.scope) as (grant, artifact):
            self.attempt_id = str(grant.attempt.attempt_id)
            self.artifact = artifact
            self.remaining = artifact.byte_size
            try:
                self.stream = artifact_storage_backend().open(tenant_id, str(artifact.object_key))
            except (FileNotFoundError, ValueError) as exc:
                raise NotFound("Artifact bytes are unavailable.") from exc

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining == 0:
            self.close()
            raise StopIteration
        try:
            with authorized_download(**self.scope):
                chunk = self.stream.read(min(self.chunk_size, self.remaining))
        except (PermissionDenied, NotFound):
            self.close()
            raise StopIteration
        if not chunk:
            self.close()
            raise StopIteration
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.stream.close()
