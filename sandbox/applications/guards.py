"""Preconditions the workflow enforces on an application's own data.

Registered at app-ready time so `sandbox.workflow` never has to know what a
payload is — it only knows a move named a guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.applications.schemas import validate_payload
from sandbox.workflow.machine import GUARD_PAYLOAD_COMPLETE
from sandbox.workflow.services import register_guard

if TYPE_CHECKING:
    from sandbox.applications.models import Application


def payload_complete(application: Application) -> None:
    """Drafts may be half-finished; submissions may not."""
    validate_payload(application.kind, application.payload)


def register_guards() -> None:
    register_guard(GUARD_PAYLOAD_COMPLETE, payload_complete)
