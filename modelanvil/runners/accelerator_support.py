"""Non-model operation readiness for one pinned text profile; qualification stays separate."""
import os
import platform
import re
from datetime import datetime,timezone
from modelanvil.accelerators import inventory,select_device

OPERATIONS=('text_inference','full_sft','lora_adapter','qlora_adapter','continued_pretraining','gguf_inference')
SELECTORS=('cpu','cuda:0','rocm:0','xpu:0','mps:0','mlx:0','vulkan:0')
GGUF_QUANTIZATIONS=('f16','q8_0','q4_k_m')
TRAINING=('full_sft','lora_adapter','qlora_adapter','continued_pretraining')


def inspect_gguf(row,selector,quantization,offload):
    """GGUF inference only: explicit CPU binding or the TASK-41 MoltenVK Vulkan backend, never training."""
    from importlib.util import find_spec
    from modelanvil.runners import vulkan_runtime
    row.update(precision=None,inference_only=True,training_supported=False,cpu_fallback=False,
        qualification_scope='Installation compatibility only; the qualified GGUF files and device are listed in docs/engineering/accelerator-support.md.')
    if selector not in ('cpu','vulkan:0'):
        row['reason']='GGUF inference runs on explicit cpu or the separately qualified, inference-only vulkan:0 backend.';return row
    if quantization not in GGUF_QUANTIZATIONS:
        row['reason']='Select the GGUF quantization explicitly: f16, q8_0 or q4_k_m.';return row
    if type(offload) is not bool or offload:
        row['reason']='Partial CPU layer offload is not a qualified GGUF profile; vulkan:0 requires every layer on the device.';return row
    try:
        if selector=='cpu':
            if not find_spec('xllamacpp') or not find_spec('gguf'):
                raise ValueError('Install requirements.inference.txt for CPU GGUF inference.')
            row.update(backend='llama.cpp-cpu',observed_device={'device':{'id':'cpu','backend':'cpu'},'cpu_threads':1,'gpu_layers':0})
        else:
            observed=vulkan_runtime.inspect()
            row.update(backend=vulkan_runtime.BACKEND,observed_device=observed,qualification_scope=vulkan_runtime.QUALIFICATION,
                cpu_fallback=vulkan_runtime.cpu_fallback_opted_in(),
                cpu_fallback_policy='Operator opt-in only (MODELANVIL_VULKAN_INFERENCE cpu_fallback); a fallback run is recorded and labelled cpu, never GPU.')
        row.update(installed_compatible=True,recipe_changed=False,
            reason='Installed GGUF runtime checks pass without loading a model. Launch verifies the exact file, every layer offloaded and device admission.')
    except ValueError as exc:
        row['reason']=str(exc)
    return row


