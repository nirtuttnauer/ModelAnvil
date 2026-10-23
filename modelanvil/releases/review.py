"""Frozen local candidate review; this never grants production qualification."""
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from modelanvil.identity.models import check_resource_access
from modelanvil.core.tenancy import get_active_project
from modelanvil.runners.evidence import training_evidence
from modelanvil.runners.models import EvaluationRun
from modelanvil.releases.artifacts import release_model_bundle
from modelanvil.releases.models import Release, ReleaseVersion
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.runtime import digest


EXPORT_PROFILE = 'modelanvil.local-export.v2'


def _consumer(runtime):
    root = Path(__file__).resolve().parents[2]
    name = 'cpu_transformer_infer.py' if 'general-transformer' in runtime else 'cpu_character_infer.py'
    raw = (root / 'scripts' / name).read_bytes()
    return raw, {'filename': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)}


def _evidence(evaluation, training):
    return {'metrics': list(evaluation.metrics.order_by('key','slice_name').values('key','slice_name','value','sample_count','uncertainty_interval')),
        'cases': list(evaluation.case_results.order_by('case_id').values('case_id','input_prompt','expected_output','candidate_output','score','passed','slice_name')),
        'baseline_metrics': evaluation.protocol_ref.get('baseline_metrics', []),
        'baseline_results': evaluation.protocol_ref.get('baseline_results', []),
        'pins': evaluation.protocol_ref['pins'], 'license': training.output_model_version.license_evidence,
        'training': {'run_id': str(training.run_id), 'steps': training.current_step,
            'dataset_digest': training.dataset_revision.manifest_digest,
            'base_version': str(training.base_model_version.model_version_id)}}


def _actual_training(candidate, tenant):
    if candidate.state in ('archived', 'rejected'):
        raise ValueError('Select an available completed candidate.')
    training = TrainingRun.all_objects.filter(tenant_id=tenant, output_model_version=candidate,
        status='completed', job__status='succeeded').first()
    if training is None or training_evidence(training)['level'] != 'integrated_execution':
        raise ValueError('Select a candidate from an actual completed worker training run.')
    return training


def _current_review(version, project=None):
    review = version.bundle_manifest.get('local_review')
    if not review or digest(review) != version.manifest_digest or review.get('export_profile') != EXPORT_PROFILE:
        raise ValueError('Create a fresh immutable candidate review before exporting or serving.')
    project = project or get_active_project() or version.project_id
    if not check_resource_access(version, project, version.tenant_id) or not check_resource_access(version.model_version, project, version.tenant_id):
        raise ValueError('Reviewed release or model access is no longer available.')
    candidate = version.model_version
    if candidate.state in ('archived','rejected'):
        raise ValueError('The reviewed candidate is archived or rejected; create a current candidate review.')
    training = _actual_training(candidate, version.tenant_id)
    evaluation = EvaluationRun.all_objects.filter(tenant_id=version.tenant_id, run_id=review['evaluation_run']).first()
    if (not evaluation or not check_resource_access(evaluation, project, version.tenant_id)
            or evaluation.candidate_model_version_id != candidate.pk or evaluation.status != 'completed'
            or not evaluation.job_id or evaluation.job.status != 'succeeded'
            or evaluation.case_results.count() != len(evaluation.suite_version.cases)):
        raise ValueError('Required evaluation is incomplete or unavailable; run it and create a fresh review.')
    from modelanvil.runners.eval_worker import resolve_inputs
    current = resolve_inputs(evaluation, evaluation.protocol_ref['pins']['max_tokens'])
    if current['pins'] != review['evaluation_pins'] or digest(_evidence(evaluation,training)) != review['evidence_digest']:
        raise ValueError('Pinned evaluation, results or training inputs changed; create a fresh review.')
    if digest(version.model_card) != review['model_card_digest']:
        raise ValueError('The frozen model card changed; create a fresh review.')
    raw = base64.b64decode(version.bundle_manifest['export_consumer'], validate=True)
    consumer = review['export_consumer']
    if len(raw) != consumer['byte_size'] or hashlib.sha256(raw).hexdigest() != consumer['sha256']:
        raise ValueError('The frozen standalone consumer is unavailable or changed.')
    material = release_model_bundle(version)
    if not material or material['artifact'].sha256 != review['model_artifact']['sha256']:
        raise ValueError('Reviewed model bytes are unavailable or changed.')
    return material, raw


