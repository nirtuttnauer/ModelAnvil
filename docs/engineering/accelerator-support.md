# Operation-specific accelerator support

Hardware detection, installed runtime compatibility, actual operation execution and model quality are separate facts. The new read-only support report checks the exact installed text profile before any model/job is created. Existing load and training preflight paths remain authoritative for actual inputs, current memory, device admission, worker capacity and budgets. A visible graphics adapter or a successful primitive diagnostic never qualifies a model or a release.

## Inspect this installation

```sh
python manage.py accelerator_support
python manage.py accelerator_support --operation full_sft --device mps:0
python manage.py accelerator_support --operation lora_adapter --device cpu
python manage.py accelerator_support --operation qlora_adapter --device mlx:0 --quantization int4
python manage.py accelerator_support --operation qlora_adapter --device mlx:0 --quantization int4 --precision bf16
```

The corresponding authenticated Viewer endpoint is `GET /api/v1/compute-support/`. Supply `operation` and `device` together for one selection, optionally `precision`, `quantization` and boolean `offload`. Unknown or duplicate parameters are refused. Results are `Cache-Control: no-store`; the endpoint creates no models, jobs, workers or quota reservations. An unavailable CLI selection returns a nonzero exit with a structured reason. The catalog describes available combinations; it does not silently select a device or alter a recipe.

