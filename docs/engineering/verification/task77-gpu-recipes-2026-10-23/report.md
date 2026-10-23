# TASK-77: bounded Apple GPU recipes

Observed 23 October 2026 UTC on Apple M5 Pro, 48 GiB unified memory, macOS 27.0.1 and Python 3.12.15. The [actual receipt](actual-report.json) binds the exact source build, model/config/tokenizer hashes, dataset groups, packages, candidate/checkpoint identities, independent consumers, API results, accounting and cleanup. [Final source hashes](source-sha256.json) identify the delivered implementation.

| Recipe / device | Intended trainable parameters | Actual baseline updates | Protected validation loss, base → candidate | Protected test loss, base → candidate |
| --- | ---: | ---: | --- | --- |
| Full FP32 SFT / MPS | 134,515,008 | 3 | 3.76370 → 3.66857 | 4.15569 → 4.05333 |
| FP32 rank-8 q/v LoRA / MPS | 460,800 | 3 | 3.76370 → 3.76248 | 4.15569 → 4.15495 |
| Four-bit affine group-32 base, FP32 rank-8 q/v adapters / MLX GPU | 460,800 | 3 | 4.78203 → 4.77319 | 4.89070 → 4.88749 |

The QLoRA row compares against the identically quantized base. **Its overall quality gate fails against the unquantized MLX FP32 base:** validation loss is 4.77319 versus 3.76334 (about 27% worse), and test loss is 4.88749 versus 4.15503 (about 18% worse). Both exceed the five-percent tolerance. Execution, recovery and a small decrease from the quantized baseline do not resolve that failure. This profile is an execution experiment, with no model-quality or production approval.

All recipes use the exact public Apache-2.0 SmolLM2-135M revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`. Torch 2.13.0, Transformers 5.14.0, Safetensors 0.8.0, Tokenizers 0.22.2, PEFT 0.21.2, MLX 0.32.3, mlx-metal 0.32.3 and mlx-lm 0.29.1 are pinned where applicable. Plain text is encoded by the actual model tokenizer; no instruction template, hidden truncation, remote code or CPU training fallback is used. The [authored mechanics corpus](authored-mechanics-corpus.jsonl) has 20 distinct source groups: 13 train, three validation and four test groups. Only three training examples are consumed. The held-out text was excluded from training. These few authored facts test mechanics; source-model pretraining contamination is unknown, and these losses do not establish customer or domain quality.

Full-SFT and QLoRA numerical runs began on main `ecc9bd103902e7e4814b7da0250981c87d96431c`; LoRA ran after PR59 on `b0dedf1933e51be8c705812c6d9fe53d486351bf`. Each receipt's build digest is independently recomputed from its exact Git source. PR59 changed the PEFT adapter staging/revision guard; the full-SFT update and native MLX numerical code did not change. Final candidate API checks and browser previews use the delivered snapshot-recognition fix on top of PR59. Existing run pins were not relabelled or migrated.

For each recipe, separate independent CPU and GPU processes import neither Django nor ModelAnvil, verify candidate/file identities and produce identical eight-token greedy IDs. The current application API loads that exact completed candidate on its named GPU and matches the independent decoded output. Independent scoring compares consumed training and protected validation/test groups. A separate actual native MLX model test verifies the frozen quantized base remains unchanged, the intended 460,800 adapter parameters train, and restored optimizer state reproduces the next update exactly.

Each worker qualification also verifies:

- A busy device or unsupported precision/adapter/quantization creates no job or reservation.
- A genuinely expired lease stops publication at committed step one. A fresh attempt restores optimizer/cursor/checkpoint state and produces exactly the uninterrupted step-three weight bytes. The old attempt cannot publish afterward, and settlement occurs once.
- Cancellation during an optimizer update retains one committed step, settles one unit and publishes no candidate. Corrupt input commits and settles zero work.
- Native ZIP contents include the actual tensor/tokenizer files, provenance and exact Apache license bytes. Optimizer state remains in internal checkpoints.

The first QLoRA attempt completed three real updates but failed an outdated qualification assertion which omitted `LICENSE.txt` from the expected ZIP entries. That failed fixture is retained privately and is not counted as passing qualification. The harness now verifies the license as well as every original tensor hash. Independent consumers also hold the shared device lease, and PEFT staging is explicitly CPU before placement/scoring.

The browser checks use actual HTTP APIs at 1,440 and 390 pixels: select full SFT, LoRA or native QLoRA, choose the exact base/tokenizer/dataset/runner/pool, and preview an approved three-step plan with actual text, token IDs and protected split counts. [Desktop full-SFT preview](full_sft-desktop-encoded.png) and [mobile QLoRA preview](qlora_adapter-mobile-encoded.png) were visually inspected. All three had no page errors or root horizontal overflow. Previewing did not launch additional training or settle budget.

That browser exercise exposed an implementation gap: operator-created GPU bases used a pinned `{source, files}` manifest that the capability check rejected without a guided managed marker. Exact operator HF/MLX base profiles are now recognized, retaining source/file-hash checks and the separate managed-instruction gate. The picker and local chat catalog can expose eligible bases; device-specific completed load receipts still require real execution.

MPS allocation samples are not true peak/reserved measurements. MLX records actual reset process peaks, with reserved/utilization unavailable. Process headroom is not globally free unified memory. Other host workloads were present; no controlled throughput or memory-saving comparison is claimed. One local GPU, FP32 adapters, 2–128 encoded tokens/example and the exact model/profile are the tested envelope. Broader workload sizes, other Apple generations, vendor GPUs, mixed precision, distributed operation, customer outcomes and production gates remain separate.

All fixture credentials were revoked, workers taken offline, tenants suspended and owned API/Vite services stopped. Each final recipe receipt reports zero active keys, available worker slots and active tenants. The original installation was not modified.

Validation: 1,126 backend tests passed with 11 optional/environment skips using file-backed SQLite and one native CPU thread; 230 web tests and the production build passed. The separate native MLX model test passed. Django system/migration and whitespace checks passed. Required exact-head backend/frontend/pgvector push and PR CI must pass before merge.

Reproduce sequentially using the pinned environment and local five-file snapshot, with a new output directory for each recipe:

```sh
python scripts/qualify_hf_gpu.py --model-dir /absolute/path/SmolLM2-135M \
  --device mps:0 --recipe full_sft --samples docs/engineering/verification/task77-gpu-recipes-2026-10-23/authored-mechanics-corpus.jsonl \
  --output /absolute/path/new-full-sft-qualification
```

Repeat with `--recipe lora_adapter`; use `--device mlx:0 --recipe qlora_adapter` for the native profile. Inspect `overall_quality_passed` and its unquantized comparison separately from execution checks. The isolated directories retain weights, reports and databases; no external provider or upload is used. The recorded run additionally revoked its temporary fixtures after inspection.
