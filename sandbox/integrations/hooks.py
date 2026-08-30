"""Workflow hooks this app answers to. Registered from `AppConfig.ready()`.

`alert_provisioning_failed` exists so the terminal state is loud: legacy's
partial failures were silent, and an application that stops half-provisioned
with nobody paged is the same outcome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sandbox.integrations.services import start_deprovisioning
from sandbox.integrations.services import start_provisioning
from sandbox.workflow.services import register_hook

if TYPE_CHECKING:
    from sandbox.applications.models import Application
    from sandbox.workflow.models import WorkflowTransition

logger = logging.getLogger(__name__)


def alert_provisioning_failed(
    application: Application,
    record: WorkflowTransition,
) -> None:
    # ERROR reaches Sentry through the logging integration (production.py).
    logger.error(
        "provisioning failed for %s: %s",
        application.reference,
        record.comment,
    )


def register_workflow_hooks() -> None:
    register_hook("provisioning_chain", start_provisioning)
    register_hook("deprovisioning_chain", start_deprovisioning)
    register_hook("alert_provisioning_failed", alert_provisioning_failed)
