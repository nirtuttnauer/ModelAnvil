# ANVIL-073 local evidence, 12 November 2026

Label: `local`. Machine: `cursor`, Linux-6.12.113+-x86_64-with-glibc2.39, Python 3.12.3, Node v24.22.3, pip-audit 2.10.1, gitleaks 8.30.1. Records use `docs/engineering/schemas/local-evidence.v1.json`. `git status --porcelain` was empty when each command started. Node v24.22.3 preceded other `node` binaries on `PATH`.

Base: `origin/main` `1d4ecd1a6f1a65f159649350be5c751645e0773a`.

The measured tree is `cc1ff5db9c47b567d2ca1cf674ebcd5cd0abd8c4`. This report is the following documentation commit. The commands below ran at `cc1ff5db9c47b567d2ca1cf674ebcd5cd0abd8c4`.

`modelanvil/core/test_privacy_destinations.py` is the change under test. `modelanvil/core/privacy.py` is unchanged. `require_destination` already refuses a destination that is not in the installed acquisition allowlist, and `open_acquisition` calls that gate before it builds an opener. The tests lock that behavior with mocks. No live connection is made: `socket.create_connection` and `socket.getaddrinfo` raise if called.

## What the tests cover

- `require_destination('http://evil.example')` raises `PrivacyRefused`.
- `require_destination('https://203.0.113.5/weights.bin')` raises `PrivacyRefused` and the message names `https://203.0.113.5` as not allowed. That address is a documentation prefix and is not in `MODELANVIL_ACQUISITION_ORIGINS`.
- `require_destination('https://huggingface.co/org/model')` returns `https://huggingface.co`. That origin is in the installed allowlist the acquisition helpers already consult.
- `open_acquisition` raises `PrivacyRefused` for `http://evil.example/weights.bin` and `https://203.0.113.5/weights.bin` before `OpenerDirector.open`.
- `open_acquisition` of `https://huggingface.co/org/model` returns the mocked body. The opener is called with that URL and `timeout=1`.
- A redirect to `http://evil.example/file` or `https://203.0.113.5/file` raises `PrivacyRefused`. A redirect to `https://cdn-lfs.huggingface.co/file` is returned, and the `Range` header is kept. That origin is also in the installed allowlist.

`MODELANVIL_OFFLINE` is forced off for these tests so an allowed origin is not refused for the offline reason.

## Records

