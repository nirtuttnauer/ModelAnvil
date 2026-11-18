# ANVIL-083 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `5418657bcc06f07e96bce38dfe382218c3dcaa17`. This report is the following documentation commit. The commands below ran at `5418657bcc06f07e96bce38dfe382218c3dcaa17`.

`modelanvil/core/test_evaluation_gate.py` calls `gate_status` directly. A non-dict, a missing numeric accuracy, a negative `max_regression`, or a `production_qualified` value that is not exactly `False` returns 2. A missed regression returns 1. A report whose `decisive` value is not `True` returns 1 when `require_decisive=True`, and returns 0 when `require_decisive=False` if the accuracies pass. A passing decisive report with `production_qualified` set to `False` returns 0, and the helper leaves that dict unchanged. The tests assert status 2, and not 0, when `production_qualified` is `True`, so a change that returns 0 for that report fails the suite. `modelanvil/core/evaluation_gate.py` is unchanged. `modelanvil/core/test_trustworthy_roadmap.py` is unchanged.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T15:53:01+00:00 | `make premerge` | 0 | 1294 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1294, 249, 28 | 0 |
| `pip-audit.json` | 2026-11-12T15:46:23+00:00 | `bash /tmp/anvil083/pip-audit.sh` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T15:45:20+00:00 | `gitleaks dir . --redact --no-banner` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T15:45:21+00:00 | `gitleaks detect --source . --redact --no-banner --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`/tmp/anvil083/pip-audit.sh` runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`. It does not pass `--ignore-vuln`. Stdout records `exit 0` for each file. Stderr records `No known vulnerabilities found` eleven times.

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil083/premerge.json`. `scripts/premerge.py` records the command as `make premerge`. The `--output` path keeps the run from writing `docs/engineering/verification/anvil-009-2026-10-29/premerge.json`. Node v24.22.3 preceded other `node` binaries on `PATH`. Backend result: `Ran 1294 tests in 299.141s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, `duration_ms 2881.703713`, after `npm --prefix web ci`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 113.001s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The displayed pg command includes `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. `DATABASE_PASSWORD` is not in the record. `docker compose ... down -v --remove-orphans` ran at the end. Exit 0.

## Gate G-local

Label: `local`. Code SHA `5418657bcc06f07e96bce38dfe382218c3dcaa17`.

Discovery with this interpreter, without executing the suite, on this SHA:

- `--exclude-tag=pg`: 1294 collected, 0 decorator skips. Nine of those are `EvaluationGateTests` in `modelanvil/core/test_evaluation_gate.py`. The other 1285 are the suite at main `1d4ecd1a6f1a65f159649350be5c751645e0773a`.
- `--tag=pg`: 28 collected.

The executed premerge run passed 1294, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. Frontend stays at 249. PostgreSQL stays at 28. The backend difference from main `1d4ecd1` is the nine new tests:

- `test_non_dict_returns_2`
- `test_missing_numeric_accuracies_return_2`
- `test_negative_max_regression_returns_2`
- `test_flag_true_or_omitted_returns_2`
- `test_true_flag_stays_2_when_the_numbers_would_otherwise_miss`
- `test_missed_regression_returns_1`
- `test_regression_at_the_allowance_returns_0`
- `test_indecisive_report_returns_1_when_required_and_can_pass_when_not`
- `test_passing_report_returns_0_and_does_not_set_the_flag`

The local virtualenv had `requirements.txt`, `requirements.gpu.txt`, and the pins from `requirements.documents.txt`, `requirements.audio.txt`, `requirements.embeddings.txt`, `requirements.vision.txt`, `requirements.inference.txt`, and `pypdfium2==5.14.0`. Torch was `2.13.0+cpu`. Discovery on this SHA with that interpreter shows 0 decorator skips in the `--exclude-tag=pg` suite.

Two IDs were not collected, because this host has neither `MODELANVIL_MLX_TEST_MODEL_DIR` nor `MODELANVIL_GGUF_TEST_MODEL`:

- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption`
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload`

They are `fixture_tests_not_collected` on `premerge.json`. The same two IDs are absent on main `1d4ecd1` without those variables. Their bodies are unchanged.

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

Every ID collected on this host is in one of those two runs. The two fixture IDs above were not collected.

## Gate G-audit

`pip-audit` 2.10.1, `pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt`, with no `--ignore-vuln`. All 11 files exited 0 with `No known vulnerabilities found`: `requirements.audio.txt`, `requirements.documents.txt`, `requirements.embeddings.txt`, `requirements.gpu.txt`, `requirements.inference.txt`, `requirements.production.txt`, `requirements.selfhost.lock.txt`, `requirements.specialists.txt`, `requirements.tools.txt`, `requirements.txt`, `requirements.vision.txt`. Record: `pip-audit.json`. No ignore was added. `requirements.documents.txt` stays at `pypdf==6.21.4` from ANVIL-042. This ticket does not bump a dependency.

## Gate G-secrets

`gitleaks` 8.30.1. No `--config` argument, no new allowlist, and no baseline. The repository `.gitleaks.toml` from ANVIL-043 stays as it is and extends the default rules.

- `gitleaks dir . --redact` at `5418657bcc06f07e96bce38dfe382218c3dcaa17` scanned 34.76 MB and exited 0, `no leaks found`. Record: `gitleaks-dir.json`. That scan ran before `make premerge` wrote `web/storybook-static/`. The bundle is gitignored build output. It was removed after the run and is not in the commit. A later `gitleaks dir . --redact` on this tree, with these evidence files present and with `web/storybook-static/` removed, also exited 0, `no leaks found`.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 228 commits and exited 1 with 36 findings, all rule `generic-api-key`, none decoded. Record: `gitleaks-detect.json`. Findings on `5418657bcc06f07e96bce38dfe382218c3dcaa17`: 0. Every fingerprint is on `reviews/ANVIL-017-gitleaks-history.md`. None are on `75e2565a83b4b0cf96aebe793a9da6823e67d165`. The working-tree hits from that commit stay covered by the ANVIL-043 allowlist already on main. This ticket adds no allowlist.

File counts for the 36 history findings: `modelanvil/runners/training/hf_runtime.py` (7), `scripts/audio_candidate_infer.py` (7), `modelanvil/runners/training/vlm_math.py` (4), `modelanvil/runners/training/audio_runtime.py` (4), `scripts/vlm_candidate_infer.py` (4), `modelanvil/runners/training/audio_math.py` (3), `scripts/verify_cpu_export.py` (3), `docs/engineering/verification/manual-qa-2026-10-12/local-workflows.md` (1), `modelanvil/core/test_selfhost.py` (1), `modelanvil/rag/chunking.py` (1), `modelanvil/context_lab/test_context_lab.py` (1).

## Gate G-rag

This ticket adds no retrieval measurement. `premerge.json` stdout carries the suite's existing lines. They are labeled here so the log is not read as a new number.

- `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002` and SQL full text `0.0`, development nDCG real `0.982545` next to random `0.0`, on 200 SciFact documents and 412 chunks. That is the existing small correctness check. The documented baseline next to it is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries.
- The `ndcg@3`, `recall@3`, `precision@3`, `hit@3`, and `mrr@3` lines are the embedding-candidate unit-test fixture: hand-written passages and their development queries. They show the evaluation code path runs. They are a small correctness check on a toy fixture.

## Result

`make premerge` exited 0 with 1294 backend, 249 frontend, and 28 PostgreSQL tests, and with no runtime skip, xfail, or timeout. Backend is 9 above main `1d4ecd1` from `EvaluationGateTests`. Frontend and PostgreSQL match that baseline. `pip-audit -r` exited 0 on all 11 requirements files, with no ignore. `gitleaks dir` exited 0. Full-history `gitleaks detect` still reports the 36 `generic-api-key` findings already on the ANVIL-017 list. The pull request stays open.
