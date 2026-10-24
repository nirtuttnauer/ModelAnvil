"""Exact local vision snapshots and single-image, bounded chat."""
from contextlib import contextmanager
import gc
import io
import json
import time

from modelanvil.identity.models import check_resource_access
from modelanvil.runners.training import vlm_math as math
from modelanvil.runners.training.runtime import digest


def snapshot(version, tenant, project):
    from modelanvil.artifacts.models import Artifact
    from modelanvil.runners.models import TrainingRun
    from modelanvil.runners.inference import verified_artifact, copy_verified
    from modelanvil.runners.training import vlm_runtime, cpu_vlm_runtime
    from modelanvil.runners.training.hf_runtime import file_ref
    processor = version.processor
    if (not isinstance(version.metadata, dict) or not isinstance(version.tokenizer.compatibility, dict)
            or processor is not None and not isinstance(processor.metadata, dict)):
        raise ValueError('Vision snapshot metadata must be an object.')
    if (processor is None or not check_resource_access(processor, project, tenant)
            or processor.metadata.get('source') != math.SOURCE or processor.metadata.get('vision_profile') != math.PROCESSOR
            or processor.configuration_digest != digest({'source_files': math.FILE_HASHES, 'overrides': math.PROCESSOR})
            or version.tokenizer.compatibility.get('hf_snapshot') != math.SOURCE):
        raise ValueError('Vision inference requires the exact accessible processor and tokenizer.')
    ref = version.metadata.get('snapshot_manifest')
    trained = False
    if ref:
        if not isinstance(ref, dict) or ref.get('artifact_id') != version.artifact_manifest_id or processor.metadata.get('artifact_manifest_id') != version.artifact_manifest_id:
            raise ValueError('Vision source and processor manifest differ.')
        artifact = verified_artifact(ref, tenant, project)
        if artifact.byte_size > 1024**2: raise ValueError('Vision manifest exceeds its limit.')
        raw = io.BytesIO(); copy_verified(ref, tenant, project, raw)
        bundle = json.loads(raw.getvalue())
        if not isinstance(bundle, dict) or bundle.get('source') != math.SOURCE or set(bundle.get('files', {})) != set(math.FILE_HASHES):
            raise ValueError('Vision snapshot must include the complete pinned processor and base.')
    else:
        run = TrainingRun.all_objects.filter(output_model_version=version, tenant_id=tenant, status='completed',
            job__status='succeeded', base_model_version__architecture_ref__in=[vlm_runtime.RUNTIME_ID, cpu_vlm_runtime.RUNTIME_ID]).first()
        if (run is None or not check_resource_access(run, project, tenant) or run.tokenizer_version_id != version.tokenizer_id
                or run.base_model_version.processor_id != version.processor_id):
            raise ValueError('Vision candidate has no successful training lineage and processor.')
        checkpoint = run.checkpoints.filter(step=version.metadata.get('selected_checkpoint_step', run.total_steps)).first()
        if checkpoint is None or version.metadata.get('checkpoint_digest') != checkpoint.state_digest:
            raise ValueError('Vision candidate checkpoint lineage changed.')
        bundle = vlm_runtime.checkpoint_bundle(run, checkpoint)
        artifact = Artifact.all_objects.filter(artifact_id=version.artifact_manifest_id, tenant_id=tenant).first()
        if artifact is None or artifact.byte_size > 1024**2: raise ValueError('Vision candidate manifest is unavailable.')
        raw = io.BytesIO(); copy_verified(file_ref(artifact), tenant, project, raw)
        if digest(json.loads(raw.getvalue())) != digest(bundle): raise ValueError('Vision candidate manifest differs from its checkpoint.')
        trained = True
    files = bundle['files']
    if not isinstance(files, dict) or any(not isinstance(files.get(name), dict) or files[name].get('sha256') != sha for name, sha in math.FILE_HASHES.items()):
        raise ValueError('Vision snapshot files differ from the pinned source.')
    for ref in files.values(): verified_artifact(ref, tenant, project)
    return {'format': 'vision', 'files': files, 'source': math.SOURCE, 'trained': trained, 'recipe': 'lora_adapter'}


@contextmanager
def session(plan, *, image_id, tenant, project, device):
    import torch
    from modelanvil.device_admission import device_lease
    from modelanvil.runners.training import vlm_runtime
    from modelanvil.runners.training.vlm_data import read_image
    # Decode and reject before allocating the model or admitting a device.
    pixels, image_pin = read_image(image_id, tenant, project)
    vlm_runtime.require_packages(); vlm_runtime.observed_device(device)
    previous = torch.get_num_threads(); model = None; value = {}
    with device_lease(device):
        try:
            torch.set_num_threads(1)
            with vlm_runtime.staged_files(plan['files'], tenant, project) as directory:
                processor = math.processor(directory)
                model = math.load_model(directory).to(device)
                if any(str(p.device) != device for p in model.parameters()): raise ValueError('Vision model device residency changed.')
                value.update(format='vision', model=model, processor=processor, image=pixels, image_pin=image_pin, device=device)
                yield value
        finally:
            value.clear(); model = None; gc.collect()
            if device == 'mps:0': torch.mps.empty_cache()
            torch.set_num_threads(previous)


def generate(session, messages, *, max_tokens, temperature, prompt_format, cancelled):
    import torch
    if (len(messages) != 1 or messages[0]['role'] != 'user' or prompt_format != 'model'
            or temperature != 0 or not 1 <= max_tokens <= 16):
        raise ValueError('Vision chat supports one visual question, native formatting, greedy decoding and 1–16 output tokens.')
    encoded, prefix = math.encode(session['processor'], session['image'], messages[0]['content'])
    if prefix + max_tokens > 128: raise ValueError('Vision prompt and output must fit within 128 tokens; no truncation.')
    model, tokenizer, device = session['model'], session['processor'].tokenizer, session['device']
    current = {k: v.to(device) for k, v in encoded.items()}
    ids, text, started, finish = [], '', time.monotonic(), 'length'
    measurement = session.setdefault('measurement', {})
    eos = model.generation_config.eos_token_id
    eos = set(eos if isinstance(eos, list) else [eos])
    with torch.inference_mode():
        for _ in range(max_tokens):
            if cancelled(): finish = 'cancelled'; break
            logits = model(**current, use_cache=False).logits[0, -1].float()
            if not torch.isfinite(logits).all().item(): raise ValueError('Vision model produced non-finite logits.')
            token = int(logits.argmax().item()); ids.append(token)
            measurement.update(usage={'prompt_tokens': prefix, 'completion_tokens': len(ids), 'total_tokens': prefix+len(ids)},
                elapsed_seconds=time.monotonic()-started)
            if token in eos: finish = 'stop'; break
            decoded = tokenizer.decode(ids, skip_special_tokens=True, clean_up_tokenization_spaces=False)
            if not decoded.startswith(text): raise ValueError('Vision decoding changed an already emitted prefix.')
            if decoded[len(text):]: yield {'text': decoded[len(text):]}
            text = decoded
            current['input_ids'] = torch.cat([current['input_ids'], torch.tensor([[token]],device=device)],dim=-1)
            current['attention_mask'] = torch.ones_like(current['input_ids'])
    yield {'finish_reason': finish, 'elapsed_seconds': time.monotonic()-started,
        'usage': {'prompt_tokens': prefix, 'completion_tokens': len(ids), 'total_tokens': prefix+len(ids)}}
