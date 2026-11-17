# TASK-16: controlled MLX adapter-training memory and throughput

Observed 15 November 2026 on one Apple M5 Pro (MLX architecture `applegpu_g17s`, 48 GiB unified memory, MLX recommended working set 40,200,896,512 bytes), macOS 27.2.1 (26B131), Python 3.12.15, MLX 0.32.3, mlx-metal 0.32.3, mlx-lm 0.29.1 and tokenizers 0.22.2, on `mlx:0`. Every measurement ran on the Metal GPU; the scripts refuse CPU execution. Other Apple chips, macOS or MLX versions and every other GPU vendor are unmeasured and unqualified.

## Files

| File | Contents |
|---|---|
| [`benchmark/benchmark.json`](benchmark/benchmark.json) | Final run at `d058773` (clean `modelanvil/` and `scripts/`): environment, model and code hashes, corpus summary, design and tolerances, per-configuration summary, every measurement, and per-step losses, gradient norms, timings and peaks. Measured file SHA-256 `8d926d6c…af14`; archived after the digest reshaping below, `2ff6559d…49ce`. |
| [`benchmark/summary.md`](benchmark/summary.md), [`benchmark/corpus.json`](benchmark/corpus.json) | The printed table and the exact token IDs of all 96 training and 32 held-out samples, identical in both runs. Measured SHA-256 `72e92fb7…a4f2`, the value recorded in each `benchmark.json`; archived `005b2daf…67a2`. |
| [`run1-predeclared/`](run1-predeclared/) | First run at `c453574` with the nine configurations declared before any result was seen. |
| [`worker-qualification.json`](worker-qualification.json) | Real worker execution of an optimized profile through preflight, launch, recovery, cancellation and corruption, with its per-step telemetry validated against the published OpenAPI schema. |
| [`convert_digest_shape.py`](convert_digest_shape.py) | The deterministic digest reshaping applied after measurement, with `--check` to restore and verify the measured bytes. |

The commit IDs recorded in the archives (`c453574`, `d058773`, `0ae0bbe`) name the unpushed branch before it was rebased onto `origin/main` and its history rewritten; they no longer exist. The measured sources are pinned by content instead: each `benchmark.json` records the SHA-256 of `mlx_profile.py`, `mlx_candidate_infer.py` and the benchmark script. On the rebased branch, all three files match the first run's hashes at the commit “Show measured step telemetry and its missing-value reasons”, and the final run's hashes at the commit “Refuse Adafactor at preflight after it failed its held-out gate”. A later commit changes only the benchmark script's digest output shape (below).

### Digest shape

Stock gitleaks 8.28.0 reports a 64-hex digest on a line keyed by a name containing “token” (for example `"tokenizer.json": "<digest>"`) as a generic API key. After measurement, `convert_digest_shape.py` therefore reshaped exactly two fields in all four JSON files, keeping every value and all other bytes:

- `environment.model_file_sha256` `{file: digest}` became `environment.model_files` `[{"file": …, "sha256": …}]`.
- The corpus `tokenizer_sha256` became `tokenizer` `{"file": "tokenizer.json", "sha256": …}`.

`python convert_digest_shape.py --check` reverses this and reproduces each measured file's SHA-256. No measurement was re-run or changed. The benchmark script now writes the new shape directly.

## Controlled comparison

Every configuration trains the runtime's own four-bit affine group-32 SmolLM2-135M adapter recipe (revision `93efa2f`, all five file hashes matching the runtime pins) from seed 42, with the pinned AdamW at learning rate 2e-5, through `modelanvil/runners/training/mlx_profile.py`, the code the worker executes. The corpus is 96 training and 32 held-out prose windows (18–128 tokens, median 76) from `docs/engineering/*.md` at commit `0cbd830`; every fifth source file is held out and never trained on.

The baseline is the unoptimized profile at eight samples per step: FP32, right padding, no checkpointing, AdamW and the library attention kernel. Each configuration runs 40 steps and measures steps 6–40: the same 280 samples and 21,686 supervised next-token pairs, in the same order. The one-sample-per-step reference runs 320 steps over the same samples. Each of the three repeats starts a fresh process per configuration, in an order rotated by one per repeat.

- **Wall time** covers the whole window: batch construction, forward, backward, optimizer update and the synchronizing evaluation. **Tokens/s** is supervised pairs divided by that time; padding and packing-boundary positions do not count.
- **Peak allocated** is the largest `mx.get_peak_memory()` over window steps, reset before each step. It is the process's peak MLX active bytes, including the resident model. **Resident** is active bytes just before the window.
- **Peak reserved** and **GPU utilization** are `null` in every record, with the reason `not_exposed_by_mlx`. MLX 0.32.3 has no peak reserved-pool or utilization counter, and macOS GPU busy time was not sampled. Nothing is estimated.
- **Held-out loss** is the token-weighted mean next-token loss on the held-out samples. It is scored by a freshly loaded FP32 model through the mlx-lm forward pass, independent of the training code, with the trained adapters loaded.

