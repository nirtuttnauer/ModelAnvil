"""Bounded operator-run CPU triplet fine-tuning over a verified private manifest."""
import hashlib
import io
import json
import math
import random
import tempfile
import zipfile
from pathlib import Path

from django.db import transaction
from modelanvil.artifacts.models import Artifact, LineageEdge, DeletionTombstone
from modelanvil.artifacts.storage import artifact_storage_backend, upload_staged_artifact
from modelanvil.data.publication import _read_verified_input, _unique_object, _reject_constant
from modelanvil.identity.models import check_resource_access, get_accessible_queryset, Tenant
from modelanvil.runners.models import EvaluationSuiteVersion
from modelanvil.runners.training.runtime import digest
from modelanvil.rag import embedding_adapter as adapter
from modelanvil.rag.models import EmbeddingCandidate, EmbeddingTrainingExposure, EmbeddingSpace
from modelanvil.rag.metrics import compute_all_retrieval_metrics

SCHEMA='modelanvil.embedding-triplets.v1'
MAX_BYTES=1024**2
FILES={'model.safetensors','tokenizer_config.json','config.json','config_sentence_transformers.json',
       'tokenizer.json','sentence_bert_config.json','modules.json','2_Normalize/config.json','1_Pooling/config.json'}


def text(value,limit=32768):
    if not isinstance(value,str) or not value.strip() or len(value.encode())>limit:
        raise ValueError('Manifest strings must be nonempty and within their declared byte bounds.')
    return value


def normalized(value):
    return ' '.join(value.casefold().split())


def group_digest(tenant,value):
    return hashlib.sha256((str(tenant)+'\n'+value).encode()).hexdigest()


def prompt_digest(tenant,value):
    return group_digest(tenant,normalized(value))


def validate_manifest(value):
    if not isinstance(value,dict) or set(value)!={'schema','license','source_uri','documents','triplets','qrels'} or value['schema']!=SCHEMA:
        raise ValueError('Use the exact embedding-triplets.v1 manifest schema.')
    text(value['license'],200);text(value['source_uri'],512)
    docs,triplets,cases=value['documents'],value['triplets'],value['qrels']
    if (not isinstance(docs,list) or not 3<=len(docs)<=100 or not isinstance(triplets,list) or not 1<=len(triplets)<=32
            or not isinstance(cases,list) or not 2<=len(cases)<=64):
        raise ValueError('Supply 3–100 documents, 1–32 training triplets and 2–64 dev/held-out qrels cases.')
    by_id={};groups={};seen={}
    def pin_text(content,split):
        key=normalized(text(content))
        if key in seen and seen[key]!=split:raise ValueError('Normalized text or query overlaps protected source splits.')
        seen[key]=split
    for doc in docs:
        if not isinstance(doc,dict) or set(doc)!={'id','text','source_group','split'}:raise ValueError('Invalid corpus document.')
        key=text(doc['id'],128);group=text(doc['source_group'],128);split=doc['split']
        if split not in ('train','dev','held_out') or key in by_id or (group in groups and groups[group]!=split):
            raise ValueError('Document IDs must be unique; each source group belongs to one protected split.')
        groups[group]=split;by_id[key]=doc;pin_text(doc['text'],split)
    if set(groups.values())!={'train','dev','held_out'}:raise ValueError('Declare independent train, dev and held-out source groups.')
    triplet_ids=set()
    for row in triplets:
        if not isinstance(row,dict) or set(row)!={'id','query','source_group','positive','negative','negative_provenance'}:raise ValueError('Invalid triplet.')
        key=text(row['id'],128);group=text(row['source_group'],128)
        positive,negative=by_id.get(text(row['positive'],128)),by_id.get(text(row['negative'],128))
        provenance=row['negative_provenance']
        if (key in triplet_ids or groups.get(group)!='train' or not positive or not negative or row['positive']==row['negative']
                or positive['source_group']!=group or negative['split']!='train'):
            raise ValueError('Triplets may use only training queries/positive/negative source groups.')
        if (not isinstance(provenance,dict) or set(provenance)!={'kind','model_revision','pool_split','document_id'}
                or provenance['kind'] not in ('manual_reviewed','baseline_mined') or provenance['pool_split']!='train'
                or provenance['document_id']!=row['negative'] or provenance['model_revision']!=adapter.PINS['revision']):
            raise ValueError('Record the exact training-only negative document, method and baseline model revision.')
        triplet_ids.add(key);pin_text(row['query'],'train')
    case_ids=set();splits=set()
    for case in cases:
        if not isinstance(case,dict) or set(case)!={'id','query','source_group','split','grades'}:raise ValueError('Invalid qrels case.')
        key=text(case['id'],128);group=text(case['source_group'],128);split=case['split'];grades=case['grades']
        if key in case_ids or split not in ('dev','held_out') or groups.get(group)!=split:
            raise ValueError('Qrels require distinct IDs and independent dev/held-out groups.')
        if (not isinstance(grades,dict) or not grades or len(grades)>100
                or any(k not in by_id or type(v) is not int or not 0<=v<=3 for k,v in grades.items())
                or any(by_id[k]['source_group']!=group for k,v in grades.items() if v>0)):
            raise ValueError('Declare bounded qrels grades for corpus IDs; positive references must share the query source group.')
        case_ids.add(key);splits.add(split);pin_text(case['query'],split)
    if splits!={'dev','held_out'}:raise ValueError('Include both dev and held-out queries.')
    return value


