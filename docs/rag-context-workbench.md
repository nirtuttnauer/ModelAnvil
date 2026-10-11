# ModelAnvil RAG and context engineering workbenches

Product and integration specification | 8 October 2026 | Planning baseline for PRD 0.6

ModelAnvil will let teams build a retrieval application, test how context is assembled, investigate failures, and release a reproducible configuration. This specification supports PRD requirements RAG01–RAG08 and CTX01–CTX04. It describes proposed behavior and qualification evidence; no integration is implemented. A named text recipe is required for the first complete release. Multimodal retrieval, graph retrieval, and autonomous agent orchestration are later targets.

## Workflow and shared records

The RAG path is source import → extraction and permission mapping → chunks → embeddings and index → retrieval → reranking → context assembly → generation → evaluation → release. The direct context path begins with a registered model and context recipe and can run without a knowledge base. Both paths share the evaluation registry, worker protocol, budgets, and release evidence.

Each source chunk needs a stable ID, source revision, content hash, page/span location, language, and access scope. A changed chunk receives a new revision; evaluation judgments retain their original source evidence and require a mapped version for comparisons across chunking strategies. Dataset Bank imports can be selected as sources, but a dataset's open license alone does not make it suitable for retrieval or automatically index it. Private authorized corpora remain private.

An embedding set records model and tokenizer revisions, license, dimensions, normalization, document/query encoding, and distance function. Index versions link this set to chunk manifests, backend settings, build attempts, and completeness checks. A pipeline release pins the index, retrieval rules, optional reranker, context recipe, generator, and evaluation report. Permission and deletion overlays are current authorization state; restoring a content version cannot undo them.

## Retrieval and answer implementation

