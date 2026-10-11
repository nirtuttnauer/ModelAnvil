# ModelAnvil job queue recommendation

Architecture decision 001 | 8 October 2026 | Status: Proposed for implementation qualification

We recommend RabbitMQ for initial job dispatch, a transactional relational database (proposed PostgreSQL) for durable job and attempt state, and artifact storage for data and checkpoints. Add Kafka when retained event replay and independent stream consumers become a measured requirement. The recommendation is not an implemented service or a final version selection.

The immediate requirement is that authorized workers take compatible jobs when execution slots become available. Work spans acquisition, CPU preparation, generation, GPU training, and evaluation. Training can last days, some runs require several nodes together, and private hybrid workers must preserve organization boundaries.

| Criterion | RabbitMQ | Kafka |
| --- | --- | --- |
| Competing workers | Manual acknowledgements and bounded prefetch suit dispatch | Share Groups also provide queue-style consumption |
| Backpressure | Consumer credit plus application admission | Fetch controls plus application admission |
| Replay after completion | Acknowledged queue messages are removed; keep durable history elsewhere | Retained topics support rereading and independent consumers |
| Long-running GPU jobs | Use durable claims, application leases, and checkpoints | The same application lifecycle controls are still needed |
| Resource allocation | Requires a scheduler and execution adapter | Requires a scheduler and execution adapter |
| Initial product fit | Recommended for dispatch and heterogeneous worker pools | Prefer when stream retention and multiple consumer pipelines justify it |

Kafka is a valid queue option. Apache Kafka 4.2 made Share Groups production-ready, including record-lock renewal. The argument for RabbitMQ is the current workload and scope, not a claim that Kafka cannot distribute work. If pilot organizations already operate Kafka and require a single broker, qualify a Share Group adapter against the same recovery, capacity, tenancy, and client-support requirements before revisiting this recommendation. [Kafka release announcement](https://kafka.apache.org/blog/2026/01/14/apache-kafka-4.2.0-release-announcement/).

RabbitMQ acknowledgements, publisher confirms, prefetch, and quorum queues provide the needed delivery primitives. Broker acknowledgements do not establish training completion or exactly-once side effects. [Acknowledgements and confirms](https://www.rabbitmq.com/docs/confirms), [consumer prefetch](https://www.rabbitmq.com/docs/consumer-prefetch), [quorum queues](https://www.rabbitmq.com/docs/quorum-queues).

## Proposed execution contract

1. Validate the request, permissions, budget, data/model compatibility, and resource needs. Persist the job and an outbox event in one database transaction.
2. Publish a small persistent dispatch notification to a durable quorum queue with publisher confirms. The outbox safely retries until confirmed; duplicate delivery remains possible.
3. Route work to an eligible pool after applying quotas and fair allocation. An available worker atomically claims the job attempt and reserves a free slot. Saturated or draining workers stop taking work; prefetch must not turn into a backlog of assigned GPU jobs.
4. Acknowledge the notification once the claim is durable. Track execution through application heartbeats, renewable leases, checkpoints, and durable attempt state. Do not leave a days-long training run attached to an unacknowledged broker message.
5. Commit verified immutable artifacts and completion state, then make dependent work eligible. Stable job IDs, conditional claims, and fencing tokens prevent duplicate or stale attempts from committing results.
6. Reconcile abandoned claims. Revoke the previous allocation or confirm it has stopped before restarting chargeable training. If stop cannot be established, keep the job interrupted for operator resolution. Resume from a verified checkpoint when supported.
7. Retry transient failures with bounded backoff and jitter. Record scheduled retries, terminal failures, and quarantined poison notifications. Cancellation records desired state and reports actual execution-backend stop and resource release.

Multi-node training requires the full allocation before launch through a qualified execution adapter, such as Kubernetes or Slurm. The broker must not dispatch independent fragments that deadlock a distributed run. CPU, GPU, acquisition, and evaluation pools can have distinct queues, but routing never substitutes for authorization and quota enforcement.

Hybrid workers may connect outbound to a scoped gateway that handles dispatch claims and heartbeats. They do not need publicly exposed broker endpoints. Data, logs, and checkpoint egress obey the installation's policy. Secrets and large artifacts stay out of messages.

## Qualification and operations

Use a single-node broker only for development without an availability claim. Qualify a three-node production quorum deployment, backup/recovery procedures, credentials, isolation, and offline installation. Pin supported broker and client versions after testing; do not inherit version-specific timeout or priority defaults without review.

Acceptance must exercise duplicate delivery, publisher interruption, broker restart, worker loss before and after claim acknowledgement, lease expiry, stale result rejection, bounded retries, cancellation, draining, tenant fairness, and whole-group distributed allocation. Track queue age, dispatch latency, ready work, active attempts, free worker slots, failed heartbeats, retries, quarantine counts, and starvation by team.

Consequences: job history and replay depend on the application database/outbox, and recovery reconciliation is core infrastructure. RabbitMQ alone does not make jobs durable after dispatch acknowledgement. Kafka is not a required first-release service; add a retained event stream only when its consumers and retention needs are defined.
