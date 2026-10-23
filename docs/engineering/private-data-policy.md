# Private data policy

23 October 2026 · TASK-48 · Local implementation

The shipped training, evaluation and chat runtimes process content on the configured execution host. Optional external chat is disabled by default and requires both a scoped operator target/credential and explicit administrator approval in Privacy settings. Chat shows the selected destination before sending conversation content. External model judges, synthetic dataset generation, analytics and support uploads are unavailable. This policy controls the shipped acquisition transports; it is not an operating-system firewall or a sandbox for arbitrary trusted Python plugins. Remote databases, brokers, artifact stores and registered workers still require the operator's separate deployment and residency controls.

## Destinations and permissions

Overview → **Privacy and data** shows the current project policy, the complete installation-approved acquisition origins, what requests can disclose, and interaction-measurement retention. An authenticated project viewer can inspect the policy and download content-free diagnostics. An administrator can tighten the destination list, select offline operation and change retention. Project settings cannot override installation restrictions. Policy changes are audited with flags and counts, without credentials or URLs.

| Operation | Destination and scope |
| --- | --- |
| Model search, inspection and file acquisition | Exact HTTPS origins approved by the installation owner and permitted by the project. Requests can disclose a search, repository/source URL and intentionally configured source credentials. Only GET/HEAD without a body is allowed. |
| Dataset bank, repository and web acquisition | The same origin and offline checks apply to shipped HTTP transports. A new source host requires installation approval before project approval. |
| Bundled public-model provisioning | Requires explicit `MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1` by the installation owner; existing provisioned files remain usable without it. |
| Training, evaluation and retrieval | Provisioned runtimes process content on their configured execution host. Missing models do not automatically enable external processing. |
| Optional external chat | Only exact installed endpoint/model/credential targets explicitly approved by the project administrator and selected in Chat. Sends the system prompt and selected conversation history; provider retention and charges apply. Disabled by default and by installation/project offline mode. Credentials stay on the API host. |
| Model judges, synthetic generation, external analytics, support upload | Unavailable; policy requests for these purposes fail. No content-collection switch is offered. |
| Diagnostic export | Downloaded to the requesting viewer's browser. Contains build identity, effective policy and job counts by status. No prompt, response, sample, upload, credential, raw log, audit body or free-form job error is collected. |

The default installation acquisition list is `https://huggingface.co`, `https://cdn-lfs.huggingface.co`, `https://cdn-lfs-us-1.hf.co`, `https://cas-bridge.xethub.hf.co`, `https://cdn-lfs.hf.co`, `https://api.github.com`, `https://raw.githubusercontent.com`, `https://github.com` and `https://archive.ics.uci.edu`. Projects without a saved policy inherit this list. Initial public catalogue reads retain this compatibility policy; content processing is never implicitly enabled. Review and restrict it before private use.

Set `MODELANVIL_ACQUISITION_ORIGINS` to a comma-separated exact-origin subset or an explicitly reviewed replacement. An empty value permits no source hosts. `MODELANVIL_OFFLINE=1` prevents shipped acquisition and optional external chat for every project, including provisioning. Per-project offline mode prevents its acquisitions. Disabling acquisition does not remove already acquired files.

Every redirect is checked against the effective policy, and credentials are stripped on a change of origin. Ambient proxy/netrc credentials and SDK cookies are disabled. The pinned Hugging Face 1.x SDK uses a guarded HTTPX client with request and redirect checks; native Xet transfer and Hub telemetry are disabled. Shared SDK sessions recheck current scope and restrictions before each request and refuse lost scope. Already-started responses are not retroactively cancelled; updated restrictions apply to subsequent requests. HTTP is accepted only for loopback development with Django DEBUG enabled. Custom transports supplied by trusted code remain the operator's responsibility.

## Collection, retention and deletion

Local interaction measurements contain only fixed event/session/project identities, event kind and approximate active milliseconds. There is no free-form metadata field or external analytics sink. The retention period is 1–365 days, default 30. Expiry makes measurements eligible for explicit administrator/operator deletion; it does not promise a scheduled cleanup process.

The project administrator can POST exactly `{"confirm":"delete_expired_measurements"}` to `/api/v1/privacy/purge-measurements/` after reviewing the current period. The operator command below previews all eligible measurements. Adding `--apply` explicitly deletes them:

```sh
.venv/bin/python manage.py purge_expired_measurements
```

Prompts, conversations, uploaded datasets, artifacts, annotations, comparisons and durable improvement decisions are intentional product records, separate from diagnostic collection. Existing authorized APIs govern their export, mutation and deletion. Records protected by lineage/integrity constraints require their supported lifecycle; this ticket does not add a blanket content purge. Saved decisions remain after interaction measurements expire. Backups and downloaded exports are under operator/recipient retention control. No diagnostic bundle is retained by the export endpoint, and responses use `Cache-Control: no-store`.

