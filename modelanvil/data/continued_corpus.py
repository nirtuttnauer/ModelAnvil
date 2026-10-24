"""Bounded immutable pretrained corpora with frozen weighted order and inherited splits."""
import copy
from decimal import Decimal,InvalidOperation
import hashlib
from fractions import Fraction
import io
import json
import random
import unicodedata
from django.db import transaction
from django.utils import timezone
from contracts import validate_envelope
from modelanvil.artifacts.models import Artifact,Dataset,DatasetRevision,LineageEdge,DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend,upload_staged_artifact
from modelanvil.identity.models import check_resource_access
from modelanvil.core.ids import uuid7
from modelanvil.data.publication import _read_verified_input
from modelanvil.data.source_import import _object,_constant

VERSION='modelanvil.continued-corpus.v1'
MAX_BYTES=2*1024**2

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def _plain_text(row):
    try:validate_envelope(row)
    except Exception:raise ValueError('Use valid canonical source envelopes.') from None
    blocks=row['blocks']
    if any(b.get('type')!='text' or b.get('role') or not isinstance(b.get('text'),str) for b in blocks):
        raise ValueError('Continued pretraining accepts only plain-text rows; use SFT for conversations.')
    text='\n'.join(b['text'] for b in blocks)
    if not text.strip():raise ValueError('Corpus text must be nonempty.')
    return text

def _read(revision,tenant,project):
    if (revision.tenant_id!=tenant or revision.state!='published' or not revision.manifest_artifact_id
        or not all(check_resource_access(x,project,tenant) for x in [revision,revision.dataset,revision.manifest_artifact])):
        raise ValueError('Select accessible published source revisions and manifests.')
    artifact=revision.manifest_artifact
    if artifact.state!='committed' or artifact.byte_size>MAX_BYTES or artifact.storage_location_id!='local' or artifact.object_version is not None:
        raise ValueError('Each corpus shard requires a committed local prepared manifest of at most2MiB.')
    if DeletionTombstone.all_objects.filter(tenant_id=tenant,resource_id__in=[str(revision.revision_id),str(revision.dataset.dataset_id),str(artifact.artifact_id),revision.manifest_digest,artifact.sha256]).exists():
        raise ValueError('Corpus source revision or artifact is deleted or revoked.')
    raw=_read_verified_input(artifact,artifact_storage_backend())
    if hashlib.sha256(raw).hexdigest()!=revision.manifest_digest:raise ValueError('Source manifest pins changed.')
    value=json.loads(raw,object_pairs_hook=_object,parse_constant=_constant)
    if not isinstance(value,dict) or not isinstance(value.get('rows'),list) or not 1<=len(value['rows'])<=1000:
        raise ValueError('Each corpus source supports1–1000 canonical rows.')
    splits=value.get('split_manifest',{})
    if not isinstance(splits,dict) or set(splits)!={'train','validation','test'} or any(not isinstance(v,list) for v in splits.values()):
        raise ValueError('Source corpora need explicit train, validation and test splits.')
    ids=[i for group in splits.values() for i in group]
    if (any(not isinstance(i,str) for i in ids) or any(not isinstance(row,dict) or not isinstance(row.get('sample_id'),str) for row in value['rows'])
            or len(set(ids))!=len(ids) or set(ids)!={row['sample_id'] for row in value['rows']}):
        raise ValueError('Source identifiers must occur exactly once in protected splits.')
    for row in value['rows']:_plain_text(row)
    return value


