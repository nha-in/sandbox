"""Applications: one row per enrollment attempt.

`kind` + a versioned JSON `payload` replace the legacy system's five
duplicated per-track tables; v0 creates only SANDBOX rows (03-database.md
§3.2).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.applications.managers import ApplicationManager
from sandbox.organisations.models import Product
from sandbox.utils.models import BaseModel


class ApplicationKind(models.TextChoices):
    SANDBOX = "SANDBOX", _("Sandbox")
    HCX = "HCX", _("HCX")
    UHI = "UHI", _("UHI")
    HIU = "HIU", _("HIU")
    NHCX = "NHCX", _("NHCX")


class ApplicationState(models.TextChoices):
    DRAFT = "DRAFT", _("Draft")
    SUBMITTED = "SUBMITTED", _("Submitted")
    SANDBOX_APPROVED = "SANDBOX_APPROVED", _("Sandbox approved")
    PROVISIONING = "PROVISIONING", _("Provisioning")
    PROVISIONED = "PROVISIONED", _("Provisioned")
    PROVISIONING_FAILED = "PROVISIONING_FAILED", _("Provisioning failed")
    REJECTED = "REJECTED", _("Rejected")
    SENT_BACK = "SENT_BACK", _("Sent back")
    EXIT_REQUESTED = "EXIT_REQUESTED", _("Exit requested")
    EXIT_REVIEW = "EXIT_REVIEW", _("Exit review")
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED", _("Production approved")
    EXIT_REJECTED = "EXIT_REJECTED", _("Exit rejected")
    WITHDRAWN = "WITHDRAWN", _("Withdrawn")


#: states that free up (product, kind) for a fresh application
NON_BLOCKING_STATES = (ApplicationState.REJECTED, ApplicationState.WITHDRAWN)


class Application(BaseModel):
    """`state` is denormalized; A5's `transition()` becomes its only writer."""

    reference = models.CharField(max_length=15, editable=False)
    kind = models.CharField(max_length=20, choices=ApplicationKind.choices)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    state = models.CharField(
        max_length=30,
        choices=ApplicationState.choices,
        default=ApplicationState.DRAFT,
    )
    payload = models.JSONField()
    submitted_at = models.DateTimeField(null=True, blank=True)

    objects = ApplicationManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["reference"],
                condition=models.Q(deleted=False),
                name="applications_application_unique_reference",
            ),
            models.UniqueConstraint(
                fields=["product", "kind"],
                condition=models.Q(deleted=False)
                & ~models.Q(state__in=NON_BLOCKING_STATES),
                name="applications_application_unique_live_product_kind",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=ApplicationKind.values),
                name="applications_application_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(state__in=ApplicationState.values),
                name="applications_application_state_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["kind", "state"],
                name="applications_application_kind_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.reference


class ApplicationReferenceCounter(models.Model):
    """Counter behind `services._next_reference`; skips `BaseModel` because no
    row here is ever addressed from outside."""

    year = models.PositiveIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.year}: {self.last_value}"
