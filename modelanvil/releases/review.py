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


def guided_review(training, evaluation):
    """Freeze the exact saved comparison decision alongside the selected candidate."""
    from modelanvil.core.activation import comparison_evidence
    from modelanvil.core.models import ImprovementDecision
    from modelanvil.identity.models import Project
    from modelanvil.runners.guided_evaluation import PROFILE, decision_report, native_pair
    if (evaluation.protocol_ref.get('profile') != PROFILE or evaluation.candidate_model_version_id != training.output_model_version_id
            or evaluation.baseline_model_version_id != training.base_model_version_id or evaluation.project_id != training.project_id):
        raise ValueError('The comparison must evaluate this exact trained candidate and its base in the same project.')
    native_pair(evaluation)
    _, evidence_digest, _, _ = comparison_evidence(evaluation, Project.all_objects.get(pk=training.project_id, tenant_id=training.tenant_id))
    decision = ImprovementDecision.all_objects.filter(tenant_id=training.tenant_id, project_id=training.project_id,
        evaluation=evaluation, evidence_digest=evidence_digest).first()
    if decision is None:
        raise ValueError('Record an explicit decision on this complete comparison before exporting its review.')
    return {'scope': 'guided_native_export', 'production_qualified': False, 'training_run': str(training.run_id),
        'candidate_model_version': str(training.output_model_version.model_version_id),
        'baseline_model_version': str(training.base_model_version.model_version_id),
        'selected_checkpoint_step': training.output_model_version.metadata['selected_checkpoint_step'],
        'evaluation_run': str(evaluation.run_id), 'evaluation_pins': evaluation.protocol_ref['pins'],
        'decision': {'decision_id': str(decision.decision_id), 'outcome': decision.outcome, 'evidence_digest': evidence_digest},
        'report': decision_report(evaluation)}


def write_guided_evidence(archive, files, review, *, adapter_only=False, resource_usage=None):
    """Additional entries for an existing native ZIP; weights are never converted."""
    from modelanvil.runners.training.hf_runtime import PACKAGES
    archive.writestr('review.json', json.dumps(review, sort_keys=True, indent=2))
    manifest = {'schema_version': 'modelanvil.reviewed-native.v1',
        'candidate': review['candidate_model_version'], 'evaluation_run': review['evaluation_run'],
        'production_qualified': False, 'files': {name: {'sha256': ref['sha256'], 'byte_size': ref['byte_size']} for name, ref in files.items()},
        'review_sha256': hashlib.sha256(json.dumps(review, sort_keys=True, indent=2).encode()).hexdigest()}
    if resource_usage is not None:
        resources = json.dumps(resource_usage, sort_keys=True, indent=2).encode()
        archive.writestr('resource-usage.json', resources)
        manifest['resource_usage_sha256'] = hashlib.sha256(resources).hexdigest()
    archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, indent=2))
    instructions = ('This archive contains the selected LoRA adapter and its exact pinned base, without merging or conversion.\n'
        'Use a clean Python environment with the following tested package versions: ' + json.dumps({**PACKAGES, 'peft': '0.17.1'}) + '\n'
        'Verify every file against manifest.json before loading. Read review.json for the decision, failures and uncertainty.\n'
        'This export is not production qualified.\n')
    if adapter_only:
        instructions += 'Adapter-only export: obtain the exact base revision and hashes from modelanvil-provenance.json; do not substitute another base.\n'
    else:
        archive.writestr('infer.py', (Path(__file__).resolve().parents[2] / 'scripts' / 'native_adapter_infer.py').read_bytes())
        instructions += 'Independent loader: python -I infer.py . --prompt "Your request" --device mps:0 --max-tokens 32\n'
        instructions += ('The loader verifies hashes, isolates local base files to prevent implicit Hub loading, '
            'loads the adapter with PEFT, renders the exported native chat template, and generates greedily.\n'
            'Use --system for a system instruction matching the evaluation. '
            'The native template, FP32 adapter, pinned base and exact tokenizer must remain together.\n')
    archive.writestr('LOADING.txt', instructions)


