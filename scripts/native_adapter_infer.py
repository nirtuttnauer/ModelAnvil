"""Load a reviewed native adapter export without importing ModelAnvil."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def verify(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('schema_version') != 'modelanvil.reviewed-native.v1':
        raise ValueError('Unsupported reviewed export manifest.')
    for name, expected in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('Export file names must be local basenames.')
        path = directory / name
        if path.is_symlink() or path.stat().st_size != expected['byte_size']:
            raise ValueError('Export file size or path changed.')
        checksum = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != expected['sha256']:
            raise ValueError('Export checksum mismatch.')
    if hashlib.sha256((directory / 'review.json').read_bytes()).hexdigest() != manifest['review_sha256']:
        raise ValueError('Export review checksum mismatch.')
    if manifest.get('resource_usage_sha256') and hashlib.sha256((directory / 'resource-usage.json').read_bytes()).hexdigest() != manifest['resource_usage_sha256']:
        raise ValueError('Export resource usage checksum mismatch.')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--prompt', required=True)
    parser.add_argument('--system', default='')
    parser.add_argument('--device', choices=['cpu', 'mps:0'], default='cpu')
    parser.add_argument('--max-tokens', type=int, default=32, choices=range(1, 33))
    args = parser.parse_args()
    manifest = verify(args.directory)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    tokenizer = AutoTokenizer.from_pretrained(str(args.directory), local_files_only=True, trust_remote_code=False)
    if args.device == 'mps:0' and (not torch.backends.mps.is_available() or os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK') == '1'):
        raise ValueError('Apple GPU inference requires MPS with CPU fallback disabled.')
    # Adapter auto-detection otherwise tries to resolve a remote base. Isolate the verified base bytes.
    with tempfile.TemporaryDirectory(prefix='modelanvil-export-base-') as temporary:
        base = Path(temporary)
        for name in ('model.safetensors', 'config.json', 'tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json'):
            if name not in manifest['files']:
                raise ValueError('Use a full native export containing the pinned base files.')
            try:
                os.link(args.directory / name, base / name)
            except OSError:
                shutil.copyfile(args.directory / name, base / name)
        model, info = AutoModelForCausalLM.from_pretrained(str(base), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
        if any(info[key] for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
            raise ValueError('Base weights do not completely match the exported configuration.')
        model = PeftModel.from_pretrained(model, str(args.directory), local_files_only=True).eval().to(args.device)
    if any(p.is_meta or p.device != torch.device(args.device) or not torch.isfinite(p).all().item() for p in model.parameters()):
        raise ValueError('Candidate weights are missing, non-finite or on the wrong device.')
    messages = ([{'role': 'system', 'content': args.system}] if args.system else []) + [{'role': 'user', 'content': args.prompt}]
    tokens = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
    if len(tokens) + args.max_tokens > min(2048, model.config.max_position_embeddings):
        raise ValueError('Prompt and output exceed the bounded context.')
    current = torch.tensor([tokens], dtype=torch.long, device=args.device)
    generated, past = [], None
    with torch.inference_mode():
        for _ in range(args.max_tokens):
            result = model(input_ids=current, past_key_values=past, use_cache=True)
            logits = result.logits[0, -1].float().cpu()
            if not torch.isfinite(logits).all().item():
                raise ValueError('Inference produced non-finite logits.')
            token = int(torch.argmax(logits).item())
            if token == tokenizer.eos_token_id:
                break
            generated.append(token)
            past = result.past_key_values
            current = torch.tensor([[token]], dtype=torch.long, device=args.device)
    print(json.dumps({'candidate': manifest['candidate'], 'generated_token_ids': generated,
        'text': tokenizer.decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False),
        'device': args.device, 'consumer_imported_modelanvil_or_django': any(name.split('.')[0] in {'modelanvil', 'django'} for name in __import__('sys').modules)}))


if __name__ == '__main__':
    main()
