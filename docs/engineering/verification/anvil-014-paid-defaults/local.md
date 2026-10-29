# ANVIL-014 local verification

Label: `local`

This receipt records the checks for “nothing paid is enabled by default.”
ANVIL-002’s evidence schema and script were not in the tree, so this file follows the existing `docs/engineering/verification/` receipt practice and does not add or edit that schema or script.

The suite below ran at code SHA `8783dad88f3b7f5ab19a4305d7836b02bfc83adb` on branch `cursor/paid-defaults-proof-b1cb`. `git status --short` was empty at the start of the SQLite run and at the start of the PostgreSQL `--tag=pg` run. The commit that adds this receipt is docs-only and was not part of that SHA.

Baseline: `3200915506331979c712c17ffd0b1817f95fda75`

Machine: Linux cursor 6.12.94+ x86_64, Ubuntu 24.04, Python 3.12.3, Node v22.23.4, pip-audit 2.10.1, gitleaks 8.28.0. Date: 2026-10-29 UTC.

This ticket does not introduce a RAG number. Gate G-rag does not apply.

## Product checks

`modelanvil/core/test_paid_defaults.py` is a `unittest.TestCase`. Django’s DiscoverRunner collects it, and pytest collects it. pytest is not a project dependency. A one-off `python -m pytest modelanvil/core/test_paid_defaults.py -p no:cacheprovider -q` on this machine reported `4 passed in 0.55s`.

The same four tests passed inside the SQLite suite (`ok` at lines for `PaidDefaultsTests`).

What they assert:

- With a clean child environment, `MODELANVIL_PLUGINS`, `MODELANVIL_EXTERNAL_PROVIDERS`, and `MODELANVIL_EXTERNAL_PROVIDER_KEYS` default to `{}`. `MODELANVIL["artifact_backend"]` is `filesystem`. S3 endpoint, bucket, access key, and secret key are empty. `s3_region` stays the code default `us-east-1`.
- The load-time import graph of the golden-path and eval entry points does not import `modelanvil.compute.runpod` or `modelanvil.runners.external_inference`. Function-body imports are not edges. `modelanvil/api/views/model_workspace.py` loads the external client only when a view calls `_external_inference()`.
- No `requirements*.txt` names a paid-provider SDK (`openai`, `anthropic`, `cohere`, `groq`, `mistralai`, `together`, `fireworks-ai`, `replicate`, `runpod`, `modal`, `google-generativeai`, `google-cloud-aiplatform`, `vertexai`). `boto3` stays allowed. S3 being unset is the settings check.
- Every `runs-on` under `.github/workflows` is a standard GitHub-hosted runner label. `.github/workflows/ci.yml` was read only. It was not edited. Its three jobs use `ubuntu-latest`.

## G-local SQLite

Date: 2026-10-29T04:20:18Z. Host: Linux cursor 6.12.94+. SHA: `8783dad88f3b7f5ab19a4305d7836b02bfc83adb`. Clean git status.

Command:

```
DATABASE_NAME=/tmp/anvil014-dev.db DATABASE_TEST_NAME=/tmp/anvil014-sqlite.sqlite3 RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F /workspace/.venv/bin/python manage.py test --noinput --exclude-tag=pg -v 2
```

Result: Found 1266, Ran 1266 tests in 400.739s, `OK (skipped=5)`, EXIT 0.

Baseline at `3200915` collected 1237 tests with the same `--exclude-tag=pg` selector. Head is 29 collected cases above that baseline. `git grep` of `def test_` counts 1266 methods at the baseline and 1296 at this SHA (30 added, 0 removed). DiscoverRunner does not collect `scripts/`, so `scripts/test_beta_release_manifest.py::test_receipt_ignores_private_data_and_changes_with_source` is the added method that is not an extra collected case. The other 26 added methods landed on main after `3200915` and are not part of this ticket:

