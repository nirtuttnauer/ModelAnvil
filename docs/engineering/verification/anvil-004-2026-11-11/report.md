# ANVIL-004 local evidence, 11 November 2026

Label: `local`. Machine: `cursor`, Linux 6.12.113+ x86_64, Python 3.12.3, Node v24.22.3. The premerge record uses `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when `make premerge` started.

Base SHA: `6febdec8fe71da4f759a7a72e419809682e1b4cd` (`origin/main`). Suite SHA: `7c6d8e88c8875c560c9dd5b24e87381f0cdf76eb`. The decision and the license clause are in `docs/open-dataset-bank.md`.

## make premerge

Command: `make premerge`. Exit code 0. Recorded at `2026-11-11T18:39:30+00:00`. Full stdout and stderr are the `stdout` and `stderr` fields of [premerge.json](premerge.json). `stderr` is empty. `make premerge` writes that record to `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. The file was moved here, and the committed ANVIL-009 record was left unchanged.

| Run | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- |
| backend | `manage.py test --noinput --exclude-tag=pg -v 1` | 0 | 1282 | 28 | 1282 | 0 |
| frontend | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |
| frontend install, build, storybook | `npm --prefix web ci`, `npm --prefix web run build`, `npm --prefix web run build-storybook` | 0 | 0 | 0 | 0 | 0 |
| pgvector | `manage.py test --noinput --tag=pg -v 1` | 0 | 28 | 0 | 28 | 0 |

Backend finished in 354.904s (`OK`). Frontend node:test reported `tests 249`, `pass 249`, `fail 0`, `skipped 0`. PostgreSQL `--tag=pg` finished in 118.840s (`OK`) against Docker images `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The record omits `DATABASE_PASSWORD`.

## Counts against main `6febdec`

`git diff 6febdec8fe71da4f759a7a72e419809682e1b4cd` changes no test file. The counts above are the counts for that main SHA and for this suite SHA. This ticket adds no test.

Those counts are above the 29 October 2026 baseline `3200915506331979c712c17ffd0b1817f95fda75` recorded in `docs/engineering/verification/anvil-002-2026-10-29/report.md` (1231 SQLite tests executed, 24 `pg` tests, 234 frontend tests). The extra tests were already on `main` at `6febdec`. This ticket does not add or remove any of them.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command excludes `pg` before the run. The PostgreSQL command runs that tag. The 28 excluded IDs, also `runs[0].excluded_ids` in `premerge.json`, are:

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

The same 28 IDs ran in the PostgreSQL command. Every ID collected on this host is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the premerge record. A missing Metal or GGUF fixture is not a runtime skip. The same two IDs are absent on `main` when those variables are unset. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1. Command: `pip-audit -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Date `2026-11-11T18:17:01Z`. SHA `7c6d8e88c8875c560c9dd5b24e87381f0cdf76eb`. Log: [pip-audit.txt](pip-audit.txt).

Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119208, CVE-2026-119206, CVE-2026-119209, and CVE-2026-119207 (fix 6.21.3), and CVE-2026-119203, CVE-2026-119205, and CVE-2026-119204 (fix 6.21.4). No ignore was added. That pin is unchanged from `6febdec`. This ticket does not edit `requirements.documents.txt`.

## Gate G-secrets

`gitleaks` 8.28.0, the version recorded by ANVIL-017. Stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir .` on the working tree, including this evidence directory, scanned 31.20 MB and exited 0 (`no leaks found`). Console: [gitleaks-8.28-dir.summary.txt](gitleaks-8.28-dir.summary.txt). The same command at `7c6d8e8` before this directory existed also exited 0. The same command at `71f633ae4bb0638b8cfe14565ea4b0d07738201e` also exited 0.
- `gitleaks detect --source . --log-opts=--all` at `7c6d8e8` scanned 195 commits and exited 1 with 411 findings, 391 unique fingerprints, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Console: [gitleaks-8.28-detect.summary.txt](gitleaks-8.28-detect.summary.txt). The raw report is not committed. The same command after the evidence commit scanned 196 commits and still found 411, with no finding on `7c6d8e8` or `71f633ae4bb0638b8cfe14565ea4b0d07738201e`.

`gitleaks` 8.30.1 is also recorded in [gitleaks-8.30-summary.txt](gitleaks-8.30-summary.txt). `gitleaks dir .` exited 1 with 370 findings, all rule `generic-api-key`, and none under this directory or the VCTK notice files. `gitleaks detect --source . --log-opts=--all` found 781. The 370 findings absent from the ANVIL-017 list are on main commit `75e2565a83b4b0cf96aebe793a9da6823e67d165`. None are on `7c6d8e8`.

## Gate G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement: held-out nDCG real 1.0 next to seeded random 0.021535, on 200 documents. That is a small correctness check. The documented baseline next to it is MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs. The same control's development split in that line is real 0.982545. This ticket adds no RAG number.

## Notice diff

`git diff` of `catalog/qualified-datasets/notices/audio-vctk-full-readme.txt` changes one line. `rg -n '@'` on that file finds no address. The hash update is recorded in `docs/open-dataset-bank.md`. `verify_notices` and `load_manifest` still require an exact match.
