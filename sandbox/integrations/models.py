"""Provisioning ledger (B1 schema; the chain that writes it is B7/B8).

What we created in each external system, so a failed or partial provisioning run
can be reconciled instead of guessed at. Legacy had no such record: rejection
deactivated Keycloak and left WSO2 and the bridge live, with nothing to detect
the drift.

`secret_ref` is a secret-store reference, never a secret value (05-security §3).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.utils.models import BaseModel


class ProvisionedSystem(models.TextChoices):
    """Systems we create resources *in*.

    Narrower than `ports.ExternalSystem`, which also has NOTIFICATION — that is
    something we send through, not something we provision, so it has no ledger row.
    """

    KEYCLOAK = "KEYCLOAK", _("Keycloak")
    WSO2 = "WSO2", _("WSO2")
    HIECM = "HIECM", _("HIE-CM")


class ProvisionedResourceState(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    DISABLED = "DISABLED", _("Disabled")
    FAILED = "FAILED", _("Failed")
    #: exists in the external system with no live owner here — reconciliation's job
    ORPHANED = "ORPHANED", _("Orphaned")


class ProvisionedResource(BaseModel):
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="provisioned_resources",
    )
    system = models.CharField(max_length=20, choices=ProvisionedSystem.choices)
    #: NOT `external_id`: that is BaseModel's public UUID, and declaring it here
    #: silently replaces it, leaving the row with no identifier of its own.
    external_ref = models.CharField(max_length=255)
    #: The handle a person sees, where it differs from the one we call the API
    #: with. Only Keycloak has both: `external_ref` is the internal UUID that
    #: `disable_client`/`rotate_client_secret` take, while the OAuth `clientId`
    #: is what C7 shows the integrator, what WSO2 maps as its consumer key, and
    #: what B7 names the HIE-CM bridge after.
    public_ref = models.CharField(max_length=255, blank=True)
    secret_ref = models.CharField(max_length=255, blank=True)
    state = models.CharField(
        max_length=20,
        choices=ProvisionedResourceState.choices,
        default=ProvisionedResourceState.ACTIVE,
    )

    class Meta:
        constraints = [
            # The idempotency backstop: a retried chain must not create a second
            # client for the same application in the same system.
            models.UniqueConstraint(
                fields=["application", "system"],
                condition=models.Q(deleted=False),
                name="integrations_provisioned_resource_unique_application_system",
            ),
            models.CheckConstraint(
                condition=models.Q(system__in=ProvisionedSystem.values),
                name="integrations_provisioned_resource_system_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=ProvisionedResourceState.values),
                name="integrations_provisioned_resource_state_valid",
            ),
        ]
        indexes = [
            # Reconciliation sweeps read by state across every application.
            models.Index(
                fields=["system", "state"],
                name="integrations_system_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.system}:{self.external_ref} ({self.state})"
