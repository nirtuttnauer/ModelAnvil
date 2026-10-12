# Runpod integration and custom plugins

Runpod Pods can provision a pinned worker container through REST API v2. ModelAnvil records the allocation, reserves its maximum lifetime against an `allocation_seconds` budget, issues a scoped worker credential, and starts the outbound worker. Operators can also install compute provider factories and task executors. The Compute page exposes available plugins, GPU discovery, allocation creation, status reconciliation, release, and custom task submission.

This implementation covers the provider control API and trusted worker protocol. It does not qualify a remote training recipe, large input staging, output artifact uploads, production serving, or a vendor invoice. A Runpod pod reporting `RUNNING` is separate from a worker reporting an attempt heartbeat.

## Operator setup

1. Apply migrations with `python manage.py migrate`. Register an active worker pool in the target organization and create an enabled budget policy with unit `allocation_seconds`, an empty currency, and a limit in seconds of allocated capacity. The allocation budget is separate from each job's budget. It counts allocation wall time, regardless of GPU count.
2. Build and publish a worker image containing this repository and the chosen executor's dependencies. Use its real registry SHA-256 digest in the configuration. The Runpod entrypoint overrides the normal web-server command with `python -m modelanvil.compute.worker`. Do not publish a container containing credentials.
3. Copy [the example configuration](../../deploy/compute-plugins.example.json). Replace both `tenant_ids` with the real organization UUID and the worker image and HTTPS endpoint. The endpoint must be accessible from Runpod and end in `/api/v1/workers/`. Both compute and task definitions must be installed for the same tenant.
4. Set `MODELANVIL_PLUGINS` to the JSON configuration in the API and reconciler process. Provision the secret named by `credential_env` separately; the example uses `MODELANVIL_RUNPOD_API_KEY`. Provider secrets are never submitted from the browser or passed to the worker. Changing a definition changes its digest; retain the same definition for existing allocations until released. Rotating the value of its credential environment variable preserves the digest.
5. Run `python manage.py reconcile_compute --loop` with the same database and provider configuration. The Compose profile `external-compute` adds this service: `docker compose --profile external-compute up --build`. Supply deployment-specific environment variables for custom provider credentials through an overlay. The local Compose API needs a suitable HTTPS deployment before remote workers can connect.
6. Open Compute with an organization-scoped administrator key. Choose Runpod, a pool, an allocation budget, GPU, data center, disk size, and maximum rental duration. Choose the installed task plugin to submit a bounded job to its matching worker pool.

Compute requests use organization scope even when a project is selected in the workspace. The browser's task jobs retain the selected project. A key intrinsically restricted to a project remains restricted and cannot provision or release organization compute.

The bundled `uppercase` task proves the extension path by returning a canonical text sample. It does not perform GPU training. Replace it with an operator-installed remote-compatible executor to run your workload. Existing executors that access Django database records or local artifact paths cannot become remote-compatible simply by placing them in a Runpod container.

## API lifecycle

`GET /api/v1/compute-plugins/` lists only plugins explicitly bound to the active tenant, their schema and revision digest, and the caller's management/submission permissions. `GET /api/v1/compute-plugins/{id}/catalog/` reads the provider catalog. Catalog pricing and availability are observations rather than a placement guarantee or an invoice.

`POST /api/v1/compute-allocations/` requires:

```json
{
  "request_id": "a UUID retained by the client for retries",
  "plugin_id": "runpod",
  "pool": 1,
  "policy_id": "the allocation_seconds budget policy UUID",
  "lifetime_seconds": 3600,
  "spec": {
    "gpu_id": "NVIDIA H100 PCIe",
    "gpu_count": 1,
    "disk_gb": 50,
    "cloud": "SECURE",
    "data_center_ids": ["a data center from the current catalog"]
  }
}
```

Repeat the same tenant request UUID and parameters after an uncertain HTTP result. The response reflects the durable allocation, including provider rejection or uncertainty; HTTP 201 does not imply provider readiness. Conflicting parameters are refused. Lifetime is bounded to 60–86400 seconds. No arbitrary image, command, environment variables, provider endpoint, secret name, or Python module is accepted in a request.

`POST /api/v1/compute-allocations/{allocation_id}/refresh/` reconciles provider state. `POST .../release/` commits a release intent, revokes its worker credentials, and requests termination. Both require an organization-scoped administrator key. GET list/detail is tenant-scoped and available to viewers.

The reconciler finds ambiguous creations by the stable `modelanvil-{allocation_id}` pod name, walks provider pagination, and requires exactly one identity match. No match or multiple matches remain unresolved. It never resubmits create. If an allocation cannot be found after a timeout, inspect the provider account before taking manual action; absence from an eventually consistent list does not prove no charge exists. Do not rename managed pods externally.

