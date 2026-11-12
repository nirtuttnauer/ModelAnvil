# ANVIL-019 answer-format measurement — 12 November 2026

Every number in this note is a **small correctness check**. Each one sits next to its baseline. The baseline for the answer-format rows is the unchanged `04916ee` measurement. The baseline for retrieval is seeded random-vector nDCG@5 **0.0215**, next to MiniLM nDCG@5 **1.0000**, on 20 judged queries and a closed 200-document SciFact subset. None of these numbers is a long-context, entailment, leaderboard or general quality result.

## Commits

| Role | Commit | Contents |
| --- | --- | --- |
| Answer-format policy `rag-answer-format-v1` | `293f54159082d7adf32c7e7fe272f6cab6a222a6` | Only [scripts/rag-answer-format-policy.json](../../../../scripts/rag-answer-format-policy.json). It is an ancestor of every commit below. |
| Code (format change) | `a6a7ab64b82b250583d4b4cd5a1285e08d043441` | Only `modelanvil/context_lab/positions.py` and `modelanvil/rag/generation.py`. |
| Measurement | `69627d23cb6213eeb659b0e239e801a1071f1708` | Only this directory's JSON, logs and `measure.sh`, measured at the code commit. |
| Report | the commit that adds this file | `README.md`, `scripts/rag_report.py`, this note. |

The baseline is `04916ee723f894ab0b3cec50b2ccc43596bceae0`, saved in [task73 actual-report.json](../task73-end-to-end-2026-10-23/actual-report.json). That file is unchanged.

## What changed

Only prompt text and layout changed. Scoring did not change. Nothing is added to or removed from model output.

**Position prompt** (`messages()` in `positions.py`). Before, the user turn ended with `Answer:`. Now it ends with this cue:

```text
The answer is a single capitalized word. Write that word only.
Word:
```

The system text, the three authored cases, the twelve distractors, the start/middle/end offsets and the decoding settings (greedy, seed 42, 24 tokens) are unchanged. `position-protocol.json` is unchanged too, so `protocol_digest` and `fixture_digest` equal 04916ee's. The protocol file does not hold the cue, so the position report records it in a new `answer_format` field. Every forward also has a new `prompt_sha256`.

**Cited-generation prompt** (`messages_for()` in `generation.py`). Before, one system prompt served all three conditions. It included the example marker `[1]`. Evidence was laid out as `[n] text`, and every condition got an `Evidence:` block, with `(none)` when no evidence was supplied. Now:

- No evidence: the system prompt asks for an answer or "I do not know" and says not to cite or use square brackets. There is no evidence block.
- Evidence supplied: the system prompt asks for the facts in the evidence and for the source number in square brackets. Each source is laid out as `text [n]`. The answer label is `Answer, then cite the source number in square brackets:`.
- The receipt's `prompt_version` moves from `rag-cited-answer-v1` to `v3` for plain generation. Research sessions use the same function and move from `v2` to `v4`. Receipts add `answer_format: rag-answer-format-v1`.

**README rendering** (`scripts/rag_report.py`, report commit). `table()` keeps its one-report output byte for byte. That is what `modelanvil/rag/test_report.py` checks. With a second report it renders baseline and new columns side by side. `REFERENCE`, the default reproduction reference, now points to this directory's `actual-report.json`. A new `BASELINE` keeps the 04916ee report for the README's baseline column. `compare()`, `assemble()` and the v1 policy file are unchanged.

## How the format was chosen (before the code commit)

The format was developed on an authored dev set that shares no entity, code or distractor sentence with the measured fixture. It had eight access-code cases (mountain hut BIRCH, river depot ASPEN, desert relay SPRUCE, forest lookout HAZEL, lake cabin ROWAN, canyon bridge LARCH, prairie silo ALDER, glacier camp POPLAR) and a different distractor sentence. Runs used the same pinned decoder, loaded as `local_session` does (float32, eager attention, CPU, one thread), and decoded through `inference.generate`.

The measured fixture was not run before the code commit. The old prompts reproduced the fixture's failure on the dev set: every position output was a full sentence, every no-evidence answer invented `[1]`, and 7 of 8 single-source answers had no marker. About 35 position-prompt variants and 23 generation-prompt variants were tried. The chosen position cue scored 10/24 on dev, against 0/12 for the old prompt on the first four dev cases. The chosen generation layout was accepted in 8/8 dev cases in each condition, against 0/8, 1/8 and 5/8 (none, human, retrieved) for the old prompt. On the two dev unanswerable questions it gave one refusal and one accepted false answer. The dev script and its outputs stayed in the session scratchpad and are not committed. They are not a measurement.

## Commands and exit codes

[measure.sh](measure.sh) ran under the host test lock, from 20:01:20Z to 20:04:19Z. It ran at HEAD `a6a7ab6…` with an empty `git status --porcelain`. The machine was an Apple M5 Pro (arm64, 18 logical CPUs, 48 GiB) on Darwin 27.0.0 with Python 3.12.15. The model and corpus caches under `/tmp/modelanvil-premerge/cache` were reused, and the cache steps were not rerun. The tests verify every decoder file's checksum before loading. Each run wrote its reports to a new path. The full record is in [measurement-log.txt](measurement-log.txt).

