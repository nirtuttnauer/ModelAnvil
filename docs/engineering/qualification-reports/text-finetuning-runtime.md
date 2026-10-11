# CPU character fine-tuning reference evidence

TASK-4 · 11 October 2026 · Implementation ready for developer review

The earlier H100/CUDA, PostgreSQL, provider-storage and production claims remain withdrawn. This report covers one explicitly bounded CPU recipe. It does not imply task acceptance or production release qualification.

## Runtime and support envelope

`modelanvil.cpu-character-sft.v1` implements `full_sft` over a small character model whose prediction depends on the previous token. It loads committed base weights, embeds the input token, applies a residual low-rank transform and projects to vocabulary logits. Online SGD updates the embedding, both residual matrices and output head; finite differences verify the pre-update gradients. The learning rate is fixed at 0.05. One `training_steps` unit is one sample pass, containing one SGD update per next-token pair. SGD has no momentum buffers; its full recovery state consists of algorithm/rate, update cursor, pinned samples and checkpointed tensors. Arithmetic uses Python float64 and checkpoints round to float32 at every committed step.

The implemented limits are vocabulary 10–256, embedding width 1–16, residual rank 1–4, 1–1000 published rows, at most 64 tokens per training sample including BOS/EOS, 1–1000 sample passes, and local input artifacts at most 1 MiB each. Plain text blocks without chat roles are supported. Every character must be covered by the tokenizer. Base architecture/tokenizer, manifest contents/digest, pool status, declared worker contract/available slot and ≥256 MiB declared worker memory are checked before dispatch. Limits bound execution; the reference measurements below cover the named small workloads, rather than a maximum-size endurance benchmark.

This is a trusted local Python executor on one host with shared database/filesystem storage. Runner manifest `image` identifies the local contract; it is not a published container. Scratch pretraining, other recipes, pretrained transformer imports, attention/context windows, AdamW, chat templates, GPU/distributed training, remote-worker tensor transport, PostgreSQL concurrency qualification and production serving are outside this support envelope. Host free-storage admission and user-facing capacity/cost preflight are TASK-5 scope. Capacity declarations are admission checks, not an OS memory quota.

## Environment and measurements

Reference host: Apple M5 Pro, macOS 27.0.1 arm64, 18 physical cores, 51,539,607,552 bytes installed RAM. Runtime: CPython 3.12.15, Django 5.2.18, SQLite, local filesystem artifacts. The numerical loop is single-threaded. No GPU, external provider, broker delivery benchmark or paid resource was used.

| Evidence | Shape and workload | Measured committed engine usage | Result |
| --- | --- | --- | --- |
| [Automated pilot](cpu-character-pilot.json) | Vocab 12, width 4, rank 2; two published text samples; 4 sample passes | 36 next-token pairs; 0.000976 process CPU seconds | Independent process and server produced identical token IDs and weight hash |
| [Browser run](task4-browser-run.json) | Vocab 33, width 8, rank 2; two published text samples; 20 sample passes | 470 next-token pairs; 0.025793 process CPU seconds | Completed, 20 checkpoints, reserved/settled 20 training steps, candidate downloaded |

`cpu_seconds` uses `time.process_time()` around the numerical update, float32 serialization/restore and post-update loss. `engine_wall_seconds` uses `time.perf_counter()`. Both exclude database/queue/storage publication overhead and uncommitted work discarded after interruption. These small single-run measurements are not elapsed-job forecasts or provider billing. Monetary cost, currency, rate and uncertainty interval are unknown; the reservation is an exact step ceiling, not invented dollars.

The [browser candidate](task4-browser-candidate.json) has weight SHA-256 `714a556a223140f2f9822992d5b487d93332c735c1700e0e4d3e22f78e9e2e99`. For prompt `a small`, both server and independent consumer produce IDs `[8, 31, 2]` and decoded completion `e.`. This demonstrates loadability and learned next-character execution, not useful language-model quality. The browser's runtime smoke check remains labelled local and independently unverified; independent verification is a separate archived command/result.

The [browser screenshot](task4-browser.jpg) shows completion, checkpoints and inference. The cancelled browser run `557c7352-22e8-4d13-b30a-cbc2ec55bf5d` had no committed steps and settled zero. The JSON report includes the complete final checkpoint state, optimizer cursor, source pins, fence provenance and checksum. The test database is disposable; these exported artifacts preserve its evidence.

## Dispatch, accounting and recovery

Launch requires an idempotency key, compatible immutable prepared dataset, verified base artifact, tokenizer, exact enabled CPU runner manifest, available worker pool, and an enabled `training_steps` policy without currency. Run, job, outbox event and exact step reservation commit together or roll back together. `Job.save()` already provided a transactional outbox before this task; earlier finding language suggesting no outbox was incorrect. The local worker consumes durable jobs by polling. Repeated identical launch reuses the same job/reservation; changed payload with the same key is rejected.

Before execution and retry, the worker re-resolves input hashes, tokenizer, recipe/config, runner and installed runtime build. Each numerical step commits only after locking the current attempt/job/run and rechecking live fence, lease, cancellation and cursor. Candidate publication and usage settlement occur inside the final durable result transaction. Configuration and protected jobs cannot be edited/deleted through the API. Exports reuse the committed candidate; they do not train or create new versions.

The CPU test suite injects lease expiry during step 3: only steps 1–2 survive, the expired worker cannot publish, and a replacement resumes step 3. Final float32 weights exactly match uninterrupted execution. The same run retains one reservation and one usage event across attempts. Cancellation during an update refuses that update, acknowledges the job fence and settles only earlier committed steps. Queued cancellation and exhausted retries settle zero. Altered tokenizer/pinned inputs and corrupted checkpoint state fail. State digests cover weights, optimizer cursor, pins, metrics and attempt provenance.

Independent consumer command (no Django/ModelAnvil imports):

```sh
.venv/bin/python -I scripts/cpu_character_infer.py \
  docs/engineering/qualification-reports/task4-browser-candidate.json --prompt 'a small'
```

## Operator setup and browser journey

Use an existing tenant/project in a local development environment. The setup command creates explicitly named reference resources and prints their identifiers; it starts no training. Its random numerical base is labelled as such and is not a pretrained language model.

```sh
.venv/bin/python manage.py setup_cpu_training_reference \
  --tenant-id TENANT_UUID --project-id PROJECT_UUID --name cpu-reference
```

Connect an authorized engineer/owner key, select the project, open Training → New training run → CPU text fine-tuning, and select the named tokenizer, base, published dataset, runner, pool and step budget. Choose steps and launch. Run the printed worker ID with the installed executor:

```sh
.venv/bin/python manage.py run_worker --worker-id WORKER_ID \
  --executor modelanvil.runners.training.executor.training_worker_executor
```

Monitor committed progress, cancel queued/running work, download the completed candidate and run the independent consumer. Browser retries preserve the same idempotency key while the payload is unchanged. Inference output clears when changing the selected run.

## Verification

Full backend: 476 tests passed, 3 existing skips. Final runtime/evidence subset after the historical-contract label change: 20 passed. Web: 91 passed; TypeScript/Vite build passed. Django check and migration drift check clean. Actual browser verification exercised launch, completion, checkpoint display, decoded inference, download and queued cancellation in an isolated database. See the [review package](../verification/task4-2026-10-11.md) for saved logs and changed files.
