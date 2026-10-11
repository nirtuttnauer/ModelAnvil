# ModelAnvil compatibility planning

All entries are planned or undecided. No implementation is currently qualified. Each release must distinguish storage, parsing, preview, annotation, training conversion, and export support.

## Data families

| Family | Proposed import targets | Training dependency | Planning state |
| --- | --- | --- | --- |
| Text/chat | TXT, MD, JSON, JSONL | Tokenizer, template, schema | R1 baseline |
| Structured datasets | CSV, TSV, Parquet, Arrow | Field mapping | R1 baseline |
| Documents/web | HTML, PDF, DOCX, PPTX, EPUB, WARC | Extraction or visual processor | Proposed adapter coverage |
| Code | Source, Git snapshots, notebooks, diffs | Text or tool-use recipe | Proposed adapter coverage |
| Images | JPEG, PNG, WebP, TIFF | Image encoder and processor | Initial training recipe to qualify |
| Audio | WAV, FLAC, MP3, Ogg | Audio model and processor | Training recipe undecided |
| Video | MP4, MOV, WebM | Temporal model and processor | Training recipe undecided |
| Custom | Custom JSON, binary, scientific records | Mapping or extension | SDK required in R1 |

## Training recipes

| Recipe | Release intent | Evidence needed |
| --- | --- | --- |
| Text model from scratch | R1 required | Architecture, tokenizer, hardware, loss/validation, external loading |
| Continued pretraining | R1 required | Corpus mixture, baseline, regression evaluation |
| Full supervised fine-tuning | R1 required | Input template, output loading, independent evaluation |
| LoRA/QLoRA | R1 on supported backends | Base revision, quantization/backend compatibility, adapter loading |
| DPO | R1 required | Validated pairs, reference settings, held-out evaluation |
| Reward model | R1 required | Preference splits, held-out metrics, score inspection |
| Verifiable-reward RL | One R1 recipe required | Versioned verifier, bounded execution, trajectories, independent evaluation |
| Image/text fine-tuning | R1 target | Encoder/processor alignment and end-to-end test |
| Audio/video training | Coverage decision pending | Named architecture, processor, compute, evaluators |
| Complete learned-reward RLHF | One text recipe required in R1 | Human-feedback provenance, held-out reward validation, fresh rollouts, pinned policy/reference/reward revisions, algorithm, divergence controls, checkpoint recovery, independent human and regression evaluations |

## Qualification record template

For each supported combination record the adapter version, dependency lock, architecture revision, tokenizer/processor revision, input schema, codecs and limits, hardware/topology, checkpoint/recovery guarantees, export format, tests, and known limitations.

Capabilities become **supported** only after passing fixtures and end-to-end qualification. Other labels are **experimental**, **requires extension**, and **unsupported**. Importing a file alone never establishes training support.

## PRD 0.2 dataset coverage

The open source catalog is organized by intended output, separately from import container formats. SVG assets require isolated rendering and task-specific pairing; audio and video output require compatible generation architectures, not just file decoding. JSON, tables, notebooks, and document exports require validated serializers or renderers. The catalog includes explicit document-layout and custom/3D coverage gaps. No listed research candidate establishes implemented parser, exporter, connector, or training support.

## Application and infrastructure baseline

| Component | Planning baseline | Qualification evidence |
| --- | --- | --- |
| Browser | React, TypeScript, Vite | API compatibility, core flows, permissions, supported browsers |
| Native Mac client | SwiftUI | Declared feature matrix, authentication, file transfer, reconnect, minimum macOS |
| API | Django, Django REST framework, ASGI; prefer Django 5.2 LTS initially | Pinned supported dependency matrix, migrations, API contract, tenancy |
| Metadata | PostgreSQL | Claims, leases, outbox, backup/restore, indexes, supported major version |
| Artifacts | S3 contract; SeaweedFS for self-hosted qualification, managed S3 for cloud | Multipart resume/abort, range reads, presigned requests, tenancy, durability and recovery |
| Web acquisition | Scrapling worker adapter | HTTP/browser fixtures, source provenance, crawl limits, durable restart, cancellation |
| Dispatch | RabbitMQ with database lifecycle | Capacity admission, duplicate dispatch, fencing, recovery, drain |
| Single-server deployment | Docker Compose | Installation, persistent data, backup, upgrade, stated host-failure limits |
| Multi-node production | Kubernetes and Helm reference | GPU resource groups, failure domains, stateful recovery, upgrades |

