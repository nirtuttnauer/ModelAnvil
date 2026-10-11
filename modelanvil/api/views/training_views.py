"""Views for TrainingRuns and TrainingCheckpoints."""
from __future__ import annotations

from modelanvil.runners.evidence import evidence, training_evidence, model_evidence, evaluation_evidence, release_evidence

import hashlib
import json
import uuid
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.tenancy import get_active_project
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role, get_accessible_queryset
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from rest_framework import serializers

from modelanvil.core.models import IdempotencyKey, record_audit
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import Project
from modelanvil.runners.models import (
    AlignmentCheckpoint,
    AlignmentRun,
    ModelVersion,
    TokenizerVersion,
    TrainingCheckpoint,
    TrainingRun,
    RunnerManifest,
    validate_model_tokenizer_compatibility,
)
from modelanvil.runners.training.engine import TrainingEngine
from modelanvil.artifacts.models import Artifact


class TrainingCheckpointSerializer(serializers.ModelSerializer):
    weights_manifest = serializers.SerializerMethodField()

    def get_weights_manifest(self, obj):
        state = obj.weights_manifest or {}
        # Polling should carry tensor summaries, not every inline weight payload.
        weights = state.get('weights', state)
        return {key: value for key, value in weights.items() if key != 'data_b64'}

    class Meta:
        model = TrainingCheckpoint
        fields = (
            "checkpoint_id", "training_run", "step", "state_digest",
            "weights_manifest", "metrics", "is_valid", "created_at"
        )
        read_only_fields = ("checkpoint_id", "created_at")


class TrainingRunSerializer(serializers.ModelSerializer):
    job = serializers.UUIDField(source='job.job_id', read_only=True, allow_null=True)
    execution_evidence = serializers.SerializerMethodField()
    execution_mode = serializers.ChoiceField(choices=['worker', 'simulation'], default='worker', write_only=True)
    runner_manifest = serializers.PrimaryKeyRelatedField(queryset=RunnerManifest.objects.all(), required=False, write_only=True)
    runtime = serializers.JSONField(source='hardware_config', read_only=True)
    preflight_token = serializers.CharField(write_only=True, required=False, max_length=2048)

    def get_execution_evidence(self, obj):
        return training_evidence(obj)

    checkpoints = TrainingCheckpointSerializer(many=True, read_only=True)
    budget_policy_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    estimated_amount = serializers.DecimalField(max_digits=12, decimal_places=4, write_only=True, required=False, allow_null=True)

    def validate(self, attrs):
        self.validate_gpu_options(attrs)
        from modelanvil.runners.training.registry import is_worker_run
        if self.instance and is_worker_run(self.instance):
            raise serializers.ValidationError('Dispatched training configuration is immutable; launch a new run.')
        recipe = attrs.get("recipe_type", getattr(self.instance, "recipe_type", None))
        base_model = attrs.get("base_model_version", getattr(self.instance, "base_model_version", None))
        tokenizer = attrs.get("tokenizer_version", getattr(self.instance, "tokenizer_version", None))
        dataset_rev = attrs.get("dataset_revision", getattr(self.instance, "dataset_revision", None))

        if recipe != TrainingRun.RecipeType.SCRATCH_PRETRAINING:
            if not base_model:
                raise serializers.ValidationError({"base_model_version": f"Recipe '{recipe}' requires a registered base model version."})
            if tokenizer:
                validate_model_tokenizer_compatibility(base_model, tokenizer)

        if dataset_rev:
            from modelanvil.artifacts.models import DatasetRevision
            if dataset_rev.state != DatasetRevision.State.PUBLISHED:
                raise serializers.ValidationError({"dataset_revision": "Dataset revision must be in 'published' state before training dispatch."})
            if not dataset_rev.manifest_digest or len(dataset_rev.manifest_digest) != 64:
                raise serializers.ValidationError({"dataset_revision": "Dataset revision must have a valid 64-character manifest digest."})
            attrs["dataset_manifest_digest"] = dataset_rev.manifest_digest

        pool = attrs.get("pool")
        if pool and getattr(pool, "status", "active") != "active":
            raise serializers.ValidationError({"pool": "Selected worker pool is inactive."})

        return attrs

    def validate_gpu_options(self, attrs):
        from modelanvil.runners.training import hf_runtime
        base = attrs.get('base_model_version', getattr(self.instance, 'base_model_version', None))
        if base and base.architecture_ref == hf_runtime.RUNTIME_ID:
            try:
                hf_runtime.validate_options(**{name: self.initial_data[name] for name in
                    ('precision', 'adapter', 'quantization') if name in self.initial_data})
            except ValueError as exc:
                raise serializers.ValidationError({'gpu_options': str(exc)}) from exc

    class Meta:
        model = TrainingRun
        fields = (
            "execution_evidence", "execution_mode", "runner_manifest", "runtime", "preflight_token",
            "run_id", "project", "recipe_type", "base_model_version", "tokenizer_version",
            "dataset_revision", "dataset_manifest_digest", "pool", "job",
            "budget_policy_id", "estimated_amount",
            "initialization_seed", "total_steps", "current_step", "status",
            "latest_loss", "metrics_log", "output_model_version", "checkpoints",
            "created_at", "updated_at", "started_at", "completed_at"
        )
        read_only_fields = (
            "run_id", "current_step", "status", "latest_loss",
            "metrics_log", "output_model_version", "dataset_manifest_digest", "created_at", "updated_at",
            "started_at", "completed_at", "job"
        )


