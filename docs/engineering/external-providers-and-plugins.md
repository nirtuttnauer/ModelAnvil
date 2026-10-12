# External API providers and custom plugins

12 October 2026 | Proposed integration map for ModelAnvil

The [Runpod and custom plugin guide](runpod-and-custom-plugins.md) describes the implemented control API and trusted task execution. The [provider TODO](provider-integration-todo.md) tracks the remaining integrations and qualification work.

ModelAnvil can connect to rented GPU capacity, managed GPU jobs, hosted model endpoints, and external artifact stores. Start with a customer-owned provider account, one Runpod compute integration, one hosted inference integration, and a custom plugin contract. Add more providers after the first integration proves worker bootstrap, artifact transfer, cancellation, cleanup, and cost reconciliation.

Provider capabilities below come from official documentation. Integration priorities and contracts are proposed engineering choices. None of these listings establishes a working or qualified ModelAnvil integration. Prices, regional capacity, quotas, and supported models must be checked for the customer's account when selecting a workload.

## Integration categories

| Category | What ModelAnvil controls | Example integrations |
| --- | --- | --- |
| Rented compute | Provision capacity, bootstrap a worker, run a pinned ModelAnvil executor, release capacity | Runpod Pods, Vast.ai instances, Lambda VMs, cloud GPU VMs |
| Managed GPU execution | Submit code or a supported training recipe, track an external job, collect outputs | Modal functions, Together fine-tuning, Fireworks training |
| Hosted inference | Invoke a model or manage a deployment; no worker registration needed for request-only access | Hugging Face endpoints, Baseten, Replicate, Together, Fireworks |
| Artifact and model access | Stage datasets and checkpoints, verify content, resolve immutable model revisions | Amazon S3, Cloudflare R2, Hugging Face Hub |
| Customer infrastructure | Register existing workers or submit jobs to customer clusters | Existing outbound worker, proposed Kubernetes and Slurm plugins |

A provider can occupy several categories. Runpod Pods and Runpod Serverless need distinct lifecycle handling; a hosted inference endpoint does not imply support for arbitrary training.

## GPU rental providers

The final column describes the proposed ModelAnvil fit and the main implementation concern, rather than a vendor ranking.

