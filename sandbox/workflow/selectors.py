"""Workflow reads. Never writes — see `services.transition()`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.applications.models import Application
from sandbox.workflow.definitions import ActorKind as EngineActor
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition
from sandbox.workflow.registry import get_workflow

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
EXIT_QUEUE_STATES = ()


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


def is_reviewable(application: Application) -> bool:
    """A state is reviewable if a review-driven decision can be taken from it.

    Asked of the workflow rather than a list, so an application on a workflow
    this module knows nothing about is not silently unreviewable. The console
    reads it too — a screen that offered a review the service refuses is how
    "cannot review an application in state SUBMITTED" reached a reviewer.
    """
    try:
        workflow = get_workflow(application.workflow_key)
    except LookupError:
        return False
    return any(
        spec.review_driven
        for (state, _action), spec in workflow.transitions.items()
        if state == application.state
    )


def decidable_actions(
    application: Application,
    actor: User | None,
) -> tuple[str, ...]:
    """Which buttons this actor may actually press — the console renders these.

    Read from the same workflow the engine enforces, so a screen cannot offer a
    move the write path will refuse.
    """
    if actor is None:
        return ()
    workflow = get_workflow(application.workflow_key)
    allowed = []
    for (from_state, action), spec in workflow.transitions.items():
        if from_state != application.state or spec.actor_kind is EngineActor.SYSTEM:
            continue
        if spec.permission and not actor.has_perm(spec.permission):
            continue
        if (
            spec.actor_kind is EngineActor.OWNER
            and not actor.memberships.filter(
                organisation_id=application.product.organisation_id,
            ).exists()
        ):
            continue
        allowed.append(action)
    return tuple(sorted(allowed))


def current_round(application: Application) -> int:
    """Round N = the applicant's Nth attempt.

    A round starts when the applicant submits and ends when a decision lands on
    it, so a reviewer's verdict is filed with the work it judged. The counter
    therefore advances on resubmission, not on the send-back: between the two
    the application is still on the round whose comments it has to answer.
    """
    return application.round


#: The opinion each decision expresses. Both workflows use the same three
#: action names; the transition log records which one it happened on.
REVIEW_DECISION_FOR_ACTION: dict[str, str] = {
    "APPROVE": ReviewDecision.APPROVE,
    "REJECT": ReviewDecision.REJECT,
    "SEND_BACK": ReviewDecision.SEND_BACK,
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


def deciding_reviews(application: Application) -> QuerySet[WorkflowReview]:
    """The opinions behind where the application now stands.

    Sending back or rejecting opens the next round, so the reviews that caused
    it belong to the round that has just closed — asking for the current one
    returns nothing, which is how the applicant came to be told to address
    comments that were never shown.

    Read as "the latest round that carried reviews" rather than `round - 1`, so
    it stays right for an application still being reviewed in its own round.
    """
    latest = (
        WorkflowReview.objects.filter(application=application)
        .order_by("-round")
        .values_list("round", flat=True)
        .first()
    )
    if latest is None:
        return WorkflowReview.objects.none()
    return reviews_for_round(application, latest)


def latest_send_back_comment(application: Application) -> str:
    """What the applicant has to answer, in the reviewer's own words.

    Read from the review row, not the transition: `SEND_BACK` is review-driven,
    and the engine refuses a comment on a review-driven transition so the text
    has exactly one home.
    """
    review = (
        deciding_reviews(application)
        .filter(decision=ReviewDecision.SEND_BACK)
        .exclude(comment="")
        .first()
    )
    return review.comment if review else ""


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
