"""Starting the external chains, for the actions that decide they should run.

Each of these is an `ActionResult.effects` entry: it runs after the deciding
transaction commits, so no adapter is ever asked to create a client for an
approval that then rolled back (plan 12 §6 E1).

There is no separate `retry_*` pair. A retry is the same call — the chain skips
every system whose ledger row is already ACTIVE, so re-running it finishes the
missing ones — and what made a retry distinguishable was its audit record,
which the `retry_provisioning` action now writes as its own `ApplicationEvent`.

Reading and rotating the secret live in `credentials.py`, not here: this module
imports `tasks`, which pulls in the adapter packages that domain code is
forbidden to reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.integrations.tasks import enqueue_chain
from sandbox.integrations.tasks import enqueue_teardown

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from sandbox.experiences.models import ApplicationInstance


def start_provisioning(
    application: ApplicationInstance,
    started_by: AbstractBaseUser | None = None,
) -> None:
    """Approval, and the retry of a failed approval."""
    enqueue_chain(application, started_by=started_by)


def start_deprovisioning(application: ApplicationInstance) -> None:
    """Rejection and withdrawal, and the retry of either.

    No attempt record: teardown has no `ProvisioningRun` to open, because what
    it reports is the ledger emptying, which the ledger already says.
    """
    enqueue_teardown(application)
