"""Authenticated on-demand CPU serving in the local application process."""
import hashlib
import platform
from datetime import datetime, timezone

from django.db import transaction

from modelanvil.identity.models import check_resource_access
from modelanvil.releases.models import DeploymentRevision, ReleaseVersion, ServingEndpoint
from modelanvil.runners.training.runtime import digest

BACKEND = 'modelanvil.local-on-demand-cpu.v1'

def build_digest():
    from pathlib import Path
    from modelanvil.runners.eval_worker import BUILD_DIGEST
    return hashlib.sha256(Path(__file__).read_bytes() + BUILD_DIGEST.encode()).hexdigest()


def verified_release(version, project):
    review = version.bundle_manifest.get('local_review')
    if (not review or digest(review) != version.manifest_digest or review.get('state') != 'approved'
            or not all(c['passed'] for c in review['criteria'])):
        raise ValueError('Local serving requires an approved frozen candidate review; failures and missing evidence cannot be waived.')
    if not check_resource_access(version, project, version.tenant_id) or not check_resource_access(version.model_version, project, version.tenant_id):
        raise ValueError('Release or model is unavailable in the endpoint project.')
    from modelanvil.releases.review import assert_current_review
    material, _ = assert_current_review(version, project)
    return material


def bounded_inference(version, project, prompt, maximum):
    material = verified_release(version, project)
    from modelanvil.runners.inference import local_session, generate
    with local_session(version.model_version, tenant=version.tenant_id, project=project, device='cpu') as session:
        parts = list(generate(session, [{'role': 'user', 'content': prompt}], max_tokens=maximum,
            temperature=0, prompt_format='plain'))
    return {'text': ''.join(p.get('text', '') for p in parts), **parts[-1],
        'model_sha256': material['artifact'].sha256, 'weights_sha256': material['verification']['weights_sha256'],
        'backend': BACKEND, 'production_qualified': False}


@transaction.atomic
def deploy_local(endpoint, version):
    endpoint = ServingEndpoint.all_objects.select_for_update().get(pk=endpoint.pk)
    version = ReleaseVersion.all_objects.select_for_update().get(pk=version.pk, tenant_id=endpoint.tenant_id)
    previous = endpoint.active_deployment
    next_revision = (endpoint.deployments.order_by('-revision_no').values_list('revision_no', flat=True).first() or 0)+1
    deployment = DeploymentRevision.all_objects.create(tenant_id=endpoint.tenant_id, endpoint=endpoint,
        release_version=version, revision_no=next_revision, previous_deployment=previous,
        readiness_state='pending', serving_config={'backend': BACKEND})
    try:
        result = bounded_inference(version, endpoint.project_id, 'x', 2)
        deployment.serving_config.update(build_digest=build_digest(), model_sha256=result['model_sha256'],
            readiness_probe={'verified_at': datetime.now(timezone.utc).isoformat(), 'weights_sha256': result['weights_sha256'],
                'output_digest': hashlib.sha256(result['text'].encode()).hexdigest(), 'usage': result['usage'],
                'elapsed_seconds': result['elapsed_seconds'], 'hardware': platform.machine()},
            execution_evidence={'level': 'integrated_execution', 'scope': 'local_application_process',
                'live_serving_verified': True, 'production_qualified': False})
        deployment.readiness_state = 'ready'
        endpoint.active_deployment = deployment
        endpoint.save(update_fields=['active_deployment', 'updated_at'])
    except Exception as exc:
        deployment.readiness_state = 'failed'
        deployment.serving_config['failure'] = str(exc) if isinstance(exc, ValueError) else 'Local runtime startup or inference failed.'
    deployment.save(update_fields=['readiness_state', 'serving_config', 'updated_at'])
    return deployment


def serve_local(endpoint, prompt, maximum):
    deployment = endpoint.active_deployment
    if not deployment or deployment.readiness_state != 'ready' or deployment.serving_config.get('backend') != BACKEND:
        raise ValueError('The endpoint has no ready local deployment.')
    if deployment.serving_config.get('build_digest') != build_digest():
        raise ValueError('The installed runtime changed; redeploy and recheck readiness.')
    result = bounded_inference(deployment.release_version, endpoint.project_id, prompt, maximum)
    if result['model_sha256'] != deployment.serving_config.get('model_sha256'):
        raise ValueError('Active deployment artifact pins changed.')
    return {**result, 'deployment_id': str(deployment.deployment_id)}


@transaction.atomic
def rollback_local(endpoint):
    endpoint = ServingEndpoint.all_objects.select_for_update().get(pk=endpoint.pk)
    current = endpoint.active_deployment
    if not current or not current.previous_deployment_id:
        raise ValueError('No previous local deployment is recorded.')
    target = current.previous_deployment
    if target.serving_config.get('backend') != BACKEND:
        raise ValueError('The previous deployment did not use the verified local serving backend.')
    # Create a new observed attempt, retaining both the current and target history.
    return deploy_local(endpoint, target.release_version)
