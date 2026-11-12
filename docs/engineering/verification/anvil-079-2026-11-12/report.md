# ANVIL-079 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `4a3f95184ff78c3bb4ac1bcab0c79d17ebe32ccc`. This report is the following documentation commit. The commands below ran at `4a3f95184ff78c3bb4ac1bcab0c79d17ebe32ccc`.

`generate_backup` writes the archive with a JSON serializer that drops credential fields before `database.json` is written. Field names removed are `password`, `secret`, `secret_hash`, `api_key`, `apikey`, `access_token`, `refresh_token`, and names ending in `_secret`, `_secret_hash`, or `_password`. `dest_dir` and `storage_dir` are confined to their own directories: a `..` segment or a symlink on the path raises `ValueError` before any archive byte is written, and copied artifact files are opened with `O_NOFOLLOW`. `verify_restore_drill` rejects an artifact path that contains `..` or lands on a symlink.

The tests live in `modelanvil/ops/test_backup_redaction.py`. They use throwaway fixture values. The unredacted Django serializer of the planted API-key row still contains the fixture token, so a backup that writes that dump fails `test_planted_api_key_material_is_absent_and_archive_verifies`.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T16:12:17+00:00 | `make premerge` | 0 | 1296 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1296, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T16:18:10+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T16:18:11+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T16:18:14+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` uses `scripts/premerge.py`, which records the command as `make premerge`. This run wrote `/tmp/anvil-079/premerge.json` and the record was copied here. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1296 tests in 296.562s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 107.892s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is absent from the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command was `/tmp/anvil-079/pip-audit.sh`. It runs `/tmp/modelanvil-venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `EXIT 0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `4a3f95184ff78c3bb4ac1bcab0c79d17ebe32ccc`.

Counts against main `1d4ecd1a6f1a65f159649350be5c751645e0773a`. The ANVIL-043 premerge record on ancestor `4dd5060e632bae598003bf3a51a474709fe8c7ac` passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests, with 0 skipped. From that commit to `1d4ecd1` the tree adds three methods in `tests/test_premerge.py` (`test_linux_host_excludes_only_pg`, `test_other_hosts_also_exclude_linux_only_tests`, `test_stale_pg_reports_are_removed_before_a_second_run`). `manage.py test` does not collect that module, and the diff adds or removes no other `test_` method and no frontend test. The main `1d4ecd1` suite is therefore 1285 backend, 249 frontend, and 28 PostgreSQL.

This run passed 1296 backend, 249 frontend, and 28 PostgreSQL tests. The backend difference is the 11 methods in `modelanvil/ops/test_backup_redaction.py`:

- `test_planted_api_key_material_is_absent_and_archive_verifies`
- `test_clean_non_secret_backup_verifies`
- `test_dest_dir_parent_segment_cannot_escape`
- `test_dest_file_symlink_is_not_written`
- `test_dest_dir_symlink_cannot_escape`
- `test_storage_dir_parent_segment_cannot_escape`
- `test_storage_dir_symlink_cannot_escape`
- `test_storage_symlink_file_is_not_copied`
- `test_storage_symlink_directory_is_not_walked`
- `test_verify_rejects_artifact_parent_segment`
- `test_verify_rejects_artifact_symlink`

1285 + 11 = 1296. Frontend and PostgreSQL are unchanged.

## Gate G-skip

A skip, xfail, or timeout at runtime is a failure. The premerge runs have zero of each. The backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the same 28 excluded IDs as the ANVIL-043 record, and `manage.py test --noinput --tag=pg` passed those 28:

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

No requirements file changed. `requirements.documents.txt` keeps the `pypdf==6.21.4` pin from ANVIL-042. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1 loaded the committed `.gitleaks.toml`. No allowlist entry was added.

- `gitleaks dir . --redact` scanned 36.27 MB and exited 0, `no leaks found`. Record: `gitleaks-dir.json`. The scan ran after `web/storybook-static/` was removed. That directory is gitignored Storybook build output and is absent from the commit.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 228 commits and exited 1 with 36 findings, all rule `generic-api-key`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None is on `4a3f95184ff78c3bb4ac1bcab0c79d17ebe32ccc`. The file counts match the history remainder recorded by ANVIL-043: `modelanvil/runners/training/hf_runtime.py` (7), `scripts/audio_candidate_infer.py` (7), `modelanvil/runners/training/vlm_math.py` (4), `modelanvil/runners/training/audio_runtime.py` (4), `scripts/vlm_candidate_infer.py` (4), `modelanvil/runners/training/audio_math.py` (3), `scripts/verify_cpu_export.py` (3), `docs/engineering/verification/manual-qa-2026-10-12/local-workflows.md` (1), `modelanvil/rag/chunking.py` (1), `modelanvil/core/test_selfhost.py` (1), `modelanvil/context_lab/test_context_lab.py` (1). Record: `gitleaks-detect.json`. `Secret` in that record is `REDACTED`.

The 370 `generic-api-key` findings introduced by `75e2565a83b4b0cf96aebe793a9da6823e67d165` stay covered by the allowlist ANVIL-043 already merged. This ticket does not add an allowlist.

## Acceptance

- A backup of a row that holds the fixture API-key token and a user password hash leaves both values out of `database.json`, `manifest.json`, and copied artifact bytes. Non-secret fields (`tenant.slug`, `user.email`, `apikey.name`) and the copied weights remain. `verify_restore_drill` returns `VERIFIED`.
- `test_planted_api_key_material_is_absent_and_archive_verifies` asserts that Django's unredacted serializer still emits the fixture token and the password hash. Writing that dump into the archive fails the test.
- `dest_dir` and `storage_dir` reject `..` and a symlink, including a symlinked `database.json`, a symlinked file inside storage, and a symlinked directory inside storage. `verify_restore_drill` rejects an artifact path with `..` and a symlinked artifact file. The outside sentinel bytes stay in place.
- A backup limited to `identity.tenant` and `identity.user`, plus one storage file, still passes `verify_restore_drill`.
- The code change is `modelanvil/ops/backup.py` and `modelanvil/ops/test_backup_redaction.py`. `identity/` and `artifacts/tombstones.py` are unchanged.

## Result

`make premerge` exited 0 with 1296 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Backend is 11 above main `1d4ecd1`, and those 11 are the new backup tests. `pip-audit -r` exited 0 on all 11 requirements files, with no ignore. `gitleaks dir` exited 0. Full-history `gitleaks detect` still reports the 36 `generic-api-key` findings on the ANVIL-017 list.
