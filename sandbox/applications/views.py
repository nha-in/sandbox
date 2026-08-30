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
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView
from django.views.generic import TemplateView
from django.views.generic.base import ContextMixin

from sandbox.applications.forms import ProductStepForm
from sandbox.applications.models import NON_BLOCKING_STATES
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationKind
from sandbox.applications.models import ApplicationState
from sandbox.applications.schemas import payload_form
from sandbox.applications.selectors import EDGE_STATES
from sandbox.applications.selectors import PENDING_STATES
from sandbox.applications.selectors import applications_for_organisation
from sandbox.applications.selectors import journey_for
from sandbox.applications.selectors import products_available_for
from sandbox.applications.services import create_draft
from sandbox.applications.services import create_draft_with_new_product
from sandbox.applications.services import rename_draft_product
from sandbox.applications.services import set_draft_product
from sandbox.applications.services import set_draft_product_by_name
from sandbox.applications.services import update_draft
from sandbox.declarations.selectors import milestone_progress
from sandbox.declarations.services import DECLARABLE_STATES
from sandbox.integrations.credentials import rotate_credentials
from sandbox.integrations.credentials import take_initial_secret
from sandbox.integrations.selectors import CREDENTIAL_STATES
from sandbox.integrations.selectors import credentials_for
from sandbox.integrations.selectors import provisioning_progress
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import url_for
from sandbox.organisations.selectors import is_owner
from sandbox.utils.errors import DomainError
from sandbox.workflow.machine import Action
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import reviews_for_round
from sandbox.workflow.services import transition

if TYPE_CHECKING:
    from django.forms import Form
    from django.http import HttpRequest
    from django_stubs_ext import StrOrPromise

    from sandbox.users.models import User

SCHEMA_VERSION = 1
#: states whose payload the applicant may still edit (mirrors A3's services)
EDITABLE_STATES = (ApplicationState.DRAFT, ApplicationState.SENT_BACK)

STEPS = (
    ("product", "Product"),
    ("details", "Sandbox details"),
    ("review", "Review"),
)

