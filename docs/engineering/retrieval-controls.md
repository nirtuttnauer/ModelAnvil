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
