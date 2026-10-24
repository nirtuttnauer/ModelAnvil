"""Views for TrainingRuns and TrainingCheckpoints."""
from __future__ import annotations

from modelanvil.runners.evidence import evidence, training_evidence, model_evidence, evaluation_evidence, release_evidence

import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path
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


def training_export_options(run):
    if run.status != TrainingRun.Status.COMPLETED:
        return []
    from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
    from modelanvil.runners.training.registry import runtime_for_run, is_worker_run
    module = runtime_for_run(run)
    transformer = is_worker_run(run) and module in (hf_runtime, mlx_runtime, cpu_hf_runtime)
    options = []
    if transformer:
        options.append({'format': 'native', 'label': 'MLX snapshot (ZIP)' if module is mlx_runtime else 'Safetensors snapshot (ZIP)',
                        'extension': 'zip', 'description': 'Includes model weights, tokenizer files and provenance. Adapter runs include the base and separate adapters; weights are not merged or converted.'})
        if module in (hf_runtime, cpu_hf_runtime) and run.recipe_type == TrainingRun.RecipeType.LORA_ADAPTER:
            options.append({'format': 'adapter', 'label': 'LoRA adapter only (ZIP)', 'extension': 'zip',
                            'description': 'Includes adapter weights, adapter configuration and base provenance. Requires the exact base model recorded in the provenance.'})
    if module is cpu_hf_runtime:
        from modelanvil.runners.training.cpu_exports import export_records, FORMATS
        prepared = {v['cpu_export']['format'] for v in export_records(run).values_list('metadata', flat=True)}
        options.extend({'format': name, 'label': label, 'extension': 'zip',
                        'description': 'Prepared immutable CPU export with verified files and load receipt. Quality and release qualification remain separate.'}
                       for name, label in FORMATS.items() if name in prepared)
    options.append({'format': 'json', 'label': 'Snapshot manifest (JSON)' if transformer else 'Reference bundle (JSON)', 'extension': 'json',
                    'description': 'Artifact references and provenance only; model weights are downloaded with the ZIP options.' if transformer
                                   else 'Includes embedded reference weights, tokenizer configuration and provenance for the ModelAnvil reference runtime.'})
    if not is_worker_run(run):
        options[-1].update(method='POST', description='Synthetic reference bundle. Export registers a fixture candidate; it does not establish model quality.')
    return options


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
    recovery_parent = serializers.SlugRelatedField(slug_field='run_id', read_only=True)
    recovery_checkpoint = serializers.SlugRelatedField(slug_field='checkpoint_id', read_only=True)
    job = serializers.UUIDField(source='job.job_id', read_only=True, allow_null=True)
    execution_evidence = serializers.SerializerMethodField()
    output_model_version_uuid = serializers.UUIDField(source='output_model_version.model_version_id', read_only=True, allow_null=True)
    progress_step = serializers.SerializerMethodField()
    export_options = serializers.SerializerMethodField()
    quality_summary = serializers.SerializerMethodField()
    execution_mode = serializers.ChoiceField(choices=['worker', 'simulation'], default='worker', write_only=True)
    runner_manifest = serializers.PrimaryKeyRelatedField(queryset=RunnerManifest.objects.all(), required=False, write_only=True)
    runtime = serializers.JSONField(source='hardware_config', read_only=True)
    purpose = serializers.ChoiceField(choices=['experiment', 'pilot'], default='experiment', write_only=True)
    preflight_token = serializers.CharField(write_only=True, required=False, max_length=2048)
    setup_check = serializers.BooleanField(write_only=True, required=False, default=False)

    def get_execution_evidence(self, obj):
        return training_evidence(obj)

    def get_progress_step(self, obj):
        attempt = obj.job.attempts.order_by('-started_at', '-pk').first() if obj.job_id else None
        return max(obj.current_step, min(obj.total_steps, int(attempt.progress * obj.total_steps))) if attempt else obj.current_step

    def get_export_options(self, obj):
        return training_export_options(obj)

    def get_quality_summary(self, obj):
        if not obj.output_model_version_id:
            return None
        selected = obj.output_model_version.metadata.get('selected_checkpoint_step', obj.total_steps)
        checkpoint = obj.checkpoints.filter(step=selected).first()
        metrics = checkpoint.metrics if checkpoint else {}
        return {'selected_step': selected, 'baseline_loss': metrics.get('validation_loss_before_training'),
                'validation_loss': metrics.get('validation_loss'), 'validation_examples': metrics.get('validation_samples', 0)}

    checkpoints = TrainingCheckpointSerializer(many=True, read_only=True)
    budget_policy_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    estimated_amount = serializers.DecimalField(max_digits=12, decimal_places=4, write_only=True, required=False, allow_null=True)

    def validate(self, attrs):
        self.validate_gpu_options(attrs)
        from modelanvil.runners.training.registry import is_worker_run
        if self.instance and is_worker_run(self.instance):
            raise serializers.ValidationError('Dispatched training configuration is immutable; launch a new run.')
        recipe = attrs.get("recipe_type", getattr(self.instance, "recipe_type", None))
        if recipe == TrainingRun.RecipeType.QLORA_ADAPTER and attrs.get("execution_mode", "worker") != "worker":
            raise serializers.ValidationError({"execution_mode": "QLoRA requires the native Metal worker; no simulation profile is provided."})
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
        from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
        from modelanvil.runners.training.registry import runtime_for_architecture
        base = attrs.get('base_model_version', getattr(self.instance, 'base_model_version', None))
        module = runtime_for_architecture(base.architecture_ref) if base else None
        if module in (hf_runtime, mlx_runtime, cpu_hf_runtime):
            unknown = set(self.initial_data) - set(self.fields) - {'precision', 'adapter', 'quantization'}
            if unknown:
                raise serializers.ValidationError({'gpu_options': 'Unsupported training options: ' + ', '.join(sorted(unknown))})
            try:
                module.validate_options(**{name: self.initial_data[name] for name in
                    ('precision', 'adapter', 'quantization') if name in self.initial_data},
                    recipe_type=attrs.get('recipe_type', getattr(self.instance, 'recipe_type', 'full_sft')))
            except ValueError as exc:
                raise serializers.ValidationError({'gpu_options': str(exc)}) from exc

    class Meta:
        model = TrainingRun
        fields = (
            "execution_evidence", "execution_mode", "runner_manifest", "runtime", "preflight_token", "setup_check",
            "run_id", "project", "recipe_type", "base_model_version", "tokenizer_version",
            "recovery_parent", "recovery_checkpoint",
            "dataset_revision", "dataset_manifest_digest", "pool", "job",
            "budget_policy_id", "estimated_amount",
            "initialization_seed", "hyperparameters", "purpose", "total_steps", "current_step", "status",
            "latest_loss", "metrics_log", "output_model_version", "output_model_version_uuid", "progress_step", "export_options", "quality_summary", "checkpoints",
            "created_at", "updated_at", "started_at", "completed_at"
        )
        read_only_fields = (
            "run_id", "current_step", "status", "latest_loss",
            "metrics_log", "output_model_version", "dataset_manifest_digest", "created_at", "updated_at",
            "started_at", "completed_at", "job"
        )