#: States in which an application has milestones worth counting. Everything
#: before PROVISIONED has no sandbox to build against yet.
_HAS_MILESTONES = (
    *DECLARABLE_STATES,
    ApplicationState.EXIT_REQUESTED,
    ApplicationState.EXIT_REVIEW,
    ApplicationState.PRODUCTION_APPROVED,
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
    """Which product. Reached twice: to open a draft, and to correct one.

    The second path is what `external_id` is for. Coming back here without it
    would create a *second* draft on a *second* product of the same name, which
    is what the Back button used to do.
    """

    template_name = "applications/step_product.html"
    form_class = ProductStepForm
    step = "product"
    kwargs: dict[str, Any]

    @cached_property
    def draft(self) -> Application | None:
        external_id = self.kwargs.get("external_id")
        if external_id is None:
            return None
        return get_object_or_404(
            Application.objects.for_organisation(self.organisation),
            external_id=external_id,
        )

    def get_form_kwargs(self):
        draft = self.draft
        return {
            **super().get_form_kwargs(),
            "available_products": products_available_for(
                self.organisation,
                ApplicationKind.SANDBOX,
                keep=draft.product if draft else None,
            ),
            # The product the name box is rendered for, read here rather than
            # posted, so the browser cannot aim a rename at anything else.
            "current": draft.product if draft else None,
        }

    def get_initial(self):
        draft = self.draft
        if draft is None:
            return {}
        # By the time you come back, a product you named is a product you have.
        return {
            "product": str(draft.product.pk),
            "product_name": draft.product.name,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["application"] = self.draft
        return context

    def form_valid(self, form):
        try:
            application = self._apply(form)
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

    def _apply(self, form) -> Application:
        """Open a draft, or move the one already open. Named or existing product."""
        draft = self.draft
        product = form.cleaned_data["selected_product"]
        name = form.cleaned_data["product_name"]

        if draft is None:
            if product:
                return create_draft(
                    organisation=self.organisation,
                    product=product,
                    applicant=self.applicant,
                    kind=ApplicationKind.SANDBOX,
                    data={},
                )
            return create_draft_with_new_product(
                organisation=self.organisation,
                product_name=name,
                applicant=self.applicant,
                kind=ApplicationKind.SANDBOX,
                data={},
            )

        if form.cleaned_data["rename_to"]:
            rename_draft_product(
                application=draft,
                name=form.cleaned_data["rename_to"],
            )
            return draft
        if product:
            return set_draft_product(application=draft, product=product)
        return set_draft_product_by_name(application=draft, product_name=name)


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

    def _refuse_if_locked(self):
        """Only an editable application gets an editor.

        `update_draft` has always refused the write, so nothing could be
        corrupted — but the screen still rendered every field and both buttons
        under a line saying it could no longer be edited, and the save path
        reported success for a write it had just been refused. The read-only
        view already exists; send them to it.

        Checked per handler rather than in `dispatch`, because the application
        cannot be resolved until `OrganisationMixin.dispatch` has run.
        """
        if self.application.state in EDITABLE_STATES:
            return None
        messages.info(
            self.request,
            _("This application can no longer be edited. Here is what was submitted."),
        )
        return redirect(
            url_for(
                "applications:step_review",
                self.organisation,
                external_id=self.application.external_id,
            ),
        )

    def get(self, request, *args, **kwargs):
        return self._refuse_if_locked() or super().get(request, *args, **kwargs)

    def get_form_class(self):
        return payload_form(self.application.kind, SCHEMA_VERSION)

    def get_initial(self):
        return dict(self.application.payload.get("data", {}))

    def post(self, request, *args, **kwargs):
        # "Save and finish later" keeps whatever has been typed, however
        # incomplete; only "Continue" has to satisfy the schema.
        locked = self._refuse_if_locked()
        if locked is not None:
            return locked
        if request.POST.get("action") == "save":
            form = self.get_form()
            form.is_valid()  # populates cleaned_data for the fields that parsed
            if not self._save(form):
                return self.form_invalid(form)
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


class ApplicationIndexView(LoginRequiredMixin, OrganisationMixin, TemplateView):
    """Every application this organisation holds, and the way to add one.

    The integrator's home. Deliberately minimal — it exists so you can choose
    which application you mean, not to summarise any of them; the detail is one
    click away in that application's Overview.

    It replaced a dashboard that narrated whichever application was newest.
    Sandbox access is granted per product, so an organisation holding a live
    sandbox and a fresh draft was shown the draft, on this screen and on every
    nav item beside it.
    """

    template_name = "applications/index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organisation"] = self.organisation
        context["page_title"] = _("Applications")
        context["rows"] = [
            {
                "application": application,
                "is_editable": application.state in EDITABLE_STATES,
                "milestones": (
                    milestone_progress(application)
                    if application.state in _HAS_MILESTONES
                    else None
                ),
            }
            for application in applications_for_organisation(self.organisation)
        ]
        return context


#: Static per state, not computed: v0 has no next-action engine (deferred to P5),
#: so the copy carries the "what now" and nothing pretends to be smarter.
_HINTS: dict[str, tuple[StrOrPromise, StrOrPromise]] = {
    ApplicationState.DRAFT: (
        _("Finish your application"),
        _("Your answers are saved. Pick up where you left off and submit when ready."),
    ),
    ApplicationState.SUBMITTED: (
        _("With the review team"),
        _(
            "A reviewer will read your application and either approve it, ask for "
            "changes, or reject it. You will see the outcome here.",
        ),
    ),
    ApplicationState.SENT_BACK: (
        _("Changes requested"),
        _(
            "A reviewer has asked for changes. Open your application to read their "
            "comments and resubmit.",
        ),
    ),
    ApplicationState.SANDBOX_APPROVED: (
        _("Approved — setting up your access"),
        _("Your sandbox credentials are being created. This page updates itself."),
    ),
    ApplicationState.PROVISIONING: (
        _("Setting up your access"),
        _(
            "We are creating your credentials in the ABDM systems. This page updates "
            "itself.",
        ),
    ),
    ApplicationState.PROVISIONING_FAILED: (
        _("Setup did not complete"),
        _(
            "Something went wrong creating your credentials. The team has been "
            "notified and will retry.",
        ),
    ),
    ApplicationState.PROVISIONED: (
        _("You are in the sandbox"),
        _(
            "Your credentials are ready. Start integrating, then declare your first "
            "milestone when it is complete.",
        ),
    ),
    ApplicationState.EXIT_REQUESTED: (
        _("Exit requested"),
        _("Your exit declaration is with the review team."),
    ),
    ApplicationState.EXIT_REVIEW: (
        _("Exit under review"),
        _("A reviewer is checking your declared milestones and evidence."),
    ),
    ApplicationState.PRODUCTION_APPROVED: (
        _("Approved for production"),
        _("You have completed the sandbox journey."),
    ),
    ApplicationState.REJECTED: (
        _("Application rejected"),
        _(
            "Read the reviewer's comments. You can start a new application for this "
            "product.",
        ),
    ),
    ApplicationState.EXIT_REJECTED: (
        _("Exit rejected"),
        _(
            "Read the reviewer's comments and address them before requesting exit "
            "again.",
        ),
    ),
    ApplicationState.WITHDRAWN: (
        _("Application withdrawn"),
        _("You can start a new application for this product whenever you are ready."),
    ),
}


class ApplicationOverviewView(ApplicationStepMixin, TemplateView):
    """One application's home: where it stands and what to do next.

    Read-only; no state changes from this screen. It is the dashboard's old
    content, now scoped to the application named in the URL rather than to
    whichever one the organisation happened to create last.
    """

    template_name = "applications/overview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.application
        context["page_title"] = application.reference
        context["can_start_new"] = application.state in NON_BLOCKING_STATES
        # Only once there is a sandbox to build against; before that the panel
        # would count zero of six at someone who cannot yet declare any of them.
        context["milestones"] = (
            milestone_progress(application)
            if application.state in DECLARABLE_STATES
            else None
        )
        context.update(_status_context(application))
        return context


class ApplicationStatusView(ApplicationStepMixin, TemplateView):
    """The self-polling fragment. Same truth as a full refresh, just smaller."""

    template_name = "dashboard/partials/application_status.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_status_context(self.application))
        return context


class CredentialsView(ApplicationStepMixin, TemplateView):
    """The Credentials section: the panel, on a page of its own.

    Separate from `CredentialsPanelView` because that one is a fragment for
    htmx to poll — it renders a bare `<div>`, and a nav item pointing at it
    hands the reader a card with no shell around it.
    """

    template_name = "applications/credentials.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = _("Credentials")
        context.update(_credentials_context(self.application, self.request.user))
        return context


class CredentialsPanelView(ApplicationStepMixin, TemplateView):
    """The panel as its own polling fragment while the chain runs (C7).

    GET only, and it never carries a secret: polling is a repeated request, and
    a value that may be shown exactly once cannot live on one.
    """

    template_name = "dashboard/credentials_panel.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(_credentials_context(self.application, self.request.user))
        return context


class RevealCredentialsView(ApplicationStepMixin, TemplateView):
    """Consume the one-time hand-off and render the secret exactly once.

    Deliberately not POST-redirect-GET: the redirect target would have to carry
    the secret in a URL or a session, and both are places it is not allowed to
    be. The cost is that this URL ends up in the address bar, so a refresh
    re-posts — which is correct, because the second POST finds the hand-off gone
    and renders the masked panel.

    GET only ever redirects. It cannot consume anything (consumption lives in
    `post`), and a browser landing here from history or a restored tab should
    meet the credentials page rather than a 405.
    """

    # The credentials page, not the overview: this response *is* the panel
    # carrying the secret, so it has to render the screen that shows one.
    template_name = "applications/credentials.html"

    def get(self, request, *args, **kwargs):
        return redirect(
            url_for(
                "applications:credentials",
                self.organisation,
                external_id=self.application.external_id,
            ),
        )

    def post(self, request, *args, **kwargs):
        secret = take_initial_secret(self.application)
        if secret is None:
            messages.info(
                request,
                _("That secret has already been shown. Rotate to get a new one."),
            )
        return self.render_to_response(
            self.get_context_data(revealed_secret=secret, **kwargs),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organisation"] = self.organisation
        context["can_start_new"] = self.application.state in NON_BLOCKING_STATES
        context.update(_status_context(self.application))
        context.update(_credentials_context(self.application, self.request.user))
        return context


class RotateCredentialsView(RevealCredentialsView):
    """Mint a new secret and show it once, on the same page as the reveal."""

    def post(self, request, *args, **kwargs):
        try:
            secret = rotate_credentials(
                application=self.application,
                actor=cast("User", request.user),
            )
        except DomainError as error:
            messages.error(request, error.message)
            secret = None
        else:
            messages.success(request, _("Your secret has been replaced."))
        return self.render_to_response(
            self.get_context_data(revealed_secret=secret, **kwargs),
        )


def _status_context(application: Application | None) -> dict:
    if application is None:
        return {"journey": [], "is_edge_state": False, "should_poll": False}
    title, body = _HINTS.get(application.state, ("", ""))
    return {
        "journey": journey_for(application.state),
        "is_edge_state": application.state in EDGE_STATES,
        # The trigger stops rendering once nothing else will change on its own.
        "should_poll": application.state in PENDING_STATES,
        "hint_title": title,
        "hint_body": body,
    }


def _credentials_context(application: Application | None, user) -> dict:
    if application is None or application.state not in CREDENTIAL_STATES:
        return {"credentials": None, "provisioning": [], "can_rotate": False}
    return {
        "credentials": credentials_for(application),
        "provisioning": provisioning_progress(application),
        "should_poll_provisioning": (
            application.state == ApplicationState.PROVISIONING
        ),
        "can_rotate": is_owner(application.product.organisation, user),
    }
