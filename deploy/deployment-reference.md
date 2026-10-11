# ModelAnvil Deployment Reference & Architecture Matrix

**Technical Standard Reference:** TECH-004, TECH-029, TECH-030.

## 1. Deployment Modes Overview

ModelAnvil supports three distinct deployment architectures tailored to organizational security, compliance, and compute topologies:

| Capability / Boundary | Managed SaaS | Self-Hosted Enterprise | Hybrid (SaaS Control Plane + Private Workers) |
| :--- | :--- | :--- | :--- |
| **Control Plane Location** | Cloud Managed | Customer Private VPC / On-Prem | Cloud Managed |
| **Compute / Worker Location**| Cloud Managed | Customer Private VPC / On-Prem | Customer Private Infrastructure / On-Prem |
| **Raw Training Data** | Cloud Artifact Storage | Customer Private Storage | **Stays 100% on Customer Perimeter** |
| **Intermediate Checkpoints** | Cloud Artifact Storage | Customer Private Storage | **Stays 100% on Customer Perimeter** |
| **Control Plane Telemetry** | Cloud Database | Customer Private DB | **Status, Progress, Metrics Only (Metadata)** |
| **Credential Lifetime** | Managed API Keys | Self-Managed Secrets | **Scoped, Revocable Worker Tokens with Leases** |

---

## 2. Hybrid Private Worker Security & Boundary Enforcement (TECH-029)

In the **Hybrid** model, sensitive data sets and proprietary base model weights never leave the customer's secure perimeter.

### 2.1 Scoped Revocable Credentials
- Hybrid workers connect outbound to the control plane using ephemeral credentials (`WorkerCredential`).
- Each token is cryptographically generated, hashed with PBKDF2/SHA256, and scoped to a specific `WorkerPool`.
- Tokens can be instantly revoked administratively via `POST /api/v1/workers/pools/{pool_id}/revoke/` without disrupting other pools.

### 2.2 Metadata-Only Result Egress Boundary
- Administrators configure worker pools with `result_egress = "metadata_only"`.
- When effective:
  1. Workers report job state (`succeeded`, `failed`, `cancelled`), monotonic progress indicators, and training loss metrics.
  2. Workers **strip all raw data samples, generated text, model weights, and sensitive error traces** before making requests to the control plane.
  3. Raw outputs and model checkpoints are saved strictly to customer-managed local storage or internal S3 buckets.

### 2.3 Resilient Worker Reconnect & Lease Fencing
- Workers communicate via outbound polling and heartbeats (`/api/v1/workers/heartbeat/`).
- If an on-prem worker loses network connectivity, the control plane respects a lease grace window (default: 90s).
- Upon network restoration, the worker re-authenticates and resumes heartbeat reporting without causing duplicate job execution or stale state commits.

---

## 3. Metadata Residency & Isolation
- **Tenant Isolation:** Every metadata table enforces tenant partitioning through `tenant_id` foreign keys and Row-Level Security / queryset filtering.
- **Audit Logging:** Every administrative configuration change, worker enrollment, and credential issuance is written to immutable `AuditEvent` records with caller context, IP address, and request ID.
