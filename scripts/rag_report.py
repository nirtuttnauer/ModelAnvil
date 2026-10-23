"""Compose actual RAG reports and render their sole public results table (stdlib only)."""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/'docs/engineering/verification/task73-end-to-end-2026-10-23/actual-report.json'
POLICY=json.loads((ROOT/'scripts/rag-reproduction-policy.json').read_text())
START='<!-- rag-results:start -->';END='<!-- rag-results:end -->'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def provenance():
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    brand=platform.processor()
    try:
        if platform.system()=='Darwin':brand=subprocess.check_output(['sysctl','-n','machdep.cpu.brand_string'],text=True).strip()
        elif Path('/proc/cpuinfo').exists():brand=next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),brand)
        memory=int(subprocess.check_output(['sysctl','-n','hw.memsize'],text=True).strip()) if platform.system()=='Darwin' else os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,subprocess.CalledProcessError):memory=None
    return {'commit':commit,'github_run_id':os.environ.get('GITHUB_RUN_ID'),'github_ref':os.environ.get('GITHUB_REF'),
        'github_event':os.environ.get('GITHUB_EVENT_NAME'),'hardware':{'system':platform.system(),'release':platform.release(),
        'architecture':platform.machine(),'cpu':brand,'logical_cpus':os.cpu_count(),'memory_bytes':memory,'gpu_used':False}}


def file_pins(files):
    return {name:{k:value[k] for k in ['sha256','byte_size']} for name,value in files.items()}


def assemble(retrieval,generation,positions,context):
    sha=context['commit'];require(bool(re.fullmatch('[0-9a-f]{40}',sha)),'Missing exact source commit.')
    require(retrieval['commit']==positions['source_commit']==generation['provenance']['commit']==sha,'Reports do not share this exact source commit.')
    require(retrieval['passed'] is True,'Frozen public retrieval control gate failed.')
    for path,value in [('modelanvil/rag/benchmark-corpus-pins.json',retrieval['corpus_pins']),('modelanvil/rag/embedding-pins.json',retrieval['model_pins']),('modelanvil/rag/decoder-pins.json',generation['model']),('modelanvil/context_lab/position-protocol.json',positions['protocol'])]:
        require(value==json.loads((ROOT/path).read_text()),'Pinned input changed: '+path)
    require(positions['protocol_digest']==digest(positions['protocol']),'Position protocol digest changed.')
    require(len(positions['runs'])==18 and len(generation['runs'])==5,'Actual forward schedule/coverage changed.')
    decoder=generation['model'];expected={name:pin for name,pin in decoder['files'].items() if name!='README.md'}
    require(file_pins(positions['model_pins']['files'])==expected,'Position decoder file pins changed.')
    for row in generation['runs']:
        receipt=row['receipt'];require(file_pins(receipt['model_pins']['files'])==expected,'Generation decoder file pins changed.')
        require({c['chunk_id'] for c in row['citations']}<=set((receipt.get('budget') or {}).get('supplied_chunk_ids',[])),'Unbound generation citation.')
        if receipt['generation_executed']:
            require(receipt['usage']['prompt_tokens']==receipt['budget']['input_tokens'],'Generation usage is not the compiled count.')
            require(receipt['usage']['total_tokens']<=receipt['budget']['runtime_limit_tokens'],'Generation context overflow.')
    for row in positions['runs']:
        require(row['evidence_fact_retained'] and row['input_tokens']==row['usage']['prompt_tokens'],'Position evidence or usage changed.')
        require(row['input_tokens']+row['output_reserve_tokens']<=row['runtime_limit_tokens'],'Position context overflow.')
    for mode in ['real','random','full_text']:
        require(retrieval['held_out'][mode]['queries_total']==retrieval['held_out'][mode]['queries_judged']==20,'Unequal held-out relevance coverage.')
    require(all(re.fullmatch('[0-9a-f]{64}',retrieval[k]) for k in ['frozen_input_digest','qrels_digest']),'Missing corpus/qrels digest.')
    return {'schema':'modelanvil.rag-end-to-end.v1','provenance':context,'reproduction_policy':POLICY,
        'inputs_sha256':{k:digest(v) for k,v in [('retrieval',retrieval),('generation',generation),('positions',positions)]},
        'retrieval':retrieval,'generation':generation,'positions':positions,
        'cv_evidence_confirmed':False,'cv_gate':'External verification must confirm a merged-main SHA, green CI on that SHA and its attached report. A report cannot certify its own unfinished CI run.',
        'limits':['Closed 200-document SciFact subset, not a leaderboard or contamination-free claim.',
            'Strict SQL full-text AND is a weak untuned control, not tuned BM25.',
            'Generation citation checks establish source membership, not entailment or general answer correctness.',
            'Position exact match includes code-only formatting; correct-code sentences score zero. Three authored cases, no general middle-dip claim.',
            'CPU-only software qualification; no GPU, customer or production-serving qualification.']}


