"""Starting and restarting provisioning.

Both entry points go through `transition()`: the console's retry button is a
workflow move like any other, so it is permission-checked and audited rather
than being a bare "run the job again".

Reading and rotating the secret live in `credentials.py`, not here: this module
imports `tasks`, which pulls in the adapter packages that domain code is
forbidden to reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.audit.services import emit
from sandbox.integrations.tasks import enqueue_chain
from sandbox.integrations.tasks import enqueue_teardown
from sandbox.utils.errors import DomainError
from sandbox.workflow.definitions import PERM_RETRY_PROVISIONING
from sandbox.workflow.engine import transition

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
        action="RETRY_PROVISIONING",
        actor=actor,
    )


def start_deprovisioning(
    application: Application,
    _transition: WorkflowTransition,
) -> None:
    """Hook body for `deprovisioning_chain`, fired by rejection and withdrawal."""
    enqueue_teardown(application)


def retry_deprovisioning(*, application: Application, actor: User) -> None:
    """Re-run the teardown for the console's retry button.

    Unlike `retry_provisioning` there is no transition to ride: the application
    already sits in a terminal state, so the permission check and the audit row
    have to be made here rather than inherited from `transition()`.
    """
    if not actor.has_perm(PERM_RETRY_PROVISIONING):
        message = f"retrying deprovisioning requires {PERM_RETRY_PROVISIONING}"
        raise DomainError(message, code="forbidden")

    emit(
        "application.deprovisioning_retried",
        obj=application,
        actor=actor,
        data={"reference": application.reference},
    )
    enqueue_teardown(application)
