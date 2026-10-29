# ModelAnvil manual QA report

ModelAnvil is useful for local dataset preparation, model inference, bounded training and alignment, evaluation, and reviewed local serving. These workflows completed against real APIs and artifact bytes. **The remaining local execution conditions are now completed:** real Dataset Bank transfers, specialist inference and recipe execution passed the [follow-up acceptance run](local-workflows.md). Production and other browsers remain outside this qualification.

Test date: 12 October 2026, Asia/Jerusalem. Exploratory browser testing used Playwright to drive Chromium against an isolated SQLite database and filesystem artifact store. Screenshots were visually inspected. Browser journeys used the actual API, without Storybook mocks. The existing application database and artifact store were retained.

Another active process changed the checkout during testing. The final repeatable browser run used a frozen source snapshot with API digest `d0ed1d9965aee31585fc462f40032203e7e0293fe2b8af50d6fdb0a15399e468`, plus the tested local server entry-point fix. [Snapshot identity](snapshot.json) records the complete source fingerprint. Later concurrent changes require their own acceptance run.

## Verification results

| Check | Result |
| --- | --- |
| Backend regression on the final snapshot | 801 tests, 9 skipped, no failures |
| Frontend regression on the final snapshot | 149 tests, no failures |
| Frontend regression on the current checkout at completion | 153 tests, no failures |
| TypeScript and Vite production builds | Passed for snapshot and checkout; the bundle-size warning was subsequently resolved in [production bundle QA](bundle-performance.md) |
| Django checks and migration drift | Passed |
| Desktop screens at 1440 by 1000 pixels | All 18 loaded without visible API errors or horizontal overflow after fixes |
| Mobile screens at 390 by 844 pixels | All 18 passed navigation and horizontal-overflow checks |
| Accessibility | No violations in the selected axe WCAG A and AA checks across 18 screens and Run Detail after fixes; overview dark-theme scan also passed |
| Concurrent local HTTP requests | Ten bursts of 24 requests: 240 successful responses, zero failures after fix |
| Full browser journey on final snapshot | Dataset preview/publication, two real training steps, candidate chat, baseline evaluation, frozen review, export, and authenticated local serving completed in 67.3 seconds |
| Independent exported model consumer | Downloaded archive executed with isolated Python; weights verified and two output tokens generated |

Automated accessibility scans complement the keyboard and visual checks; they do not establish complete assistive-technology compliance. The nine skipped backend tests are excluded from the pass claim.

## User journeys exercised

| Area | Actual coverage |
| --- | --- |
| Overview | Empty workspace, project creation and selection, seven prerequisites recorded, navigation shortcuts |
| Dataset Bank | Catalog, source inspection, license and scope display, budget selection, explicit refusal when acquisition compute is unavailable |
| Datasets | CSV, JSON arrays, DOCX body text, searchable PDF and canonical JSONL publication; required preview; invalid CSV refusal; immutable revision confirmation; active-project isolation |
| Annotation | Campaign creation, protected audit sample refusal, manual labels, immutable closure and JSON export; export preserved the exact sample-to-label mapping |
| Recipes | Prepare-documents starter, immutable version save, definition export, invalid dependency rejection; execution not qualified in the browser |
| Models | Actual CPU transformer and character base weights; verified upload and import of the existing SmolLM2 135M snapshot |
| Chat | Actual candidate inference, natural-language completion from imported SmolLM2, saved conversations, reload, export, comparison and durable preference vote |
| Specialists | Empty catalog, execution prerequisites and disabled controls; model acquisition and OCR/layout/decision execution not qualified |
| Training | Pinned preflight, worker connection, budget reservation, two actual optimizer steps, committed candidate and durable run reload |
| Alignment | Separate training and held-out preference artifacts; two actual DPO steps and an output candidate |
| Evaluation | Immutable suite, exact candidate and baseline, actual failed case, complete coverage, queued cancellation and zero-case settlement |
| Workflows | Invalid payload refusal, durable queue, acknowledged cancellation and preserved attempt state |
| RAG | Knowledge-base creation, document indexing, source-linked retrieval, empty query results clearing prior evidence |
| Context Lab | Immutable recipe, exact compiled prompt, token allocation, malformed input refusal, drafts surviving navigation and reload |
| Releases | Failed review preserved; failing review disabled deployment; verified archive download; explicit infrastructure-only approval, real readiness probe and authenticated local serving |
| Infrastructure | Worker registration, one-time credential flow, actual worker process and heartbeat; registration distinguished from connection |
| Budgets | Policy creation, measured usage and rejection of a limit below existing commitments |
| Audit | Recorded events, filtering, offline error display and explicit refresh recovery |

