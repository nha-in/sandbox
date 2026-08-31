"""The ABDM programme: enrollment and exit workflows, matrix and DAG.

This module is the entire flow legacy spread across a React component, a CSV
column and a wide table (plan/09-redesign.md §4.3). The two sources of truth
are `MILESTONE_PREREQS` (the DAG) and `SOLUTION_TYPE_MILESTONES` (the DHIS
matrix, verified against the NHA flow spec and plan/10-production-truth.md).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django import forms
from django.db.models import TextChoices
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from sandbox.workflow.definitions import PERM_APPROVE
from sandbox.workflow.definitions import PERM_REJECT
from sandbox.workflow.definitions import PERM_RETRY_PROVISIONING
from sandbox.workflow.definitions import PERM_SEND_BACK
from sandbox.workflow.definitions import ActorKind
from sandbox.workflow.definitions import FormDefinition
from sandbox.workflow.definitions import TransitionSpec
from sandbox.workflow.definitions import Workflow

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sandbox.workflow.definitions import Context

# ---------------------------------------------------------------------------
# Vocabulary


class Milestone(enum.StrEnum):
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    PHR = "PHR"
    HEALTH_LOCKER = "HEALTH_LOCKER"


class SolutionType(enum.StrEnum):
    """The five DHIS-eligible solution types of the NHA matrix."""

    HMIS = "HMIS"
    LMIS = "LMIS"
    TELEMEDICINE = "TELEMEDICINE"
    HEALTH_LOCKER = "HEALTH_LOCKER"
    PHARMACY = "PHARMACY"


class DocumentKind(enum.StrEnum):
    """Evidence kinds of the production exit form (10-production-truth.md §3)."""

    FUNCTIONAL_TEST_REPORT = "FUNCTIONAL_TEST_REPORT"
    AUDIT_CERTIFICATE = "AUDIT_CERTIFICATE"  # the WASA / Safe-to-Host certificate
    UNDERTAKING = "UNDERTAKING"  # signed hard copy also goes by post
    GSTIN_CERTIFICATE = "GSTIN_CERTIFICATE"
    SUPPORTING = "SUPPORTING"


MILESTONE_LABELS: dict[Milestone, str] = {
    Milestone.M1: "M1 — ABHA creation & verification",
    Milestone.M2: "M2 — Health Information Provider (HIP)",
    Milestone.M3: "M3 — Health Information User (HIU)",
    Milestone.PHR: "PHR application",
    Milestone.HEALTH_LOCKER: "Health Locker",
}

#: the DAG: M3 does NOT require M2; PHR stands alone; Health Locker needs PHR
MILESTONE_PREREQS: dict[Milestone, tuple[Milestone, ...]] = {
    Milestone.M1: (),
    Milestone.M2: (Milestone.M1,),
    Milestone.M3: (Milestone.M1,),
    Milestone.PHR: (),
    Milestone.HEALTH_LOCKER: (Milestone.PHR,),
}

#: the DHIS matrix: a button is eligible iff its row is covered
SOLUTION_TYPE_MILESTONES: dict[SolutionType, frozenset[Milestone]] = {
    SolutionType.HMIS: frozenset({Milestone.M1, Milestone.M2, Milestone.M3}),
    SolutionType.LMIS: frozenset({Milestone.M1, Milestone.M2}),
    SolutionType.TELEMEDICINE: frozenset({Milestone.M1, Milestone.M2, Milestone.M3}),
    SolutionType.HEALTH_LOCKER: frozenset(
        {Milestone.PHR, Milestone.HEALTH_LOCKER},
    ),
    SolutionType.PHARMACY: frozenset({Milestone.M1, Milestone.M2}),
}


def milestone_form_key(milestone: Milestone | str) -> str:
    return f"MILESTONE_{milestone}"


def dhis_solution_types(
    registered: Iterable[str],
) -> frozenset[SolutionType]:
    """The DHIS-eligible subset of what was selected at registration.

    Narrow on purpose: legacy expanded HMIS to {HMIS, LMIS, Pharmacy} and
    ratcheted the result, so one selection granted three and narrowing never
    narrowed the grant. Widening is the admin's explicit call at exit instead
    (master plan open question 11).
    """
    members = {solution_type.value for solution_type in SolutionType}
    return frozenset(SolutionType(value) for value in registered if value in members)


# ---------------------------------------------------------------------------
# Predicates (plan/09-redesign.md §4.4) — four questions, four names.
# `covered`/`approved_types`/`dhis_enabled`/`is_compliant` are pure functions
# over grants so the scenario table tests them without a database; selectors
# build the grants from approved exits.


@dataclass(frozen=True, slots=True)
class ExitGrant:
    """One approved exit's contribution: the claim as it stood when decided."""

    covers: frozenset[Milestone]
    approved_types: frozenset[SolutionType]


