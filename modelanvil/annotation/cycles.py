"""Bounded, real CPU training and independent qualification of reviewed labels."""
import hashlib
import json
import math

from django.db.models import Sum
from rest_framework import serializers
from modelanvil.artifacts.models import DatasetRevision
from modelanvil.budgets.models import BudgetPolicy
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import Job, WorkerPool
from modelanvil.runners.models import EvaluationRun, EvaluationSuiteVersion, ModelVersion, RunnerManifest
from modelanvil.runners.training.runtime import RUNTIME_ID


class CycleConfiguration(serializers.Serializer):
    base_model_version = serializers.UUIDField()
    runner_manifest = serializers.IntegerField(min_value=1)
    training_pool = serializers.IntegerField(min_value=1)
    training_budget = serializers.UUIDField()
    evaluation_suite = serializers.UUIDField()
    evaluation_pool = serializers.IntegerField(min_value=1)
    evaluation_budget = serializers.UUIDField()
    steps_per_cycle = serializers.IntegerField(min_value=1, max_value=100)
    max_training_steps = serializers.IntegerField(min_value=1, max_value=10000)
    max_evaluation_cases = serializers.IntegerField(min_value=1, max_value=10000)
    max_tokens = serializers.IntegerField(min_value=1, max_value=32, default=8)
    min_accuracy = serializers.FloatField(min_value=0, max_value=1, default=0.7)

    def validate(self, data):
        if set(self.initial_data) - set(self.fields):
            raise serializers.ValidationError('Unknown cycle configuration fields.')
        if not math.isfinite(data['min_accuracy']):
            raise serializers.ValidationError('Minimum accuracy must be finite.')
        if data['steps_per_cycle'] > data['max_training_steps']:
            raise serializers.ValidationError('The training cap must cover one cycle.')
        return {k: str(v) if k in ('base_model_version', 'training_budget', 'evaluation_suite', 'evaluation_budget') else v for k, v in data.items()}


def suite_digest(suite):
    return hashlib.sha256(json.dumps({'cases': suite.cases, 'scorer': suite.scorer_type,
        'configuration': suite.scorer_config, 'role': suite.protected_role}, sort_keys=True, allow_nan=False).encode()).hexdigest()


def resources(config, source):
    """Recheck current scope on every stage; configuration never grants access."""
    tenant = get_active_tenant()
    base = get_accessible_queryset(ModelVersion).filter(model_version_id=config['base_model_version']).first()
    suite = get_accessible_queryset(EvaluationSuiteVersion).filter(suite_version_id=config['evaluation_suite']).first()
    revision = get_accessible_queryset(DatasetRevision).filter(revision_id=source.get('source_revision')).first()
    runner = RunnerManifest.objects.filter(pk=config['runner_manifest'], tenant_id=tenant, enabled=True).first()
    pools = [WorkerPool.objects.filter(pk=config[key], tenant_id=tenant, status='active').first()
             for key in ('training_pool', 'evaluation_pool')]
    policies = [BudgetPolicy.objects.filter(policy_id=config[key], tenant_id=tenant, enabled=True, unit=unit, currency='').first()
                for key, unit in [('training_budget', 'training_steps'), ('evaluation_budget', 'evaluation_cases')]]
    if not all([base, suite, revision, runner, *pools, *policies]):
        raise serializers.ValidationError('Select currently accessible source, CPU model, suite, runner, pools and quantity budgets.')
    if base.architecture_ref != RUNTIME_ID:
        raise serializers.ValidationError('The reviewed-label cycle currently supports the registered CPU character runtime.')
    if revision.manifest_digest != source.get('source_manifest_digest'):
        raise serializers.ValidationError('The pinned source manifest changed.')
    from modelanvil.runners.eval_executor import validate_local_suite
    try: validate_local_suite(suite.cases, suite.scorer_type, suite.scorer_config, require_source_groups=True)
    except ValueError as exc: raise serializers.ValidationError(str(exc)) from exc
    if suite.protected_role != 'protected_eval':
        raise serializers.ValidationError('Select a protected evaluation suite.')
    if config.get('suite_digest') and suite_digest(suite) != config['suite_digest']:
        raise serializers.ValidationError('The pinned evaluation suite changed; create a new campaign.')
    return base, suite, runner, pools, policies


def prepare_configuration(data, source, dollar_limit, kind):
    form = CycleConfiguration(data=data); form.is_valid(raise_exception=True)
    config = form.validated_data
    if dollar_limit != 0:
        raise serializers.ValidationError('CPU cycle costs are unpriced. Set the dollar limit to 0 and use explicit step/case caps and quantity budgets.')
    if kind not in ('classification', 'text_generation') or not source.get('source_revision'):
        raise serializers.ValidationError('Real cycles require a published text source and classification or text-generation labels.')
    _, suite, _, _, _ = resources(config, source)
    if len(suite.cases) > config['max_evaluation_cases']:
        raise serializers.ValidationError('The evaluation cap must cover the protected suite.')
    config['suite_digest'] = suite_digest(suite)
    groups = {case['source_group_id'] for case in suite.cases}
    refs = {case['sample_id'] for case in suite.cases if case.get('sample_id')}
    source['protected_source_groups'] = sorted(set(source.get('protected_source_groups', [])) | groups)
    source['audit_sample_refs'] = sorted(set(source.get('audit_sample_refs', [])) | refs)
    return config


