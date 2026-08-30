"""The enrolment wizard.

Every step is a real POST + redirect that works with JavaScript off. Views never
write state directly — each step calls an A3/A5 service, so the wizard cannot
produce an application the domain would reject.

The organisation is chosen, never edited here: its profile is the tenant's own
data and lives in the organisations app.

Contact verification is not a step here: A4's `VerificationRequiredMiddleware`
already refuses the portal to anyone whose email and phone are unverified, so
by the time the wizard renders, both are done.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any
from typing import cast

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from django.views.generic import TemplateView
from django.views.generic import View
from django.views.generic.base import ContextMixin

from sandbox.applications.forms import ProductStepForm
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas import payload_form
from sandbox.applications.selectors import products_available_for
from sandbox.applications.services import create_draft
from sandbox.applications.services import create_draft_with_new_product
from sandbox.applications.services import update_draft
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import url_for
from sandbox.utils.errors import DomainError
from sandbox.workflow.machine import Action
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import reviews_for_round
from sandbox.workflow.services import transition

if TYPE_CHECKING:
    from django.forms import Form

    from sandbox.users.models import User

SCHEMA_VERSION = 1
#: states whose payload the applicant may still edit (mirrors A3's services)
EDITABLE_STATES = (ApplicationState.DRAFT, ApplicationState.SENT_BACK)

STEPS = (
    ("product", "Product"),
    ("details", "Sandbox details"),
    ("review", "Review"),
)


def _summary_rows(form: Form) -> list[tuple[str, str]]:
    """Label/value pairs for the read-only review, with codes resolved to the
    labels the applicant actually chose — `['EUA']` is not an answer."""
    rows = []
    for field in form:
        value = field.value()
        choices = dict(getattr(field.field, "choices", []) or [])
        if isinstance(value, list | tuple):
            shown = ", ".join(str(choices.get(item, item)) for item in value)
        elif value in (None, ""):
            shown = ""
        else:
            shown = str(choices.get(value, value))
        rows.append((str(field.label), shown))
    return rows


class WizardMixin(LoginRequiredMixin, OrganisationMixin, ContextMixin):
    step = ""
    request: HttpRequest

    @property
    def applicant(self) -> User:
        """`LoginRequiredMixin` has already refused anonymous callers."""
        return cast("User", self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["steps"] = STEPS
        context["current_step"] = self.step
        context["organisation"] = self.organisation
        return context


class ProductStepView(WizardMixin, FormView):
    template_name = "applications/step_product.html"
    form_class = ProductStepForm
    step = "product"

    def get_form_kwargs(self):
        return {
            **super().get_form_kwargs(),
            "available_products": products_available_for(
                self.organisation,
                ApplicationKind.SANDBOX,
            ),
        }

    def form_valid(self, form):
        product = form.cleaned_data.get("product")
        try:
            if product:
                application = create_draft(
                    organisation=self.organisation,
                    product=product,
                    applicant=self.applicant,
                    kind=ApplicationKind.SANDBOX,
                    data={},
                )
            else:
                application = create_draft_with_new_product(
                    organisation=self.organisation,
                    product_name=form.cleaned_data["new_product_name"],
                    applicant=self.applicant,
                    kind=ApplicationKind.SANDBOX,
                    data={},
                )
        except DomainError as error:
            form.add_error(None, error.message)
            return self.form_invalid(form)

        return redirect(
            url_for(
                "applications:step_details",
                self.organisation,
                external_id=application.external_id,
            ),
        )


class ApplicationStepMixin(WizardMixin):
    """Steps that operate on an existing draft. Wrong org resolves 404."""

    kwargs: dict[str, Any]

    @cached_property
    def application(self) -> Application:
        # Lazy, because `self.organisation` is only set once OrganisationMixin's
        # dispatch has run — by which time every caller here is inside get/post.
        return get_object_or_404(
            Application.objects.for_organisation(self.organisation),
            external_id=self.kwargs["external_id"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["application"] = self.application
        context["editable"] = self.application.state in EDITABLE_STATES
        return context


class DetailsStepView(ApplicationStepMixin, FormView):
    template_name = "applications/step_details.html"
    step = "details"

    def get_form_class(self):
        return payload_form(self.application.kind, SCHEMA_VERSION)

    def get_initial(self):
        return dict(self.application.payload.get("data", {}))

    def post(self, request, *args, **kwargs):
        # "Save and finish later" keeps whatever has been typed, however
        # incomplete; only "Continue" has to satisfy the schema.
        if request.POST.get("action") == "save":
            form = self.get_form()
            form.is_valid()  # populates cleaned_data for the fields that parsed
            self._save(form)
            messages.success(request, _("Draft saved."))
            return redirect(
                url_for(
                    "applications:step_details",
                    self.organisation,
                    external_id=self.application.external_id,
                ),
            )
        return super().post(request, *args, **kwargs)

    def _save(self, form) -> bool:
        try:
            update_draft(application=self.application, data=form.cleaned_data)
        except DomainError as error:
            form.add_error(None, error.message)
            return False
        return True

    def form_valid(self, form):
        if not self._save(form):
            return self.form_invalid(form)
        return redirect(
            url_for(
                "applications:step_review",
                self.organisation,
                external_id=self.application.external_id,
            ),
        )


class ReviewStepView(ApplicationStepMixin, TemplateView):
    template_name = "applications/step_review.html"
    step = "review"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        data = self.application.payload.get("data", {})
        form = payload_form(self.application.kind, SCHEMA_VERSION)(initial=data)
        context["summary"] = _summary_rows(form)
        # After a send-back the round has already advanced, so the comments the
        # applicant has to act on are the closed round's, not the open one's.
        previous_round = current_round(self.application) - 1
        context["reviews"] = (
            reviews_for_round(self.application, previous_round)
            if previous_round >= 1
            else reviews_for_round(self.application)
        )
        return context

    def post(self, request, *args, **kwargs):
        try:
            transition(
                application=self.application,
                action=Action.SUBMIT,
                actor=request.user,
            )
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                f"{self.application.reference} submitted for review.",
            )
        return redirect(
            url_for(
                "applications:step_review",
                self.organisation,
                external_id=self.application.external_id,
            ),
        )


class WizardEntryView(LoginRequiredMixin, OrganisationMixin, View):
    """`/applications/new/` — resume the draft in flight, or start a new one."""

    def get(self, request, *args, **kwargs):
        draft = (
            Application.objects.for_organisation(self.organisation)
            .filter(state__in=EDITABLE_STATES)
            .order_by("-created_date")
            .first()
        )
        if draft is not None:
            return redirect(
                url_for(
                    "applications:step_details",
                    self.organisation,
                    external_id=draft.external_id,
                ),
            )
        return redirect(url_for("applications:step_product", self.organisation))
