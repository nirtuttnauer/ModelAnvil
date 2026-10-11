# ModelAnvil open dataset source bank

Research date: 8 October 2026. Status: Initial catalog and product specification; download connectors are not implemented or qualified.

## Recommendation

Add a searchable Dataset Bank to ModelAnvil. A user chooses a task preset such as SVG starter, previews a small sample, and downloads the selected source snapshots into authorized storage. Preparation recipes turn raw sources into versioned datasets with retained provenance and license records.

This catalog contains 23 sources: 10 SVG asset collections and 13 datasets or media fixtures across text, preferences, reasoning, code, tool calls, images, speech, video, and numeric outputs. SVG collections are useful source corpora, but they are not equivalent to datasets of verified natural-language instructions paired with SVG code. A source's storage format is separate from the intended model output. Container conversion does not supply missing task labels or qualify a training recipe.

## Open license policy

For this bank, open means a declared license permits reuse, modification, and redistribution, including commercial use, subject to its obligations. Noncommercial-only, no-derivatives, research-only, and unclear asset licenses are excluded. Attribution and share-alike sources remain open, but their obligations must be visible. The default profile includes permissive and attribution licenses; share-alike material is an explicit project choice.

The listed licenses are publisher declarations inspected on the research date. Each production connector must still qualify its selected assets at an immutable revision and check exceptions. A code repository license must not be substituted for a dataset or graphics license. Inclusion here is a research candidate status, not a blanket rights clearance for future revisions or generated models.

## Initial source catalog

