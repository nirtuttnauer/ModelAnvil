"""Tenant-scoped REST APIs for Model, ModelVersion, TokenizerVersion, and Evaluation registries."""
from __future__ import annotations

from modelanvil.runners.evidence import evidence, training_evidence, model_evidence, evaluation_evidence, release_evidence

from django.db import IntegrityError, transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.runners.models import (
    EvaluationCaseResult,
    EvaluationMetric,
    EvaluationRun,
    EvaluationSuite,
    EvaluationSuiteVersion,
    Model,
    ModelVersion,
    TokenizerVersion,
)


class TokenizerVersionSerializer(serializers.ModelSerializer):
    vocabulary_size = serializers.IntegerField(min_value=1, max_value=1000000, required=False)
    revision_no = serializers.IntegerField(min_value=1, required=False)

    def validate_special_tokens(self, value):
        if not isinstance(value, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items()):
            raise serializers.ValidationError('Special tokens must be an object mapping names to strings.')
        return value

    def validate_compatibility(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Compatibility must be a JSON object.')
        return value

    class Meta:
        model = TokenizerVersion
        fields = (
            "id", "tokenizer_id", "name", "revision_no", "vocabulary_size",
            "special_tokens", "chat_template", "compatibility", "configuration_digest", "artifact_manifest_id", "created_at"
        )
        read_only_fields = ("id", "tokenizer_id", "created_at")


class TokenizerVersionViewSet(TenantScopedViewSet):
    queryset = TokenizerVersion.objects.all()
    serializer_class = TokenizerVersionSerializer
    lookup_field = "tokenizer_id"


class ModelSerializer(serializers.ModelSerializer):
    def validate_intended_tasks(self, value):
        if not isinstance(value, list) or len(value) > 50 or any(not isinstance(task, str) or not task.strip() for task in value):
            raise serializers.ValidationError('Intended tasks must be a list of up to 50 nonempty task names.')
        return value

    class Meta:
        model = Model
        fields = ("id", "model_id", "name", "description", "intended_tasks", "created_at", "updated_at")
        read_only_fields = ("id", "model_id", "created_at", "updated_at")


class ModelViewSet(TenantScopedViewSet):
    queryset = Model.objects.all()
    serializer_class = ModelSerializer
    lookup_field = "model_id"


class ModelVersionSerializer(serializers.ModelSerializer):
    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        return model_evidence(obj)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["recorded_state"] = data["state"]
        if data["state"] in ("ready", "qualified") and not model_evidence(instance)["production_qualified"]:
            data["state"] = ModelVersion.State.DRAFT
        return data


    model_name = serializers.CharField(source="model.name", read_only=True)

    def validate_state(self, value):
        if value == ModelVersion.State.QUALIFIED:
            raise serializers.ValidationError("Production qualification requires runtime evidence; metadata cannot qualify a model.")
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from modelanvil.identity.models import get_accessible_queryset
        if "model" in self.fields:
            self.fields["model"].queryset = get_accessible_queryset(Model)
        if "tokenizer" in self.fields:
            self.fields["tokenizer"].queryset = get_accessible_queryset(TokenizerVersion)

    class Meta:
        model = ModelVersion
        fields = (
            "execution_evidence",
            "id", "model_version_id", "project", "model", "model_name", "revision_no",
            "architecture_ref", "artifact_manifest_id", "tokenizer", "state", "parameters_count",
            "license_evidence", "metadata", "created_at", "updated_at"
        )
        read_only_fields = ("id", "model_version_id", "model_name", "created_at", "updated_at")


class ModelVersionViewSet(TenantScopedViewSet):
    queryset = ModelVersion.objects.select_related("model", "tokenizer")
    serializer_class = ModelVersionSerializer
    lookup_field = "model_version_id"

    @action(detail=False, methods=['post'], url_path='initialize-cpu')
    def initialize_cpu(self, request):
        from modelanvil.core.tenancy import get_active_project
        from modelanvil.runners.local_execution import initialize_character_base
        name = serializers.CharField(max_length=180, allow_blank=False).run_validation(request.data.get('name'))
        seed = serializers.IntegerField(min_value=0, max_value=2147483647).run_validation(request.data.get('seed', 42))
        try:
            model, tokenizer, version = initialize_character_base(tenant=get_active_tenant(), project=get_active_project(), name=name, seed=seed)
        except ValueError as exc:
            raise serializers.ValidationError({'initialization': str(exc)}) from exc
        except IntegrityError as exc:
            raise serializers.ValidationError({'name': 'A model or tokenizer with this name already exists; choose a different name.'}) from exc
        return Response({'model': ModelSerializer(model).data, 'tokenizer': TokenizerVersionSerializer(tokenizer).data, 'model_version': ModelVersionSerializer(version).data, 'execution_evidence': evidence('configuration_only', 'Untrained bounded CPU character weights initialized from the recorded seed.')}, status=201)

    def perform_create(self, serializer):
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        model = serializer.validated_data["model"]
        tokenizer = serializer.validated_data.get("tokenizer")
        active_project = get_active_project() or getattr(model, "project_id", None)
        if not check_resource_access(model, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        if tokenizer and not check_resource_access(tokenizer, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        kwargs = {"tenant_id": get_active_tenant()}
        if active_project:
            kwargs["project_id"] = active_project
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        model = serializer.validated_data.get("model", serializer.instance.model)
        tokenizer = serializer.validated_data.get("tokenizer", serializer.instance.tokenizer)
        active_project = get_active_project() or getattr(serializer.instance, "project_id", None) or getattr(model, "project_id", None)
        if not check_resource_access(model, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        if tokenizer and not check_resource_access(tokenizer, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        serializer.save()


class EvaluationSuiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationSuite
        fields = ("id", "suite_id", "name", "description", "created_at", "updated_at")
        read_only_fields = ("id", "suite_id", "created_at", "updated_at")


class EvaluationSuiteViewSet(TenantScopedViewSet):
    queryset = EvaluationSuite.objects.all()
    serializer_class = EvaluationSuiteSerializer
    lookup_field = "suite_id"

    @action(detail=False, methods=['post'], url_path='register-cpu')
    def register_cpu(self, request):
        """Validate before atomically registering a logical suite and its first pin."""
        from modelanvil.core.tenancy import get_active_project
        from modelanvil.runners.eval_executor import validate_local_suite
        name = serializers.CharField(max_length=200).run_validation(request.data.get('name'))
        cases = request.data.get('cases')
        scorer = request.data.get('scorer_type', 'exact_match')
        config = request.data.get('scorer_config', {})
        try:
            validate_local_suite(cases, scorer, config)
        except ValueError as exc:
            raise serializers.ValidationError({'cases': str(exc)}) from exc
        try:
            with transaction.atomic():
                suite = EvaluationSuite.objects.create(tenant_id=get_active_tenant(), project_id=get_active_project(), name=name)
                version = EvaluationSuiteVersion.objects.create(tenant_id=suite.tenant_id, project_id=suite.project_id, suite=suite, cases=cases, scorer_type=scorer, scorer_config=config)
        except IntegrityError as exc:
            raise serializers.ValidationError({'name': 'An evaluation suite with this name already exists.'}) from exc
        return Response(EvaluationSuiteVersionSerializer(version).data, status=201)


class EvaluationSuiteVersionSerializer(serializers.ModelSerializer):
    cases = serializers.JSONField(write_only=True)
    revision_no = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs):
        from modelanvil.runners.eval_executor import validate_local_suite
        try:
            validate_local_suite(attrs.get('cases', []), attrs.get('scorer_type', 'exact_match'), attrs.get('scorer_config', {}))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return attrs

    suite_name = serializers.CharField(source="suite.name", read_only=True)

    class Meta:
        model = EvaluationSuiteVersion
        fields = ("id", "suite_version_id", "suite", "suite_name", "revision_no", "cases", "cases_count", "scorer_type", "scorer_config", "protected_role", "created_at")
        read_only_fields = ("id", "suite_version_id", "suite_name", "cases_count", "created_at")


class EvaluationSuiteVersionViewSet(TenantScopedViewSet):
    queryset = EvaluationSuiteVersion.objects.select_related("suite")
    serializer_class = EvaluationSuiteVersionSerializer
    lookup_field = "suite_version_id"
    http_method_names = ["get", "post", "head", "options"]

    def perform_create(self, serializer):
        from modelanvil.core.tenancy import get_active_project
        suite = serializer.validated_data["suite"]
        serializer.save(tenant_id=get_active_tenant(), project_id=get_active_project() or suite.project_id)


class EvaluationMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationMetric
        fields = ("key", "slice_name", "value", "sample_count", "uncertainty_interval")


class EvaluationRunSerializer(serializers.ModelSerializer):
    baseline_metrics = serializers.JSONField(source='protocol_ref.baseline_metrics', read_only=True, default=list)
    protocol_ref = serializers.JSONField(read_only=True)

    def validate(self, attrs):
        if self.instance:
            if self.instance.status != EvaluationRun.Status.PENDING:
                raise serializers.ValidationError('Executed evaluation records are immutable; create a new run.')
            from modelanvil.identity.models import check_resource_access
            project = self.instance.project_id
            for field in ('suite_version', 'candidate_model_version', 'baseline_model_version'):
                resource = attrs.get(field, getattr(self.instance, field))
                if resource and not check_resource_access(resource, project, get_active_tenant()):
                    raise serializers.ValidationError({field: 'Resource is unavailable in the evaluation project.'})
            if 'project' in attrs and getattr(attrs['project'], 'pk', None) != project:
                raise serializers.ValidationError({'project': 'An evaluation cannot move between projects.'})
        return attrs

    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        return evaluation_evidence(obj)

    metrics = EvaluationMetricSerializer(many=True, read_only=True)
    # EvaluationRun currently records creation and completion, not execution start.
    started_at = serializers.DateTimeField(read_only=True, default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from modelanvil.identity.models import get_accessible_queryset
        if "suite_version" in self.fields:
            self.fields["suite_version"].queryset = get_accessible_queryset(EvaluationSuiteVersion)
        if "candidate_model_version" in self.fields:
            self.fields["candidate_model_version"].queryset = get_accessible_queryset(ModelVersion)
        if "baseline_model_version" in self.fields:
            self.fields["baseline_model_version"].queryset = get_accessible_queryset(ModelVersion)

    class Meta:
        model = EvaluationRun
        fields = (
            "execution_evidence",
            "run_id", "project", "suite_version", "candidate_model_version",
            "baseline_model_version", "status", "metrics", "baseline_metrics", "protocol_ref", "created_at", "started_at", "completed_at"
        )
        read_only_fields = ("run_id", "status", "metrics", "created_at", "started_at", "completed_at")


class EvaluationRunViewSet(TenantScopedViewSet):
    queryset = EvaluationRun.objects.prefetch_related("metrics")
    serializer_class = EvaluationRunSerializer
    lookup_field = "run_id"

    def perform_create(self, serializer):
        from modelanvil.identity.models import check_resource_access
        from modelanvil.core.tenancy import get_active_project
        suite_version = serializer.validated_data["suite_version"]
        cand = serializer.validated_data["candidate_model_version"]
        base = serializer.validated_data.get("baseline_model_version")
        active_project = get_active_project() or getattr(serializer.validated_data.get("project"), "pk", None) or getattr(cand, "project_id", None)
        if not check_resource_access(suite_version, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        if not check_resource_access(cand, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        if base and not check_resource_access(base, active_project, get_active_tenant()):
            from rest_framework.exceptions import NotFound
            raise NotFound()
        kwargs = {"tenant_id": get_active_tenant()}
        if active_project:
            kwargs["project_id"] = active_project
        serializer.save(**kwargs)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def execute(self, request, run_id=None):
        from modelanvil.core.tenancy import get_active_project
        from modelanvil.runners.eval_executor import execute_evaluation_run, validate_local_suite
        from modelanvil.runners.local_execution import load_character_bundle
        from modelanvil.runners.training.engine import TrainingEngine
        run = self.get_queryset().select_for_update().get(pk=self.get_object().pk)
        if run.status == EvaluationRun.Status.COMPLETED:
            return Response(self.get_serializer(run).data)
        if run.status != EvaluationRun.Status.PENDING:
            raise serializers.ValidationError('Only a pending evaluation can be executed.')
        max_tokens = serializers.IntegerField(min_value=1, max_value=32).run_validation(request.data.get('max_tokens', 8))
        try:
            validate_local_suite(run.suite_version.cases, run.suite_version.scorer_type, run.suite_version.scorer_config)
            tenant, project = get_active_tenant(), get_active_project() or run.project_id
            from modelanvil.identity.models import check_resource_access
            if not check_resource_access(run.suite_version, project, tenant):
                raise ValueError('Evaluation suite is unavailable in this project.')
            candidate, candidate_artifact, verification = load_character_bundle(run.candidate_model_version, tenant=tenant, project=project)
            baseline_runner = None
            pins = {'candidate_artifact_id': str(candidate_artifact.artifact_id), 'candidate_bundle_sha256': candidate_artifact.sha256, 'candidate_weights_sha256': verification['weights_sha256'], 'suite_version_id': str(run.suite_version.suite_version_id)}
            if run.baseline_model_version_id:
                baseline, baseline_artifact, baseline_verification = load_character_bundle(run.baseline_model_version, tenant=tenant, project=project)
                pins.update(baseline_artifact_id=str(baseline_artifact.artifact_id), baseline_bundle_sha256=baseline_artifact.sha256, baseline_weights_sha256=baseline_verification['weights_sha256'])
                baseline_runner = lambda prompt, params: TrainingEngine.generate_candidate_completion(baseline, prompt, params['max_tokens'])['completion']
            run.protocol_ref = {'max_tokens': max_tokens, 'decoding': 'greedy', 'pins': pins, 'execution_evidence': {'level': 'integrated_execution', 'source': 'Actual bounded local CPU character inference from checksum-verified committed weight bundles; production qualification unavailable.'}}
            execute_evaluation_run(run, lambda prompt, params: TrainingEngine.generate_candidate_completion(candidate, prompt, params['max_tokens'])['completion'], baseline_runner_fn=baseline_runner, decoding_params={'max_tokens': max_tokens})
        except (ValueError, TypeError, KeyError) as exc:
            raise serializers.ValidationError({'execution': str(exc)}) from exc
        run.refresh_from_db()
        return Response(self.get_serializer(run).data)

    def destroy(self, request, *args, **kwargs):
        if self.get_object().status != EvaluationRun.Status.PENDING:
            raise serializers.ValidationError('Executed evaluation records retain their case and artifact provenance.')
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["get"])
    def cases(self, request, run_id=None):
        results = self.get_object().case_results.filter(tenant_id=get_active_tenant()).select_related('run')
        page = self.paginate_queryset(results)
        return self.get_paginated_response(EvaluationCaseResultSerializer(page, many=True).data)

    @action(detail=False, methods=["get"])
    def leaderboard(self, request):
        """Aggregate model performance leaderboard across completed runs."""
        runs = self.get_queryset().filter(status=EvaluationRun.Status.COMPLETED)
        leaderboard_data = []
        for r in runs:
            metrics_summary = {m.key: m.value for m in r.metrics.filter(slice_name="all")}
            leaderboard_data.append({
                "run_id": str(r.run_id),
                "model_version_id": str(r.candidate_model_version_id),
                "metrics": metrics_summary,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            })
        return Response({"leaderboard": leaderboard_data})


class EvaluationCaseResultSerializer(serializers.ModelSerializer):
    baseline_output = serializers.SerializerMethodField()
    baseline_score = serializers.SerializerMethodField()

    def _baseline(self, obj):
        return next((result for result in obj.run.protocol_ref.get('baseline_results', []) if result['case_id'] == obj.case_id), {})

    def get_baseline_output(self, obj):
        return self._baseline(obj).get('candidate_output')

    def get_baseline_score(self, obj):
        return self._baseline(obj).get('score')

    class Meta:
        model = EvaluationCaseResult
        fields = ("result_id", "case_id", "input_prompt", "candidate_output", "expected_output", "score", "passed", "failure_reason", "slice_name", "baseline_output", "baseline_score")
