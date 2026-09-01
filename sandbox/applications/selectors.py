"""Read-only queries over Application.

Wrong-org lookups 404 rather than 403 — a 403 confirms the record exists (A2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.formats import date_format
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
    from collections.abc import Iterable
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
    depends_on: tuple[str, ...] = ()

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
                depends_on=tuple(definition.depends_on),
            ),
        )
    return rows


def milestone_graph(application: Application) -> list[dict]:
    """The prerequisite DAG, as columns the screen can draw.

    One entry per milestone that depends on nothing, with the milestones that
    name it. The rules are the product — "M3 does not need M2" is the kind of
    thing an integrator gets wrong and pays for at exit — and a flat list of
    five rows says nothing about them.

    Two levels only, which is what the ABDM graph is. A third would need a
    different drawing, and inventing one for a shape nobody has is guesswork.
    """
    rows = milestone_rows(application)
    return [
        {
            "root": root,
            "dependents": [row for row in rows if root.form_key in row.depends_on],
        }
        for root in rows
        if not root.depends_on
    ]


def milestone_progress(application: Application) -> dict[str, Any]:
    """Declared-of-total plus what is still outstanding, for the dashboard."""
    rows = milestone_rows(application)
    return {
        "declared": sum(1 for row in rows if row.declared),
        "total": len(rows),
        "next": [row.title for row in rows if not row.declared and row.unlocked][:3],
    }


def applications_for_organisation(organisation: Organisation) -> QuerySet[Application]:
    """The enrollments an integrator can open. Exits are applications too, but
    they are reached from the enrollment they exit, and have no registration
    form for these screens to ask about."""
    return (
        Application.objects.for_organisation(organisation)
        .filter(workflow_key="ABDM")
        .select_related(
            "product",
            "applicant",
        )
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


#: States in which an application has milestones worth counting and declaring:
#: before PROVISIONED there is no sandbox to build against.
DECLARABLE_STATES = (ApplicationState.PROVISIONED,)

#: What a solution type still needs, per milestone.
COVERED = "covered"
DECLARED = "declared"
OUTSTANDING = "outstanding"


@dataclass(frozen=True, slots=True)
class CoverageCell:
    milestone: str
    title: StrOrPromise
    state: str


@dataclass(frozen=True, slots=True)
class CoverageRow:
    """One registered solution type, and how close it is to being live."""

    solution_type: str
    label: StrOrPromise
    cells: tuple[CoverageCell, ...]
    is_live: bool

    @property
    def outstanding(self) -> int:
        return sum(1 for cell in self.cells if cell.state != COVERED)


def coverage(application: Application) -> list[CoverageRow]:
    """One row per registered solution type: what it needs, and what it has.

    The matrix is the product and it was nowhere on screen — an integrator had
    to hold `SOLUTION_TYPE_MILESTONES` in their head to know that two declared
    milestones and an approved exit still left HMIS one short.

    Reporting only. It gates nothing, ever: exiting M1 while M3 is outstanding
    is a legal path, and a screen that called it non-compliant would be wrong
    about the product rather than about the data.
    """
    registered = current_form_data(application, "REGISTRATION").get(
        "solution_types",
        [],
    )
    grants = exit_grants(application.product)
    live = abdm.covered(grants)
    workflow = get_workflow(application.workflow_key)
    declared = {
        submission.form_key
        for submission in application.submissions.filter(is_current=True)
    }
    # labels belong to the definitions that declare them, not a second list here
    solution_labels = dict(abdm.RegistrationSolutionType.choices)

    rows = []
    for solution_type in abdm.dhis_solution_types(registered):
        cells = tuple(
            CoverageCell(
                milestone=str(milestone),
                title=workflow.form(abdm.milestone_form_key(milestone)).label,
                state=(
                    COVERED
                    if milestone in live
                    else DECLARED
                    if abdm.milestone_form_key(milestone) in declared
                    else OUTSTANDING
                ),
            )
            for milestone in sorted(abdm.SOLUTION_TYPE_MILESTONES[solution_type])
        )
        rows.append(
            CoverageRow(
                solution_type=str(solution_type),
                label=solution_labels.get(str(solution_type), str(solution_type)),
                cells=cells,
                is_live=abdm.dhis_enabled(grants, solution_type),
            ),
        )
    return rows


@dataclass(frozen=True, slots=True)
class NextAction:
    """The one thing worth doing now, and why it is worth doing."""

    title: StrOrPromise
    reason: StrOrPromise
    action_label: StrOrPromise
    route: str
    route_kwargs: dict[str, Any]


def _milestone_reason(application: Application, row: MilestoneRow) -> StrOrPromise:
    """Name the solution type this milestone is the last one standing between.

    Worth the extra query: "declare M3" is an instruction, while "M3 is the last
    milestone HMIS needs" is the reason someone acts on it.
    """
    for coverage_row in coverage(application):
        outstanding = [cell for cell in coverage_row.cells if cell.state == OUTSTANDING]
        if len(outstanding) == 1 and outstanding[0].milestone == row.key.upper():
            return _("%(milestone)s is the last milestone %(solution)s needs.") % {
                "milestone": outstanding[0].milestone,
                "solution": coverage_row.label,
            }
    return _("Declaring it opens whatever depends on it.")


def _sandbox_action(application: Application, *, explain: bool) -> NextAction | None:
    """What is left once there is a sandbox to build against."""
    exit_application = exit_in_flight(application.product)
    if exit_application is not None:
        if exit_application.state == "SENT_BACK":
            return NextAction(
                title=_("Answer NHA on your exit request"),
                reason=_("The round does not advance while it is with you."),
                action_label=_("Open exit request"),
                route="applications:exit",
                route_kwargs={"external_id": application.external_id},
            )
        if exit_application.state != "DRAFT":
            return None

    rows = milestone_rows(application)
    undeclared = [row for row in rows if row.unlocked and not row.declared]
    if undeclared:
        row = undeclared[0]
        return NextAction(
            title=_("Declare %(milestone)s complete") % {"milestone": row.title},
            reason=_milestone_reason(application, row) if explain else "",
            action_label=_("Declare"),
            route="applications:declare_milestone",
            route_kwargs={"external_id": application.external_id, "key": row.key},
        )
    if any(row.declared for row in rows):
        return NextAction(
            title=_("Request your exit to production"),
            reason=_("Every milestone open to you is declared."),
            action_label=_("Start exit request"),
            route="applications:exit",
            route_kwargs={"external_id": application.external_id},
        )
    return None


def next_action(application: Application, *, explain: bool = True) -> NextAction | None:
    """What to do next, or None when the answer is honestly "wait".

    Derived, never stored. A screen that told someone to act while their
    application sat with a reviewer would be inventing work for them, so the
    states where nothing is theirs to do return None and the screen says so.

    `explain=False` skips the coverage query behind the reason, for the list
    screen, which shows seventeen titles and no reasons.
    """
    if application.state == ApplicationState.DRAFT:
        return NextAction(
            title=_("Finish your application"),
            reason=_("Your answers are saved. Submit it when you are ready."),
            action_label=_("Continue"),
            route="applications:step_details",
            route_kwargs={"external_id": application.external_id},
        )
    if application.state == ApplicationState.SENT_BACK:
        return NextAction(
            title=_("Answer the reviewer's comments"),
            reason=_("Your application is back with you until you resubmit it."),
            action_label=_("Open application"),
            route="applications:step_review",
            route_kwargs={"external_id": application.external_id},
        )
    if application.state not in DECLARABLE_STATES:
        return None
    return _sandbox_action(application, explain=explain)


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
    label: StrOrPromise
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


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One thing that happened, in the applicant's terms rather than the log's."""

    happened_at: Any
    summary: StrOrPromise
    actor: str
    consequence: StrOrPromise = ""


