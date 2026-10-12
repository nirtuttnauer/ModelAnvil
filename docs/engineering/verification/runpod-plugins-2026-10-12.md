# Runpod and custom plugin verification

12 October 2026. Branch `codex/runpod-custom-plugins`, based on `origin/main` at `a958f30`.

## Passing checks

- Fresh Python 3.12 environment with `requirements.txt`: full backend suite, **741 tests, 22 skips**. Optional training/inference packages are absent in this CI dependency set.
- PostgreSQL 16 isolated container: **19 compute tests**, including concurrent replay creating one allocation and one provider resource, budget admission, tenant/role/project boundaries, uncertain creation recovery, identity checks, verified release, expiry cleanup, cancellation, and actual custom task result publication.
- Worker, SDK and API regressions: **109 tests, one skip** in the development environment before the final additional compute cases.
- Frontend: **138 tests**, production TypeScript/Vite build, and Storybook build.
- Storybook browser interactions: provision/release, custom task submission, replay of the same request UUID after an uncertain response, and disabled rental controls for viewers. These use synthetic HTTP handlers and never contact Runpod.
- Responsive checks: 375×812 light layout and 812×375 dark layout, reduced motion, no page-level horizontal overflow. The allocation table scrolls within its container.
- Django checks, migration consistency, clean migration/`bootstrap_dev`, smoke checks and diff whitespace validation.

## Existing optional runtime failures

The development environment with optional Torch/Transformers installed produced nine model-workspace inference failures involving a closed SQLite connection. The same one failure and eight errors reproduced in `modelanvil.api.test_model_workspace` on an untouched `origin/main` archive. The Runpod change does not alter that runtime.

The CI dependency set also exposed one pre-existing unguarded Torch import in `RealLoRACheckpointTests.test_deterministic_update_policy_restores_on_failure`. It reproduced on untouched main. The PR adds the neighboring tests' optional-dependency skip pattern, retaining execution when Torch is installed.

## Qualification boundary

No billable GPU was rented and no live Runpod account was used. Vendor capacity, credentials, GPU training performance, large artifact transfer, output artifact uploads, persistent volume behavior and invoice reconciliation remain unqualified. The implemented allocation budget measures elapsed allocation seconds; it does not establish a dollar-cost ceiling. Automatic expiry release requires a running, monitored compute reconciler.
