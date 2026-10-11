from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "modelanvil.core"
    label = "core"

    def ready(self) -> None:
        # Import signal registrations so they are wired at startup.
        from modelanvil.core import signals  # noqa: F401