def assert_current_review(version, project=None):
    from django.core.exceptions import ObjectDoesNotExist
    try:
        return _current_review(version, project)
    except (KeyError, TypeError, AttributeError, ObjectDoesNotExist):
        raise ValueError('Required frozen evidence is missing; create a fresh review.') from None


def review_freshness(version):
    try:
        assert_current_review(version)
        return {'valid': True, 'checked_at': timezone.now().isoformat(), 'reason': 'Evidence is current. Check the frozen review criteria before release.'}
    except (ValueError, PermissionError) as exc:
        return {'valid': False, 'checked_at': timezone.now().isoformat(), 'reason': str(exc)}
    except (KeyError, TypeError, AttributeError):
        return {'valid': False, 'checked_at': timezone.now().isoformat(), 'reason': 'Required frozen evidence is missing; create a fresh review.'}


@transaction.atomic
def create_candidate_review(*, tenant, project, name, candidate, evaluation, min_accuracy, license_record=None):
    if not check_resource_access(candidate, project, tenant) or not check_resource_access(evaluation, project, tenant):
        raise ValueError('Candidate and evaluation must be accessible in the release project.')
    training = _actual_training(candidate, tenant)
    if evaluation.candidate_model_version_id != candidate.pk:
        raise ValueError('The evaluation must reference this exact candidate.')
    if (evaluation.status != 'completed' or not evaluation.job_id or evaluation.job.status != 'succeeded'
            or evaluation.case_results.count() != len(evaluation.suite_version.cases)):
        raise ValueError('Attach a complete durable evaluation with all actual case outputs.')
    from modelanvil.runners.eval_worker import resolve_inputs
    verified = resolve_inputs(evaluation, evaluation.protocol_ref['pins']['max_tokens'])
    if verified['pins'] != evaluation.protocol_ref['pins']:
        raise ValueError('Evaluation pins no longer match the candidate, suite or runtime.')
    release, _ = Release.all_objects.get_or_create(tenant_id=tenant, name=name, defaults={'project_id': project})
    if not check_resource_access(release, project, tenant):
        raise ValueError('This release name is already used outside the selected project.')
    release = Release.all_objects.select_for_update().get(pk=release.pk)
    material = release_model_bundle(ReleaseVersion(tenant_id=tenant, project_id=project, model_version=candidate))
    if not material:
        raise ValueError('This export profile requires a committed CPU reference model bundle.')
    consumer_raw, consumer = _consumer(material['bundle']['config.json']['runtime'])
    current_evidence = _evidence(evaluation, training)
    request = {'export_profile': EXPORT_PROFILE, 'consumer': consumer, 'evidence_digest': digest(current_evidence), 'candidate': str(candidate.model_version_id), 'evaluation': str(evaluation.run_id),
               'min_accuracy': min_accuracy, 'project': str(project) if project else None, 'license_record': license_record}
    request_digest = digest(request)
    existing = release.versions.filter(bundle_manifest__local_review__request_digest=request_digest).first()
    if existing:
        return existing, False
    version = ReleaseVersion.all_objects.create(tenant_id=tenant, project_id=project, release=release,
        revision_no=(release.versions.order_by('-revision_no').values_list('revision_no', flat=True).first() or 0)+1,
        candidate_type='model', candidate_ref=str(candidate.model_version_id), model_version=candidate)
    metrics = current_evidence['metrics']
    accuracy = next((m['value'] for m in metrics if m['key'] == 'accuracy' and m['slice_name'] == 'all'), None)
    baseline_accuracy = next((m['value'] for m in evaluation.protocol_ref.get('baseline_metrics', [])
                              if m['key'] == 'accuracy' and m['slice_name'] == 'all'), None)
    license = license_record['spdx'] if license_record else candidate.license_evidence or 'unknown'
    criteria = [
        {'key': 'actual_training', 'required': 'completed worker run and verified output bytes', 'actual': str(training.run_id), 'passed': True},
        {'key': 'held_out_evaluation', 'required': 'complete pinned evaluation', 'actual': str(evaluation.run_id), 'passed': True},
        {'key': 'min_accuracy', 'required': min_accuracy, 'actual': accuracy, 'passed': accuracy is not None and accuracy >= min_accuracy},
        {'key': 'no_regression', 'required': baseline_accuracy, 'actual': accuracy,
         'passed': baseline_accuracy is not None and accuracy is not None and accuracy >= baseline_accuracy},
        {'key': 'license_compliance', 'required': 'recorded supported license', 'actual': license,
         'passed': license in ('apache-2.0', 'mit', 'bsd-3-clause', 'open-rail')},
    ]
    review = {'scope': 'local_cpu_export', 'export_profile': EXPORT_PROFILE, 'export_consumer': consumer,
        'evidence_digest': digest(current_evidence), 'reviewed_at': timezone.now().isoformat(), 'request_digest': request_digest,
        'state': 'approved' if all(c['passed'] for c in criteria) else 'failing', 'criteria': criteria,
        'evaluation_run': str(evaluation.run_id), 'evaluation_pins': verified['pins'], 'metrics': metrics,
        'baseline_metrics': evaluation.protocol_ref.get('baseline_metrics', []),
        'cases': current_evidence['cases'],
        'provenance': {'training_run': str(training.run_id), 'dataset_revision': str(training.dataset_revision.revision_id),
            'base_model_version': str(training.base_model_version.model_version_id), 'recipe': training.recipe_type,
            'committed_steps': training.current_step, 'training_pins': training.hardware_config.get('pins', {})},
        'model_artifact': {'artifact_id': str(material['artifact'].artifact_id), 'sha256': material['artifact'].sha256},
        'production_qualified': False}
    review['license_record'] = license_record or {'spdx': license, 'source': 'Recorded model license evidence'}
    version.model_card = {'name': name, 'license': license, 'intended_use': 'Bounded local CPU reference inference',
        'production_qualified': False, 'model_version': str(candidate.model_version_id)}
    review['model_card_digest'] = digest(version.model_card)
    version.bundle_manifest = {'local_review': review, 'export_consumer': base64.b64encode(consumer_raw).decode()}
    version.manifest_digest = digest(review)
    version.save(update_fields=['bundle_manifest', 'manifest_digest', 'model_card', 'updated_at'])
    return version, True


