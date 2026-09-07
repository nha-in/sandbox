"""Route-gate matrix — the authz proof for every URL in the portal (C3).

## How to add a row

Every named URL must appear in `ROUTES`, or this module fails with the URL name
and this docstring. Adding a screen means adding one line:

    "applications:detail": Route(Access.ORG_SCOPED, kwargs=application_kwargs),

Pick the `Access` that states the rule you intend, not the behaviour you happen
to have; the assertions below are derived from it and are what make the rule
true. If a URL needs captured arguments, pass `kwargs` — either a dict, or a
callable taking the `actors`/objects context so a wrong-organisation row
genuinely targets another organisation's object.

Legacy authorization was `permitAll()` on every GET plus client-side role checks
in a React bundle. The rule here is that no view ships without a row, and the
matrix is mechanically complete because the suite diffs it against the live
URLconf.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING
from typing import Any

import pytest
from django.test import Client
from django.urls import URLResolver
from django.urls import get_resolver
from django.urls import reverse

from tests.conftest import ANONYMOUS
from tests.conftest import APPLICATION
from tests.conftest import ATTACHMENT
from tests.conftest import EVENT
from tests.conftest import INVITATION
from tests.conftest import MEMBER_OTHER_ORG
from tests.conftest import MEMBERSHIP
from tests.conftest import ORG_MEMBER
from tests.conftest import QUERY
from tests.conftest import STAFF_ACTORS
from tests.conftest import TICKET

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
REDIRECT_CODES = frozenset({301, 302})
DENIED_CODES = frozenset({HTTP_FORBIDDEN, HTTP_NOT_FOUND})
GROUPED_PREFIXES = ("admin:",)


class Access(enum.StrEnum):
    """The rule a URL is claiming. Assertions are derived from this."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    SELF_RESOURCE = "self_resource"
    SELF_ONLY = "self_only"
    #: A vendor surface with no tenant in the URL: each member reaches their
    #: own organisation's, and an actor with no organisation cannot.
    TENANT_MEMBER = "tenant_member"
    ORG_SCOPED = "org_scoped"
    #: Reviewers read evidence through the vendor URL by design — see
    #: `ApplicationInstance.objects.visible_to`.
    MEMBER_OR_CONSOLE = "member_or_console"
    CONSOLE = "console"
    #: Exists only on a development machine. 404 for everyone under any
    #: settings where DEBUG is off, which is every deployed environment.
    DEVELOPMENT_ONLY = "development_only"


@dataclass(frozen=True)
class Route:
    access: Access
    kwargs: dict[str, Any] | Callable[[dict], dict] = field(default_factory=dict)
    methods: tuple[str, ...] = ("GET",)
    #: POSTed with the request. Some endpoints guard on the form itself, and an
    #: empty body would then be refused for every actor alike, telling us
    #: nothing about who may reach it.
    data: dict[str, Any] = field(default_factory=dict)
    known_gap: str = ""


def _reference(context: dict) -> dict:
    return {"reference": context[APPLICATION].reference}


def _form(context: dict) -> dict:
    return {"reference": context[APPLICATION].reference, "form_key": "declaration"}


def _form_action(context: dict) -> dict:
    return {**_form(context), "form_action_key": "none"}


def _action(context: dict) -> dict:
    return {
        "reference": context[APPLICATION].reference,
        "action_key": "ask_review_team",
    }


def _console_action(context: dict) -> dict:
    return {"reference": context[APPLICATION].reference, "action_key": "approve"}


def _query(context: dict) -> dict:
    return {
        "reference": context[APPLICATION].reference,
        "query_pk": context[QUERY].pk,
    }


def _attachment(context: dict) -> dict:
    return {
        "reference": context[APPLICATION].reference,
        "attachment_pk": context[ATTACHMENT].pk,
    }


def _access_user(context: dict) -> dict:
    return {
        "reference": context[APPLICATION].reference,
        "user_pk": context[MEMBERSHIP].user_id,
    }


def _membership_pk(context: dict) -> dict:
    return {"pk": context[MEMBERSHIP].pk}


def _invitation_pk(context: dict) -> dict:
    return {"pk": context[INVITATION].pk}


