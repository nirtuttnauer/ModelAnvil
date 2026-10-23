"""Tenant-scoped job and artifact APIs; worker protocol stays separate."""
import hashlib
import json
import uuid
from typing import Any

from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from django.db import transaction
from django.http import FileResponse
from pathlib import PurePosixPath
from contracts import ApiError, ErrorCode

from modelanvil.core.ids import uuid7
from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, TransferSession
from modelanvil.artifacts.storage import (
    S3ArtifactStorage,
    artifact_storage_backend,
    upload_staged_artifact,
)
from modelanvil.artifacts.transfers import (
    TransferConflict,
    abort_transfer,
    add_transfer_part,
    complete_transfer as commit_transfer,
)
from modelanvil.core.models import IdempotencyKey, record_audit
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role
from modelanvil.jobs.models import Job, JobAttempt
from modelanvil.jobs.access import accessible_jobs, cancellation_endpoint
from modelanvil.budgets.models import BudgetPolicy, BudgetReservation


class ScopedViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated, TenantRBAC)
    write_role = Role.ENGINEER

    def initial(self, request, *args, **kwargs):
        self.required_role = Role.VIEWER if self.action in ("list", "retrieve", "download", "inspect") else self.write_role
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        tenant = get_active_tenant()
        if tenant is None:
            return self.queryset.none()
        qs = self.queryset.filter(tenant_id=tenant)
        if hasattr(self.queryset.model, "project"):
            from modelanvil.identity.models import get_accessible_queryset
            accessible_pks = get_accessible_queryset(self.queryset.model).values("pk")
            qs = qs.filter(pk__in=accessible_pks)
        return qs

    def perform_create(self, serializer):
        kwargs = {"tenant_id": get_active_tenant()}
        if hasattr(serializer.Meta.model, "project"):
            from modelanvil.core.tenancy import get_active_project
            active_project = get_active_project()
            if active_project:
                kwargs["project_id"] = active_project
        serializer.save(**kwargs)


