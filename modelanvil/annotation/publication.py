"""Pinned source selection and immutable reviewed text/label publication."""
import hashlib
import io
import json
import uuid
from modelanvil.api.resource_inspection import prepared_manifest
from modelanvil.artifacts.models import Artifact, Dataset, DatasetRevision
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import get_accessible_queryset


def source_configuration(revision_id, audit_refs):
    revision = get_accessible_queryset(DatasetRevision).filter(revision_id=revision_id).first()
    if revision is None:
        raise ValueError('Source revision is unavailable in this project.')
    manifest = prepared_manifest(revision)
    train = set(manifest['split_manifest'].get('train', []))
    protected_groups = {row['source_group_id'] for row in manifest['rows'] if row['sample_id'] not in train or row['sample_id'] in audit_refs}
    protected_ids = [row['sample_id'] for row in manifest['rows'] if row['source_group_id'] in protected_groups]
    return {'source_revision': str(revision.revision_id), 'source_manifest_digest': revision.manifest_digest,
        'protected_source_groups': sorted(protected_groups), 'audit_sample_refs': sorted(set(audit_refs) | set(protected_ids))}


def select_source_samples(campaign, limit=100):
    config = campaign.configuration
    revision = get_accessible_queryset(DatasetRevision).filter(revision_id=config.get('source_revision')).first()
    if not revision or revision.manifest_digest != config.get('source_manifest_digest'):
        raise ValueError('Pinned source revision is unavailable or changed.')
    manifest = prepared_manifest(revision)
    train = set(manifest['split_manifest'].get('train', []))
    protected = set(config.get('protected_source_groups', []))
    seen = set(campaign.tasks.values_list('sample_ref', flat=True))
    fingerprints = {sample_fingerprint(content.get('text', '')) for content in campaign.tasks.values_list('content', flat=True)}
    selected = []
    for row in manifest['rows']:
        if (row['sample_id'] not in train or row['source_group_id'] in protected or row['sample_id'] in seen
                or row.get('metadata', {}).get('training_eligible') is False
                or any(block.get('type') != 'text' for block in row['blocks'])):
            continue
        text = '\n'.join(block['text'] for block in row['blocks'])
        if not text or sample_fingerprint(text) in fingerprints:
            continue
        selected.append({'id': row['sample_id'], 'text': text, 'source_group_id': row['source_group_id'],
            'source_revision': str(revision.revision_id), 'source_manifest_digest': revision.manifest_digest,
            'provenance': row['provenance']})
        fingerprints.add(sample_fingerprint(text))
        if len(selected) >= limit:
            break
    if not selected:
        raise ValueError('No unused, unprotected, training-eligible text samples remain in this source.')
    return selected


def sample_fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def publish_snapshot(snapshot):
    if snapshot.dataset_revision_id or not snapshot.items:
        return snapshot.dataset_revision
    campaign = snapshot.campaign
    if campaign.label_schema.kind not in ('classification', 'text_generation'):
        return None
    rows = []
    protected = set(campaign.configuration.get('protected_source_groups', []))
    for item in snapshot.items:
        content = item['content']; group = content.get('source_group_id', item['sample_ref'])
        if group in protected or item['sample_ref'] in campaign.configuration.get('audit_sample_refs', []):
            raise ValueError('Protected source cannot enter the approved training snapshot.')
        text = content.get('text', content.get('prompt', content.get('input')))
        label = item['human_label'].get('label')
        if not isinstance(text, str) or not isinstance(label, str):
            raise ValueError('Text/label publication requires text source inputs and reviewed string labels.')
        training_text = text + '\n' + label
        rows.append({'schema_version': '1.0', 'sample_id': str(uuid.uuid5(snapshot.snapshot_id, item['sample_ref'])),
            'source_group_id': group, 'blocks': [{'block_id': 'reviewed-text-label', 'type': 'text', 'text': training_text}],
            'provenance': {'source_snapshot_ref': str(snapshot.snapshot_id), 'source_record_key': item['sample_ref'],
                'content_sha256': hashlib.sha256(training_text.encode()).hexdigest()},
            'metadata': {'annotation_snapshot': str(snapshot.snapshot_id), 'source_revision': content.get('source_revision'),
                'source_provenance': content.get('provenance'), 'label_schema_id': str(campaign.label_schema.schema_id),
                'rubric_id': str(campaign.rubric.rubric_id) if campaign.rubric else None, 'reviewer_id': item['reviewer_id'],
                'review_decision': item['decision'], 'label': label, 'input_text': text, 'training_schema': 'text_newline_label_v1'}})
    payload = b''.join(json.dumps(row, ensure_ascii=False).encode() + b'\n' for row in rows)
    artifact = Artifact.all_objects.create(tenant_id=campaign.tenant_id, project_id=campaign.project_id,
        storage_location_id='local', object_key=f'annotation/{snapshot.snapshot_id}/approved.jsonl',
        sha256=hashlib.sha256(payload).hexdigest(), byte_size=len(payload), media_type='application/x-ndjson',
        metadata={'kind': 'approved_annotation', 'snapshot_id': str(snapshot.snapshot_id)})
    upload_staged_artifact(artifact, io.BytesIO(payload), backend=artifact_storage_backend())
    dataset = Dataset.all_objects.create(tenant_id=campaign.tenant_id, project_id=campaign.project_id,
        name=f'{campaign.name} · approved cycle {snapshot.cycle_no}')
    revision = publish_prepared_dataset(dataset, artifact, validation_percent=0, test_percent=0)
    snapshot.dataset_revision = revision
    snapshot.save(update_fields=['dataset_revision', 'updated_at'])
    return revision