def guided_archive(version):
    import shutil
    import tempfile
    from modelanvil.runners.models import EvaluationRun
    from modelanvil.runners.inference import snapshot, staged_snapshot
    review = version.bundle_manifest.get('local_review', {})
    if review.get('scope') != 'guided_native_export' or digest(review) != version.manifest_digest:
        raise ValueError('The frozen guided candidate review is invalid.')
    training = TrainingRun.all_objects.get(tenant_id=version.tenant_id, run_id=review['training_run'])
    evaluation = EvaluationRun.all_objects.get(tenant_id=version.tenant_id, run_id=review['evaluation_run'])
    current = guided_review(training, evaluation)
    if any(review.get(key) != value for key, value in current.items()):
        raise ValueError('The reviewed candidate, decision or evaluation evidence changed.')
    plan = snapshot(version.model_version, version.tenant_id, version.project_id)
    output = tempfile.TemporaryFile()
    try:
        with staged_snapshot(plan['files'], version.tenant_id, version.project_id) as directory:
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED, allowZip64=True) as archive:
                for name in plan['files']:
                    with (directory / name).open('rb') as source, archive.open(name, 'w', force_zip64=True) as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                archive.writestr('modelanvil-provenance.json', json.dumps({'source': plan['source'], 'files': plan['files'],
                    'training_run': review['training_run'], 'selected_checkpoint_step': review['selected_checkpoint_step']}, indent=2))
                from modelanvil.core.activation import evaluation_resources
                write_guided_evidence(archive, plan['files'], review, resource_usage=evaluation_resources(evaluation))
        output.seek(0)
        return output
    except BaseException:
        output.close()
        raise


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
    from modelanvil.runners.eval_worker import verified_evaluation_inputs
    verified = verified_evaluation_inputs(evaluation)
    if verified['pins'] != evaluation.protocol_ref['pins']:
        raise ValueError('Evaluation pins no longer match the candidate, suite or runtime.')
    if evaluation.protocol_ref.get('profile') == 'guided-native':
        review = guided_review(training, evaluation)
        review['request_digest'] = digest({'review': review, 'min_accuracy': min_accuracy, 'license_record': license_record})
        release, _ = Release.all_objects.get_or_create(tenant_id=tenant, name=name, defaults={'project_id': project})
        if not check_resource_access(release, project, tenant):
            raise ValueError('This release name is already used outside the selected project.')
        release = Release.all_objects.select_for_update().get(pk=release.pk)
        existing = release.versions.filter(bundle_manifest__local_review__request_digest=review['request_digest']).first()
        if existing:
            return existing, False
        accuracy = review['report']['candidate']['accuracy']
        license = (license_record['spdx'] if license_record else candidate.license_evidence or 'unknown').lower()
        review['criteria'] = [
            {'key': 'explicit_acceptance', 'required': 'accept', 'actual': review['decision']['outcome'], 'passed': review['decision']['outcome'] == 'accept'},
            {'key': 'min_accuracy', 'required': min_accuracy, 'actual': accuracy, 'passed': accuracy >= min_accuracy},
            {'key': 'no_regression', 'required': 0, 'actual': review['report']['accuracy_delta'], 'passed': review['report']['accuracy_delta'] >= 0},
            {'key': 'license_compliance', 'required': 'recorded supported license', 'actual': license, 'passed': license in ('apache-2.0', 'mit', 'bsd-3-clause', 'open-rail')}]
        review['state'] = 'approved' if all(c['passed'] for c in review['criteria']) else 'failing'
        review['license_record'] = license_record or {'spdx': license, 'source': 'Recorded model license evidence'}
        version = ReleaseVersion.all_objects.create(tenant_id=tenant, project_id=project, release=release,
            revision_no=(release.versions.order_by('-revision_no').values_list('revision_no', flat=True).first() or 0) + 1,
            candidate_type='model', candidate_ref=str(candidate.model_version_id), model_version=candidate,
            bundle_manifest={'local_review': review}, manifest_digest=digest(review),
            model_card={'name': name, 'license': license, 'intended_use': 'Bounded local classification', 'production_qualified': False})
        return version, True
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
