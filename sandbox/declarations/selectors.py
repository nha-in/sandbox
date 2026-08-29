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
from sandbox.declarations.models import DeclarationMilestone

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
