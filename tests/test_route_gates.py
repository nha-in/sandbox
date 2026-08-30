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
from tests.conftest import DOCUMENT_A
from tests.conftest import MEMBER_OTHER_ORG
from tests.conftest import MILESTONE_M1
from tests.conftest import ORG_MEMBER
from tests.conftest import STAFF_ACTORS

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
REDIRECT_CODES = frozenset({301, 302})
DENIED_CODES = frozenset({HTTP_FORBIDDEN, HTTP_NOT_FOUND})


class Access(enum.StrEnum):
    """The rule a URL is claiming. Assertions are derived from this."""

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    SELF_RESOURCE = "self_resource"
    SELF_ONLY = "self_only"
    ORG_SCOPED = "org_scoped"
    CONSOLE = "console"
    #: Exists only on a development machine. 404 for everyone under any settings
    #: where DEBUG is off, which is every deployed environment and this suite.
    DEVELOPMENT_ONLY = "development_only"


@dataclass(frozen=True)
class Route:
    access: Access
    kwargs: dict[str, Any] | Callable[[dict], dict] = field(default_factory=dict)
    #: `reverse()` cannot build a query string, but the active organisation now
    #: lives in one, so org-scoped rows have to supply it.
    query: Callable[[dict], str] | str = ""
    methods: tuple[str, ...] = ("GET",)
    known_gap: str = ""


def _org_a(context: dict) -> str:
    """Every actor is sent at org A. Only its member may get in."""
    return f"org={context[ORG_MEMBER].memberships.get().organisation.external_id}"


def _member_external_id(context: dict) -> dict:
    return {"external_id": context[ORG_MEMBER].external_id}


def _application_id(context: dict) -> dict:
    return {"external_id": context["application"].external_id}


def _document_id(context: dict) -> dict:
    return {"external_id": context[DOCUMENT_A].external_id}


def _application_and_milestone(context: dict) -> dict:
    return {
        "external_id": context["application"].external_id,
        "key": context[MILESTONE_M1].key,
    }


# The matrix. One row per named URL; django-admin is asserted as a group below.
ROUTES: dict[str, Route] = {
    # Marketing
    "home": Route(Access.PUBLIC),
    "about": Route(Access.PUBLIC),
    # Account — anonymous must be able to reach these to get in at all
    "account_login": Route(Access.PUBLIC, methods=("GET",)),
    "account_signup": Route(Access.PUBLIC),
    "account_reset_password": Route(Access.PUBLIC),
    "account_reset_password_done": Route(Access.PUBLIC),
    "account_reset_password_from_key": Route(
        Access.PUBLIC,
        kwargs={"uidb36": "0", "key": "set-password"},
    ),
    "account_reset_password_from_key_done": Route(Access.PUBLIC),
    "account_confirm_email": Route(Access.PUBLIC, kwargs={"key": "invalid-key"}),
    "account_email_verification_sent": Route(Access.PUBLIC),
    "account_inactive": Route(Access.PUBLIC),
    "account_confirm_login_code": Route(Access.AUTHENTICATED),
    "account_logout": Route(Access.PUBLIC),
    # Account — signed-in surfaces
    "account_email": Route(Access.AUTHENTICATED),
    "account_change_password": Route(Access.AUTHENTICATED),
    "account_set_password": Route(Access.AUTHENTICATED),
    "account_reauthenticate": Route(Access.AUTHENTICATED),
    # MFA. The device-bound ones 404 for a user who has no device, which is why
    # they are SELF_RESOURCE: reviewer/staff hold TOTP and must reach them.
    "mfa_index": Route(Access.AUTHENTICATED),
    "mfa_activate_totp": Route(Access.AUTHENTICATED),
    "mfa_deactivate_totp": Route(Access.SELF_RESOURCE),
    "mfa_authenticate": Route(Access.AUTHENTICATED),
    "mfa_reauthenticate": Route(Access.AUTHENTICATED),
    "mfa_generate_recovery_codes": Route(Access.AUTHENTICATED),
    "mfa_view_recovery_codes": Route(Access.SELF_RESOURCE),
    "mfa_download_recovery_codes": Route(Access.SELF_RESOURCE),
    # Social account — installed but unused in v0
    "socialaccount_connections": Route(Access.AUTHENTICATED),
    "socialaccount_login_cancelled": Route(Access.PUBLIC),
    "socialaccount_login_error": Route(Access.PUBLIC),
    "socialaccount_signup": Route(Access.AUTHENTICATED),
    # Portal
    # The contact-verification gate. Authenticated but deliberately
    # reachable while unverified, otherwise the gate would loop on itself.
    "users:verify_contacts": Route(Access.AUTHENTICATED),
    "users:redirect": Route(Access.AUTHENTICATED),
    "users:update": Route(Access.AUTHENTICATED),
    "users:detail": Route(Access.SELF_ONLY, kwargs=_member_external_id),
    # The front door: any signed-in user with no tenant needs to be able to make
    # one, or their account is a dead end.
    "organisations:create": Route(Access.AUTHENTICATED, methods=("GET",)),
    "organisations:choose": Route(Access.AUTHENTICATED),
    "organisations:district_options": Route(Access.AUTHENTICATED),
    "organisations:profile": Route(
        Access.ORG_SCOPED,
        query=_org_a,
        methods=("GET", "POST"),
    ),
    # Enrolment wizard (C4). Every screen names its tenant in `?org=`, so the
    # rule is the same whether or not the URL also names an application.
    "applications:index": Route(Access.ORG_SCOPED, query=_org_a),
    "applications:overview": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "applications:application_status": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "applications:step_product": Route(
        Access.ORG_SCOPED,
        query=_org_a,
        methods=("GET", "POST"),
    ),
    # The Back button's target. Named by application, so the wrong-org row is
    # the one that matters: it must not be a way to repoint someone else's draft.
    "applications:step_product_edit": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
        methods=("GET", "POST"),
    ),
    "applications:step_details": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "applications:step_review": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    # Credentials panel (C7). The two mutating rows are the ones that matter:
    # they are the only routes in the system that can put a secret on a screen,
    # so "wrong org 404s" is load-bearing rather than routine.
    "applications:credentials": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "applications:credentials_panel": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "applications:reveal_credentials": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
        methods=("POST",),
    ),
    "applications:rotate_credentials": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
        methods=("POST",),
    ),
    # Console (C5). Staff-only; an org member must be refused even for their own
    # application, because the console is a different surface, not a nicer view.
    "console:queue": Route(Access.CONSOLE),
    "console:application_detail": Route(Access.CONSOLE, kwargs=_application_id),
    "console:record_review": Route(
        Access.CONSOLE,
        kwargs=_application_id,
        methods=("POST",),
    ),
    "console:decide": Route(
        Access.CONSOLE,
        kwargs=_application_id,
        methods=("POST",),
    ),
    "console:retry_provisioning": Route(
        Access.CONSOLE,
        kwargs=_application_id,
        methods=("POST",),
    ),
    # The reviewer's way to a declaration's evidence. Staff hold no membership,
    # so this is scoped by the review permission instead — and it must stay
    # unreachable by any integrator, including the file's own owner, who has
    # their own org-scoped route below.
    "console:document_download": Route(Access.CONSOLE, kwargs=_document_id),
    # Milestones and exit (C8). POST rows included because the writes are what
    # actually matter: a declaration accepted for the wrong tenant would attach
    # evidence to somebody else's application.
    "declarations:milestones": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
    ),
    "declarations:declare_milestone": Route(
        Access.ORG_SCOPED,
        kwargs=_application_and_milestone,
        query=_org_a,
        methods=("GET", "POST"),
    ),
    "declarations:exit": Route(
        Access.ORG_SCOPED,
        kwargs=_application_id,
        query=_org_a,
        methods=("GET", "POST"),
    ),
    # Presigned download. Org-scoped: the bucket is private, so this row is the
    # only thing standing between another tenant and the file.
    "declarations:document_download": Route(
        Access.ORG_SCOPED,
        kwargs=_document_id,
        query=_org_a,
    ),
    # The component gallery (C10). Not a product screen: routed always so
    # `{% url %}` resolves, but gone unless DEBUG and staff. The DEBUG-on half
    # of the rule is asserted by test_styleguide_is_staff_only_in_development.
    "theme:styleguide": Route(Access.DEVELOPMENT_ONLY),
}

