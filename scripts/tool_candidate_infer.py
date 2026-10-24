"""Independent exact Qwen3 CPU/native-tool-template consumer; no Django/application imports."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import resource
import signal
import sys
import time

SOURCE = {'repo_id': 'Qwen/Qwen3-0.6B', 'revision': 'c1899de289a04d12100db370d81485cdf75e47ca', 'license': 'Apache-2.0'}
FILES = {'config.json': {'sha256': '660db3b73d788119c04535e48cf9be5f55bc3100841a718637ae695b442f27dd', 'byte_size': 726}, 'generation_config.json': {'sha256': '2325da0f15bb848e018c5ae071b7943332e9f871d6b60e2ed22ca97d4cb993d2', 'byte_size': 239}, 'tokenizer.json': {'sha256': 'aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4', 'byte_size': 11422654}, 'tokenizer_config.json': {'sha256': 'd5d09f07b48c3086c508b30d1c9114bd1189145b74e982a265350c923acd8101', 'byte_size': 9732}, 'model.safetensors': {'sha256': 'f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b', 'byte_size': 1503300328}, 'LICENSE': {'sha256': '832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e', 'byte_size': 11343}}
PACKAGES={'torch':'2.13.0','transformers':'5.14.0','safetensors':'0.8.0','tokenizers':'0.22.2'}
PARAMETERS=596049920


def file_hash(path):
    result=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(1024**2):result.update(block)
    return result.hexdigest()


def verify_files(directory):
    if any(p.name not in set(FILES)|{'verified-source.json','README.md'} or not p.is_file() or p.is_symlink() for p in directory.iterdir()):
        raise ValueError('Tool-model directory contains unqualified files; adapters and remote code are unsupported.')
    result={}
    for name,pin in FILES.items():
        path=directory/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=pin['byte_size'] or file_hash(path)!=pin['sha256']:
            raise ValueError('Exact tool-model source/tokenizer checksum differs.')
        result[name]=pin['sha256']
    return result


def load(directory):
    import torch
    from transformers import Qwen3ForCausalLM,AutoTokenizer
    model,info=Qwen3ForCausalLM.from_pretrained(str(directory),local_files_only=True,use_safetensors=True,
        dtype=torch.float32,attn_implementation='eager',output_loading_info=True)
    if any(info[n] for n in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')):
        raise ValueError('Exact Qwen3 tensors did not load completely.')
    if (sum(p.numel() for p in model.parameters())!=PARAMETERS
            or any(p.is_meta or p.device.type!='cpu' or p.dtype!=torch.float32 or not torch.isfinite(p).all().item() for p in model.parameters())):
        raise ValueError('Tool model needs complete finite FP32 CPU tensors.')
    tokenizer=AutoTokenizer.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False)
    if len(tokenizer)!=151669 or not tokenizer.chat_template:raise ValueError('Exact native tool tokenizer/template differs.')
    return model.eval().requires_grad_(False),tokenizer


def prepare(tokenizer,value):
    if (not isinstance(value,dict) or set(value)!={'messages','tools','max_tokens'}
            or not isinstance(value['messages'],list) or not 1<=len(value['messages'])<=12
            or not isinstance(value['tools'],list) or len(value['tools'])>8
            or type(value['max_tokens']) is not int or not 1<=value['max_tokens']<=128):
        raise ValueError('Use bounded native messages/tools and1–128 output tokens.')
    for message in value['messages']:
        if (not isinstance(message,dict) or message.get('role') not in ('system','user','assistant','tool')
                or not isinstance(message.get('content',''),str) or len(message.get('content','').encode())>16384):
            raise ValueError('Tool model message shape exceeds its bound.')
    serialized=json.dumps(value,allow_nan=False)
    if any(token in serialized for token in tokenizer.all_special_tokens):
        raise ValueError('Input contains reserved native control tokens.')
    encoded=tokenizer.apply_chat_template(value['messages'],tools=value['tools'],tokenize=True,return_dict=True,
        return_tensors='pt',add_generation_prompt=True,enable_thinking=False)
    count=encoded['input_ids'].shape[-1]
    if not 1<=count or count+value['max_tokens']>1536:raise ValueError('Native tool prompt/output exceeds1536 tokens; no truncation.')
    return encoded,count


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('model_dir',type=Path)
    parser.add_argument('--input',type=Path,required=True);args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CPU,(45,45));signal.alarm(60)
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(12*1024**3,12*1024**3))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false')
    for name,version in PACKAGES.items():
        if importlib.metadata.version(name).split('+')[0]!=version:raise ValueError('Pinned tool inference package differs.')
    with args.input.open('rb') as stream:raw=stream.read(65537)
    if not 0<len(raw)<=65536:raise ValueError('Tool-model input exceeds64KiB.')
    value=json.loads(raw,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON.')))
    import torch
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True);torch.manual_seed(42)
    started,cpu=time.monotonic(),time.process_time();hashes=verify_files(args.model_dir)
    model,tokenizer=load(args.model_dir);encoded,count=prepare(tokenizer,value)
    with torch.inference_mode():output=model.generate(**encoded,max_new_tokens=value['max_tokens'],do_sample=False)
    ids=output[0,count:].tolist();eos=model.generation_config.eos_token_id;eos=eos if isinstance(eos,list) else [eos]
    stopped=bool(ids and ids[-1] in eos);tokens=len(ids)
    while ids and ids[-1] in eos:ids.pop()
    text=tokenizer.decode(ids,skip_special_tokens=False,clean_up_tokenization_spaces=False)
    if len(text.encode())>16384:raise ValueError('Tool-model response exceeds its bound.')
    print(json.dumps({'schema_version':'modelanvil.independent-tool-generation.v1','source':SOURCE,'file_sha256':hashes,
        'input_sha256':hashlib.sha256(raw).hexdigest(),'content':text,'finish_reason':'stop' if stopped else 'length',
        'usage':{'prompt_tokens':count,'completion_tokens':tokens,'total_tokens':count+tokens},
        'cpu_seconds':time.process_time()-cpu,'wall_seconds':time.monotonic()-started,'parameters':PARAMETERS,
        'device':'cpu','precision':'fp32','thinking':False,'production_qualified':False,
        'consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules)},allow_nan=False))


if __name__=='__main__':main()
