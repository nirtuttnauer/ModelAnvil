# Usage rates and reconciliation

This accounting slice adds pinned prices and append-only monetary corrections to the existing quantity ledger. It does not implement provider collectors, automatic reservation settlement, hierarchical budget limits, or in-flight budget stop enforcement.

## Recording priced usage

Operators/integration services create a tenant-owned `RateRevision` with a unique revision label, provider, resource kind, usage unit, decimal unit price, three-letter uppercase currency, effective start, optional exclusive effective end, and source attribution. Rates are immutable through the model and its public managers; publish a new revision to change a price.

Pass that revision label to `UsageEvent.record(...)` with the provider event key, non-negative finite quantity, matching unit, and actual `occurred_at` timestamp. Price selection is explicit rather than inferred from overlapping schedules. The service checks the tenant, unit and effective interval, multiplies decimal quantity by the pinned price, and rounds half-even to six decimal places. An omitted revision leaves `amount` null and `currency` empty: unknown prices must not appear as zero charges. Previously recorded usage is not retroactively repriced.

A duplicate provider event key returns the original event. Changing its quantity, unit, reservation, rate revision, detail, or an explicitly supplied occurrence time raises a conflict. Replays that omit the occurrence time use the existing event, including after the rate's effective interval ends. Concurrent identical provider callbacks rely on a database uniqueness constraint and return one durable event.

## Provider billing corrections

Use `UsageAdjustment.record(...)` with a same-tenant priced event, signed decimal `amount_delta`, mandatory reason, and tenant-unique provider/source event key. The currency is inherited from the original priced usage; cross-currency corrections require a separately attributed event, not silent conversion. A duplicate source key returns the existing adjustment; altered content is rejected.

`event.net_amount()` adds all its corrections to the original charge. It returns null for unpriced events. Adjustments do not rewrite quantities, the pinned rate, or the original charge. The existing read-only `/api/v1/usage-events/` API discloses `amount`, `currency`, and `net_amount` alongside the original usage fields.

Rates, usage events and adjustments reject model updates/deletions, queryset updates/deletions, and bulk creation/upsert. These are application-level safeguards, not database triggers against privileged direct SQL. Database administrators and migrations must preserve this append-only policy. There is not yet a public write API for rate provisioning or provider corrections.

## Verification and deployment

Run normal migrations before using the new fields/tables. Existing usage remains unpriced. `make test-accounting-integration` builds the current API image, runs the accounting/API/concurrent callback tests against an isolated PostgreSQL instance, and cleans that test stack and its volumes. SQLite alone is not evidence for PostgreSQL concurrent callback behavior.

The monetary ledger does not change the existing quantity-based reservation calculations. Budget-policy currency aggregation, automatic provider reconciliation and late-bill stop decisions remain separate work. Do not treat a recorded usage event or adjustment as proof that a running backend has stopped.
