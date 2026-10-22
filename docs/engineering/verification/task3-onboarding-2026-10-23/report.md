# Fresh workspace onboarding verification

Observed 23 October 2026 (Asia/Jerusalem), on main `e29325b1d7d71a2beaadd48f730c06c808a45229` plus the project-selector loading fix. `web/src/main.tsx` SHA-256: `cfef26d79138916ed02c3536ca6972814e57aa40ae568be00e7cd0137214f5c3`.

A fresh browser account completed project creation, pinned CPU model/tokenizer initialization, worker registration, a 20-step allowance, and publication of four CSV examples entirely through the product. An operator started the registered local worker using its one-time credential. The model action was submitted with the keyboard. The next action led to an approved training preflight, with actual encoded token counts of 34, 39, 37 and 44.

The continuous automated observation took **9.152 seconds from valid connection to approved preflight** (one attempt, one completion). This excludes dependency installation and downloads. It does not estimate representative human activation time or abandonment. See [machine-readable observation](onboarding.json).

The saved checklist survived refresh at 7/7. Switching to the empty project produced 3/7, hid the other project's model and dataset, and retained independent training drafts (two steps versus three). Switching back restored 7/7. The selector now uses the loaded project identity, so its loading state cannot briefly select the create-project option for an unloaded saved ID.

Browser checks at 1440 and 390 pixels found no page errors or horizontal page overflow. Empty-state setup links and the preflight next step were exercised; the failed-comparison retry and keyboard action also have browser evidence in the preceding decision-loop qualification. Full frontend verification passed: 225 tests and production build. The preceding merged decision-loop change passed 914 backend tests (four optional skips).

## Reproduction

Use an isolated migrated SQLite database and artifact root, a loopback API and Vite frontend, and a disposable browser profile. Sign up with a throwaway account; create a second project; initialize a CPU model/tokenizer from the model page; register a CPU worker in Infrastructure and start it locally; create an allowance; preview and publish four CSV rows in Datasets. Open the checklist, reload, switch projects and inspect the independent training drafts. Select the published revision and matching pinned resources in Training, request preflight, and inspect the encoded sample counts. Do not launch training for this observation. Stop the disposable worker afterward.

Private session cookies, worker credentials, databases, model artifacts and preflight authorization tokens are excluded. This verifies the local CPU setup contract; it does not qualify GPU execution, model quality, production delivery, or customer usability research. Monetary cost remained unknown and was displayed as such.
