"""Settings for the private API behind the production Caddy proxy."""
import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


def required(name):
    value = os.environ.get(name, '')
    if not value.strip():
        raise ImproperlyConfigured(f'{name} is required for production.')
    return value


if os.environ.get('DJANGO_DEBUG', '0') != '0':
    raise ImproperlyConfigured('DJANGO_DEBUG must be 0 for production.')
DEBUG = False
SECRET_KEY = required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY must be a strong production secret.')

ALLOWED_HOSTS = [host.strip() for host in required('DJANGO_ALLOWED_HOSTS').split(',')]
if any(not host or '*' in host or host.startswith('.') or '/' in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS must contain explicit hostnames.')

origin = required('MODELANVIL_PUBLIC_ORIGIN')
try:
    parsed = urlsplit(origin)
    parsed.port
except ValueError:
    raise ImproperlyConfigured('MODELANVIL_PUBLIC_ORIGIN must be a valid HTTPS origin.') from None
if (parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username is not None or parsed.password is not None
        or parsed.path or parsed.query or parsed.fragment):
    raise ImproperlyConfigured('MODELANVIL_PUBLIC_ORIGIN must be an HTTPS origin on an allowed host.')
CSRF_TRUSTED_ORIGINS = [origin]
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [origin]

if os.environ.get('DATABASE_ENGINE') != 'postgresql':
    raise ImproperlyConfigured('Production requires DATABASE_ENGINE=postgresql.')
for name in ('DATABASE_NAME', 'DATABASE_USER', 'DATABASE_PASSWORD', 'DATABASE_HOST'):
    required(name)

MODELANVIL_SELF_SERVICE_ACCOUNTS = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
# Only the private Caddy proxy can reach this API and it overwrites this header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_REDIRECT_EXEMPT = [r'^api/v1/health/$', r'^api/v1/ready/$']
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# Enable preloading only after the operator has qualified the domain long term.
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
