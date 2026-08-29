"""`transition()` — the only code allowed to change an application's state.

Everything downstream (console buttons, the provisioning chain, the exit flow)
routes through here, so an application can never move off the books. The legacy
equivalent was an 849-line service writing magic integers through native SQL
with swallow-all catches and no audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django.db import transaction

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.audit.services import emit
from sandbox.utils.errors import DomainError
from sandbox.workflow.machine import PERM_REVIEW
from sandbox.workflow.machine import TRANSITIONS
from sandbox.workflow.machine import Action
from sandbox.workflow.machine import ActorKind
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.models import WorkflowReview
from sandbox.workflow.models import WorkflowTransition
from sandbox.workflow.selectors import current_round

if TYPE_CHECKING:
    from collections.abc import Callable

    from sandbox.users.models import User

#: hook name -> callable(application, transition). B7/B8 register theirs at
#: app-ready time; an unregistered name is a no-op so A5 can ship before them.
_HOOKS: dict[str, Callable[[Application, WorkflowTransition], None]] = {}


def register_hook(
    name: str,
    handler: Callable[[Application, WorkflowTransition], None],
) -> None:
    _HOOKS[name] = handler


def clear_hooks() -> None:
    """For tests — never call this from application code."""
    _HOOKS.clear()


def _check_actor(spec_kind: ActorKind, actor: User | None, action: Action) -> None:
    if spec_kind is ActorKind.SYSTEM:
        if actor is not None:
            message = f"{action} is a system move and cannot carry an actor"
            raise DomainError(message, code="forbidden")
        return

    if actor is None:
        message = f"{action} requires an actor"
        raise DomainError(message, code="forbidden")


def _check_owner(application: Application, actor: User) -> None:
    """Owner moves belong to the applicant's organisation, not to any member."""
    organisation_id = application.product.organisation_id
    is_member = actor.memberships.filter(organisation_id=organisation_id).exists()
    if not is_member:
        message = "actor is not a member of the owning organisation"
        raise DomainError(message, code="forbidden")


@transaction.atomic
def transition(
    *,
    application: Application,
    action: Action,
    actor: User | None = None,
    comment: str = "",
    data: dict[str, Any] | None = None,
) -> WorkflowTransition:
    """Move `application` by `action`, atomically and audibly.

    `comment` is only for moves with no review behind them (withdrawal, system
    notes); a review-driven action's text is single-homed on A6's review row.

    Raises `DomainError` for an illegal move, a wrong actor kind, a
    non-member owner move, a missing permission, or a comment on a
    review-driven action. Side-effect hooks run only after the transaction
    commits.
    """
    # Locked re-read: two reviewers clicking Approve must not both succeed.
    locked = Application.objects.select_for_update().get(pk=application.pk)
    from_state = ApplicationState(locked.state)

    spec = TRANSITIONS.get((from_state, action))
    if spec is None:
        message = f"{action} is not legal from {from_state}"
        raise DomainError(message, code="illegal_transition")

    _check_actor(spec.actor_kind, actor, action)

    if spec.actor_kind is ActorKind.OWNER and actor is not None:
        _check_owner(locked, actor)

    if spec.permission and (actor is None or not actor.has_perm(spec.permission)):
        message = f"{action} requires {spec.permission}"
        raise DomainError(message, code="forbidden")

    if spec.review_driven and comment:
        message = (
            f"{action} is review-driven; its comment belongs on the review row, "
            "not on the transition"
        )
        raise DomainError(message, code="comment_not_allowed")

    record = WorkflowTransition.objects.create(
        application=locked,
        from_state=from_state,
        to_state=spec.to_state,
        action=action,
        actor=actor,
        comment=comment,
    )

    locked.state = spec.to_state
    locked.save(update_fields=["state", "modified_date"])
    application.state = spec.to_state

    emit(
        f"application.{action.lower()}",
        obj=locked,
        actor=actor,
        data={
            "from_state": from_state.value,
            "to_state": spec.to_state.value,
            "reference": locked.reference,
            **(data or {}),
        },
    )

    for hook_name in spec.hooks:
        handler = _HOOKS.get(hook_name)
        if handler is not None:
            transaction.on_commit(
                lambda handler=handler: handler(locked, record),  # type: ignore[misc]
            )

    return record


@transaction.atomic
def record_review(
    *,
    application: Application,
    reviewer: User,
    decision: str,
    comment: str = "",
) -> WorkflowReview:
    """Record a reviewer's opinion. Advisory — this never moves the application.

    Re-reviewing within the same round updates that reviewer's row; a send-back
    opens a new round, leaving the previous one readable.
    """
    if application.state != ApplicationState.SUBMITTED:
        message = f"cannot review an application in state {application.state}"
        raise DomainError(message, code="illegal_review")

    if decision not in ReviewDecision.values:
        message = f"{decision} is not a review decision"
        raise DomainError(message, code="invalid")

    if not reviewer.has_perm(PERM_REVIEW):
        message = f"recording a review requires {PERM_REVIEW}"
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
