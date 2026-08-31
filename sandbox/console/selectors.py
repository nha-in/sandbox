"""Console reads: the queue, its counts, and the payload presented for humans."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db.models import Count
from django.db.models import Q

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import current_form_data
from sandbox.applications.selectors import exit_documents
from sandbox.programmes import abdm
from sandbox.workflow.registry import get_workflow

if TYPE_CHECKING:
    from django.db.models import QuerySet

PAGE_SIZE = 25


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
    # exits are their own applications, with their own reviewable state
    "UNDER_REVIEW",
)


def awaiting_review_count() -> int:
    """The sidebar badge. One query, ignoring any search or state filter — it
    reports the size of the reviewers' backlog, not of the view they happen to
    be looking at."""
    return Application.objects.filter(state__in=AWAITING_REVIEW_STATES).count()


def payload_groups(application: Application) -> list[dict[str, Any]]:
    """Registration as labelled groups — never a raw JSON dump on a reviewer's
    screen, and never a bare code: `['EUA']` is not an answer.

    Headings and labels come from the form the applicant actually filled in, so
    a field added to the programme shows up here without a second list to edit.
    """
    data = current_form_data(application, "REGISTRATION")
    if not data:
        return []

    form = get_workflow(application.workflow_key).form("REGISTRATION").form_class()
    groups: list[dict[str, Any]] = []
    for name, field in form.fields.items():
        value = data.get(name)
        if value in (None, "", []):
            continue
        labels = dict(getattr(field, "choices", []) or [])
        values = value if isinstance(value, list | tuple) else [value]
        groups.append(
            {
                "heading": str(field.label or name),
                "values": [str(labels.get(item, item)) for item in values],
            },
        )
    return groups


def registered_solution_types(exit_application: Application) -> list[tuple[str, str]]:
    """The admin's ceiling: only what the applicant selected may be approved.

    Read at decision time from the product's sandbox application, so widening
    the registration later grants nothing until the next exit is decided (§10).
    """
    sandbox = (
        Application.objects.filter(
            product_id=exit_application.product_id,
            workflow_key="ABDM",
            deleted=False,
        )
        .order_by("-created_date")
        .first()
    )
    if sandbox is None:
        return []
    selected = current_form_data(sandbox, "REGISTRATION").get("solution_types", [])
    labels = dict(abdm.RegistrationSolutionType.choices)
    eligible = abdm.dhis_solution_types(selected)
    return [
        (solution_type.value, str(labels.get(solution_type.value, solution_type.value)))
        for solution_type in sorted(eligible)
    ]


def exit_review(exit_application: Application) -> dict[str, Any]:
    """What the reviewer decides on: the claim, the WASA, and the evidence."""
    claim = current_form_data(exit_application, "EXIT_CLAIM")
    return {
        "covers": claim.get("covers", []),
        "summary": claim.get("summary", ""),
        "wasa": current_form_data(exit_application, "WASA"),
        "documents": exit_documents(exit_application),
        "decision_form": abdm.ExitDecisionForm(
            registered_choices=registered_solution_types(exit_application),
        ),
    }
