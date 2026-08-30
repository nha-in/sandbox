"""Read-only queries over declarations.

Two shapes, because the UI asks two different questions: "where does this
application stand right now" (current claims only) and "what has been submitted
over time" (everything, supersession included).

Wrong-org lookups 404 rather than 403 — a 403 confirms the record exists (A2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.http import Http404

from sandbox.declarations.models import Declaration
from sandbox.declarations.models import DeclarationDocument
from sandbox.declarations.models import DeclarationKind
from sandbox.declarations.models import DeclarationMilestone
from sandbox.declarations.models import DeclarationState

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet

    from sandbox.applications.models import Application
    from sandbox.organisations.models import Organisation


def milestone_coverage(application: Application) -> QuerySet[DeclarationMilestone]:
    """The current claim on each milestone — one row per (kind, milestone).

    The milestones page walks `catalog.active_milestones()` against this: a
    milestone missing from the result has never been declared. Read
    `declaration.state` for the rest — a claim held by a REJECTED declaration
    is still the current one until the integrator resubmits.
    """
    return (
        DeclarationMilestone.objects.filter(
            application=application,
            superseded_by__isnull=True,
        )
        .select_related("milestone", "declaration")
        .order_by("milestone__track", "milestone__order")
    )


def declaration_timeline(application: Application) -> QuerySet[Declaration]:
    """Every declaration ever made, newest first.

    No supersession filter on purpose: superseded claims are marked, not
    hidden, so a rejected bundle stays readable alongside what replaced it.
    """
    return (
        Declaration.objects.filter(application=application)
        .select_related("declared_by")
        .prefetch_related(
            "milestones__milestone",
            "milestones__superseded_by",
            "documents",
        )
    )


def declarations_for_organisation(
    organisation: Organisation,
) -> QuerySet[Declaration]:
    return Declaration.objects.for_organisation(organisation).select_related(
        "application",
    )


def current_exit_declaration(application: Application) -> Declaration | None:
    """The exit bundle awaiting an outcome, if there is one.

    Both filters earn their place. `state` excludes a settled bundle — a
    rejection releases no claims, so a rejected declaration still holds live
    ones until the replacement supersedes them, and without this it could be
    re-requested unchanged. `superseded_by` excludes a bundle that was replaced
    before it was ever reviewed, which is still SUBMITTED.
    """
    return (
        Declaration.objects.filter(
            application=application,
            kind=DeclarationKind.EXIT,
            state=DeclarationState.SUBMITTED,
            milestones__superseded_by__isnull=True,
        )
        .prefetch_related("milestones__milestone", "documents")
        .distinct()
        .first()
    )


def undeclared_exit_milestones(declaration: Declaration) -> list[str]:
    """Milestone keys the exit covers that were never declared complete.

    A8's `request_exit` guard: you cannot take M2 to production without having
    declared M2 done, but exiting M1 does not oblige you to declare M3.
    """
    covered = {claim.milestone_id for claim in declaration.milestones.all()}
    declared = set(
        DeclarationMilestone.objects.filter(
            application_id=declaration.application_id,
            kind=DeclarationKind.MILESTONE,
            milestone_id__in=covered,
        ).values_list("milestone_id", flat=True),
    )
    missing = covered - declared
    return sorted(
        claim.milestone.key
        for claim in declaration.milestones.all()
        if claim.milestone_id in missing
    )


def document_detail(
    organisation: Organisation,
    external_id: UUID | str,
) -> DeclarationDocument:
    """The download view's only lookup — scoping is the whole authorization."""
    document = (
        DeclarationDocument.objects.for_organisation(organisation)
        .filter(external_id=external_id)
        .first()
    )
    if document is None:
        raise Http404
    return document
