"""Views never write state (01-backend.md §3.2) — this one only touches the session."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from sandbox.organisations.mixins import ACTIVE_ORGANISATION_SESSION_KEY
from sandbox.organisations.models import Membership


class OrganisationSwitchView(LoginRequiredMixin, View):
    """Lets a multi-membership user pick their active org for this session."""

    template_name = "organisations/switch.html"

    def _safe_next(self, request) -> str:
        next_url = request.GET.get("next") or request.POST.get("next") or ""
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return next_url
        return reverse("home")

    def get(self, request):
        memberships = Membership.objects.filter(user=request.user).select_related(
            "organisation",
        )
        return render(
            request,
            self.template_name,
            {"memberships": memberships, "next": self._safe_next(request)},
        )

    def post(self, request):
        memberships = Membership.objects.filter(user=request.user).select_related(
            "organisation",
        )
        selected = memberships.filter(
            organisation__external_id=request.POST.get("organisation"),
        ).first()
        if selected is None:
            return HttpResponseBadRequest("Not a member of that organisation.")

        request.session[ACTIVE_ORGANISATION_SESSION_KEY] = selected.organisation_id
        return redirect(self._safe_next(request))
