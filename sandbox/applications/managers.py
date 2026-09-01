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


class FormSubmissionQuerySet(OrganisationScopedQuerySet):
    organisation_lookup = "application__product__organisation"


class FormSubmissionManager(
    models.Manager.from_queryset(FormSubmissionQuerySet),  # type: ignore[misc]
):
    """`objects` for ApplicationFormSubmission — append-only, no soft delete."""


class ApplicationDocumentQuerySet(OrganisationScopedQuerySet):
    organisation_lookup = "submission__application__product__organisation"


class ApplicationDocumentManager(
    SoftDeleteManagerMixin,
    models.Manager.from_queryset(ApplicationDocumentQuerySet),  # type: ignore[misc]
):
    """`objects` for ApplicationDocument — scoping is what gates downloads."""
