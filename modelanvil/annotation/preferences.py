"""Formal blind reviews of measured local pairs; informal votes are never labels."""
import hashlib
import json
import secrets
import uuid

from django.db import transaction

from modelanvil.annotation.models import AnnotationRecord, AnnotationTask
from modelanvil.identity.models import ApiKey, Role, get_accessible_queryset
from modelanvil.runners.models import ChatComparison, EvaluationSuiteVersion
from modelanvil.runners.training.runtime import digest

ORIGIN = 'formal_preference'


def formal(campaign):
    return campaign is not None and campaign.configuration.get('origin') == ORIGIN


def principal(request):
    return f'{request.modelanvil_actor_kind}:{request.modelanvil_actor_id}'


def rubric_pin(campaign):
    rubric = campaign.rubric
    if rubric is None or not rubric.guidelines_text.strip():
        raise ValueError('Formal preferences require versioned review guidelines.')
    return {'id': str(rubric.rubric_id), 'revision': rubric.revision_no,
        'guidelines': rubric.guidelines_text, 'criteria': rubric.criteria}


def require_live(campaign):
    if digest(rubric_pin(campaign)) != campaign.configuration['rubric_digest']:
        raise ValueError('The pinned review rubric changed; results are withheld.')


def reviewers(tenant, project):
    return [key for key in ApiKey.objects.filter(tenant_id=tenant, is_active=True, role=Role.REVIEWER)
        if not key.is_expired() and (not key.project_id or key.project_id == project)]


def model_pin(version, tenant, project):
    from modelanvil.runners.inference import snapshot_guard
    from modelanvil.runners.training.hf_runtime import file_ref
    from modelanvil.artifacts.models import Artifact
    guard = snapshot_guard(version, tenant, project)
    return {'model_version': str(version.model_version_id), 'identity': guard.identity,
        'tokenizer': str(version.tokenizer.tokenizer_id),
        'manifest': file_ref(Artifact.all_objects.get(artifact_id=version.artifact_manifest_id, tenant_id=tenant))}


def require_pairs_live(task):
    from modelanvil.runners.models import ModelVersion
    for pin in task.content['_preference']['models']:
        version = ModelVersion.all_objects.select_related('tokenizer').filter(
            model_version_id=pin['model_version'], tenant_id=task.tenant_id).first()
        if version is None or model_pin(version, task.tenant_id, task.campaign.project_id) != pin:
            raise ValueError('A pinned comparison model changed or is unavailable.')
    origin = task.content['_preference']
    if origin.get('source'):
        from modelanvil.annotation.publication import source_configuration
        source = source_configuration(origin['source']['revision'], task.campaign.configuration.get('audit_sample_refs', []))
        if (source['source_manifest_digest'] != origin['source']['manifest_digest']
                or origin['source_group'] in source['protected_source_groups']):
            raise ValueError('Pinned source changed or its group is protected.')
    for suite in get_accessible_queryset(EvaluationSuiteVersion):
        for case in suite.cases:
            if isinstance(case, dict) and (case.get('source_group_id') == origin['source_group']
                    or any(m['content'].strip() == str(case.get('input_prompt', '')).strip() for m in origin['messages'] if m['role'] == 'user')):
                raise ValueError('Protected evaluation inputs cannot enter preference review or export.')


