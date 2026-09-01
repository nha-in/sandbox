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

from sandbox.applications.documents import download_url
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationState
from sandbox.console.forms import DecisionForm
from sandbox.console.forms import ReviewForm
from sandbox.console.mixins import ConsoleMixin
from sandbox.console.selectors import PAGE_SIZE
from sandbox.console.selectors import exit_review
from sandbox.console.selectors import payload_groups
from sandbox.console.selectors import queue
from sandbox.console.selectors import registered_solution_types
from sandbox.console.selectors import state_counts
from sandbox.integrations.selectors import CREDENTIAL_STATES
from sandbox.integrations.selectors import provisioning_progress
from sandbox.integrations.services import retry_provisioning
from sandbox.programmes.abdm import ExitDecisionForm
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.registry import get_workflow
from sandbox.workflow.registry import workflows_visible_to
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import decidable_actions
from sandbox.workflow.selectors import history_for
from sandbox.workflow.selectors import is_reviewable
from sandbox.workflow.selectors import review_tally
from sandbox.workflow.selectors import reviews_for_round
from sandbox.workflow.services import record_review

#: actions the detail page offers as a decision button. `START_REVIEW` is not
#: among them: claiming the work is not an opinion, and offering it beside the
#: verdicts put the approval paperwork on screen to support "start review".
DECISION_ACTIONS = frozenset(
    {
        "APPROVE",
        "REJECT",
        "SEND_BACK",
    },
)

START_REVIEW = "START_REVIEW"

#: a button must never read START_REVIEW at a person
ACTION_LABELS = {
    "APPROVE": "Approve",
    "REJECT": "Reject",
    "SEND_BACK": "Send back",
    START_REVIEW: "Start review",
}

#: actions rendered in the destructive style
_DESTRUCTIVE_ACTIONS = frozenset({"REJECT"})

EXIT_WORKFLOW = "ABDM_EXIT"

#: the opinion each decision expresses, shared by both workflows
REVIEW_DECISION_FOR_ACTION = {
    "APPROVE": ReviewDecision.APPROVE,
    "REJECT": ReviewDecision.REJECT,
    "SEND_BACK": ReviewDecision.SEND_BACK,
}


class QueueView(ConsoleMixin, ListView):
    template_name = "console/queue.html"
    context_object_name = "applications"

    def get_queryset(self):
        after = self.request.GET.get("after")
        return queue(
            visible=workflows_visible_to(self.request.user),
            state=self.request.GET.get("state", ""),
            search=self.request.GET.get("q", "").strip(),
            after=int(after) if after and after.isdigit() else None,
        )[: PAGE_SIZE + 1]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = list(context["applications"])
        has_more = len(rows) > PAGE_SIZE
        counts = state_counts(
            workflows_visible_to(self.request.user),
            self.request.GET.get("q", "").strip(),
        )
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
        # Another programme's application is not found, not forbidden: a 403
        # would confirm the reference exists.
        return Application.objects.filter(
            workflow_key__in=workflows_visible_to(self.request.user),
        ).select_related("product__organisation", "applicant")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.object
        is_exit = application.workflow_key == EXIT_WORKFLOW
        # ConsoleMixin has already refused anonymous, so this is a real user.
        allowed = decidable_actions(application, self.request.user)  # type: ignore[arg-type]
        decisions = [action for action in allowed if action in DECISION_ACTIONS]
        # Approving an exit takes EXIT_DECISION with it, so that button has to
        # sit with those fields rather than beside buttons that ignore them.
        approve_spec = get_workflow(application.workflow_key).transitions.get(
            (application.state, "APPROVE"),
        )
        approve_apart = bool(approve_spec and approve_spec.decision_form_key)
        ceiling = registered_solution_types(application) if approve_apart else []
        context.update(
            {
                "page_title": application.reference,
                "breadcrumbs": [
                    {"label": "Queue", "url": reverse("console:queue")},
                    {"label": application.reference},
                ],
                "is_exit": is_exit,
                "exit_review": exit_review(application) if is_exit else None,
                "payload_groups": [] if is_exit else payload_groups(application),
                "history": history_for(application),
                "reviews": reviews_for_round(application),
                "tally": review_tally(application),
                "round": current_round(application),
                "review_form": ReviewForm(),
                "can_start_review": START_REVIEW in allowed,
                "start_review_label": ACTION_LABELS[START_REVIEW],
                "decision_actions": [
                    {
                        "value": action,
                        "label": ACTION_LABELS[action],
                        "is_destructive": action in _DESTRUCTIVE_ACTIONS,
                    }
                    for action in decisions
                    if not (approve_apart and action == "APPROVE")
                ],
                "approve_action": (
                    {"value": "APPROVE", "label": ACTION_LABELS["APPROVE"]}
                    if approve_apart and "APPROVE" in decisions
                    else None
                ),
                # An empty ceiling makes the required field unsatisfiable, so
                # say why rather than render a form nobody can submit.
                "approval_blocked": approve_apart and not ceiling,
                # A review is refused outside a state a verdict can be taken
                # from; the panel used to be offered on the permission alone.
                "can_review": (
                    self.request.user.has_perm(
                        get_workflow(application.workflow_key).review_permission,
                    )
                    and is_reviewable(application)
                ),
                # Status only. There is no reveal route on this surface, and no
                # staff-facing path to a secret anywhere in the system.
                "provisioning": (
                    provisioning_progress(application)
                    if application.state in CREDENTIAL_STATES
                    else []
                ),
                "can_retry_provisioning": "RETRY_PROVISIONING" in allowed,
            },
        )
        return context


