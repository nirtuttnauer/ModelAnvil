"""Independent offline Hugging Face candidate consumer; no Django/ModelAnvil imports."""
import argparse
import hashlib
import json
import os
import re
import time
import tempfile
import shutil
from pathlib import Path

import torch
from transformers import AutoTokenizer, LlamaForCausalLM


def selected_device(selector):
    if selector == 'cpu':
        return torch.device('cpu'), 'cpu'
    if not re.fullmatch(r'(?:cuda|rocm|xpu):(?:0|[1-9][0-9]*)|mps:0', selector):
        raise ValueError('Select cpu, mps:0, cuda:N, rocm:N or xpu:N explicitly.')
    backend, index = selector.split(':'); index = int(index)
    if backend == 'mps':
        if os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK') == '1' or not torch.backends.mps.is_available():
            raise ValueError('MPS unavailable or CPU fallback enabled; inference refused.')
        recommended = torch.mps.recommended_max_memory()
        allocated = torch.mps.driver_allocated_memory()
        if type(recommended) is not int or type(allocated) is not int or recommended <= 0 or allocated < 0:
            raise ValueError('MPS process memory allowance is unknown.')
        if int(recommended * 0.9) - allocated < 4 * 1024**3:
            raise ValueError('MPS process headroom is below 4 GiB.')
        torch.mps.set_per_process_memory_fraction(0.9)
    else:
        if backend in {'cuda', 'rocm'}:
            actual = 'rocm' if torch.version.hip else 'cuda' if torch.version.cuda else None
            if actual != backend:
                raise ValueError('Selected backend does not match the installed CUDA/HIP framework build.')
        api = getattr(torch, 'cuda' if backend == 'rocm' else backend, None)
        if api is None or not api.is_available() or index >= api.device_count():
            raise ValueError('Selected GPU unavailable; inference refuses CPU fallback.')
        capacity = api.get_device_properties(index).total_memory
        if type(capacity) is not int or capacity < 4 * 1024**3:
            raise ValueError('Selected GPU has less than 4 GiB reported memory.')
    return torch.device(f"{'cuda' if backend == 'rocm' else backend}:{index}"), backend


def load_candidate(directory):
    """Offline complete finite Safetensors/PEFT reload shared by independent consumers."""
    adapter = (directory / 'adapter_config.json').exists()
    with tempfile.TemporaryDirectory(prefix='verified-base-') as temp:
        base_directory = Path(temp) if adapter else directory
        if adapter:
            for name in ('model.safetensors', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
                shutil.copyfile(directory / name, base_directory / name)
        model, info = LlamaForCausalLM.from_pretrained(str(base_directory), local_files_only=True,
            use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
        if adapter:
            from peft import PeftModel, get_peft_model_state_dict
            config = json.loads((directory / 'adapter_config.json').read_text())
            if config.get('r') != 8 or config.get('lora_alpha') != 16 or set(config.get('target_modules', [])) != {'q_proj', 'v_proj'} or config.get('lora_dropout') != 0:
                raise ValueError('Candidate adapter does not match the declared rank-8 q/v profile.')
            model = PeftModel.from_pretrained(model, str(directory), local_files_only=True)
            from safetensors.torch import load_file
            saved = load_file(str(directory / 'adapter_model.safetensors'))
            expected = get_peft_model_state_dict(model, save_embedding_layers=False)
            if set(saved) != set(expected) or any(saved[n].shape != p.shape for n, p in expected.items()):
                raise ValueError('Candidate adapter tensors are incomplete or have incompatible shapes.')
    if any(info[k] for k in ['missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs']):
        raise ValueError('Candidate tensors do not completely match the transformer.')
    if any(p.is_meta or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Candidate did not load complete finite weights.')
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model_dir', type=Path)
    parser.add_argument('--device', default='cpu', help='Explicit cpu, mps:0, cuda:N, rocm:N or xpu:N; no fallback')
    parser.add_argument('--precision', choices=['fp32'], default='fp32')
    parser.add_argument('--prompt', default='Once upon a time')
    parser.add_argument('--max-new-tokens', type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.max_new_tokens <= 32 or len(args.prompt) > 4096:
        parser.error('Use 1–32 new tokens and a prompt up to 4096 characters.')
    device, backend = selected_device(args.device)
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    adapter = (args.model_dir / 'adapter_config.json').exists()
    model = load_candidate(args.model_dir)
    model.to(device).eval()
    if any(p.device != device for p in model.parameters()):
        raise ValueError('Candidate weights left the explicitly selected device.')
    ids = tokenizer.encode(args.prompt, add_special_tokens=True)
    if not 1 <= len(ids) <= 128:
        parser.error('Prompt must encode to 1–128 tokens; no implicit truncation.')
    started = time.perf_counter()
    with torch.no_grad():
        output = model.generate(torch.tensor([ids], device=device), attention_mask=torch.ones((1, len(ids)), dtype=torch.long, device=device), max_new_tokens=args.max_new_tokens,
            do_sample=False, pad_token_id=tokenizer.eos_token_id)
    if output.device != device or not torch.isfinite(model.get_input_embeddings().weight).all().item():
        raise ValueError('Inference output/weights left the device or became non-finite.')
    api = getattr(torch, 'cuda' if backend == 'rocm' else backend, None)
    if backend != 'cpu':
        api.synchronize() if backend == 'mps' else api.synchronize(device)
    measured = {'backend': backend, 'device': str(device), 'precision': 'fp32',
        'device_residency_checked': True, 'wall_seconds': time.perf_counter() - started,
        'allocated_bytes': (api.current_allocated_memory() if backend == 'mps' else api.memory_allocated(device)) if backend != 'cpu' else None}
    if backend == 'mps':
        measured.update(driver_allocated_bytes=api.driver_allocated_memory(), recommended_bytes=api.recommended_max_memory(),
            process_headroom_bytes=max(0, int(api.recommended_max_memory() * 0.9) - api.driver_allocated_memory()))
    sha = hashlib.sha256()
    weight_name = 'adapter_model.safetensors' if adapter else 'model.safetensors'
    with (args.model_dir / weight_name).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
    import sys
    hashes = {weight_name: sha.hexdigest()}
    for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', *(['model.safetensors', 'adapter_config.json'] if adapter else [])):
        hashes[name] = hashlib.sha256((args.model_dir / name).read_bytes()).hexdigest()
    print(json.dumps({'weights_sha256': sha.hexdigest(), 'prompt': args.prompt,
        'file_hashes': hashes,
        'generated_token_ids': output[0, len(ids):].tolist(),
        'completion': tokenizer.decode(output[0, len(ids):], skip_special_tokens=True),
        'parameter_count': sum(p.numel() for p in model.parameters()), 'execution': measured,
        'consumer_imported_modelanvil_or_django': any(m.split('.')[0] in {'modelanvil','django'} for m in sys.modules),
        'scope': f'Independent process, {args.device} FP32 inference from actual GPU-produced candidate; no quality or production claim.'}))


if __name__ == '__main__':
    main()
