"""Verified, scoped resource inspection and exact lineage for browser handoffs."""
import hashlib
import json
from modelanvil.artifacts.models import Artifact, DatasetRevision, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend
from modelanvil.data.publication import _read_verified_input
from modelanvil.core.tenancy import get_active_project
from modelanvil.identity.models import get_accessible_queryset, check_resource_access
from modelanvil.runners.models import TrainingRun, EvaluationRun
from modelanvil.releases.models import ReleaseVersion


def prepared_manifest(revision):
    artifact = revision.manifest_artifact
    if (revision.state != DatasetRevision.State.PUBLISHED or not artifact
            or artifact.state != Artifact.State.COMMITTED
            or not check_resource_access(artifact, get_active_project() or revision.project_id, revision.tenant_id)
            or DeletionTombstone.all_objects.filter(tenant_id=revision.tenant_id, resource_id=str(artifact.artifact_id)).exists()):
        raise ValueError('The published manifest is unavailable in this project.')
    raw = _read_verified_input(artifact, artifact_storage_backend())
    if hashlib.sha256(raw).hexdigest() != revision.manifest_digest:
        raise ValueError('The manifest bytes no longer match the pinned revision.')
    prepared = json.loads(raw)
    if not isinstance(prepared, dict) or not isinstance(prepared.get('rows'), list):
        raise ValueError('This revision does not contain an inspectable prepared manifest.')
    return prepared


def training_lineage(queryset):
    return [{'run_id': str(run.run_id), 'status': run.status, 'recipe': run.recipe_type,
        'dataset_revision': str(run.dataset_revision.revision_id) if run.dataset_revision_id else None,
        'base_model_version': str(run.base_model_version.model_version_id) if run.base_model_version_id else None,
        'output_model_version': str(run.output_model_version.model_version_id) if run.output_model_version_id else None,
        'recovery_parent': str(run.recovery_parent.run_id) if run.recovery_parent_id else None}
        for run in queryset.select_related('dataset_revision', 'base_model_version', 'output_model_version', 'recovery_parent')]


def model_lineage(version):
    return {'training_runs': training_lineage(get_accessible_queryset(TrainingRun).filter(output_model_version=version)),
        'evaluations': [{'run_id': str(run.run_id), 'status': run.status} for run in
            get_accessible_queryset(EvaluationRun).filter(candidate_model_version=version)],
        'releases': [{'release_version_id': str(item.release_version_id), 'revision_no': item.revision_no, 'status': item.status}
            for item in get_accessible_queryset(ReleaseVersion).filter(model_version=version)],
        'tokenizer_id': str(version.tokenizer.tokenizer_id) if check_resource_access(version.tokenizer, get_active_project() or version.project_id, version.tenant_id) else None,
        'artifacts': [{'artifact_id': str(a.artifact_id), 'sha256': a.sha256, 'byte_size': a.byte_size, 'state': a.state, 'media_type': a.media_type}
            for a in get_accessible_queryset(Artifact).filter(artifact_id=version.artifact_manifest_id)] if version.artifact_manifest_id else []}


def inspect_dataset(revision, cursor=0, query=''):
    prepared = prepared_manifest(revision)
    splits = {id: split for split, ids in prepared.get('split_manifest', {}).items() for id in ids}
    all_rows = prepared['rows']
    rows = [row for row in all_rows if not query or query.casefold() in json.dumps(row, ensure_ascii=False).casefold()]
    page = [{**row, 'assigned_split': splits.get(row['sample_id'], 'not_assigned')} for row in rows[cursor:cursor+25]]
    train_ids = prepared.get('split_manifest', {}).get('train', [])
    text_only = all(all(b.get('type') == 'text' for b in row.get('blocks', [])) for row in all_rows)
    return {'rows': page, 'total': len(rows), 'next_cursor': cursor+25 if cursor+25 < len(rows) else None,
        'source_group_count': prepared.get('source_group_count'), 'recipe': prepared.get('recipe'),
        'split_counts': {key: len(ids) for key, ids in prepared.get('split_manifest', {}).items()},
        'report': prepared.get('report'), 'dropped': prepared.get('dropped', [])[:25],
        'dropped_total': len(prepared.get('dropped', [])),
        'capabilities': {'train': bool(train_ids and text_only), 'annotate': bool(train_ids and text_only),
            'evaluate': False, 'index': False,
            'limits': 'Training still validates the selected model tokenizer and recipe. Dataset-to-evaluation suite and durable index handoffs are not available.'},
        'training_runs': training_lineage(get_accessible_queryset(TrainingRun).filter(dataset_revision=revision))}
