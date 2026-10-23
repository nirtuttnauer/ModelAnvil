# Verified candidate exports

Open Releases → New candidate release after an actual CPU worker training run and its complete held-out evaluation. Choose the exact candidate/evaluation, quality threshold and recorded license evidence. The review freezes measured results and all required criteria. Failing quality or license criteria stay visible and do not qualify a release. Downloading a failing candidate for inspection preserves those failures in the archive.

A reviewed v2 bundle contains actual weights, tokenizer/configuration, frozen recipe/source/base/evaluation/license/model-card evidence, per-file checksums and a standalone standard-library consumer. Its consumer is frozen with the review; repeated downloads are byte-identical. Unzip in an empty Python environment and run `python -I infer.py . --prompt x --max-tokens 2`. The consumer checks the manifest before inference. This is bounded character/general-transformer CPU compatibility, not general Hugging Face, adapter, accelerator or production qualification.

Current checks revalidate evidence and access. The UI reports frozen and checked times; missing or changed evidence makes the review stale, hides its frozen case content and blocks export/serving. Restore authorized inputs, rerun an outdated evaluation and create a fresh review. Older reviews without immutable consumer/evidence pins also require a fresh review. A passing frozen review, endpoint pointer and old startup record alone do not establish current live serving readiness.

See [actual browser, empty-environment and stale-evidence verification](verification/task7-export-2026-10-23/report.md).

Pretrained CPU runs additionally support [recoverable merged Safetensors and Q8_0 GGUF exports](cpu-weight-exports.md), with separate format, held-out regression and release gates. The frozen reference release profile above remains bounded.