| File | Recorded at | Command | Exit | Collected | Excluded by tag | Passed | Skipped / xfail / timeout |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `premerge.json` | 2026-11-12T14:54:09+00:00 | `make premerge` | 0 | 1291 backend, 249 frontend, 28 PostgreSQL | 28 on the backend run | 1291, 249, 28 | 0 |
| `make-check.json` | 2026-11-12T14:44:51+00:00 | `make check` | 0 | 0 | 0 | 0 | 0 |
| `pip-audit.json` | 2026-11-12T14:57:02+00:00 | `pip-audit --progress-spinner=off -r` on every root `requirements*.txt` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-dir.json` | 2026-11-12T14:44:53+00:00 | `gitleaks dir . --redact` | 0 | 0 | 0 | 0 | 0 |
| `gitleaks-detect.json` | 2026-11-12T14:44:55+00:00 | `gitleaks detect --source . --redact --log-opts=--all` | 1 | 0 | 0 | 0 | 0 |

`make premerge` was `.venv/bin/python scripts/premerge.py --output /tmp/anvil073/premerge.json`. The record's command field is `make premerge`. Backend result: `Ran 1291 tests in 365.776s` then `OK`. Frontend: `tests 249`, `pass 249`, `fail 0`, `skipped 0`, then a production build and a Storybook build. PostgreSQL: `Ran 28 tests in 130.842s` then `OK`, against `pgvector/pgvector:pg16` and `rabbitmq:4.1-alpine`. The database password is the published CI password and is not in the record. `HF_HUB_OFFLINE=1` was set for that run after the pinned caches were filled.

`make check` printed `System check identified no issues (0 silenced).`

The audit command was `/tmp/anvil073/pip-audit.sh`. It runs `.venv/bin/pip-audit --progress-spinner=off -r <file>` for every root `requirements*.txt` and does not pass `--ignore-vuln`. Stdout records `exit 0` for each file. Stderr records `No known vulnerabilities found` for each file.

## Gate G-local

Label: `local`. Code SHA `cc1ff5db9c47b567d2ca1cf674ebcd5cd0abd8c4`.

Discovery with this interpreter, without executing the suite:

- `1d4ecd1a6f1a65f159649350be5c751645e0773a`, `--exclude-tag=pg`: 1285 collected.
- This SHA, `--exclude-tag=pg`: 1291 collected.
- Both SHAs, `--tag=pg`: 28 collected.

The executed premerge run on this SHA passed 1291, 249, and 28, with 0 skipped, 0 xfailed, and 0 timeout. The six added tests are `AcquisitionDestinationTests.test_open_acquisition_accepts_an_installed_origin_without_a_live_connection`, `AcquisitionDestinationTests.test_open_acquisition_refuses_unexpected_destinations_before_connecting`, `AcquisitionDestinationTests.test_redirect_refuses_an_unexpected_next_hop_and_accepts_an_installed_one`, `AcquisitionDestinationTests.test_require_destination_accepts_an_installed_origin`, `AcquisitionDestinationTests.test_require_destination_refuses_a_literal_ip_outside_the_allowlist`, and `AcquisitionDestinationTests.test_require_destination_refuses_an_unexpected_http_host`. This ticket adds no frontend test and no `pg` test.

Counts against main `4dd5060e632bae598003bf3a51a474709fe8c7ac`: the ANVIL-042 premerge record on that history passed 1285 backend tests, 249 frontend tests, and 28 PostgreSQL tests. This run passed 1291, 249, and 28. Each count is equal to or above that record.

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

`requirements.documents.txt` pins `pypdf==6.21.4`. That pin is the ANVIL-042 fix for CVE-2026-119203, CVE-2026-119204, CVE-2026-119205, CVE-2026-119206, CVE-2026-119207, CVE-2026-119208, and CVE-2026-119209. This run does not report those CVEs. No ignore was added.

## Gate G-secrets

`gitleaks` 8.30.1. The repository `.gitleaks.toml` from ANVIL-043 is loaded by default. This ticket does not edit that file and does not add an allowlist.

- `gitleaks dir . --redact` at `cc1ff5db9c47b567d2ca1cf674ebcd5cd0abd8c4` exited 0, `no leaks found`, 28.25 MB. Record: `gitleaks-dir.json`. The scan ran before `make premerge` wrote `web/storybook-static/`. That build output is gitignored and is not in the commit.
- `gitleaks detect --source . --redact --log-opts=--all` scanned 224 commits and exited 1 with 36 findings, all rule `generic-api-key`. Findings on `cc1ff5db9c47b567d2ca1cf674ebcd5cd0abd8c4`: 0. Findings on `75e2565a83b4b0cf96aebe793a9da6823e67d165`: 0 under this config. The 36 are the same files and counts ANVIL-043 left in history: `modelanvil/runners/training/hf_runtime.py` (7), `scripts/audio_candidate_infer.py` (7), `modelanvil/runners/training/vlm_math.py` (4), `modelanvil/runners/training/audio_runtime.py` (4), `scripts/vlm_candidate_infer.py` (4), `modelanvil/runners/training/audio_math.py` (3), `scripts/verify_cpu_export.py` (3), `docs/engineering/verification/manual-qa-2026-10-12/local-workflows.md` (1), `modelanvil/core/test_selfhost.py` (1), `modelanvil/rag/chunking.py` (1), `modelanvil/context_lab/test_context_lab.py` (1). Record: `gitleaks-detect.json`. The raw finding report is not committed.

The 370 working-tree hits on `75e2565a83b4b0cf96aebe793a9da6823e67d165` are the decoded-digest `generic-api-key` set triaged by ANVIL-043. This ticket does not reopen that allowlist.

`gitleaks dir docs/engineering/verification/anvil-073-2026-11-12 --redact` exited 0, `no leaks found`.

## Gate G-rag

`premerge.json` stdout includes the existing control `TASK69_CONTROLS`: held-out nDCG real `1.0` next to seeded random `0.021535000000000002`, on 200 documents and 412 chunks. Development nDCG real in that same object is `0.982545`. That is a small correctness check. The documented baseline next to it, from `README.md`, is MiniLM nDCG@5 `1.0000` next to seeded random `0.0215` on 20 judged queries and a closed 200-document SciFact subset. This change does not claim a new RAG number.

## Result

Unexpected acquisition destinations are refused with `PrivacyRefused` before a connection. An installed origin is accepted. `make premerge` exited 0 with no runtime skip, xfail, or timeout. `pip-audit` exited 0 on every root requirements file. `gitleaks dir` exited 0. The pull request stays open.
