# Local model tools

Chat → Tools runs the exact provisioned Qwen3-0.6B snapshot on one CPU worker. The model generates native tool calls, receives actual results and generates a continuation. It does not infer permission from prompts or MCP annotations. Model quality, customer integrations and production qualification remain separate gates.

## Provision and start

Install the normal requirements plus `requirements.tools.txt` in the API/worker environment. Provision the six files listed in `modelanvil/runners/tool_runtime.py` from Qwen/Qwen3-0.6B revision `c1899de289a04d12100db370d81485cdf75e47ca`, including its Apache-2.0 license. The setup command and independent consumer verify exact sizes and SHA-256 values. Model acquisition is an operator step; execution never downloads files, loads pickle weights or runs remote model code.

```sh
python manage.py setup_tools --tenant-id TENANT_UUID --project-id PROJECT_UUID \
  --name local-tools --model-dir /absolute/provisioned/qwen3 --token-limit 10000
python manage.py run_worker --worker-id WORKER_ID \
  --executor modelanvil.runners.tool_jobs.tool_executor
```

Keep the worker running. Its CLI marks it offline when it exits, including `--once`. The import creates a draft model, immutable native tokenizer, single-slot worker pool and a generated-token quota. It does not grant tool permissions or launch a job. Use a host with at least16GiB physical memory; that observation is a profile minimum, not a free-memory reservation. Inference is explicit FP32 CPU with one thread, native tool formatting, thinking disabled and greedy decoding.

An administrator enables specific MCP targets and/or disposable Python in **Overview → Privacy and data**. Each run also explicitly selects its tools, worker pool and quota. The local arithmetic MCP server requires a project grant and works offline.

## MCP connections and credentials

This qualification supports MCP protocol `2025-11-25`: real initialization, tool discovery and tool calls over the bundled fixed arithmetic stdio server or an operator-installed HTTPS Streamable HTTP endpoint. It does not claim arbitrary/latest MCP interoperability. Sampling, elicitation, roots callbacks, arbitrary stdio commands, redirects, proxies, cookies, embedded URL credentials and consequential tools are unavailable.

`MODELANVIL_MCP_SERVERS` and `MODELANVIL_MCP_SERVER_KEYS` are separate JSON environment maps keyed by `tenantUUID:projectUUID`. An installed target looks like:

```json
{"reviewed-target":{"name":"Reviewed arithmetic","endpoint":"https://operator.example/mcp","allowed_tools":["add"],"credential_id":"arithmetic-reader","read_only":true}}
```

The corresponding scoped key map contains the host credential under `arithmetic-reader`; provision its value outside the repository. Only administrators configure endpoints and reviewed read-only allowlists. Model text and server annotations cannot turn on writes. Project privacy adds a second explicit allowlist; offline mode blocks remote MCP. Invalid/unavailable customer targets leave local arithmetic usable. MCP target IDs are stable within a project and cannot be reused as grants in another project.

Discovery and execution verify the exact catalog digest. Each dispatch rechecks project grants, offline policy and a private keyed configuration signature, including credential rotation. Credentials are sent only to the installed endpoint by the fixed broker. They never enter model inputs or public target metadata. Known credential strings and common encoded forms are scrubbed from server results before model/trace egress. Private transport diagnostics are replaced with fixed errors. A customer server's retention and security still require its own qualification.

The supported JSONSchema subset uses explicit object, array, string, number, integer, boolean or null types, bounded nesting, arrays and strings, and `additionalProperties:false` on objects. References, regex, compositions and unions are refused. At most8 uniquely named functions can be offered. Conflicting MCP tool names require a distinct operator allowlist. Only complete native call blocks containing duplicate-free finite JSON and matching an offered schema can dispatch. Plain prose is never executable.

## Disposable Python

Provision Docker locally and explicitly pull the pinned image before enabling Python:

```sh
docker pull python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
```

Jobs use `--pull=never`. Only the operator's validated local Unix-socket Linux Docker engine with its built-in seccomp profile is accepted; remote Docker engines and ambient Docker credentials/header overrides are refused. The controller verifies the actual container configuration before supplying source.

The root image is read-only, with no host mounts or network, one CPU,128MiB memory/swap,32PIDs, and two16MiB private noexec/nosuid/nodev tmpfs directories. Python runs as UID/GID65534 with no capabilities, no extra groups and no-new-privileges. The trusted PID1 watchdog retains only SETUID, SETGID and KILL so it can drop the child's identity and terminate it. The child has CPU, file-size and descriptor limits. It receives only a fixed minimal environment, never host credentials.

