# TASK-69: frozen public retrieval controls

Date: 2026-10-23. Actual source commit **415abbfe29a04309c9e273589418be7c628b89d4**, after normally integrating PR42/main6faf417. Corpus/split/protocol were committed first in7d4e89a, before model results; implementation1182028 produced the first report. The final full PostgreSQL run repeated that protocol. Neither sampling nor thresholds were changed based on held-out metrics.

## Corpus, licensing and scope

The original publisher SciFact archive is pinned to SHA256 **11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be** (3,115,079 bytes). The publisher's [license snapshot](https://github.com/allenai/scifact/blob/a5254a1bf108726a1704d8e191b8a7f2225a029f/LICENSE.md) identifies claims/evidence as CC-BY-4.0 and corpus abstracts as ODC-By-1.0; its542-byte file is also hash pinned. Attribution: Wadden et al.2020, *Fact or Fiction: Verifying Scientific Claims*, EMNLP2020, doi:10.18653/v1/2020.emnlp-main.609. Raw corpus/query text is downloaded into the operator cache and temporary owned database, not committed here.

The frozen subset has **200 documents,412 actual token chunks,20 development and20 held-out queries**. Claims sharing cited/positive documents are grouped before a hash split. Required positives plus deterministic distractors define the closed corpus; query IDs, source groups and corpus IDs are recorded in [frozen-plan.json](frozen-plan.json). Normalized query duplicates cannot cross roles. This is an operator-held-out public subset, not the complete SciFact test benchmark or proof of uncontaminated model pretraining.

## Actual relevance comparison

All modes use identical held-out document qrels, document cutoff5, up to20 chunk candidates and document deduplication. The real encoder is fixed normalized384-dimensional MiniLM revision1110a243fdf4706b3f48f1d95db1a4f5529b4d41. Random document/query vectors are independent seeded Gaussian unit vectors. The full-text control is the production simple-config PostgreSQL tsvector/websearch/ts_rank_cd profile frozen in TASK68. Its conjunctive semantics returned no documents on these queries: this is a weak lexical control, not a tuned BM25 comparison.

| Mode | Judged/total | Relevance recall@5 | MRR@5 | nDCG@5 |
| --- | --- | --- | --- | --- |
| real | 20/20 | 1.0000 | 1.0000 | 1.0000 |
| random | 20/20 | 0.0500 | 0.0125 | 0.0215 |
| full_text | 20/20 | 0.0000 | 0.0000 | 0.0000 |

Development control maximum nDCG@5 was0.0; that minimum was frozen before held-out evaluation. The real model exceeded it and both held-out controls. Equal positive-qrels coverage is explicit; an unlabeled query has N/A metrics, excluded from means, with a separate software fixture proving that behavior. The fixture relevant A,B,C / retrieved B,X,A / K3 yields recall2/3, precision2/3 and MRR1, within the metric API's four-decimal rounding.

## Separate raw ANN-neighbor recall

This measures chunk-neighbor overlap against exact PostgreSQL cosine search, not relevance. Actual exact-underfill fallback is **disabled only for this measurement**. Production requests keep the fallback. Five queries per role are run for each effort/filter combination; HNSW m16/ef_construction64, strict iterative scans and20,000 visited-tuple bound are recorded. The smallest development-qualified effort was ef_search10 at minimum0.95 mean raw neighbor recall across every declared filter.

| Eligible chunks | ef10 held-out mean | ef40 held-out mean | ef100 held-out mean |
| --- | --- | --- | --- |
| 412 | 1.0000 | 1.0000 | 1.0000 |
| 111 | 1.0000 | 1.0000 | 1.0000 |
| 23 | 1.0000 | 1.0000 | 1.0000 |

Fresh HNSW graph construction can vary. Development selection and raw per-query neighbor IDs/counts remain in the report; no held-out effort tuning or universal recall/speed claim is made. Narrow filters retain only111 and23 of412 chunks. The actual API also accepts bounded ef_search1–1000 and persists the chosen effort in query receipts.

## Verification and reproduction

[Complete measured report](actual-report.json) includes input/qrels digests, fixed model/package pins, CPU architecture/thread count, PostgreSQL/pgvector versions, source commit, thresholds, every query rank and ANN observation. The final actual PostgreSQL suite passed **21 tests**, including the original real encoder/broker/candidate/SQL access tests and this public control rerun. The benchmark verifies an unrelated tenant/knowledge base survives while only its newly generated unkeyed fixture tenant/corpus/indexes are removed. Three clean software guards passed before the first model run. Full integrated backend: **1,034 passed, six optional skips**. Final clean RAG/chunking/OpenAPI/control guards: **37 passed**. Migration drift: **no changes detected**. Workflow YAML and commit-named report artifact wiring were checked.

CI caches the exact corpus/license, reruns the actual controls as a required pgvector test and retains `retrieval-controls-COMMIT` as a14-day artifact. Failed measured reports are preserved before the test fails. [Operator commands and limitations](../../retrieval-controls.md). No frontend layout was introduced, and no full-benchmark, customer quality, generation or CV-evidence claim is made by this ticket alone.