def dispatch_training(campaign, snapshot, request):
    config = campaign.configuration.get('cycle')
    if not config or snapshot.training_run_id:
        return
    base, _, runner, pools, policies = resources(config, campaign.configuration)
    if campaign.active_drafting_model_id:
        base = get_accessible_queryset(ModelVersion).filter(pk=campaign.active_drafting_model_id).first()
        if base is None or base.architecture_ref != RUNTIME_ID:
            raise serializers.ValidationError('The current drafting model is unavailable or incompatible.')
    planned = campaign.snapshots.filter(training_run__isnull=False).aggregate(total=Sum('training_run__total_steps'))['total'] or 0
    if planned + config['steps_per_cycle'] > config['max_training_steps']:
        raise serializers.ValidationError('Campaign training-step cap reached; approved reviews remain available.')
    if not snapshot.dataset_revision_id:
        raise serializers.ValidationError('Approve at least one publishable text label before training.')
    from modelanvil.api.views.training_views import TrainingRunSerializer
    from modelanvil.api.training_admission import admit_training
    form = TrainingRunSerializer(data={'recipe_type': 'full_sft', 'execution_mode': 'worker',
        'base_model_version': base.pk, 'tokenizer_version': base.tokenizer_id,
        'dataset_revision': snapshot.dataset_revision_id, 'runner_manifest': runner.pk,
        'pool': pools[0].pk, 'budget_policy_id': str(policies[0].policy_id),
        'total_steps': config['steps_per_cycle']}, context={'request': request})
    form.is_valid(raise_exception=True)
    snapshot.training_run = admit_training(form, request)
    snapshot.save(update_fields=['training_run', 'updated_at'])


def advance(campaign):
    config = campaign.configuration.get('cycle')
    if not config or campaign.status != 'active':
        raise serializers.ValidationError('An active campaign with a reviewed cycle configuration is required.')
    _, suite, _, pools, policies = resources(config, campaign.configuration)
    snapshot = campaign.snapshots.select_for_update().order_by('-cycle_no').first()
    if not snapshot or not snapshot.training_run_id or snapshot.qualification:
        return snapshot
    training = snapshot.training_run
    if training.status in ('pending', 'running'):
        return snapshot
    if training.status != 'completed' or not training.output_model_version_id:
        snapshot.qualification = {'decision': 'rejected', 'reason': 'Training did not complete; previous drafting model retained.'}
    elif not snapshot.evaluation_run_id:
        planned = sum(s.evaluation_run.suite_version.cases_count for s in campaign.snapshots.filter(evaluation_run__isnull=False).select_related('evaluation_run__suite_version'))
        if planned + len(suite.cases) > config['max_evaluation_cases']:
            raise serializers.ValidationError('Campaign evaluation-case cap reached; no evaluation was dispatched.')
        from modelanvil.runners.eval_worker import queue_evaluation
        run = EvaluationRun.objects.create(tenant_id=campaign.tenant_id, project_id=campaign.project_id,
            suite_version=suite, candidate_model_version=training.output_model_version,
            baseline_model_version=training.base_model_version, protocol_ref={'prompt_format': 'plain'})
        try: queue_evaluation(run, pool=pools[1], policy=policies[1], max_tokens=config['max_tokens'])
        except (ValueError, TypeError, KeyError) as exc: raise serializers.ValidationError(str(exc)) from exc
        snapshot.evaluation_run = run
    else:
        run = snapshot.evaluation_run
        if run.status in ('pending', 'running'):
            return snapshot
        accuracy = run.metrics.filter(key='accuracy', slice_name='all').first()
        baseline = next((m for m in run.protocol_ref.get('baseline_metrics', []) if m['key'] == 'accuracy' and m['slice_name'] == 'all'), None)
        batch = campaign.batches.get(cycle_no=snapshot.cycle_no)
        unchanged = campaign.active_drafting_model_id == batch.assigned_drafting_model_id
        passed = (run.status == 'completed' and run.case_results.count() == len(suite.cases)
            and accuracy is not None and baseline is not None and math.isfinite(accuracy.value)
            and accuracy.value >= config['min_accuracy'] and accuracy.value >= baseline['value'] and unchanged)
        snapshot.qualification = {'decision': 'promoted' if passed else 'rejected',
            'evaluation_run': str(run.run_id), 'accuracy': accuracy.value if accuracy else None,
            'baseline_accuracy': baseline['value'] if baseline else None,
            'prior_model': str(training.base_model_version.model_version_id),
            'candidate_model': str(training.output_model_version.model_version_id),
            'reason': 'Independent protected evaluation passed threshold and non-regression.' if passed else
                      'Incomplete/failed evaluation, unmet gate, regression or changed assignment; previous drafting model retained.'}
        if passed:
            campaign.active_drafting_model = training.output_model_version
            campaign.save(update_fields=['active_drafting_model', 'updated_at'])
    snapshot.save(update_fields=['evaluation_run', 'qualification', 'updated_at'])
    if snapshot.qualification and campaign.current_cycle >= campaign.max_cycles:
        campaign.status = 'completed'; campaign.save(update_fields=['status', 'updated_at'])
    return snapshot


def stop_jobs(campaign):
    """Persist cancellation intent; acknowledge queued jobs only when finalized."""
    for snapshot in campaign.snapshots.select_related('training_run__job', 'evaluation_run__job'):
        for run in (snapshot.training_run, snapshot.evaluation_run):
            if not run or not run.job_id:
                continue
            job = Job.all_objects.select_for_update().get(pk=run.job_id, tenant_id=campaign.tenant_id)
            if job.status not in ('queued', 'running'):
                continue
            job.desired_action = 'cancel'
            if job.status == 'queued':
                job.status = 'cancelled'
                if isinstance(run, EvaluationRun):
                    from modelanvil.runners.eval_worker import finalize_evaluation
                    finalize_evaluation(job, 'cancelled')
                else:
                    from modelanvil.runners.training.registry import finalize_job
                    finalize_job(job, 'cancelled')
            job.save(update_fields=['desired_action', 'status', 'updated_at'])