class TrainingPreflightSerializer(TrainingRunSerializer):
    total_steps = serializers.IntegerField(min_value=1, max_value=3000, required=False)

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
        from modelanvil.api.training_admission import training_preflight
        return training_preflight(attrs, lock_budget=lock_budget)

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
            req_hash = hashlib.sha256(json.dumps({k: v for k, v in request.data.items() if k != "preflight_token"}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

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
        from modelanvil.api.training_admission import admit_training
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        run = admit_training(serializer, request)
        out = self.get_serializer(run).data
        return Response(out, status=201, headers=self.get_success_headers(out))

    @action(detail=True, methods=['get', 'post'], url_path='comparison')
    def comparison(self, request, run_id=None):
        from modelanvil.api.views.models_evals import EvaluationRunSerializer
        from modelanvil.runners.guided_comparison import comparison_preview, queue_guided_comparison
        run = self.get_queryset().select_related('job', 'dataset_revision', 'output_model_version', 'base_model_version', 'pool').get(pk=self.get_object().pk)
        if request.method == 'GET':
            return Response(comparison_preview(run))
        if set(request.data) - {'confirm', 'max_tokens', 'questions'}:
            raise serializers.ValidationError('Submit only confirm, max_tokens, and optional questions.')
        maximum = serializers.IntegerField(min_value=1, max_value=32).run_validation(request.data.get('max_tokens', 32))
        try:
            evaluation, created = queue_guided_comparison(run, questions=request.data.get('questions'),
                confirm=request.data.get('confirm') is True, max_tokens=maximum)
        except (ValueError, TypeError, KeyError) as exc:
            raise serializers.ValidationError({'comparison': str(exc)}) from exc
        return Response(EvaluationRunSerializer(evaluation, context={'request': request}).data, status=201 if created else 200)

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

    @action(detail=True, methods=['get', 'post'], url_path='resume')
    def resume(self, request, run_id=None):
        from modelanvil.runners.training.recovery import recovery_review, resume_training
        run = self.get_object()
        if request.method == 'GET':
            return Response(recovery_review(run))
        checkpoint_id = serializers.UUIDField().run_validation(request.data.get('checkpoint_id'))
        policy_id = serializers.UUIDField().run_validation(request.data.get('budget_policy_id'))
        try:
            child, created = resume_training(run, checkpoint_id=checkpoint_id, policy_id=policy_id)
        except ValueError as exc:
            raise serializers.ValidationError({'recovery': str(exc)}) from exc
        if created:
            record_audit('training.resume', 'training_run', child.run_id,
                actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
                input_snapshot={'parent_run_id': str(run.run_id), 'checkpoint_id': str(checkpoint_id),
                    'start_step': child.current_step, 'budget_policy_id': str(policy_id), 'job_id': str(child.job.job_id)})
        return Response(self.get_serializer(child).data, status=201 if created else 200)

    def _worker_bundle(self, run):
        from modelanvil.runners.training.registry import checkpoint_bundle
        if run.status != TrainingRun.Status.COMPLETED:
            raise serializers.ValidationError('Wait for successful worker completion before exporting or inferring.')
        try:
            selected_step = (run.output_model_version.metadata.get('selected_checkpoint_step', run.total_steps)
                             if run.output_model_version else run.total_steps)
            return checkpoint_bundle(run, run.checkpoints.get(step=selected_step))
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

    @action(detail=True, methods=['get', 'post'], url_path='download')
    def download(self, request, *args, **kwargs):
        """Download verified native files or a JSON bundle; optimizer state stays in checkpoints."""
        from django.http import FileResponse
        from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime
        from modelanvil.runners.training.registry import runtime_for_run, is_worker_run
        import tempfile
        import zipfile
        import shutil
        run = self.get_object()
        module = runtime_for_run(run)
        selected_format = request.query_params.get('export_format', 'native')
        if selected_format not in {option['format'] for option in training_export_options(run)}:
            raise serializers.ValidationError('Choose a supported export format from a completed training run.')
        if selected_format in {'merged', 'gguf-q8'}:
            from modelanvil.runners.training.cpu_exports import open_export
            try:
                record, stream = open_export(run, selected_format)
            except (ValueError, OSError) as exc:
                raise serializers.ValidationError(str(exc)) from exc
            response = FileResponse(stream, as_attachment=True, filename=f'modelanvil-{run.run_id}-{selected_format}.zip', content_type='application/zip')
            response['ETag'] = '"' + record.sha256 + '"'
            response['X-Artifact-ID'] = str(record.artifact_id)
            return response
        if is_worker_run(run):
            bundle = self._worker_bundle(run)
        else:
            if request.method != 'POST':
                raise serializers.ValidationError('Synthetic fixture exports register a candidate and require POST.')
            _, bundle = TrainingEngine().export_candidate_model(run)
        output = tempfile.TemporaryFile()
        try:
            if selected_format == 'json':
                from modelanvil.runners.training.registry import verify_bundle
                if not is_worker_run(run) or module not in (hf_runtime, mlx_runtime, cpu_hf_runtime):
                    verify_bundle(bundle)
                output.write(json.dumps(bundle, indent=2, allow_nan=False).encode())
                output.seek(0)
                return FileResponse(output, as_attachment=True, filename=f'modelanvil-{run.run_id}.json', content_type='application/json')
            files = bundle['files']
            if selected_format == 'adapter':
                names = {'adapter_model.safetensors', 'adapter_config.json', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'}
                if not names.issubset(files):
                    raise ValueError('The selected checkpoint does not contain a complete LoRA adapter.')
                files = {name: files[name] for name in sorted(names)}
            with module.staged_files(files, run.tenant_id, run.project_id) as directory:
                if selected_format == 'adapter':
                    config = json.loads((directory / 'adapter_config.json').read_text())
                    config.update(base_model_name_or_path=bundle['source']['repo_id'], revision=bundle['source']['revision'])
                    (directory / 'adapter_config.json').write_text(json.dumps(config, sort_keys=True, allow_nan=False))
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                    for name in sorted(files):
                        with (directory / name).open('rb') as source, archive.open(zipfile.ZipInfo(name, (1980,1,1,0,0,0)), 'w', force_zip64=True) as target:
                            shutil.copyfileobj(source, target, length=1024 * 1024)
                    provenance = bundle
                    if selected_format == 'adapter':
                        from modelanvil.runners.training.cpu_exports import pin
                        provenance = {**bundle, 'export_format': selected_format, 'included_files': sorted(files),
                                      'export_files': {name: pin(directory / name) for name in sorted(files)}}
                    license_path = Path(module.__file__).parent / 'assets' / 'Apache-2.0.txt'
                    archive.writestr(zipfile.ZipInfo('LICENSE.txt', (1980,1,1,0,0,0)), license_path.read_bytes())
                    archive.writestr(zipfile.ZipInfo('modelanvil-provenance.json', (1980,1,1,0,0,0)), json.dumps(provenance, sort_keys=True, allow_nan=False))
            output.seek(0)
            return FileResponse(output, as_attachment=True, filename=f'modelanvil-{run.recipe_type}-{run.run_id}.zip', content_type='application/zip')
        except (ValueError, OSError) as exc:
            output.close()
            raise serializers.ValidationError(str(exc)) from exc
        except Exception:
            output.close()
            raise

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
    source_group_id = serializers.CharField(max_length=128, required=False, trim_whitespace=False)
    prompt = serializers.CharField(max_length=62, trim_whitespace=False)
    chosen = serializers.CharField(max_length=62, trim_whitespace=False)
    rejected = serializers.CharField(max_length=62, trim_whitespace=False)

    def validate(self, pair):
        if any(not value.strip() for value in pair.values()):
            raise serializers.ValidationError('Prompt, responses and any source group ID must be nonempty.')
        if pair['chosen'] == pair['rejected']:
            raise serializers.ValidationError('Chosen and rejected responses must differ.')
        if len(pair['prompt']) + max(len(pair['chosen']), len(pair['rejected'])) > 62:
            raise serializers.ValidationError('Prompt plus response must fit the 62-character CPU context bound.')
        return pair


class PreferenceRegistrationSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    samples = PreferencePairSerializer(many=True, min_length=1, max_length=32)
    labels_reviewed = serializers.BooleanField(default=False)

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
    regression_dataset_artifact = serializers.SlugRelatedField(slug_field='artifact_id', required=False, allow_null=True,
        queryset=Artifact.objects.all())
    job_id = serializers.UUIDField(source='job.job_id', read_only=True, default=None)
    job_status = serializers.CharField(source='job.status', read_only=True, default=None)
    execution_capabilities = serializers.SerializerMethodField()

    def get_execution_capabilities(self, obj):
        from modelanvil.runners.alignment.execution import alignment_capabilities
        return alignment_capabilities(obj)

    execution_evidence = serializers.SerializerMethodField()

    def get_execution_evidence(self, obj):
        if obj.execution_pins:
            result = evidence('integrated_execution' if obj.current_step else 'configuration_only',
                ('Bounded pretrained CPU reward/RLOO stages with separate resource budgets and independent qualification gates.' if obj.algorithm in ('reward_model', 'rloo') else 'Bounded Apple GPU DPO on pinned preference bytes and model weights; independent qualification gates apply.') if obj.job_id else
                'Bounded CPU character alignment on pinned preference bytes and model weights; no hardware or production qualification.')
            result['runtime_scope'] = obj.execution_pins.get('runtime')
            return result
        if obj.current_step or obj.status in (AlignmentRun.Status.COMPLETED, AlignmentRun.Status.RUNNING):
            return evidence('simulation', 'Legacy alignment fixture metrics; no verified preference weight training.')
        return evidence('configuration_only', 'Saved alignment plan; no preference weight training has executed.')

    def validate(self, attrs):
        if self.instance and (self.instance.job_id or self.instance.status != AlignmentRun.Status.PENDING or self.instance.started_at or self.instance.current_step):
            raise serializers.ValidationError('Started alignment plans are immutable; create a new run.')
        algo = attrs.get("algorithm", getattr(self.instance, "algorithm", None))
        if algo == 'grpo':
            unknown = set(self.initial_data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({'grpo_options': 'Unsupported GRPO options: ' + ', '.join(sorted(unknown))})
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
                'train_dataset_artifact', 'held_out_dataset_artifact', 'regression_dataset_artifact', 'worker_pool')}
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
        elif algo in ("ppo_rlhf", "rloo"):
            reward_model = attrs.get("reward_model_version", getattr(self.instance, "reward_model_version", None))
            if not reward_model:
                raise serializers.ValidationError({"reward_model_version": "Learned-reward RLHF requires a pinned trained reward model version."})
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
            "regression_dataset_artifact", "worker_pool", "job_id", "job_status",
            "verifier_spec", "dataset_manifest_digest", "held_out_validation_digest",
            "hyperparameters", "current_step", "total_steps", "latest_metrics",
            "metrics_history", "rollouts_log", "output_model_version", "stop_reason",
            "created_at", "updated_at", "started_at", "completed_at"
        )
        read_only_fields = (
            "run_id", "current_step", "status", "latest_metrics",
            "execution_pins", "resource_reservation_id", "stop_reason",
            "job_id", "job_status",
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
    def resume(self, request, run_id=None):
        from modelanvil.runners.alignment.execution import execute_alignment
        try:
            run = execute_alignment(self.get_object(), resume=True)
        except ValueError as exc:
            raise serializers.ValidationError({'recovery': str(exc)}) from exc
        self._audit_execution(request, 'alignment.resume', run)
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
        if instance.job_id or instance.status != AlignmentRun.Status.PENDING or instance.started_at or instance.current_step:
            raise serializers.ValidationError('Started alignment plans and execution results are immutable.')
        return super().perform_destroy(instance)

    @action(detail=True, methods=['get'])
    def download(self, request, run_id=None):
        import tempfile
        import zipfile
        from pathlib import Path
        from django.http import FileResponse
        from modelanvil.runners.alignment import mps_dpo, hf_rlhf
        from modelanvil.runners.inference import snapshot
        from modelanvil.runners.training import hf_runtime
        run = self.get_object()
        if not run.job_id or run.status != 'completed' or not run.output_model_version_id:
            raise serializers.ValidationError('Complete a pretrained worker alignment run before downloading its weights.')
        try:
            module = hf_rlhf if run.algorithm in ('reward_model', 'rloo') else mps_dpo
            if module is mps_dpo:
                snapshot(run.output_model_version, run.tenant_id, run.project_id)
            bundle = module.candidate_bundle(run.output_model_version, run.tenant_id, run.project_id)
            names = ('reward_head.safetensors',) if run.algorithm == 'reward_model' else ('adapter_model.safetensors', 'adapter_config.json')
            staging = hf_rlhf.stage_files if module == hf_rlhf else hf_runtime.staged_files
            stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024**2)
            with staging({name: bundle['files'][name] for name in names}, run.tenant_id, run.project_id) as directory:
                with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
                    for name in names: archive.write(directory / name, name)
                    if run.algorithm == 'reward_model':
                        archive.writestr('reward_config.json', json.dumps(bundle['reward_config'], sort_keys=True))
                    archive.write(Path(hf_runtime.__file__).parent / 'assets/Apache-2.0.txt', 'LICENSE.txt')
                    archive.writestr('provenance.json', json.dumps({**bundle,
                        'independent_evaluation': run.latest_metrics.get('independent_evaluation'),
                        'archive_scope': 'Learned head or adapter only; acquire the exact pinned base revision separately.'}, sort_keys=True))
            stream.seek(0)
        except (ValueError, OSError) as exc:
            if 'stream' in locals(): stream.close()
            raise serializers.ValidationError({'download': str(exc)}) from exc
        return FileResponse(stream, as_attachment=True, filename=f'{run.algorithm}-{run.run_id}-weights.zip', content_type='application/zip')

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
        review = {'method': 'owner_attestation', 'labels_reviewed': data['labels_reviewed'],
            'actor_id': str(request.modelanvil_actor_id), 'actor_kind': request.modelanvil_actor_kind}
        payload = json.dumps({'schema_version': 'modelanvil.preference-pairs.v1', 'pairs': data['samples'], 'review': review},
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
