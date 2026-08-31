"""Read-only queries over Application.

Wrong-org lookups 404 rather than 403 — a 403 confirms the record exists (A2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from django.db.models import Q
from django.http import Http404
from django.utils.translation import gettext_lazy as _

from sandbox.applications.models import RESTING_STATES
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.applications.models import ApplicationState
from sandbox.organisations.models import Product
from sandbox.programmes import abdm
from sandbox.workflow.registry import get_workflow

if TYPE_CHECKING:
    from uuid import UUID

    from django.db.models import QuerySet
    from django_stubs_ext import StrOrPromise

    from sandbox.organisations.models import Organisation


def current_submission(
    application: Application,
    form_key: str,
) -> ApplicationFormSubmission | None:
    return application.submissions.filter(form_key=form_key, is_current=True).first()


def current_form_data(application: Application, form_key: str) -> dict:
    """The answers as last saved, or an empty form if never filled in."""
    submission = current_submission(application, form_key)
    return dict(submission.data) if submission else {}


@dataclass(frozen=True, slots=True)
class MilestoneRow:
    """One milestone as the milestones screen needs it."""

    key: str
    form_key: str
    title: StrOrPromise
    claim: ApplicationFormSubmission | None
    unlocked: bool
    blocked_by: tuple[StrOrPromise, ...]

    @property
    def declared(self) -> bool:
        return self.claim is not None


def milestone_rows(application: Application) -> list[MilestoneRow]:
    """Every milestone the programme defines, with the claim that stands on it.

    Offered milestones are gated by the prerequisite DAG alone. The
    solution-type matrix governs DHIS eligibility, never what you may declare:
    an EUA-only integrator still builds M1.
    """
    # Deferred: the engine imports models, which need the app registry ready.
    from sandbox.workflow.engine import ApplicationContext  # noqa: PLC0415

    workflow = get_workflow(application.workflow_key)
    context = ApplicationContext(application)
    submissions = {
        submission.form_key: submission
        for submission in application.submissions.filter(is_current=True)
    }
    rows = []
    for definition in workflow.forms:
        if not definition.key.startswith("MILESTONE_"):
            continue
        blocked_by = tuple(
            workflow.form(key).label
            for key in definition.depends_on
            if not context.has_current(key)
        )
        rows.append(
            MilestoneRow(
                key=definition.key.removeprefix("MILESTONE_").lower(),
                form_key=definition.key,
                title=definition.label,
                claim=submissions.get(definition.key),
                unlocked=definition.is_unlocked(context),
                blocked_by=blocked_by,
            ),
        )
    return rows


def milestone_progress(application: Application) -> dict[str, Any]:
    """Declared-of-total plus what is still outstanding, for the dashboard."""
    rows = milestone_rows(application)
    return {
        "declared": sum(1 for row in rows if row.declared),
        "total": len(rows),
        "next": [row.title for row in rows if not row.declared and row.unlocked][:3],
    }


def applications_for_organisation(organisation: Organisation) -> QuerySet[Application]:
    return Application.objects.for_organisation(organisation).select_related(
        "product",
        "applicant",
    )


def exit_in_flight(product: Product) -> Application | None:
    """The product's open exit, if it has one. Approved exits are history."""
    return (
        Application.objects.filter(
            product=product,
            workflow_key="ABDM_EXIT",
            deleted=False,
        )
        .exclude(state__in=RESTING_STATES)
        .first()
    )


def exit_grants(product: Product) -> list[abdm.ExitGrant]:
    """What this product's approved exits granted, as they stood when decided.

    Never a live claim and never an in-flight exit: a second exit under review
    grants nothing until its decision lands, and an approved exit's grant is
    not revoked by anything that happens afterwards.
    """
    approved = Application.objects.filter(
        product=product,
        workflow_key="ABDM_EXIT",
        state="APPROVED",
        deleted=False,
    ).prefetch_related("submissions")

    grants = []
    for application in approved:
        current = {
            submission.form_key: submission.data
            for submission in application.submissions.all()
            if submission.is_current
        }
        grants.append(
            abdm.ExitGrant(
                covers=frozenset(
                    abdm.Milestone(value)
                    for value in current.get("EXIT_CLAIM", {}).get("covers", [])
                ),
                approved_types=frozenset(
                    abdm.SolutionType(value)
                    for value in current.get("EXIT_DECISION", {}).get(
                        "approved_solution_types",
                        [],
                    )
                ),
            ),
        )
    return grants


