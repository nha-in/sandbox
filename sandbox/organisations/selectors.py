from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .models import MILESTONE_PREREQUISITES
from .models import Membership
from .models import Milestone
from .models import MilestoneGrant

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from django_stubs_ext import StrOrPromise


def get_membership_for(user) -> Membership | None:
    """The user's single membership, or None.

    One organisation per user today (the signup form creates it), so this
    returns the first membership rather than asking callers to pick one. The
    Membership model already supports many members per organisation, so adding
    an organisation switcher later only changes this function's contract.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        Membership.objects.filter(user=user)
        .select_related("organisation", "user")
        .first()
    )


def get_organisation_for(user):
    membership = get_membership_for(user)
    return membership.organisation if membership else None


def granted_milestones(organisation) -> frozenset[str]:
    """Every milestone this organisation holds, across all its applications."""
    return frozenset(
        MilestoneGrant.objects.filter(
            organisation=organisation,
        ).values_list("milestone", flat=True),
    )


def unmet_prerequisites(
    organisation,
    milestone: str,
    *,
    also_granting: Iterable[str] = (),
) -> tuple[str, ...]:
    """Which of `milestone`'s prerequisites are neither held nor being granted.

    `also_granting` is the rest of the same approval — approving M1 through M4
    at once is legal, and checking each against stored grants alone would
    reject it.
    """
    available = granted_milestones(organisation) | frozenset(also_granting)
    return tuple(
        prerequisite
        for prerequisite in MILESTONE_PREREQUISITES[milestone]
        if prerequisite not in available
    )


@dataclass(frozen=True, slots=True)
class MilestoneProgress:
    milestone: str
    label: StrOrPromise
    granted: bool
    granted_at: datetime | None
    #: Prerequisites this organisation does not hold yet. Only M4 owes any
    #: (§3.1), and naming them beats a locked row that will not say why.
    blocked_by: tuple[str, ...]


def milestone_progress(organisation) -> list[MilestoneProgress]:
    """All four milestones in order, held or not.

    Every one is listed rather than only the held ones: "we have not been
    granted M4" and "there is no M4" look identical if you render only what
    exists, and the first is where every integrator starts.
    """
    grants = {
        grant.milestone: grant
        for grant in MilestoneGrant.objects.filter(organisation=organisation)
    }
    return [
        MilestoneProgress(
            milestone=milestone.value,
            label=milestone.label,
            granted=milestone.value in grants,
            granted_at=(
                grants[milestone.value].granted_at
                if milestone.value in grants
                else None
            ),
            blocked_by=(
                ()
                if milestone.value in grants
                else unmet_prerequisites(organisation, milestone.value)
            ),
        )
        for milestone in Milestone
    ]
