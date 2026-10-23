# Native Apple GPU adapter training

`modelanvil.smollm2-mlx-qlora.v1` trains real rank-eight q/v adapters over a frozen four-bit affine base on `mlx:0`. The immutable SmolLM2-135M source and published protected text splits are shared with the existing transformer profiles. Linear layers use group size 32; token embeddings and tied output weights remain FP32. Adapter parameters, activations and Adam moments use FP32. This is native MLX quantization, not a bitsandbytes or NF4 implementation.

Install `requirements.inference.txt` in the trusted local API/worker environment on Apple Silicon. The profile checks exact MLX 0.32.3, mlx-metal 0.32.3, mlx-lm 0.29.1 and the existing transformer/tokenizer pins. Metal must be available and selected; CPU training fallback is refused. Host memory must be at least 8 GiB and observed recommended process headroom at least 4 GiB. MPS and MLX share the exclusive local device lease.

Register verified local inputs with:

```sh
python manage.py setup_gpu_training \
  --tenant-id TENANT_UUID --project-id PROJECT_UUID --name apple-adapter \
  --model-dir /path/to/smollm2-135m --samples /path/to/canonical-text.jsonl \
  --device mlx:0 --recipe qlora_adapter --steps 3
```

The command creates the native base profile, tokenizer, prepared dataset, exact runner, dedicated worker and step budget. It performs no model download or training. In the browser select **Apple GPU QLoRA**, the registered native base/runner/pool, then preview and launch. The worker consumes the same durable job protocol as the other local runtimes. Unchanged input, package, build, device and optimizer pins are checked at execution.

Each committed step saves actual adapter tensors and complete safe Adam state. The quantized frozen base is stored once and reused by reference. Expired attempts cannot publish checkpoints; recovery restores both moments and the cursor, cancellation settles committed steps, and corrupt bytes fail before publication. The downloadable ZIP contains `model.safetensors`, quantized `config.json`, the original tokenizer, `adapters.safetensors`, standard MLX `adapter_config.json` and ModelAnvil provenance. Optimizer state stays in internal checkpoints. Completed candidates appear in local chat and require `mlx:0`.

Measured telemetry includes gradient norm, active/peak MLX memory and prediction tokens per second including the post-update loss pass. Utilization and reserved-memory values remain unavailable. No comparative speedup claim is made.

## Mac evidence and quality limit

The [23 October current-stack qualification](verification/task77-gpu-recipes-2026-10-23/report.md) repeats actual native updates, exact recovery, independent CPU/GPU reload, current API inference and desktop/mobile encoded-sample previews. On its separate authored mechanics corpus, the candidate exceeds the unquantized base's loss by about 27% on validation and 18% on test. Both fail the five-percent quality tolerance. The operation mechanics pass; this does not qualify model quality. The older report below retains its own corpus, pins and different measurements.

The [Mac evidence](verification/modelanvil-native-adapter-mac-2026-10-12.json) records three actual updates, exact resumed adapter bytes, cancellation after one committed step, corruption without charging steps, verified ZIP contents, independent CPU/Metal reload and actual API candidate generation. The independent consumer imports neither Django nor ModelAnvil.

The corpus is the same deduplicated, pinned engineering-document corpus used for the FP32 profiles. Training loss must decrease against the identically quantized base, and protected validation/test loss may regress at most five percent. Those adapter checks pass. A separate comparison against the unquantized MLX FP32 base records the cost of quantization: validation loss exceeds the five-percent tolerance slightly, while test loss stays within it. **Overall model-quality acceptance fails for this three-step four-bit candidate.** The evidence retains this result; the runtime does not qualify a production release or bypass its quality gate.

Reproduce with a new output directory:

```sh
python scripts/qualify_hf_gpu.py --model-dir /path/to/smollm2-135m \
  --device mlx:0 --recipe qlora_adapter --samples /path/to/canonical-text.jsonl \
  --output /path/to/new-qualification-directory
python scripts/qualify_candidate_chat.py --qualification /path/to/new-qualification-directory
```

These checks qualify implementation behavior only within this local envelope. Larger models, other data formats, distributed jobs and NVIDIA/AMD/Intel GPU execution remain pending.
