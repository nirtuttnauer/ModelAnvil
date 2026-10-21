"""ModelAnvil Django settings.

Single module, environment-driven. The control plane must run identically
across environments; the only things that change are the database backend,
secret material, and toggles. Tests run on an in-memory/temporary SQLite
database by default so the suite is dependency-free, and production uses
PostgreSQL via ``DATABASE_URL``-style env vars.
"""

from __future__ import annotations

import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

import tempfile
MODELANVIL_DEVICE_LOCK_ROOT = os.environ.get('MODELANVIL_DEVICE_LOCK_ROOT',
    str(Path(tempfile.gettempdir()) / f'modelanvil-devices-{os.getuid() if hasattr(os, "getuid") else "local"}'))

# Operator secrets are keyed by tenant UUID:project UUID; ambient Hub credentials are ignored.
MODELANVIL_HUB_TOKENS = json.loads(os.environ.get('MODELANVIL_HUB_TOKENS', '{}'))
if not isinstance(MODELANVIL_HUB_TOKENS, dict) or any(not isinstance(v, str) or not v for v in MODELANVIL_HUB_TOKENS.values()):
    raise ValueError('MODELANVIL_HUB_TOKENS must map tenant:project identifiers to nonempty tokens.')

# ---------------------------------------------------------------------------
# Secrets & environment
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "insecure-development-key-change-me-in-production",
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
MODELANVIL_SELF_SERVICE_ACCOUNTS = os.environ.get("MODELANVIL_SELF_SERVICE_ACCOUNTS", "1" if DEBUG else "0") == "1"
MODELANVIL_LOCAL_MODEL_DIR = os.environ.get("MODELANVIL_LOCAL_MODEL_DIR", "")
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")
    if h.strip()
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Default: SQLite (dev + tests). Set DATABASE_ENGINE=postgresql for a real
# Postgres via DATABASE_NAME/USER/PASSWORD/HOST/PORT.
_db_engine = os.environ.get("DATABASE_ENGINE", "sqlite")
if _db_engine == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DATABASE_NAME", "modelanvil"),
            "USER": os.environ.get("DATABASE_USER", "modelanvil"),
            "PASSWORD": os.environ.get("DATABASE_PASSWORD", ""),
            "HOST": os.environ.get("DATABASE_HOST", "localhost"),
            "PORT": os.environ.get("DATABASE_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / os.environ.get("DATABASE_NAME", "modelanvil.db"),
            # Acquire the writer lock before reads so worker heartbeats cannot
            # invalidate a later lock upgrade in a local API write transaction.
            "OPTIONS": {"transaction_mode": "IMMEDIATE"},
            # HTTP tests need separate connections instead of shared in-memory SQLite.
            "TEST": {"NAME": os.environ.get("DATABASE_TEST_NAME")},
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "django_filters",
    "corsheaders",
    # modelanvil apps (order matters for signal wiring)
    "modelanvil.core",
    "modelanvil.identity",
    "modelanvil.jobs",
    "modelanvil.artifacts",
    "modelanvil.data",
    "modelanvil.runners",
    "modelanvil.budgets",
    "modelanvil.annotation",
    "modelanvil.rag",
    "modelanvil.context_lab",
    "modelanvil.releases",
    "modelanvil.ops",
    "modelanvil.acceptance",
    "modelanvil.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # request id + structured error envelope
    "modelanvil.core.middleware.RequestIdMiddleware",
    "modelanvil.core.middleware.ExceptionMiddleware",
]

ROOT_URLCONF = "modelanvil.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "web" / "dist"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "modelanvil.wsgi.application"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
AUTH_USER_MODEL = "identity.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "modelanvil.identity.auth.ApiKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "modelanvil.core.pagination.CursorPagination",
    "PAGE_SIZE": 50,
    "EXCEPTION_HANDLER": "modelanvil.core.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "accounts": "10/min",
        "activation": "60/min",
        "user": "600/min",
        "worker": "1200/min",
    },
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if o.strip()
]

# ---------------------------------------------------------------------------
# i18n / static / media
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# ModelAnvil platform settings
# ---------------------------------------------------------------------------
# Where immutable artifacts live. In production this is object storage; the
# filesystem backend is the dev/test default.
MODELANVIL = {
    "artifact_backend": os.environ.get("MODELANVIL_ARTIFACT_BACKEND", "filesystem"),
    "artifact_root": os.environ.get(
        "MODELANVIL_ARTIFACT_ROOT", str(BASE_DIR / "storage" / "artifacts")
    ),
    "s3_endpoint_url": os.environ.get("MODELANVIL_S3_ENDPOINT", ""),
    "s3_bucket": os.environ.get("MODELANVIL_S3_BUCKET", ""),
    "s3_region": os.environ.get("MODELANVIL_S3_REGION", "us-east-1"),
    "s3_access_key": os.environ.get("MODELANVIL_S3_ACCESS_KEY", ""),
    "s3_secret_key": os.environ.get("MODELANVIL_S3_SECRET_KEY", ""),
    # Lease / fencing defaults for the execution protocol.
    "worker_lease_seconds": int(os.environ.get("MODELANVIL_WORKER_LEASE_SECONDS", "300")),
    "worker_heartbeat_grace_seconds": int(
        os.environ.get("MODELANVIL_WORKER_HEARTBEAT_GRACE_SECONDS", "900")
    ),
    "worker_credential_seconds": int(
        os.environ.get("MODELANVIL_WORKER_CREDENTIAL_SECONDS", str(30 * 24 * 60 * 60))
    ),
    "max_attempts_default": int(os.environ.get("MODELANVIL_MAX_ATTEMPTS", "3")),
    # Outbox flush batch size.
    "outbox_batch_size": int(os.environ.get("MODELANVIL_OUTBOX_BATCH", "100")),
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "modelanvil.core.logging.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
}