def read_manifest(source,project):
    if (source.tenant_id!=project.tenant_id or source.project_id!=project.pk or not check_resource_access(source,project.pk,project.tenant_id)
            or source.state!='committed' or source.storage_location_id!='local' or source.object_version is not None or source.byte_size>MAX_BYTES):
        raise ValueError('Use an accessible committed local manifest artifact within 1 MiB.')
    if DeletionTombstone.all_objects.filter(tenant_id=project.tenant_id,resource_id__in=[str(source.artifact_id),source.sha256]).exists():
        raise ValueError('The training manifest has been deleted.')
    raw=_read_verified_input(source,artifact_storage_backend())
    try:value=json.loads(raw,object_pairs_hook=_unique_object,parse_constant=_reject_constant)
    except (ValueError,TypeError,RecursionError):raise ValueError('The triplet manifest must be strict UTF-8 JSON.') from None
    return validate_manifest(value)


@transaction.atomic
def protect_splits(project,value):
    Tenant.objects.select_for_update().get(pk=project.tenant_id)
    train={d['source_group'] for d in value['documents'] if d['split']=='train'}
    train_text={normalized(d['text']) for d in value['documents'] if d['split']=='train'}
    train_text.update(normalized(t['query']) for t in value['triplets'])
    for suite in get_accessible_queryset(EvaluationSuiteVersion,project_id=project.pk,tenant_id=project.tenant_id).exclude(
            protected_role__in=['development','development_inspected','training_feedback_inspected']):
        for case in suite.cases:
            if (case.get('source_group_id') in train or (isinstance(case.get('input_prompt'),str) and normalized(case['input_prompt']) in train_text)):
                raise ValueError('Registered protected evaluation groups/prompts cannot enter embedding training.')
    exposure=get_accessible_queryset(EmbeddingTrainingExposure,project_id=project.pk,tenant_id=project.tenant_id)
    from django.db.models import Q
    train_groups={group_digest(project.tenant_id,g) for g in train}
    train_prompts={prompt_digest(project.tenant_id,t) for t in train_text}
    if exposure.filter(role='held_out').filter(Q(source_group_digest__in=train_groups)|Q(prompt_digest__in=train_prompts)).exists():
        raise ValueError('A previously protected held-out embedding group cannot become training data.')
    held=[d for d in value['documents'] if d['split']=='held_out']+[c for c in value['qrels'] if c['split']=='held_out']
    if exposure.filter(role='training').filter(Q(source_group_digest__in={group_digest(project.tenant_id,d['source_group']) for d in held})
            |Q(prompt_digest__in={prompt_digest(project.tenant_id,d.get('text',d.get('query'))) for d in held})).exists():
        raise ValueError('Previously inspected training text/groups cannot be declared clean held-out evaluation.')
    for row in value['documents']+value['triplets']+value['qrels']:
        role='training' if row.get('split','train')=='train' else 'held_out' if row.get('split')=='held_out' else None
        if role:
            EmbeddingTrainingExposure.all_objects.get_or_create(tenant_id=project.tenant_id,project=project,
                source_group_digest=group_digest(project.tenant_id,row['source_group']),
                prompt_digest=prompt_digest(project.tenant_id,row.get('text',row.get('query'))),role=role)


