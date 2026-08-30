"""Workflow reads. Never writes — see `services.transition()`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.workflow.machine import TRANSITIONS
from sandbox.workflow.machine import Action
from sandbox.workflow.machine import ActorKind
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from sandbox.users.models import User


def history_for(application: Application) -> QuerySet[WorkflowTransition]:
    """Newest first, for the application detail timeline (C5/C6)."""
    return WorkflowTransition.objects.filter(application=application).select_related(
        "actor",
    )


def queue_by_state(state: str) -> QuerySet[Application]:
    """Console queue backing selector (C5)."""
    return Application.objects.filter(state=state).select_related(
        "product__organisation",
        "applicant",
    )


#: everything sitting in the exit half of the journey, for C5's queue filter
EXIT_QUEUE_STATES = (
    ApplicationState.EXIT_REQUESTED,
    ApplicationState.EXIT_REVIEW,
)


def exit_queue() -> QuerySet[Application]:
    """Applications awaiting an exit decision, oldest request first.

    Oldest first because this is a work queue, unlike the review queue's
    newest-first browse.
    """
    return (
        Application.objects.filter(state__in=EXIT_QUEUE_STATES)
        .select_related("product__organisation", "applicant")
        .order_by("created_date")
    )


def available_actions(
    application: Application,
    actor: User | None,
) -> tuple[Action, ...]:
    """Which buttons this actor may actually press — the console renders these.

    Deriving the buttons from the same table `transition()` enforces means a
    screen cannot offer a move the service will refuse.
    """
    allowed = []
    for (from_state, action), spec in TRANSITIONS.items():
        if from_state != application.state or spec.actor_kind is ActorKind.SYSTEM:
            continue
        if actor is None:
            continue
        if spec.permission and not actor.has_perm(spec.permission):
            continue
        if (
            spec.actor_kind is ActorKind.OWNER
            and not actor.memberships.filter(
                organisation_id=application.product.organisation_id,
            ).exists()
        ):
            continue
        allowed.append(action)
    return tuple(allowed)


#: Decisions that hand the application back to the integrator, ending a round.
#: `REJECT` is absent because it is terminal on the sandbox side; `REJECT_EXIT`
#: is present because EXIT_REJECTED can request exit again.
_ROUND_ENDING_ACTIONS = (
    Action.SEND_BACK,
    Action.SEND_BACK_EXIT,
    Action.REJECT_EXIT,
)


def current_round(application: Application) -> int:
    """Round N = one more than the bounces so far.

    Derived from the append-only transition log rather than stored on the
    application: there is then no counter that can disagree with the history.
    """
    bounces = WorkflowTransition.objects.filter(
        application=application,
        action__in=_ROUND_ENDING_ACTIONS,
    ).count()
    return bounces + 1


#: The opinion each decision expresses. Exit decisions reuse the same three
#: values rather than growing `ReviewDecision`: a reject is a reject, and the
#: transition log already records which half of the journey it happened in.
REVIEW_DECISION_FOR_ACTION: dict[Action, str] = {
    Action.APPROVE: ReviewDecision.APPROVE,
    Action.REJECT: ReviewDecision.REJECT,
    Action.SEND_BACK: ReviewDecision.SEND_BACK,
    Action.APPROVE_EXIT: ReviewDecision.APPROVE,
    Action.REJECT_EXIT: ReviewDecision.REJECT,
    Action.SEND_BACK_EXIT: ReviewDecision.SEND_BACK,
}


def reviews_for_round(
    application: Application,
    round_number: int | None = None,
) -> QuerySet[WorkflowReview]:
    """Opinions recorded in one round; the current round by default."""
    if round_number is None:
        round_number = current_round(application)
    return WorkflowReview.objects.filter(
        application=application,
        round=round_number,
    ).select_related("reviewer")


def review_tally(
    application: Application,
    round_number: int | None = None,
) -> dict[str, int]:
    """Counts per decision for the console's tally beside the approve button.

    Advisory only: A6 deliberately has no quorum rule, so this informs the admin
    rather than gating them.
    """
    tally = dict.fromkeys(ReviewDecision.values, 0)
    for row in reviews_for_round(application, round_number).values_list(
        "decision",
        flat=True,
    ):
        tally[row] += 1
    return tally
