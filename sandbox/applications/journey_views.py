"""The integrator's milestone and exit screens.

Every write goes to an A7 or A8 service; these views resolve the application,
shape context and turn `DomainError` into a message. The guards stay in the
services on purpose — a view that decided for itself when a declaration was
legal would be a second copy of the rule, and the two would drift.

Every screen here names its application in the URL. Sandbox access is granted
per product, so an organisation can hold several at once, and a claim belongs to
one of them — `DeclarationMilestone` has the foreign key to prove it. An
unscoped page had to guess, and guessed at the newest, which is a draft the
moment someone starts a second application beside a live one.

Milestones are declared one at a time against the *same* application, over as
long as it takes: `DeclarationMilestone` holds one current claim each, so coming
back next month to declare M3 is the designed path, not a new application.
"""

from __future__ import annotations

from datetime import date
from functools import cached_property
from typing import TYPE_CHECKING
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from django.views.generic import TemplateView
from django.views.generic import View

from sandbox.applications.documents import attach_documents
from sandbox.applications.documents import download_url
from sandbox.applications.models import Application
from sandbox.applications.selectors import approval_outcomes
from sandbox.applications.selectors import current_form_data
from sandbox.applications.selectors import document_detail
from sandbox.applications.selectors import exit_documents
from sandbox.applications.selectors import exit_grants
from sandbox.applications.selectors import exit_history
from sandbox.applications.selectors import exit_in_flight
from sandbox.applications.selectors import milestone_graph
from sandbox.applications.selectors import milestone_rows
from sandbox.applications.services import open_exit
from sandbox.applications.views import DECLARABLE_STATES
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import url_for
from sandbox.programmes import abdm
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine
from sandbox.workflow.registry import get_workflow
from sandbox.workflow.selectors import deciding_reviews
from sandbox.workflow.selectors import latest_send_back_comment

if TYPE_CHECKING:
    from django.http import HttpRequest

    from sandbox.users.models import User

#: form key -> the document kinds it must carry, straight from the workflow
REQUIRED_EXIT_DOCUMENTS = {
    key: get_workflow("ABDM_EXIT").form(key).requires_document
    for key in ("EXIT_CLAIM", "WASA")
}

EXIT_WORKFLOW = "ABDM_EXIT"

#: The exit wizard's steps. Filling the two forms and requesting the exit are
#: three separate acts, so they are three screens: saving a certificate to come
#: back to must not be the same click as asking NHA to review it.
EXIT_STEPS = (
    ("claim", _("What you are taking live")),
    ("wasa", _("Safe-to-Host certificate")),
    ("review", _("Review and request")),
)


def document_fields(form_key: str) -> list[tuple[str, str]]:
    """Upload fields as (name, label). A bare `DocumentKind` is not a label."""
    definition = get_workflow(EXIT_WORKFLOW).form(form_key)
    return [
        (kind, abdm.DOCUMENT_KIND_LABELS[abdm.DocumentKind(kind)])
        for kind in definition.requires_document
    ]


def exit_evidence(exit_application: Application | None) -> list[dict]:
    """The gate's checklist, so a missing file is seen before it refuses."""
    attached = exit_documents(exit_application)
    return [
        {"label": label, "files": attached.get(name, [])}
        for form_key in ("EXIT_CLAIM", "WASA")
        for name, label in document_fields(form_key)
    ]


def upload_fields(form_key: str, exit_application: Application | None) -> list[dict]:
    """The upload inputs for one step, and what each already holds.

    A carried-forward file must not be `required`: the browser would demand it
    again, which is the re-upload the carry-forward exists to avoid.
    """
    attached = exit_documents(exit_application)
    return [
        {"name": name, "label": label, "existing": attached.get(name, [])}
        for name, label in document_fields(form_key)
    ]


