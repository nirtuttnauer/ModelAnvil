# Provider integration TODO

12 October 2026. Runpod Pods and operator-installed custom plugins are the first implementation. Other providers remain explicit backlog items until implemented and qualified.

## This pull request

- [x] Add Runpod REST v2 GPU discovery and authenticated pod lifecycle.
- [x] Persist tenant-scoped allocation intents and prevent duplicate creates.
- [x] Reconcile uncertain creates and releases; add expiry cleanup.
- [x] Bootstrap scoped outbound workers without exposing provider credentials.
- [x] Add operator-configured custom compute and task plugins with schema validation.
- [x] Expose allocation and plugin controls in the API and compute page.
- [x] Test isolation, errors, idempotency, cancellation, and plugin execution.
- [x] Document setup, contracts, and qualification limits.
- [x] Run required checks; see [verification](verification/runpod-plugins-2026-10-12.md).
- [ ] Open a PR against main.

## Compute provider backlog

- [ ] Runpod Serverless: endpoint deployment, jobs, cancellation, autoscaling, usage.
- [ ] Runpod clusters and persistent/network volumes: topology, retention, transfer qualification.
- [ ] Vast.ai: offer filters, rent/inspect/destroy, interruption and host failure recovery.
- [ ] Lambda: catalog, regional availability, VM bootstrap, termination, usage.
- [ ] Paperspace: current API, machine availability, lifecycle, persistent disk policy.
- [ ] CoreWeave: Kubernetes access, node pools, GPU scheduling and cluster recovery.
- [ ] Nebius: current compute API, VM and GPU cluster lifecycle, identity and storage.
- [ ] Crusoe: project VM lifecycle, GPU topology, ephemeral disk staging, usage.
- [ ] Scaleway: zonal GPU catalog, instance lifecycle, images, volumes and retention.
- [ ] AWS EC2: customer IAM, GPU catalog/quotas, networking, bootstrap, dependent resource cleanup.
- [ ] Google Compute Engine: service accounts, GPU compatibility/quotas, asynchronous VM lifecycle.
- [ ] Azure: subscription identity, GPU quotas, VM lifecycle, deallocation versus deletion.

## Managed execution and inference backlog

- [ ] Modal: pinned functions, submit/inspect/cancel, verified outputs, usage.
- [ ] Together AI: fine-tuning method/model matrix, dataset upload, job lifecycle, export and inference.
- [ ] Fireworks AI: managed training, programmable Training API, inference and deployments.
- [ ] Hugging Face Inference Endpoints: pinned models, deployment lifecycle, inference and usage.
- [ ] Baseten: model/Chain inference, deployment routing, asynchronous completion.
- [ ] Replicate: pinned predictions/training, deployments, cancellation and verified outputs.

## Storage and customer extension backlog

- [ ] Amazon S3: managed multipart transfer, checksums, versions, scoped credentials and retention.
- [ ] Cloudflare R2: qualify supported S3 operations and checksum differences.
- [ ] Hugging Face Hub: immutable model/tokenizer/dataset revisions, private/gated credentials and publication.
- [ ] Customer Kubernetes: namespace identity, Job lifecycle, GPU scheduling and artifact staging.
- [ ] Customer Slurm: job submission/status/cancellation, topology and checkpoint recovery.
- [ ] Custom serving and inference plugins: declared request schemas, streaming, embeddings and usage.
- [ ] Custom storage and dataset plugins: canonical inputs/outputs, integrity and residency.

## Qualification required per provider

- [ ] Real bounded workload on the exact image/runtime and hardware combination.
- [ ] Verified input transfer, independently usable outputs, credential and tenant isolation.
- [ ] Capacity failures, ambiguous create recovery, controller restart and confirmed release.
- [ ] Cancellation, lease loss, expiry cleanup, persistent storage policy and cost reconciliation.
