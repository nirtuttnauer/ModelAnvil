# TASK 44 activation and capability baseline verification

21 October 2026 · Local implementation ready for review

TASK-44 adds local measurement of explicit improvement decisions and reconciles the older capability audit with later execution evidence. The [current support baseline](../../supported-capabilities.md) and [machine-readable index](../../supported-capabilities.json) cover import, training, evaluation, export, serving and recovery with dated evidence, runtime/hardware limits and artifact identities. Missing hashes remain null.

## Delivered behavior

- Evaluation records an explicit immutable accept/reject choice after a real durable trained-candidate/baseline comparison. Server validation checks current access, completed worker execution, exact input pins and complete candidate/baseline case coverage. Recording a choice does not deploy a model.
- Overview exposes the current project's local workflow report. Tenant totals require an unscoped administrator. Team/candidate/evaluation tuples are deduplicated across projects, and identical event/decision retries are idempotent.
- Accepted improvements require an accept choice and higher measured accuracy. A tie, lower training loss, simulation or partial result cannot inflate that count. Rejections remain useful completed decisions.
- Fixed-field local events record session opens and approximate interaction time. They accept no prompts, answers, arbitrary metadata or credentials. Captured project scope survives cleanup and project changes. There is no external analytics transport.
- Reports separate browser-reported interaction time, first-visit-to-decision wall time, worker queue time, execution time and model acquisition. Missing observations stay unknown.

The additive `core.0005_local_activation_measurement` migration creates two tables without rewriting existing resource records. It was applied to the running local installation after a private SQLite backup. The disposable browser fixture used separate database/artifact storage; it was stopped and removed after verification.

## Verification

The [check summary](checks.json) identifies the source revision/digest and exact verification scope.

| Check | Result |
| --- | --- |
| Complete backend regression | 902 tests, passed with 9 skips. |
| Updated activation regressions | 7 tests passed, including an additional cross-project deduplication check after the broad run. |
| Frontend regression | 225 tests passed, including idle/focus timing, uncertain retry identity, private payload allowlisting and captured project scope. |
| TypeScript and Vite build | Passed. |
| Django system and migration-drift checks | Passed; no ungenerated migration changes. |
| Mechanical design detector | No findings on the changed UI targets. |
| Evidence index | Every referenced local report exists and its checksum matches. |
| OpenAPI | Canonical and engineering copies match and describe all three new endpoints. |

The [browser checks](browser-checks.json) used a real loopback API and two actually executed CPU comparisons. A reject choice was saved through the browser and survived reload. The report showed two distinct comparison decisions, two rejections and zero accepted improvements; it did not turn repeated browser events into cycles. The report disclosure worked with the keyboard. Desktop and 390-pixel layouts were inspected; no browser console errors were recorded. Screenshots are alongside this report.

## Baseline and limits

The [fresh automated baseline](baseline.json) creates and migrates a new database, executes two real reference-model training updates, evaluates one held-out case against a distinct baseline and records a rejection. It records exact model artifact pins, execution timings, source digest and observed physical hardware. Reproduce it with:

```sh
.venv/bin/python scripts/measure_activation_baseline.py \
  --output /absolute/path/activation-baseline.json
```

This is a tiny automated CPU workflow. Dependency installation, model download and human onboarding were not observed and remain null. The separate browser run records automation interaction time, not a human onboarding study. No customer activation, retention, useful-model quality, new GPU qualification or production serving claim follows. Representative user measurements belong to TASK-43; evaluation of the exact guided GPU adapters remains TASK-46.

TASK-44 is ready for human review. The next independent engineering roadmap ticket is TASK-48, whose dependency TASK-2 is already completed.
