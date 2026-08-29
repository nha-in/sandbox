"""Org-scoping queryset — the authz backbone every org-owned model reuses.

Filtering by organisation is the only thing standing between "your data" and
"someone else's data"; centralizing it here means every future app (A3/A7)
gets the same behavior by pointing `organisation_lookup` at its own path to
the tenant, rather than each app hand-rolling its own `.filter(...)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Self

from django.db import models

from sandbox.utils.models import BaseQuerySet
from sandbox.utils.models import SoftDeleteManagerMixin

if TYPE_CHECKING:
    from sandbox.organisations.models import Organisation


class OrganisationScopedQuerySet(BaseQuerySet):
    #: path from this model to its owning Organisation, Django lookup syntax
    #: (e.g. "organisation" for a direct FK, "product__organisation" for A3)
    organisation_lookup: str = "organisation"

    def for_organisation(self, organisation: Organisation) -> Self:
        return self.filter(**{self.organisation_lookup: organisation})


class OrganisationScopedManager(
    SoftDeleteManagerMixin,
    models.Manager.from_queryset(OrganisationScopedQuerySet),  # type: ignore[misc]
):
    """`objects` for org-owned models — soft delete plus `.for_organisation()`."""
