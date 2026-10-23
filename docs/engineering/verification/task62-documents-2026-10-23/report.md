# TASK-62 — document evidence and remaining OCR qualification

2026-10-23. This report completes the documentation/software verification portion. TASK-62 remains blocked on the mixed scanned-page OCR publication criterion; the user requested skipping hardware/runtime blockers.

## Fresh software checks

46 existing regressions passed in the current pinned optional environment: `modelanvil.api.test_dataset_preparation_http`, `modelanvil.data.test_source_import`, `modelanvil.data.test_pdf_import`, `modelanvil.api.test_specialists`, `modelanvil.api.test_specialist_jobs`, `modelanvil.runners.test_specialist_runtime`.

The actual frontend dataset client exercised a real loopback Django HTTP server: upload, prepare, immutable publication, list and manifest download for CSV/JSON/DOCX and two-page embedded-text PDF. Assertions verify source-byte and text digests, exact rows, page/paragraph/record locations, one protected group per document, manifest bytes and lineage. These are local test transactions, not customer datasets or model-quality qualification.

Additional authored input fixtures independently extracted two rows each from PDF, DOCX and CSV and verified exact source hashes and locations. A mixed two-page PDF has one embedded-text page and one raster-only page; the second page has no extractable PDF text. Direct text import refused the whole document with OCR-required guidance. Real pinned PDFium rasterization produced both numbered RGB pages and digests. All four PDF page renderings were inspected; no clipped or unreadable fixture text was observed. The [structured receipt](fixtures.json) records digests, provenance, bounds and actual dependency versions, without customer content.

OCR/model generation was not replaced with fixture text. Specialist API and durable-worker tests use controlled model callbacks: they verify admission, checkpoint identity, cancellation, retry, fencing, lineage, project access and accounting, but their output does not measure recognition or layout accuracy.

## Remaining acceptance gap

A single published mixed PDF/DOCX/CSV dataset including recognized scanned-page content was **not produced**. The current process has no `MODELANVIL_SPECIALIST_PYTHON` configured. The available older GPU environment has Torch 2.9.0/Transformers 4.57.1 and lacks MLX/MLX-VLM; current specialist pins require the separate versions in `scripts/specialist_runtime.py`. The archived 12 October OCR/layout pilots cannot qualify the changed dependency and execution build.

Completing this criterion requires an isolated matching specialist runtime, verified immutable model files, an available supported Apple device, actual bounded OCR/layout inference and publication with source/page/model/runtime lineage. Representative accuracy and language/layout coverage require separate qualification. No customer decision is needed to continue independent implementation tickets.

## Scope overlap

Attributed notes were saved on TASK-21 and TASK-33. TASK-62 records extraction/OCR/layout/worker evidence; it does not change the approved data-recipe generation or document-chat/research/compaction requirements on those tickets.