No entry is implemented or qualified. MinIO community is not the new-installation default; existing endpoints require the same S3 contract checks. Architecture decision 002 records evidence and revisit conditions.

## RAG and context engineering

| Capability | Release intent | Qualification evidence |
| --- | --- | --- |
| Text RAG pipeline | One R1 recipe required | Corpus/chunk/index lineage, lexical/dense/hybrid retrieval, reranking, citations, endpoint, export, rollback |
| PostgreSQL full-text and pgvector | First backend to qualify | Dimensions/distance, exact reference, approximate/filter recall, tenant isolation, concurrency, update/deletion handling |
| Local embedding/reranking/generation/judging | Required self-hosted path | Pinned model/license/backend matrix, resource profile, egress controls, metric calibration |
| Retrieval metrics | R1 required | Hand-scored Recall/Precision/Hit/MRR/nDCG fixtures, relevance mapping, judgment coverage, N/A policy |
| Answer evaluation | R1 required | Correctness, groundedness, relevance, citations, abstention, judge/human agreement, latency and cost |
| Embedding explorer | R1 required | Saved projection, optional labels, source links, query/relevance overlays, original-space neighbors, sampling, accessible table |
| Context recipe and experiments | R1 required | Exact serialized inputs, token counts/reserve, block provenance, ablations, frozen replay, release gate |
| Context stress suites | R1 required | Evidence position/length, overflow, contradictions, injection, memory updates, session isolation, tool failures |
| Multimodal/graph retrieval and autonomous agents | Later targets | Separate corpus/model/runtime and evaluation qualification |

LlamaIndex, Sentence Transformers, ir-measures, Ragas, UMAP/PCA, HDBSCAN/K-means, and Plotly scattergl are candidates to qualify. No candidate is implemented or supported yet. Record corpus/index scale, concurrency, filter selectivity, tested context lengths, visualization point limits, versions, and known limitations with each qualification report.

## Iterative labeling

| Capability | Release intent | Qualification evidence |
| --- | --- | --- |
| Manual and model-assisted seed batches | R1 on one text task | Empty-label and existing-model paths, label mapping, review/correction, approved snapshot |
| Repeated labeling-model training | R1 on one text task | Two train-and-next-batch cycles per entry mode, cumulative approved data, pinned recipe/model, source-group split exclusion |
| Review and model lifecycle | R1 required | Original drafts and human revisions, adjudication, model gate, in-flight version pinning, failed candidate, rollback, pause/recovery |
| Cycle quality and limits | R1 required | Independent audit, task metrics, review effort/coverage, calibrated-score status, cycle/budget stops, tenant isolation |
| Further label schemas and modalities | Qualified individually | Schema, correction UI, task model/trainer, evaluator, processors, hardware |
| Automated uncertainty/disagreement/diversity selection | Target | Acquisition method, representativeness, confidence calibration, selection provenance and separate random audit |

Label Studio prediction/review integration is a candidate requiring exact edition/version, license, task-schema, identity/access, and round-trip tests. No iterative-labeling integration is implemented or qualified.

## Engineering conformance contracts

The [technical requirements](engineering/technical-requirements.md) and [backend schema](engineering/backend-schema.md) define versioned capability qualification and the sample/adapter interchange contracts. The JSON schemas validate declarations and record envelopes; they do not qualify a model, file format, engine, storage provider, or deployment. WP-01 selects exact combinations; WP-14 and WP-17 publish conformance and release evidence. Existing support intent in this matrix is unchanged.
