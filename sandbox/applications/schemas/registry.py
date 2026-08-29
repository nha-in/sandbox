"""Payload envelope + per-kind schema registry (03-database.md §3.2).

Envelope `{"schema_version": N, "data": {...}}`, dispatched on
`(kind, schema_version)` to a Django `Form` acting as that kind's spec.

Not in `forms.py` because the import-linter contract orders
`views -> forms -> services`, which would stop services validating their own
writes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.forms import Form

_REGISTRY: dict[tuple[str, int], type[Form]] = {}


def register(
    kind: str,
    schema_version: int,
) -> Callable[[type[Form]], type[Form]]:
    """Decorator: binds a spec form to one `(kind, schema_version)` pair."""

    def decorator(form_class: type[Form]) -> type[Form]:
        _REGISTRY[(kind, schema_version)] = form_class
        return form_class

    return decorator


def payload_form(kind: str, schema_version: int) -> type[Form]:
    """The spec class for a kind — C4 renders what the services validate with."""
    form_class = _REGISTRY.get((kind, schema_version))
    if form_class is None:
        message = f"no payload schema registered for {kind} v{schema_version}"
        raise DomainError(message)
    return form_class


def _format_errors(form: Form) -> str:
    return "; ".join(
        f"{'payload' if field == '__all__' else field}: "
        f"{' '.join(str(error) for error in errors)}"
        for field, errors in form.errors.items()
    )


def validate_payload(kind: str, payload: dict[str, Any]) -> None:
    """Raises `DomainError` on any structural or content problem."""
    if (
        not isinstance(payload, dict)
        or "schema_version" not in payload
        or "data" not in payload
    ):
        message = 'payload must be {"schema_version": int, "data": {...}}'
        raise DomainError(message)

    data = payload["data"]
    if not isinstance(data, dict):
        message = "payload.data must be an object"
        raise DomainError(message)

    form = payload_form(kind, payload["schema_version"])(data=data)
    if not form.is_valid():
        raise DomainError(_format_errors(form))
