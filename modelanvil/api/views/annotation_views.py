"""Human labeling workflows. No heuristic inference or registry-only training is executed here."""
import hashlib
import json
import uuid

from django.db import transaction
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
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
from modelanvil.identity.models import check_resource_access, get_accessible_queryset, role_at_least, Role, ApiKey
from modelanvil.runners.models import ModelVersion


def audit(request, action_name, resource, resource_id, **details):
    record_audit(action_name, resource, resource_id,
                 actor_id=request.modelanvil_actor_id,
                 actor_kind=request.modelanvil_actor_kind, input_snapshot=details)


class ReadWorkflowViewSet(TenantScopedViewSet):
    # Reviewed history and snapshots are immutable through this API.
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        from modelanvil.annotation.feedback import hidden_campaigns
        hidden=hidden_campaigns(get_active_tenant())
        if qs.model == LabelingCampaign:
            return qs.exclude(pk__in=hidden)
        if hasattr(qs.model, 'campaign'):
            return qs.filter(campaign__in=get_accessible_queryset(LabelingCampaign).exclude(pk__in=hidden))
        return qs

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
    training_run_id = serializers.UUIDField(source='training_run.run_id', read_only=True, allow_null=True)
    evaluation_run_id = serializers.UUIDField(source='evaluation_run.run_id', read_only=True, allow_null=True)
    dataset_revision_id = serializers.UUIDField(source='dataset_revision.revision_id', read_only=True, allow_null=True)
    class Meta:
        model = CumulativeSnapshot
        fields = ("snapshot_id", "cycle_no", "item_count", "manifest_digest", "created_at", "dataset_revision_id", "training_run_id", "evaluation_run_id", "qualification")