Tolerances were fixed in the script before the first run. Held-out loss may differ from the baseline by at most 1% relative. The exact reformulations (checkpointing, packing, forced fused kernel) must also keep every step's training loss within 1e-3 relative of the baseline and their learned weight update `scale·A·B` at cosine ≥ 0.999 to the baseline's. The baseline lowered held-out loss by 2.55% from the untrained adapter (5.54223 → 5.40099), so the 1% gate discriminates. Held-out losses were identical across repeats for every configuration.

| Configuration | Wall s, median (range) | Supervised tokens/s (vs baseline) | Peak allocated MiB (vs baseline) | Resident MiB | Optimizer state KiB | Held-out loss | Δ vs baseline | Gate |
|---|---|---|---|---|---|---|---|---|
| `baseline`: FP32, padded, AdamW, 8 samples/step | 2.936 (2.904–3.064) | 7,385 (1.00×) | 2,563.7 (1.00×) | 196.3 | 3,600.0 | 5.40099 | 0% | pass |
| `gradient_checkpointing`: baseline + gradient checkpointing | 3.605 (3.569–3.718) | 6,015 (0.81×) | 1,506.2 (0.59×) | 196.3 | 3,600.0 | 5.40099 | 0% | pass; equivalence pass |
| `bf16_compute`: baseline + BF16 compute | 2.337 (2.300–2.347) | 9,278 (1.26×) | 1,836.4 (0.72×) | 187.6 | 3,600.0 | 5.40096 | −0.0005% | pass |
| `packed`: baseline + packing | 7.595 (7.037–13.576) | 2,855 (0.39×) | 2,904.0 (1.13×) | 196.6 | 3,600.0 | 5.40099 | +0.0001% | pass; equivalence pass |
| `force_fused_attention`: baseline + forced fused attention | 2.878 (2.876–3.256) | 7,536 (1.02×) | 2,405.2 (0.94×) | 196.3 | 3,600.0 | 5.40102 | +0.0007% | pass; equivalence pass |
| `adafactor`: baseline + Adafactor | 3.222 (3.110–3.490) | 6,730 (0.91×) | 2,557.8 (1.00×) | 190.5 | 228.8 | 5.52564 | +2.3080% | **fail** |
| `bf16_checkpointing`: BF16 + checkpointing | 2.969 (2.899–3.116) | 7,305 (0.99×) | 1,182.3 (0.46×) | 187.6 | 3,600.0 | 5.40096 | −0.0005% | pass |
| `bf16_checkpointing_packed`: BF16 + checkpointing + packing | 2.689 (2.645–2.874) | 8,064 (1.09×) | 1,091.5 (0.43×) | 188.0 | 3,600.0 | 5.40103 | +0.0008% | pass |
| `low_memory`: BF16 + checkpointing + Adafactor | 3.124 (3.119–3.229) | 6,941 (0.94×) | 1,176.8 (0.46×) | 182.0 | 228.8 | 5.52564 | +2.3079% | **fail** |
| `low_memory_packed`: BF16 + checkpointing + Adafactor + packing | 3.044 (2.889–3.274) | 7,123 (0.96×) | 1,088.1 (0.42×) | 182.0 | 228.8 | 5.52561 | +2.3075% | **fail** |
| `reference_one_sample_per_step`: production default, one sample per step (320 steps) | 6.960 (6.760–8.458) | 3,116 (0.42×) | 596.0 (0.23×) | 196.3 | 3,600.0 | 5.17009 | −4.2752% | not applicable: 8× the updates |

Equivalence detail (max per-step relative training-loss deviation; update cosine): checkpointing 0 and 1.0000000 (bit-identical), packing 6.3e-5 and 0.9999990, forced fused kernel 7.7e-5 and 0.9999988. BF16 is not an exact reformulation: 2.7e-3 and 0.9992. Adafactor: 2.9e-2 and 0.925.

## Findings

