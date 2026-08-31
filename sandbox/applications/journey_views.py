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

from functools import cached_property
from typing import TYPE_CHECKING
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from django.views.generic import TemplateView
from django.views.generic import View

from sandbox.applications.documents import attach_documents
from sandbox.applications.documents import download_url
from sandbox.applications.models import Application
from sandbox.applications.selectors import current_form_data
from sandbox.applications.selectors import document_detail
from sandbox.applications.selectors import exit_documents
from sandbox.applications.selectors import exit_grants
from sandbox.applications.selectors import exit_in_flight
from sandbox.applications.selectors import milestone_rows
from sandbox.applications.services import open_exit
from sandbox.applications.views import DECLARABLE_STATES
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import url_for
from sandbox.programmes import abdm
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine
from sandbox.workflow.registry import get_workflow

if TYPE_CHECKING:
    from django.http import HttpRequest

    from sandbox.users.models import User

#: form key -> the document kinds it must carry, straight from the workflow
REQUIRED_EXIT_DOCUMENTS = {
    key: get_workflow("ABDM_EXIT").form(key).requires_document
    for key in ("EXIT_CLAIM", "WASA")
}


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
        context.update(
            {
                **self.base_context(),
                "page_title": _("Milestones"),
                "rows": rows,
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


class ExitView(ApplicationScopedMixin, TemplateView):
    """The gate, the two forms and the outcome — which one shows is state's call.

    The exit is its own application: this screen hangs off the sandbox one
    because that is where the integrator is, but everything it writes goes to
    the `ABDM_EXIT` row for the same product.
    """

    template_name = "journey/exit.html"

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

    def _claim_form(self, data=None):
        return abdm.ExitClaimForm(
            data,
            covers_choices=self.declared_covers(),
            initial=self._current("EXIT_CLAIM"),
        )

    def _wasa_form(self, data=None):
        return abdm.WasaForm(data, initial=self._current("WASA"))

    def _current(self, form_key: str) -> dict:
        if self.exit_application is None:
            return {}
        return current_form_data(self.exit_application, form_key)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        covers = self.declared_covers()
        exit_application = self.exit_application
        context.update(
            {
                **self.base_context(),
                "page_title": _("Exit to production"),
                "declared_covers": covers,
                "is_locked": not covers,
                "exit_application": exit_application,
                "exit_state": exit_application.state if exit_application else "",
                "claim_form": kwargs.get("claim_form") or self._claim_form(),
                "wasa_form": kwargs.get("wasa_form") or self._wasa_form(),
                "has_claim": bool(self._current("EXIT_CLAIM")),
                "documents": exit_documents(exit_application),
                "required_documents": REQUIRED_EXIT_DOCUMENTS,
            },
        )
        return context

    def post(self, request, *args, **kwargs):
        handlers = {
            "claim": self._save_claim,
            "wasa": self._save_wasa,
            "submit": self._submit,
        }
        handler = handlers.get(request.POST.get("step", ""))
        if handler is None:
            # the route exists and the caller may use it; the body is just wrong
            messages.error(request, _("That form could not be read. Try again."))
            return redirect(self.exit_url())
        try:
            return handler(request)
        except DomainError as error:
            messages.error(request, error.message)
            return redirect(self.exit_url())

    def _open(self) -> Application:
        return open_exit(product=self.application.product, applicant=self.actor)

    def _save_claim(self, request):
        form = self._claim_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(claim_form=form))
        submission = engine.submit_form(
            application=self._open(),
            form_key="EXIT_CLAIM",
            cleaned_data=form.cleaned_data,
            user=self.actor,
        )
        self._attach(submission, request)
        messages.success(request, _("Exit declaration saved."))
        return redirect(self.exit_url())

    def _save_wasa(self, request):
        form = self._wasa_form(request.POST)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(wasa_form=form))
        submission = engine.submit_form(
            application=self._open(),
            form_key="WASA",
            cleaned_data=form.cleaned_data,
            user=self.actor,
        )
        self._attach(submission, request)
        messages.success(request, _("Safe-to-Host details saved."))
        return redirect(self.exit_url())

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

    def _submit(self, request):
        exit_application = self.exit_application
        if exit_application is None:
            message = "there is no exit to submit yet"
            raise DomainError(message, code="no_exit")
        engine.transition(
            application=exit_application,
            action="SUBMIT",
            actor=self.actor,
        )
        messages.success(request, _("Exit requested. NHA will review it."))
        return redirect(self.exit_url())


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
