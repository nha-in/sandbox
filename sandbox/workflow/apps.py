from django.apps import AppConfig
from django.db.models.signals import post_migrate


def sync_workflow_permissions(sender, **kwargs) -> None:
    """Create one Permission per name the workflow registry declares.

    Deliberately not `WorkflowTransition.Meta.permissions`: a programme is code
    and adding one must not require a migration in this app.
    """
    from django.contrib.auth.models import Permission  # noqa: PLC0415
    from django.contrib.contenttypes.models import ContentType  # noqa: PLC0415

    from sandbox.workflow.models import WorkflowTransition  # noqa: PLC0415
    from sandbox.workflow.registry import permission_labels  # noqa: PLC0415

    content_type = ContentType.objects.get_for_model(WorkflowTransition)
    for name, label in permission_labels().items():
        Permission.objects.update_or_create(
            codename=name.split(".", 1)[1],
            content_type=content_type,
            defaults={"name": label},
        )


class WorkflowConfig(AppConfig):
    name = "sandbox.workflow"
    verbose_name = "Workflow"

    def ready(self) -> None:
        # Deferred: registering at import time would run before the app registry.
        from sandbox.workflow.guards import register_default_guards  # noqa: PLC0415

        register_default_guards()
        post_migrate.connect(sync_workflow_permissions, sender=self)
