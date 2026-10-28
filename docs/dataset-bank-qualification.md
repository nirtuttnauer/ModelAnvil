# Qualified Dataset Bank downloads

Complete releases have separate evidence and download scope; see [full-download qualification](dataset-bank-full-downloads.md). This page records the sample qualification.

## Expansion on 17 October 2026

Three existing candidates now support verified preview, queued acquisition, canonical publication and authenticated downloads. This brings the bank to fourteen qualified sources: Lucide and thirteen HTTP sample inventories totaling 320 records.

| Source | Qualified samples | Upstream selection | Pinned range bytes |
| --- | ---: | --- | ---: |
| GSM8K | 80 | Twenty evenly spaced problems from each of four row groups in the `main` training shard | 1,124,262 |
| MBPP | 20 | Twenty evenly spaced tasks from the `full` training shard | 148,922 |
| Dolly 15k | 20 | First twenty complete JSONL instructions in a bounded 256 KiB prefix | 283,836 |

The qualifier fetched the publisher data and license cards at immutable Hugging Face commits, validated the source fields, then independently refetched every admitted sample through the production range reader. Manifests and archived cards are in `catalog/qualified-datasets/`. GSM8K question/answer fields, MBPP code and test lists, and Dolly instruction/context/response/category fields remain intact. Code and tests are stored without execution. Group identities use GSM8K questions, MBPP task IDs and Dolly instruction/context pairs, keeping alternative answers together. Only upstream training records are admitted; official benchmark test, validation and prompt splits remain outside these inventories.

Dolly requires explicit share-alike consent (`project_policy.allow_share_alike: true`). These three sources support sample scope only; complete releases and training adapters are not qualified. Unknown upstream coverage is not inferred from sample counts.

Reproduce this expansion with:

```sh
python -m scripts.qualify_bank_subsets \
  --source math-gsm8k --source code-mbpp --source text-dolly15k \
  --date 2026-10-17 --report /tmp/dataset-bank-expansion.json
```

## Original qualification on 11 October 2026

Qualified on 11 October 2026. The ten additions have frozen, tested inventories totaling 200 samples. They now support actual previews, queued acquisition, verified publication, and authenticated artifact downloads. The existing Lucide connector remains available.

| Source | Qualified samples | Upstream selection | Pinned range bytes |
| --- | ---: | --- | ---: |
| Smol-Magpie-Ultra | 20 | Four row groups in the first training shard; this configuration only | 11,325,167 |
| UltraChat 200k | 20 | Four row groups in the first `train_sft` shard | 11,944,010 |
| SQuAD 1.1 | 20 | Four row groups in the training shard; checked answer offsets | 824,159 |
| UltraFeedback Binarized | 20 | Four row groups in the first `train_prefs` shard; chosen/rejected preserved | 11,906,411 |
| Glaive function calling v2 | 20 | First complete conversations in the JSON prefix; source strings retained | 311,990 |
| CLEVR v1.0 | 10 | Training images paired with complete questions found in the first 2 MiB of the question member | 16,418,346 |
| CSTR VCTK 0.92 | 20 | Two mic1 utterances for each of ten speakers, paired with transcripts | 15,888,546 |
| LibriTTS-R | 10 | Complete WAV/transcript pairs within the first 8 MiB compressed prefix of `train_clean_100` | 8,388,608 |
| UCI Iris | 20 | Evenly spaced rows in the source table | 3,738 |
| UCI Wine Quality | 40 | Twenty evenly spaced rows each from red and white wine tables | 91,353 |

The transfer figures count the admitted ranges, including overlapping ranges and archive/Parquet metadata; they exclude locally archived license notices. They are qualified transfer bounds, not full source sizes. Progress counts decoded, verified sample bytes. A smaller sample selection can still require shared archive or row-group ranges.

## Qualification and integrity

