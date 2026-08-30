"""Console reads: the queue, its counts, and the payload presented for humans."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db.models import Count
from django.db.models import Q

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas.sandbox import IntegrationIntent
from sandbox.applications.schemas.sandbox import PayerCategory
from sandbox.applications.schemas.sandbox import SolutionType

if TYPE_CHECKING:
    from django.db.models import QuerySet

PAGE_SIZE = 25

#: payload key -> (heading, the choices enum whose labels we render)
_PAYLOAD_CHOICES = {
    "solution_types": ("Solution types", SolutionType),
    "integration_intents": ("Integration intents", IntegrationIntent),
    "payer_categories": ("Payer categories", PayerCategory),
}


def _matching(search: str) -> QuerySet[Application]:
    """One definition of "matches the search", so the badges and the table can
    never disagree about how many results there are."""
    applications = Application.objects.all()
    if search:
        applications = applications.filter(
            Q(reference__icontains=search)
            | Q(product__organisation__name__icontains=search),
        )
    return applications


def queue(
    *,
    state: str = "",
    search: str = "",
    after: int | None = None,
) -> QuerySet[Application]:
    """Filtered console queue.

    Ordered by descending id rather than `created_date`: the seed and any bulk
    import create many rows inside one transaction, so timestamps tie and an
    ordering on them is not stable enough to paginate against.
    """
    applications = (
        _matching(search)
        .select_related(
            "product__organisation",
            "applicant",
        )
        .order_by("-id")
    )

    if state:
        applications = applications.filter(state=state)
    if after is not None:
        applications = applications.filter(id__lt=after)

    return applications


def state_counts(search: str = "") -> dict[str, int]:
    """Every state with its count, zeros included, in workflow order.

    Counts what the search is showing: a badge reading "Draft 1" next to a
    filtered table that has no drafts is worse than no badge at all.
    """
    counted = {
        row["state"]: row["total"]
        for row in _matching(search).values("state").annotate(total=Count("id"))
    }
    return {state: counted.get(state, 0) for state in ApplicationState.values}


#: states where the ball is in a reviewer's court. Deliberately not "everything
#: that is not finished": a SENT_BACK application is waiting on the integrator,
#: and counting it would have the console nag reviewers about work they cannot do.
AWAITING_REVIEW_STATES = (
    ApplicationState.SUBMITTED,
    ApplicationState.EXIT_REQUESTED,
    ApplicationState.EXIT_REVIEW,
)


def awaiting_review_count() -> int:
    """The sidebar badge. One query, ignoring any search or state filter — it
    reports the size of the reviewers' backlog, not of the view they happen to
    be looking at."""
    return Application.objects.filter(state__in=AWAITING_REVIEW_STATES).count()


def payload_groups(application: Application) -> list[dict[str, Any]]:
    """Payload as labelled groups — never a raw JSON dump on a reviewer's screen."""
    data = application.payload.get("data", {})
    groups: list[dict[str, Any]] = []

    for key, (heading, choices) in _PAYLOAD_CHOICES.items():
        values = data.get(key) or []
        labels = dict(choices.choices)
        groups.append(
            {
                "heading": heading,
                "values": [str(labels.get(value, value)) for value in values],
            },
        )

    narrative = data.get("use_case_narrative")
    if narrative:
        groups.append({"heading": "Use case", "values": [narrative]})
    return groups
