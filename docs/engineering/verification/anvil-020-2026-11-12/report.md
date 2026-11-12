# ANVIL-020: expanded SciFact RAG correctness check on CPU

Date: 2026-11-12. Machine: Apple M5 Pro, 18 CPU cores, 48 GiB, macOS (Darwin 27.0.0 arm64), Python 3.12.15. CPU only, one torch thread, no GPU, no paid provider ($0). Label: `local`.

**This is a small correctness check, not a benchmark.** It is a larger public set run next to the existing 200-document / 20-query result, which is unchanged. The numbers are not comparable with published BEIR SciFact nDCG@10, because token chunks are deduplicated to documents at cutoff 5.

**The size awaits QA sign-off.** QA had not set a size. The implementing agent proposed it and froze it in a new policy before any measurement. Nir may change it. A change gets a new policy id and its own commit before any new measurement.

## Results next to both baselines

All rows are nDCG@5 on the full 5,183-document SciFact corpus (9,765 token chunks in five shards), with document cutoff 5 after deduplicating up to 20 merged chunk candidates.

| Small correctness check, nDCG@5 | Development (531 queries, 600 judgments) | Held-out (300 BEIR SciFact test queries, 339 judgments) |
| --- | --- | --- |
| MiniLM (pinned all-MiniLM-L6-v2) | 0.6507 | **0.6243** |
| Seeded random-vector baseline | 0.0000 | 0.0062 |
| SQL full-text baseline | 0.0132 | 0.0154 |

Held-out result: **passed**. The rule was frozen before the run: MiniLM had to be above the frozen minimum relevance 0.0132 and above both held-out baselines.

Other metrics at cutoff 5:

| Phase | Mode | Recall@5 | Precision@5 | Hit@5 | MRR@5 | Queries returning any document |
| --- | --- | --- | --- | --- | --- | --- |
| development | MiniLM | 0.7296 | 0.1623 | 0.7533 | 0.6332 | 531/531 |
| development | random-vector | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 531/531 |
| development | SQL full-text | 0.0132 | 0.0026 | 0.0132 | 0.0132 | 12/531 |
| held-out | MiniLM | 0.7352 | 0.1613 | 0.7500 | 0.5922 | 300/300 |
| held-out | random-vector | 0.0100 | 0.0020 | 0.0100 | 0.0050 | 300/300 |
| held-out | SQL full-text | 0.0167 | 0.0033 | 0.0167 | 0.0150 | 5/300 |

The SQL full-text baseline is the production simple-config `websearch_to_tsquery` / `ts_rank_cd` profile, untuned. Its conjunctive semantics return nothing for most whole-claim queries, so it is a weak lexical control, not a tuned BM25 comparison. The same small correctness check on the original set remains MiniLM nDCG@5 1.0 next to seeded random 0.0215 on 20 queries / 200 SciFact documents.

## Size and why

Policy `rag-expanded-corpus-v1`, [`scripts/rag-expanded-corpus-policy.json`](../../../../scripts/rag-expanded-corpus-policy.json):

- **Corpus**: all 5,183 abstracts of `data/corpus.jsonl` (7,792,860 bytes of title and abstract text).
- **Held-out**: all 300 claims of `data/claims_dev.jsonl`, which is the BEIR SciFact test split. It has 339 judgments over 283 documents. Judgments are each claim's cited documents, as in BEIR.
- **Development**: the 531 claims of `data/claims_train.jsonl` whose source group contains no held-out claim and whose normalized text differs from every held-out claim. They have 600 judgments over 372 documents. Of the 809 training claims, 278 were excluded.
- **Why this size**: It is the largest judged set in the publisher archive that was already pinned, so the corpus needed no new download and the license terms are unchanged. The held-out split is the published BEIR test split, which this project did not choose. It runs on CPU at $0. Before any relevance result, MiniLM was timed at about 70 chunks per second on one thread over 221 chunks. The measured chunk embedding then took 139 s (development) and 135 s (held-out).
- **Shards**: a production local index holds at most 2,000,000 bytes of active source text (`modelanvil/rag/ingestion.py`), so the corpus does not fit in one index. Five ordinary knowledge bases are chosen by `int(SHA256('shard:'+doc_id)[:8],16) % 5`. No production limit changed. Each shard returns its top 20 chunks through the production `RetrievalEngine`. The candidates are merged by score, then chunk ID. For exact cosine and `ts_rank_cd` this is the same ranking as one index, apart from the order of exact ties. A guard test checks the merge.

