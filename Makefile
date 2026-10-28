PYTHON ?= .venv/bin/python

.PHONY: test-production
test-production:
	$(PYTHON) scripts/production_integration.py

.PHONY: check test test-broker-integration test-accounting-integration test-worker-integration test-dataset-integration test-web migrate migration-check smoke reconcile prune-transfer-parts web-install web-build up down logs local
check:
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) manage.py check

test:
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) -m django test -v 1

test-broker-integration:
	@set -eu; \
	project=modelanvil-broker-test; \
	trap 'docker compose -p "$$project" -f compose.yaml down -v --remove-orphans' EXIT; \
	docker compose -p "$$project" -f compose.yaml up -d --wait db rabbitmq; \
	docker compose -p "$$project" -f compose.yaml run --build --rm --no-deps -e DJANGO_SETTINGS_MODULE=modelanvil.settings -e PYTHONPATH=/app -e LOG_LEVEL=WARNING api python -m django test modelanvil.jobs.test_broker -v 2

migrate:
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) manage.py migrate

test-accounting-integration:
	@set -eu; \
	project=modelanvil-accounting-test; \
	trap 'docker compose -p "$$project" -f compose.yaml down -v --remove-orphans' EXIT; \
	docker compose -p "$$project" -f compose.yaml up -d --wait db; \
	docker compose -p "$$project" -f compose.yaml run --build --rm --no-deps -e DJANGO_SETTINGS_MODULE=modelanvil.settings -e PYTHONPATH=/app -e LOG_LEVEL=WARNING api python -m django test modelanvil.budgets modelanvil.api.test_accounting -v 2

test-worker-integration:
	@set -eu; \
	project=modelanvil-worker-test; \
	trap 'docker compose -p "$$project" -f compose.yaml down -v --remove-orphans' EXIT; \
	docker compose -p "$$project" -f compose.yaml up -d --wait db; \
	docker compose -p "$$project" -f compose.yaml run --build --rm --no-deps -e DJANGO_SETTINGS_MODULE=modelanvil.settings -e PYTHONPATH=/app -e LOG_LEVEL=WARNING api python -m django test modelanvil.jobs.test_remote_worker modelanvil.jobs.test_remote_artifacts modelanvil.api.test_worker_egress modelanvil.api.test_worker_artifacts modelanvil.api.test_worker_artifact_http -v 2

migration-check:
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) manage.py makemigrations --check --dry-run

test-dataset-integration:
	@set -eu; \
	project=modelanvil-dataset-test; \
	trap 'docker compose -p "$$project" -f compose.yaml -f compose.dataset-tests.yaml down -v --remove-orphans' EXIT; \
	docker compose -p "$$project" -f compose.yaml -f compose.dataset-tests.yaml up -d --wait db; \
	docker compose -p "$$project" -f compose.yaml -f compose.dataset-tests.yaml run --build --rm --no-deps -e DJANGO_SETTINGS_MODULE=modelanvil.settings -e PYTHONPATH=/app api python -m django test modelanvil.data.test_preparation modelanvil.api.test_dataset_preparation modelanvil.api.test_dataset_preparation_http -v 1

test-web:
	cd web && npm test

.PHONY: test-web-browser
test-web-browser:
	cd web && npm run test:browser

smoke:
	PYTHONPATH=. $(PYTHON) -m scripts.smoke

reconcile:
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) manage.py reconcile_leases

prune-transfer-parts:
	@test -n "$(RETENTION_DAYS)" || { echo "Set RETENTION_DAYS to an approved retention period."; exit 2; }
	DJANGO_SETTINGS_MODULE=modelanvil.settings PYTHONPATH=. $(PYTHON) manage.py prune_transfer_parts --retention-days "$(RETENTION_DAYS)"

web-install:
	cd web && npm ci

web-build:
	cd web && npm ci && npm run build

up:
	docker compose -f compose.yaml up --build

down:
	docker compose -f compose.yaml down

logs:
	docker compose -f compose.yaml logs -f api db rabbitmq object-store outbox-publisher lease-reconciler web

# Installation owner entry point; user training runs are launched in the browser.
local:
	.venv-gpu/bin/python manage.py run_local