# Named URLs deliberately not given individual rows.
GROUPED_PREFIXES = ("admin:",)


def iter_named_urls(resolver=None, prefix: str = ""):
    """Every named URL in the live URLconf, namespaces included."""
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            namespace = pattern.namespace
            child = f"{prefix}{namespace}:" if namespace else prefix
            yield from iter_named_urls(pattern, child)
        elif pattern.name:
            yield f"{prefix}{pattern.name}"


def live_url_names() -> set[str]:
    return {name for name in iter_named_urls() if not name.startswith(GROUPED_PREFIXES)}


def _redirects_to_login(response) -> bool:
    login_url = reverse("account_login")
    location = response.headers.get("Location", "")
    return response.status_code in REDIRECT_CODES and login_url in location


def _resolve(name: str, route: Route, context: dict) -> str:
    kwargs = route.kwargs(context) if callable(route.kwargs) else route.kwargs
    url = reverse(name, kwargs=kwargs)
    query = route.query(context) if callable(route.query) else route.query
    return f"{url}?{query}" if query else url


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
    unexpected = {
        name
        for name in public
        if not name.startswith(("home", "about", "account_", "socialaccount_", "mfa_"))
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
        response = client.generic(method, url)
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


def _assert_self_only(actor, response, where):
    if actor == ORG_MEMBER:
        assert response.status_code == HTTP_OK, where
    else:
        assert response.status_code == HTTP_NOT_FOUND, f"{where}: {NOT_FOUND_REQUIRED}"


def _assert_org_scoped(actor, response, where):
    # Only the owning organisation's member gets in. Staff are not members, so
    # an integrator URL 404s for them too — the console has its own screens.
    if actor == ORG_MEMBER:
        assert response.status_code not in DENIED_CODES, where
    else:
        assert response.status_code == HTTP_NOT_FOUND, f"{where}: {NOT_FOUND_REQUIRED}"


def _assert_console(actor, response, where):
    if actor in STAFF_ACTORS:
        assert response.status_code not in DENIED_CODES, where
    else:
        assert response.status_code in DENIED_CODES, (
            f"{where}: console URL reachable by a non-staff actor"
        )


_ASSERTERS = {
    Access.AUTHENTICATED: _assert_authenticated,
    Access.SELF_RESOURCE: _assert_self_resource,
    Access.SELF_ONLY: _assert_self_only,
    Access.ORG_SCOPED: _assert_org_scoped,
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
