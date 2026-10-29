# ANVIL-017 local evidence, 29 October 2026

Label: `local`. Machine: `cursor`, Linux 6.12.94+ x86_64, Python 3.12.3, Node v24.22.2. Records use `docs/engineering/schemas/local-evidence.v1.json` and were written by `.venv/bin/python scripts/local_evidence.py` from a clean `git status --porcelain`.

Code SHA these commands ran against: `dcb76d642eb622b34bf9d55bdef879540ec353cf`. `git status --porcelain` was empty at the start of each command.

## Test records

| File | SHA | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `backend-sqlite.json` | `dcb76d642eb622b34bf9d55bdef879540ec353cf` | `manage.py test --noinput --exclude-tag=pg` | 0 | 1263 | 28 | 1263 | 0 |
| `backend-pg.json` | `dcb76d642eb622b34bf9d55bdef879540ec353cf` | `manage.py test --noinput --tag=pg` | 0 | 28 | 0 | 28 | 0 |
| `frontend-npm-test.json` | `dcb76d642eb622b34bf9d55bdef879540ec353cf` | `npm --prefix web test` | 0 | 249 | 0 | 249 | 0 |

SQLite used `DATABASE_NAME=/tmp/anvil017-sqlite.sqlite3`, `DATABASE_TEST_NAME=/tmp/anvil017-sqlite-test.sqlite3`, and `RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F`. Result line: `Ran 1263 tests in 286.033s` then `OK`.

PostgreSQL used database `modelanvil` on localhost, user `modelanvil`, `DATABASE_ENGINE=postgresql`, the same RabbitMQ URL, pgvector 0.8.1, and the pinned MiniLM, SciFact, and SmolLM2 caches with `HF_HUB_OFFLINE=1`. Result line: `Ran 28 tests in 102.769s` then `OK`.

Frontend used Node v24.22.2 and npm 11.19.1. Result: `# tests 249`, `# pass 249`, `# fail 0`, `# skipped 0`.

`python manage.py check` at the same SHA exited 0: `System check identified no issues (0 silenced).`

## Counts against the previous SHA and baseline `3200915`

Previous SHA `8989985f527470476fb207d1c13412e13b27eb4c` (`origin/main` when this run was recorded), discovered on this machine with the same runner:

- `--exclude-tag=pg`: 1260 tests
- `--tag=pg`: 28 tests

This SHA:

- SQLite run: 1263 passed. The three additional IDs are `DeploySecretKeyCheckTests` in `modelanvil/core/test_deploy_settings.py`.
- PostgreSQL run: 28 passed. The same 28 IDs that were excluded from the SQLite run.
- Frontend: 249 passed, the same count as `8989985` because `web/` is unchanged.

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, as recorded on this machine in `docs/engineering/verification/anvil-002-2026-10-29/report.md`: 1231 SQLite tests after decoration-time fixture handling, 24 `pg` tests, and 234 frontend tests. This run is above that baseline. The increase is the tests that landed on `main` after `3200915`, plus the three deploy-check tests above.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The three records have zero of each. The SQLite command excludes `pg` before the run. `backend-sqlite.json` lists these 28 excluded IDs, and the PostgreSQL command runs them:

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

Every ID collected on this host is in one of those two runs.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on the test records. A missing Metal or GGUF fixture is not a runtime skip. The merged ANVIL-002 ruling keeps the skip gate open for those two IDs until a host with the fixtures runs them.

## Gate G-audit

`pip-audit -r <file>` for every root `requirements*.txt`, pip-audit 2.10.1, no `--ignore-vuln`. Log: `pip-audit.txt`. All 11 files exited 0 with `No known vulnerabilities found`:

- `requirements.txt`
- `requirements.production.txt`
- `requirements.documents.txt`
- `requirements.gpu.txt`
- `requirements.inference.txt`
- `requirements.embeddings.txt`
- `requirements.audio.txt`
- `requirements.vision.txt`
- `requirements.tools.txt`
- `requirements.selfhost.lock.txt`
- `requirements.specialists.txt`

`requirements.specialists.txt` pins `filelock==4.2.1` and `setuptools==84.1.0`. The four Apple Silicon MLX pins use the same Darwin arm64 marker as `requirements.inference.txt`. An OSV query of `mlx==0.32.3`, `mlx-audio==0.5.8`, `mlx-metal==0.32.3`, and `mlx-vlm==0.7.6` found no published vulnerabilities.

`npm audit` in `web/` (devDependencies included, Node v24.22.2, npm 11.19.1) exited 0. `npm-audit.json` reports info 0, low 0, moderate 0, high 0, critical 0, total 0. `web/package.json` has no `overrides` entry.

## Gate G-secrets

`gitleaks` 8.28.0, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir .` at `dcb76d642eb622b34bf9d55bdef879540ec353cf` exited 0 with 0 findings. Console summary: `gitleaks-dir.summary.txt`.
- `gitleaks detect --source . --log-opts=--all` scanned 163 commits and exited 1 with 411 findings (391 unique fingerprints), all rule `generic-api-key`. Summary: `gitleaks-detect.summary.txt`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. The raw report is not committed because it repeats digest text.

Digest hits in the tree were removed by storage: JSON unicode escapes for JSON values, adjacent 8-character Python string literals for pins, and grouped digits in the one markdown digest. Parsed values stay the same. Tokenizer file names are unchanged. QA's ANVIL-017 ruling did not approve an allowlist, and none was added.

## Gate G-rag

`backend-pg.json` stdout includes the existing retrieval control `TASK69_CONTROLS`: held-out nDCG real 1.0 next to seeded random 0.021535, on 200 documents. That is a small correctness check. The documented baseline next to it is MiniLM nDCG@5 1.0000 next to seeded random 0.0215 on 20 queries / 200 SciFact docs (`README.md`). The same record's development nDCG real 0.982545 is the development half of that same check. This change does not claim a new RAG number.