- `modelanvil/api/test_deployment_capabilities.py`: `test_requires_authentication`, `test_observed_capacity_and_role_do_not_grant_permission`
- `modelanvil/api/test_guided_evaluation.py`: 11 methods (`test_reviewed_native_manifest_detects_corrupt_weights_and_review`, `test_suite_uses_only_original_test_rows_and_full_task_labels`, `test_native_case_preserves_system_and_history_and_exact_label`, `test_classification_bounds_and_invalid_predictions_count_as_errors`, `test_loaded_native_session_is_reused_and_base_disables_adapter`, `test_known_cpu_evidence_survives_but_unknown_build_and_changed_bytes_fail`, `test_guided_preparation_refuses_non_guided_training_without_jobs_or_allowances`, `test_resource_report_uses_actual_timing_and_ledger_units_and_leaves_unknown_cost_unavailable`, `test_native_dispatch_report_and_exactly_once_accounting`, `test_cpu_worker_cannot_claim_native_profile_and_cancel_settles_zero`, `test_native_recovery_retains_pairs_and_does_not_repeat_committed_cases`)
- `modelanvil/api/test_model_workspace.py`: `test_provisioned_transformer_inference_does_not_connect_to_external_services`
- `modelanvil/core/test_trustworthy_roadmap.py`: 11 methods (`test_gpu_wall_stays_until_a_gpu_measurement_exists`, `test_cpu_report_can_raise_only_the_cpu_profile`, `test_measure_script_pins_match_the_runtime`, `test_ledger_text_matches_the_code_limits`, `test_small_samples_stay_inconclusive_and_a_thirty_case_loss_is_a_rejection`, `test_playbooks_fit_the_published_envelope_and_name_one_rejection`, `test_regression_gate_and_directory_rehearsal_do_not_qualify_production`, `test_failed_development_cases_train_later_and_cannot_enter_the_protected_test`, `test_viewers_can_read_the_ledger_and_paid_packaging_stays_closed`, `test_backlog_providers_cannot_be_selected`, `test_configured_mail_hides_the_reset_code`)

This ticket adds the four `PaidDefaultsTests` methods.

## G-local PostgreSQL `--tag=pg`

Date: 2026-10-29T04:34:05Z through 2026-10-29T04:35:57Z. Same SHA. Clean git status. PostgreSQL 16 with pgvector 0.8.1. RabbitMQ on 127.0.0.1:5672. Encoder, SciFact corpus, and SmolLM2-135M decoder caches were present.

Command:

```
DATABASE_ENGINE=postgresql DATABASE_NAME=modelanvil DATABASE_USER=modelanvil DATABASE_HOST=127.0.0.1 DATABASE_PORT=5432 RABBITMQ_URL=amqp://guest:guest@127.0.0.1:5672/%2F HF_HOME=/tmp/anvil014-hf MODELANVIL_BENCHMARK_CACHE=/tmp/anvil014-bench MODELANVIL_RAG_DECODER_CACHE=/tmp/anvil014-decoder MODELANVIL_RAG_GENERATION_REPORT=/tmp/anvil014-rag-generation.json MODELANVIL_POSITION_REPORT=/tmp/anvil014-positions.json MODELANVIL_RETRIEVAL_REPORT=/tmp/anvil014-retrieval.json PYTHONPATH=/workspace PYTHONDONTWRITEBYTECODE=1 DJANGO_SETTINGS_MODULE=modelanvil.settings /workspace/.venv/bin/python manage.py test --noinput --tag=pg -v 2
```

The database password was supplied in the environment and is not recorded here.

Result: Found 24, Ran 24 tests in 105.179s, `OK`, EXIT 0. No skips. The same 24 IDs are tagged `pg` at `3200915`.

Excluded from the SQLite run by `--exclude-tag=pg`, and executed in this run:

- `modelanvil.rag.test_pgvector.VectorExtensionTests.test_vector_extension_round_trip`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_all_tombstone_identities_and_wrong_resource_grants`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_exact_hnsw_plans_and_transaction_settings`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_grant_revocation_and_tenant_scope_on_already_created_queryset`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_narrow_membership_tombstones_and_revocations_stay_inside_ranking`
- `modelanvil.rag.test_sql_retrieval.SQLRetrievalTests.test_sql_full_text_rank_hybrid_and_parameters`
- `modelanvil.annotation.test_cycles.ConcurrentCampaignClosureTests.test_concurrent_closure_dispatches_one_snapshot_run_and_reservation`
- `modelanvil.annotation.test_feedback.ApplicationFeedbackConcurrencyTests.test_concurrent_inspection_and_clean_registration_cannot_both_commit`
- `modelanvil.annotation.test_feedback.ApplicationFeedbackConcurrencyTests.test_concurrent_retries_create_one_receipt_and_review_candidate`
- `modelanvil.api.test_team_access.ConcurrentInvitationTests.test_simultaneous_issue_allows_only_one_pending_invitation`
- `modelanvil.context_lab.test_positions.ActualPositionSweepTests.test_actual_pinned_model_repeats_positions_and_records_output_scoring`
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
- `modelanvil.rag.test_research.ActualPostgreSQLResearch.test_actual_keyword_retrieval_model_answer_compaction_and_revocation`

An earlier `--tag=pg` attempt on the same SHA failed in 10.7s because the host pgvector was 0.6.0 and the encoder, corpus, and decoder caches were empty. Those were host setup gaps. The run above is the one that counts.

## Frontend