Default structured application and Django request/server logs omit message arguments, raw exception text, tracebacks, URLs and request bodies. They retain severity, logger, timestamps, validated identities, HTTP status and exception class. Inbound request IDs must be UUIDs. This deliberately reduces free-form debugging detail. Third-party process output, reverse-proxy access logs and custom operator handlers need their own configuration; they are excluded from the diagnostic export.

## Project isolation and revocation

New knowledge bases inherit the selected project. Index APIs filter through current knowledge-base permissions. An existing retrieval engine rechecks the current index state, current knowledge-base grant, source revocation and deletion tombstones before retrieving chunks; cached engine construction cannot preserve a revoked permission. Saved comparisons also require current access to both model versions. Existing annotation, artifact-download and worker-grant isolation controls remain in effect.

The additive migration preserves existing knowledge bases with no project as tenant-shared. It does not guess their owner or silently transfer their content. Operators must review those legacy records before a private-project rollout. This compatibility boundary is material: legacy tenant-shared content is not newly isolated by this migration.

See the [verification report](verification/task48-privacy-2026-10-23/report.md) for executable offline evidence, permission checks and unqualified deployment boundaries.

## Optional compatible chat providers

The operator supplies `MODELANVIL_EXTERNAL_PROVIDERS` as a JSON object keyed by `tenant UUID:project UUID`, with up to 16 named targets per project. Each target contains exactly `name`, `endpoint`, `model` and `credential_id`. The separate `MODELANVIL_EXTERNAL_PROVIDER_KEYS` setting maps the same scope and credential ID to its Bearer secret; it is never returned by APIs, diagnostics or saved conversations. The setting name is recognized as secret by Django's error-reporting filter. No ambient environment proxy, netrc credential, cookie or cross-project credential fallback is used.

Example public target (substitute actual tenant/project UUIDs):

```json
{"TENANT_UUID:PROJECT_UUID":{"reference":{"name":"Team reference","endpoint":"https://provider.example/v1/chat/completions","model":"explicit-model-revision","credential_id":"team-reference"}}}
```

The corresponding secret mapping has the same scope and `team-reference` key. Provision it through the deployment's secret environment mechanism. HTTPS is required, with no embedded credential, query or fragment; literal loopback HTTP is permitted only with DEBUG for local qualification. Browser/API callers cannot supply arbitrary endpoints or keys. Configure another target to select a different endpoint/model/credential combination.

Overview → Privacy and data lists the public installed targets for this project. A project administrator explicitly enables target UUIDs; default approval is empty. Acquisition approval never enables external generation. Chat lists only enabled targets, shows endpoint/model/credential ID before Send, and uses the provider's native template. The operator and project restrictions are rechecked before connection and before each published event. Revoking the API key, role, project target, offline flag or credential/configuration stops subsequent publication and closes the upstream response; already sent content cannot be recalled from the provider.

Only bounded text completion is supported: at most 256 output tokens requested, 32,000 input/output characters, one response, a 256 KiB upstream stream envelope, 64 KiB per buffered event, 10-second socket timeout and a 30-second read-loop deadline. Redirects are refused, including same-host redirects. Unsupported tools, changed reported model identity, malformed usage and incomplete streams fail closed; upstream error bodies are withheld. Cancellation closes the response. Missing token usage remains unavailable; provider-reported counts and model names are recorded as reported, without independent token/weight verification or invented billing amounts. An upstream read can remain blocked for its socket timeout after the read-loop deadline.

External arena comparisons persist the exact public target snapshot, requested/reported model identifiers, inputs, settings, output digests, usage and latency. A provider selector or reported model name does not establish immutable upstream weights. Votes are informal product preferences. External pairs cannot enter the local model review workflow, independent held-out evaluation or release qualification through an arena vote. The actual Mac transport proof uses a self-hosted compatible endpoint on loopback; it makes no third-party provider, network residency or production claim.

## Optional inference replay cache

`Idempotency-Key` opts a completion into a scoped durable replay cache containing its generated response, original request ID and measured usage. It stores no raw input prompt. Normal inference records continue to retain input/output digests and usage rather than text. Completed retries for seven days return the original output and usage after current access checks, without another generation or ledger charge. Incomplete/failed requests never become successful cached output. The replay window does not promise automatic physical deletion: expired completed bodies are removed on key reuse or by `purge_expired_inference_replays --apply` (preview without the flag). Pending interrupted-key metadata and ordinary product/measurement history have their existing retention. Requests without a key do not opt into output caching.
