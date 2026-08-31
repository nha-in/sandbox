"""Which realm roles each workflow's client gets.

Names, never ids: legacy pinned realm role **UUIDs and containerIds** in YAML,
which tied the deployment to one Keycloak instance and silently broke whenever
the realm was rebuilt. `KeycloakIdpAdmin` resolves these to ids at call time.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def role_names_for(kind: str) -> tuple[str, ...]:
    """Least privilege: legacy granted all 14 realm roles to every integrator."""
    try:
        return tuple(settings.KEYCLOAK_ROLE_NAMES[kind])
    except KeyError as exc:
        msg = (
            f"No Keycloak role set configured for workflow {kind!r}. "
            f"Add it to settings.KEYCLOAK_ROLE_NAMES."
        )
        raise ImproperlyConfigured(msg) from exc
