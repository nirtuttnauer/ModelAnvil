# TASK-61 final integration inventory

23 October 2026 · Documentation-only completion of the integration gate, after the scoped runtime implementations landed.

## Observed baseline and deliveries

The inventory observes main `2bf35ec61fa163c98706b9f5b2452d2385b98739` (PR46). It deliberately records a fixed observation, rather than rewriting old branch heads to the future hash of this report's own commit. The final documentation PR/head and its merge/CI receipts are attached separately to TASK-61.

- [Branches](branches.json): 94 local/remote refs, with exact heads, ancestry, ticket mappings or explicit untracked flags, including remote-only branding work.
- [Worktrees](worktrees.json): six retained registrations, including the missing recipes checkout's stale registration; no original checkout was removed.
- [Original scopes](original-scopes.json): all 974 original dirty/untracked paths grouped by ticket or explicitly untracked scope. The full per-path private inventory records SHA256/size/state/owners and has SHA256 `814c780c768e8e5c3da201a0ace66dae1502cb79040e7b667a9f55b1df6bfa10`; it is attached to TASK-61. The original checkout remains at `c39a2e9554efdd6c5c644fb012580298f4bc78ca`.
- [Deliveries](deliveries.json): 33 merged scoped PRs, all targeting main, each with successful observed final-head checks. PR19/20/35 remain partial task deliveries; merging them did not complete TASK-74/75/62. PR16/customer discovery remains open.

Original dirty paths comprise 253 byte-identical files, 150 retained differing files and 571 retained paths absent from main. No original runtime source path under `modelanvil/`, `web/src/`, `scripts/`, `contracts/` or `.github/` is absent. Path/byte comparisons are inventory evidence, not a semantic equivalence test: individual implementation reports and CI establish the scoped runtime behavior. Retained differing snapshots are not copied over newer permission/schema/runtime changes.

The non-ancestor branding refs are explicitly reconciled: the original README logo picture block is present in main; eight of the eleven remote-only branding files are byte-identical, and three old app/style files overlap newer main versions. Customer discovery is a separate held scope. No owner branch/ref is deleted. No original database, model cache, raw run directory, artifact store or design source is committed by this report.

## Current documentation and evidence

[README](../../../../README.md), [status](../../status.md), [capability evidence](../../capability-evidence.md), [supported capabilities](../../supported-capabilities.md) and [integration inventory](../../integration-inventory.md) now describe the merged bounded CPU/control-plane, embedding/retrieval, reviewed-label, export and actual generation/context paths. Historical audits remain clearly dated. The machine-readable capability baseline retains its archived snapshots/checksums; its old entries are not silently expanded to new operations.

The source-bound RAG measurement remains `04916ee723f894ab0b3cec50b2ccc43596bceae0`; its report-generated README table is unchanged. Exact merged main `2bf35ec61fa163c98706b9f5b2452d2385b98739` passed backend/frontend/pgvector in [CI run 39925859135](https://github.com/nirtuttnauer/ModelAnvil/actions/runs/39925859135). Its [matching combined report artifact](https://github.com/nirtuttnauer/ModelAnvil/actions/runs/39925859135/artifacts/12489890930) was independently downloaded and verified: ZIP SHA256 `19559448d2556b81f1cf09e5351b23f8209a3790632d2dd72c2422ee172742c5`, raw report SHA256 `391d57d503abe16121134c76d074fbc0600590403297e1c2172c4dcf653552e1`. External receipts are durably attached to TASK-73. This qualifies the named bounded CPU software/reference reproduction, not customer, GPU or production outcomes.

## Verification and limits

Documentation verification: all new JSON parses; local Markdown file links in the changed documents resolve; inventory counts, SHA256 and complete per-path coverage agree; every delivery is merged to main with successful final-head checks; `python3 scripts/rag_report.py --check-readme` and `git diff --check` pass. The documentation PR must additionally pass every current CI job on its final head before merge. Its checks and final merge are recorded in Aftur; this static report does not predict their results.

No new local runtime test is claimed for documentation-only edits. The preceding integrated-code evidence records 1,041 backend tests with five optional skips, 23 actual PostgreSQL/model/broker checks and 226 frontend tests plus production/Storybook builds. The required CI rerun is the final integration gate.

Hardware/current OCR qualification, customer discovery and downstream customer-input dependencies, optional dependency remediation and history-rewrite decisions remain unfinished where recorded. This inventory completes integration of the authorized available implementation; it does not waive those separate criteria. TASK-75 remains a plan only, with no history rewrite or force push. The native human-only Ready transition was performed through authorized Computer Use; tracker authority checks remained intact.
