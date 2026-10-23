"""Actual bounded CPU RAG; source-membership checks never certify answer correctness."""
import hashlib
import importlib.metadata
import re
import time
import unicodedata
from modelanvil.core.tenancy import get_active_project,get_active_tenant
from modelanvil.identity.models import check_resource_access
from modelanvil.rag.models import RAGGeneration,IndexVersion
from modelanvil.rag.retrieval import RetrievalEngine
from modelanvil.rag.workflow import retrieve
from modelanvil.runners import inference
from modelanvil.runners.training.runtime import digest

PROMPT_VERSION='rag-cited-answer-v1'
SYSTEM='Answer the question. If evidence is supplied, use only its facts and cite supporting source numbers in square brackets, for example [1]. If the evidence cannot answer the question, say "I do not know". If no evidence is supplied, answer from your knowledge without citations, or say "I do not know". Do not invent sources.'



def source_pin(chunk):
    if hashlib.sha256(chunk.text.encode()).hexdigest()!=chunk.content_hash:raise ValueError('Source chunk bytes changed.')
    return {'chunk_id':str(chunk.chunk_id),'content_hash':chunk.content_hash,'document_id':str(chunk.document.doc_id),
        'document_revision':chunk.document.revision_no,'document_hash':chunk.document.content_hash}


def index_pin(index):
    return {'index_id':str(index.index_id),'manifest_digest':index.manifest_digest,
        'configuration_digest':digest(index.configuration),'embedding_space_id':str(index.embedding_space_id)}


def checked_sources(index,pins,expected_index=None):
    current_index=IndexVersion.all_objects.select_related('knowledge_base').filter(pk=index.pk,tenant_id=index.tenant_id,status='ready').first()
    if current_index is None or not check_resource_access(current_index) or not check_resource_access(current_index.knowledge_base):
        raise ValueError('Index authorization changed; output was withheld.')
    if expected_index is not None and index_pin(current_index)!=expected_index:
        raise ValueError('Frozen index pins changed; output was withheld.')
    expected={p['chunk_id']:p for p in pins}
    current={str(c.chunk_id):source_pin(c) for c in RetrievalEngine(index).eligible_queryset().filter(chunk_id__in=expected)}
    if current!=expected:raise ValueError('Source content or authorization changed; generation was withheld.')


def citation_result(output,chunks,condition):
    normalized=unicodedata.normalize('NFKC',output)
    markers=re.findall(r'\[([^\[\]]+)\]',normalized)
    allowed={str(i+1):c for i,c in enumerate(chunks)}
    if any(marker not in allowed for marker in markers):return 'validation_refusal','',[],'unknown_citation'
    if re.match(r"\s*(?:I (?:do not|don't) know|insufficient evidence|not enough (?:evidence|information)|cannot answer)",normalized,re.I):
        return 'model_abstain','',[],'model_declared_unknown'
    if not output.strip():return 'validation_refusal','',[],'empty_output'
    if condition!='none' and not markers:return 'validation_refusal','',[],'missing_citation'
    citations=[]
    for label in dict.fromkeys(markers):
        c=allowed[label]
        citations.append({'label':int(label),'chunk_id':str(c.chunk_id),'title':c.document.title,
            'source_uri':c.document.source_uri,'content_hash':c.content_hash,'span_start':c.span_start,'span_end':c.span_end})
    return 'answered',output,citations,'source_membership_validated'


def messages_for(query,chunks,condition):
    evidence='(none)' if condition=='none' else '\n\n'.join(f'[{i+1}] {c.text}' for i,c in enumerate(chunks))
    return [{'role':'system','content':SYSTEM},{'role':'user','content':f'Evidence:\n{evidence}\n\nQuestion: {query}\nAnswer:'}]


def budget(session,query,chunks,condition,max_tokens,policy):
    tokenizer=session['tokenizer'];limit=min(2048,getattr(session['config'],'max_position_embeddings',2048))
    active=list(chunks);omitted=[]
    def count(rows):
        messages=messages_for(query,rows,condition)
        prompt=inference.rendered_prompt(tokenizer,messages,'model')
        ids=tokenizer.encode(prompt,add_special_tokens=not bool(tokenizer.chat_template))
        return messages,prompt,len(ids)
    messages,prompt,tokens=count(active)
    while tokens+max_tokens>limit:
        if policy!='omit_optional_evidence' or not active:
            raise ValueError('Required question/template plus output reserve exceed this context; reduce evidence explicitly or shorten the question.')
        omitted.append(str(active.pop().chunk_id));messages,prompt,tokens=count(active)
    return messages,active,{'input_tokens':tokens,'output_reserve_tokens':max_tokens,'total_reserved_tokens':tokens+max_tokens,
        'runtime_limit_tokens':limit,'remaining_tokens':limit-tokens-max_tokens,'overflow_policy':policy,
        'omitted_chunk_ids':omitted,'supplied_chunk_ids':[str(c.chunk_id) for c in active],
        'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'required_question_preserved':True,
        'chat_template_sha256':hashlib.sha256((tokenizer.chat_template or '').encode()).hexdigest()}


