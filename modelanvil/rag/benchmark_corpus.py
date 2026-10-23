"""Hash-pinned public retrieval corpus; no runtime request downloads."""
import hashlib
import json
import os
from pathlib import Path
import tarfile

PINS=json.loads(Path(__file__).with_name('benchmark-corpus-pins.json').read_text())
PROTOCOL=json.loads(Path(__file__).with_name('benchmark-protocol.json').read_text())


def cache_directory():
    return Path(os.environ.get('MODELANVIL_BENCHMARK_CACHE','~/.cache/modelanvil/retrieval-benchmark')).expanduser().resolve()


def cache_corpus():
    import requests
    root=cache_directory();root.mkdir(parents=True,exist_ok=True)
    for name,url,expected,size in [('scifact.tar.gz',PINS['url'],PINS['sha256'],PINS['byte_size']),
            ('LICENSE-upstream.md',PINS['license_url'],PINS['license_sha256'],542)]:
        target=root/name
        if target.exists():
            if target.stat().st_size!=size or hashlib.sha256(target.read_bytes()).hexdigest()!=expected:
                raise ValueError('Cached public corpus/license differs from the fixed pin; preserve it and use a fresh cache directory.')
            continue
        import tempfile
        staged=None
        try:
            with tempfile.NamedTemporaryFile(dir=root,prefix='.download-',delete=False) as out:
                staged=Path(out.name);observed=hashlib.sha256();total=0
                with requests.get(url,stream=True,timeout=(10,30),allow_redirects=False) as response:
                    response.raise_for_status()
                    for block in response.iter_content(65536):
                        total+=len(block)
                        if total>size:raise ValueError('Public corpus download exceeds its pinned size.')
                        observed.update(block);out.write(block)
            if total!=size or observed.hexdigest()!=expected:raise ValueError('Public corpus download checksum differs from the frozen pin.')
            # Atomic no-overwrite publication; a parallel bootstrap never replaces bytes.
            os.link(staged,target)
        finally:
            if staged:staged.unlink(missing_ok=True)
    return root


def load():
    root=cache_directory()
    for name,expected in [('scifact.tar.gz',PINS['sha256']),('LICENSE-upstream.md',PINS['license_sha256'])]:
        path=root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('Bootstrap the pinned public retrieval benchmark cache first.')
    result={}
    with tarfile.open(root/'scifact.tar.gz','r:gz') as archive:
        for name in PINS['members']:
            member=archive.getmember(name)
            if not member.isfile() or member.size>16*1024**2:raise ValueError('Public corpus member exceeds its bounded JSONL layout.')
            result[name]=[json.loads(line) for line in archive.extractfile(member).read().splitlines()]
    docs={str(d['doc_id']):d for d in result['data/corpus.jsonl']}
    claims=result['data/claims_train.jsonl']+result['data/claims_dev.jsonl']
    return docs,claims


def ordered_key(prefix,value):
    return hashlib.sha256((prefix+':'+str(value)).encode()).hexdigest()


def select(docs,claims):
    parent={key:key for key in docs}
    def find(key):
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    def union(left,right):
        a,b=find(left),find(right)
        parent[max(a,b)]=min(a,b)
    for case in claims:
        ids=sorted({str(v) for v in case.get('cited_doc_ids',[])}|set(case['evidence']))
        if any(key not in docs for key in ids):raise ValueError('A claim references a missing corpus document.')
        for other in ids[1:]:union(ids[0],other)
    roles={'development':[],'held_out':[]}
    for case in claims:
        positives=sorted(case['evidence'])
        if not positives:continue
        group=find(positives[0]);role='development' if int(ordered_key('group',group)[:2],16)%2==0 else 'held_out'
        roles[role].append({'id':str(case['id']),'query':case['claim'],'relevant':positives,'source_group':group,'role':role})
    selected=[]
    for role,rows in roles.items():
        rows.sort(key=lambda row:ordered_key('query',row['id']))
        if len(rows)<PROTOCOL['queries_per_split']:raise ValueError('Insufficient independent labeled query groups.')
        selected+=rows[:PROTOCOL['queries_per_split']]
    required={key for row in selected for key in row['relevant']}
    if len(required)>PROTOCOL['document_count']:raise ValueError('Frozen positives exceed the declared corpus bound.')
    ids=sorted(required)
    ids+=sorted(set(docs)-required,key=lambda key:ordered_key('document',key))[:PROTOCOL['document_count']-len(ids)]
    by_role={role:{r['source_group'] for r in selected if r['role']==role} for role in roles}
    if by_role['development']&by_role['held_out']:raise ValueError('Source groups cross the evaluation split.')
    normalized={}
    for row in selected:
        query=' '.join(row['query'].casefold().split())
        if query in normalized and normalized[query]!=row['role']:
            raise ValueError('Duplicate normalized query text crosses the source-group evaluation split.')
        normalized[query]=row['role']
    return [docs[key] for key in ids],selected
