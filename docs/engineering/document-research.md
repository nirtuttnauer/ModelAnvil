# Document chat, reviewed-page research and conversation memory

Chat → Documents & research provides owned-project sessions with a provisioned local CPU answer model, attached sources, actual lexical retrieval, validated citations and inspectable conversation memory. It reuses the actual RAG decoder/generation and current source authorization from TASK-11, and the measured-token, explicit-overflow approach from TASK-12. It does not replace those evaluations with generated scores.

## Provisioning

The answer profile is the Apache-2.0 `HuggingFaceTB/SmolLM2-135M-Instruct` snapshot at `12fd25f77366fa6b3b4b768ec3050bf629380bac`. Exact file sizes/hashes are in `modelanvil/rag/decoder-pins.json`. Provision the pinned optional CPU inference dependencies and a verified local cache, then register it in the chosen project:

```sh
MODELANVIL_RAG_DECODER_DIR=/absolute/verified/snapshot \
  python manage.py setup_rag_decoder --project PROJECT_UUID --accepted-license apache-2.0
```

`cache_rag_decoder` is an explicit operator download command when acquisition is intended; requests never download models. Install the pinned `requirements.documents.txt` dependencies for PDF extraction. The registered model remains Draft; bounded software execution and citation membership do not establish general answer quality or production qualification.

## Inputs and current gates

Attach one file up to 1 MiB at a time. Embedded-text PDF uses the pinned bounded pypdf child process; DOCX reads only its main-body paragraphs without following relationships or extracting archive paths. UTF-8 text and code are indexed as text and never executed. Source-byte hashes, extractor revisions and page/paragraph locations are preserved alongside reconstructed-text character spans. An attachment allows at most 256 location records and 32 KiB of location metadata; larger documents are refused whole. At most 50 source revisions and 2 MB of active source text enter a session index. Index chunks use the existing pinned token recipe.

Scanned PDFs are refused when a page needs OCR. Raw image input is not passed to the text decoder. The separate `attach-ocr` path requires a completed durable OCR request, a Qualified OCR model, current specialist runtime evidence and verified source/model/result artifacts; draft or stale OCR output is refused. Its extracted sources remain conditional on current artifact access and model qualification. Current OCR language/layout qualification remains held under TASK-62; archived pilots do not meet that gate. Audio attachment is unavailable until a separately qualified transcription path exists. Speech synthesis and an ASR evaluation proxy do not supply product transcription.

## Reviewed-page research

An engineer may explicitly fetch one or two HTTPS HTML/plain-text page URLs per step. Each exact origin must be installed by the operator through `MODELANVIL_ACQUISITION_ORIGINS` and approved for the project in Privacy settings. Offline policy refuses network work before starting a child. No question, conversation history, model output, cookies, host credentials or ambient proxy configuration is sent to a search provider.

The fetch child resolves public addresses, pins a checked address for the socket, verifies the original TLS hostname, refuses embedded credentials, redirects, non-200 responses, compressed bodies and unsupported media, and does not execute page scripts. Limits are 1 MiB per page, 8 seconds per page, a 20-second parent deadline and 2 MiB of child output. DNS and a blocked child are also bounded by the parent deadline. At most eight fetch steps are allowed per session. API receipts preserve actual URLs, retrieval timestamps, status, byte/text hashes, elapsed times and configured budgets.

Search is lexical over the explicitly fetched pages and attached documents. It is not a global web search engine or an autonomous crawler. A bounded, quoted disjunction of question keywords avoids PostgreSQL treating every question word as required; the actual retrieval query is recorded. The existing PostgreSQL full-text ranker and explicitly labeled SQLite compatibility path execute retrieval. No semantic-vector score is manufactured.

## Answers and history

Each question retrieves up to three currently accessible source spans. The actual native tokenizer/template counts the complete input and reserves 1–128 output tokens within the 2,048-token profile. Optional evidence omissions are recorded; a required question that cannot fit is refused. The local CPU device lease is shared with other installed model operations. A cooperative 30-second generation deadline is checked between model forward passes; it is not a hard process sandbox or a guarantee that a single forward pass can be interrupted.

The pinned `verbatim-prefix-recent-v1` compactor uses the actual tokenizer, a 64–512-token memory limit and a digest of its implementation. History that fits is retained whole. On overflow, the recent two messages get first claim, followed by bounded earlier prefixes. Every retained excerpt is a literal prefix of its source message; the receipt records roles, positions, source hashes, retained/original characters, actual token counts and omissions. It produces no invented summary. The history-content count excludes prompt wrappers; the final compiled input receipt includes all wrapper/template overhead. The complete saved turns remain inspectable while their source permissions remain valid. A session allows at most 20 questions and 64,000 history characters.

Historical citation numbers are untrusted context, not current evidence. Native ChatML delimiters in document/history/question text are broken before formatting, without changing stored source spans. Model text cannot grant tools or run code. Delivered citations must refer to supplied source numbers and accessible chunks; absent/unknown citations, explicit model abstention and lack of evidence have distinct outcomes. Membership validation does not prove that the answer is correct. The UI shows validation refusal instead of delivering an uncited answer.

Source removal, source/chunk tombstones, changed frozen source pins, withdrawn project grants, missing backing OCR artifacts and unavailable models are checked during retrieval and again before output/history reuse. Revoked content is excluded by the shared retrieval engine, including other RAG routes. If a saved turn depends on unavailable evidence, session answers, research history and memory are withheld. Clear conversation memory to continue with current sources, or start a new session if its model is unavailable. Stored audit/history rows are not silently erased by this visibility rule.

## API and recovery

All routes are under `/api/v1/research-sessions/` and require authenticated project scope. Read access is Viewer; mutations require Engineer. Sessions must belong to the active project even when resources have cross-project grants.

| Operation | Request |
|---|---|
| List sessions and provisioned models | `GET /research-sessions/` |
| Create | `POST` with `title`, `model_version` |
| Reload source/answer/memory state | `GET /research-sessions/{session_id}/` |
| Attach file | multipart `POST .../attach/` with `revision_no`, `file` |
| Attach qualified OCR | `POST .../attach-ocr/` with `revision_no`, `request_id` |
| Fetch explicit pages | `POST .../fetch/` with `revision_no`, `urls` |
| Search and answer | `POST .../ask/` with `revision_no`, `question`, optional `max_tokens`, `memory_tokens` |
| Remove a source | `POST .../remove-source/` with `revision_no`, `document_id` |
| Clear saved turns/memory | `POST .../clear-memory/` with `revision_no` |

Every mutation locks its session row and checks the revision. PostgreSQL locks only the session itself, avoiding its nullable index join. Stale requests return conflict before another model run. If a client disconnects, the bounded request may finish; reload before retrying. The same stale revision cannot silently repeat the operation. Fetch/extraction failures leave the existing source revision intact. Clearing memory retains the currently accessible source index.

Measured HTTP/PostgreSQL/browser receipts and explicit model limitations are in the [TASK-33 evidence directory](verification/task33-research-2026-10-24/). Qualification covers this small local profile and authored cases. OCR/ASR, representative research accuracy, broader document languages/layouts and larger model/hardware profiles retain their separate gates.