def compare(reference,current):
    require(reference['reproduction_policy']==current['reproduction_policy']==POLICY,'Reproduction policy changed.')
    left,right=reference['retrieval'],current['retrieval']
    for key in ['corpus_pins','model_pins','protocol','frozen_input_digest','qrels_digest','documents','chunks','index_parameters']:
        require(left[key]==right[key],'Retrieval pins/configuration changed: '+key)
    for mode in ['real','random','full_text']:
        for key in ['queries_total','queries_judged','cutoff']:require(left['held_out'][mode][key]==right['held_out'][mode][key],'Relevance coverage changed.')
        for key,value in left['held_out'][mode]['metrics'].items():
            require(abs(value-right['held_out'][mode]['metrics'][key])<=POLICY['retrieval_metrics_absolute_tolerance'],'Relevance reproduction outside tolerance: '+mode+'/'+key)
    ann=lambda report:{(r['filter_percent'],r['ef_search']):r for r in report['ann_neighbor_recall']['held_out']}
    a,b=ann(left),ann(right);require(a.keys()==b.keys(),'ANN schedule changed.')
    for key,row in a.items():
        require(row['eligible_chunks']==b[key]['eligible_chunks'],'ANN eligible population changed.')
        require(abs(row['mean_neighbor_recall']-b[key]['mean_neighbor_recall'])<=POLICY['ann_mean_neighbor_recall_absolute_tolerance']+1e-12,'ANN reproduction outside tolerance.')
    a,b=reference['generation'],current['generation']
    require(a['model']==b['model'] and a['abstention']==b['abstention'] and a['retrieval_relevance']==b['retrieval_relevance'],'Generation pins/abstention/retrieval summary changed.')
    require([(r['condition'],r['status']) for r in a['runs']]==[(r['condition'],r['status']) for r in b['runs']],'Generation status reproduction failed.')
    for first,second in zip(a['runs'],b['runs']):
        require(first['query']==second['query'] and first['receipt']['settings']==second['receipt']['settings'],'Generation question/decoding changed.')
        one,two=first['receipt'].get('budget'),second['receipt'].get('budget')
        require(bool(one)==bool(two),'Generation forward schedule changed.')
        if one:
            require(all(one[k]==two[k] for k in ['input_tokens','output_reserve_tokens','runtime_limit_tokens','prompt_sha256','chat_template_sha256']),'Generation prompt/template/budget changed.')
    a,b=reference['positions'],current['positions']
    require(a['protocol_digest']==b['protocol_digest'] and a['fixture_digest']==b['fixture_digest'],'Position input pins changed.')
    projection=lambda data:[{k:r[k] for k in ['case_id','repeat','position','prompt_sha256','input_tokens','output_reserve_tokens','runtime_limit_tokens']} for r in data['runs']]
    require(projection(a)==projection(b),'Position actual prompt schedule changed.')
    for key,row in a['summary']['positions'].items():
        other=b['summary']['positions'][key];require(row['total']==other['total'],'Position coverage changed.')
        require(abs(row['accuracy']-other['accuracy'])<=POLICY['position_accuracy_absolute_tolerance']+1e-12,'Position accuracy reproduction outside tolerance.')
    return {'passed':True,'policy':POLICY['id'],'reference_source_commit':reference['provenance']['commit'],
            'current_source_commit':current['provenance']['commit'],'limits':'Raw answer strings and latency are retained but not exact-string or cross-host speed assertions.'}


