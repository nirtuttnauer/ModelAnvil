"""Session-scoped actual retrieval, citations and bounded reviewed-site research."""
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from django.conf import settings
from modelanvil.core.privacy import require_destination
from modelanvil.core.tenancy import get_active_project,get_active_tenant
from modelanvil.identity.models import check_resource_access
from modelanvil.rag import generation
from modelanvil.rag.ingestion import index_documents
from modelanvil.rag.models import SourceDocument,RAGGeneration
from modelanvil.runners.training.runtime import digest

FETCHER=Path(__file__).resolve().parents[2]/'scripts/research_fetch.py'
LIMITS={'pages_per_step':2,'page_bytes':1024**2,'page_seconds':8,'fetch_wall_seconds':20,'research_steps_per_session':8,
    'answer_tokens':128,'generation_cooperative_seconds':30,'memory_tokens':512,'conversation_turns':20,'index_utf8_bytes':2000000,'cpu_device':'cpu'}


def retrieval_terms(question):
    # PostgreSQL websearch ANDs a natural-language question, including question words.
    stop={'what','which','is','the','of','for','in','a','an','are','do','does','to','and','how','can','you','please'}
    words=list(dict.fromkeys(word.lower() for word in re.findall(r'\w+',question) if word.lower() not in stop and len(word)<=48))[:16]
    if not words:raise ValueError('Use a question containing searchable source terms.')
    return ' OR '.join('"'+word+'"' for word in words)


def authorized(session):
    if (str(session.project_id)!=str(get_active_project()) or session.tenant_id!=get_active_tenant()
        or not all(check_resource_access(x) for x in (session,session.knowledge_base,session.model_version))):
        raise ValueError('Select a research session owned by the active project.')
    if session.model_version.state in ('archived','rejected'):raise ValueError('The session model is unavailable.')
    for turn in session.turns:
        run=RAGGeneration.all_objects.filter(run_id=turn['generation_id'],tenant_id=session.tenant_id,project_id=session.project_id).first()
        if run is None or generation.visible(run) is None:
            raise ValueError('Saved evidence or model authorization changed. Clear conversation memory before continuing; unavailable answers are withheld.')


def payload(session):
    try:authorized(session);valid=True
    except ValueError:valid=False
    documents=[]
    if session.index_id:
        from modelanvil.rag.retrieval import RetrievalEngine
        eligible={c.document_id for c in RetrievalEngine(session.index).get_eligible_chunks()}
        for d in SourceDocument.all_objects.filter(knowledge_base=session.knowledge_base,tenant_id=session.tenant_id):
            documents.append({'document_id':str(d.doc_id),'title':d.title if d.pk in eligible else 'Unavailable source',
                'available':d.pk in eligible,'source_uri':d.source_uri if d.pk in eligible else '',
                'metadata':d.metadata if d.pk in eligible else {}})
    turns=[]
    if valid:
        for t in session.turns:
            run=RAGGeneration.all_objects.get(run_id=t['generation_id'],tenant_id=session.tenant_id)
            turns.append({'question':t['question'],'generation':generation.visible(run)})
    return {'session_id':str(session.session_id),'title':session.title,'revision_no':session.revision_no,
        'model_version':str(session.model_version.model_version_id),'index_id':str(session.index.index_id) if session.index_id else None,
        'turns':turns,'memory':session.memory if valid else {},'evidence_available':valid,'documents':documents,
        'research_steps':session.research_steps if valid else [],'limits':LIMITS,
        'unsupported_inputs':['raw image without qualified OCR','audio without qualified ASR'],
        'search_scope':'Lexical search of explicitly fetched reviewed pages and attached documents; no global search engine or background browsing.'}


def attach(session,documents):
    if SourceDocument.all_objects.filter(knowledge_base=session.knowledge_base).count()+len(documents)>50:
        raise ValueError('Use at most50 source revisions per session.')
    index=index_documents(session.knowledge_base,[{k:d[k] for k in ('title','source_uri','content')} for d in documents],128,16)
    for item in documents:
        doc=SourceDocument.all_objects.filter(knowledge_base=session.knowledge_base,source_uri=item['source_uri']).latest('revision_no')
        doc.metadata=item['metadata'];doc.save(update_fields=['metadata','updated_at'])
    session.index=index;session.revision_no+=1;session.save()
    return payload(session)


