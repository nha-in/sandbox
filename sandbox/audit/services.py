"""`emit()` — the only writer of audit rows."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sandbox.audit.models import AuditEvent
from sandbox.utils.correlation import get_correlation_id

if TYPE_CHECKING:
    from django.db.models import Model

    from sandbox.users.models import User


def emit(
    action: str,
    *,
    obj: Model | None = None,
    actor: User | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    """Record that `action` happened.

    `data` must be render-safe: it reaches a console screen and a log, so no
    secrets, no tokens, no payload dumps.
    """
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=obj._meta.label_lower if obj is not None else "",  # noqa: SLF001
        object_external_id=getattr(obj, "external_id", None),
        correlation_id=get_correlation_id(),
        data=data or {},
    )
