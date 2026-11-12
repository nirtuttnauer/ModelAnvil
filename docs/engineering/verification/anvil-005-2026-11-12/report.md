# ANVIL-005 history backup, 12 November 2026

Label: `local`. Machine: Nir's Mac, Apple M5 Pro, 48 GiB, macOS 27.0.1, `git` 2.54.0 (Apple Git-157).

This is the private backup that must exist before any history rewrite (ANVIL-006, ANVIL-007). Nothing was rewritten or pushed. The bundle and the ref manifest carry the old commit metadata, so they are not attached to this report, a ticket, a pull request, or a chat. This report records counts, hashes, and the storage location only.

## Mirror

A fresh `git clone --mirror https://github.com/nirtuttnauer/ModelAnvil.git` into an empty temporary directory under the session scratchpad. No existing checkout was used.

| Ref class | Count |
| --- | --- |
| `refs/heads` | 87 |
| `refs/tags` | 7 |
| `refs/pull` | 88 |
| Total | 182 |

`refs/heads/main` in the mirror: `56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7`.

The ticket text counted 70 branches, 0 tags, and refs/pull/1..70 on 29 October 2026. The repository has grown since then. The counts above are the ones this bundle covers.

## Bundle

```sh
git -C mirror.git bundle create ../modelanvil-pre-rewrite-56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7.bundle --all
git -C mirror.git bundle verify ../modelanvil-pre-rewrite-56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7.bundle
shasum -a 256 modelanvil-pre-rewrite-56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7.bundle
```

`git bundle verify` exited 0 and printed `The bundle records a complete history.` The bundle is 89,014,264 bytes. Its SHA-256, in 8-character groups so a stock `gitleaks` scan does not read it as a key:

```text
0417098f 53e60574 d6e62afb 9f5b9931 f7f3f1fe e84014e7 d4667d9e 80acba02
```

## Restore test

```sh
git clone --mirror modelanvil-pre-rewrite-56b35ccca6ed3d3a2aca0c28fbce1dabaa445be7.bundle restore.git
git -C restore.git fsck --full
git -C mirror.git for-each-ref --format='%(objectname) %(refname)' | sort > mirror-refs.txt
git -C restore.git for-each-ref --format='%(objectname) %(refname)' | sort > restore-refs.txt
diff mirror-refs.txt restore-refs.txt
```

The restore went into a second, separate temporary directory. `git fsck --full` exited 0 with no output. `diff` exited 0: all 182 refs, `refs/pull/*` and tags included, have the same name and object ID in the restore as in the mirror.

## Storage

The bundle, `bundle.sha256`, and `mirror-refs.txt` (object ID and ref name per line, no commit metadata) are stored outside the repository on Nir's Mac at `~/Backups/ModelAnvil/history-2026-11-12/`. The directory is mode `700` and each file is mode `600`. `shasum -a 256 -c bundle.sha256` on the stored copy printed `OK`. The temporary mirror, restore, and bundle copies under the scratchpad were deleted.

Rollback for ANVIL-007 pushes refs back from this bundle.

## Gates

This change adds this report only. The G-local, G-skip, G-audit, and G-secrets records for the branch head are in [gates.md](gates.md). This report has no RAG number.
