# ANVIL-065 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3. Records use `docs/engineering/schemas/local-evidence.v1.json`. Test, check, audit, and gitleaks records were written by `.venv/bin/python scripts/local_evidence.py` or `scripts/premerge.py` from a clean `git status --porcelain`.

The measured tree is `5463f31acac575df313ad5e9f82f8791e7e7ff41`. This report is the following documentation commit. The commands below ran at `5463f31acac575df313ad5e9f82f8791e7e7ff41`. Adding these files changes the PR head by one commit.

Base: `origin/main` `4dd5060e632bae598003bf3a51a474709fe8c7ac`.

## Grant checks

`modelanvil/artifacts/test_worker_grants.py` calls `authorized_download` in process, with fixtures. `WorkerArtifactGrant.expires_at` is the existing expiry field, so expiry is in scope. No model field was added.

- A grant id that was never issued raises `NotFound`.
- A grant whose `expires_at` is in the past, while the execution lease is still current, raises `PermissionDenied` with detail `Artifact grant is no longer valid.`
- An issued grant yields that grant and the committed local artifact.
- `worker_access.py` has no helper that builds a presigned URL. The word `presigned` appears in the module docstring that states there is no upload or presigned URL. Query-string signature markers (`X-Amz-Signature`, `AWS4-HMAC-SHA256`, and the related names in the test) are absent.

`worker_access.py` was not edited. A missing grant already raises `NotFound`. The tests use the local filesystem backend. There is no live S3 call. `modelanvil/artifacts/tombstones.py`, `modelanvil/data/`, and `modelanvil/worker_agent.py` are unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:49:42+00:00 | `make premerge` | 0 | 1289 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1289, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:42:15+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:42:14+00:00 | `pip-audit -r` on every `requirements*.txt` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:40:58+00:00 | `gitleaks dir . --redact` | 1 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:41:01+00:00 | `gitleaks detect --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`premerge.json` was produced by this command, with Node 24.22.3 ahead of other Node binaries on `PATH`:

```sh
.venv/bin/python scripts/premerge.py --output /tmp/anvil065-evidence/premerge.json
```

`scripts/premerge.py` records the command as `make premerge`. Backend result: `Ran 1289 tests in 338.373s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 135.823s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password was the published CI password and is not in the record.

`make check` printed `System check identified no issues (0 silenced).`

## Counts against main `4dd5060`

Discovery with this interpreter, without executing the suite, on this SHA:

- `--exclude-tag=pg`: 1289 collected, including the four tests in `modelanvil.artifacts.test_worker_grants`.
- `--tag=pg`: 28 collected.

`git diff 4dd5060e632bae598003bf3a51a474709fe8c7ac` at the measured SHA changes `modelanvil/artifacts/test_worker_grants.py` and no other file. Main at `4dd5060` is that discovery minus these four tests: 1285 backend, 249 frontend, 28 PostgreSQL. That matches the executed counts ANVIL-012 recorded for the suite merged in `4dd5060`.

The executed premerge run on this SHA passed 1289, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The four added tests are `WorkerGrantAuthorizationTests.test_authorized_download_refuses_a_missing_grant`, `WorkerGrantAuthorizationTests.test_authorized_download_refuses_an_expired_grant`, `WorkerGrantAuthorizationTests.test_issued_grant_is_authorized_in_process`, and `WorkerAccessSourceTests.test_worker_access_does_not_build_a_presigned_url`. This ticket adds no frontend test and no `pg` test. `web/` is unchanged from `4dd5060`.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are listed on `premerge.json` as `fixture_tests_not_collected`. The same two IDs are absent on `4dd5060` without those variables.

## Gate G-local

Executed counts on this SHA are 1289 backend, 249 frontend, and 28 PostgreSQL. Each is equal to or above main `4dd5060` (1285, 249, 28). The increase is the four grant tests above.

## Gate G-skip

The premerge backend command is `manage.py test --noinput --exclude-tag=pg`. `premerge.json` lists the 28 excluded IDs. The PostgreSQL command is `manage.py test --noinput --tag=pg` and passed those 28. Every collected ID is in one of those two runs. Skipped, xfailed, and timeout are 0 in each executed run.

The 28 excluded IDs are:

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

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. Ten files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`.

`requirements.documents.txt` exited 1. `pypdf` 6.21.2 has CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. The reported fix versions are 6.21.3 and 6.21.4. That file is outside this ticket's edit list, the pin matches `4dd5060`, and no ignore was added. Those pypdf CVEs are owned by 042.

## Gate G-secrets

`gitleaks` 8.30.1, stock config. No `--config`, no baseline, no allowlist, and no `.gitleaks.toml`. The raw reports are not committed.

- `gitleaks dir --redact` on the working tree at `5463f31acac575df313ad5e9f82f8791e7e7ff41` exited 1 with 370 findings, all rule `generic-api-key`. None are in `modelanvil/artifacts/test_worker_grants.py`. The diff from `4dd5060` is that one file, so the 370 findings are the same set as main. Console: `gitleaks-dir.json`.
- `gitleaks detect --redact --log-opts=--all` scanned 206 commits and exited 1 with 781 findings. Findings on `5463f31acac575df313ad5e9f82f8791e7e7ff41`: 0. Findings on `4dd5060e632bae598003bf3a51a474709fe8c7ac`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 370. Those 370 hits are owned by 043. Console: `gitleaks-detect.json`.

`gitleaks dir` is not 0. It matches main. This ticket adds no finding and no allowlist.

After these evidence files were written, `gitleaks dir --redact` on `docs/engineering/verification/anvil-065-2026-11-12` exited 0.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is the existing small correctness check. This change does not claim a new retrieval number.

## Result

`make premerge` exited 0 with no runtime skip, xfail, or timeout. Counts are above main `4dd5060` by the four grant tests. `pip-audit` exits 1 on the unchanged `requirements.documents.txt` pin. `gitleaks dir` exits 1 with the same 370 findings as main. The pull request stays open.