def _invitation_token(context: dict) -> dict:
    return {"token": context[INVITATION].token}


def _ticket(context: dict) -> dict:
    return {"reference": context[TICKET].reference}


def _event_slug(context: dict) -> dict:
    return {"slug": context[EVENT].slug}


def _organisation_slug(context: dict) -> dict:
    return {"slug": context[APPLICATION].organisation.slug}


def _member_pk(context: dict) -> dict:
    return {"pk": context[ORG_MEMBER].pk}


# The matrix. One row per named URL; django-admin is asserted as a group below.
ROUTES: dict[str, Route] = {
    # Marketing
    "home": Route(Access.PUBLIC),
    "about": Route(Access.PUBLIC),
    # Account — anonymous must be able to reach these to get in at all
    "account_login": Route(Access.PUBLIC),
    "account_signup": Route(Access.PUBLIC),
    "account_logout": Route(Access.PUBLIC),
    "account_inactive": Route(Access.PUBLIC),
    "account_reset_password": Route(Access.PUBLIC),
    "account_reset_password_done": Route(Access.PUBLIC),
    "account_reset_password_from_key": Route(
        Access.PUBLIC,
        kwargs={"uidb36": "0", "key": "set-password"},
    ),
    "account_reset_password_from_key_done": Route(Access.PUBLIC),
    "account_confirm_email": Route(Access.PUBLIC, kwargs={"key": "invalid-key"}),
    "account_email_verification_sent": Route(Access.PUBLIC),
    "account_confirm_login_code": Route(Access.AUTHENTICATED),
    # Account — signed-in surfaces
    "account_email": Route(Access.AUTHENTICATED),
    "account_change_password": Route(Access.AUTHENTICATED),
    "account_set_password": Route(Access.AUTHENTICATED),
    "account_reauthenticate": Route(Access.AUTHENTICATED),
    # MFA. The device-bound ones 404 for a user who has no device, which is why
    # they are SELF_RESOURCE: reviewer and staff hold TOTP and must reach them.
    "mfa_index": Route(Access.AUTHENTICATED),
    "mfa_activate_totp": Route(Access.AUTHENTICATED),
    "mfa_deactivate_totp": Route(Access.SELF_RESOURCE),
    "mfa_authenticate": Route(Access.AUTHENTICATED),
    "mfa_reauthenticate": Route(Access.AUTHENTICATED),
    "mfa_generate_recovery_codes": Route(Access.AUTHENTICATED),
    "mfa_view_recovery_codes": Route(Access.SELF_RESOURCE),
    "mfa_download_recovery_codes": Route(Access.SELF_RESOURCE),
    # Social account — installed but unused
    "socialaccount_connections": Route(Access.AUTHENTICATED),
    "socialaccount_login_cancelled": Route(Access.PUBLIC),
    "socialaccount_login_error": Route(Access.PUBLIC),
    "socialaccount_signup": Route(Access.AUTHENTICATED),
    # The vendor shell
    "dashboard": Route(Access.TENANT_MEMBER),
    "users:redirect": Route(Access.AUTHENTICATED),
    # A bare redirect stub with no gate of its own; the page it lands on has
    # one. Public because that is what it is, not because it should serve
    # anyone anything.
    "users:update": Route(Access.PUBLIC),
    "users:profile": Route(Access.AUTHENTICATED),
    # A RedirectView to your own profile, kept so `get_absolute_url` resolves.
    # It never serves another user's anything, so the id in the URL is inert.
    "users:detail": Route(Access.AUTHENTICATED, kwargs=_member_pk),
    "organisations:onboarding": Route(Access.TENANT_MEMBER),
    # Each actor reaches their *own* organisation here, so the gate is
    # membership rather than a named tenant.
    "organisations:detail": Route(Access.TENANT_MEMBER),
    "organisations:team": Route(Access.TENANT_MEMBER),
    # These name org A's rows, so only org A's member may act on them.
    "organisations:member-role": Route(
        Access.ORG_SCOPED,
        kwargs=_membership_pk,
        methods=("POST",),
    ),
    "organisations:member-remove": Route(
        Access.ORG_SCOPED,
        kwargs=_membership_pk,
        methods=("POST",),
    ),
    "organisations:invitation-resend": Route(
        Access.ORG_SCOPED,
        kwargs=_invitation_pk,
        methods=("POST",),
    ),
    "organisations:invitation-revoke": Route(
        Access.ORG_SCOPED,
        kwargs=_invitation_pk,
        methods=("POST",),
    ),
    # The token is the credential, and an invitee usually has no account yet:
    # the view stashes the token and sends them to sign up.
    "organisations:invitation-accept": Route(
        Access.PUBLIC,
        kwargs=_invitation_token,
    ),
    # Applications
    "experiences:list": Route(Access.TENANT_MEMBER),
    "experiences:start": Route(
        Access.TENANT_MEMBER,
        kwargs={"application_type": "abdm_production_access"},
    ),
    "experiences:detail": Route(Access.ORG_SCOPED, kwargs=_reference),
    "experiences:form": Route(Access.ORG_SCOPED, kwargs=_form),
    "experiences:form-action": Route(
        Access.ORG_SCOPED,
        kwargs=_form_action,
        known_gap="no form declares actions yet, so every actor gets 404",
    ),
    "experiences:action": Route(Access.ORG_SCOPED, kwargs=_action),
    "experiences:query": Route(Access.ORG_SCOPED, kwargs=_query),
    "experiences:access": Route(Access.ORG_SCOPED, kwargs=_reference),
    "experiences:access-remove": Route(
        Access.ORG_SCOPED,
        kwargs=_access_user,
        methods=("POST",),
    ),
    "experiences:attachment": Route(Access.MEMBER_OR_CONSOLE, kwargs=_attachment),
    # C7's panel. Integrator-only by omission as much as by gate: there is no
    # console counterpart and no staff route to a secret in the URLconf.
    # Reveal and rotate are actions on this one route, not routes of their own.
    "experiences:credentials": Route(
        Access.ORG_SCOPED,
        kwargs=_reference,
        methods=("GET", "POST"),
        data={"action": "reveal"},
    ),
    # Support
    "support:list": Route(Access.TENANT_MEMBER),
    "support:create": Route(Access.TENANT_MEMBER),
    "support:detail": Route(Access.ORG_SCOPED, kwargs=_ticket),
    "support:reply": Route(Access.ORG_SCOPED, kwargs=_ticket, methods=("POST",)),
    # `TicketStatusForm` is the guard on *what* may be asked — closing is the
    # NHA team's call — so a body is needed to ask *who* may ask at all.
    "support:status": Route(
        Access.ORG_SCOPED,
        kwargs=_ticket,
        methods=("POST",),
        data={"status": "resolved"},
    ),
    # Events are published to every vendor, so they are not tenant-scoped.
    "events:list": Route(Access.AUTHENTICATED),
    "events:detail": Route(Access.AUTHENTICATED, kwargs=_event_slug),
    # The console
    "staff:queue": Route(Access.CONSOLE),
    "staff:applications": Route(Access.CONSOLE),
    "staff:application-detail": Route(Access.CONSOLE, kwargs=_reference),
    "staff:application-action": Route(Access.CONSOLE, kwargs=_console_action),
    "staff:application-form-action": Route(
        Access.CONSOLE,
        kwargs=_form_action,
        known_gap="no form declares actions yet, so every actor gets 404",
    ),
    "staff:application-query": Route(Access.CONSOLE, kwargs=_query),
    "staff:application-query-resolve": Route(
        Access.CONSOLE,
        kwargs=_query,
        methods=("POST",),
    ),
    "staff:ticket": Route(Access.CONSOLE, kwargs=_ticket),
    "staff:ticket-reply": Route(Access.CONSOLE, kwargs=_ticket, methods=("POST",)),
    "staff:ticket-update": Route(Access.CONSOLE, kwargs=_ticket, methods=("POST",)),
    "staff:organisations": Route(Access.CONSOLE),
    "staff:organisation": Route(Access.CONSOLE, kwargs=_organisation_slug),
    "staff:organisation-verification": Route(
        Access.CONSOLE,
        kwargs=_organisation_slug,
        methods=("POST",),
    ),
    "staff:events": Route(Access.CONSOLE),
    "staff:event-create": Route(Access.CONSOLE),
    "staff:event-update": Route(Access.CONSOLE, kwargs=_event_slug),
    "staff:event-publish": Route(
        Access.CONSOLE,
        kwargs=_event_slug,
        methods=("POST",),
    ),
}


