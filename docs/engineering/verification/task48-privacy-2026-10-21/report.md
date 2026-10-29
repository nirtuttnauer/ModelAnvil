# TASK-48 private data policy verification

21 October 2026 · Local implementation ready for review

The [policy contract](../../private-data-policy.md) describes destinations, disclosure, administrator controls, retention, content-free export and deployment limits. Overview exposes these controls before saving a policy. Shipped source acquisition checks installation and project policy before requests and redirects, strips cross-origin credentials, disables ambient credentials/cookies and refuses content uploads. External judges, generation, analytics and support uploads remain unavailable.

The additive `core.0006_private_data_policy` and `rag.0003_private_data_policy` migrations were applied to the running local SQLite installation after a private backup. New knowledge bases become project-scoped. Existing tenant-shared knowledge bases retain their historical scope and require an operator ownership review. No existing content was reassigned or purged.

## Verification

| Check | Result |
| --- | --- |
| Broad backend regression | 909 tests passed, 9 skipped. This run preceded the final SDK cookie/scope and fresh retrieval-state hardening. |
| Initial focused regression | 66 tests passed across privacy, acquisition, model workspace, annotation and retrieval. |
| Updated privacy and provisioned transformer | 8 tests passed, including shared-session scope/cookie checks and actual tiny Safetensors inference with socket connections refused. |
| Final policy and retrieval regression | 17 tests passed after adding fresh index-state revalidation; the final combined policy/retrieval/comparison run passed 18 tests. |
| Saved comparison regression | Actual paired model responses, cross-project concealment and model-grant revocation checked after the broad run; the final run also denies creation retries after revocation; see `final-policy-tests.txt`. |
| Frontend regression and production build | 225 tests passed; TypeScript/Vite build passed. |
| System, migration and contract checks | Django checks passed; no migration drift; canonical and engineering OpenAPI copies match. |
| Mechanical design check | No findings on the changed UI targets. |

The [check summary](checks.json) identifies these scopes. Negative checks cover destination revocation, blocked redirects, cross-origin credential removal, unsupported external purposes, uploads, lost SDK scope, cross-project policy access, revoked retrieval and comparison access. Existing backend regressions also cover annotation project boundaries and expired/revoked artifact-worker grants. Diagnostic tests insert private sentinel text/credentials and confirm they are absent from exports and formatted logs. Expired-measurement deletion requires confirmation and leaves another project's records intact.

The [browser record](browser-checks.json) uses a disposable database, real loopback API and executed CPU fixture. Keyboard disclosure, saving offline mode and seven-day retention, reload persistence, desktop and 390-pixel layouts passed. No horizontal overflow or console errors was observed. The attached screenshots show the settings form. Only synthetic disposable policy was changed during browser verification.

## Offline execution evidence

The [offline baseline](offline-baseline.json) creates a new database/artifact root and runs actual CPU reference training, durable candidate/baseline evaluation, authenticated chat and an explicit rejection. Both Python socket connection entry points are refused throughout the journey. It records **zero outbound connection attempts**, two committed updates, one evaluation case, exact artifact pins, source digest and physical hardware. Reproduce with:

```sh
.venv/bin/python scripts/measure_private_baseline.py \
  --output /absolute/path/offline-baseline.json
```

The observed run took approximately 3.37 seconds on an Apple M5 Pro with 48 GiB RAM, using already installed dependencies and initialized local reference weights. Installation, download and human onboarding times remain unknown. A separate test loads a provisioned tiny transformer and generates actual output with socket connections refused.

This is local CPU execution evidence, not an OS firewall test, GPU qualification, useful-model benchmark or remote PostgreSQL/S3/broker/private-worker air-gap qualification. Arbitrary trusted plugins and operator infrastructure are outside the transport guard. Already-open transfers are not cancelled when policy changes. Raw third-party process/proxy logging requires operator configuration. Product history and backup retention remain explicit operator responsibilities; the measurement retention setting alone does not schedule deletion.

TASK-48 is ready for human outcome review. TASK-49 remains dependency-gated on its acceptance. TASK-43 can prepare discovery materials independently, but real interviews, observed workflows and willing partners cannot be produced by implementation tests.
