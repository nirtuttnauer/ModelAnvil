# TASK-49 — bounded private-team onboarding

Verified 2026-10-23 against the local supported development deployment, actual Django API and Vite app. No external email or customer invitation was sent.

## Result

A fresh owner created an isolated workspace, team and first project through the account form. The owner issued a 72-hour one-time reviewer invitation, hid its secret, revoked it and issued a replacement through Team access. A separate fresh browser rejected a wrong email, then joined using the matching email and replacement code. Owner campaign creation and source-file import also used the app forms, without database or raw-API onboarding operations.

The reviewer used keyboard activation to label an actual source sample, reloaded and inspected the persisted revision history. Actual 1440px and 390px checks passed without horizontal overflow or page errors. The owner removed the reviewer through the UI; the existing reviewer session immediately returned 401 for project access and reported unauthenticated. Browser screenshots were inspected once as a desktop/mobile batch after functional completion. Invitation codes were hidden before capture and are absent from this report, task logs and structured receipt.

## Permissions and lifecycle

- New and previously issued teammate invitations create the explicit reviewer role. Reviewers read workspace evidence, submit/escalate ordinary labels and record measured evaluation accept/reject decisions. They cannot create campaigns, close/publish batches, launch training/evaluation, create keys/memberships, invite others or mutate serving endpoints. Adjudication and assignment remain manager operations.
- Server-side permissions remain authoritative. Reviewer navigation exposes Overview, Annotation and Evaluation; execution setup, campaign management and access controls are unavailable. Authentication returns the current role, including on existing browser-session restoration.
- Codes are cryptographically random, stored only as hashes, returned once with no-store, expire after 72 hours and are consumed atomically. Owner listings omit secrets and hashes. Revocation, expiry, wrong email, cross-tenant revocation and replay have actual HTTP regressions. Unsupported invitation methods return 405.
- A real PostgreSQL two-request race creates exactly one pending invitation. Issue, acceptance and revocation share the workspace row lock. Consumption also conditionally checks unused, unexpired and unrevoked state.
- Personal bearer keys and browser sessions require current active membership. Personal key authority is capped by current membership, and membership removal deactivates existing user keys. Independent service keys without a user retain their explicitly granted authority. An engineer cannot mint an owner key. Owner removal through the bounded membership/user APIs is refused.

## Verification

Full pre-final-refinement backend: 985 tests passed, six optional skips (before importing independent merged device-admission changes). Final 31 focused account/identity/review/actual-evaluation/OpenAPI tests, the actual PostgreSQL invitation race, migration checks, 226 frontend tests, production build and Storybook passed; logs are recorded in the private factory evidence. Actual executed CPU evaluation fixture confirms reviewer decision submission and viewer rejection; no model-quality or deployment qualification is claimed. After integrating merged device admission, 26 affected guards passed. The clean base runtime passed 22 account/access/OpenAPI checks without optional ML packages. Final PR-head CI is required before merge.

## Bounds

One non-owner teammate or active invitation per workspace; workspace-wide reviewer visibility across its projects. New invitees must use an email without an existing workspace account. The installation owner explicitly enables self-service accounts for production; normal production HTTPS/cookie/configuration requirements still apply. Email delivery, multi-workspace account linking, project-specific reviewer invitations and role-transfer administration are outside this bounded flow. Local browser evidence is not a production-host/customer adoption claim.
