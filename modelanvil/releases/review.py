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
from modelanvil.releases.artifacts import release_model_bundle
from modelanvil.releases.models import Release, ReleaseVersion
from modelanvil.runners.models import TrainingRun
from modelanvil.runners.training.runtime import digest


@transaction.atomic
def create_candidate_review(*, tenant, project, name, candidate, evaluation, min_accuracy, license_record=None):
    if not check_resource_access(candidate, project, tenant) or not check_resource_access(evaluation, project, tenant):
        raise ValueError('Candidate and evaluation must be accessible in the release project.')
    training = TrainingRun.all_objects.filter(tenant_id=tenant, output_model_version=candidate,
        status='completed', job__status='succeeded').first()
    if training is None:
        raise ValueError('Select a candidate from an actual completed worker training run.')
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
    request = {'candidate': str(candidate.model_version_id), 'evaluation': str(evaluation.run_id),
               'min_accuracy': min_accuracy, 'project': str(project) if project else None, 'license_record': license_record}
    request_digest = digest(request)
    existing = release.versions.filter(bundle_manifest__local_review__request_digest=request_digest).first()
    if existing:
        return existing, False
    version = ReleaseVersion.all_objects.create(tenant_id=tenant, project_id=project, release=release,
        revision_no=(release.versions.order_by('-revision_no').values_list('revision_no', flat=True).first() or 0)+1,
        candidate_type='model', candidate_ref=str(candidate.model_version_id), model_version=candidate)
    material = release_model_bundle(version)
    if not material:
        raise ValueError('This export profile requires a committed CPU reference model bundle.')
    metrics = list(evaluation.metrics.values('key', 'slice_name', 'value', 'sample_count', 'uncertainty_interval'))
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
    review = {'scope': 'local_cpu_export', 'reviewed_at': timezone.now().isoformat(), 'request_digest': request_digest,
        'state': 'approved' if all(c['passed'] for c in criteria) else 'failing', 'criteria': criteria,
        'evaluation_run': str(evaluation.run_id), 'evaluation_pins': verified['pins'], 'metrics': metrics,
        'baseline_metrics': evaluation.protocol_ref.get('baseline_metrics', []),
        'cases': list(evaluation.case_results.values('case_id', 'input_prompt', 'expected_output', 'candidate_output', 'score', 'passed', 'slice_name')),
        'provenance': {'training_run': str(training.run_id), 'dataset_revision': str(training.dataset_revision.revision_id),
            'base_model_version': str(training.base_model_version.model_version_id), 'recipe': training.recipe_type,
            'committed_steps': training.current_step, 'training_pins': training.hardware_config.get('pins', {})},
        'model_artifact': {'artifact_id': str(material['artifact'].artifact_id), 'sha256': material['artifact'].sha256},
        'production_qualified': False}
    review['license_record'] = license_record or {'spdx': license, 'source': 'Recorded model license evidence'}
    version.bundle_manifest = {'local_review': review}
    version.manifest_digest = digest(review)
    version.model_card = {'name': name, 'license': license, 'intended_use': 'Bounded local CPU reference inference',
        'production_qualified': False, 'model_version': str(candidate.model_version_id)}
    version.save(update_fields=['bundle_manifest', 'manifest_digest', 'model_card', 'updated_at'])
    return version, True


def candidate_archive(version):
    review = version.bundle_manifest.get('local_review')
    if not review or digest(review) != version.manifest_digest:
        raise ValueError('Create a frozen local candidate review before downloading weights.')
    material = release_model_bundle(version)
    if not material or material['artifact'].sha256 != review['model_artifact']['sha256']:
        raise ValueError('Reviewed model bytes are unavailable or changed.')
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
    root = Path(__file__).resolve().parents[2]
    runtime = bundle['config.json']['runtime']
    consumer = 'cpu_transformer_infer.py' if 'general-transformer' in runtime else 'cpu_character_infer.py'
    files['infer.py'] = (root / 'scripts' / consumer).read_bytes()
    files['README.txt'] = b'Unzip into a new folder. Run: python -I infer.py . --prompt x --max-tokens 2\nThe consumer uses only the Python standard library and checks manifest hashes.\n'
    manifest = {'schema_version': 'modelanvil.local-export.v1', 'runtime': runtime,
        'release_version': str(version.release_version_id), 'production_qualified': False,
        'files': {name: {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw)} for name, raw in files.items()}}
    files['manifest.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
    return output.getvalue()
