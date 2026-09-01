"""The shell's own gate (C10).

The route matrix proves every URL is *guarded*. It cannot prove any of them is
*reachable*, and it says nothing at all about what the chrome offers. This repo
has twice shipped a screen with no inbound link, and once shipped a nav link
whose target 404s for the person reading it — both while the route tests were
green.

So this module asserts the two properties the matrix cannot:

1. Every link the shell renders for an actor actually answers that actor.
2. Every screen that exists is reachable from the shell without typing a URL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from sandbox.applications.models import ApplicationState
from sandbox.applications.tests.factories import ApplicationFactory
from sandbox.organisations.context_processors import NAV_SECTIONS
from sandbox.organisations.mixins import organisation_query
from sandbox.users.tests.factories import VerifiedUserFactory
from tests.conftest import ORG_MEMBER
from tests.conftest import STAFF
from tests.test_route_gates import live_url_names

pytestmark = pytest.mark.django_db

HTTP_OK = 200
HTTP_NOT_FOUND = 404
DENIED_CODES = frozenset({403, 404})

#: Screens that deliberately carry no highlighted sidebar item.
#:
#: Kept explicit so the list can be argued with. Anything not here and not in
#: NAV_SECTIONS fails below, which is how a new screen is stopped from quietly
#: rendering a sidebar with nothing current in it.
CHROME_LESS = {
    # Marketing and the whole of allauth/MFA: their own chrome, or none.
    "home",
    "about",
    # The verification gate. It is where every request goes until contacts are
    # verified, so highlighting a section would be a lie about where you are.
    "users:verify_contacts",
    # A redirect, never rendered.
    "users:redirect",
    # A JSON fragment for the district select.
    "organisations:district_options",
    # Fragments and POST targets inside the dashboard, not places you navigate
    # to. The credentials panel is a region of applications:overview.
    "applications:credentials_panel",
    "applications:reveal_credentials",
    "applications:rotate_credentials",
    # POST-only console actions and a presigned redirect: no page, no chrome.
    "console:record_review",
    "console:decide",
    "console:retry_provisioning",
    "console:document_download",
    "applications:document_download",
    # Development-only, and deliberately outside the product's nav.
    "theme:styleguide",
}

_PREFIXES_WITHOUT_APP_CHROME = ("account_", "socialaccount_", "mfa_")

#: Screens with no `{% url %}` anywhere in the templates, and why that is right.
#:
#: Everything else must be linked from somewhere, or a user can only reach it by
#: typing the path — which is how the enrolment wizard and the organisation
#: switcher both shipped unreachable while their tests were green.
NO_INBOUND_LINK = {
    # Reached by VerificationRequiredMiddleware, which redirects every request
    # here until contacts are verified. A link would be redundant.
    "users:verify_contacts",
    # `LOGIN_REDIRECT_URL`. allauth sends you here; nothing links to it, and the
    # nav deliberately does not — "your profile" must mean the profile, not
    # "wherever this account belongs after signing in".
    "users:redirect",
    # Deliberately outside the product's navigation.
    "theme:styleguide",
}

_URL_TAG = re.compile(r"{%\s*url\s*['\"]([^'\"]+)['\"]")
_TEMPLATES = Path(settings.APPS_DIR) / "templates"
_HREF_ATTR = re.compile(rb'href="(/[^"]*)"')


@pytest.mark.parametrize(
    ("actor", "destination"),
    [
        (ORG_MEMBER, "applications:index"),
        (STAFF, "console:queue"),
    ],
)
def test_signing_in_leads_to_the_screen_that_actor_came_for(
    clients,
    actor,
    destination,
):
    """`users:redirect` is where allauth drops everyone after sign-in.

    A reviewer used to land on their own profile page, in the integrator shell,
    whose sidebar offered them nothing they could open — the console was
    reachable only by typing its URL. `test_every_screen_has_an_inbound_link`
    was green throughout, because the console *is* linked: from inside itself.
    A link you can only follow once you have arrived is not a way in.
    """
    landing = clients[actor].get(reverse("users:redirect"), follow=True)
    final = landing.redirect_chain[-1][0] if landing.redirect_chain else ""
    reachable = {
        href.decode().split("?")[0] for href in _HREF_ATTR.findall(landing.content)
    }

    assert reverse(destination) in final or reverse(destination) in reachable, (
        f"{actor} signs in, lands on {final!r}, and cannot click through to "
        f"{destination}"
    )


def test_a_staff_user_in_the_integrator_shell_can_get_back_to_the_console(clients):
    """Staff reach that shell through their profile and the MFA screens."""
    response = clients[STAFF].get(reverse("users:update"))
    links = _sidebar_links(response.content, b"app-nav")

    assert reverse("console:queue") in links


def test_a_console_user_can_reach_their_own_account(clients, staff_user):
    """The rail's user card was inert text, so 2FA and email settings were
    unreachable from the only shell staff ever see."""
    links = {
        href.split("?")[0]
        for href in _sidebar_links(
            clients[STAFF].get(reverse("console:queue")).content,
            b"console-nav",
        )
    }

    assert (
        reverse("users:detail", kwargs={"external_id": staff_user.external_id}) in links
    )


def test_every_screen_has_an_inbound_link():
    linked = {
        match.group(1)
        for path in _TEMPLATES.rglob("*.html")
        for match in _URL_TAG.finditer(path.read_text())
    }
    unreachable = sorted(
        name
        for name in live_url_names()
        if name not in linked
        and name not in NO_INBOUND_LINK
        and not name.startswith(("djdt:", *_PREFIXES_WITHOUT_APP_CHROME))
    )
    assert not unreachable, (
        f"Screens no template links to: {unreachable}. Give each one an inbound "
        "link, or add it to NO_INBOUND_LINK with the reason it needs none."
    )


_HREF = re.compile(rb'href="([^"]+)"')


def _sidebar_links(html: bytes, nav_id: bytes) -> list[str]:
    """Every href inside the shell's <nav>, in document order."""
    start = html.index(b'id="' + nav_id + b'"')
    end = html.index(b"</nav>", start)
    return [href.decode() for href in _HREF.findall(html[start:end])]