- **BF16 compute** is the only single option with a clear throughput gain: 1.26× tokens/s at 0.72× peak, with held-out loss unchanged to 0.0005%. It runs the block matmuls on BF16 inputs and keeps the residual stream, norms, embeddings and logits in FP32. An all-BF16 variant, measured on the unit-test fixture before the run and not shipped, moved the initial loss by 1.7% (gradient cosine 0.937 to FP32), against 0.03% (0.980) for the shipped form.
- **Gradient checkpointing** is bit-exact and cuts peak allocation to 0.59× for 0.81× throughput. With BF16 it reaches 0.46× peak at 0.99× throughput.
- **Packing** preserves boundaries and quality, but alone it is slower (0.39× here, 0.53× in the first run; its timing varies most) and larger (1.13×). One packed row (median 611, at most 803 positions) computes attention over the whole row under a block-diagonal mask array, 2.6–5.0 times (median 3.6) the attention score positions of the eight padded rows; that costs more than the 35% padding it removes on this model and corpus. Combined with BF16 and checkpointing it gives the smallest qualified peak measured, 0.43×, at 1.09× tokens/s.
- **The forced fused attention kernel** gives 0.94× peak at 1.02× throughput, within the equivalence tolerance. The pinned mlx-lm model already calls `mx.fast.scaled_dot_product_attention`; `force_fused=True` is the only real switch MLX offers.
- **Adafactor** shrinks optimizer state 16× (229 vs 3,600 KiB) but leaves peak allocation unchanged, because that state is under 0.2% of the peak. With the pinned learning rate it learned far less: held-out loss fell only 0.3% from the untrained adapter, 2.3% above the AdamW baseline. It fails the gate, and runs now refuse it at preflight. It was not retuned against this held-out set.
- **One sample per step** (the runtime default) has the lowest peak (0.23×) but 0.42× throughput for the same tokens. Its eight times as many updates give a lower held-out loss. That is a different training run, not an optimization, so no quality gate applies.

The first run reproduced every held-out loss to five decimals and every pass/fail result. Its baseline had one slow repeat (7.85 s; median 2.90 s), and its throughput ratios differ from the final run's by up to 0.14× (packing). The two BF16 + checkpointing combinations were added after the first run, because Adafactor failed and both pre-declared combinations included it.

These numbers describe this Mac, this 135M model and this corpus only. They establish no speedup or memory claim for any other hardware, model, sequence length or product. No comparison with Unsloth or any other tool was made.

## Real worker path

[`worker-qualification.json`](worker-qualification.json) records `scripts/qualify_hf_gpu.py --device mlx:0 --recipe qlora_adapter` with the BF16 + checkpointing + four-sample packed profile, in an isolated database at `0ae0bbe`:

- Busy-device and unsupported top-level precision/adapter/quantization requests were refused without jobs or budget.
- Profiles with FP8, FP16, packing one sample per step, `adamw_8bit` and Adafactor blocked the `optimization-profile` preview check before inputs resolved (no pins, no input check), and their launches were refused, also without jobs or budget.
- The approved launch ran three real updates with the profile pinned. Independent CPU and Metal consumers reloaded the exported adapter with identical greedy output.
- A genuinely expired lease stopped at committed step 1, and the next attempt reproduced the uninterrupted step-3 adapter bytes exactly. Cancellation settled one step; corrupt input settled none.
- The three real step records, including their `null` peak reserved and utilization values and `not_exposed_by_mlx` reasons, validate against the OpenAPI `TrainingStepMetric` schema with no errors.

That corpus is ten synthetic sentences. The run checks mechanics and recovery only, not quality, and the throughput of its tiny steps is not a benchmark.

## Tests

Focused unit and fixture tests in `modelanvil/runners/training/test_mlx_runtime.py` cover the following:

- Profile validation and every refusal, including that refusals happen before inputs resolve. Preflight blocking, registry forwarding, checkpoint refusal of a changed profile or optimizer, and agreement with the published contract.
- With the real model: the shared forward pass equals the library's bit-for-bit, and padded and packed batches match unbatched losses within the measured FP32 batch-shape noise. Padding tokens and other packed samples change no supervised prediction (exactly zero difference), and boundary pairs carry zero loss.
- Checkpointing is exact, and the forced fused kernel stays within tolerance. BF16 keeps FP32 adapters and gradients. Adafactor's factored state restores exactly, and AdamW state is refused for it.

## Reproduce

Behind the host compute lock, into new directories:

```sh
python scripts/benchmark_mlx_training.py --model-dir /verified/smollm2-135m --output NEW_DIR
python scripts/qualify_hf_gpu.py --model-dir /verified/smollm2-135m --device mlx:0 --recipe qlora_adapter \
  --optimization '{"compute_precision":"bf16","gradient_checkpointing":true,"batch_samples":4,"sequence_layout":"packed"}' \
  --output NEW_PRIVATE_DIR
MODELANVIL_MLX_TEST_MODEL_DIR=/verified/smollm2-135m python manage.py test \
  modelanvil.runners.training.test_mlx_runtime --tag=pg
```

Expect timing to vary by a few percent between runs. Held-out losses and gates should reproduce exactly on the same hardware and packages.
