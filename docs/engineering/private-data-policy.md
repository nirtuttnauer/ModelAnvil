# Private data policy

21 October 2026 · TASK-48 · Local implementation, pending review

The shipped training, evaluation and chat runtimes process content on the configured execution host. External model judges, synthetic generation, analytics and support uploads are unavailable. This policy controls the shipped acquisition transports; it is not an operating-system firewall or a sandbox for arbitrary trusted Python plugins. Remote databases, brokers, artifact stores and registered workers still require the operator's separate deployment and residency controls.

## Destinations and permissions

Overview → **Privacy and data** shows the current project policy, the complete installation-approved acquisition origins, what requests can disclose, and interaction-measurement retention. An authenticated project viewer can inspect the policy and download content-free diagnostics. An administrator can tighten the destination list, select offline operation and change retention. Project settings cannot override installation restrictions. Policy changes are audited with flags and counts, without credentials or URLs.

| Operation | Destination and scope |
| --- | --- |
| Model search, inspection and file acquisition | Exact HTTPS origins approved by the installation owner and permitted by the project. Requests can disclose a search, repository/source URL and intentionally configured source credentials. Only GET/HEAD without a body is allowed. |
| Dataset bank, repository and web acquisition | The same origin and offline checks apply to shipped HTTP transports. A new source host requires installation approval before project approval. |
| Bundled public-model provisioning | Requires explicit `MODELANVIL_PUBLIC_MODEL_DOWNLOADS=1` by the installation owner; existing provisioned files remain usable without it. |
| Training, evaluation, chat and retrieval | Provisioned local runtimes have no external content-processing service. A missing model is an actionable provisioning failure rather than permission to enable a hosted model. |
| Model judges, synthetic generation, external analytics, support upload | Unavailable; policy requests for these purposes fail. No content-collection switch is offered. |
| Diagnostic export | Downloaded to the requesting viewer's browser. Contains build identity, effective policy and job counts by status. No prompt, response, sample, upload, credential, raw log, audit body or free-form job error is collected. |

The default installation acquisition list is `https://huggingface.co`, `https://cdn-lfs.huggingface.co`, `https://cdn-lfs-us-1.hf.co`, `https://cas-bridge.xethub.hf.co`, `https://cdn-lfs.hf.co`, `https://api.github.com`, `https://raw.githubusercontent.com`, `https://github.com` and `https://archive.ics.uci.edu`. Projects without a saved policy inherit this list. Initial public catalogue reads retain this compatibility policy; content processing is never implicitly enabled. Review and restrict it before private use.

Set `MODELANVIL_ACQUISITION_ORIGINS` to a comma-separated exact-origin subset or an explicitly reviewed replacement. An empty value permits no source hosts. `MODELANVIL_OFFLINE=1` prevents shipped acquisition for every project, including provisioning. Per-project offline mode prevents its acquisitions. Disabling acquisition does not remove already acquired files.

Every redirect is checked against the effective policy, and credentials are stripped on a change of origin. Ambient proxy/netrc credentials and SDK cookies are disabled. The Hugging Face SDK uses the guarded transport; native Xet transfer and Hub telemetry are disabled. Shared SDK sessions recheck current scope and restrictions before each request and refuse lost scope. Already-started responses are not retroactively cancelled; updated restrictions apply to subsequent requests. HTTP is accepted only for loopback development with Django DEBUG enabled. Custom transports supplied by trusted code remain the operator's responsibility.

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

See the [verification report](verification/task48-privacy-2026-10-21/report.md) for executable offline evidence, permission checks and unqualified deployment boundaries.
