"""OrganisationMixin — the authz backbone every integrator-facing view sits on.

The active organisation is carried in the `?org=` query string, not the session:
one browser tab must not silently change what another tab is writing to, and a
URL should say which tenant it acts on.

Consuming views build their querysets via
`<Model>.objects.for_organisation(self.organisation)` so records outside it 404
(never 403 — a 403 would confirm the record exists).
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse

from sandbox.organisations.models import Membership
from sandbox.organisations.models import Organisation

ORGANISATION_QUERY_PARAM = "org"


def organisation_query(organisation: Organisation) -> str:
    """`?org=…` for links and redirects that must stay inside one tenant."""
    return urlencode({ORGANISATION_QUERY_PARAM: str(organisation.external_id)})


def url_for(view_name: str, organisation: Organisation, **kwargs) -> str:
    return f"{reverse(view_name, kwargs=kwargs)}?{organisation_query(organisation)}"


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

        organisation = self._requested_organisation(request, memberships)
        if organisation is None:
            return self._redirect_to_picker(request)

        self.organisation = organisation
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def _requested_organisation(
        self,
        request,
        memberships: list[Membership],
    ) -> Organisation | None:
        requested = request.GET.get(ORGANISATION_QUERY_PARAM)
        if requested:
            for membership in memberships:
                if str(membership.organisation.external_id) == requested:
                    return membership.organisation
            # Asking for an organisation you are not in is indistinguishable
            # from one that does not exist.
            raise Http404

        # No parameter. Inferring is only safe when there is nothing to infer —
        # a dropped `?org=` must never write to the wrong tenant.
        if len(memberships) == 1:
            return memberships[0].organisation
        return None

    def _redirect_to_picker(self, request):
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{reverse('organisations:choose')}?{query}")
