"""Offline child runtime; optional dependencies never enter the API process."""
import contextlib
import importlib.metadata
import hashlib
import json
import math
from pathlib import Path
import sys
import warnings

VERSIONS = {'laya': '0.4.3', 'torch': '2.9.0', 'transformers': '5.14.0',
            'mlx-vlm': '0.7.6', 'mlx': '0.32.3', 'Pillow': '12.2.0', 'safetensors': '0.8.0', 'pypdfium2': '5.14.0',
            'torchvision': '0.24.0'}


def validate_decision(inputs):
    if not isinstance(inputs, dict) or set(inputs) != {'state', 'questions'}:
        raise ValueError('Supply state and questions only.')
    state, questions = inputs['state'], inputs['questions']
    if not isinstance(state, (str, dict)) or not state or (isinstance(state, str) and not state.strip()):
        raise ValueError('State must be nonempty text or a JSON object.')
    try:
        size = len(json.dumps(inputs, allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        raise ValueError('State and questions must be finite JSON.') from None
    if size > 32000 or not isinstance(questions, dict) or not 1 <= len(questions) <= 8:
        raise ValueError('Use 1–8 questions in a request of at most 32,000 JSON bytes.')
    for key, q in questions.items():
        if (not isinstance(key, str) or not 1 <= len(key) <= 80 or not isinstance(q, dict)
                or set(q) - {'type', 'instructions', 'criteria'} or q.get('type') not in {'choice', 'score', 'noul'}
                or not isinstance(q.get('instructions'), str) or not q['instructions'].strip()
                or len(q['instructions']) > 600):
            raise ValueError('Each question needs a name, type and bounded text instructions.')
        criteria = q.get('criteria')
        if q['type'] == 'noul':
            if criteria is not None:
                raise ValueError('Yes/no questions use the fixed boolean answer space.')
            continue
        if q['type'] == 'choice':
            if not isinstance(criteria, dict) or not 2 <= len(criteria) <= 8 or any(
                    not isinstance(k, str) or not 1 <= len(k) <= 60 for k in criteria):
                raise ValueError('Choice questions need 2–8 named text options.')
            values = criteria.values()
        else:
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 8:
                raise ValueError('Score questions need 2–8 ordered text levels.')
            values = criteria
        if any(not isinstance(v, str) or not v.strip() or len(v) > 240 for v in values):
            raise ValueError('Criteria must contain nonempty bounded text.')


def validate_ocr(inputs):
    if (not isinstance(inputs, dict) or set(inputs) != {'max_tokens'}
            or type(inputs['max_tokens']) is not int or not 32 <= inputs['max_tokens'] <= 1024):
        raise ValueError('OCR max_tokens must be an integer from 32 to 1024.')


def check_decision_tokens(tok, cfg, inputs):
    from laya.agent import Agent
    from laya.common import build_sequence, render_options
    if tok.mask_token in json.dumps(inputs, ensure_ascii=False):
        raise ValueError('Literal model mask tokens are unsupported in decision inputs.')
    for q in inputs['questions'].values():
        internal = Agent._to_internal(q)
        seq, markers, options, state = build_sequence(tok, inputs['state'], internal,
            cfg['max_len'], cfg['head_max_len'], return_stats=True, return_truncation_stats=True)
        rendered = render_options(internal)
        lengths = [len(tok.encode(' ' + opt.replace(tok.mask_token, ' '), add_special_tokens=False)) for opt in rendered]
        head_budget = cfg['head_max_len'] - sum(n + 1 for n in lengths)
        instructions = f"{internal['t']} question: {internal['ins']}".replace(tok.mask_token, ' ')
        if (state['truncated'] or options['tokens_per_option'] is not None
                or options['options_distinct'] != len(rendered) or len(markers) != len(rendered)
                or any(n > 48 for n in lengths)
                or len(tok.encode(instructions, add_special_tokens=False)) > max(8, head_budget)):
            raise ValueError('The state, instructions or options exceed the pinned token budget; shorten the request.')


def decide(directory, device, inputs):
    validate_decision(inputs)
    inputs = json.loads(json.dumps(inputs, sort_keys=True, ensure_ascii=False))
    import torch
    import laya
    from transformers import AutoTokenizer
    cfg = json.loads((directory / 'rl_agent_config.json').read_text())
    tok = AutoTokenizer.from_pretrained(str(directory / 'tokenizer'), local_files_only=True, trust_remote_code=False)
    check_decision_tokens(tok, cfg, inputs)
    if device not in {'cpu', 'mps:0'} or (device == 'mps:0' and not torch.backends.mps.is_available()):
        raise ValueError('The selected Laya device is unavailable.')
    if device == 'mps:0' and torch.mps.recommended_max_memory() - torch.mps.current_allocated_memory() < 4 * (directory / 'model.safetensors').stat().st_size + 256 * 1024**2:
        raise ValueError('MPS process memory headroom is insufficient for Laya.')
    # Runtime warnings stop the SDK before it can retry a failed GPU request on CPU.
    with warnings.catch_warnings():
        warnings.filterwarnings('error', message=r'(?is).*(falling back|retrying this request|could not place).*', category=RuntimeWarning)
        agent = laya.load(str(directory), device='mps' if device == 'mps:0' else 'cpu', backend='eager')
        if agent.device.type != ('mps' if device == 'mps:0' else 'cpu'):
            raise ValueError('Laya changed the requested device; inference refused.')
        result = agent.predict(inputs['state'], inputs['questions'])
        if result['usage'].get('truncated') or agent.cpu_fallback_count:
            raise ValueError('Laya truncated input or changed device; output refused.')
    for answer in result['answers'].values():
        answer.pop('action', None)
    result.update(device=device, runtime_versions=VERSIONS, calibration='not_qualified_for_this_domain')
    return result


def render_sources(image):
    from PIL import Image, ImageOps
    if Path(image).stat().st_size > 8 * 1024**2:
        raise ValueError('OCR source exceeds 8 MiB.')
    with open(image, 'rb') as stream:
        is_pdf = stream.read(5) == b'%PDF-'
    pages = []
    if is_pdf:
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(image) as document:
            if pdfium.raw.FPDF_GetSecurityHandlerRevision(document.raw) >= 0:
                raise ValueError('Encrypted PDF sources are unsupported.')
            if not 1 <= len(document) <= 5:
                raise ValueError('OCR PDF sources must contain 1–5 pages.')
            total_pixels = 0
            for number in range(len(document)):
                with contextlib.closing(document[number]) as page:
                    width, height = page.get_size()
                    if not all(math.isfinite(n) and 14 <= n <= 2000 for n in (width, height)):
                        raise ValueError('PDF page dimensions are outside the bounded renderer.')
                    scale = min(2, 2047 / max(width, height), math.sqrt(1_990_000 / (width * height)))
                    pixels = math.ceil(width * scale) * math.ceil(height * scale)
                    total_pixels += pixels
                    if total_pixels > 6_000_000:
                        raise ValueError('PDF rasterization exceeds the 6-million-pixel document limit.')
                    with contextlib.closing(page.render(scale=scale, may_draw_forms=False)) as bitmap:
                        normalized = bitmap.to_pil().convert('RGB')
                        reject_flat_image(normalized)
                        target = f'{image}-page-{number + 1}.png'
                        normalized.save(target)
                        pages.append({'page': number + 1, 'path': target, 'image_dimensions': list(normalized.size),
                            'raster_sha256': hashlib.sha256(normalized.tobytes()).hexdigest()})
        return pages, {'source_format': 'pdf', 'renderer': 'pypdfium2==5.14.0', 'max_scale': 2,
                       'normalization': 'pdfium_rgb', 'page_count': len(pages)}
    Image.MAX_IMAGE_PIXELS = 2_000_000
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(image) as source:
            if (source.format not in {'PNG', 'JPEG'} or getattr(source, 'n_frames', 1) != 1
                    or source.width * source.height > 2_000_000
                    or min(source.size) < 28 or max(source.size) > 2048):
                raise ValueError('OCR needs a single PNG/JPEG, 28–2048 pixels per edge and at most 2 million pixels.')
            source.load()
            normalized = ImageOps.exif_transpose(source).convert('RGB')
            reject_flat_image(normalized)
            normalized.save(str(image) + '.png')
            dimensions = list(normalized.size)
            pages.append({'page': 1, 'path': str(image) + '.png', 'image_dimensions': dimensions,
                          'raster_sha256': hashlib.sha256(normalized.tobytes()).hexdigest()})
    return pages, {'source_format': 'image', 'normalization': 'exif_transpose_rgb', 'page_count': 1}


def reject_flat_image(image):
    # The model invented a website on an all-white page in the qualification probe.
    if all(high - low <= 2 for low, high in image.getextrema()):
        raise ValueError('Blank or nearly uniform OCR pages are unsupported; no text was published.')


def layout_pages(directory, pages):
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForObjectDetection
    torch.set_num_threads(4)
    torch.set_default_device('cpu')
    processor = AutoImageProcessor.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False)
    model = AutoModelForObjectDetection.from_pretrained(str(directory), local_files_only=True, trust_remote_code=False).to('cpu').eval()
    count = 0
    for page in pages:
        with Image.open(page['path']) as source:
            with torch.inference_mode():
                output = model(**processor(images=source, return_tensors='pt'))
            result = processor.post_process_object_detection(output,
                target_sizes=torch.tensor([source.size[::-1]]), threshold=0.5)[0]
        regions = []
        for order, (box, label, score) in enumerate(zip(result['boxes'], result['labels'], result['scores'])):
            coordinates = box.tolist(); confidence = score.item()
            if not all(math.isfinite(n) for n in [*coordinates, confidence]) or not 0.5 <= confidence <= 1:
                raise ValueError('Layout detector returned nonfinite geometry.')
            width, height = page['image_dimensions']
            x1, y1, x2, y2 = [max(0, min(n, width if i % 2 == 0 else height)) for i, n in enumerate(coordinates)]
            if x2 <= x1 or y2 <= y1:
                raise ValueError('Layout detector returned an empty region.')
            regions.append({'region_id': f"page-{page['page']}-region-{order + 1}", 'order': order + 1,
                'label': model.config.id2label[label.item()], 'confidence': round(confidence, 6),
                'box': [round(n, 3) for n in (x1, y1, x2, y2)],
                'coordinate_system': 'normalized_page_rgb_pixels_xyxy'})
        count += len(regions)
        if not regions or count > 24:
            raise ValueError('Layout extraction needs 1–24 detected regions per document; no partial result was published.')
        page['regions'] = regions
    return pages


def detect_layout(directory, device, inputs, image):
    validate_ocr(inputs)
    if device != 'cpu':
        raise ValueError('Layout detection requires explicit CPU placement.')
    pages, rasterization = render_sources(image)
    pages = layout_pages(directory, pages)
    return {'pages': [{k:v for k,v in p.items() if k != 'path'} for p in pages], 'rasterization': rasterization,
        'device': device, 'runtime_versions': VERSIONS, 'usage': {'pages':len(pages),
        'regions':sum(len(p['regions']) for p in pages)}, 'layout_threshold':0.5}


def recognize(directory, device, inputs, image, layout_directory=None):
    validate_ocr(inputs)
    if device != 'mlx:0':
        raise ValueError('GLM-OCR requires explicit mlx:0.')
    pages, rasterization = render_sources(image)
    if layout_directory:
        pages = layout_pages(Path(layout_directory), pages)
    import mlx.core as mx
    from mlx_vlm import load, stream_generate
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import prepare_inputs, should_add_special_tokens
    if not mx.metal.is_available():
        raise ValueError('MLX Metal is unavailable.')
    mx.set_default_device(mx.gpu)
    allowance = mx.device_info().get('max_recommended_working_set_size', 0)
    if allowance - mx.get_active_memory() < 2 * (directory / 'model.safetensors').stat().st_size + 512 * 1024**2:
        raise ValueError('MLX process memory headroom is insufficient for OCR.')
    model, processor = load(str(directory), trust_remote_code=False, local_files_only=True)
    results, usage = [], {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'peak_memory_gb': 0}
    for page in pages:
        targets = page.get('regions', [{'label':'text'}]); texts = []
        for region in targets:
            if region['label'] in {'image', 'chart', 'seal'}:
                continue
            path = page['path']
            if layout_directory:
                from PIL import Image, ImageOps
                width, height = page['image_dimensions']
                x1,y1,x2,y2 = region['box']
                crop_box = [max(0, math.floor(x1)-2), max(0, math.floor(y1)-2),
                            min(width, math.ceil(x2)+2), min(height, math.ceil(y2)+2)]
                with Image.open(path) as source:
                    crop = source.crop(crop_box)
                region.update(crop_box=crop_box, crop_sha256=hashlib.sha256(crop.tobytes()).hexdigest())
                crop = ImageOps.expand(crop, border=(max(0, (28-crop.width+1)//2), max(0, (28-crop.height+1)//2)), fill='white')
                path = f"{page['path']}-{region['order']}.png"; crop.save(path)
            task = 'Table Recognition:' if region['label'] == 'table' else 'Formula Recognition:' if region['label'] == 'formula' else 'Text Recognition:'
            prompt = apply_chat_template(processor, model.config, task, num_images=1)
            tensors = prepare_inputs(processor, images=[path], prompts=prompt,
                image_token_index=getattr(model.config, 'image_token_index', None),
                add_special_tokens=should_add_special_tokens(model.config.model_type, processor))
            if tensors['input_ids'].size > 4096:
                raise ValueError('OCR processor output exceeds the 4096-token region budget.')
            tensors['mask'] = tensors.pop('attention_mask', None)
            text, last = '', None
            for part in stream_generate(model, processor, prompt, image=[path],
                                        max_tokens=inputs['max_tokens'], temperature=0, **tensors):
                text += part.text; last = part
            if last is None or last.finish_reason != 'stop' or not text.strip():
                raise ValueError('OCR output is empty or reached its token limit; no partial text was published.')
            region['text'] = text; texts.append(text)
            for key, value in [('input_tokens', last.prompt_tokens), ('output_tokens', last.generation_tokens), ('total_tokens', last.total_tokens)]:
                usage[key] += value
            usage['peak_memory_gb'] = max(usage['peak_memory_gb'], last.peak_memory)
        if not texts:
            raise ValueError('No text regions were recognized; no dataset was published.')
        results.append({k:v for k,v in {**page, 'text':'\n\n'.join(texts)}.items() if k != 'path'})
    return {'text': '\n\n'.join(p['text'] for p in results), 'pages': results, 'rasterization': rasterization,
            'device': device, 'runtime_versions': VERSIONS, 'image_dimensions': results[0]['image_dimensions'],
            'usage': usage, 'finish_reason': 'stop'}


def main():
    import resource
    import signal
    # An orphaned GPU child must release its inherited device lease even if the API dies.
    signal.alarm(120)
    resource.setrlimit(resource.RLIMIT_CPU, (115, 115))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024**2, 2 * 1024**2))
    # macOS does not provide a usable RLIMIT_AS for Metal; input/model/output caps apply.
    try:
        for name, version in VERSIONS.items():
            if importlib.metadata.version(name) != version:
                raise ValueError('Install the exact pinned specialist runtime versions.')
        if len(sys.argv) == 3 and sys.argv[1] == '--probe':
            device = sys.argv[2]
            if device == 'mps:0':
                import torch
                if not torch.backends.mps.is_available():
                    raise ValueError('MPS is unavailable.')
            elif device == 'mlx:0':
                import mlx.core as mx
                if not mx.metal.is_available():
                    raise ValueError('MLX Metal is unavailable.')
            elif device != 'cpu':
                raise ValueError('Unknown device.')
            sys.stdout.write(json.dumps({'device':device, 'runtime_versions':VERSIONS}))
            return 0
        raw = sys.stdin.buffer.read(64000)
        request = json.loads(raw)
        with contextlib.redirect_stdout(sys.stderr):
            directory = Path(request['directory'])
            if request['kind'] == 'laya':
                result = decide(directory, request['device'], request['inputs'])
            elif request['kind'] == 'ocr':
                result = recognize(directory, request['device'], request['inputs'], request['image'], request.get('layout_directory'))
            elif request['kind'] == 'layout':
                result = detect_layout(directory, request['device'], request['inputs'], request['image'])
            else:
                raise ValueError('Unknown specialist kind.')
        sys.stdout.write(json.dumps(result, allow_nan=False))
        return 0
    except ValueError as exc:
        sys.stdout.write(json.dumps({'error': str(exc)}))
    except Exception:
        sys.stdout.write(json.dumps({'error': 'Specialist runtime failed; check model, image, device and dependency compatibility.'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