The report covers the exact public SmolLM2-135M text source at `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. It checks fixed package pins, importable CPU framework identity, declared recipes, host memory and the existing device probes. GPU training probes require a visible matching backend, known physical identity where the runtime requires it, and live process headroom. GPU driver/framework initialization is part of detection; no model tensors or training jobs are created. Runtime package versions and CUDA/HIP build versions are not mislabeled as independently measured vendor driver versions.

## Current matrix

| Operation / backend | Software and installed checks | Measured evidence and remaining gate |
|---|---|---|
| 135M Safetensors FP32 inference / CPU | Explicit CPU; exact PyTorch/Transformers/tokenizer/Safetensors pins and bounded snapshot/model load checks | Fresh TASK-35 actual JSON/SSE, decoded tokens, replay, cancellation, source/project isolation and unload. No general model-quality qualification. |
| Same inference / Apple MPS | Explicit `mps:0`; available MPS, sufficient process allowance, CPU kernel fallback disabled | Fresh TASK-35 same greedy output/usage as CPU, actual MPS parameter residency and unload observations. True MPS peak/reserved/global free-memory counters are not invented. |
| Dense MLX inference / Apple GPU | Native Metal runtime, explicit default GPU, compatible reviewed snapshot | Fresh TASK-35 actual JSON/SSE, computed-token accounting, replay/cancel, default-CPU refusal and live authority revocation. This is the dense profile, not a claim for every MLX quantization. |
| F16 GGUF inference / CPU | Optional pinned llama.cpp binding; GPU layers zero and KV/operation offload disabled | Fresh TASK-35 actual decoded tokens, matching greedy output, native cancellation and cleanup. Vulkan has its own row; no GPU claim here. |
| F16, Q8_0, Q4_K_M GGUF inference / `vulkan:0` (inference only) | Pinned llama.cpp `f5027fb` Vulkan build with Metal not compiled; Homebrew MoltenVK 1.4.2 and Vulkan loader 1.4.363.0 on macOS 27.2.1 arm64. Server binary, ICD manifest, driver and loader bytes, the single visible device and full offload are rechecked per session | TASK-41 on the Apple M5 Pro: 31/31 layers and the KV cache on Vulkan0, decoded output, tokens/s, buffers, op placement and `test-backend-ops`. F16 greedy output equals the CPU-only build of the same commit on 3/3 prompts; Q8_0 (0/3) and Q4_K_M (1/3) diverge after a shared prefix. Inference only. See [Vulkan GGUF inference](#vulkan-gguf-inference-task-41). |
| 135M FP32 full SFT and rank-8 q/v LoRA / Apple MPS | Exact current training contract, package pins, minimum host/GPU process allowance, dedicated local device admission | Fresh TASK-35 three-step training and immutable ZIP exports for each recipe; independent CPU and MPS candidate reloads agree, exact optimizer/checkpoint recovery, cancellation and corrupt-input accounting pass. Authored correctness data does not establish domain quality. |
| Same full SFT / LoRA / CPU | Separate one-thread, 16 GiB, 20-step CPU contract; no device substitution | Bounded pretrained CPU mechanics/export evidence remains in TASK-15/TASK-27. Current support inspection is compatibility, not a new CPU training measurement. |
| Native four-bit affine group-32 QLoRA / MLX GPU | Explicit `qlora_adapter`, `mlx:0`, `int4` base and FP32 rank-8 adapters; FP32 or BF16 compute and the other [optimization profile](native-apple-adapter-training.md#optimization-profile) settings; exact MLX package/working-set checks | Earlier TASK-77 records actual updates, exports and recovery, with an explicit failed comparison against the unquantized baseline. TASK-16's [controlled Apple M5 Pro comparison](verification/task16-mlx-2026-11-15/README.md) qualifies BF16 compute, gradient checkpointing, packing and the forced fused attention kernel against the FP32 baseline within a 1% held-out tolerance on that Mac only; Adafactor failed and is refused. TASK-35 refreshes dense inference, not that training/quality gate. |
| Continued pretraining / CPU and GPU text contracts | Listed only when the selected runtime contract contains the recipe; exact frozen corpus/source pins and protected splits required | TASK-26 adds actual bounded CPU two-shard training, independent original-test loss proxies, candidate export and exact optimizer/cursor recovery. See [the corpus contract and separate qualification gates](continued-pretraining.md). This CPU evidence does not qualify other devices or production quality. |
| CUDA / NVIDIA text training | CUDA build, visible selected device, UUID/capacity, exact profile dependencies and options required | This Mac has no CUDA device/build. Refusal is measured; actual vendor hardware load/train/export qualification remains held. No CPU result is presented as CUDA work. |
| ROCm / AMD text training | HIP build through PyTorch's CUDA namespace, explicit `rocm:N`, AMD identity retained | This Mac has no ROCm hardware/build. Detection-policy fixtures do not qualify AMD devices; actual vendor execution remains held. |
| XPU / Intel text training | Compatible XPU build, visible explicit device, identity/memory probes supported by that runtime | This Mac has no XPU device. Missing UUID/free-memory support is a refusal, not an invented capacity. Actual Intel qualification remains held. |
| Other operations / models | Vision, speech, DPO and RLOO have their own fixed processor/source/device contracts | See TASK-28 vision CPU/MPS, TASK-29 CPU speech, TASK-23 Apple DPO and TASK-24 CPU reward/RLOO evidence. This text report does not extend any of those to other vendors, models or training methods. Current OCR, ASR, diffusion and distributed hardware gates remain separate. |

All reported `model_qualified` and `production_qualified` flags remain false. Compatibility can be true while a candidate fails its quality gate, while the device is busy, or while no actual model has been loaded. Process allowances are not global free memory or reservations. Actual launch still rechecks capacity and acquires the shared physical device lease.

## Precision, fallback and offload

The named full-SFT/LoRA profiles require FP32, unquantized base weights and no model/optimizer offload. FP16/BF16, unsupported quantization, CUDA QLoRA, implicit CPU fallback and automatic recipe changes are refused before loading. Native MLX QLoRA is a distinct explicit implementation with its declared quantization; it is not an alias for a CUDA adapter recipe. It alone accepts `bf16`, meaning BF16 matmuls with an FP32 residual stream, logits, adapters and optimizer state. FP16 is refused there because no loss scaling is implemented. Every FP8 variant is refused on every listed device: MLX 0.32.3 offers FP8 only as storage conversion, with no FP8 matmul or training dtype on Apple GPUs, and no other GPU has an FP8 measurement. `PYTORCH_ENABLE_MPS_FALLBACK=1` refuses MPS selection. The underlying execution paths also validate real tensor residency and retain actual backend identity in their receipts.

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

## Vulkan GGUF inference (TASK-41)

`vulkan:0` is a separately named, **inference-only** GGUF backend: llama.cpp's Vulkan backend reaching this Mac's Apple M5 Pro GPU through the MoltenVK translation layer. It is qualified for exactly that device and software stack. There is no discrete-GPU, other-vendor, Linux, Windows or DirectML claim, and Vulkan inference does not imply Vulkan training: `select_device`, GPU worker setup and every training row of the support report refuse Vulkan selectors before any allocation.

| Fact | Qualified value |
|---|---|
| Device | Apple M5 Pro integrated GPU, Vulkan device `Vulkan0`, vendor `0x106b`, MoltenVK driver ID, unified memory (48 GiB heap reported) |
| OS | macOS 27.2.1 (build 26B131), arm64 |
| Driver / loader | Homebrew `molten-vk` 1.4.2 (Vulkan API 1.4.357, conformance 1.4.4.0, driverVersion 0.2.2210) through Homebrew `vulkan-loader` 1.4.363.0; only the MoltenVK ICD manifest is passed to the child and implicit layers are disabled |
| Runtime | llama.cpp `f5027fb21307eb264aed483242603d68c87b0fe3` (build 11836) `llama-server`, Vulkan on, Metal and BLAS not compiled, static, built with Homebrew CMake 4.5.0 |
| Formats | GGUF, llama architecture, `general.file_type` F16, Q8_0 or Q4_K_M, at most 1 GiB of weights and 2,048 context tokens (measured: pinned SmolLM2-135M-Instruct). Q4_K_M on this 576-wide model is a mix of Q4_K, Q5_0, Q6_K and Q8_0 tensors because K-quants need 256-wide rows. Other quantizations, architectures, sizes and multimodal projectors are refused |
| Placement | Every layer and the KV cache on `Vulkan0` (llama.cpp reports `offloaded 31/31 layers`). The token-embedding table stays in Vulkan host-visible memory and its `GET_ROWS` lookup runs on the CPU, as llama.cpp does for the input layer on every GPU backend; every other node of the model graph (`MUL_MAT`, `FLASH_ATTN_EXT`, `ROPE`, `RMS_NORM`, `SWIGLU`, `ADD`, `MUL`, `SET_ROWS`, `DUP` and the output-row `GET_ROWS`) runs on Vulkan |

The [TASK-41 evidence](verification/task41-moltenvk-2026-11-15/README.md) records the exact build, environment, hashes, decoded output, tokens per second, buffers, op placement and `test-backend-ops` results. F16 greedy output is identical to the CPU-only build of the same commit on all three pinned prompts. Q8_0 and Q4_K_M outputs are deterministic on each backend but differ from the CPU build after a shared prefix (Q8_0 on 3/3 prompts, Q4_K_M on 2/3) because Vulkan's quantized kernels round and accumulate differently; this is reported rather than hidden and is not a quality claim. `test-backend-ops support` reports type/shape combinations this device does not support (for example some `CPY`, `SET_ROWS` and `MUL_MAT` type pairs, most `OUT_PROD`, all `TOP_K_MASK`); the qualified model graph uses none of them, as its scheduler trace shows, and a model needing them is outside this qualification. The graph's ops passed `test-backend-ops test` against the CPU backend.

### Install, build and configure

1. `brew install molten-vk vulkan-loader vulkan-headers vulkan-tools shaderc` (pulls `glslang`, `spirv-headers`, `spirv-tools`). `vulkaninfo --summary` must show one `Apple M5 Pro` device with `driverName = MoltenVK`.
2. `brew install cmake`, check out llama.cpp `f5027fb21307eb264aed483242603d68c87b0fe3` outside the repository and build it with Vulkan on and Metal off: `cmake -S llama.cpp -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_VULKAN=ON -DGGML_METAL=OFF -DGGML_BLAS=OFF -DLLAMA_OPENSSL=OFF -DGGML_NATIVE=ON -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF`, then `cmake --build build --config Release -j 8 --target llama-server llama-completion llama-bench llama-quantize test-backend-ops`. The UI options keep the build offline (no web UI download); the server runs with `--no-webui`. The measured [build record](verification/task41-moltenvk-2026-11-15/build-record-vulkan.json) lists the CMake cache values, compile flags, linked libraries and hashes. Build the CPU-only reference the same way with `-DGGML_VULKAN=OFF`.
3. Set operator-owned JSON (never accepted over HTTP):

```json
{"server": {"path": "/absolute/path/to/llama-server", "sha256": "ACTUAL_BINARY_SHA256"},
 "icd": "/opt/homebrew/etc/vulkan/icd.d/MoltenVK_icd.json",
 "loader": "/opt/homebrew/opt/vulkan-loader/lib/libvulkan.1.dylib",
 "cpu_fallback": false}
