# Contributing to ModelAnvil

Bug reports and pull requests are welcome. For a bug report, include reproduction steps, expected behavior, and your Python/Node versions. Remove credentials, private datasets, and identifying logs before sharing them.

Follow the [local setup](README.md#local-development), then run:

```sh
make check test migration-check smoke
cd web
npm ci
npm test
npm run build
npm run build-storybook
```

Keep changes focused. Add a regression test for substantive behavior changes and update API contracts when request or response fields change. Use Storybook's synthetic fixtures for UI examples.

Preserve tenant/project isolation, permission checks, artifact integrity, cancellation and usage accounting. Distinguish measured execution from demo fixtures and hardware/production qualification. Do not commit local databases, model weights, dataset contents, credentials or generated verification output.

Contributions are licensed under the repository's [MIT license](LICENSE). Dataset and model licenses remain separate from the software license.
