"""Organisation screens. State changes go through services (01-backend.md §3.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import cast

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import FormView

from sandbox.catalog.selectors import districts_for_state
from sandbox.organisations.forms import OrganisationCreateForm
from sandbox.organisations.forms import OrganisationProfileForm
from sandbox.organisations.mixins import ORGANISATION_QUERY_PARAM
from sandbox.organisations.mixins import OrganisationMixin
from sandbox.organisations.mixins import organisation_query
from sandbox.organisations.mixins import url_for
from sandbox.organisations.models import Membership
from sandbox.organisations.services import create_organisation
from sandbox.organisations.services import update_organisation_profile

if TYPE_CHECKING:
    from sandbox.users.models import User


def _safe_next(request) -> str:
    next_url = request.GET.get("next") or request.POST.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return ""


def _with_organisation(url: str, organisation) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{organisation_query(organisation)}"


class OrganisationChooseView(LoginRequiredMixin, View):
    """Shown when a multi-org user asks for a screen without saying which org.

    GET only: choosing is a navigation, not a state change, so every option is
    a plain link carrying `?org=`.
    """

    template_name = "organisations/choose.html"

    def get(self, request):
        memberships = Membership.objects.filter(user=request.user).select_related(
            "organisation",
        )
        destination = _safe_next(request) or reverse("applications:dashboard")
        # A `next` that already names an organisation would defeat the point.
        destination = destination.split(f"?{ORGANISATION_QUERY_PARAM}=")[0].split(
            f"&{ORGANISATION_QUERY_PARAM}=",
        )[0]
        return render(
            request,
            self.template_name,
            {
                "options": [
                    {
                        "organisation": membership.organisation,
                        "url": _with_organisation(
                            destination,
                            membership.organisation,
                        ),
                    }
                    for membership in memberships
                ],
            },
        )


class OrganisationCreateView(LoginRequiredMixin, FormView):
    """Sign-up creates a user with no tenant; this is how they get one.

    The full profile is collected here so an incomplete organisation cannot
    exist, and nothing downstream has to guard against one.
    """

    template_name = "organisations/create.html"
    form_class = OrganisationCreateForm

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "reload":
            form = self.form_class(initial=request.POST.dict())
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        organisation = create_organisation(
            creator=cast("User", self.request.user),
            **form.cleaned_data,
        )
        return redirect(url_for("applications:step_product", organisation))


class OrganisationProfileView(LoginRequiredMixin, OrganisationMixin, FormView):
    """Edit the tenant's own facts. Any member may (roles gate nothing yet)."""

    template_name = "organisations/profile.html"
    form_class = OrganisationProfileForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "instance": self.organisation}

    def post(self, request, *args, **kwargs):
        # No-JS dependent select: re-render the bound form so the district list
        # is rebuilt for the state just chosen, without saving a half-filled form.
        if request.POST.get("action") == "reload":
            form = self.form_class(
                instance=self.organisation,
                initial=request.POST.dict(),
            )
            return self.render_to_response(self.get_context_data(form=form))
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["organisation"] = self.organisation
        context["next"] = _safe_next(self.request)
        return context

    def form_valid(self, form):
        update_organisation_profile(
            organisation=self.organisation,
            **form.cleaned_data,
        )
        destination = _safe_next(self.request) or reverse("organisations:profile")
        return redirect(_with_organisation(destination, self.organisation))


class DistrictOptionsView(LoginRequiredMixin, View):
    """htmx dependent select for the profile form. Without JS the "Load
    districts" button re-renders the same list server-side."""

    def get(self, request, *args, **kwargs):
        options = ['<option value="">—</option>']
        options += [
            f'<option value="{code}">{name}</option>'
            for code, name in districts_for_state(request.GET.get("lgd_state_code", ""))
        ]
        return HttpResponse("".join(options))
