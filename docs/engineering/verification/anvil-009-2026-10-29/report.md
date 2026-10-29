# ANVIL-009 local pre-merge, 29 October 2026

Label: `local`

`make premerge` ran at `c12d6f176f9fa5eab0483ffe464174ca4845e4b7`. `git status --porcelain` was empty when the command started. The record is [premerge.json](premerge.json), written by `scripts/premerge.py` to `docs/engineering/schemas/local-evidence.v1.json`. This report is the following docs-only commit.

Machine: `cursor`, Linux 6.12.94+ x86_64, Ubuntu 24.04, Python 3.12.3, Node v24.22.2, pip-audit 2.10.1, gitleaks 8.30.1. Date: 2026-10-29T05:05:46Z through 2026-10-29T05:15:01Z.

Command: `make premerge`. Exit code 0. Full stdout and stderr are the `stdout` field of `premerge.json`.

| Run | Command | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- |
| backend | `manage.py test --noinput --exclude-tag=pg -v 1` | 1260 | 28 | 1260 | 0 |
| frontend | `npm --prefix web test` | 249 | 0 | 249 | 0 |
| frontend-install | `npm --prefix web ci` | 0 | 0 | 0 | 0 |
| frontend-build | `npm --prefix web run build` | 0 | 0 | 0 | 0 |
| frontend-storybook | `npm --prefix web run build-storybook` | 0 | 0 | 0 | 0 |
| pgvector | `manage.py test --noinput --tag=pg -v 1` | 28 | 0 | 28 | 0 |

Backend finished in 408.164s (`OK`). Frontend node:test reported `tests 249`, `pass 249`, `fail 0`, `skipped 0`. `npm ci`, `npm run build`, and `npm run build-storybook` exited 0. PostgreSQL `--tag=pg` finished in 105.680s (`OK`) against Docker images `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the value already published in `.github/workflows/ci.yml` and `compose.premerge.yaml`. The record omits `DATABASE_PASSWORD`.

`python3.12 tests/test_premerge.py` on this SHA: 12 tests, `OK`. Django's runner does not collect that module.

## Counts against baseline `3200915`

Baseline `3200915506331979c712c17ffd0b1817f95fda75`, measured on this machine class in the [ANVIL-002 record](../anvil-002-2026-10-29/report.md):

- Default SQLite discovery collected 1237 tests. Six were decoration-time skips, leaving 1231 executed tests.
- The `pg` tag collected 24 tests.
- Frontend `npm test`: 234 passed, 0 skipped.

This run:

- Backend: 1260 passed. That is 29 more executed tests than the baseline's 1231. ANVIL-002 accounts for 25 of them (tests that landed on `main` after `3200915`) and for the six baseline skips leaving the default run: four retagged `pg`, and the MLX and GGUF tests collected only when their fixture paths are set. The remaining four are `PaidDefaultsTests` from `d39751a` (`#72`), already on `main` before this ticket. This ticket adds no Django test.
- PostgreSQL: 28 passed. That is the baseline 24 `pg` tests plus the four tests ANVIL-002 retagged. The same 28 IDs are `runs[0].excluded_ids` in `premerge.json`.
- Frontend: 249 passed. That is 15 above the baseline. ANVIL-002 records those 15 as UI tests that landed on `main` after `3200915`. This ticket changes `web/package.json` `engines` and `web/.nvmrc` only.

## Node.js 20

On the same SHA, with Node v20.20.2 first on `PATH`, `make premerge` returned in 0.061s. Process exit 2 (`make` reports a recipe error as status 2). The recipe exited 1 before any suite:

```
premerge requires Node.js 24; found v20.20.2.
Node.js 20 fails the frontend suite. Install Node.js 24, run `nvm use` from the repository root (.nvmrc), and run `make premerge` again.
```

Transcript: [node20.txt](node20.txt).

## Excluded by tag, then run on PostgreSQL

`--exclude-tag=pg` listed these 28 IDs. The Docker `--tag=pg` run executed all 28.

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

`fixture_tests_not_collected` on this host, where the fixture variables are unset:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

Those two are the pre-existing MLX and GGUF fixture tests. They were not runtime skips.

## Gate G-audit

`pip-audit -r <file>` with no ignore flags. pip-audit 2.10.1. Log: [pip-audit.txt](pip-audit.txt).

| File | Exit | Result |
| --- | --- | --- |
| requirements.txt | 0 | No known vulnerabilities found |
| requirements.audio.txt | 0 | No known vulnerabilities found |
| requirements.documents.txt | 0 | No known vulnerabilities found |
| requirements.embeddings.txt | 0 | No known vulnerabilities found |
| requirements.gpu.txt | 0 | No known vulnerabilities found |
| requirements.inference.txt | 0 | No known vulnerabilities found |
| requirements.production.txt | 0 | No known vulnerabilities found |
| requirements.selfhost.lock.txt | 0 | No known vulnerabilities found |
| requirements.tools.txt | 0 | No known vulnerabilities found |
| requirements.vision.txt | 0 | No known vulnerabilities found |
| requirements.specialists.txt | 1 | pip cannot resolve `mlx-metal==0.32.3` on Linux. Pre-existing. No ignore was added. |

## Gate G-secrets

Stock gitleaks 8.30.1. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`.

- `gitleaks dir . --redact` on the working tree: 404 findings, all rule `generic-api-key`, exit 1. Console: [gitleaks-dir.summary.txt](gitleaks-dir.summary.txt). Fingerprints match [the ANVIL-002 dir report](../anvil-002-2026-10-29/gitleaks-dir.txt).
- `gitleaks detect --redact` after this evidence directory was committed scanned 168 commits: 411 findings, all rule `generic-api-key`, exit 1. Console: [gitleaks-detect.summary.txt](gitleaks-detect.summary.txt). Fingerprints match [the ANVIL-002 history report](../anvil-002-2026-10-29/gitleaks-detect.txt).

A gitignored `web/storybook-static/` bundle from `build-storybook` added one extra `generic-api-key` hit while it was on disk. That directory is build output. It was removed before the recorded `gitleaks dir` scan. It is not in the commit.

No ANVIL-017 triage list is in the repository. The 404 and 411 findings are the pre-existing set.

## Gate G-rag

`premerge.json` stdout includes the existing `TASK69_CONTROLS` measurement: held-out nDCG real 1.0 next to seeded random 0.021535, on 200 documents. That is a small correctness check. The documented baseline next to it is MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact docs. The same control's development split in that line is real 0.982545. This ticket adds no RAG number.

## CI

`.github/workflows/ci.yml` is unchanged. Its jobs remain `backend`, `frontend`, and `pgvector`.
