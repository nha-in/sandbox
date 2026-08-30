from __future__ import annotations

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    name = "sandbox.integrations"
    verbose_name = "Integrations"

    def ready(self) -> None:
        # Imported here, not at module scope: hooks reach the workflow app, whose
        # models are not loaded yet when AppConfig classes are constructed.
        from sandbox.integrations.hooks import register_workflow_hooks  # noqa: PLC0415

        register_workflow_hooks()