```

as `MODELANVIL_VULKAN_INFERENCE`, restart the API, and inspect `python manage.py accelerator_support --operation gguf_inference --device vulkan:0 --quantization f16` (or `GET /api/v1/compute-support/?operation=gguf_inference&device=vulkan:0&quantization=f16`). The code pins the qualified ICD manifest, MoltenVK and loader SHA-256 values and the macOS version, so a Homebrew upgrade or OS update makes the backend refuse until it is requalified.

### Execution, evidence, fallback and isolation

A chat completion with `"device": "vulkan:0"` on a GGUF model takes the shared Apple GPU lease (the same physical lease as `mps:0` and `mlx:0`), re-verifies the installation and the single visible device, starts a private `llama-server` on an ephemeral `127.0.0.1` port with a fresh per-session bearer key, a minimal environment, `--n-gpu-layers all --fit off --split-mode none`, no prompt or slot caches, and then requires llama.cpp's own load report to show every layer and the KV cache on `Vulkan0`. The request record and response carry `backend: llama.cpp-vulkan`, `gpu_execution: true`, offloaded/total layers, per-device model/KV/compute buffer sizes, the device's reported free memory, flash-attention state and the server/ICD/driver/loader identities. Load receipts are bound to those identities, so a changed binary or driver no longer counts as load-tested.

If the Vulkan backend is unavailable (not configured, changed bytes, unqualified host or format, no qualified device, failed or partial offload) the request fails closed. Only when the operator sets `"cpu_fallback": true` does ModelAnvil release the GPU lease, take the CPU lease and run the existing CPU GGUF path. That response reports `device: cpu`, `requested_device: vulkan:0` and a `fallback` record (`operator_opt_in`, reason, `gpu_execution: false`, `billing_device: cpu`); the stored receipt is CPU evidence and never load-tests `vulkan:0`. A busy GPU lease is not a fallback trigger. Chat completions create no GPU billing events.

Cancellation stops native generation and accounts computed tokens exactly as the CPU GGUF path does. A native crash fails that request, releases admission and leaves the next request to start a fresh server; the server child inherits the GPU lease and a hard lifetime, so an orphan cannot overlap another GPU user. Projects and tenants keep the existing model, artifact and key boundaries; each session's server, port and key are private to one request and removed on unload.

### Requalify

Rebuild and requalify after changing llama.cpp, MoltenVK, the loader, macOS or the device: run `scripts/qualify_vulkan_inference.py` with the Vulkan and CPU-only builds and the GGUF files into a new private directory, then the tagged native tests (`MODELANVIL_VULKAN_INFERENCE=... MODELANVIL_GGUF_TEST_MODEL=... python manage.py test modelanvil.runners.test_vulkan_runtime --tag=vulkan`), and update the pinned values in `modelanvil/runners/vulkan_runtime.py` only from those new measurements.