def iter_named_urls(resolver=None, prefix="") -> set[str]:
    resolver = resolver or get_resolver()
    names: set[str] = set()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            namespace = f"{pattern.namespace}:" if pattern.namespace else ""
            names |= iter_named_urls(pattern, prefix + namespace)
        elif pattern.name:
            names.add(prefix + pattern.name)
    return names


def live_url_names() -> set[str]:
    return {name for name in iter_named_urls() if not name.startswith(GROUPED_PREFIXES)}


def _redirects_to_login(response) -> bool:
    login_url = reverse("account_login")
    location = response.headers.get("Location", "")
    return response.status_code in REDIRECT_CODES and login_url in location


def _resolve(name: str, route: Route, context: dict) -> str:
    kwargs = route.kwargs(context) if callable(route.kwargs) else route.kwargs
    return reverse(name, kwargs=kwargs)


# Drift: the matrix cannot silently fall behind the URLconf


def test_every_named_url_has_a_row():
    missing = sorted(live_url_names() - set(ROUTES))
    assert not missing, (
        f"URLs with no route-gate row: {missing}. "
        "Add one to ROUTES in this module — see the module docstring."
    )


def test_matrix_has_no_stale_rows():
    stale = sorted(set(ROUTES) - live_url_names())
    assert not stale, f"Route-gate rows for URLs that no longer exist: {stale}"