def pages(session,urls):
    if not isinstance(urls,list) or not 1<=len(urls)<=2 or len(set(urls))!=len(urls) or len(session.research_steps)>=8:
        raise ValueError('Fetch1–2 distinct reviewed page URLs per step, at most8 steps per session.')
    for url in urls:require_destination(url)
    started=time.monotonic()
    with tempfile.TemporaryFile() as output:
        try:
            result=subprocess.run([sys.executable,'-I',str(FETCHER)],input=json.dumps({'urls':urls,'allow_local':settings.DEBUG}).encode(),
                stdout=output,stderr=subprocess.DEVNULL,timeout=20,env={'PATH':os.defpath})
        except subprocess.TimeoutExpired:raise ValueError('Research exceeded its20-second fetch budget; no sources were indexed.') from None
        if result.returncode:raise ValueError('Page fetch refused or failed within its public-address, TLS, format, byte or time limits; no sources were indexed.')
        output.seek(0);raw=output.read(2*1024**2+1)
    if len(raw)>2*1024**2:raise ValueError('Research output exceeded2MiB.')
    rows=json.loads(raw)['pages']
    if [p['url'] for p in rows]!=urls or any(hashlib.sha256(p['text'].encode()).hexdigest()!=p['text_sha256'] for p in rows):
        raise ValueError('Research output identity changed.')
    for url in urls:require_destination(url)
    documents=[{'title':p['title'],'source_uri':p['url'],'content':p['text'],
        'metadata':{k:v for k,v in p.items() if k not in ('text','title','url')} | {'extraction':'bounded-public-html-text-v1','fetcher_sha256':hashlib.sha256(FETCHER.read_bytes()).hexdigest()}} for p in rows]
    session.research_steps.append({'operation':'fetch','urls':urls,'pages':len(rows),'bytes':sum(p['bytes'] for p in rows),
        'elapsed_seconds':time.monotonic()-started,'wall_budget_seconds':20,'page_byte_budget':1024**2,
        'conversation_or_question_sent':False,'receipts':[d['metadata'] for d in documents]})
    return attach(session,documents)


def ask(session,question,*,max_tokens=64,memory_tokens=256):
    authorized(session)
    from modelanvil.rag import decoder
    from modelanvil.runners import inference
    plan=inference.snapshot(session.model_version,session.tenant_id,session.project_id)
    expected={k:v for k,v in decoder.PINS['files'].items() if k!='README.md'}
    if (plan.get('format')!='safetensors' or set(plan.get('files',{}))!=set(expected)
            or any(plan.get('source',{}).get(k)!=v for k,v in {'repo_id':decoder.PINS['model'],
                'revision':decoder.PINS['revision'],'license':decoder.PINS['license']}.items())):
        raise ValueError('This session requires the exact provisioned CPU RAG decoder snapshot.')
    for name,pin in expected.items():
        artifact=inference.verified_artifact(plan['files'][name],session.tenant_id,session.project_id)
        if artifact.sha256!=pin['sha256'] or artifact.byte_size!=pin['byte_size']:
            raise ValueError('Decoder file pins changed; no model was loaded.')
    if not session.index_id:raise ValueError('Attach a document or fetch a reviewed page before asking.')
    if len(session.turns)>=20:raise ValueError('This session reached20 turns; start a new isolated session.')
    history=[]
    for turn in session.turns:
        history.append({'role':'user','content':turn['question']})
        if turn['answer']:history.append({'role':'assistant','content':turn['answer']})
    run=generation.generate(session.index,session.model_version,session.project,query=question,condition='retrieved',
        retrieval_mode='lexical',retrieval_query=retrieval_terms(question),top_k=3,max_tokens=max_tokens,
        overflow_policy='omit_optional_evidence',history=history,memory_tokens=memory_tokens)
    authorized(session)
    if generation.visible(run) is None:raise ValueError('Evidence changed during generation; output withheld.')
    session.turns.append({'question':question,'answer':run.answer,'generation_id':str(run.run_id)})
    session.memory=run.receipt.get('memory',{});session.revision_no+=1;session.save()
    return payload(session)