def assemble(sources,*,train_samples,seed):
    if type(train_samples) is not int or not 1<=train_samples<=1000 or not isinstance(seed,str) or not 1<=len(seed)<=128:
        raise ValueError('Use1–1000 training samples and a1–128 character seed.')
    if not 1<=len(sources)<=4 or len({s['pin']['revision_id'] for s in sources})!=len(sources):
        raise ValueError('Use1–4 distinct versioned corpus shards.')
    weights=[];groups={};content={};seen=set();held={'validation':[],'test':[]};trains=[]
    for source in sources:
        try:weight=Decimal(str(source['weight']))
        except (InvalidOperation,ValueError):raise ValueError('Use finite positive decimal weights.') from None
        if not weight.is_finite() or not 0<weight<=1000 or weight.as_tuple().exponent < -3:
            raise ValueError('Weights require at most3 decimal places and must be greater than0 and at most1000.')
        weights.append(int(Fraction(weight)*1000));value=source['prepared'];lookup={i:s for s,ids in value['split_manifest'].items() for i in ids};train=[]
        for row in value['rows']:
            text=_plain_text(row)
            identifier=row['sample_id'];split=lookup.get(identifier);group=row.get('source_group_id',identifier)
            normalized=' '.join(unicodedata.normalize('NFKC',text).casefold().split());key=hashlib.sha256(normalized.encode()).hexdigest()
            if identifier in seen or (group in groups and groups[group]!=split) or (key in content and content[key]!=split):
                raise ValueError('Duplicate identifiers or protected source/content overlap across corpus splits.')
            if key in content:raise ValueError('Duplicate normalized source text across corpus shards; prepare disjoint sources.')
            seen.add(identifier);groups[group]=split;content[key]=split
            copied=copy.deepcopy(row);copied.setdefault('metadata',{})['mixture_source_revision']=source['pin']['revision_id']
            if split=='train':train.append(copied)
            elif split in held:held[split].append(copied)
            else:raise ValueError('Every source row must retain its protected split.')
        if not train:raise ValueError('Every weighted source needs nonempty training rows.')
        trains.append(train)
    total=sum(weights);quotas=[train_samples*w//total for w in weights]
    for i in sorted(range(len(weights)),key=lambda i:(-(train_samples*weights[i]%total),i))[:train_samples-sum(quotas)]:quotas[i]+=1
    if any(q==0 or q>len(rows) for q,rows in zip(quotas,trains)):
        raise ValueError('Requested weighted quotas must include each source and fit its available training rows; weights are not silently rebalanced.')
    rng=random.Random(seed);train=[]
    for rows,quota in zip(trains,quotas):train.extend(rng.sample(rows,quota))
    rng.shuffle(train);rows=train+held['validation']+held['test']
    if len(rows)>1000 or not held['validation'] or not held['test']:
        raise ValueError('A corpus supports at most1000 total rows and requires nonempty protected validation/test splits.')
    components=[{**s['pin'],'weight':f'{w//1000}.{w%1000:03d}','normalized_weight':str(Fraction(w,total)),'train_quota':q} for s,w,q in zip(sources,weights,quotas)]
    recipe={'version':VERSION,'components':components,'seed':seed,'ordering':'seeded_weighted_without_replacement_then_frozen_cyclic_v1',
        'split_policy':'inherit_source_splits_no_reallocation','train_samples':train_samples,'normalization':'NFKC_casefold_whitespace_duplicate_guard_v1'}
    return {'schema_version':'1.0','rows':rows,'row_count':len(rows),'recipe':recipe,'recipe_digest':digest(recipe),
        'split_manifest':{'train':[r['sample_id'] for r in train],**{k:[r['sample_id'] for r in v] for k,v in held.items()}}}


@transaction.atomic
def publish(*,project,name,components,train_samples,seed):
    if not isinstance(name,str) or not name.strip() or len(name)>180:raise ValueError('Use a corpus name of1–180 characters.')
    if not isinstance(components,list) or not 1<=len(components)<=4:raise ValueError('Use1–4 corpus components.')
    sources=[];revisions=[]
    for component in components:
        revision=DatasetRevision.all_objects.select_related('dataset','manifest_artifact').filter(revision_id=component['revision_id'],tenant_id=project.tenant_id).first()
        if revision is None:raise ValueError('Source revision is unavailable.')
        prepared=_read(revision,project.tenant_id,project.pk)
        if prepared.get('recipe',{}).get('version')==VERSION:raise ValueError('Select original source shards; nested corpus mixtures are unavailable.')
        sources.append({'prepared':prepared,'weight':component['weight'],'pin':{'revision_id':str(revision.revision_id),'manifest_digest':revision.manifest_digest,
            'manifest_artifact_id':str(revision.manifest_artifact.artifact_id)}});revisions.append(revision)
    prepared=assemble(sources,train_samples=train_samples,seed=seed);raw=json.dumps(prepared,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>MAX_BYTES:raise ValueError('The complete frozen corpus manifest exceeds2MiB.')
    dataset=Dataset.all_objects.create(tenant_id=project.tenant_id,project=project,name=name.strip())
    artifact=Artifact.all_objects.create(tenant_id=project.tenant_id,project=project,storage_location_id='local',object_key=f'corpora/{uuid7()}.json',
        sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),media_type='application/json',metadata={'kind':VERSION})
    upload_staged_artifact(artifact,io.BytesIO(raw),backend=artifact_storage_backend())
    revision=DatasetRevision.all_objects.create(tenant_id=project.tenant_id,project=project,dataset=dataset,revision_no=1,schema_version='1.0',
        manifest_digest=artifact.sha256,manifest_artifact=artifact,recipe_digest=prepared['recipe_digest'],row_count=len(prepared['rows']),
        state='published',published_at=timezone.now(),metadata={'preparation_kind':VERSION,'recipe':prepared['recipe'],
            'source_group_count':len({r.get('source_group_id',r['sample_id']) for r in prepared['rows']}),
            'split_counts':{k:len(v) for k,v in prepared['split_manifest'].items()}})
    dataset.current_revision=revision;dataset.save(update_fields=['current_revision','updated_at'])
    for parent in revisions:LineageEdge.all_objects.create(tenant_id=project.tenant_id,parent_artifact=parent.manifest_artifact,child_artifact=artifact,
        relation='continued_corpus_source',detail={'source_revision':str(parent.revision_id),'recipe_digest':prepared['recipe_digest']})
    return revision


def pins(revision,tenant,project):
    prepared=_read(revision,tenant,project);recipe=prepared.get('recipe',{})
    if not prepared['split_manifest']['validation'] or not prepared['split_manifest']['test']:
        raise ValueError('Continued pretraining requires protected validation and test rows; training rows are never borrowed.')
    if recipe.get('version')!=VERSION:
        # A single published plain-text source is still an explicit one-shard corpus.
        return {'components':[{'revision_id':str(revision.revision_id),'manifest_digest':revision.manifest_digest,'weight':'1'}],
            'ordering':'published_manifest_order_cyclic','sampler_rng':'none_dropout_disabled'}
    if digest(recipe)!=prepared.get('recipe_digest') or revision.recipe_digest!=prepared['recipe_digest']:
        raise ValueError('Corpus recipe pins changed.')
    for pin in recipe['components']:
        source=DatasetRevision.all_objects.select_related('dataset','manifest_artifact').filter(revision_id=pin['revision_id'],tenant_id=tenant).first()
        if source is None or source.manifest_digest!=pin['manifest_digest'] or str(source.manifest_artifact.artifact_id)!=pin['manifest_artifact_id']:
            raise ValueError('Corpus source pins changed.')
        _read(source,tenant,project)
    return {**recipe,'recipe_digest':prepared['recipe_digest'],'sampler_rng':'frozen_order_no_runtime_sampling_dropout_disabled'}
