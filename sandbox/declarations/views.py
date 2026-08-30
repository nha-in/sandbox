"""The integrator's milestone and exit screens.

Every write goes to an A7 or A8 service; these views resolve the application,
shape context and turn `DomainError` into a message. The guards stay in the
services on purpose — a view that decided for itself when a declaration was
legal would be a second copy of the rule, and the two would drift.

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

from sandbox.applications.selectors import dashboard_application
from sandbox.catalog.selectors import active_milestones
from sandbox.declarations.forms import ExitDeclarationForm
from sandbox.declarations.forms import MilestoneDeclarationForm
from sandbox.declarations.selectors import current_exit_declaration
from sandbox.declarations.selectors import declaration_timeline
from sandbox.declarations.selectors import declared_milestone_claims
from sandbox.declarations.selectors import document_detail
from sandbox.declarations.services import DECLARABLE_STATES
from sandbox.declarations.services import download_url
from sandbox.declarations.services import submit_exit_declaration
from sandbox.declarations.services import submit_milestone_declaration
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import url_for
from sandbox.utils.errors import DomainError
from sandbox.workflow.services import request_exit

if TYPE_CHECKING:
    from django.http import HttpRequest

    from sandbox.applications.models import Application
    from sandbox.catalog.models import Milestone
    from sandbox.users.models import User


class ApplicationScopedMixin(LoginRequiredMixin, OrganisationMixin):
    """Resolves the organisation's application. There may not be one.

    Milestones and Exit are permanent sidebar items, so a member who has not
    applied at all still follows those links — 404ing them would put a dead
    link in the shell, which is the defect C10's navigation test exists to
    catch. The read screens render an empty state instead; writing still needs
    an application, and `require_application()` is what insists on it.
    """

    request: HttpRequest

    @property
    def actor(self) -> User:
        """`LoginRequiredMixin` has already refused anonymous callers."""
        return cast("User", self.request.user)

    @cached_property
    def application(self) -> Application | None:
        return dashboard_application(self.organisation)

    def require_application(self) -> Application:
        if self.application is None:
            raise Http404
        return self.application

    def base_context(self) -> dict:
        application = self.application
        return {
            "application": application,
            "organisation": self.organisation,
            "can_declare": (
                application is not None and application.state in DECLARABLE_STATES
            ),
        }


class MilestonesView(ApplicationScopedMixin, TemplateView):
    """Every active milestone, with whatever claim currently stands on it."""

    template_name = "declarations/milestones.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.application
        claims = (
            {
                claim.milestone_id: claim
                for claim in declared_milestone_claims(application)
            }
            if application is not None
            else {}
        )
        rows = [
            {"milestone": milestone, "claim": claims.get(milestone.pk)}
            for milestone in active_milestones()
        ]
        context.update(
            {
                **self.base_context(),
                "page_title": _("Milestones"),
                "rows": rows,
                "declared_count": len(claims),
                "timeline": (
                    declaration_timeline(application) if application is not None else []
                ),
            },
        )
        return context


class DeclareMilestoneView(ApplicationScopedMixin, FormView):
    """One milestone's form. Re-declaring supersedes the claim that stood."""

    template_name = "declarations/declare_milestone.html"
    form_class = MilestoneDeclarationForm

    @property
    def milestone(self) -> Milestone:
        for candidate in active_milestones():
            if candidate.key == self.kwargs["key"]:
                return candidate
        raise Http404

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        claims = {
            claim.milestone_id: claim
            for claim in declared_milestone_claims(self.require_application())
        }
        context.update(
            {
                **self.base_context(),
                "page_title": self.milestone.title,
                "milestone": self.milestone,
                "existing_claim": claims.get(self.milestone.pk),
            },
        )
        return context

    def form_valid(self, form):
        try:
            submit_milestone_declaration(
                application=self.require_application(),
                milestone=self.milestone,
                payload=form.payload(),
                files=form.cleaned_data["documents"],
                actor=self.actor,
                started_on=form.cleaned_data["started_on"],
                completed_on=form.cleaned_data["completed_on"],
            )
        except DomainError as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)

        messages.success(
            self.request,
            _("%(milestone)s declared complete.") % {"milestone": self.milestone.title},
        )
        return redirect(url_for("declarations:milestones", self.organisation))


class ExitView(ApplicationScopedMixin, FormView):
    """The gate, the form and the outcome — which one shows is state's decision."""

    template_name = "declarations/exit.html"
    form_class = ExitDeclarationForm

    def declared_milestones(self) -> list[Milestone]:
        """Only what has been declared: A8's guard refuses to exit the rest."""
        if self.application is None:
            return []
        claims = declared_milestone_claims(self.application)
        return [claim.milestone for claim in claims]

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "choices": [
                (milestone.key, milestone.title)
                for milestone in self.declared_milestones()
            ],
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        declared = self.declared_milestones()
        context.update(
            {
                **self.base_context(),
                "page_title": _("Exit to production"),
                "declared_milestones": declared,
                "is_locked": not declared,
                "exit_declaration": (
                    current_exit_declaration(self.application)
                    if self.application is not None
                    else None
                ),
            },
        )
        return context

    def form_valid(self, form):
        by_key = {milestone.key: milestone for milestone in self.declared_milestones()}
        application = self.require_application()
        try:
            submit_exit_declaration(
                application=application,
                milestones=[by_key[key] for key in form.cleaned_data["milestones"]],
                payload=form.payload(),
                files=form.cleaned_data["documents"],
                actor=self.actor,
            )
            request_exit(application=application, actor=self.actor)
        except DomainError as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)

        messages.success(self.request, _("Exit requested. NHA will review it."))
        return redirect(url_for("declarations:exit", self.organisation))


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