#: Transitions worth showing an applicant. The rest are internal bookkeeping —
#: a chain step that moved PROVISIONING to PROVISIONED tells them nothing that
#: "Sandbox credentials issued" does not.
_ACTIVITY_ACTIONS: dict[str, tuple[StrOrPromise, StrOrPromise]] = {
    "SUBMIT": (_("Application submitted for review"), ""),
    "APPROVE": (_("Application approved"), _("Your sandbox is being set up.")),
    "SEND_BACK": (
        _("Changes requested"),
        _("The round does not advance while it is with you."),
    ),
    "REJECT": (_("Application rejected"), ""),
    "WITHDRAW": (_("Application withdrawn"), ""),
}


def activity(application: Application, limit: int = 8) -> list[ActivityEntry]:
    """What has happened to this application, newest first.

    Merged from two tables because the applicant's history is spread over both:
    the transition log holds decisions, and the submission log holds everything
    they wrote. Neither alone reads as an account of the work.
    """
    entries: list[ActivityEntry] = []

    for transition in application.transitions.select_related("actor"):
        if transition.action not in _ACTIVITY_ACTIONS:
            continue
        summary, consequence = _ACTIVITY_ACTIONS[transition.action]
        entries.append(
            ActivityEntry(
                happened_at=transition.created_date,
                summary=summary,
                actor=transition.actor.email if transition.actor else str(_("System")),
                consequence=consequence,
            ),
        )

    workflow = get_workflow(application.workflow_key)
    for submission in application.submissions.select_related("submitted_by"):
        if submission.form_key == "REGISTRATION":
            summary = _("Integration profile updated")
            consequence = _("Grants nothing until your next exit is reviewed.")
        elif submission.form_key.startswith("MILESTONE_"):
            summary = _("%(milestone)s declared complete") % {
                "milestone": workflow.form(submission.form_key).label,
            }
            consequence = "" if submission.is_current else str(_("Superseded since."))
        else:
            continue
        entries.append(
            ActivityEntry(
                happened_at=submission.created_date,
                summary=summary,
                actor=(
                    submission.submitted_by.email
                    if submission.submitted_by
                    else str(_("System"))
                ),
                consequence=consequence,
            ),
        )

    entries.sort(key=lambda entry: entry.happened_at, reverse=True)
    return entries[:limit]