def test_public_allowlist_is_small_and_deliberate():
    """Deny-by-default: every public URL is marketing or a way to sign in."""
    public = {name for name, route in ROUTES.items() if route.access is Access.PUBLIC}
    allowed_prefixes = ("home", "about", "account_", "socialaccount_", "mfa_")
    #: Public on purpose, each for a stated reason — see their rows.
    allowed_names = {
        "users:update",
        "organisations:invitation-accept",
    }
    unexpected = {
        name
        for name in public
        if not name.startswith(allowed_prefixes) and name not in allowed_names
    }
    assert not unexpected, f"Unexpected public URLs: {sorted(unexpected)}"


# The matrix itself


def _cases():
    cases: list[Any] = []
    for name, route in sorted(ROUTES.items()):
        marks = (
            [pytest.mark.xfail(reason=route.known_gap, strict=True)]
            if route.known_gap
            else []
        )
        cases.extend(
            pytest.param(name, route, method, marks=marks, id=f"{name}-{method}")
            for method in route.methods
        )
    return cases


@pytest.mark.parametrize(("name", "route", "method"), _cases())
def test_route_gate(name, route, method, clients, context):
    url = _resolve(name, route, context)

    for actor, client in clients.items():
        response = client.post(url, route.data) if method == "POST" else client.get(url)
        where = f"{actor} {method} {name} ({url}) -> {response.status_code}"
        _assert_actor(route.access, actor, response, where)


NOT_FOUND_REQUIRED = "expected 404 — a 403 would confirm it exists"


def _assert_public(actor, response, where):
    if actor == ANONYMOUS:
        assert not _redirects_to_login(response), f"{where}: public URL sent to login"
    assert response.status_code != HTTP_FORBIDDEN, where


def _assert_authenticated(actor, response, where):
    assert response.status_code not in DENIED_CODES, where


def _assert_self_resource(actor, response, where):
    # An actor holding the resource must reach it; one without may only 404.
    if actor in STAFF_ACTORS:
        assert response.status_code not in DENIED_CODES, where
    else:
        assert response.status_code != HTTP_FORBIDDEN, f"{where}: {NOT_FOUND_REQUIRED}"


def _refused(response) -> bool:
    """Not served. A redirect away counts; a 403 does not, because it confirms
    the resource is there."""
    return response.status_code not in {HTTP_OK, HTTP_FORBIDDEN}