Start with PostgreSQL full-text search and pgvector qualification. Compare exact vector search with the chosen approximate index before using that index in a qualified recipe. Measure result completeness and relevance under tenant and metadata filters, including narrow filters and permission revocation. pgvector documents both approximate-index filter behavior and hybrid search with PostgreSQL full-text search. [pgvector documentation](https://github.com/pgvector/pgvector).

Expose lexical, dense, and hybrid recipes with recorded rank fusion, candidate count, reranker, thresholds, and final top-K. Show the retrieval candidate list separately from reranked results and from the chunks that actually fit the final context. Preserve source citations and an explicit no-answer policy. Diagnose retrieval misses, reranking mistakes, context omissions, and generation failures separately.

Use an authenticated query-serving adapter with its own concurrency and timeout limits. Heavy inference runs in a model-serving process; index builds and batch evaluation run as RabbitMQ-dispatched worker jobs under PostgreSQL job state. API requests do not load model weights or compete in the training queue. Support local embedding, reranking, generation, and judging for self-hosted installations. Remote providers require configured egress authorization.

LlamaIndex and Sentence Transformers are integration candidates behind ModelAnvil adapters. ModelAnvil retains ownership of stable identifiers, permissions, versioning, job execution, and release gates. Qualify library versions and model licenses independently. [LlamaIndex framework](https://developers.llamaindex.ai/python/framework/), [Sentence Transformers](https://sbert.net/docs/sentence_transformer/usage/usage.html).

## Evaluation data and metrics

An evaluation case contains a query, corpus version, expected answerability, relevant source spans or IDs, optional graded relevance and reference answer, task/language tags, and origin. Synthetic cases must retain their generator revision and human-review status. Maintain development and held-out test sets; labels and queries used for recipe selection must not silently become final test evidence.

For retrieval, report Recall@K, Precision@K, Hit@K, MRR@K, and nDCG@K. Pin cutoffs, relevance thresholds, grading/gain formula, duplicate handling, tie order, unjudged-result policy, and aggregation. Report document and chunk metrics separately. Show judged coverage, per-query outcomes, sample counts, slices, and uncertainty. Approximate nearest-neighbor recall compares with exact vector neighbors; it is not relevance recall. [ir-measures definitions](https://ir-measur.es/en/latest/measures.html).

The initial precision denominator is K even if fewer results are returned. Queries without relevant labels are N/A for recall and ideal-normalized nDCG; display their count. Confirmed unanswerable cases belong to a separate abstention evaluation. Unlabeled queries cannot provide supervised relevance recall, although they can still receive answer reviews or explicitly named judge-based measures.

For example, let the relevant IDs be A, B, and C, with retrieved order B, X, A and K = 3. Recall is 2/3, precision is 2/3, hit is 1, and reciprocal rank is 1. If the system returns only B at K = 3, recall and precision are both 1/3. With no relevant judgments, do not fabricate a recall score. These are acceptance fixtures, not measured product results.

Answer evaluation covers groundedness, correctness, relevance, citation support precision, citation coverage, and abstention. Operational measures include stage/end-to-end p50/p95 latency, token counts, cost, index build time, storage, and source freshness. Specify which measures need references or human judgments. Ragas is a candidate for context/answer judges; judge-model scores must expose their configuration, human calibration, and disagreement. [Ragas metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/).

Every stored score needs a metric ID/version, case ID, run ID, value and unit, applicability status, evidence references, scorer configuration, and failure details. A missing field, failed judge, or unsupported metric produces an explicit status rather than a zero. Aggregate reports show exclusions, not just the mean. Project owners choose release thresholds based on task needs and baseline evidence.

## Context composition and experiments

A context block has a type, source/revision, trust level, role, ordering rule, priority, token allocation, selection policy, and optional expiry. Blocks may include instructions, user input, examples, retrieved evidence, conversation history, memory, tool schemas, and tool results. Context recipes define how these blocks become actual messages for a particular model template.

The preview must show exact serialized input, token counts for the pinned tokenizer, output reserve, and included/omitted/truncated/summarized blocks. Distinguish estimated local counts from provider-reported usage where tokenization differs. Validate input plus output reserve against the qualified runtime limit. Overflow behavior must be explicit: fail, trim a named category, reduce selected evidence, or apply a declared compression step. Required instructions or evidence cannot be removed silently.

Experiment dimensions include examples, evidence ordering, chunk packing, top-K, history window, rolling summaries, memory retrieval, compression strategy, and token allocation by block. Run paired comparisons with fixed test versions, model and decoding settings; repeat stochastic cases and show variation. Separate frozen replay from live tools and current memory. Do not describe replay as bitwise deterministic across model-serving environments.

Minimum stress coverage includes:

- Evidence at the start, middle, and end across increasing tested context lengths.
- Irrelevant passages, duplicate evidence, conflicting sources, outdated facts, and missing evidence.
- Instructions injected into documents or tool results, with a declared attack objective and observed actions.
- Multi-turn facts, corrected preferences, memory deletion/expiry, and cross-session isolation.
- Tool errors, timeouts, stale results, schema changes, and context overflow using controlled fixtures.

Measure task success, instruction adherence, required-evidence retention and use, memory precision/recall against labeled facts, abstention, attack success rate, per-block tokens, compression ratio, cost, and latency. Memory denominators and fact-equivalence rules belong to the metric configuration. Compression ratio alone cannot establish useful context quality.

Use no-retrieval, retrieved-evidence, and human-supplied-evidence runs to investigate the retrieval/generation boundary. Reorder or remove blocks through controlled ablations. Inspect context differences beside outputs, citations, and tool actions; do not require hidden model reasoning. Position tests are motivated by [Lost in the Middle](https://arxiv.org/abs/2307.03172); [RULER](https://github.com/NVIDIA/RULER) is a candidate synthetic stress adapter whose license and task suitability need review. Real project tasks remain required.

## Visual investigation

The embedding explorer starts with a saved 2D UMAP projection and a PCA comparison option. Optional HDBSCAN or K-means labels use original embeddings or an explicitly configured higher-dimensional reduction. Record input space, distance, parameters, library version, seed where applicable, sample selection, coordinates, and cluster IDs. Never silently treat 2D plot distance as the retrieval distance. UMAP can distort density and apparent cluster structure. [UMAP clustering guidance](https://umap-learn.readthedocs.io/en/latest/clustering.html).

Provide color by source, language, task, label, or failure type; search, filters, hover preview, lasso selection, outlier review, and a details panel with source locations. Overlay a query, retrieved results, relevance judgments, and rank. Query placement uses the saved transform or a clearly labeled alternative; recomputing a projection creates a new artifact. Similarity and nearest-neighbor lists use the declared embedding space. Compare different embedding models in separate aligned views only when a mapping is explicitly defined.

Selections can create a review batch or export an authorized ID manifest. Sampled views show the total and displayed counts and sampling policy; cluster summaries disclose their population. Large datasets use bounded samples or server aggregation. Qualify Plotly scattergl as the first browser rendering candidate, with a measured point-count and interaction profile rather than an unlimited-scale promise. Provide an accessible searchable table with equivalent detail and selection actions. [Plotly WebGL guidance](https://plotly.com/javascript/webgl-vs-svg/).

Context Lab adds token-allocation bars, ordered message inspection, block diffs, evidence-position/length heatmaps, and quality-versus-cost/latency charts. Link failures between these views, query traces, source chunks, and the embedding explorer. Display raw cases and confidence information alongside aggregated scores.

## Release evidence

Qualify one named text recipe in managed and self-hosted modes with local models and judges. Pass PRD scenarios 14–16, including retrieval metric fixtures, authenticated query serving, source updates, permission revocation, deletion, cancellation/recovery, saved projections, context overflow, multi-turn isolation, and a failing promotion gate. Record dependency locks, hardware, corpus size, concurrent query profile, tested context lengths, visualization limits, and known limitations.

Expose versioned API resources for knowledge bases/builds, pipelines/query traces, relevance suites, context recipes/experiments, projections/selections, and release manifests. Exact routes are an implementation design task; both clients and automation must use the same permissions and records. Trace retention, redaction, cache authorization, and exports must obey organization residency policies. The Mac feature matrix determines native explorer coverage without changing backend support.