def live_since(application: Application):
    """When the sandbox actually started working, for "live since" and day counts.

    The transition into PROVISIONED, not `created_date`: an application drafted
    in March and provisioned in July has been usable for one of those months.
    """
    transition = (
        application.transitions.filter(to_state=ApplicationState.PROVISIONED)
        .order_by("created_date")
        .first()
    )
    return transition.created_date if transition else None


def days_live(application: Application) -> int | None:
    """Day 1 is the day it was provisioned, which is how people count it."""
    started = live_since(application)
    if started is None:
        return None
    return (timezone.localdate() - timezone.localtime(started).date()).days + 1


#: What approving the claim in front of NHA would change, per solution type.
GOES_LIVE = "goes_live"
ALREADY_LIVE = "already_live"
STAYS_SANDBOX = "stays_sandbox"


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """One solution type, and what an approval would mean for it."""

    label: StrOrPromise
    outcome: str
    detail: StrOrPromise


def approval_outcomes(
    application: Application,
    claimed: Iterable[str],
) -> list[ApprovalOutcome]:
    """What this exit claim would and would not put into production.

    Computed from the same rules the reviewer decides against, so the applicant
    can see before sending that a claim missing one milestone enables nothing.
    An approval is additive and never revokes, which is why an already-live type
    still gets a row rather than disappearing.
    """
    registered = current_form_data(application, "REGISTRATION").get(
        "solution_types",
        [],
    )
    grants = exit_grants(application.product)
    live = abdm.covered(grants)
    would_cover = live | {str(milestone) for milestone in claimed}
    labels = dict(abdm.RegistrationSolutionType.choices)

    outcomes = []
    for solution_type in abdm.dhis_solution_types(registered):
        needed = {str(m) for m in abdm.SOLUTION_TYPE_MILESTONES[solution_type]}
        label = labels.get(str(solution_type), str(solution_type))
        detail: StrOrPromise
        if abdm.dhis_enabled(grants, solution_type):
            outcome = ALREADY_LIVE
            detail = _("Already in production, and never revoked.")
        elif needed <= would_cover:
            outcome = GOES_LIVE
            detail = _("Every milestone it needs would be covered.")
        else:
            short = sorted(needed - would_cover)
            outcome = STAYS_SANDBOX
            detail = _("Still short of %(milestones)s.") % {
                "milestones": ", ".join(short),
            }
        outcomes.append(ApprovalOutcome(label=label, outcome=outcome, detail=detail))
    return outcomes