def _assert_self_only(actor, response, where):
    # Not `== 200`: a self-only route may now take a POST, and a successful
    # write redirects. The gate's question is whether the owner is refused,
    # and a redirect is not a refusal — same shape as `_assert_org_scoped`.
    if actor == ORG_MEMBER:
        assert response.status_code not in DENIED_CODES, where
    else:
        assert response.status_code == HTTP_NOT_FOUND, f"{where}: {NOT_FOUND_REQUIRED}"


def _assert_org_scoped(actor, response, where):
    # Only the owning organisation's member gets in.
    if actor == ORG_MEMBER:
        assert response.status_code not in DENIED_CODES, where
    elif actor == MEMBER_OTHER_ORG:
        # Vendor to vendor is where hiding existence matters most.
        assert response.status_code == HTTP_NOT_FOUND, f"{where}: {NOT_FOUND_REQUIRED}"
    else:
        assert _refused(response), f"{where}: {NOT_FOUND_REQUIRED}"


def _assert_console(actor, response, where):
    if actor in STAFF_ACTORS:
        assert response.status_code not in DENIED_CODES, where
    else:
        assert response.status_code in DENIED_CODES, (
            f"{where}: console URL reachable by a non-staff actor"
        )


def _assert_tenant_member(actor, response, where):
    # Both vendors reach their own. An actor with no organisation is turned
    # away — for the review team that is a redirect to the console rather than a
    # 403, which `OrganisationMixin` chooses deliberately.
    if actor in STAFF_ACTORS:
        assert _refused(response), (
            f"{where}: a vendor surface answered an actor with no organisation"
        )
    else:
        assert response.status_code not in DENIED_CODES, where


def _assert_member_or_console(actor, response, where):
    if actor == MEMBER_OTHER_ORG:
        assert response.status_code == HTTP_NOT_FOUND, f"{where}: {NOT_FOUND_REQUIRED}"
    else:
        assert response.status_code not in DENIED_CODES, where


_ASSERTERS = {
    Access.AUTHENTICATED: _assert_authenticated,
    Access.SELF_RESOURCE: _assert_self_resource,
    Access.SELF_ONLY: _assert_self_only,
    Access.TENANT_MEMBER: _assert_tenant_member,
    Access.ORG_SCOPED: _assert_org_scoped,
    Access.MEMBER_OR_CONSOLE: _assert_member_or_console,
    Access.CONSOLE: _assert_console,
}


def _assert_actor(access, actor, response, where):
    if access is Access.PUBLIC:
        _assert_public(actor, response, where)
        return

    # Checked before the anonymous branch: with DEBUG off the URL does not exist
    # for anyone, so there is nothing to send a stranger to the login page for.
    if access is Access.DEVELOPMENT_ONLY:
        assert response.status_code == HTTP_NOT_FOUND, (
            f"{where}: a development-only URL answered off a development machine"
        )
        return

    # Deny by default: everything non-public sends a stranger to the login page.
    if actor == ANONYMOUS:
        assert _redirects_to_login(response), f"{where}: expected redirect to login"
        return

    _ASSERTERS[access](actor, response, where)


# Rules asserted generically, not per row


def test_django_admin_is_staff_only(clients):
    """Admin is 95 URLs; asserted as a group rather than row by row."""
    url = reverse("admin:index")

    for actor in (ANONYMOUS, ORG_MEMBER, MEMBER_OTHER_ORG):
        response = clients[actor].get(url)
        assert response.status_code in REDIRECT_CODES, (
            f"{actor} reached the admin index ({response.status_code})"
        )

    for actor in STAFF_ACTORS:
        assert clients[actor].get(url).status_code == HTTP_OK


def test_mutating_routes_reject_a_missing_csrf_token(context, org_member):
    """Django's test client skips CSRF unless asked, so ask explicitly."""
    checked = 0
    for name, route in ROUTES.items():
        if "POST" not in route.methods:
            continue
        client = Client(enforce_csrf_checks=True)
        client.force_login(org_member)
        response = client.post(_resolve(name, route, context))
        assert response.status_code == HTTP_FORBIDDEN, (
            f"{name} accepted a POST with no CSRF token ({response.status_code})"
        )
        checked += 1

    assert checked, "No mutating routes exercised — did methods=('POST',) get dropped?"