class ApplicationScopedMixin(LoginRequiredMixin, OrganisationMixin):
    """Resolves the application named in the URL, inside the caller's org.

    Wrong organisation 404s rather than 403s — a 403 would confirm the
    application exists (A2).
    """

    request: HttpRequest
    kwargs: dict

    @property
    def actor(self) -> User:
        """`LoginRequiredMixin` has already refused anonymous callers."""
        return cast("User", self.request.user)

    @cached_property
    def application(self) -> Application:
        application = (
            Application.objects.for_organisation(self.organisation)
            .filter(external_id=self.kwargs["external_id"])
            .select_related("product")
            .first()
        )
        if application is None:
            raise Http404
        return application

    def milestones_url(self) -> str:
        return url_for(
            "applications:milestones",
            self.organisation,
            external_id=self.application.external_id,
        )

    def exit_url(self) -> str:
        return url_for(
            "applications:exit",
            self.organisation,
            external_id=self.application.external_id,
        )

    def dhis_url(self) -> str:
        return url_for(
            "applications:dhis",
            self.organisation,
            external_id=self.application.external_id,
        )

    def base_context(self) -> dict:
        return {
            "application": self.application,
            "organisation": self.organisation,
            "can_declare": self.application.state in DECLARABLE_STATES,
            "milestones_url": self.milestones_url(),
            "exit_url": self.exit_url(),
            "dhis_url": self.dhis_url(),
        }


class MilestonesView(ApplicationScopedMixin, TemplateView):
    """Every milestone the programme defines, with the claim that stands on it."""

    template_name = "journey/milestones.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = milestone_rows(self.application)
        covered = frozenset().union(
            *(grant.covers for grant in exit_grants(self.application.product)),
        )
        context.update(
            {
                **self.base_context(),
                "page_title": _("Milestones"),
                "rows": rows,
                "graph": milestone_graph(self.application),
                # a declared milestone is not a live one until an exit covers it
                "covered": {f"MILESTONE_{value}" for value in covered},
                "declared_count": sum(1 for row in rows if row.declared),
            },
        )
        return context


class DeclareMilestoneView(ApplicationScopedMixin, FormView):
    """One milestone's form. Re-declaring supersedes the claim that stood."""

    template_name = "journey/declare_milestone.html"

    @cached_property
    def row(self):
        for candidate in milestone_rows(self.application):
            if candidate.key == self.kwargs["key"]:
                return candidate
        raise Http404

    def get_form_class(self):
        workflow = get_workflow(self.application.workflow_key)
        return workflow.form(self.row.form_key).form_class

    def get_initial(self):
        claim = self.row.claim
        return dict(claim.data) if claim else {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                **self.base_context(),
                "page_title": self.row.title,
                "milestone": self.row,
                "existing_claim": self.row.claim,
                "unlocks": [
                    dependent.title
                    for group in milestone_graph(self.application)
                    if group["root"].key == self.row.key
                    for dependent in group["dependents"]
                ],
            },
        )
        return context

    def form_valid(self, form):
        try:
            engine.submit_form(
                application=self.application,
                form_key=self.row.form_key,
                cleaned_data=form.cleaned_data,
                user=self.actor,
            )
        except DomainError as error:
            form.add_error(None, error.message)
            return self.form_invalid(form)

        messages.success(
            self.request,
            _("%(milestone)s declared complete.") % {"milestone": self.row.title},
        )
        return redirect(self.milestones_url())


