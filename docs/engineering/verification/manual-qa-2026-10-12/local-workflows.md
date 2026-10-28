# Dataset Bank specialists and recipes local acceptance

The remaining local journeys passed real execution on 12 October 2026. Dataset Bank downloaded and published every qualified sample source. OCR and typed decisions used verified pinned models. Recipes performed real generation, recovered saved work and published reviewed outputs. This completes the earlier report's three outstanding local execution conditions.

Tests used isolated SQLite and filesystem storage, real authenticated HTTP, Chromium and the installed CPU, Apple MPS and MLX runtimes. Specialist weights were imported from already-downloaded pinned files with size and digest verification; this run does not qualify a new multi-gigabyte specialist Hub download. Existing workspace data was retained. Concurrent checkout changes required a frozen browser acceptance copy; current-checkout regressions were run separately.

Final browser/API source digest: `acd04b02a9903a261cd3789d05d566dbaa446baa0acfc6ee43017dba02604fdd`. [Source identity](local-snapshot.json) records the complete fingerprint.

## Results

| Journey | Observed result |
| --- | --- |
| Dataset Bank sample acquisition | All 11 qualified sources transferred actual upstream bytes and published canonical revisions: Lucide, Iris, Smol-Magpie-Ultra, UltraChat, SQuAD, UltraFeedback, Glaive, CLEVR, VCTK, LibriTTS-R and Wine Quality. Each exercised a bounded subset. |
| Complete source release | Iris's complete 3,738-byte ZIP verified and appeared with its file and manifest download actions. Larger full releases were not downloaded. |
| Bank cancellation and resume | Queued cancellation released its reservation. An injected interruption after one real verified SVG record preserved that record; resume downloaded only the remaining three records and the license, then published four rows. |
| OCR and layout | The two authored scanned PDF pages matched their expected text; eight ordered layout regions produced two canonical rows with shared source grouping. Browser review was required before publication. |
| OCR page recovery | Interruption after saving page 1 produced no partial document. Retry reused page 1 and processed page 2; saved-page usage was counted once and two started attempts settled. |
| Laya decisions | All six authored department cases matched expected routes on MPS. Choice, ordered score and yes/no probability executed; CPU execution also passed. Masked and oversized input were refused. |
| Generated recipes | Real MPS text preview completed, restored after reload, required review, and published two rows. Interruption after the first generated row reused that row and generated only the remaining row on retry. Full-run replay and a stale commit could not duplicate publication. |
| Recipe source formats | CSV, DOCX, PDF and OCR canonical JSONL passed real deterministic CPU execution. A two-source merge preserved original locations and distinct source groups. |
| Output validation | Actual Python output passed syntax checks and stayed data. Actual malformed JSON remained a measured rejection with zero accepted rows. |
| Cancellation accounting | Queued specialist and recipe cancellations settled zero attempts and created no usage events. |
| Artifact integrity | All 45 authenticated output downloads matched their committed SHA-256 and byte size. |
| Fresh core browser repeat | A new project completed CSV preparation, two real CPU transformer steps, candidate chat, held-out baseline/candidate evaluation, retained quality failure, reviewed archive download, authenticated local serving and mobile/reload checks in 47.388 seconds. The local review threshold was explicitly zero for infrastructure testing. The downloaded archive also ran independently with its standard-library consumer and verified manifest hashes. |
| Current checkout regression | 820 backend tests, 9 skipped, no failures; 153 frontend tests, no failures; production build, Django checks and migration consistency passed. |
| Frozen acceptance regression | 815 backend tests, 9 skipped, no failures; 153 frontend tests and production build passed. Final worker changes additionally passed 10 focused checks. |
| Populated browser screens | Dataset Bank, Specialists and Recipes passed desktop/mobile overflow checks and selected axe WCAG A/AA checks after fixes. Recipe output accepted keyboard focus and scrolling. |

## Fixes retained in the checkout

- Public GitHub API rate limits blocked Lucide review and acquisition. A checksum-pinned inventory of the exact qualified commit now supplies the tree when GitHub returns HTTP 403 or 429. Actual raw files still undergo size and Git blob digest verification. Corrupt inventory and mismatched revisions are refused.
- A replay requesting a different subset or split seed silently returned an existing acquisition. The API now rejects that mismatch and retains the frozen plan; the UI displays the saved record count. Another project can acquire a different subset of the same revision.
- Trusted local workers did not report heartbeats while idle or offline status after shutdown. Bank, specialist and recipe commands now refresh their connection while polling, mark shutdown offline, reconnect on restart and preserve draining. An offline worker remains displayed offline after its heartbeat ages. `--once` performs one poll and exits; it does not keep execution capacity connected.
- Completed recipe publication now links to the exact dataset revision for records, splits, artifacts and lineage inspection.
- Populated recipe output was scrollable without keyboard focus. Accepted rows and rejection output now have labelled focus targets; keyboard scrolling and accessibility checks passed.
- The compute inventory secrecy test now inspects rendered JSON, including serialized timestamps, while retaining its token-disclosure assertion.

## Practical qualification

The exercised local workflows are usable with appropriate datasets, pinned weights, quotas and running operator-installed compute. Run the normal `run_specialists` and `run_recipes` commands while queueing browser jobs. Dataset Bank's operator registration and executor command are documented in [Dataset Bank qualification](../../../dataset-bank-qualification.md). Specialist and recipe setup are documented in [local specialists](../../local-specialists.md) and [resumable recipes](../../resumable-pages-and-data-recipes.md).

Execution correctness does not establish model quality. The tiny generator invented an end time that the source did not supply. Review generated text and extracted documents before publication; the authored OCR and decision fixtures do not measure representative accuracy or calibrated probabilities. Production deployment, other browsers, non-Mac GPUs, every training algorithm, remote providers and large full-corpus transfers remain outside this qualification.

An intermediate rollback regression failed while other real inference held the shared CPU admission lease. Rollback passed in isolation and in the final complete regression run after competing inference finished. No rollback implementation change was needed.

[Sanitized evidence](local-workflows-evidence.json), [bank recovery](local-bank-recovery.json), [OCR recovery](local-page-resume.json), [recipe recovery](local-recipe-recovery.json), [source formats](local-recipe-formats.json), [artifact hashes](local-integrity.json), [accessibility](local-accessibility.json) and the local test summaries record the actual outcomes. Credentials, private browser traces and model binaries are excluded.

QA services were stopped. Isolated API keys were deactivated, worker credentials revoked and workers left offline. The user's existing database, artifact store and running services were retained.

[Remaining local fixes](remaining-fixes.md) adds Infrastructure setup for Dataset Bank and CPU recipes, observed-capacity admission, full-run binding restoration and readable validation errors. Its final regressions passed 829 backend tests (9 skipped) and 156 frontend tests.
