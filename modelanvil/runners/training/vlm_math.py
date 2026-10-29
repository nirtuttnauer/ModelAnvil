"""Pinned SmolVLM image/text preparation and bounded FP32 text-decoder LoRA."""
import hashlib
import json
import os
from pathlib import Path

SOURCE = {'repo_id': 'HuggingFaceTB/SmolVLM-256M-Instruct', 'revision': '7e3e67edbbed1bf9888184d9df282b700a323964', 'license': 'Apache-2.0'}
FILE_HASHES = {'added_tokens.json': ('74135b86' '64b56088' 'c0006f1c' '8e848d79' 'a8eba003' '411f72eb' 'f1dc2ee9' '6227be3a'), 'chat_template.json': 'a68ad1a42681ae44eacd109ff8dd56a840f761c03d72f4ff4c515d092f882168', 'config.json': 'b70fb4bfde88df9eeebc9d8ff523733b8bf70d6c9b06c610325960e06ae9db52', 'generation_config.json': '067a2a54e5f87162ecac6e0e911cc4665fc8f7f3324794ecbac0f76badb56636', 'merges.txt': '0b54e8aa4e53d5383e2e4bc635a56b43f9647f7b13832d5d9ecd8f82dac4f510', 'model.safetensors': '74dea5904032e5ae99a2e0eef5179e6ac0f1dedc3ab0c7c2a5d4d387c843203e', 'preprocessor_config.json': '6cb6e36d6fcb88ca1502c4a26750715dc3e7dedddc9a8f17b27d8d167d1457e7', 'processor_config.json': 'e7bff42da73ae9eec9042ef20e066e11f1ee20f025358ff79131e3c0fb549b46', 'special_tokens_map.json': ('aa0ff906' '077086df' 'a9734a7f' '97f68c82' '5877a48f' '9468807b' 'e6550449' '5cdeef09'), 'tokenizer.json': ('5ece781d' 'c8d2b2f3' 'e2f289ca' '0ae50b17' 'cfc27dd2' '7bfe7971' 'bb8241e0' 'b964331a'), 'tokenizer_config.json': ('36c6fd44' 'd07d10fd' '8180ee6b' '46dcccf6' '9fb7c067' '53968ff0' 'd7e17b8b' 'fe17b777'), 'vocab.json': '82b84012e3add4d01d12ba14442026e49b8cbbaead1f79ecf3d919784f82dc79'}
ADAPTER = {'r': 8, 'lora_alpha': 16, 'target_modules': r'model\.text_model\.layers\.\d+\.self_attn\.(q_proj|v_proj)',
    'lora_dropout': 0., 'bias': 'none', 'task_type': 'CAUSAL_LM'}
PROCESSOR = {'size': {'longest_edge': 512}, 'do_image_splitting': False}


def decode_image(raw, media_type):
    import io
    import warnings
    from PIL import Image, ImageOps, UnidentifiedImageError
    if type(raw) is not bytes or not 0 < len(raw) <= 2 * 1024**2 or media_type not in ('image/png', 'image/jpeg'):
        raise ValueError('Use a PNG or JPEG image of at most 2 MiB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if (image.format not in ('PNG', 'JPEG') or Image.MIME[image.format] != media_type
                        or getattr(image, 'n_frames', 1) != 1 or not 1 <= image.width <= 1024
                        or not 1 <= image.height <= 1024 or image.width * image.height > 1024**2):
                    raise ValueError('This vision profile accepts one PNG/JPEG frame up to 1024 by 1024 pixels.')
                image.verify()
            with Image.open(io.BytesIO(raw)) as image:
                decoded = ImageOps.exif_transpose(image).convert('RGB'); decoded.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValueError('Image decoding failed; use a complete supported PNG or JPEG.') from None
    return decoded, {'sha256': hashlib.sha256(raw).hexdigest(), 'byte_size': len(raw), 'media_type': media_type,
        'decoded_width': decoded.width, 'decoded_height': decoded.height, 'transform': 'exif_transpose_rgb_v1'}


def processor(directory):
    from transformers import AutoProcessor
    value = AutoProcessor.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False,
        backend="pil", **PROCESSOR)
    if value.__class__.__name__ != 'Idefics3Processor' or value.image_seq_len != 64:
        raise ValueError('Use the exact pinned Idefics3 processor with 64 image tokens.')
    return value


