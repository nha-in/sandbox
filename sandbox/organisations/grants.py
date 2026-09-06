"""Writing milestone grants.

Driven by the `milestone_declaration` submission and its bundled WASA
certification (plan 12 §6 D8), not by the production-access approval — that
decision is application-level and does not enumerate milestones. D8 has not
landed, so nothing calls this yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sandbox.organisations.models import Milestone
from sandbox.organisations.models import MilestoneGrant

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sandbox.experiences.models import ApplicationInstance


def record_milestone_grants(
    application: ApplicationInstance,
    milestones: Iterable[str],
) -> None:
    """Persist the milestones this application earned.

    `get_or_create`, because grants are additive and a resubmission must not
    move an earlier `granted_at`.
    """
    for milestone in milestones:
        if milestone not in Milestone.values:
            continue
        MilestoneGrant.objects.get_or_create(
            organisation=application.organisation,
            milestone=milestone,
            defaults={"granted_by": application},
        )
