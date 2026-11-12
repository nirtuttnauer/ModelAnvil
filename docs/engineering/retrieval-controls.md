# Reproducible retrieval controls

The frozen public qualification compares the pinned MiniLM encoder with random unit vectors and the actual PostgreSQL full-text baseline. It evaluates document relevance separately from raw HNSW chunk-neighbor recall. Corpus/source-group selection, query counts, cutoffs, candidate overfetch, random seed, development threshold rules and ANN effort/filter grid are versioned in `modelanvil/rag/benchmark-protocol.json` before evaluation.

The original SciFact publisher archive and dated license are hash pinned in `benchmark-corpus-pins.json`. Claims/evidence use CC-BY-4.0; corpus abstracts use ODC-By-1.0 under the publisher's identified terms. Cite Wadden et al.2020, *Fact or Fiction: Verifying Scientific Claims*, EMNLP2020, doi:10.18653/v1/2020.emnlp-main.609. The report records license evidence and attribution.

## Run locally

Use a PostgreSQL database with pgvector>=0.8, apply migrations and install/cache the [fixed embedding runtime](embedding-indexes.md). Bootstrap only the pinned public corpus/license in a separate explicit operator action:

```sh
python -c "from modelanvil.rag.benchmark_corpus import cache_corpus; print(cache_corpus())"
python manage.py verify_retrieval_controls --output /absolute/new-report.json
```

`MODELANVIL_BENCHMARK_CACHE` selects a public cache directory (default `~/.cache/modelanvil/retrieval-benchmark`). The inference/evaluation command never downloads. Bootstrap refuses changed size/hash or redirects and preserves a mismatching existing cache. Choose a new directory rather than overwriting unknown bytes. Both the JSONL files and the fixed MiniLM files are checked before evaluation.

The command creates a fresh, temporary, unkeyed tenant/project for this run. It encodes actual source spans and queries locally, stores native pgvector rows, builds cosine HNSW indexes and runs exact/full-text/ANN SQL. Only its owned fixture tenant/corpus/indexes are removed, including on errors; existing tenants and data remain intact. Use an operator-controlled database with capacity for the declared bounded work. It does not use a paid provider or GPU. Existing output reports are never overwritten. A failed control gate still writes the measured report and returns a nonzero exit status.

## Interpretation

The subset contains200 documents and40 labeled queries split20/20 by source groups. Positive documents plus hash-selected distractors form a **closed bounded corpus**; this does not reproduce the complete SciFact leaderboard. Query/evidence groups do not cross development and held-out roles. The public pretrained encoder may have encountered public material during pretraining; no contamination-free pretraining assertion is made.

Relevance uses document cutoff5 after deduplicating up to20 chunk candidates. All modes share the same qrels and corpus. Random query/document vectors are independent normalized384-dimensional Gaussian controls. Full-text is the application's fixed simple tsvector/websearch/ts_rank_cd implementation, including its strict conjunctive query semantics. If it underfills, the report says so; it is not a tuned BM25 baseline. Metrics use the same denominator semantics as ordinary versioned qrels comparisons. Missing positive judgments yield N/A and are excluded from metric means.

The development maximum of random/full-text nDCG@5 freezes the minimum held-out relevance score. Development raw ANN recall chooses the smallest tested ef_search attaining0.95 mean neighbor overlap across all declared filters. Held-out relevance must exceed each control and the frozen development minimum. No model choice, data sampling, effort selection or threshold is changed using held-out results.

ANN recall is computed at10 **chunk** neighbors against exact SQL for effort10/40/100 and fixed100%/25%/5% memberships, five queries per role. The benchmark explicitly disables exact underfill fallback while measuring raw ANN. Production search keeps its default fallback and strict iterative scans. `ef_search`1–1000 is an optional query API field and appears in persisted execution receipts. A full result count does not prove ANN recall; document relevance is another independent measurement.

CI's required pgvector job caches verified public inputs, runs this actual test and uploads a commit-named JSON artifact even when a measured gate fails. It also checks the frozen plan, unrelated data retention and original SQL/HNSW/access boundaries. The [dated report](verification/task69-retrieval-controls-2026-10-23/report.md) is the evidence source; TASK73 owns generated README results and qualification on the final merged CI SHA.