def test_every_screen_has_a_nav_section_or_is_listed_as_chrome_less():
    unclassified = sorted(
        name
        for name in live_url_names()
        if name not in NAV_SECTIONS
        and name not in CHROME_LESS
        and not name.startswith(_PREFIXES_WITHOUT_APP_CHROME)
    )
    assert not unclassified, (
        f"Screens with no sidebar section: {unclassified}. Add a row to "
        "NAV_SECTIONS, or list it in CHROME_LESS with a reason."
    )


def test_nav_sections_do_not_outlive_their_urls():
    stale = sorted(set(NAV_SECTIONS) - live_url_names())
    assert not stale, f"NAV_SECTIONS rows for URLs that no longer exist: {stale}"


@pytest.mark.parametrize(
    ("actor", "landing", "nav_id"),
    [
        (ORG_MEMBER, "applications:index", b"app-nav"),
        (STAFF, "console:queue", b"console-nav"),
    ],
)
def test_every_sidebar_link_answers_the_actor_who_can_see_it(
    clients,
    org_member,
    actor,
    landing,
    nav_id,
):
    """The defect this repo has shipped: a link to a screen the reader cannot open."""
    query = (
        f"?{organisation_query(org_member.memberships.get().organisation)}"
        if actor == ORG_MEMBER
        else ""
    )
    client = clients[actor]
    response = client.get(reverse(landing) + query)
    assert response.status_code == HTTP_OK

    links = _sidebar_links(response.content, nav_id)
    assert links, "the sidebar rendered no links at all"

    for href in links:
        followed = client.get(href, follow=True)
        assert followed.status_code not in DENIED_CODES, (
            f"{actor} is offered {href} in the sidebar but gets "
            f"{followed.status_code} on following it"
        )


