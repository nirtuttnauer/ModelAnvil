"""Offline numerical export child. All inputs are staged by the trusted operator."""
import json
import os
from pathlib import Path
import sys


def export(source, target):
    import torch
    from transformers import AutoTokenizer, LlamaForCausalLM
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    options = dict(local_files_only=True, trust_remote_code=False, use_safetensors=True,
                   dtype=torch.float32, attn_implementation='eager')
    base = source / 'base'
    base.mkdir(exist_ok=True)
    for name in ('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
        if (source / name).exists() and not (base / name).exists():
            os.link(source / name, base / name)
    model, info = LlamaForCausalLM.from_pretrained(str(base), output_loading_info=True, **options)
    if any(info[key] for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError('Incomplete base weights.')
    if (source / 'adapter_config.json').exists():
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, str(source), local_files_only=True, torch_device='cpu').merge_and_unload(safe_merge=True)
    if any(p.device.type != 'cpu' for p in model.parameters()): raise ValueError('CPU export cannot allocate model tensors on another device.')
    if any(not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Nonfinite merged weights.')
    model.save_pretrained(str(target), safe_serialization=True, max_shard_size='1GB')
    AutoTokenizer.from_pretrained(str(base), local_files_only=True, trust_remote_code=False).save_pretrained(str(target))
    # Reload through a fresh compatible loader; the in-memory merge cannot qualify its own output.
    del model
    import gc
    gc.collect()
    model = LlamaForCausalLM.from_pretrained(str(target), **options).eval()
    tokenizer = AutoTokenizer.from_pretrained(str(target), local_files_only=True, trust_remote_code=False)
    inputs = tokenizer('A telescope collects', return_tensors='pt')
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=8, do_sample=False, use_cache=True,
                                pad_token_id=tokenizer.eos_token_id)
    ids = output[0, inputs['input_ids'].shape[1]:].tolist()
    if not ids:
        raise ValueError('The exported model generated no tokens.')
    print(json.dumps({'runtime': 'transformers.LlamaForCausalLM', 'device': 'cpu',
                      'generated_token_ids': ids, 'completion': tokenizer.decode(ids, skip_special_tokens=True)}))


if __name__ == '__main__':
    export(Path(sys.argv[1]), Path(sys.argv[2]))