@transaction.atomic
def start_batch(campaign, identifiers, assigned, creator, source_revision=None):
    from modelanvil.annotation.campaign_engine import CampaignEngine
    if (campaign.status != 'active' or campaign.label_schema.kind != 'preference_ranking'
            or campaign.batches.exists() or campaign.seed_mode != 'manual'):
        raise ValueError('Start formal review in a new manual preference campaign.')
    if (not isinstance(identifiers, list) or not 1 <= len(identifiers) <= 32
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError('Select 1–32 distinct measured comparison pairs.')
    eligible_keys = {f'api_key:{key.pk}': key for key in reviewers(campaign.tenant_id, campaign.project_id)}
    eligible = set(eligible_keys)
    if (not isinstance(assigned, list) or not 2 <= len(assigned) <= 8 or len(set(assigned)) != len(assigned)
            or not set(assigned) <= eligible or creator in assigned):
        raise ValueError('Assign 2–8 distinct active project reviewer credentials, separate from the pair creator.')
    owners = [eligible_keys[actor].created_by_id for actor in assigned if eligible_keys[actor].created_by_id]
    if len(set(owners)) != len(owners):
        raise ValueError('Assigned reviewers must use distinct user accounts where credential owners are known.')
    rubric = rubric_pin(campaign)
    source_rows = None
    source_pin = None
    if source_revision:
        from modelanvil.annotation.publication import source_configuration
        from modelanvil.api.resource_inspection import prepared_manifest
        from modelanvil.artifacts.models import DatasetRevision
        from modelanvil.data.detection import sample_text
        config = source_configuration(source_revision, campaign.configuration.get('audit_sample_refs', []))
        revision = get_accessible_queryset(DatasetRevision).get(revision_id=source_revision)
        manifest = prepared_manifest(revision)
        train = set(manifest['split_manifest']['train'])
        source_rows = [row for row in manifest['rows'] if row['sample_id'] in train
            and row['sample_id'] not in config['audit_sample_refs']
            and row['source_group_id'] not in config['protected_source_groups']
            and row.get('metadata', {}).get('training_eligible') is not False
            and all(block['type'] == 'text' for block in row['blocks'])]
        source_pin = {'revision': str(revision.revision_id), 'manifest_digest': revision.manifest_digest}
    protected = {case['input_prompt'] for suite in get_accessible_queryset(EvaluationSuiteVersion)
        for case in suite.cases if isinstance(case, dict) and isinstance(case.get('input_prompt'), str)}
    samples = []
    for identifier in identifiers:
        pair = get_accessible_queryset(ChatComparison).select_for_update().select_related(
            'first_request__model_version__tokenizer', 'second_request__model_version__tokenizer').filter(comparison_id=identifier).first()
        if pair is None or pair.review_campaign_id:
            raise ValueError('Select accessible unused measured pairs.')
        messages = pair.messages
        if any(m['content'] in protected for m in messages if m['role'] == 'user'):
            raise ValueError('Protected evaluation prompts cannot become preference training data.')
        source_row = None
        if source_rows is not None:
            matching = [row for row in source_rows if len(messages) == 1 and messages[0]['role'] == 'user'
                and sample_text(row) == messages[0]['content']]
            if len(matching) != 1:
                raise ValueError('Pair prompts must match one eligible training row in the pinned source; protected groups are excluded.')
            source_row = matching[0]
        records = [(pair.first_request, pair.first_text), (pair.second_request, pair.second_text)]
        generator_ids = [request.principal_id for request, _ in records]
        if set(assigned) & {f'api_key:{identifier}' for identifier in generator_ids}:
            raise ValueError('The credentials that generated a pair cannot review it blindly.')
        generator_owners = set(ApiKey.objects.filter(tenant_id=campaign.tenant_id, pk__in=generator_ids).exclude(
            created_by__isnull=True).values_list('created_by_id', flat=True))
        if generator_owners & set(owners):
            raise ValueError('The users who generated a pair cannot review it blindly.')
        if secrets.randbits(1):
            records.reverse()
        pins = []
        for request, text in records:
            if (request.model_version_id is None or request.status != 'completed'
                    or request.input_digest != digest(messages) or not text.strip()
                    or hashlib.sha256(text.encode()).hexdigest() != request.output_digest):
                raise ValueError('Use complete actual local responses with verified input/output digests.')
            pins.append(model_pin(request.model_version, campaign.tenant_id, campaign.project_id))
        if pins[0]['model_version'] == pins[1]['model_version'] or records[0][1] == records[1][1]:
            raise ValueError('Preference pairs need distinct local models and different responses.')
        from modelanvil.runners.inference import generation_configuration
        settings = [generation_configuration(request.configuration) for request, _ in records]
        if settings[0] != settings[1]:
            raise ValueError('Comparison generation settings must match.')
        from modelanvil.runners.inference import model_chat_template
        raw_prompt = len(messages) == 1 and messages[0]['role'] == 'user' and all(
            request.configuration.get('prompt_format', 'model') == 'plain' or
            request.configuration.get('prompt_format', 'model') == 'model' and not model_chat_template(request.model_version)
            for request, _ in records)
        samples.append({'id': str(uuid.uuid4()), 'prompt': messages[0]['content'] if raw_prompt else json.dumps(messages, ensure_ascii=False),
            'candidate_a': records[0][1], 'candidate_b': records[1][1],
            '_preference': {'comparison': str(pair.comparison_id), 'messages': messages, 'models': pins,
                'requests': [str(request.request_id) for request, _ in records], 'settings': settings,
                'source_group': source_row['source_group_id'] if source_row else digest(messages),
                'source': {**source_pin, 'sample_id': source_row['sample_id'], 'provenance': source_row['provenance']} if source_row else None,
                'raw_single_user_prompt': raw_prompt, 'rubric': rubric}})
        pair.review_campaign = campaign
        pair.save(update_fields=['review_campaign', 'updated_at'])
    campaign.configuration = {**campaign.configuration, 'origin': ORIGIN, 'reviewers': assigned,
        'creator': creator, 'rubric_digest': digest(rubric)}
    campaign.save(update_fields=['configuration', 'updated_at'])
    batch = CampaignEngine().start_batch(campaign, samples)
    batch.status = 'reviewing'; batch.save(update_fields=['status', 'updated_at'])
    return batch


def latest_votes(task):
    votes = {}
    for record in task.records.order_by('-revision_no'):
        if record.reviewer_id in task.campaign.configuration['reviewers'] and not record.is_adjudication:
            votes.setdefault(record.reviewer_id, record)
    return votes


def coverage(batch):
    required = reviewed = agreed = resolved = conflicts = 0
    for task in batch.tasks.all():
        votes = latest_votes(task); count = len(task.campaign.configuration['reviewers'])
        required += count; reviewed += len(votes)
        labels = {r.human_label.get('label') for r in votes.values() if r.decision == 'corrected'}
        complete = len(votes) == count
        agreed += int(complete and len(labels) == 1 and all(r.decision == 'corrected' for r in votes.values()))
        conflicts += int(task.needs_adjudication)
        resolved += int(complete and not task.needs_adjudication)
    return {'required_reviews': required, 'submitted_reviews': reviewed, 'missing_reviews': required-reviewed,
        'unanimous_pairs': agreed, 'resolved_pairs': resolved, 'disagreements': conflicts,
        'agreement_denominator': batch.sample_count, 'agreement_rate': agreed/batch.sample_count if batch.sample_count else None}


def validate_review(task, actor, data, adjudicate):
    require_live(task.campaign); require_pairs_live(task)
    if task.status == 'adjudicated' and not adjudicate:
        raise ValueError('An adjudicated choice requires an explicit manager correction.')
    if adjudicate:
        if len(latest_votes(task)) != len(task.campaign.configuration['reviewers']):
            raise ValueError('Collect every assigned review or explicit abstention before adjudication.')
    elif actor not in task.campaign.configuration['reviewers']:
        raise ValueError('This blind preference task is assigned to other reviewers.')
    if data['decision'] == 'accepted_without_edit':
        raise ValueError('Formal preferences require an independent supplied choice.')
    reason = data['human_label'].get('reason')
    if (set(data['human_label']) - {'label', 'reason'} or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 2000):
        raise ValueError('Record a bounded rubric reason with each review or abstention.')


def reconcile(task, adjudicate):
    votes = latest_votes(task)
    labels = {r.human_label.get('label') if r.decision == 'corrected' else 'abstain' for r in votes.values()}
    task.needs_adjudication = False if adjudicate else len(labels) > 1
    task.status = 'adjudicated' if adjudicate else 'completed'
    task.save(update_fields=['needs_adjudication', 'status', 'updated_at'])


def export(snapshot):
    from modelanvil.runners.model_catalog import _store
    from modelanvil.runners.alignment.execution import validate_preference_pairs
    import io
    require_live(snapshot.campaign)
    pairs = []; excluded = {'tie': 0, 'abstain': 0}
    for task in snapshot.campaign.tasks.filter(batch__cycle_no=snapshot.cycle_no):
        require_pairs_live(task)
        record = task.records.order_by('-revision_no').first()
        if record is None or task.needs_adjudication or len(latest_votes(task)) != len(snapshot.campaign.configuration['reviewers']):
            raise ValueError('Unresolved or missing reviews cannot enter preference export.')
        choice = record.human_label.get('label') if record.decision == 'corrected' else 'abstain'
        if choice not in ('candidate_a', 'candidate_b'):
            excluded['tie' if choice == 'tie' else 'abstain'] += 1
            continue
        content = task.content; origin = content['_preference']
        a, b = ('candidate_a', 'candidate_b') if choice == 'candidate_a' else ('candidate_b', 'candidate_a')
        pairs.append({'prompt': content['prompt'], 'chosen': content[a], 'rejected': content[b],
            'metadata': {'source_group_id': origin['source_group'], 'origin': origin,
                'snapshot': str(snapshot.snapshot_id), 'reviews': [{'record': str(r.record_id), 'revision': r.revision_no,
                    'reviewer': r.reviewer_id, 'choice': r.human_label, 'adjudication': r.is_adjudication} for r in task.records.order_by('revision_no')]}})
    reason = ''
    try:
        validate_preference_pairs(pairs)
        if any(not p['metadata']['origin']['raw_single_user_prompt'] for p in pairs):
            raise ValueError('Current CPU alignment requires exact raw single-user prompts; formatted conversations are exported without alignment eligibility.')
    except ValueError as exc:
        reason = str(exc)
    payload = json.dumps({'schema_version': 'modelanvil.preference-pairs.v1', 'pairs': pairs,
        'excluded': excluded, 'rubric': rubric_pin(snapshot.campaign)}, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    from modelanvil.runners.training.runtime import LIMITS
    if len(payload) > LIMITS['input_bytes']:
        reason = 'Reviewed provenance exceeds the current CPU alignment input byte limit.'
    ref = _store(io.BytesIO(payload), tenant=snapshot.tenant_id, project=snapshot.campaign.project_id,
        name='reviewed-preferences.json', media_type='application/json', metadata={
            'kind': 'reviewed_preferences' if reason else 'alignment_preferences',
            'name': snapshot.campaign.name, 'row_count': len(pairs), 'snapshot_id': str(snapshot.snapshot_id)})
    snapshot.qualification = {'formal_preference': {'artifact': ref, 'alignment_eligible': not bool(reason),
        'reason': reason, 'binary_pairs': len(pairs), 'excluded': excluded,
        'coverage': coverage(snapshot.campaign.batches.get(cycle_no=snapshot.cycle_no))}}
    snapshot.save(update_fields=['qualification', 'updated_at'])
    return ref


def read_export(snapshot):
    import io
    from modelanvil.runners.inference import copy_verified
    require_live(snapshot.campaign)
    for task in snapshot.campaign.tasks.all(): require_pairs_live(task)
    ref = snapshot.qualification['formal_preference']['artifact']
    if ref['byte_size'] > 16 * 1024**2:
        raise ValueError('Preference export exceeds its bounded response size.')
    stream = io.BytesIO(); copy_verified(ref, snapshot.tenant_id, snapshot.campaign.project_id, stream)
    return json.loads(stream.getvalue())