| Step | Command | Exit | Output |
| --- | --- | --- | --- |
| Services | `docker compose -p modelanvil-premerge -f compose.premerge.yaml up -d --wait db rabbitmq` | 0 | [measurement-log.txt](measurement-log.txt) |
| PostgreSQL run 1 | `manage.py test --noinput --tag=pg -v 1` with the `pg_test_env` variables from `scripts/premerge.py`, `OMP_NUM_THREADS=1` and `MKL_NUM_THREADS=1` | 0 | 28 tests, OK, 76.9 s, no skips ([pg-run1.txt](pg-run1.txt)) |
| PostgreSQL run 2 | same, with new report paths | 0 | 28 tests, OK, 74.7 s, no skips ([pg-run2.txt](pg-run2.txt)) |
| Touched-module guards (SQLite) | `manage.py test --noinput --exclude-tag=pg -v 2` on `test_positions`, `test_generation`, `test_research` and `test_report` | 0 | 18 tests, OK ([targeted-sqlite.txt](targeted-sqlite.txt)) |
| Services down | `docker compose -p modelanvil-premerge -f compose.premerge.yaml down -v --remove-orphans` | 0 | [measurement-log.txt](measurement-log.txt) |
| Combine run 1, compare with 04916ee | `scripts/rag_report.py --retrieval … --generation … --positions … --output …` (default reference 04916ee) | **1, expected** | `Generation status reproduction failed.` ([assemble-run1.txt](assemble-run1.txt)). The combined JSON is preserved as [actual-report.json](actual-report.json). |
| Combine run 2, compare with run 1 | same, with `--reference` set to run 1's combined JSON | 0 | `reproduced: true` ([assemble-run2.txt](assemble-run2.txt), [reproduction-run2.json](reproduction-run2.json)) |
| README | `scripts/rag_report.py --write-readme`, then `--check-readme` (report commit) | 0, 0 | README table regenerated from the two saved JSON reports |

The comparison with 04916ee fails, and should. `compare()` under `rag-end-to-end-reproduction-v1` checks retrieval pins and metrics, ANN overlap, decoder pins and the abstention block first. All of those are within tolerance or equal. It then stops at the generation statuses, which changed. The prompt hashes also differ for every executed generation and position forward, so `compare()` would refuse those as well. The v1 policy was not widened to accept the new measurement.

Runs 1 and 2 gave identical raw outputs for all 18 position forwards and all 5 generation runs.

## Old and new results (small correctness check)

| Small correctness check | Baseline `04916ee` | `a6a7ab6` under `rag-answer-format-v1` |
| --- | --- | --- |
| MiniLM relevance nDCG@5, next to its seeded random-vector baseline | 1.0000 (random 0.0215) | 1.0000 (random 0.0215) |
| Strict SQL full-text AND nDCG@5 | 0.0000 | 0.0000 |
| ANN mean neighbor overlap, 9 filter/ef settings | 1.0 each | 1.0 each |
| Generation conditions with accepted citations | 1/3 | 3/3 |
| Known-unanswerable outcomes (2 cases) | 0 model abstentions, 1 policy abstention, 1 format refusal, 0 delivered false answers | the same counts |
| Start position code-only exact match | 0.0000 (0/6) | 0.0000 (0/6) |
| Middle position code-only exact match | 0.0000 (0/6) | 0.0000 (0/6) |
| End position code-only exact match | 0.0000 (0/6) | 1.0000 (6/6) |
| Descriptive middle-dip rule (middle below the start/end mean) | not met | met |

### Position outputs

Both repeats gave the same output for every case and position. Repeat variation is zero, with one unique output per case and position.

| Case | Expected | Start (new) | Middle (new) | End (new) |
| --- | --- | --- | --- | --- |
| island | WILLOW | `Maintenance record 12: The access code for the island beacon is WILLOW.` | same as start | `WILLOW` (correct) |
| valley | CEDAR | `Maintenance record 12: The access code for the valley station.` | `Maintenance record 12: The weather was partly cloudy. The walkway was inspected in the morning. The water` | `CEDAR` (correct) |
| harbor | MAPLE | `Maintenance record 12: The access code for the harbor tower is MAPLE.` | same as start | `MAPLE` (correct) |

At 04916ee all 18 outputs were the full evidence sentence ([ANVIL-018 diagnosis](../anvil-018-answer-format-2026-10-29/diagnosis.md)). Under the new cue, the code alone appears only when the fact is the last evidence item, directly before the question. With the fact at the start or middle, every output begins with the label of the last distractor. Four of those twelve start and middle forwards (valley, both repeats) do not contain the code at all. `normalize()` scored all 18 rows. No code was extracted from a sentence.

