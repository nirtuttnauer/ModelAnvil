# Worker artifact client

**Status:** Implemented bounded input helper. Filesystem grants only; not full TECH-029 qualification.

The standalone worker exposes `context.download_artifact(grant_id, sha256=expected_digest, byte_size=expected_size)` to trusted operator-installed executors. It returns a Python `bytes` value only after complete size and SHA-256 verification. Failure raises a sanitized `WorkerProtocolError`; no partial bytes, file path or JSON error object are returned. A valid empty artifact may return `b""`. The default per-input cap is 16 MiB, configurable up to 64 MiB. Expected metadata must come from a pinned authorized input, not simply be copied from response headers.

## Authority and lifecycle

A tenant administrator explicitly issues a grant binding one artifact to one current attempt and worker. Multiple grants may exist for an attempt and grants are reusable while valid, not one-use tickets:

```text
POST /api/v1/workers/artifact-grants/
```

Body:

```json
{
  "worker_id": 42,
  "attempt_id": "923c9517-7b96-4cb4-8ed1-36d5cd013ad9",
  "artifact_id": "a5f7436a-2d64-4b19-971b-b8a77646641a",
  "ttl_seconds": 60
}
```

The HTTP 201 response contains `grant_id`, `artifact_id`, `expires_at`, and `download_path`. The request identifiers above are illustrative. Grant IDs are canonical hyphenated UUIDs, not credentials.

The grant is **not** automatically issued on claim or heartbeat. It is scoped to the current running attempt only; subsequent heartbeats do not extend it. Once the attempt ends (succeeded/failed/cancelled/interrupted) or the lease expires, the grant becomes invalid.

Default TTL is 60 seconds, permitted TTL is 1–300 seconds, and expiry is capped at the attempt lease observed at issuance. An authorized external controller chooses and issues grants; the worker can obtain their references with the scoped discovery helper below. Do not provision an administrator credential to a worker for grant issuance. Automatic grant push/renewal and frozen-manifest resolution are not implemented.

## Explicit discovery

`context.discover_artifacts(cursor=None)` fetches one page of already-issued input grants for this context's fenced attempt through `POST /api/v1/workers/artifact-grants/discover/`. The helper supplies execution identity in the JSON body using the scoped worker credential. The server exposes no tenant-wide registry access and creates no grants.

The returned Python dictionary has exactly `attempt_id`, `grants`, and `next_cursor`. Each reference has exactly `grant_id`, `artifact_id`, `sha256`, `byte_size`, and `expires_at`. The helper validates its attempt binding, canonical IDs, lowercase digest, nonnegative integer size, timezone-aware unexpired grant expiry, page bound, strict grant ordering and advancing cursor. Unknown fields, malformed metadata, repeated IDs or a wrong-attempt response raise a sanitized `WorkerProtocolError`. Local cancellation/lease loss/expiry are checked before the request and before returning. References can describe inputs above the operator download cap; selecting them for download still fails the independent byte-cap check.

The server validates at most 32 candidates per page and omits ineligible references, so an empty page with a non-null cursor is valid. A non-null cursor is scan position, not download authority; it can advance past an ineligible grant. Every page rechecks current access. Pagination is not a frozen snapshot: later grants with lower IDs require restarting discovery, and references can expire or be revoked before download.

The executor controls whether to request another page or download a selected artifact. The helper does not auto-paginate, auto-download, issue, renew or retry grants. Discovery returns administrator-authorized pinned size/digest metadata, not proof that an artifact is the run's intended input; select by the intended artifact ID and retain any required independently frozen run metadata. See [scoped discovery](worker-artifact-grants.md#scoped-discovery) for server bounds and authority checks.

## Download request

The client uses the grant ID to request the artifact:

```text
GET /api/v1/workers/artifact-grants/{grant_id}/download/
Authorization: Bearer [REDACTED]
```

