# TASK71 — real evidence-position sweep, 2026-10-23

The fixed local Apache-2.0 SmolLM2-135M-Instruct decoder revision `12fd25f77366fa6b3b4b768ec3050bf629380bac` executed all18 forwards. Protocol commit `3e25770` froze the fixture, decoding, scoring and reproduction tolerance **before measurement**. Implementation source commit `45a9ff3` is recorded in the [complete measured JSON](actual-report.json), with the protocol digest, model/tokenizer/file pins and CPU package/hardware provenance.

Three authored CC0 code facts are placed before, amid or after twelve identical distractor records. Two repetitions use exactly the same temperature0, seed42,24-token reserve and chat template, with balanced placement order. All target facts survive in the complete prompt. Inputs use575–576 tokens and fit the2048-token runtime together with output reserve. This is a small software qualification fixture, not a representative long-context benchmark.

| Position | Code-only exact matches | Accuracy | Repeat accuracies | Repeat stddev | Unique outputs per case |
| --- | --- | --- | --- | --- | --- |
| Start | 0/6 | 0.0000 | 0.0000, 0.0000 | 0.0000 | 1, 1, 1 |
| Middle | 0/6 | 0.0000 | 0.0000, 0.0000 | 0.0000 | 1, 1, 1 |
| End | 0/6 | 0.0000 | 0.0000, 0.0000 | 0.0000 | 1, 1, 1 |

**No middle dip was observed.** Edge-mean minus middle accuracy is0. The model returned the correct code in a complete sentence in every raw output, rather than following the code-only instruction. For example, the island output was “The access code for the island beacon is WILLOW.” The predeclared strict metric therefore scores it incorrect. Scoring was not relaxed after observing this behavior. These zeros show format noncompliance under this metric; they do not establish failure to retain the evidence. There is no position effect or general quality claim.

Actual output-derived decisions, repeated prompt hashes, token usage, fact offsets and raw strings remain available in the JSON. No scores are assigned from position names or simulated inference. Unit fixtures independently prove that all-correct outputs produce no dip and that changing an actual scored middle observation changes both its accuracy and repeat variation. The actual-model test checks the schedule, recomputes scores from outputs and verifies exact usage/context bounds without asserting model answer strings.

The operator CLI was also exercised against the existing private QA project with the public fixed profile. It writes a separate new report, preserves existing data and uses the same shared CPU lease as other training/inference. No alternate lock namespace or fake reference model was used. The old Context Lab compilation-only `/sweep/` inspection remains accurately labeled not-run for model recall; the new command supplies actual evidence instead of simulated scores.

Final verification: two clean software guards, three actual protocol tests, 25 Context Lab/OpenAPI regressions and the complete23-test PostgreSQL/model/broker suite passed. The standalone operator command reproduced the same prompt hashes and summary. Migration drift: no changes detected. No frontend layout changed. CI reruns the complete protocol and uploads the raw JSON under its actual commit SHA. [Operator commands](../../evidence-position-sweep.md). TASK73 owns the combined report and final merged-main-SHA evidence.
