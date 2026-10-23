"""Resolve imported and reviewed preference group IDs without ambiguous aliases."""


def source_group(pair, *, required=False):
    values = [pair['source_group_id']] if 'source_group_id' in pair else []
    metadata = pair.get('metadata')
    if isinstance(metadata, dict) and 'source_group_id' in metadata:
        values.append(metadata['source_group_id'])
    if not values:
        if required: raise ValueError('Every preference row requires a source group ID.')
        return None
    if any(not isinstance(value, str) or not 1 <= len(value.strip()) <= 128 for value in values):
        raise ValueError('Preference source group IDs must contain 1–128 characters.')
    groups = {value.strip() for value in values}
    if len(groups) != 1:
        raise ValueError('Conflicting preference source group IDs.')
    return groups.pop()
