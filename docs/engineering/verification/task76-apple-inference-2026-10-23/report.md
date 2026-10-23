# TASK-76: current Apple inference

Observed 23 October 2026 UTC on Apple M5 Pro, macOS 27.0.1, Python 3.12.15. This is bounded operation qualification on this Mac; it is not model quality or production approval. [Runtime contract and reproduction](../../apple-inference.md).

The [actual execution receipt](execution.json) pins the five public SmolLM2-135M files at revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2`, the converted F16 GGUF SHA-256, all runtime packages, OS/device and implementation hashes. Dependencies include Torch 2.13.0, Transformers 5.14.0, MLX 0.32.3, mlx-metal 0.32.3, mlx-lm 0.29.1 and xllamacpp 2026.10.11549. [Final source hashes](source-sha256.json) bind the implementation and qualification command.

| Actual format/device | Measured result |
| --- | --- |
| Safetensors / CPU | Four prompt tokens, eight computed output tokens, decoded output and completed runtime receipt |
| Safetensors / MPS | Same greedy output and usage as CPU; every parameter on `mps:0`; FP32 loader; no CPU fallback/offload |
| Dense MLX / Apple GPU | Same greedy output and usage; default GPU enforced; actual process allocation and reset peak recorded |
| F16 GGUF / CPU | Same greedy output and usage; GPU layers zero and both KV/operation offload disabled |

Prompt: `Once upon a time`. All four produced `, there was a little girl named Lily`. The observed stop reason was length. That small mechanical equality is not a language-quality result.

Each backend completed JSON and SSE execution, identical idempotent replay, early-close accounting, oversized-context rejection and cross-project model/artifact isolation. Closing a stream released device admission. Before execution, every catalog entry was unprobed. A CPU completion qualified only the CPU device, followed by a separate MPS proof. The trained [full-SFT and LoRA candidate receipt](trained-candidates.json) uses an isolated database backup of the actual completed PR58 three-step runs, reads their original immutable artifacts and verifies matching CPU/MPS greedy output, checkpoint/file identities and all parameter devices. No new training occurred for that check. The original export database and stored weights were not modified.

The MLX early-close check wraps the actual loaded model to count forwards: one forward call equalled one measured computed token. A separate controlled stop test marked the real first computed token as EOS and observed `stop` with one completion token. It does not claim that the base model naturally selected its default EOS. Actual MLX default-CPU selection was refused, and revoking the credential role during a loaded MLX stream withheld subsequent content and marked the request failed.

The MPS base request observed 538,060,544 current allocated bytes and 1,117,601,792 driver allocated bytes. True peak and reserved counters remain null. Dense MLX observed 270,013,064 active bytes and a 278,020,530-byte process peak for the recorded base request. After the model batch and direct close/stop checks, MPS model allocations returned to zero and MLX active allocations returned to the initialized eight-byte RNG baseline. Small MPS driver allocations remained. Process allowances are not global free memory; unrelated host workloads were present. No idle-host latency comparison is claimed.

The first actual run exposed a native cleanup-order bug: closing an unopened GGUF stream destroyed the runtime before reading its final computed count. That failed fixture is retained privately. Cleanup now accounts for native work before unloading, with an automated lifecycle regression and a passing real GGUF cancellation. A second qualification attempt correctly rejected an uninitialized zero-byte MLX baseline against its persistent eight-byte RNG state; the final command initializes that state before measuring. Neither failed run is counted as qualification.

Temporary credentials were revoked and fixture tenants suspended. No external model provider, private Hub upload, customer data or paid host was used. GGUF GPU/Vulkan, other GPU vendors, larger/other MLX profiles, native QLoRA candidate qualification, general memory telemetry and production/customer quality retain their separate gates.

Validation: 1,125 backend tests passed with 11 optional/environment skips using file-backed SQLite and one native CPU thread; 230 web tests and the production build passed. Django system checks, migration drift and whitespace checks passed. The unopened native-stream cleanup regression, device/project/runtime-bound load proof, exact adapter base/revision rejection and blind comparison consumers are covered in that backend run. Required exact-head backend/frontend/pgvector push and pull-request CI must pass before merge.
