"""Reviews — a reviewer's opinion, recorded alongside the work it judges.

Deliberately not a write path for `Application.state`: a review is advisory and
never moves anything. `workflow.engine` is the only code that moves an
application, which is what stops a screen inventing a transition of its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

from sandbox.audit.services import emit
from sandbox.utils.errors import DomainError
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.registry import get_workflow
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import is_reviewable

if TYPE_CHECKING:
    from sandbox.applications.models import Application
    from sandbox.users.models import User


@transaction.atomic
def record_review(
    *,
    application: Application,
    reviewer: User,
    decision: str,
    comment: str = "",
) -> WorkflowReview:
    """Record a reviewer's opinion. Advisory — this never moves the application.

    Re-reviewing within the same round updates that reviewer's row; the round
    turns over when the applicant resubmits, leaving the previous one readable.
    """
    if not is_reviewable(application):
        message = f"cannot review an application in state {application.state}"
        raise DomainError(message, code="illegal_review")

    if decision not in ReviewDecision.values:
        message = f"{decision} is not a review decision"
        raise DomainError(message, code="invalid")

    if not reviewer.has_perm(get_workflow(application.workflow_key).review_permission):
        message = "recording a review requires the programme's review permission"
        raise DomainError(message, code="forbidden")

    review, _created = WorkflowReview.objects.update_or_create(
        application=application,
        reviewer=reviewer,
        round=current_round(application),
        defaults={"decision": decision, "comment": comment},
    )

    emit(
        "application.reviewed",
        obj=application,
        actor=reviewer,
        data={
            "decision": decision,
            "round": review.round,
            "reference": application.reference,
        },
    )
    return review
