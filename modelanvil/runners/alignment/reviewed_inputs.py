"""Audited owner attestations and exact formal-review export admission for alignment."""
import json
import uuid


def read_reviewed_preferences(artifact, tenant, project):
    from django.db.models import Q
    from modelanvil.identity.models import check_resource_access
    from .execution import read_preferences
    from modelanvil.runners.training.runtime import read_artifact
    if artifact is None or not 0 < artifact.byte_size <= 1024**2:
        raise ValueError('Pin bounded committed preference and regression artifacts.')
    pairs, sha = read_preferences(artifact, tenant=tenant, project=project)
    value = json.loads(read_artifact(artifact, tenant, project))
    review = value.get('review', {})
    owner_reviewed = (isinstance(review, dict) and review.get('method') == 'owner_attestation'
        and review.get('labels_reviewed') is True and bool(review.get('actor_id')))
    if owner_reviewed:
        from modelanvil.core.models import AuditEvent
        try:
            actor = uuid.UUID(str(review['actor_id']))
        except (ValueError, TypeError):
            owner_reviewed = False
        else:
            owner_reviewed = AuditEvent.all_objects.filter(tenant_id=tenant,
                action='preferences.register', resource_type='artifact', resource_id=artifact.artifact_id,
                actor_id=actor, actor_kind=review.get('actor_kind'), result='ok', input_snapshot__sha256=sha
                ).filter(Q(project_id=project) | Q(project_id__isnull=True)).exists()
    formal_reviewed = False
    if artifact.metadata.get('snapshot_id'):
        from modelanvil.annotation.models import CumulativeSnapshot
        snapshot = CumulativeSnapshot.all_objects.select_related('campaign').filter(tenant_id=tenant,
            snapshot_id=artifact.metadata['snapshot_id'],
            qualification__formal_preference__artifact__artifact_id=str(artifact.artifact_id),
            qualification__formal_preference__artifact__sha256=sha,
            qualification__formal_preference__artifact__byte_size=artifact.byte_size).first()
        formal_reviewed = bool(snapshot and check_resource_access(snapshot.campaign, project, tenant))
    if not owner_reviewed and not formal_reviewed:
        raise ValueError('Alignment requires a reviewed preference export or an explicit owner review attestation frozen in the registered bytes.')
    if len({pair['prompt'].strip() for pair in pairs}) != len(pairs):
        raise ValueError('Reviewed preference sets require unique prompts after whitespace trimming.')
    groups = set()
    for pair in pairs:
        group = pair.get('source_group_id')
        if not isinstance(group, str) or not 1 <= len(group.strip()) <= 128:
            raise ValueError('Every reviewed preference/regression row requires a source group ID.')
        groups.add(group.strip())
    return pairs, sha, groups