## Expanded SciFact correctness check (ANVIL-020)

A second, larger set runs next to the 200-document result above. It does not replace or change it: `benchmark-corpus-pins.json`, `benchmark-protocol.json` and their report stay as they were. Policy `rag-expanded-corpus-v1` in [`scripts/rag-expanded-corpus-policy.json`](../../scripts/rag-expanded-corpus-policy.json) fixes the size, split, shards and threshold rules. It was committed alone before any measurement on this set. The size was proposed without QA and awaits QA sign-off.

- **Corpus**: all 5,183 SciFact abstracts from the same pinned publisher archive (ODC-By-1.0).
- **Held-out**: all 300 claims of `data/claims_dev.jsonl`, which is the BEIR SciFact test split (339 judgments, CC-BY-4.0 claims). Judgments are each claim's cited documents, as in BEIR. Rebuilt as BEIR qrels TSV, they equal BEIR's `test.tsv` byte for byte. That file is pinned by SHA256 but not committed or needed at run time.
- **Development**: the 531 training claims whose source group and normalized text share nothing with a held-out claim (600 judgments).
- **Shards**: a production local index holds at most 2,000,000 bytes of source text, and the corpus has 7,792,860. The check therefore builds five ordinary knowledge bases, chosen by a SHA256 rule. Each shard returns its top 20 chunks through the production `RetrievalEngine`. The candidates are merged by score, then chunk ID. For exact cosine search and `ts_rank_cd` full text this gives the same ranking as one index, apart from the order of exact ties. Production limits are unchanged.

The new pins are in [`modelanvil/rag/benchmark-expanded-pins.json`](../../modelanvil/rag/benchmark-expanded-pins.json): member SHA256, sizes, record counts and licenses, the rebuilt judgment digests, and the BEIR file's revision, SHA256 and card license. The frozen split and shard membership are in the [frozen plan](verification/anvil-020-2026-11-12/frozen-plan.json).

```sh
python -c "from modelanvil.rag.benchmark_corpus import cache_corpus; print(cache_corpus())"
# Optional one-time cross-check against BEIR test.tsv (downloads 5,389 pinned bytes):
python -c "import django; django.setup(); from modelanvil.rag.benchmark_expanded import cache_beir_qrels; print(cache_beir_qrels())"
python manage.py verify_expanded_retrieval --phase plan --beir-cross-check --output /absolute/new-plan.json
python manage.py verify_expanded_retrieval --phase development --output /absolute/development-report.json \
  --freeze docs/engineering/verification/<dir>/frozen-thresholds.json
git add docs/engineering/verification/<dir>/frozen-thresholds.json && git commit -m "Freeze the development thresholds"
python manage.py verify_expanded_retrieval --phase held_out --output /absolute/held-out-report.json \
  --thresholds docs/engineering/verification/<dir>/frozen-thresholds.json
```

The development phase evaluates only development queries. It sets the minimum relevance as the larger of the development random-vector and SQL full-text nDCG@5. It sets the ANN effort as the smallest `ef_search` with at least 0.95 mean neighbor recall in every filter. The held-out phase refuses to run unless the policy, the new pins, the frozen plan and the thresholds file are tracked and unchanged from HEAD, and it records the commit of each. It evaluates only held-out queries and passes only when MiniLM nDCG@5 is above the frozen minimum and above both held-out baselines. A failed run keeps its report and exits nonzero; nothing is re-run or retuned on held-out results. Each phase builds its own temporary tenant, five shards, MiniLM and random-vector indexes, and drops them afterwards, including its HNSW indexes.

Measured on 2026-11-12 as a **small correctness check**: held-out MiniLM nDCG@5 0.6243 next to the seeded random-vector baseline 0.0062 and the SQL full-text baseline 0.0154 on 300 queries over 5,183 documents (development: 0.6507, 0.0000 and 0.0132 on 531 queries). It is not a benchmark. Results are not comparable with published BEIR nDCG@10, because token chunks are deduplicated to documents at cutoff 5. The public encoder may have seen this public data during pretraining. The `pg`-tagged test rebuilds the frozen plan from the cached archive. The measurement itself runs as the explicit command above, not in the test suite. [Dated report](verification/anvil-020-2026-11-12/report.md).