- The helper validates a canonical lowercase, hyphenated UUID-shaped `grant_id` and constructs the path under its configured `/api/v1/workers/` endpoint. Invalid identifiers are rejected, not normalized. It does not accept a job-selected URL or follow a supplied `download_path`.
- It uses the agent's existing tenant/worker-bound scoped credential. That credential is not grant-specific or attempt-lifetime-only; download authority additionally requires a valid grant and current execution. Its other allowed operations are claim, heartbeat, result and attempt-scoped discovery, not tenant artifact CRUD/upload or grant administration.
- The client **must not** follow redirects or use the credential to access unrelated endpoints.

## Bounded stream semantics

### Upper bound

- `artifact_max_bytes` is configured per-operator (default 16 MiB) via the CLI `--artifact-max-bytes` flag.
- The client **must** enforce a positive integer upper bound ≤ 64 MiB.
- If the artifact's `byte_size` exceeds `artifact_max_bytes`, the client must abort and report a validation error.

### Bounded reads

- The gateway reads at most 64 KiB from the filesystem per authorized read. This is not a guarantee about HTTP packet boundaries.
- The client uses `read1()` requests of at most 64 KiB and accumulates input in memory while computing a rolling SHA-256.
- Before and after each read it checks observed cancellation, lease loss, local lease expiry and a monotonic deadline based on the agent's request timeout. A blocked socket operation can still wait for its configured timeout before that check runs; this is not forceful interruption of arbitrary executor code.
- Truncation, excess bytes, corruption or access/deadline refusal discard the input from the caller's perspective. The helper neither writes staging files nor automatically retries/resumes.
- The cap is per input, not an aggregate process-memory quota. Buffering and the final immutable bytes copy consume memory. It is separate from the one-MiB JSON control bound and is not a new gateway-side storage quota.

### Identity verification

- The artifact record provides the expected SHA-256 digest (lowercase 64 hex) and `byte_size` (nonnegative integer).
- Before HTTP, the client rejects malformed digests, non-integer/negative sizes, booleans, sizes exceeding the operator cap, and locally cancelled/lost/expired contexts.
- Before body reads, it requires HTTP 200, exactly one matching `Content-Length`, and exactly one `X-ModelAnvil-Attempt-ID` matching its context's attempt. The attempt header contains no fencing value.
- Partial-content status, compression, transfer encoding and duplicate identity/framing headers are refused.
- Final accumulated byte count and computed SHA-256 must match the independently pinned expected metadata.
- The server's quoted digest `ETag` is informative. The helper does not require it or use it instead of actual content verification.

## Connection and credentials

### Endpoint

- The client uses the agent's configured HTTPS worker endpoint with certificate verification and disabled ambient proxies.
- Plain HTTP requires explicit numeric-loopback opt-in for local development.
- Redirects are not followed or supplied the credential.

### Credential

- The client receives a scoped bearer token from the operator (not from the job payload).
- The credential is tenant/worker-bound, expiring and revocable. It is not grant-specific; a grant is additional authority, not a replacement credential.
- The helper supplies the credential only to the constructed same-origin download request. The agent also uses it on the permitted worker protocol routes.
- No backend credentials or presigned storage URLs are released. A grant ID alone cannot authenticate a request.

### Revocation

- The client does not receive an expiry parameter or independently query grant expiry. The gateway enforces grant validity; the client checks its local attempt lease and observed cancellation/lease loss.
- Before each file read (≤ 64 KiB), the gateway rechecks:
  - Grant validity (not revoked, not expired).
  - Current attempt lease and desired action.
  - Credential expiry/revocation, worker/tenant binding and active tenant.
  - Current job/attempt/worker/pool ownership, fencing, leases and desired action.
  - Artifact committed state, pinned identity and local backend fingerprint.
