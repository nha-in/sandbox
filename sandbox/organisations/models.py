"""Tenancy: who acts for which company, and what that company actually certifies.

`Membership` is the join between identity (`users.User`) and tenancy
(`Organisation`); `Product` is what gets certified — one organisation can run
several products, each with its own applications and milestone track.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
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


class NatureOfEntity(models.TextChoices):
    """Legacy `natureOfEntity`. The SANDBOX form's list; the HCX form omits
    GOVERNMENT, so revisit when the HCX kind lands."""

    COMPANY = "COMPANY", _("Company")
    GOVERNMENT = "GOVERNMENT", _("Government")
    LLP = "LLP", _("LLP")
    PARTNERSHIP_FIRM = "PARTNERSHIP_FIRM", _("Partnership Firm")
    PROPRIETORSHIP_FIRM = "PROPRIETORSHIP_FIRM", _("Proprietorship Firm")
    SOCIETY = "SOCIETY", _("Society")
    TRUST = "TRUST", _("Trust")


class OrganisationOwnership(models.TextChoices):
    """Legacy `typeOfApplication`, shown as "Type of organization"."""

    GOVERNMENT = "GOVERNMENT", _("Government")
    PRIVATE = "PRIVATE", _("Private")


class OrganisationCategory(models.TextChoices):
    """Legacy `selectCategory`."""

    CENTRAL_GOVERNMENT_PROGRAM = (
        "CENTRAL_GOVERNMENT_PROGRAM",
        _("Central Government Program"),
    )
    CENTRAL_GOVERNMENT_ENTITY_TMS = (
        "CENTRAL_GOVERNMENT_ENTITY_TMS",
        _("Central Government Entity - TMS"),
    )
    DIAGNOSTIC_LABS = "DIAGNOSTIC_LABS", _("Diagnostic Labs")
    NCD_PROGRAMME_GOI = "NCD_PROGRAMME_GOI", _("For NCD Programme of GoI")
    GOVERNMENT_HEALTH_LOCKER = (
        "GOVERNMENT_HEALTH_LOCKER",
        _("Government Health Locker"),
    )
    GOVERNMENT_HMIS_SOLUTION_PROVIDER = (
        "GOVERNMENT_HMIS_SOLUTION_PROVIDER",
        _("Government HMIS Solution Provider"),
    )
    HEALTH_LOCKER = "HEALTH_LOCKER", _("Health Locker")
    HEALTHCARE_SOLUTION_PROVIDER = (
        "HEALTHCARE_SOLUTION_PROVIDER",
        _("Healthcare Solution Provider"),
    )
    HMIS = "HMIS", _("HMIS")
    INSURANCE = "INSURANCE", _("Insurance")
    PHARMACY = "PHARMACY", _("Pharmacy")
    PSU = "PSU", _("PSU")
    STATE_GOVERNMENT_PROGRAM = (
        "STATE_GOVERNMENT_PROGRAM",
        _("State Government Program"),
    )


gstin_validator = RegexValidator(
    regex=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$",
    message=_("Enter a valid 15-character GSTIN."),
)


class Organisation(BaseModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    kind = models.CharField(max_length=20, choices=OrganisationKind.choices)
    # collected by C4's wizard; blank on orgs created before that exists
    nature_of_entity = models.CharField(
        max_length=30,
        choices=NatureOfEntity.choices,
        blank=True,
        default="",
    )
    ownership = models.CharField(
        max_length=20,
        choices=OrganisationOwnership.choices,
        blank=True,
        default="",
    )
    category = models.CharField(
        max_length=40,
        choices=OrganisationCategory.choices,
        blank=True,
        default="",
    )
    gst_number = models.CharField(
        max_length=15,
        blank=True,
        default="",
        validators=[gstin_validator],
    )
    registered_in_india = models.BooleanField(null=True, blank=True, default=None)
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
            # "" is legal: these are optional until C4 collects them
            models.CheckConstraint(
                condition=models.Q(
                    nature_of_entity__in=[*NatureOfEntity.values, ""],
                ),
                name="organisations_organisation_nature_of_entity_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    ownership__in=[*OrganisationOwnership.values, ""],
                ),
                name="organisations_organisation_ownership_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    category__in=[*OrganisationCategory.values, ""],
                ),
                name="organisations_organisation_category_valid",
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