class TrainingPreflightSerializer(TrainingRunSerializer):
    total_steps = serializers.IntegerField(min_value=1, max_value=1000, required=False)

    def validate(self, attrs):
        # Report compatibility failures together after scoped relation/type validation.
        self.validate_gpu_options(attrs)
        return attrs


class TrainingRunViewSet(TenantScopedViewSet):
    queryset = TrainingRun.objects.all().prefetch_related("checkpoints")
    serializer_class = TrainingRunSerializer
    lookup_field = "run_id"

    def get_serializer_class(self):
        return TrainingPreflightSerializer if self.action == 'preflight' else TrainingRunSerializer

    def _preflight_report(self, attrs, *, lock_budget=False):
        from modelanvil.runners.training.preflight_report import build_preflight_report
        from modelanvil.budgets.models import BudgetPolicy
        tenant = get_active_tenant()
        project = get_active_project() or getattr(attrs.get('project'), 'pk', None) or getattr(attrs.get('base_model_version'), 'project_id', None)
        policies = BudgetPolicy.all_objects.filter(tenant_id=tenant, policy_id=attrs.get('budget_policy_id'))
        policy = (policies.select_for_update() if lock_budget else policies).first()
        report = build_preflight_report(recipe_type=attrs.get('recipe_type', 'full_sft'),
            tokenizer_version=attrs.get('tokenizer_version'), base_model_version=attrs.get('base_model_version'),
            dataset_revision=attrs.get('dataset_revision'), pool=attrs.get('pool'), runner=attrs.get('runner_manifest'),
            total_steps=attrs.get('total_steps', 100), budget_policy=policy,
            execution_mode=attrs.get('execution_mode', 'worker'), tenant=tenant, project=project)
        return report, policy

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get("project")
        return qs.filter(project_id=serializers.UUIDField().run_validation(project_id)) if project_id else qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        idempotency_key_header = (request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY") or '').strip()
        tenant_id = get_active_tenant()
        if request.data.get('execution_mode', 'worker') == 'worker' and (not idempotency_key_header or len(idempotency_key_header) > 128):
            raise serializers.ValidationError({'Idempotency-Key': 'Worker launch requires a key of 1–128 characters.'})

        if idempotency_key_header and tenant_id:
            principal = f"{getattr(request.user, 'pk', 'legacy')}:{get_active_project() or 'tenant'}"
            req_hash = hashlib.sha256(json.dumps(request.data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

            cached = IdempotencyKey.objects.filter(
                tenant_id=tenant_id,
                key=idempotency_key_header,
                principal=principal,
                http_method="POST",
                path=request.path,
            ).first()
            if cached and cached.request_hash != req_hash:
                return Response({"detail": "Idempotency key already used for a different request."}, status=status.HTTP_409_CONFLICT)
            if cached and cached.response_status:
                return Response(cached.response_body, status=cached.response_status)

            idem_obj, created = IdempotencyKey.objects.select_for_update().get_or_create(
                tenant_id=tenant_id,
                key=idempotency_key_header,
                principal=principal,
                http_method="POST",
                path=request.path,
                defaults={
                    "request_hash": req_hash,
                },
            )
            if idem_obj.request_hash != req_hash:
                return Response({'detail': 'Idempotency key already used for a different request.'}, status=409)
            if not created and idem_obj.response_status:
                return Response(idem_obj.response_body, status=idem_obj.response_status)

            response = self._perform_launch(request)
            idem_obj.response_status = response.status_code
            idem_obj.response_body = json.loads(JSONRenderer().render(response.data))
            idem_obj.completed_at = timezone.now()
            idem_obj.save(update_fields=["response_status", "response_body", "completed_at"])
            return response

        return self._perform_launch(request)

    def _perform_launch(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from modelanvil.budgets.models import BudgetReservation
        from modelanvil.jobs.models import Job
        attrs = serializer.validated_data
        proof = attrs.pop('preflight_token', None)
        mode = attrs.get('execution_mode', 'worker')
        tenant = get_active_tenant()
        project = get_active_project() or getattr(attrs.get('project'), 'pk', None) or getattr(attrs.get('base_model_version'), 'project_id', None)
        pins = None
        if mode == 'worker':
            from modelanvil.runners.training.preflight_report import verify_token
            report, policy = self._preflight_report(attrs, lock_budget=True)
            if report['status'] != 'approved':
                raise serializers.ValidationError({'preflight': [f"{c['check']}: {c['reason']} {c['corrective_action']}" for c in report['checks'] if c['blocking']]})
            if proof:
                try:
                    verify_token(proof, report, request.user.pk)
                except ValueError as exc:
                    raise serializers.ValidationError({'preflight_token': str(exc)}) from exc
            pins = report['pins']
            if attrs.get('estimated_amount') is not None and attrs['estimated_amount'] != pins['steps']:
                raise serializers.ValidationError({'estimated_amount': 'Reservation must equal the requested sample passes.'})
        budget_id = attrs.pop('budget_policy_id', None)
        attrs.pop('estimated_amount', None)
        attrs.pop('execution_mode', None)
        runner = attrs.pop('runner_manifest', None)
        if mode == 'simulation' and (attrs.get('pool') or budget_id or runner):
            raise serializers.ValidationError('Simulation cannot allocate workers or reserve compute budget.')
        run = serializer.save(tenant_id=tenant, project_id=project,
            hardware_config={'execution_mode': mode, **({'pins': pins} if pins else {})})
        if pins:
            gpu = pins.get('accelerator', {}).get('device')
            requirements = {'training_runtime': pins['contract_digest'], 'slots': 1}
            if gpu:
                requirements.update(gpu_backend=gpu['backend'], gpu_device=gpu['id'])
            job = Job.objects.create(tenant_id=tenant, pool=run.pool, name=f'Text SFT: {run.run_id}',
                payload={'type': 'qualified_training', 'run_id': str(run.run_id)},
                requirements=requirements, max_attempts=3)
            try:
                reservation = BudgetReservation.reserve(tenant_id=tenant, policy=policy,
                    job_id=job.job_id, estimated_amount=pins['steps'])
            except ValueError as exc:
                raise serializers.ValidationError({'budget_policy_id': str(exc)}) from exc
            run.job = job
            run.resource_reservation_id = reservation.reservation_id
            run.save(update_fields=['job', 'resource_reservation_id', 'updated_at'])
        out = self.get_serializer(run).data
        return Response(out, status=201, headers=self.get_success_headers(out))

    @action(detail=False, methods=['get'], url_path='runtime-contract')
    def runtime_contract(self, request):
        from modelanvil.runners.training.registry import runtime_contract
        return Response(runtime_contract(request.query_params.get('runtime')))

    @action(detail=False, methods=['post'], url_path='preflight')
    def preflight(self, request):
        """Preview encoded samples, itemized checks, an honest estimate and runtime scope (TASK-5)."""
        from modelanvil.runners.training.preflight_report import issue_token
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        report, _ = self._preflight_report(serializer.validated_data)
        report['preflight_token'] = issue_token(report, request.user.pk)
        return Response(report)

    def _worker_bundle(self, run):
        from modelanvil.runners.training.registry import checkpoint_bundle
        if run.status != TrainingRun.Status.COMPLETED:
            raise serializers.ValidationError('Wait for successful worker completion before exporting or inferring.')
        try:
            return checkpoint_bundle(run, run.checkpoints.get(step=run.total_steps))
        except (ValueError, TrainingCheckpoint.DoesNotExist) as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=True, methods=["post"], url_path="train-steps")
    def train_steps(self, request, *args, **kwargs):
        """Advance training by steps (interactive / simulator)."""
        run = self.get_object()
        from modelanvil.runners.training.registry import is_worker_run
        if is_worker_run(run):
            raise serializers.ValidationError('Worker runs advance only through the fenced worker executor.')
        steps = serializers.IntegerField(min_value=1, max_value=1000).run_validation(request.data.get('steps', 5))
        checkpoint_interval = serializers.IntegerField(min_value=1, max_value=1000).run_validation(request.data.get("checkpoint_interval", 1))
        engine = TrainingEngine()
        engine.train_steps(run, num_steps=steps, checkpoint_interval=checkpoint_interval)
        return Response(self.get_serializer(run).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="export")
    def export(self, request, *args, **kwargs):
        """Export candidate model and return bundle with verification."""
        run = self.get_object()
        engine = TrainingEngine()
        from modelanvil.runners.training.registry import is_worker_run, verify_bundle
        if is_worker_run(run):
            mv, bundle = run.output_model_version, self._worker_bundle(run)
        else:
            mv, bundle = engine.export_candidate_model(run)
        verification = verify_bundle(bundle)
        return Response({
            "model_version_id": str(mv.model_version_id),
            "bundle": bundle,
            "verification": verification,
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, *args, **kwargs):
        """Cancel an in-progress or queued training run and signal the durable worker job."""
        run = self.get_object()
        if run.status in (TrainingRun.Status.COMPLETED, TrainingRun.Status.FAILED, TrainingRun.Status.CANCELLED):
            return Response({"detail": f"Run is already in terminal state '{run.status}'."}, status=status.HTTP_400_BAD_REQUEST)

        from modelanvil.runners.training.registry import is_worker_run, finalize_job
        from modelanvil.jobs.models import Job
        if is_worker_run(run):
            job = Job.all_objects.select_for_update().get(pk=run.job_id)
            run = TrainingRun.all_objects.select_for_update().get(pk=run.pk)
            if job.status in (Job.Status.SUCCEEDED, Job.Status.FAILED, Job.Status.CANCELLED, Job.Status.INTERRUPTED):
                raise serializers.ValidationError('Job is already terminal.')
            job.desired_action = Job.DesiredAction.CANCEL
            if job.status == Job.Status.QUEUED:
                job.status = Job.Status.CANCELLED
                finalize_job(job, job.status)
            job.save(update_fields=['desired_action', 'status', 'updated_at'])
            run.refresh_from_db()
        else:
            run.status = TrainingRun.Status.CANCELLED
            run.save(update_fields=['status', 'updated_at'])
            # Cleanup old fixture jobs created before worker mode was separated.
            if run.job:
                run.job.desired_action = Job.DesiredAction.CANCEL
                run.job.save(update_fields=['desired_action', 'updated_at'])
            if run.resource_reservation_id:
                from modelanvil.budgets.models import BudgetReservation
                reservation = BudgetReservation.all_objects.filter(tenant_id=run.tenant_id,
                    reservation_id=run.resource_reservation_id, state=BudgetReservation.State.RESERVED).first()
                if reservation:
                    reservation.release()

        return Response(self.get_serializer(run).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        from modelanvil.runners.training.registry import is_worker_run
        if is_worker_run(self.get_object()):
            raise serializers.ValidationError('Worker runs retain checkpoint and accounting provenance; cancel an active run instead.')
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="infer")
    def infer(self, request, *args, **kwargs):
        """Perform external inference test on the trained candidate model checkpoint."""
        run = self.get_object()
        prompt = serializers.CharField(max_length=4096, allow_blank=True).run_validation(request.data.get("prompt", "Hello world"))
        max_tokens = serializers.IntegerField(min_value=1, max_value=32).run_validation(request.data.get("max_tokens", 8))

        engine = TrainingEngine()
        from modelanvil.runners.training.registry import is_worker_run, verify_bundle, generate_completion
        if is_worker_run(run):
            bundle = self._worker_bundle(run)
        else:
            model_version, bundle = engine.export_candidate_model(run)
        verification = verify_bundle(bundle)
        inference = generate_completion(bundle, prompt=prompt, max_new_tokens=max_tokens)

        return Response({
            "run_id": str(run.run_id),
            "verification": verification,
            "inference": inference,
        }, status=status.HTTP_200_OK)


class TrainingCheckpointViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (permissions.IsAuthenticated, TenantRBAC)
    required_role = Role.VIEWER
    queryset = TrainingCheckpoint.objects.all()
    serializer_class = TrainingCheckpointSerializer

    def get_queryset(self):
        tenant_id = get_active_tenant()
        if not tenant_id:
            return self.queryset.none()
        qs = self.queryset.filter(tenant_id=tenant_id, training_run__in=get_accessible_queryset(TrainingRun))
        run_id = self.request.query_params.get("run_id")
        if run_id:
            qs = qs.filter(training_run_id=run_id)
        return qs


class PreferencePairSerializer(serializers.Serializer):
    prompt = serializers.CharField(max_length=62, trim_whitespace=False)
    chosen = serializers.CharField(max_length=62, trim_whitespace=False)
    rejected = serializers.CharField(max_length=62, trim_whitespace=False)

    def validate(self, pair):
        if any(not value.strip() for value in pair.values()):
            raise serializers.ValidationError('Prompt and both responses must be nonempty.')
        if pair['chosen'] == pair['rejected']:
            raise serializers.ValidationError('Chosen and rejected responses must differ.')
        if len(pair['prompt']) + max(len(pair['chosen']), len(pair['rejected'])) > 62:
            raise serializers.ValidationError('Prompt plus response must fit the 62-character CPU context bound.')
        return pair


class PreferenceRegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    samples = PreferencePairSerializer(many=True, min_length=1, max_length=32)

    def validate_samples(self, pairs):
        from modelanvil.runners.alignment.execution import validate_preference_pairs
        try:
            validate_preference_pairs(pairs)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        return pairs


class AlignmentRunSerializer(serializers.ModelSerializer):
    train_dataset_artifact = serializers.SlugRelatedField(slug_field='artifact_id', required=False, allow_null=True,
        queryset=Artifact.objects.all())
    held_out_dataset_artifact = serializers.SlugRelatedField(slug_field='artifact_id', required=False, allow_null=True,
        queryset=Artifact.objects.all())
    execution_capabilities = serializers.SerializerMethodField()

    def get_execution_capabilities(self, obj):
        from modelanvil.runners.alignment.execution import alignment_capabilities
        return alignment_capabilities(obj)

    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        if obj.execution_pins:
            result = evidence('integrated_execution' if obj.current_step else 'configuration_only',
                'Bounded CPU character alignment on pinned preference bytes and model weights; no hardware or production qualification.')
            result['runtime_scope'] = 'modelanvil.cpu-character-alignment.v1'
            return result
        if obj.current_step or obj.status in (AlignmentRun.Status.COMPLETED, AlignmentRun.Status.RUNNING):
            return evidence('simulation', 'Legacy alignment fixture metrics; no verified preference weight training.')
        return evidence('configuration_only', 'Saved alignment plan; no preference weight training has executed.')

    def validate(self, attrs):
        if self.instance and (self.instance.status != AlignmentRun.Status.PENDING or self.instance.started_at or self.instance.current_step):
            raise serializers.ValidationError('Started alignment plans are immutable; create a new run.')
        algo = attrs.get("algorithm", getattr(self.instance, "algorithm", None))
        total_steps = attrs.get("total_steps", getattr(self.instance, "total_steps", 100))
        if total_steps <= 0:
            raise serializers.ValidationError({"total_steps": "Total steps must be greater than 0."})

        hyp = attrs.get("hyperparameters", getattr(self.instance, "hyperparameters", {}))
        if not isinstance(hyp, dict):
            raise serializers.ValidationError({"hyperparameters": "Hyperparameters must be a JSON object."})

        train = attrs.get('train_dataset_artifact', getattr(self.instance, 'train_dataset_artifact', None))
        held = attrs.get('held_out_dataset_artifact', getattr(self.instance, 'held_out_dataset_artifact', None))
        if train or held:
            if not train or not held:
                raise serializers.ValidationError({'preference_artifacts': 'Pin both training and held-out preference artifacts.'})
            fields = {field: attrs.get(field, getattr(self.instance, field, None)) for field in (
                'algorithm', 'policy_model_version', 'reference_model_version', 'reward_model_version',
                'train_dataset_artifact', 'held_out_dataset_artifact')}
            requested_project = attrs.get('project', getattr(self.instance, 'project', None))
            fields.update(tenant_id=get_active_tenant(), project_id=get_active_project() or getattr(requested_project, 'pk', None),
                total_steps=total_steps, hyperparameters=hyp,
                verifier_spec=attrs.get('verifier_spec', getattr(self.instance, 'verifier_spec', {})))
            from modelanvil.runners.alignment.execution import validate_alignment_inputs
            try:
                prepared = validate_alignment_inputs(AlignmentRun(**fields))
            except ValueError as exc:
                raise serializers.ValidationError({'alignment_inputs': str(exc)}) from exc
            attrs['dataset_manifest_digest'] = prepared['pins']['dataset_manifest_digest']
            attrs['held_out_validation_digest'] = prepared['pins']['held_out_validation_digest']

        data_dig = attrs.get("dataset_manifest_digest", getattr(self.instance, "dataset_manifest_digest", ""))
        held_dig = attrs.get("held_out_validation_digest", getattr(self.instance, "held_out_validation_digest", ""))

        if not data_dig or len(data_dig) != 64 or not all(c in "0123456789abcdef" for c in data_dig):
            raise serializers.ValidationError({"dataset_manifest_digest": "Must be 64 lowercase hex characters."})
        if not held_dig or len(held_dig) != 64 or not all(c in "0123456789abcdef" for c in held_dig):
            raise serializers.ValidationError({"held_out_validation_digest": "Must be 64 lowercase hex characters."})
        if data_dig == held_dig:
            raise serializers.ValidationError({"held_out_validation_digest": "Held-out validation dataset cannot match training dataset."})

        if algo == "dpo":
            ref_model = attrs.get("reference_model_version", getattr(self.instance, "reference_model_version", None))
            if not ref_model:
                raise serializers.ValidationError({"reference_model_version": "DPO requires a pinned reference model version."})
        elif algo == "ppo_rlhf":
            reward_model = attrs.get("reward_model_version", getattr(self.instance, "reward_model_version", None))
            if not reward_model:
                raise serializers.ValidationError({"reward_model_version": "PPO RLHF requires a pinned reward model version."})
        elif algo == "verifier_rl":
            verifier_spec = attrs.get("verifier_spec", getattr(self.instance, "verifier_spec", {}))
            if not verifier_spec:
                raise serializers.ValidationError({"verifier_spec": "Verifier RL requires a non-empty verifier specification."})

        policy_model = attrs.get("policy_model_version", getattr(self.instance, "policy_model_version", None))
        tenant_id = get_active_tenant()
        if policy_model and tenant_id and str(policy_model.tenant_id) != str(tenant_id):
            raise serializers.ValidationError({"policy_model_version": "Policy model version must belong to the active tenant."})

        return attrs

    class Meta:
        model = AlignmentRun
        fields = (
            "execution_evidence", "execution_capabilities",
            "run_id", "project", "algorithm", "status",
            "policy_model_version", "reference_model_version", "reward_model_version",
            "train_dataset_artifact", "held_out_dataset_artifact", "execution_pins", "resource_reservation_id",
            "verifier_spec", "dataset_manifest_digest", "held_out_validation_digest",
            "hyperparameters", "current_step", "total_steps", "latest_metrics",
            "metrics_history", "rollouts_log", "output_model_version", "stop_reason",
            "created_at", "updated_at", "started_at", "completed_at"
        )
        read_only_fields = (
            "run_id", "current_step", "status", "latest_metrics",
            "execution_pins", "resource_reservation_id", "stop_reason",
            "metrics_history", "rollouts_log", "output_model_version",
            "created_at", "updated_at", "started_at", "completed_at"
        )


class AlignmentRunViewSet(TenantScopedViewSet):
    queryset = AlignmentRun.objects.all()
    serializer_class = AlignmentRunSerializer
    lookup_field = 'run_id'

    def get_object(self):
        # Preserve older numeric detail URLs while durable links use run UUIDs.
        lookup = self.kwargs.get(self.lookup_field)
        if lookup and str(lookup).isdigit():
            from django.shortcuts import get_object_or_404
            obj = get_object_or_404(self.filter_queryset(self.get_queryset()), pk=lookup)
            self.check_object_permissions(self.request, obj)
            return obj
        return super().get_object()

    @action(detail=True, methods=['post'])
    def execute(self, request, run_id=None):
        from modelanvil.runners.alignment.execution import execute_alignment
        try:
            run = execute_alignment(self.get_object())
        except ValueError as exc:
            raise serializers.ValidationError({'execution': str(exc)}) from exc
        self._audit_execution(request, 'alignment.execute', run)
        return Response(self.get_serializer(run).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, run_id=None):
        from modelanvil.runners.alignment.execution import cancel_alignment
        try:
            run = cancel_alignment(self.get_object())
        except ValueError as exc:
            raise serializers.ValidationError({'cancellation': str(exc)}) from exc
        self._audit_execution(request, 'alignment.cancel', run)
        return Response(self.get_serializer(run).data)

    @staticmethod
    def _audit_execution(request, action_name, run):
        record_audit(action_name, 'alignment_run', run.run_id,
            actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
            input_snapshot={'status': run.status, 'algorithm': run.algorithm, 'current_step': run.current_step,
                'checkpoint_count': run.checkpoints.count(), 'runtime': run.execution_pins.get('runtime'),
                'build_digest': run.execution_pins.get('build_digest'),
                'dataset_manifest_digest': run.dataset_manifest_digest,
                'held_out_validation_digest': run.held_out_validation_digest,
                'output_model_version_id': str(run.output_model_version.model_version_id) if run.output_model_version_id else None})

    def perform_destroy(self, instance):
        if instance.status != AlignmentRun.Status.PENDING or instance.started_at or instance.current_step:
            raise serializers.ValidationError('Started alignment plans and execution results are immutable.')
        return super().perform_destroy(instance)

    @action(detail=False, methods=['get'], url_path='preference-artifacts')
    def preference_artifacts(self, request):
        from modelanvil.artifacts.models import Artifact
        artifacts = get_accessible_queryset(Artifact).filter(state=Artifact.State.COMMITTED,
            metadata__kind='alignment_preferences').order_by('-created_at', '-id')
        page = self.paginate_queryset(artifacts)
        return self.get_paginated_response([self._preference_summary(artifact) for artifact in page])

    @staticmethod
    def _preference_summary(artifact):
        return {'artifact_id': str(artifact.artifact_id), 'name': artifact.metadata.get('name', 'Preference pairs'),
            'sha256': artifact.sha256, 'byte_size': artifact.byte_size, 'row_count': artifact.metadata.get('row_count'),
            'state': artifact.state}

    @action(detail=False, methods=['post'], url_path='register-preferences')
    def register_preferences(self, request):
        import io
        from modelanvil.artifacts.models import Artifact
        from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
        serializer = PreferenceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payload = json.dumps({'schema_version': 'modelanvil.preference-pairs.v1', 'pairs': data['samples']},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        artifact = Artifact.all_objects.create(tenant_id=get_active_tenant(), project_id=get_active_project(),
            storage_location_id='local', object_key=f'alignment/preferences/{uuid.uuid4()}.json',
            sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/json',
            metadata={'kind': 'alignment_preferences', 'name': data['name'], 'row_count': len(data['samples'])})
        try:
            upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
        except (OSError, ValueError) as exc:
            raise serializers.ValidationError({'artifact': 'Preference bytes could not be committed.'}) from exc
        artifact.refresh_from_db()
        record_audit('preferences.register', 'artifact', artifact.artifact_id,
            actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
            input_snapshot={'sha256': artifact.sha256, 'byte_size': artifact.byte_size,
                'row_count': len(data['samples']), 'state': artifact.state})
        return Response(self._preference_summary(artifact), status=status.HTTP_201_CREATED)

    def get_queryset(self):
        qs = super().get_queryset()
        project_id = self.request.query_params.get("project")
        if project_id:
            qs = qs.filter(project_id=serializers.UUIDField().run_validation(project_id))
        return qs
