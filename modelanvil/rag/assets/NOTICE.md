# Bundled tokenizer

`minilm-tokenizer.json` is the unmodified 466,247-byte tokenizer from `sentence-transformers/all-MiniLM-L6-v2`, revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, licensed Apache-2.0 by its model card. See LICENSE-2.0.txt.

Source: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/tokenizer.json

SHA-256: `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037`.

The native tokenizers runtime is pinned to 0.22.2. Loading disables truncation, padding and added special tokens. RAG chunking reads these local bytes; it never downloads a tokenizer or sends document content to a provider. Unicode source text and offsets remain exact despite the tokenizer's case/accent normalization. This tokenizer pin does not qualify embedding semantics or model inference.
