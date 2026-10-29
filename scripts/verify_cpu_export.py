"""Independent offline Transformers/PEFT consumer for bounded CPU Safetensors archives.

No Django, registry, API server, remote code, ambient credentials or network model loading.
Adapter-only exports require the separately provisioned exact base directory.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

BASE_HASHES = {
    'model.safetensors': '80521b40281d6ce74e35c9282c22539e75aa0ac8578892b2a59955ef78d55da1',
    'config.json': '1d556eab73b69c7f11f64c557a2f9c6f440bd4c6b89bb2584a6b498c92603843',
    'tokenizer.json': ('9ca9acdd' 'b6525a19' '4ec8ac7a' '87f24fbb' 'a7232a9a' '15ffa1af' '0c1224fc' 'd888e47c'),
    'tokenizer_config.json': ('4bb9af56' 'a342753d' '39374f40' '16a16574' 'cab299fe' '088e896f' '425ce3c4' '33f61424'),
    'special_tokens_map.json': ('e786b595' 'b9a23148' 'bf1630df' '78d9037a' '048ea671' 'e48bfd35' '49a1e3c2' '33742bb3'),
}


def validate_profile(config, adapter=None):
    expected = {'model_type': 'llama', 'hidden_size': 576, 'num_hidden_layers': 30,
                'vocab_size': 49152, 'intermediate_size': 1536, 'num_attention_heads': 9,
                'num_key_value_heads': 3, 'max_position_embeddings': 8192}
    if any(config.get(key) != value for key, value in expected.items()):
        raise ValueError('Only the bounded SmolLM2-135M configuration is qualified.')
    if adapter is not None and (adapter.get('peft_type') != 'LORA' or adapter.get('task_type') != 'CAUSAL_LM'
            or adapter.get('r') != 8 or adapter.get('lora_alpha') != 16
            or set(adapter.get('target_modules', [])) != {'q_proj', 'v_proj'}
            or any(adapter.get(k) for k in ('rank_pattern', 'alpha_pattern', 'modules_to_save', 'layer_replication',
                'trainable_token_indices', 'target_parameters', 'use_dora', 'use_rslora', 'use_qalora', 'auto_mapping'))):
        raise ValueError('Only the bounded rank-8 q/v LoRA configuration is qualified.')


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024): value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True); parser.add_argument('--sha256', required=True)
    parser.add_argument('--base', type=Path)
    args = parser.parse_args()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
    if not 1 <= args.archive.stat().st_size <= 2 * 1024**3 or sha(args.archive) != args.sha256:
        raise ValueError('Archive checksum or size changed.')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(args.archive) as archive:
            names = archive.namelist()
            allowed = {*BASE_HASHES, 'adapter_model.safetensors', 'adapter_config.json', 'generation_config.json',
                       'LICENSE.txt', 'NOTICE.txt', 'modelanvil-provenance.json', 'chat_template.jinja'}
            if len(names) != len(set(names)) or set(names) - allowed or len(names) > 16:
                raise ValueError('Unsupported export paths or duplicate members.')
            if sum(info.file_size for info in archive.infolist()) > 2 * 1024**3:
                raise ValueError('Archive exceeds expanded size bound.')
            for info in archive.infolist():
                if not 0 < info.file_size <= (1024**3 if info.filename.endswith('.safetensors') else 16 * 1024**2) or info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError('Unsupported archive member size or encoding.')
                with archive.open(info) as source, (root / info.filename).open('wb') as target:
                    import shutil
                    shutil.copyfileobj(source, target, 1024 * 1024)
        manifest = json.loads((root / 'modelanvil-provenance.json').read_text())
        pins = manifest.get('export', {}).get('files') or manifest.get('export_files') or manifest.get('files')
        if not isinstance(pins, dict): raise ValueError('Missing exported file hashes.')
        actual_files = set(names) - {'modelanvil-provenance.json', 'LICENSE.txt', 'NOTICE.txt'}
        for name in actual_files:
            if name not in pins or sha(root / name) != pins[name]['sha256'] or (root / name).stat().st_size != pins[name]['byte_size']:
                raise ValueError('Exported model files do not match the provenance.')
        import torch
        from transformers import AutoTokenizer, LlamaForCausalLM
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        model_directory = root
        adapter = (root / 'adapter_model.safetensors').exists()
        if adapter:
            if args.base:
                for name, expected in BASE_HASHES.items():
                    if sha(args.base / name) != expected: raise ValueError('Adapter base revision bytes changed.')
                model_directory = args.base
            else:
                model_directory = root / 'base'; model_directory.mkdir()
                for name in BASE_HASHES:
                    if sha(root / name) != BASE_HASHES[name]: raise ValueError('Native adapter base bytes changed.')
                    os.link(root / name, model_directory / name)
        config = json.loads((model_directory / 'config.json').read_text())
        validate_profile(config, json.loads((root / 'adapter_config.json').read_text()) if adapter else None)
        model, info = LlamaForCausalLM.from_pretrained(str(model_directory), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
        if any(info[k] for k in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
            raise ValueError('Incomplete exported weights.')
        if adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, str(root), local_files_only=True, torch_device='cpu')
        if any(p.device.type != 'cpu' for p in model.parameters()): raise ValueError('Export consumer must stay on CPU.')
        if any(not torch.isfinite(p).all().item() for p in model.parameters()): raise ValueError('Nonfinite exported weights.')
        model.eval()
        tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
        if len(tokenizer) != 49152: raise ValueError('Export tokenizer vocabulary exceeds the qualified profile.')
        inputs = tokenizer('A telescope collects', return_tensors='pt')
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=8, do_sample=False, use_cache=True, pad_token_id=tokenizer.eos_token_id)
        ids = output[0, inputs['input_ids'].shape[1]:].tolist()
        if not ids: raise ValueError('No output tokens generated.')
        print(json.dumps({'archive_sha256': args.sha256, 'adapter': adapter, 'device': 'cpu',
            'runtime': 'independent Transformers/PEFT', 'generated_token_ids': ids,
            'completion': tokenizer.decode(ids, skip_special_tokens=True), 'production_qualified': False}))


if __name__ == '__main__': main()
