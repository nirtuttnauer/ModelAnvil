# Commit identity and proposed history rewrite

TASK-75, 23 October 2026. Nir selected **prepare a history-rewrite plan**. This document is that plan; execution, force-pushing, changing branch protection and contacting collaborators remain pending approval. Ordinary implementation PRs may continue merging into main meanwhile. Schedule the rewrite after those PRs land so the plan uses fresh ref IDs.

## Future commits

This workstation's shared ModelAnvil Git configuration now uses:

```sh
git config --local user.name nirtuttnauer
git config --local user.email 21014429+nirtuttnauer@users.noreply.github.com
git config --local user.useConfigOnly true
```

These local settings apply to this clone and its linked worktrees, not other clones or GitHub's web merge identity. Use the same settings in every contributing clone. Verify the effective author and committer with `git var GIT_AUTHOR_IDENT` and `git var GIT_COMMITTER_IDENT` before committing; environment variables or command flags can override configuration. Merge locally with this identity, verify the resulting commit and push a normal fast-forward to main. If merging through GitHub's UI/API, first verify the account's commit email privacy setting; the local configuration cannot control it.

The tracked `.mailmap` declares the canonical identity. A private owner-alias map was generated from observed raw author/committer metadata, stored with mode 0600 under the shared Git directory at `info/modelanvil-private.mailmap`, and configured through local `mailmap.file`. All three observed legacy owner addresses resolve to the canonical identity in `git check-mailmap`. Other clones must create their own private mappings if they want this display normalization. Old addresses are deliberately absent from the tracked mailmap and this document.

Mailmap changes display identity only. Raw commit objects still contain the original metadata; neither the current configuration nor `.mailmap` removes historical addresses. The private alias map and backups contain those addresses and must stay private.

## Proposed rewrite scope

Rewrite only the three verified legacy owner author/committer identities to `nirtuttnauer <21014429+nirtuttnauer@users.noreply.github.com>` across approved published branches and tags. Preserve other contributors, GitHub's committer identity, commit dates, messages and every tracked file byte. Audit author/committer metadata, annotated-tag taggers, commit/tag messages and historical file blobs separately. An email found in a message or blob needs an explicitly reviewed replacement scope: identity rewriting alone cannot promise zero matches across repository contents.

Commit IDs and descendant IDs change. Commit/tag signatures will not survive unchanged; decide which release tags to recreate and sign. CI/release pins, Aftur artifacts, evidence links and deployed build references need a private old-to-new ID map. Historical reports should retain original observations, with an explicit mapping supplement rather than silently relabeling their evidence. GitHub PR refs, cached commit views, forks and existing clones can retain old objects after a branch rewrite; zero findings in a fresh clone does not establish deletion from those locations.

## Execution procedure after approval

1. Agree a short push freeze with every collaborator and automation owner. Inventory all remote heads/tags, open PRs, forks and local worktrees. Save dirty changes, untracked source/evidence and local-only commits privately; include ignored databases and run/artifact output in a separate backup when needed. Do not reset or clean any existing checkout. Record the exact approved refs and their original object IDs immediately before execution.
2. Create a **private untouched backup mirror from GitHub first**, in a new restricted directory outside this checkout: `git clone --mirror https://github.com/nirtuttnauer/ModelAnvil.git /private/approved-backup/ModelAnvil.git`. Export a ref manifest and a bundle (`git -C /private/approved-backup/ModelAnvil.git bundle create /private/approved-backup/ModelAnvil.bundle --all`); run `git fsck --full` and `git bundle verify`, then test restoring the bundle to another disposable repository. Hash the bundle and ref manifest. Back up local-only refs separately; a remote mirror does not capture them. Stop if any backup or restore verification fails.
3. Make a second fresh mirror for rehearsal, keeping the backup untouched. Use a reviewed pinned `git-filter-repo` release and a private mailmap containing only the approved three owner aliases. Rehearse `git filter-repo --mailmap /private/approved-backup/owner-identities.mailmap` in that disposable mirror. Never run it against the shared working clone or use `--force` to bypass fresh-clone checks. Retain its commit/ref maps privately. Inspect annotated tags; if their tagger identities remain, use an explicit reviewed tag callback and repeat the rehearsal from a fresh copy.
4. Verify **raw**, non-mailmapped author/committer/tagger fields in every rewritten ref against the private denylist: zero legacy-owner hits. Separately scan commit/tag messages and every reachable historical blob. Report counts without printing the addresses. Any remaining message/blob hits stop publication until their removal scope is agreed. Compare each original commit's tree ID with the mapped commit's tree ID: all must match for a metadata-only rewrite. Check parent topology, commit counts, ref coverage, intended identities and preserved third-party identities. Run `git fsck --full`, backend/frontend tests, builds and CI on rewritten main in a clean checkout. Recreate/re-sign approved tags and check release references.
5. Show the exact before/after ref manifest, backup checksums, scan counts, tree/topology checks and test results to Nir. Obtain explicit approval to publish those rewritten refs. Re-read remote heads/tags and abort if any has moved since the freeze. With temporary protection changes approved separately, publish explicit branch/tag refspecs using `--force-with-lease=REF:OLD_ID` per ref (and an atomic push where supported). **Do not use `push --mirror`**: it may delete unrelated refs or try to update GitHub-managed PR refs. Restore branch protections immediately and retain their previous settings.
6. Fresh-clone from GitHub; repeat raw metadata/content scans, ref/tree checks and CI. Contact GitHub Support about cached/PR references if private-data removal is required; follow GitHub's eligibility guidance. Coordinate fork owners separately. This cannot revoke bytes already copied elsewhere.
7. Tell every collaborator and automation owner the rewrite has completed, provide the private ID map only where needed, and require a fresh clone or a reviewed transplant of unpublished patches. Never merge/push old branches back into rewritten history. Recreate open PRs against rewritten main and update CI/deployment pins. Record notification delivery before closing TASK-75; no notifications have been sent by this planning change.

## Rollback

Keep the push freeze in place if post-push checks fail. Stop new merges. Confirm that no new commits arrived, then restore each approved head/tag from the untouched mirror with explicit leases against the observed rewritten IDs. If a ref moved, reconcile that work before restoring it. Restore protection settings, re-clone and rerun integrity checks/CI. Tell affected collaborators that the rewrite was rolled back. Restoring the original refs restores the original email exposure, so rollback is a recovery option rather than a privacy success.

No mirror rewrite, ref replacement, force-push, branch-protection change or collaborator message has been executed. TASK-75 remains open for the publication decision and its eventual zero-hit/notification evidence.

References: [Git mailmap syntax](https://git-scm.com/docs/gitmailmap), [git-filter-repo documentation](https://github.com/newren/git-filter-repo/blob/main/Documentation/git-filter-repo.txt), and [GitHub history-removal guidance and side effects](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
