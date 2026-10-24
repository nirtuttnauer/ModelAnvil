"""Independent exact CPU TTS reload, held-out composite loss and ASR intelligibility proxy."""
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


def words(text): return re.findall(r"[a-z0-9]+(?:'[a-z]+)?",text.casefold())


def word_errors(expected,actual):
    reference,hypothesis=words(expected),words(actual)
    if not reference:raise ValueError('Intelligibility scoring needs a nonempty reference transcript.')
    row=list(range(len(hypothesis)+1))
    for i,left in enumerate(reference,1):
        current=[i]
        for j,right in enumerate(hypothesis,1):current.append(min(current[-1]+1,row[j]+1,row[j-1]+(left!=right)))
        row=current
    return row[-1],len(reference)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('base','candidate','evaluator','manifest'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();resource.setrlimit(resource.RLIMIT_CPU,(120,120));signal.alarm(140)
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false')
    import torch
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    started,cpu=time.monotonic(),time.process_time()
    path=Path(__file__).with_name('audio_candidate_infer.py');spec=importlib.util.spec_from_file_location('independent_audio_consumer',path)
    consumer=importlib.util.module_from_spec(spec);spec.loader.exec_module(consumer)
    with args.manifest.open('rb') as stream:raw=stream.read(1024**2+1)
    if not 0<len(raw)<=1024**2:raise ValueError('Audio evaluation manifest exceeds1MiB.')
    manifest=json.loads(raw)
    if manifest['source']!=consumer.SOURCE:raise ValueError('Audio evaluation source differs.')
    hashes={'base':consumer.verify_files(args.base),'candidate':consumer.verify_files(args.candidate),
        'evaluator':{'evaluator/'+n:consumer.file_hash(args.evaluator/n) for n in consumer.EVALUATOR_HASHES}}
    if any(hashes[name]!=manifest[name+'_files'] for name in hashes):raise ValueError('Audio evaluation checksums differ from the exact producer pins.')
    cases=manifest['cases'];seen=set()
    if not isinstance(cases,list) or not 1<=len(cases)<=4:raise ValueError('Use1–4 protected audio cases.')
    for case in cases:
        if (not re.fullmatch(r'case-[0-9]+\.(wav|flac)',case.get('audio_filename',''))
                or not isinstance(case.get('text'),str) or not case['text'].strip() or len(case['text'])>96
                or case['sample_id'] in seen or case['media_type'] not in ('audio/wav','audio/flac')
                or case['source_group_id'] in manifest['training_groups'] or case['speaker_id'] in manifest['training_speakers']
                or case['audio_sha256'] in manifest['training_audio_hashes'] or case['normalized_sha256'] in manifest['training_normalized_hashes']):
            raise ValueError('Protected speaker/source/audio identities overlap training or have an invalid schema.')
        seen.add(case['sample_id']);path=args.manifest.parent/case['audio_filename']
        if consumer.file_hash(path)!=case['audio_sha256']:raise ValueError('Protected audio input checksum changed.')
        waveform,normalized=consumer.normalized_audio(path,case['media_type'])
        if normalized!=case['normalized_sha256']:raise ValueError('Independent audio normalization differs from producer pins.')
    generated={}
    def evaluate(directory,label):
        model,vocoder,processor,voice=consumer.load(directory);rows=[];total=frames=0
        for index,case in enumerate(cases):
            waveform,_=consumer.normalized_audio(args.manifest.parent/case['audio_filename'],case['media_type'])
            loss,count=consumer.target_loss(model,processor,voice,waveform,case['text'])
            if not math.isfinite(loss):raise ValueError('Independent composite audio loss is non-finite.')
            wave,observation=consumer.synthesize(model,vocoder,processor,voice,case['text'],seed=42,max_seconds=6)
            filename=f'{label}-{index}.wav';(args.manifest.parent/filename).write_bytes(wave)
            total+=loss*count;frames+=count
            rows.append({'sample_id':case['sample_id'],'speaker_id':case['speaker_id'],'source_group_id':case['source_group_id'],
                'expected':case['text'],'composite_loss':loss,'prediction_mel_frames':count,
                'wave_filename':filename,'wave_sha256':hashlib.sha256(wave).hexdigest(),'observation':observation})
        model=vocoder=processor=voice=None;gc.collect()
        generated[label]=rows
        return {'loss':total/frames,'prediction_mel_frames':frames,'cases':rows}
    baseline=evaluate(args.base,'baseline');candidate=evaluate(args.candidate,'candidate')
    asr,asr_processor=consumer.load_evaluator(args.evaluator)
    for result in (baseline,candidate):
        errors=reference_words=0
        for row in result['cases']:
            wave,_=consumer.normalized_audio(args.manifest.parent/row['wave_filename'],'audio/wav')
            transcript=consumer.transcribe(asr,asr_processor,wave);count,denominator=word_errors(row['expected'],transcript)
            row.update(asr_transcript=transcript,word_errors=count,reference_words=denominator,word_error_rate=count/denominator)
            errors+=count;reference_words+=denominator
        result.update(word_error_rate=errors/reference_words,word_errors=errors,reference_words=reference_words)
    checks={'tts_natural_stop':all(row['observation']['finish_reason']=='stop' for row in candidate['cases']),
        'tts_loss_within_ten_percent':candidate['loss']<=baseline['loss']*1.1,
        'asr_proxy_wer_at_most_half':candidate['word_error_rate']<=.5,
        'asr_proxy_wer_not_regressed':candidate['word_error_rate']<=baseline['word_error_rate']+.1}
    print(json.dumps({'schema_version':'modelanvil.independent-audio-evaluation.v1','manifest_sha256':hashlib.sha256(raw).hexdigest(),
        'file_sha256':hashes,'audio_sha256':{c['sample_id']:c['audio_sha256'] for c in cases},
        'normalized_sha256':{c['sample_id']:c['normalized_sha256'] for c in cases},'baseline':baseline,'candidate':candidate,
        'checks':checks,'passed':all(checks.values()),'production_qualified':False,
        'quality_scope':'English fixed-demo-conditioning TTS composite loss and independent WhisperTiny transcription proxy; no product ASR, speaker fidelity or human/customer qualification.',
        'cpu_seconds':time.process_time()-cpu,'wall_seconds':time.monotonic()-started,
        'consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules)},allow_nan=False))


if __name__=='__main__':main()
