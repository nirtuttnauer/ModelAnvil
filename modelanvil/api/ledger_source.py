from modelanvil.jobs.models import Job
from modelanvil.runners.models import AlignmentRun
from modelanvil.core.models import AuditEvent


def reservation_source(reservation):
    if not reservation:
        return {'scope': 'tenant-wide or unattributed', 'job_id': None, 'actor_id': None}
    job = Job.all_objects.filter(tenant_id=reservation.tenant_id, job_id=reservation.job_id).first()
    if job:
        owner = job.training_runs.first() or job.evaluation_runs.first()
        model_import = getattr(job, 'model_import', None)
        project = getattr(owner, 'project_id', None) or getattr(model_import, 'project_id', None) or job.project_id
        event_ids = [job.job_id] + ([owner.run_id] if owner else [])
        event = AuditEvent.all_objects.filter(tenant_id=reservation.tenant_id, resource_id__in=event_ids).order_by('created_at').first()
        return {'job_id': str(job.job_id), 'kind': 'training' if job.training_runs.exists() else 'evaluation' if job.evaluation_runs.exists() else 'job',
            'run_id': str(owner.run_id) if owner else str(job.job_id), 'project_id': str(project) if project else None,
            'scope': 'project' if project else 'tenant-wide', 'actor_id': str(event.actor_id) if event and event.actor_id else None}
    alignment = AlignmentRun.all_objects.filter(tenant_id=reservation.tenant_id, run_id=reservation.job_id).first()
    return {'job_id': None, 'kind': 'alignment' if alignment else None, 'run_id': str(alignment.run_id) if alignment else None,
        'project_id': str(alignment.project_id) if alignment and alignment.project_id else None,
        'scope': 'project' if alignment and alignment.project_id else 'tenant-wide or unattributed', 'actor_id': None}
