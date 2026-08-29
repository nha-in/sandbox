"""Tenancy: who acts for which company, and what that company actually certifies.

`Membership` is the join between identity (`users.User`) and tenancy
(`Organisation`); `Product` is what gets certified — one organisation can run
several products, each with its own applications and milestone track.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from sandbox.organisations.managers import OrganisationScopedManager
from sandbox.utils.models import BaseModel


class OrganisationKind(models.TextChoices):
    ORGANIZATION = "ORGANIZATION", _("Organization")
    INDIVIDUAL = "INDIVIDUAL", _("Individual")


class OrganisationVerificationState(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    VERIFIED = "VERIFIED", _("Verified")


class MembershipRole(models.TextChoices):
    OWNER = "OWNER", _("Owner")
    DEVELOPER = "DEVELOPER", _("Developer")


class Organisation(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    kind = models.CharField(max_length=20, choices=OrganisationKind.choices)
    website = models.URLField(blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    address_city = models.CharField(max_length=100, blank=True)
    address_pincode = models.CharField(max_length=10, blank=True)
    # LGD is external reference data with no table of ours (A1) — stored by code only
    lgd_state_code = models.CharField(max_length=10, blank=True)
    lgd_district_code = models.CharField(max_length=10, blank=True)
    verification_state = models.CharField(
        max_length=20,
        choices=OrganisationVerificationState.choices,
        default=OrganisationVerificationState.PENDING,
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="organisations_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(deleted=False),
                name="organisations_organisation_unique_slug",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=OrganisationKind.values),
                name="organisations_organisation_kind_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    verification_state__in=OrganisationVerificationState.values,
                ),
                name="organisations_organisation_verification_state_valid",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Product(BaseModel):
    """What actually gets certified — an org with two products applies twice."""

    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.PROTECT,
        related_name="products",
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    description = models.TextField(blank=True)

    objects = OrganisationScopedManager()  # type: ignore[misc]

    class Meta:
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "slug"],
                condition=models.Q(deleted=False),
                name="organisations_product_unique_organisation_slug",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Membership(BaseModel):
    organisation = models.ForeignKey(
        Organisation,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=MembershipRole.choices)

    class Meta:
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "user"],
                condition=models.Q(deleted=False),
                name="organisations_membership_unique_organisation_user",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=MembershipRole.values),
                name="organisations_membership_role_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.organisation} ({self.role})"
