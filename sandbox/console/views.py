"""Console views. Thin: they validate input and call Lane A services.

The console has no write path of its own — every state change goes through
`workflow.services.transition()`, so a button can never do something the engine
would refuse.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import View

from sandbox.applications.documents import download_url
from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationDocument
from sandbox.applications.models import ApplicationState
from sandbox.applications.selectors import approval_outcomes
from sandbox.applications.selectors import current_form_data
from sandbox.console.forms import DecisionForm
from sandbox.console.forms import ReviewForm
from sandbox.console.forms import RoleForm
from sandbox.console.forms import UserRolesForm
from sandbox.console.mixins import ConsoleMixin
from sandbox.console.selectors import PAGE_SIZE
from sandbox.console.selectors import asking_for
from sandbox.console.selectors import exit_review
from sandbox.console.selectors import humanised_history
from sandbox.console.selectors import payload_groups
from sandbox.console.selectors import queue
from sandbox.console.selectors import queue_rows
from sandbox.console.selectors import registered_solution_types
from sandbox.console.selectors import review_subtitle
from sandbox.console.selectors import reviewer_flags
from sandbox.console.selectors import state_counts
from sandbox.console.services import delete_role
from sandbox.console.services import save_role
from sandbox.console.services import set_user_roles
from sandbox.integrations.selectors import CREDENTIAL_STATES
from sandbox.integrations.selectors import provisioning_progress
from sandbox.integrations.services import retry_provisioning
from sandbox.programmes.abdm import ExitDecisionForm
from sandbox.users.models import User
from sandbox.utils.errors import DomainError
from sandbox.workflow import engine
from sandbox.workflow.models import ReviewDecision
from sandbox.workflow.registry import get_workflow
from sandbox.workflow.registry import workflows_visible_to
from sandbox.workflow.selectors import current_round
from sandbox.workflow.selectors import decidable_actions
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

#: the button style each decision carries. Send back is not destructive — the
#: work comes back — but it is not the plain forward move either.
_ACTION_VARIANTS = {"REJECT": "destructive", "SEND_BACK": "warning"}

#: What each outcome costs the applicant. Stated beside the option itself,
#: because the asymmetry between send back and reject is the thing a reviewer
#: most needs before choosing (09-redesign §5.3).
_EXIT_CONSEQUENCES = {
    "APPROVE": _(
        "Grants production for the solution types you tick below. Never revoked.",
    ),
    "REJECT": _(
        "A new round, and a major fix voids the Safe-to-Host certificate — a "
        "fresh audit before they can try again.",
    ),
    "SEND_BACK": _(
        "Minutes for the applicant. The claim reopens, the round stays, and "
        "the certificate is retained.",
    ),
}

_ENROLMENT_CONSEQUENCES = {
    "APPROVE": _("Provisioning starts and credentials are issued."),
    "REJECT": _("Closes this application. They would start a new one."),
    "SEND_BACK": _("Returns it for edits. The round does not advance."),
}

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
        context["rows"] = queue_rows(rows[:PAGE_SIZE])
        context["over_target"] = sum(1 for row in context["rows"] if row.is_over_target)
        context["longest_wait"] = max(
            (row.waiting_days for row in context["rows"] if row.waiting_days),
            default=0,
        )
        context["review_target_days"] = settings.REVIEW_TARGET_DAYS
        context["next_cursor"] = rows[PAGE_SIZE - 1].id if has_more else None
        # shaped here because a template cannot index a dict by a loop variable
        context["state_filters"] = [
            {"value": value, "label": label, "count": counts.get(value, 0)}
            for value, label in ApplicationState.choices
        ]
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
                # Who and what, not the reference: a reviewer arrived here by
                # clicking that reference and already knows it.
                "page_title": _("%(organisation)s — %(asking_for)s")
                % {
                    "organisation": application.product.organisation.name,
                    "asking_for": asking_for(application),
                },
                "page_subtitle": review_subtitle(application),
                "breadcrumbs": [
                    {"label": "Queue", "url": reverse("console:queue")},
                    {"label": application.reference},
                ],
                "is_exit": is_exit,
                "exit_review": exit_review(application) if is_exit else None,
                "payload_groups": [] if is_exit else payload_groups(application),
                "history": humanised_history(application),
                "flags": reviewer_flags(application) if is_exit else [],
                "outcomes": (
                    approval_outcomes(
                        application,
                        current_form_data(application, "EXIT_CLAIM").get("covers", []),
                    )
                    if is_exit
                    else []
                ),
                "reviews": reviews_for_round(application),
                "tally": [
                    {"label": ReviewDecision(decision).label, "count": count}
                    for decision, count in review_tally(application).items()
                ],
                "round": current_round(application),
                "review_form": ReviewForm(),
                "can_start_review": START_REVIEW in allowed,
                "start_review_label": ACTION_LABELS[START_REVIEW],
                "decision_choices": [
                    {
                        "value": action,
                        "label": ACTION_LABELS[action],
                        "variant": _ACTION_VARIANTS.get(action, "default"),
                        "consequence": (
                            _EXIT_CONSEQUENCES if is_exit else _ENROLMENT_CONSEQUENCES
                        ).get(action, ""),
                    }
                    for action in decisions
                ],
                # Approving an exit carries EXIT_DECISION, so the screen has
                # fields that belong to one option alone and are revealed by it.
                "approval_fields": approve_apart and "APPROVE" in decisions,
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
        document = get_object_or_404(
            ApplicationDocument.objects.filter(
                submission__application__workflow_key__in=workflows_visible_to(
                    request.user,
                ),
            ),
            external_id=external_id,
        )
        return redirect(download_url(document))


class RoleMixin(ConsoleMixin):
    """Editing a role is authority over authority, so it has its own gate."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.has_perm(
            "users.manage_roles",
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def back_to_roles(self):
        return redirect(reverse("console:roles"))