@dataclass(frozen=True, slots=True)
class ExitAttempt:
    """One exit this product has requested, as its own row of history."""

    application: Application
    covers: tuple[str, ...]
    requested_at: Any
    decided_at: Any
    is_open: bool


def exit_history(product: Product) -> list[ExitAttempt]:
    """Every exit this product has requested, newest first.

    One row per exit application, not per round: a rejection and the
    resubmission answering it are rounds of the same exit, while taking further
    milestones live later is a new one.
    """
    applications = (
        Application.objects.filter(
            product=product,
            workflow_key="ABDM_EXIT",
            deleted=False,
        )
        .prefetch_related("submissions", "transitions")
        .order_by("-created_date")
    )

    attempts = []
    for application in applications:
        claim: dict = next(
            (
                submission.data
                for submission in application.submissions.all()
                if submission.is_current and submission.form_key == "EXIT_CLAIM"
            ),
            {},
        )
        transitions = sorted(
            application.transitions.all(),
            key=lambda t: t.created_date,
        )
        submitted = next((t for t in transitions if t.action == "SUBMIT"), None)
        decided = next(
            (t for t in reversed(transitions) if t.action in {"APPROVE", "REJECT"}),
            None,
        )
        attempts.append(
            ExitAttempt(
                application=application,
                covers=tuple(claim.get("covers", [])),
                requested_at=submitted.created_date if submitted else None,
                decided_at=decided.created_date if decided else None,
                is_open=application.state not in RESTING_STATES,
            ),
        )
    return attempts


#: The four things an application can be doing, in the order the list shows them.
PHASE_YOUR_MOVE = "your_move"
PHASE_BUILDING = "building"
PHASE_WITH_NHA = "with_nha"
PHASE_CLOSED = "closed"

_PHASE_HEADINGS: dict[str, tuple[StrOrPromise, StrOrPromise]] = {
    PHASE_YOUR_MOVE: (
        _("Your move"),
        _("Stalled until someone here acts."),
    ),
    PHASE_BUILDING: (
        _("Building in the sandbox"),
        _("Live credentials. Declare milestones as you finish them."),
    ),
    PHASE_WITH_NHA: (
        _("With NHA"),
        _("Nothing to do while it is being reviewed."),
    ),
    PHASE_CLOSED: (
        _("Closed"),
        _("Kept for the record. Start a new application to try again."),
    ),
}

_CLOSED_STATES = frozenset(
    {
        ApplicationState.REJECTED,
        ApplicationState.WITHDRAWN,
        ApplicationState.PROVISIONING_FAILED,
    },
)


@dataclass(frozen=True, slots=True)
class ApplicationRow:
    """One application as the list draws it."""

    application: Application
    phase: str
    badge_label: StrOrPromise
    #: a real workflow state, used only to pick the badge colour
    badge_state: str
    meta: StrOrPromise
    next_action: NextAction | None
    #: one per milestone the programme defines, True where it is declared
    ticks: tuple[bool, ...]

    @property
    def is_blocking(self) -> bool:
        """Whether the row's own button should be the filled one."""
        return self.phase == PHASE_YOUR_MOVE

    @property
    def ticks_title(self) -> StrOrPromise:
        return _("%(declared)s of %(total)s milestones declared") % {
            "declared": sum(self.ticks),
            "total": len(self.ticks),
        }


@dataclass(frozen=True, slots=True)
class ApplicationGroup:
    title: StrOrPromise
    subhead: StrOrPromise
    rows: list[ApplicationRow]


