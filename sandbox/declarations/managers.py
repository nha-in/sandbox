"""Org-scoped querysets — the tenant is several hops away, via the application."""

from __future__ import annotations

from django.db import models

from sandbox.organisations.managers import OrganisationScopedQuerySet
from sandbox.utils.models import SoftDeleteManagerMixin


class DeclarationQuerySet(OrganisationScopedQuerySet):
    organisation_lookup = "application__product__organisation"


class DeclarationManager(
    SoftDeleteManagerMixin,
    models.Manager.from_queryset(DeclarationQuerySet),  # type: ignore[misc]
):
    """`objects` for Declaration — soft delete plus `.for_organisation()`."""


class DeclarationDocumentQuerySet(OrganisationScopedQuerySet):
    organisation_lookup = "declaration__application__product__organisation"


class DeclarationDocumentManager(
    SoftDeleteManagerMixin,
    models.Manager.from_queryset(DeclarationDocumentQuerySet),  # type: ignore[misc]
):
    """`objects` for DeclarationDocument — scoping is what gates downloads."""