def inspect(operation,selector,*,precision='fp32',quantization='none',offload=False,observed=None):
    row={'operation':operation,'device':selector,'installed_compatible':False,'reason':'',
        'model_loaded':False,'tensors_created':False,'model_qualified':False,'production_qualified':False,
        'qualification_scope':'Installation compatibility only. Actual model/device/operation evidence is separate.',
        'precision':precision,'quantization':quantization,'offload':offload}
    def refuse(reason):row['reason']=reason;return row
    if operation not in OPERATIONS:return refuse('Choose one listed text operation.')
    if isinstance(selector,str) and re.fullmatch(r'vulkan(?::\d+)?',selector):
        from modelanvil.runners.vulkan_runtime import INFERENCE_ONLY
        if operation in TRAINING:row.update(inference_only=True,training_supported=False);return refuse(INFERENCE_ONLY)
        if selector!='vulkan:0':return refuse('Only vulkan:0, the Apple GPU through MoltenVK, has Vulkan inference qualification.')
        if operation!='gguf_inference':return refuse('Vulkan serves GGUF only; select the gguf_inference operation.')
    if operation=='gguf_inference':return inspect_gguf(row,selector,quantization,offload)
    if not isinstance(selector,str) or not re.fullmatch(r'cpu|(?:cuda|rocm|xpu):(?:0|[1-9][0-9]*)|mps:0|mlx:0',selector):
        return refuse('Select an explicit cpu, cuda:N, rocm:N, xpu:N, mps:0, mlx:0 or (GGUF inference only) vulkan:0; auto selection is unavailable.')
    if type(offload) is not bool or offload:
        return refuse('This profile requires FP32 and refuses model/optimizer offloading; no recipe is changed automatically.')
    if isinstance(precision,str) and 'fp8' in precision.lower():
        return refuse('FP8 is not qualified on any listed device: MLX 0.32.3 has no FP8 training dtype on Apple GPUs, and no other GPU has an FP8 measurement.')
    if operation=='qlora_adapter' and precision not in ('fp32','bf16'):
        return refuse('Native QLoRA computes in FP32 or BF16 with FP32 adapters and optimizer state; FP16 needs loss scaling and is not qualified.')
    if operation!='qlora_adapter' and precision!='fp32':
        return refuse('This profile requires FP32 and refuses model/optimizer offloading; no recipe is changed automatically.')
    if quantization!=('int4' if operation=='qlora_adapter' else 'none'):
        return refuse('Native QLoRA requires explicit int4 base weights and FP32 adapters; other listed profiles require unquantized weights.')
    if operation=='qlora_adapter' and selector!='mlx:0':return refuse('This installed QLoRA implementation supports only explicit Apple mlx:0; CUDA/ROCm/XPU variants need separate implementations and qualification.')
    if operation!='qlora_adapter' and selector=='mlx:0':return refuse('Select the native qlora_adapter operation for MLX training; dense MLX inference has its own documented profile.')
    if operation=='text_inference' and selector not in ('cpu','mps:0'):
        return refuse('This named FP32 inference support profile is bounded to CPU or Apple MPS; other hardware needs separate inference qualification.')
    try:
        from modelanvil.runners.training import hf_runtime,cpu_hf_runtime,mlx_runtime
        module=mlx_runtime if operation=='qlora_adapter' else cpu_hf_runtime if selector=='cpu' else hf_runtime
        if operation!='text_inference' and operation not in module.CONTRACT['recipes']:
            return refuse('The selected operation is absent from this installed runtime contract; select a supported recipe without automatic substitution.')
        module.require_packages()
        if operation=='lora_adapter':hf_runtime.require_adapter_package()
        if selector=='mps:0' and os.environ.get('PYTORCH_ENABLE_MPS_FALLBACK')=='1':
            return refuse('Unset PYTORCH_ENABLE_MPS_FALLBACK; Apple GPU results cannot include silent CPU kernel fallback.')
        from modelanvil.runners.training.hardware import total_memory_bytes
        host=total_memory_bytes();minimum=8*1024**3 if operation=='text_inference' else module.LIMITS['memory_bytes']
        if type(host) is not int or host<minimum:return refuse('Host memory is unknown or below the pinned profile minimum.')
        row.update(profile_source=hf_runtime.SOURCE,packages=module.PACKAGES,host_memory_bytes=host,
            required_host_memory_bytes=minimum,runtime_contract=module.CONTRACT_DIGEST if operation!='text_inference' else None,
            recipe_changed=False,cpu_fallback=False)
        if operation=='text_inference' and selector=='mps:0':
            device=select_device(observed or inventory(),selector)
            memory=hf_runtime.mps_memory();required=4*269060552+256*1024**2
            if memory['process_headroom_bytes']<required:return refuse('MPS process allowance is insufficient for the exact135M FP32 snapshot.')
            row['observed_device']={'device':device,'memory':memory}
        elif selector=='cpu':
            framework=(observed or inventory())['framework'].get('version')
            if not framework or framework.split('+')[0]!=module.PACKAGES['torch']:
                return refuse('The imported CPU tensor framework is unavailable or differs from its exact package pin; repair the runtime before loading.')
            row['observed_device']={'device':{'id':'cpu','backend':'cpu'},'cpu_threads':1}
        else:
            # Existing runtime probes check visibility, exact packages, UUID and live process headroom.
            row['observed_device']=module.observed_device(selector)
        row.update(installed_compatible=True,reason='Installed profile/device checks pass without loading a model. Launch still verifies exact inputs, quotas, current capacity and device admission.')
    except Exception as exc:
        row['reason']=str(exc) if isinstance(exc,ValueError) else f'Backend inspection failed ({type(exc).__name__}); repair the installed runtime/driver before selecting it.'
    return row


def report():
    observed=inventory()
    selectors=list(SELECTORS)
    for backend in observed['backends'].values():
        for device in backend['devices']:
            if device['id'] not in selectors:selectors.append(device['id'])
    rows=[inspect(operation,device,quantization={'qlora_adapter':'int4','gguf_inference':'f16'}.get(operation,'none'),observed=observed)
        for operation in OPERATIONS for device in selectors]
    rows.append(inspect('qlora_adapter','mlx:0',precision='bf16',quantization='int4',observed=observed))
    return {'schema_version':'modelanvil.operation-support.v1','observed_at':datetime.now(timezone.utc).isoformat(),
        'host':{'system':platform.system(),'release':platform.release(),'machine':platform.machine()},
        'framework_inventory':observed,'operations':rows,'automatic_backend_selection':False,
        'inference_only_backends':{'vulkan:0':'llama.cpp Vulkan GGUF inference through MoltenVK on the qualified Apple GPU; Vulkan training is not supported.'},
        'scope':'Named pinned SmolLM2-135M text operations. Other model families use their own runtime contracts; detection does not qualify them.',
        'production_qualified':False,'qualification_guide':'docs/engineering/accelerator-support.md'}
