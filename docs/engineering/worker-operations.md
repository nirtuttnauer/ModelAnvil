# Worker and artifact operations

These are the current executor, credential and transfer contracts. For local setup and project scope, start with the [project README](../../README.md). Run worker code only in an environment you control.

## Controlled local executor

The optional [accelerator inventory and diagnostic tool](accelerators.md)
checks CUDA, ROCm, Intel XPU and Apple MPS on the worker host with
`python -m modelanvil.accelerators`. Successful detection does not register training capacity.
The optional [local GPU training setup](smollm2-gpu-training.md)
registers one dedicated worker for the pinned SmolLM2 recipe. Shared-device admission,
remote GPU workers and additional vendor qualification remain separate work.

`manage.py run_worker --worker-id ID --executor package.module.callable --once` claims one compatible job from PostgreSQL and executes it with an operator-installed Python callable. Omit `--once` to poll continuously. The callable receives the claim descriptor and an execution context; it must call `context.heartbeat()` regularly and stop when that returns false. Job payloads are data and are never executed as shell commands. This path polls the database; use the RabbitMQ consumer below when consuming broker dispatches. Only load trusted executor code.

For RabbitMQ dispatch, run `manage.py consume_worker --worker-id ID --executor package.module.callable` with `RABBITMQ_URL` set. It consumes the worker's tenant/pool topic, makes a durable database claim before acknowledging a dispatch, and uses delayed retry and quarantine queues. The executor remains operator-installed trusted code. This local consumer is not the outbound hybrid-worker gateway and has not been production-qualified.

## Worker credentials

An administrator registering a worker receives a one-time `worker_token` in the registration response. It is tenant- and worker-bound, stored only as a hash, and expires after 30 days by default (`MODELANVIL_WORKER_CREDENTIAL_SECONDS` configures the lifetime). The token can call only the worker claim, heartbeat, result, attempt-scoped input-grant discovery, and explicitly granted input-artifact download endpoints; it cannot access the tenant artifact registry or uploads. Use `POST /api/v1/workers/{worker_id}/credential/revoke/` with an administrator API key to revoke it. Do not log or persist the registration response as ordinary application output.

## Outbound HTTP worker

`python -m modelanvil.worker_agent` is a standalone polling worker, separate from the DB-dependent Django commands. It imports no Django, connects to no database or broker, and uses the scoped worker API for claims, automatic/manual heartbeats, cancellation and fenced results. Supply the credential through a securely provisioned `MODELANVIL_WORKER_TOKEN` environment variable, not a command-line argument. Start it with:

```sh
.venv/bin/python -m modelanvil.worker_agent \
  --endpoint https://control.example/api/v1/workers/ \
  --worker-id 1 --pool cpu --executor trusted_package.remote:execute
```

The executor is trusted, operator-installed Python code selected at startup; the agent never imports modules, interprets shell commands, or redirects its API requests based on job payloads. Executor code remains responsible for its own network and data access. Its signature is `(descriptor, context)` and it returns a canonical EnvelopeSample or `None`. `context.heartbeat(progress)` returns false on cancellation or uncertain/lost lease ownership; the callable must cooperate by stopping its backend. Background heartbeats do not force-kill Python code or prove that an external provider stopped. Expired claims do not execute, and loss of ownership prevents result publication.

HTTPS uses certificate verification. Redirects and ambient proxy settings are disabled; credentials stay on the configured endpoint. Plain HTTP requires `--allow-loopback-http` and a numeric loopback address (local development only). JSON control requests/responses are limited to one MiB; verified binary inputs use the separate byte cap below. Executor exceptions and transport failures are reported without their original bodies/messages. `--once` handles one claim and exits. A lost result acknowledgement is reported as `commit_unconfirmed`; the CLI exits nonzero without rerunning or blindly retrying the work. Reconcile server state before restarting after an uncertain commit or lost lease.

### Result-egress boundary

A tenant administrator can set a pool's result policy with `POST /api/v1/workers/pools/{pool_id}/egress/` and JSON `{"result_egress":"metadata_only"}`. The other supported value is `envelope`; it remains the compatibility default, **not** a private-workload safety default. Changes are tenant-scoped and audited. Registration, claim and heartbeat responses disclose the current policy.

For private workers, also pin `--result-egress metadata_only` locally before starting. Either local or pool restriction wins; job payloads cannot relax it, and an attempt remains restricted after observing a stricter heartbeat even if the pool is subsequently relaxed. In this mode the agent sends only attempt identity, fence and terminal status: returned envelopes are withheld before HTTP and reported as failed; executor exceptions send no free-form error. Return `None` to report successful status without a sample. The API rejects supplied envelopes (including empty objects), nonempty errors and artifact descriptors under a metadata-only policy. The shared transactional result-commit service rechecks the policy before persistence.

