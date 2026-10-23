# Bounded CPU embedding fine-tuning

ModelAnvil can fine-tune the fixed local Apache-2.0 MiniLM encoder on a committed, project-owned triplet manifest, export independently loadable Safetensors, serve the candidate through the existing authenticated embedding endpoint and build a new native vector index. Training is a **trusted operator command**, separate from the HTTP service and the inference/index worker. This release does not add a browser training form, GPU training, arbitrary embedding architectures, hosted inference or automatic quality-based promotion.

Install the pinned [embedding runtime and model cache](embedding-indexes.md). Apply migrations, including `rag.0009_embedding_candidates_and_protected_exposures`. Upload the manifest through the existing immutable local artifact contract in the selected project. Run this from a separate operator process configured for the same database and artifact store:

```sh
python manage.py train_embedding_candidate \
  --project PROJECT_UUID \
  --manifest-artifact COMMITTED_ARTIFACT_UUID \
  --name 'Private embedding candidate 1' \
  --steps 4 --learning-rate 0.001 --seed 7
```

The command verifies actual input bytes, current access, the fixed model/package hashes and the protected splits before loading training data. It trains a fresh model instance: the serving baseline cache is never modified. The result prints the candidate UUID, a **new embedding space UUID**, export artifact UUID/hash, frozen protocol and measured report. The read-only `/api/v1/embedding-candidates/` collection and detail endpoint expose the same project-scoped protocol/evidence. HTTP POST cannot register a forged training result.

Operator limits: 1 MiB manifest; 3–100 corpus documents; 1–32 training triplets; 2–64 dev/held-out qrels; 1–20 optimizer steps; one CPU process; actual 256-token text bound including special tokens. SGD learning rate is 0.00001–0.01; seed is a nonnegative 31-bit integer. This is bounded single-process work, without a durable training job, quota reservation or resumable optimizer checkpoint. Interrupted training publishes no candidate; minimal inspection receipts remain. Serialize operator invocations for the desired space name. Reusing a published name is refused; a different name deliberately creates another immutable version. The existing index build remains a durable, metered worker job.

## Manifest and leakage protection

See the [complete CC0-authored software fixture](examples/embedding-triplets-reference.json). The exact schema has `schema`, declared `license`, `source_uri`, `documents`, `triplets` and `qrels`. Each document has a stable ID, text, source group and split (`train`, `dev`, `held_out`). A source group belongs to only one split. The parser rejects duplicate JSON keys, nonfinite numbers, duplicate IDs, normalized text/query overlap across splits and overlong input. Declared source groups must represent related source material honestly; these checks cannot infer every semantic near-duplicate or verify a supplied license assertion.

Training triplets identify query, positive document and negative document. Queries and both documents must be in training groups; positives share the query's source group. Negative provenance pins its document, the training-only pool, fixed baseline revision and declared method (`manual_reviewed` or `baseline_mined`). The runtime measures the negative's actual training-only similarity rank. A declared baseline-mined negative must be the highest-ranked eligible nonpositive document; otherwise training fails. Manual review remains a supplied attestation, clearly labeled as not independently verified. Held-out documents/queries never enter gradients or negative mining.

Before any gradients, the operator freezes steps, learning rate, seed, cosine softplus triplet objective, optimizer, clipping, input/corpus/split/negative/qrels digests and code/package/model hashes. There is no early stopping, checkpoint selection or automatic hyperparameter search against held-out results. The same versioned dev and held-out qrels are evaluated with baseline and candidate at cutoff 3. Unlabeled queries report N/A and are excluded from aggregate means; reports record total/judged query counts and per-query rankings. A small software fixture is not customer qualification.

Registered protected evaluation source groups/prompts cannot enter training. Tenant-serialized persistent fingerprint receipts also prevent previously held-out embedding data becoming training and prevent inspected training data being relabeled as clean held-out or formal evaluation under new IDs. Both existing protected-suite registration paths share the training-inspection gate. Raw source text is not stored in these receipts. Project/grant namespaces are respected; unrelated private projects do not share a group-name namespace. Failed or interrupted attempts still count as inspected data; receipts do not certify a successful training run.

## Export, serve and compare

The export contains only the qualified Sentence Transformers model files, updated Safetensors, Apache-2.0 license and source notice. It excludes raw examples and qrels. The stored candidate pins each member and the complete archive hash, input artifact, training protocol and reports. Download the export through the existing authenticated artifact path. An independent process can load it without Django, a ModelAnvil database or registry:

```sh
python scripts/verify_embedding_export.py \
  --archive downloaded-candidate.zip --sha256 EXPORT_SHA256
```

The probe verifies package hash/layout, allowed local modules, 384 dimensions, 256-token context, finite normalized vectors and actual CPU encoding. It disables remote model code and requires local files. With the downloaded model directory, standard `SentenceTransformer(..., device='cpu', local_files_only=True, trust_remote_code=False, token=False)` also loads it directly.

Use the new space UUID with `/embedding-spaces/{space_id}/encode/` or the existing Local embedding index form. Candidate encoding verifies source/export state, hashes and current permissions on each request; changed physical package identity forces byte/member verification before reuse. Overlong text is refused, not truncated. Requests never download model files. The selected candidate's exact weight revision, export hash and protocol digest appear in space/index/query pins. Corpus vectors are keyed by `(chunk, space)`, so the candidate builds separate rows and a new index instead of reusing baseline vectors. Other dimensions are refused by this qualified profile and require a separately supported model plus a fresh index.

After a new runtime deployment, reconnect an embedding worker with its current code fingerprint before building. Query both new native indexes through the existing versioned qrels comparison. The actual PostgreSQL integration test builds both baseline and candidate, verifies four rows per distinct space and compares the same held-out query and qrels digest with explicit cutoff/coverage.

Source or export withdrawal/tombstones refuse further candidate serving, including cached models. Candidate publication retains immutable source/export/lineage provenance. This is not a claim to remove information from previously downloaded packages or trained weights; those copies have their own lifecycle. No customer quality gain is inferred from changing weights or passing an export probe.

Primary references: [Sentence Transformers model/save API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html), [triplet training losses](https://www.sbert.net/docs/package_reference/sentence_transformer/losses.html#tripletloss), [dated verification](verification/task30-embedding-finetuning-2026-10-23/report.md).
