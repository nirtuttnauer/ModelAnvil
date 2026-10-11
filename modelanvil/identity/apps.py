from django.apps import AppConfig


class IdentityConfig(AppConfig):
    name = "modelanvil.identity"
    label = "identity"

    def ready(self) -> None:
        from modelanvil.identity import signals  # noqa: F401
