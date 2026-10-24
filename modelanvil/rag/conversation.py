"""Pinned extractive history compaction with actual decoder token counts."""
import hashlib
import json
from pathlib import Path

STRATEGY='verbatim-prefix-recent-v1'
STRATEGY_DIGEST=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def compact(tokenizer, history, *, limit=256):
    if not isinstance(history,list) or len(history)>40 or any(
        not isinstance(m,dict) or set(m)!={'role','content'} or m['role'] not in ('user','assistant')
        or not isinstance(m['content'],str) for m in history):
        raise ValueError('Use at most40 prior user/assistant messages.')
    if sum(len(m['content']) for m in history)>64000:raise ValueError('Saved history exceeds64,000 characters; start a new session.')
    count=lambda text:len(tokenizer.encode(text,add_special_tokens=False))
    render=lambda rows:json.dumps(rows,ensure_ascii=False,separators=(',',':')) if rows else ''
    full=render([{'position':i,**m} for i,m in enumerate(history)]);rows=[];selected=[]
    if count(full)<=limit:
        return full,{'strategy':STRATEGY,'strategy_sha256':STRATEGY_DIGEST,
            'original_tokens':count(full),'retained_tokens':count(full),'token_limit':limit,
            'entries':[{'position':i,'role':m['role'],'retained_characters':len(m['content']),
                'original_characters':len(m['content']),'source_sha256':hashlib.sha256(m['content'].encode()).hexdigest(),
                'verbatim_prefix':True} for i,m in enumerate(history)],'omitted_positions':[],
            'text':full,'generated_summary':False,'compacted':False}
    # Recent messages get first claim; earlier memory is exact prefixes, never generated facts.
    for i in list(range(max(0,len(history)-2),len(history)))+list(range(max(0,len(history)-2))):
        message=history[i];cap=96 if i>=len(history)-2 else 32
        low,high=0,len(message['content'])
        while low<high:
            middle=(low+high+1)//2
            candidate=sorted(rows+[{'position':i,'role':message['role'],'content':message['content'][:middle]}],key=lambda x:x['position'])
            if count(message['content'][:middle])<=cap and count(render(candidate))<=limit:low=middle
            else:high=middle-1
        excerpt=message['content'][:low]
        if not excerpt:continue
        proposed=sorted(rows+[{'position':i,'role':message['role'],'content':excerpt}],key=lambda x:x['position'])
        if count(render(proposed))>limit:continue
        rows=proposed;selected.append({'position':i,'role':message['role'],'source_sha256':hashlib.sha256(message['content'].encode()).hexdigest(),
            'retained_characters':len(excerpt),'original_characters':len(message['content']),'verbatim_prefix':True})
    text=render(rows)
    return text,{'strategy':STRATEGY,'strategy_sha256':STRATEGY_DIGEST,
        'original_tokens':count(full),'retained_tokens':count(text),'token_limit':limit,'entries':sorted(selected,key=lambda x:x['position']),
        'omitted_positions':[i for i in range(len(history)) if i not in {x['position'] for x in rows}],
        'text':text,'generated_summary':False,'compacted':True,
        'retained_evidence':'Source citations remain pinned separately; historical citation numbers are not current evidence.'}
