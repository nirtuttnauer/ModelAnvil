# TASK-15 — bounded pretrained CPU training

23 October 2026. The human authorized CPU-first software delivery with separate hardware qualification gates. TASK-15 now covers real pretrained CPU full SFT and LoRA; the original GPU/QLoRA acceptance criteria remain preserved in TASK-77. This profile does not complete TASK-77.

## Implemented envelope

`modelanvil.smollm2-cpu-sft.v1` trains the exact Apache-2.0 SmolLM2-135M base revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. It uses the existing verified artifact, tokenizer, dataset, optimizer/checkpoint, fencing, budget and independent export paths. One dedicated CPU worker runs one Torch thread, FP32 full SFT or rank-8 q/v LoRA, 1–20 updates, up to 1,000 examples and 128 tokens per example. It requires 16 GiB observed physical host memory. That conservative physical-memory gate and bounded tensors are not a free-memory reservation or protection from unrelated processes consuming RAM.

The setup command accepts `--device cpu`; it imports only exact already-local model files and never launches or downloads implicitly. The browser selects the registered pretrained base, matching tokenizer, recipe, published dataset, runner, worker pool and training-step quota. Preflight previews actual encoded examples and revalidates immutable inputs, runtime build, single-slot capacity, device lease, storage and budget before launch. Unsupported precision, quantization, QLoRA, continued pretraining, large/instruction sources and mismatched worker profiles are refused. A worker setup profile also exposes the observed CPU executor.

To bootstrap inputs using an existing tenant/project and authored canonical samples:

```sh
python manage.py setup_gpu_training --tenant-id TENANT_UUID --project-id PROJECT_UUID \
  --name cpu-pretrained --model-dir /absolute/verified/SmolLM2-135M \
  --samples /absolute/samples.jsonl --device cpu --recipe full_sft --steps 3
```

The command retains its existing name for compatibility. Its output identifies the dedicated worker and browser launch resources. Run that worker with the existing local training executor. GPU and CPU profiles have different runtime IDs, manifests and contract digests; the CPU manifest requests zero GPUs. The existing placement/metrics JSON fields retain their historical `gpu_` names with explicit `cpu` backend/device. Missing GPU memory/utilization metrics remain null; CPU execution does not fabricate them.

## Actual bounded execution

The [structured receipt](actual-report.json) records actual three-update full SFT and LoRA on this Mac (M5 Pro, 48 GiB, macOS 27.0.1), Python 3.12, Torch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, Tokenizers 0.22.2 and PEFT 0.21.2. Both runs share the exact frozen runtime contract/build, verified base and authored ten-text corpus. Full SFT updated 134,515,008 trainable parameters; LoRA updated 460,800 while the frozen base received no gradients.

Each actual worker produced three committed Safetensors/Adam checkpoints and a completed candidate. Exported ZIP files matched every recorded artifact checksum. A standalone consumer that imported neither ModelAnvil nor Django loaded the candidate bytes and decoded text on CPU. Repeated independent CPU inference agreed exactly.

Protected validation and test groups were excluded from training. The independent scorer measured token-weighted baseline/candidate loss on three consumed train texts, three validation texts and three test texts. Both candidates reduced consumed training loss and remained within the explicit five-percent held-out regression checks. These tiny authored three-step checks establish execution and integrity, not useful task quality, customer outcomes or broader generalization.

A controlled lease-expiry injection stopped each real training run at the first committed checkpoint; the second attempt restored Adam state and sampler cursor and reproduced the uninterrupted final weight hash exactly. A stale attempt could not publish again. Cancellation after one committed step produced no candidate and settled one step. Corrupt tokenizer metadata produced no updates, candidate or charge. Busy-device and unsupported-option checks refused allocation before creating a job or reserving budget.

Full SFT weights: `0ea2dec34fec4638f5f53ad97f541735f04bccfe5c95876aa69791b4d169cb9e`.
LoRA adapter weights: `c5ef786f2010aeab1b8c1b0a04174a4be336c4e3c609f71eddc5f600416d41c2`.

The shared qualification script retains historical `gpu` filenames and console labels; the archived data explicitly records CPU placement at every step. Raw scripts, logs and receipts are preserved in private project evidence under `takeover-2026-10-23/cpu-pretrained`; models, optimizer tensors, API credentials and disposable databases remain outside Git.

## Software and browser checks

Six new admission/export guards and the existing relevant suites passed (39 tests total). The frontend passed 226 tests and its production build. An actual Chromium browser selected full-SFT and LoRA, previewed exact encoded samples with zero GPUs, and launched a durable full-SFT job through the real HTTP API at desktop and narrow viewports. The [separate worker receipt](browser.json) records execution and settlement for that browser-launched job; no request was mocked.
