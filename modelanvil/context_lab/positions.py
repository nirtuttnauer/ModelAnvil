"""Actual fixed-protocol local CPU evidence-position measurements; no simulated scores."""
import hashlib
import importlib.metadata
import json
import platform
import statistics
import subprocess
import sys
import unicodedata
from pathlib import Path
from modelanvil.core.tenancy import get_active_project,get_active_tenant
from modelanvil.runners import inference
from modelanvil.runners.training.runtime import digest

PROTOCOL=json.loads(Path(__file__).with_name('position-protocol.json').read_text())


def normalize(value):
    return ' '.join(unicodedata.normalize('NFKC',value).casefold().split()).removesuffix('.')


def messages(case,position):
    distractors=[PROTOCOL['distractor'].format(number=n+1) for n in range(PROTOCOL['distractor_count'])]
    offset={'start':0,'middle':len(distractors)//2,'end':len(distractors)}[position]
    distractors.insert(offset,case['fact'])
    evidence='\n\n'.join(distractors)
    return [{'role':'system','content':PROTOCOL['system']},
            {'role':'user','content':f"Evidence:\n{evidence}\n\nQuestion: {case['question']}\nAnswer:"}]


def summarize(rows):
    result={}
    for position in PROTOCOL['positions']:
        selected=[r for r in rows if r['position']==position]
        repeats=[sum(r['correct'] for r in selected if r['repeat']==i)/len(PROTOCOL['cases']) for i in range(PROTOCOL['repeats'])]
        result[position]={'correct':sum(r['correct'] for r in selected),'total':len(selected),
            'accuracy':sum(r['correct'] for r in selected)/len(selected),
            'repeat_accuracies':repeats,'repeat_accuracy_stddev':statistics.pstdev(repeats),
            'unique_outputs_by_case':{case['case_id']:len({r['output'] for r in selected if r['case_id']==case['case_id']}) for case in PROTOCOL['cases']}}
    edge=(result['start']['accuracy']+result['end']['accuracy'])/2
    return {'positions':result,'edge_mean_minus_middle':edge-result['middle']['accuracy'],
            'middle_dip_observed':result['middle']['accuracy']<edge,
            'interpretation':'Descriptive three-case authored fixture only; no significance or general context-window claim.'}


def run(model):
    tenant,project=get_active_tenant(),get_active_project()
    before=inference.snapshot(model,tenant,project)
    if before.get('format')!='safetensors':raise ValueError('The real position protocol requires a supported verified local Safetensors snapshot.')
    rows=[];settings=PROTOCOL['decoding']
    with inference.local_session(model,tenant=tenant,project=project,device='cpu') as session:
        import torch
        # Keep the trusted operator/CI fixture bounded; no separate device lease namespace.
        previous_threads=torch.get_num_threads();torch.set_num_threads(1)
        try:
            tokenizer=session['tokenizer'];limit=min(PROTOCOL['context_limit'],session['config'].max_position_embeddings)
            for repeat in range(PROTOCOL['repeats']):
                for number,case in enumerate(PROTOCOL['cases']):
                    order=PROTOCOL['positions'][number:]+PROTOCOL['positions'][:number]
                    if repeat%2:order=list(reversed(order))
                    for position in order:
                        prompt_messages=messages(case,position)
                        prompt=inference.rendered_prompt(tokenizer,prompt_messages,'model')
                        count=len(tokenizer.encode(prompt,add_special_tokens=not bool(tokenizer.chat_template)))
                        if count+settings['max_tokens']>limit:raise ValueError('Complete position fixture and reserved output exceed the runtime context; no evidence was trimmed.')
                        events=list(inference.generate(session,prompt_messages,max_tokens=settings['max_tokens'],temperature=settings['temperature'],seed=settings['seed'],prompt_format='model'))
                        output=''.join(e.get('text','') for e in events)
                        final=next((e for e in reversed(events) if 'usage'in e),None)
                        if final is None or final['usage']['prompt_tokens']!=count:raise ValueError('Actual position usage differs from the complete tokenizer count.')
                        rows.append({'case_id':case['case_id'],'repeat':repeat,'position':position,'expected':case['expected'],
                            'output':output,'correct':normalize(output)==normalize(case['expected']),
                            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'evidence_fact_retained':case['fact'] in prompt,
                            'fact_character_offset':prompt.index(case['fact']),'input_tokens':count,'output_reserve_tokens':settings['max_tokens'],
                            'runtime_limit_tokens':limit,'usage':final['usage'],'finish_reason':final['finish_reason'],'elapsed_seconds':final['elapsed_seconds']})
            environment={'python':sys.version.split()[0],'system':platform.system(),'release':platform.release(),'architecture':platform.machine(),
                'device':'cpu','threads':torch.get_num_threads(),'packages':{p:importlib.metadata.version(p) for p in ['torch','transformers','tokenizers','safetensors']}}
        finally:torch.set_num_threads(previous_threads)
    if digest(inference.snapshot(model,tenant,project))!=digest(before):raise ValueError('Model access or pins changed during the position sweep; report withheld.')
    try:source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).resolve().parents[2],text=True).strip()
    except (OSError,subprocess.CalledProcessError):source=None
    return {'protocol':PROTOCOL,'protocol_digest':digest(PROTOCOL),'fixture_digest':digest(PROTOCOL['cases']),
        'source_commit':source,'model_pins':before,'model_snapshot_digest':digest(before),
        'environment':environment,'runs':rows,'summary':summarize(rows),
        'limits':'Actual CPU runs on a small authored CC0 fixture. Equal fixed decoding is repeated, not resampled. Unique outputs and repeat accuracy variation are measured, including zero variation. This does not qualify arbitrary saved context recipes.'}
