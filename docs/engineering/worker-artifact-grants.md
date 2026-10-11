# Worker input artifact grants

**Status:** Bounded attempt-scoped download hook. Local filesystem only; not full TECH-029 qualification.

The authoritative requirements remain in [technical requirements](technical-requirements.md) and [implementation plan](implementation-plan.md), especially scoped artifact access in WP-03 and the current-access gateway in WP-04. This hook authorizes **control-plane-to-worker inputs**, not worker output publication.

## API and explicit authority

An authenticated tenant administrator (admin or owner) issues:

```text
POST /api/v1/workers/artifact-grants/
```

Provide `worker_id` (integer), `attempt_id` and `artifact_id` (UUIDs), and optionally `ttl_seconds` (integer, default 60, range 1–300). All references must belong to the administrator's tenant. The attempt must currently run on that worker, with matching job ownership and fencing, live job/attempt leases, and no cancellation request. Offline workers and unknown execution actions fail closed; draining does not terminate an existing attempt's access.

HTTP 201 returns `grant_id`, `artifact_id`, `expires_at`, and `download_path`. The expiry is capped at the attempt lease as observed at issuance. Subsequent heartbeats do not extend the grant. Grants may be reused while valid; they are not one-use transfer tickets.

Only an unversioned committed artifact whose `storage_location_id` is `local` can receive this grant, and only with the configured filesystem backend. S3, arbitrary location labels and versioned objects are refused. This deliberately avoids claiming location-aware routing or version-aware storage access that the current backend factory does not implement.

The administrator chooses the artifact explicitly. Grants are not derived from job payloads, limited to an automatically resolved manifest, or attached automatically to claims. The API does not implement project authorization beyond the existing tenant boundary. Do not represent this as complete frozen-run-input or organization/project grant support.

## Scoped discovery

The worker can explicitly discover existing grants through `POST /api/v1/workers/artifact-grants/discover/`. Send the same fenced execution identity used for heartbeat (`worker_id`, `attempt_id`, `fencing_token`), with optional `cursor` (canonical lowercase hyphenated grant UUID). Identity is in the request body, not the URL. Fencing values are compared literally: discovery, heartbeat and result serializers do not trim padding into a valid value. This route requires the bound scoped worker credential; administrator keys cannot substitute. The endpoint never creates or renews authority, and an empty valid page does not create grants.

HTTP 200 returns `attempt_id`, `grants`, and `next_cursor`, with `Cache-Control: private, no-store`. Each reference contains only `grant_id`, `artifact_id`, `sha256`, `byte_size`, and `expires_at`. No bytes, object keys, backend roots, filenames, storage credentials or fencing values are included. Scope/current execution, credential and active tenant are checked even if no grant candidates exist. Each candidate is reauthorized against the pinned artifact/backend. Execution and credential expiry are checked again before returning; grants that expire during validation are omitted.

The page examines at most 32 candidates, with one lookahead row to determine whether a subsequent candidate page existed. It orders by grant UUID and uses the last examined candidate as the advancing cursor. Ineligible references are omitted without scanning an unbounded number of rows to fill a page. A page can therefore have no grants and a non-null cursor; the cursor may name an ineligible candidate and never authorizes a download. Continue explicitly until `next_cursor` is null, not merely until a page is empty. Every page checks current access again. This is not a frozen multi-page snapshot: grants issued later with lower IDs require restarting discovery, and expiry/revocation can change later pages.

`context.discover_artifacts(cursor=...)` on the standalone context fetches and validates one page. It does not auto-paginate, auto-download, or resolve the run's intended input manifest. The worker still cannot list the tenant artifact registry or issue/revoke grants.

## Download

GET the returned path:

```text
GET /api/v1/workers/artifact-grants/{grant_id}/download/
```

Use the bound worker's active scoped credential. A grant ID or URL alone is not authorization. Another worker or tenant cannot use it, and administrator API keys cannot substitute for the worker credential on this endpoint. The worker still cannot use the general tenant artifact APIs, issue/revoke grants, upload objects or create resumable upload sessions. The download route accepts GET, not uploads.

The response is a private, no-store attachment, with the declared `Content-Length`, a quoted SHA-256 `ETag`, and `X-ModelAnvil-Attempt-ID` identifying the authorized grant's attempt (not its fencing value). The server never releases backend credentials or presigned storage URLs. Consumers must check complete length and SHA-256 before treating bytes as a usable pinned input. An ETag declaration alone is not independent content verification, and storage operators remain trusted with the filesystem's bytes.

