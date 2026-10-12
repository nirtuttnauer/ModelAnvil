"""Jobs inherit access restrictions from their owning runs or acquisitions."""
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import Job
from django.db.models import CharField, Q, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Replace


def accessible_jobs():
    from modelanvil.runners.models import TrainingRun
    from modelanvil.data.models import SourceSnapshot

    tenant = get_active_tenant()
    if tenant is None:
        return Job.objects.none()
    hidden_runs = TrainingRun.all_objects.filter(tenant_id=tenant, job__isnull=False).exclude(
        pk__in=get_accessible_queryset(TrainingRun).values("pk")
    )
    from modelanvil.runners.models import InferenceRequest
    requests = get_accessible_queryset(InferenceRequest).annotate(
        normalized_id=Replace(Cast('request_id', CharField()), Value('-'), Value(''))
    ).values('normalized_id')
    snapshots = get_accessible_queryset(SourceSnapshot).annotate(
        normalized_id=Replace(Cast("snapshot_id", CharField()), Value("-"), Value(""))
    ).values("normalized_id")
    return Job.objects.filter(tenant_id=tenant).exclude(pk__in=hidden_runs.values("job_id")).annotate(
        accessible_snapshot_id=Replace(KeyTextTransform("snapshot_id", "payload"), Value("-"), Value(""), output_field=CharField())
    ).filter(Q(payload__type__isnull=True) | ~Q(payload__type="dataset_acquisition") | Q(accessible_snapshot_id__in=snapshots)).annotate(
        accessible_request_id=Replace(KeyTextTransform('request_id', 'payload'), Value('-'), Value(''), output_field=CharField())
    ).filter(Q(payload__type__isnull=True) | ~Q(payload__type='specialist_inference') | Q(accessible_request_id__in=requests))


def cancellation_endpoint(job):
    if isinstance(job.payload, dict) and job.payload.get('type') == 'specialist_inference':
        return f"/api/v1/specialists/jobs/{job.payload['request_id']}/cancel/"
    if isinstance(job.payload, dict) and job.payload.get("type") == "dataset_acquisition":
        return f"/api/v1/dataset-bank/acquisitions/{job.payload['snapshot_id']}/cancel/"
    owner = job.training_runs.filter(hardware_config__execution_mode="worker").first()
    if owner:
        return f"/api/v1/training-runs/{owner.run_id}/cancel/"
    return f"/api/v1/jobs/{job.job_id}/cancel/"