class ExitJourneyMixin(ApplicationScopedMixin):
    """What the exit status page and its three steps all need.

    The exit is its own application: these screens hang off the sandbox one
    because that is where the integrator is, but everything they write goes to
    the `ABDM_EXIT` row for the same product.
    """

    @cached_property
    def exit_application(self) -> Application | None:
        return exit_in_flight(self.application.product)

    def declared_covers(self) -> list[tuple[str, str]]:
        """Only what has been declared: the gate refuses to exit the rest."""
        return [
            (row.form_key.removeprefix("MILESTONE_"), str(row.title))
            for row in milestone_rows(self.application)
            if row.declared
        ]

    def _current(self, form_key: str) -> dict:
        if self.exit_application is None:
            return {}
        return current_form_data(self.exit_application, form_key)

    def _unlocked(self, form_key: str) -> bool:
        """Ask the form definition, so the step order cannot drift from it."""
        exit_application = self.exit_application
        if exit_application is None:
            return False
        definition = get_workflow(EXIT_WORKFLOW).form(form_key)
        return definition.is_unlocked(engine.ApplicationContext(exit_application))

    def is_editable(self) -> bool:
        """A submitted exit is with NHA; only DRAFT and SENT_BACK take edits."""
        exit_application = self.exit_application
        if exit_application is None:
            return True
        editable = get_workflow(EXIT_WORKFLOW).form("EXIT_CLAIM").editable_states
        return exit_application.state in editable

    def claim_form(self, data=None):
        return abdm.ExitClaimForm(
            data,
            covers_choices=self.declared_covers(),
            initial=self._current("EXIT_CLAIM"),
        )

    def wasa_needs_reaffirming(self) -> bool:
        """A statement carried over from an earlier round is reused, not restated."""
        exit_application = self.exit_application
        if exit_application is None:
            return False
        submission = engine.ApplicationContext(exit_application).current("WASA")
        return submission is not None and submission.round != exit_application.round

    def wasa_has_expired(self) -> bool:
        """No tick renews a lapsed audit, so the screen must not offer one."""
        valid_upto = self._current("WASA").get("valid_upto")
        if not valid_upto:
            return False
        return date.fromisoformat(str(valid_upto)) < timezone.localdate()

    def wasa_form(self, data=None):
        return abdm.WasaForm(data, initial=self._current("WASA"))

    def exit_step_url(self, step: str) -> str:
        return url_for(
            f"applications:exit_{step}",
            self.organisation,
            external_id=self.application.external_id,
        )

    def exit_context(self) -> dict:
        exit_application = self.exit_application
        return {
            **self.base_context(),
            "declared_covers": self.declared_covers(),
            "is_locked": not self.declared_covers(),
            "exit_application": exit_application,
            "exit_state": exit_application.state if exit_application else "",
            "send_back_comment": (
                latest_send_back_comment(exit_application) if exit_application else ""
            ),
        }


class ExitView(ExitJourneyMixin, TemplateView):
    """Where an exit stands, and the way into the wizard that fills one in.

    Deliberately not a form: the gate, an exit under review and an approved
    exit all need somewhere to be, and none of them is a step.
    """

    template_name = "journey/exit.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claim = self._current("EXIT_CLAIM")
        wasa = self._current("WASA")
        covers = claim.get("covers", [])
        context.update(
            {
                **self.exit_context(),
                "page_title": _("Exit to production"),
                "has_claim": bool(claim),
                "has_wasa": bool(wasa),
                "claim_covers": covers,
                "wasa": wasa,
                "outcomes": approval_outcomes(self.application, covers),
                "history": exit_history(self.application.product),
            },
        )
        return context


class ExitStepMixin(ExitJourneyMixin):
    """One step of the exit wizard, and the reasons it may refuse to render.

    Checked per handler rather than in `dispatch`, because the application
    cannot be resolved until `OrganisationMixin.dispatch` has run.
    """

    step = ""

    def refuse(self):
        """Nothing declared, or nothing editable, means there is no step to do."""
        if not self.declared_covers() or not self.is_editable():
            return redirect(self.exit_url())
        return None

    # The concrete view supplies these; the mixin only gets to refuse first.
    def get(self, request, *args, **kwargs):
        return self.refuse() or super().get(request, *args, **kwargs)  # type: ignore[misc]

    def post(self, request, *args, **kwargs):
        return self.refuse() or super().post(request, *args, **kwargs)  # type: ignore[misc]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        context.update(
            {
                **self.exit_context(),
                "steps": EXIT_STEPS,
                "current_step": self.step,
            },
        )
        return context

    def _open(self) -> Application:
        return open_exit(product=self.application.product, applicant=self.actor)

    def _attach(self, submission, request) -> None:
        for kind in REQUIRED_EXIT_DOCUMENTS.get(submission.form_key, ()):
            uploads = request.FILES.getlist(kind)
            if uploads:
                attach_documents(
                    submission=submission,
                    uploads=uploads,
                    kind=kind,
                    actor=self.actor,
                )

    def _save(self, form, form_key: str):
        """Write the step, carrying its uploads. Returns False to re-render."""
        try:
            submission = engine.submit_form(
                application=self._open(),
                form_key=form_key,
                cleaned_data=form.cleaned_data,
                user=self.actor,
            )
        except DomainError as error:
            form.add_error(None, error.message)
            return False
        self._attach(submission, self.request)
        return True


