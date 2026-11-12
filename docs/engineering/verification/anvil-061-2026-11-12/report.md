# ANVIL-061 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7`.

The measured tree is `7e43f3469e03f875311e65e2d45bb75eed62894c`. This report is the following documentation commit. The commands below ran at `7e43f3469e03f875311e65e2d45bb75eed62894c`.

`JsonFormatter` still emits one JSON object per record. The object has a `message` field (`Application event` or `Application error`). When a request is bound, `request_id` is the active request id. When a tenant is active, `tenant_id` is that tenant. Record extras `request_id` and `tenant` are included when they are UUIDs (or integers, for the id fields that already accepted integers) and the context has not already set them. String log text and traceback text stay off the line.

Keys such as `password`, `token`, `authorization`, and `api_key` (also hyphenated, upper-case, and nested forms) are replaced with `[redacted]` when they appear in record extras or in a dict message. The raw value is not written. This ticket does not edit `modelanvil/core/middleware.py`, `modelanvil/settings.py`, or `modelanvil/core/tenancy.py`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:52:35+00:00 | `make premerge` | 0 | 1294 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1294, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T14:56:43+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:45:00+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:45:07+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. This run passed `--output /tmp/anvil-061/premerge.json` so it did not write `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1294 tests in 323.082s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 118.823s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command recorded in `pip-audit.json` is `/tmp/anvil-061/pip-audit.sh`. That script runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit:0` for each of the 11 files. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `7e43f3469e03f875311e65e2d45bb75eed62894c`.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`, from the ANVIL-012 premerge record: 1285 backend, 249 frontend, 28 PostgreSQL, 0 skipped. This run passed 1294, 249, and 28, with 0 skipped. That is 9 more backend tests than `4dd5060`.

Counts against `origin/main` `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7`: `git diff --name-only 4dd5060..56b35cc` on test paths changes `modelanvil/api/test_dataset_preparation_http.py` and no other test file. That edit is the pypdf pin assertion. It does not add or remove a test, so the main counts at `56b35cc` are the same 1285, 249, and 28. This ticket adds `modelanvil/core/test_logging.py` and no frontend test and no `pg` test. `web/` is unchanged from `56b35cc`.

The nine added tests are `JsonLogTests.test_formatted_record_is_json_with_a_message`, `JsonLogTests.test_error_record_uses_the_error_message_and_exception_type`, `JsonLogTests.test_request_and_tenant_context_are_included`, `JsonLogTests.test_request_id_and_tenant_on_the_record_are_included`, `JsonLogTests.test_non_uuid_request_id_extra_stays_off_the_line`, `JsonLogTests.test_secret_keys_in_extras_are_replaced_with_a_placeholder`, `JsonLogTests.test_secret_keys_in_a_dict_message_are_replaced_with_a_placeholder`, `JsonLogTests.test_nested_secret_in_an_extra_is_replaced_and_plain_extras_stay_off`, and `JsonLogTests.test_dict_message_does_not_replace_request_or_tenant_fields`.

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

`requirements.documents.txt` on this main pins `pypdf==6.21.4`. The audit does not report CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, or CVE-2026-119209. No ignore was added. This ticket does not edit any `requirements*.txt`.

## Gate G-secrets

`gitleaks` 8.30.1. No new `--config`, no new baseline, and no allowlist edit. The repository already contains `.gitleaks.toml` from ANVIL-043. This ticket does not change that file. The raw finding report is not committed. `Secret` in the redacted detect report is `REDACTED`.

- `gitleaks dir . --redact` on the working tree at `7e43f3469e03f875311e65e2d45bb75eed62894c` scanned 30.71 MB and exited 0 (`no leaks found`). Console: `gitleaks-dir.json`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 219 commits and exited 1 with 36 findings, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Findings on `7e43f3469e03f875311e65e2d45bb75eed62894c`: 0. Console: `gitleaks-detect.json`.

The 370 working-tree hits on `75e2565a83b4b0cf96aebe793a9da6823e67d165` are the set ANVIL-043 allowlisted. They are absent from this dir scan. This ticket adds no finding and no allowlist.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

A formatted record is one JSON object with `message`, and with `request_id` and `tenant_id` or `tenant` when that context is already recorded. Secret keys in extras and in a dict message are `[redacted]`. `make premerge` exited 0 with 1294, 249, and 28 passed and no runtime skip, xfail, or timeout. `pip-audit` exited 0 on every requirements file. `gitleaks dir` exited 0.