def test_a_member_reaches_the_wizard_and_the_switcher_from_the_sidebar(
    clients,
    org_member,
):
    """Both of these once existed with no inbound link. Name them explicitly so
    a future tidy-up of the nav cannot quietly strand them again."""
    query = f"?{organisation_query(org_member.memberships.get().organisation)}"
    response = clients[ORG_MEMBER].get(reverse("applications:index") + query)
    links = {
        href.split("?")[0] for href in _sidebar_links(response.content, b"app-nav")
    }

    assert reverse("applications:index") in links
    assert reverse("organisations:choose") in links


def test_the_rail_switches_between_an_organisations_applications(
    clients,
    context,
):
    """Two products is the case the rail exists for. Reaching the second one
    should not mean going back to the list and picking again."""
    application = context["application"]
    organisation = application.product.organisation
    sibling = ApplicationFactory.create(product__organisation=organisation)
    query = f"?{organisation_query(organisation)}"

    response = clients[ORG_MEMBER].get(
        reverse(
            "applications:overview",
            kwargs={"external_id": application.external_id},
        )
        + query,
    )
    links = {
        href.split("?")[0] for href in _sidebar_links(response.content, b"app-nav")
    }

    assert (
        reverse(
            "applications:overview",
            kwargs={"external_id": sibling.external_id},
        )
        in links
    )


def test_a_user_with_no_organisation_is_offered_the_one_screen_that_helps(
    client,
    django_user_model,
):
    """A fresh signup holds no membership, so every org-scoped URL 404s for them.

    Offering any of them would rebuild the dead end that shipped in B1.
    """
    user = VerifiedUserFactory()
    client.force_login(user)
    response = client.get(
        reverse("users:detail", kwargs={"external_id": user.external_id}),
    )
    assert response.status_code == HTTP_OK

    links = _sidebar_links(response.content, b"app-nav")
    assert reverse("organisations:create") in links
    assert reverse("organisations:profile") not in links
    assert reverse("applications:index") not in links


def test_the_console_does_not_offer_staff_an_integrator_view_they_cannot_open(
    clients,
):
    """Staff hold no membership, so the integrator dashboard 404s for them."""
    response = clients[STAFF].get(reverse("console:queue"))
    links = {
        href.split("?")[0] for href in _sidebar_links(response.content, b"console-nav")
    }

    assert reverse("applications:index") not in links


def test_the_queue_badge_counts_the_reviewers_backlog(clients, application):
    response = clients[STAFF].get(reverse("console:queue"))
    nav = response.content[response.content.index(b'id="console-nav"') :]
    nav = nav[: nav.index(b"</nav>")]

    assert b"ui-sidebar-badge" in nav, "the queue badge did not render"
    assert b">1</span>" in nav


def test_the_mobile_drawer_needs_no_javascript(clients, org_member):
    """The drawer is a checkbox and a label. A script may enhance it; nothing
    may be required to open it, because the ticket's constraint is that every
    mutation works with JavaScript disabled."""
    query = f"?{organisation_query(org_member.memberships.get().organisation)}"
    html = clients[ORG_MEMBER].get(reverse("applications:index") + query).content

    assert b'id="app-drawer"' in html
    assert b'type="checkbox"' in html
    assert b'for="app-drawer"' in html


@override_settings(DEBUG=True)
def test_styleguide_is_staff_only_in_development(clients):
    url = reverse("theme:styleguide")

    assert clients[STAFF].get(url).status_code == HTTP_OK
    assert clients[ORG_MEMBER].get(url).status_code == HTTP_NOT_FOUND


