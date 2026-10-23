# Resumable OCR pages and data recipes

Document workers now persist each completed OCR page before acknowledging permission to process the next page. A failed attempt exposes saved page numbers and total page count in the specialist job status. Retry verifies artifact checksums, frozen input identity, page raster, dimensions, rasterization settings and runtime versions before reusing a page. Layout and recognition execute only for missing pages. Completed-page token usage is aggregated once; started attempts consume the existing currency-free attempt quota. Cancellation, stale fencing and metadata-only egress prohibit checkpoints and publication. No partial document is published.

The Recipes screen provides an editable dependency graph and a labelled ordered list. Definitions use `modelanvil.recipe.v1`, import/export as JSON, and are saved as immutable content-addressed artifact versions. Run bindings freeze source artifacts, model snapshot, explicit device, runtime, protected sources, worker pool and quota policy. Client recipes cannot specify executables, evaluation code or remote model providers.

Supported steps:

- Source: original JSON, CSV, DOCX and PDF bytes through the existing source extractors, or canonical JSONL. Source locations and complete source groups survive transformation.
- Sample: deterministic selection with an explicit seed and limit.
- Expression: literal strip, lower, upper or replacement on text.
- Template: literal text with `{{value}}` and `{{source}}` substitution.
- Generate: actual local text, finite JSON or Python output from verified model files. Python is parsed for syntax and stored as data; it is never executed.
- Validate: minimum characters, required literal strings and required JSON keys. Invalid generations are recorded with measured usage and rejection reasons.
- Merge: combine two to four earlier outputs of the same type.
- Output: one final step; every step must contribute to it.

A generation worker loads the existing bounded local inference runtime, with explicit CPU, Apple MPS or MLX selection. Optional generation packages are not required for a deterministic CPU worker. Register workers with `manage.py run_recipes --pool-id <id> --name <name> --device cpu|mps:0|mlx:0`. Model/runtime failures fail the attempt rather than becoming ordinary validation rejections.

Full execution requires a completed, nonempty preview of identical recipe/source/model/runtime/protected bindings and explicit review. Preview results can be restored after a browser reload. Full runs publish through the existing dataset preparation service, advancing the dataset's immutable revision for the training picker. Privacy, deduplication and protected-source checks run before generation and publication. Canonical protected inputs exclude complete source groups; prepared manifests protect their validation and test groups.

Each completed step and generation row has an immutable, checksum-verified checkpoint. Retry reuses saved rows; it does not regenerate them. A final result checkpoint survives lost commits, while job fencing and idempotent admission prevent duplicate publication and quota events. Quotas reserve three attempt units and settle started attempts; tokens report unique completed generation calls, including validation rejections. Usage from an interrupted unfinished call cannot be reconstructed and is not represented as a completed-call total.

Current bounds are 64,000-byte definitions, 2–12 steps, 1–4 sources, 16 MiB and 256 records per source, at most three preview rows per transform/generation step, 32 rows per generation step, 64 generation calls per attempt, 128 merged rows, 256 new tokens and a 120-second generation-row deadline. PDF and specialist document limits remain those of their respective existing import/runtime paths. Graph cycles, unused steps, unsupported fields and executable expressions are refused.

## Verification on 12 October 2026

The isolated feature snapshot passed 773 backend tests (25 optional/platform skips), 145 frontend tests, production and Storybook builds, migration consistency and fresh database migration. The focused recipe/specialist checks cover immutable versions, reviewed-preview admission, source protection before model loading, malformed output, partial-row recovery, lost-commit replay, cancellation, quota binding identity, corrupt checkpoints, scope and stale publication fencing.

Actual Mac inference used the previously pinned GLM-OCR/PP-DocLayoutV3 snapshots and Apache-2.0 `HuggingFaceTB/SmolLM2-135M-Instruct` revision `12fd25f77366fa6b3b4b768ec3050bf629380bac`:

- After page 1 of an authored two-page scanned PDF was saved, an injected worker interruption occurred before child acknowledgement. Retry reused page 1 and processed only page 2, producing eight layout regions and two canonical rows; saved-page usage was counted once and two started attempts were charged.
- After the first actual MPS generation row was saved, an injected interruption failed the recipe attempt. Retry generated only the remaining row. A reviewed full run published one immutable revision; replay and stale commit did not create another revision.
- The tiny model produced accepted text and Python syntax. Its JSON response was malformed and remained an explicit measured rejection; this is evidence of output validation, not evidence of JSON-generation quality.
- Actual CPU recipes processed CSV, DOCX, PDF and OCR canonical JSONL sources; a two-source merge preserved source groups and all original locations.
- The browser restored the real preview, admitted a reviewed full run, and displayed its completed publication and origins.

Machine-readable evidence is in `verification/modelanvil-resume-recipes-2026-10-12.json`. These authored fixtures qualify execution and recovery mechanics. Representative document/model quality, non-Mac accelerators, remote generation providers and larger streaming recipes remain pending.

Local recipe workers refresh their heartbeat while idle and become offline when stopped. `--once` is for a single poll, not persistent registration; run the normal command while submitting browser jobs. Completed full runs link to their exact published dataset revision for row, split, artifact and lineage inspection. The additional local acceptance run is recorded in [manual QA](verification/manual-qa-2026-10-12/local-workflows.md).

## Local compute setup

Infrastructure now offers **CPU data recipes** as a shipped profile. Register it with an active envelope pool, save the one-time credential and run the displayed `run_worker --profile cpu-recipes` command with the same database and artifact storage as the API. Deterministic CPU recipes need no optional generation packages. The worker advertises CPU generation only when the pinned inference packages are installed. Apple MPS and MLX generation retain the explicit `run_recipes --device` operator command. Newly provisioned profiles require fresh heartbeats and active credentials before queueing. Observed legacy workers are refused when stale, draining or without slots.

Selecting a completed full recipe run restores its frozen definition and source/model/device bindings. Publication still requires selecting and reviewing a matching successful preview; restoring history never restores an approval checkbox.

## CPU recipe verification, 23 October 2026

The [current bounded recipe receipt](verification/task21-cpu-recipes-2026-10-23/report.md) records real pretrained CPU process recovery, actual text/JSON/code fixture generation, measured malformed-output rejection, cancellation without publication, and browser publication of seven rows from four real source formats into the Training picker. Verified CPU reference bundles are supported alongside pinned pretrained snapshots. Registered model/tokenizer pins and current access are checked before checkpoints and publication; runtime failures fail the attempt rather than becoming validation rejections. The editor defaults to CPU and shows actual local device/token bounds. External Chat targets are excluded from the local recipe selector.

A real eight-character output exposed a repetition-detector bug: one copy of a short unit was treated as repeated. The shared detector now requires three copies as documented. Minimum-length and privacy filters still apply. Generated rows retain review-required provenance; the authored automated review establishes execution mechanics, without certifying representative output quality or accelerator/remote/production qualification.
