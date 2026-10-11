"""Human labeling workflows. No heuristic inference or registry-only training is executed here."""
import hashlib
import json
import uuid

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from modelanvil.annotation.campaign_engine import CampaignEngine
from modelanvil.annotation.models import (
    AnnotationRecord, AnnotationTask, CampaignBatch, CumulativeSnapshot,
    LabelingCampaign, LabelSchema, RubricRevision,
)
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.models import record_audit
from modelanvil.core.exceptions import WorkflowConflict as Conflict
from modelanvil.core.tenancy import get_active_tenant, get_active_project
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.models import ModelVersion


def audit(request, action_name, resource, resource_id, **details):
    record_audit(action_name, resource, resource_id,
                 actor_id=request.modelanvil_actor_id,
                 actor_kind=request.modelanvil_actor_kind, input_snapshot=details)


class ReadWorkflowViewSet(TenantScopedViewSet):
    # Reviewed history and snapshots are immutable through this API.
    http_method_names = ["get", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed("POST")


class SchemaSerializer(serializers.ModelSerializer):
    class Meta:
        model = LabelSchema
        fields = ("schema_id", "name", "kind", "classes", "specification")


class RubricSerializer(serializers.ModelSerializer):
    class Meta:
        model = RubricRevision
        fields = ("rubric_id", "name", "revision_no", "guidelines_text", "criteria")


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CumulativeSnapshot
        fields = ("snapshot_id", "cycle_no", "item_count", "manifest_digest", "created_at")


class BatchSerializer(serializers.ModelSerializer):
    drafting_model_id = serializers.UUIDField(source="assigned_drafting_model.model_version_id", read_only=True, allow_null=True)
    reviewed_count = serializers.SerializerMethodField()

    def get_reviewed_count(self, batch):
        return batch.tasks.filter(records__isnull=False).distinct().count()

    class Meta:
        model = CampaignBatch
        fields = ("batch_id", "cycle_no", "status", "sample_count", "reviewed_count", "approved_count",
                  "snapshot_manifest_digest", "drafting_model_id", "created_at")


class CampaignSerializer(serializers.ModelSerializer):
    label_schema = SchemaSerializer(read_only=True)
    rubric = RubricSerializer(read_only=True)
    active_model_id = serializers.UUIDField(source="active_drafting_model.model_version_id", read_only=True, allow_null=True)
    batches = BatchSerializer(many=True, read_only=True)
    snapshots = SnapshotSerializer(many=True, read_only=True)

    class Meta:
        model = LabelingCampaign
        fields = ("campaign_id", "name", "status", "seed_mode", "current_cycle", "max_cycles",
                  "budget_limit_dollars", "accumulated_cost_dollars", "held_out_audit_digest",
                  "active_model_id", "label_schema", "rubric", "configuration", "batches", "snapshots", "created_at")


class CampaignSetupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    kind = serializers.ChoiceField(choices=LabelSchema.Kind.choices)
    classes = serializers.ListField(child=serializers.CharField(max_length=128), default=list, max_length=200)
    guidelines = serializers.CharField(default="", allow_blank=True, max_length=20000)
    seed_mode = serializers.ChoiceField(choices=LabelingCampaign.SeedMode.choices, default="manual")
    drafting_model_id = serializers.UUIDField(required=False, allow_null=True)
    max_cycles = serializers.IntegerField(min_value=1, max_value=100, default=3)
    budget_limit_dollars = serializers.FloatField(min_value=0, max_value=1000000, default=100)
    audit_sample_refs = serializers.ListField(child=serializers.CharField(max_length=128), default=list, max_length=10000)

    def validate(self, data):
        if LabelingCampaign.objects.filter(name=data["name"], tenant_id=get_active_tenant()).exists():
            raise ValidationError({"name": "A campaign with this name already exists."})
        if data["kind"] == "classification" and (not data["classes"] or len(set(data["classes"])) != len(data["classes"])):
            raise ValidationError({"classes": "Provide distinct classification labels."})
        model_id = data.pop("drafting_model_id", None)
        model = ModelVersion.objects.filter(model_version_id=model_id, tenant_id=get_active_tenant()).first() if model_id else None
        if model_id and (model is None or not check_resource_access(model, get_active_project(), get_active_tenant())):
            raise ValidationError({"drafting_model_id": "Model version not found in this workspace."})
        if data["seed_mode"] == "existing_model" and model is None:
            raise ValidationError({"drafting_model_id": "Select the version that produced the imported drafts."})
        if data["seed_mode"] == "manual" and model is not None:
            raise ValidationError({"drafting_model_id": "Manual campaigns must not specify a drafting model."})
        data["active_drafting_model"] = model
        return data


class CampaignViewSet(ReadWorkflowViewSet):
    queryset = LabelingCampaign.objects.select_related("label_schema", "rubric", "active_drafting_model").prefetch_related("batches", "snapshots")
    serializer_class = CampaignSerializer
    lookup_field = "campaign_id"

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        ser = CampaignSetupSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tenant = get_active_tenant()
        suffix = str(uuid.uuid4())[:8]
        schema = LabelSchema.objects.create(tenant_id=tenant, name=f'{data["name"][:170]} · labels {suffix}', kind=data["kind"], classes=data["classes"])
        rubric = RubricRevision.objects.create(tenant_id=tenant, name=f'{data["name"][:170]} · rubric {suffix}', guidelines_text=data["guidelines"]) if data["guidelines"] else None
        campaign = CampaignEngine().create_campaign(
            name=data["name"], tenant_id=tenant, label_schema=schema, rubric=rubric,
            seed_mode=data["seed_mode"], active_drafting_model=data["active_drafting_model"],
            max_cycles=data["max_cycles"], budget_limit_dollars=data["budget_limit_dollars"],
            audit_samples=[{"id": ref} for ref in data["audit_sample_refs"]],
            configuration={"audit_sample_refs": data["audit_sample_refs"], "draft_source": "imported"},
        )
        audit(request, "create", "labeling_campaign", campaign.campaign_id)
        return Response(self.get_serializer(campaign).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def lifecycle(self, request, campaign_id=None):
        campaign = self.get_queryset().select_for_update(of=("self",)).get(pk=self.get_object().pk)
        transition = request.data.get("transition")
        target = {("active", "pause"): "paused", ("paused", "resume"): "active"}.get((campaign.status, transition))
        if target is None:
            raise Conflict("This campaign cannot make that transition.")
        campaign.status = target
        campaign.save(update_fields=["status", "updated_at"])
        audit(request, "update", "labeling_campaign", campaign.campaign_id, transition=transition)
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def batches(self, request, campaign_id=None):
        campaign = self.get_queryset().select_for_update(of=("self",)).get(pk=self.get_object().pk)
        if campaign.status != "active" or campaign.current_cycle >= campaign.max_cycles:
            raise Conflict("The campaign must be active and have a remaining cycle.")
        if campaign.batches.exclude(status="closed").exists():
            raise Conflict("Close the current batch before starting another cycle.")
        ser = SamplesSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        samples = ser.validated_data["samples"]
        audit_refs = set(campaign.configuration.get("audit_sample_refs", []))
        seen = set(campaign.tasks.values_list("sample_ref", flat=True))
        fingerprints = {sample_digest(c) for c in campaign.tasks.values_list("content", flat=True)}
        for sample in samples:
            ref = sample["id"]
            fingerprint = sample_digest(sample)
            if ref in seen or fingerprint in fingerprints:
                raise ValidationError({"samples": f"Duplicate or previously used sample: {ref}."})
            if ref in audit_refs or sample.get("protected") or sample.get("split") in ("audit", "test", "evaluation", "protected_eval", "held_out"):
                raise ValidationError({"samples": f"Protected audit/evaluation sample cannot enter training: {ref}."})
            if "draft_prediction" in sample:
                if campaign.active_drafting_model is None:
                    raise ValidationError({"samples": "Imported predictions require a pinned drafting model."})
                prediction = sample["draft_prediction"]
                if not isinstance(prediction, dict) or prediction.get("model_version_id") != str(campaign.active_drafting_model.model_version_id):
                    raise ValidationError({"samples": "Every draft must identify the campaign's pinned model_version_id."})
                validate_label(campaign.label_schema, {"label": prediction.get("predicted_label")})
            seen.add(ref)
            fingerprints.add(fingerprint)
        batch = CampaignEngine().start_batch(campaign, samples)
        batch.tasks.filter(content__has_key="draft_prediction").update(status="drafted")
        batch.status = "reviewing"
        batch.save(update_fields=["status", "updated_at"])
        audit(request, "create", "labeling_batch", batch.batch_id, sample_count=len(samples))
        return Response(BatchSerializer(batch).data, status=201)


def sample_digest(sample):
    # Provenance and prediction metadata do not make the underlying input new.
    content = {k: sample[k] for k in ("text", "prompt", "input", "candidate_a", "candidate_b") if k in sample}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


class SamplesSerializer(serializers.Serializer):
    samples = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=500)

    def validate_samples(self, samples):
        for sample in samples:
            if not isinstance(sample.get("id"), str) or not sample["id"].strip() or len(sample["id"]) > 128:
                raise ValidationError("Every sample requires a unique string id (1–128 characters).")
            if not any(key in sample for key in ("text", "prompt", "input", "candidate_a")):
                raise ValidationError("Every sample needs text, prompt, input, or candidate_a content.")
        return samples


def validate_label(schema, value):
    label = value.get("label")
    if schema.kind == "classification" and label not in schema.classes:
        raise ValidationError({"human_label": "Choose a label from the campaign schema."})
    if schema.kind == "text_generation" and (not isinstance(label, str) or not label.strip()):
        raise ValidationError({"human_label": "Provide a nonempty text response."})
    if schema.kind == "preference_ranking" and label not in ("candidate_a", "candidate_b", "tie", "abstain"):
        raise ValidationError({"human_label": "Choose candidate_a, candidate_b, tie, or abstain."})
    if schema.kind in ("ner_span", "rubric_scoring") and not isinstance(label, (dict, list)):
        raise ValidationError({"human_label": "Provide structured JSON for spans or rubric scores."})


class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnnotationRecord
        fields = ("record_id", "revision_no", "reviewer_id", "original_prediction", "human_label", "decision", "preference_choice", "created_at")


class TaskSerializer(serializers.ModelSerializer):
    latest_review = serializers.SerializerMethodField()

    def get_latest_review(self, task):
        record = task.records.order_by("-revision_no").first()
        return RecordSerializer(record).data if record else None

    class Meta:
        model = AnnotationTask
        fields = ("task_id", "sample_ref", "content", "status", "latest_review")


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=AnnotationRecord.Decision.choices)
    human_label = serializers.DictField(default=dict)
    expected_revision = serializers.IntegerField(min_value=1)


