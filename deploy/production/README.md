# ModelAnvil production deployment

Deploy the API and compiled frontend on one Docker host using PostgreSQL,
Gunicorn and Caddy. This is the first SaaS deployment milestone. Customer
invitations, billing, hosted workers and end-to-end training qualification have
separate acceptance gates; this stack does not start a job worker.

## Configure a release

Use Docker with Compose v2 or later. For a public deployment, point the domain's
DNS at the host and allow inbound TCP 80 and 443. Caddy obtains and renews public
certificates. The API and database have no published host ports. PostgreSQL,
artifacts and certificates live in persistent named volumes on this host.

From the repository root:

```sh
cp deploy/production/.env.example deploy/production/.env
chmod 600 deploy/production/.env
```

Edit the ignored `.env` with the domain, matching HTTPS origin, a unique release
tag and the source commit being built. Set `MODELANVIL_BIND_ADDRESS=0.0.0.0` on
the intended public host; the default binds only to loopback. Use ports 80 and
443 for public certificate issuance. Generate independent secrets with
`python3 -c 'import secrets; print(secrets.token_urlsafe(64))'` and save them as
`DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`. Keep the secret file outside source
control and retain a secure recovery copy.

Production settings reject missing secrets, debug mode, wildcard hosts, HTTP
origins and SQLite. Signup is disabled. Set `MODELANVIL_SEND_RESET_EMAIL=1` and `EMAIL_HOST` when password reset should send mail; the API never returns the reset code while debug is off. The API runs as a non-root user with a
read-only image and a writable artifact volume; development bootstrap is
removed from the image. Gunicorn access logging is disabled to avoid recording
artifact grants. Caddy owns the trusted proxy boundary and overwrites the
forwarded scheme.

## Start the deployment

Use the same Compose project name for every release so volumes remain attached:

```sh
dc() {
  docker compose --env-file deploy/production/.env \
    -p modelanvil-production -f deploy/production/compose.yaml "$@"
}
dc config --quiet
dc build api web
dc up -d --wait --wait-timeout 60 db
dc run --rm migrate
dc run --rm --no-deps migrate python manage.py check --deploy --fail-level ERROR
dc up -d --wait --wait-timeout 120 api web
```

Migrations are an explicit release operation. The API checks for unapplied
migrations and refuses startup; it does not apply them. Never call
`bootstrap_dev` in this stack. Provision the initial Django administrator with
`dc exec api python manage.py createsuperuser` through the interactive prompt.
That administrator does not create a customer tenant or a ModelAnvil browser
account. Tenant onboarding is the next milestone.

The deployment check reports `security.W021`: HSTS preload is intentionally
disabled. HTTPS responses initially use a one-hour HSTS policy with subdomains.
Increase that policy only after confirming the domain and certificate lifecycle;
preload is a separate operator decision.

## Verify HTTPS and persistence

For the deployed public origin:

```sh
python3 scripts/production_smoke.py --origin https://YOUR-DOMAIN
dc ps
dc logs --tail 100 api web
```

The smoke check verifies certificate trust, built assets, SPA routing, Django
static files, database readiness, proxy handling, secure CSRF cookies and rejected
foreign-origin requests. To check sign-in with an existing dedicated test
account, add `--credentials /secure/path/staging-user.json`; the private JSON
contains `email` and `password`. Do not commit that file. Sign-in creates a
session, so use a test account for this optional check.

For a complete local staging exercise:

```sh
make test-production
```

The test builds both images, chooses loopback ports, creates its own PostgreSQL
database and trusted local Caddy CA, confirms startup refuses unapplied
migrations, then migrates and provisions a synthetic test account. It checks
HTTPS redirects, authentication and CSRF behavior, restarts the API, and confirms
the account and writable artifact volume persist. It removes only the uniquely
named test project's containers and volumes. CI runs this exercise too. It does
not prove public DNS or ACME issuance.

## Back up before an upgrade

Retain the current environment file and both release images. Never rebuild an
existing release tag; frontend and backend must come from the same source
revision. Base images use version tags, so preserve the actual built images or
publish them to your registry by digest for repeatable rollback.

Pause writes before capturing PostgreSQL and artifacts together. With no workers
running in this stack, stop the API and web services:

```sh
set -eu
mkdir -p storage/backups
chmod 700 storage/backups
dc stop web api
dc exec -T db pg_dump -U modelanvil -d modelanvil -Fc > storage/backups/database.dump
dc run --rm -T --no-deps migrate tar -C /app/storage/artifacts -czf - . > storage/backups/artifacts.tar.gz
chmod 600 storage/backups/database.dump storage/backups/artifacts.tar.gz
```

Use a fresh backup directory per release so earlier recovery points survive.
Copy backups and release images to durable storage off this host. Backups are
only useful once restored in a separate rehearsal environment. Certificate
volumes can be retained in place; keep their private keys protected if copied.
Changing the database password in `.env` does not rotate an existing PostgreSQL
user's password; perform database credential rotation separately.

## Upgrade and roll back

After the backup succeeds, change only the image tag and source revision in
`.env`, build both images, run the explicit migration and deployment check, then
start and verify both services using the commands above. Keep the project name,
secrets and domain stable.

If the previous code supports the resulting database schema, restore the old
image tag and revision in `.env`, then run:

```sh
dc up -d --no-build --wait --wait-timeout 120 api web
python3 scripts/production_smoke.py --origin https://YOUR-DOMAIN
```

Do not rebuild the old tag during rollback. If a migration is incompatible with
the previous code, stop writes and restore the paired database and artifact
backup into a separate recovery stack first. Validate it there before switching
traffic; do not run destructive restores against the live database as a routine
rollback. Never use `docker compose down --volumes` on the live project.

This milestone verifies deployment and restart persistence locally. Off-host
restore, availability monitoring, durable object storage and GPU worker recovery
are later production acceptance gates.
