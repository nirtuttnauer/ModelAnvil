"""Verified transcript/audio pairs with protected speaker and source boundaries."""
import io
import hashlib
import json
import uuid

from contracts import validate_envelope, InvalidDocumentError
from modelanvil.artifacts.models import Artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.runners.inference import verified_artifact,copy_verified
from modelanvil.runners.training.hf_runtime import file_ref
from modelanvil.runners.training.runtime import read_artifact, digest
from . import audio_math


def audio_artifact(identifier, tenant, project):
    try:
        artifact = Artifact.all_objects.get(artifact_id=uuid.UUID(str(identifier)), tenant_id=tenant)
    except (ValueError, TypeError, Artifact.DoesNotExist):
        raise ValueError('Audio input requires an accessible committed artifact UUID.') from None
    verified_artifact(file_ref(artifact),tenant,project)
    if not 0 < artifact.byte_size <= 4 * 1024**2 or artifact.media_type not in ('audio/wav','audio/flac'):
        raise ValueError('Use a local PCM16 WAV/FLAC artifact of at most 4 MiB.')
    return artifact


def read_audio(identifier, tenant, project):
    artifact = audio_artifact(identifier,tenant,project)
    raw=io.BytesIO();copy_verified(file_ref(artifact),tenant,project,raw)
    wave,pin=audio_math.decode_audio(raw.getvalue(),artifact.media_type)
    return wave, {**pin,'artifact':file_ref(artifact)}


def _features(processor, wave, text):
    encoded, frames = audio_math.encode(processor,text,wave)
    return encoded, {'token_ids':encoded['input_ids'][0].tolist(),'mel_frames':frames,
        'padded_mel_frames':encoded['labels'].shape[1],
        'mel_sha256':hashlib.sha256(encoded['labels'].detach().contiguous().numpy().tobytes()).hexdigest()}


def samples(dataset, processor, tenant, project):
    if (dataset is None or dataset.state != 'published' or not dataset.manifest_artifact_id
            or not check_resource_access(dataset,project,tenant)):
        raise ValueError('Publish an accessible paired speech dataset before training.')
    raw = read_artifact(dataset.manifest_artifact,tenant,project)
    if hashlib.sha256(raw).hexdigest() != dataset.manifest_digest:
        raise ValueError('Audio dataset manifest changed; publish a new revision.')
    try: manifest = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError): raise ValueError('Audio dataset manifest is malformed.') from None
    if not isinstance(manifest,dict): raise ValueError('Audio dataset manifest must be an object.')
    rows, splits = manifest.get('rows'), manifest.get('split_manifest')
    if (not isinstance(rows,list) or not 3 <= len(rows) <= 32 or not isinstance(splits,dict)
            or set(splits) != {'train','validation','test'}
            or any(not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) for ids in splits.values())):
        raise ValueError('Speech training requires 3–32 paired rows and nonempty train, validation and protected test splits.')
    named = {identifier:split for split,ids in splits.items() for identifier in ids}
    if sum(map(len,splits.values())) != len(named) or len(rows) != len(named):
        raise ValueError('Audio split identifiers overlap or do not cover every paired row.')
    ledgers = [{},{},{},{}]; seen = set(); result = {name:[] for name in splits}
    for row in rows:
        try: validate_envelope(row)
        except (InvalidDocumentError, TypeError, ValueError): raise ValueError('Audio rows require the canonical sample-envelope schema.') from None
        identifier, group = row['sample_id'], row['source_group_id'].strip(); split = named.get(identifier)
        speaker = row.get('metadata',{}).get('speaker_id')
        if (split is None or identifier in seen or not group or len(group)>128
                or not isinstance(speaker,str) or not speaker.strip() or len(speaker)>128):
            raise ValueError('Each audio row needs a unique split identity, source group and declared speaker ID.')
        seen.add(identifier); speaker = speaker.strip(); blocks = row['blocks']
        if len(blocks) != 2 or [(b['type'],b.get('role')) for b in blocks] != [('text','user'),('audio','assistant')]:
            raise ValueError('This TTS profile requires one user transcript and one assistant target-audio artifact; ASR is separate.')
        ref = blocks[1]['asset_ref']
        if not ref.startswith('artifact:'): raise ValueError('Audio references must be artifact:UUID; URLs and paths are unsupported.')
        wave,pin = read_audio(ref.removeprefix('artifact:'),tenant,project)
        if (blocks[1].get('metadata',{}).get('sha256',pin['sha256']) != pin['sha256']
                or blocks[1].get('media_type',pin['media_type']) != pin['media_type']):
            raise ValueError('Paired audio hash or MIME differs from its committed source.')
        if pin['normalized_rms'] < .0001: raise ValueError('This speech profile requires a nonsilent target recording.')
        for value,ledger in zip((group,speaker,pin['sha256'],pin['normalized_sha256']),ledgers):
            if value in ledger and ledger[value] != split:
                raise ValueError('Speaker/source groups or identical decoded audio cross protected splits.')
            ledger[value] = split
        text = blocks[0]['text']; _,features = _features(processor,wave,text)
        result[split].append({'sample_id':identifier,'source_group_id':group,'speaker_id':speaker,
            'text':text,'audio':pin,**features,'pair_digest':digest({'audio':pin,'text':text,'provenance':row['provenance'],
                'source_group_id':group,'speaker_id':speaker})})
    return result


def materialize(sample, processor, tenant, project):
    wave,pin = read_audio(sample['audio']['artifact']['artifact_id'],tenant,project)
    if pin != sample['audio']: raise ValueError('Audio bytes, normalization or current project access changed.')
    encoded,features = _features(processor,wave,sample['text'])
    if any(sample[key] != value for key,value in features.items()):
        raise ValueError('Audio processor, native text encoding or mel target changed after launch.')
    return encoded