def evaluate(model,value,cutoff=3):
    docs=value['documents'];ids=[d['id'] for d in docs]
    vectors=model.encode([d['text'] for d in docs],batch_size=16,device='cpu',normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
    vectors=adapter.validate_vectors(vectors,len(docs));results={}
    for split in ('dev','held_out'):
        rows=[]
        for case in [c for c in value['qrels'] if c['split']==split]:
            query=model.encode([case['query']],device='cpu',normalize_embeddings=True,convert_to_numpy=True,show_progress_bar=False)
            query=adapter.validate_vectors(query,1)[0]
            ranked=sorted(zip(ids,(vectors@query).tolist()),key=lambda x:(-x[1],x[0]))[:cutoff]
            metrics=compute_all_retrieval_metrics([key for key,_ in ranked],{key for key,v in case['grades'].items() if v>0},case['grades'],cutoff)
            rows.append({'query_id':case['id'],'retrieved_ids':[key for key,_ in ranked],'metrics':metrics,'positive_qrels':sum(v>0 for v in case['grades'].values())})
        means={key:(sum(r['metrics'][key] for r in rows if r['metrics'][key] is not None)/sum(r['metrics'][key] is not None for r in rows)
                    if any(r['metrics'][key] is not None for r in rows) else None) for key in rows[0]['metrics']}
        results[split]={'queries_total':len(rows),'queries_with_positive_qrels':sum(r['positive_qrels']>0 for r in rows),
                        'cutoff':cutoff,'metrics':means,'queries':rows,'na_semantics':'No positive qrels means N/A; excluded from metric means.'}
    return results


def train_weights(value,target,*,steps,learning_rate,seed):
    adapter.environment();root=adapter.verified_directory()
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(1);torch.manual_seed(seed)
    model=SentenceTransformer(str(root),device='cpu',local_files_only=True,trust_remote_code=False,token=False)
    all_texts=[d['text'] for d in value['documents']]+[r['query'] for r in value['triplets']+value['qrels']]
    for start in range(0,len(all_texts),16):
        tokens=model.tokenizer(all_texts[start:start+16],truncation=False,padding=False,add_special_tokens=True)['input_ids']
        if any(len(row)>256 for row in tokens):raise ValueError('A manifest text exceeds 256 actual model tokens; shorten it explicitly.')
    # Configuration is frozen before any evaluation. Held-out data never enters gradients or mining.
    before=evaluate(model,value);by_id={d['id']:d for d in value['documents']}
    initial=hashlib.sha256(next(model.parameters()).detach().cpu().numpy().tobytes()).hexdigest()
    optimizer=torch.optim.SGD(model.parameters(),lr=learning_rate)
    order=list(value['triplets']);random.Random(seed).shuffle(order);losses=[]
    model.train()
    for step in range(steps):
        row=order[step%len(order)];optimizer.zero_grad(set_to_none=True)
        features=model.tokenizer([row['query'],by_id[row['positive']]['text'],by_id[row['negative']]['text']],
            padding=True,truncation=False,return_tensors='pt')
        features={k:v.to('cpu') for k,v in features.items()}
        embeddings=torch.nn.functional.normalize(model(features)['sentence_embedding'],dim=1)
        loss=torch.nn.functional.softplus((embeddings[0]*embeddings[2]).sum()-(embeddings[0]*embeddings[1]).sum()+.2)
        if not torch.isfinite(loss):raise ValueError('Embedding training produced a nonfinite loss.')
        loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True);optimizer.step()
        losses.append(float(loss.detach()))
    final=hashlib.sha256(next(model.parameters()).detach().cpu().numpy().tobytes()).hexdigest()
    if final==initial:raise ValueError('Training did not change actual model weights.')
    model.eval();after=evaluate(model,value)
    model[0].auto_model.config._name_or_path=adapter.PINS['model']
    model.save_pretrained(str(target),create_model_card=False)
    files={str(p.relative_to(target)):{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'byte_size':p.stat().st_size}
           for p in target.rglob('*') if p.is_file()}
    if set(files)!=FILES:raise ValueError('The saved model layout differs from the qualified export format.')
    if files['model.safetensors']['sha256']==adapter.PINS['files']['model.safetensors']['sha256']:
        raise ValueError('The exported candidate still has unchanged baseline weights.')
    return files,{'baseline':before,'candidate':after,'loss':losses,'initial_parameter_digest':initial,
                  'final_parameter_digest':final,'held_out_role':'inspected_after_frozen_configuration','quality_improvement_claimed':False}


