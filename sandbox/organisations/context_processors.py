"""Active-organisation context for the integrator shell."""

from __future__ import annotations

from sandbox.organisations.mixins import ORGANISATION_QUERY_PARAM
from sandbox.organisations.mixins import organisation_query
from sandbox.organisations.models import Membership


def active_organisation(request):
    """The shell needs to name the tenant being acted on, and offer a way out.

    Mirrors `OrganisationMixin`: the organisation comes from `?org=`, and is
    only inferred when the user belongs to exactly one.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    memberships = list(
        Membership.objects.filter(user=user).select_related("organisation"),
    )
    if not memberships:
        return {}

    requested = request.GET.get(ORGANISATION_QUERY_PARAM)
    active = next(
        (
            m.organisation
            for m in memberships
            if str(m.organisation.external_id) == requested
        ),
        memberships[0].organisation if len(memberships) == 1 else None,
    )
    return {
        "is_organisation_member": True,
        "active_organisation": active,
        "org_query": f"?{organisation_query(active)}" if active else "",
        "has_multiple_organisations": len(memberships) > 1,
    }
