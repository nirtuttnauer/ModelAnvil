# Main integration inventory

23 October 2026 · TASK-61 · Branches, checkouts and original work are retained.

The [branch inventory](verification/task61-integration-2026-10-23/branches.json) records exact committed heads and whether they were already in main at observation time. Main contains the former feature-parity base `c39a2e9`; merging that old committed branch again would not deliver its uncommitted work. The original checkout is preserved. The full local path/hash/status inventory is saved with the Aftur ticket evidence, without publishing databases, artifacts, credentials or model weights.

## Scoped deliveries and remaining work

| Scope | Integration / ticket | Qualification boundary |
| --- | --- | --- |
| Foundational feature-parity commits, public project guide and production packaging | Committed heads are already ancestors of main; clean documentation/packaging checkouts retained | Production and hardware claims remain operation-specific. |
| Guided decision loop and account recovery | PR14 merged; reset tokens are single-use, prior sessions revoked, native-template comparison retained | No new GPU/customer quality claim. |
| Context-score truth and publisher contact cleanup | PR17/18 merged, TASK-63/65 complete | Measured execution and publisher licensing provenance retained. |
| Dependency upgrade and Git identity | PR19/20 merged; TASK-74/75 retain their explicit outstanding decisions | Optional DiskCache advisory lacks a fixed upstream release; history rewrite is a plan only. |
| Fresh onboarding, activation, privacy, preflight and protected evaluation | PR21–25 merged, TASK-3/44/48/5/6 delivered | Local CPU/browser evidence; human activation, current GPU qualification and legacy tenant-shared KB ownership remain separately documented. |
| Screen coherence | PR15 reconciled with current main, retaining decision/invitation/privacy flows and protected suite versioning | Legacy routes, linked tab panels, keyboard navigation and 1440/390 layouts checked. |
| Runpod and custom plugins | PR9 reconciled against current main; [fresh software review](verification/task61-runpod-2026-10-23/report.md) and final-head CI govern integration | No paid resource provisioned; named GPU/provider qualification is not inferred. |
| RAG infrastructure and retrieval changes in the original checkout | TASK-64/66/67/68/69/70 and later RAG report tickets | Isolated from the UI merge; process in factory dependency order, including Postgres qualification. |
| Customer discovery preparation | PR16 / TASK-43 | Research remains blocked on customer input. Preparation is not completed discovery. |
| Design sources and historical verification | Retained in the original checkout, with individual paths/hashes in private Aftur inventory | Untracked design snapshots and historical reports are not runtime qualification or disposable data. |

The RAG scope includes the separate PostgreSQL CI runner, vector extension migration, embedding runtime and SQL retrieval tests, plus their associated settings/compose/schema changes. Older copies of privacy, account, dependency and evaluation files differ from newer merged fixes; do not copy the old checkout wholesale over main. Preserve fresh permission, native-template, credential and dependency protections when reconciling them.

## Checkout retention

- Original feature-parity checkout: retained with its uncommitted scopes and local data.
- Managed integration checkout: retained for scoped implementation and final verification.
- Runpod/plugin checkout: retained on its original branch.
- Public-guide and production-packaging checkouts: clean and their committed heads are in main; retained pending owner cleanup.
- A stale recipes-verification registration points at a directory that is no longer a Git checkout. Its directory and registration were left intact.

No owner checkout was reset, cleaned, pruned or archived. Disposable merge checkouts created for this run were removed only after their merge commit was pushed. No local database, raw run output, model weights, session cookie or worker credential is included in these commits.

The [supported capability index](supported-capabilities.md) governs present execution claims; the dated status/audit documents preserve their historical reviews. This inventory is updated as remaining scoped PRs land. A merged integration stage does not mark hardware or customer blockers complete.
