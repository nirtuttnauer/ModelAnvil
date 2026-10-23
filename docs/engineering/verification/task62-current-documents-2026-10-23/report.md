# TASK-62 — current bounded OCR and mixed-document publication

23 October 2026. The previously outstanding mixed scanned-page publication criterion now has actual execution evidence on this Mac. This addendum preserves the earlier [software-only report](../task62-documents-2026-10-23/report.md) and its limits. It does not qualify representative recognition accuracy, languages, layouts, customers or production.

## Exact execution

Runtime source: merged main `4b4ba7220e5e4afb5b368df5eca05496fe5eceb5`; specialist runtime digest `c40bb5b7386ecf2eeb8a39f77ca9bb2283dc40fec5c90c7f37f4274fb486b418`. Subsequent PR49 changed documentation only. Apple M5 Pro, 48 GiB unified memory, macOS 27.0.1; isolated Python 3.12 environment with Laya 0.4.3, Torch 2.13.0, Transformers 5.14.0, MLX-VLM 0.7.6, MLX 0.32.3, Pillow 13.0.0, Safetensors 0.8.0 and PDFium 5.14.0. Execution device was `mlx:0`; there was no CPU fallback.

Only the existing frozen, independently checksum-verified public model files were acquired: MIT `mlx-community/GLM-OCR-bf16` revision `24f15402e83baa0a80eeeaecf5480e172abc6f2e` and Apache-2.0 `PaddlePaddle/PP-DocLayoutV3_safetensors` revision `e4f489dc536556fc1be02b973ba06756e0d4a2ac`. Full file hashes and byte sizes are in the [actual receipt](actual-report.json). Model weights and disposable databases stay outside Git.

The actual authenticated Django API views admitted a durable OCR job into an isolated worker pool with an exact runtime/device capability and attempt quota. `execute_one` ran the real isolated specialist child, verified models, acquired its device lease, checkpointed both numbered pages, committed results and settled one attempt. This qualification uses Django's API test client, not a network HTTP/browser transport. Replaying admission returned the same request/job without duplicate execution.

The authored two-page PDF contains one embedded-text page and one raster-only page. Direct PDF text extraction previously refused that scanned page; OCR generated its content from raster pixels. The OCR-only worker recognized all three lines:

```text
SCANNED PAGE FIXTURE
Invoice sample: 2 review items
This text exists only as image pixels.
```

It also recognized the first page's sentence. Recognition consumed 1,880 input and 39 output tokens, with a reported 3.415 GB peak and 8.1751 seconds of model execution. The receipt's `publication_elapsed_seconds` measures only the separate publication resume and must not be reported as OCR latency.

## Publication and provenance

Two OCR page envelopes, two actual DOCX paragraph envelopes and two CSV record envelopes were combined and passed through the existing dataset preparation API into one immutable published six-row revision. Assertions verified all expected scanned-page text, page 2 locations, source-byte hashes, model/runtime provenance, canonical envelope validation, manifest byte checksum, exact sample IDs and source-group isolation. Three document groups all landed in train for this tiny split: validation and test are empty. This is publication/integrity evidence, not an evaluation suite.

The published manifest SHA-256 is `e98e263ec3a6fd2f9007b6cc5f9df34aa4028d6d63a377373269948fbcc9f486`. Source-to-combined artifact lineage is retained. OCR rows retain `review_required: true`; the work does not silently accept recognized text as reviewed ground truth. Both actual specialist jobs reserved three attempts and settled exactly one each.

## Observed layout limitation

The first, separately preserved [layout-guided worker result](layout-limitation.json) succeeded operationally but omitted the scanned page heading, retaining the other two lines. Its exact-reference assertion failed. The later OCR-only request deliberately omitted `layout_model`; it recognized the complete reference and supplied the published rows. These are two actual jobs, not a retry that overwrote a failure. No quality threshold was relaxed and no fixture text was substituted for model output. Layout-guided completeness remains unqualified for this fixture; users must review its extracted text.

The raw scripts, logs, fixtures and receipts are archived under the project's private `evidence/takeover-2026-10-23/current-documents` directory. The public structured receipts contain only authored fixture content and local artifact identities, without API secrets.