def load_model(directory, *, training=False):
    import torch
    from transformers import Idefics3ForConditionalGeneration
    from peft import LoraConfig, PeftModel, get_peft_model, get_peft_model_state_dict
    base = directory / 'base'; base.mkdir(exist_ok=True)
    for name in FILE_HASHES:
        if not (base / name).exists(): os.link(directory / name, base / name)
    model, info = Idefics3ForConditionalGeneration.from_pretrained(str(base), local_files_only=True,
        use_safetensors=True, dtype=torch.float32, attn_implementation='eager', output_loading_info=True)
    if any(info[key] for key in ('missing_keys', 'unexpected_keys', 'mismatched_keys', 'error_msgs')):
        raise ValueError('Vision-language weights do not completely match the pinned architecture.')
    if any(p.is_meta or not torch.isfinite(p).all().item() or p.device.type != 'cpu' for p in model.parameters()):
        raise ValueError('Vision-language base must load complete finite CPU FP32 weights.')
    if (directory / 'adapter_model.safetensors').exists():
        config = json.loads((directory / 'adapter_config.json').read_text())
        if (any(config.get(key) != expected for key, expected in ADAPTER.items())
                or config.get('base_model_name_or_path') != SOURCE['repo_id'] or config.get('revision') != SOURCE['revision']):
            raise ValueError('Vision-language adapter configuration or base revision changed.')
        model = PeftModel.from_pretrained(model, str(directory), is_trainable=training,
            local_files_only=True, torch_device='cpu')
        from safetensors.torch import load_file
        saved = load_file(str(directory / 'adapter_model.safetensors'), device='cpu')
        expected = get_peft_model_state_dict(model, save_embedding_layers=False)
        if set(saved) != set(expected) or any(saved[n].shape != p.shape or not torch.isfinite(saved[n]).all().item() for n,p in expected.items()):
            raise ValueError('Vision-language adapter tensors are incomplete or non-finite.')
    else:
        with torch.random.fork_rng():
            torch.manual_seed(42); model = get_peft_model(model, LoraConfig(**ADAPTER))
    model.peft_config['default'].base_model_name_or_path = SOURCE['repo_id']
    model.peft_config['default'].revision = SOURCE['revision']
    model.config.use_cache = False
    model.train(training)
    if not training: model.requires_grad_(False)
    if any(p.requires_grad and ('.lora_' not in n or '.text_model.' not in n) for n,p in model.named_parameters()):
        raise ValueError('This VLM profile may update only text-decoder q/v adapters.')
    return model


def encode(processor, image, question, answer=None):
    if not isinstance(question, str) or not question.strip() or len(question) > 512:
        raise ValueError('Use a nonempty visual question up to 512 characters.')
    if answer is not None and (not isinstance(answer, str) or not answer.strip() or len(answer) > 256):
        raise ValueError('Use a nonempty visual answer up to 256 characters.')
    if any(token in text for token in processor.tokenizer.all_special_tokens for text in [question, *([answer] if answer is not None else [])]):
        raise ValueError('Visual text cannot inject tokenizer control tokens.')
    messages = [{'role': 'user', 'content': [{'type': 'image'}, {'type': 'text', 'text': question}]}]
    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    prefix = processor(text=prompt, images=[image], return_tensors='pt')
    if answer is None: result = prefix
    else:
        full = processor.apply_chat_template([*messages, {'role': 'assistant', 'content': [{'type': 'text', 'text': answer}]}],
            tokenize=False, add_generation_prompt=False)
        result = processor(text=full, images=[image], return_tensors='pt')
    import torch
    length = prefix['input_ids'].shape[-1]
    if (result['input_ids'].shape[-1] > 128 or length > 120 or not torch.equal(prefix['input_ids'], result['input_ids'][:, :length])
            or answer is not None and result['input_ids'].shape[-1] <= length
            or tuple(result['pixel_values'].shape) != (1, 1, 3, 512, 512)
            or result['input_ids'].eq(processor.image_token_id).sum().item() != 64):
        raise ValueError('VLM image tiles, token budget or assistant boundary exceeds the pinned profile; no truncation.')
    return dict(result), length


def answer_loss(model, sample, prompt_tokens, device):
    import torch.nn.functional as F
    inputs = {name: value.to(device) for name, value in sample.items()}
    logits = model(**inputs, use_cache=False).logits
    return F.cross_entropy(logits[0, prompt_tokens - 1:-1].float(), inputs['input_ids'][0, prompt_tokens:], reduction='mean')