class RoleListView(RoleMixin, ListView):
    """Every console role, and the form that adds one."""

    template_name = "console/roles.html"
    context_object_name = "roles"

    def get_queryset(self):
        return (
            Group.objects.prefetch_related("permissions")
            .annotate(member_count=Count("user"))
            .order_by("name")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Roles"
        context["form"] = kwargs.get("form") or RoleForm()
        return context

    def post(self, request, *args, **kwargs):
        form = RoleForm(request.POST)
        if not form.is_valid():
            self.object_list = self.get_queryset()
            return self.render_to_response(self.get_context_data(form=form))
        role = save_role(form=form, actor=request.user, creating=True)
        messages.success(request, f"Role {role.name} created.")
        return self.back_to_roles()


class RoleDetailView(RoleMixin, DetailView):
    """One role: rename it, and change what it grants."""

    template_name = "console/role_detail.html"
    context_object_name = "role"
    model = Group

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.name
        context["breadcrumbs"] = [
            {"label": "Roles", "url": reverse("console:roles")},
            {"label": self.object.name},
        ]
        context["form"] = kwargs.get("form") or RoleForm(instance=self.object)
        context["members"] = self.object.user_set.order_by("email")
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if request.POST.get("action") == "delete":
            name = self.object.name
            delete_role(role=self.object, actor=request.user)
            messages.success(request, f"Role {name} deleted.")
            return self.back_to_roles()

        form = RoleForm(request.POST, instance=self.object)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        save_role(form=form, actor=request.user, creating=False)
        messages.success(request, "Role updated.")
        return self.back_to_roles()


class UserListView(RoleMixin, ListView):
    """Console users and what each of them holds."""

    template_name = "console/users.html"
    context_object_name = "console_users"

    def get_queryset(self):
        people = User.objects.filter(is_staff=True).prefetch_related("groups")
        search = self.request.GET.get("q", "").strip()
        if search:
            people = people.filter(
                Q(email__icontains=search) | Q(name__icontains=search),
            )
        return people.order_by("email")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Console users"
        context["search"] = self.request.GET.get("q", "")
        return context


class UserRolesView(RoleMixin, DetailView):
    """Give one person their roles. The direction an administrator works in."""

    template_name = "console/user_detail.html"
    context_object_name = "console_user"
    slug_field = "external_id"
    slug_url_kwarg = "external_id"

    def get_queryset(self):
        return User.objects.filter(is_staff=True)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.object.email
        context["breadcrumbs"] = [
            {"label": "Console users", "url": reverse("console:users")},
            {"label": self.object.email},
        ]
        context["form"] = kwargs.get("form") or UserRolesForm(user=self.object)
        context["granted"] = sorted(
            Permission.objects.filter(group__user=self.object)
            .distinct()
            .values_list("name", flat=True),
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = UserRolesForm(request.POST, user=self.object)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        set_user_roles(
            user=self.object,
            roles=form.cleaned_data["roles"],
            actor=request.user,
        )
        messages.success(request, f"Roles updated for {self.object.email}.")
        return redirect(reverse("console:users"))
