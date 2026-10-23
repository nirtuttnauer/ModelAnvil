# TASK-66 — pinned token windows and immutable rechunking

2026-10-23. New lexical-index imports use actual offline WordPiece tokenization rather than character slicing. Source text remains exact, including whitespace, combining marks, CJK characters, emoji and characters normalized away by the tokenizer.

## Pins and behavior

The bundled 466,247-byte tokenizer is from `sentence-transformers/all-MiniLM-L6-v2` revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, SHA-256 `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`. Apache-2.0 license and source notice accompany the asset. `tokenizers==0.22.2` is pinned; no tokenizer download or remote document request occurs during indexing. Runtime verifies package version and asset bytes, and disables truncation, padding and added special tokens.

A chunk has at most the requested actual encoded content tokens; overlap has at most the requested independently encoded tokens. Paragraph boundaries are preferred, then sentence boundaries, in the latter half of a token window when they allow forward progress. WordPiece continuation boundaries can re-tokenize differently, so both chunk length and overlap are re-encoded and checked. Each chunk stores exact original character spans, source-token offsets, actual token/overlap counts and tokenizer pins. Defaults are 254 content tokens/32 overlap; valid sizes are 16–4096, with overlap at most half. A later inference/embedding runtime must account for its special tokens and own context limit independently.

Chunk recipes have immutable digests. Reimporting unchanged text at the same source identifier reuses its document revision and chunks. Changing the chunk recipe creates another immutable chunk set for the same source revision; older indexes keep their original members and text. Legacy character chunks remain available to older indexes and never enter a new token-recipe snapshot. All active sources are included under the requested recipe, including sources omitted from the latest upload. A token index is bounded to 2 MB active UTF-8 source and 10,000 chunks; errors roll back the transaction. The source identifier remains necessary to recognize the same document across imports.

## Verification

- Full pre-integration backend: 996 tests passed, six optional skips. Final targeted RAG/authoring/privacy suite: 46 pass. Clean base runtime: 30 RAG/authoring/OpenAPI tests pass without Torch/Transformers. All three existing PostgreSQL checks pass. Migration check passes.
- Exact reconstruction and actual token budgets pass on accented/combining/CJK/emoji/control text and 30 seeded worst-case sequences. Hash determinism, zero overlap, paragraph/sentence preference, altered tokenizer refusal, invalid inputs, unchanged-source reuse, legacy retention, whole-corpus rechunking and rollback are covered by `modelanvil/rag/test_chunking.py` plus existing workflow tests.
- Actual browser/API import → unchanged reimport → new recipe → reload passes at 1440/390. Document revision remains unchanged; unchanged manifest repeats; the previous index remains queryable; returned Unicode spans exactly equal original text. The persisted receipt includes tokenizer, unit, recipe and overlap semantics. One desktop/mobile inspection batch found no overflow or clipped controls.
- 226 frontend tests, production build and Storybook pass. The fully resolved base dependency set, including the added tokenizer/Hub pins, reports no known vulnerabilities in the current audit. Optional DiskCache remains tracked separately in TASK-74.

No vector embeddings, model generation, semantic retrieval accuracy or hardware qualification is inferred. TASK-67 owns actual embedding and worker-index execution. Final-head CI and affected integration checks gate merging.