def covered(grants: Iterable[ExitGrant]) -> frozenset[Milestone]:
    """Union over approved exits. Approvals are additive: they only ever add."""
    return frozenset().union(*(grant.covers for grant in grants))


def approved_types(grants: Iterable[ExitGrant]) -> frozenset[SolutionType]:
    return frozenset().union(*(grant.approved_types for grant in grants))


def dhis_enabled(
    grants: Iterable[ExitGrant],
    solution_type: SolutionType,
) -> bool:
    """Is the DHIS button live? Reads decisions, never a live claim."""
    materialised = list(grants)
    return solution_type in approved_types(
        materialised,
    ) and SOLUTION_TYPE_MILESTONES[solution_type] <= covered(materialised)


def is_compliant(
    selected: Iterable[SolutionType],
    grants: Iterable[ExitGrant],
) -> bool:
    """Reporting only; gates nothing. Exiting M1 with M3 outstanding is legal."""
    rows = [SOLUTION_TYPE_MILESTONES[s] for s in selected]
    if not rows:
        return False
    return frozenset().union(*rows) <= covered(grants)


def milestone_unlocked(ctx: Context, milestone: Milestone) -> bool:
    """May this milestone's form be filled? The DAG, applied."""
    return all(
        ctx.has_current(milestone_form_key(prerequisite))
        for prerequisite in MILESTONE_PREREQS[milestone]
    )


def exit_gate(ctx: Context) -> bool:
    """May this exit be submitted? Not the same predicate as compliance."""
    covers = ctx.form_data("EXIT_CLAIM").get("covers", [])
    return (
        bool(covers)
        # milestone claims live on the sibling ABDM application, not the exit
        and all(ctx.product_has_current("ABDM", milestone_form_key(m)) for m in covers)
        and ctx.has_current_at_round("WASA")
    )


# ---------------------------------------------------------------------------
# Django forms. Choice sets for registration are the legacy lists from
# `sandbox-website/src/constants/common-data.js`; the DHIS-eligible five are a
# strict subset of `RegistrationSolutionType`, which is what lets the matrix
# read the registration's selection directly.


class RegistrationSolutionType(TextChoices):
    """Legacy `sd_login.solution_type` — the full registration choice set."""

    CLINIC_HMIS = "CLINIC_HMIS", _("Clinic HMIS")
    EUA = "EUA", _("End User Applications (EUA)")
    GOVT_PROGRAM = "GOVT_PROGRAM", _("Govt Program")
    GOVT_HMIS = "GOVT_HMIS", _("Govt HMIS")
    GOVT_PHR = "GOVT_PHR", _("Govt PHR")
    HEALTH_LOCKER = "HEALTH_LOCKER", _("Health Locker")
    HEALTHTECH = "HEALTHTECH", _("Healthtech")
    HMIS = "HMIS", _("HMIS")
    INSURANCE = "INSURANCE", _("Insurance")
    LMIS = "LMIS", _("LMIS")
    OTHERS = "OTHERS", _("Others")
    PAYERS = "PAYERS", _("Payers")
    PHARMACY = "PHARMACY", _("Pharmacy")
    PHR = "PHR", _("PHR")
    PROVIDERS = "PROVIDERS", _("Providers")
    TELEMEDICINE = "TELEMEDICINE", _("Telemedicine")


class PayerCategory(TextChoices):
    TPA = "TPA", _("TPA")
    INSURANCE_COMPANY = "INSURANCE_COMPANY", _("Insurance company")


class IntegrationIntent(TextChoices):
    """Legacy `sd_login.field_detail`, built from `intentForRequestDTOs`."""

    ABHA_M1 = "ABHA_M1", _("ABHA Creation/Verification - M1")
    HIP_M2 = "HIP_M2", _("Building Health Information Provider (HIP) - M2")
    HIU_M3 = "HIU_M3", _("Building Health Information User (HIU) - M3")
    HPR_HFR_M4 = "HPR_HFR_M4", _("National Healthcare Provider Registry (HPR/HFR) - M4")
    HEALTH_LOCKER = "HEALTH_LOCKER", _("Health Locker")
    PHR_APP = "PHR_APP", _("PHR App")
    PAYERS = "PAYERS", _("Payers")
    PROVIDERS = "PROVIDERS", _("Providers")
    EUA = "EUA", _("End User Applications (EUA)")
    HSPA = "HSPA", _("Health Service Provider Application (HSPA)")


