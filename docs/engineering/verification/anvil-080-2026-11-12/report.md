# ANVIL-080 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `ae3ed20347f75f1419194c650af864b11beb7ba3`. This report is the following documentation commit. The commands below ran at `ae3ed20347f75f1419194c650af864b11beb7ba3`. Node v24.22.3 preceded other `node` binaries on `PATH`.

`modelanvil/sdk/runtime.py` is unchanged from `1d4ecd1`. `verify_network_access` and `verify_artifact_access` already compare the destination and the artifact kind with exact set membership, so an empty allowlist denies every value and a scheme, port, case, suffix, or prefix does not match. No hole showed up under the new tests. `modelanvil/sdk/test_sdk.py` and `modelanvil/sdk/manifest.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:56:08+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T15:47:03+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T15:45:52+00:00 | `gitleaks dir . --redact --no-banner` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T15:45:55+00:00 | `gitleaks detect --source . --redact --no-banner --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil-080/premerge.json`. `scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1289 tests in 360.985s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 124.043s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

The audit command was `/tmp/anvil-080/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `EXIT 0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Behavior locked by the new tests

`modelanvil/sdk/test_runtime_allowlist.py` calls `verify_network_access` and `verify_artifact_access` directly.

- An empty `network_hosts` list denies `example.com`, `localhost`, and `api.approved.com`.
- A manifest that grants `api.approved.com` accepts that string. It denies `https://api.approved.com`, `http://api.approved.com`, `https://api.approved.com:443`, `api.approved.com:443`, `api.approved.com:80`, `API.APPROVED.COM`, `Api.Approved.Com`, `notapi.approved.com`, `api.approved.com.evil.com`, `evil.api.approved.com`, a trailing dot, surrounding spaces, and `example.com`.
- A manifest that grants `read_job_inputs` accepts that kind. It denies `write_to_arbitrary_s3_bucket`, the ungranted kind `write_attempt_staging`, `READ_JOB_INPUTS`, `read_job_inputs.extra`, and `notread_job_inputs`.
- An empty `artifact_access` list denies `read_job_inputs`, `write_attempt_staging`, and `write_to_arbitrary_s3_bucket`.

A temporary mutation of `runtime.py` made those checks accept an empty allowlist, a scheme, a port, a case-insensitive match, and a suffix or prefix. `manage.py test modelanvil.sdk.test_runtime_allowlist` then exited 1 with `FAILED (failures=22)`. The mutation was reverted before `ae3ed20`. The log is `mutation-allowlist.txt`. After the revert the same four tests passed, and `git diff` for `modelanvil/sdk/runtime.py` was empty.

## Gate G-local

Label: `local`. Code SHA `ae3ed20347f75f1419194c650af864b11beb7ba3`.

Discovery on this interpreter, without executing the suite:

- `1d4ecd1`, `--exclude-tag=pg`: 1285 collected, 0 decorator skips.
- This SHA, `--exclude-tag=pg`: 1289 collected, 0 decorator skips.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The four added tests are `RuntimeAllowlistTests.test_empty_network_allowlist_denies_every_destination`, `RuntimeAllowlistTests.test_granted_host_succeeds_only_as_the_exact_string`, `RuntimeAllowlistTests.test_unknown_artifact_kind_is_denied_and_granted_kind_succeeds`, and `RuntimeAllowlistTests.test_empty_artifact_allowlist_denies_every_kind`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `1d4ecd1`, and the frontend run passed 249.

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

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on `1d4ecd1` without those variables. Their bodies are unchanged.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`.

`requirements.documents.txt` on this SHA pins `pypdf==6.21.4`, the same pin as `1d4ecd1`. No dependency was bumped and no ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. No new allowlist was added. The repository `.gitleaks.toml` from ANVIL-043 is the config gitleaks loaded. Raw finding reports are not committed. `Secret` in a redacted report is `REDACTED`.

- `gitleaks dir . --redact --no-banner` at `ae3ed20347f75f1419194c650af864b11beb7ba3` scanned 34.75 MB and exited 0 with `no leaks found`. Record: `gitleaks-dir.json`. That scan ran before `make premerge` wrote `web/storybook-static/`. The bundle is gitignored build output. While it was on disk, `gitleaks dir` reported one `generic-api-key` hit in `web/storybook-static/assets/iframe-DUDqBZgA.js`. The directory was removed. It is not in the commit. A later dir scan of this tree, after that removal and before these evidence files were added, also exited 0.
- `gitleaks detect --source . --redact --no-banner --log-opts=--all` scanned 228 commits and exited 1 with 36 findings, all rule `generic-api-key`. Record: `gitleaks-detect.json`. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. Findings on `ae3ed20347f75f1419194c650af864b11beb7ba3`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0. Those history hits are the ones ANVIL-043 already allowlisted. This ticket does not add an allowlist.

## Result

`make premerge` exited 0 with 1289 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Backend is 4 above main `1d4ecd1` (1285). Frontend and PostgreSQL match that baseline (249 and 28). The four new tests are the difference. `pip-audit -r` exited 0 on all 11 requirements files, with no ignore. `gitleaks dir` exited 0. Full-history `gitleaks detect` still reports the 36 `generic-api-key` findings whose fingerprints are on the ANVIL-017 list.