- Initial refusals can return HTTP errors. After response headers have been sent, revocation cannot change the response into a new error status: it stops subsequent authorized reads and may leave a short HTTP 200 body, which the client rejects.
- The client must stop downloading on the first refusal and discard any buffered bytes.
- Already-read, buffered or transmitted bytes cannot be recalled. Revocation is not retroactive erasure.

## Error handling

| Condition | Helper behavior |
| --- | --- |
| Initial HTTP refusal | Sanitized `WorkerProtocolError` reporting status, without server body |
| Malformed identity/digest/size or over-cap size | Local exception before HTTP; no HTTP 400 is generated |
| Framing/attempt mismatch, compression, partial status | Exception before body reads |
| Digest mismatch or incomplete stream | Exception; no partial input returned |
| Redirect | Refused; no redirected credential-bearing request |
| Cancellation, lease loss/expiry or deadline check | Refused locally before/after reads |
| Transport failure | Sanitized exception; no automatic backoff/retry |

A revoked credential can fail authentication before grant authorization, so not every authority refusal uses the same HTTP status. Local client exceptions are not HTTP 400/500 responses.

## Output

On success, the helper returns verified Python `bytes`. On failure it raises, not returns an empty artifact, and does not log response bodies or exception diagnostics. An empty committed artifact is a legitimate success and must not be confused with failure.

If an exception escapes the executor, the agent's existing executor-failure handling applies. Metadata-only result policy withholds free-form errors. The helper does not produce a JSON result envelope or file-path result.

## Limitations

- The client is **standalone**: importing the worker does not initialize Django or connect to a database/broker. It still uses the worker context/lifecycle and the scoped HTTP gateway.
- The client is **input-only**: it does not upload or publish worker outputs.
- The helper is **attempt-bound**: it accepts only responses whose authorized-attempt header matches the calling context. This does not sandbox the trusted executor or replace server authorization.
- Supported grants are **filesystem-only**, committed, unversioned, and at literal `storage_location_id == "local"`. S3/version-aware routing is not implemented. The worker may be remote; "local" names the gateway's supported storage mapping, not the worker's physical location.
- The client is **unsandboxed**: the operator controls the executor; the client inherits the operator's network privileges.
- The client is **not resumable** and does not automatically restart failed downloads. A caller's retry may no longer be authorized.
- It does not provide automatic grant push/renewal, project-level grants, frozen-manifest resolution, output-artifact egress/residency routing, gateway byte/request quotas, large-file staging, or offline/reconnect/production hybrid qualification.
- Trusted executors are not sandboxed; the helper and result-egress policy do not restrict their independent network calls or erase bytes they deliberately retain. Metadata-only results are separate from administrator-authorized inputs.

## Verification

- `modelanvil/api/test_worker_artifact_http.py` exercises the real gateway/client, including scoped discovery followed by verified consumption, explicit multi-page discovery, empty inputs, attempt binding, corrupted bytes despite matching declared metadata, size caps and synchronized in-flight revocation with incomplete-input rejection.
- `modelanvil/api/test_worker_artifacts.py` verifies discovery authorization/isolation, bounded cursor pages, empty/ineligible pages, no auto-issuance, and credential/lease/grant expiry during page validation.
- `modelanvil/jobs/test_remote_artifacts.py` covers canonical paths, malformed metadata, noncompliant framing/duplicate headers, truncation, partial status, redirects, sanitized errors, cancellation, deadline checks and bounded reads.
- `modelanvil/jobs/test_remote_worker.py` covers CLI cap configuration and worker lifecycle/result boundaries.
- `make test-worker-integration` rebuilds current source and runs these modules with the grant API/result-egress tests against isolated PostgreSQL. EXIT cleanup removes the temporary stack and volumes.
- These are bounded gateway/client tests, not complete production, managed-storage, throughput or disconnected-worker acceptance evidence.

## References

- [Worker artifact grants](./worker-artifact-grants.md)
- [Worker result-egress policy](./worker-result-egress.md)
- [Technical requirements](./technical-requirements.md)