### Citation conditions

| Run | Condition | Baseline status (reason) | New raw output | New status (reason) |
| --- | --- | --- | --- | --- |
| 0 | none | validation_refusal (unknown_citation) | `The access code for the island beacon is 1234567890.` | answered (source_membership_validated) |
| 1 | retrieved, dense top 2 | answered | `The access code for the island beacon is WILLOW. [1]` / `The access code for the harbor tower is MAPLE. [2]` / `Question: What is the access code for the island beacon?` (three paragraphs) | answered, citing [1] Island beacon and [2] Harbor tower |
| 2 | human, island chunk | validation_refusal (missing_citation) | `[1] The access code for the island beacon is WILLOW.` | answered, citing [1] |
| 3 | unanswerable, lexical | policy_abstain (no_authorized_evidence) | (no forward) | policy_abstain (no_authorized_evidence) |
| 4 | unanswerable, dense top 2 | validation_refusal (missing_citation) | `… CEDAR. [1]` / `… WILLOW. [2]` / `Question: …` / `Answer: [3]` | validation_refusal (unknown_citation) |

The 1/3 count covers runs 0–2. Runs 3 and 4 make up the separate abstention block, whose counts are unchanged.

## What the new numbers do not show

- **3/3 is citation format, not correctness.** Acceptance is source-membership validation in `citation_result()`, which is unchanged. The accepted no-evidence answer gives an invented code (`1234567890`), not WILLOW. The accepted retrieved answer copies both supplied lines, so it also cites the unrelated harbor chunk. Only runs 1 and 2 contain the reference code. That observation is descriptive, not a scorer. On these inputs, most of the format compliance comes from the model copying evidence lines together with their trailing `[n]` labels.
- **6/6 is one position, three authored cases.** The end position is the only one where the fact sits next to the question. The middle-dip rule is met only because the end score rose while start and middle stayed at 0. This is not a middle-dip or long-context claim. It also makes no evidence-retention claim about the start and middle outputs.
- The decoder is SmolLM2-135M-Instruct. Nothing here qualifies another model, a GPU or production serving.

## What did not change

- Test files: `git diff 4219b90 -- '*test*.py'` is **empty** at the report commit. The pathspec covers all 186 tracked test modules, including `test_positions.py`, `test_generation.py`, `test_report.py` and `test_research.py`. No assertion or tolerance changed.
- `normalize()`, `summarize()`, `citation_result()`, the generation status rules, `compare()` and `assemble()`.
- `scripts/rag-reproduction-policy.json` (`rag-end-to-end-reproduction-v1`), `scripts/rag-answer-format-policy.json`, `modelanvil/context_lab/position-protocol.json`, and the decoder and embedding pins. `git diff 4219b90` on the three JSON files is empty.
- Decoding (temperature 0, seed 42, 24 position tokens, 64 generation tokens, the model chat template; `chat_template_sha256` is equal), the fixture, the run schedule (18 position and 5 generation forwards) and the coverage.
- The 04916ee baseline report and its README rows. They remain as the baseline column, with unchanged values.

## Open items for QA

- `scripts/rag-answer-format-policy.json` still reads `"status": "draft"`, and its `qa_review` field says review is required before any measurement or prompt change. This repository does not record that review. The measurement ran on the orchestrator's ANVIL-019 instruction. QA should confirm it accepts the policy, or treat this measurement as pending that acceptance. The policy file was not edited.
- The position cue lives in `positions.py`, not `position-protocol.json`. Editing the protocol file would break `test_report.py`, which assembles the saved task71 report against the current protocol. The protocol id is still `authored-code-position-v1`, even though the prompt differs. The per-forward `prompt_sha256` and the new `answer_format` field record the difference.
- The generation prompt change applies to all local cited generation, including research sessions. Only the RAG reference fixture was measured.
- `docs/engineering/capability-ledger.md` (lines 39 and 71) still says "Position exact-match is 0". That is the baseline result. Under the new format, start and middle are still 0, and end is 6/6. The ledger was not edited here, because the API serves it and `modelanvil/core/test_trustworthy_roadmap.py` checks it.
- CI's "Compose and reproduce" step now compares CI's run with this measurement under the unchanged v1 policy. Run 2 reproduced run 1 on this Mac. A Linux CI run has not been tried, because nothing was pushed. v1 requires exact generation statuses, so a decoding difference across hosts would fail that step. The intermediate commits `a6a7ab6` and `69627d2` still default to the 04916ee reference, so CI's reproduction step would fail on them. The report commit restores it.
- The two raw PostgreSQL logs keep one line of test-printed JSON with plain 64-hex digests, as the saved `premerge.json` gate records do. The JSON reports here store every 64-hex digest and the decoder tokenizer id as JSON unicode escapes. Stock gitleaks 8.28.0 `dir` finds 0 in this directory.
- Shared gates (G-local, G-skip, G-audit, G-secrets on the full tree and history) were not run for this note. They are run separately.
