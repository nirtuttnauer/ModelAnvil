# TASK-7 — immutable verified CPU exports and current review evidence

2026-10-23. Actual bounded CPU candidate export is independently loadable. This checkpoint repairs archive instability and missing current-evidence checks; it grants no model-quality, hardware or production qualification.

## Result

Release review requires an actual completed recognized worker training run and a complete durable evaluation of that exact candidate. Pinned candidate/base/tokenizer/source/suite artifacts and current access are revalidated. Request identity includes the frozen evidence digest, export profile and consumer checksum. Repeating the same request is idempotent; changed evidence or consumer code requires a new immutable review.

The v2 archive freezes the standalone consumer bytes and hash at review creation, actual model weights, tokenizer/configuration and provenance/recipe/data/base/evaluation/license/model-card records. Per-file checksums, stable sorted members, fixed timestamps/permissions and stored ZIP entries make repeated archive bytes identical across download times. Export no longer substitutes a later application consumer into a previously reviewed bundle. An ETag identifies actual archive bytes. Both standalone consumers accept v1/v2 manifests and verify file hashes before bounded inference.

Release serialization now checks current evaluation/training evidence, results, input bytes, access, model card and frozen consumer. Stale reviews hide case content and consumer bytes from both the top-level review and generic bundle manifest. Download, JSON export and local serving reject missing/stale evidence; the UI shows the checked/frozen times and repair guidance and disables download. Frozen quality/license failures remain visible independently of evidence freshness. Legacy reviews without the new immutable pins require a fresh review. Endpoint pointers and recorded startup state remain separate from actual current serving readiness.

## Actual browser and external environment

An owned disposable CPU executor ran one fresh protected negative-control case against the prior actual two-step character candidate. One case unit settled, its temporary API credential was removed and the owned executor marked offline. The owner froze the candidate/evaluation/license review through the actual UI. Its measured accuracy is zero, correctly failing the 0.8 quality gate; no useful-model or improvement claim is made.

The downloaded 25,413-byte archive has SHA-256 `5b39aa9d83c517b674c6be0f6f3f86155f5d33d407b9b31baa3b083d4762f0c5`. Repeated downloads have the same bytes/ETag. An isolated Python virtual environment containing no ModelAnvil, Django, Torch or NumPy extracted and checked every file, then executed the declared standard-library inference consumer. Token output `[2]` (EOS) and the weight checksum match the application. Appending bytes to the extracted weights is refused. This verifies compatibility, not output quality.

A controlled status change to the newly created verification evaluation demonstrated stale-state repair guidance, disabled/400 download and removal of frozen case data at 1440/390. The fixture was restored to completed afterward; its original archive hash returned unchanged. One desktop/mobile inspection batch found no overflow or clipped controls. No endpoint was deployed by this browser check.

## Validation

Full backend before final integration/empty-environment test refinement: 1,001 tests pass, six optional skips. Targeted candidate/release/local-serving checks include deterministic bytes, frozen consumer, actual general-transformer independent loading, corrupted weights, actual-training refusal, changed results, incomplete legacy evidence, current-data redaction and stale-serving refusal. Frontend 226 tests, production build and Storybook pass. Final affected checks and final PR-head CI gate merge.

The flow is deliberately scoped to bounded self-contained CPU character/general-transformer exports. Large external snapshots/adapters and vendor-specific loading retain their separate runtime/hardware requirements. A failing-quality candidate can be downloaded for inspection while its frozen failure remains explicit; local serving requires all required criteria plus current evidence, and production qualification remains unavailable.
