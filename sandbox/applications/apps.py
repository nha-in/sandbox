from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    name = "sandbox.applications"
    verbose_name = "Applications"

    def ready(self):
        # Deferred: registering at import time would run before the app registry.
        from sandbox.applications.guards import register_guards  # noqa: PLC0415

        register_guards()
