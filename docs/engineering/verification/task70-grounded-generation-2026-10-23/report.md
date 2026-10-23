# TASK70 — actual grounded generation, 2026-10-23

The pinned Apache-2.0 SmolLM2-135M-Instruct model ran locally through the shared CPU Safetensors runtime. This replaces the generation gap without relabeling retrieval-only traces. Model revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`; weight SHA256 `5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c`. Every model/tokenizer file is pinned in `decoder-pins.json`; the runtime receipts retain exact snapshot/file, source document/chunk and frozen-index pins.

## Measured qualification

Three authored CC0 facts identify island WILLOW, valley CEDAR and harbor MAPLE. A real pinned MiniLM worker builds the PostgreSQL/pgvector dense index. The answerable island question uses the same prompt version, greedy temperature0, seed42 and64 output reserve in all three evidence conditions. The human condition supplies only the island chunk. The retrieved condition supplies the top2 actual dense neighbors. The no-retrieval condition supplies none. There is no exact-string assertion on generated text.

| Condition | Retrieval | Observed status | Input tokens | Generated tokens | Accepted citations |
| --- | --- | --- | --- | --- | --- |
| none | none | validation_refusal | 105 | 12 | 0 |
| retrieved | dense | answered | 133 | 61 | 1 |
| human | human | validation_refusal | 117 | 13 | 0 |
| retrieved | lexical | policy_abstain | — | — | 0 |
| retrieved | dense | validation_refusal | 136 | 15 | 0 |

The correctly cited retrieved answer passed membership validation. The human-evidence answer omitted its citation and was refused despite containing the reference code. The no-evidence output invented a citation and was refused. These observations show weak formatting by a small model; citation membership alone does not establish answer correctness or entailment. No general quality, model-abstention or benchmark improvement claim follows from this fixture.

Known-unanswerable cases are measured independently of retrieval relevance. The lexical absent-entity query returns no evidence and a policy abstention without inference. The dense absent-entity query receives irrelevant evidence and executes the actual model. {"delivered_false_answers": 0, "known_unanswerable": 2, "model_declared_abstentions": 0, "model_executed": 1, "policy_abstentions": 1, "validation_refusals": 1}. The answerable retrieval hit@2 is 1 over one labeled query. Policy abstentions and format refusals are not counted as model-declared abstention.

## Integrity and product checks

Actual inference usage equals the tokenizer's complete serialized input count, and input plus output fits2048 tokens. Output reserves are bounded1–128; fail is the default overflow policy. Explicit optional-evidence omission preserves the required question. Unknown/Unicode-normalized out-of-range citation labels, missing citations, unknown human-source IDs and references in the no-source condition are refused. A source revoked after the real forward pass prevents publication; saved history also withholds withdrawn source output. Current model access and snapshot digests are rechecked. Index manifest/configuration and retrieval execution settings remain in receipts.

The actual authenticated browser/API check ran three conditions at1440px and390px, then reloaded saved history. It found no page overflow or browser errors, and the new question was absent from local/session storage. [Desktop](desktop.png), [mobile](mobile.png), [browser receipt](browser-report.json). The browser retrieved3 chunks, while the fixed PostgreSQL test deliberately uses2; their token counts and answer strings are therefore separate observations.

## Verification

Final backend suite: **1,036 tests, five optional skips**. Final serialized PostgreSQL suite: **22 tests passed**, including actual retrieval controls, embedding fine-tuning/export and generation. Clean base guards/OpenAPI: **six tests passed**. Frontend: **226 tests passed**, production build and Storybook build passed. Migration drift: no changes detected. The first parallel full PostgreSQL attempt encountered the shared CPU device lease held by a separate backend test process; it was refused safely. No lock bypass or assertion waiver was used. Fresh-cache bootstrap verifies every pinned public file; API inference is offline. CI repeats this real PostgreSQL/model/broker qualification and uploads a commit-named measured report. [Operator and API commands](../../grounded-generation.md), [complete measured JSON](actual-report.json).

The machine is Apple arm64, Python3.12, CPU thread count1 for the measured fixture; exact Torch/Transformers/tokenizers/safetensors versions are present per run. This ticket does not claim GPU execution, customer qualification, a full corpus answer benchmark or final merged-SHA CV evidence; TASK73 owns the final reproducible report.