class ApplicationActionView(ConsoleMixin, View):
    """POST-only base: resolves the application and returns to its detail page."""

    def get_application(self):
        return get_object_or_404(
            Application.objects.filter(
                workflow_key__in=workflows_visible_to(self.request.user),
            ),
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
    """Approve / reject / send back, on the sandbox review and on the exit.

    A supplied comment is recorded as the actor's review row first, because A5
    refuses a comment on a review-driven transition — the review row is the
    single home for that text. `START_REVIEW` expresses no opinion, so its
    comment rides on the transition instead, which is the other home the schema
    allows ("only when no review behind it").
    """

    def post(self, request, *args, **kwargs):
        application = self.get_application()
        form = DecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, form.errors.as_text())
            return self.back_to(application)

        try:
            self._decide(
                request,
                application,
                form.cleaned_data["action"],
                form.cleaned_data["comment"],
            )
        except DomainError as error:
            messages.error(request, error.message)
        else:
            messages.success(
                request,
                f"{application.reference} moved to {application.state}.",
            )
        return self.back_to(application)

    def _decide(self, request, application, action: str, comment: str) -> None:
        workflow = get_workflow(application.workflow_key)
        spec = workflow.transitions.get((application.state, action))
        if spec is None:
            message = f"{action} is not available from {application.state}"
            raise DomainError(message, code="illegal_transition")

        decision = REVIEW_DECISION_FOR_ACTION.get(action)
        if decision is not None and comment:
            record_review(
                application=application,
                reviewer=request.user,
                decision=decision,
                comment=comment,
            )

        decision_data = None
        if spec.decision_form_key:
            decision_form = ExitDecisionForm(
                request.POST,
                registered_choices=registered_solution_types(application),
            )
            if not decision_form.is_valid():
                messages.error(request, decision_form.errors.as_text())
                return
            decision_data = decision_form.cleaned_data

        engine.transition(
            application=application,
            action=action,
            actor=request.user,
            # a review-driven move's text lives on the review row, not here
            comment="" if spec.review_driven else comment,
            decision_data=decision_data,
        )


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


class DocumentDownloadView(ConsoleMixin, View):
    """A reviewer's way to the evidence — deliberately not the integrator's.

    `applications:document_download` scopes by organisation membership, which a
    reviewer does not have. Rather than teach that view a second authorization
    rule, this one looks the document up across every organisation and leans on
    `ConsoleMixin`. Two audiences, two rules, two routes.

    Staff-but-no-permission is the whole gate on purpose: the detail page it is
    reached from already names these files to anyone who can open it, so a
    stricter rule here would 404 the link that page renders.
    """

    def get(self, request, external_id):
        document = get_object_or_404(ApplicationDocument, external_id=external_id)
        return redirect(download_url(document))
