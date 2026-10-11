# Complete Dataset Bank releases

Qualification completed on 2026-10-12 (Asia/Jerusalem), after downloads and checks on October 11–12.

The ten sources added in the open-dataset expansion have a separate complete-release acquisition scope. `catalog/full-datasets/` pins every original dataset file and split, every byte's chunk digest, complete-file SHA-256, publisher checksums where available, content checks and archived notices. A full qualification is admitted only after every file is downloaded and validated. Dataset payloads stay outside Git.

The sample scope remains available for canonical training preparation. A complete release downloads the publisher's original ZIP, gzip TAR, Parquet or JSON files and a verification manifest. Full raw releases do not create canonical training revisions or qualify training adapters. Preview continues to show qualified samples.

## Release scope

| Source | Original files | Complete bytes | Coverage |
| --- | ---: | ---: | --- |
| `image-clevr` | 1 | 19,021,600,724 | 100,000 images; 999,968 questions; 85,000 available scenes |
| `text-ultrachat-200k` | 8 | 1,624,049,723 | 515,311 rows across train/test SFT and generation splits |
| `numeric-iris` | 1 | 3,738 | Both official 150-row tables |
| `audio-vctk` | 1 | 11,747,302,977 | 88,328 FLAC recordings; complete 0.92 corpus, both microphones |
| `preference-ultrafeedback-binarized` | 6 | 649,967,196 | 187,405 rows across all preference, SFT and generation files |
| `audio-libritts-r` | 9 | 88,566,937,189 | 375,035 WAV recordings across all seven splits; documentation and failed-restoration examples |
| `numeric-wine-quality` | 1 | 91,353 | 6,497 red/white wine rows |
| `tools-glaive-v2` | 1 | 271,190,065 | 112,960 tool conversations |
| `text-smol-magpie-ultra` | 7 | 1,469,322,657 | 431,092 rows across all train/test shards of this configuration |
| `text-squad` | 2 | 16,278,203 | 98,169 train/validation questions and aligned answer spans |

Total: 37 complete source files, **123,366,743,825 bytes** (123.4 GB). Row counts sum original files; overlapping publisher configurations are preserved. Exact content pins and validation counts are recorded in each full manifest.

## Select and download

Use the same registered `dataset_acquisition` worker and executor described in [sample qualification](dataset-bank-qualification.md). In Dataset Bank, select **Complete source release**, review the measured byte size and storage allowance, select any required acquisition budget, and choose **Acquire to workspace**. Refresh the byte progress. After the release reaches `ready`, use **Save** for each original file and **Save verification manifest** for its hashes, file validation and publisher notices.

Browser saves stream directly to a selected disk file using the file save picker in supporting browsers, such as Chrome and Edge. Other browsers can use the authenticated artifact download API with a client that streams to disk. Downloads recheck current tenant, project and viewer permissions; no credentials appear in URLs.

For example, using an engineer key, launch all qualified files:

```http
POST /api/v1/dataset-bank/sources/audio-libritts-r/acquisitions/
Authorization: Bearer YOUR_API_KEY
X-Project-ID: YOUR_PROJECT_ID
Content-Type: application/json

{"download_scope":"full","project_policy":{"max_storage_quota_bytes":177133874378}}
```

Preflight uses the same body at `/sources/{source_id}/preflight/`. The default scope is `sample`. A `source_revision` must match the full card's content pin. Full scope rejects a partial `record_limit`; its unit is **original source files**, not rows or archive members. `GET /sources/{source_id}/upstream/?download_scope=full` reports the frozen full pin. New releases require requalification.

Inspect `/api/v1/dataset-bank/acquisitions/{snapshot_id}/`. Ready full responses include `source_files` with artifact IDs, source paths, byte sizes and SHA-256, plus `manifest_artifact_id`. Download each via `GET /api/v1/artifacts/{artifact_id}/download/`. For an HTTP client:

```sh
curl --fail --show-error \
  --header "Authorization: Bearer $MODELANVIL_API_KEY" \
  --header "X-Project-ID: $MODELANVIL_PROJECT_ID" \
  --output train_clean_100.tar.gz \
  http://localhost:8000/api/v1/artifacts/ARTIFACT_ID/download/
```

SQuAD still requires the explicit share-alike checkbox or the literal boolean `project_policy.allow_share_alike: true`. Attribution and retained notices apply to the other datasets. Enabled `bank_acquisition_records` budget policies reserve and settle **verified source-file counts** for full releases; interrupted jobs settle completed files, and resume reserves the remaining files.

## Storage, resume and qualification limits

Full preflight requires at least **twice the release byte size** for final artifact objects and retained resumable parts. The default 100 GiB allowance is insufficient for all LibriTTS-R splits, so its full request needs the larger explicit allowance above. This is per-acquisition admission; operators must provision actual storage and account for other workspace objects. Existing operator-controlled transfer retention and pruning still apply.

Transfers use at most 16 MiB per part and durable verified checkpoints. Resume checks stored parts and cached complete-file digests again, renews an expired session, fetches missing ranges from the pinned publisher endpoints (with the listed OpenSLR mirror as an alternate) and verifies the complete artifact digest. Corrupted source bytes, conflicting cached parts, changed manifests, stale worker leases or cancellation cannot publish a ready release. Each release is ready only after every qualified file and its verification manifest are committed.

Scope follows the named source: CLEVR's main v1.0 archive includes all 100,000 images, available scenes and all question splits; CoGenT is a separate release. Smol-Magpie-Ultra includes all shards of that configuration; the other SmolTalk configurations have separate scope and licensing. LibriTTS-R includes all seven train/dev/test archives, documentation and failed-restoration examples. VCTK preserves both microphones and documented missing-transcript/mic2 exceptions. Iris preserves both official 150-row versions. Original splits and duplicate rows across publisher configurations are retained.

Format qualification reads every Parquet row and validates Arrow buffers and expected field shapes; reads every JSON tool record; checks all numeric CSV rows; reads every ZIP member to verify CRC; and reads every gzip TAR member and the gzip stream to EOF, checking safe paths and media headers. It does not assess perceptual media quality, label correctness, representativeness, cross-source deduplication, or training performance.

## Repeat content validation

With pinned requirements installed and the original complete files already downloaded into `CACHE/SOURCE_ID/BASENAME`:

```sh
python -m scripts.qualify_bank_full_releases \
  --inventory catalog/full-datasets/image-clevr.json \
  --cache /path/to/full-release-cache
```

The command recomputes each chunk and complete-file digest, compares publisher checksums when present, and repeats complete-content validation. It writes only aggregate reports beside the cached files. Repeat for each full manifest. Keep caches, pilot databases and generated reports outside Git; new pins and qualification claims need a reviewed catalog change.

## Qualification and runtime verification

All 37 complete files were downloaded from the pinned publisher endpoints, checked against available publisher checksums, and read through the format validators above. A separate isolated SQLite/filesystem worker pilot acquired every release from that verified local cache, committed its original files and notice receipt, and streamed all 123,366,743,825 bytes through the authenticated, project-scoped artifact API with matching SHA-256. The runtime pilot reused the verified cache rather than fetching another copy of every large archive over HTTPS. Iris and Wine Quality additionally passed authenticated API launch, a claimed worker using the production HTTPS transport, and authenticated full-file export directly from UCI.

Verification passed: 688 backend tests (three existing integration skips), four smoke tests, migration checks, 131 frontend tests, production build and Storybook build. The 13 complete-download tests cover resume, cached and upstream corruption, publisher notices, storage admission, file-count budgets, worker execution, project isolation and all admitted release pins. Separate frontend tests cover browser streaming. Browser streaming uses a mocked save picker in its frontend test; a physical browser save, production PostgreSQL/object storage deployment and training runs were not tested.
