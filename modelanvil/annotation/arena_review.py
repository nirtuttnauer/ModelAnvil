"""Informal generated comparisons enter a separate, unlabelled human review batch."""
from django.db import transaction
from modelanvil.annotation.campaign_engine import CampaignEngine
from modelanvil.annotation.models import LabelSchema, RubricRevision, LabelingCampaign
from modelanvil.core.tenancy import get_active_project
from modelanvil.identity.models import check_resource_access, get_accessible_queryset
from modelanvil.runners.models import ChatComparison, EvaluationSuiteVersion


@transaction.atomic
def review_comparison(comparison):
    comparison = ChatComparison.all_objects.select_for_update().select_related('first_request__model_version', 'second_request__model_version').get(pk=comparison.pk)
    if comparison.review_campaign_id:
        campaign = get_accessible_queryset(LabelingCampaign).filter(pk=comparison.review_campaign_id).first()
        if campaign is None: raise ValueError('The review campaign is inaccessible in this project.')
        return campaign, False
    for request in (comparison.first_request, comparison.second_request):
        if request.status != 'completed' or not check_resource_access(request.model_version, get_active_project(), comparison.tenant_id):
            raise ValueError('Comparison models must remain accessible and generated responses must be complete.')
    prompts = {message['content'] for message in comparison.messages if message['role'] == 'user'}
    protected = {case['input_prompt'] for suite in get_accessible_queryset(EvaluationSuiteVersion) for case in suite.cases}
    if prompts & protected:
        raise ValueError('Protected evaluation prompts cannot enter training feedback review.')
    name = f'Arena review {comparison.comparison_id}'
    schema = LabelSchema.all_objects.create(tenant_id=comparison.tenant_id, name=name, kind='preference_ranking')
    rubric = RubricRevision.all_objects.create(tenant_id=comparison.tenant_id, name=name,
        guidelines_text='Independently compare both responses against the exact input. The informal arena vote is not an approved human label. Use blind review and choose candidate_a, candidate_b, tie or abstain.')
    campaign = CampaignEngine().create_campaign(tenant_id=comparison.tenant_id, name=name, label_schema=schema,
        rubric=rubric, seed_mode='manual', max_cycles=1, configuration={'origin': 'informal_arena', 'comparison_id': str(comparison.comparison_id)})
    first, second = comparison.first_request, comparison.second_request
    a, b = (first, second) if comparison.first_is_a else (second, first)
    text_a, text_b = (comparison.first_text, comparison.second_text) if comparison.first_is_a else (comparison.second_text, comparison.first_text)
    sample = {'id': str(comparison.comparison_id), 'prompt': '\n'.join(f'{m["role"]}: {m["content"]}' for m in comparison.messages),
        'candidate_a': text_a, 'candidate_b': text_b, 'arena_vote': comparison.vote,
        'comparison_origin': {'comparison_id': str(comparison.comparison_id), 'messages': comparison.messages,
            'model_a': str(a.model_version.model_version_id), 'model_b': str(b.model_version.model_version_id),
            'configuration_a': a.configuration, 'configuration_b': b.configuration,
            'arena_voter': comparison.voter_id, 'arena_voted_at': comparison.voted_at.isoformat() if comparison.voted_at else None}}
    batch = CampaignEngine().start_batch(campaign, [sample]); batch.status = 'reviewing'; batch.save(update_fields=['status', 'updated_at'])
    comparison.review_campaign = campaign; comparison.save(update_fields=['review_campaign', 'updated_at'])
    return campaign, True
