# Classification beta release

This release has two separate products for small teams: local Apple adapter training and a private hosted CPU classifier. The supported workflow is **prepare → train → compare → decide → export**. Export is the handoff; production serving, remote Mac workers, expanded capacity, other GPU vendors and recurring billing remain later work.

## Preserved baseline and reproducibility

The original public and private working trees were captured independently before implementation, including their non-ignored untracked sources. The checkpoints did not change either working tree or index:

| Repository | Baseline ref | Commit |
| --- | --- | --- |
| Public | `codex/beta-baseline-20261028` | `11e37d8876ac724a4ab6336369b9ea65638b026d` |
| Private, separate local repository | `codex/beta-baseline-20261028` | Recorded only in its private release receipt |

The private extension remains excluded from public Git tracking and Docker contexts. Its private build imports public primitives and FigCraft tokens through a named public build context. It supplies its own browser entrypoint, settings, migrations and images. Account recovery, invitations, storage, entitlements and CPU training were integrated, rather than replaced.

`scripts/beta_release_manifest.py` records source SHA-256 values, baseline revisions, locked dependency inputs and local image IDs. It excludes credentials, datasets, weights and environment files. Record private identities only in the private repository:

```sh
.venv/bin/python scripts/beta_release_manifest.py --output output/local-beta-release.json
.venv/bin/python scripts/beta_release_manifest.py --verify output/local-beta-release.json
# Private operator only:
.venv/bin/python scripts/beta_release_manifest.py --private --output private-saas/output/beta-release.json
```

Append `--image NAME=IMAGE` for each already-built release image. Verification detects source changes; it does not establish hardware or deployment qualification. Rebuild images after changing their source and preserve both source and image receipts with the matching evidence. Python requirements and the npm lockfile are the dependency authorities. Storybook is pinned to 10.6.5, Vitest to 4.1.12, and Playwright to 1.64.1.

## Local workflow

Overview chooses the next useful action from saved project state. Overview, Data, Training, Evaluation and Models stay prominent; advanced tools retain their existing URLs. Candidate/base/suite handoffs persist through routes and saved drafts. The starter dataset explains labels, source groups, and distinct training, validation and protected test splits.

The guided SmolLM2-1.7B Apple adapter has an **Evaluate against base** action. Preparation pins the exact validation-selected checkpoint and parent, tokenizer, native template, decoding, protected suite and runtime. A compatible imported protected suite can replace the training dataset's test split. Preparation supplies managed evaluation capacity; users do not configure Infrastructure or Budgets for this journey. Existing admission checks still enforce roles and allowances.

Evaluation loads one model and reuses it across cases, disabling the adapter for its exact base comparison. The existing CPU profile and previously recorded CPU contracts remain supported. Durable cases, fencing, cancellation and recovery retain their existing guarantees. Classification bounds remain **64 cases and 32 output tokens**. Reports lead with accuracy, macro F1, paired coverage, changed cases and regressions, and disclose uncertainty. Technical identities remain available in evidence details.

Accept/reject decisions and reviewed ZIP exports bind to the actual evaluated candidate. Exports include frozen evidence, the decision, checksums, base and tokenizer/template identities, and independent loading instructions. A rejected candidate can still be downloaded for inspection; the decision travels with it.

## Verification

Run the existing checks from preserved source:

```sh
make check migration-check
DATABASE_TEST_NAME=/tmp/modelanvil-beta-tests.sqlite3 .venv/bin/python manage.py test --noinput --exclude-tag=pg
cd web
npm ci
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

The browser runner executes the existing Storybook interaction and accessibility checks in Chromium using the [Vitest addon](https://storybook.js.org/docs/writing-tests/integrations/vitest-addon). Test fixtures remain isolated from a running API. In Vitest only, Storybook's base link target is set to the current iframe so native links do not unload the test runner. Standalone native navigation is checked separately. Native inference applies the pinned tokenizer's [chat template](https://huggingface.co/docs/transformers/chat_templating).

The real Apple pilot is recorded in [native classification evidence](engineering/verification/native-classification-2026-10-28/report.json). It ran three training steps, nine paired cases across three labels, an immutable reject decision, a reviewed ZIP and an independent `python -I` consumer on MPS. The consumer reproduced the evaluated response without ModelAnvil or Django imports. This small synthetic fixture verifies the chain of identities and execution, not representative model quality. Requalify when any recorded runtime source or dependency changes.

The private repository contains its browser checks, deployment harness and operational runbooks. Local qualification uses isolated PostgreSQL, Caddy HTTPS and versioned S3-compatible fixture storage; it removes its temporary services and volumes. The public image is checked for absence of private imports and hosted UI. The user selected local qualification for this release work.

## Launch gates and measurements

Live SMTP, public DNS/HTTPS, AWS S3, off-host restoration, and deployment upgrade/rollback still require the intended hosted environment. Local container evidence is not live-cloud qualification. The operator view distinguishes observed queue/worker/storage state from mail-delivery and backup checks that have not been measured.

Pilot each track with three teams before broadening access. Record completed decisions, independently loaded exports, and second experiments. At least two teams per track must complete a second cycle. Observe five first-time users per track after installation/provisioning; four must reach a recorded decision without developer assistance. Measure hands-on preparation/review time separately from downloads and compute. These are human observation gates and are not replaced by automated tests.

Keep evidence and additive migration history needed to interpret older runs. Preserve each customer's database and artifact versions together before upgrades; retain previous release images for rollback. Separate customer environments initially share release image identities, not databases or artifact namespaces.
