"""Shell context: which tenant is being acted on, and where in the nav we are."""

from __future__ import annotations

from sandbox.organisations.mixins import ORGANISATION_QUERY_PARAM
from sandbox.organisations.mixins import organisation_query
from sandbox.organisations.models import Membership

#: view name -> the sidebar item that should read as current.
#:
#: Derived here rather than set in each view on purpose: a view that forgets to
#: set it renders a sidebar with nothing highlighted, and that is a silent
#: defect nobody notices in review. A missing row here is loud instead —
#: tests/test_navigation.py walks every live URL and fails on any that is
#: neither mapped nor deliberately listed as chrome-less.
#:
#: A view may still override by putting `nav_section` in its own context; the
#: view's dict is pushed after the processors', so it wins.
NAV_SECTIONS: dict[str, str] = {
    "applications:index": "applications",
    "applications:overview": "overview",
    "applications:application_status": "overview",
    "applications:credentials": "credentials",
    "applications:credentials_panel": "credentials",
    "applications:reveal_credentials": "credentials",
    "applications:rotate_credentials": "credentials",
    "applications:step_product": "applications",
    "applications:step_product_edit": "details",
    "applications:step_details": "details",
    "applications:step_review": "details",
    "applications:milestones": "milestones",
    "applications:declare_milestone": "milestones",
    "applications:exit": "exit",
    "applications:exit_claim": "exit",
    "applications:exit_wasa": "exit",
    "applications:exit_review": "exit",
    # DHIS is what an approved exit unlocks, so it belongs to the same section
    "applications:dhis": "exit",
    "organisations:profile": "settings",
    "organisations:choose": "organisations",
    "organisations:create": "organisation_create",
    "users:detail": "settings",
    "users:update": "settings",
    "console:queue": "queue",
    "console:application_detail": "queue",
}

#: view name -> the settings tab that should read as current.
SETTINGS_SECTIONS: dict[str, str] = {
    "organisations:profile": "organisation",
    "users:detail": "profile",
    "users:update": "profile",
}


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


def navigation(request):
    """Which sidebar item and settings tab are current, plus a breadcrumb slot.

    `breadcrumbs` defaults to empty and is filled by the views that have
    something to name — a crumb trail is built from objects the processor
    cannot see (an application's reference), so it cannot be tabulated here.
    An empty list renders no bar at all rather than an orphaned one.
    """
    match = getattr(request, "resolver_match", None)
    view_name = match.view_name if match else ""
    return {
        "nav_section": NAV_SECTIONS.get(view_name, ""),
        "settings_section": SETTINGS_SECTIONS.get(view_name, ""),
        "breadcrumbs": [],
    }
