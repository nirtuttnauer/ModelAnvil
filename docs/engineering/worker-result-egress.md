# Worker result-egress policy

**Status:** Implemented bounded result-content policy; not a qualified private-data gateway.

This describes the current worker API and standalone HTTP agent. The authoritative platform scope remains in [technical requirements](technical-requirements.md), especially TECH-029 and the job/storage contracts. This slice does not satisfy their complete hybrid or artifact-egress acceptance criteria.

## 1. Modes and compatibility

`WorkerPool.result_egress` accepts:

| Mode | Result boundary |
| --- | --- |
| `envelope` | Existing result-envelope and error behavior. |
| `metadata_only` | Status-only result submissions; no envelope, nonempty free-form error, or nonempty artifact descriptors. |

Both the pool field and agent's local configuration default to `envelope` for compatibility. This is **not** a private-workload safety default. Existing pools receive that value through `jobs.0006_workerpool_result_egress`.

For a private worker, configure the pool and pin `--result-egress metadata_only` locally **before starting execution**. This limits the agent's result payload, not arbitrary network activity by trusted executor code.

## 2. Administrative configuration

A tenant administrator (admin or owner role) sends:

```text
POST /api/v1/workers/pools/{pool_id}/egress/
```

```json
{"result_egress": "metadata_only"}
```

A successful response is HTTP 200:

```json
{"ok": true, "result_egress": "metadata_only"}
```

Configuration is tenant-scoped and transactional. It records an `update` audit event for `worker_pool`, with only `pool_id` and `result_egress` in its input snapshot. It does not record credentials or worker result content.

- An authenticated non-administrator API principal is rejected with 403.
- A scoped worker credential cannot access this administrative route and is rejected by authentication with 401.
- A pool outside the authenticated tenant is concealed with 404.
- A missing or unsupported mode is rejected with 400 without changing the policy.

Worker/pool IDs in the current implementation are integer database IDs. Registration renders `worker_id` as a decimal string; worker protocol requests use an integer. Job and attempt IDs are UUIDs. This document does not imply completion of organization/project-scoped API migration.

## 3. Policy discovery and precedence

Registration, successful claim and heartbeat responses include `result_egress`. Registration is informational; the standalone agent receives execution policy from its claim and subsequent heartbeats, not by registering itself.

A metadata-only local setting or pool setting restricts the effective mode. Job payloads cannot select or relax that setting. After an attempt observes metadata-only policy, a later heartbeat reporting `envelope` does **not** relax that attempt. A future attempt starts with its own claim and local configuration.

An unknown claim policy prevents executor invocation. An unknown heartbeat policy makes lease ownership uncertain and prevents result publication. The agent retains the legacy `envelope` fallback when an older server omits the claim field; an explicitly pinned local metadata-only setting still applies.

## 4. Executor and agent behavior

The operator-installed executor receives `(descriptor, context)` and normally returns a canonical EnvelopeSample or `None`.

Under effective metadata-only policy:

- Returning `None` reports `succeeded`, unless cancellation, executor failure, or lease loss changes the outcome.
- Returning an envelope withholds it **before the HTTP request** and reports a status-only `failed` result.
- Executor exceptions report `failed` without a free-form `error` field.
- Cooperative cancellation reports status-only `interrupted` after the executor returns; the control plane maps acknowledged cancellation to the job's cancelled state.
- Lease loss abandons the result. Uncertain commit acknowledgements are not blindly retried and do not rerun the executor.

The normal status-only request includes `worker_id`, `attempt_id`, `fencing_token`, and `status`. It **omits** `result_envelope`, `error`, and `artifacts`. `None` is a Python executor return value, not an instruction to send JSON `null` in the envelope field.

A conforming agent's withheld-envelope case is a normal status-only result commit, not a 403 response. The API returns HTTP 200 when that failed attempt is successfully committed. HTTP success acknowledges recording the terminal state; it does not mean the execution succeeded.

The agent does not implement artifact upload/download in either mode. Scoped worker credentials permit claim, heartbeat and result protocol routes, plus the dedicated download endpoint for administrator-issued [attempt-scoped input grants](worker-artifact-grants.md). They cannot access the general tenant artifact APIs. This input-access hook does not grant worker output uploads or relax metadata-only result enforcement.

## 5. Server and transactional enforcement

The result API authorizes the worker/attempt and checks the current tenant-owned job pool before envelope schema validation. In a metadata-only pool, it rejects:

- Any supplied dictionary `result_envelope`, including `{}`.
- A nonempty `error` string.
- Nonempty `artifacts` descriptors.

These policy violations produce a generic 403, without echoing the submitted content, and leave the attempt and worker slot unchanged. Explicit `result_envelope: null` is not accepted: the serializer rejects it with 400. Omit the field for status-only reporting.

An omitted error or empty string and an omitted artifacts field or empty list do not violate this result policy. Other serializer, authorization, lease and fencing checks still apply. An unknown stored pool mode fails closed, including for a status-only submission.

The shared `commit_result()` service rechecks the pool mode inside its transaction before persistence. It uses job → worker → pool lock ordering consistent with claims, and serializes publication with administrator policy changes. This also prevents direct model callers from persisting an envelope or nonempty error in a metadata-only pool; such callers receive a validation exception rather than an HTTP response. The service does not persist artifact descriptors.

## 6. Security limits

This is a result-content boundary, not proof of comprehensive data-loss prevention:

- Server rejection cannot recall bytes already transmitted by an old or noncompliant client. Local metadata-only pinning is the conforming agent's pre-transmission boundary.
- Pool updates cannot recall in-flight requests or retrospectively redact previously stored results.
- Control-to-worker job payloads are not minimized by this result-only policy.
- Heartbeat progress and other permitted metadata are not protected against covert channels or privacy inference.
- Trusted executor code is not sandboxed. Its own network calls, data access, logs and external providers require separate controls.
- There is no content classifier or secret detector. Do not include credentials or connection strings in job inputs, results, logs or documentation. Registration deliberately returns a one-time credential; store it securely and never log the registration response.
- This policy does not change tenant API keys' permissions on unrelated APIs.

Artifact residency routing, attempt-scoped artifact transfer grants, permitted artifact destinations, credential provisioning/rotation, backend stop confirmation, and disconnected/reconnected private-worker qualification remain separate work. Do not advertise full TECH-029 compliance from this slice.

## 7. Verification

`make test-worker-integration` rebuilds the current API image and exercises the agent over real HTTP backed by isolated PostgreSQL. It also runs the result-egress API regressions and removes its test stack and volumes.

The automated cases cover administration and tenant isolation, policy discovery, content refusal without attempt mutation, pre-transmission suppression, local/pool precedence, tightening and relaxation during an attempt, unknown-policy failure, status-only commits, executor errors, and a policy change between the view's initial read and the transactional commit.

The fast suite includes the same cases with SQLite. These checks do not constitute production hybrid qualification, distributed policy-race stress testing, or evidence that external backend execution has stopped.