class JobSerializer(serializers.ModelSerializer):
    cancel_endpoint = serializers.SerializerMethodField()
    budget_policy_id = serializers.UUIDField(write_only=True, required=False)
    estimated_amount = serializers.DecimalField(max_digits=24, decimal_places=6, write_only=True, required=False)
    requirements = serializers.DictField(required=False, default=dict)
    payload = serializers.DictField(required=False, default=dict)

    def get_cancel_endpoint(self, obj):
        return cancellation_endpoint(obj)

    class Meta:
        model = Job
        fields = ("job_id", "project", "name", "pool", "status", "desired_action", "cancel_endpoint", "requirements", "payload", "attempt_count", "max_attempts", "priority", "depends_on", "budget_policy_id", "estimated_amount", "created_at", "updated_at")
        read_only_fields = ("job_id", "project", "status", "desired_action", "attempt_count", "created_at", "updated_at")

    def validate(self, attrs):
        if attrs.get('payload', {}).get('type') in {'specialist_inference','recipe_execution'} or (self.instance and self.instance.payload.get('type') in {'specialist_inference','recipe_execution'}):
            raise serializers.ValidationError('Manage this job through its specialist request or recipe run.')
        if attrs.get('payload', {}).get('type') == 'qualified_evaluation' or (self.instance and self.instance.evaluation_runs.exists()):
            raise serializers.ValidationError('Manage evaluation jobs through their evaluation run.')
        requirements = attrs.get("requirements", self.instance.requirements if self.instance else {})
        payload = attrs.get("payload", self.instance.payload if self.instance else {})
        if "task_plugin" in requirements or "task_plugin_digest" in requirements:
            from modelanvil.compute.plugins import PluginError, definition, validate_configuration
            try:
                entry, digest = definition(requirements.get("task_plugin"), get_active_tenant(), "task")
                if requirements.get("task_plugin_digest") != digest:
                    raise PluginError("Task plugin revision is not installed.")
                validate_configuration(entry["configuration_schema"], payload.get("configuration", {}))
            except PluginError as exc:
                raise serializers.ValidationError(str(exc)) from None
        if (attrs.get('payload', {}).get('type') == 'model_import' or
                (self.instance and self.instance.payload.get('type') == 'model_import')):
            raise serializers.ValidationError('Manage model acquisition through the model-imports API.')
        if (self.instance and self.instance.training_runs.filter(hardware_config__execution_mode='worker').exists()):
            raise serializers.ValidationError('Training jobs are immutable; manage the associated training run.')
        if attrs.get('payload', {}).get('type') == 'qualified_training':
            raise serializers.ValidationError('Launch qualified training through the training-runs API.')
        if (attrs.get('payload', {}).get('type') == 'dataset_acquisition' or
                (self.instance and isinstance(self.instance.payload, dict) and self.instance.payload.get('type') == 'dataset_acquisition')):
            raise serializers.ValidationError('Manage dataset acquisition through the dataset-bank API.')
        has_policy = "budget_policy_id" in attrs
        has_estimate = "estimated_amount" in attrs
        if has_policy != has_estimate:
            raise serializers.ValidationError("budget_policy_id and estimated_amount must be provided together.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tenant_id = validated_data.pop("tenant_id")
        policy_id = validated_data.pop("budget_policy_id", None)
        estimated_amount = validated_data.pop("estimated_amount", None)
        has_enabled_policies = BudgetPolicy.all_objects.filter(tenant_id=tenant_id, enabled=True).exists()
        if has_enabled_policies and policy_id is None:
            raise serializers.ValidationError({"budget_policy_id": "A budget reservation is required for this tenant."})
        job_id = uuid7()
        if policy_id is not None:
            policy = BudgetPolicy.all_objects.filter(
                tenant_id=tenant_id, policy_id=policy_id, enabled=True
            ).first()
            if policy is None:
                raise serializers.ValidationError({"budget_policy_id": "No enabled policy exists in this tenant."})
            try:
                BudgetReservation.reserve(
                    tenant_id=tenant_id, policy=policy, job_id=job_id,
                    estimated_amount=estimated_amount,
                )
            except ValueError as exc:
                raise serializers.ValidationError({"budget": str(exc)}) from exc
        return Job.objects.create(tenant_id=tenant_id, job_id=job_id, **validated_data)


class JobViewSet(ScopedViewSet):
    queryset = Job.objects.select_related("pool")
    serializer_class = JobSerializer
    lookup_field = "job_id"

    def get_queryset(self):
        return accessible_jobs().select_related("pool").prefetch_related("training_runs")

    def destroy(self, request, *args, **kwargs):
        job = self.get_object()
        if job.evaluation_runs.exists():
            raise serializers.ValidationError('Manage this job through its evaluation run.')
        if isinstance(job.payload, dict) and job.payload.get('type') == 'dataset_acquisition':
            raise serializers.ValidationError('Dataset acquisition jobs retain provenance; cancel the acquisition.')
        if self.get_object().training_runs.filter(hardware_config__execution_mode='worker').exists():
            raise serializers.ValidationError('Training jobs retain accounting provenance; cancel the training run.')
        return super().destroy(request, *args, **kwargs)

    idempotency_ttl_seconds = 7 * 24 * 60 * 60

    @staticmethod
    def _idempotency_error(request, code, message, response_status, details=None):
        error = ApiError(code, message, response_status, details=details or [])
        error.request_id = getattr(request, "modelanvil_request_id", None)
        return Response(error.to_dict(), status=response_status)

    def create(self, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key", "").strip()
        if not key or len(key) > 128:
            return self._idempotency_error(
                request,
                ErrorCode.VALIDATION_FAILED,
                "A valid Idempotency-Key header is required.",
                status.HTTP_400_BAD_REQUEST,
                details=[{"path": "Idempotency-Key", "message": "Provide 1–128 non-whitespace characters."}],
            )

        tenant_id = get_active_tenant()
        principal = f"{getattr(request, 'modelanvil_actor_kind', 'principal')}:{getattr(request, 'modelanvil_actor_id', request.user.pk)}"
        request_hash = hashlib.sha256(
            json.dumps(request.data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        lookup = {
            "tenant_id": tenant_id,
            "principal": principal,
            "http_method": request.method,
            "path": request.path,
            "key": key,
        }

        with transaction.atomic():
            record, created = IdempotencyKey.all_objects.select_for_update().get_or_create(
                **lookup,
                defaults={"request_hash": request_hash},
            )
            if not created and record.is_expired(self.idempotency_ttl_seconds):
                record.delete()
                record = IdempotencyKey.all_objects.create(**lookup, request_hash=request_hash)
                created = True

            if not created:
                if record.request_hash != request_hash:
                    return self._idempotency_error(
                        request,
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "This Idempotency-Key was already used with a different request.",
                        status.HTTP_409_CONFLICT,
                    )
                if record.response_status is None:
                    return self._idempotency_error(
                        request,
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "A request with this Idempotency-Key is still in progress.",
                        status.HTTP_409_CONFLICT,
                    )
                response = Response(record.response_body, status=record.response_status)
            else:
                response = super().create(request, *args, **kwargs)
                record.response_status = response.status_code
                record.response_body = json.loads(JSONRenderer().render(response.data))
                record.completed_at = timezone.now()
                record.save(update_fields=("response_status", "response_body", "completed_at", "updated_at"))

        response["Idempotency-Retention"] = str(self.idempotency_ttl_seconds)
        return response

    def perform_create(self, serializer):
        if serializer.validated_data["pool"].tenant_id != get_active_tenant():
            raise NotFound()
        from modelanvil.core.tenancy import get_active_project
        job = serializer.save(tenant_id=get_active_tenant(), project_id=get_active_project())
        record_audit("create", "job", job.job_id, tenant_id=job.tenant_id,
            actor_id=getattr(self.request, "modelanvil_actor_id", None),
            actor_kind=getattr(self.request, "modelanvil_actor_kind", "principal"),
            input_snapshot={"name": job.name, "pool": job.pool_id, "status": job.status})

    def perform_update(self, serializer):
        pool = serializer.validated_data.get("pool", serializer.instance.pool)
        if pool.tenant_id != get_active_tenant():
            raise NotFound()
        serializer.save()

    def perform_destroy(self, instance):
        if instance.payload.get('type') == 'model_import':
            raise serializers.ValidationError('Model import jobs retain their acquisition history.')
        if instance.payload.get('type') in {'specialist_inference','recipe_execution'}:
            raise serializers.ValidationError('Execution jobs retain durable request and accounting history.')
        super().perform_destroy(instance)

    @action(detail=True, methods=("post",))
    def cancel(self, request, job_id=None):
        job = self.get_object()
        if job.payload.get('type') == 'model_import':
            raise serializers.ValidationError('Cancel this job through its model import.')
        if job.payload.get('type') in {'specialist_inference','recipe_execution'}:
            raise serializers.ValidationError('Cancel this job through its specialist request or recipe run.')
        if job.evaluation_runs.exists():
            raise serializers.ValidationError('Manage this job through its evaluation run.')
        if isinstance(job.payload, dict) and job.payload.get('type') == 'dataset_acquisition':
            raise serializers.ValidationError('Cancel this job through its dataset acquisition.')
        if job.training_runs.filter(hardware_config__execution_mode='worker').exists():
            raise serializers.ValidationError('Cancel this job through its associated training run.')
        response_status = status.HTTP_200_OK
        with transaction.atomic():
            job = Job.objects.select_for_update().get(pk=job.pk)
            previous = (job.status, job.desired_action)
            if job.status == Job.Status.QUEUED:
                job.status = Job.Status.CANCELLED
                job.desired_action = Job.DesiredAction.CANCEL
                job.save(update_fields=("status", "desired_action", "updated_at"))
            elif job.status == Job.Status.RUNNING:
                if job.desired_action != Job.DesiredAction.CANCEL:
                    job.desired_action = Job.DesiredAction.CANCEL
                    job.save(update_fields=("desired_action", "updated_at"))
                response_status = status.HTTP_202_ACCEPTED
            elif job.status != Job.Status.CANCELLED:
                return Response(
                    {"detail": "This job is already terminal and cannot be cancelled."},
                    status=status.HTTP_409_CONFLICT,
                )
            if job.status == Job.Status.CANCELLED:
                BudgetReservation.objects.filter(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    state=BudgetReservation.State.RESERVED,
                ).update(state=BudgetReservation.State.RELEASED, settled_at=timezone.now())
            if previous != (job.status, job.desired_action):
                record_audit("cancel", "job", job.job_id, tenant_id=job.tenant_id,
                    actor_id=getattr(request, "modelanvil_actor_id", None),
                    actor_kind=getattr(request, "modelanvil_actor_kind", "principal"),
                    input_snapshot={"status": job.status, "desired_action": job.desired_action})
        return Response(JobSerializer(job).data, status=response_status)


class JobAttemptSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source="job.job_id", read_only=True)

    class Meta:
        model = JobAttempt
        fields = ("attempt_id", "job_id", "worker_id", "status", "lease_expires_at", "progress", "result_envelope", "error", "started_at", "completed_at")
        read_only_fields = fields


class JobAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = JobAttempt.objects.select_related("job", "worker")
    serializer_class = JobAttemptSerializer
    permission_classes = (IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    lookup_field = "attempt_id"

    def get_queryset(self):
        tenant = get_active_tenant()
        if not tenant:
            return self.queryset.none()
        qs = self.queryset.filter(tenant_id=tenant, job__in=accessible_jobs())
        job_id = self.request.query_params.get("job_id")
        if job_id:
            try:
                job_id = uuid.UUID(job_id)
            except ValueError:
                raise ValidationError({"job_id": "Provide a valid job UUID."})
            qs = qs.filter(job__job_id=job_id)
        return qs


class ArtifactSerializer(serializers.ModelSerializer):
    def validate(self,attrs):
        if attrs.get('metadata',{}).get('application_feedback_id'):
            raise serializers.ValidationError('Application feedback provenance is server-owned.')
        if self.instance and self.instance.metadata.get('application_feedback_id'):
            raise serializers.ValidationError('Manage application feedback artifacts through their owned feedback record.')
        return attrs
    class Meta:
        model = Artifact
        fields = ("artifact_id", "project", "storage_location_id", "object_key", "object_version", "sha256", "byte_size", "media_type", "state", "committed_at", "tombstoned_at", "metadata", "created_at")
        read_only_fields = ("artifact_id", "state", "committed_at", "tombstoned_at", "created_at")


class ArtifactViewSet(ScopedViewSet):
    queryset = Artifact.objects.all()
    serializer_class = ArtifactSerializer
    lookup_field = "artifact_id"

    @staticmethod
    def _transfer_response(transfer: TransferSession) -> dict[str, Any]:
        return {
            "transfer_id": transfer.transfer_id,
            "artifact_id": transfer.artifact.artifact_id,
            "state": transfer.state,
            "bytes_verified": transfer.bytes_verified,
            "expires_at": transfer.expires_at,
            "part_manifest": transfer.part_manifest,
        }

    @action(detail=True, methods=("post",), url_path="transfers")
    def create_transfer(self, request, artifact_id=None):
        artifact = self.get_object()
        with transaction.atomic():
            artifact = Artifact.all_objects.select_for_update().filter(
                pk=artifact.pk,
                tenant_id=get_active_tenant(),
            ).first()
            if artifact is None:
                raise NotFound()
            if artifact.state != Artifact.State.STAGING:
                return Response(
                    {"detail": "Only staging artifacts accept transfer sessions."},
                    status=status.HTTP_409_CONFLICT,
                )
            transfer = TransferSession.all_objects.select_for_update().filter(
                tenant_id=artifact.tenant_id,
                artifact=artifact,
                state=TransferSession.State.OPEN,
            ).first()
            response_status = status.HTTP_200_OK
            if transfer and transfer.expires_at <= timezone.now():
                transfer.state = TransferSession.State.EXPIRED
                transfer.save(update_fields=("state", "updated_at"))
                transfer = None
            if transfer is None:
                transfer = TransferSession(
                    tenant_id=artifact.tenant_id,
                    artifact=artifact,
                )
                transfer.save()
                response_status = status.HTTP_201_CREATED
        return Response(self._transfer_response(transfer), status=response_status)

    @action(detail=True, methods=("get",), url_path=r"transfers/(?P<transfer_id>[^/.]+)")
    def transfer_status(self, request, artifact_id=None, transfer_id=None):
        artifact = self.get_object()
        with transaction.atomic():
            transfer = TransferSession.all_objects.select_for_update().filter(
                transfer_id=transfer_id,
                tenant_id=artifact.tenant_id,
                artifact=artifact,
            ).first()
            if transfer is None:
                raise NotFound()
            if transfer.state == TransferSession.State.OPEN and transfer.expires_at <= timezone.now():
                transfer.state = TransferSession.State.EXPIRED
                transfer.save(update_fields=("state", "updated_at"))
        return Response(self._transfer_response(transfer))

    @action(
        detail=True,
        methods=("put",),
        url_path=r"transfers/(?P<transfer_id>[^/.]+)/parts/(?P<part_number>[0-9]+)",
    )
    def upload_transfer_part(self, request, artifact_id=None, transfer_id=None, part_number=None):
        artifact = self.get_object()
        transfer = TransferSession.all_objects.filter(
            transfer_id=transfer_id,
            tenant_id=artifact.tenant_id,
            artifact=artifact,
        ).first()
        if transfer is None:
            raise NotFound()
        uploaded_file = request.data.get("file")
        if uploaded_file is None or not hasattr(uploaded_file, "read"):
            raise ValidationError({"file": "A multipart file field is required."})
        try:
            transfer = add_transfer_part(
                transfer,
                int(part_number),
                uploaded_file,
                expected_sha256=request.headers.get("X-Part-SHA256", ""),
                expected_size=int(uploaded_file.size),
                backend=artifact_storage_backend(),
            )
        except TransferConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except S3ArtifactStorage.ConditionalConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self._transfer_response(transfer))

    @action(
        detail=True,
        methods=("post",),
        url_path=r"transfers/(?P<transfer_id>[^/.]+)/complete",
    )
    def complete_transfer(self, request, artifact_id=None, transfer_id=None):
        artifact = self.get_object()
        transfer = TransferSession.all_objects.filter(
            transfer_id=transfer_id,
            tenant_id=artifact.tenant_id,
            artifact=artifact,
        ).first()
        if transfer is None:
            raise NotFound()
        try:
            transfer = commit_transfer(transfer, backend=artifact_storage_backend())
        except TransferConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except S3ArtifactStorage.ConditionalConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self._transfer_response(transfer))

    @action(
        detail=True,
        methods=("post",),
        url_path=r"transfers/(?P<transfer_id>[^/.]+)/abort",
    )
    def abort_transfer(self, request, artifact_id=None, transfer_id=None):
        artifact = self.get_object()
        transfer = TransferSession.all_objects.filter(
            transfer_id=transfer_id,
            tenant_id=artifact.tenant_id,
            artifact=artifact,
        ).first()
        if transfer is None:
            raise NotFound()
        try:
            transfer = abort_transfer(transfer)
        except TransferConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(self._transfer_response(transfer))

    @action(detail=True, methods=("get",))
    def download(self, request, artifact_id=None):
        artifact = self.get_object()
        from modelanvil.annotation.feedback import artifact_live
        try:artifact_live(artifact)
        except ValueError as exc:raise NotFound('Feedback artifact is unavailable.') from exc
        if artifact.state == Artifact.State.TOMBSTONED:
            raise NotFound()
        if artifact.state != Artifact.State.COMMITTED:
            return Response(
                {"detail": "Artifact bytes are unavailable until the artifact is committed."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            stream = artifact_storage_backend().open(artifact.tenant_id, str(artifact.object_key))
        except FileNotFoundError as exc:
            raise NotFound("Committed artifact bytes are unavailable.") from exc
        response = FileResponse(
            stream,
            as_attachment=True,
            filename=PurePosixPath(str(artifact.object_key)).name,
            content_type=str(artifact.media_type),
        )
        response["Content-Length"] = str(artifact.byte_size)
        response["ETag"] = f'"{artifact.sha256}"'
        response["Cache-Control"] = "private, no-store"
        return response

    @action(detail=True, methods=("post",))
    def upload(self, request, artifact_id=None):
        artifact = self.get_object()
        uploaded_file = request.data.get("file")
        if uploaded_file is None or not hasattr(uploaded_file, "read"):
            raise ValidationError({"file": "A multipart file field is required."})
        try:
            upload_staged_artifact(artifact, uploaded_file, backend=artifact_storage_backend())
        except FileExistsError as exc:
            return Response({"detail": "An object already exists at this immutable key."}, status=status.HTTP_409_CONFLICT)
        except S3ArtifactStorage.ConditionalConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except (ValueError, TypeError) as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(self.get_serializer(artifact).data)


class DatasetSerializer(serializers.ModelSerializer):
    def validate_name(self, value):
        matches = Dataset.all_objects.filter(tenant_id=get_active_tenant(), name=value)
        if self.instance:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise ValidationError('A dataset already uses this name in your workspace. Choose a different dataset name.')
        return value

    class Meta:
        model = Dataset
        fields = ("dataset_id", "project", "name", "description", "current_revision", "metadata", "created_at", "updated_at")
        read_only_fields = ("dataset_id", "current_revision", "created_at", "updated_at")


class DatasetViewSet(ScopedViewSet):
    queryset = Dataset.objects.all()
    serializer_class = DatasetSerializer
    lookup_field = "dataset_id"

    def create(self, request, *args, **kwargs):
        from modelanvil.api.idempotence import idempotent_write
        return idempotent_write(request, lambda: super(DatasetViewSet, self).create(request, *args, **kwargs))

    @action(detail=False, methods=['post'], url_path='preview')
    def preview(self, request):
        from modelanvil.data.publication import prepare_source, DatasetPreparationError, MAX_INPUT_BYTES
        file = request.data.get('file')
        if file is None or not hasattr(file, 'read') or not 0 < file.size <= MAX_INPUT_BYTES:
            raise ValidationError('Choose a nonempty source file of at most 16 MiB.')
        try:
            configuration = json.loads(request.data.get('configuration', '{}'))
        except (TypeError, ValueError):
            raise ValidationError('Preview configuration must be a JSON object.') from None
        serializer = DatasetPreparationOptionsSerializer(data=configuration)
        serializer.is_valid(raise_exception=True)
        try:
            prepared, _ = prepare_source(file.read(MAX_INPUT_BYTES+1), **serializer.validated_data)
        except DatasetPreparationError as exc:
            raise ValidationError({'preview': str(exc)}) from None
        splits = {sample_id: split for split, ids in prepared['split_manifest'].items() for sample_id in ids}
        return Response({'recipe': prepared['recipe'], 'recipe_digest': prepared['recipe_digest'],
            'row_count': prepared['row_count'], 'source_group_count': prepared['source_group_count'],
            'split_counts': {split: len(ids) for split, ids in prepared['split_manifest'].items()},
            'rows': [{**row, 'assigned_split': splits.get(row['sample_id'])} for row in prepared['rows'][:25]],
            'dropped': prepared.get('dropped', [])[:25], 'report': prepared.get('report'),
            'limits': 'Preview shows at most 25 parsed samples and 25 exclusions. Publication repeats this exact recipe on verified source bytes; no resources were created by preview.'})

    @action(detail=True, methods=("post",))
    def prepare(self, request, dataset_id=None):
        from modelanvil.api.idempotence import idempotent_write
        return idempotent_write(request, lambda: self._prepare(request, dataset_id))

    def _prepare(self, request, dataset_id=None):
        from modelanvil.data.publication import DatasetPreparationError, publish_prepared_dataset

        dataset = self.get_object()
        serializer = DatasetPreparationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        artifact_id = values.pop("input_artifact_id")
        artifact = Artifact.all_objects.filter(artifact_id=artifact_id, tenant_id=get_active_tenant()).first()
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        if artifact is None or not check_resource_access(artifact, dataset.project_id or get_active_project(), get_active_tenant()):
            raise NotFound()
        if artifact.state != Artifact.State.COMMITTED:
            return Response({"detail": "Preparation requires a committed input artifact."},
                            status=status.HTTP_409_CONFLICT)
        try:
            revision = publish_prepared_dataset(dataset, artifact, **values)
        except DatasetPreparationError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response(DatasetRevisionSerializer(revision).data, status=status.HTTP_201_CREATED)


class DatasetPreparationOptionsSerializer(serializers.Serializer):
    source_format = serializers.ChoiceField(choices=("jsonl", "csv", "json", "docx", "pdf", "training"), required=False, default="jsonl")
    source_mapping = serializers.JSONField(required=False)
    text_field = serializers.CharField(required=False, default="text", max_length=128, trim_whitespace=False)
    group_field = serializers.CharField(required=False, default=None, allow_null=True, max_length=128, trim_whitespace=False)
    chunk_characters = serializers.JSONField(required=False, default=None, allow_null=True)
    split_seed = serializers.JSONField(required=False, default="0")
    validation_percent = serializers.JSONField(required=False, default=10)
    test_percent = serializers.JSONField(required=False, default=10)
    # Detection options pass through to the pure kernel, which owns type
    # validation (invalid values surface as 400s, never partial publications).
    detect = serializers.JSONField(required=False, default=None, allow_null=True)
    dedup = serializers.JSONField(required=False, default=None, allow_null=True)
    protected = serializers.JSONField(required=False, default=None, allow_null=True)
    near_threshold = serializers.JSONField(required=False, default=3)
    min_text_chars = serializers.JSONField(required=False, default=None, allow_null=True)

    def to_internal_value(self, data):
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({
                "non_field_errors": ["Unknown preparation request fields are not supported."],
            })
        return super().to_internal_value(data)

    def validate(self, attrs):
        limit = attrs["chunk_characters"]
        if limit is not None and (type(limit) is not int or not 32 <= limit <= 4096):
            raise serializers.ValidationError("Chunk character limit must be an integer from 32 to 4096.")
        if not isinstance(attrs["split_seed"], str) or len(attrs["split_seed"]) > 1024:
            raise serializers.ValidationError("Split seed must be a string of at most 1024 characters.")
        percentages = (attrs["validation_percent"], attrs["test_percent"])
        if any(type(value) is not int or value < 0 for value in percentages) or sum(percentages) >= 100:
            raise serializers.ValidationError("Split percentages must be nonnegative integers with a sum below 100.")
        return attrs


class DatasetPreparationSerializer(DatasetPreparationOptionsSerializer):
    input_artifact_id = serializers.UUIDField()


class DatasetRevisionSerializer(serializers.ModelSerializer):
    dataset_name = serializers.CharField(source='dataset.name', read_only=True)
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from modelanvil.identity.models import get_accessible_queryset
        if "dataset" in self.fields:
            self.fields["dataset"].queryset = get_accessible_queryset(Dataset)
        if "manifest_artifact" in self.fields:
            self.fields["manifest_artifact"].queryset = get_accessible_queryset(Artifact)

    class Meta:
        model = DatasetRevision
        fields = ("id", "dataset_name", "revision_id", "project", "dataset", "revision_no", "schema_version", "manifest_digest", "manifest_artifact", "recipe_digest", "source_snapshots", "row_count", "state", "published_at", "metadata")
        read_only_fields = ("id", "dataset_name", "revision_id", "state", "published_at")


class DatasetRevisionViewSet(ScopedViewSet):
    queryset = DatasetRevision.objects.select_related("dataset", "manifest_artifact")
    serializer_class = DatasetRevisionSerializer
    lookup_field = "revision_id"

    @action(detail=True, methods=['get'], url_path='inspect')
    def inspect(self, request, revision_id=None):
        from modelanvil.api.resource_inspection import inspect_dataset
        cursor = serializers.IntegerField(min_value=0, max_value=10000).run_validation(request.query_params.get('cursor', 0))
        query = serializers.CharField(max_length=200, allow_blank=True).run_validation(request.query_params.get('query', ''))
        try:
            return Response(inspect_dataset(self.get_object(), cursor, query))
        except (ValueError, OSError) as exc:
            raise ValidationError({'inspection': str(exc) if isinstance(exc, ValueError) else 'Manifest bytes are unavailable.'}) from exc

    def perform_create(self, serializer):
        dataset = serializer.validated_data["dataset"]
        artifact = serializer.validated_data.get("manifest_artifact")
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        active_project = get_active_project() or getattr(dataset, "project_id", None)
        if not check_resource_access(dataset, active_project, get_active_tenant()):
            raise NotFound()
        if artifact and not check_resource_access(artifact, active_project, get_active_tenant()):
            raise NotFound()
        kwargs = {"tenant_id": get_active_tenant()}
        if active_project:
            kwargs["project_id"] = active_project
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        dataset = serializer.validated_data.get("dataset", serializer.instance.dataset)
        artifact = serializer.validated_data.get("manifest_artifact", serializer.instance.manifest_artifact)
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        active_project = get_active_project() or getattr(serializer.instance, "project_id", None) or getattr(dataset, "project_id", None)
        if not check_resource_access(dataset, active_project, get_active_tenant()):
            raise NotFound()
        if artifact and not check_resource_access(artifact, active_project, get_active_tenant()):
            raise NotFound()
        serializer.save()

    @action(detail=True, methods=("post",))
    def publish(self, request, revision_id=None):
        revision = self.get_object()
        try:
            revision.publish()
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(DatasetRevisionSerializer(revision).data)
