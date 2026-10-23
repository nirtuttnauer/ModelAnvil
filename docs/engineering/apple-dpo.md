# Bounded Apple GPU DPO

The alignment workspace supports real DPO updates on the operator-registered plain SmolLM2-135M base. It trains rank-eight q/v LoRA adapters on Apple MPS using FP32, a frozen independent reference model and response-only sequence log probabilities. The earlier [CPU character alignment](cpu-character-alignment.md) remains a separate synchronous runtime. ORPO and KTO are unavailable.

The objective follows [DPO equation 7](https://arxiv.org/html/2305.18290v3): negative log-sigmoid of beta times the policy chosen/rejected log-ratio relative to the frozen reference. Response log probabilities are **sums**, including EOS, with the prompt excluded. The worker uses summed cross-entropy because PyTorch's MPS gather backward requires an unsupported nondeterministic scatter operation. Deterministic algorithms remain enabled; CPU fallback is refused.

## Operator setup and inputs

Apply migrations through `0020_gpu_alignment_job`. Reuse a base imported with `setup_gpu_training`: architecture `modelanvil.smollm2-gpu-sft.v1`, exact revision `93efa2f097d58c2a74874c7e644dbc9b0cee75a2` and the runtime's five pinned file hashes. Imported arbitrary models, instruction/chat templates, quantization and previously trained adapters are outside this DPO profile. Policy and reference must use the same tokenizer revision. The tokenizer registry vocabulary must match its pinned bytes.

Register a fresh trusted worker without launching training:

```sh
python manage.py setup_mps_dpo_worker --tenant-id TENANT_UUID --name apple-dpo
python manage.py run_worker --worker-id WORKER_ID --executor modelanvil.runners.alignment.mps_dpo.worker_executor --once
```

Keep the worker's environment and source checkout identical to the API. The contract pins PyTorch, Transformers, PEFT, Accelerate, tokenizer and Safetensors versions, host/device identity and implementation hashes. Source changes require restarting both processes. The profile requires at least 8 GiB host memory and 4 GiB observed MPS process headroom, a dedicated single worker slot and shared local filesystem artifacts. MPS recommended memory is not global free GPU memory; true peak/reserved allocation counters remain unavailable.

Use the existing formal blind-review export, or explicitly register owner-reviewed labels through `register-preferences` with `labels_reviewed: true`. An owner attestation and authenticated actor identity enter the immutable bytes; the runtime requires their matching registration audit. This attestation does not imply formal multi-reviewer agreement or model quality. Unreviewed legacy artifacts cannot enter this GPU path.

Pin three artifacts: training preferences, held-out preferences and separate regression pairs. Every row requires a source group; trimmed prompts and groups must be disjoint across all sets. Top-level and formal-export metadata group IDs normalize consistently; conflicting aliases are rejected. Each set has 1–32 unique prompts. Responses support 32 characters and prompt plus response 62 characters. Plain prompt tokenization must be an exact prefix of each completed sequence, with at least one response token. Tokenizer control tokens, truncation and sequences over 128 tokens including EOS are rejected.

## Queue, recovery and accounting

Create an alignment run with `algorithm: dpo`, policy/reference numeric record IDs, `worker_pool`, three artifact UUIDs (`train_dataset_artifact`, `held_out_dataset_artifact`, `regression_dataset_artifact`), `total_steps` and `hyperparameters`. Bounds are 1–20 updates, beta 0.001–1, learning rate 0.000001–0.0002 and maximum gradient norm 0.1–1. An explicit enabled `training_steps` budget policy is mandatory; monetary budgets are unsupported here.

`POST /api/v1/alignment-runs/{run_id}/execute/` queues a durable job and reserves its step budget. Queueing does not train or mark the candidate qualified. Queued plans and owning jobs are immutable. Generic job mutation/cancellation is refused; use the alignment API. The worker must claim its pinned host, physical device, worker identity and project, and the shared OS device lock. Apple MLX and MPS cooperate on the same physical device lock.

Every update checks claim, tenant/project access, code/input pins and current budget before publication. Checkpoints contain verified base/adapter references, actual measured losses/gradients, changed parameter counts and Safetensors Adam moments. Only 460,800 q/v adapter parameters may train; the reference remains frozen. A stale worker cannot publish a checkpoint, candidate or result.

Expired leases requeue the same reserved job and mark its alignment run interrupted. `resume/` revalidates pins and resumes the last committed adapter/Adam state through a fresh attempt; it never takes over a live claim. Cancellation stops future publication and settles only committed steps. Terminal settlement is idempotent. Pending cancellation settles zero. Unsupported or busy devices allocate no job or budget reservation.

## Independent gates and output

After the updates, a fixed offline child loads the exact base and candidate with a separate CPU consumer. It imports neither Django nor ModelAnvil. It independently computes response log probabilities using log-softmax/gather, scores disjoint held-out chosen/rejected preferences and separately measures chosen-response regression NLL per token. The manifest binds every model-file hash, both protected input hashes, beta and training groups. The child has a 120-second alarm; the parent kills it on cancellation, claim loss or deadline and inherits the CPU lock into the child.

All three checks must pass: preference accuracy cannot regress, reference-relative held-out DPO loss cannot exceed the unchanged policy's log(2), and separate regression loss cannot exceed baseline by more than 5%. Missing, invalid, timed-out or failed scoring blocks qualification. Training may still complete with draft loadable weights and an explicit failed/unavailable gate. Even a passing bounded fixture gate does not provide customer or production qualification; the release gate remains closed.

Completed candidates require their successful producing job, committed checkpoint and manifest for CPU/MPS inference. They do not become eligible as new SFT bases. `GET /api/v1/alignment-runs/{run_id}/download/` returns an adapter-only ZIP with the exact base revision, Apache license and evaluation provenance. Acquire the exact base separately; no optimizer state enters that archive.

Run `python scripts/qualify_mps_dpo.py --model-dir /absolute/pinned/base --output /absolute/new/qualification-directory` for the opt-in isolated physical-MPS proof. It uses authored correctness fixtures with test-owner attestation, verifies actual updates, independent scoring, adapter download, exact adapter/Adam recovery after lease expiry and one-update cancellation, then revokes fixture keys, disables workers and suspends fixture tenants. Run it serially with other numerical proofs. No existing database or customer data is used.
