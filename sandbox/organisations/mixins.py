"""OrganisationMixin — the authz backbone every integrator-facing view sits on.

Resolves the active organisation from session + membership; consuming views
build their querysets via `<Model>.objects.for_organisation(self.organisation)`
so records outside it 404 (never 403 — a 403 would confirm the record exists).
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from sandbox.organisations.models import Membership
from sandbox.organisations.models import Organisation

ACTIVE_ORGANISATION_SESSION_KEY = "active_organisation_id"


class OrganisationMixin:
    """Mix in before the view class; sets `self.organisation` in `dispatch()`."""

    organisation: Organisation

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise Http404

        memberships = list(
            Membership.objects.filter(user=request.user).select_related("organisation"),
        )
        if not memberships:
            raise Http404

        organisation = self._active_organisation(request, memberships)
        if organisation is None:
            return self._redirect_to_switcher(request)

        self.organisation = organisation
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def _active_organisation(
        self,
        request,
        memberships: list[Membership],
    ) -> Organisation | None:
        active_id = request.session.get(ACTIVE_ORGANISATION_SESSION_KEY)
        for membership in memberships:
            if membership.organisation_id == active_id:
                return membership.organisation

        if len(memberships) == 1:
            only_membership = memberships[0]
            request.session[ACTIVE_ORGANISATION_SESSION_KEY] = (
                only_membership.organisation_id
            )
            return only_membership.organisation

        return None

    def _redirect_to_switcher(self, request):
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{reverse('organisations:switch')}?{query}")