| Source | Type | Declared asset or dataset license | Acquisition design | Useful for |
| --- | --- | --- | --- | --- |
| [Lucide](https://github.com/lucide-icons/lucide) | SVG asset collection | [ISC AND MIT](https://github.com/lucide-icons/lucide/blob/main/LICENSE) | Git snapshot | Outline icons with consistent geometry and semantic filenames. |
| [Tabler Icons](https://github.com/tabler/tabler-icons) | SVG asset collection | [MIT](https://github.com/tabler/tabler-icons/blob/main/LICENSE) | Git snapshot | Outline and filled UI icon variants. |
| [Heroicons](https://github.com/tailwindlabs/heroicons) | SVG asset collection | [MIT](https://github.com/tailwindlabs/heroicons/blob/master/LICENSE) | Git snapshot | UI icons in several sizes and styles. |
| [Bootstrap Icons](https://github.com/twbs/icons) | SVG asset collection | [MIT](https://github.com/twbs/icons/blob/main/LICENSE) | Git snapshot | UI icons with outline and filled shapes. |
| [Phosphor Icons](https://github.com/phosphor-icons/core) | SVG asset collection | [MIT](https://github.com/phosphor-icons/core/blob/main/LICENSE) | Git snapshot | Icons spanning multiple stroke weights and styles. |
| [Feather Icons](https://github.com/feathericons/feather) | SVG asset collection | [MIT](https://github.com/feathericons/feather/blob/main/LICENSE) | Git snapshot | A compact outline-icon collection suitable for initial experiments. |
| [Material Design Icons](https://github.com/google/material-design-icons) | SVG asset collection | [Apache-2.0](https://github.com/google/material-design-icons/blob/master/LICENSE) | Git snapshot | SVG assets from the Material icon family. |
| [Twemoji graphics](https://github.com/jdecked/twemoji) | SVG asset collection | [CC-BY-4.0](https://github.com/jdecked/twemoji/blob/main/LICENSE-GRAPHICS) | Git snapshot | Colored emoji SVG artwork indexed by Unicode sequences. |
| [OpenMoji](https://github.com/hfg-gmuend/openmoji) | SVG asset collection | [CC-BY-SA-4.0](https://github.com/hfg-gmuend/openmoji/blob/master/LICENSE.txt) | Git snapshot | Colored and monochrome emoji with accompanying metadata. |
| [Game Icons](https://github.com/game-icons/icons) | SVG asset collection | [CC-BY-3.0](https://github.com/game-icons/icons/blob/master/license.txt) | Git snapshot | Game-related silhouettes and symbolic artwork organized by contributor. |
| [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1) | Dataset | [Apache-2.0](https://huggingface.co/datasets/OpenAssistant/oasst1) | HF snapshot | Human conversation trees and ranking signals for supervised and preference training. |
| [Databricks Dolly 15k](https://huggingface.co/datasets/databricks/databricks-dolly-15k) | Dataset | [CC-BY-SA-3.0](https://huggingface.co/datasets/databricks/databricks-dolly-15k) | HF snapshot | Instruction following, question answering, and summarization examples. |
| [Anthropic HH RLHF](https://huggingface.co/datasets/Anthropic/hh-rlhf) | Dataset | [MIT](https://huggingface.co/datasets/Anthropic/hh-rlhf) | HF snapshot | Chosen and rejected conversations for preference optimization and reward modeling. |
| [GSM8K](https://huggingface.co/datasets/openai/gsm8k) | Dataset | [MIT](https://huggingface.co/datasets/openai/gsm8k) | HF snapshot | Grade-school math problems with worked answers for training and held-out evaluation. |
| [LibriSpeech](https://www.openslr.org/12) | Dataset | [CC-BY-4.0](https://www.openslr.org/12) | HTTP archive | Read English speech aligned with transcripts. |
| [Fashion MNIST](https://github.com/zalandoresearch/fashion-mnist) | Dataset | [MIT](https://github.com/zalandoresearch/fashion-mnist#license) | Git snapshot | Small grayscale clothing images and class labels for pipeline smoke tests. |
| [Mostly Basic Python Problems](https://huggingface.co/datasets/google-research-datasets/mbpp) | Dataset | [CC-BY-4.0](https://huggingface.co/datasets/google-research-datasets/mbpp) | HF snapshot | Python generation examples with natural-language tasks and tests. |
| [xLAM function-calling 60k](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | Dataset | [CC-BY-4.0](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k) | HF snapshot | Queries, tool schemas, and structured function-call answers. |
| [HumanEval](https://github.com/openai/human-eval) | Dataset | [MIT](https://github.com/openai/human-eval/blob/master/LICENSE) | Git snapshot | Python completion benchmark; evaluation only in default presets. |
| [dSprites](https://github.com/google-deepmind/dsprites-dataset) | Dataset | [Apache-2.0](https://github.com/google-deepmind/dsprites-dataset/blob/master/LICENSE) | Git snapshot | Synthetic binary shape images with known factors; small image-generation and conversion fixture. |
| [LibriTTS](https://www.openslr.org/60/) | Dataset | [CC-BY-4.0](https://www.openslr.org/60/) | HTTP archive | English speech and text designed for text-to-speech research. |
| [Big Buck Bunny](https://peach.blender.org/download/) | Dataset | [CC-BY-3.0](https://peach.blender.org/about/) | HTTP archive | Open movie for video decoding, clip preparation, and limited generation experiments; not a diverse captioned corpus. |
| [ElectricityLoadDiagrams20112014](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014) | Dataset | [CC-BY-4.0](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014) | HTTP archive | Electricity consumption series for numeric forecasting and table-output adapters. |

## Source specific preparation

- **Lucide:** Lucide uses ISC; the license also identifies Feather-derived icons under MIT. Preserve both notices. Deduplicate against Feather.
- **Tabler Icons:** Preserve copyright and permission notice. Group style variants and exclude branded assets by default.
- **Heroicons:** Preserve copyright and permission notice. Group size and style variants of each concept before splitting.
- **Bootstrap Icons:** Preserve copyright and permission notice. Filter branded and duplicate variants in the preparation recipe.
- **Phosphor Icons:** Preserve copyright and permission notice. Keep weight and style variants in the same split.
- **Feather Icons:** Preserve copyright and permission notice. Significant conceptual and asset overlap with Lucide requires cross-source deduplication.
- **Material Design Icons:** Preserve the license and applicable notices; track modifications. Qualify selected SVG directories and exclude font binaries.
- **Twemoji graphics:** Graphics use CC BY 4.0; code has a separate license. Preserve attribution, license link, source references, and modification records. Do not infer text captions from codepoints without a versioned Unicode mapping.
- **OpenMoji:** Preserve attribution and share-alike conditions for applicable redistributed adapted material. Opt-in under project distribution policy; do not automatically infer how obligations apply to trained weights.
- **Game Icons:** Attribute the original artist, not only the hosting site. Preserve author directory and asset origin. Verify per-asset exceptions during ingestion.
- **OpenAssistant OASST1:** Preserve license and notices. Reconstruct conversation trees; do not treat each message as an independent complete conversation. Keep trees together across splits.
- **Databricks Dolly 15k:** Publisher allows academic and commercial use under CC BY-SA 3.0. Preserve Databricks and relevant Wikipedia attribution. Opt-in under project distribution policy.
- **Anthropic HH RLHF:** Preserve MIT notice. Parse paired conversation histories correctly. Distinguish preference data from red-team data and do not use chosen responses as unconditional ideal-answer SFT.
- **GSM8K:** MIT is declared on the official dataset card. Preserve its license evidence. Keep benchmark test examples out of training and synthetic-data seeds.
- **LibriSpeech:** Preserve attribution and source metadata. Scope this preset to corpus archives; separate original-book and MP3 downloads are not included.
- **Fashion MNIST:** Preserve the publisher MIT notice. This is a small image-classification fixture, not a general vision-language training corpus.
- **Mostly Basic Python Problems:** Preserve attribution. Use official training split only for training; keep validation, test, and prompt examples distinct. Execute generated code only in isolated evaluators.
- **xLAM function-calling 60k:** Gated access requires user acceptance and credentials. Inspect the current access conditions before enabling download; never accept them silently. Preserve attribution and APIGen citation.
- **HumanEval:** Preserve MIT notice. Exclude benchmark tasks, solutions, and derived examples from training and synthetic seeds. Sandbox all execution.
- **dSprites:** Preserve repository license and notices. Decode numeric arrays without executing notebooks or loading untrusted pickled metadata. This is not a natural-image caption corpus.
- **LibriTTS:** Preserve attribution, speakers, and transcript alignment. Related to LibriSpeech; check overlap before mixing. Select corpus archives, not separate original-source books or recordings.
- **Big Buck Bunny:** Scope to the released movie under the official CC BY 3.0 declaration and retain Blender Foundation credit. Exclude separately released isolated score and unrelated site files; their terms can differ. No prompt/clip captions are assumed.
- **ElectricityLoadDiagrams20112014:** Preserve Artur Trindade attribution. Parse semicolon delimiters and documented numeric conventions. Account for Portuguese time and daylight-saving encoding; zero may mark a client not yet present.

## Sources by intended output

- **SVG vector graphics (svg):** [Lucide](https://github.com/lucide-icons/lucide), [Tabler Icons](https://github.com/tabler/tabler-icons), [Heroicons](https://github.com/tailwindlabs/heroicons), [Bootstrap Icons](https://github.com/twbs/icons), [Phosphor Icons](https://github.com/phosphor-icons/core), [Feather Icons](https://github.com/feathericons/feather), [Material Design Icons](https://github.com/google/material-design-icons), [Twemoji graphics](https://github.com/jdecked/twemoji), [OpenMoji](https://github.com/hfg-gmuend/openmoji), [Game Icons](https://github.com/game-icons/icons)
- **Prose chat and reasoning (txt, md, jsonl):** [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1), [Databricks Dolly 15k](https://huggingface.co/datasets/databricks/databricks-dolly-15k), [GSM8K](https://huggingface.co/datasets/openai/gsm8k)
- **Rankings and reward scores (json, jsonl, parquet):** [Anthropic HH RLHF](https://huggingface.co/datasets/Anthropic/hh-rlhf), [OpenAssistant OASST1](https://huggingface.co/datasets/OpenAssistant/oasst1)
- **Code and notebooks (py, source_files, ipynb):** [Mostly Basic Python Problems](https://huggingface.co/datasets/google-research-datasets/mbpp), [HumanEval](https://github.com/openai/human-eval)
- **Structured records and tool calls (json, jsonl, yaml):** [xLAM function-calling 60k](https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k)
- **Raster images (png, jpeg, webp, tiff):** [dSprites](https://github.com/google-deepmind/dsprites-dataset), [Fashion MNIST](https://github.com/zalandoresearch/fashion-mnist)
- **Speech audio (wav, flac, mp3, ogg):** [LibriTTS](https://www.openslr.org/60/), [LibriSpeech](https://www.openslr.org/12)
- **Video (mp4, webm, mov):** [Big Buck Bunny](https://peach.blender.org/download/)
- **Tables and time series (csv, tsv, parquet, arrow, npy, hdf5):** [ElectricityLoadDiagrams20112014](https://archive.ics.uci.edu/dataset/321/electricityloaddiagrams20112014)
- **Documents presentations and web pages (html, pdf, docx, pptx, epub):** No dedicated document-layout output corpus qualified; use a separately licensed synthetic template recipe.
- **Custom formats 3D and other modalities (custom):** No approved generic corpus; requires task-specific source review and a validated adapter.

## SVG starter workflow

1. Select the SVG starter preset with Lucide, Tabler, Heroicons, Bootstrap, Phosphor, Feather, and Material SVG assets. Start with a bounded preview rather than downloading every repository.
2. Resolve each source to a commit, retain its license evidence, select only qualified SVG paths, and record every asset hash and origin.
3. Parse SVG as untrusted structured input. Render in an isolated environment with scripts, external references, and network access disabled; enforce dimension, time, and complexity limits. Record rejected or unsupported features.
4. Keep the original SVG and create a rendered image. Extract available names, tags, styles, and Unicode metadata without claiming they are detailed captions.
5. Deduplicate across all sources. Group conceptual icons and size, color, stroke-weight, and style variants before assigning train/validation/test splits. Lucide and Feather require particular attention to overlap.
6. Produce task-specific views. Image-to-SVG uses rendered-image/SVG pairs. Text-to-SVG can start from clearly labeled weak descriptions derived from names; richer captions need separate generation, review, and provenance. SVG repair or editing examples require a versioned transformation with a known target.
7. Publish a dataset version with asset references, recipe version, split assignments, attribution manifest, validation report, and compatible model processors. The training workflow accepts it only when a supported recipe can consume the chosen view.

These sources emphasize icons and emoji. They do not establish coverage of long illustrations, engineering diagrams, charts, animation, typography, or complex SVG editing. A useful later source is a synthetic corpus generated from parameterized shapes and charts, with owned generation code, controlled text descriptions, and known geometry.

## Preset cards and download behavior

Cards should show task, source type, modalities, declared license, attribution/share-alike flags, last check date, immutable revision, sample preview, available splits, measured download/storage size, and preparation needs. Unknown sizes must be shown as unknown. Users can select a subset or sample limit and choose destination storage under their organization's policy.

Download resolves to one versioned import job. Repeated clicks reuse a matching completed artifact within the authorized scope. Jobs support progress, cancellation, retry, checksums, and interrupted-transfer recovery. Failed or incomplete downloads never appear as ready datasets. Cached data, previews, and artifacts must respect organization isolation.

A new upstream version is offered as an update and never changes an existing dataset version. Changed licenses or asset paths require a new review. The adapter must archive the relevant license texts and notices and produce attribution records for exports. Download eligibility and training compatibility are separate statuses.

## Sources held outside the open bank

[SVG Stack](https://huggingface.co/datasets/starvector/svg-stack) is relevant to SVG research, but no dataset license declaration was found on the inspected official card. It stays outside the approved downloadable bank until asset rights and licensing can be verified. [StarVector's code repository](https://github.com/joanrod/star-vector) having an Apache license does not establish the gathered dataset's license.

Mixed-license aggregation sites also need per-asset checks rather than a single site-wide open badge. Public access and an open file format are insufficient evidence of an open content license.

## What has been prepared

The accompanying JSON catalog records source identities, output groups, license evidence URLs, download connector designs, preparation requirements, and three SVG presets. Fields for precise revisions, byte sizes, and counts remain unset until qualification. Connector paths are candidates to test against the selected snapshot. HumanEval is evaluation-only by default; xLAM requires user-approved gated access. FineVideo stays held pending license and access-term review. No bulk datasets have been downloaded, and the catalog does not yet implement a clickable interface or fetcher.