class BatchViewSet(ReadWorkflowViewSet):
    queryset = CampaignBatch.objects.select_related("campaign", "campaign__label_schema")
    serializer_class = BatchSerializer
    lookup_field = "batch_id"

    @action(detail=True, methods=["get"])
    def tasks(self, request, batch_id=None):
        tasks = self.get_object().tasks.filter(tenant_id=get_active_tenant())
        page = self.paginate_queryset(tasks)
        return self.get_paginated_response(TaskSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def close(self, request, batch_id=None):
        found = self.get_object()
        campaign = LabelingCampaign.objects.select_for_update().get(pk=found.campaign_id, tenant_id=get_active_tenant())
        batch = CampaignBatch.objects.select_for_update().get(pk=found.pk, tenant_id=get_active_tenant())
        if batch.status == "closed":
            return Response(SnapshotSerializer(campaign.snapshots.get(cycle_no=batch.cycle_no)).data)
        if campaign.status != "active":
            raise Conflict("Resume the campaign before closing this batch.")
        if batch.tasks.filter(records__isnull=True).exists():
            raise Conflict("Review or skip every sample before closing the batch.")
        snapshot = CampaignEngine().close_batch(batch)
        if campaign.current_cycle + 1 >= campaign.max_cycles:
            campaign.status = "completed"
            campaign.save(update_fields=["status", "updated_at"])
        audit(request, "create", "annotation_snapshot", snapshot.snapshot_id, digest=snapshot.manifest_digest)
        return Response(SnapshotSerializer(snapshot).data)


class TaskViewSet(ReadWorkflowViewSet):
    queryset = AnnotationTask.objects.select_related("campaign", "campaign__label_schema", "batch")
    serializer_class = TaskSerializer
    lookup_field = "task_id"

    @action(detail=True, methods=["get"])
    def history(self, request, task_id=None):
        page = self.paginate_queryset(self.get_object().records.filter(tenant_id=get_active_tenant()))
        return self.get_paginated_response(RecordSerializer(page, many=True).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def review(self, request, task_id=None):
        found = self.get_object()
        if found.campaign_id is None or found.batch_id is None:
            raise Conflict("This task does not belong to a campaign batch.")
        # Same lock order as close/batch creation prevents review versus closure races.
        campaign = LabelingCampaign.objects.select_for_update().select_related("label_schema").get(pk=found.campaign_id, tenant_id=get_active_tenant())
        batch = CampaignBatch.objects.select_for_update().get(pk=found.batch_id, tenant_id=get_active_tenant())
        task = AnnotationTask.objects.select_for_update().get(pk=found.pk, tenant_id=get_active_tenant())
        if campaign.status != "active" or batch.status == "closed":
            raise Conflict("Reviews require an active campaign and an open batch.")
        ser = ReviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        latest = task.records.order_by("-revision_no").first()
        if data["expected_revision"] != (latest.revision_no if latest else 0) + 1:
            raise Conflict("Another reviewer changed this task. Refresh before submitting again.")
        if data["decision"] in ("corrected", "accepted_without_edit"):
            validate_label(campaign.label_schema, data["human_label"])
            prediction = task.content.get("draft_prediction", {})
            if data["decision"] == "accepted_without_edit" and data["human_label"].get("label") != prediction.get("predicted_label"):
                raise ValidationError({"decision": "Accept requires an unchanged imported prediction. Use Save label for manual work."})
        record = CampaignEngine().submit_review(task=task,
            reviewer_id=f'{request.modelanvil_actor_kind}:{request.modelanvil_actor_id}',
            **data, preference_choice=data["human_label"].get("label", "") if campaign.label_schema.kind == "preference_ranking" else "")
        audit(request, "create", "annotation_review", record.record_id, task_id=str(task.task_id), decision=record.decision)
        return Response(TaskSerializer(task).data, status=201)


class SnapshotViewSet(ReadWorkflowViewSet):
    queryset = CumulativeSnapshot.objects.all()
    serializer_class = SnapshotSerializer
    lookup_field = "snapshot_id"

    @action(detail=True, methods=["get"])
    def export(self, request, snapshot_id=None):
        snapshot = self.get_object()
        return Response({**self.get_serializer(snapshot).data, "items": snapshot.items})
