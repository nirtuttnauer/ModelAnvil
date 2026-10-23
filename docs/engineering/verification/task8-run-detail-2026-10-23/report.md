# TASK-8 durable run details and recovery

23 October 2026. Reviewed the existing current-main run-detail implementation and retained the former agent's original checkout. Found and fixed a first-page cursor bug that hid older worker attempts. Polling now initializes the continuation cursor once and preserves its progress after later refreshes, including the exhausted state.

Fresh verification:

- Seven actual run-projection API tests pass: tenant isolation, observed/desired state, lost ownership, cancellation acknowledgement, linked inputs, sixty-attempt cursor pagination, evaluation candidate links and explicit recovery blockers.
- Five checkpoint recovery tests run with one optional runtime skip. Supported CPU recovery retains parent execution/checkpoint/usage history, is idempotent, and rejects changed checkpoints, incompatible pins, insufficient budget, active ownership and unauthorized callers.
- The committed Storybook interaction loads 50 plus 10 attempts, exhausts the cursor, retains all history and its note through a synthetic HTTP503 polling failure, reconnects, and confirms refresh does not restart pagination. These are synthetic HTTP responses against the actual component, not real worker execution.
- An actual API/database-backed browser check loads 60 disposable failed-job attempts. Its deep link, browser-session note and source filters survive reload/back/forward. No job was dispatched or executed. Both 1440/390 layouts have no page-level overflow or browser errors.
- Frontend tests, production build and Storybook build pass. Final-head CI gates the merge.

Cancellation remains requested until acknowledged. Unknown/lost ownership stays explicit. Resume is offered only by the supported runtime's verified-checkpoint review and server admission; unsupported jobs keep actionable blockers. This software verification makes no new GPU or customer-use claim.
