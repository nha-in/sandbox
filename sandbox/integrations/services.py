"""Starting and restarting provisioning, and reading its credentials back once.

Both entry points go through `transition()`: the console's retry button is a
workflow move like any other, so it is permission-checked and audited rather
than being a bare "run the job again".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.secret_ref import discard_secret
from sandbox.integrations.secret_ref import resolve_secret
from sandbox.integrations.tasks import enqueue_chain
from sandbox.workflow.machine import Action
from sandbox.workflow.services import transition

if TYPE_CHECKING:
    from sandbox.applications.models import Application
    from sandbox.users.models import User
    from sandbox.workflow.models import WorkflowTransition


def start_provisioning(
    application: Application,
    _transition: WorkflowTransition,
) -> None:
    """Hook body for `provisioning_chain`, fired by approval and by retry."""
    enqueue_chain(application)


def retry_provisioning(
    *,
    application: Application,
    actor: User,
) -> WorkflowTransition:
    """Re-run the chain for the console's retry button.

    Nothing is cleaned up first: completed systems have ACTIVE ledger rows and
    are skipped, so a retry finishes the missing ones. The transition's own hook
    is what re-enqueues the chain.
    """
    return transition(
        application=application,
        action=Action.RETRY_PROVISIONING,
        actor=actor,
    )


def take_initial_secret(application: Application) -> str | None:
    """Read the Keycloak secret once, then destroy the reference (C7).

    Returns None when it has already been read or the short TTL has passed; the
    integrator's route back from there is rotation, not a second look.
    """
    row = ProvisionedResource.objects.filter(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
        state=ProvisionedResourceState.ACTIVE,
    ).first()
    if row is None or not row.secret_ref:
        return None

    try:
        secret = resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK)
    except AdapterError:
        return None
    finally:
        discard_secret(row.secret_ref)
        row.secret_ref = ""
        row.save(update_fields=["secret_ref", "modified_date"])

    return secret
