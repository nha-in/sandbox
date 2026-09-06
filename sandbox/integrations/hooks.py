"""Provisioning entry points, currently unregistered.

These used to be workflow hooks. `sandbox/workflow/` is gone, and the engine's
`ActionResult.effects` (plan 12 E1) does not exist yet, so plan 14 step 3
leaves them disconnected rather than half-wired: the chains below are intact
and importable, and step 5 attaches them to the approve, reject and withdraw
actions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sandbox.integrations.services import start_deprovisioning  # noqa: F401
from sandbox.integrations.services import start_provisioning  # noqa: F401

if TYPE_CHECKING:
    from sandbox.experiences.models import ApplicationInstance

logger = logging.getLogger(__name__)


def alert_provisioning_failed(application: ApplicationInstance, reason: str) -> None:
    # ERROR reaches Sentry through the logging integration (production.py).
    logger.error("provisioning failed for %s: %s", application.reference, reason)


def register_workflow_hooks() -> None:
    """No-op until step 5. Kept so `AppConfig.ready()` needs no change."""
