"""The transient hand-off for a secret we deliberately do not store.

`ApiGateway.map_keys` needs the integrator's Keycloak secret to hand to WSO2,
but 05-security §3 forbids persisting it: legacy kept plaintext copies in
`sd_status.gen_securate` and emailed them. So the provisioning chain (B7) puts
the value here under an opaque reference with a short TTL, and the one caller
that genuinely needs it reads it back within the same chain run.

Cache-backed, so it expires on its own even if a chain dies mid-way. Nothing
here is ever logged, and the reference is not derived from the secret.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.cache import cache

from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem

_KEY = "secret_ref:{ref}"


def store_secret(value: str) -> str:
    """Park a secret for the length of one provisioning chain; returns its ref."""
    ref = secrets.token_urlsafe(24)
    cache.set(_KEY.format(ref=ref), value, settings.SECRET_REF_TTL_SECONDS)
    return ref


def resolve_secret(ref: str, system: ExternalSystem) -> str:
    """Expired or unknown refs are retryable: the chain can re-run from Keycloak."""
    value = cache.get(_KEY.format(ref=ref))
    if not value:
        raise AdapterError(
            system,
            "SECRET_REF_EXPIRED",
            retryable=True,
            message="the referenced secret is no longer available",
        )
    return value


def discard_secret(ref: str) -> None:
    cache.delete(_KEY.format(ref=ref))
