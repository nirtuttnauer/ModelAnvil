# Training preflight completion evidence, 23 October 2026

The implementation is already on main. This reconciliation records a current execution of its ten preflight regressions and the fresh browser setup-to-preflight observation, rather than duplicating the implementation.

The browser reached approved preflight for four real encoded samples, with 34, 39, 37 and 44 tokens. The panel exposes exact token IDs and text, resolved recipe/host memory/storage, grouped compatibility and capacity checks, pinned revisions and expiry. The [redacted evidence](checks.json) includes requirements and check outcomes, without preflight authorization tokens or sample text.

The ten passing regressions compare sample bytes/token IDs to the actual runtime resolver; exercise simultaneous worker-slot, budget and storage failures with corrective actions; refuse unknown capacity; and prove no run, job or budget reservation is allocated on incompatible inputs. They mutate steps, model metadata/revision, capacity, budget, storage and runner status after preview, and reject stale, expired, tampered or other-principal tokens at launch. Same-request idempotent replay returns the existing run without another allocation.

An actual CPU optimization pilot supplies a matching measured engine-time estimate. Corrupting its checkpoint invalidates that estimate. Monetary cost, rate and currency remain unknown without priced usage; the UI shows source, assumptions, units and uncertainty rather than a fabricated price. The browser observation at 1440/390 pixels had no page errors or page overflow. Current main's frontend tests and build passed during the immediately preceding onboarding/privacy qualifications.

Reproduce with `python manage.py test modelanvil.runners.training.test_preflight_report -v 2` in a fresh installed base environment. Browser reproduction is described in the [onboarding report](../task3-onboarding-2026-10-23/report.md). GPU admission software has separate checks; physical accelerator execution is not inferred from this CPU proof.