@override_settings(DEBUG=True)
def test_a_secret_is_readable_without_javascript(clients):
    """components/secret_value.html renders revealed, and static/js/project.js
    masks it on load. The other order would put a user's own credential behind a
    button that does nothing when the script fails to load."""
    html = clients[STAFF].get(reverse("theme:styleguide")).content.decode()

    def classes_of(marker: str) -> str:
        # The element carrying `marker`, back to the tag that opened it.
        tag = html[
            html.rindex("<", 0, html.index(marker)) : html.index(
                ">",
                html.index(marker),
            )
            + 1
        ]
        found = re.search(r'class="([^"]*)"', tag)
        return found.group(1) if found else ""

    assert "hidden" in classes_of("data-secret-mask"), "the mask must start hidden"
    assert "hidden" not in classes_of("data-secret-value"), (
        "the value must start visible"
    )
    assert "hidden" in classes_of("data-secret-toggle"), (
        "the reveal button must start hidden — it does nothing until the script runs"
    )
    assert "not-a-real-secret" in html


def test_styleguide_renders_every_primitive(clients):
    with override_settings(DEBUG=True):
        html = clients[STAFF].get(reverse("theme:styleguide")).content.decode()

    for primitive in (
        "ui-sidebar-link",
        "ui-sidebar-badge",
        "ui-breadcrumb",
        "ui-stepper",
        "ui-rail",
        "ui-stat",
        "ui-meter",
        "ui-kv",
        "ui-dot",
        "ui-log",
        "ui-timeline",
        "ui-empty",
        "ui-code-chip",
    ):
        assert primitive in html, f"the gallery does not show {primitive}"


@pytest.mark.parametrize(
    "state",
    [
        ApplicationState.DRAFT,
        ApplicationState.PROVISIONED,
    ],
)
def test_every_application_rail_link_answers_the_actor(clients, context, state):
    """The level-1 test above never enters an application, so it cannot see the
    rail that replaces it. Each section is listed whatever the state \u2014 they
    explain their own gate rather than disappearing \u2014 so each must open."""
    application = context["application"]
    application.state = state
    application.save(update_fields=["state"])
    organisation = application.product.organisation
    client = clients[ORG_MEMBER]

    url = reverse(
        "applications:overview",
        kwargs={"external_id": application.external_id},
    )
    response = client.get(f"{url}?{organisation_query(organisation)}")
    assert response.status_code == HTTP_OK

    links = _sidebar_links(response.content, b"app-nav")
    assert links, "the application rail rendered no links at all"

    for href in links:
        followed = client.get(href, follow=True)
        assert followed.status_code not in DENIED_CODES, (
            f"{state}: the rail offers {href} but following it gives "
            f"{followed.status_code}"
        )
        # A 200 is not enough. `applications:credentials` used to be C7's htmx
        # fragment, so following the nav item returned a bare card with no
        # shell around it — reachable, and still broken.
        assert b'id="app-nav"' in followed.content, (
            f"{state}: {href} answers, but renders no shell — a nav item must "
            "point at a page, not at a fragment"
        )


def test_the_application_rail_replaces_the_organisation_rail(clients, context):
    """Replacing, not nesting: inside an application the rail must not still be
    offering organisation-level items that talk about a different one.

    The account group is part of that. Among items that are all about this
    application, a Settings link reads as this application's settings, and
    leaves the section without saying so.
    """
    application = context["application"]
    organisation = application.product.organisation
    url = reverse(
        "applications:overview",
        kwargs={"external_id": application.external_id},
    )

    body = (
        clients[ORG_MEMBER]
        .get(
            f"{url}?{organisation_query(organisation)}",
        )
        .content
    )
    links = {href.split("?")[0] for href in _sidebar_links(body, b"app-nav")}

    assert reverse("applications:index") in links, "no way back to the list"
    assert (
        reverse(
            "applications:milestones",
            kwargs={"external_id": application.external_id},
        )
        in links
    )
    assert reverse("organisations:profile") not in links
    assert reverse("organisations:choose") not in links
