"""Console reads: the queue, its counts, and the payload presented for humans."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.db.models import Count
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationFormSubmission
from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import current_form_data
from sandbox.applications.selectors import exit_documents
from sandbox.programmes import abdm
from sandbox.workflow.registry import get_workflow

if TYPE_CHECKING:
    from collections.abc import Sequence

    from django.db.models import QuerySet
    from django_stubs_ext import StrOrPromise

PAGE_SIZE = 25


def _matching(search: str, visible: Sequence[str]) -> QuerySet[Application]:
    """One definition of "matches the search", so the badges and the table can
    never disagree about how many results there are.

    `visible` is the actor's programmes: a team holds no authority over another
    programme's applications and has no business reading their evidence either.
    """
    applications = Application.objects.filter(workflow_key__in=visible)
    if search:
        applications = applications.filter(
            Q(reference__icontains=search)
            | Q(product__organisation__name__icontains=search),
        )
    return applications


def queue(
    *,
    visible: Sequence[str],
    state: str = "",
    search: str = "",
    after: int | None = None,
) -> QuerySet[Application]:
    """Filtered console queue.

    Ordered by descending id rather than `created_date`: the seed and any bulk
    import create many rows inside one transaction, so timestamps tie and an
    ordering on them is not stable enough to paginate against.
    """
    applications = (
        _matching(search, visible)
        .select_related(
            "product__organisation",
            "applicant",
        )
        .order_by("-id")
    )

    if state:
        applications = applications.filter(state=state)
    if after is not None:
        applications = applications.filter(id__lt=after)

    return applications


def state_counts(visible: Sequence[str], search: str = "") -> dict[str, int]:
    """Every state with its count, zeros included, in workflow order.

    Counts what the search is showing: a badge reading "Draft 1" next to a
    filtered table that has no drafts is worse than no badge at all.
    """
    counted = {
        row["state"]: row["total"]
        for row in _matching(search, visible)
        .values("state")
        .annotate(total=Count("id"))
    }
    return {state: counted.get(state, 0) for state in ApplicationState.values}


#: states where the ball is in a reviewer's court. Deliberately not "everything
#: that is not finished": a SENT_BACK application is waiting on the integrator,
#: and counting it would have the console nag reviewers about work they cannot do.
AWAITING_REVIEW_STATES = (
    ApplicationState.SUBMITTED,
    # exits are their own applications, with their own reviewable state
    "UNDER_REVIEW",
)


def awaiting_review_count(visible: Sequence[str]) -> int:
    """The sidebar badge. One query, ignoring any search or state filter — it
    reports the size of the reviewers' backlog, not of the view they happen to
    be looking at."""
    return Application.objects.filter(
        workflow_key__in=visible,
        state__in=AWAITING_REVIEW_STATES,
    ).count()


def payload_groups(application: Application) -> list[dict[str, Any]]:
    """Registration as labelled groups — never a raw JSON dump on a reviewer's
    screen, and never a bare code: `['EUA']` is not an answer.

    Headings and labels come from the form the applicant actually filled in, so
    a field added to the programme shows up here without a second list to edit.
    """
    data = current_form_data(application, "REGISTRATION")
    if not data:
        return []

    form = get_workflow(application.workflow_key).form("REGISTRATION").form_class()
    groups: list[dict[str, Any]] = []
    for name, field in form.fields.items():
        value = data.get(name)
        if value in (None, "", []):
            continue
        labels = dict(getattr(field, "choices", []) or [])
        values = value if isinstance(value, list | tuple) else [value]
        groups.append(
            {
                "heading": str(field.label or name),
                "values": [str(labels.get(item, item)) for item in values],
            },
        )
    return groups


def registered_solution_types(exit_application: Application) -> list[tuple[str, str]]:
    """The admin's ceiling: only what the applicant selected may be approved.

    Read at decision time from the product's sandbox application, so widening
    the registration later grants nothing until the next exit is decided (§10).
    """
    sandbox = (
        Application.objects.filter(
            product_id=exit_application.product_id,
            workflow_key="ABDM",
            deleted=False,
        )
        .order_by("-created_date")
        .first()
    )
    if sandbox is None:
        return []
    selected = current_form_data(sandbox, "REGISTRATION").get("solution_types", [])
    labels = dict(abdm.RegistrationSolutionType.choices)
    eligible = abdm.dhis_solution_types(selected)
    return [
        (solution_type.value, str(labels.get(solution_type.value, solution_type.value)))
        for solution_type in sorted(eligible)
    ]


def exit_review(exit_application: Application) -> dict[str, Any]:
    """What the reviewer decides on: the claim, the WASA, and the evidence."""
    claim = current_form_data(exit_application, "EXIT_CLAIM")
    return {
        "covers": claim.get("covers", []),
        "summary": claim.get("summary", ""),
        "wasa": current_form_data(exit_application, "WASA"),
        "documents": exit_documents(exit_application),
        "decision_form": abdm.ExitDecisionForm(
            registered_choices=registered_solution_types(exit_application),
        ),
    }


@dataclass(frozen=True, slots=True)
class QueueRow:
    """One queue line: what is being asked for, and how long it has waited."""

    application: Application
    asking_for: StrOrPromise
    waiting_days: int | None
    is_over_target: bool


def _submitted_at(application: Application):
    """The clock starts when the applicant last sent it, not when they drafted
    it, and restarts on a resubmission — a round is what a reviewer owes."""
    transition = (
        application.transitions.filter(action="SUBMIT")
        .order_by("-created_date")
        .first()
    )
    return transition.created_date if transition else None


def _asking_for(application: Application) -> StrOrPromise:
    """Labels, not stored values: a reviewer should not have to expand
    HEALTH_LOCKER in their head to know what is being asked for."""
    if application.workflow_key == "ABDM_EXIT":
        covers = current_form_data(application, "EXIT_CLAIM").get("covers", [])
        if covers:
            return _("Exit — %(covers)s") % {"covers": ", ".join(covers)}
        return _("Exit to production")
    labels = dict(abdm.RegistrationSolutionType.choices)
    types = current_form_data(application, "REGISTRATION").get("solution_types", [])
    if types:
        return _("Sandbox access — %(types)s") % {
            "types": ", ".join(str(labels.get(value, value)) for value in types),
        }
    return _("Sandbox access")


def queue_rows(applications: Sequence[Application]) -> list[QueueRow]:
    """The queue as the screen draws it, ageing included.

    Ageing is reporting only. It colours a cell and gates nothing: a target is
    something NHA measures itself against, not a rule applied to an applicant.
    """
    target = settings.REVIEW_TARGET_DAYS
    today = timezone.localdate()
    rows = []
    for application in applications:
        submitted = _submitted_at(application)
        waiting = (
            (today - timezone.localtime(submitted).date()).days
            if submitted is not None
            else None
        )
        rows.append(
            QueueRow(
                application=application,
                asking_for=_asking_for(application),
                waiting_days=waiting,
                is_over_target=waiting is not None and waiting > target,
            ),
        )
    return rows


@dataclass(frozen=True, slots=True)
class ReviewerFlag:
    """Something worth a second look. Advisory: no flag blocks a decision."""

    title: StrOrPromise
    detail: StrOrPromise


def reviewer_flags(exit_application: Application) -> list[ReviewerFlag]:
    """Facts a reviewer would otherwise have to reconstruct by hand.

    Both are warnings and neither is a block — 09-redesign §5.3 is explicit
    that a repeated hash is the reviewer's call, not the system's.
    """
    flags: list[ReviewerFlag] = []

    current = exit_application.submissions.filter(
        form_key="WASA",
        is_current=True,
    ).first()
    if current is not None:
        hashes = {
            document.sha256
            for document in ApplicationDocument.objects.filter(
                submission=current,
                deleted=False,
            )
        }
        earlier = ApplicationDocument.objects.filter(
            submission__application=exit_application,
            submission__round__lt=current.round,
            sha256__in=hashes,
            deleted=False,
        ).exists()
        if hashes and earlier:
            flags.append(
                ReviewerFlag(
                    title=_(
                        "The Safe-to-Host certificate is the same as an earlier round",
                    ),
                    detail=_(
                        "The same audit backs both rounds. Reasonable after a minor "
                        "fix, not after a backend change — your call.",
                    ),
                ),
            )

    decided = (
        exit_application.transitions.filter(action__in=("APPROVE", "REJECT"))
        .order_by("-created_date")
        .first()
    )
    if decided is not None:
        widened = ApplicationFormSubmission.objects.filter(
            application__product=exit_application.product,
            application__workflow_key="ABDM",
            form_key="REGISTRATION",
            created_date__gt=decided.created_date,
        ).exists()
        if widened:
            flags.append(
                ReviewerFlag(
                    title=_("The integration profile changed since the last decision"),
                    detail=_(
                        "What they registered for was edited after the previous round "
                        "was decided. Check the change before approving.",
                    ),
                ),
            )
    return flags


#: `action` -> what happened, in a sentence. The raw triple stays beside it as
#: mono subtext: the audit trail is the record, this is only the reading of it.
_HISTORY_SENTENCES: dict[str, StrOrPromise] = {
    "SUBMIT": _("Submitted for review"),
    "START_REVIEW": _("Picked up for review"),
    "APPROVE": _("Approved"),
    "REJECT": _("Rejected"),
    "SEND_BACK": _("Sent back for changes"),
    "WITHDRAW": _("Withdrawn by the applicant"),
    "RETRY_PROVISIONING": _("Provisioning retried"),
}


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    transition: Any
    sentence: StrOrPromise
    raw: str


def humanised_history(application: Application) -> list[HistoryEntry]:
    """The transition log, read rather than transcribed."""
    entries = []
    for transition in application.transitions.select_related("actor"):
        raw = f"{transition.from_state} → {transition.to_state}"
        entries.append(
            HistoryEntry(
                transition=transition,
                sentence=_HISTORY_SENTENCES.get(
                    transition.action,
                    transition.action,
                ),
                raw=f"{raw} · {transition.action}",
            ),
        )
    return entries


def asking_for(application: Application) -> StrOrPromise:
    """What this application wants, in a few words.

    Shorter than the queue's version on purpose: beside the organisation name
    in a page title, the full list of solution types buries the one word that
    tells a reviewer which of the two workflows they are looking at.
    """
    if application.workflow_key == "ABDM_EXIT":
        return _("exit to production")
    return _("sandbox access")


def review_subtitle(application: Application) -> StrOrPromise:
    """Reference, round and age — the facts a reviewer orients by.

    The age is the same read the queue ages on, so a row that looked urgent
    there does not look ordinary once opened.
    """
    parts: list[str] = [application.reference]
    if application.round > 1:
        parts.append(str(_("Round %(round)s") % {"round": application.round}))
    submitted = _submitted_at(application)
    if submitted is not None:
        waiting = (timezone.localdate() - timezone.localtime(submitted).date()).days
        parts.append(
            str(
                ngettext(
                    "submitted %(days)s day ago",
                    "submitted %(days)s days ago",
                    waiting,
                )
                % {"days": waiting},
            )
            if waiting
            else str(_("submitted today")),
        )
    return " · ".join(parts)
