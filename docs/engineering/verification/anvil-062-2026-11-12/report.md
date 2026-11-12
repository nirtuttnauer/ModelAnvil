# ANVIL-062 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1 and 8.28.0. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when `make premerge` started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`. That commit is after `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

The measured tree is `113ab2f67285216db0ee884fcb340304f5c241c4`. This report is the following documentation commit. The commands below ran at `113ab2f67285216db0ee884fcb340304f5c241c4`.

`modelanvil/api/idempotence.py` is unchanged. `modelanvil/api/test_idempotence.py` calls `idempotent_write` with Django `TestCase` fixtures, a DRF `APIRequestFactory` request, `JSONParser`, and the existing `IdempotencyKey` model. No network call is made.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:51:53+00:00 | `make premerge` | 0 | 1290 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1290, 249, 28 | 0 |
| `pip-audit.txt` | 2026-11-12T14:43:30Z | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-summary.txt` | 2026-11-12T14:43Z | `gitleaks dir .` with the repository config | 0 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. Its default output path is `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. This run used `--output /tmp/anvil-062-premerge.json` and the file was copied here, so the ANVIL-009 record was not overwritten. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1290 tests in 329.219s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 129.154s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

## Acceptance

| Criterion | Test |
| --- | --- |
| A missing key calls the write function | `IdempotentWriteTests.test_missing_key_calls_write_and_stores_nothing` |
| A successful 2xx stores the response | `IdempotentWriteTests.test_successful_write_stores_status_body_and_completion` |
| The same key, method, path, and body returns the stored status and body without calling write again | `IdempotentWriteTests.test_replay_returns_stored_status_and_body_without_calling_write` |
| The same key with a different body returns 409 | `IdempotentWriteTests.test_same_key_with_different_body_returns_409` |
| A key longer than 128 characters is rejected | `IdempotentWriteTests.test_key_longer_than_128_characters_is_rejected` |

The missing-key test also sends a whitespace key. After `strip()`, that key is empty, so write runs and no `IdempotencyKey` row is stored. The length test rejects 129 characters with `ValidationError` before write, and accepts 128 characters. The replay request reorders the same JSON keys. The stored hash uses `sort_keys=True`, so the stored status and body are returned and write is not called. A different body returns status 409 and the stored body is unchanged.

## Gate G-local

Label: `local`. Code SHA `113ab2f67285216db0ee884fcb340304f5c241c4`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`: the ANVIL-012 and ANVIL-042 premerge records on that history passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests, with 0 skipped. This run passed 1290, 249, and 28. The five added tests are the methods in the table above. This ticket adds no frontend test and no `pg` test.

Commits on `main` after `4dd5060` through `1d4ecd1` do not add a Django test method to the default suite. The Linux-tagged verifier test stays in the Linux backend run. On this host the backend count is the `4dd5060` count plus these five tests.

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

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Log: `pip-audit.txt`.

`requirements.documents.txt` on `4dd5060` pinned `pypdf==6.21.2`, which `pip-audit` reported as CVE-2026-119203 through CVE-2026-119209. ANVIL-042 moved that pin to `pypdf==6.21.4`. This run does not report those CVEs. No ignore was added. This ticket does not edit any `requirements*.txt`.

## Gate G-secrets

`gitleaks dir .` on the working tree at `113ab2f67285216db0ee884fcb340304f5c241c4` uses the repository `.gitleaks.toml` already on `main` from ANVIL-043. This ticket does not edit that file and does not add an allowlist.

- gitleaks 8.30.1, repository config, `gitleaks dir . --redact`: scanned 31.10 MB and exited 0 (`no leaks found`).
- gitleaks 8.28.0, `gitleaks dir . --redact`: scanned 31.10 MB and exited 0 (`no leaks found`).
- gitleaks 8.30.1, stock config, on `git archive HEAD` with `.gitleaks.toml` removed: exited 1 with 370 findings, all rule `generic-api-key`. The file and line set matches `docs/engineering/verification/anvil-043-2026-11-11/findings.json` (370 rows, 366 unique path/line pairs). ANVIL-043 records that every one of those rows was introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165`. None are in `modelanvil/api/test_idempotence.py`.
- gitleaks 8.30.1, repository config, `gitleaks detect --source . --redact --log-opts=--all`: exited 1 with 36 findings, all rule `generic-api-key`. Findings on `113ab2f67285216db0ee884fcb340304f5c241c4`: 0. ANVIL-043 records these 36 as the history findings that remain on the ANVIL-017 list.

Console: `gitleaks-summary.txt`. Raw finding reports are not committed.

After these evidence files were written, `gitleaks dir . --redact` scanned 35.54 MB and exited 0. A gitignored `web/storybook-static/` bundle from `build-storybook` had been on disk and produced one `generic-api-key` hit. That directory is build output. It was removed before this scan. It is not in the commit.

## Gate G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change adds no RAG number.

## Result

The five idempotent-write cases pass. `idempotence.py` did not need a change. `make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts are above the `4dd5060` baseline by those five tests. `pip-audit` exited 0 on every requirements file. `gitleaks dir` exited 0. The 370 stock-config hits remain the ANVIL-043 set from `75e2565`.
