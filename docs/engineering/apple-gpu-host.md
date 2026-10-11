# Current Mac GPU host

On 11 October 2026, the developer requested this computer as a GPU host and a **ModelAnvil GPU** project in **Default Organization**. That project, a dedicated single-slot worker and a three-step qualification fixture are now registered in the local `modelanvil.db`. The worker polling process was started against this database and `storage/artifacts`.

| Resource | Registered value |
| --- | --- |
| Organization | Default Organization |
| Project | ModelAnvil GPU (`658f7990-a750-44df-8bfd-d114355b67d5`) |
| Worker | ID `1`, pool `mac-mps-reference-gpu` |
| Device | Apple M5 Pro, 48 GiB unified host memory, `mps:0` |
| Runtime | `modelanvil.smollm2-gpu-sft.v1`, FP32 full SFT |
| Local Python | `.venv-gpu/bin/python`, CPython 3.12.15 |
| Tensor libraries | PyTorch 2.9.0, Transformers 4.57.1, Safetensors 0.6.2, Tokenizers 0.22.2 |
| Source snapshot | `data/smollm2-135m`, pinned SmolLM2-135M revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2` |
| Registration and launch payload | `runs/mac-gpu-host.json` (local, ignored) |

The control-plane `.venv` also has the optional GPU libraries so its preflight can inspect this worker. Use the main database and artifact root on both sides. No API keys were issued by this registration; use an existing authorized engineer credential in this organization/project.

## Start or restart

From the repository root, in a persistent terminal:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=0 OMP_NUM_THREADS=4 \
  .venv-gpu/bin/python manage.py run_worker --worker-id 1 \
  --executor modelanvil.runners.training.executor.training_worker_executor --interval 2
```

The process started during setup is a foreground poller, not an installed login/reboot service. Restart it with this command after it exits. Start only one poller for this worker. Stop it with Ctrl-C when idle. Keep worker and API code/environment aligned; restart the worker after runtime source changes.

In Training, select this project's `mac-mps-reference` base, tokenizer, published dataset, runner, pool and training-step budget. The local registration JSON has the exact launch IDs. Preview preflight, inspect encoded text/device/FP32 requirements, then launch with its fresh token and an idempotency key. The synthetic fixture budget permits three total committed steps; further runs need an explicitly configured budget and suitable published data. Setup checked preflight and polled an empty queue; it did not consume this project budget. GPU duration and monetary cost remain unknown.

## Memory and operation limits

This runtime uses one local GPU and one worker slot. The tested envelope is full SFT on the pinned 135M model, FP32 weights/AdamW, one sample per step, 2–128 encoded tokens, up to 1000 published rows and 1–1000 steps. The physical pilot checked three steps and 30 next-token pairs; it does not qualify the full workload range or other Apple generations.

MPS recommended memory is a shared working-set recommendation, not dedicated VRAM. The runtime sets a 90% per-process limit and requires 4 GiB headroom after accounting for driver/cache allocations. Training records this process allowance each step. Other applications can still consume unified memory; cross-pool device admission/reservations belong to TASK-42. Avoid independent pools running on this GPU concurrently.

PyTorch documents [recommended working-set memory](https://docs.pytorch.org/docs/2.9/generated/torch.mps.recommended_max_memory.html), [driver/cache allocation accounting](https://docs.pytorch.org/docs/2.9/generated/torch.mps.driver_allocated_memory.html) and the [per-process memory fraction](https://docs.pytorch.org/docs/2.9/generated/torch.mps.set_per_process_memory_fraction.html). `PYTORCH_ENABLE_MPS_FALLBACK=1` is rejected. Unsupported kernels fail instead of silently running on CPU.

| Operation | Current scope |
| --- | --- |
| Training | Pinned SmolLM2 FP32 full SFT; physical M5 Pro pilot passed |
| GPU inference | Independent offline consumer, explicit `mps:0`; weights and output residency checked |
| CPU portability | Same Safetensors candidate loads in a separate CPU consumer; fixture greedy tokens match |
| Server inference API | CPU runtime; no GPU-serving claim |
| Export | Verified Safetensors plus config/tokenizer files; candidate JSON contains artifact references |
| FP16/BF16, LoRA, QLoRA, quantized training | Unsupported; rejected before job/budget allocation |
| MLX, multi-GPU, remote workers, Vulkan/DirectML | Not implemented by this recipe |
| CUDA, ROCm, XPU | Explicit runtime/consumer paths and guards prepared; no hardware qualification on this Mac |

For independent MPS inference, materialize the candidate's five verified files in one directory, then run:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTORCH_ENABLE_MPS_FALLBACK=0 \
  .venv-gpu/bin/python scripts/hf_candidate_infer.py /path/to/candidate --device mps:0
```

The retained physical test candidate is at `runs/task40-mps-qualification/candidate`; omit `--device` to independently check CPU portability. See [qualification evidence](verification/task40-2026-10-11.md) before extending the scope. Production qualification flags remain false.
