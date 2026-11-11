# ANVIL-042 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The measured tree is `870400d28041573c419900e6827c5f0e19c5f149`. This report is the following documentation commit. The commands below ran at `870400d28041573c419900e6827c5f0e19c5f149`.

`requirements.documents.txt` pins `pypdf==6.21.4`. That is the release in which CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209 are fixed. No ignore, exception, allowlist, baseline, or override was added.

No lock file and no hash pin names `pypdf` 6.21.2. The parser refuses any other installed version: `PDF_VERSION` in `modelanvil/data/source_import.py` and the version check in `scripts/pdf_extract.py` are that pin. They moved to 6.21.4 with the requirements file so document tests run against the installed package. `modelanvil/api/test_dataset_preparation_http.py` asserts the published parser revision and moved with them. `docs/engineering/source-import.md` and `docs/engineering/capability-evidence.md` state the current pin. `docs/engineering/dependency-security.md` records this pin and leaves the 23 October 2026 sentence as the pin from that date.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-11T22:06:55+00:00 | `make premerge` | 0 | 1285 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1285, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-11T22:13:56+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-11T22:14:02+00:00 | `gitleaks dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-11T22:14:04+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. Its default output path is `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. This run wrote that path. The record was copied here and the ANVIL-009 file was restored, so that directory stays the ANVIL-009 record. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1285 tests in 336.338s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 120.982s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command was `/tmp/anvil-042/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit 0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `870400d28041573c419900e6827c5f0e19c5f149`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`: the ANVIL-012 premerge record on that history passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests, with 0 skipped. This run passed the same counts. The diff from `4dd5060` to `870400d` adds no test. One assertion in `modelanvil/api/test_dataset_preparation_http.py` changes from `pypdf==6.21.2` to `pypdf==6.21.4`.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists these 28 excluded IDs, and `manage.py test --noinput --tag=pg` passed the same 28:

- `modelanvil.annotation.test_cycles.ConcurrentCampaignClosureTests.test_concurrent_closure_dispatches_one_snapshot_run_and_reservation`
- `modelanvil.annotation.test_feedback.ApplicationFeedbackConcurrencyTests.test_concurrent_inspection_and_clean_registration_cannot_both_commit`
- `modelanvil.annotation.test_feedback.ApplicationFeedbackConcurrencyTests.test_concurrent_retries_create_one_receipt_and_review_candidate`
- `modelanvil.api.test_dataset_preparation.DatasetPreparationApiTests.test_concurrent_preparation_allocates_distinct_revisions_and_advances_to_latest`
- `modelanvil.api.test_team_access.ConcurrentInvitationTests.test_simultaneous_issue_allows_only_one_pending_invitation`
- `modelanvil.budgets.test_concurrency.AccountingConcurrencyTests.test_simultaneous_callback_creation_returns_the_same_event`
- `modelanvil.compute.tests.ConcurrentAllocationTests.test_concurrent_replays_create_one_provider_resource_and_one_reservation`
- `modelanvil.context_lab.test_positions.ActualPositionSweepTests.test_actual_pinned_model_repeats_positions_and_records_output_scoring`
- `modelanvil.jobs.test_broker.RabbitMQLoopIntegrationTests.test_consumer_loop_executes_a_dispatch_and_stops_cleanly`
- `modelanvil.jobs.test_device_claims.DeviceClaimConcurrencyTests.test_two_workers_tenants_claim_one_device_once`
- `modelanvil.rag.test_benchmark.ActualPublicRetrievalControls.test_frozen_public_corpus_controls_ann_recall_and_owned_cleanup`
- `modelanvil.rag.test_embedding_training.ActualEmbeddingCandidateTests.test_real_cpu_weights_independent_export_private_serve_and_protected_roles`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_actual_encoder_dimensions_norm_determinism_and_context_refusal`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_attempt_cap_and_new_space_never_reuse_another_space_cache`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_bad_dimension_failure_and_fenced_attempt_never_publish_ready`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_cancel_after_checkpoint_and_resume_encodes_only_remaining_chunks`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_cancel_queued_leaves_no_ready_index_and_zero_attempt_charge`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_publication_rechecks_source_and_checksum_and_generic_job_routes_are_closed`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_queue_is_async_idempotent_then_actual_pgvector_query_and_pca`
- `modelanvil.rag.test_embeddings.EmbeddingWorkerTests.test_registered_profile_real_outbox_broker_worker_and_vector_publication`
- `modelanvil.rag.test_generation.ActualGroundedGenerationTests.test_actual_three_conditions_usage_citation_scope_abstention_and_revocation`
- `modelanvil.rag.test_pgvector.VectorExtensionTests.test_vector_extension_round_trip`
- `modelanvil.rag.test_research.ActualPostgreSQLResearch.test_actual_keyword_retrieval_model_answer_compaction_and_revocation`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_all_tombstone_identities_and_wrong_resource_grants`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_exact_hnsw_plans_and_transaction_settings`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_grant_revocation_and_tenant_scope_on_already_created_queryset`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_narrow_membership_tombstones_and_revocations_stay_inside_ranking`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_sql_full_text_rank_hybrid_and_parameters`

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main without those variables. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on `4dd5060` pins `pypdf==6.21.2`. The ANVIL-012 audit of that pin reports CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This run does not report those CVEs.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw finding reports are not committed. `Secret` in a redacted report is `REDACTED`.

- `gitleaks dir . --redact` at `870400d28041573c419900e6827c5f0e19c5f149` scanned 27.04 MB and exited 1 with 370 findings, all rule `generic-api-key`. Console: `gitleaks-dir.json`.
- The same command on a clean worktree of main `4dd5060e632bae598003bf3a51a474709fe8c7ac` exited 1 with 370 findings. File and line, the two sets match. This commit adds no finding.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 198 commits and exited 1 with 781 findings, all rule `generic-api-key`. Console: `gitleaks-detect.json`. A redacted report from that same SHA has 370 findings on commit `75e2565a83b4b0cf96aebe793a9da6823e67d165` and 0 findings on `870400d28041573c419900e6827c5f0e19c5f149`. Those 370 history findings are on main and are owned by ANVIL-043. No allowlist was added.

`gitleaks dir` is not 0. It matches main. A Storybook build directory, `web/storybook-static/`, added one extra `generic-api-key` hit while it was on disk. That directory is build output. It was removed before the recorded `gitleaks dir` scan. It is not in the commit. A scan of these evidence files before they were committed reported no leaks.

## Document handling

`make premerge` executed the PDF tests: the run has 0 skips, and `pypdf` 6.21.4 was installed. Before that suite, the same tree passed `manage.py test modelanvil.data.test_pdf_import modelanvil.api.test_dataset_preparation_http --noinput -v 2`: `Ran 9 tests in 4.686s` then `OK`.

## Result

`make premerge` exited 0 with 1285 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Those counts equal the ANVIL-012 counts on main `4dd5060`. `pip-audit -r` exited 0 on all 11 requirements files, including `requirements.documents.txt`, with no ignore. `gitleaks dir` exits 1 with the same 370 findings as main `4dd5060`. Full-history `gitleaks detect` still reports the 370 `generic-api-key` findings on commit `75e2565`.