The standalone worker agent does not automatically issue grants or download inputs. An operator's trusted executor can explicitly call `context.download_artifact(grant_id, sha256=expected_digest, byte_size=expected_size)` to receive verified bytes in memory. It can obtain a reference through scoped discovery and select the intended artifact by ID, rather than provision administrator credentials or copy digest metadata from download headers. The helper constructs a same-origin path, refuses redirects and wrong-attempt responses, and checks length, digest, framing, cancellation and lease state. Its operator byte cap defaults to 16 MiB and cannot exceed 64 MiB; `--artifact-max-bytes` configures it. No partial bytes are returned. File staging, resumability and automatic grant push/renewal are not implemented. The agent's one-MiB JSON control-response bound is separate from the helper's input cap and the gateway itself has no new per-artifact size quota.

## Current-access reauthorization

See [standalone worker input client](worker-artifact-client.md) for the helper interface, response-attempt binding, transport checks and caller-visible failure behavior.

Before opening and before each file read of at most 64 KiB, the gateway rechecks:

- Grant tenant, worker, attempt, expiry and revocation.
- Current job/attempt ownership, statuses, fencing and leases, desired action, worker status and pool tenant scope.
- The authenticating credential's worker/tenant binding, expiry and revocation, and the tenant's active state.
- Artifact tenant and committed state, and its pinned object identity, digest, size and media type.
- The configured local backend identity, pinned as a digest of its resolved root, without recording storage credentials.

Execution checks acquire attempt → job → worker → pool locks, consistent with the existing result-commit/reconciliation path. Reads additionally hold grant, credential, tenant and artifact locks within the bounded read transaction. Network writes occur after that transaction; locks are not retained for the whole HTTP response. Administrator grant revocation serializes on the grant row. This is locally tested behavior, not distributed lock-stress qualification.

Metadata and expiry are immutable through model `save()`; revocation cannot be restored. These are application-level guards, not SQL-trigger protection against trusted direct database writes. Tombstones, terminal results, changed ownership/fencing, cancellation, expired leases, credential revocation or tenant suspension stop subsequent reads. Backend changes invalidate an existing grant instead of redirecting it to another root.

A mid-transfer refusal closes the stream, leaving a truncated response whose declared length is not satisfied. Bytes already read, buffered or received cannot be recalled. Clients must discard incomplete inputs; revocation is not retroactive erasure. Filesystem/backend errors can also interrupt a transfer and require discarding its staging bytes.

## Revocation and audit

An authenticated administrator in the grant's tenant sends:

```text
POST /api/v1/workers/artifact-grants/{grant_id}/revoke/
```

HTTP 200 confirms revocation; repeated revocation is idempotent. Other tenants' grant IDs are concealed. Issue and revoke operations record the administrator identity and metadata-only audit events in the same transaction as the mutation. Audits do not contain file bytes, object paths, fencing values or credentials.

Revoking the worker credential also stops its subsequent reads. Expired/revoked grant rows currently remain for inspection; there is no automatic grant retention/pruning job. Their protected foreign keys can block physical deletion of referenced attempts/workers/artifacts. Dependency-aware deletion/retention remains operational work; do not delete grant history without an approved policy.

## Boundaries still open

This does not provide worker output-artifact transfers, configurable per-pool artifact destinations, residency routing, private object-store gateways, managed-S3/version qualification, automatic grant push/renewal or frozen input-manifest resolution, resumable downloads, gateway byte/request quotas, project-level grants, or complete offline/reconnect/production acceptance. Metadata-only **result** policy does not prohibit these administrator-authorized **inputs** and does not sandbox an executor's independent network calls.

## Verification

Fast API tests are in `modelanvil/api/test_worker_artifacts.py`. Real HTTP tests in `modelanvil/api/test_worker_artifact_http.py` download verified fixture bytes and revoke a gated in-flight transfer, proving that the standalone client discards the incomplete input. They also cover corrupted bytes, attempt binding, empty artifacts and the client byte cap. The gate coordinates the real stream; it does not replace storage reads, authorization or revocation. `modelanvil/jobs/test_remote_artifacts.py` qualifies client framing, redirects, cancellation, deadline checks and sanitized errors, including deliberately noncompliant HTTP servers.

`make test-worker-integration` rebuilds current source and runs these cases with the worker/result-egress tests against isolated PostgreSQL. Its EXIT cleanup removes the temporary stack and volumes. SQLite success alone is not evidence of PostgreSQL lock behavior, managed storage, production throughput or hybrid data-residency compliance.
