from __future__ import annotations

from typing import TYPE_CHECKING

from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView

from sandbox.events.selectors import dashboard_events
from sandbox.experiences.registry import registry
from sandbox.experiences.selectors import application_summary
from sandbox.experiences.selectors import dashboard_activity
from sandbox.experiences.selectors import dashboard_applications
from sandbox.organisations.selectors import get_membership_for
from sandbox.organisations.selectors import milestone_progress
from sandbox.organisations.views import OrganisationMixin
from sandbox.users.permissions import is_console_user

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.http import HttpResponse

# Setup checklist rows on the dashboard. Each is (label, url name, done-flag key).
SETUP_STEPS = [
    (_("Complete your company profile"), "organisations:detail", "profile_complete"),
    (_("Invite your team"), "organisations:team", "team_invited"),
]


class LandingView(TemplateView):
    """Screen 1a's marketing half — the signed-out front door."""

    template_name = "pages/home.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if request.user.is_authenticated:
            destination = resolve_post_login_destination(request.user)
            # A signed-in user with no organisation has nowhere to be sent —
            # show them the marketing page rather than bouncing them in a loop.
            if destination != "home":
                return redirect(destination)
        return super().get(request, *args, **kwargs)


class DashboardView(OrganisationMixin, TemplateView):
    """Screen 1c — where the organisation stands, and what to do next.

    Built around the two things that outlive a session: the applications in
    flight, and the milestones the organisation holds (§3.1). Both are read
    through selectors the application list also uses, so the two screens
    cannot tell an integrator different numbers.
    """

    template_name = "dashboard/dashboard.html"

    def get(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not self.organisation.is_onboarded:
            return redirect("organisations:onboarding")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs) -> dict:
        context = super().get_context_data(**kwargs)
        organisation = self.organisation
        team_size = organisation.memberships.count()
        pending_invites = organisation.invitations.pending().count()

        completed = {
            "profile_complete": organisation.is_onboarded,
            "team_invited": team_size > 1 or pending_invites > 0,
        }
        steps = [
            {
                "label": label,
                "url_name": url_name,
                "done": completed[key],
            }
            for label, url_name, key in SETUP_STEPS
        ]
        done_count = sum(1 for step in steps if step["done"])

        user = self.request.user
        milestones = milestone_progress(organisation)
        context.update(
            {
                "nav_section": "dashboard",
                "team_size": team_size,
                "pending_invites": pending_invites,
                "setup_steps": steps,
                "setup_done": done_count,
                "setup_total": len(steps),
                "setup_percent": round(done_count / len(steps) * 100),
                "applications": dashboard_applications(user, organisation),
                "activity": dashboard_activity(user, organisation),
                "milestones": milestones,
                "milestones_held": sum(1 for item in milestones if item.granted),
                "milestone_total": len(milestones),
                # Offered by name, so the empty state is a way in rather than
                # a pointer at a list to choose from.
                "start_definitions": registry.all(),
                # Events are published to every vendor, so this is not scoped
                # to the organisation — see events.selectors.
                "upcoming_events": dashboard_events(),
                **application_summary(user, organisation),
            },
        )
        return context


def resolve_post_login_destination(user) -> str:
    """Where a freshly signed-in user belongs.

    Most people have exactly one vendor organisation. Staff usually have
    none — the console is their home, so send them there rather than to a
    dashboard that would 403 or a landing page that tells them nothing. Staff
    who also belong to a vendor keep the vendor route; the console is one click
    away in the sidebar.
    """
    membership = get_membership_for(user)
    if membership is None:
        return "staff:queue" if is_console_user(user) else "home"
    if not membership.organisation.is_onboarded:
        return "organisations:onboarding"
    return "dashboard"
