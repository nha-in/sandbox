"""Read-only queries over Application.

Wrong-org lookups 404 rather than 403 — a 403 confirms the record exists (A2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import Http404

from sandbox.applications.models import NON_BLOCKING_STATES
from sandbox.applications.models import Application
from sandbox.organisations.models import Product

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet

    from sandbox.organisations.models import Organisation


def applications_for_organisation(organisation: Organisation) -> QuerySet[Application]:
    return Application.objects.for_organisation(organisation).select_related(
        "product",
        "applicant",
    )


def application_detail(
    organisation: Organisation,
    external_id: UUID | str,
) -> Application:
    application = (
        applications_for_organisation(organisation)
        .filter(
            external_id=external_id,
        )
        .first()
    )
    if application is None:
        raise Http404
    return application


def console_queue(
    *,
    kind: str | None = None,
    state: str | None = None,
) -> QuerySet[Application]:
    queryset = Application.objects.select_related(
        "product",
        "product__organisation",
        "applicant",
    )
    if kind:
        queryset = queryset.filter(kind=kind)
    if state:
        queryset = queryset.filter(state=state)
    return queryset.order_by("-created_date")


def products_available_for(
    organisation: Organisation,
    kind: str,
) -> QuerySet[Product]:
    """C4's product picker: offering a product that already has a live
    application of this kind would trip the partial-unique constraint."""
    taken = (
        Application.objects.filter(kind=kind)
        .exclude(state__in=NON_BLOCKING_STATES)
        .values("product_id")
    )
    return Product.objects.for_organisation(organisation).exclude(pk__in=taken)
