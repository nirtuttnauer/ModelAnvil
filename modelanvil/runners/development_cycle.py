"""Turn failed development cases into a training dataset without touching the protected test."""
from __future__ import annotations

import hashlib
import io
import json
import uuid

from django.db import transaction

from modelanvil.artifacts.models import Artifact, Dataset
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.data.publication import publish_prepared_dataset
from modelanvil.identity.models import check_resource_access
from modelanvil.releases.models import ServingEndpoint
from modelanvil.runners.evidence import evaluation_evidence


def _text(value):
    if not isinstance(value, str):
        return ''
    return value.strip()


@transaction.atomic
def handoff_failed_cases(*, run, corrections, dataset_name):
    """Publish corrected failed cases for a later guided run. Nothing is promoted."""
    if not isinstance(dataset_name, str) or not dataset_name.strip() or len(dataset_name.strip()) > 200:
        raise ValueError('Name the corrected dataset with 1–200 characters.')
    if run.suite_version.protected_role != 'development':
        raise ValueError('Only a development evaluation can seed the next training cycle. Protected final tests stay untouched.')
    if run.status != 'completed' or evaluation_evidence(run).get('level') != 'integrated_execution':
        raise ValueError('Complete an actual development evaluation before correcting cases.')
    if not isinstance(corrections, list) or not corrections or any(not isinstance(item, dict) for item in corrections):
        raise ValueError('Submit at least one corrected failed case.')
    cases = {case.get('case_id'): case for case in run.suite_version.cases or [] if isinstance(case, dict)}
    results = {row.case_id: row for row in run.case_results.all()}
    seen = set()
    rows = []
    endpoints_before = ServingEndpoint.all_objects.filter(tenant_id=run.tenant_id).count()
    for item in corrections:
        case_id = item.get('case_id')
        corrected = _text(item.get('corrected_output'))
        if not isinstance(case_id, str) or case_id in seen:
            raise ValueError('Each correction needs a unique case from this evaluation.')
        seen.add(case_id)
        case = cases.get(case_id)
        result = results.get(case_id)
        group = case.get('source_group_id') if case else None
        prompt = _text(case.get('input_prompt')) if case else ''
        if result is None or result.passed or not isinstance(group, str) or not group.strip() or not prompt or not corrected:
            raise ValueError('Correct only failed development cases that still have their prompt and source group.')
        if len(corrected) > 4000:
            raise ValueError('Corrected answers must be at most 4000 characters.')
        body = prompt + '\n' + corrected
        sample_id = str(uuid.uuid4())
        rows.append({
            'schema_version': '1.0',
            'sample_id': sample_id,
            'source_group_id': group.strip(),
            'blocks': [
                {'block_id': 'user', 'type': 'text', 'role': 'user', 'text': prompt},
                {'block_id': 'assistant', 'type': 'text', 'role': 'assistant', 'text': corrected},
            ],
            'provenance': {
                'source_snapshot_ref': f'evaluation:{run.run_id}',
                'source_record_key': case_id,
                'content_sha256': hashlib.sha256(body.encode()).hexdigest(),
            },
        })
    if not check_resource_access(run, run.project_id, run.tenant_id):
        raise ValueError('This evaluation is not available in the active project.')
    raw = b''.join(json.dumps(row).encode() + b'\n' for row in rows)
    dataset = Dataset.all_objects.create(tenant_id=run.tenant_id, project_id=run.project_id, name=dataset_name.strip(),
        description=f'Corrections from development evaluation {run.run_id}.')
    artifact = Artifact.all_objects.create(
        tenant_id=run.tenant_id, project_id=run.project_id, storage_location_id='local',
        object_key=f'development-cycle/{uuid.uuid4()}.jsonl', sha256=hashlib.sha256(raw).hexdigest(),
        byte_size=len(raw), media_type='application/x-ndjson', metadata={'origin_evaluation': str(run.run_id)})
    upload_staged_artifact(artifact, io.BytesIO(raw), backend=artifact_storage_backend())
    revision = publish_prepared_dataset(dataset, artifact, validation_percent=0, test_percent=0)
    suite = run.suite_version
    suite.protected_role = 'development_inspected'
    suite.save(update_fields=['protected_role', 'updated_at'])
    if ServingEndpoint.all_objects.filter(tenant_id=run.tenant_id).count() != endpoints_before:
        raise ValueError('Development corrections must not change serving.')
    return {
        'dataset_id': str(dataset.dataset_id),
        'revision_id': str(revision.revision_id),
        'source_groups': sorted({row['source_group_id'] for row in rows}),
        'promoted': False,
        'active_release_unchanged': True,
        'production_qualified': False,
        'next_step': 'Train on this dataset, then run a new comparison. The previous candidate stays active until that comparison is accepted.',
    }
