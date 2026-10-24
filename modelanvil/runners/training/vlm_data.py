"""Verified paired image/text samples; image imports do not imply model compatibility."""
import hashlib
import json
import uuid

from modelanvil.artifacts.models import Artifact
from modelanvil.runners.inference import verified_artifact
from modelanvil.runners.training.hf_runtime import file_ref
from modelanvil.runners.training.runtime import read_artifact, digest
from . import vlm_math


def image_artifact(identifier, tenant, project):
    try:
        identifier = uuid.UUID(str(identifier))
        artifact = Artifact.all_objects.get(artifact_id=identifier, tenant_id=tenant)
    except (ValueError, TypeError, Artifact.DoesNotExist):
        raise ValueError('Vision input requires an accessible committed image artifact UUID.') from None
    verified_artifact(file_ref(artifact), tenant, project)
    if not 0 < artifact.byte_size <= 2 * 1024**2 or artifact.media_type not in ('image/png', 'image/jpeg'):
        raise ValueError('Vision input requires a local PNG/JPEG artifact of at most 2 MiB.')
    return artifact


def read_image(identifier, tenant, project):
    artifact = image_artifact(identifier, tenant, project)
    image, observed = vlm_math.decode_image(read_artifact(artifact, tenant, project), artifact.media_type)
    return image, {**observed, 'artifact': file_ref(artifact)}


def samples(dataset, processor, tenant, project):
    from contracts import validate_envelope, InvalidDocumentError
    from modelanvil.identity.models import check_resource_access
    if (dataset is None or dataset.state != 'published' or not dataset.manifest_artifact_id
            or not check_resource_access(dataset, project, tenant)):
        raise ValueError('Publish an accessible paired vision dataset before training.')
    raw = read_artifact(dataset.manifest_artifact, tenant, project)
    if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
        raise ValueError('Vision dataset manifest changed; publish a new revision.')
    try: manifest = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError): raise ValueError('Vision dataset manifest is malformed.') from None
    if not isinstance(manifest, dict): raise ValueError('Vision dataset manifest must be an object.')
    rows, splits = manifest.get('rows'), manifest.get('split_manifest')
    if (not isinstance(rows, list) or not 3 <= len(rows) <= 32 or not isinstance(splits, dict)
            or set(splits) != {'train', 'validation', 'test'}
            or any(not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids) for ids in splits.values())):
        raise ValueError('Vision training requires 3–32 paired rows and nonempty train, validation and protected test splits.')
    named = {identifier: split for split, ids in splits.items() for identifier in ids}
    if sum(map(len, splits.values())) != len(named) or len(rows) != len(named):
        raise ValueError('Vision split identifiers overlap or do not cover all paired rows.')
    groups, assets, seen, result = {}, {}, set(), {name: [] for name in splits}
    for row in rows:
        try: validate_envelope(row)
        except (InvalidDocumentError, TypeError, ValueError): raise ValueError('Vision rows must use the canonical sample-envelope schema.') from None
        identifier, group = row['sample_id'], row['source_group_id'].strip()
        split = named.get(identifier)
        if split is None or identifier in seen or not group or len(group) > 128:
            raise ValueError('Vision row IDs and source groups must resolve to unique protected splits.')
        seen.add(identifier)
        blocks = row['blocks']
        if (len(blocks) != 3 or [(b['type'], b.get('role')) for b in blocks] !=
                [('image', 'user'), ('text', 'user'), ('text', 'assistant')]):
            raise ValueError('Vision rows require one user image, one user question and one assistant answer in that order.')
        ref = blocks[0]['asset_ref']
        if not ref.startswith('artifact:'):
            raise ValueError('Vision image references must be artifact:UUID; paths and remote URLs are unsupported.')
        image, pin = read_image(ref.removeprefix('artifact:'), tenant, project)
        if (blocks[0].get('metadata', {}).get('sha256', pin['sha256']) != pin['sha256']
                or blocks[0].get('media_type', pin['media_type']) != pin['media_type']):
            raise ValueError('Paired image hash differs from its declared source asset.')
        for value, ledger in ((group, groups), (pin['sha256'], assets)):
            if value in ledger and ledger[value] != split:
                raise ValueError('Vision source groups or identical image bytes cross protected splits.')
            ledger[value] = split
        question, answer = blocks[1]['text'], blocks[2]['text']
        encoded, prefix = vlm_math.encode(processor, image, question, answer)
        token_ids = encoded['input_ids'][0].tolist()
        result[split].append({'sample_id': identifier, 'source_group_id': group,
            'text': question + '\n' + answer, 'question': question, 'answer': answer, 'image': pin, 'token_ids': token_ids, 'prompt_tokens': prefix,
            'pair_digest': digest({'image_sha256': pin['sha256'], 'text': question + '\n' + answer, 'question': question, 'answer': answer,
                'provenance': row['provenance'], 'source_group_id': group})})
    return result


def materialize(sample, processor, tenant, project):
    image, pin = read_image(sample['image']['artifact']['artifact_id'], tenant, project)
    if pin != sample['image']:
        raise ValueError('Vision image bytes, decoded dimensions or current access changed.')
    encoded, prefix = vlm_math.encode(processor, image, sample['question'], sample['answer'])
    if prefix != sample['prompt_tokens'] or encoded['input_ids'][0].tolist() != sample['token_ids']:
        raise ValueError('Vision processor output differs from the pinned image/text pair.')
    return encoded, prefix
