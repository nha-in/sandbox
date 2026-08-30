"""Console views. Thin: they validate input and call Lane A services.

The console has no write path of its own — every state change goes through
`workflow.services.transition()`, so a button can never do something the engine
would refuse.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import View

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.console.forms import DecisionForm
from sandbox.console.forms import ReviewForm
from sandbox.console.mixins import ConsoleMixin
from sandbox.console.selectors import PAGE_SIZE
from sandbox.console.selectors import payload_groups
from sandbox.console.selectors import queue
from sandbox.console.selectors import state_counts
from sandbox.integrations.selectors import CREDENTIAL_STATES
from sandbox.integrations.selectors import provisioning_progress
from sandbox.integrations.services import retry_provisioning
from sandbox.utils.errors import DomainError
from sandbox.workflow.machine import Action
from sandbox.workflow.selectors import available_actions
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import history_for
from sandbox.workflow.selectors import review_tally
from sandbox.workflow.selectors import reviews_for_round
from sandbox.workflow.services import record_review
from sandbox.workflow.services import transition

#: actions the detail page offers; exit actions arrive with A8
DECISION_ACTIONS = (Action.APPROVE, Action.REJECT, Action.SEND_BACK)


class QueueView(ConsoleMixin, ListView):
    template_name = "console/queue.html"
    context_object_name = "applications"

    def get_queryset(self):
        after = self.request.GET.get("after")
        return queue(
            state=self.request.GET.get("state", ""),
            search=self.request.GET.get("q", "").strip(),
            after=int(after) if after and after.isdigit() else None,
        )[: PAGE_SIZE + 1]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = list(context["applications"])
        has_more = len(rows) > PAGE_SIZE
        counts = state_counts(self.request.GET.get("q", "").strip())
        context["applications"] = rows[:PAGE_SIZE]
        context["next_cursor"] = rows[PAGE_SIZE - 1].id if has_more else None
        # shaped here because a template cannot index a dict by a loop variable
        context["state_filters"] = [
            {"value": value, "label": label, "count": counts.get(value, 0)}
            for value, label in ApplicationState.choices
        ]
        context["states"] = ApplicationState.choices
        context["selected_state"] = self.request.GET.get("state", "")
        context["search"] = self.request.GET.get("q", "")
        context["page_title"] = "Review queue"
        return context


class ApplicationDetailView(ConsoleMixin, DetailView):
    template_name = "console/application_detail.html"
    context_object_name = "application"
    slug_field = "external_id"
    slug_url_kwarg = "external_id"

    def get_queryset(self):
        return Application.objects.select_related("product__organisation", "applicant")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.object
        # ConsoleMixin has already refused anonymous, so this is a real user.
        allowed = available_actions(application, self.request.user)  # type: ignore[arg-type]
        context.update(
            {
                "page_title": application.reference,
                "breadcrumbs": [
                    {"label": "Queue", "url": reverse("console:queue")},
                    {"label": application.reference},
                ],
                "payload_groups": payload_groups(application),
                "history": history_for(application),
                "reviews": reviews_for_round(application),
                "tally": review_tally(application),
                "round": current_round(application),
                "review_form": ReviewForm(),
                "decision_actions": [a for a in DECISION_ACTIONS if a in allowed],
                "can_review": self.request.user.has_perm("workflow.review_application"),
                # Status only. There is no reveal route on this surface, and no
                # staff-facing path to a secret anywhere in the system.
                "provisioning": (
                    provisioning_progress(application)
                    if application.state in CREDENTIAL_STATES
                    else []
                ),
                "can_retry_provisioning": Action.RETRY_PROVISIONING in allowed,
            },
        )
        return context


class ApplicationActionView(ConsoleMixin, View):
    """POST-only base: resolves the application and returns to its detail page."""

    def get_application(self):
        return get_object_or_404(
            Application,
            external_id=self.kwargs["external_id"],
        )

    def back_to(self, application):
        return redirect(
            reverse(
                "console:application_detail",
                kwargs={"external_id": application.external_id},
            ),
        )


class RecordReviewView(ApplicationActionView):
    def post(self, request, *args, **kwargs):
        application = self.get_application()
        form = ReviewForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self.back_to(application)

        try:
            record_review(
                application=application,
                reviewer=request.user,
                decision=form.cleaned_data["decision"],
                comment=form.cleaned_data["comment"],
            )
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(request, "Review recorded.")
        return self.back_to(application)


class DecideView(ApplicationActionView):
    """Approve / reject / send back.

    A supplied comment is recorded as the actor's review row first, because A5
    refuses a comment on a review-driven transition — the review row is the
    single home for that text.
    """

    def post(self, request, *args, **kwargs):
        application = self.get_application()
        form = DecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self.back_to(application)

        action = Action(form.cleaned_data["action"])
        comment = form.cleaned_data["comment"]

        try:
            if comment:
                record_review(
                    application=application,
                    reviewer=request.user,
                    decision=action.value,
                    comment=comment,
                )
            transition(application=application, action=action, actor=request.user)
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                f"{application.reference} moved to {application.state}.",
            )
        return self.back_to(application)


class RetryProvisioningView(ApplicationActionView):
    """Re-run a failed chain. The console's only credentials-adjacent action —
    it moves the application, it does not read anything."""

    def post(self, request, *args, **kwargs):
        application = self.get_application()
        try:
            retry_provisioning(application=application, actor=request.user)
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                f"Provisioning restarted for {application.reference}.",
            )
        return self.back_to(application)