def generate(index,model,project,*,query,condition='retrieved',retrieval_mode='lexical',human_chunk_ids=None,
             top_k=3,max_tokens=64,overflow_policy='fail'):
    if (not isinstance(query,str) or not query.strip() or len(query.encode())>32768 or condition not in ('none','retrieved','human')
            or type(top_k) is not int or not 1<=top_k<=5 or type(max_tokens) is not int or not 1<=max_tokens<=128
            or overflow_policy not in ('fail','omit_optional_evidence') or retrieval_mode not in ('lexical','dense','hybrid')):
        raise ValueError('Use bounded nonempty input, a declared evidence condition/policy and supported retrieval settings.')
    tenant=project.tenant_id
    if (get_active_tenant()!=tenant or get_active_project()!=project.pk or index.tenant_id!=tenant or model.tenant_id!=tenant
            or not check_resource_access(index) or not check_resource_access(index.knowledge_base) or not check_resource_access(model)):
        raise ValueError('Index or model is unavailable in this project.')
    if index.status!='ready':raise ValueError('Select a ready frozen index.')
    if condition!='human' and human_chunk_ids:raise ValueError('Only the human-evidence condition accepts selected chunks.')
    started=time.monotonic();rows=[];engine=RetrievalEngine(index)
    if condition=='retrieved':rows=[r.chunk for r in retrieve(index,query,retrieval_mode,top_k,engine=engine)]
    elif condition=='human':
        ids=human_chunk_ids or []
        if not 1<=len(ids)<=5 or len(set(map(str,ids)))!=len(ids):raise ValueError('Select 1–5 distinct human-evidence chunks.')
        pool={str(c.chunk_id):c for c in RetrievalEngine(index).eligible_queryset().filter(chunk_id__in=ids)}
        if set(map(str,ids))!=set(pool):raise ValueError('Human evidence is outside the currently accessible frozen index.')
        rows=[pool[str(key)] for key in ids]
    elif human_chunk_ids:raise ValueError('No-retrieval condition cannot receive evidence.')
    pins=[source_pin(c) for c in rows];index_pins=index_pin(index)
    plan=inference.snapshot(model,tenant,project.pk)
    if plan.get('format')!='safetensors' or not isinstance(plan.get('files'),dict) or not plan['files']:
        raise ValueError('RAG generation requires a verified local Safetensors text snapshot.')
    model_pins={'model_version_id':str(model.model_version_id),'tokenizer_id':str(model.tokenizer.tokenizer_id),
        'snapshot_digest':digest(plan),'source':plan.get('source'),'files':plan['files']}
    settings={'prompt_version':PROMPT_VERSION,'max_tokens':max_tokens,'temperature':0.,'seed':42,'prompt_format':'model','device':'cpu'}
    receipt={'settings':settings,'model_pins':model_pins,'sources':pins,'retrieved_chunk_ids':[str(c.chunk_id) for c in rows],
        'generation_executed':False,'citation_validation':'source_membership_only','answer_correctness_verified':False,
        'retrieval_mode':retrieval_mode if condition=='retrieved' else condition,
        'index_pins':index_pins,'retrieval_config':engine.settings(top_k) if condition=='retrieved' else None}
    answer=raw='';citations=[];status='policy_abstain'
    if condition!='none' and not rows:
        receipt.update(reason='no_authorized_evidence',budget=None,usage=None)
    else:
        with inference.local_session(model,tenant=tenant,project=project.pk,device='cpu') as session:
            if session['format']!='safetensors':raise ValueError('RAG generation currently requires a supported local Safetensors text snapshot.')
            messages,supplied,counts=budget(session,query,rows,condition,max_tokens,overflow_policy)
            receipt['budget']=counts
            receipt['environment']={p:importlib.metadata.version(p) for p in ['torch','transformers','tokenizers','safetensors']}
            if condition!='none' and not supplied:
                receipt.update(reason='all_optional_evidence_omitted',usage=None)
            else:
                events=list(inference.generate(session,messages,max_tokens=max_tokens,temperature=0.,seed=42,prompt_format='model'))
                raw=''.join(e.get('text','') for e in events);final=next((e for e in reversed(events) if 'usage' in e),{})
                if not final or final['usage']['prompt_tokens']!=counts['input_tokens']:
                    raise ValueError('Actual inference input usage differs from the compiled token count.')
                receipt.update(generation_executed=True,usage=final['usage'],finish_reason=final['finish_reason'])
                status,answer,citations,reason=citation_result(raw,supplied,condition);receipt['reason']=reason
    # No generated answer escapes a source/model revocation during local inference.
    checked_sources(index,pins,index_pins)
    from modelanvil.runners.models import ModelVersion
    current=ModelVersion.all_objects.get(pk=model.pk,tenant_id=tenant)
    if digest(inference.snapshot(current,tenant,project.pk))!=model_pins['snapshot_digest']:
        raise ValueError('Model pins changed during generation; output was withheld.')
    receipt['elapsed_ms']=round((time.monotonic()-started)*1000,3)
    return RAGGeneration.all_objects.create(tenant_id=tenant,project=project,index=index,model_version=model,
        condition=condition,query=query,status=status,answer=answer,raw_output=raw,citations=citations,receipt=receipt)


def visible(run):
    try:
        if not check_resource_access(run) or not check_resource_access(run.model_version):return None
        checked_sources(run.index,run.receipt['sources'],run.receipt['index_pins'])
        if digest(inference.snapshot(run.model_version,run.tenant_id,get_active_project()))!=run.receipt['model_pins']['snapshot_digest']:return None
    except (ValueError,KeyError):return None
    return {'run_id':str(run.run_id),'model_version_id':str(run.model_version.model_version_id),'condition':run.condition,
        'query':run.query,'status':run.status,'answer':run.answer,'raw_output':run.raw_output,'citations':run.citations,
        'receipt':run.receipt,'created_at':run.created_at.isoformat()}