The local serving test deliberately used an accuracy threshold of zero for an infrastructure review. The original quality review remained failing. Successful deployment here establishes working infrastructure, not a useful trained model or production model quality.

## Defects fixed and retested

| Priority | Reproduction and impact | Fix and evidence |
| --- | --- | --- |
| P1 | Queued evaluation had `cancel.available=true` and a valid endpoint, but Run Detail hid cancellation and said there was nothing to cancel | Removed the evaluation-only UI restriction. Browser cancellation was acknowledged; zero completed cases settled zero usage. [Before](evaluation-cancel-before.png), [after](evaluation-cancel-final.png) |
| P1 | A burst of 24 health requests through Vite produced 10 HTTP 502 responses; normal page-loading bursts also failed intermittently | Increased Django development server's connection accept queue from 10 to 128 in the standard `manage.py runserver` entry point. Ten repeated 24-request bursts passed; page reloads and the full journey were retested |
| P2 | Screen-search button's accessible name omitted its visible label | Matched the accessible name to the visible label. Axe and keyboard search/Enter/Escape checks passed |
| P2 | Chat transcript had an accessible label on a generic unnamed container | Added the semantic conversation-log role. Chat's accessibility scan passed |
| P2 | Terminal runs stopped polling as designed, then incorrectly displayed a stale-live-data warning | Applied the stale display only to live runs while preserving recovery freshness guards. Retested after two polling intervals. [Before](terminal-stale-before.png), [after](terminal-stale-after.png) |

The earlier snapshot's dataset client also omitted the active-project header, creating tenant-shared uploads. Concurrent implementation work supplied the scope fix. A new upload was invisible in the other project and visible again in its original project. QA did not change the access semantics of existing shared resources.

The Dataset Bank test harness was updated for the new draft and explicit-review flow without removing its budget, license, storage, cancellation or late-response checks. An additional check confirms that source review fetches context and preflight without allocating an acquisition. An unused Recipes type import was removed so the production build could complete.

## Conditions for broader sign-off

- **Dataset Bank, Specialists and Recipes:** real execution, publication, cancellation and recovery now pass with operator-installed workers and verified pinned models. See [follow-up evidence and remaining quality limits](local-workflows.md). Infrastructure now provisions Dataset Bank and CPU recipe profiles. Specialist inference and Apple recipe generation retain their documented device-specific operator commands; see [remaining defect fixes](remaining-fixes.md).
- **Model and runtime coverage:** actual DPO and CPU training/evaluation were exercised. This run did not qualify PPO, reward-model training, verifier RL, GPU training, GGUF, MLX inference, remote Hub download/resume or every catalog connector.
- **Deployment coverage:** Safari, Firefox, real mobile devices, PostgreSQL/RabbitMQ/S3 operations, distributed workers, production servers, TLS, sustained load and restore/rollback drills require separate qualification.
- **Usability limit:** a new workspace requires suitable data, weights, quotas and running compute. The untrained CPU references prove execution mechanics and can emit poor text; imported model inference is the demonstrated natural-language path.

## Evidence and reproduction

[Sanitized browser evidence](evidence.json), [backend summary](backend-tests.txt), [snapshot frontend summary](frontend-snapshot-tests.txt), [checkout frontend summary](frontend-current-tests.txt), [build output](frontend-build.txt), and [independent consumer](independent-consumer.json) contain the recorded results. Credentials, private browser traces and model binaries are excluded.

Run `make check migration-check`, `.venv/bin/python manage.py test --noinput`, and `cd web && npm test && npm run build` for regressions. For the local connection regression, run the normal API and Vite processes, then issue 24 concurrent GET requests to `/api/v1/health/` through Vite and require all responses to be HTTP 200. For evaluation cancellation, connect an evaluation worker, pause it with SIGSTOP without marking it offline, queue a budgeted evaluation, open its durable run and request cancellation; verify the cancelled state and zero-case settlement.

Verdict: **qualified local execution for the exercised workflows, including Dataset Bank, Specialists and Recipes; model quality and production sign-off remain subject to the conditions above.**