| Shard | Documents | Source text bytes | Token chunks |
| --- | --- | --- | --- |
| 0 | 1,043 | 1,577,158 | 1,975 |
| 1 | 1,008 | 1,493,770 | 1,878 |
| 2 | 1,025 | 1,548,097 | 1,931 |
| 3 | 1,042 | 1,592,906 | 2,002 |
| 4 | 1,065 | 1,580,929 | 1,979 |

## Pins and licenses

Old pins are kept. `modelanvil/rag/benchmark-corpus-pins.json`, `benchmark-protocol.json`, `benchmark.py`, `benchmark_corpus.py`, `test_benchmark.py`, `rag-reproduction-policy.json` and `rag-answer-format-policy.json` are byte-identical to `origin/main` 4219b90. The new pins are in [`modelanvil/rag/benchmark-expanded-pins.json`](../../../../modelanvil/rag/benchmark-expanded-pins.json) (id `scifact-full-beir-test-v1`).

| Pinned input | SHA256 | Bytes | Records | License |
| --- | --- | --- | --- | --- |
| Publisher archive `data.tar.gz` (unchanged v1 pin) | `11c62128 8d41ac14 4d29b13b 0f8503b3 820b7d6e 8b1f6ff2 4dff335c 196d76be` | 3,115,079 | | |
| Publisher `LICENSE.md` at allenai/scifact a5254a1 (unchanged v1 pin) | `56ee69bc 639cbab8 f0b2e4b6 7091ec5e 9390aa99 a1d65f0a 35e42746 86c9a806` | 542 | | |
| `data/corpus.jsonl` | `b8d6c896 24cb2ed7 4dee8938 effc4f5d 8bd20868 87880af8 110d64be 4ceade62` | 8,307,875 | 5,183 | ODC-By-1.0 |
| `data/claims_train.jsonl` (development) | `f4c8fa82 d8bd0653 a9cc8d61 a6ea48c2 5eacea64 e90af5db f390ebb1 b74372f0` | 175,616 | 809 | CC-BY-4.0 |
| `data/claims_dev.jsonl` (held-out) | `86f0435d 08fdb65d 1aa41d14 72684f57 e6e71930 626497bd f4d7a9ec 1a632217` | 65,007 | 300 | CC-BY-4.0 |
| Held-out qrels rebuilt from the claims (BEIR TSV) | `0864bb98 5e0ca236 7ba21797 7e72004d 549054b2 b06666ed 9d4825ac 7c21284c` | 5,389 | 339 | CC-BY-4.0 (derived) |
| Development qrels rebuilt from the claims (BEIR TSV) | `d93e6148 9e1736ba 43f8bbc8 31739603 ad4e9d5f 6cdfce20 c781e8bb 061727cf` | 9,464 | 600 | CC-BY-4.0 (derived) |
| BEIR `test.tsv`, Hugging Face `BeIR/scifact-qrels` revision `2938d17dc3b09882fdb8c12bbbe2e2dc0e75a029`, git blob `c62f58c75f10c0cee23483b7269bff2902ae4080` | same as the rebuilt held-out qrels | 5,389 | 339 | cc-by-sa-4.0 per card metadata |
| BEIR card `README.md` at the same revision, git blob `bc58b6940a415a26e38244f8c688ff5ef134abf0` | `fd34a283 0e557f1e 32d46d0b 34a218d2 80c9800e e4071579 610d4ff5 87b4fd45` | 13,995 | | |

Sources: archive `https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`. BEIR file `https://huggingface.co/datasets/BeIR/scifact-qrels/raw/2938d17dc3b09882fdb8c12bbbe2e2dc0e75a029/test.tsv`, downloaded without redirects. Its git blob ID matches the dataset tree at that revision. The rebuilt held-out judgments equal BEIR's `test.tsv` byte for byte (`BEIR_CROSS_CHECK ... "identical_bytes": true, "matches_pin": true`). The BEIR card's YAML says cc-by-sa-4.0, and its Licensing Information section says "Needs More Information". The BEIR file is therefore used only as a cache-only cross-check: it is not committed, redistributed or read at run time. The committed plan and the measured judgments come from the publisher claims (CC-BY-4.0). Raw corpus and claim text stay in the operator cache and the temporary database. Attribution: Wadden et al. (2020), *Fact or Fiction: Verifying Scientific Claims*, EMNLP 2020, doi:10.18653/v1/2020.emnlp-main.609; Thakur et al. (2021), *BEIR*, NeurIPS 2021 Datasets and Benchmarks. Encoder: sentence-transformers/all-MiniLM-L6-v2 revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 (Apache-2.0), the existing `embedding-pins.json`.

## Commit order (freeze before measurement)

