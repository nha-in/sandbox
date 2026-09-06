"""Writing an audit line, now that `sandbox/audit/` is gone.

Plan 12 §4.2: every `audit.services.emit` call folds into `ApplicationEvent`,
which is append-only by virtue of `save()` raising on any re-save. The one
guarantee that did not survive is the database-level `REVOKE UPDATE, DELETE`
the audit app carried — recorded there as a deliberate weakening.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sandbox.experiences.models import ApplicationEvent
from sandbox.experiences.models import EventKind

if TYPE_CHECKING:
    from sandbox.experiences.models import ApplicationInstance
    from sandbox.users.models import User


def record(
    action_key: str,
    *,
    application: ApplicationInstance,
    title: str,
    actor: User | None = None,
    payload: dict[str, Any] | None = None,
) -> ApplicationEvent:
    """One thing that happened, with its actor. `actor=None` means the system."""
    return ApplicationEvent.objects.create(
        application=application,
        actor=actor,
        kind=EventKind.ACTION,
        title=title,
        action_key=action_key,
        payload=payload or {},
    )