class RegistrationForm(forms.Form):
    # Checkboxes rather than `<select multiple>`: there, a plain click on a
    # second option replaces the first, and losing answers silently is the
    # failure that matters here.
    solution_types = forms.MultipleChoiceField(
        choices=RegistrationSolutionType.choices,
        widget=forms.CheckboxSelectMultiple,
        label=_("Solution type"),
    )
    solution_type_others = forms.CharField(
        required=False,
        max_length=255,
        label=_("Other solution type"),
    )
    integration_intents = forms.MultipleChoiceField(
        choices=IntegrationIntent.choices,
        widget=forms.CheckboxSelectMultiple,
        label=_("Intent for request"),
    )
    # legacy stored NULL here and rendered it as "NA"
    payer_categories = forms.MultipleChoiceField(
        choices=PayerCategory.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Payer categories"),
    )
    use_case_narrative = forms.CharField(
        widget=forms.Textarea,
        label=_("Intent behind applying for sandbox"),
    )

    def clean(self):
        cleaned_data = super().clean() or {}
        solution_types = cleaned_data.get("solution_types") or []
        if RegistrationSolutionType.OTHERS in solution_types and not cleaned_data.get(
            "solution_type_others",
        ):
            self.add_error(
                "solution_type_others",
                _("Required when 'Others' is selected."),
            )
        return cleaned_data


class MilestoneDeclarationForm(forms.Form):
    """Declare one milestone complete. The milestone itself comes from the URL."""

    started_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Started on"),
    )
    completed_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Completed on"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("What you built and how you tested it"),
    )

    def clean(self):
        cleaned_data = super().clean() or {}
        started_on = cleaned_data.get("started_on")
        completed_on = cleaned_data.get("completed_on")
        today = timezone.localdate()
        for field, value in (
            ("started_on", started_on),
            ("completed_on", completed_on),
        ):
            if value is not None and value > today:
                self.add_error(field, _("That date is in the future."))
        if started_on and completed_on and completed_on < started_on:
            self.add_error("completed_on", _("Cannot be before the start date."))
        return cleaned_data


class ExitClaimForm(forms.Form):
    """Which declared milestones this exit takes to production."""

    covers = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        label=_("Milestones to take to production"),
    )
    summary = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4}),
        label=_("Summary of your integration"),
    )

    def __init__(self, *args, covers_choices=(), **kwargs) -> None:
        super().__init__(*args, **kwargs)
        field = self.fields["covers"]
        assert isinstance(field, forms.MultipleChoiceField)
        field.choices = list(covers_choices)


class WasaForm(forms.Form):
    """The Safe-to-Host certificate's validity window, as the applicant states it."""

    start = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("WASA start date"),
    )
    valid_upto = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("WASA valid until"),
    )

    def clean(self):
        cleaned_data = super().clean() or {}
        start = cleaned_data.get("start")
        valid_upto = cleaned_data.get("valid_upto")
        if start and valid_upto and valid_upto <= start:
            self.add_error("valid_upto", _("Must be after the start date."))
        return cleaned_data


class ExitDecisionForm(forms.Form):
    """The admin's verdict. Written only by the engine inside APPROVE."""

    approved_solution_types = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        label=_("Approved solution types"),
    )
    undertaking_hard_copy_received_on = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label=_("Signed Undertaking hard copy received on"),
    )
    m1_on_v3_confirmed = forms.BooleanField(
        required=False,
        label=_("M1 implementation verified on V3 APIs"),
    )

    def __init__(self, *args, registered_choices=(), **kwargs) -> None:
        # the ceiling: only what the applicant selected is offered (§10)
        super().__init__(*args, **kwargs)
        field = self.fields["approved_solution_types"]
        assert isinstance(field, forms.MultipleChoiceField)
        field.choices = list(registered_choices)


class DhisClaimForm(forms.Form):
    """Record a DHIS handoff. DHIS itself enforces claim-once; we only record."""

    solution_type = forms.ChoiceField(
        choices=[(member.value, member.value) for member in SolutionType],
        label=_("Solution type claimed"),
    )