def exit_documents(application: Application | None) -> dict[str, list]:
    """Evidence on the exit's current revisions, keyed by document kind."""
    if application is None:
        return {}
    documents: dict[str, list] = {}
    for submission in application.submissions.filter(is_current=True):
        for document in submission.documents.filter(deleted=False):
            documents.setdefault(document.kind, []).append(document)
    return documents


def document_detail(
    organisation: Organisation,
    external_id: UUID | str,
) -> ApplicationDocument:
    """One stored file, scoped to the caller's tenant.

    Wrong organisation 404s rather than 403s — a 403 would confirm the file
    exists, which is the thing being protected.
    """
    document = (
        ApplicationDocument.objects.filter(
            external_id=external_id,
            deleted=False,
            submission__application__product__organisation=organisation,
        )
        .select_related("submission__application")
        .first()
    )
    if document is None:
        raise Http404
    return document


def application_detail(
    organisation: Organisation,
    external_id: UUID | str,
) -> Application:
    application = (
        applications_for_organisation(organisation)
        .filter(
            external_id=external_id,
        )
        .first()
    )
    if application is None:
        raise Http404
    return application


def console_queue(
    *,
    workflow_key: str | None = None,
    state: str | None = None,
) -> QuerySet[Application]:
    queryset = Application.objects.select_related(
        "product",
        "product__organisation",
        "applicant",
    )
    if workflow_key:
        queryset = queryset.filter(workflow_key=workflow_key)
    if state:
        queryset = queryset.filter(state=state)
    return queryset.order_by("-created_date")


def products_available_for(
    organisation: Organisation,
    workflow_key: str,
    keep: Product | None = None,
) -> QuerySet[Product]:
    """C4's product picker: offering a product that already has a live
    application on this workflow would trip the partial-unique constraint.

    `keep` is the product the draft being edited already holds. Its own
    application is what makes it unavailable, so without this the applicant
    stepping back from the details step cannot see the product they just named.
    """
    taken = (
        Application.objects.filter(workflow_key=workflow_key)
        .exclude(state__in=RESTING_STATES)
        .values("product_id")
    )
    available = Product.objects.for_organisation(organisation).exclude(pk__in=taken)
    if keep is None:
        return available
    return Product.objects.for_organisation(organisation).filter(
        Q(pk__in=available) | Q(pk=keep.pk),
    )


@dataclass(frozen=True, slots=True)
class JourneyStep:
    key: str
    label: str
    status: str  # done | current | upcoming


#: The sandbox journey ends at credentials: an exit is its own application with
#: its own states, so it is not a further step on this one.
JOURNEY_LABELS: tuple[tuple[str, StrOrPromise], ...] = (
    ("apply", _("Apply")),
    ("verify", _("Verify")),
    ("review", _("Review")),
    ("credentials", _("Credentials")),
)

S = ApplicationState

STATE_STEP: dict[str, str] = {
    S.DRAFT: "apply",
    S.SUBMITTED: "review",
    S.SANDBOX_APPROVED: "credentials",
    S.PROVISIONING: "credentials",
    S.PROVISIONING_FAILED: "credentials",
    S.PROVISIONED: "credentials",
}

EDGE_STATES = frozenset({S.REJECTED, S.SENT_BACK, S.WITHDRAWN})

PENDING_STATES = frozenset({S.SUBMITTED, S.PROVISIONING})


def journey_for(state: str) -> list[JourneyStep]:
    """The track with each step marked done, current or upcoming.

    Edge states have no position, so every step reads as upcoming and the
    template shows a banner rather than a stepper.
    """
    current = STATE_STEP.get(state, "")
    keys = [key for key, _label in JOURNEY_LABELS]
    current_index = keys.index(current) if current else -1
    steps = []
    for index, (key, label) in enumerate(JOURNEY_LABELS):
        if current_index < 0:
            status = "upcoming"
        elif index < current_index:
            status = "done"
        elif index == current_index:
            status = "current"
        else:
            status = "upcoming"
        steps.append(JourneyStep(key=key, label=str(label), status=status))
    return steps