def candidate_archive(version):
    material, consumer_raw = assert_current_review(version)
    review = version.bundle_manifest['local_review']
    bundle = material['bundle']
    files = {name: json.dumps(value, sort_keys=True, indent=2).encode() for name, value in bundle.items() if name.endswith('.json')}
    files['model.safetensors'] = base64.b64decode(bundle['model.safetensors.b64'], validate=True)
    files['review.json'] = json.dumps(review, sort_keys=True, indent=2).encode()
    files['model-card.json'] = json.dumps(version.model_card, sort_keys=True, indent=2).encode()
    files['NOTICES.txt'] = (f"Recorded model license: {review['license_record']['spdx']}\n"
        f"License evidence: {json.dumps(review['license_record'], sort_keys=True)}\n"
        'This archive is a bounded CPU reference model. Review failures remain in review.json.\n'
        'Unknown or failing license evidence does not grant redistribution rights.\n'
        'The base reference and training/data pins are in review.json; this full model includes all required weights.\n'
        'No production or hardware qualification is asserted.\n').encode()
    runtime = bundle['config.json']['runtime']
    files['infer.py'] = consumer_raw
    files['README.txt'] = b'Unzip into a new folder. Run: python -I infer.py . --prompt x --max-tokens 2\nThe consumer uses only the Python standard library and checks manifest hashes.\n'
    manifest = {'schema_version': EXPORT_PROFILE, 'runtime': runtime,
        'release_version': str(version.release_version_id), 'production_qualified': False,
        'files': {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)} for name, raw in files.items()}}
    files['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980,1,1,0,0,0))
            info.create_system = 3; info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return output.getvalue()
