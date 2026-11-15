# ANVIL-003 (TASK-80): new commits carry only the noreply identity

Label: `local`. 15 November 2026, `Mac` (Apple M5 Pro). Addresses are reported by class only; legacy owner addresses are never written here.

## Criterion 0: the GitHub setting

On 2026-11-13, asked whether GitHub's email privacy setting is on, Nir answered in chat: "It's on; I'll unblock it". On 2026-11-15, asked whether to move the ticket back to Approved and finish it, he answered: "Yes, unblock and finish (Recommended)".

## Criteria 1 and 2: identities on `main`

The first GitHub merge after the setting change, `b182600` (PR #90), has a noreply author and the GitHub committer. Since then, `git log --format='%ae %ce' b182600..origin/main` at `0cbd830` lists 136 commits:

| Field | Canonical noreply | GitHub (`noreply@github.com`) | Cursor agent (`cursoragent@cursor.com`) | Anything else |
| --- | --- | --- | --- | --- |
| author | 88 | 0 | 48 | 0 |
| committer | 50 | 38 | 48 | 0 |

The tip of `main`, merge `0cbd830` (PR #135), has `%ae` = `21014429+nirtuttnauer@users.noreply.github.com` and `%ce` = `noreply@github.com`. This branch's own commits use the canonical noreply identity for author and committer.

## Gates

On 2026-11-15, the first run at `0cbd830` (main) passed G-local, G-skip and G-secrets but failed G-audit: `pip-audit` reported CVE-2026-126360 in `opentelemetry-api` 1.45.1 from `requirements.specialists.txt`, fixed in 1.45.2. This branch moves the pin to 1.45.2. `gates/gates.md` records every gate at that commit.

## Not covered

GitHub's web-merge identity is an account setting outside the repository. A later change to that setting would not show up until the next web merge; the identity table above is a point-in-time check. Existing history still contains legacy owner addresses; that is ANVIL-006 and ANVIL-007.
