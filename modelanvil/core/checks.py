"""Deploy checks for insecure development defaults."""

from django.core.checks import Error, Tags, register

# Kept in sync with the development default in modelanvil.settings.
INSECURE_DEFAULT_SECRET_KEY = "insecure-development-key-change-me-in-production"


@register(Tags.security, deploy=True)
def check_debug_off_rejects_default_secret_key(app_configs, **kwargs):
    """Fail deploy checks when DEBUG is off and the development key is still set."""
    from django.conf import settings

    if settings.DEBUG:
        return []
    if settings.SECRET_KEY == INSECURE_DEFAULT_SECRET_KEY:
        return [
            Error(
                "Refusing the insecure development SECRET_KEY while DJANGO_DEBUG is off.",
                hint="Set DJANGO_SECRET_KEY to a unique secret before running with DJANGO_DEBUG=0.",
                id="modelanvil.E001",
            )
        ]
    return []
