# Action and resource authorization matrix

TASK-2 · 11 October 2026 · Implemented changes awaiting developer review

This describes the selected API paths, not platform-wide security certification. API keys resolve a tenant, role and optional project. A project key cannot select another project through headers. Tenant-wide keys intentionally access tenant-owned resources across projects. Project-null resources are tenant-shared. An explicit same-tenant `ProjectGrant` makes a project/resource accessible; the current grant schema does not distinguish read from write access. Do not use a grant as a read-only sharing contract.

`TenantScopedViewSet` requires viewer for reads and engineer for ordinary writes (including deletion). It returns no resources without tenant context. Project-owned querysets and writable relation fields use `get_accessible_queryset`; explicit project fields are limited to the caller's scope and cannot erase ownership for a project-scoped key. Training and alignment now use this base view, replacing their tenant-only querysets and authentication-only permissions. Checkpoint reads derive project access through the parent training run.

| Resource/action | Minimum role | Resource scope / relationship checks | Audit evidence |
| --- | --- | --- | --- |
| Models, tokenizer/model versions, sources/snapshots, evaluation suites/runs, releases/versions | Viewer read; Engineer write/delete | Active tenant; active project, tenant-shared or explicit grant; writable relationships scoped before mutation | Ordinary registry CRUD is not individually audited by this base class |
| Model version qualification | Unavailable | Client registry metadata cannot set qualified; runtime evidence required (TASK-1) | Validation denial |
| Training create/update | Engineer | Base model, tokenizer, dataset and pool relation querysets scoped; project ownership bound; output/job/manifest fields server-owned | No per-action training audit yet |
| Training steps/export/infer/cancel | Engineer | Scoped run lookup returns 404 for inaccessible or absent runs | No per-action training audit yet |
| Training idempotent create | Engineer | Replay cache bound to key principal and active project, not just tenant; changed body returns 409 | Same run response; no duplicate record in sequential replay regression |
| Alignment create/update | Engineer | Policy/reference/reward model fields scoped through base serializer; project binding enforced | No per-action alignment audit yet |
| Release gate evaluation | Engineer | Bounded criteria, scoped evaluation UUID, candidate match before lifecycle mutation | Gate result rows; no separate action audit |
| Endpoint promotion/rollback and policy exceptions | Manager | Scoped endpoint/version/gate; related release access checked | Denied role/reference actions and valid exception operations audited; unqualified promotion denial audited |
| Production release qualification/promotion | Unavailable | Fixture/unknown results, client labels and policy exceptions cannot waive runtime qualification | Failed runtime gate; promotion denial audit |
| Budget policies / runner manifests | Admin write | Tenant-scoped; ordinary engineers denied | Base permission denial; no generic registry CRUD audit |
| Adapter registry | Manager write | Tenant-scoped | Base permission denial |
| Worker/pool administration and worker artifact grants | Admin | Existing tenant, worker/attempt, lease/fence and artifact checks | Privileged issuance/registration denials and successful operations audited in dedicated endpoints |
| Project grants | Manager write | Same-tenant projects/resources; cannot cross tenants | Existing dedicated grant checks; no promise of per-row CRUD audit |

Denials return a generic unresolvable relationship validation error (400), inaccessible resource lookup (404), or insufficient role (403). They must not surface ORM exceptions. API-level tests cover two tenants/two restricted projects, legitimate scoped writes, explicit sharing, related writes and selected custom actions. Training regressions add POST/PUT/PATCH relationship denial, ownership/null override denial, inaccessible run/action lookup, viewer denial and principal-scoped idempotency. Release tests cover role/reference denial and runtime-unqualified promotion; a manager role alone is not serving qualification.

Local test evidence is recorded in [status](status.md). Concurrency, external storage, production identity providers and full operational penetration review are outside this local verification. TASK-4 must establish concurrent idempotent dispatch, durable outbox/accounting and worker execution; TASK-5 must establish changed-resource launch revalidation.