#: The line under a row's name, per state. One table so the phrasing of the
#: whole list can be read in one place.
_ROW_META: dict[str, StrOrPromise] = {
    ApplicationState.DRAFT: _("Started %(when)s · not submitted"),
    ApplicationState.SENT_BACK: _("Round %(round)s · sent back"),
    ApplicationState.PROVISIONING_FAILED: _(
        "NHA has been notified — no action needed from you",
    ),
    ApplicationState.REJECTED: _("%(state)s %(when)s"),
    ApplicationState.WITHDRAWN: _("%(state)s %(when)s"),
    ApplicationState.SUBMITTED: _("Submitted %(when)s"),
}


def _state_meta(application: Application, started: str) -> StrOrPromise:
    if application.state == ApplicationState.SUBMITTED and application.round > 1:
        return _("Round %(round)s · resent") % {"round": application.round}
    template = _ROW_META.get(application.state)
    if template is None:
        return ""
    return template % {
        "when": started,
        "round": application.round,
        "state": application.get_state_display(),
    }


def _row_meta(
    application: Application,
    exit_application: Application | None,
) -> StrOrPromise:
    """The line under the name: the date that matters, in this state's terms."""
    if exit_application is not None and exit_application.state == "SENT_BACK":
        return _("Exit round %(round)s is with you") % {"round": exit_application.round}
    # otherwise the row shows a live sandbox and no next action, and the reason
    # for the silence — an exit already under review — is the missing fact
    if exit_application is not None and exit_application.state not in {
        "DRAFT",
        *RESTING_STATES,
    }:
        return _("Exit %(reference)s is with NHA") % {
            "reference": exit_application.reference,
        }
    started = date_format(timezone.localtime(application.created_date), "j M")
    return _state_meta(application, started)


def _milestone_ticks(application: Application) -> tuple[bool, ...]:
    return tuple(row.declared for row in milestone_rows(application))


def _row_phase(application: Application, exit_application: Application | None) -> str:
    if application.state in {ApplicationState.DRAFT, ApplicationState.SENT_BACK}:
        return PHASE_YOUR_MOVE
    if application.state in _CLOSED_STATES:
        return PHASE_CLOSED
    if application.state in DECLARABLE_STATES:
        if exit_application is not None and exit_application.state == "SENT_BACK":
            return PHASE_YOUR_MOVE
        return PHASE_BUILDING
    return PHASE_WITH_NHA


def application_groups(organisation: Organisation) -> list[ApplicationGroup]:
    """Every application this organisation holds, grouped by whose move it is.

    Seventeen rows in one flat list are seventeen rows of equal weight, and the
    two that are stalled on the reader look exactly like the fifteen that are
    not. The grouping is an ordering of the same query, never a filter: nothing
    is hidden, it is only ranked.
    """
    buckets: dict[str, list[ApplicationRow]] = {key: [] for key in _PHASE_HEADINGS}

    for application in applications_for_organisation(organisation):
        exit_application = (
            exit_in_flight(application.product)
            if application.state in DECLARABLE_STATES
            else None
        )
        phase = _row_phase(application, exit_application)
        exit_sent_back = (
            exit_application is not None and exit_application.state == "SENT_BACK"
        )
        buckets[phase].append(
            ApplicationRow(
                application=application,
                phase=phase,
                badge_label=(
                    _("Exit sent back")
                    if exit_sent_back
                    else application.get_state_display()
                ),
                # a provisioned application whose exit is stalled reads as
                # "Provisioned", which hides the only fact that matters about it
                badge_state=("SENT_BACK" if exit_sent_back else application.state),
                meta=_row_meta(application, exit_application),
                next_action=next_action(application, explain=False),
                # empty before PROVISIONED: a draft showing 0 of 5 reads exactly
                # like a live product that has genuinely declared none
                ticks=(
                    _milestone_ticks(application)
                    if application.state in DECLARABLE_STATES
                    else ()
                ),
            ),
        )

    return [
        ApplicationGroup(
            title=_PHASE_HEADINGS[key][0],
            subhead=_PHASE_HEADINGS[key][1],
            rows=rows,
        )
        for key, rows in buckets.items()
        if rows
    ]
