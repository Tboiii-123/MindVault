from django.apps import AppConfig


class ContainersConfig(AppConfig):
    name = "apps.containers"

    def ready(self):
        from . import signals  # noqa: F401
