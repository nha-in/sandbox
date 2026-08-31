from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "sandbox.workflow"
    verbose_name = "Workflow"

    def ready(self) -> None:
        # Deferred: registering at import time would run before the app registry.
        from sandbox.workflow.guards import register_default_guards  # noqa: PLC0415

        register_default_guards()
