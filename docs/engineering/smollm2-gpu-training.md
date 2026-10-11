# Bounded local SmolLM2 GPU training

TASK-13 implements an independent ModelAnvil runtime, `modelanvil.smollm2-gpu-sft.v1`, using PyTorch and Hugging Face Transformers. The existing CPU runtimes remain separate. This recipe is full FP32 SFT with AdamW, one text sample per step, 2–128 actual tokenizer tokens, 1–1000 steps and at most 1000 published rows. It consumes only the protected train split and rejects truncation, chat roles, incompatible inputs and unknown GPU memory capacity.

The source is [SmolLM2-135M](https://huggingface.co/HuggingFaceTB/SmolLM2-135M), Apache-2.0, pinned to commit `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. Five exact file digests are allowlisted in `hf_runtime.py`. Inputs are local committed tenant/project artifacts; checkpoints are verified Safetensors weight and Adam-moment artifacts. Loaders use local files only and cannot execute remote model code or load pickle weights.

## Environment and input preparation

Use Python 3.12 and install the control-plane requirements plus `requirements.gpu.txt` in the **same trusted local API/worker environment**. Select the correct PyTorch 2.9.0 vendor wheel and driver using the [official installer](https://pytorch.org/get-started/locally/); the optional requirements file alone is not a driver installer or a hermetic container. The pinned model libraries are Transformers 4.57.1, Safetensors 0.6.2 and Tokenizers 0.22.2. Framework build versions with a vendor suffix are accepted; the actual framework/build and hardware are recorded in run pins.

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

The GPU recipe accepts FP32 full SFT only. Preflight and launch reject requests for FP16/BF16, LoRA or quantization before creating a job or reserving budget. On MPS, training and independent inference cap the process at 90% of the framework's recommended working set and require at least 4 GiB of remaining process allowance, including driver/cache allocations. This is not a system-wide free-memory measurement or a shared-device reservation. See the [current Mac host instructions](apple-gpu-host.md) and [TASK-40 verification](verification/task40-2026-10-11.md).

## Reproduce the hardware checks

```sh
python scripts/qualify_hf_gpu.py \
  --model-dir /path/to/smollm2-135m --device mps:0 \
  --output /path/to/new-qualification-directory
```

The output directory must be new. The script explicitly selects an isolated database/artifact root, creates synthetic qualification samples, rejects unsupported request options before allocation, trains three steps, invokes independent CPU and selected-GPU inference processes, expires a lease during a later optimizer update and resumes, then tests cancellation and corrupt-input settlement. It asserts identical CPU/GPU greedy tokens for this fixture, exact final-weight recovery and one usage event. It leaves the isolated database, artifacts, candidate files and JSON reports there for inspection; allow roughly 15 GiB of disk space. These are correctness fixtures, not model quality or throughput benchmarks.

The [11 October MPS report](verification/task13-gpu-2026-10-11.md) is the evidence for the checked envelope. CUDA, ROCm and XPU have explicit selection/placement paths but have not been tested on their hardware. There is no MLX, Vulkan, DirectML, LoRA, QLoRA, quantization, distributed or remote-worker implementation in this runtime. TASK-37–40 own vendor qualification; TASK-41 owns Vulkan inference. TASK-42 must add shared-device admission/reservations before independent pools share a GPU. Committed checkpoint retention and orphaned filesystem bytes after a database rollback still need an operator cleanup policy. Production qualification flags remain false.
