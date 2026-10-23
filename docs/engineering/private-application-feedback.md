# Private application feedback

Application feedback imports authorized, versioned development observations into the existing Annotation review and dataset publication flow. It neither polls applications nor enables telemetry. Collection is disabled by default in every project. Even after enabling collection, an event is metadata only unless the administrator enables content and its caller explicitly attests consent for that event.

## Configure and import

In Annotation, open **Private application feedback → Feedback collection and retention** as an organization administrator. Enable collection and choose retention within the project's Privacy limit. Content collection has a separate opt-in. Shortening either retention setting also shortens existing receipts; increasing it never extends them. The effective default is the project's measurement retention period, normally 30 days.

An engineer or authorized scoped application key can use the form or POST `/api/v1/application-feedback/` with `X-Project-ID`. Supply the original application/model versions, a stable application event ID, pseudonymous source ID and related source group, rubric, observed verdict and original evaluation role. The caller must confirm authorization. Model versions and optional linked evaluation cases must be accessible in the selected project.

```json
{
  "application": "private-helpdesk",
  "application_version": "2026.10",
  "event_id": "stable-feedback-event-17",
  "model_version": "REPLACE_WITH_ACCESSIBLE_MODEL_VERSION_UUID",
  "source_id": "pseudonymous-source-17",
  "source_group_id": "related-development-group-9",
  "rubric": "Answer the development request accurately.",
  "verdict": "failure",
  "evaluation_role": "development",
  "authorized": true
}
```

This minimal event collects no prompt or prediction. To open a correction review with source content, additionally provide `content_consent: true` and `content: {"prompt": "...", "prediction": "..."}` after both project opt-ins. Only observed development failures collect content. Each string supports at most 16,000 characters and the combined content at most 32 KiB. An empty actual model prediction is valid failure evidence. Use a new event ID for a separately consented observation; changing an already recorded event conflicts rather than silently rewriting it.

Identical application/event retries return the existing receipt and create no duplicate review task. The receipt freezes request identity, source/group identity, original model version, authorization/consent principal and expiry. Content is stored only in its owned review task, never audit snapshots or diagnostic output. Feedback lists do not echo prompt/prediction content. No hosted judge, external analytics or automatic generation is invoked.

An optional `evaluation_suite` UUID plus `evaluation_case_id` links an existing development case. Its source group and original prompt must match exactly. Protected/final-test content, its related groups and equivalent known protected prompts cannot enter a development feedback candidate. A declared final-test group also remains protected against later attempts to relabel it under a different event ID.

## Review and publish

A consented failure opens one project-scoped text-response Annotation campaign and one review task with its original prediction/model version intact. **Review application correction** opens that task. Reviewers use the ordinary independent review, conflict detection, adjudication and immutable batch snapshot path. Accepting the failed prediction unchanged is unavailable: only an independently supplied correction can enter training. Rejected/skipped records are excluded.

Closing the reviewed batch publishes a new immutable prepared dataset, with the original source group and feedback provenance. Its training text contains the original prompt and approved correction; the failed prediction remains in review history and does not enter the training text. Existing Training handoffs can consume the resulting revision. This ticket does not automatically launch training, replace a model, claim improvement or enable a release.

The feedback role becomes `development_inspected`, then `training_feedback_inspected` when publication succeeds. A linked development suite is recategorized too, invalidating any prior assumption that its case remains uninspected. Within the selected project and its explicit resource grants, clean protected-suite registration checks persistent group and normalized prompt fingerprints, including metadata observations and deleted receipts. Unrelated private projects can reuse their own group names without revealing or blocking one another. A tenant row lock serializes feedback inspection against protected-suite registration; concurrent operations cannot both succeed. Unknown/non-development suite roles are treated as protected by the feedback gate.

Import fields and application-feedback review drafts stay in tab memory rather than browser session backups. Other product drafts retain their existing behavior. Browser copies or exports already made by an authorized person cannot be recalled.

## Expiry and deletion

The qualified publication path uses unversioned local artifact storage. Other storage backends require separate qualification.

Expiry immediately redacts receipt identifying fields and hides its campaign, tasks, history and snapshots from product APIs. Source/manifest artifact reads, worker grants and training input reads fail closed after expiry, deletion or a newly protected source. An alternate artifact registry row pointing at the same object cannot shed the original feedback provenance or expiry. Server-owned feedback artifact provenance is immutable through generic artifact updates.

Administrators can delete one receipt or erase expired feedback in the UI/API. Erasure clears its owned task content, original/corrected review text, rubric and snapshot items; tombstones its published input and prepared manifest; and physically deletes those local/storage objects after the database commit. Historical dataset identities and hashes remain immutable and unavailable for further training. The original application/model records and unrelated campaigns are retained.

Storage failure leaves an explicit `cleanup_pending` receipt. Reads remain refused. Expired-feedback cleanup retries pending physical deletion, including already deleted receipts; successful retry clears the flag. Do not rely on UI visits to run physical retention. Configure the operator to run this command periodically, for example hourly, in the same environment/database/storage as the API:

```sh
python manage.py purge_application_feedback
```

The command erases expired feedback across the installation and retries pending storage erasure. Run it only as the trusted installation operator. The API equivalent is an administrator POST to `/api/v1/application-feedback/purge/` with `{"confirm":"delete_expired_feedback"}` in a selected project.

Minimal receipt/request/group/prompt fingerprints and deletion time are retained for idempotency and leakage prevention. Already exported external copies and previously trained model weights have their own lifecycle; deletion erases this receipt's owned review and training **source artifacts**. It does not retroactively untrain a model. Current input/evidence checks refuse the deleted source for new work.

See the [dated verification report](verification/task53-private-feedback-2026-10-23/report.md) for actual CPU inference, browser review/publication/deletion and concurrency evidence.