Pool policy changes cannot recall bytes already sent by an old or noncompliant client. Local pinning is the agent's pre-transmission boundary, not a sandbox for trusted executor code, a content/privacy classifier, or protection against covert channels in permitted metadata. The control-to-worker job payload is not minimized by this result-only policy.

This implements the outbound execution protocol, a bounded result-egress mode, and the input-download hook below, **not** a completed private-data gateway: artifact residency/egress rules, output-artifact transfer, credential rotation/provisioning, and disconnected/reconnected private-worker qualification remain outstanding. Do not treat it as qualified for workloads requiring those unimplemented boundaries. See `--help` for polling/heartbeat/timeout controls.

### Attempt-scoped input artifact downloads

A tenant administrator can issue a download grant with `POST /api/v1/workers/artifact-grants/` and JSON fields `worker_id`, `attempt_id`, `artifact_id`, and optional `ttl_seconds` (default 60, range 1–300). It binds one committed artifact to the current worker execution and expires no later than its issued lease. The response contains a `download_path`; GET it using that worker's scoped credential. The grant ID alone does not authorize access. Revoke it with administrator-only `POST /api/v1/workers/artifact-grants/{grant_id}/revoke/`.

This slice accepts only unversioned `local` artifacts on the configured filesystem backend. Other storage locations, S3 and versioned objects fail closed. Scope, fencing, leases, cancellation, grant/credential expiry and revocation, tenant suspension, artifact state and pinned metadata/backend are checked before each bounded file read. Revocation stops future reads; already-read or buffered bytes cannot be recalled. Consumers must reject incomplete transfers and verify the declared byte size and SHA-256 before using an input.

Grants are manually issued by an administrator; they are not inferred from job payloads or automatically attached to claims. A standalone executor can explicitly call `context.download_artifact(grant_id, sha256=expected_digest, byte_size=expected_size)` with pinned input metadata. It returns bytes only after full length and SHA-256 verification, and requires the response's authorized attempt to match the context. It constructs a same-origin path from a canonical grant UUID, not a job-selected URL. Cancellation, lease loss, transfer timeout checks, truncation, ambiguous framing, wrong-attempt responses and corruption refuse the input without returning partial bytes. The input is buffered in memory, not written to disk. `--artifact-max-bytes` sets the per-input cap (default 16 MiB, permitted 1 byte through 64 MiB); larger inputs need a future streaming/staging implementation, not an unbounded setting.

An executor can explicitly call `context.discover_artifacts(cursor=...)` to fetch one bounded page of already-issued grants for its own current fenced attempt. The response contains `attempt_id`, `grants` and `next_cursor`; each reference exposes only grant/artifact IDs, pinned size/digest and expiry. At most 32 candidates are validated per page; pages can be empty with a non-null advancing cursor when candidates are ineligible. The helper does not automatically paginate or download. It validates response scope, identifiers, metadata, expiry and cursor progression before returning. The executor must select the intended artifact explicitly; discovery is not a frozen input-manifest resolver.

Neither helper issues, renews or retries grants, and downloads are not resumable. Do not provision an administrator credential to the worker: an authorized external controller still chooses and issues the grants, while the scoped worker can now retrieve their references itself. This is control-plane-to-worker input access, not worker output upload permission, an artifact-residency router, or a network sandbox. Metadata-only result policy continues to restrict worker-to-control-plane results, not these explicitly authorized inputs. See [worker artifact grants](worker-artifact-grants.md) for scope and lifecycle limits.

The [standalone input client](worker-artifact-client.md) documents the executor helper's return/exception contract, byte cap, attempt binding and remaining boundaries.

## Resumable artifact uploads

Create a transfer session for a staging artifact with `POST /api/v1/artifacts/{artifact_id}/transfers/`. Upload each non-empty part with `PUT /api/v1/artifacts/{artifact_id}/transfers/{transfer_id}/parts/{part_number}/`, as multipart form field `file`, and provide the lowercase part digest in `X-Part-SHA256`. Parts are limited to 16 MiB and numbered from 1; they may arrive out of order and exact retries are idempotent. `GET .../transfers/{transfer_id}/` returns the durable manifest for resume. `POST .../complete/` verifies order, total size, and the staged artifact digest before committing; incomplete transfers remain staging. `POST .../abort/` is idempotent. Sessions expire after 24 hours. Part objects for old terminal sessions can be purged while retaining their manifests with `make prune-transfer-parts RETENTION_DAYS=N`; choose a retention period that matches the installation policy. Managed-provider behavior and automated cleanup scheduling still require qualification.

