# TASK-10 bounded reviewed-label training and qualification

23 October 2026. The prior API handled review and immutable snapshot publication, but its candidate-training and qualification helpers only simulated execution. The opt-in cycle now connects reviewed labels to actual fenced CPU character training and independent protected evaluation. Existing manual workflows and original agent checkouts are retained.

## Delivered behavior

A campaign pins a published source, baseline model, runner, pools, training-step and evaluation-case budgets, per-cycle steps, campaign caps, protected suite/scorer digest, accuracy threshold and draft prompt. Evaluation source groups and sample references are reserved before the first review batch. Each batch pins its model, prompt and rubric; original predictions and human review revisions remain separate. Draft predictions remain imported, not synthesized by a heuristic.

Closing a fully reviewed and adjudicated batch atomically publishes its approved cumulative snapshot and queues at most one training execution through the same validated admission as ordinary training. Repeated closure returns the same snapshot/run. A failed admission rolls back closure and dispatch while retaining the saved reviews.

After training, **Check cycle and advance** queues the independent evaluation; a subsequent check records promotion or rejection. Queueing and repeated advancement are idempotent. Promotion requires complete actual evaluation, the configured accuracy threshold, a score at least equal to the baseline, unchanged suite and current model assignment, and current resource access. Failed, incomplete or worse candidates retain the prior drafting model. The next review batch waits for a recorded decision or explicit rollback.

Pause/cancel blocks future stages and requests cancellation of active jobs; a running job remains unacknowledged until the worker stops. Queued jobs finalize cancellation and settle zero work. Rollback changes future assignment to the original baseline or a previously promoted campaign model while retaining labels, runs and decisions. Declared cycle/step/case caps and ordinary budget admission stop further dispatch. Quantity limits do not establish a currency cost ceiling; this unpriced CPU workflow explicitly uses quantity budgets with a zero *declared* dollar ceiling, without claiming free execution.

The UI exposes the optional configuration, explicit advancement, pause/cancel, baseline restoration and links to both execution records. Canonical OpenAPI copies describe the configuration, transitions, pinned batch data and snapshot links.

## Fresh verification

- Twelve SQLite cycle tests and a PostgreSQL concurrent-closure test cover two real CPU training/evaluation cycles, protected-group exclusion, prompt whitespace, repeat-safe closure/advancement, immutable labels, budget rollback, current suite pin checks, failed gates, controlled regression rejection, rollback, step/case caps, viewer denial and running cancellation acknowledgement. Together with existing annotation/API/preflight tests: **43 pass**, plus the PostgreSQL closure/pgvector checks.
- Full optional-runtime backend suite: **959 tests, six optional skips**, passed before the final prompt-preservation and pending-rollback regressions; final targeted tests cover those changes. Frontend: **226 tests**, production build and Storybook build pass. Final-head CI gates merging, including PostgreSQL checks and production deployment.
- Actual browser setup at 1440/390 pins a source, protected group, quantity caps and threshold, with no page errors or horizontal overflow. A database/API-backed local execution then completes two cycles with **four settled training steps and two settled cases**. Both deliberately impossible negative-control cases score zero; both candidates are rejected at the configured threshold of one, and the prior assignment and all approved labels remain intact. Repeated closure returns the same run. Completed UI shows both training/evaluation pairs and disables further advancement.
- Promotion in a separate unit fixture deliberately uses a zero threshold to test transition mechanics. It is not evidence of task quality or improvement. The live run establishes execution and correct rejection, not customer or hardware qualification.

No GPU, paid provider, external judge, private content upload or customer study was used. The temporary scoped verification key was deleted and its local executor marked offline. No model weights, raw source payloads, credentials or database are committed.