# ---------------------------------------------------------------------------
# Form definitions


class Registration(FormDefinition):
    key = "REGISTRATION"
    label = "Registration"
    form_class = RegistrationForm
    # PROVISIONED is deliberate: the applicant may widen their selection later
    # ("edit integration profile"); the decision-time ceiling means a widening
    # grants nothing until the next reviewed exit decision (§10).
    editable_states = frozenset({"DRAFT", "SENT_BACK", "PROVISIONED"})


def _milestone_form(milestone: Milestone) -> type[FormDefinition]:
    return type(
        f"Milestone{milestone}",
        (FormDefinition,),
        {
            "key": milestone_form_key(milestone),
            "label": MILESTONE_LABELS[milestone],
            "form_class": MilestoneDeclarationForm,
            "depends_on": tuple(
                milestone_form_key(p) for p in MILESTONE_PREREQS[milestone]
            ),
            # you declare what you built, not all of it
            "required": False,
            "editable_states": frozenset({"PROVISIONED"}),
        },
    )


MILESTONE_FORMS: tuple[type[FormDefinition], ...] = tuple(
    _milestone_form(milestone) for milestone in Milestone
)


class DhisClaim(FormDefinition):
    key = "DHIS_CLAIM"
    label = "DHIS claim"
    form_class = DhisClaimForm
    required = False
    repeatable = True  # pure history: never current, every claim a distinct event
    editable_states = frozenset({"PROVISIONED"})


class ExitClaim(FormDefinition):
    key = "EXIT_CLAIM"
    label = "Exit declaration"
    form_class = ExitClaimForm
    # the production exit form's own attachments ride on the claim
    requires_document = (
        DocumentKind.FUNCTIONAL_TEST_REPORT,
        DocumentKind.UNDERTAKING,
        DocumentKind.GSTIN_CERTIFICATE,
    )
    editable_states = frozenset({"DRAFT", "SENT_BACK"})


class Wasa(FormDefinition):
    key = "WASA"
    label = "WASA / Safe-to-Host"
    form_class = WasaForm
    depends_on = ("EXIT_CLAIM",)
    requires_document = (DocumentKind.AUDIT_CERTIFICATE,)
    editable_states = frozenset({"DRAFT", "SENT_BACK"})


class ExitDecision(FormDefinition):
    key = "EXIT_DECISION"
    label = "Exit decision"
    form_class = ExitDecisionForm
    actor_kind = ActorKind.STAFF
    permission = PERM_APPROVE


# ---------------------------------------------------------------------------
# Workflows

#: resolved against the guard registry; a draft may be incomplete, submitting
#: it is the point at which it must not be
GUARD_REGISTRATION_COMPLETE = "registration_complete"
GUARD_EXIT_GATE = "exit_gate"


