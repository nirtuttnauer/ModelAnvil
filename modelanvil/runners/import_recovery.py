"""Safe acknowledgement and retry of an immutable model acquisition plan."""
from django.db import transaction
from modelanvil.core.tenancy import get_active_project
from modelanvil.jobs.models import Job, JobAttempt, Worker, OutboxEvent, dispatch_topic
from modelanvil.runners.models import ModelImport


@transaction.atomic
def change_import(item, action):
    if get_active_project() != item.project_id:
        raise ValueError('Manage this import from its originating project.')
    if not item.job_id:
        raise ValueError('This local import has no asynchronous transfer to recover.')
    job = Job.all_objects.select_for_update().get(pk=item.job_id, tenant_id=item.tenant_id)
    item = ModelImport.all_objects.select_for_update().get(pk=item.pk, tenant_id=item.tenant_id)
    if item.candidate_id or item.status == 'completed':
        raise ValueError('This import has already published its immutable candidate.')
    if action == 'cancel':
        if job.status == Job.Status.QUEUED:
            job.status = Job.Status.CANCELLED; item.status = 'cancelled'
        elif job.status not in (Job.Status.RUNNING, Job.Status.CANCELLED):
            raise ValueError('Only queued or running transfers can be cancelled.')
        job.desired_action = Job.DesiredAction.CANCEL
    else:
        if job.status == Job.Status.QUEUED and job.desired_action == Job.DesiredAction.RUN:
            return item
        if (job.status not in (Job.Status.FAILED, Job.Status.INTERRUPTED, Job.Status.CANCELLED)
                or job.claimed_by_id or job.lease_expires_at or job.fencing_token
                or job.attempts.filter(status=JobAttempt.Status.RUNNING).exists()):
            raise ValueError('Wait for acknowledged terminal ownership before resuming.')
        if (not job.pool or job.pool.status != 'active' or not Worker.all_objects.filter(
                tenant_id=item.tenant_id, pool=job.pool, status__in=['available', 'busy'], capabilities__model_import=True).exists()):
            raise ValueError('Reconnect an available model-import worker in this pool before retrying.')
        job.status, job.desired_action = Job.Status.QUEUED, Job.DesiredAction.RUN
        job.max_attempts = job.attempt_count + 3
        item.status = 'queued'
        OutboxEvent.all_objects.create(tenant_id=item.tenant_id,
            topic=dispatch_topic(job.tenant_id, job.pool.queue_name, job.pool.name),
            payload={'event_type': 'job.queued', 'job_id': str(job.job_id)})
    job.save(update_fields=['status', 'desired_action', 'max_attempts', 'updated_at'])
    item.save(update_fields=['status', 'updated_at'])
    return item
