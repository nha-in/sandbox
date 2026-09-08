from __future__ import annotations

from django.db.models import Count
from django.db.models import Q

from .models import ApplicationEvent
from .models import ApplicationInstance
from .models import QueryStatus
from .registry import registry

PENDING_QUERY_STATUSES = (
    QueryStatus.AWAITING_APPLICANT,
    QueryStatus.AWAITING_REVIEWER,
)


def applications_for_user(user):
    return ApplicationInstance.objects.visible_to(user).with_workspace_data()


def filter_applications(queryset, selected: dict[str, str]):
    queryset = queryset.annotate(
        open_query_count=Count(
            "query_threads",
            filter=Q(query_threads__status__in=PENDING_QUERY_STATUSES),
            distinct=True,
        ),
    )
    if status := selected.get("status"):
        queryset = queryset.filter(status=status)
    if application_type := selected.get("application_type"):
        queryset = queryset.filter(application_type=application_type)
    if query := selected.get("q"):
        queryset = queryset.filter(
            Q(reference__icontains=query)
            | Q(title__icontains=query)
            | Q(organisation__name__icontains=query)
            | Q(product__name__icontains=query),
        )
    if selected.get("query_state") == "pending":
        queryset = queryset.filter(open_query_count__gt=0)
    elif selected.get("query_state") == "clear":
        queryset = queryset.filter(open_query_count=0)
    return queryset


def decorate_applications(applications) -> None:
    """Attach each row's definition and status definition for display."""
    for application in applications:
        application.definition = registry.get(application.application_type)
        application.status_definition = application.definition.get_status(
            application.status,
        )


def application_summary(user, organisation) -> dict[str, int]:
    """The counts the list header and the dashboard both show.

    One source, because two that drift are worse than neither: the dashboard
    saying nothing is in review while the list shows two is a bug nobody
    reports and everybody stops trusting.
    """
    base = ApplicationInstance.objects.visible_to(user).filter(
        organisation=organisation,
    )
    return {
        "total_count": base.count(),
        "in_review_count": base.filter(
            status__in=["submitted", "under_review", "revision_submitted"],
        ).count(),
        "query_count": base.filter(
            query_threads__status__in=PENDING_QUERY_STATUSES,
        )
        .distinct()
        .count(),
        "approved_count": base.filter(status="approved").count(),
    }


def dashboard_applications(user, organisation, limit: int = 3):
    """The most recently touched applications, decorated for display.

    Ordered by `updated_at` rather than status: the one you were last working
    on is the one you came back for.
    """
    applications = list(
        filter_applications(
            applications_for_user(user).filter(organisation=organisation),
            {},
        ).order_by("-updated_at", "-pk")[:limit],
    )
    decorate_applications(applications)
    return applications


def dashboard_activity(user, organisation, limit: int = 6):
    """What has happened across this organisation's applications.

    `is_internal` events are the review team's own notes and never appear —
    the flag exists precisely because one internal note of an otherwise public
    kind has to be hideable (§4.2).
    """
    visible = ApplicationInstance.objects.visible_to(user).filter(
        organisation=organisation,
    )
    return list(
        ApplicationEvent.objects.filter(
            application__in=visible,
            is_internal=False,
        ).select_related("application", "actor")[:limit],
    )


def startable_definitions(organisation):
    """Types this organisation may open now.

    A milestone exit is reachable only from the sandbox access it is about
    (§1.2), so it never appears here — offering it as a top-level start gave a
    page that opened and a submit that 403'd.
    """
    return [
        definition
        for definition in registry.all()
        if not definition.started_from_predecessor
        and definition.can_start(organisation)[0]
    ]
