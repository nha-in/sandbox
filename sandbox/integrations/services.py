"""Starting and restarting provisioning.

Plan 14 step 3 unplugged this: `sandbox/workflow/` is gone, so neither entry
point rides a transition any more, and the permission check that guarded a
retry has nowhere to live until step 5 turns it into a registry action. Both
retries enqueue their chain directly in the meantime — safe, because nothing
calls either until step 5 reconnects the hooks.

Reading and rotating the secret live in `credentials.py`, not here: this module
imports `tasks`, which pulls in the adapter packages that domain code is
forbidden to reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.integrations.events import record
from sandbox.integrations.tasks import enqueue_chain
from sandbox.integrations.tasks import enqueue_teardown

if TYPE_CHECKING:
    from sandbox.experiences.models import ApplicationInstance
    from sandbox.users.models import User


def start_provisioning(application: ApplicationInstance) -> None:
    """Reconnected to the approve action's `effects` in step 5."""
    enqueue_chain(application)


def start_deprovisioning(application: ApplicationInstance) -> None:
    """Reconnected to reject and withdraw in step 5."""
    enqueue_teardown(application)


def retry_provisioning(*, application: ApplicationInstance, actor: User) -> None:
    """Re-run the chain.

    Nothing is cleaned up first: completed systems have ACTIVE ledger rows and
    are skipped, so a retry finishes the missing ones.
    """
    record(
        "retry_provisioning",
        application=application,
        title="Provisioning retried",
        actor=actor,
        payload={"reference": application.reference},
    )
    enqueue_chain(application)


def retry_deprovisioning(*, application: ApplicationInstance, actor: User) -> None:
    """Re-run the teardown."""
    record(
        "retry_deprovisioning",
        application=application,
        title="Deprovisioning retried",
        actor=actor,
        payload={"reference": application.reference},
    )
    enqueue_teardown(application)