| Step | Commit | Content |
| --- | --- | --- |
| 1 | `98d8616ef7b416a5059a1d9b0aad2b02e6db0740` | Policy `rag-expanded-corpus-v1` alone: size, split, shards, threshold rules. No measurement. |
| 2 | `de8dcb9a2fe9385c1904f385655dd708420b38b1` | New pins, the [frozen plan](frozen-plan.json) (split, judgments, shard membership; no claim text), the command and the guards. No retrieval result. |
| 3 | `a0e2b437cb30be1cdee0d210974562a67fd91187` | Fix: four corpus titles (up to 300 characters) exceed the 255-character `SourceDocument.title`. The stored title keeps 255 characters; the indexed content keeps the full title. The first development attempt at step 2 stopped on this insert while ingesting shard 0. It ran no embedding, query or metric and wrote no report. |
| 4 | `44e7a9ebd6874abbf84e27c732845c2653adc06c` | [Frozen thresholds](frozen-thresholds.json) and the [development report](development-report.json) from the development run at step 3. No held-out query had been evaluated. |
| 5 | this evidence commit | [Held-out report](held-out-report.json), this report, docs and the README block. |

The held-out phase ran once, at step 4, with a clean `git status`. It refused to start unless the policy, pins, plan and thresholds files were tracked and unchanged from HEAD. It recorded their commits in the report: policy 98d8616, pins and plan de8dcb9, thresholds 44e7a9e. Nothing was re-run, retuned or changed after the held-out result.

Frozen thresholds, from development only: minimum relevance **0.013182674199623353**, the larger of development random-vector 0.0 and development SQL full-text 0.0132. ANN effort: **ef_search 40**, the smallest effort with at least 0.95 mean development neighbor recall in every filter.

Digests: policy file `0e6f6023 b66b8eb0 8e6686eb 2d828b15 a23c639d cc5307df 89172630 6dc7592c`; new pins file `764f3df7 28120992 3e75ff2e 1dafff27 284d54c6 879a6c9a d0526fd2 dc9fba39`; frozen plan file `f7f31f74 787421cd 73658f92 6cbc20c1 fea5b0a5 6890bdc1 7fdc879a 1364f63c`; plan digest (canonical JSON) `7e552dea 79dd838f a1fb66bf 30eb525b 028b7289 ccf66e98 8f1a05cc b74adaa7`; development report `d05b7e54 5310caf1 1b7c6a0b e6427b04 98148dcc 266a9dfd 3e20e296 aa9f2c73` (recorded in the thresholds file); thresholds file `46012bba c36be918 c4bc2c48 11d0f703 7e03e453 a4ab3d65 de435120 515fc644`; held-out report `08b68bae 43598524 5f9b5e8a a1a16a3b 8e99ca0e c6d849b5 a81bee5a 55fcb9cf`.

## Raw ANN chunk-neighbor recall

This is separate from relevance. Each value is mean recall@10 against exact SQL inside each shard, averaged over 20 queries times 5 shards. Exact underfill fallback was disabled for this measurement only and was never used. Settings: HNSW m 16, ef_construction 64, strict iterative scan, 20,000 maximum scanned tuples.

| Filter | Eligible chunks | Dev ef10 | Dev ef40 | Dev ef100 | Held-out ef10 | Held-out ef40 | Held-out ef100 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 100% | 9,765 | 0.933 | 0.990 | 1.000 | 0.930 | 0.993 | 0.998 |
| 25% | 2,504 | 0.941 | 0.975 | 0.995 | 0.928 | 0.974 | 0.995 |
| 5% | 482 | 0.978 | 0.981 | 0.992 | 0.964 | 0.982 | 0.993 |

Held-out ANN results are reported, not used for selection. A fresh HNSW graph can vary between runs.

## Commands and exit codes

The environment matched `scripts/premerge.py`: `compose.premerge.yaml` db (`pgvector/pgvector:pg16`; PostgreSQL 16.15, pgvector 0.8.7) and rabbitmq under the project name `modelanvil-anvil020`, with `pg_test_env` variables. Caches: `HF_HOME` held the pinned MiniLM files and `MODELANVIL_BENCHMARK_CACHE` held the pinned archive and license; both are verified by hash at run time. Interpreter: the `anvil-gates` worktree `.venv` Python 3.12.15, `PYTHONPATH=<worktree>`, `DJANGO_SETTINGS_MODULE=modelanvil.settings`. Every compose and test sequence ran inside the host test lock and ended with `docker compose down -v --remove-orphans` (exit 0 each time).

