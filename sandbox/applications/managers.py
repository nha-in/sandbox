"""Org-scoped queryset for Application — the tenant is reached via `product`."""

from __future__ import annotations

from django.db import models

from sandbox.organisations.managers import OrganisationScopedQuerySet
from sandbox.utils.models import SoftDeleteManagerMixin


class ApplicationQuerySet(OrganisationScopedQuerySet):
    organisation_lookup = "product__organisation"


class ApplicationManager(
    SoftDeleteManagerMixin,
    models.Manager.from_queryset(ApplicationQuerySet),  # type: ignore[misc]
):
    """`objects` for Application — soft delete plus `.for_organisation()`."""
