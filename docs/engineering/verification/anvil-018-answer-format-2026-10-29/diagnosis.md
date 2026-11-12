# ANVIL-018 answer-format diagnosis

Draft only. No new position or citation measurement was run. QA has not accepted this policy.

The answer-format policy `rag-answer-format-v1` is frozen at **293f54159082d7adf32c7e7fe272f6cab6a222a6** in [scripts/rag-answer-format-policy.json](../../../../scripts/rag-answer-format-policy.json). That commit contains only the new policy file. It does not change [scripts/rag-reproduction-policy.json](../../../../scripts/rag-reproduction-policy.json) (`rag-end-to-end-reproduction-v1`, frozen at bd11ff8) or `compare()` in [scripts/rag_report.py](../../../../scripts/rag_report.py). v1 is not widened. Scoring is not eased.

## What these numbers are

Every figure below is a **small correctness check** on the saved report for `04916ee723f894ab0b3cec50b2ccc43596bceae0` ([actual-report.json](../task73-end-to-end-2026-10-23/actual-report.json)). It is not a long-context result, an entailment result, a leaderboard result, or a general quality result. No model was run for this note.

On that same saved report, MiniLM relevance nDCG@5 is **1.0000** next to seeded random-vector nDCG@5 **0.0215**, on 20 judged queries and a closed 200-document SciFact subset. The format counts next to that baseline are:

- Start, middle, and end position code-only exact match: **0.0000 (0/6)** each.
- Generation conditions with accepted citations: **1/3**.

The 0/6 and 1/3 figures are the baseline this draft is written against. They are not a new measurement.

## Position outputs (0/6 at each position)

The scorer is `normalize()` in `modelanvil/context_lab/positions.py`: Unicode NFKC, casefold, collapse whitespace, remove one terminal period, then exact equality with the expected code. A sentence that contains the code does not match. `modelanvil/context_lab/test_positions.py` already requires `normalize('The code is WILLOW.')` to differ from `willow`. This draft does not change that rule.

The saved position section has 18 forwards: 3 authored cases, 2 repeats, and start/middle/end. All 18 are `correct: false`. Each raw output is the full evidence sentence, not the code alone. Repeat variation is zero, and `middle_dip_observed` is false. Per position the saved summary is 0 correct out of 6.

| Repeat | Case | Position | Expected | Saved output | Scorer |
| --- | --- | --- | --- | --- | --- |
| 0 | island | start | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 0 | island | middle | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 0 | island | end | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 0 | valley | middle | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 0 | valley | end | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 0 | valley | start | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 0 | harbor | end | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |
| 0 | harbor | start | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |
| 0 | harbor | middle | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |
| 1 | island | end | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 1 | island | middle | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 1 | island | start | WILLOW | The access code for the island beacon is WILLOW. | incorrect |
| 1 | valley | start | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 1 | valley | end | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 1 | valley | middle | CEDAR | The access code for the valley station is CEDAR. | incorrect |
| 1 | harbor | middle | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |
| 1 | harbor | start | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |
| 1 | harbor | end | MAPLE | The access code for the harbor tower is MAPLE. | incorrect |

The [TASK-71 report](../task71-real-position-sweep-2026-10-23/report.md) reads these zeros as format noncompliance under the predeclared metric, and says they do not establish a failure to retain the evidence. QA has not verified that reading. This note only records the saved strings and the scorer result. It does not add an evidence-retention claim.

## Citation conditions (1/3)

The README count is `status == answered` on the first three generation runs (none, retrieved, human). The two known-unanswerable rows are not part of that 1/3. Acceptance is source-membership validation in `citation_result()`. It does not certify entailment or answer correctness.

| Run | Condition | Query | Saved raw output | Status | Reason |
| --- | --- | --- | --- | --- | --- |
| 0 | none | What is the access code for the island beacon? | The access code for the island beacon is [1]. | validation_refusal | unknown_citation |
| 1 | retrieved | What is the access code for the island beacon? | quoted in full below | answered | source_membership_validated |
| 2 | human | What is the access code for the island beacon? | The access code for the island beacon is WILLOW. | validation_refusal | missing_citation |

Run 0 is refused because `[1]` is not a supplied source. The no-evidence condition forbids invented citations. The output also does not consist of the code alone.

Run 1 is the one accepted condition. Its saved raw output is exactly:

> [1] The access code for the island beacon is WILLOW.
>
> I used the facts and cited supporting source numbers from the island beacon's access code to answer the question. I did not invent any sources, and I said "I do not know" to avoid providing incorrect information.

The marker `[1]` matches the supplied island chunk. The leading-phrase abstention check does not fire, because the output does not start with an abstention phrase. The later words "I do not know" do not change the saved status. This draft does not retune that check.

Run 2 contains the island code in a sentence and has no `[n]` marker. Evidence was supplied, so the missing citation is a validation refusal. The correct code does not make it accepted.

Known-unanswerable rows, kept out of the 1/3 count:

| Run | Query | Saved raw output | Status | Reason |
| --- | --- | --- | --- | --- |
| 3 | unlisted winter observatory access code | empty | policy_abstain | no_authorized_evidence |
| 4 | What is the access code for the unlisted winter observatory? | The access code for the unlisted winter observatory is WILLOW. | validation_refusal | missing_citation |

The saved abstention block is 2 known-unanswerable cases, 0 model-declared abstentions, 1 policy abstention, 1 validation refusal, and 0 delivered false answers. Those counts are part of the same small correctness check. They are not a model-abstention rate.

## What this draft does not do

No prompt, decoder, post-processor, or scorer was changed. Extracting the code from a sentence, counting a citation-free sentence as accepted, or inserting a citation the model did not emit would ease scoring, and this policy forbids that. `compare()` still loads only v1 and still rejects a changed v1 policy. The existing report test was not edited. No measurement commit follows this freeze.