The qualifier fetched actual publisher bytes, decoded each selected record, archived publisher license declarations/notices, and independently refetched every record through the production range reader. Each admitted range, decoded sample and notice has a SHA-256 digest. Hugging Face selectors use immutable repository commits; archive selectors pin the observed range bytes. The catalog revision is the SHA-256 of the canonical subset manifest in `catalog/qualified-datasets/`. Publisher full-file checksums are recorded when available but were not independently verified for the complete archives/shards.

A separate live pilot used an isolated SQLite database and filesystem storage, the real queued executor, and authenticated artifact download endpoints. All ten acquisitions reached `ready`, published all 200 rows, and returned matching artifact digests. The pilot also verified downloads of 10 PNGs, 20 FLACs and 10 WAVs. Local fixture tests exercise tampering, invalid range responses, limits, manifest changes, retry, canonical publication, media lineage and tenant isolation. Existing acquisition checks cover cancellation, worker fencing, budgets and project boundaries.

Records retain original fields as JSON/table blocks. Image/audio bytes become committed artifacts in the acquisition's tenant and project; media blocks carry a content-addressed `asset_ref` and an authorized downloadable `metadata.artifact_ref`. Attribution, source selectors, hashes, notices and group identities remain in snapshot/dataset metadata. Prompt, passage, image, speaker and duplicate feature groups stay together in local splits; only the listed upstream training selections are admitted. This qualification does not establish training adapters, full-corpus coverage, complete question coverage for CLEVR, cross-source deduplication, representative evaluation splits, or publication of larger inventories.

## Run a download

Install the pinned requirements, including PyArrow, on the API/worker environment. In Infrastructure, choose **Register local worker**, select **Dataset Bank acquisition**, and choose an active pool that allows verified dataset output. Save the one-time credential and run the displayed `python manage.py run_worker --worker-id WORKER_ID --profile dataset-bank` command on the trusted API/storage host; paste the credential at its hidden prompt. Registration stays offline until the worker connects. Existing operator-installed workers can still use the documented `dataset_acquisition` capability and `--executor modelanvil.data.bank.acquisition.bank_acquisition_executor` command. In Dataset Bank, inspect the source's qualified scope and transfer size, select any required acquisition budget, and choose **Review acquisition**, inspect the real samples and frozen plan, then **Confirm and acquire**. Refresh to inspect the published revision; cancelled or failed imports can resume from verified record checkpoints.

SQuAD and Dolly require the unchecked share-alike consent control to be selected explicitly. The API requires the literal boolean `project_policy.allow_share_alike: true`; strings and numeric substitutes are refused. Other source notices and attribution obligations remain applicable.

Use `GET /api/v1/artifacts/{artifact_id}/download/` with current tenant/project authorization for canonical JSONL and media artifacts. Media artifact IDs are recorded in canonical blocks. Failed integrity checks never publish a ready dataset.

`GET /api/v1/dataset-bank/sources/{source_id}/upstream/` returns the frozen revision for these HTTP sources with `upstream_head_revision: null`, `moved: null`, and `automatic_update_check_supported: false`. Admitting another revision, record, range or release requires requalification.

## Reproduce or extend qualification

```sh
python -m scripts.qualify_bank_subsets --date 2026-10-11 --report /tmp/dataset-bank-qualification.json
# One source:
python -m scripts.qualify_bank_subsets --source numeric-iris --date 2026-10-11
```

This command makes real HTTPS requests and updates manifests, license evidence and catalog metadata for review. It never executes remote dataset loading scripts or writes extracted archive members. Keep optional measurement reports, pilot databases and dataset payloads in temporary/ignored storage. Re-run the application publication/download checks and repository checks before accepting newly captured evidence. Mutable publisher pages or upstream revisions can produce a new manifest digest; existing qualified revisions must not be silently relabeled.

Lucide carries a SHA-256-pinned inventory for its qualified immutable commit. If the public GitHub tree API returns HTTP 403 or 429, the worker verifies that inventory checksum and revision, then downloads raw files and recomputes their Git blob digests. It never substitutes another upstream revision. A saved acquisition keeps its original subset and split seed; restore or resume it, or use another project for a different subset.