def publish(*,project,source,name,steps=4,learning_rate=.001,seed=7):
    text(name,200)
    if type(steps) is not int or not 1<=steps<=20 or type(seed) is not int or not 0<=seed<2**31:
        raise ValueError('Use 1–20 steps and a nonnegative 31-bit seed.')
    if type(learning_rate) not in (float,int) or not math.isfinite(learning_rate) or not 1e-5<=learning_rate<=.01:
        raise ValueError('Use a finite SGD learning rate between 0.00001 and 0.01.')
    if EmbeddingSpace.all_objects.filter(tenant_id=project.tenant_id,name=name).exists():raise ValueError('Choose a new embedding space name.')
    value=read_manifest(source,project);source_hash=source.sha256;protect_splits(project,value)
    protocol={'schema':SCHEMA,'input_sha256':source_hash,'manifest_digest':digest(value),'baseline':adapter.PINS,
        'steps':steps,'learning_rate':learning_rate,'seed':seed,'optimizer':'sgd','objective':'softplus(cosine_negative-cosine_positive+0.2)',
        'gradient_clip':1.,'device':'cpu','environment':adapter.environment(),'qrels_digest':digest(value['qrels']),
        'source_group_split_digest':digest([(d['id'],d['source_group'],d['split']) for d in value['documents']]),
        'negative_provenance_digest':digest([r['negative_provenance'] for r in value['triplets']]),'metric_cutoff':3,
        'limit':{'steps':20,'triplets':32,'documents':100,'context_tokens':256,'gpu':False},
        'code_digest':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    backend=artifact_storage_backend()
    with tempfile.TemporaryDirectory(prefix='modelanvil-embedding-train-') as folder:
        target=Path(folder)/'model';target.mkdir()
        files,report=train_weights(value,target,steps=steps,learning_rate=learning_rate,seed=seed)
        payload=io.BytesIO()
        with zipfile.ZipFile(payload,'w',compression=zipfile.ZIP_STORED) as archive:
            for file in sorted(files):archive.writestr(zipfile.ZipInfo(file,date_time=(1980,1,1,0,0,0)),(target/file).read_bytes())
            archive.writestr('LICENSE.txt',Path(__file__).with_name('assets').joinpath('LICENSE-2.0.txt').read_bytes())
            archive.writestr('NOTICE.txt',f"Derived from {adapter.PINS['model']} revision {adapter.PINS['revision']}; Apache-2.0. ModelAnvil CPU triplet fine-tuning.\n")
        raw=payload.getvalue()
    # Recheck input bytes, current grants and protected suites before making any candidate visible.
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=project.tenant_id)
        current=Artifact.all_objects.select_for_update().get(pk=source.pk)
        if current.sha256!=source_hash or digest(read_manifest(current,project))!=protocol['manifest_digest']:
            raise ValueError('The training input changed before publication.')
        protect_splits(project,value)
        from modelanvil.core.ids import uuid7
        export=Artifact.all_objects.create(tenant_id=project.tenant_id,project=project,storage_location_id='local',
            object_key=f'embeddings/{uuid7()}/candidate.zip',sha256=hashlib.sha256(raw).hexdigest(),byte_size=len(raw),
            media_type='application/zip',metadata={'kind':'embedding_candidate','input_sha256':source_hash,'protocol_digest':digest(protocol)})
        try:
            upload_staged_artifact(export,io.BytesIO(raw),backend=backend)
            revision=files['model.safetensors']['sha256']
            space=EmbeddingSpace.all_objects.create(tenant_id=project.tenant_id,project=project,name=name,
                model_name=adapter.PINS['model'],model_revision=revision,license_expression='apache-2.0',dimension=384,
                normalized=True,distance_metric='cosine',metadata={'profile_digest':digest(files),'candidate_artifact':str(export.artifact_id)})
            candidate=EmbeddingCandidate.all_objects.create(tenant_id=project.tenant_id,project=project,source=source,export=export,
                space=space,source_digest=source_hash,export_digest=export.sha256,files=files,protocol=protocol,report=report)
            LineageEdge.all_objects.create(tenant_id=project.tenant_id,parent_artifact=source,child_artifact=export,relation='embedding_fine_tune')
            return candidate
        except BaseException:
            backend.delete(project.tenant_id,export.object_key)
            raise
