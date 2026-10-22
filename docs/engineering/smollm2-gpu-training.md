# Bounded local SmolLM2 GPU training

TASK-13 implements an independent ModelAnvil runtime, `modelanvil.smollm2-gpu-sft.v1`, using PyTorch and Hugging Face Transformers. The existing CPU runtimes remain separate. The runtime supports full FP32 SFT and FP32 rank-8 q/v LoRA with AdamW, one text sample per step, 2–128 actual tokenizer tokens, 1–1000 steps and at most 1000 published rows. It consumes only the protected train split and rejects truncation, chat roles, incompatible inputs and unknown GPU memory capacity.

Apple Silicon also has a separate [native four-bit adapter profile](native-apple-adapter-training.md), selected with `--device mlx:0 --recipe qlora_adapter`. Its exported weights and adapter files use the standard MLX format and its measured quantization quality limit is recorded explicitly.

The same FP32 transformer runtime supports [continued pretraining](continued-pretraining.md) with `--recipe continued_pretraining`, a pinned published text corpus and measured protected validation loss at every step.

The source is [SmolLM2-135M](https://huggingface.co/HuggingFaceTB/SmolLM2-135M), Apache-2.0, pinned to commit `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. Five exact file digests are allowlisted in `hf_runtime.py`. Inputs are local committed tenant/project artifacts; checkpoints are verified Safetensors weight and Adam-moment artifacts. Loaders use local files only and cannot execute remote model code or load pickle weights.

## Environment and input preparation

Use Python 3.12 and install the control-plane requirements plus `requirements.gpu.txt` in the **same trusted local API/worker environment**. Select the correct PyTorch 2.13.0 vendor wheel and driver using the [official installer](https://pytorch.org/get-started/locally/); the optional requirements file alone is not a driver installer or a hermetic container. The pinned model libraries are Transformers 5.14.0, Safetensors 0.8.0 and Tokenizers 0.22.2. Framework build versions with a vendor suffix are accepted; the actual framework/build and hardware are recorded in run pins.

Acquire the immutable model explicitly before registering it. With the optional environment installed:

```python
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='HuggingFaceTB/SmolLM2-135M',
    revision='93efa2f097d58c2a74874c7e644dbc9b0cee75a2',
    allow_patterns=['model.safetensors', 'config.json', 'tokenizer.json',
                    'tokenizer_config.json', 'special_tokens_map.json'],
    local_dir='/path/to/smollm2-135m',
)
```

Supply canonical sample-envelope text JSONL from your own prepared data. Each row needs a unique sample identifier and source group, text blocks and provenance. Registration publishes protected train/validation/test splits. The command performs no download or training:

```sh
python manage.py setup_gpu_training \
  --tenant-id TENANT_UUID --project-id PROJECT_UUID --name unique-run-name \
  --model-dir /path/to/smollm2-135m --samples /path/to/canonical-text.jsonl \
  --device mps:0 --steps 3
```

It creates the verified base/tokenizer/dataset, runner, dedicated single-slot worker and a lifetime budget in **training steps**, and outputs a launch payload plus worker ID. It requires at least 8 GiB host memory and 4 GiB framework-reported GPU capacity; on MPS this uses the recommended shared-memory budget, not dedicated VRAM or free memory. It rejects `PYTORCH_ENABLE_MPS_FALLBACK=1`.

POST the returned `launch` object to `/api/v1/training-runs/preflight/` with your engineer API credential. Inspect itemized checks, actual encoded samples and requirements; then POST it with the returned `preflight_token` to `/api/v1/training-runs/`, using a unique `Idempotency-Key`. Launch and worker execution resolve and verify the pinned inputs again. GPU duration and money remain unknown; measured CPU process seconds are never presented as GPU elapsed time.

Execute the registered worker against the same local database and artifact root:

```sh
python manage.py run_worker --worker-id WORKER_ID \
  --executor modelanvil.runners.training.executor.training_worker_executor --once
```

Use the existing run/checkpoint/candidate APIs to inspect results. Model candidate metadata contains immutable file references rather than embedding hundreds of megabytes in database JSON. The independent consumer, `scripts/hf_candidate_infer.py`, takes a directory containing the verified model and tokenizer files without importing Django or ModelAnvil. It defaults to portable CPU inference; select `--device mps:0`, `cuda:N`, `rocm:N` or `xpu:N` explicitly for a compatible GPU runtime. It validates the selected backend and device residency and refuses CPU fallback. CUDA, ROCm and XPU remain unqualified until checked on their physical hardware.

The browser now also selects `lora_adapter` for this pinned model. Install `requirements.inference.txt` (including PEFT 0.21.2), register the current runner/worker contract and preview again. LoRA freezes base weights and trains 460,800 rank-8 q/v adapter parameters with alpha 16, zero dropout and non-reentrant gradient checkpointing. The initialization seed, profile, package and actual trainable count are pinned. Checkpoints retain immutable base references, actual adapter Safetensors and FP32 Adam moments; recovery restores their sampler cursor and optimizer state. Preflight and launch reject unsupported precision, adapter profiles and quantization before creating a job or reserving budget. On MPS, training and independent inference cap the process at 90% of the framework's recommended working set and require at least 4 GiB of remaining process allowance, including driver/cache allocations. This is not a system-wide free-memory measurement or a shared-device reservation. See the [current Mac host instructions](apple-gpu-host.md) and [TASK-40 verification](verification/task40-2026-10-11.md).

The dependency security update changes the runtime contract again. Reinstall the pinned environment, register the current runner/worker contract and launch a new run; existing checkpoints are not silently resumed under different package pins. The CPU adapter/recovery regression passes with these versions. Historical GPU reports retain their original version pins and do not qualify this updated stack; repeat the hardware checks before claiming GPU qualification. See [dependency security status](dependency-security.md) for audit coverage and the unresolved optional inference dependency.

## Reproduce the hardware checks

```sh
python scripts/qualify_hf_gpu.py \
  --model-dir /path/to/smollm2-135m --device mps:0 \
  --output /path/to/new-qualification-directory
```

The output directory must be new. The script explicitly selects an isolated database/artifact root, creates synthetic qualification samples, rejects unsupported request options before allocation, trains three steps, invokes independent CPU and selected-GPU inference processes, expires a lease during a later optimizer update and resumes, then tests cancellation and corrupt-input settlement. It asserts identical CPU/GPU greedy tokens for this fixture, exact final-weight recovery and one usage event. It leaves the isolated database, artifacts, candidate files and JSON reports there for inspection; allow roughly 15 GiB of disk space. These are correctness fixtures, not model quality or throughput benchmarks.

The [11 October MPS report](verification/task13-gpu-2026-10-11.md) is the evidence for the checked envelope. CUDA, ROCm and XPU have explicit selection/placement paths but have not been tested on their hardware. There is no MLX training, Vulkan, DirectML, QLoRA, quantization, distributed or remote-worker implementation in this training runtime. The separate local chat runtime supports MLX inference. TASK-37–40 own vendor qualification; TASK-41 owns Vulkan inference. Local cooperating API/training processes now share exclusive device admission; remote/cross-account/multi-device reservations and vendor qualification remain pending. Committed checkpoint retention and orphaned filesystem bytes after a database rollback still need an operator cleanup policy. Production qualification flags remain false.

## LoRA and measured telemetry extension

The runtime contract digest changed when LoRA, telemetry, strict deterministic operations and exclusive local device admission were added; existing registered runners/workers and unfinished runs retain their earlier pins and are rejected rather than silently migrated. Register the current contract and launch a new run. Historical qualification evidence describes its recorded code version. Deterministic operations are required for optimizer recovery; unsupported kernels fail instead of silently weakening reproducibility. PyTorch's prior deterministic mode is restored when execution exits.

Use `--recipe lora_adapter` with the qualification script to exercise real adapter updates, exact recovery, cancellation, corruption and independent inference. The [current Mac extension evidence](verification/modelanvil-lora-mac-2026-10-11.json) records both LoRA and requalified full SFT. LoRA saves adapter weights without PEFT Hub probes; all training/reload bytes stay local. The small CPU regression also proves frozen base parameters stay unchanged and optimizer recovery reproduces the next update exactly.

Training displays timestamped gradient norms, trainable/total parameters, prediction tokens per engine wall second and actual allocated memory. Throughput includes the post-update loss pass and excludes storage/queue time. MPS peak memory and utilization are unavailable and display “Not reported”; CUDA/XPU peak metrics have implementation paths but require vendor hardware qualification. Mixed precision, packing, low-memory optimizers, FP8 and QLoRA remain pending. These measurements do not establish controlled optimization speedups.

Completed transformer runs now download a ZIP containing actual verified model/tokenizer files and, for LoRA, actual adapter files. `GET /api/v1/training-runs/RUN_UUID/download/` authenticates and scopes the run, verifies all referenced bytes, and writes `modelanvil-provenance.json` with hashes and lineage. The ZIP includes the pinned base for adapter loading; use the independent consumer or explicitly instantiate that local base before loading PEFT. It does not contain optimizer moments. Both full SFT and LoRA archives were read back and every file hash matched the committed checkpoint. GGUF export/quantization and their quality benchmarks remain pending; the GGUF inference pilot used an explicit operator conversion.

Completed full-SFT and LoRA candidates appear in the local chat catalog. Inference checks the successful producing job, final checkpoint, candidate manifest, tokenizer relationship and accessible artifacts. Adapter reload isolates the pinned local base from Transformers' automatic adapter detection. Imported adapters without this verified candidate lineage are refused. Imported and trained model versions cannot be edited through the registry API.

## Protected documentation corpus pilot

The user delegated corpus and tolerance selection. The Mac pilot uses 20 versioned engineering documentation files from commit `98b930c3785799098c3a119f74729b646cbecfff`. Preprocessing explicitly takes up to 64 words from each file's first prose paragraph, bounds each example to 128 actual tokenizer tokens and removes identical text before publication. Source-file groups stay in separate train/validation/test splits. Three actual training examples are consumed; five validation and five test examples are independently scored. The target is reduced token-weighted training loss and at most 5% validation/test loss regression versus the pinned base. Both recipes passed. This small three-update pilot checks the implementation and its declared target; it does not establish production task quality.

```sh
python scripts/build_documentation_corpus.py --revision 98b930c \
  --model-dir /path/to/smollm2-135m --output /path/to/new-documentation.jsonl
python scripts/qualify_hf_gpu.py --recipe lora_adapter --device mps:0 \
  --model-dir /path/to/smollm2-135m --samples /path/to/new-documentation.jsonl \
  --output /path/to/new-pilot-directory
python scripts/qualify_candidate_chat.py --qualification /path/to/new-pilot-directory
```

Repeat with `--recipe full_sft` in a separate new directory. Independent CPU FP32 scoring imports neither Django nor ModelAnvil, rejects duplicate text and source-group overlap and fails qualification when the target is missed. The initial full-SFT real-text pilot exposed a recovery mismatch with nondeterministic operations; the current contract enables strict deterministic kernels and both final pilots recovered byte-identical weights. The evidence includes corpus/source hashes, measured losses, final contract/build pins, archive verification and CPU/GPU candidate chat results. Other GPU qualification remains pending as instructed.

## Exclusive local device admission

The current contract also requires exclusive local device use. API and workers under one OS account must share the same private `MODELANVIL_DEVICE_LOCK_ROOT`. PyTorch MPS and MLX contend for one Apple GPU identity. Strict file permissions and non-symlink regular lock files are required. The OS releases locks after process death; normal exit cleans model/optimizer allocations and caches before release. Preview and launch reject an observed busy device without job/budget allocation; execution rechecks admission to close the launch race. An execution-time conflict fails without GPU allocation and settles committed work only. This does not reserve memory against unrelated applications, different accounts, remote hosts or device groups. The build digest covers the admission implementation. See [Mac admission evidence](verification/modelanvil-device-admission-mac-2026-10-12.json).
