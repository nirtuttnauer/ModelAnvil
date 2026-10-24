# Operation-specific accelerator support

Hardware detection, installed runtime compatibility, actual operation execution and model quality are separate facts. The new read-only support report checks the exact installed text profile before any model/job is created. Existing load and training preflight paths remain authoritative for actual inputs, current memory, device admission, worker capacity and budgets. A visible graphics adapter or a successful primitive diagnostic never qualifies a model or a release.

## Inspect this installation

```sh
python manage.py accelerator_support
python manage.py accelerator_support --operation full_sft --device mps:0
python manage.py accelerator_support --operation lora_adapter --device cpu
python manage.py accelerator_support --operation qlora_adapter --device mlx:0 --quantization int4
```

The corresponding authenticated Viewer endpoint is `GET /api/v1/compute-support/`. Supply `operation` and `device` together for one selection, optionally `precision`, `quantization` and boolean `offload`. Unknown or duplicate parameters are refused. Results are `Cache-Control: no-store`; the endpoint creates no models, jobs, workers or quota reservations. An unavailable CLI selection returns a nonzero exit with a structured reason. The catalog describes available combinations; it does not silently select a device or alter a recipe.

The report covers the exact public SmolLM2-135M text source at `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. It checks fixed package pins, importable CPU framework identity, declared recipes, host memory and the existing device probes. GPU training probes require a visible matching backend, known physical identity where the runtime requires it, and live process headroom. GPU driver/framework initialization is part of detection; no model tensors or training jobs are created. Runtime package versions and CUDA/HIP build versions are not mislabeled as independently measured vendor driver versions.

## Current matrix

| Operation / backend | Software and installed checks | Measured evidence and remaining gate |
|---|---|---|
| 135M Safetensors FP32 inference / CPU | Explicit CPU; exact PyTorch/Transformers/tokenizer/Safetensors pins and bounded snapshot/model load checks | Fresh TASK-35 actual JSON/SSE, decoded tokens, replay, cancellation, source/project isolation and unload. No general model-quality qualification. |
| Same inference / Apple MPS | Explicit `mps:0`; available MPS, sufficient process allowance, CPU kernel fallback disabled | Fresh TASK-35 same greedy output/usage as CPU, actual MPS parameter residency and unload observations. True MPS peak/reserved/global free-memory counters are not invented. |
| Dense MLX inference / Apple GPU | Native Metal runtime, explicit default GPU, compatible reviewed snapshot | Fresh TASK-35 actual JSON/SSE, computed-token accounting, replay/cancel, default-CPU refusal and live authority revocation. This is the dense profile, not a claim for every MLX quantization. |
| F16 GGUF inference / CPU | Optional pinned llama.cpp binding; GPU layers zero and KV/operation offload disabled | Fresh TASK-35 actual decoded tokens, matching greedy output, native cancellation and cleanup. GPU/Vulkan remains held separately. |
| 135M FP32 full SFT and rank-8 q/v LoRA / Apple MPS | Exact current training contract, package pins, minimum host/GPU process allowance, dedicated local device admission | Fresh TASK-35 three-step training and immutable ZIP exports for each recipe; independent CPU and MPS candidate reloads agree, exact optimizer/checkpoint recovery, cancellation and corrupt-input accounting pass. Authored correctness data does not establish domain quality. |
| Same full SFT / LoRA / CPU | Separate one-thread, 16 GiB, 20-step CPU contract; no device substitution | Bounded pretrained CPU mechanics/export evidence remains in TASK-15/TASK-27. Current support inspection is compatibility, not a new CPU training measurement. |
| Native four-bit affine group-32 QLoRA / MLX GPU | Explicit `qlora_adapter`, `mlx:0`, `int4` base and FP32 rank-8 adapters; exact MLX package/working-set checks | Earlier TASK-77 records actual updates, exports and recovery, with an explicit failed comparison against the unquantized baseline. TASK-35 refreshes dense inference, not that training/quality gate. |
| Continued pretraining / GPU text contract | Listed only when the selected runtime contract contains the recipe | Installed compatibility does not establish corpus/mixture or domain-gain evidence. TASK-26 retains that implementation/qualification scope. CPU contract support is reported from its actual recipe list. |
| CUDA / NVIDIA text training | CUDA build, visible selected device, UUID/capacity, exact profile dependencies and options required | This Mac has no CUDA device/build. Refusal is measured; actual vendor hardware load/train/export qualification remains held. No CPU result is presented as CUDA work. |
| ROCm / AMD text training | HIP build through PyTorch's CUDA namespace, explicit `rocm:N`, AMD identity retained | This Mac has no ROCm hardware/build. Detection-policy fixtures do not qualify AMD devices; actual vendor execution remains held. |
| XPU / Intel text training | Compatible XPU build, visible explicit device, identity/memory probes supported by that runtime | This Mac has no XPU device. Missing UUID/free-memory support is a refusal, not an invented capacity. Actual Intel qualification remains held. |
| Other operations / models | Vision, speech, DPO and RLOO have their own fixed processor/source/device contracts | See TASK-28 vision CPU/MPS, TASK-29 CPU speech, TASK-23 Apple DPO and TASK-24 CPU reward/RLOO evidence. This text report does not extend any of those to other vendors, models or training methods. Current OCR, ASR, diffusion and distributed hardware gates remain separate. |

All reported `model_qualified` and `production_qualified` flags remain false. Compatibility can be true while a candidate fails its quality gate, while the device is busy, or while no actual model has been loaded. Process allowances are not global free memory or reservations. Actual launch still rechecks capacity and acquires the shared physical device lease.

## Precision, fallback and offload

The named full-SFT/LoRA profiles require FP32, unquantized base weights and no model/optimizer offload. FP16/BF16, unsupported quantization, CUDA QLoRA, implicit CPU fallback and automatic recipe changes are refused before loading. Native MLX QLoRA is a distinct explicit implementation with its declared quantization; it is not an alias for a CUDA adapter recipe. `PYTORCH_ENABLE_MPS_FALLBACK=1` refuses MPS selection. The underlying execution paths also validate real tensor residency and retain actual backend identity in their receipts.

No automatic fallback is tested by relabeling a CPU run as GPU. CPU is an explicit independent choice with a different training contract. The new report does not authorize an unsupported backend or override any execution gate.

## Installation and recovery

Install the exact repository requirements for the chosen runtime in an isolated environment. A CUDA/ROCm/XPU host additionally needs a compatible vendor framework build and driver; neither copying this Mac's environment nor detecting a display adapter supplies those prerequisites. The existing inventory reports missing/broken framework import, wrong vendor build, unavailable devices, unknown capacity and partial enumeration as explicit refusals. Controlled fixtures exercise those policies without pretending to be real hardware installations.

After changing a driver, framework or execution build, restart the API and dedicated worker, inspect the operation again and rerun the named hardware qualification in a new private directory. Old load receipts are bound to their actual project, model, runtime, host and device. A historical JSON flag must not unlock new hardware or a changed build. Existing fenced job recovery accepts only matching checkpoint/input/runtime pins; changed profiles require diagnosis and a newly qualified run rather than a forced resume.

Fresh current-stack reproduction on a provisioned Mac, using local verified files:

```sh
python scripts/qualify_apple_inference.py --snapshot /verified/smollm2-base \
  --gguf /verified/smollm2-base-f16.gguf --output /private/new-inference-proof
python scripts/qualify_hf_gpu.py --model-dir /verified/smollm2-base \
  --device mps:0 --recipe full_sft --output /private/new-full-sft-proof
python scripts/qualify_hf_gpu.py --model-dir /verified/smollm2-base \
  --device mps:0 --recipe lora_adapter --output /private/new-lora-proof
```

These commands require a new output directory and create isolated synthetic application state. They use no paid host, provider or customer data. Revoke their temporary keys, suspend their fixture tenants and stop/offline the fixture workers after execution; TASK-35's cleanup receipts confirm that closure. Keep databases, model archives and raw logs private. The [TASK-35 evidence directory](verification/task35-accelerators-2026-10-24/) binds current source/package/device receipts and public summaries. Vendor hardware, clean physical OS installation, customer quality and production capacity are not inferred from this Mac run.
