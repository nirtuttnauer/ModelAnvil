"""Independent offline CPU SmolVLM adapter/processor consumer; no application imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

BASE_WEIGHT_SHA256 = '74dea5904032e5ae99a2e0eef5179e6ac0f1dedc3ab0c7c2a5d4d387c843203e'
SOURCE = {'repo_id': 'HuggingFaceTB/SmolVLM-256M-Instruct', 'revision': '7e3e67edbbed1bf9888184d9df282b700a323964', 'license': 'Apache-2.0'}
BASE_SHA256 = {'added_tokens.json': ('74135b86' '64b56088' 'c0006f1c' '8e848d79' 'a8eba003' '411f72eb' 'f1dc2ee9' '6227be3a'), 'chat_template.json': 'a68ad1a42681ae44eacd109ff8dd56a840f761c03d72f4ff4c515d092f882168', 'config.json': 'b70fb4bfde88df9eeebc9d8ff523733b8bf70d6c9b06c610325960e06ae9db52', 'generation_config.json': '067a2a54e5f87162ecac6e0e911cc4665fc8f7f3324794ecbac0f76badb56636', 'merges.txt': '0b54e8aa4e53d5383e2e4bc635a56b43f9647f7b13832d5d9ecd8f82dac4f510', 'model.safetensors': '74dea5904032e5ae99a2e0eef5179e6ac0f1dedc3ab0c7c2a5d4d387c843203e', 'preprocessor_config.json': '6cb6e36d6fcb88ca1502c4a26750715dc3e7dedddc9a8f17b27d8d167d1457e7', 'processor_config.json': 'e7bff42da73ae9eec9042ef20e066e11f1ee20f025358ff79131e3c0fb549b46', 'special_tokens_map.json': ('aa0ff906' '077086df' 'a9734a7f' '97f68c82' '5877a48f' '9468807b' 'e6550449' '5cdeef09'), 'tokenizer.json': ('5ece781d' 'c8d2b2f3' 'e2f289ca' '0ae50b17' 'cfc27dd2' '7bfe7971' 'bb8241e0' 'b964331a'), 'tokenizer_config.json': ('36c6fd44' 'd07d10fd' '8180ee6b' '46dcccf6' '9fb7c067' '53968ff0' 'd7e17b8b' 'fe17b777'), 'vocab.json': '82b84012e3add4d01d12ba14442026e49b8cbbaead1f79ecf3d919784f82dc79'}
TARGETS = r'model\.text_model\.layers\.\d+\.self_attn\.(q_proj|v_proj)'
BASE_NAMES = {'added_tokens.json', 'chat_template.json', 'config.json', 'generation_config.json', 'merges.txt',
    'model.safetensors', 'preprocessor_config.json', 'processor_config.json', 'special_tokens_map.json',
    'tokenizer.json', 'tokenizer_config.json', 'vocab.json'}


def file_hash(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024**2): sha.update(block)
    return sha.hexdigest()


def verify_files(directory, expected):
    if set(expected) not in (BASE_NAMES, BASE_NAMES | {'adapter_model.safetensors', 'adapter_config.json'}):
        raise ValueError('Independent VLM reload needs a complete base/processor and optional adapter.')
    for name, sha in expected.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= (600 * 1024**2 if name == 'model.safetensors' else 8 * 1024**2):
            raise ValueError('Independent VLM model file exceeds its bound.')
        if file_hash(path) != sha: raise ValueError('Independent VLM file checksum differs.')
    if {n: expected[n] for n in BASE_NAMES} != BASE_SHA256: raise ValueError('Independent VLM source weights differ.')
    config = json.loads((directory / 'config.json').read_text())
    if (config.get('model_type') != 'idefics3' or config.get('image_token_id') != 49190 or config.get('scale_factor') != 4
            or any(config.get('text_config', {}).get(k) != v for k,v in {'hidden_size':576,'num_hidden_layers':30,'vocab_size':49280}.items())
            or any(config.get('vision_config', {}).get(k) != v for k,v in {'hidden_size':768,'num_hidden_layers':12,'image_size':512}.items())):
        raise ValueError('Independent VLM architecture exceeds the qualified shape.')
    return expected


def load(directory):
    import torch
    from transformers import Idefics3ForConditionalGeneration, AutoProcessor
    with tempfile.TemporaryDirectory(prefix='independent-vlm-base-') as temp:
        base = Path(temp)
        for name in BASE_NAMES: shutil.copyfile(directory / name, base / name)
        model, info = Idefics3ForConditionalGeneration.from_pretrained(str(base), local_files_only=True,
            use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
        if any(info[k] for k in ('missing_keys','unexpected_keys','mismatched_keys','error_msgs')):
            raise ValueError('Independent VLM base tensors are incomplete.')
        if (directory / 'adapter_config.json').exists():
            from peft import PeftModel, get_peft_model_state_dict
            from safetensors.torch import load_file
            config = json.loads((directory / 'adapter_config.json').read_text())
            expected = {'r':8,'lora_alpha':16,'target_modules':TARGETS,'lora_dropout':0.,'bias':'none','task_type':'CAUSAL_LM',
                'base_model_name_or_path':SOURCE['repo_id'],'revision':SOURCE['revision']}
            if any(config.get(k) != v for k,v in expected.items()): raise ValueError('Independent VLM adapter contract differs.')
            model = PeftModel.from_pretrained(model,str(directory),local_files_only=True,torch_device='cpu')
            saved = load_file(str(directory/'adapter_model.safetensors'),device='cpu'); wanted = get_peft_model_state_dict(model,save_embedding_layers=False)
            if set(saved) != set(wanted) or any(saved[n].shape != p.shape for n,p in wanted.items()): raise ValueError('Independent VLM adapter tensors are incomplete.')
    if any(p.is_meta or p.device.type != 'cpu' or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Independent VLM needs complete finite CPU weights.')
    processor = AutoProcessor.from_pretrained(str(directory),local_files_only=True,trust_remote_code=False,backend='pil',
        size={'longest_edge':512},do_image_splitting=False)
    if processor.__class__.__name__ != 'Idefics3Processor' or processor.image_seq_len != 64: raise ValueError('Independent VLM processor differs.')
    return model.eval().requires_grad_(False), processor


def image(path, media_type):
    import io
    from PIL import Image, ImageOps
    if not 0 < path.stat().st_size <= 2 * 1024**2: raise ValueError('Independent image exceeds 2 MiB.')
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as source:
        if (source.format not in ('PNG','JPEG') or Image.MIME[source.format] != media_type
                or getattr(source,'n_frames',1) != 1 or not 1 <= source.width <= 1024 or not 1 <= source.height <= 1024):
            raise ValueError('Independent image format, frame or dimensions exceed the profile.')
        source.verify()
    with Image.open(io.BytesIO(raw)) as source: result = ImageOps.exif_transpose(source).convert('RGB'); result.load()
    return result


def encode(processor, pixels, question, answer=None):
    import torch
    messages=[{'role':'user','content':[{'type':'image'},{'type':'text','text':question}]}]
    prompt=processor.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
    prefix=processor(text=prompt,images=[pixels],return_tensors='pt')
    if answer is None:return dict(prefix),prefix['input_ids'].shape[-1]
    full=processor.apply_chat_template([*messages,{'role':'assistant','content':[{'type':'text','text':answer}]}],tokenize=False,add_generation_prompt=False)
    encoded=processor(text=full,images=[pixels],return_tensors='pt');start=prefix['input_ids'].shape[-1]
    if encoded['input_ids'].shape[-1]>128 or not torch.equal(prefix['input_ids'],encoded['input_ids'][:,:start]):
        raise ValueError('Independent assistant boundary or token bound differs.')
    return dict(encoded),start


def score(model, encoded, start):
    import torch
    logits=model(**encoded,use_cache=False).logits[0,start-1:-1].float()
    labels=encoded['input_ids'][0,start:]
    return -float(logits.log_softmax(-1).gather(-1,labels[:,None]).sum()),len(labels)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model_dir',type=Path);parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--media-type',choices=['image/png','image/jpeg'],required=True);parser.add_argument('--prompt',required=True)
    args=parser.parse_args();os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    import torch,sys
    torch.set_num_threads(1)
    names=BASE_NAMES | ({'adapter_model.safetensors','adapter_config.json'} if (args.model_dir/'adapter_config.json').exists() else set())
    hashes=verify_files(args.model_dir,{n:file_hash(args.model_dir/n) for n in names})
    model,processor=load(args.model_dir);encoded,start=encode(processor,image(args.image,args.media_type),args.prompt)
    if not 1 <= start <= 120:raise ValueError('Independent prompt exceeds the bounded context.')
    with torch.inference_mode():output=model.generate(**encoded,max_new_tokens=8,do_sample=False,pad_token_id=processor.tokenizer.pad_token_id)
    print(json.dumps({'file_sha256':hashes,'image_sha256':file_hash(args.image),'completion':processor.tokenizer.decode(output[0,start:],skip_special_tokens=True),
        'generated_token_ids':output[0,start:].tolist(),'device':'cpu','consumer_imported_modelanvil_or_django':any(n.split('.')[0] in {'modelanvil','django'} for n in sys.modules)},allow_nan=False))


if __name__=='__main__':main()