class ABDMWorkflow(Workflow):
    """Sandbox enrollment. `PROVISIONED` is where an integrator lives —
    compliance is a computation over exits, never a state."""

    key = "ABDM"
    label = "ABDM Sandbox"
    initial_state = "DRAFT"
    terminal_states = frozenset({"REJECTED", "WITHDRAWN"})
    resting_states = frozenset({"REJECTED", "WITHDRAWN"})
    forms = (Registration, *MILESTONE_FORMS, DhisClaim)
    transitions = {
        ("DRAFT", "SUBMIT"): TransitionSpec(
            "SUBMITTED",
            ActorKind.OWNER,
            guards=(GUARD_REGISTRATION_COMPLETE,),
        ),
        ("SENT_BACK", "SUBMIT"): TransitionSpec(
            "SUBMITTED",
            ActorKind.OWNER,
            guards=(GUARD_REGISTRATION_COMPLETE,),
            # reviews are unique per round; re-review needs a new cycle
            advances_round=True,
        ),
        ("DRAFT", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
        ("SUBMITTED", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
        ("SENT_BACK", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
        ("SUBMITTED", "APPROVE"): TransitionSpec(
            "SANDBOX_APPROVED",
            ActorKind.STAFF,
            PERM_APPROVE,
            hooks=("provisioning_chain",),
            review_driven=True,
        ),
        ("SUBMITTED", "REJECT"): TransitionSpec(
            "REJECTED",
            ActorKind.STAFF,
            PERM_REJECT,
            hooks=("deprovisioning_chain", "notify_rejected"),
            review_driven=True,
        ),
        ("SUBMITTED", "SEND_BACK"): TransitionSpec(
            "SENT_BACK",
            ActorKind.STAFF,
            PERM_SEND_BACK,
            review_driven=True,
        ),
        # Provisioning (B7). The chain owns these; a person never drives them.
        ("SANDBOX_APPROVED", "START_PROVISIONING"): TransitionSpec(
            "PROVISIONING",
            ActorKind.SYSTEM,
        ),
        ("PROVISIONING", "COMPLETE_PROVISIONING"): TransitionSpec(
            "PROVISIONED",
            ActorKind.SYSTEM,
            hooks=("notify_provisioned",),
        ),
        ("PROVISIONING", "FAIL_PROVISIONING"): TransitionSpec(
            "PROVISIONING_FAILED",
            ActorKind.SYSTEM,
            hooks=("alert_provisioning_failed",),
        ),
        ("PROVISIONING_FAILED", "RETRY_PROVISIONING"): TransitionSpec(
            "PROVISIONING",
            ActorKind.STAFF,
            PERM_RETRY_PROVISIONING,
            hooks=("provisioning_chain",),
        ),
        # Withdrawal is the way out of a chain that failed for good, and it has
        # to tear down the partial resources it created (B8).
        ("PROVISIONING_FAILED", "WITHDRAW"): TransitionSpec(
            "WITHDRAWN",
            ActorKind.OWNER,
            hooks=("deprovisioning_chain",),
        ),
        ("PROVISIONED", "WITHDRAW"): TransitionSpec(
            "WITHDRAWN",
            ActorKind.OWNER,
            hooks=("deprovisioning_chain",),
        ),
    }


class ABDMExitWorkflow(Workflow):
    """One exit attempt: claim + WASA + decision, per round (§5.3).

    `APPROVED` is terminal — taking more milestones to production is a new
    exit on the same product, and this exit's grant persists untouched.
    """

    key = "ABDM_EXIT"
    label = "ABDM production exit"
    initial_state = "DRAFT"
    terminal_states = frozenset({"APPROVED", "WITHDRAWN"})
    #: APPROVED/REJECTED rest: January's approved exit sits beside September's
    #: in-flight one, but two exits may never be under review at once
    resting_states = frozenset({"APPROVED", "REJECTED", "WITHDRAWN"})
    forms = (ExitClaim, Wasa, ExitDecision)
    transitions = {
        ("DRAFT", "SUBMIT"): TransitionSpec(
            "SUBMITTED",
            ActorKind.OWNER,
            guards=(GUARD_EXIT_GATE,),
        ),
        ("SENT_BACK", "SUBMIT"): TransitionSpec(
            "SUBMITTED",
            ActorKind.OWNER,
            guards=(GUARD_EXIT_GATE,),
            advances_round=True,
        ),
        ("SUBMITTED", "START_REVIEW"): TransitionSpec(
            "UNDER_REVIEW",
            ActorKind.STAFF,
            PERM_APPROVE,
        ),
        ("UNDER_REVIEW", "APPROVE"): TransitionSpec(
            "APPROVED",
            ActorKind.STAFF,
            PERM_APPROVE,
            hooks=("notify_exit_approved",),
            # the engine writes the decision inside this move, same transaction
            decision_form_key="EXIT_DECISION",
            review_driven=True,
        ),
        ("UNDER_REVIEW", "REJECT"): TransitionSpec(
            "REJECTED",
            ActorKind.STAFF,
            PERM_REJECT,
            hooks=("notify_exit_rejected",),
            review_driven=True,
        ),
        ("UNDER_REVIEW", "SEND_BACK"): TransitionSpec(
            "SENT_BACK",
            ActorKind.STAFF,
            PERM_SEND_BACK,
            hooks=("notify_exit_sent_back",),
            review_driven=True,
        ),
        # a rejected attempt's resubmission is a new round: fresh WASA statement,
        # reviews and decisions distinguishable from the rejected cycle's
        ("REJECTED", "RESUBMIT"): TransitionSpec(
            "DRAFT",
            ActorKind.OWNER,
            advances_round=True,
        ),
        ("DRAFT", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
        ("SUBMITTED", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
        ("SENT_BACK", "WITHDRAW"): TransitionSpec("WITHDRAWN", ActorKind.OWNER),
    }
