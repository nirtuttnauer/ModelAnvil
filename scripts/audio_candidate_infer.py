"""Independent offline CPU SpeechT5/head/processor/vocoder consumer; no application imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time

SOURCE = {'tts': {'repo_id': 'microsoft/speecht5_tts', 'revision': '30fcde30f19b87502b8435427b5f5068e401d5f6', 'license': 'MIT', 'upstream_weights_sha256': 'd60d28067349ef66b50d8cd643ae56b6d6b8f27def929bc4ef6fcad907954190'}, 'vocoder': {'repo_id': 'microsoft/speecht5_hifigan', 'revision': 'bb6f429406e86a9992357a972c0698b22043307d', 'license': 'MIT', 'upstream_weights_sha256': 'b171e9bcd8a2b50dc9780040478dfa26783a9ee4be012cf5776914f091d6887b'}, 'speaker': {'repo_id': 'Matthijs/cmu-arctic-xvectors', 'revision': '5c1297a9eb6c91714ea77c0d4ac5aca9b6a952e5', 'license': 'MIT', 'archive_sha256': '28ea1b685a49fedce92d1af7e68b22bf511a23432bc7a13d621a4deeee9fe9a1', 'member': 'spkrec-xvect/cmu_us_slt_arctic-wav-arctic_a0001.npy', 'speaker_sha256': '21719c0414a470561e6d037466fd239ab59c1f9ed4e1b97db557dad6d0223e73', 'norm': 0.9999998807907104}}
BASE_HASHES = {'config.json': '2caf62dde93699a90cfc35ff2a8de27b02b479a0c98881cbc55f9682cc43e258', 'preprocessor_config.json': '9461d890ff65badba5ad726f9059436bc69963883dc803fa6ed3cdb8f8af3687', 'tokenizer_config.json': 'd589430c619db2d95ff0fa757a187b55ef5ea44eff7fb08a6fbf0e78e32a6247', 'special_tokens_map.json': '2a098b61fe8ec4cfd7674832ca00b4268c07569743a4ad15c8164e8f60ebf981', 'added_tokens.json': '74be21ecff0a1fb1f304fe7c72ab21e4f0c046f8359fdf2852eb1b80967069ad', 'spm_char.model': '7fcc48f3e225f627b1641db410ceb0c8649bd2b0c982e150b03f8be3728ab560', 'model.safetensors': 'aec2409d90f7f8e521021d7dea905cf11245cf9e4f2013634b478183aeb1349d', 'vocoder/config.json': 'ac281bbb65c617a3fe7c5c082c8106f5a35b14d236b6a12f99cbbb12e576ab96', 'vocoder/model.safetensors': '38907fe505de5bfc5ebd8c956d56721a2c30fdf8f5c7d4d9604f24759186246b', 'speaker.npy': '21719c0414a470561e6d037466fd239ab59c1f9ed4e1b97db557dad6d0223e73'}
LEGACY_BUFFERS = {'speecht5.encoder.prenet.encode_positions.pe': (1, 600, 768), 'speecht5.decoder.prenet.encode_positions.pe': (1, 1876, 768)}
HEAD_NAMES = {f'speech_decoder_postnet.{layer}.{kind}' for layer in ('feat_out','prob_out') for kind in ('weight','bias')}


def file_hash(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024**2):result.update(block)
    return result.hexdigest()


def verify_files(directory):
    names=set(BASE_HASHES)
    if (directory/'audio_head.safetensors').exists():names.add('audio_head.safetensors')
    result={}
    for name in names:
        path=directory/name
        maximum=700*1024**2 if name=='model.safetensors' else 64*1024**2 if name=='vocoder/model.safetensors' else 2*1024**2
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file() or not 0<path.stat().st_size<=maximum:
            raise ValueError('Independent audio snapshot file exceeds its bound or escapes the snapshot.')
        sha=file_hash(path)
        if name in BASE_HASHES and sha!=BASE_HASHES[name]:raise ValueError('Independent audio source/processor/vocoder/conditioning checksum differs.')
        result[name]=sha
    return result


def load(directory):
    import torch
    import numpy as np
    from safetensors.torch import load_file
    from transformers import SpeechT5ForTextToSpeech,SpeechT5HifiGan,SpeechT5Processor
    model,info=SpeechT5ForTextToSpeech.from_pretrained(str(directory),local_files_only=True,use_safetensors=True,
        dtype=torch.float32,attn_implementation='eager',output_loading_info=True)
    if set(info['unexpected_keys'])!=set(LEGACY_BUFFERS) or any(info[n] for n in ('missing_keys','mismatched_keys','error_msgs')):
        raise ValueError('Independent SpeechT5 tensors do not match the qualified architecture.')
    original=load_file(str(directory/'model.safetensors'),device='cpu')
    for name,shape in LEGACY_BUFFERS.items():
        value=original[name]
        if tuple(value.shape)!=shape or not torch.isfinite(value).all().item():raise ValueError('Independent publisher positional buffer differs.')
        parent,field=name.rsplit('.',1);model.get_submodule(parent)._buffers[field]=value.clone()
    del original
    if (directory/'audio_head.safetensors').exists():
        head=load_file(str(directory/'audio_head.safetensors'),device='cpu');parameters=dict(model.named_parameters())
        if set(head)!=HEAD_NAMES or any(head[n].shape!=parameters[n].shape or head[n].dtype!=torch.float32 or not torch.isfinite(head[n]).all().item() for n in HEAD_NAMES):
            raise ValueError('Independent audio head has incomplete or incompatible tensors.')
        with torch.no_grad():
            for name in HEAD_NAMES:parameters[name].copy_(head[name])
    vocoder,info=SpeechT5HifiGan.from_pretrained(str(directory/'vocoder'),local_files_only=True,
        use_safetensors=True,dtype=torch.float32,output_loading_info=True)
    if any(info[n] for n in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')):
        raise ValueError('Independent vocoder tensors are incomplete.')
    for module in (model,vocoder):
        if any(p.is_meta or p.device.type!='cpu' or p.dtype!=torch.float32 or not torch.isfinite(p).all().item() for p in module.parameters()):
            raise ValueError('Independent audio reload needs complete finite CPU FP32 tensors.')
        module.eval().requires_grad_(False)
    processor=SpeechT5Processor.from_pretrained(str(directory),local_files_only=True)
    voice=np.load(directory/'speaker.npy',allow_pickle=False)
    if voice.shape!=(512,) or voice.dtype!=np.float32 or not np.isfinite(voice).all() or not .99<np.linalg.norm(voice)<1.01:
        raise ValueError('Independent conditioning vector is invalid.')
    if len(processor.tokenizer)!=81 or processor.feature_extractor.sampling_rate!=16000:
        raise ValueError('Independent SpeechT5 processor differs.')
    return model,vocoder,processor,torch.from_numpy(voice.copy())[None]


def synthesize(model,vocoder,processor,voice,text,*,seed=42,max_seconds=6):
    import torch
    import numpy as np
    import io,wave
    if (not isinstance(text,str) or not text.strip() or len(text)>96
            or any(t in text for t in processor.tokenizer.all_special_tokens)
            or type(seed) is not int or not 0<=seed<=2147483647 or type(max_seconds) is not int or not 1<=max_seconds<=6):
        raise ValueError('Use bounded text, an integer seed and 1–6 seconds of audio.')
    inputs=processor(text=text,return_tensors='pt');count=inputs['input_ids'].shape[-1]
    if not 1<=count<=128 or inputs['input_ids'].eq(processor.tokenizer.unk_token_id).any().item():
        raise ValueError('Text exceeds the exact supported SpeechT5 character vocabulary or token budget.')
    maximum_steps=max_seconds*16000//(256*2)
    last=[]
    hook=model.speech_decoder_postnet.prob_out.register_forward_hook(lambda module,args,output:last.append(float(torch.sigmoid(output).sum())))
    try:
        with torch.random.fork_rng(),torch.inference_mode():
            torch.manual_seed(seed)
            values=model.generate_speech(inputs['input_ids'],attention_mask=inputs.get('attention_mask'),speaker_embeddings=voice,
                maxlenratio=(2*maximum_steps+.25)/count,vocoder=vocoder)
    finally:hook.remove()
    value=values.detach().cpu().numpy()
    if value.ndim!=1 or not 4000<=len(value)<=max_seconds*16000 or not np.isfinite(value).all():
        raise ValueError('Missing, non-finite or oversized audio is not a successful generation.')
    rms=float(np.sqrt(np.mean(value.astype(np.float64)**2)));clipped=float(np.mean(np.abs(value)>1))
    if rms<1e-6 or clipped>.01:raise ValueError('Silent or severely clipped waveform is not a successful generation.')
    raw=io.BytesIO()
    with wave.open(raw,'wb') as output:
        output.setparams((1,2,16000,0,'NONE','not compressed'))
        output.writeframes((np.clip(value,-1,1)*32767).round().astype('<i2').tobytes())
    return raw.getvalue(),{'frames':len(value),'sample_rate':16000,'channels':1,'sample_format':'PCM_S16_LE',
        'duration_seconds':len(value)/16000,'rms_before_quantization':rms,'clipped_fraction':clipped,
        'finish_reason':'stop' if last and last[-1]>=.5 else 'length','last_stop_probability_sum':last[-1] if last else None,
        'prompt_tokens':count,'seed':seed,'maximum_seconds':max_seconds}


EVALUATOR_HASHES = {'added_tokens.json': '560be47bea388757f8d4cc185c5d82067426cbb6361e38016dd90ddc01ab203a', 'config.json': 'b5366317df280f79e6cc366f259f379674f81a8721d458acf2e00680ccb10b1d', 'generation_config.json': '38744c19d5cede6ff4dab5079c6d6ddc02ca726960bbef208fb602ad5a030eab', 'merges.txt': '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5', 'model.safetensors': 'db59695928ded6043adaef491a53ef4e12da9611184d77c53baa691a60b958ad', 'normalizer.json': 'bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd', 'preprocessor_config.json': '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666', 'special_tokens_map.json': '014f8f802366ed818919550be0ad9e35907327cb9e142e8aaa102420f460bda8', 'tokenizer.json': '5eb60cec1e77aeeb6869a2bb5a8e01a84c3fe5d072d75369343021fe6f5310d0', 'tokenizer_config.json': '14f84bdf4b9ecdbd4738ddc81c17a1baedfc02bb93c6e049c951e15a1b40b70d', 'vocab.json': '3ba3c3109ff33976c4bd966589c11ee14fcaa1f4c9e5e154c2ed7f99d80709e7'}


def load_evaluator(directory):
    import torch
    from transformers import WhisperProcessor,WhisperForConditionalGeneration
    for name,sha in EVALUATOR_HASHES.items():
        path=directory/name
        maximum=200*1024**2 if name=='model.safetensors' else 8*1024**2
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()) or not path.is_file() or not 0<path.stat().st_size<=maximum or file_hash(path)!=sha:
            raise ValueError('Independent ASR proxy source files differ.')
    model,info=WhisperForConditionalGeneration.from_pretrained(str(directory),local_files_only=True,use_safetensors=True,
        dtype=torch.float32,attn_implementation='eager',output_loading_info=True)
    if any(info[n] for n in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')) or any(p.is_meta or p.device.type!='cpu' or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Independent ASR proxy tensors are incomplete or non-finite.')
    return model.eval().requires_grad_(False),WhisperProcessor.from_pretrained(str(directory),local_files_only=True)


def transcribe(model,processor,waveform):
    import torch
    encoded=processor(waveform,sampling_rate=16000,return_tensors='pt')
    with torch.inference_mode():ids=model.generate(**encoded,max_new_tokens=64,do_sample=False)
    return processor.batch_decode(ids,skip_special_tokens=True,clean_up_tokenization_spaces=False)[0]


def normalized_audio(path,media_type):
    import io,math
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    if not 0<path.stat().st_size<=4*1024**2:raise ValueError('Independent audio input exceeds4MiB.')
    raw=path.read_bytes()
    with sf.SoundFile(io.BytesIO(raw)) as stream:
        rate,channels,frames=stream.samplerate,stream.channels,stream.frames
        if (stream.format!=('WAV' if media_type=='audio/wav' else 'FLAC') or stream.subtype!='PCM_16'
                or rate not in (8000,16000,22050,24000,32000,44100,48000) or channels not in (1,2) or not rate/4<=frames<=6*rate):
            raise ValueError('Independent audio decoding exceeds the qualified format/rate/frame bounds.')
        values=stream.read(frames+1,dtype='float32',always_2d=True)
    if values.shape!=(frames,channels) or not np.isfinite(values).all():raise ValueError('Independent target audio is incomplete or non-finite.')
    values=values.mean(axis=1,dtype=np.float32);divisor=math.gcd(rate,16000)
    if rate!=16000:values=resample_poly(values,16000//divisor,rate//divisor,window=('kaiser',5.0))
    values=np.clip(values,-1,1).astype('<f4')
    return values,hashlib.sha256(values.tobytes()).hexdigest()


def target_loss(model,processor,voice,waveform,text):
    import torch
    encoded=processor(text=text,audio_target=waveform,sampling_rate=16000,return_tensors='pt')
    encoded={k:encoded[k] for k in ('input_ids','attention_mask','labels') if k in encoded}
    frames=encoded['labels'].shape[1]
    if not 1<=frames<=376 or encoded['input_ids'].shape[-1]>128:raise ValueError('Independent target mel/text limits differ.')
    if frames%2:encoded['labels']=torch.cat([encoded['labels'],torch.full((1,1,80),-100.)],dim=1)
    with torch.random.fork_rng(),torch.no_grad():
        torch.manual_seed(42);loss=float(model(**encoded,speaker_embeddings=voice,use_cache=False).loss)
    return loss,frames

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('model_dir',type=Path)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--text',required=True)
    parser.add_argument('--seed',type=int,default=42);parser.add_argument('--max-seconds',type=int,default=6)
    args=parser.parse_args()
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(45,45));signal.alarm(60)
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(8*1024**3,8*1024**3))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false')
    import torch
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    started,cpu=time.monotonic(),time.process_time();hashes=verify_files(args.model_dir)
    model,vocoder,processor,voice=load(args.model_dir)
    raw,report=synthesize(model,vocoder,processor,voice,args.text,seed=args.seed,max_seconds=args.max_seconds)
    with args.output.open('xb') as output:output.write(raw)
    print(json.dumps({**report,'schema_version':'modelanvil.independent-audio-generation.v1','file_sha256':hashes,
        'wave_sha256':hashlib.sha256(raw).hexdigest(),'wave_bytes':len(raw),'cpu_seconds':time.process_time()-cpu,
        'wall_seconds':time.monotonic()-started,'production_qualified':False,
        'consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules)},allow_nan=False))


if __name__=='__main__':main()
