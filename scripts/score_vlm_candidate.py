"""Independent bounded CPU visual holdout scoring from exact file and image hashes."""
import argparse
import gc
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import signal
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','candidate','manifest'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();resource.setrlimit(resource.RLIMIT_CPU,(120,120));signal.alarm(125)
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import torch
    torch.set_num_threads(1);started,cpu=time.monotonic(),time.process_time()
    path=Path(__file__).with_name('vlm_candidate_infer.py')
    spec=importlib.util.spec_from_file_location('independent_vlm_consumer',path);consumer=importlib.util.module_from_spec(spec);spec.loader.exec_module(consumer)
    with args.manifest.open('rb') as stream:raw=stream.read(1024**2+1)
    if not 0<len(raw)<=1024**2:raise ValueError('Visual evaluation manifest exceeds 1 MiB.')
    manifest=json.loads(raw)
    if manifest['source']!=consumer.SOURCE:raise ValueError('Visual evaluation source revision differs.')
    hashes={'base':consumer.verify_files(args.base,manifest['base_files']),
        'candidate':consumer.verify_files(args.candidate,manifest['candidate_files'])}
    if any(hashes['base'][n]!=hashes['candidate'][n] for n in consumer.BASE_NAMES):raise ValueError('Visual evaluation changed the frozen base or processor.')
    cases=manifest['cases']
    if not isinstance(cases,list) or not 1<=len(cases)<=30:raise ValueError('Use1–30 protected visual cases.')
    seen=set()
    for case in cases:
        if (not isinstance(case,dict) or not re.fullmatch(r'case-[0-9]+\.(png|jpg)',case.get('image_filename',''))
                or any(not isinstance(case.get(k),str) or not case[k].strip() for k in ('question','answer','source_group_id','sample_id'))
                or len(case['question'])>512 or len(case['answer'])>256 or case['sample_id'] in seen):
            raise ValueError('Malformed protected visual case.')
        seen.add(case['sample_id'])
        if case['source_group_id'] in manifest['training_groups'] or case['image_sha256'] in manifest['training_image_hashes']:
            raise ValueError('Protected visual source groups/images overlap training.')
        image_path=args.manifest.parent/case['image_filename']
        if consumer.file_hash(image_path)!=case['image_sha256']:raise ValueError('Protected visual image hash changed.')
        consumer.image(image_path,case['media_type'])
    def normalize(text):return text.strip().lower().strip(' .!?\n\t')
    def evaluate(directory):
        model,processor=consumer.load(directory);rows=[];nll=0.;tokens=0
        with torch.inference_mode():
            for case in cases:
                pixels=consumer.image(args.manifest.parent/case['image_filename'],case['media_type'])
                encoded,start=consumer.encode(processor,pixels,case['question'],case['answer'])
                value,count=consumer.score(model,encoded,start)
                if not math.isfinite(value):raise ValueError('Non-finite visual holdout loss.')
                prompt,prefix=consumer.encode(processor,pixels,case['question'])
                if prefix>120:raise ValueError('Visual generation exceeds context bound.')
                output=model.generate(**prompt,max_new_tokens=8,do_sample=False,pad_token_id=processor.tokenizer.pad_token_id)
                answer=processor.tokenizer.decode(output[0,prefix:],skip_special_tokens=True)
                rows.append({'sample_id':case['sample_id'],'image_sha256':case['image_sha256'],'completion':answer,
                    'expected':case['answer'],'exact_match':normalize(answer)==normalize(case['answer']),
                    'negative_log_likelihood':value,'prediction_tokens':count})
                nll+=value;tokens+=count
        model=None;gc.collect()
        return {'loss':nll/tokens,'exact_match':sum(r['exact_match'] for r in rows)/len(rows),'cases':rows,'prediction_tokens':tokens}
    baseline=evaluate(args.base);candidate=evaluate(args.candidate)
    checks={'visual_exact_match_not_regressed':candidate['exact_match']>=baseline['exact_match'],
        'visual_holdout_loss_within_five_percent':candidate['loss']<=baseline['loss']*1.05}
    print(json.dumps({'schema_version':'modelanvil.independent-vlm-evaluation.v1','manifest_sha256':hashlib.sha256(raw).hexdigest(),
        'file_sha256':hashes,'image_sha256':{c['sample_id']:c['image_sha256'] for c in cases},'baseline':baseline,'candidate':candidate,
        'checks':checks,'passed':all(checks.values()),'production_qualified':False,'cpu_seconds':time.process_time()-cpu,
        'wall_seconds':time.monotonic()-started,'consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules)},allow_nan=False))


if __name__=='__main__':main()
