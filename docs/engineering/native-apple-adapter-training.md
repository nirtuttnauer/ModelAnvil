# Native Apple GPU adapter training

`modelanvil.smollm2-mlx-qlora.v1` trains real rank-eight q/v adapters over a frozen four-bit affine base on `mlx:0`. The immutable SmolLM2-135M source and published protected text splits are shared with the existing transformer profiles. Linear layers use group size 32; token embeddings and tied output weights remain FP32. By default, adapter parameters, activations and Adam moments use FP32; the optimization profile below adds BF16 compute and other explicit options. This is native MLX quantization, not a bitsandbytes or NF4 implementation.

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

Measured telemetry includes gradient norm, active/peak MLX memory and prediction tokens per second including the post-update loss pass. Utilization and reserved-memory values remain unavailable. Comparative speed and memory statements are limited to the controlled comparison below.

## Optimization profile

Each run pins one explicit optimization profile, sent as `hyperparameters.optimization` at preview and launch. Omitted settings take the default, which is the original recipe. No other hyperparameter is accepted, and nothing is chosen automatically.

| Setting | Values (default first) | What it does |
|---|---|---|
| `compute_precision` | `fp32`, `bf16` | `bf16` runs the attention and MLP matmuls on BF16 inputs with BF16 quantization scales/biases. The residual stream, norms, embeddings and logits stay FP32, as do adapter weights, gradients and optimizer state. On the fixture, an all-BF16 residual stream moved the initial loss by 1.7% (gradient cosine 0.937 to FP32), while this mixed form moves it by 0.03% (cosine 0.980), so only the mixed form is offered. The stored base and exported files are identical to an FP32 run. |
| `gradient_checkpointing` | `false`, `true` | `mx.checkpoint` around each of the 30 transformer blocks; activations are recomputed in the backward pass. |
| `batch_samples` | `1`–`8` | Whole samples per optimizer step, in manifest order. Steps and budgets still count optimizer steps. One sample per step is the original cursor. |
| `sequence_layout` | `padded`, `packed` | `padded` right-pads to the longest sample in the step under the causal mask; padded targets carry zero loss weight. `packed` concatenates the step's samples into one row with a block-diagonal causal mask, so no token attends across a sample boundary, and the pair joining two samples is unsupervised. Loss is the mean over supervised next-token pairs in both layouts. |
| `attention_kernel` | `mlx_fast_sdpa`, `mlx_fast_sdpa_force_fused` | The pinned mlx-lm model already calls `mx.fast.scaled_dot_product_attention`. The second value passes `force_fused=True`, which makes MLX use its fused kernel where its own heuristics would not. There is no eager/FlashAttention backend switch in MLX. |
| `optimizer` | `adamw` | The pinned AdamW. Adafactor (factored second moment, no first moment, the same fixed learning rate) is implemented and measured but refused, because it failed the held-out tolerance. |

Preview checks the profile first, as the blocking `optimization-profile` check, before inputs resolve: an unsupported or incompatible profile never stages files or probes the device, and launch refuses it without a job or budget reservation. Refused: FP16 compute (no dynamic loss scaling is implemented), every FP8 variant (see below), packing with one sample per step, batch sizes above eight, Adafactor (failed its held-out gate), 8-bit or paged optimizers (CUDA bitsandbytes), non-MLX attention backends and unknown settings. The complete profile and its optimizer are part of the run's pins and every checkpoint, so recovery refuses a checkpoint written with a different profile, and optimizer-state restore refuses mismatched keys, shapes or precision.

Assistant-label masking does not apply here: this runtime accepts plain text only and refuses conversation rows. Packing and padding never truncate or split a sample.

### Telemetry

Each committed step records training loss, gradient norm, supervised tokens per engine wall second (still including the post-update loss pass), active and peak MLX bytes, optimizer-state bytes and the measurement time. Peak reserved bytes and GPU utilization are `null`, with `unavailable_metrics` naming the reason `not_exposed_by_mlx`: MLX 0.32.3 reports active, peak-active and current cache bytes, but no peak reserved-pool or utilization counter, and macOS GPU busy time is not sampled. The browser run view shows these values with their timestamps, prints “Not exposed by MLX” or “Not reported” for missing values with the reason below the table, and shows the pinned profile in plain language. No missing value is estimated.

### Precision and hardware support

| Hardware | Compute precision | Status |
|---|---|---|
| Apple M5 Pro (this Mac, applegpu_g17s, 48 GiB), macOS 27.2.1, MLX 0.32.3 on `mlx:0` | FP32 | Qualified baseline. |
| Same | BF16 matmuls, FP32 residual stream, logits, adapters and optimizer state | Qualified: held-out loss within 0.001% of FP32 in the controlled benchmark. |
| Same | FP16 | Refused at preflight: no dynamic loss scaling is implemented. |
| Same | Any FP8 variant | Refused at preflight: MLX 0.32.3 has FP8 storage conversion only, no FP8 matmul or training dtype on Apple GPUs. |
| Other Apple chips, other macOS or MLX versions | Any | Unqualified. The runtime pins exact MLX packages; other chips have not been measured. |
| NVIDIA, AMD, Intel or any other GPU | Any | Unqualified. This runtime is MLX on `mlx:0` only; no FP8 or other precision is measured elsewhere. |

On the same Mac, gradient checkpointing, packing and the forced fused attention kernel are qualified as exact reformulations: their training losses and learned updates match the baseline within the declared numerical tolerance. Adafactor is implemented but refused, because it failed the held-out tolerance (below).

### Controlled comparison

The [TASK-16 archive](verification/task16-mlx-2026-11-15/README.md) compares every option against the unoptimized FP32 profile at eight samples per step, using the same pinned model, seed, 96-sample corpus, sample order, 21,686 supervised tokens and measurement window, on this Mac, in fresh processes with three interleaved repeats. Peak allocated memory is MLX's peak active bytes including resident weights.

| Profile | Tokens/s vs baseline | Peak allocated vs baseline | Held-out loss vs baseline |
|---|---|---|---|
| BF16 compute | 1.26× | 0.72× | −0.0005%, pass |
| Gradient checkpointing | 0.81× | 0.59× | identical (bit-exact losses), pass |
| BF16 + checkpointing | 0.99× | 0.46× | −0.0005%, pass |
| BF16 + checkpointing + packing | 1.09× | 0.43× | +0.0008%, pass |
| Packing alone | 0.39× (0.53× in the first run) | 1.13× | +0.0001%, pass |
| Forced fused attention kernel | 1.02× | 0.94× | +0.0007%, pass |
| Adafactor | 0.91× | 1.00× (optimizer state 229 KiB vs 3,600 KiB) | +2.3%, **fail** |

The held-out tolerance is 1% relative to the baseline, which itself improved held-out loss by 2.5% over the untrained adapter, so the gate discriminates. Packing alone is slower and larger here because one packed row (median 611, at most 803 positions) computes attention over the whole row under a block-diagonal mask array, 2.6–5.0 times (median 3.6) the attention score positions of the eight padded rows; that costs more than the 35% padding it removes on this model and corpus. With BF16 and checkpointing it gives the smallest qualified peak measured, still faster than the baseline. These ratios hold for this Mac, model and corpus only. No comparison with Unsloth or any other product was made, and none is implied.

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