| Provider | Documented programmable surface | Proposed fit and main concern |
| --- | --- | --- |
| [Runpod](https://docs.runpod.io/api-reference-v2/overview) | REST v2 for Pods, Serverless endpoints, clusters, GPU catalog, volumes, logs, and billing | First rental integration: container workers on Pods. Treat Serverless as a separate plugin path. Persist resource IDs and verify deletion after each owned allocation. |
| [Vast.ai](https://docs.vast.ai/api-reference/hello-world) | REST API, SDK, and CLI for offer search, instance rental, state, connection, and destruction | Next rental integration: offer selection and interruptible experiments. Match memory, host and network requirements; handle offline hosts and disk charges after compute exits. |
| [Lambda](https://docs.lambda.ai/api/cloud) | Cloud API for instance types, specifications, prices, regional availability, and instance lifecycle | Dedicated GPU VM alternative. Separate VM readiness from a healthy ModelAnvil worker; bootstrap and capacity failures need reconciliation. |
| [Paperspace](https://docs.digitalocean.com/reference/paperspace/) | Current REST API and CLI for machines and other resources; [machine availability API](https://docs.digitalocean.com/reference/paperspace/api-reference/machine-types/) | Optional VM alternative. Use the current API; old Core and Gradient endpoints are deprecated. Persistent machine storage needs an explicit retention policy. |
| [CoreWeave](https://docs.coreweave.com/products/cks) | Managed Kubernetes clusters, node pools, Kubernetes API access, and GPU workload scheduling | Larger cluster integration through Kubernetes. Requires cluster access, node allocation, scheduling, and distributed workload qualification. |
| [Nebius](https://docs.nebius.com/cli/reference/compute/instance) | Current Compute instance lifecycle tooling, with REST, gRPC, and SDK surfaces; [GPU VM quickstart](https://docs.nebius.com/compute/quickstart) | GPU VM and cluster candidate. Pin the current API contract; older `compute v1alpha1` command references are deprecated. |
| [Crusoe](https://docs.crusoecloud.com/api/v1alpha5/) | Project-scoped VM API; [GPU VM specifications](https://docs.crusoecloud.com/compute/virtual-machines/overview/) | Cluster and GPU VM candidate. Match topology explicitly and stage checkpoints outside ephemeral local disks. |
| [Scaleway](https://www.scaleway.com/en/developers/api/instance) | Instance REST API, GPU instance types, server actions, images, and volumes | Regional GPU compute alternative. Availability and placement must be checked per zone; validate storage behavior separately. |
| [AWS EC2](https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html) | GPU instance families and [EC2 launch API through Boto3](https://docs.aws.amazon.com/boto3/latest/reference/services/ec2/client/run_instances.html) | Customer AWS account integration. IAM, quotas, images, networking, disks, and termination make this a larger adapter than a GPU marketplace integration. |
| [Google Compute Engine](https://docs.cloud.google.com/compute/docs/gpus) | GPU machine types and [instances REST API](https://docs.cloud.google.com/compute/docs/reference/rest/v1/instances/insert) | Customer Google Cloud account integration. Region and accelerator compatibility, service accounts, quotas, and asynchronous operations need explicit handling. |
| [Azure](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nc-family) | GPU VM families and [Compute REST API](https://learn.microsoft.com/en-us/rest/api/compute/virtual-machines) | Customer Azure subscription integration. Track resource groups and dependent resources; deallocation and deletion have different retention consequences. |

**Runpod migration requirement:** its [REST v1 documentation](https://docs.runpod.io/api-reference/overview) states that v1 will retire on November 15, 2026. New integrations should use REST v2 at `https://api.runpod.io/v2` and pin its OpenAPI contract.

## Managed execution and model services

| Provider | Documented service and API | Proposed ModelAnvil plugin |
| --- | --- | --- |
| [Modal](https://modal.com/docs/guide/gpu) | Python-defined GPU functions with configurable hardware; [HTTP functions](https://modal.com/docs/guide/webhooks) expose application endpoints | Managed job execution for evaluation, embeddings, and selected training workloads. Package the executor around Modal's runtime and qualify its timeout, cancellation, and output behavior. |
| [Together AI](https://docs.together.ai/docs/fine-tuning/overview) | Managed LoRA and full fine-tuning, SFT and preference training, job monitoring, dedicated serving, and downloadable results | Training plugin with a declared model and method matrix. Add inference as a separate capability; dataset formats and exported weight behavior need qualification. |
| [Fireworks AI](https://docs.fireworks.ai/fine-tuning/finetuning-intro) | Managed training and a programmable Training API, plus hosted inference and deployments | Separate managed training, programmable training, and inference paths. Its documentation distinguishes their supported methods; do not collapse them into one training flag. |
| [Hugging Face Inference Endpoints](https://huggingface.co/docs/inference-endpoints/api_reference) | Endpoint management through API/OpenAPI and the Hub Python client, plus a model catalog API | Deployment lifecycle and inference plugin for selected model revisions. Keep model provenance, deployment identity, and inference usage linked. |
| [Baseten](https://docs.baseten.co/reference/inference-api/overview) | Model and Chain inference endpoints with deployment/environment routing and asynchronous inference | Serving and prediction plugin. Qualify request schemas, streaming or asynchronous completion as applicable, and deployment operations separately. |
| [Replicate](https://replicate.com/docs/reference/http) | HTTP API for predictions, deployments, model versions, and training jobs | Prediction and supported-model training plugins. Pin model versions and validate output formats; an available training endpoint does not establish arbitrary trainer support. |

A shared inference client can cover an explicitly tested common request format. Keep provider-specific model discovery, embeddings, structured outputs, streaming, errors, and billing behind declared capabilities. One provider's compatibility claim should not enable every feature in ModelAnvil.

## Storage and model access

| Integration | Purpose | Contract to qualify |
| --- | --- | --- |
| [Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html) | Durable datasets, checkpoints, candidate bundles, and evaluation artifacts | Multipart transfer, checksums, version IDs, scoped credentials, retention, and recovery against a managed service |
| [Cloudflare R2](https://developers.cloudflare.com/r2/api/s3/api/) | Alternative object storage through an S3-compatible API | Its documented compatibility differences, including checksum behavior; qualify the actual operations ModelAnvil uses |
| [Hugging Face Hub](https://huggingface.co/docs/huggingface_hub/guides/overview) | Base models, tokenizers, dataset repositories, and optional candidate publication | Immutable revisions, file hashes, gated access, licenses, private repository credentials, and explicit publication authorization |

GPU disks, provider network volumes, and artifact stores are separate resources. Track their owners and retention independently so releasing a GPU cannot silently delete the only checkpoint or leave an unintended recurring charge.

## Existing ModelAnvil extension foundations

- [Adapter manifest schema](schemas/adapter-manifest.schema.json) defines image digests, versions, task capabilities, schemas, resources, network hosts, artifact permissions, secrets, dependencies, and recovery declarations.
- [Manifest SDK](../../modelanvil/sdk/manifest.py) builds and validates manifests. Its default image digest is generated from the adapter ID; a deployable plugin must provide a real image digest with `with_image()`.
- [Adapter and runner registry](../../modelanvil/runners/models.py) stores tenant-scoped revisions and compatibility metadata. Registration and `enabled` do not establish execution support or qualification.
- [Custom format SDK](../../modelanvil/sdk/custom_format.py) provides record mapping and a sample adapter foundation.
- [Outbound worker](../../modelanvil/worker_agent.py) provides claims, heartbeats, cancellation checks, and fenced results using a trusted executor installed by the operator. It does not install arbitrary plugins from job payloads.
- [Worker artifact input contract](worker-artifact-client.md) currently covers bounded, attempt-scoped input downloads. Large remote inputs, managed storage grants, and worker output transfer need their own qualified path.

The existing capability enum covers domain tasks such as `train`, `predict`, `embed`, `evaluate`, and `serve`. It does **not** include provisioning compute, managing storage, or a plugin installation lifecycle. Add a versioned provider contract for these capabilities; do not put undeclared fields into the current strict schema or label GPU provisioning as training.

## Proposed custom plugin contracts

Support operator-installed, versioned packages or pinned containers first. Each plugin declares its configuration schema, capabilities, supported input/output formats, resource requirements, secret references, and permitted network destinations. An installation is tenant-authorized and qualified for a particular runtime and provider combination.

| Plugin family | Required operations | Examples |
| --- | --- | --- |
| Compute provider | Validate connection, discover compatible offers, quote or mark price unknown, create, inspect, release, reconcile | Runpod, Vast.ai, private GPU provisioning service |
| External job executor | Submit, inspect, cancel, retrieve result and artifact references | Modal, managed training API, Kubernetes Job, Slurm job |
| Inference provider | Invoke with declared schema, report usage; optional streaming and embeddings | Hosted model service or private inference endpoint |
| Serving provider | Deploy, inspect readiness, scale if supported, remove deployment | Dedicated model deployment service |
| Artifact store | Stage, read, write, verify, finalize, apply explicit retention | S3, R2, customer storage gateway |
| Data and model adapter | Resolve source revisions, acquire or convert content, validate canonical outputs | Proprietary datasets, internal model registries |
| Domain task adapter | Execute declared transform, annotation, training, evaluation, retrieval, or export capability | Custom trainer, judge, embedding model, export format |

Optional operations must be discoverable and refused when unsupported. Adopt existing tenant, job, attempt, fence, artifact, and budget identities rather than introducing a parallel workflow system.

For customer plugins, extend the manifest with an explicit contract revision and qualification reference. Compute offers should expose provider/account, region, accelerator and count, memory per device, CPU/RAM, topology, storage, interruption policy, price units/currency, quote timestamp/expiry, and availability. Preserve unknown fields as unknown; a GPU name alone does not establish fitness for a recipe.

Run executable plugins in a separate worker or provider-controller process. Manifest network and secret declarations require enforcement; JSON validation alone does not constrain trusted Python code. Keep provider provisioning credentials in the controller and give workers only scoped execution and artifact credentials.

## Allocation and cleanup lifecycle

1. Validate the recipe, compatible hardware, data location policy, credentials, quote, and budget before allocation. Mark account quota failures separately from lack of capacity.
2. Persist an allocation intent with a stable request ID before calling the provider. On a timeout, reconcile by provider ID or ownership label before retrying creation.
3. Provision from a pinned image, securely bootstrap the worker, and wait for both provider readiness and worker health. Reclaim allocations whose workers never arrive.
4. Stage verified inputs, execute the fenced attempt, and publish verified outputs. Keep provider allocation state separate from ModelAnvil attempt state.
5. On cancellation or lease loss, stop execution and verify provider state. A fenced result prevents a stale commit; it does not stop GPU billing.
6. Release owned compute after its workload ends and apply explicit volume retention. Keep pre-existing customer resources under their configured lifecycle policy.
7. Reconcile estimated usage with observed runtime and provider billing where available. An independent cleanup process must recover resources left behind by a crashed controller.

Track provisioning, bootstrapping, ready, active, release requested, released, failed, and uncertain allocation states. Provider creation time, job completion, and confirmed billable resource release are different events.

## Cost comparison

Compare total workload cost: allocated GPU time, boot and idle time, CPU/RAM, persistent and temporary storage, data transfer, endpoint warm capacity, and provider-specific minimum billing. Record currency, pricing unit, region, timestamp, source, and uncertainty for each estimate. Managed training may use tokens or job charges; inference may use tokens, requests, or execution time.

Rank offers by recipe compatibility and measured workload cost after qualification. List price per GPU hour is insufficient for comparing different accelerators or providers. Budget enforcement must include a maximum allocation lifetime and verified cleanup; a reservation in ModelAnvil cannot independently cap the customer's provider bill.

## Proposed delivery order

| Phase | Scope | Evidence required to advance |
| --- | --- | --- |
| 1 | Register an existing remote worker; qualify managed artifact transfer and output publication | A real bounded GPU job with verified inputs, independently loadable output, cancellation, credential isolation, and recovery |
| 2 | Runpod Pods using a customer account; compute plugin contract and cleanup controller | Full create/bootstrap/execute/release lifecycle, ambiguous-create recovery, orphan cleanup, and bill reconciliation |
| 3 | One hosted inference integration plus an operator-installed custom task plugin | Declared schemas and permissions, tenant isolation, pinned revisions, bounded usage, and actionable unsupported-feature errors |
| 4 | Vast.ai and Lambda; one managed training or Modal execution path | Second-provider conformance, capacity failure handling, verified outputs, and provider-specific cancellation behavior |
| 5 | Customer Kubernetes/Slurm and selected enterprise cloud providers | Multi-node topology, networking, checkpoint recovery, storage locality, and the customer's operational controls |

Paperspace, Scaleway, Nebius, and Crusoe remain alternatives to select from actual demand. AWS, Google Cloud, Azure, and CoreWeave should follow a customer account or cluster requirement. Avoid implementing every provider before measuring the first complete workload lifecycle.

The map changes no release requirements. Provider selection, contract implementation, and exact hardware/runtime qualification remain separate decisions within the existing [technical requirements](technical-requirements.md) and [implementation plan](implementation-plan.md).
