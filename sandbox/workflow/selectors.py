"""Workflow reads. Never writes — see `services.transition()`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.applications.models import Application
from sandbox.workflow.machine import TRANSITIONS
from sandbox.workflow.machine import Action
from sandbox.workflow.machine import ActorKind
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
