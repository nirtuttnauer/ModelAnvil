"""Independent offline CPU loss proxies on untouched domain/protected corpus test rows."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
sys.path.insert(0,str(Path(__file__).resolve().parent))
import torch
from transformers import AutoTokenizer
from hf_candidate_score import score
from hf_candidate_infer import load_candidate


def encoded_samples(data,tokenizer):
    if not isinstance(data,dict):raise ValueError('Use an evaluation object.')
    for key in ['expected_test_ids','training_and_validation_ids','training_and_validation_groups']:
        if not isinstance(data.get(key),list) or any(not isinstance(v,str) or not v for v in data[key]):raise ValueError('Use explicit string identifiers for every split.')
    rows=data.get('samples');expected=set(data['expected_test_ids'])
    if not isinstance(rows,list) or not 2<=len(rows)<=64 or not expected:
        raise ValueError('Supply 2–64 explicit original corpus test rows and their exact expected identifiers.')
    blocked=set(data.get('training_and_validation_ids',[]));blocked_groups=set(data.get('training_and_validation_groups',[]))
    seen=set();content=set();encoded=[];groups={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('Use explicit test row objects.')
        if row.get('split') not in ('domain_test','protected_test') or not isinstance(row.get('text'),str) or not row['text'].strip():
            raise ValueError('Use explicit domain/protected test text.')
        identifier=row.get('sample_id');group=row.get('source_group_id')
        text_hash=hashlib.sha256(' '.join(unicodedata.normalize('NFKC',row['text']).casefold().split()).encode()).hexdigest()
        if not isinstance(identifier,str) or not isinstance(group,str) or identifier in seen or identifier in blocked or group in blocked_groups or text_hash in content or group in groups and groups[group]!=row['split']:
            raise ValueError('Protected evaluation overlaps training/validation or repeats identifiers/content.')
        seen.add(identifier);content.add(text_hash);groups[group]=row['split']
        ids=tokenizer.encode(row['text'],add_special_tokens=True)
        if not 2<=len(ids)<=128:raise ValueError('Use 2–128 actual tokens per untouched test sample; no truncation.')
        encoded.append((row,ids))
    if seen!=expected or {r['split'] for r in rows}!={'domain_test','protected_test'}:
        raise ValueError('Evaluate every declared test identifier with both independent subsets.')
    return encoded


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-dir',type=Path,required=True);parser.add_argument('--candidate-dir',type=Path,required=True);parser.add_argument('--samples',type=Path,required=True)
    args=parser.parse_args();torch.set_num_threads(1)
    raw=args.samples.read_bytes()
    if len(raw)>1024**2:raise ValueError('Evaluation manifest exceeds 1MiB.')
    data=json.loads(raw);tokenizer=AutoTokenizer.from_pretrained(str(args.base_dir),local_files_only=True,trust_remote_code=False)
    encoded=encoded_samples(data,tokenizer)
    model=load_candidate(args.base_dir).eval();baseline=score(model,encoded);del model;gc.collect()
    model=load_candidate(args.candidate_dir).eval();candidate=score(model,encoded);parameters=sum(p.numel() for p in model.parameters());del model;gc.collect()
    checks={'domain_test_loss_decreased':candidate['domain_test']['loss']<baseline['domain_test']['loss'],
        'protected_test_loss_within_five_percent':candidate['protected_test']['loss']<=baseline['protected_test']['loss']*1.05}
    outputs={'schema_version':'modelanvil.independent-continued-loss.v1','dataset_digest':data['dataset_digest'],'corpus_recipe_digest':data['corpus_recipe_digest'],
        'evaluation_manifest_sha256':hashlib.sha256(raw).hexdigest(),'baseline':baseline,'candidate':candidate,'checks':checks,'proxy_checks_passed':all(checks.values()),
        'domain_loss_gain_fraction':1-candidate['domain_test']['loss']/baseline['domain_test']['loss'],
        'protected_loss_regression_fraction':candidate['protected_test']['loss']/baseline['protected_test']['loss']-1,
        'parameters':parameters,'device':'cpu','precision':'fp32','base_weights_sha256':hashlib.sha256((args.base_dir/'model.safetensors').read_bytes()).hexdigest(),
        'candidate_weights_sha256':hashlib.sha256((args.candidate_dir/'model.safetensors').read_bytes()).hexdigest(),
        'consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules),
        'production_qualified':False,'scope':'Independent token-weighted loss on original untouched corpus test splits. Authored loss proxies do not establish general protected capabilities, customer quality or production readiness.'}
    if outputs['consumer_imported_modelanvil_or_django']:raise ValueError('Independent consumer imported producer code.')
    print(json.dumps(outputs,allow_nan=False))

if __name__=='__main__':main()