class BatchSerializer(serializers.ModelSerializer):
    drafting_model_id = serializers.UUIDField(source="assigned_drafting_model.model_version_id", read_only=True, allow_null=True)
    reviewed_count = serializers.SerializerMethodField()

    def get_reviewed_count(self, batch):
        return batch.tasks.filter(records__isnull=False).distinct().count()

    class Meta:
        model = CampaignBatch
        fields = ("batch_id", "cycle_no", "status", "sample_count", "reviewed_count", "approved_count",
                  "snapshot_manifest_digest", "drafting_model_id", "draft_configuration", "created_at")


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
    cycle = serializers.DictField(required=False)
    draft_prompt = serializers.CharField(max_length=4000, default="{text}\n", trim_whitespace=False)
    source_revision = serializers.UUIDField(required=False, allow_null=True)
    audit_sample_refs = serializers.ListField(child=serializers.CharField(max_length=128), default=list, max_length=10000)

    def validate(self, data):
        if data['kind'] in ('ner_span', 'rubric_scoring'):
            raise ValidationError('Structured span and rubric campaigns require a validated editor; these schemas are currently unsupported.')
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
        data["source_configuration"] = {}
        if data.get('source_revision') and data['kind'] == 'preference_ranking':
            raise ValidationError({'source_revision': 'Preference ranking requires manually imported samples with both candidate responses.'})
        if data.get('source_revision'):
            from modelanvil.annotation.publication import source_configuration
            try: data['source_configuration'] = source_configuration(data['source_revision'], data['audit_sample_refs'])
            except ValueError as exc: raise ValidationError({'source_revision': str(exc)}) from exc
        if data.get('cycle') is not None:
            from modelanvil.annotation.cycles import prepare_configuration
            data['cycle'] = prepare_configuration(data['cycle'], data['source_configuration'], data['budget_limit_dollars'], data['kind'])
            if model is not None and str(model.model_version_id) != data['cycle']['base_model_version']:
                raise ValidationError('The initial drafting model and cycle baseline must be the same pinned version.')
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
            configuration={"audit_sample_refs": data["audit_sample_refs"], "draft_source": "imported", "draft_prompt": data["draft_prompt"], **data["source_configuration"], **({"cycle": data["cycle"]} if "cycle" in data else {})},
        )
        audit(request, "create", "labeling_campaign", campaign.campaign_id)
        return Response(self.get_serializer(campaign).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def lifecycle(self, request, campaign_id=None):
        campaign = self.get_queryset().select_for_update(of=("self",)).get(pk=self.get_object().pk)
        transition = request.data.get("transition")
        target = {("active", "pause"): "paused", ("paused", "resume"): "active", ("active", "cancel"): "cancelled", ("paused", "cancel"): "cancelled"}.get((campaign.status, transition))
        if target is None:
            raise Conflict("This campaign cannot make that transition.")
        campaign.status = target
        campaign.save(update_fields=["status", "updated_at"])
        if transition in ('pause', 'cancel') and campaign.configuration.get('cycle'):
            from modelanvil.annotation.cycles import stop_jobs
            stop_jobs(campaign)
        audit(request, "update", "labeling_campaign", campaign.campaign_id, transition=transition)
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def advance(self, request, campaign_id=None):
        if request.data:
            raise ValidationError("Cycle advancement uses the campaign's pinned configuration; submit an empty object.")
        campaign = self.get_queryset().select_for_update(of=('self',)).get(pk=self.get_object().pk)
        from modelanvil.annotation.cycles import advance
        advance(campaign)
        campaign.refresh_from_db()
        audit(request, 'update', 'labeling_cycle', campaign.campaign_id)
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def rollback(self, request, campaign_id=None):
        if set(request.data) != {'model_version_id'}:
            raise ValidationError('Submit only the prior qualified model version.')
        campaign = self.get_queryset().select_for_update(of=('self',)).get(pk=self.get_object().pk)
        config = campaign.configuration.get('cycle')
        if not config or campaign.status not in ('active', 'paused', 'completed'):
            raise Conflict('Rollback requires an active, paused or completed real cycle.')
        target = str(serializers.UUIDField().run_validation(request.data['model_version_id']))
        allowed = {config['base_model_version']}
        allowed.update(s.qualification.get('candidate_model') for s in campaign.snapshots.all() if s.qualification.get('decision') == 'promoted')
        model = get_accessible_queryset(ModelVersion).filter(model_version_id=target).first()
        if target not in allowed or model is None:
            raise ValidationError('Select the original baseline or a previously promoted model in this campaign.')
        from modelanvil.annotation.cycles import stop_jobs
        stop_jobs(campaign)
        for snapshot in campaign.snapshots.filter(training_run__isnull=False):
            if not snapshot.qualification:
                snapshot.qualification = {'decision': 'rejected', 'reason': 'Superseded by explicit rollback; labels and run history retained.'}
                snapshot.save(update_fields=['qualification', 'updated_at'])
        campaign.active_drafting_model = model
        campaign.save(update_fields=['active_drafting_model', 'updated_at'])
        audit(request, 'update', 'labeling_rollback', campaign.campaign_id, model_version_id=target)
        campaign.refresh_from_db()
        return Response(self.get_serializer(campaign).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def batches(self, request, campaign_id=None):
        campaign = self.get_queryset().select_for_update(of=("self",)).get(pk=self.get_object().pk)
        if campaign.status != "active" or campaign.current_cycle >= campaign.max_cycles:
            raise Conflict("The campaign must be active and have a remaining cycle.")
        if campaign.configuration.get('cycle') and any(not snap.qualification for snap in campaign.snapshots.filter(training_run__isnull=False)):
            raise Conflict('Finish or explicitly roll back the preceding training/qualification cycle first.')
        if campaign.batches.exclude(status="closed").exists():
            raise Conflict("Close the current batch before starting another cycle.")
        if campaign.configuration.get('source_revision'):
            if request.data.get('samples'):
                raise ValidationError('Pinned-source campaigns select eligible samples from their source revision.')
            from modelanvil.annotation.publication import select_source_samples
            limit = serializers.IntegerField(min_value=1, max_value=500).run_validation(request.data.get('limit', 100))
            try: samples = select_source_samples(campaign, limit)
            except ValueError as exc: raise ValidationError({'source': str(exc)}) from exc
        else:
            ser = SamplesSerializer(data=request.data)
            ser.is_valid(raise_exception=True)
            samples = ser.validated_data['samples']
        for sample in samples:
            # Match publication's field precedence so an unusable earlier field cannot mask a valid input.
            source = sample.get('text', sample.get('prompt', sample.get('input')))
            if campaign.label_schema.kind != 'preference_ranking' and (not isinstance(source, str) or not source.strip()):
                raise ValidationError({'samples': f'Sample {sample["id"]} requires nonempty text, prompt, or input; the first supplied field is used.'})
            if campaign.label_schema.kind == 'preference_ranking' and not all(
                isinstance(sample.get(key), str) and sample[key].strip() for key in ('candidate_a', 'candidate_b')
            ):
                raise ValidationError({'samples': f'Sample {sample["id"]} requires nonempty candidate_a and candidate_b responses.'})
        audit_refs = set(campaign.configuration.get("audit_sample_refs", []))
        seen = set(campaign.tasks.values_list("sample_ref", flat=True))
        fingerprints = {sample_digest(c) for c in campaign.tasks.values_list("content", flat=True)}
        for sample in samples:
            ref = sample["id"]
            fingerprint = sample_digest(sample)
            if ref in seen or fingerprint in fingerprints:
                raise ValidationError({"samples": f"Duplicate or previously used sample: {ref}."})
            if ref in audit_refs or sample.get("protected") or any(
                str(sample.get(key, "")).strip().lower() in ("audit", "test", "validation", "val", "evaluation", "eval", "protected_eval", "held_out")
                for key in ("split", "assigned_split")
            ):
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
            if not any(isinstance(sample.get(key), str) and sample[key].strip() for key in ("text", "prompt", "input", "candidate_a")):
                raise ValidationError("Every sample needs nonempty text, prompt, input, or candidate_a content.")
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
    def to_representation(self, record):
        data = super().to_representation(record)
        if self.context.get('blind') or (self.context.get('request') and self.context['request'].query_params.get('blind') == '1'):
            data.update(human_label={}, original_prediction={}, preference_choice='')
        return data

    class Meta:
        model = AnnotationRecord
        fields = ("record_id", "revision_no", "reviewer_id", "original_prediction", "human_label", "decision", "preference_choice", "is_blind_review", "is_adjudication", "created_at")


class TaskSerializer(serializers.ModelSerializer):
    def to_representation(self, task):
        from copy import deepcopy
        data = super().to_representation(task)
        request = self.context.get('request')
        if self.context.get('blind') or (request and request.query_params.get('blind') == '1'):
            data['content'] = deepcopy(data['content']); data['content'].pop('draft_prediction', None); data['content'].pop('arena_vote', None); data['content'].pop('comparison_origin', None)
            if data['latest_review']:
                data['latest_review'] = {**data['latest_review'], 'human_label': {}, 'original_prediction': {}}
        return data

    latest_review = serializers.SerializerMethodField()

    def get_latest_review(self, task):
        record = task.records.order_by("-revision_no").first()
        return RecordSerializer(record, context=self.context).data if record else None

    class Meta:
        model = AnnotationTask
        fields = ("task_id", "sample_ref", "content", "status", "latest_review", "assigned_reviewer", "needs_adjudication")


class ReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=AnnotationRecord.Decision.choices)
    human_label = serializers.DictField(default=dict)
    expected_revision = serializers.IntegerField(min_value=1)
    blind_review = serializers.BooleanField(default=False)
    adjudicate = serializers.BooleanField(default=False)


class BatchViewSet(ReadWorkflowViewSet):
    queryset = CampaignBatch.objects.select_related("campaign", "campaign__label_schema")
    serializer_class = BatchSerializer
    lookup_field = "batch_id"

    @action(detail=True, methods=["get"])
    def tasks(self, request, batch_id=None):
        tasks = self.get_object().tasks.filter(tenant_id=get_active_tenant())
        page = self.paginate_queryset(tasks)
        return self.get_paginated_response(TaskSerializer(page, many=True, context={'request': request}).data)

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
        if batch.tasks.filter(needs_adjudication=True).exists():
            raise Conflict('Resolve escalated or conflicting reviews before closing this batch.')
        snapshot = CampaignEngine().close_batch(batch)
        from modelanvil.annotation.publication import publish_snapshot
        try: publish_snapshot(snapshot)
        except ValueError as exc: raise ValidationError({'publication': str(exc)}) from exc
        if campaign.configuration.get('cycle'):
            from modelanvil.annotation.cycles import dispatch_training
            dispatch_training(campaign, snapshot, request)
        campaign.refresh_from_db()
        if campaign.current_cycle >= campaign.max_cycles and not campaign.configuration.get('cycle'):
            campaign.status = "completed"
            campaign.save(update_fields=["status", "updated_at"])
        audit(request, "create", "annotation_snapshot", snapshot.snapshot_id, digest=snapshot.manifest_digest)
        return Response(SnapshotSerializer(snapshot).data)


class TaskViewSet(ReadWorkflowViewSet):
    action_write_roles = {"review": Role.REVIEWER, "escalate": Role.REVIEWER}
    queryset = AnnotationTask.objects.select_related("campaign", "campaign__label_schema", "batch")
    serializer_class = TaskSerializer
    lookup_field = "task_id"

    @action(detail=True, methods=["get"])
    def history(self, request, task_id=None):
        page = self.paginate_queryset(self.get_object().records.filter(tenant_id=get_active_tenant()))
        return self.get_paginated_response(RecordSerializer(page, many=True, context={'request': request}).data)

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
        from modelanvil.annotation.feedback import require_campaign_live
        try:feedback=require_campaign_live(campaign)
        except ValueError as exc:raise ValidationError(str(exc)) from exc
        if feedback and data['decision'] in ('corrected','accepted_without_edit'):
            if data['decision']!='corrected' or data['human_label'].get('label')==task.content.get('draft_prediction',{}).get('predicted_label'):
                raise ValidationError('Supply an independently reviewed correction to the failed prediction.')
        principal = f'{request.modelanvil_actor_kind}:{request.modelanvil_actor_id}'
        adjudicate = data.pop('adjudicate')
        blind = data.pop('blind_review') or request.query_params.get('blind') == '1'
        if adjudicate and not role_at_least(request.modelanvil_role, Role.MANAGER):
            raise PermissionDenied('Adjudication requires a manager.')
        if task.needs_adjudication and not adjudicate:
            raise Conflict('This task requires an authorized adjudication.')
        if task.assigned_reviewer and task.assigned_reviewer != principal and not adjudicate:
            raise PermissionDenied('This task is assigned to another reviewer.')
        if blind and data['decision'] == 'accepted_without_edit':
            raise ValidationError('Blind review requires an independently supplied label.')
        if campaign.label_schema.kind in ('ner_span', 'rubric_scoring'):
            raise ValidationError('Structured span and rubric review is unsupported until validated editors are available.')
        if data["decision"] in ("corrected", "accepted_without_edit"):
            validate_label(campaign.label_schema, data["human_label"])
            prediction = task.content.get("draft_prediction", {})
            if data["decision"] == "accepted_without_edit" and data["human_label"].get("label") != prediction.get("predicted_label"):
                raise ValidationError({"decision": "Accept requires an unchanged imported prediction. Use Save label for manual work."})
        record = CampaignEngine().submit_review(task=task,
            reviewer_id=f'{request.modelanvil_actor_kind}:{request.modelanvil_actor_id}',
            **data, preference_choice=data["human_label"].get("label", "") if campaign.label_schema.kind == "preference_ranking" else "")
        record.is_blind_review, record.is_adjudication = blind, adjudicate
        record.save(update_fields=['is_blind_review', 'is_adjudication', 'updated_at'])
        disagreement = bool(latest and latest.reviewer_id != principal and latest.human_label != record.human_label
            and latest.decision in ('corrected', 'accepted_without_edit') and record.decision in ('corrected', 'accepted_without_edit'))
        task.needs_adjudication = False if adjudicate else disagreement
        if adjudicate: task.status = AnnotationTask.Status.ADJUDICATED
        task.save(update_fields=['needs_adjudication', 'status', 'updated_at'])
        audit(request, "create", "annotation_review", record.record_id, task_id=str(task.task_id), decision=record.decision)
        return Response(TaskSerializer(task, context={'request': request, 'blind': blind}).data, status=201)

    def _locked_task(self):
        found = self.get_object()
        LabelingCampaign.objects.select_for_update().get(pk=found.campaign_id)
        CampaignBatch.objects.select_for_update().get(pk=found.batch_id)
        return AnnotationTask.objects.select_for_update().select_related('campaign', 'batch').get(pk=found.pk)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def escalate(self, request, task_id=None):
        task = self._locked_task()
        if task.batch.status == 'closed' or task.campaign.status != 'active':
            raise Conflict('Only an active open review can be escalated.')
        reason = serializers.CharField(max_length=2000).run_validation(request.data.get('reason'))
        task.needs_adjudication = True
        task.save(update_fields=['needs_adjudication', 'updated_at'])
        audit(request, 'annotation.escalate', 'annotation_task', task.task_id, reason=reason)
        return Response(self.get_serializer(task).data)

    @action(detail=True, methods=['get', 'post'])
    @transaction.atomic
    def assignment(self, request, task_id=None):
        task = self._locked_task()
        if not role_at_least(request.modelanvil_role, Role.MANAGER):
            raise PermissionDenied('Reviewer assignment requires a manager.')
        keys = ApiKey.objects.filter(tenant_id=get_active_tenant(), is_active=True)
        eligible = [key for key in keys if not key.is_expired() and role_at_least(key.role, Role.REVIEWER) and (not key.project_id or key.project_id == task.campaign.project_id)]
        if request.method == 'GET':
            return Response({'reviewers': [{'principal_id': f'api_key:{key.pk}', 'name': key.name} for key in eligible]})
        if task.batch.status == 'closed' or task.campaign.status != 'active':
            raise Conflict('Only active open review assignments can change.')
        selected = serializers.CharField(max_length=128, allow_blank=True).run_validation(request.data.get('reviewer', ''))
        if selected and selected not in [f'api_key:{key.pk}' for key in eligible]:
            raise ValidationError('Select an authorized active reviewer in this project.')
        task.assigned_reviewer = selected
        task.save(update_fields=['assigned_reviewer', 'updated_at'])
        audit(request, 'annotation.assign', 'annotation_task', task.task_id, reviewer=selected)
        return Response(self.get_serializer(task).data)


class SnapshotViewSet(ReadWorkflowViewSet):
    queryset = CumulativeSnapshot.objects.all()
    serializer_class = SnapshotSerializer
    lookup_field = "snapshot_id"

    @action(detail=True, methods=["get"])
    def export(self, request, snapshot_id=None):
        snapshot = self.get_object()
        return Response({**self.get_serializer(snapshot).data, "items": snapshot.items})