class ExitClaimStepView(ExitStepMixin, FormView):
    """Step 1: which declared milestones are going live, and the evidence."""

    template_name = "journey/exit_claim.html"
    step = "claim"

    def get_form(self, form_class=None):
        data = self.request.POST if self.request.method == "POST" else None
        return self.claim_form(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("What you are taking live")
        context["uploads"] = upload_fields("EXIT_CLAIM", self.exit_application)
        return context

    def form_valid(self, form):
        if not self._save(form, "EXIT_CLAIM"):
            return self.form_invalid(form)
        messages.success(self.request, _("Exit declaration saved."))
        return redirect(self.exit_step_url("wasa"))


class ExitWasaStepView(ExitStepMixin, FormView):
    """Step 2: the Safe-to-Host certificate the claim has to carry."""

    template_name = "journey/exit_wasa.html"
    step = "wasa"

    def refuse(self):
        # WASA declares its dependency on the claim; honour it rather than
        # write the step order down a second time.
        return super().refuse() or (
            None if self._unlocked("WASA") else redirect(self.exit_step_url("claim"))
        )

    def get_form(self, form_class=None):
        data = self.request.POST if self.request.method == "POST" else None
        return self.wasa_form(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Safe-to-Host certificate")
        context["uploads"] = upload_fields("WASA", self.exit_application)
        return context

    def form_valid(self, form):
        if not self._save(form, "WASA"):
            return self.form_invalid(form)
        messages.success(self.request, _("Safe-to-Host details saved."))
        return redirect(self.exit_step_url("review"))


class ExitReviewStepView(ExitStepMixin, TemplateView):
    """Step 3: read it back, then request the exit. The only step that submits."""

    template_name = "journey/exit_review.html"
    step = "review"

    def refuse(self):
        refusal = super().refuse()
        if refusal is not None:
            return refusal
        if not self._current("EXIT_CLAIM"):
            return redirect(self.exit_step_url("claim"))
        if not self._current("WASA"):
            return redirect(self.exit_step_url("wasa"))
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exit_application = self.exit_application
        claim = self._current("EXIT_CLAIM")
        covers = dict(self.declared_covers())
        expired = self.wasa_has_expired()
        context.update(
            {
                "page_title": _("Review and request exit"),
                "covers": [covers.get(key, key) for key in claim.get("covers", [])],
                "summary": claim.get("summary", ""),
                "wasa": self._current("WASA"),
                "wasa_expired": expired,
                "evidence": exit_evidence(exit_application),
                # a sent-back exit is answering comments it has to be able to read
                "reviews": deciding_reviews(exit_application)
                if exit_application
                else [],
            },
        )
        context.setdefault(
            "affirmation_form",
            abdm.WasaAffirmationForm()
            if self.wasa_needs_reaffirming() and not expired
            else None,
        )
        return context

    def post(self, request, *args, **kwargs):
        refusal = self.refuse()
        if refusal is not None:
            return refusal
        exit_application = self.exit_application
        if exit_application is None:
            return redirect(self.exit_step_url("claim"))
        if self.wasa_needs_reaffirming() and not self.wasa_has_expired():
            form = abdm.WasaAffirmationForm(request.POST)
            if not form.is_valid():
                return self.render_to_response(
                    self.get_context_data(affirmation_form=form),
                )
            self._reaffirm_wasa(exit_application)
        try:
            engine.transition(
                application=exit_application,
                action="SUBMIT",
                actor=self.actor,
            )
        except DomainError as error:
            messages.error(request, error.message)
            return redirect(self.exit_step_url("review"))
        messages.success(request, _("Exit requested. NHA will review it."))
        return redirect(self.exit_url())

    def _reaffirm_wasa(self, exit_application: Application) -> None:
        # Restating the certificate stamps it with this round, which is the
        # affirmation the gate reads; nothing about the statement changes.
        engine.submit_form(
            application=exit_application,
            form_key="WASA",
            cleaned_data=dict(self._current("WASA")),
            user=self.actor,
        )


class DhisView(ApplicationScopedMixin, TemplateView):
    """Which solution types may be registered on DHIS, and recording that you did.

    The sandbox records a claim and blocks nothing: DHIS itself enforces
    claim-once, so a button disabled here on the strength of our own record
    would be us guessing at another system's state.
    """

    template_name = "journey/dhis.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grants = exit_grants(self.application.product)
        claimed = {
            submission.data.get("solution_type")
            for submission in self.application.submissions.filter(
                form_key="DHIS_CLAIM",
            )
        }
        context.update(
            {
                **self.base_context(),
                "page_title": _("Register on DHIS"),
                "rows": [
                    {
                        "value": solution_type.value,
                        "label": solution_type.value,
                        "enabled": abdm.dhis_enabled(grants, solution_type),
                        "required": sorted(
                            abdm.SOLUTION_TYPE_MILESTONES[solution_type],
                        ),
                        "claimed": solution_type.value in claimed,
                    }
                    for solution_type in abdm.SolutionType
                ],
                "covered": sorted(abdm.covered(grants)),
            },
        )
        return context

    def post(self, request, *args, **kwargs):
        try:
            engine.submit_form(
                application=self.application,
                form_key="DHIS_CLAIM",
                cleaned_data={"solution_type": request.POST.get("solution_type", "")},
                user=self.actor,
            )
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, _("Recorded. Complete the handoff on DHIS."))
        return redirect(self.dhis_url())


class DocumentDownloadView(LoginRequiredMixin, OrganisationMixin, View):
    """The only way a declaration document is ever reached.

    The bucket is private and has no public URLs; this resolves an `external_id`
    inside the caller's organisation and redirects to a short-lived presigned
    GET. Wrong organisation 404s — a 403 would confirm the file exists.
    """

    def get(self, request, external_id):
        document = document_detail(self.organisation, external_id)
        return redirect(download_url(document))


document_download_view = DocumentDownloadView.as_view()


class PastExitView(ExitJourneyMixin, TemplateView):
    """One exit as it was decided. Strictly read-only: no form, no POST.

    An application accrues exits over its life, and until now a decided one
    could only be read through the console. The applicant is the other party to
    that decision and had no copy of it.
    """

    template_name = "journey/exit_detail.html"

    @cached_property
    def past_exit(self) -> Application:
        exit_application = (
            Application.objects.filter(
                product=self.application.product,
                workflow_key=EXIT_WORKFLOW,
                external_id=self.kwargs["exit_id"],
                deleted=False,
            )
            .select_related("product")
            .first()
        )
        if exit_application is None:
            raise Http404
        return exit_application

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        exit_application = self.past_exit
        claim = current_form_data(exit_application, "EXIT_CLAIM")
        decision = current_form_data(exit_application, "EXIT_DECISION")
        approved = decision.get("approved_solution_types", [])
        labels = dict(abdm.RegistrationSolutionType.choices)
        context.update(
            {
                **self.base_context(),
                "page_title": exit_application.reference,
                "past_exit": exit_application,
                "covers": claim.get("covers", []),
                "summary": claim.get("summary", ""),
                "wasa": current_form_data(exit_application, "WASA"),
                "documents": exit_documents(exit_application),
                "granted": [labels.get(value, value) for value in approved],
                "reviews": deciding_reviews(exit_application),
                "history": exit_application.transitions.select_related("actor"),
            },
        )
        return context
