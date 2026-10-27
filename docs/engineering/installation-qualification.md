# Installation qualification

28 October 2026. This records the single-host gates that are in the tree and the ones that are still open. `production_qualified: false`.

In the tree:

- The production Compose stack serves HTTPS with Gunicorn, PostgreSQL, and Caddy, and refuses unapplied migrations. Signup is disabled. See `deploy/production/README.md`.
- Password reset returns a code only when `MODELANVIL_SEND_RESET_EMAIL` is off and debug is on. With that setting on and `EMAIL_HOST` set, the code is emailed and the response does not contain it.
- `scripts/replay_evaluation_gate.py` reads a decision report and exits non-zero when the candidate regresses past `--max-regression` or the report is not decisive.
- `scripts/rehearse_restore_copy.py` copies a directory, checks every file hash, and writes `production_qualified: false`.

Still open, so this host is not a qualified installation:

- An off-host restore of PostgreSQL plus artifacts checked against a real trained release.
- A worker on the production host, including interruption, cancellation, duplicate delivery, corrupt artifacts, and memory exhaustion.
- An upgrade and rollback rehearsal that does not rebuild the old image tag.
- A clean external consumer of a guided export from that same host.
- A recovery-time or recovery-point claim.

Filesystem artifacts remain the supported store. Executor code is trusted code.