Release stays pending when termination cannot be verified. Only a matching resource reporting `TERMINATED` or a resource GET returning 404 permits settlement and terminal release. Explicit provider rejection releases the unused reservation. Confirmed release settles observed wall time; uncertain allocations retain reservations. Expiry revokes execution authority and requests release on the next reconciler pass. It is not an independent provider-enforced billing cap: run and monitor the reconciler, and resolve reported failures.

## Custom compute provider contract

An operator definition declares `contract_version: "1.0"`, `kind: "compute"`, explicit tenant UUIDs, a trusted `factory` in `module:callable` form, `credential_env`, a local JSON Schema for configuration, pinned `image`, `worker_endpoint`, and `worker_executor`. The factory receives the resolved credential and returns an object with:

| Method | Contract |
| --- | --- |
| `catalog()` | Return JSON-safe offer objects. The Runpod UI uses `id`, `name`, `memory`, and `dataCenters`. Custom providers may use the JSON configuration form. |
| `create(name, spec, bootstrap)` | Create once with the exact supplied ownership name and return `{id, name, status}`. Bootstrap contains the pinned image and scoped worker environment. |
| `inspect(resource_id)` | Return `{id, name, status}` or `None` only when authoritative inspection confirms absence. |
| `find(name)` | Return all matching normalized resource identities, including every provider page. |
| `release(resource_id)` | Request termination; inspection must subsequently establish release. |

IDs must contain only letters, digits, underscores or hyphens and fit in 128 characters. Status names use uppercase letters/underscores; `TERMINATED` is the terminal release status. Ownership names must be preserved. Raise `ProviderError(code, uncertain=False)` only for a definite create rejection; transport failures and uncertain mutations use `uncertain=True`. Error codes must be static identifiers with no secret values or provider response bodies. Unexpected plugin exceptions are sanitized by the controller.

The built-in Runpod adapter uses a fixed HTTPS origin, disables redirects and ambient proxies, bounds responses to one MiB, uses a 30-second request timeout, and never implicitly retries a create. It uses the current [Runpod REST v2 contract](https://docs.runpod.io/api-reference-v2/overview), including [GPU catalog](https://docs.runpod.io/api-reference-v2/catalog/list-gpu-types), [pod creation](https://docs.runpod.io/api-reference-v2/pods/create-a-pod), [pagination](https://docs.runpod.io/api-reference-v2/pods/list-pods), and [termination](https://docs.runpod.io/api-reference-v2/pods/terminate-a-pod).

## Custom task contract

A task definition declares `contract_version: "1.0"`, `kind: "task"`, tenant UUIDs, a trusted `executor` in `module:callable` form, and `configuration_schema`. The callable receives `(descriptor, context, configuration)` and returns a canonical sample envelope or `None`. Call `context.heartbeat()` regularly and stop when it returns false. The existing worker validates outputs, honors cancellation, and fences result publication.

Register a dedicated worker with capabilities `task_plugin` and `task_plugin_digest` matching the plugin list response. Submit through the existing `/api/v1/jobs/` API with those same two fields in `requirements` and configuration in `payload.configuration`; retain the normal `Idempotency-Key` and job-budget behavior. Admission validates the installed plugin digest and schema. Configuration is bounded to 16 KiB and cannot resolve remote schema references. Jobs supply data, not executor import paths.

For a local trusted process, run:

```sh
python manage.py run_plugin_worker --worker-id ID --plugin-id uppercase --once
```

For a Runpod task worker, set `task_plugin` on the compute definition and use `worker_executor: "modelanvil.compute.task_worker:execute"`. ModelAnvil automatically adds the task revision to worker capabilities and sends only that task's definition to the container. The task module/package must already exist in the image. The outbound agent requires no database or broker connection; this dispatcher loads Django settings for the operator allowlist without initializing Django models.

Installed Python code is trusted operator code. Configuration validation and the adapter registry do not sandbox its filesystem or network access. Deployment isolation remains the operator's responsibility. Provider management permissions, scoped worker credentials, tenant identity, and schema validation are enforced by this implementation.

## Verification and remaining providers

The compute tests cover REST v2 request construction, sanitized provider errors, pagination, allocation replay, budget admission, ambiguous creation recovery, ownership checks, expiry cleanup, verified release, tenant/role/project boundaries, and actual fenced task execution. Live Runpod capacity, GPU workload performance, persistent volume retention, large artifact transfer, and provider invoice reconciliation require separate qualification.

See the [provider TODO](provider-integration-todo.md) for every mapped compute, inference, storage, and customer infrastructure integration. Unchecked providers are not implemented by this PR.
