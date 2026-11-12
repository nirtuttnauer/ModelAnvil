# ANVIL-081 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c`. This report is the following documentation commit. The commands below ran at `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c`.

`rehearse_copy` walked the source with `shutil.copytree`, which copies the bytes of a symlink target, and then checksummed destination files with `Path.read_bytes`, which follows links. A symlink inside the source that points outside that tree was copied into the destination as a regular file. The new tests in `modelanvil/core/test_restore_rehearsal.py` failed on that behavior. `rehearse_copy` now plans the tree without following links, refuses a symlink whose target resolves outside the source, copies regular files, rejects a destination that already exists (including a dangling symlink), and returns `production_qualified: false` and `hardware_qualified: false`. The scope text stays a byte-copy description and does not state an off-host restore or a recovery time. `scripts/local_restore_drill.py` and `scripts/rehearse_restore_copy.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:59:03+00:00 | `make premerge` | 0 | 1290 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1290, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T15:50:50+00:00 | `bash /tmp/anvil081/pip-audit.sh` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T15:50:51+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T15:50:54+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was run as `.venv/bin/python scripts/premerge.py --output /tmp/anvil081/premerge.json`. The record's command field is `make premerge`. Node v24.22.3 was the `node` on `PATH`. Backend result: `Ran 1290 tests in 313.174s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 111.387s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for the PostgreSQL run after the pinned caches were filled.

The audit command runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` in sorted order and does not pass `--ignore-vuln`. Stdout records `EXIT 0` for each file. Stderr records `No known vulnerabilities found` for each file.

`gitleaks dir` and `gitleaks detect` used the repository `.gitleaks.toml` that is already on main. No allowlist was added. The raw gitleaks reports are not committed.

## Gate G-local

Label: `local`. Code SHA `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c`.

Counts against main `1d4ecd1a6f1a65f159649350be5c751645e0773a`, collected with the same interpreter and the project test runner before this suite ran:

| Suite | main `1d4ecd1` collected | this run passed | Skipped / xfail / timeout |
| --- | --- | --- | --- |
| Backend `--exclude-tag=pg` | 1285 | 1290 | 0 |
| Frontend `npm test` | 249 | 249 | 0 |
| PostgreSQL `--tag=pg` | 28 | 28 | 0 |

The backend difference is five tests in `modelanvil.core.test_restore_rehearsal.RestoreRehearsalTests`:

- `test_absolute_symlink_outside_the_source_is_not_followed`
- `test_relative_symlink_outside_the_source_is_not_followed`
- `test_directory_symlink_outside_the_source_is_not_followed`
- `test_internal_symlink_is_not_materialized_as_a_second_file`
- `test_existing_destination_is_rejected_and_a_copy_stays_under_the_new_path`

Collected counts on this SHA were 1290 and 28, matching the passed counts. Frontend files were not changed. No test was weakened, skipped, or marked expected-fail.

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

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main `1d4ecd1` without those variables.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`. No requirements file was changed.

## Gate G-secrets

`gitleaks` 8.30.1, config `.gitleaks.toml` as it stands on main. No new allowlist.

- `gitleaks dir . --redact` at `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c` scanned 31.14 MB and exited 0, `no leaks found`. Record: `gitleaks-dir.json`. That scan ran before `make premerge` wrote `web/storybook-static/`. The bundle is gitignored build output and was removed after the suite. It is not in the commit.
- `gitleaks detect --redact --log-opts=--all` scanned 228 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c`: 0. All 36 fingerprints are listed in `reviews/ANVIL-017-gitleaks-history.md`. Record: `gitleaks-detect.json`. Those history findings are owned by the already-merged ANVIL-043 allowlist work. This change does not add an allowlist.

## Acceptance criteria

- A symlink inside the source that points outside the source tree is not followed into the destination. Absolute file links, relative file links, and directory links are covered. The foreign bytes stay at the original path.
- An existing destination directory, file, or dangling symlink is rejected. A successful copy writes the source's regular files under the new destination and leaves the surrounding files unchanged.
- The returned dict keeps `production_qualified` and `hardware_qualified` false. Its keys are `files`, `inventory`, `production_qualified`, `hardware_qualified`, and `scope`. The scope text does not state an off-host restore or a recovery time.
- Before the fix, the new symlink tests failed because the foreign bytes appeared under the destination, and the dangling-destination case raised `FileExistsError` from `copytree`. After the fix, those tests pass. A copy that followed the link, replaced an existing destination, or set either flag to true would fail them.
- `make premerge` exited 0 at `eaf6c30d3a531c5ed82a7e1de0b7735d58748f8c` from an empty `git status`, labeled `local`.

## Result

`make premerge` exited 0 with 1290 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Backend is five above main `1d4ecd1` because of the new rehearsal tests. Frontend and PostgreSQL match main. `pip-audit -r` exited 0 on all 11 requirements files with no ignore. `gitleaks dir` exited 0. Full-history `gitleaks detect` still reports 36 `generic-api-key` findings, all on the ANVIL-017 list and none on this commit.
