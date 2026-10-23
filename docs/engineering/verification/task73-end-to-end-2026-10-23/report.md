# Reproducible CPU RAG report — 23 October 2026

[The complete self-contained measured report](actual-report.json) joins actual retrieval, grounded generation and evidence-position runs from the same implementation commit **04916ee723f894ab0b3cec50b2ccc43596bceae0**. Each input has a canonical SHA256 digest; mismatched commits, changed corpus/model pins, unbound citations and context overflow are refused. The policy was frozen at **bd11ff8** before this combined measurement. Required CI repeats the actual protocols and compares them with this saved reference; it never substitutes mock model output.

| Measured CPU reference | Result | Scope |
| --- | --- | --- |
| MiniLM relevance nDCG@5 | 1.0000 | 20 judged queries; closed 200-document SciFact subset |
| Seeded random-vector nDCG@5 | 0.0215 | 20 judged queries; closed 200-document SciFact subset |
| Strict SQL full-text AND nDCG@5 | 0.0000 | 20 judged queries; closed 200-document SciFact subset |
| Generation conditions with accepted citations | 1/3 | No evidence / retrieved / human evidence; membership validation only |
| Known-unanswerable outcomes | 0 model abstentions, 1 policy abstentions, 1 format refusals | 2 authored cases; separate from retrieval relevance |
| Start position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |
| Middle position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |
| End position code-only exact match | 0.0000 (0/6) | Code-only format required; descriptive middle dip not observed |

Source measurement: `04916ee723f894ab0b3cec50b2ccc43596bceae0`. [Complete report and reproduction limits](report.md). This table is generated only from its saved JSON.

## Inputs, parameters and hardware

- Public retrieval: original publisher SciFact archive SHA256 `11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be`, source-group frozen20-development/20-held-out query split and200 selected documents/412 actual chunks. Claims/evidence CC-BY4.0; abstracts ODC-By1.0; exact upstream license and attribution evidence remains in the report. This is a closed subset, with no full-leaderboard or contamination-free claim.
- Encoder: `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, all file hashes and package/runtime pins retained;384 dimensions, normalized cosine. Exact SQL and HNSW use the same authorized eligibility set; HNSW m16, ef_construction64, strict iterative scan and20,000 visited-tuple bound. Development-selected ef_search10. Raw ANN-neighbor overlap is separate from relevance; its measurement disables exact fallback while product retrieval keeps the underfill fallback. Strict SQL full-text AND returned zero on this fixture and is explicitly a weak untuned control, not tuned BM25.
- Decoder: `HuggingFaceTB/SmolLM2-135M-Instruct` revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`, Apache-2.0, all model/tokenizer hashes retained. Generation: greedy temperature0, seed42,64 reserved output tokens, maximum2048 total context;3 evidence conditions plus2 known-unanswerable cases. Citation membership does not establish entailment. Actual policy abstentions and validation refusals are separate from model-declared abstentions and retrieval relevance.
- Position fixture: authored CC0 three-code facts/twelve distractors, start/middle/end, two repeats,18 real forwards, fixed greedy seed42 and24 output tokens. The frozen code-only exact-match score is0 at all positions because every output used a complete sentence containing the correct code. Zero repeat variation and no middle dip were observed. The metric was not relaxed after seeing those outputs; no evidence-retention failure is inferred from format noncompliance.
- Local measured hardware: Apple M5 Pro, arm64,18 logical CPUs,48 GiB physical memory, Darwin27; inference CPU only, one Torch thread. Exact Python/package/database/pgvector versions, prompt usage, output usage and elapsed times remain in the complete report. Latency is recorded without a cross-host speed claim. CI records its actual Linux CPU and memory independently.

## Reproduction policy and commands

[scripts/rag-reproduction-policy.json](../../../../scripts/rag-reproduction-policy.json) fixes exact model/corpus/qrels/schedule/coverage pins, relevance metric tolerance1e-6, ANN mean-neighbor-overlap tolerance0.05 and position accuracy tolerance1/3 (at most one of the three authored cases). Generation statuses, abstention and retrieval-relevance summaries must match exactly. Complete prompt/template hashes and input/reserve counts also match; generated answer strings are retained without exact-string assertions. Timing/hardware may differ. This is a reproduction envelope, not a general quality target.

Use Python3.12, pinned base/CPU embedding requirements, PostgreSQL16 with pgvector>=0.8 and RabbitMQ4.1. Explicitly bootstrap the licensed public corpus, pinned MiniLM and pinned decoder caches as in the [retrieval controls](../../retrieval-controls.md) and [grounded generation](../../grounded-generation.md) guides. Then run actual tests offline, serially with other local inference:

```sh
export MODELANVIL_RETRIEVAL_REPORT=/absolute/new/retrieval.json
export MODELANVIL_RAG_GENERATION_REPORT=/absolute/new/generation.json
export MODELANVIL_POSITION_REPORT=/absolute/new/positions.json
# Set database, RabbitMQ and verified local cache paths.
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python manage.py test --tag=pg --noinput
python scripts/rag_report.py --retrieval "$MODELANVIL_RETRIEVAL_REPORT" \
  --generation "$MODELANVIL_RAG_GENERATION_REPORT" --positions "$MODELANVIL_POSITION_REPORT" \
  --output /absolute/new/combined.json --check-readme
```

The default reference is this saved JSON. A comparison failure preserves the measured combined JSON before exiting nonzero; CI preserves the three component reports too. `python scripts/rag_report.py --write-readme` regenerates the README table exclusively from the saved reference. `--check-readme` fails on manual result drift. Full source commits remain in every component and the combined report; report hashes include actual fixture identities rather than hiding them.

## Verification and evidence gate

The complete23-test PostgreSQL suite passed, including actual public retrieval controls, embedding fine-tuning/export, broker-fenced builds, cited generation/revocation and the18-forward position sweep. Source-bound composition and exact local-reference reproduction passed. Three clean fail-closed report guards and four OpenAPI regressions passed; the final broad backend suite passed1,041 tests with five optional skips. Migration drift: no changes. No frontend layout changed.

CI runs the same full suite and compares the combined report within the frozen tolerances, checks the generated README table, and uploads `rag-end-to-end-SHA` plus all components as14-day artifacts. A report starts with `cv_evidence_confirmed:false` because its own CI job has not finished. **CV evidence requires external confirmation after merge: main contains that exact SHA, every required CI job on that SHA is green, and the corresponding report is attached and preserved.** The completion receipt in Aftur records the run URL, exact SHA, artifact digest and durable report copy after those checks. CPU software evidence does not qualify GPU execution, customer benefit or production serving.