The native `python` function admits a4096-character string within the executor's8192-byte source cap. Each execution is limited to5seconds and16KiB per output stream. No persistent files are returned. Timeout, code error, output ceiling and cancellation produce structured reports; graceful cancellation preserves captured output. The controller waits for removal of its UUID container before releasing CPU admission. Cleanup that cannot be verified makes the execution unqualified.

## Durable automatic API

`GET /api/v1/tools/` reports eligible models, installed targets, grants, sandbox availability and limits. `POST /api/v1/tools/discover/` with `{"target":"UUID"}` performs actual permitted discovery. All requests use normal project authentication and scope headers.

```json
{
  "model":"MODEL_VERSION_UUID",
  "prompt":"Use add to calculate17plus25, then explain the result.",
  "targets":["INSTALLED_TARGET_UUID"],
  "code_execution":false,
  "max_tokens":128,
  "pool":1,
  "budget_policy":"GENERATED_TOKEN_POLICY_UUID",
  "idempotency_key":"unique-request-key"
}
```

Submit this body to `POST /api/v1/tools/jobs/`. Poll `GET /api/v1/tools/jobs/REQUEST_UUID/`, cancel with `POST .../cancel/`, and download the authenticated terminal JSON artifact at `GET .../trace/`. Read access is project scoped; viewer credentials cannot queue, discover or cancel. Generic job APIs cannot create, mutate, delete or cancel typed tool jobs.

The runtime admits at most1536 total prompt/output tokens with no truncation,128 generated tokens per turn,3 model turns,2 total tool calls and3 worker attempts. Invalid/truncated model replies get bounded validation retries and never execute. The quota reserves9times the per-turn output maximum. A started generation receives a durable ceiling charge before computation; verified generated tokens replace that estimate. Lost computation retains its ceiling rather than reporting zero. Reservations survive lease recovery and settle on terminal status.

Calls are committed as started before dispatch. Results are committed before continuation. A lost tool result remains unknown and is not automatically executed again, even for a read-only function. Committed results are reused after a worker lease is recovered. Model, tokenizer, source, code build, worker, budget, grants, catalog and credential identities are checked before the next dispatch/commit. A physical CPU admission descriptor remains held by model/broker/controller children until cleanup. A fake worker success without a complete validated model/tool trace is failed by the trusted finalizer. Failed and cancelled runs retain terminal trace artifacts; partial output is evidence, never a successful final answer.

## Compatible caller-managed completions

`POST /api/v1/inference/chat/completions` accepts native tool fields for this exact model when `tools` or `tool_choice` is present. Other model paths retain their existing strict inputs. Supply an `Idempotency-Key` header and a `budget_policy` extension selecting a generated-token quota.

Supported fields: `model`, `messages`, `tools`, `tool_choice` (`auto`, `none`, `required`), `max_tokens`1–128, `temperature:0`, `stream:false`, and `budget_policy`. Native messages support `assistant.tool_calls` with unique IDs and JSON-string `function.arguments`, followed by matching `tool` messages with `tool_call_id`. All outstanding results must precede continuation. Caller-supplied results are explicitly unverified by the platform.

The200 response uses `choices[].message.tool_calls` and `finish_reason:"tool_calls"`, or a normal assistant answer with `finish_reason:"stop"`; token usage is actual. This endpoint never dispatches caller-defined functions or grants MCP/Python access. The caller executes its own function and supplies the next tool message. Streaming, named forced choices and arbitrary generation controls need separate qualification. Same-key successful replay returns the identical stored response; in-flight or failed same-key requests return409.

Synchronous completions reserve one bounded turn. If the API process is lost, after its hard execution limit run `python manage.py reconcile_tool_completions` to fail requests older than120seconds and settle their admitted ceiling once. Use durable automatic tool jobs for worker lease recovery and cancellation. Keep completed keys for replay; use a fresh key after failure.

## Qualification

Evidence is in `verification/task32-tools-2026-10-24/`. The tested arithmetic is intentionally small: it proves actual model→MCP/Python→model execution, permissions and bounds, not broad reasoning quality. Other models, larger contexts, remote/customer servers, side effects, public multi-tenant hostile-code hosting, OS sandbox alternatives and other accelerators remain unqualified.
