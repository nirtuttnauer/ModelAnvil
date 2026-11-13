# ANVIL-028: first version tag v0.1.0, 13 November 2026

Label: `local`. Ticket: ANVIL-028 (Aftur TASK-105). Nir approved pushing the tag in chat on 13 November 2026: "Yes, push v0.1.0".

## The tag

- `v0.1.0` is an annotated tag (tag object `ddb6d4f7bdb8ef29ea107e8619663aa5a1be5cfe`) on `53e7ff3ecf6094df6e89ab50d085db3072f34a4c`. That commit is `main` after #134, the merge of ANVIL-027.
- It was pushed with `git push origin v0.1.0` only, and `git ls-remote --tags origin` lists `refs/tags/v0.1.0^{}` at `53e7ff3`.
- No GitHub release and no image was published. The tag is not signed.
- The tag message names the release, the gate results and the install page.

## Gates at the tagged commit

[gates/gates.md](gates/gates.md) records the shared gates at `53e7ff3`, from a clean checkout on Nir's Mac:

- `make premerge` exit 0: backend 1455, frontend 249 and PostgreSQL 30 passed, with no skip, xfail or timeout. The MLX and GGUF fixture tests ran.
- `pip-audit` is clean on all 11 requirement groups, with no ignores.
- Stock `gitleaks` 8.28.0 finds 0 findings in the tree. Every history finding is on `reviews/ANVIL-017-gitleaks-history.md`.

## Release manifest records the tagged commit

[release-0.1.0.json](release-0.1.0.json) is the manifest of release `0.1.0`, built from the tagged commit with `scripts/build_selfhost_release.py --output ~/.cache/modelanvil-selfhost/releases/0.1.0`. With `--version` omitted, the builder took the version from `deploy/selfhost/VERSION`. The manifest records `version` `0.1.0`, `source_revision` `53e7ff3ecf6094df6e89ab50d085db3072f34a4c`, the same commit as the tag, and `production_qualified` `false`. [release-build-and-fresh-install.txt](release-build-and-fresh-install.txt) holds the build and check output.

An earlier test build of 0.1.0 had been made from `fe9a94c`, the ANVIL-024 branch, for ANVIL-024 to ANVIL-029. It was kept, not deleted: its directory was renamed to `0.1.0-fe9a94c` and its image tags to `0.1.0-fe9a94c` before this rebuild. The builder refuses to reuse an existing image tag.

## The tagged release installs on a fresh engine

The rebuilt release was then installed with `scripts/install_selfhost.py` on a brand-new `docker:dind` engine with 0 images and 0 volumes, the reset environment Nir chose for the second-machine check. The install loaded the release's own `images.tar` and exited 0 in 24 s, reporting `ready: true`, version `0.1.0` and `production_qualified: false`. `curl --fail --cacert <instance CA> https://localhost:18443/api/v1/health/` returned `{"status": "ok"}`. `stop` and `uninstall` exited 0, and the engine and its volume were removed. The second-machine record for the same release line is ANVIL-026, in `docs/engineering/verification/anvil-026-2026-11-12/`.

## Not done

- No GitHub release, no published image and no package registry entry. Operators build the release from the tag, as `docs/self-host-install.md` describes.
- The tag is not GPG or SSH signed.
- No separate physical Linux arm64 host was used. The fresh engine runs inside the Docker Desktop VM of the Mac that built the release.