def table(report):
    r,g,p=report['retrieval'],report['generation'],report['positions']
    lines=[START,'| Measured CPU reference | Result | Scope |','| --- | --- | --- |']
    for mode,label in [('real','MiniLM relevance nDCG@5'),('random','Seeded random-vector nDCG@5'),('full_text','Strict SQL full-text AND nDCG@5')]:
        lines.append(f"| {label} | {r['held_out'][mode]['metrics']['ndcg@5']:.4f} | 20 judged queries; closed 200-document SciFact subset |")
    accepted=sum(row['status']=='answered' for row in g['runs'][:3])
    lines.append(f'| Generation conditions with accepted citations | {accepted}/3 | No evidence / retrieved / human evidence; membership validation only |')
    a=g['abstention'];lines.append(f"| Known-unanswerable outcomes | {a['model_declared_abstentions']} model abstentions, {a['policy_abstentions']} policy abstentions, {a['validation_refusals']} format refusals | {a['known_unanswerable']} authored cases; separate from retrieval relevance |")
    for position in ['start','middle','end']:
        dip='observed' if p['summary']['middle_dip_observed'] else 'not observed'
        row=p['summary']['positions'][position];lines.append(f"| {position.capitalize()} position code-only exact match | {row['accuracy']:.4f} ({row['correct']}/{row['total']}) | Code-only format required; descriptive middle dip {dip} |")
    lines.extend(['',f"Source measurement: `{report['provenance']['commit']}`. [Complete report and reproduction limits](docs/engineering/verification/task73-end-to-end-2026-10-23/report.md). This table is generated only from its saved JSON.",END])
    return '\n'.join(lines)


def readme(report,write=False):
    path=ROOT/'README.md';text=path.read_text();rendered=table(report)
    if START in text:
        updated=text[:text.index(START)]+rendered+text[text.index(END)+len(END):]
    else:
        require(write,'Generated results table missing from README.')
        updated=text.replace('## Current capabilities','## Measured RAG reference\n\n'+rendered+'\n\n## Current capabilities',1)
    if write:path.write_text(updated)
    else:require(text==updated,'README results differ from the saved report; regenerate them.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retrieval');parser.add_argument('--generation');parser.add_argument('--positions');parser.add_argument('--output')
    parser.add_argument('--reference',default=str(REFERENCE));parser.add_argument('--write-readme',action='store_true');parser.add_argument('--check-readme',action='store_true')
    args=parser.parse_args()
    reference=json.loads(Path(args.reference).read_text()) if Path(args.reference).exists() else None
    if args.output:
        require(all([args.retrieval,args.generation,args.positions]),'Supply all three actual reports.')
        report=assemble(*(json.loads(Path(p).read_text()) for p in [args.retrieval,args.generation,args.positions]),provenance())
        failure=None
        if reference:
            try:report['reproduction']=compare(reference,report)
            except ValueError as exc:
                failure=exc;report['reproduction']={'passed':False,'reason':str(exc)}
        with Path(args.output).open('x') as stream:json.dump(report,stream,indent=2,allow_nan=False)
        if failure:raise failure
        print(json.dumps({'report':args.output,'source':report['provenance']['commit'],'reproduced':bool(report.get('reproduction'))}))
    if args.write_readme or args.check_readme:
        require(reference is not None,'Saved reference report missing.')
        readme(reference,args.write_readme)


if __name__=='__main__':main()
