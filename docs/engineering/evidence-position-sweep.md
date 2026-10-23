# Actual evidence-position sweep

Run the frozen authored CC0 evidence-position protocol with the actual public CPU decoder from [grounded generation](grounded-generation.md). The operator command registers or reuses that verified pinned model in an existing project and writes a new measured JSON file; it never overwrites evidence. It does not evaluate arbitrary saved context recipes. The older Context Lab `/sweep/` endpoint remains clearly labeled prompt inspection and reports model recall as not run.

```sh
# Install base + pinned CPU embedding packages; cache the public decoder explicitly.
export MODELANVIL_RAG_DECODER_CACHE=/absolute/path/to/decoder-cache
python manage.py cache_rag_decoder
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  python manage.py verify_evidence_positions --project PROJECT_UUID \
  --accepted-license apache-2.0 --output /absolute/new/position-report.json
```

[The frozen protocol](../../modelanvil/context_lab/position-protocol.json) declares three facts, twelve fixed distractor records, start/middle/end placements, two repeats and a strict normalized code-only exact-match score. All18 scheduled actual forwards use the same pinned model/chat template, seed42, greedy decoding and24 reserved output tokens. The complete prompt is tokenized before each forward and must fit2048 tokens; evidence is never trimmed. Start/middle/end order rotates and reverses across cases/repeats. Every exact prompt hash, fact character offset, raw output, expected answer, usage and scoring decision is retained. Runtime failure aborts the report rather than creating a successful or zero-score stand-in.

Per-position results include total/correct counts, per-repeat accuracy, population standard deviation and the number of unique raw outputs for each case. Greedy repeats can have zero variation; that observation is reported. A descriptive middle dip is present only when measured middle accuracy is below the mean edge accuracy. The report makes no statistical significance or general long-context claim.

[Measured report and limitations](verification/task71-real-position-sweep-2026-10-23/report.md). The actual PostgreSQL CI suite reruns this protocol and preserves `evidence-position-COMMIT` for14 days. Model/prompt/protocol pins and schedule must match exactly; the accuracy tolerance, frozen before measurement, is at most one of the three cases per position (absolute1/3). That is a reproduction tolerance, not a quality threshold or tuning rule.
