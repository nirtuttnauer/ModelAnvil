# Main integration inventory

23 October 2026 · TASK-61 · Observed main `2bf35ec61fa163c98706b9f5b2452d2385b98739`. Original branches, checkouts and local data remain retained.

The [final branch inventory](verification/task61-final-integration-2026-10-23/branches.json) includes **94 local and remote refs**, including remote-only branches. [Six worktree registrations](verification/task61-final-integration-2026-10-23/worktrees.json) include the original dirty feature-parity checkout and the stale recipes-verification registration. The active inventory branch is observed before this documentation commit; its final PR/head and merge evidence are recorded separately with TASK-61. [Earlier stage inventory](verification/task61-integration-2026-10-23/branches.json) remains historical.

## Scoped deliveries

[The delivery ledger](verification/task61-final-integration-2026-10-23/deliveries.json) maps each scoped PR to its ticket, final head, merge commit and observed checks. Merged partial deliveries remain explicitly partial.

| Scope | Merged delivery / ticket | Evidence boundary |
| --- | --- | --- |
| Guided decision loop, account recovery and screen coherence | PR14/15, TASK-61 | Native-template comparison, single-use reset/revoked sessions, existing privacy/invitation/protected-suite flows preserved. |
| Runpod and custom plugins | PR9, TASK-61 | Actual software reconciliation/CI; no paid provisioning or live provider/GPU qualification. |
| Context-score truth, publisher notices, dependency fixes and Git identity | PR17–20, TASK-63/65/74/75 | TASK-74 optional DiskCache decision remains; TASK-75 supplies a history-rewrite plan only. No rewritten refs were published. |
| Onboarding, activation, privacy, preflight and protected evaluation | PR21–25, TASK-3/44/48/5/6 | Actual bounded CPU/browser/control-plane evidence; customer activation/current GPU qualification separate. |
| PostgreSQL, run history, source import and reviewed-label cycles | PR26–29, TASK-64/8/9/10 | SQL isolation/fencing, current run receipts, immutable source lineage and actual bounded reviewed-label CPU training/evaluation. Draft labels remain imported. |
| Retrieval/PCA, Context Lab, model acquisition, device admission and team access | PR30–34, TASK-11/12/14/42/49 | Actual bounded software/API/browser evidence; no general model, hardware or production qualification. |
| Document ingestion, token-aware chunks and independent export | PR35–37, TASK-62/66/7 | Text/PDF/DOCX/CSV parsing, exact token spans and export consumers. TASK-62 scanned-page OCR publication remains unfinished. |
| Real embeddings, private feedback, token budgets and SQL retrieval | PR38–41, TASK-30/67/53/72/68 | Actual fixed MiniLM vectors/worker builds, private correction provenance, exact budgets, SQL full-text/exact/HNSW/RRF with current access checks. |
| Embedding fine-tuning and public retrieval controls | PR42/43, TASK-30/69 | Actual CPU weight updates/export/reload; closed SciFact subset with declared weak full-text control. No general quality gain inferred. |
| Cited generation, real position sweep and reproducible report | PR44–46, TASK-70/71/73 | Actual fixed local decoder; citation membership/refusal and separate abstention counts; 18 position forwards; source-bound combined report. Main CI/artifact verified on exact `2bf35ec`. |
| Customer discovery preparation | PR16 / TASK-43 remains open | Customer interviews/use-case evidence absent; preparation is not completed discovery. |

## Original uncommitted scopes

The original `codex/modelanvil-feature-parity` checkout remains at `c39a2e9` with **974 dirty/untracked paths**. [The scope map](verification/task61-final-integration-2026-10-23/original-scopes.json) maps each aggregate to ticket owners or explicitly flags it untracked. The full private inventory attached to TASK-61 records every relative path, byte size, SHA256, state and owner mapping; the published aggregate records that inventory's checksum.

- **253 paths** have the same bytes as observed main.
- **150 paths** differ and remain as retained older snapshots; current permission, dependency, identity, schema and integration fixes must not be overwritten with those copies.
- **571 paths** are absent from main, predominantly design sources and historical verification. They are retained and mapped/flagged; their presence does not qualify current runtime behavior.
- **No original runtime source path** under `modelanvil/`, `web/src/`, `scripts/`, `contracts/` or `.github/` is missing from main. Matching paths do not by themselves prove semantic equivalence: the scoped implementations and verification above provide that evidence, while the original snapshots remain recoverable.

The original RAG infrastructure now has separate merged migrations, real embeddings, SQL retrieval, context/generation and report scopes. The original migration numbering was not copied over newer migrations. Local databases, artifacts, raw run directories, model weights and credentials remain outside these documentation commits.

## Retained non-ancestor refs

- `codex/factory-task43-discovery` (`99b229a`, local and remote): PR16/customer-input hold, unfinished.
- `codex/readme-logo` (`426012a`, local and remote): its exact theme-aware README picture block is already present in main; the original commit remains retained.
- Remote-only `origin/codex/modelanvil-brand-integration` (`07fba94`): eight of its eleven changed files, including all brand assets/license, are byte-identical to main. The remaining `web/src/main.tsx`, `premium.css` and `style.css` have newer main versions. This legacy integration ref is flagged as retained overlapping branding, not merged wholesale over current code.

All other inventoried heads are ancestors of observed main. Unmapped historical scopes are explicitly flagged untracked, including already-contained refs; that label does not authorize new implementation.

## Preservation and remaining gates

No owner checkout was reset, cleaned, pruned or archived. Original feature-parity, Runpod/plugin, guide and packaging checkouts remain. The stale registration/directory was not repaired or removed. Only disposable merge checkouts created by this run were removed after their merge was pushed. Aftur's human-only Ready transition was used through native Computer Use to resume this final ticket; no tracker file or authority guard was bypassed.

Current operation-specific scope is recorded in the [supported baseline](supported-capabilities.md), [status ledger](status.md) and [capability evidence](capability-evidence.md). Hardware qualification, customer-input dependencies, current scanned-page OCR, optional dependency remediation and history-rewrite decisions remain unfinished where recorded. Completing this integration inventory does not mark those tickets Done.