Baseline worktree `3200915`, command `npm test` in `web/` (`node --test tests/*.test.mjs`): 234 tests, 234 pass, 0 fail, 0 skipped.

This SHA, same command, after `npm install --no-audit --no-fund` because `npm ci` cannot install: 249 tests, 249 pass, 0 fail, 0 skipped, duration_ms 2542.728532, exit 0. `web/package-lock.json` and `web/.storybook/static/mockServiceWorker.js` were restored afterward and are not part of this change.

Net +15. Sixteen names exist only at this SHA, and one baseline name is gone: “training and models pages provide in-product registration flows without API curl dead-ends”. The current tree has “the models page provides in-product registration flows without API curl dead-ends” plus fifteen other UI tests. Those names come from main after `3200915`. This ticket does not change `web/`.

`npm ci` in `web/` exits with `EUSAGE` because `package-lock.json` is missing `msw@2.15.0` and related packages. That drift predates this ticket. The lockfile was not rewritten.

## G-skip (fails, outside this ticket)

The required SQLite run skipped 5 tests. A skip is a G-skip failure. No skip was added or removed by this ticket.

Skipped on SQLite:

- `modelanvil.api.test_dataset_preparation.DatasetPreparationApiTests.test_concurrent_preparation_allocates_distinct_revisions_and_advances_to_latest` — `@skipUnless(postgresql)`, not tagged `pg`
- `modelanvil.budgets.test_concurrency.AccountingConcurrencyTests.test_simultaneous_callback_creation_returns_the_same_event` — `@skipUnless(postgresql)`, not tagged `pg`
- `modelanvil.compute.tests.ConcurrentAllocationTests.test_concurrent_replays_create_one_provider_resource_and_one_reservation` — `@skipUnless(postgresql)`, not tagged `pg`
- `modelanvil.runners.training.test_mlx_runtime.NativeAdapterModelTests.test_frozen_four_bit_base_actual_update_exact_resume_and_corruption` — requires `MODELANVIL_MLX_TEST_MODEL_DIR` and Metal. Not set on this Linux host.
- `modelanvil.runners.test_gguf_runtime.GGUFNative.test_actual_cpu_generation_cancellation_and_unload` — requires `MODELANVIL_GGUF_TEST_MODEL`. Not set.

The three PostgreSQL tests are outside `--tag=pg`, so the prescribed split never runs them. An extra local PostgreSQL invocation of those three IDs at the same SHA (2026-10-29T04:38:06Z) ran 3 tests in 1.208s, `OK`, EXIT 0. That extra run does not clear the SQLite skips, and it does not retag the tests. The MLX and GGUF cases were not given fixture paths. Setting those variables on this host would not make Metal or the pinned GGUF available.

## G-audit (fails, pre-existing)

`pip-audit -r <file>` with no ignore flags. pip-audit 2.10.1.

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
| requirements.specialists.txt | 1 | pip cannot resolve `mlx-metal==0.32.3` on Linux (`No matching distribution found`). Not recorded as a CVE. No ignore was added. |

## G-secrets (fails, outside this ticket)

Stock gitleaks 8.28.0. No `.gitleaks.toml`, no allowlist, no baseline. JSON reports stayed on the runner and are not committed, because they contain the matched strings.

- `gitleaks dir` on the working tree: 404 findings, all rule `generic-api-key`, 71 files, EXIT 1.
- `gitleaks detect` over 161 commits: 411 findings, all rule `generic-api-key`, 71 files, EXIT 1.

Most matches are under `docs/engineering/verification/`. Working-tree matches outside `docs/` (33 of 404): `scripts/audio_candidate_infer.py` (7), `modelanvil/runners/training/hf_runtime.py` (5), `scripts/vlm_candidate_infer.py` (4), `modelanvil/runners/training/vlm_math.py` (4), `modelanvil/runners/training/audio_runtime.py` (4), `scripts/verify_cpu_export.py` (3), `modelanvil/runners/training/audio_math.py` (3), `modelanvil/rag/chunking.py` (1), `modelanvil/core/test_selfhost.py` (1), `modelanvil/context_lab/test_context_lab.py` (1). History adds two more hits in `hf_runtime.py`.

No ANVIL-017 QA-signed triage list is in the repository. Every finding is therefore off that list. No allowlist was added.

## Merge

The pull request stays open. Shared gates that fail for reasons outside this ticket: G-skip (pre-existing skips, including untagged PostgreSQL tests and MLX/GGUF fixtures this host cannot run), G-secrets (gitleaks findings and no ANVIL-017 triage list), and G-audit (`requirements.specialists.txt` cannot resolve `mlx-metal` on Linux). `npm ci` also fails on a pre-existing lockfile drift. This ticket’s four checks passed.
