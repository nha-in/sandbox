"""Public API for payload schemas.

Each kind's spec module is imported here for its `@register` side-effect;
adding HCX/UHI/HIU/NHCX later is a new module plus one line below.
"""

from __future__ import annotations

from sandbox.applications.schemas import sandbox  # noqa: F401  (registers SANDBOX v1)
from sandbox.applications.schemas.registry import payload_form
from sandbox.applications.schemas.registry import register
from sandbox.applications.schemas.registry import validate_payload

__all__ = ["payload_form", "register", "validate_payload"]
