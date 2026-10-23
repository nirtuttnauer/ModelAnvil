# TASK-53 private application feedback — 23 October 2026

Authorized development observations can now enter the existing Annotation correction and immutable training-data flow. Collection defaults to disabled/metadata only. Both project opt-in and per-event consent are required before a failure's prompt and original prediction are stored. There is no application polling, external telemetry or automatic training/release.

## Actual application-to-review evidence

The owned local browser application called the actual CPU inference API for the previously worker-trained candidate `01a16619-a78e-7c9e-b72f-73791977e9fa`. The control prompt `baaa` generated EOS token `2`, with an empty decoded completion. The browser then imported this exact observed response with application/model versions, stable event identity, pseudonymous source/group, rubric and explicit authorization/consent.

The resulting one-task campaign retained the original empty prediction and pinned model version. The QA owner session supplied correction `a` through the normal review UI and closed the reviewed batch. A new immutable prepared training revision contained the original prompt plus reviewed correction, with its source group preserved. The failed prediction remained in review history and did not enter the training text. Reload reopened the published snapshot.

This is an intentionally failing development control and a software workflow qualification. The browser-authored reviewer action is not an independent customer/human quality assessment. No model was trained from these feedback snapshots, no improvement was asserted and no deployment or GPU/provider job was launched.

The first owned receipt `01a16706-1739-72a1-9931-41ab9fb29eb3` opened campaign `01a16706-173a-7a08-bec4-70ca04089848` and published dataset revision `01a16706-18ac-7f5a-81a6-54339b5edcb0`. The confirmation exercised the second owned receipt's review/publication too. Both were then deleted through the UI: their owned source download and campaign APIs returned 404. The actual data/artifact cleanup affected only these newly owned feedback fixtures. Existing model weights, original QA datasets and unrelated campaigns were retained. Feedback/content collection were restored to disabled; project offline/privacy settings were preserved.

- [Browser receipt and actual token outcome](browser-report.json)
- [Deletion, draft privacy and restored settings](browser-confirmation.json)
- [Feedback desktop](feedback-desktop.png), [feedback mobile](feedback-mobile.png)
- [Private correction desktop](private-review-desktop.png), [private correction mobile](private-review-mobile.png)

One desktop/mobile inspection batch and one confirmation batch ran at 1440/390 pixels with no horizontal overflow or browser errors. Confirmation verified private review drafts have no session-storage backup and the failed original prediction cannot be accepted unchanged. Import content also stays out of browser draft storage. A successful submit clears the import content fields.

## Guardrails exercised

- Disabled/default metadata-only collection, project opt-in, per-event consent, authorization and content-size bounds; optional empty actual model outputs.
- Stable application event retries return one receipt/campaign. Conflicting retries are refused. Cross-project model/receipt access and reviewer policy/ingestion writes are denied.
- The ordinary Annotation revision/conflict/reviewer checks preserve original predictions. Only independently corrected failures publish into a new immutable prepared training revision; rejected/skipped cases do not enter it.
- Known protected suite groups/prompts and declared final-test groups cannot be relabeled into development training under another event ID. Inspected group/prompt fingerprints prevent later clean-test registration, including after content deletion. Source-group namespaces respect selected-project/resource-grant access; unrelated private projects can reuse their own names without revealing or blocking each other.
- Linked development cases become inspected and then training-feedback cases. Existing protected registration endpoints reject a new misleading clean-test claim.
- Actual PostgreSQL concurrency checks proved duplicate imports produce one candidate, and competing feedback inspection/clean-test registration cannot both commit.
- Retention cannot exceed Privacy, shortening applies to existing events, and increasing it does not extend them. Expiry hides review/history/snapshots and refuses source artifact, worker-grant and training reads before physical purge.
- Deletion clears owned review/correction/rubric/snapshot content and tombstones/deletes its source and manifest objects. A second registry row for the same object cannot shed expiry; generic artifact mutation cannot remove or forge feedback provenance. Simulated storage failure retained a pending-cleanup flag, kept reads refused, and a subsequent cleanup successfully retried deletion.

## Validation

The branch was reconciled normally with main after embedding foundation PR38 merged. Full backend verification passed 1,020 tests with six optional skips after that integration; the final source-scope/artifact-provenance refinements were then covered by 107 focused checks in the clean base runtime (two optional CPU-package skips). All 14 required Postgres checks passed with the actual embedding model and RabbitMQ, including the two new feedback concurrency checks. The complete final feedback suite also passed all 13 checks on PostgreSQL, covering scope namespaces, content bounds, expiry, erasure retries and provenance guards. Frontend 226 tests, production build, Storybook build and migration drift checks passed.

The full run first caught an invalid evaluation-source-identity regression in the new inspection guard. Validation now precedes fingerprinting; the affected local-ML suite and final focused checks pass. This finding was repaired rather than waived. Required final-head CI remains the merge gate.

See [policy, API, scope and operator retention details](../../private-application-feedback.md). Physical retention requires periodically running `purge_application_feedback`; reads fail closed immediately on expiry even before that command runs. Minimal idempotency/leakage fingerprints remain after erasure. Already exported copies and previously trained weights have their own lifecycle; this deletion covers owned review and training source artifacts.