| When (UTC) | Command | Exit |
| --- | --- | --- |
| before step 2 | `python -c "...benchmark_expanded import cache_beir_qrels; print(cache_beir_qrels())"` | 0 |
| before step 2 | `python manage.py verify_expanded_retrieval --phase plan --beir-cross-check --output docs/engineering/verification/anvil-020-2026-11-12/frozen-plan.json` | 0 |
| 20:16 at de8dcb9 | `python manage.py test modelanvil.rag.test_benchmark_expanded --exclude-tag=pg --noinput -v 2` (SQLite): 7 tests OK | 0 |
| 20:16 at de8dcb9 | PostgreSQL `manage.py migrate --noinput`, then `manage.py test modelanvil.rag.test_benchmark_expanded modelanvil.rag.test_benchmark --noinput -v 2`: 12 tests OK | 0, 0 |
| 20:16 at de8dcb9 | `manage.py verify_expanded_retrieval --phase development ...` stopped on the title insert (see step 3); no report | 1 |
| 20:20 at a0e2b43 | SQLite guards, 8 tests OK | 0 |
| 20:20 at a0e2b43 | PostgreSQL migrate, then the two modules above: 13 tests OK, including the `pg` plan rebuild and the unchanged TASK-69 control rerun | 0, 0 |
| 20:21–20:38 at a0e2b43 | `manage.py verify_expanded_retrieval --phase development --output <scratch>/development-report.json --freeze <scratch>/frozen-thresholds.json` (1,021.7 s) | 0 |
| 20:44–20:53 at 44e7a9e | `manage.py verify_expanded_retrieval --phase held_out --output <scratch>/held-out-report.json --thresholds docs/engineering/verification/anvil-020-2026-11-12/frozen-thresholds.json` (542.7 s) | 0 |

Both reports were copied byte for byte into this directory. Command summaries:

```text
ANVIL020_DEVELOPMENT {"label": "small correctness check", "phase": "development", "queries": 531, "documents": 5183, "chunks": 9765, "ndcg@5": {"real": 0.6507020715630886, "random": 0.0, "full_text": 0.013182674199623353}, "thresholds": {"minimum_relevance": 0.013182674199623353, "chosen_ef_search": 40, "source": "development baselines and development ANN only"}, "elapsed_seconds": 1021.67, "ready_to_freeze": true}
ANVIL020_HELD_OUT {"label": "small correctness check", "phase": "held_out", "queries": 300, "documents": 5183, "chunks": 9765, "ndcg@5": {"real": 0.6242946666666667, "random": 0.006204666666666667, "full_text": 0.015436333333333335}, "thresholds": {"minimum_relevance": 0.013182674199623353, "chosen_ef_search": 40, "source": "development baselines and development ANN only"}, "elapsed_seconds": 542.678, "passed": true}
```

Phase timings in seconds (development / held-out): index documents 19.6 / 17.2; embed chunks 138.7 / 135.0; vector indexes 8.3 / 7.0; relevance 781.9 / 322.2; ANN 72.0 / 60.7. The 20-minute budget held, but development came within three minutes of it. Most of the time goes to per-shard SQL relevance queries, not to the model.

## Tests added

`modelanvil/rag/test_benchmark_expanded.py`, run with the Django runner:

- `ExpandedCorpusGuards` (8, SQLite and PostgreSQL). The new policy and pins keep the v1 archive pin and 200-document protocol. Every test claim is held out, and source groups and normalized texts do not cross. The judgments use the BEIR qrels byte layout. Long titles fit the field and stay in the indexed content. The shard merge equals one ranking over all chunks. Frozen inputs must be committed and unchanged (temporary git repository). Digests are stored as JSON unicode escapes. Only a qualified development report can be frozen.
- `ExpandedPublicPlan` (1, tagged `pg`, because it needs the cached archive that the PostgreSQL environment provides). The pinned members rebuild the committed frozen plan exactly, and the rebuilt held-out judgments have the BEIR `test.tsv` SHA256.

The measurement itself is an explicit operator command, not a test, so the shared `pg` suite gains only the plan rebuild, not the 17-minute measurement. The shared G-local, G-skip, G-audit and G-secrets gates are run by the orchestrator, not recorded here.

## Secret scan

Stock gitleaks 8.28.0, `gitleaks dir <path> --config stock-8.28.0.toml --no-banner`, with no allowlist or baseline, was run on every new or changed file. Every scan reported "no leaks found", exit 0. 64-hex digests are stored in JSON as JSON unicode escapes and written in Markdown as 8-character groups.

## Limits

- This is public data that the public pretrained encoder may have seen during pretraining. No contamination-free claim is made.
- The check uses five shards with an exact merge, not one production index. ANN recall is measured per shard.
- The SQL full-text baseline is weak by construction (conjunctive whole-claim queries).
- The results are not a leaderboard, a BEIR reproduction, a customer quality result or a general retrieval quality result. They are not compared with published BEIR numbers.
- The size awaits QA sign-off.
