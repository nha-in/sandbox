"""Read-only queries over Application.

Wrong-org lookups 404 rather than 403 — a 403 confirms the record exists (A2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import NON_BLOCKING_STATES
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.organisations.models import Product

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet
    from django_stubs_ext import StrOrPromise

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
    keep: Product | None = None,
) -> QuerySet[Product]:
    """C4's product picker: offering a product that already has a live
    application of this kind would trip the partial-unique constraint.

    `keep` is the product the draft being edited already holds. Its own
    application is what makes it unavailable, so without this the applicant
    stepping back from the details step cannot see the product they just named.
    """
    taken = (
        Application.objects.filter(kind=kind)
        .exclude(state__in=NON_BLOCKING_STATES)
        .values("product_id")
    )
    available = Product.objects.for_organisation(organisation).exclude(pk__in=taken)
    if keep is None:
        return available
    return Product.objects.for_organisation(organisation).filter(
        Q(pk__in=available) | Q(pk=keep.pk),
    )


@dataclass(frozen=True, slots=True)
class JourneyStep:
    key: str
    label: str
    status: str  # done | current | upcoming


JOURNEY_LABELS: tuple[tuple[str, StrOrPromise], ...] = (
    ("apply", _("Apply")),
    ("verify", _("Verify")),
    ("review", _("Review")),
    ("credentials", _("Credentials")),
    ("milestones", _("Milestones")),
    ("exit", _("Exit")),
    ("production", _("Production")),
)

S = ApplicationState

STATE_STEP: dict[str, str] = {
    S.DRAFT: "apply",
    S.SUBMITTED: "review",
    S.SANDBOX_APPROVED: "credentials",
    S.PROVISIONING: "credentials",
    S.PROVISIONING_FAILED: "credentials",
    S.PROVISIONED: "credentials",
    S.EXIT_REQUESTED: "exit",
    S.EXIT_REVIEW: "exit",
    S.PRODUCTION_APPROVED: "production",
}

EDGE_STATES = frozenset(
    {S.REJECTED, S.SENT_BACK, S.WITHDRAWN, S.EXIT_REJECTED},
)

PENDING_STATES = frozenset({S.SUBMITTED, S.PROVISIONING})


def journey_for(state: str) -> list[JourneyStep]:
    """The track with each step marked done, current or upcoming.

    Edge states have no position, so every step reads as upcoming and the
    template shows a banner rather than a stepper.
    """
    current = STATE_STEP.get(state, "")
    keys = [key for key, _label in JOURNEY_LABELS]
    current_index = keys.index(current) if current else -1
    steps = []
    for index, (key, label) in enumerate(JOURNEY_LABELS):
        if current_index < 0:
            status = "upcoming"
        elif index < current_index:
            status = "done"
        elif index == current_index:
            status = "current"
        else:
            status = "upcoming"
        steps.append(JourneyStep(key=key, label=str(label), status=status))
    return steps
