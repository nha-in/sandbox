"""The two operations C7's panel performs on a Keycloak client.

Separate from `services.py` deliberately. That module imports `tasks`, which
imports the Keycloak and WSO2 adapter packages by name, and the anti-corruption
contract (06-integrations §3) forbids `sandbox.applications` from reaching them
even transitively. A view needs these two functions and nothing else in the
chain, so they live where a view may import them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.audit.services import emit
from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.ports import AdapterError
from sandbox.integrations.ports import ExternalSystem
from sandbox.integrations.registry import get_idp_admin
from sandbox.integrations.secret_ref import discard_secret
from sandbox.integrations.secret_ref import resolve_secret
from sandbox.organisations.selectors import is_owner
from sandbox.utils.errors import DomainError

if TYPE_CHECKING:
    from sandbox.applications.models import Application
    from sandbox.users.models import User


def _keycloak_client(application: Application) -> ProvisionedResource | None:
    return ProvisionedResource.objects.filter(
        application=application,
        system=ProvisionedSystem.KEYCLOAK,
        state=ProvisionedResourceState.ACTIVE,
    ).first()


def _forget_secret_ref(row: ProvisionedResource) -> None:
    discard_secret(row.secret_ref)
    row.secret_ref = ""
    row.save(update_fields=["secret_ref", "modified_date"])


def take_initial_secret(application: Application) -> str | None:
    """Read the Keycloak secret once, then destroy the reference (C7).

    Returns None when it has already been read or the short TTL has passed; the
    integrator's route back from there is rotation, not a second look.
    """
    row = _keycloak_client(application)
    if row is None or not row.secret_ref:
        return None

    try:
        secret = resolve_secret(row.secret_ref, ExternalSystem.KEYCLOAK)
    except AdapterError:
        return None
    finally:
        _forget_secret_ref(row)

    return secret


def rotate_credentials(*, application: Application, actor: User) -> str:
    """Mint a new Keycloak secret and return it for its one showing (C7).

    Returned rather than parked in the hand-off: the caller is the request that
    is about to render it, so there is nothing to hand off to and no reason for
    the value to touch the cache at all.

    Keycloak is the only system touched. WSO2 keeps the key mapping made at
    provisioning, which now holds the previous secret; the gateway validates the
    JWT rather than the secret, so this is expected to be harmless — but it is
    unverified against a real gateway, and is C7's second staging line.
    """
    if not is_owner(application.product.organisation, actor):
        message = "only an owner of this organisation may rotate credentials"
        raise DomainError(message, code="forbidden")

    row = _keycloak_client(application)
    if row is None:
        message = "there are no credentials to rotate yet"
        raise DomainError(message, code="not_provisioned")

    rotated = get_idp_admin().rotate_client_secret(row.external_ref)

    # An unread initial secret is now the wrong one, and the panel reads this
    # field to decide whether to offer a reveal.
    if row.secret_ref:
        _forget_secret_ref(row)

    emit(
        "credentials.rotated",
        obj=application,
        actor=actor,
        data={"reference": application.reference, "client_id": row.public_ref},
    )
    return rotated.secret
