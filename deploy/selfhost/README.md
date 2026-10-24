# ModelAnvil offline self-host package

This package installs an authenticated HTTPS workspace, database, artifact storage and a dedicated local CPU worker. It runs with acquisition disabled and the API/worker/database on an internal Docker network. It does not use development bootstrap accounts or silently download models.

The initial supported profile is a small numerical CPU transformer and its named `full_sft` recipe. The included opt-in example is randomly initialized, not a pretrained language model. It qualifies installation, data flow, real inference and actual parameter updates. Language quality, larger/pretrained models, accelerators and production/customer readiness have separate gates. The package does not claim that every ModelAnvil model/runtime is installed.

Requirements: local Linuxarm64 Docker engine with Composev2, at least4GiB assigned to Docker, Python3.9+ on the controller host, and the complete verified release directory. Windows and other architectures are unqualified. macOS `.app` and Linux `.desktop` launchers are unsigned experimental shortcuts to this same installation; signing/notarization and clean native OS qualification remain separate.

From a verified release directory:

```sh
python3 modelanvil.py install --directory "$HOME/ModelAnvil"
```

The installer prompts for the owner's email, workspace name and a new strong password. Password input is hidden. It creates an empty offline workspace, runs migrations, registers the CPU worker and starts all required services. Keep the directory private; it contains instance secrets. If setup stops before creating the owner account, correct the reported prerequisite/input and run `python3 modelanvil.py initialize --directory /path/to/instance` to resume. Initialization refuses to replace existing accounts. It binds only to loopback by default. Nothing is published to a public service.

The returned HTTPS origin uses a new local CA. `ca.crt` is its public trust anchor. Use that CA explicitly with clients (`curl --cacert /path/to/ca.crt https://localhost:8443/api/v1/ready/`). Browser/system trust setup is an operator step; this installer does not change the system keychain or pretend that a new local certificate is already trusted. The private CA keys remain in the instance's certificate volume.

For reviewed LAN access, explicitly select the local hostname, bind address and unused ports with `--host`, `--bind`, `--http-port` and `--https-port`. Give clients the public CA through a trusted channel and verify its identity. Authentication and HTTPS remain required. Public DNS/ACME and internet hosting are separate from this local-CA package.

```sh
python3 modelanvil.py start --directory "$HOME/ModelAnvil" --open
python3 modelanvil.py status --directory "$HOME/ModelAnvil"
python3 modelanvil.py diagnostics --directory "$HOME/ModelAnvil"
python3 modelanvil.py stop --directory "$HOME/ModelAnvil"
```

Diagnostics report public instance/image/container identity and offline status; they do not export passwords, API keys, model content or database dumps. All runtime image references are immutable local image IDs and use `pull_policy:never`. The installer verifies every package file and image identity. Checksums detect corruption; release signing/distribution trust is a separate gate.

## Explicit local import and recipe

```sh
python3 modelanvil.py example --directory "$HOME/ModelAnvil" --name offline-example
```

This explicitly imports the included finite, checksum-verified reference weights and native byte tokenizer, and prepares four small authored text records and a16-step quota. It returns model IDs and a4-step launch payload without running training or asserting quality. Open Chat for a plain single prompt; use the returned resources in Training with `full_sft`. The existing durable worker performs actual updates and checkpoints. Larger recipes requiring absent optional packages are visibly unavailable.

To import another compatible bounded numerical reference bundle:

```sh
python3 modelanvil.py import-reference --directory "$HOME/ModelAnvil" \
  --file /absolute/reference.json --name my-reference --license MIT
```

The reference format is at most2MiB and contains exact `config.json`, `tokenizer_config.json`, `model.safetensors.b64` and `weights_manifest.json` entries. Configuration dimensions, finite tensors, shapes, complete tensor names, native tokenizer and the Safetensors hash are checked before registration. This is a native numerical reference format, not arbitrary Python/model code or a generic HuggingFace importer. Local dataset upload, preparation, inference and this recipe require no network acquisition after installation.

## Backup, restore, upgrade and retention

Finish or cancel active jobs before backing up. The controller stops application writes and workers, requires a quiescent durable job queue, captures PostgreSQL and artifacts together, hashes the paired files and restarts the original instance. Backups include private identity and instance secrets and are written with private permissions. Keep an off-host recovery copy under the operator's retention policy.

```sh
python3 modelanvil.py backup --directory "$HOME/ModelAnvil" --output /private/new-backup
python3 modelanvil.py restore --directory /private/new-restored-instance \
  --backup /private/new-backup --release /path/to/matching-release \
  --http-port 18080 --https-port 18443
```

Restore requires a new directory and creates a distinct Docker project and volumes. It verifies the backup before loading it, rejects unsafe artifact archive paths/links, preserves accounts, artifacts, quotas and model lineage, runs migrations and starts the restored services. It never overwrites a running instance. The restored endpoint has its own CA; explicitly verify/trust its public anchor.

```sh
python3 modelanvil.py upgrade --directory "$HOME/ModelAnvil" \
  --release /path/to/new-verified-release --backup /private/new-upgrade-backup
```

Upgrade verifies and stages the new release, retains the previous images/package, creates the paired backup while writes are stopped, then migrates and restarts. Keep the same instance directory and Docker project so user data stays attached. A failed schema upgrade requires diagnosis or an isolated restore using the matching old release; code rollback does not reverse database migrations automatically. Qualification of future schema changes remains a release-specific gate.

```sh
python3 modelanvil.py uninstall --directory "$HOME/ModelAnvil"
```

Uninstall removes containers/networks and retains all named data volumes, the private instance directory, prior releases and backups. `start` reconnects the retained installation. This command never deletes user data; permanent deletion requires a separate explicit operator procedure.

## Build an offline release

From a clean committed source checkout with the normal development Python dependencies:

```sh
python3 scripts/build_selfhost_release.py --output /private/new-release
```

The builder uses pinned Python/Node/Caddy/PostgreSQL image digests, the complete Linuxarm64 Python lock and the frontend package lock. It preserves source revision and exact built image IDs, saves all runtime images into the package, verifies installed Python dependencies and hashes every shipped file. Build-time acquisition is explicit; installation/runtime require no pulls or dependency downloads. Existing release versions/tags are never rebuilt. Keep generated images, private instances, backups and credentials outside the repository.
