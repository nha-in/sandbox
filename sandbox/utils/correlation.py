"""Correlation id shared by every subsystem that records what happened.

One id ties a web request to the audit rows it wrote, the Celery chain it
enqueued, and the outbound calls that chain made (04-observability.md). It lives
in utils rather than in `integrations` so `audit` can stamp it without importing
the HTTP layer.
"""

from __future__ import annotations

import contextvars
import uuid

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id",
    default="",
)


def get_correlation_id() -> str:
    """The current context's id, generated on first use."""
    current = _correlation_id.get()
    if not current:
        current = uuid.uuid4().hex
        _correlation_id.set(current)
    return current


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)
