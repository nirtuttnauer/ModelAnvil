# Bounded Apple inference

TASK-76 qualifies local inference on the Apple M5 Pro under the current pinned optional inference dependencies. It does not qualify training, other GPU vendors, every architecture, domain quality or production deployment. [Recorded execution and limits](verification/task76-apple-inference-2026-10-23/report.md).

| Input | Attemptable device | Qualified reference operation |
| --- | --- | --- |
| Safetensors | CPU; available PyTorch MPS | Pinned SmolLM2-135M base and completed full-SFT/LoRA candidates, FP32 on CPU and MPS |
| Dense MLX Safetensors | Explicit available Apple MLX GPU | Pinned SmolLM2-135M dimensions, at most 1 GiB of weights; no imported quantized model |
| Native MLX adapter checkpoint | Explicit Apple MLX GPU | Requires verified completed native QLoRA lineage and its exact quantization/adapter configuration; training and candidate qualification remain separate in TASK-77 |
| GGUF | CPU | Pinned converted SmolLM2 F16 reference; GPU layers, KV offload and operation offload disabled |

The general Safetensors bounds remain 300 million parameters and 1 GiB of stored weights. The existing guided large profile has separate bounds and earlier evidence. Eligibility permits an actual load attempt; it does not establish successful loading or broad model support. GGUF GPU/Vulkan, CUDA, ROCm and XPU inference are outside this qualification.

`GET /api/v1/inference/models/` reports `load_tested_devices`. A device enters that list only after a real completed inference request in the same project, with matching model/tokenizer field identity, implementation hashes, dependency versions, host and device. `load_tested` is true if that list is nonempty. An imported snapshot, legacy completed row, CPU completion, cancelled request or failed load does not establish another device's proof. A changed runtime or input identity requires fresh execution. Restart API processes after a runtime deployment. Production qualification remains false.

The first explicit completion request performs the load/probe. Completed JSON responses and final SSE frames contain server-owned runtime provenance, actual tensor placement and available memory observations. The stored inference request retains the same receipt. Device, streaming controls and server observations do not change the generation settings used to match blind comparison pairs.

Loading holds the shared host/device lease until native generation stops and resources unload. MPS and MLX share the Apple device lease. MPS CPU fallback and MLX default-CPU execution are refused. LoRA loading checks its exact base repository/revision, stages the adapter on CPU and then places all parameters on the explicitly selected device. MLX executes synchronous sampled steps so closing a stream cannot hide a prefetched computed token. Closing an unopened GGUF stream accounts for native work before destroying its HTTP/runtime resources.

The current envelope is 1–256 output tokens and at most 2,048 total prompt/output tokens, subject to the smaller model context. Plain text, the actual imported template and explicit ChatML are distinct choices; a base without a template rejects multi-message model formatting. Live authority and input checks continue during streams and cached replay. Project isolation applies to models, tokenizers and every committed artifact.

MPS reports current parameter allocations and driver allocation/process allowance; true peak/reserved counters remain unavailable. MLX records active and reset process-peak allocation, with reserved memory unavailable. Neither framework's recommended process allowance is global free memory. Small framework/driver allocations can remain after model unload; the verification distinguishes those from model tensors. These observations do not resolve TASK-16's broader telemetry gates.

Reproduce offline with the exact five-file public snapshot and the pinned operator-converted F16 GGUF:

```sh
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv/bin/python scripts/qualify_apple_inference.py \
  --snapshot /absolute/path/SmolLM2-135M \
  --gguf /absolute/path/smollm2-base-f16.gguf \
  --output /absolute/path/new-private-qualification-directory
```

The command creates a fresh isolated database/artifact directory, verifies all input hashes, executes the real backends sequentially, checks streaming/replay/cancel/EOS/context/isolation and live MLX access revocation, then revokes its temporary credentials and suspends its fixture tenant. Its controlled EOS test temporarily selects a real computed token as the stop token; it is explicitly separate from the model's default EOS behavior. No external model service or upload is used.
