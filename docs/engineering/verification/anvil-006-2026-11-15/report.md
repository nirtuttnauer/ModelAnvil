# ANVIL-006 (TASK-83): identity-rewrite rehearsal on a disposable mirror

Label: `local`. 15 November 2026, `Mac` (Apple M5 Pro, macOS 27.2.1). Nothing was pushed. GitHub refs were not changed. Nir chose this step in chat on 2026-11-15, answering whether to rewrite history or leave it as is: "Dry-run rewrite, no push (Recommended)". The force-push (TASK-85, ANVIL-007) still needs his separate approval.

Private inputs stay outside the repository in a mode-0700 directory on this Mac: the owner mailmap (`info/modelanvil-private.mailmap`, 3 entries, all mapped to `nirtuttnauer <21014429+nirtuttnauer@users.noreply.github.com>`), the denylist derived from it, the commit maps and the raw scan output. This report gives counts only and never repeats a legacy address.

## Inputs

- Two fresh `git clone --mirror https://github.com/nirtuttnauer/ModelAnvil.git` copies, refs identical: 286 refs (135 heads, 8 tags of which 1 annotated, 143 `refs/pull/*`), 493 commits. `main` was `0cbd8307299acdf6f5690d2f6c5936246e7ec04e`. Ref manifest SHA-256 `8ba3c9108d0b939cf1be73f76376a5d752578473761aea1fc620fade336b325c`. One copy stayed untouched for comparison; the ANVIL-005 bundle remains the backup.
- `git-filter-repo` 2.47.0 (PyPI wheel, version `a40bce548d2c`) in a dedicated tool environment. No `--force`.

## Baseline raw scan (untouched mirror)

Every object reachable from every ref (493 commits, 1 tag object, 3175 trees, 4681 blobs), raw, without mailmap:

| Where | Objects or fields with a legacy owner address |
| --- | --- |
| commit `author` | 64 |
| commit `committer` | 37 |
| commit message | 2 (`Co-authored-by:` trailers on commits reachable from `main`) |
| blob | 2 (two versions of `docs/engineering/verification/anvil-002-2026-10-29/gitleaks-detect.txt`, one of them in the current tree) |
| tag `tagger` | 0 |

The blob hits come from gitleaks copying each finding's commit-author email into its JSON report. The current-tree copy is redacted by the commit this report ships with, which leaves 0 tracked files with a legacy address.

## Rehearsal A: identity only (`--mailmap`)

- Raw identity headers: 0 legacy addresses on every ref, tags and `refs/pull/*` included. Classes after: author 376 canonical noreply and 117 Cursor agent (`cursoragent@cursor.com`); committer 302 canonical noreply, 74 GitHub (`noreply@github.com`), 117 Cursor agent; tagger 1 canonical noreply. No other identity appears.
- Messages and blobs: the 2 message and 2 blob hits remain. The zero-hit criterion fails, as the plan predicted: an identity rewrite cannot change content.
- Every one of the 493 mapped commits keeps its original tree ID; 490 commit IDs change, 3 early commits keep theirs. Parent topology matches for all 493. `git fsck --full` exit 0. All 286 refs mapped.

## Rehearsal B: identity, messages and the report file

`--mailmap` plus `--replace-message` (legacy address to the canonical noreply address, so the two trailers keep crediting the owner) and `--replace-text` (legacy address to `[legacy owner address redacted 2026-11-15]`, the same placeholder as the current-tree redaction).

- Raw scan of every object on every ref: 0 objects contain a legacy address (headers, messages, blobs).
- Tree IDs: 265 of 493 commits keep their original tree. 228 differ, and the only differing path in every one of them is `docs/engineering/verification/anvil-002-2026-10-29/gitleaks-detect.txt`. This is a content change outside the ticket's metadata-only rule, so it needs the same separate review the plan reserves for the VCTK line. ANVIL-004's VCTK author email is not part of either rehearsal.
- Parent topology matches for all 493 commits. `git fsck --full` exit 0. 286 of 286 refs mapped; rewritten `main` is `7dccebe6dc1d86ad8624b021ee60aac18e6fddf9`, ref manifest SHA-256 `58f97637ae4398cde68b4ff5c0c5ce546d72adcc93e07cd99c3eaff9c29acbfe`.
- gitleaks 8.28.0, stock config, `detect --log-opts=--all` (every ref, `refs/pull/*` included): 411 findings, 391 unique fingerprints, all 391 on the ANVIL-017 triage list after remapping each listed commit through the commit map (0 listed commits missing from the map). The untouched mirror gives the same 411/391 with 0 off-list. Working tree `dir`: see the rewritten-main gates.
- Signatures: 191 commits carry a `gpgsig` header today (mostly GitHub web-flow merges); after either rehearsal 0 do. GitHub will show the rewritten commits as unverified. The annotated tag `v0.1.0` is unsigned and is rewritten to point at the mapped commit with the canonical tagger.

## Full local suite on rewritten `main`

[`gates/rewritten-main/gates.md`](gates/rewritten-main/gates.md) runs the shared gates in a clean clone of rehearsal B's `main` (`7dccebe`): premerge exit 0 with backend 1455, frontend 249 and PostgreSQL 30, no skips, the same counts as `0cbd830`. gitleaks 8.28.0 stock `dir` finds 0, and the history scan has no finding off the remapped ANVIL-017 list. G-audit fails there only for CVE-2026-126360 in `opentelemetry-api` 1.45.1, which #136 fixed on GitHub after the mirror was taken; a rehearsal repeated from a fresh mirror picks the fix up.

[`gates/gates.md`](gates/gates.md) records the gates at this branch's redaction commit.

## Branches for Nir to decide (ANVIL-006 detail)

135 heads on GitHub: `main`, 113 branches already merged into `main` (18 `claude/`, 64 `codex/`, 31 `cursor/`), and 21 not merged (2 `codex/` from 11 October, 19 `cursor/`; 8 of those have open PRs #113–#121). Proposed default for TASK-85: rewrite `main`, the 8 tags and the 21 unmerged branches; delete the 113 merged branches instead of rewriting them; recreate or close the 8 open PRs, whose heads change. `refs/pull/*` are GitHub-managed and keep old objects until GitHub Support removes them.

## Not done here

No backup was replaced, no ref was pushed, no branch protection changed and no collaborator or GitHub Support message was sent. Before TASK-85 the rehearsal must be repeated from a fresh mirror, because every merge on GitHub changes the inputs.
