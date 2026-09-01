"""Reads over the provisioning ledger, for C7's panel and the console mirror.

Nothing here returns a secret. The one value that is a secret lives in the
short-lived hand-off (`secret_ref`), is read exactly once by
`services.take_initial_secret`, and is never selected into a context dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils.translation import gettext_lazy as _

from sandbox.integrations.models import ProvisionedResource
from sandbox.integrations.models import ProvisionedResourceState
from sandbox.integrations.models import ProvisionedSystem
from sandbox.integrations.secret_ref import has_secret

if TYPE_CHECKING:
    from django_stubs_ext import StrOrPromise

    from sandbox.applications.models import Application

#: Application states where credentials are a topic at all. Excludes the three
#: that fire B8's teardown: after those the client is gone, and offering a
#: rotate button for a client that no longer exists is worse than silence.
#:
#: Strings rather than the enum, because importing `applications.models` here
#: would close a cycle — that module's own views import this one.
CREDENTIAL_STATES = frozenset(
    {
        "SANDBOX_APPROVED",
        "PROVISIONING",
        "PROVISIONING_FAILED",
        "PROVISIONED",
    },
)

#: What the integrator is told each system is for. The ledger's own names are
#: vendor names; these are the ones on screen.
SYSTEM_LABELS: dict[str, StrOrPromise] = {
    ProvisionedSystem.KEYCLOAK: _("Identity"),
    ProvisionedSystem.WSO2: _("Gateway"),
    ProvisionedSystem.HIECM: _("Bridge"),
}

#: Ledger state -> the careui badge modifier that carries it.
_BADGES = {
    ProvisionedResourceState.ACTIVE: "ui-badge--success",
    ProvisionedResourceState.FAILED: "ui-badge--destructive",
    ProvisionedResourceState.DISABLED: "ui-badge--neutral",
    ProvisionedResourceState.ORPHANED: "ui-badge--warning",
}


@dataclass(frozen=True, slots=True)
class SystemProgress:
    system: str
    label: StrOrPromise
    state: str
    display: StrOrPromise
    badge: str


@dataclass(frozen=True, slots=True)
class Credentials:
    """What the integrator may see. `client_id` is not a secret; the secret is
    never a field here, because a dataclass on a template context is exactly
    how it would end up in a log or an error page."""

    client_id: str
    gateway_ref: str
    bridge_ref: str
    #: Whether the one-time hand-off is still readable. False once revealed or
    #: once the TTL has passed — either way the route on is rotation.
    initial_secret_available: bool


def provisioning_progress(application: Application) -> list[SystemProgress]:
    """One row per system, in chain order, including the ones not reached yet.

    A system with no ledger row is shown rather than omitted: "we have not
    started the bridge" and "there is no bridge" look identical if you only
    render what exists, and the first is the common case mid-chain.

    What that absence *means* depends on the application. B7 deliberately writes
    no row for a system that produced nothing, so on a failed chain the system
    that broke and the systems never attempted are indistinguishable here — but
    neither of them is waiting for anything, and a badge saying so on a chain
    that has stopped reads as progress that is still coming.

    Empty when the chain has not run at all, so a caller can use it to decide
    whether there is anything to show.
    """
    rows = {
        row.system: row
        for row in ProvisionedResource.objects.filter(application=application)
    }
    if not rows:
        return []

    pending = _("Waiting") if application.state == "PROVISIONING" else _("Not set up")
    progress = []
    for system in ProvisionedSystem.values:
        row = rows.get(system)
        progress.append(
            SystemProgress(
                system=system,
                label=SYSTEM_LABELS[system],
                state=row.state if row else "",
                display=row.get_state_display() if row else pending,
                badge=_BADGES.get(row.state, "ui-badge--neutral")
                if row
                else "ui-badge--neutral",
            ),
        )
    return progress


def credentials_for(application: Application) -> Credentials | None:
    """The panel's contents, or None while there is no Keycloak client yet."""
    rows = {
        row.system: row
        for row in ProvisionedResource.objects.filter(
            application=application,
            state=ProvisionedResourceState.ACTIVE,
        )
    }
    client = rows.get(ProvisionedSystem.KEYCLOAK)
    if client is None:
        return None

    gateway = rows.get(ProvisionedSystem.WSO2)
    bridge = rows.get(ProvisionedSystem.HIECM)
    return Credentials(
        client_id=client.public_ref,
        gateway_ref=gateway.public_ref if gateway else "",
        bridge_ref=bridge.public_ref if bridge else "",
        initial_secret_available=has_secret(client.secret_ref),
    )
