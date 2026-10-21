"""Historical audit authority explains current deletion/access without returning hidden data."""
from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision, DeletionTombstone
from modelanvil.identity.models import get_accessible_queryset
from modelanvil.jobs.models import Job
from modelanvil.jobs.access import accessible_jobs
from modelanvil.runners.models import TrainingRun, EvaluationRun, ModelVersion, ChatConversation, ChatComparison
from modelanvil.releases.models import ReleaseVersion, ServingEndpoint


def audit_resource_state(event):
    mapping = {'training_run': (TrainingRun, 'run_id'), 'evaluation_run': (EvaluationRun, 'run_id'),
        'model_version': (ModelVersion, 'model_version_id'), 'dataset_revision': (DatasetRevision, 'revision_id'),
        'dataset': (Dataset, 'dataset_id'), 'artifact': (Artifact, 'artifact_id'), 'job': (Job, 'job_id'),
        'release_version': (ReleaseVersion, 'release_version_id'), 'serving_endpoint': (ServingEndpoint, 'endpoint_id'),
        'chat_conversation': (ChatConversation, 'conversation_id'), 'chat_comparison': (ChatComparison, 'comparison_id')}
    if not event.resource_id or event.resource_type not in mapping:
        return {'state': 'historical_only', 'reason': 'Use the recorded input snapshot; this event has no supported current resource identifier.'}
    if DeletionTombstone.all_objects.filter(tenant_id=event.tenant_id, resource_id=str(event.resource_id)).exists():
        return {'state': 'deleted', 'reason': 'A deletion tombstone applies to this recorded resource.'}
    model, field = mapping[event.resource_type]
    current = accessible_jobs() if model == Job else get_accessible_queryset(model)
    if current.filter(**{field: event.resource_id}).exists():
        return {'state': 'available', 'reason': 'The exact record is currently accessible; its route rechecks current permissions.'}
    if model.all_objects.filter(tenant_id=event.tenant_id, **{field: event.resource_id}).exists():
        return {'state': 'access_lost', 'reason': 'The previously recorded resource is outside current access scope. Hidden content is not returned.'}
    return {'state': 'unavailable', 'reason': 'The historical reference no longer resolves to a current record. The audit snapshot remains available.'}
